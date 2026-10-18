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


def roll(world: "World", biz: "Business") -> None:
    """Give a just-founded farm or mine its land. Sets the fields; reveals
    nothing."""
    goods = GOODS.get(biz.type)
    biz.land_rolled = True
    if not goods:
        return
    seed = (world.land_seed, biz.location, biz.id)
    if _unit(*seed, "lucky") >= BONUS_CHANCE:
        return
    lean = leanings(world, biz.location, biz.type)
    if lean and _unit(*seed, "lean") < LEAN_CHANCE:
        item = lean[int(_unit(*seed, "which") * len(lean))]
        pct = MIN_PCT + (MAX_PCT - MIN_PCT) * (0.4 + 0.6 * _unit(*seed, "pct"))   # leanings run richer
    else:
        item = goods[int(_unit(*seed, "which") * len(goods))]
        pct = MIN_PCT + (MAX_PCT - MIN_PCT) * _unit(*seed, "pct")
    biz.land_bonus_item = item
    biz.land_bonus_pct = round(pct, 3)


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
