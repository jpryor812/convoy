"""The ten entity types from the World State Schema tab, as real data structures.

Field names track the spreadsheet's field names closely enough to be checkable
against it. Everything is plain dataclasses so checkpointing is straightforward.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

from . import data as D
from . import economy as E
from . import world_map as M


# ---------------------------------------------------------------------------
# 1. AGENT
# ---------------------------------------------------------------------------

@dataclass
class Activity:
    """What an agent is currently doing, and when it resolves."""

    kind: str                      # idle | travel | work | craft | convoy | dead
    ends_at: float                 # sim seconds; inf for open-ended shifts
    detail: dict[str, Any] = field(default_factory=dict)


# How many past decisions an agent carries. The full record lives in the event
# log; this is the working set an agent can be asked about without a log scan.
MAX_REASONING_KEPT = 40

# Long enough for a real justification, short enough that 40 of them per agent
# stay cheap to hold and to render.
REASONING_CHARS = 600


# A recommendation is live for this many simulated hours unless the giver says
# otherwise. Advice about a market goes stale with the market: telling an agent
# at hour 60 what it was told at hour 12 is worse than telling it nothing,
# because it reads as current.
ADVICE_TTL_HOURS = 6.0

# Long enough for a real instruction with a reason attached.
ADVICE_CHARS = 400

# The inbox is a ring, like `reasoning`. An advisor hammering one agent must not
# be able to grow it without bound across a 120-hour run.
MAX_ADVICE_KEPT = 20


@dataclass
class Snapshot:
    """The state of the world at the instant a recommendation was given.

    Captured so that "what did this advice change?" is ARITHMETIC rather than a
    story. The claim worth making to a classroom -- "you told Agent 4 to open a
    second mine; its net worth tripled, and Agent 6's fell as it lost share" --
    is only worth making if it can be checked, and after the fact there is no
    way to recover what the valley looked like at hour 44. It has to be taken
    then or not at all.

    The WHOLE leaderboard, not just the advised agent: the interesting half of
    a market intervention is what it did to everyone who was not advised, and
    that is exactly the half nobody thinks to record.

    What this deliberately does NOT capture is a counterfactual. Nothing here
    knows what would have happened otherwise; `runway_hours` is the closest
    honest thing -- how long each business could have met payroll out of cash at
    the moment advice landed. "Would have gone bankrupt" is a projection from
    that number, and it must be shown as one.
    """

    hour: float
    net_worth: dict[str, float] = field(default_factory=dict)      # agent id -> value
    denari: dict[str, float] = field(default_factory=dict)
    businesses: dict[str, int] = field(default_factory=dict)       # agent id -> open count
    # business id -> hours of payroll its cash covers; inf when it owes nothing.
    runway_hours: dict[str, float] = field(default_factory=dict)


@dataclass
class Recommendation:
    """Advice given to an agent from OUTSIDE the simulation, and its fate.

    This is the teaching surface: a student tells an agent what they think it
    should do, and the run records whether it listened. That second half is the
    point. "I told it to sell the ore and it didn't" has to be checkable, or the
    exercise is a toy -- and the predictable failure is not disobedience, it is
    the advice never reaching the prompt at all (PHASE4 §2, thirteen times).

    So delivery is recorded as a FACT, not assumed: `times_seen` and
    `first_seen_hour` are written by `observe.py` at the moment the text enters
    a prompt, and by nothing else. If a student says the agent ignored them and
    `times_seen` is 0, the answer is that the agent never heard it.

    Advice EXPIRES. It is a nudge at a moment in a market, not a standing order
    an agent carries to its grave.
    """

    id: str
    from_who: str                  # who is speaking -- "mentor", a student's name
    text: str
    given_at_hour: float
    expires_after_hours: float = ADVICE_TTL_HOURS
    times_seen: int = 0
    first_seen_hour: float | None = None
    # The valley at the moment this was given. See `Snapshot`.
    before: Snapshot | None = None

    def expires_at_hour(self) -> float:
        return self.given_at_hour + self.expires_after_hours

    def is_live(self, hour: float) -> bool:
        return hour < self.expires_at_hour()

    def format(self, hour: float) -> str:
        """How it reads in the prompt.

        The age and the deadline are both stated. Advice with no clock on it
        invites an agent to file it away and act eventually; this one says how
        long it has.
        """
        age = hour - self.given_at_hour
        left = self.expires_at_hour() - hour
        when = "just now" if age < 0.1 else f"{age:.1f}h ago"
        return (
            f'{self.from_who} told you {when}: "{self.text}" '
            f"(advice, not an order -- you may judge it wrong and say so. "
            f"It stops applying in {left:.1f}h.)"
        )


@dataclass
class Plot:
    """One parcel of ground, owned by somebody, maybe built on.

    LAND IS THE SCARCE THING. Before this, `Business.plots` was an integer and
    every main-road location reported 10**6 free plots, so cash was the only
    limit on how big anything could get and location carried no cost. A plot is
    now an asset in its own right: an agent buys it, holds it, develops it,
    attaches it to a business, and sells it to whoever will pay.

    Separating OWNERSHIP from ASSIGNMENT is what makes that a market rather than
    a fee. Land can be held vacant, bought before it is needed, and sold without
    selling the business standing next to it -- so someone can corner the ground
    around Town without ever running a shop, which is the interesting move.

    `developed` is the difference between ground and floor space. Raw land
    counts for nothing: it holds no stock and seats no employee until somebody
    spends the time or the money to build on it.
    """

    id: str
    location: str
    owner: str | None = None                  # agent id; None == still the world's
    business: str | None = None               # business it is attached to, if any
    developed: bool = False
    # Set while a build is running; the engine finishes it. See `Engine._develop`.
    developing_until: float | None = None
    developing_for: str | None = None         # business the build is for
    # Asking price if the owner has put it on the market, else None.
    for_sale_at: float | None = None
    # A citizen's home stands on it (2026-10-18): not for sale, not a business.
    home: bool = False
    # A defense standing on it: "Guard post" | "Catapult" (2026-10-18).
    structure: str = ""
    # What its owner paid for it (2026-10-28): land counts in net worth at
    # its purchase price. Land handed over with a business, or made before
    # this, paid nothing and counts nothing.
    paid: float = 0.0

    def is_building(self, now: float) -> bool:
        return self.developing_until is not None and now < self.developing_until


@dataclass
class Reasoning:
    """One decision in the agent's own words, and what it did about it.

    `Agent.memory` records what HAPPENED to an agent. Nothing recorded why it
    chose anything: the model's justification existed only in a response body
    that was read for tool calls and then dropped. Asking an agent "why did you
    do that?" therefore produced fluent post-hoc confabulation rather than
    recall, because there was nothing to recall from.

    Intent and consequence are stored together on purpose. "I am buying charcoal
    because the refinery is stalled" is worth little on its own; paired with the
    call that followed and whether it was refused, it is a decision that can be
    judged.
    """

    hour: float
    woken_because: str             # the same `reason` the observation was built for
    text: str                      # the model's own words; may be empty if it just acted
    actions: list[str] = field(default_factory=list)   # e.g. ["buy_item", "travel (refused)"]

    def format(self) -> str:
        did = ", ".join(self.actions) if self.actions else "no action taken"
        said = self.text or "(acted without saying why)"
        return f"[h{self.hour:.1f}] woken: {self.woken_because} | {said} | did: {did}"


@dataclass
class StolenStack:
    """Hot goods sitting in a safehouse, waiting out the 24-hour cure."""

    item: str
    qty: int
    stashed_at: float

    def ready_at(self) -> float:
        return self.stashed_at + D.SAFEHOUSE_CURE_HOURS * 3600.0

    def is_clean(self, now: float) -> bool:
        return now >= self.ready_at()


@dataclass
class Agent:
    id: str
    name: str
    model: str                     # OpenRouter model id; "rule-based" in Phase 1
    archetype: str = "standard"    # Phase 1 rule-agent variant; unused from Phase 2 on
    # WHICH CITY THIS PERSON IS OF. Empty means the home city, which is what
    # every agent in every run recorded before 2026-09-03 was, so an old
    # checkpoint loads with its whole population correctly placed rather than
    # citizenless. Read it through `World.city_of` rather than directly.
    #
    # Citizenship is FIXED. It is not a location -- an agent standing in its own
    # market and an agent down a spur are equally citizens -- and there is no
    # action that changes it. The cities do not touch, so there is nowhere to
    # defect to; what an agent can change is how much its city is worth.
    city: str = ""
    denari: float = D.STARTING_DENARI
    location: str = "Town"
    in_transit: tuple[str, str, float] | None = None   # (origin, dest, progress 0-1)
    inventory: dict[str, int] = field(default_factory=dict)
    # Hot goods. Kept OUT of `inventory` so every sell/trade path excludes them
    # automatically -- they must be laundered in a safehouse first.
    stolen: dict[str, int] = field(default_factory=dict)
    equipped_weapon: str = "Bat"
    equipped_tools: bool = False   # Upgraded Tools: +extraction speed while equipped
    equipped_armor: dict[str, str | None] = field(
        default_factory=lambda: {"Head": None, "Chest": None, "Legs": None}
    )
    owned_vehicles: list[str] = field(default_factory=list)      # Vehicle IDs
    mounted_vehicle: str | None = None                            # Vehicle ID
    owned_businesses: list[str] = field(default_factory=list)     # Business IDs
    owned_property: str | None = None
    current_job: tuple[str, str, float] | None = None             # (business_id, role, wage)
    skill_hours: dict[str, float] = field(
        default_factory=lambda: {r: 0.0 for r in D.WAGE_ROLES}
    )
    # A lifetime bonus, one of D.CALLINGS ("" for none). See data.CALLINGS.
    calling: str = ""
    # KNOW-HOW (2026-10-18): techs learned, and the one being studied
    # {"tech": id, "done": research-hours}. See convoy/progress.py.
    tech: list[str] = field(default_factory=list)
    researching: dict[str, Any] | None = None
    # THE HOUSEHOLD: family members (scripted, not citizens), the house's name
    # (the dynasty), and the houses married into it. See convoy/family.py.
    family: list["FamilyMember"] = field(default_factory=list)
    house: str = ""
    sex: str = ""                    # "m" | "f"; the head of the house's own
    allies: list[str] = field(default_factory=list)
    # Raiders cannot touch a newcomer until this time (sim seconds).
    protected_until: float = 0.0
    # OUTPOSTS (2026-10-27): the claim your home stands on, and whether you
    # have chosen it yet. Everyone before outposts is settled, homeless or in
    # a market square. See `claims.settle`.
    home: str = ""
    settled: bool = True
    # Owed to the state: borrowed to settle somewhere dear. Grows daily and is
    # paid down from what your businesses earn. See `claims.settle`.
    debt: float = 0.0
    # The settlers this one has found (agent ids). With outposts you can only
    # trade with people you have met. See `convoy/discovery.py`.
    known: list[str] = field(default_factory=list)
    # MEETING PEOPLE (2026-10-28): what this agent has chosen to share WITH
    # each other settler (their id -> kinds, see `convoy/social.py`), and the
    # player's own pins on the full map ({x, y, label}).
    shared: dict[str, list[str]] = field(default_factory=dict)
    pins: list[dict[str, Any]] = field(default_factory=list)
    # A delivery run under way (convoy/delivery.py), or None.
    delivery: dict[str, Any] | None = None
    # Missions (convoy/missions.py): those finished, and the one under way.
    missions_done: list[str] = field(default_factory=list)
    mission: dict[str, Any] | None = None
    # A consignment this agent is hauling for a business, and its size. Goods
    # under carriage never enter `inventory`, so they cannot be sold en route.
    hauling: str | None = None
    hauling_units: int = 0
    # Escorts hired for the NEXT journey, paid up front and disbanded on
    # arrival. Hiring is per-trip because that is the decision an owner
    # actually makes -- "is this load worth guarding" is asked of a load, not
    # of a quarter. See `banditry` for what they are worth on the road.
    escorts: list[ConvoyMember] = field(default_factory=list)
    # Set on an AGENT who has taken escort work: the id of whoever it is
    # guarding. A bound escort travels with its employer and is released and
    # paid on arrival. It is one field rather than a second activity because an
    # agent does exactly one thing at a time, and "guarding a convoy" is that
    # thing while it lasts.
    escorting: str | None = None
    bounty_total: float = 0.0
    crimes: list[dict[str, Any]] = field(default_factory=list)
    guild: str | None = None
    is_guild_leader: bool = False
    health: float = 100.0
    alive: bool = True
    respawn_at: float | None = None
    # Sustenance (World State Schema tab, appended section)
    hours_since_last_meal: float = 0.0
    sustenance_stage: str = "Normal"
    last_meal_window: float = D.SELF_PREP_WINDOW_HOURS
    meal_work_bonus: float = 0.0      # from a Laborer's Bread, lasts the window
    insurance: dict[str, float] = field(default_factory=dict)     # product -> coverage
    activity: Activity = field(default_factory=lambda: Activity("idle", 0.0))
    memory: list[int] = field(default_factory=list)               # indices into EventLog
    # Why this agent did things, in its own words. See `Reasoning`.
    reasoning: list[Reasoning] = field(default_factory=list)
    # Advice from outside the simulation. See `Recommendation`.
    inbox: list[Recommendation] = field(default_factory=list)
    next_reeval_at: float = 0.0
    next_diary_at: float = 3600.0
    # When this agent last had the world digest in front of it, so a NEW one
    # can be flagged on line one. See `convoy/digest.py`.
    digest_seen_at: float = -1.0
    # When the model was last asked to decide for this agent, and what was NEWS
    # to it then. A reflex may stand in for the model only while this has not
    # moved and not for long. See `convoy/reflexes.py`.
    last_thought_at: float = -1.0
    thought_fingerprint: list = field(default_factory=list)

    # -- derived ----------------------------------------------------------

    def carry_capacity(self, world: "World") -> int:
        if self.mounted_vehicle:
            base = D.VEHICLES[world.vehicles[self.mounted_vehicle].type].cargo_capacity
        else:
            base = D.ON_FOOT_CAPACITY
        mult = 1.0
        if self.calling == "Hauler":
            mult *= 1.0 + D.CALLING_BONUS
        if "saddles" in self.tech:                  # Pack saddles know-how
            mult *= 1.10
        return math.ceil(base * mult) if mult > 1.0 else base

    def carried_units(self) -> int:
        """Everything on your person, hot goods included -- loot takes up room.

        A consignment being hauled for someone else counts too, and is held as a
        plain unit count rather than as inventory: goods under carriage are not
        yours, so no sell path can reach them. Storing the count here rather
        than looking it up in the world means every capacity check in the
        codebase accounts for a load without knowing consignments exist.
        """
        return sum(self.inventory.values()) + sum(self.stolen.values()) + self.hauling_units

    def remember_reasoning(
        self, hour: float, woken_because: str, text: str, actions: list[str]
    ) -> Reasoning:
        """Record why this agent just did what it did, keeping the last N.

        Trimming here rather than at the call site means no policy can grow an
        agent without bound by being chatty -- a 120-hour run asks some agents
        several hundred times.
        """
        entry = Reasoning(
            hour=round(hour, 2),
            woken_because=woken_because,
            text=(text or "")[:REASONING_CHARS],
            actions=list(actions),
        )
        self.reasoning.append(entry)
        if len(self.reasoning) > MAX_REASONING_KEPT:
            del self.reasoning[:-MAX_REASONING_KEPT]
        return entry

    def assets(self, world: "World") -> dict[str, Any]:
        """What this agent OWNED at this instant, for pinning to a decision.

        A decision row records why and what; without this it does not record
        what the agent had to work with, and "found a mine with 345 denari in
        hand" and "found a mine with 175" are different decisions to judge. Only
        `diary` carried any of it, hourly and net worth alone, so a decision at
        h6.68 could not be tied to the cash behind it.

        Taken at the decision because it cannot be recovered afterwards. The
        event log is append-only and holds no balances; replaying an economy to
        find out what somebody was carrying at hour 40 is not a thing anyone is
        going to do. Same argument as `Snapshot`, one scope down.

        Kept to identifiers and counts. This fires on EVERY decision -- ~7,000
        in an 84-hour run -- so it is sized to be affordable at that rate, and
        the nested structures an observation renders (per-business inventories,
        vehicle cargo) are deliberately left out. What is here is enough to ask
        "what did you own when you made that call?" and get a true answer.
        """
        return {
            "denari": round(self.denari, 2),
            "net_worth": round(self.net_worth(world), 2),
            "location": self.location,
            "health": round(self.health, 1),
            "hunger": self.sustenance_stage,
            "hours_since_meal": round(self.hours_since_last_meal, 2),
            "carrying": dict(self.inventory),
            "carried_units": self.carried_units(),
            "capacity": self.carry_capacity(world),
            "vehicles": [
                {"id": vid, "type": v.type}
                for vid in self.owned_vehicles
                if (v := world.vehicles.get(vid)) is not None
            ],
            "mounted": self.mounted_vehicle,
            # Open businesses only, with the cash and wage bill that decide
            # whether the next payroll lands -- the pair that every insolvency
            # in the last run came down to.
            "businesses": [
                {
                    "id": bid, "type": b.type, "at": b.location,
                    "cash": round(b.cash, 2),
                    "payroll_per_hour": round(
                        sum(e.wage for e in b.roster if e.wage > 0), 2
                    ),
                    "staff": len(b.roster),
                }
                for bid in self.owned_businesses
                if (b := world.businesses.get(bid)) is not None and not b.closed
            ],
            "home": self.owned_property,
            "job": (
                {"business": self.current_job[0], "role": self.current_job[1],
                 "wage": round(self.current_job[2], 2)}
                if self.current_job else None
            ),
        }

    def receive_advice(
        self,
        hour: float,
        from_who: str,
        text: str,
        *,
        expires_after_hours: float = ADVICE_TTL_HOURS,
        rec_id: str | None = None,
    ) -> Recommendation:
        """Put a recommendation in this agent's inbox.

        Queuing only. Nothing here says the agent has SEEN it -- that is
        `observe.py`'s to record, because that is where it either does or does
        not reach the prompt.
        """
        rec = Recommendation(
            id=rec_id or f"ADV{len(self.inbox) + 1:03d}-{self.id}",
            from_who=from_who,
            text=(text or "").strip()[:ADVICE_CHARS],
            given_at_hour=round(hour, 2),
            expires_after_hours=expires_after_hours,
        )
        self.inbox.append(rec)
        if len(self.inbox) > MAX_ADVICE_KEPT:
            del self.inbox[:-MAX_ADVICE_KEPT]
        return rec

    def live_advice(self, hour: float) -> list[Recommendation]:
        """Recommendations still in force at `hour`, oldest first.

        Expired advice stays in the inbox rather than being deleted: the
        transcript needs to be able to show what an agent was told at hour 12
        even when it is being asked about it at hour 60.
        """
        return [r for r in self.inbox if r.is_live(hour)]

    def add_stolen(self, item: str, qty: int = 1) -> None:
        self.stolen[item] = self.stolen.get(item, 0) + qty

    def remove_stolen(self, item: str, qty: int = 1) -> bool:
        have = self.stolen.get(item, 0)
        if have < qty:
            return False
        if have == qty:
            del self.stolen[item]
        else:
            self.stolen[item] = have - qty
        return True

    def net_worth(self, world: "World") -> float:
        prop_value = 0.0
        if self.owned_property:
            prop_value = world.properties[self.owned_property].assessed_value()
        return E.net_worth(
            self.denari,
            self.inventory,
            [world.businesses[b].valuation(world) for b in self.owned_businesses],
            [world.vehicles[v].type for v in self.owned_vehicles],
            prop_value,
            # What it would sell for, here -- the same rule as a business's stock.
            E.realizable_value(world, self.inventory, world.city_of(self)),
        ) + self.land_value(world) - self.debt   # land at cost; owed for settling

    def land_value(self, world: "World") -> float:
        """The land this agent holds, at what was paid for it."""
        return sum(p.paid for p in world.plots.values() if p.owner == self.id)

    def add_item(self, item: str, qty: int = 1) -> None:
        self.inventory[item] = self.inventory.get(item, 0) + qty

    def remove_item(self, item: str, qty: int = 1) -> bool:
        have = self.inventory.get(item, 0)
        if have < qty:
            return False
        if have == qty:
            del self.inventory[item]
        else:
            self.inventory[item] = have - qty
        return True


# ---------------------------------------------------------------------------
# 2. BUSINESS
# ---------------------------------------------------------------------------

@dataclass
class Employment:
    agent_id: str            # Agent ID, or "NPC" for a hired NPC employee
    role: str
    wage: float
    is_researcher: bool = False
    is_npc: bool = False     # NPC hires cost NPC_WAGES and are always on shift


@dataclass
class ResearchState:
    rp: float = 0.0
    efficiency_tier: int = 0
    quality_tier: int = 0
    unspent_rp: float = 0.0
    quality_allocation: dict[str, float] = field(default_factory=dict)


@dataclass
class Business:
    id: str
    type: str
    name: str
    owner: str                       # Agent ID or "Government"
    location: str
    cash: float = 0.0
    roster: list[Employment] = field(default_factory=list)
    inventory: dict[str, int] = field(default_factory=dict)
    # How tall the storehouse is. Production sites grow UPWARD -- a taller
    # barn holds more without taking more ground, which keeps a site's land
    # budget spent on people rather than on stockpile.
    storage_tier: int = 0
    retail_prices: dict[str, float] = field(default_factory=dict)
    # Wages live in their OWN dict. They used to be stuffed into retail_prices
    # under a "wage:<role>" key, and anything that walked that dict expecting
    # tradeable items -- the observation's local-price table did -- asked for
    # the base price of "wage:Miner" and took the whole simulation down with a
    # KeyError. That could only ever fire once a player owned a business AND
    # set a wage, so it survived 60 simulated hours before killing the run on
    # 2026-08-15. One dict, one meaning.
    wages: dict[str, float] = field(default_factory=dict)     # role -> per hour
    research: ResearchState = field(default_factory=ResearchState)
    active_production: str | None = None      # what this business is currently making
    insolvent_since: float | None = None
    # What the business must hold to prove it is viable again: one hour of the
    # payroll it failed to meet, captured BEFORE the unpaid staff walked.
    # Without it, shedding the whole roster drops payroll to zero and the
    # insolvency clock clears itself -- bankruptcy dodged by firing everyone.
    insolvent_debt: float = 0.0
    closed: bool = False
    production_buffer: float = 0.0    # fractional units carried between ticks
    # Set by the engine when production cannot proceed -- no feedstock, or the
    # yard is full. NPC hires are paid only for hours the business can actually
    # produce, so this is what makes an idle NPC free instead of ruinous. One
    # agent lost 2,124 denari in 11 simulated hours to three NPC refinery workers
    # standing in a refinery with no ore (2026-08-16).
    production_blocked: bool = False
    research_buffer: float = 0.0
    peak_headcount: int = 0           # max simultaneous production staff observed
    # The ground under a farm or mine: hidden at founding, revealed when it
    # first produces. See `convoy/land.py`.
    land_rolled: bool = False
    land_bonus_item: str = ""
    land_bonus_pct: float = 0.0
    land_revealed: bool = False
    # PROJECTS (2026-10-18): the one being built {"kind", "done", "total"},
    # and what finished projects added, by kind. See convoy/progress.py.
    project: dict[str, Any] | None = None
    improvements: dict[str, int] = field(default_factory=dict)
    # THE GROUND WEARS AND THE AIR FOULS (2026-10-18). `richness` is a mine's
    # seam left or a farm's soil, 1.0 fresh; `smoke` is what this business is
    # putting into the air. See convoy/ground.py.
    richness: float = 1.0
    smoke: float = 0.0
    plots: int = 0                    # spur land taken; 0 for main-road businesses
    outstanding_insured_value: float = 0.0
    last_convoy_post: float = -1e9

    # -- derived ----------------------------------------------------------

    @property
    def is_government(self) -> bool:
        return self.owner == "Government"

    @property
    def spec(self) -> D.BusinessType:
        return D.BUSINESS_TYPES[self.type]

    def production_staff(self) -> list[Employment]:
        return [e for e in self.roster if not e.is_researcher]

    def researchers(self) -> list[Employment]:
        return [e for e in self.roster if e.is_researcher]

    def is_staffed(self, world: "World") -> bool:
        """Government businesses are always considered fully staffed (Businesses tab).

        For player-owned businesses, a worker counts only if they are alive, present,
        and actually on shift here.
        """
        if self.is_government:
            return True
        for emp in self.production_staff():
            if emp.is_npc:
                return True     # NPC hires are always on shift
            agent = world.agents.get(emp.agent_id)
            if agent and agent.alive and agent.activity.kind == "work" \
                    and agent.activity.detail.get("business") == self.id:
                return True
        return False

    def active_headcount(self, world: "World") -> int:
        """Workers actually on shift right now. Drives the 0.95^(n-1) decay."""
        if self.is_government:
            # Always fully staffed by exemption; treated as a single efficient worker
            # so government output stays a stable market floor rather than scaling.
            return 1
        n = 0
        for emp in self.production_staff():
            if emp.is_npc:
                n += 1
                continue
            agent = world.agents.get(emp.agent_id)
            if agent and agent.alive and agent.activity.kind == "work" \
                    and agent.activity.detail.get("business") == self.id:
                n += 1
        return n

    def active_researchers(self, world: "World") -> int:
        n = 0
        for emp in self.researchers():
            agent = world.agents.get(emp.agent_id)
            if agent and agent.alive and agent.activity.kind == "work" \
                    and agent.activity.detail.get("business") == self.id:
                n += 1
        return n

    def price_for(self, item: str) -> float:
        """Retail price this business charges. NPC businesses use the fixed formula."""
        if self.is_government:
            return E.npc_sell_price(item)
        set_price = self.retail_prices.get(item)
        if set_price is None:
            return E.npc_sell_price(item)
        return max(set_price, E.player_price_floor(item))

    def daily_revenue(self, world: "World") -> float:
        return world.market.revenue_since(self.id, world.sim_time - 24 * 3600.0)

    def daily_profit(self, world: "World") -> float:
        """What this business EARNED over the last 24 hours, above book value.

        Never negative for valuation purposes -- see `valuation`.
        """
        return world.market.margin_since(self.id, world.sim_time - 24 * 3600.0)

    def valuation(self, world: "World") -> float:
        """What this business is worth: what it cost, plus what it earns.

        Startup cost alone made a business a static number that never reflected
        whether it traded; 3x daily sales alone valued a brand-new business at
        zero, so founding one destroyed net worth on the spot and punished the
        behaviour the run exists to observe. Both terms together mean a business
        is worth its purchase price on day one and grows with what it does.

        Cash and stock are counted too, or the books lie in both directions.
        Without cash, a business could run itself deep into debt and still show
        as an asset: on 2026-08-16 the leading agent was ranked at 1,375 while
        holding two businesses 2,852 in the red, so the score the agents were
        told to maximise had come loose from solvency. Without stock, spending
        cash on feedstock would LOOK like destroying value -- the same mistake
        that once made founding a business read as a loss -- and ordering stock
        is the behaviour these runs exist to observe.

        Twice the startup cost is the fixed asset, cash and stock are current
        assets, and 3x daily PROFIT is goodwill; nothing is counted twice. Stock
        is booked at base price while liquidation pays the NPC buy rate, so net
        worth runs a little ahead of what a fire sale would realise. That is
        ordinary book value, and deliberate.

        TWO CHANGES, 2026-09-03, and both are incentives rather than accounting.

        THE COST TERM DOUBLED. Founding used to move net worth sideways: you
        swapped 450 denari for a business worth 450. Now founding CREATES 450,
        because the thing these runs exist to observe is agents building rather
        than drawing wages, and a neutral trade is a weak invitation to take a
        risk. See `BUSINESS_COST_MULTIPLE`.

        GOODWILL IS ON PROFIT, NOT REVENUE. On revenue, every sale minted three
        times its price in net worth whether or not the seller made anything --
        so two agents passing goods back and forth at book price generated
        unbounded value from a trade that moved nothing into or out of anywhere.
        Individual scoring limited that, since the counterparty's gain was a
        rival's gain; CITY scoring counts both sides for you and makes the wash
        trade dominant. On margin it is worth exactly zero. See `margin_since`.

        LOSSES ARE FLOORED AT ZERO here, and only here. A business selling below
        book is destroying value and the books already say so -- the stock
        leaves at base price and less cash comes back. Multiplying that loss by
        three as well would charge it twice and would make selling to the state
        at 0.4x book (the only buyer some agents ever have) a catastrophe rather
        than a bad price. Goodwill is what profitable trade is worth; an
        unprofitable business simply has none.
        """
        spec = D.BUSINESS_TYPES.get(self.type)
        base = spec.startup_cost if spec else 0.0
        # STOCK AT WHAT IT WOULD SELL FOR (2026-10-16). Counted at book, a
        # warehouse of ore nobody would buy made its owner the richest agent in
        # the 2026-10-15 run while he begged for a meal. See `realizable_value`.
        from . import world_map as _M
        return (
            D.BUSINESS_COST_MULTIPLE * base
            + D.BUSINESS_PROFIT_MULTIPLE * max(0.0, self.daily_profit(world))
            + self.cash
            + E.realizable_value(world, self.inventory, _M.city_of(self.location))
        )

    def buy_price_for(self, item: str) -> float:
        """What this business pays a player selling `item` to it."""
        return E.npc_buy_price(item)

    def add_item(self, item: str, qty: int = 1) -> None:
        self.inventory[item] = self.inventory.get(item, 0) + qty

    def remove_item(self, item: str, qty: int = 1) -> bool:
        have = self.inventory.get(item, 0)
        if have < qty:
            return False
        if have == qty:
            del self.inventory[item]
        else:
            self.inventory[item] = have - qty
        return True

    def has_inputs(self, recipe: D.Recipe, batches: int = 1) -> bool:
        return all(self.inventory.get(i, 0) >= q * batches for i, q in recipe.inputs.items())


# ---------------------------------------------------------------------------
# 3. VEHICLE
# ---------------------------------------------------------------------------

@dataclass
class VehicleInstance:
    id: str
    type: str
    owner: str
    location: str
    cargo: dict[str, int] = field(default_factory=dict)
    condition: str = "functional"     # functional | damaged | destroyed
    mounted_by: str | None = None

    @property
    def capacity(self) -> int:
        return D.VEHICLES[self.type].cargo_capacity

    def cargo_units(self) -> int:
        return sum(self.cargo.values())

    def cargo_value(self) -> float:
        return E.inventory_value(self.cargo)


# ---------------------------------------------------------------------------
# 4. PROPERTY
# ---------------------------------------------------------------------------

@dataclass
class Property:
    id: str
    owner: str
    location: str
    garage_tier: int = 0
    storage_tier: int = 0
    upgrades: list[str] = field(default_factory=list)
    rented_to: str | None = None
    purchase_price: float = D.PROPERTY_BASE_COST
    stored: dict[str, int] = field(default_factory=dict)   # home storage
    safehouse: list[StolenStack] = field(default_factory=list)
    plots: int = 4        # land taken on the spur; +1 per storage/garage tier

    def assessed_value(self) -> float:
        value = self.purchase_price
        for t in range(1, self.garage_tier + 1):
            value += D.GARAGE_TIERS[t][0] - (D.GARAGE_TIERS[t - 1][0] if t > 1 else 0)
        for t in range(1, self.storage_tier + 1):
            value += D.STORAGE_TIERS[t][0] - (D.STORAGE_TIERS[t - 1][0] if t > 1 else 0)
        return value

    def storage_capacity(self) -> int:
        if self.storage_tier == 0:
            return D.PROPERTY_BASE_STORAGE
        return D.STORAGE_TIERS[self.storage_tier][1]

    def garage_slots(self) -> int:
        return 0 if self.garage_tier == 0 else D.GARAGE_TIERS[self.garage_tier][1]


# ---------------------------------------------------------------------------
# 5. CONVOY
# ---------------------------------------------------------------------------

@dataclass
class ConvoyMember:
    agent_id: str                # Agent ID, or "NPC" for a hired escort
    role: str                    # Driver-own | Driver-provided | Scout | Bodyguard
    vehicle_id: str | None = None
    # What they bring to a robbery. `banditry` prices deterrence off these, so
    # an escort with an iron sword genuinely is worth more than one with a
    # spear -- and costs more to hire. Defaulted so old checkpoints, which
    # predate escorts entirely, still decode.
    weapon: str = "Wooden Spear"
    armor: tuple[str, ...] = ()
    wage_paid: float = 0.0       # what this journey cost, for the event log


@dataclass
class Convoy:
    id: str
    organizer_business: str
    organizer_agent: str | None
    origin: str
    destination: str
    status: str = "Recruiting"   # Recruiting|Loading|In-Transit|Arrived|Ambushed|Destroyed|Cancelled
    roster: list[ConvoyMember] = field(default_factory=list)
    manifest: dict[str, int] = field(default_factory=dict)
    cargo_owner: dict[str, str] = field(default_factory=dict)
    pay_terms: dict[str, dict] = field(default_factory=lambda: dict(D.CONVOY_PAY))
    posted_at: float = 0.0
    extensions: int = 0
    departs_at: float | None = None
    arrives_at: float | None = None
    progress: float = 0.0

    def vehicle_count(self) -> int:
        return sum(1 for m in self.roster if m.role.startswith("Driver"))

    def cargo_value(self) -> float:
        return E.inventory_value(self.manifest)


# ---------------------------------------------------------------------------
# 6. MARKET
# ---------------------------------------------------------------------------

@dataclass
class Transaction:
    """One sale, for the price feed.

    `city` is the city the trade happened in. The valleys are separate markets
    with no road between them, so a Cinderhold agent reading Aldermarch's prices
    would be reading a market it cannot buy in or sell to -- and worse, the two
    populations would be quietly informing each other, which is precisely the
    contamination that isolating them was meant to avoid.

    Defaulted so an older checkpoint's transactions load as the home city's,
    which is what they were.
    """

    sim_time: float
    item: str
    qty: int
    unit_price: float
    seller: str
    buyer: str
    city: str = ""


@dataclass
class Consignment:
    """Goods a business bought from another business, and the job of moving them.

    The purchase and the haulage are one object on purpose. A store buys from a
    refinery and the goods are immediately the store's -- paid for, out of the
    seller's hands, and sitting at the seller's site waiting for someone to
    carry them. The seller is finished and carries no delivery risk; if nobody
    ever hauls it, that is the buyer's loss.

    Money moves once, at order time: the buyer's business pays the seller for
    the goods AND escrows the courier's fee, so a courier who completes the job
    is always paid.
    """

    id: str
    seller_business: str
    buyer_business: str
    item: str
    qty: int
    goods_price: float          # already paid to the seller
    courier_fee: float          # escrowed by the buyer, released on delivery
    origin: str
    destination: str
    created_at: float
    status: str = "awaiting_courier"   # awaiting_courier|claimed|delivered|cancelled
    courier: str | None = None
    # A vehicle the poster is LENDING for this job, if any. Bound to the
    # consignment rather than transferred: a consignment moves whole, so a
    # 100-unit load is unclaimable by anyone on foot (capacity 5), and without
    # lending only agents who already own a cart can take the jobs that matter.
    # It returns to its owner on delivery, cancellation or abandonment, so
    # lending carries no risk of losing it and needs no trust system.
    lent_vehicle: str | None = None
    # True when the SELLER posted this to push stock out, rather than the buyer
    # posting it to pull stock in. See `post_delivery_job`.
    seller_posted: bool = False
    # THE SELLER'S SHARE of the convoy -- both the courier fee and anything
    # bandits take, split by the same fraction, because "who is responsible for
    # the convoy" is one question and paying for it while not carrying its risk
    # is not a deal anybody would offer.
    #
    # 0.0 is the old hard-coded behaviour and still the default: goods are the
    # buyer's the moment they are paid for, so a load that never arrives is
    # their loss. 1.0 is the seller carrying all of it. The rungs between are
    # `data.CONVOY_SPLITS`, and which one a deal gets is not imposed by the
    # engine -- it is proposed and refused only where the market plainly will
    # not bear it. See `banditry.market_power`.
    seller_share: float = 0.0
    # What was loaded. `qty` falls when bandits take some, so without this there
    # is no way at delivery to know how much of the consignment actually
    # arrived -- and therefore no way to pay a courier for the part it kept.
    # Defaults to 0 and is read through `delivered_fraction`, which falls back
    # to `qty`, so consignments in checkpoints written before this still decode
    # and still pay a full fee for a full load.
    qty_posted: int = 0

    @property
    def buyer_share(self) -> float:
        return 1.0 - self.seller_share

    def delivered_fraction(self) -> float:
        """How much of the original load is still aboard, 0-1."""
        base = self.qty_posted or self.qty
        return min(1.0, self.qty / base) if base else 1.0

    def split_label(self) -> str:
        """How the deal reads, seller first: "75/25"."""
        return f"{self.seller_share * 100:.0f}/{self.buyer_share * 100:.0f}"


@dataclass
class FamilyMember:
    """Someone in a citizen's household: not a citizen, never a model call.

    The household is a citizen's first workforce (designer decision,
    2026-10-18): a member can work any business of the household's, unpaid,
    always on shift. Children grow up on a timer. New children come only from
    a MARRIAGE, which joins two households -- so a family grows through
    diplomacy, not by itself."""
    id: str
    name: str
    adult: bool
    born_at: float
    grown_at: float = 0.0            # when a child comes of age (sim seconds)
    calling: str = ""
    works_at: str = ""               # a business id of the household's, or ""
    spouse: str = ""                 # the member they married, in this household
    from_house: str = ""             # the house they married in from
    next_child_at: float = 0.0       # for a married couple; set on the elder
    sex: str = ""                    # "m" | "f"
    role: str = ""                   # partner | son | daughter | in-law


@dataclass
class Claim:
    """A place made where there was none (designer request, 2026-10-18): four
    plots on open land anywhere on the map, joined to the road network by a
    dirt road its claimant paid for. It behaves as a spur off its nearest
    junction -- see `world_map.register_claims`."""
    name: str
    city: str                        # the town of its nearest junction
    junction: str
    x: float                         # metres, layout coordinates (the block's centre)
    y: float
    road: list[list[float]]          # the dirt road, [[x, y], ...], from the network to here
    road_m: float
    seconds: float                   # one way to the junction at Medium
    owner: str                       # who paid for it
    created_at: float = 0.0


@dataclass
class Dispatch:
    """Something on its way that nobody walks (2026-10-27): a meal a tavern
    sends out to someone's outpost, or the state's convoy coming to collect
    goods it has bought from a yard. Paid or delivered at `arrives_at`."""
    id: str
    kind: str                        # "meal" | "state_pickup"
    agent: str                       # who ordered it
    business: str                    # the tavern that sends, or the yard sold from
    item: str
    qty: int
    unit_price: float
    fee: float
    destination: str                 # where it goes (a meal) or is collected from
    created_at: float
    arrives_at: float
    status: str = "on_way"           # on_way | done


@dataclass
class ShareRequest:
    """One settler asking another to share something (2026-10-28): their
    standing, holdings, locations, trade, family or contact. See social.py."""
    id: str
    sender: str
    target: str
    kind: str
    created_at: float
    status: str = "open"             # open | accepted | declined


@dataclass
class ChatGroup:
    """A group chat (2026-10-28): its owner invites people who have shared
    their contact. Separate from clans, which are political."""
    id: str
    name: str
    owner: str
    members: list[str] = field(default_factory=list)


@dataclass
class MarriageOffer:
    """A proposal: your member marries theirs, who joins your household, and
    you pay the dowry. Accepted, the two houses are allies."""
    id: str
    proposer: str                    # agent
    member: str                      # the proposer's member
    target: str                      # agent asked
    their_member: str
    dowry: float
    created_at: float
    status: str = "open"             # open | accepted | declined


@dataclass
class BuyOrder:
    """A standing bid: "I will pay `price` each for `qty` of `item`, at my business."

    Designer request, 2026-10-17: post the price and how many you want, so that
    other people can fill it. The other half of a market -- until now goods
    could only be OFFERED at a price (`retail_prices`), never asked for, so a
    buyer had to find a seller and take what they charged.

    THE MONEY IS HELD, so a seller who fills it is certain of being paid: the
    buying business escrows `price * qty`, plus the carriage, when it posts. A
    fill pays the seller from that and leaves the goods to be carried, exactly
    as an `order_from_business` does -- a consignment at the seller's site,
    with this order's share of `courier_fee` for whoever hauls it (none, and
    the buyer fetches it). Partial fills are fine; cancelling returns the rest.
    """
    id: str
    buyer: str                       # agent who posted it
    business: str                    # where the goods go; pays from its cash
    item: str
    qty: int                         # still wanted
    price: float                     # per unit
    created_at: float
    qty_posted: int = 0
    courier_fee: float = 0.0         # for the whole order; a fill carries its share
    escrow: float = 0.0              # held now: goods + carriage still unspent
    status: str = "open"             # open | filled | cancelled


@dataclass
class Raid:
    """People lying in wait on a road, to rob whoever comes along it.

    THE BANDITS ARE PEOPLE NOW (designer decision, 2026-10-16). Robbery is no
    longer a dice roll by nobody: an agent plans a raid on a road segment,
    others join it, and they wait on that road with whatever weapons they own.
    When a load crosses the road the raiders' strength meets the convoy's --
    escorts, weapons, armour, the cart's own plating -- and either the load is
    taken, the convoy outruns them, or the raiders are beaten off and some of
    them die. Death costs what was on you: cargo, the cart you rode, your
    weapons and armour. Cash and everything else you own are kept.

    `target` narrows it to one named traveller; empty means anyone with cargo.
    Members must be standing at one end of the road to join -- you cannot lie
    in wait from the other side of the map.
    """
    id: str
    organizer: str
    segment: str
    created_at: float
    until: float
    members: list[str] = field(default_factory=list)
    target: str | None = None
    status: str = "waiting"          # waiting | over
    takings: float = 0.0             # book value stolen so far


@dataclass
class EscortPosting:
    """An owner advertising a place on their next convoy, open to any agent.

    The escort market's whole point is that a PERSON is cheaper than an NPC
    (`banditry.ESCORT_NPC_MULTIPLIER`), so an owner who is willing to wait and
    negotiate pays less than one who wants a guard this instant. That is the
    same trade the job board already makes for employees, and the same one
    `post_delivery_job` makes for haulage.

    It names a DESTINATION because an escort is being asked to end up somewhere,
    which is a real cost to them -- a guard hired from Town to Refinery Row is
    in Refinery Row afterwards, with whatever that is worth.
    """

    id: str
    owner: str                       # agent id
    role: str                        # a key of data.CONVOY_PAY
    fee: float
    origin: str
    destination: str
    posted_at: float
    # A weapon the owner will lend for the trip, if the escort's own is weak.
    # Bound to the job and returned on arrival, exactly like a lent vehicle --
    # see `Consignment.lent_vehicle` for the argument that lending needs no
    # trust system when the thing cannot be kept.
    lent_weapon: str | None = None
    status: str = "open"             # open|taken|cancelled|done
    taken_by: str | None = None


@dataclass
class Market:
    transactions: list[Transaction] = field(default_factory=list)

    def record(self, t: Transaction) -> None:
        self.transactions.append(t)

    def margin_since(self, seller: str, since: float) -> float:
        """PROFIT on what `seller` sold at or after `since`, against book value.

        Revenue minus what the goods were worth, rather than revenue. The
        difference decides whether trading with yourself is a strategy.

        Book price is the yardstick because it is the same yardstick
        `inventory_value` uses, and the two have to agree or the books
        contradict themselves. A business holding 100 Grain is credited with
        100 x base; selling it for exactly base moves that value from stock to
        cash and creates nothing, which is correct -- no wealth was made, an
        asset changed form. Selling it ABOVE base is the business earning its
        keep, and that is what gets capitalised.

        WHY NOT COST OF ACQUISITION. Charging each sale against what the seller
        actually paid would be truer accounting and needs per-unit cost
        tracking through production, refining and haulage, which does not
        exist. Book value is the honest approximation available: it is what
        every other valuation in this economy already uses.

        A REFINERY IS NOT PENALISED FOR SELLING AT BOOK. Its value-add is
        already banked -- turning 600 of ore into 4,400 of bronze raises
        `inventory_value` by 3,800 the moment the bronze exists. The margin
        term is for trade, not for production; production is paid in stock.

        Walks backwards and stops at the cutoff, like `revenue_since`.
        """
        total = 0.0
        for t in reversed(self.transactions):
            if t.sim_time < since:
                break
            if t.seller == seller:
                total += (t.unit_price - D.base_price(t.item)) * t.qty
        return total

    def revenue_since(self, seller: str, since: float) -> float:
        """What `seller` took in from sales at or after `since`.

        Walks backwards and stops at the cutoff: transactions are appended in
        time order, and this is called once per business per observation, so a
        full scan would grow with the length of the run.
        """
        total = 0.0
        for t in reversed(self.transactions):
            if t.sim_time < since:
                break
            if t.seller == seller:
                total += t.unit_price * t.qty
        return total

    def recent_avg_price(self, item: str, since: float) -> float | None:
        rows = [t for t in self.transactions if t.item == item and t.sim_time >= since]
        if not rows:
            return None
        units = sum(t.qty for t in rows)
        return sum(t.unit_price * t.qty for t in rows) / units if units else None


# ---------------------------------------------------------------------------
# 7. GUILD
# ---------------------------------------------------------------------------

@dataclass
class Guild:
    id: str
    name: str
    leader: str
    members: list[str] = field(default_factory=list)
    invited: list[str] = field(default_factory=list)   # invite-only: must be asked
    # A secret clan: nobody outside it sees who belongs (2026-10-18).
    secret: bool = False


# ---------------------------------------------------------------------------
# CHAT -- three channels
# ---------------------------------------------------------------------------

@dataclass
class JobPosting:
    """A business advertising a role at a wage, visible to everyone.

    Before this the player labour market was invisible. An owner could set any
    wage above the floor, but a jobseeker standing at the business saw only
    "1 player-owned and may hire" -- no role, no rate, no sign it was hiring at
    all. On 2026-08-16 a mine offering a Miner 35.00/hr could not attract a
    single agent and fell back on an NPC at 43.33, while agents queued for the
    state's 20.56. The offer existed; nothing carried it.

    Applications do NOT auto-hire. The owner reviews and picks, which is what
    makes reposting at a lower wage -- or a higher one when nobody bites -- a
    real decision rather than a formality.
    """

    id: str
    business_id: str
    owner: str                        # agent id, so applicants know who decides
    role: str
    wage: float
    posted_at: float
    expires_at: float
    as_researcher: bool = False
    applicants: list[str] = field(default_factory=list)   # agent ids, in order
    status: str = "open"              # open | filled | closed | expired
    # A JOB OFFER to one named person rather than an advert to everyone
    # (`offer_job`). That person can take it outright with `accept_job_offer`
    # -- including from another employer, which is the point: poaching.
    invitee: str | None = None

    def is_live(self, sim_time: float) -> bool:
        return self.status == "open" and sim_time < self.expires_at

    def hours_open(self, sim_time: float) -> float:
        return max(0.0, (sim_time - self.posted_at) / 3600.0)


@dataclass
class ChatMessage:
    """One line of chat.

    Per the Actions tab, READING chat is available context every turn rather than
    a callable action; only posting is an action.
    """

    sim_time: float
    channel: str          # "world" | "guild" | "direct"
    sender: str           # Agent ID
    sender_name: str
    text: str
    guild_id: str | None = None      # channel == "guild"
    recipient: str | None = None     # channel == "direct"
    # OUTPOSTS (2026-10-28): public chat is heard only by those near the
    # speaker when it was said (None: everyone, as before); group chat by the
    # group's members.
    heard_by: list[str] | None = None
    group_id: str | None = None      # channel == "group"
    # The speaker's city, copied from `Agent.city` RAW rather than normalised
    # through `World.city_of`. "World" chat is a city's marketplace, not a
    # broadcast across the map: there is no road between the valleys and
    # shouting does not travel further than walking. Carried on the message
    # rather than looked up on the sender, so `visible_to` stays a pure function
    # of two records and a message keeps meaning what it meant when it was
    # spoken -- which also means both sides of the comparison must be the same
    # kind of value. Normalising one and not the other made an agent unable to
    # read its own messages.
    sender_city: str = ""

    def visible_to(self, agent: "Agent") -> bool:
        # WORLD CHAT REACHES EVERY CITY now that roads join them (2026-10-16):
        # hiring, recruiting and convoys cross city lines, so talk must too.
        # The speaker's city is shown on the line, so a reader knows who's who.
        if self.channel == "world":
            return self.heard_by is None or agent.id == self.sender or agent.id in self.heard_by
        if self.channel == "group":
            return agent.id == self.sender or agent.id in (self.heard_by or [])
        if self.channel == "direct":
            return agent.id in (self.sender, self.recipient)
        if self.channel == "guild":
            return agent.guild is not None and agent.guild == self.guild_id
        return False

    def format(self) -> str:
        h = int(self.sim_time // 3600)
        m = int((self.sim_time % 3600) // 60)
        if self.channel == "world":
            tag = "[world]" if self.heard_by is None else "[nearby]"
        elif self.channel == "group":
            tag = f"[group {self.group_id}]"
        elif self.channel == "guild":
            tag = f"[guild {self.guild_id}]"
        else:
            tag = f"[dm -> {self.recipient}]"
        # The sender's ID, which is what `pay`, `offer_job` and a DM take. A
        # name alone left the 2026-10-16 smoke's Cinderhold citizens guessing
        # it from "A4" in somebody's message -- and paying their refinery
        # pool to an Aldermarch citizen who was raising one of his own.
        return f"{h:03d}:{m:02d} {tag} {self.sender_name} ({self.sender}): {self.text}"


# ---------------------------------------------------------------------------
# 8. BOUNTY
# ---------------------------------------------------------------------------

@dataclass
class Bounty:
    target: str
    total: float = 0.0
    crimes: list[dict[str, Any]] = field(default_factory=list)
    player_contributions: list[tuple[str, float]] = field(default_factory=list)
    status: str = "active"


# ---------------------------------------------------------------------------
# 9. GOVERNMENT
# ---------------------------------------------------------------------------

@dataclass
class Proposal:
    id: str
    proposer: str
    kind: str
    payload: dict[str, Any]
    cosigners: list[str] = field(default_factory=list)
    votes_for: list[str] = field(default_factory=list)
    votes_against: list[str] = field(default_factory=list)
    status: str = "draft"        # draft | ballot | enacted | rejected | reversed
    opened_at: float = 0.0


@dataclass
class Government:
    wage_tax: float = D.DEFAULT_WAGE_TAX
    sales_tax: float = D.DEFAULT_SALES_TAX
    property_tax: float = D.DEFAULT_PROPERTY_TAX
    road_tax: float = D.ROAD_TAX_DAILY    # daily levy on Net Worth, funds roads/police
    police_tier: int = 0
    treasury: float = 0.0
    bounty_multiplier: float = 1.0
    convoy_speed_modifier: float = 1.0
    second_route: bool = False
    active_policies: list[str] = field(default_factory=list)
    proposals: dict[str, Proposal] = field(default_factory=dict)
    history: list[dict[str, Any]] = field(default_factory=list)

    def collect(self, amount: float) -> None:
        self.treasury += amount

    def enact(self, policy_name: str) -> tuple[bool, str]:
        """Apply a road/police policy: adjust the daily levy and the service.

        Voting itself is Phase 3; this is the effect side, so a passed vote has
        somewhere to land.
        """
        policy = D.ROAD_POLICIES.get(policy_name)
        if policy is None:
            return False, f"no such policy {policy_name!r}"
        if policy_name in self.active_policies:
            return False, f"{policy_name} is already in force"
        if policy.police_tier and policy.police_tier != self.police_tier + 1:
            return False, (
                f"police tiers are cumulative -- need tier {self.police_tier + 1} first"
            )

        self.road_tax = D.road_tax_per_bill(self.road_tax + policy.rate_delta)
        self.convoy_speed_modifier += policy.convoy_speed
        if policy.police_tier:
            self.police_tier = policy.police_tier
        if policy.second_route:
            self.second_route = True
        self.active_policies.append(policy_name)
        self.history.append({"policy": policy_name, "road_tax": self.road_tax})
        return True, f"{policy_name} enacted; road tax now {self.road_tax:.2%}/day"

    def reverse(self, policy_name: str) -> tuple[bool, str]:
        """Undo a policy -- restores both the service level and its tax delta."""
        policy = D.ROAD_POLICIES.get(policy_name)
        if policy is None or policy_name not in self.active_policies:
            return False, "not in force"
        self.road_tax = D.road_tax_per_bill(self.road_tax - policy.rate_delta)
        self.convoy_speed_modifier -= policy.convoy_speed
        if policy.police_tier:
            self.police_tier = policy.police_tier - 1
        if policy.second_route:
            self.second_route = False
        self.active_policies.remove(policy_name)
        self.history.append({"reversed": policy_name, "road_tax": self.road_tax})
        return True, f"{policy_name} reversed; road tax now {self.road_tax:.2%}/day"


# ---------------------------------------------------------------------------
# TRADE OFFERS -- direct player-to-player exchange
# ---------------------------------------------------------------------------

@dataclass
class TradeOffer:
    """A proposed swap of goods for Denari between two co-located agents.

    Only goods the seller can actually REACH are tradeable: what they carry, plus
    a vehicle's hold or their home's storage if either is at the same location.
    """

    id: str
    seller: str
    buyer: str
    items: dict[str, int]
    price: float
    location: str
    offered_at: float
    status: str = "open"       # open | accepted | declined | expired | invalid


# ---------------------------------------------------------------------------
# 10. WORLD
# ---------------------------------------------------------------------------

@dataclass
class World:
    sim_time: float = 0.0            # seconds since hour 0
    # THE CITIES THIS WORLD CONTAINS, by key, in a stable order. A one-city
    # world -- everything before 2026-09-03, and still the default -- holds one
    # entry and behaves exactly as it always did. `world_map` knows how to
    # describe more cities than any given world actually populates, so this is
    # the authority on which ones exist, not `M.CITY_KEYS`.
    cities: list[str] = field(default_factory=lambda: [M.HOME_CITY])
    agents: dict[str, Agent] = field(default_factory=dict)
    businesses: dict[str, Business] = field(default_factory=dict)
    vehicles: dict[str, VehicleInstance] = field(default_factory=dict)
    properties: dict[str, Property] = field(default_factory=dict)
    plots: dict[str, Plot] = field(default_factory=dict)
    convoys: dict[str, Convoy] = field(default_factory=dict)
    market: Market = field(default_factory=Market)
    guilds: dict[str, Guild] = field(default_factory=dict)
    bounties: dict[str, Bounty] = field(default_factory=dict)
    government: Government = field(default_factory=Government)
    chat: list[ChatMessage] = field(default_factory=list)
    trade_offers: dict[str, "TradeOffer"] = field(default_factory=dict)
    consignments: dict[str, "Consignment"] = field(default_factory=dict)
    escort_postings: dict[str, "EscortPosting"] = field(default_factory=dict)
    raids: dict[str, "Raid"] = field(default_factory=dict)
    buy_orders: dict[str, "BuyOrder"] = field(default_factory=dict)
    marriage_offers: dict[str, "MarriageOffer"] = field(default_factory=dict)
    claims: dict[str, "Claim"] = field(default_factory=dict)
    dispatches: dict[str, "Dispatch"] = field(default_factory=dict)
    share_requests: dict[str, "ShareRequest"] = field(default_factory=dict)
    # Where anyone off the road network really stands (the player, walking
    # the 3D world), in map metres: id -> [x, y]. See discovery.position.
    positions: dict[str, list[float]] = field(default_factory=dict)
    groups: dict[str, "ChatGroup"] = field(default_factory=dict)
    # OUTPOSTS (2026-10-27): nobody starts in a town. Everyone settles on open
    # land; the state's sites in each market are the anchors that feed, hire
    # and buy, and selling to the state calls its convoy. See GAME_MODES.md.
    outposts: bool = False
    # Faceless dice-roll bandits on every road (`engine._resolve_banditry`).
    # Off for runs since 2026-10-16: robbery is done by people (`Raid`).
    npc_bandits: bool = True
    # Draws every farm's and mine's hidden ground. See `convoy/land.py`.
    land_seed: int = 0
    # The latest "what's working" summary, when it was published, and the
    # numbers the next one measures change against. See `convoy/digest.py`.
    digest: str = ""
    digest_at: float = -1.0
    digest_baseline: dict[str, Any] = field(default_factory=dict)
    job_postings: dict[str, "JobPosting"] = field(default_factory=dict)
    # Items and Denari dropped on death, lootable by anyone at that location.
    ground_loot: dict[str, dict] = field(default_factory=dict)
    # The hour the government left, or None while it is still here. Read by the
    # observation layer and by the prompt prefix: after a withdrawal the whole
    # briefing has to stop describing a state that no longer exists, and this is
    # the single fact everything else keys off. Checkpointable, so a resumed
    # world does not forget that the state is gone.
    state_withdrawn_at: float | None = None
    # PER CITY, when the state leaves one valley and stays in the other
    # (`EngineConfig.state_exits_city`). `state_withdrawn_at` stays the record of
    # a withdrawal from EVERYWHERE, so every run before this field existed reads
    # exactly as it did. Ask `state_gone_at(city)`, never either field directly.
    state_withdrawn_in: dict[str, float] = field(default_factory=dict)
    # NO GOVERNMENT, EVER (designer decision, 2026-10-16). Not a withdrawal: no
    # state businesses are built, nothing buys or sells at a fixed price, no
    # wages are paid by anyone but a citizen, and no tax is collected. Every
    # reader of "is the state gone?" answers yes from hour zero.
    no_state: bool = False
    # STARTER SITES (designer decision, 2026-10-18): a no-state world that
    # still opens with the state's Tavern, Farm, Mine and Refinery in each
    # city -- a fixed-price backstop that sells, buys and hires from hour zero,
    # so a town has somewhere to eat and work while citizens build. No tax, no
    # other branches.
    starter_sites: bool = False
    next_property_tax_at: float = D.PROPERTY_TAX_PERIOD_HOURS * 3600.0
    next_road_tax_at: float = D.ROAD_TAX_PERIOD_HOURS * 3600.0
    _seq: int = 0

    def drop_loot(self, location: str, items: dict[str, int], denari: float) -> None:
        pile = self.ground_loot.setdefault(location, {"denari": 0.0, "items": {}})
        pile["denari"] += denari
        for item, qty in items.items():
            pile["items"][item] = pile["items"].get(item, 0) + qty

    @property
    def sim_hour(self) -> float:
        return self.sim_time / 3600.0

    def new_id(self, prefix: str) -> str:
        self._seq += 1
        return f"{prefix}{self._seq:04d}"

    def businesses_at(self, location: str, type: str | None = None) -> list[Business]:
        return [
            b for b in self.businesses.values()
            if b.location == location and not b.closed and (type is None or b.type == type)
        ]

    def government_business(self, type: str) -> Business | None:
        for b in self.businesses.values():
            if b.is_government and b.type == type and not b.closed:
                return b
        return None

    def leaderboard(self) -> list[tuple[str, float]]:
        rows = [(a.name, a.net_worth(self)) for a in self.agents.values()]
        return sorted(rows, key=lambda kv: -kv[1])

    # -- cities ------------------------------------------------------------

    def city_of(self, agent: "Agent | str") -> str:
        """Which city an agent is of. Empty citizenship means the home city.

        Takes an agent or an id, because half the callers hold one and half the
        other and neither should have to look the other up.
        """
        if isinstance(agent, str):
            found = self.agents.get(agent)
            if found is None:
                return self.cities[0]
            agent = found
        return agent.city or self.cities[0]

    def state_gone_at(self, city: str) -> float | None:
        """The hour the government left THIS city, or None if it is still here.

        The single question the briefing, the tool schemas, the refusals and the
        observation all ask. Asking it per city is the whole of the one-city
        experiment: with the state gone from Cinderhold only, an Aldermarcher
        must go on being told about -- and offered -- a government that still
        exists for them, and a Cinderholder must not.
        """
        if self.no_state:
            return 0.0
        if city in self.state_withdrawn_in:
            return self.state_withdrawn_in[city]
        return self.state_withdrawn_at

    def agents_in(self, city: str) -> list["Agent"]:
        return [a for a in self.agents.values() if self.city_of(a) == city]

    def rival_of(self, city: str) -> str | None:
        """The FIRST other city, or None in a one-city world. With three cities
        there is more than one rival; ask `rivals_of` for all of them."""
        others = self.rivals_of(city)
        return others[0] if others else None

    def rivals_of(self, city: str) -> list[str]:
        return [c for c in self.cities if c != city]

    def is_contest(self) -> bool:
        return len(self.cities) > 1

    def city_wealth(self, city: str) -> float:
        """THE SCORE. The sum of every citizen's net worth, living and dead.

        This is the definition of winning, so it is worth being explicit about
        what it does and does not do.

        IT IS A SUM, NOT A MEAN. Twenty citizens each worth 500 and nineteen
        citizens each worth 520 with one dead are 10,000 and 9,880: losing a
        person costs the city that person's entire contribution and is never
        offset by the survivors averaging higher. That is the intended
        incentive. Death already wipes an agent's businesses, vehicles and home
        (`Engine._wipe_assets`), so a corpse contributes roughly its pocket
        change -- keeping a neighbour alive is worth more to a city than almost
        anything else one citizen can do for another.

        THE DEAD ARE COUNTED, at whatever they are now worth, rather than
        dropped. Dropping them would make a city's score RISE when its poorest
        citizen starved, which is the exact opposite of the thing being
        measured.

        BUSINESS CASH IS COUNTED ONCE, through the owner, because
        `Business.valuation` is what `Agent.net_worth` already uses. A business
        is not a citizen and has no separate seat at the table.
        """
        return self._city_totals().get(city, 0.0)

    def _city_totals(self) -> dict[str, float]:
        """WHERE WEALTH COUNTS (designer decision, 2026-10-16), now that people
        can work and build in any city: a citizen's own cash, goods, vehicles
        and home count for the city they belong to; every business counts for
        the city it STANDS in, whoever owns it. Build a mine in a rival's
        valley and you have made the rival richer.

        Business cash is still counted once: a business's valuation is taken
        out of its owner's personal worth here and added to its city instead.
        """
        totals = {c: 0.0 for c in self.cities}
        for a in self.agents.values():
            home = self.city_of(a)
            biz_value = 0.0
            for bid in a.owned_businesses:
                b = self.businesses.get(bid)
                if b is None:
                    continue
                v = b.valuation(self)
                biz_value += v
                where = M.city_of(b.location)
                totals[where] = totals.get(where, 0.0) + v
            totals[home] = totals.get(home, 0.0) + a.net_worth(self) - biz_value
        return totals

    def city_standings(self) -> list[dict[str, Any]]:
        """Every city, richest first, with the numbers behind the number.

        The shape the observation, the boards and the hourly event all read, so
        that a citizen, a spectator and the log cannot disagree about who is
        winning.
        """
        rows = []
        totals = self._city_totals()
        for city in self.cities:
            people = self.agents_in(city)
            worths = {a.id: a.net_worth(self) for a in people}
            total = totals.get(city, 0.0)
            rows.append({
                "city": city,
                "name": M.CITIES[city].name if city in M.CITIES else city,
                "total_net_worth": round(total, 2),
                "citizens": len(people),
                "living": sum(1 for a in people if a.alive),
                "dead": sum(1 for a in people if not a.alive),
                "businesses": sum(
                    1 for b in self.businesses.values()
                    if not b.closed and not b.is_government
                    and M.city_of(b.location) == city
                ),
                "richest": (
                    max(people, key=lambda a: worths[a.id]).name if people else None
                ),
                "mean_net_worth": round(total / len(people), 2) if people else 0.0,
            })
        rows.sort(key=lambda r: -r["total_net_worth"])
        return rows
