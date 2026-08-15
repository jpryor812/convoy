"""Phase 1 deterministic policies -- no API calls, no reasoning.

Fixed logic that always produces the same output for the same input. These are
throwaway test tools, not a preview of the real roster: their only job is to
exercise every system in Phase 1 hard enough that broken state surfaces.

`StandardRules` is the priority ladder specified in the handoff. Two deliberately
broken control archetypes run alongside it, because the specified ladder by
construction never starves and never goes bankrupt -- and Phase 1 has to *prove*
those paths fire correctly, not merely avoid them:

  * NeverEats   -- ignores the eat rule entirely, to drive Hungry -> Starving -> Death
  * Overreacher -- founds a business it cannot fund, to drive the 24h bankruptcy path
"""

from __future__ import annotations

from . import actions as A
from . import data as D
from . import economy as E
from . import world_map as M
from .events import EventLog
from .state import Agent, World

SHIFT_HOURS = 4.0
EAT_THRESHOLD_HOURS = 8.0          # handoff: "If Hours Since Last Meal > 8: eat"
LOW_DENARI = 150.0                 # "Denari is low"
BUSINESS_THRESHOLD = D.BUSINESS_TYPES["Farm"].startup_cost + 120.0


# ---------------------------------------------------------------------------
# Location helpers
# ---------------------------------------------------------------------------

def _nearest(world: World, agent: Agent, btype: str):
    """Closest non-closed business of `btype` by travel time."""
    candidates = [
        b for b in world.businesses.values() if b.type == btype and not b.closed
    ]
    if not candidates:
        return None
    return min(
        candidates,
        key=lambda b: E.travel_seconds(agent.location, b.location, None),
    )


def _goto(world: World, log: EventLog, agent: Agent, location: str) -> bool:
    """True if already there; otherwise start travelling and return False."""
    if agent.location == location:
        return True
    A.travel_to(world, log, agent, location)
    return False


def _spur_with_room(world: World, agent: Agent, plots: int) -> str | None:
    """Nearest spur with at least `plots` of free land, ties broken by distance."""
    options = [
        s.name for s in M.SPURS if M.plots_free(world, s.name) >= plots
    ]
    if not options:
        return None
    return min(options, key=lambda n: E.travel_seconds(agent.location, n, None))


def _sellable(agent: Agent) -> str | None:
    for item in agent.inventory:
        if item in D.RESOURCES:
            return item
    return next(iter(agent.inventory), None)


# ---------------------------------------------------------------------------
# The specified rule set
# ---------------------------------------------------------------------------

