"""THE HEX GRID (designer, 2026-11-01): "move one space at a time, and each
movement drains energy ... This makes it kind of turn based strategy but in a
continuous world."

Pointy-top axial hexes laid over the map in map metres, 250 m flat to flat
(so a day's ten moves is about two and a half kilometres). The same arithmetic
is in game3d/hexes.js; tests/test_hexes.py and tests/test_hexes.mjs check that
the two give the same answers.

What a hex IS -- open ground, water, a mountain, off the map -- is `terrain`,
from what the server already knows: the rivers, the ranges, the roads (a road
across water is a ford) and the map's edge.
"""

from __future__ import annotations

import heapq
import math
from typing import TYPE_CHECKING, Callable, Iterable

if TYPE_CHECKING:
    from .state import World

ACROSS_M = 250.0                         # flat side to flat side
R = ACROSS_M / math.sqrt(3.0)            # centre to corner
SQRT3 = math.sqrt(3.0)
DIRS = [(1, 0), (1, -1), (0, -1), (-1, 0), (-1, 1), (0, 1)]

Hex = tuple[int, int]


def key(h: Hex) -> str:
    return f"{h[0]},{h[1]}"


def parse(k: str) -> Hex:
    q, r = k.split(",")
    return int(q), int(r)


def centre(h: Hex) -> tuple[float, float]:
    q, r = h
    return R * SQRT3 * (q + r / 2.0), R * 1.5 * r


def _round(qf: float, rf: float) -> Hex:
    sf = -qf - rf
    q, r, s = round(qf), round(rf), round(sf)
    dq, dr, ds = abs(q - qf), abs(r - rf), abs(s - sf)
    if dq > dr and dq > ds:
        q = -r - s
    elif dr > ds:
        r = -q - s
    return int(q), int(r)


def to_hex(x: float, y: float) -> Hex:
    qf = (SQRT3 / 3.0 * x - y / 3.0) / R
    rf = (2.0 / 3.0 * y) / R
    return _round(qf, rf)


def neighbours(h: Hex) -> list[Hex]:
    return [(h[0] + dq, h[1] + dr) for dq, dr in DIRS]


def distance(a: Hex, b: Hex) -> int:
    dq, dr = a[0] - b[0], a[1] - b[1]
    return int((abs(dq) + abs(dr) + abs(dq + dr)) // 2)


def ring(h: Hex, radius: int) -> list[Hex]:
    """Every hex within `radius` of `h`, `h` included."""
    out = []
    for dq in range(-radius, radius + 1):
        for dr in range(max(-radius, -dq - radius), min(radius, -dq + radius) + 1):
            out.append((h[0] + dq, h[1] + dr))
    return out


def path(a: Hex, b: Hex, cost: Callable[[Hex], float | None], limit: int = 4000) -> list[Hex] | None:
    """The cheapest way from `a` to `b`, `a` left out. `cost(h)` is what
    stepping onto `h` costs, or None where you cannot go."""
    if a == b:
        return []
    seen = {a: 0.0}
    came: dict[Hex, Hex] = {}
    todo = [(distance(a, b), 0, a)]
    n = 0
    while todo and n < limit:
        _, _, h = heapq.heappop(todo)
        if h == b:
            out = [b]
            while out[-1] in came and came[out[-1]] != a:
                out.append(came[out[-1]])
            return list(reversed(out))
        n += 1
        for nb in neighbours(h):
            c = cost(nb)
            if c is None:
                continue
            g = seen[h] + c
            if g < seen.get(nb, float("inf")):
                seen[nb] = g
                came[nb] = h
                heapq.heappush(todo, (g + distance(nb, b), n, nb))
    return None


# -- what a hex is ----------------------------------------------------------------

_TERRAIN: dict[tuple, dict[str, str]] = {}


def _road_points(world: "World") -> Iterable[tuple[float, float]]:
    from . import layout as L
    cities = list(world.cities)
    lines = [[(p.x, p.y) for p in road] for road in L.main_roads(cities)]
    lines += [[(p.x, p.y) for p in road] for road in L.intercity_roads(cities)]
    lines += [[(p.x, p.y) for p in pl.path] for pl in L.places_cached(cities).values() if pl.path]
    lines += [list(map(tuple, c.road)) for c in world.claims.values() if c.road]
    for line in lines:
        for (ax, ay), (bx, by) in zip(line, line[1:]):
            n = max(1, int(math.hypot(bx - ax, by - ay) // 40))
            for i in range(n + 1):
                yield ax + (bx - ax) * i / n, ay + (by - ay) * i / n


def _table(world: "World") -> dict[str, str]:
    """Hex key -> "road" for hexes a road runs through; cached per map."""
    tag = (id(world), tuple(world.cities), sum(1 for c in world.claims.values() if c.road))
    t = _TERRAIN.get(tag)
    if t is None:
        t = {key(to_hex(x, y)): "road" for x, y in _road_points(world)}
        _TERRAIN.clear()
        _TERRAIN[tag] = t
    return t


_KIND: dict[str, str] = {}
_KIND_TAG: list = [None]


def terrain(world: "World", h: Hex) -> str:
    """"open", "road", "mountain", "water" (impassable unless a road crosses
    it: a ford, which is "road") or "edge" (off the map). Remembered per map:
    the status asks it of every found hex, every poll."""
    tag = (id(world), tuple(world.cities), sum(1 for c in world.claims.values() if c.road))
    if _KIND_TAG[0] != tag:
        _KIND.clear()
        _KIND_TAG[0] = tag
    k = key(h)
    if k not in _KIND:
        _KIND[k] = _terrain(world, h)
    return _KIND[k]


def _terrain(world: "World", h: Hex) -> str:
    from . import layout as L
    x, y = centre(h)
    cities = list(world.cities)
    minx, miny, maxx, maxy = L.bounds(L.places_cached(cities))
    pad = L.MOUNTAIN_OFFSET + 250.0
    if not (minx - pad <= x <= maxx + pad and miny - pad <= y <= maxy + pad):
        return "edge"
    road = _table(world).get(key(h)) == "road"
    wet = L.in_river(y) or any(abs(x - a) < L.BORDER_RIVER_HALF_WIDTH for a in L.border_rivers(cities))
    if wet:
        return "road" if road else "water"
    for m in L.mountains(cities):
        if math.hypot(x - m["x"], y - m["y"]) < m["r"] * 2.2:
            return "mountain"
    return "road" if road else "open"


def step_cost(world: "World", h: Hex) -> int | None:
    """Energy to step onto `h`, or None where you cannot go."""
    t = terrain(world, h)
    return None if t in ("water", "edge") else 2 if t == "mountain" else 1
