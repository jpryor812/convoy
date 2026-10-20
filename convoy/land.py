"""Land quality: the luck in farming and mining.

Designer decision, 2026-10-17. Where a farm or mine is founded matters, and
nobody knows how until it is too late to choose again. Each farm or mine gets
hidden land when it is founded: about two times in three, ground that makes
ONE of its goods 5-25% faster -- richer soil for Dirty Water, Hide or Wheat;
a better seam of Wood, Stone, Clay, Copper, Tin or Iron.

WHERE MATTERS. Every spur has hidden leanings -- one is likelier to hold
copper, another clay -- so the luck is not pure dice: players and agents who
watch what others strike can learn which ground pays. Refineries and shops
have no land luck; they make things, they do not dig them.

HIDDEN UNTIL IT PRODUCES. The bonus applies from the start (the ground is what
it is) but is REVEALED -- to the owner's observation, on the map, in the
building's card -- when the business makes its first unit. Then the land shows
it: more wells, more cows, a thicker field, heaps of copper-coloured ore.

Deterministic per game: `world.land_seed` is drawn when the world is made, so
a reloaded game keeps its land, and another game has different land.
"""

from __future__ import annotations

import hashlib
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .state import Business, World

FARM_GOODS = ("Dirty Water", "Hide", "Wheat")
MINE_GOODS = ("Wood", "Stone", "Clay", "Copper Ore", "Tin Ore", "Iron Ore")
GOODS = {"Farm": FARM_GOODS, "Mining Operation": MINE_GOODS}
BONUS_CHANCE = 0.65         # share of founded farms and mines on good ground
LEAN_CHANCE = 0.6           # of those, share whose bonus is the spur's leaning
MIN_PCT, MAX_PCT = 0.05, 0.25


def _unit(*parts) -> float:
    """A number in [0, 1) from the parts, the same every time."""
    h = hashlib.sha256("|".join(str(p) for p in parts).encode()).digest()
    return int.from_bytes(h[:8], "big") / 2 ** 64


def leanings(world: "World", place: str, kind: str) -> tuple[str, ...]:
    """What a spur's ground tends toward, for farms or for mines. Hidden."""
    goods = GOODS.get(kind, ())
    if not goods:
        return ()
    first = goods[int(_unit(world.land_seed, place, kind, "lean") * len(goods))]
    if kind == "Mining Operation":
        rest = [g for g in goods if g != first]
        return (first, rest[int(_unit(world.land_seed, place, kind, "lean2") * len(rest))])
    return (first,)


# GEOGRAPHY (designer request, 2026-10-18): land near water farms well, land
# near the mountains holds rich seams -- and good ground comes in POCKETS. Every
# farm or mine at one place shares that ground's luck (with a little variation),
# so the first rich strike at a place says its neighbours are likely rich too:
# a reason to buy the plots next door, and to go looking.
FARM_REACH = 700.0             # metres from water at which a farm gains nothing
MINE_REACH = 900.0             # metres from a mountainside at which a mine gains nothing
FARM_WATER_GOODS = ("Dirty Water", "Wheat")
MINE_MOUNTAIN_GOODS = ("Copper Ore", "Tin Ore", "Iron Ore", "Stone")


POCKET_M = 260.0               # rich ground comes in patches this wide


def coords(world: "World", place: str) -> tuple[float, float] | None:
    """Where a place is on the map: a claim's own spot, or a named place's middle."""
    c = world.claims.get(place)
    if c is not None:
        return c.x, c.y
    from . import layout as L
    p = L.places_cached(list(world.cities)).get(place)
    return (p.center.x, p.center.y) if p is not None else None


def affinity(world: "World", place: str, kind: str) -> float:
    """0..1: how close this place is to what its kind of business wants."""
    from . import layout as L
    xy = coords(world, place)
    if xy is None:
        return 0.0
    x, y = xy
    if kind == "Farm":
        d = abs(y - L.river_axis())
        for bx in L.border_rivers(list(world.cities)):
            d = min(d, abs(x - bx))
        return max(0.0, min(1.0, 1.0 - d / FARM_REACH))
    if kind == "Mining Operation":
        d = min(((x - m["x"]) ** 2 + (y - m["y"]) ** 2) ** 0.5 - m["r"] for m in L.mountains(list(world.cities)))
        return max(0.0, min(1.0, 1.0 - max(0.0, d) / MINE_REACH))
    return 0.0


def pocket(world: "World", place: str, kind: str) -> tuple[str, float] | None:
    """The luck of the ground at a place, for farms or mines: (good, pct) or None.
    The same for every business there -- that is what makes it a pocket."""
    goods = GOODS.get(kind)
    if not goods:
        return None
    aff = affinity(world, place, kind)
    # THE PATCH, not the place: everything within one POCKET_M square of the
    # map shares its luck -- a claim beside a rich strike is likely rich too.
    xy = coords(world, place)
    patch = (int(xy[0] // POCKET_M), int(xy[1] // POCKET_M)) if xy else place
    seed = (world.land_seed, patch, kind, "pocket")
    if _unit(*seed, "lucky") >= 0.30 + 0.60 * aff:
        return None
    favoured = FARM_WATER_GOODS if kind == "Farm" else MINE_MOUNTAIN_GOODS
    pool = favoured if _unit(*seed, "fav") < 0.35 + 0.55 * aff else goods
    lean = leanings(world, place, kind)
    if lean and _unit(*seed, "lean") < LEAN_CHANCE * 0.5:
        pool = lean
    item = pool[int(_unit(*seed, "which") * len(pool))]
    pct = MIN_PCT + (MAX_PCT - MIN_PCT) * (0.25 + 0.75 * aff * (0.5 + 0.5 * _unit(*seed, "pct")))
    return item, pct


def roll(world: "World", biz: "Business") -> None:
    """Give a just-founded farm or mine its land: the pocket at its place, a
    little richer or poorer for this patch. Sets the fields; reveals nothing."""
    biz.land_rolled = True
    found = pocket(world, biz.location, biz.type)
    if found is None:
        return
    item, pct = found
    pct += (_unit(world.land_seed, biz.id, "patch") - 0.5) * 0.04
    biz.land_bonus_item = item
    biz.land_bonus_pct = round(max(MIN_PCT, min(MAX_PCT, pct)), 3)


def multiplier(biz: "Business", output: str | None) -> float:
    """How much faster this business makes `output` for its ground."""
    return 1.0 + biz.land_bonus_pct if output and output == biz.land_bonus_item else 1.0


def describe(biz: "Business") -> str | None:
    """What the owner knows about the ground, or None for businesses with none."""
    if biz.type not in GOODS:
        return None
    if not biz.land_revealed:
        return "Unknown until it first produces: the ground may favour one of its goods."
    if not biz.land_bonus_item:
        return "Ordinary ground: no bonus."
    return (f"RICH GROUND: makes {biz.land_bonus_item} {biz.land_bonus_pct:.0%} faster. "
            f"Making {biz.land_bonus_item} here pays best.")