class StandardRules:
    """The handoff's Phase 1 ladder, evaluated top-down. First match wins."""

    eats = True

    buys_vehicle = True

    joins_guilds = True

    def act(self, world: World, log: EventLog, agent: Agent, reason: str) -> None:
        if self._rule_loot(world, log, agent):
            return
        if self.joins_guilds and self._rule_accept_invite(world, log, agent):
            return
        if self.eats and self._rule_eat(world, log, agent):
            return
        if self._rule_sell(world, log, agent):
            return
        if self.buys_vehicle and self._rule_buy_vehicle(world, log, agent):
            return
        if self._rule_buy_business(world, log, agent):
            return
        if self._rule_run_own_business(world, log, agent):
            return
        self._rule_work(world, log, agent)

    # -- rule 0: free money on the ground ----------------------------------

    def _rule_loot(self, world, log, agent) -> bool:
        pile = world.ground_loot.get(agent.location)
        if not pile or (not pile["items"] and pile["denari"] <= 0):
            return False
        ok, _ = A.loot_ground(world, log, agent)
        return ok

    # -- rule 0.5: take a guild invite if one is waiting -------------------

    def _rule_accept_invite(self, world, log, agent) -> bool:
        if agent.guild:
            return False
        for guild in world.guilds.values():
            if agent.id in guild.invited:
                ok, _ = A.accept_guild_invite(world, log, agent, guild.id)
                if ok:
                    A.post_guild_chat(
                        world, log, agent, f"{agent.name} joining from {agent.location}."
                    )
                return ok
        return False

    # -- rule 1: eat (non-negotiable) --------------------------------------

    def _rule_eat(self, world, log, agent) -> bool:
        if agent.hours_since_last_meal <= EAT_THRESHOLD_HOURS:
            return False
        ok, _ = A.eat_self_prep(world, log, agent)
        if ok:
            return True
        tavern = _nearest(world, agent, "Tavern / Inn")
        if tavern is None:
            return False
        if agent.denari < E.meal_price("Meal"):
            return False        # can't afford it; fall through and go earn
        if not _goto(world, log, agent, tavern.location):
            return True         # travelling to eat counts as acting on the rule
        ok, _ = A.buy_meal(world, log, agent, tavern.id)
        return ok

    # -- rule 2: sell what we're holding -----------------------------------

    def _rule_sell(self, world, log, agent) -> bool:
        if not agent.inventory:
            return False
        full = agent.carried_units() >= agent.carry_capacity(world)
        holding_goods = any(i in D.RESOURCES for i in agent.inventory)
        if not (full or holding_goods):
            return False
        # Keep self-prep ingredients rather than selling our own food supply.
        item = _sellable(agent)
        if item in D.SELF_PREP_INPUTS and agent.hours_since_last_meal > 4:
            return False
        buyer = _nearest(world, agent, "Refinery")
        if buyer is None or item is None:
            return False
        if not _goto(world, log, agent, buyer.location):
            return True
        A.sell_to_business(world, log, agent, buyer.id, item, agent.inventory[item])
        return True

    # -- rule 2.5: buy a pack animal before founding anything --------------

    def _rule_buy_vehicle(self, world, log, agent) -> bool:
        """A Farm makes 72 units/hr; on foot you can move 5 per trip, so ~93% of
        production strands. The cheap early vehicle is what makes owning a
        business beat wage labour at all -- measured 588 -> 1,065 Net Worth."""
        if agent.owned_vehicles:
            return False
        price = E.npc_sell_price("Camel")
        if agent.denari < price + 60:
            return False
        stable = _nearest(world, agent, "Vehicle Dealer / Stable")
        if stable is None:
            return False
        if not _goto(world, log, agent, stable.location):
            return True
        ok, _ = A.buy_vehicle(world, log, agent, "Camel")
        if ok:
            A.mount(world, log, agent, agent.owned_vehicles[-1])
        return ok

    # -- rule 3: buy a business once we can afford one ---------------------

    def _rule_buy_business(self, world, log, agent) -> bool:
        if agent.owned_businesses or agent.denari < BUSINESS_THRESHOLD:
            return False
        # A farm is worked land: it only exists down a spur, and needs 8 free
        # plots there. Go find ground before spending anything.
        spur = _spur_with_room(world, agent, M.SITE_BASE_PLOTS)
        if spur is None:
            return False
        if not _goto(world, log, agent, spur):
            return True
        if agent.current_job:
            A.quit_job(world, log, agent)
        ok, _ = A.start_business(world, log, agent, "Farm", seed_cash=100.0)
        if not ok:
            return False
        biz_id = agent.owned_businesses[-1]
        A.set_production(world, log, agent, biz_id, "Grain")
        A.apply_for_job(world, log, agent, biz_id, "Farmhand")
        A.start_shift(world, log, agent, SHIFT_HOURS)
        return True

    # -- rule 4: run the business we own -----------------------------------

    def _rule_run_own_business(self, world, log, agent) -> bool:
        if not agent.owned_businesses:
            return False
        biz = world.businesses.get(agent.owned_businesses[0])
        if biz is None or biz.closed:
            agent.owned_businesses.clear()
            agent.current_job = None
            return False
        if not _goto(world, log, agent, biz.location):
            return True
        # Pull finished stock into personal inventory so rule 2 can sell it.
        # Take a FULL load -- collecting a fixed 5 regardless of capacity wastes
        # every vehicle an agent owns and makes production look unprofitable.
        space = agent.carry_capacity(world) - agent.carried_units()
        if biz.inventory.get("Grain", 0) >= space and space > 0:
            A.collect_business_inventory(world, log, agent, biz.id, "Grain", space)
            return True
        if agent.activity.kind != "work":
            if not agent.current_job:
                A.apply_for_job(world, log, agent, biz.id, "Farmhand")
            A.start_shift(world, log, agent, SHIFT_HOURS)
        return True

    # -- rule 5: otherwise go work for wages -------------------------------

    def _rule_work(self, world, log, agent) -> None:
        if agent.activity.kind == "work":
            return
        # "Travel to the nearest resource node and mine/farm" -- under the
        # employment bootstrap that means taking a shift at the nearest
        # government extraction business.
        target, role = self._pick_workplace(world, agent)
        if target is None:
            return
        if not _goto(world, log, agent, target.location):
            return
        if agent.current_job and agent.current_job[0] != target.id:
            A.quit_job(world, log, agent)
        if not agent.current_job:
            A.apply_for_job(world, log, agent, target.id, role)
        if agent.current_job:
            A.start_shift(world, log, agent, SHIFT_HOURS)

    def _pick_workplace(self, world, agent):
        mine = _nearest(world, agent, "Mining Operation")
        farm = _nearest(world, agent, "Farm")
        options = []
        if mine:
            options.append((mine, "Miner"))
        if farm:
            options.append((farm, "Farmhand"))
        if not options:
            return None, ""
        return min(
            options, key=lambda o: E.travel_seconds(agent.location, o[0].location, None)
        )


