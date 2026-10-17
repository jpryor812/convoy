"""World construction: the government businesses that exist from hour zero, and
the starting agent population.

Per the World tab, one government-owned business of every type exists from hour
zero, always fully staffed regardless of real hires. They are the hour-zero
employer and convoy organizer -- the bootstrap answer -- and act as the market
floor (buying at 0.4x base) and ceiling (selling at the Assumptions markups).
"""

from __future__ import annotations

from . import data as D
from .events import EventLog
from .state import Agent, Business, Plot, World

# Placement now comes from the world design: the state's mine and farm sit on the
# two spurs closest to the refineries, so its own supply chain is short and
# everyone else has to beat it on price or on distance to the market.
from . import world_map as M
from .world_map import (  # noqa: F401
    GOVERNMENT_SITES,
    PLOT_CONSUMING_BUSINESSES,
    SITE_BASE_PLOTS,
)

# What each government production site makes by default.
GOVERNMENT_DEFAULT_OUTPUT: dict[str, str] = {
    "Mining Operation": "Copper Ore",
    "Farm": "Wheat",
    "Refinery": "Charcoal",
}


def build_government(world: World, log: EventLog, city: str | None = None) -> None:
    """The state's own sites, standing on the state's own land.

    Government plots are recorded like anyone else's rather than left implicit,
    so `plots_free` counts them and a player cannot found a shop on ground the
    state is already standing on. They are owned by "Government", which owns no
    agent record -- so the land market cannot buy them either, which is correct:
    the backstop is not for sale.

    ONE FULL SET PER CITY. Both sides start with the same backstop, the same
    market floor and the same market ceiling, or the contest measures the state
    rather than the citizens. When the state withdraws it withdraws from
    everywhere at once, for the same reason.
    """
    for btype, location in M.government_sites_for(city or world.cities[0]).items():
        biz = Business(
            id=world.new_id("G"),
            type=btype,
            name=f"Government {btype}",
            owner="Government",
            location=location,
            cash=0.0,
            active_production=GOVERNMENT_DEFAULT_OUTPUT.get(btype),
            plots=D.SITE_BASE_PLOTS,
        )
        world.businesses[biz.id] = biz
        for _ in range(D.SITE_BASE_PLOTS):
            plot = Plot(
                id=world.new_id("L"), location=location, owner="Government",
                business=biz.id, developed=True,
            )
            world.plots[plot.id] = plot


def spawn_agents(
    world: World, log: EventLog, roster: list[tuple[str, str]],
    city: str | None = None,
) -> None:
    """roster is a list of (name, model_id). Everyone starts in their market."""
    home = city or world.cities[0]
    for name, model in roster:
        agent = Agent(
            id=world.new_id("A"), name=name, model=model,
            city=home, location=M.market_of(home),
        )
        world.agents[agent.id] = agent


def rule_based_roster(n: int) -> list[tuple[str, str]]:
    return [(f"Agent-{i + 1:02d}", "rule-based") for i in range(n)]


def full_roster() -> list[tuple[str, str]]:
    """The Phase 3 population: 75 agents, 15 per model."""
    roster: list[tuple[str, str]] = []
    for slot in D.MODEL_ROSTER:
        short = slot.openrouter_id.split("/")[-1]
        for i in range(slot.agents):
            roster.append((f"{short}-{i + 1:02d}", slot.openrouter_id))
    return roster


def new_world(
    log: EventLog,
    roster: list[tuple[str, str]],
    rosters: dict[str, list[tuple[str, str]]] | None = None,
    *,
    government: bool = True,
) -> World:
    """A one-city world from `roster`, or a contest from `rosters`.

    `rosters` maps city key -> that city's population. Passing it is what turns
    the simulation into a contest: each city gets its own valley, its own full
    set of government branches and its own twenty people, and nothing crosses
    between them but the scoreboard.

    EVERY GOVERNMENT FIRST, THEN EVERY POPULATION. `World.new_id` runs one
    sequence across businesses, plots and agents alike, so interleaving the two
    passes would scatter agent ids through the land register -- A0046 next to
    A0092 with seventy plot ids between them. Seating the state everywhere
    first means each city's people take one contiguous block of ids, which is
    what makes a raw event log readable without a lookup table. Ids are the only
    handle a log line has on a person.
    """
    world = World()
    if not government:
        _no_state(world)
    if rosters:
        world.cities = list(rosters)
        if government:
            for city in world.cities:
                build_government(world, log, city)
        for city, people in rosters.items():
            spawn_agents(world, log, people, city)
    else:
        if government:
            build_government(world, log)
        spawn_agents(world, log, roster)
    if not government:
        # Fed for a day, because nothing sells food until a citizen makes it.
        for agent in world.agents.values():
            agent.last_meal_window = D.START_FED_HOURS_NO_STATE
    return world


def _no_state(world: World) -> None:
    """A valley with no government: no tax of any kind is collected, because
    there is nobody to collect it. Land bought from nobody is money that simply
    leaves the economy; after that, land changes hands between citizens."""
    world.no_state = True
    g = world.government
    g.wage_tax = g.sales_tax = g.property_tax = g.road_tax = 0.0
