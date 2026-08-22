"""Bandits on the road: whether a load arrives, and how much of it.

No combat, no turn order, no action. A journey with cargo is resolved as a
chain of probabilities and, if it fails, a fraction of the load is gone.

WHY A CHAIN AND NOT ONE NUMBER
------------------------------
Every road segment has carried three numbers since Phase 1 -- `concealment`,
`vantage` and `exposure` -- and until now they were averaged into `danger` and
used for exactly one thing: pricing a courier's fee. Their own docstrings say
what they were for. Concealment is "how well an ambusher hides FROM SCOUTS",
vantage is "the attacker's first-strike advantage", and exposure is "how
trapped the convoy is (blocks Flee Off-Road)".

Those are three different questions and they take three different answers:

    1. are you found?      concealment   <- scouts
    2. do they press?      vantage       <- guards, weapons, armour
    3. can you run?        exposure      <- vehicle speed

So the model is `p_intercept * p_press * (1 - p_escape)`, per segment, and a
route's risk is the chance of losing at least one of them. This is why buying a
scout and buying a sword are different purchases with different effects, rather
than two ways of adding to a single "safety" stat.

WHERE THE RISK LIVES
--------------------
On the trunk road, one roll per segment crossed. Not on the spurs, because
`world_map.travel_path` already states the rule this model has to obey:
"convoys never use spurs, only solo trips do." A dead-end track where a robber
can be seen coming and cannot get away is a bad place to work.

That also means DISTANCE enters as segment count rather than as a multiplier
someone chose. Copper Gulch to Town crosses one segment; Refinery Row to Town
crosses two, and is genuinely twice-ish the exposure. Within a segment, a fast
vehicle is exposed for less time and is proportionally less likely to be found.

TWO RULES THAT OVERRIDE THE EQUATION
------------------------------------
A traveller ON FOOT is never robbed, and a convoy is never safer than
`MIN_SEGMENT_RISK` per stretch. The first is the bottom of the ladder and the
second is the top: walking is slow and safe, the best convoy in the valley is
fast and still not certain, and everything interesting happens in between.

ON FOOT IS THE WORST WAY TO CARRY ANYTHING
------------------------------------------
Slowest on the road, so exposed longest; no speed to run with, so `p_escape` is
zero; and one pair of hands with whatever it happens to be holding. The only
thing in a walker's favour is that a cheap load is not worth the ambush -- and
that protection evaporates the moment what they carry is worth something.

Splitting a big load into many small walked ones therefore does NOT buy safety
any more. It buys many separate rolls at a risk that is only low while the
per-trip value is low.

THE CART IS NEVER TAKEN
-----------------------
Bandits take goods and leave the vehicle, always (designer decision,
2026-08-20). No theft, no damage, no `VehicleInstance.condition` changing --
that is the full game's business, not this mode's.

It is stated here, and pinned by a test, because it is currently true by
OMISSION: nothing in this file mentions vehicles, so nothing takes them, and an
invariant nobody wrote down is one a later edit removes without noticing. The
same reasoning applies to a vehicle lent with a consignment, which
`_return_lent_vehicle` always gives back.

It also means a driver on a convoy is NOT risking its cart, whatever a future
bidding screen might want to charge for. If the cart is ever to be at stake,
that is a deliberate change here, not a side effect somewhere else.

WHAT IT DOES NOT DO
-------------------
Nobody is hurt. `health` stays untouched and armour is deterrence, not
protection -- it makes the bandits decide you are not worth it.

But the CARGO is not protected. Being caught costs between half the load and
all of it, rolled flat, and losing all of it is a real outcome rather than a
theoretical one. That is deliberate: it is what makes a guard worth hiring and
a premium worth paying, and it is why `Cargo` insurance stopped being a product
that did nothing.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from . import data as D
from . import world_map as M

if TYPE_CHECKING:                      # pragma: no cover
    from .state import Agent, World

# ---------------------------------------------------------------------------
# Constants -- calibrated in `calibrate()`, which prints the table these were
# tuned against. Change one and run it.
# ---------------------------------------------------------------------------

# Stage 1: being found.
INTERCEPT_BASE = 1.55           # scales the whole interception term
REFERENCE_SECONDS = 45.0        # _BASE: a nominal segment at Medium speed
SCOUT_MAX_REDUCTION = 0.75      # the most scouts can hide you
SCOUT_HALF = 1.5                # scouts for half of that maximum

# A robbery has to be worth the walk. Without this the model says a labourer
# carrying five units of ore is ambushed on the Bridge nine times in ten, which
# stops the economy before it starts -- at hour zero every agent is on foot with
# a free Slingshot, and no one can buy the cart that fixes it if nothing they
# carry ever arrives. It is also what makes the upgrade ladder cohere: a bigger
# vehicle carries more value and therefore ATTRACTS more attention, so the cart
# and the guards are bought together rather than the cart alone being "safer".
REFERENCE_CARGO_VALUE = 300.0   # a middling load; the curve's half-way point
ATTRACT_FLOOR = 0.15            # even a pauper is occasionally unlucky

# Stage 2: being pressed. A contest function -- neither side ever hits 0 or 1.
BANDIT_BASE = 1.00
VANTAGE_WEIGHT = 1.00           # how much first-strike ground emboldens them

# Stage 3: getting away. Gated by exposure, so the Bridge is nearly inescapable.
ESCAPE_MAX = 0.80

# WALKING IS NOT SAFE ANY MORE (designer decision, 2026-08-21). The blanket
# exemption was removed after the 20-agent run of that date routed the entire
# convoy system around it: of 26 haulage jobs posted, TWENTY were for exactly
# five units -- foot capacity -- and every one of the 32 loads delivered was ten
# units or fewer, while four hundred-unit loads sat unclaimed for hours. One
# agent said it plainly at h0.08: "Traveling by foot feels safer."
#
# The reasoning that justified the exemption was that walking is slow, so
# splitting a load would cost more in time than it saved in risk. That holds for
# ONE agent and fails for a MARKET of twenty: twenty couriers each walking five
# units move the same tonnage as one cart, and the time is paid in parallel by
# spare labour rather than serially by the shipper.
#
# Nothing replaced it, because nothing had to. The equation already says what a
# person on foot is: the SLOWEST thing on the road (longest exposure), with the
# worst escape (speed floor, so `p_escape` is zero), carrying almost no
# deterrence. Only `attractiveness` is low, and only while the load is cheap --
# five bronze daggers are worth six hundred denari and are noticed. That is the
# gradient we wanted, and we had been overriding it with a flat rule.
ON_FOOT = "On Foot"

# NO AMOUNT OF MONEY BUYS SAFETY (designer decision, 2026-08-20). Every stretch
# of open road carries at least this much risk however good the convoy is.
# Floored PER SEGMENT rather than per route, so risk still composes: a two-
# segment journey with the best kit in the game floors at 5.9%, not 3%, which
# keeps "a longer road is more dangerous" true all the way to the top of the
# ladder.
MIN_SEGMENT_RISK = 0.03

# A Bronze Sword is the mid anchor: one armed adult of no special quality.
WEAPON_ANCHOR_DAMAGE = 34.0
UNARMED_STRENGTH = 0.15         # a floor, so an empty party is not certain doom
VEHICLE_ARMOR_BONUS = {"None": 0.00, "Light": 0.15, "Medium": 0.30, "Heavy": 0.45}

# What a successful robbery takes, rolled flat between these (designer
# decision, 2026-08-20). NOT graded by how badly the standoff went: the odds of
# being caught are where all the structure lives, and layering a second
# probability on the size of the loss would make a load's fate depend on two
# rolls a player cannot see separately.
#
# 100% MEANS TOTAL LOSS IS REAL. An earlier version guaranteed something always
# survived; it does not any more. Being caught is now genuinely ruinous, which
# is the whole reason cargo insurance exists rather than being a curiosity.
LOOT_FRACTION_MIN = 0.50
LOOT_FRACTION_MAX = 1.00

# What a robbery costs ON AVERAGE, given it happens. The fair-odds price of
# insuring a load is this times the chance of being caught, so the brokerage
# and the risk model read the same number rather than each carrying a copy.
EXPECTED_LOSS_FRACTION = (LOOT_FRACTION_MIN + LOOT_FRACTION_MAX) / 2.0


# ---------------------------------------------------------------------------
# The escort
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Escort:
    """One body on the road, agent or NPC.

    `weapon` and `armor` are item names from `data.WEAPONS` / `data.ARMOR`, so
    an agent's own kit and a hired NPC's kit price out through the same code.
    """
    name: str
    role: str = "Bodyguard"          # a key of data.CONVOY_PAY
    weapon: str = "Slingshot"
    armor: tuple[str, ...] = ()

    @property
    def strength(self) -> float:
        w = D.WEAPONS.get(self.weapon)
        power = (w.damage if w else 0.0) / WEAPON_ANCHOR_DAMAGE
        reduction = sum(
            D.ARMOR[a].damage_reduction for a in self.armor if a in D.ARMOR
        )
        return power * (1.0 + reduction)


@dataclass(frozen=True)
class Party:
    """Who and what is on the road, and what they are carrying.

    `escorts` INCLUDES THE TRAVELLER. A lone courier is a party of one, and the
    weapon they happen to be carrying is the whole of the party's strength --
    which is why an agent's default free Slingshot is not a rounding error but
    the entire early game. Use `Party.solo()` rather than building a one-element
    tuple by hand.
    """
    escorts: tuple[Escort, ...] = ()
    vehicle: str = "On Foot"
    cargo_value: float = 0.0

    @property
    def attractiveness(self) -> float:
        """How much this load is worth being robbed for, 0-1.

        Saturating rather than linear: past a few hundred denari a load is
        already worth the trouble and more value adds little. The floor keeps
        even a trivial load slightly risky, so "carry nothing valuable" is not a
        way to make the road free.
        """
        v = max(0.0, self.cargo_value)
        return ATTRACT_FLOOR + (1.0 - ATTRACT_FLOOR) * v / (v + REFERENCE_CARGO_VALUE)

    @classmethod
    def solo(
        cls,
        vehicle: str = "On Foot",
        cargo_value: float = 0.0,
        weapon: str = "Slingshot",
        armor: tuple[str, ...] = (),
    ) -> "Party":
        """One person, their own kit, no hired help."""
        return cls((Escort("traveller", "Driver-own", weapon, armor),), vehicle, cargo_value)

    @property
    def on_foot(self) -> bool:
        """Walking: slowest, least escapable, least deterring. Not safe."""
        return self.vehicle == ON_FOOT

    @property
    def scouts(self) -> int:
        return sum(1 for e in self.escorts if e.role == "Scout")

    @property
    def speed_mult(self) -> float:
        v = D.VEHICLES.get(self.vehicle)
        return v.speed_mult if v else D.VEHICLES["On Foot"].speed_mult

    @property
    def strength(self) -> float:
        """Total deterrence. Scouts fight too, but they are not why you buy one."""
        v = D.VEHICLES.get(self.vehicle)
        armor = VEHICLE_ARMOR_BONUS.get(v.armor if v else "None", 0.0)
        # An empty party is nobody on the road, which cannot happen -- but a
        # strength of zero makes the contest function certain, and a model that
        # returns "robbed, definitely" for a state the world cannot reach is a
        # trap for the first caller who forgets the traveller. Floor it at one
        # unarmed pair of hands.
        bodies = sum(e.strength for e in self.escorts) or UNARMED_STRENGTH
        return bodies * (1.0 + armor)


# ---------------------------------------------------------------------------
# The equation
# ---------------------------------------------------------------------------

def _clamp(x: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, x))


def p_intercept(segment: M.RoadSegment, party: Party) -> float:
    """Stage 1 -- are you found at all?

    Concealment is the ambusher's cover and scouts are what strips it. Time on
    the stretch is the second half: a slow cart is simply available for longer.
    The third is whether the load is worth the ambush at all.
    """
    hidden = segment.concealment * (
        1.0 - SCOUT_MAX_REDUCTION * party.scouts / (party.scouts + SCOUT_HALF)
    )
    exposure_time = (segment.seconds / party.speed_mult) / REFERENCE_SECONDS
    return _clamp(INTERCEPT_BASE * hidden * exposure_time * party.attractiveness)


def p_press(segment: M.RoadSegment, party: Party) -> float:
    """Stage 2 -- having found you, do they come on?

    A contest between their nerve and your escort. Vantage is ground that makes
    them bolder; weapons, armour and numbers are what makes them reconsider.
    Neither side is ever certain, which is why this is a ratio and not a
    threshold.
    """
    bandit = BANDIT_BASE * (1.0 + VANTAGE_WEIGHT * segment.vantage)
    return _clamp(bandit / (bandit + party.strength))


def p_escape(segment: M.RoadSegment, party: Party) -> float:
    """Stage 3 -- can you outrun them with the load still aboard?

    Gated by exposure, so this is where `can_flee_offroad()` stops being a flag
    nothing reads. On the Bridge, exposure 0.90 leaves almost nothing here
    however fast the horses are: there is nowhere to go but forward or back.
    """
    speed = _clamp((party.speed_mult - 0.5) / 1.5)
    return _clamp(ESCAPE_MAX * speed * (1.0 - segment.exposure))


def segment_risk(segment: M.RoadSegment, party: Party) -> float:
    """Chance of losing cargo on ONE stretch of road.

    One rule sits outside the equation: nobody is ever perfectly safe, however
    well equipped. Walking used to be a second exemption and is not any more --
    see `ON_FOOT`.
    """
    risk = (
        p_intercept(segment, party)
        * p_press(segment, party)
        * (1.0 - p_escape(segment, party))
    )
    return _clamp(max(risk, MIN_SEGMENT_RISK))


@dataclass(frozen=True)
class RouteRisk:
    origin: str
    destination: str
    probability: float
    per_segment: tuple[tuple[str, float], ...] = field(default_factory=tuple)
    on_foot: bool = False

    @property
    def percent(self) -> str:
        return f"{self.probability * 100:.0f}%"

    def explain(self) -> str:
        """One line an agent can be shown BEFORE it dispatches.

        The whole point of the system is that better vehicles and better escorts
        get bought, and nothing gets bought on the strength of a number the
        buyer never sees. PHASE4 §2: the observation has to carry what the code
        already knows, at the moment of the decision.
        """
        if not self.per_segment:
            return "No open road on this route -- nothing to rob you."
        worst = max(self.per_segment, key=lambda s: s[1])
        floored = all(r <= MIN_SEGMENT_RISK + 1e-9 for _n, r in self.per_segment)
        tail = (
            " That is the floor: no convoy is ever completely safe."
            if floored else
            f" Worst stretch: {worst[0]} at {worst[1] * 100:.0f}%."
        )
        return (
            f"CONVOY RISK: about {self.percent} chance of losing part of this load "
            f"between {self.origin} and {self.destination}." + tail
        )


def route_risk(origin: str, destination: str, party: Party) -> RouteRisk:
    """Chance of being robbed at least once between two places."""
    _seconds, segments = M.travel_path(origin, destination)
    survives = 1.0
    per_segment: list[tuple[str, float]] = []
    for seg in segments:
        risk = segment_risk(seg, party)
        per_segment.append((seg.name, risk))
        survives *= 1.0 - risk
    return RouteRisk(
        origin, destination, 1.0 - survives, tuple(per_segment), party.on_foot,
    )


def resolve(
    origin: str,
    destination: str,
    party: Party,
    rng: random.Random | None = None,
) -> tuple[bool, float]:
    """Roll it. Returns (robbed, fraction_lost).

    The rng is injected so a run is reproducible and a test is not a coin toss.
    """
    rng = rng or random.Random()
    risk = route_risk(origin, destination, party)
    if rng.random() >= risk.probability:
        return False, 0.0
    return True, rng.uniform(LOOT_FRACTION_MIN, LOOT_FRACTION_MAX)


def escort_cost(party: Party, cargo_value: float) -> float:
    """What the escort bills, through the existing Convoy tab rates."""
    return sum(
        D.CONVOY_PAY[e.role]["flat"]
        + cargo_value * D.CONVOY_PAY[e.role]["commission"]
        for e in party.escorts
        if e.role in D.CONVOY_PAY
    )


# ---------------------------------------------------------------------------
# Hiring, and the bridge from a live agent to a party on the road
# ---------------------------------------------------------------------------

# An escort brings their own kit and charges for the privilege, per journey.
# Without this every hire would cost the same whatever they carried, and "what
# kind of weapons they have" would be a lever with no price on it -- agents
# would always take the best, and the choice would not be a choice.
ESCORT_KIT_RATE = 0.02

# AN NPC COSTS HALF AGAIN WHAT AN AGENT DOES, exactly as `NPC_WAGE_MULTIPLIER`
# already does for employees -- convenience at a premium. The Convoy tab's rates
# are what a PERSON is worth; an NPC is that plus the premium for turning up on
# demand with no negotiation, no posting and no waiting.
#
# It is the whole reason an escort labour market can exist. If an NPC were the
# cheap option, no agent would ever be worth hiring and `post_escort_job` would
# be a tool nobody used -- the same trap the wage multiplier was cut from 2.25
# to 1.50 to escape, where the convenient option was also the only viable one.
ESCORT_NPC_MULTIPLIER = 1.50

# A cart is not a company. Enough that numbers matter, few enough that hiring
# stays one decision rather than a recruitment drive.
MAX_ESCORTS = 6


def escort_kit_price(weapon: str, armor: tuple[str, ...]) -> float:
    """Per-journey surcharge for the gear an escort turns up with."""
    value = D.WEAPONS[weapon].base_price if weapon in D.WEAPONS else 0.0
    value += sum(D.ARMOR[a].base_price for a in armor if a in D.ARMOR)
    return value * ESCORT_KIT_RATE


def hire_price(
    role: str, weapon: str, armor: tuple[str, ...], cargo_value: float,
    npc: bool = False,
) -> float:
    """What one escort costs for one journey: Convoy tab rate, plus their kit.

    This is what a PERSON is worth for the trip, and it is the number an owner
    should expect to post a job at. An NPC costs `ESCORT_NPC_MULTIPLIER` times
    it, so hiring a real agent is always the cheaper of the two and the labour
    market has a reason to exist.
    """
    terms = D.CONVOY_PAY[role]
    price = terms["flat"] + cargo_value * terms["commission"] + escort_kit_price(weapon, armor)
    return price * (ESCORT_NPC_MULTIPLIER if npc else 1.0)


def suggested_fee(role: str, cargo_value: float, brings_vehicle: bool = False) -> float:
    """What to offer an AGENT for one escort journey.

    A recommendation, not a rule -- like `courier_fee`, an owner may offer what
    they like and a job nobody takes is information too. Quoted against a plain
    spear-and-no-armour escort, because what an agent turns up carrying is the
    agent's business and pricing it in would be guessing at their kit.
    """
    role = "Driver-own" if brings_vehicle and role.startswith("Driver") else role
    return hire_price(role, "Wooden Spear", (), cargo_value, npc=False)


def cargo_at_risk(world: "World", agent: "Agent") -> tuple[float, str]:
    """What this agent stands to lose on the road, and what to call it.

    Two kinds of cargo and they are NOT interchangeable. An agent's own
    `inventory` is theirs to lose. A consignment under `hauling` belongs to the
    business that bought it -- the courier is carrying someone else's property,
    which is exactly why `Consignment` keeps it out of `inventory` in the first
    place. Both are robbable; who eats the loss is a different question, and
    `Consignment.seller_share` on the consignment is what answers it.

    BOTH ARE COUNTED, AND THAT MATTERS. An earlier version returned the
    consignment OR the inventory, and a bandit cannot tell the difference: it
    made "take a courier job, then carry your valuables along" a way to move
    your own goods at somebody else's risk and none of your own. What is on the
    cart is what is on the cart.
    """
    from . import economy as E

    value, parts = 0.0, []
    if agent.hauling and agent.hauling in world.consignments:
        con = world.consignments[agent.hauling]
        value += D.base_price(con.item) * con.qty
        parts.append(f"{con.qty}x {con.item} under carriage")
    own = E.inventory_value(agent.inventory)
    if own > 0:
        value += own
        parts.append(f"{sum(agent.inventory.values())} units of your own goods")
    return value, " and ".join(parts) if parts else "nothing"


def party_for(world: "World", agent: "Agent", cargo_value: float | None = None) -> Party:
    """The agent, whatever it hired, and whatever it is riding.

    The agent counts as one of the bodies -- see `Party` -- carrying the weapon
    and armour it actually has equipped, which at hour zero is a free Slingshot
    and nothing else.
    """
    if cargo_value is None:
        cargo_value, _what = cargo_at_risk(world, agent)

    own_armor = tuple(a for a in agent.equipped_armor.values() if a)
    bodies = [Escort(agent.id, "Driver-own", agent.equipped_weapon, own_armor)]
    bodies += [
        Escort(m.agent_id, m.role, m.weapon, tuple(m.armor)) for m in agent.escorts
    ]

    # THE BEST CART IN THE CONVOY IS THE CONVOY'S CART. A Driver-own escort is
    # paid the top rate precisely for bringing one, so if theirs is faster than
    # the employer's, that is what the party moves at -- otherwise the premium
    # buys nothing and the role is a worse-paid Driver-provided.
    candidates = []
    if agent.mounted_vehicle and agent.mounted_vehicle in world.vehicles:
        candidates.append(world.vehicles[agent.mounted_vehicle].type)
    for m in agent.escorts:
        if m.vehicle_id and m.vehicle_id in world.vehicles:
            candidates.append(world.vehicles[m.vehicle_id].type)
    vehicle = max(
        candidates, key=lambda v: D.VEHICLES[v].speed_mult, default=ON_FOOT
    )
    return Party(tuple(bodies), vehicle, cargo_value)


def risk_for(world: "World", agent: "Agent", destination: str) -> RouteRisk:
    """The number to put in front of an agent BEFORE it sets off."""
    return route_risk(agent.location, destination, party_for(world, agent))


# ---------------------------------------------------------------------------
# Who pays for the convoy
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class MarketPower:
    """How many people you could deal with instead, on both sides of a trade.

    The rule Justin stated, and it is just scarcity: ONE refinery buying from
    THREE mines does not have to pay for haulage, because a mine with no other
    customer will offer to. THREE refineries chasing ONE mine will pay,
    because the mine can wait and they cannot.

    So the ABUNDANT side pays and the SCARCE side names the terms. Nothing here
    imposes that -- it is disclosed to both sides and the engine only refuses a
    demand the market plainly would not bear.
    """
    item: str
    sellers: int
    buyers: int

    @property
    def stronger(self) -> str:
        if self.sellers > self.buyers:
            return "buyer"          # spoilt for choice
        if self.buyers > self.sellers:
            return "seller"
        return "neither"

    @property
    def customary(self) -> str:
        """Who would normally carry the convoy cost, given who needs whom."""
        return {"buyer": "seller", "seller": "buyer"}.get(self.stronger, "buyer")

    def explain(self) -> str:
        if self.stronger == "neither":
            return (
                f"{self.item}: {self.sellers} selling, {self.buyers} buying -- "
                f"evenly matched, so haulage is whatever you can agree."
            )
        return (
            f"{self.item}: {self.sellers} selling, {self.buyers} buying. "
            f"A {self.stronger} can pick and choose and a {self.customary} "
            f"cannot, so the {self.customary} would normally pay for the convoy."
        )


def _consumers_of(item: str) -> set[str]:
    """Business types with a recipe that eats this item."""
    types: set[str] = set()
    for table in (D.REFINING_RECIPES, D.CRAFTING_RECIPES):
        for recipe in table.values():
            if item in recipe.inputs:
                types.add(recipe.produced_at)
    return types


def market_power(world: "World", item: str) -> MarketPower:
    """Count who is actually trading this, right now.

    Open businesses only, and government sites COUNT -- they are the market
    floor, they really will buy and sell, and pretending otherwise would tell a
    miner it has no customer when the state refinery is standing there. What
    they are not is a business that can be haggled with, which is why the floor
    shows up as a count rather than as an offer.
    """
    consumers = _consumers_of(item)
    sellers = buyers = 0
    for biz in world.businesses.values():
        if biz.closed:
            continue
        if item in biz.spec.outputs:
            sellers += 1
        if biz.type in consumers:
            buyers += 1
    return MarketPower(item, sellers, buyers)


def customary_split(power: MarketPower) -> float:
    """The seller's share that the market structure would normally produce.

    Scarcity decides. Where sellers are thin the buyer needs them more, so the
    buyer carries most of the convoy; where buyers are thin it reverses; and
    evenly matched is an even split. Exactly Justin's mines-and-refineries rule,
    expressed on the ladder instead of as a coin flip.
    """
    if power.stronger == "seller":
        return 0.25          # a scarce seller makes the buyer carry most of it
    if power.stronger == "buyer":
        return 0.75          # a scarce buyer makes the seller carry most of it
    return 0.50