# ---------------------------------------------------------------------------
# Deliberately broken controls
# ---------------------------------------------------------------------------

class NeverEats(StandardRules):
    """Identical to StandardRules but skips the eat rule.

    Proves the Sustenance escalation actually fires: this agent must go Normal ->
    Hungry (12h past window) -> Starving (-5 HP) -> Death, then respawn.
    """

    eats = False


class Overreacher(StandardRules):
    """Founds a Farm on a shoestring and hires an NPC Farmhand it cannot afford.

    Now that owners draw no wage, self-staffing alone can no longer bankrupt a
    business, so this control overspends on payroll instead: an NPC Farmhand at
    the full 50/hr NPC wage against 20 Denari of seed cash. The business must hit
    zero inside the first hour and close after exactly the 24-hour grace period.

    It deliberately uses the CHEAPEST business (Farm, 300) rather than a
    Weaponsmith (700) -- with the government now paying the smart wage instead of
    the NPC wage, an agent never accumulates 700 inside 48 hours, so a Weaponsmith
    control silently never fires.
    """

    def act(self, world, log, agent, reason):
        if self._rule_eat(world, log, agent):
            return
        if not agent.owned_businesses:
            cost = D.BUSINESS_TYPES["Farm"].startup_cost
            if agent.denari >= cost + 20:
                spur = _spur_with_room(world, agent, M.SITE_BASE_PLOTS)
                if spur is None or not _goto(world, log, agent, spur):
                    return
                if agent.current_job:
                    A.quit_job(world, log, agent)
                ok, _ = A.start_business(world, log, agent, "Farm", seed_cash=20.0)
                if ok:
                    biz_id = agent.owned_businesses[-1]
                    A.set_production(world, log, agent, biz_id, "Grain")
                    A.hire_npc_employee(world, log, agent, biz_id, "Farmhand")
                    A.apply_for_job(world, log, agent, biz_id, "Farmhand")
                    A.start_shift(world, log, agent, SHIFT_HOURS)
                return
            self._rule_work(world, log, agent)
            return

        biz = world.businesses.get(agent.owned_businesses[0])
        if biz is None or biz.closed:
            agent.owned_businesses.clear()
            agent.current_job = None
            return
        if not _goto(world, log, agent, biz.location):
            return
        if agent.activity.kind != "work":
            if not agent.current_job:
                A.apply_for_job(world, log, agent, biz.id, "Blacksmith")
            A.start_shift(world, log, agent, SHIFT_HOURS)


# ---------------------------------------------------------------------------
# Policy dispatch
# ---------------------------------------------------------------------------

