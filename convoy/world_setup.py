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


def build_government(world: World, log: EventLog) -> None:
    """The state's own sites, standing on the state's own land.

    Government plots are recorded like anyone else's rather than left implicit,
    so `plots_free` counts them and a player cannot found a shop on ground the
    state is already standing on. They are owned by "Government", which owns no
    agent record -- so the land market cannot buy them either, which is correct:
    the backstop is not for sale.
    """
    for btype, location in GOVERNMENT_SITES.items():
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


def spawn_agents(world: World, log: EventLog, roster: list[tuple[str, str]]) -> None:
    """roster is a list of (name, model_id)."""
    for name, model in roster:
        agent = Agent(id=world.new_id("A"), name=name, model=model, location="Town")
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


def new_world(log: EventLog, roster: list[tuple[str, str]]) -> World:
    world = World()
    build_government(world, log)
    spawn_agents(world, log, roster)
    return world
