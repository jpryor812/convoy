"""BORDERS AND THE REFINERY DISTRICT (designer, 2026-11-01).

"I like the idea of building borders around your buildings ... maybe you
build borders around your home and farms/mines, but refineries are in their
separate section of the map? And initially there is one government owned one
but space to buy more. If you do buy a refinery and put it there though, it
won't be in your borders, and you have to likely hire people to protect it."

  * TERRITORY: a house's land is the hex of its home and of every claim it
    holds, and the ring of six round each (convoy/hexes.py). Where two houses'
    rings meet the hex is the first claimer's. Nobody claims inside another's
    borders (claims.check).
  * THE REFINERY DISTRICT: each city's state refinery stands in one -- its
    place and the hexes within two of it, open land nobody may claim. With
    outposts a new refinery is founded only there, on the place's plots for
    sale (actions.start_business), so it stands outside its owner's borders,
    and gangs find it the easier mark (robbery.hourly_chance).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from . import claims as CL
from . import hexes as H

if TYPE_CHECKING:
    from .state import World

RING = 1                       # your land and the hexes round it
DISTRICT_RING = 2              # the district: the refinery's hex and two rings
OUTSIDE_BORDERS = 1.5          # gangs: a building outside its owner's borders


_OWNERS: dict[tuple, dict[str, str]] = {}


def owners(world: "World") -> dict[str, str]:
    """Hex key -> the house whose territory it is. First claimer wins."""
    tag = (id(world), len(world.claims), tuple(sorted(a.home for a in world.agents.values() if a.home)))
    t = _OWNERS.get(tag)
    if t is not None:
        return t
    t = {}
    for c in sorted(world.claims.values(), key=lambda c: (c.created_at, c.name)):
        if not c.owner:
            continue
        for h in H.ring(H.to_hex(c.x, c.y), RING):
            t.setdefault(H.key(h), c.owner)
    _OWNERS.clear()
    _OWNERS[tag] = t
    return t


def owner_at(world: "World", x: float, y: float) -> str:
    return owners(world).get(H.key(H.to_hex(x, y)), "")


def inside(world: "World", owner: str, x: float, y: float) -> bool:
    return owner_at(world, x, y) == owner


# -- the refinery districts --------------------------------------------------

def district_places(world: "World") -> list[str]:
    """The state refinery's place in each city: where the districts are."""
    from . import world_map as M
    return [M.CITIES[city].locations[0] for city in world.cities if city in M.CITIES]


_DISTRICTS: dict[tuple, dict[str, str]] = {}


def districts(world: "World") -> dict[str, str]:
    """Hex key -> the district's place, for every hex of every district."""
    tag = (id(world), tuple(world.cities))
    t = _DISTRICTS.get(tag)
    if t is None:
        t = {}
        for p in district_places(world):
            xy = CL.place_xy(world, p)
            if xy:
                for h in H.ring(H.to_hex(*xy), DISTRICT_RING):
                    t.setdefault(H.key(h), p)
        _DISTRICTS.clear()
        _DISTRICTS[tag] = t
    return t


def district_at(world: "World", x: float, y: float) -> str:
    return districts(world).get(H.key(H.to_hex(x, y)), "")


def nearest_district(world: "World", x: float, y: float) -> str:
    import math
    best, bd = "", float("inf")
    for p in district_places(world):
        xy = CL.place_xy(world, p)
        if xy and math.dist(xy, (x, y)) < bd:
            best, bd = p, math.dist(xy, (x, y))
    return best


def house_name(world: "World", owner: str) -> str:
    a = world.agents.get(owner)
    return (a.house or a.name) if a else "someone"