class Manufacturer(StandardRules):
    """Saves for a Home Improvement Store and makes Property Upgrades.

    Exists to exercise the input-consuming production path -- farms extract raw
    Grain and consume nothing, so without this the factory auto-sourcing code
    never runs. Home Improvement Store (500) is the cheapest business with a real
    recipe that an agent can actually afford inside 48 hours.
    """

    TARGET = "Home Improvement Store"

    def act(self, world, log, agent, reason):
        if self._rule_loot(world, log, agent):
            return
        if self._rule_eat(world, log, agent):
            return
        if not agent.owned_businesses:
            cost = D.BUSINESS_TYPES[self.TARGET].startup_cost
            if agent.denari >= cost + 150:
                # A store belongs on the main road, not down a spur.
                if not _goto(world, log, agent, "Town"):
                    return
                if agent.current_job:
                    A.quit_job(world, log, agent)
                ok, _ = A.start_business(world, log, agent, self.TARGET, seed_cash=140.0)
                if ok:
                    biz_id = agent.owned_businesses[-1]
                    A.set_production(world, log, agent, biz_id, "Property Upgrade")
                    A.apply_for_job(world, log, agent, biz_id, "Store Clerk")
                    A.start_shift(world, log, agent, SHIFT_HOURS)
                return
            self._rule_work(world, log, agent)
            return

        biz = world.businesses.get(agent.owned_businesses[0])
        if biz is None or biz.closed:
            agent.owned_businesses.clear()
            agent.current_job = None
            return
        if not _goto(world, log, agent, biz.location):
            return
        # Sell finished upgrades back through the business so it earns revenue.
        space = agent.carry_capacity(world) - agent.carried_units()
        if biz.inventory.get("Property Upgrade", 0) >= space and space > 0:
            A.collect_business_inventory(world, log, agent, biz.id, "Property Upgrade", space)
            return
        if agent.activity.kind != "work":
            if not agent.current_job:
                A.apply_for_job(world, log, agent, biz.id, "Store Clerk")
            A.start_shift(world, log, agent, SHIFT_HOURS)


class ResearchHouse(StandardRules):
    """Founds a Farm and works it as a RESEARCHER rather than a producer.

    Exercises the research path end to end: staff the Researcher pool -> accrue
    RP -> spend it on a track -> see the Efficiency bonus actually change output.

    The owner self-staffs because that is the only affordable way in: an NPC
    Researcher costs 75/hr, which no agent accumulates inside 48 hours, whereas
    an owner draws no wage at all. It also makes the real trade-off visible --
    every hour spent researching is an hour not producing.
    """

    buys_vehicle = False
    CASH_FLOOR = 60.0           # below this, go back to producing so we can eat

    def _rule_run_own_business(self, world, log, agent) -> bool:
        """Alternate between producing (for income) and researching (for RP).

        A pure researcher earns nothing and starves -- research has no revenue
        model of its own, so it has to be funded by production. That trade-off is
        the point of the archetype.
        """
        if not agent.owned_businesses:
            return False
        biz = world.businesses.get(agent.owned_businesses[0])
        if biz is None or biz.closed:
            agent.owned_businesses.clear()
            agent.current_job = None
            return False
        if not _goto(world, log, agent, biz.location):
            return True

        # Spend RP the moment a tier becomes affordable; Efficiency first.
        for track in ("efficiency", "quality"):
            ok, _ = A.allocate_research(world, log, agent, biz.id, track)
            if ok:
                return True

        # Broke? Haul and sell stock so we can keep eating.
        space = agent.carry_capacity(world) - agent.carried_units()
        if agent.denari < self.CASH_FLOOR and biz.inventory.get("Grain", 0) >= space > 0:
            A.collect_business_inventory(world, log, agent, biz.id, "Grain", space)
            return True

        want = "Farmhand" if agent.denari < self.CASH_FLOOR else "Researcher"
        current = agent.current_job[1] if agent.current_job else None
        if current != want:
            if agent.current_job:
                A.quit_job(world, log, agent)
            A.apply_for_job(
                world, log, agent, biz.id, want, as_researcher=(want == "Researcher")
            )
        if agent.activity.kind != "work":
            A.start_shift(world, log, agent, SHIFT_HOURS)
        return True


