"""WILD HERDS (designer, 2026-11-01): "in civilization it is exciting when you
find plots of land with goods on it, like wild horses, or sheep, or cattle
... Rather than just be able to build goods like Hide because you have a
farm, should it not be possible to build goods like hide ... until you find
land with wild cattle?" -- and "you can find a horse rather than buy one".

  * Herds are put down once per world, from its land seed, on open hexes away
    from every place: CATTLE (about one in thirty open hexes) and HORSES
    (about one in forty-five).
  * HIDE needs cattle: a farm makes Hide only with a cattle herd on its land
    -- its hex or the ring round it -- and, for the player, a herd they have
    found on the map (actions.set_production).
  * HORSES are caught: stand on a horse herd's hex and spend two hours, and
    one is yours to ride (journey.catch). A herd grows back a head every
    three days.
"""

from __future__ import annotations

import random
from typing import TYPE_CHECKING, Any

from . import hexes as H
from .events import Significance
from .state import Herd

if TYPE_CHECKING:
    from .events import EventLog
    from .state import Agent, World

CATTLE_EVERY = 30              # open hexes per cattle herd
HORSES_EVERY = 45              # ... per horse herd
CATTLE_SIZE = (4, 7)
HORSE_SIZE = (3, 5)
CLEAR = 2                      # hexes from any place, claim or district
REGROW_S = 3 * 86400.0         # a head comes back every three days
CATCH_H = 2.0
GRAZING = 1                    # a farm's land: its hex and the ring round it


def _candidates(world: "World") -> list[H.Hex]:
    from . import journey as JY
    from . import layout as L
    from . import territory as TR
    minx, miny, maxx, maxy = L.bounds(L.places_cached(list(world.cities)))
    pad = L.MOUNTAIN_OFFSET
    lo, hi = H.to_hex(minx - pad, miny - pad), H.to_hex(maxx + pad, maxy + pad)
    busy = {H.parse(k) for k in JY.places_by_hex(world)} | {H.parse(k) for k in TR.districts(world)}
    out = []
    for r in range(min(lo[1], hi[1]) - 2, max(lo[1], hi[1]) + 3):
        for q in range(min(lo[0], hi[0]) - abs(r) - 2, max(lo[0], hi[0]) + abs(r) + 3):
            h = (q, r)
            # On land a farm could be claimed round (claims.check's edge,
            # less a hex for the ring).
            x, y = H.centre(h)
            edge = L.MOUNTAIN_OFFSET - 150.0 - H.ACROSS_M * 1.2
            if not (minx - edge <= x <= maxx + edge and miny - edge <= y <= maxy + edge):
                continue
            if H.terrain(world, h) != "open":
                continue
            if any(H.distance(h, b) <= CLEAR for b in busy):
                continue
            out.append(h)
    return out


def ensure(world: "World") -> None:
    """Put the herds down, once."""
    if world.herds or not world.outposts:
        return
    rng = random.Random(f"herds:{world.land_seed}")
    spots = _candidates(world)
    rng.shuffle(spots)
    taken: list[H.Hex] = []

    def place(kind: str, n: int, size: tuple[int, int]) -> None:
        for h in spots:
            if n <= 0:
                return
            if any(H.distance(h, t) < 4 for t in taken):
                continue
            taken.append(h)
            k = rng.randint(*size)
            hid = world.new_id("H")
            world.herds[hid] = Herd(id=hid, kind=kind, hex=[h[0], h[1]], size=k, max_size=k)
            n -= 1

    place("cattle", max(3, len(spots) // CATTLE_EVERY), CATTLE_SIZE)
    place("horses", max(2, len(spots) // HORSES_EVERY), HORSE_SIZE)


def near(world: "World", h: H.Hex, kind: str, reach: int = GRAZING) -> list[Herd]:
    ensure(world)
    return [x for x in world.herds.values() if x.kind == kind and H.distance(h, (x.hex[0], x.hex[1])) <= reach]


def cattle_for(world: "World", agent: "Agent", place: str) -> str:
    """Why a farm at `place` cannot raise Hide, or "" if it can."""
    from . import claims as CL
    xy = CL.place_xy(world, place)
    if xy is None:
        return "a farm raises Hide only on land with wild cattle"
    herds = near(world, H.to_hex(*xy), "cattle")
    if not herds:
        return ("a farm raises Hide only where wild cattle graze: found a farm on a herd's "
                "hex or the ring round it -- explore to find one")
    if agent.id == world.human and agent.explored:
        found = set(agent.explored)
        if not any(H.key((x.hex[0], x.hex[1])) in found for x in herds):
            return "there are cattle near, but you have not found them yet: walk out and look"
    return ""


def hint(world: "World", x: float, y: float) -> str:
    """For the hint on a site: wild cattle or horses graze here."""
    if not world.outposts:
        return ""
    h = H.to_hex(x, y)
    if near(world, h, "cattle"):
        return "wild cattle graze here: a farm can raise Hide"
    if near(world, h, "horses"):
        return "wild horses run here"
    return ""


def tick(world: "World") -> None:
    """Herds grow back, a head every three days."""
    for x in world.herds.values():
        if x.size >= x.max_size:
            x.regrow_at = 0.0
            continue
        if not x.regrow_at:
            x.regrow_at = world.sim_time + REGROW_S
        elif world.sim_time >= x.regrow_at:
            x.size += 1
            x.regrow_at = world.sim_time + REGROW_S if x.size < x.max_size else 0.0


def horse_here(world: "World", agent: "Agent") -> Herd | None:
    if agent.hex is None:
        return None
    ensure(world)
    return next((x for x in world.herds.values() if x.kind == "horses" and x.hex == list(agent.hex) and x.size > 0), None)


def caught(world: "World", log: "EventLog", agent: "Agent", herd_id: str) -> str:
    """The catch is done: a Horse is yours, and the herd is one smaller."""
    from .state import VehicleInstance
    x = world.herds.get(herd_id)
    if x is None or x.size <= 0:
        return "The horses scattered before you could get a rope on one."
    x.size -= 1
    vid = world.new_id("V")
    world.vehicles[vid] = VehicleInstance(id=vid, type="Horse", owner=agent.id, location=agent.location)
    log.emit(world.sim_time, "horse_caught", actor=agent.id, location=agent.location, herd=x.id,
             significance=Significance.MEDIUM)
    return "You caught a wild horse. It is yours: ride it, and go 12 hexes between rests."


def view(world: "World", agent: "Agent") -> list[dict[str, Any]]:
    ensure(world)
    found = set(agent.explored)
    return [{"id": x.id, "kind": x.kind, "hex": x.hex, "size": x.size}
            for x in world.herds.values() if H.key((x.hex[0], x.hex[1])) in found]
