"""Claiming open land anywhere on the map, joined to the roads by a dirt road.

Designer request, 2026-10-18: "all land on the map can be purchased if there
are four open squares there. Any land is fair game so that exploration becomes
a bigger part of the game ... to have a building that produces goods or
receives goods, it must be connected to a road system."

A CLAIM is four plots on open grass -- not river, not mountainside, clear of
every road and every other place -- made into a place of its own. It is joined
to the nearest road by a dirt road, laid at once and paid for by the claimant
at ROAD_COST_PER_M; its travel time is the distance at a track's pace. The
plots are the world's until somebody buys or builds on them, exactly as at any
other place. See `world_map.register_claims` for how it becomes a place.
"""

from __future__ import annotations

import math
from typing import TYPE_CHECKING

from . import layout as L
from . import world_map as M
from .events import Significance
from .state import Claim

if TYPE_CHECKING:
    from .events import EventLog
    from .state import Agent, World

ROAD_COST_PER_M = 0.12         # coins per metre of dirt road
TRACK_SPEED = 4.0              # metres a second along a track, at Medium
MIN_FROM_PLACE = 110.0         # metres from a named place's middle
MIN_FROM_CLAIM = 85.0          # two squares: neighbouring claims may touch, not overlap
MAX_ROAD_M = 1200.0
SUFFIX = {"Farm": "Fields", "Mining Operation": "Diggings", "Refinery": "Works"}


def _roads(world: "World") -> list[list[tuple[float, float]]]:
    cities = list(world.cities)
    lines = [[(p.x, p.y) for p in road] for road in L.main_roads(cities)]
    lines += [[(p.x, p.y) for p in road] for road in L.intercity_roads(cities)]
    lines += [[(p.x, p.y) for p in pl.path] for pl in L.places_cached(cities).values() if pl.path]
    lines += [[tuple(pt) for pt in c.road] for c in world.claims.values()]
    return [ln for ln in lines if len(ln) >= 2]


def _nearest_on(px: float, py: float, a, b) -> tuple[float, float, float]:
    ax, ay = a; bx, by = b
    dx, dy = bx - ax, by - ay
    t = 0.0 if dx == dy == 0 else max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / (dx * dx + dy * dy)))
    qx, qy = ax + t * dx, ay + t * dy
    return math.hypot(px - qx, py - qy), qx, qy


def nearest_road(world: "World", x: float, y: float) -> tuple[float, float, float]:
    """(distance, x, y) of the nearest point on any road or track."""
    best = (float("inf"), x, y)
    for line in _roads(world):
        for a, b in zip(line, line[1:]):
            d = _nearest_on(x, y, a, b)
            if d[0] < best[0]:
                best = d
    return best


def check(world: "World", x: float, y: float) -> str:
    """Why a claim cannot be made here, or "" if it can."""
    cities = list(world.cities)
    places = L.places_cached(cities)
    minx, miny, maxx, maxy = L.bounds(places)
    if not (minx - 250 <= x <= maxx + 250 and miny - 250 <= y <= maxy + 250):
        return "that is beyond the edge of the map"
    if abs(y - L.river_axis()) < L.RIVER_HALF_WIDTH + 30:
        return "that is in the river"
    for bx in L.border_rivers(cities):
        if abs(x - bx) < L.BORDER_RIVER_HALF_WIDTH + 30:
            return "that is in the river"
    for m in L.mountains(cities):
        if math.hypot(x - m["x"], y - m["y"]) < m["r"] + 25:
            return "that is on the mountainside"
    for p in places.values():
        if math.hypot(x - p.center.x, y - p.center.y) < MIN_FROM_PLACE:
            return f"that is part of {p.name}"
    for c in world.claims.values():
        if math.hypot(x - c.x, y - c.y) < MIN_FROM_CLAIM:
            return f"that is part of {c.name}"
    d, _, _ = nearest_road(world, x, y)
    if d < 30:
        return "that is on a road"
    if d > MAX_ROAD_M:
        return f"too far from any road ({d:.0f} m; at most {MAX_ROAD_M:.0f})"
    return ""


def quote(world: "World", x: float, y: float) -> dict:
    """What a claim here would cost and where its road would come from."""
    d, rx, ry = nearest_road(world, x, y)
    return {"road_m": round(d), "road_cost": round(d * ROAD_COST_PER_M, 2), "from": [rx, ry],
            "why_not": check(world, x, y)}


def _nearest_junction(world: "World", x: float, y: float) -> str:
    places = L.places_cached(list(world.cities))
    juncs = [p for p in places.values() if p.kind != "spur"]
    return min(juncs, key=lambda p: math.hypot(x - p.center.x, y - p.center.y)).name


def _name(world: "World", agent: "Agent", purpose: str) -> str:
    stem = (agent.house or "House Newcomer").replace("House ", "")
    suffix = SUFFIX.get(purpose, "Steading")
    n = 1
    while True:
        name = f"{stem} {suffix}" + ("" if n == 1 else f" {n}")
        if name not in M.EVERY_PLACE and name not in world.claims:
            return name
        n += 1


def claim(world: "World", log: "EventLog", agent: "Agent", x: float, y: float,
          purpose: str = "") -> tuple[bool, str, Claim | None]:
    """Make a claim at (x, y): lay and pay for its road; its four plots are
    then for sale like any others. Returns (ok, message, claim)."""
    why = check(world, x, y)
    if why:
        return False, why, None
    d, rx, ry = nearest_road(world, x, y)
    cost = round(d * ROAD_COST_PER_M, 2)
    if agent.denari < cost:
        return False, f"the road here costs {cost:.0f} ({d:.0f} m); you have {agent.denari:.0f}", None
    junction = _nearest_junction(world, x, y)
    jp = L.places_cached(list(world.cities))[junction].center
    seconds = (math.hypot(x - jp.x, y - jp.y)) / TRACK_SPEED
    c = Claim(name=_name(world, agent, purpose), city=M.city_of(junction), junction=junction,
              x=round(x, 1), y=round(y, 1), road=[[round(rx, 1), round(ry, 1)], [round(x, 1), round(y, 1)]],
              road_m=round(d, 1), seconds=round(seconds, 1), owner=agent.id, created_at=world.sim_time)
    agent.denari -= cost
    world.claims[c.name] = c
    M.register_claims(world.claims.values())
    log.emit(world.sim_time, "land_claimed", actor=agent.id, location=c.name,
             significance=Significance.MEDIUM, x=c.x, y=c.y, road_m=c.road_m, cost=cost,
             city=c.city)
    return True, (f"Claimed {c.name}: a dirt road of {d:.0f} m from the nearest road, for {cost:.0f}. "
                  f"Its four plots are yours to buy or build on."), c