class Trader(StandardRules):
    """Exercises the social layer: all three chat channels, guilds, and P2P trade.

    Phase 1 only needs to prove the plumbing works and that the channels are
    correctly isolated -- real agents will do something far more interesting with
    it. This one founds a guild, invites whoever is standing next to it, talks on
    each channel, and offers its goods to co-located agents rather than dumping
    everything on the state at 0.4x.
    """

    def act(self, world, log, agent, reason):
        if self._rule_loot(world, log, agent):
            return
        if self._rule_eat(world, log, agent):
            return

        here = [
            a for a in world.agents.values()
            if a.alive and a.id != agent.id and a.location == agent.location
        ]

        # Found a guild once we can afford the social capital to run one.
        if not agent.guild and agent.denari > 200:
            A.create_guild(world, log, agent, f"{agent.name}'s Company")
            A.post_world_chat(
                world, log, agent,
                f"Founded {agent.name}'s Company at {agent.location}. Hiring and trading.",
            )
            return

        # Invite a neighbour who has no guild yet.
        if agent.is_guild_leader:
            guild = world.guilds.get(agent.guild)
            for other in here:
                if other.guild is None and other.id not in guild.invited:
                    A.invite_to_guild(world, log, agent, other.id)
                    A.post_guild_chat(
                        world, log, agent, f"Invited {other.name} at {agent.location}."
                    )
                    return

        # Accept any invite we are holding (proves invite-only actually gates).
        if not agent.guild:
            for guild in world.guilds.values():
                if agent.id in guild.invited:
                    A.accept_guild_invite(world, log, agent, guild.id)
                    return

        # Sell to a person rather than to the state, if anyone is here.
        if agent.inventory and here:
            item = next(iter(agent.inventory))
            qty = agent.inventory[item]
            # Ask above the state's 0.4x buy rate but below its 1.6x sell rate --
            # the whole point of dealing with a person instead of a storefront.
            price = round(D.base_price(item) * qty * 0.9, 2)
            buyer = max(here, key=lambda a: a.denari)
            if buyer.denari >= price:
                ok, _ = A.offer_trade(world, log, agent, buyer.id, {item: qty}, price)
                if ok:
                    A.send_direct_message(
                        world, log, agent, buyer.id,
                        f"Offered {qty}x {item} for {price:.0f}. Fair price, below store rates.",
                    )
                    return

        # Take any offer that is cheaper than buying the same goods from the state.
        for offer in world.trade_offers.values():
            if offer.buyer == agent.id and offer.status == "open":
                store_cost = sum(
                    E.npc_sell_price(i) * q for i, q in offer.items.items()
                )
                if offer.price <= store_cost and agent.denari >= offer.price:
                    A.accept_trade(world, log, agent, offer.id)
                else:
                    A.decline_trade(world, log, agent, offer.id)
                return

        super().act(world, log, agent, reason)


ARCHETYPES = {
    "standard": StandardRules(),
    "never_eats": NeverEats(),
    "overreacher": Overreacher(),
    "manufacturer": Manufacturer(),
    "research_house": ResearchHouse(),
    "trader": Trader(),
}


# Deterministic repeating mix: 50% standard, 30% manufacturer, 10% overreacher,
# 10% never_eats. Cycling rather than assigning the controls only to the first
# few agents, so the population stays varied at any size -- otherwise a 25-agent
# run is just 22 identical copies of the standard ladder.
ARCHETYPE_MIX = (
    "never_eats", "trader", "manufacturer", "trader", "overreacher",
    "standard", "research_house", "trader", "manufacturer", "standard",
)


def assign_archetypes(world: World) -> dict[str, str]:
    """Assign archetypes by spawn order, cycling through ARCHETYPE_MIX.

    Stored on the Agent, not derived from the ID -- agent IDs share a counter
    with businesses, so index arithmetic on them is wrong and silently disables
    the controls.
    """
    assignment: dict[str, str] = {}
    for i, agent in enumerate(world.agents.values()):
        agent.archetype = ARCHETYPE_MIX[i % len(ARCHETYPE_MIX)]
        assignment[agent.name] = agent.archetype
    return assignment


class RuleBasedPolicy:
    """Dispatches on the agent's assigned archetype."""

    def __init__(self, log: EventLog, seed: int = 7):
        self.log = log

    def decide(self, world: World, agent: Agent, reason: str) -> None:
        ARCHETYPES[agent.archetype].act(world, self.log, agent, reason)
