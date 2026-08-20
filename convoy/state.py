"""The ten entity types from the World State Schema tab, as real data structures.

Field names track the spreadsheet's field names closely enough to be checkable
against it. Everything is plain dataclasses so checkpointing is straightforward.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from . import data as D
from . import economy as E


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
    denari: float = D.STARTING_DENARI
    location: str = "Town"
    in_transit: tuple[str, str, float] | None = None   # (origin, dest, progress 0-1)
    inventory: dict[str, int] = field(default_factory=dict)
    # Hot goods. Kept OUT of `inventory` so every sell/trade path excludes them
    # automatically -- they must be laundered in a safehouse first.
    stolen: dict[str, int] = field(default_factory=dict)
    equipped_weapon: str = "Slingshot"
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
    # A consignment this agent is hauling for a business, and its size. Goods
    # under carriage never enter `inventory`, so they cannot be sold en route.
    hauling: str | None = None
    hauling_units: int = 0
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

    # -- derived ----------------------------------------------------------

    def carry_capacity(self, world: "World") -> int:
        if self.mounted_vehicle:
            return D.VEHICLES[world.vehicles[self.mounted_vehicle].type].cargo_capacity
        return D.ON_FOOT_CAPACITY

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
        )

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

        Startup cost is the fixed asset, cash and stock are current assets, and
        3x daily revenue is goodwill; nothing is counted twice. Stock is booked
        at base price while liquidation pays the NPC buy rate, so net worth runs
        a little ahead of what a fire sale would realise. That is ordinary book
        value, and deliberate.
        """
        spec = D.BUSINESS_TYPES.get(self.type)
        base = spec.startup_cost if spec else 0.0
        return (
            base
            + D.BUSINESS_REVENUE_MULTIPLE * self.daily_revenue(world)
            + self.cash
            + E.inventory_value(self.inventory)
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
    agent_id: str
    role: str                    # Driver-own | Driver-provided | Scout | Bodyguard
    vehicle_id: str | None = None


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
    sim_time: float
    item: str
    qty: int
    unit_price: float
    seller: str
    buyer: str


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


@dataclass
class Market:
    transactions: list[Transaction] = field(default_factory=list)

    def record(self, t: Transaction) -> None:
        self.transactions.append(t)

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

    def visible_to(self, agent: "Agent") -> bool:
        if self.channel == "world":
            return True
        if self.channel == "direct":
            return agent.id in (self.sender, self.recipient)
        if self.channel == "guild":
            return agent.guild is not None and agent.guild == self.guild_id
        return False

    def format(self) -> str:
        h = int(self.sim_time // 3600)
        m = int((self.sim_time % 3600) // 60)
        if self.channel == "world":
            tag = "[world]"
        elif self.channel == "guild":
            tag = f"[guild {self.guild_id}]"
        else:
            tag = f"[dm -> {self.recipient}]"
        return f"{h:03d}:{m:02d} {tag} {self.sender_name}: {self.text}"


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
    job_postings: dict[str, "JobPosting"] = field(default_factory=dict)
    # Items and Denari dropped on death, lootable by anyone at that location.
    ground_loot: dict[str, dict] = field(default_factory=dict)
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
