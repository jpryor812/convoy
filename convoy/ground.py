"""The ground wears out and the air fouls: depletion and pollution.

Designer request, 2026-10-18: "build in depletion ... farms should deplete too.
And that leads to needing more land and worrying about inefficient production.
We can have upgrades to prolong resource supply in that land." And pollution
"created by refineries that weaken farm production and slow mining output and
refinery production because workers can't work as well in polluted
environments, also happens through fast production and can be mitigated by
upgrades."

DEPLETION. Every farm and mine has `richness`, 1.0 when founded.

  * A MINE's seam is finite. Working it draws it down -- a lone hand works a
    seam out in about MINE_LIFE_H game hours -- and it never comes back. Output
    holds until half the seam is gone, then fades, and at nothing the mine is
    worked out: dig somewhere else, or sink a deeper shaft.
  * A FARM's soil tires as it is farmed (about FARM_WEAR_H hours of one hand to
    exhaust it) and RECOVERS while it rests -- nothing being grown, or nobody
    working it -- at FALLOW_PER_H. Tired soil still grows, down to FARM_FLOOR.

  Both are counted in hours of a worker at base pace, not in units, so Dirty
  Water (fast) and Wheat (slow) tire a field at the same rate per hour worked.
  More hands, better tools, richer land: faster output and faster wear.

POLLUTION. Everything that makes things gives off `smoke` for each hour of
work it does -- a refinery the most, a mine some, a farm a little -- so a
business running fast fouls the air faster. Smoke thins over about
SMOKE_HALF_LIFE_H hours. The air at a place is the smoke of everything within
SMOKE_RANGE_M, nearer counting more, and it slows the work there: crops most,
then miners and refinery hands.

UPGRADES (projects, convoy/progress.py) push back: crop rotation and hedgerows
on a farm, timbered and deeper shafts in a mine, a tall chimney on anything
that smokes. The state's own sites neither wear nor smoke: they are the market
floor, not players.
"""

from __future__ import annotations

import math
from typing import TYPE_CHECKING, Any

from . import data as D

if TYPE_CHECKING:
    from .events import EventLog
    from .state import Business, World

MINE_LIFE_H = 72.0             # worker-hours at base pace to work a seam out
FARM_WEAR_H = 48.0             # ... to tire a field to nothing
FALLOW_PER_H = 1.0 / 24.0      # a resting field recovers fully in a day
FARM_FLOOR = 0.35              # tired soil still grows this share
FARM_FULL_ABOVE = 0.6          # ... and full speed down to this richness
MINE_FULL_ABOVE = 0.5          # a seam yields fully until half is gone
MINE_FLOOR = 0.2               # ... then fades to this just before it is spent

# Smoke a business gives off per worker-hour of output, by type.
EMIT = {"Refinery": 1.0, "Mining Operation": 0.3, "Farm": 0.05}
EMIT_OTHER = 0.15              # taverns, smithies, stores
SMOKE_HALF_LIFE_H = 8.0
SMOKE_RANGE_M = 600.0
SMOKE_SCALE = 30.0             # smoke for air at 1 - 1/e (63%) foul
# How much foul air slows work, at its worst.
HARM = {"Farm": 0.6, "Mining Operation": 0.3, "Refinery": 0.3}
HARM_OTHER = 0.2


def wears(biz: "Business") -> bool:
    return biz.type in D.EXTRACTION_BUSINESS_TYPES and not biz.is_government


def _imp(biz: "Business", kind: str) -> int:
    return biz.improvements.get(kind, 0)


def spent(biz: "Business") -> bool:
    return biz.type == "Mining Operation" and wears(biz) and biz.richness <= 0.0


def depletion_multiplier(biz: "Business") -> float:
    if not wears(biz):
        return 1.0
    r = max(0.0, biz.richness)
    if biz.type == "Mining Operation":
        if r <= 0.0:
            return 0.0
        return 1.0 if r >= MINE_FULL_ABOVE else MINE_FLOOR + (1.0 - MINE_FLOOR) * r / MINE_FULL_ABOVE
    return 1.0 if r >= FARM_FULL_ABOVE else FARM_FLOOR + (1.0 - FARM_FLOOR) * r / FARM_FULL_ABOVE


# -- the air ------------------------------------------------------------------

_cache: dict[str, Any] = {"key": None, "air": {}}


def _emitters(world: "World") -> list[tuple[float, float, float]]:
    from . import land as LAND
    out = []
    for b in world.businesses.values():
        if b.closed or b.smoke < 0.05:
            continue
        xy = LAND.coords(world, b.location)
        if xy is not None:
            out.append((xy[0], xy[1], b.smoke))
    return out


