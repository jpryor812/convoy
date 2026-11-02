#!/usr/bin/env python3
"""Wild herds (designer, 2026-11-01; convoy/herds.py).

Cattle and horses are put down once a world, the same for the same seed, on
open ground away from every place. A farm raises Hide only where cattle graze
(its hex or the ring round it) -- and the player only once they have found
them. Wild horses are caught, two hours with a rope, and grow back.
"""

from __future__ import annotations

import random
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from convoy import actions as A
from convoy import checkpoint as CK
from convoy import claims as CL
from convoy import hexes as H
from convoy import herds as HD
from convoy import journey as JY
from convoy import town as TOWN
from convoy.events import EventLog
from convoy.world_setup import new_world

FAILURES: list[str] = []


def ok(label, condition, detail="") -> None:
    if not condition:
        FAILURES.append(f"{label}{': ' + detail if detail else ''}")


class _S:
    model = "x/rule-based"
    outposts = True
    cities = {"aldermarch": 6, "cinderhold": 6, "thornwick": 6}


def _world(seed: int = 7):
    log = EventLog(None, echo_min=99)
    world = new_world(log, [], TOWN._rosters(_S), government=False, starter_sites=True)
    world.land_seed = seed
    TOWN.populate_outposts(world, log, random.Random(seed))
    HD.ensure(world)
    return world, log


def test_herds_are_put_down() -> None:
    w1, _ = _world(7)
    w2, _ = _world(7)
    k = lambda w: sorted((x.kind, tuple(x.hex), x.size) for x in w.herds.values())
    ok("the same for the same seed", k(w1) == k(w2))
    kinds = [x.kind for x in w1.herds.values()]
    ok("cattle and horses", kinds.count("cattle") >= 3 and kinds.count("horses") >= 2, str(kinds))
    busy = {H.parse(p) for p in JY.places_by_hex(w1)}
    ok("on open ground away from places", all(H.terrain(w1, tuple(x.hex)) == "open"
       and all(H.distance(tuple(x.hex), b) > HD.CLEAR for b in busy) for x in w1.herds.values()))


def _farm_at(world, log, who, h):
    who.denari = 9000
    x, y = H.centre(h)
    okc, msg, c = CL.claim(world, log, who, x, y, "Farm")
    assert okc, msg
    who.location = c.name
    A.start_business(world, log, who, "Farm")
    return world.businesses[who.owned_businesses[-1]]


def test_hide_needs_cattle() -> None:
    world, log = _world()
    a, b = list(world.agents.values())[:2]
    herd = next(x for x in world.herds.values() if x.kind == "cattle")
    far = next(h for h in (H.to_hex(*CL.place_xy(world, a.home)),)
               if not HD.near(world, h, "cattle"))
    home_farm = None
    for nb in H.ring(far, 3):
        if not HD.near(world, nb, "cattle") and not CL.check(world, *H.centre(nb), who=a.id):
            home_farm = _farm_at(world, log, a, nb)
            break
    okp, msg = A.set_production(world, log, a, home_farm.id, "Hide")
    ok("no cattle, no Hide", not okp and "cattle" in msg, msg)
    # A settler's farm by a herd: cattle are enough.
    by = next(n for n in H.ring(tuple(herd.hex), 1) if not CL.check(world, *H.centre(n), who=b.id))
    bf = _farm_at(world, log, b, by)
    okp, msg = A.set_production(world, log, b, bf.id, "Hide")
    ok("a settler's farm by cattle raises Hide", okp, msg)
    # The player, by the same kind of herd, must have found it.
    world.human = a.id
    JY.ensure(world, a)
    herd2 = next(x for x in world.herds.values() if x.kind == "cattle" and x is not herd)
    by2 = next((n for n in H.ring(tuple(herd2.hex), 1) if not CL.check(world, *H.centre(n), who=a.id)), None)
    if by2:
        pf = _farm_at(world, log, a, by2)
        a.explored = [k for k in a.explored if k != H.key(tuple(herd2.hex))]
        okp, msg = A.set_production(world, log, a, pf.id, "Hide")
        ok("not found yet, not yet", not okp and "found" in msg, msg)
        a.explored.append(H.key(tuple(herd2.hex)))
        okp, msg = A.set_production(world, log, a, pf.id, "Hide")
        ok("found, Hide", okp, msg)
    ok("a site by cattle says so", "cattle" in CL.ground_hint(world, *H.centre(tuple(herd.hex))))


def test_catch_a_horse() -> None:
    world, log = _world()
    a = next(iter(world.agents.values()))
    world.human = a.id
    JY.ensure(world, a)
    herd = next(x for x in world.herds.values() if x.kind == "horses")
    size = herd.size
    okc, msg = JY.catch(world, log, a)
    ok("not without horses here", not okc, msg)
    a.hex = list(herd.hex)
    okc, msg = JY.catch(world, log, a)
    ok("among them, after them with a rope", okc and a.activity.kind == "catch", msg)
    world.sim_time = a.activity.ends_at + 1
    ev = JY.advance(world, log, a)
    mine = [v for v in world.vehicles.values() if v.owner == a.id and v.type == "Horse"]
    ok("a horse of your own", ev and "caught" in ev and mine, str(ev))
    ok("and the herd is one smaller", herd.size == size - 1)
    a.mounted_vehicle = mine[0].id
    ok("ride it: 12 hexes between rests", JY.max_energy(world, a) == 12)
    world.sim_time += 1
    HD.tick(world)
    world.sim_time += HD.REGROW_S + 1
    HD.tick(world)
    ok("it grows back", herd.size == size)


def test_checkpoint_keeps_the_herds() -> None:
    world, log = _world()
    with tempfile.TemporaryDirectory() as tmp:
        p = Path(tmp) / "w.json"
        CK.save(world, p)
        back = CK.load(p)
    ok("herds survive a restart", len(back.herds) == len(world.herds) and back.herds)


def main() -> int:
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for t in tests:
        t()
    print(f"test_herds.py: {len(tests)} tests, {len(FAILURES)} failures")
    for f in FAILURES:
        print(f"  FAIL {f}")
    return 1 if FAILURES else 0


if __name__ == "__main__":
    raise SystemExit(main())
