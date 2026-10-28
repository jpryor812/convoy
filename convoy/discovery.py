"""Finding people on the frontier (designer request, 2026-10-28).

"There needs to be more exploration in the early stages ... You can't sell to
people until you find them." In a world with outposts nobody knows anybody at
the start. You FIND a settler by seeing them or their land: coming within
SIGHT_M of them, of their home or of any business they own -- and they find
you at the same moment. Until then you cannot trade with them: no selling to
their bids, buying from their stock, filling their orders or taking their
delivery runs. The state's trading posts are known to everyone from the start.

Only worlds with outposts work this way; everywhere else everyone knows
everyone, exactly as before.
"""

from __future__ import annotations

import math
from typing import TYPE_CHECKING

from .events import Significance

if TYPE_CHECKING:
    from .events import EventLog
    from .state import Agent, Business, World

SIGHT_M = 400.0                # how far you can see a person or their land
EVERY_S = 300.0                # how often, in game seconds, the frontier is looked over


def _xy(world: "World", place: str) -> tuple[float, float] | None:
    from . import claims as CL
    return CL.place_xy(world, place)


def position(world: "World", agent: "Agent",
             overrides: dict[str, tuple[float, float]] | None = None) -> tuple[float, float] | None:
    """Where an agent is: a point along the road it is travelling, the
    player's own reported position (walking the 3D world), or its place."""
    if agent.in_transit:
        origin, dest, p = agent.in_transit
        a, b = _xy(world, origin), _xy(world, dest)
        if a and b:
            return a[0] + (b[0] - a[0]) * p, a[1] + (b[1] - a[1]) * p
        return a or b
    if overrides and agent.id in overrides:
        return overrides[agent.id]
    return _xy(world, agent.location)


def land(world: "World", agent: "Agent") -> list[tuple[float, float]]:
    """Every spot that shows someone lives or works there: home, claims, businesses."""
    places = {agent.home} if agent.home else set()
    places |= {c.name for c in world.claims.values() if c.owner == agent.id}
    places |= {world.businesses[b].location for b in agent.owned_businesses
               if b in world.businesses and not world.businesses[b].closed}
    return [xy for xy in (_xy(world, p) for p in places if p) if xy]


def knows(world: "World", agent: "Agent", other: str | None) -> bool:
    """Whether `agent` has found `other` (an agent id). Always true without
    outposts, for oneself, for the state, and for allies by marriage."""
    if not world.outposts or not other or other == agent.id or other == "Government":
        return True
    return other in agent.known or other in agent.allies


def business_known(world: "World", agent: "Agent", biz: "Business") -> bool:
    return biz.is_government or knows(world, agent, biz.owner)


def not_found(world: "World", who: str | None) -> str:
    a = world.agents.get(who or "")
    name = a.name if a else "them"
    return (f"you have not found {name} yet -- you can only trade with people you have met. "
            f"Explore: anyone whose land you pass within {SIGHT_M:.0f} m, you find")


def meet(world: "World", log: "EventLog", a: "Agent", b: "Agent", where: str) -> None:
    for x, y in ((a, b), (b, a)):
        if y.id not in x.known:
            x.known.append(y.id)
    log.emit(world.sim_time, "met", actor=a.id, subject=b.id, location=where,
             significance=Significance.MEDIUM, a=a.name, b=b.name,
             text=f"{a.name} and {b.name} found each other near {where}.")


def tick(world: "World", log: "EventLog",
         overrides: dict[str, tuple[float, float]] | None = None) -> int:
    """Look the frontier over: everyone within sight of someone, or of their
    land, finds them. Returns how many new meetings there were."""
    if not world.outposts:
        return 0
    people = [a for a in world.agents.values() if a.alive and a.home]
    pos = {a.id: position(world, a, overrides) for a in people}
    lands = {a.id: land(world, a) for a in people}
    near = lambda p, q: p is not None and q is not None and math.hypot(p[0] - q[0], p[1] - q[1]) <= SIGHT_M
    n = 0
    for i, a in enumerate(people):
        for b in people[i + 1:]:
            if b.id in a.known and a.id in b.known:
                continue
            pa, pb = pos[a.id], pos[b.id]
            if near(pa, pb) or any(near(pa, q) for q in lands[b.id]) or any(near(pb, q) for q in lands[a.id]):
                meet(world, log, a, b, a.location)
                n += 1
    return n