def air(world: "World", place: str) -> float:
    """0..1: how foul the air is at a place."""
    key = (id(world), round(world.sim_time, 3))
    if _cache["key"] != key:
        _cache["key"], _cache["air"], _cache["src"] = key, {}, _emitters(world)
    if place in _cache["air"]:
        return _cache["air"][place]
    from . import land as LAND
    xy = LAND.coords(world, place)
    total = 0.0
    if xy is not None:
        for x, y, smoke in _cache["src"]:
            d = math.hypot(x - xy[0], y - xy[1])
            if d < SMOKE_RANGE_M:
                total += smoke * (1.0 - d / SMOKE_RANGE_M)
    level = 1.0 - math.exp(-total / SMOKE_SCALE)
    _cache["air"][place] = level
    return level


def air_multiplier(world: "World", biz: "Business") -> float:
    if biz.is_government:
        return 1.0
    harm = HARM.get(biz.type, HARM_OTHER) * (0.5 ** _imp(biz, "Hedgerows"))
    return 1.0 - harm * air(world, biz.location)


def multiplier(world: "World", biz: "Business") -> float:
    """Everything the ground and the air do to this business's pace."""
    return depletion_multiplier(biz) * air_multiplier(world, biz)


# -- the engine's hooks -------------------------------------------------------

def worked(world: "World", log: "EventLog", biz: "Business", output: str, units: int) -> None:
    """Units were just made: wear the ground, foul the air."""
    if biz.is_government or units <= 0:
        return
    hours = units / max(1e-6, D.production_rate_hr(output))    # worker-hours at base pace
    emit = EMIT.get(biz.type, EMIT_OTHER) * (0.6 ** _imp(biz, "Tall chimney"))
    biz.smoke += emit * hours
    if not wears(biz):
        return
    before = biz.richness
    if biz.type == "Mining Operation":
        biz.richness -= hours / MINE_LIFE_H * (0.7 ** _imp(biz, "Timbered shafts"))
    else:
        biz.richness -= hours / FARM_WEAR_H * (0.65 ** _imp(biz, "Crop rotation"))
    biz.richness = max(0.0, biz.richness)
    from .events import Significance
    if biz.type == "Mining Operation" and before > 0 and biz.richness <= 0:
        log.emit(world.sim_time, "seam_spent", actor=biz.owner, subject=biz.id, location=biz.location,
                 significance=Significance.MEDIUM, business=biz.name)
    elif before >= 0.25 > biz.richness:
        log.emit(world.sim_time, "ground_tiring", actor=biz.owner, subject=biz.id, location=biz.location,
                 significance=Significance.MEDIUM, business=biz.name, richness=round(biz.richness, 2))


def tick(world: "World", hours: float) -> None:
    """Smoke thins; fields at rest recover."""
    decay = 0.5 ** (hours / SMOKE_HALF_LIFE_H)
    for b in world.businesses.values():
        if b.smoke:
            b.smoke = b.smoke * decay if b.smoke > 0.01 else 0.0
        if b.type == "Farm" and wears(b) and b.richness < 1.0 and not b.closed:
            resting = (not b.active_production or b.production_blocked
                       or b.active_headcount(world) == 0)
            if resting:
                b.richness = min(1.0, b.richness + FALLOW_PER_H * hours * (2.0 if _imp(b, "Manure pits") else 1.0))


def improved(biz: "Business", kind: str) -> None:
    """A finished project that changes the ground."""
    if kind == "Deeper shaft":
        biz.richness = min(1.0, biz.richness + 0.5)
    elif kind == "Manure pits":
        biz.richness = min(1.0, biz.richness + 0.25)


# -- what the owner sees --------------------------------------------------------

def view(world: "World", biz: "Business") -> dict[str, Any]:
    out: dict[str, Any] = {}
    if wears(biz):
        out["ground"] = {"kind": "seam" if biz.type == "Mining Operation" else "soil",
                         "left": round(biz.richness, 3), "pace": round(depletion_multiplier(biz), 3),
                         "spent": spent(biz)}
    level = air(world, biz.location)
    out["air"] = {"foul": round(level, 3), "pace": round(air_multiplier(world, biz), 3),
                  "smoke": round(biz.smoke, 2)}
    return out


def describe(world: "World", biz: "Business") -> str | None:
    """One line for an agent's view, or None when nothing is worth saying."""
    bits = []
    if wears(biz):
        if spent(biz):
            bits.append("the seam is WORKED OUT: nothing more comes out of it (sink a Deeper shaft, or dig elsewhere)")
        elif biz.richness < 0.9:
            what = "seam" if biz.type == "Mining Operation" else "soil"
            pace = depletion_multiplier(biz)
            bits.append(f"{what} {biz.richness:.0%} left" + (f", working {1 - pace:.0%} slower" if pace < 0.995 else "")
                        + ("; it recovers while the field rests" if biz.type == "Farm" else "; it does not come back"))
    level = air(world, biz.location)
    if level >= 0.05:
        bits.append(f"air {level:.0%} foul: work here {1 - air_multiplier(world, biz):.0%} slower")
    return "; ".join(bits) or None
