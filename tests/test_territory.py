#!/usr/bin/env python3
"""Borders and the refinery district (designer, 2026-11-01; convoy/territory.py).

A house's land is the hex of each of its claims and the ring round it; the
first claimer keeps a contested hex; nobody claims inside another's borders
or in a refinery district. With outposts a new refinery is founded only at a
district, outside its owner's borders, where gangs come more often --
unless it is watched. Refineries standing elsewhere keep working.
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
from convoy import robbery as RB
from convoy import territory as TR
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
    return world, log


def test_your_land_and_the_ring_round_it() -> None:
    world, log = _world()
    a = next(iter(world.agents.values()))
    home = CL.place_xy(world, a.home)
    h = H.to_hex(*home)
    own = TR.owners(world)
    ok("your home's hex and its ring are yours", all(own.get(H.key(x)) == a.id for x in H.ring(h, 1)))
    a.denari = 5000
    x, y = CL.sample_sites(world, *home, random.Random(3), n=1, near=600, far=900, who=a.id)[0]
    okc, msg, c = CL.claim(world, log, a, x, y, "Farm")
    ok("claim more land", okc, msg)
    ok("and its ring is yours too", TR.inside(world, a.id, x, y) and
       all(TR.owners(world).get(H.key(n)) == a.id or TR.owners(world).get(H.key(n)) not in (None, "")
           for n in H.ring(H.to_hex(x, y), 1)))


def test_nobody_claims_inside_your_borders() -> None:
    world, log = _world()
    a, b = list(world.agents.values())[:2]
    b.denari = 5000
    home = CL.place_xy(world, a.home)
    cx, cy = H.centre(H.neighbours(H.to_hex(*home))[0])
    why = CL.check(world, cx, cy, who=b.id)
    ok("inside another house's borders, no", "borders" in why, why)
    ok("inside your own, the borders do not stop you", "borders" not in CL.check(world, cx, cy, who=a.id))
    okc, msg, _ = CL.claim(world, log, b, cx, cy, "Farm")
    ok("so the claim is refused", not okc and "borders" in msg, msg)


def test_first_claimer_keeps_a_shared_hex() -> None:
    world, log = _world()
    claims = sorted(world.claims.values(), key=lambda c: c.created_at)
    first = claims[0]
    later = claims[-1]
    later.created_at = first.created_at - 1          # now it came first
    TR._OWNERS.clear()
    t = TR.owners(world)
    ok("the earlier claim wins its hex", t[H.key(H.to_hex(later.x, later.y))] == later.owner)


def test_the_refinery_district() -> None:
    world, log = _world()
    a = next(iter(world.agents.values()))
    a.denari = 9000
    places = TR.district_places(world)
    ok("one district per city", len(places) == len(world.cities), str(places))
    d = CL.place_xy(world, places[0])
    dh = H.to_hex(*d)
    nx, ny = H.centre((dh[0] + 1, dh[1]))
    ok("nobody claims in it", "refinery district" in CL.check(world, nx, ny, who=a.id))
    home = CL.place_xy(world, a.home)
    x, y = CL.sample_sites(world, *home, random.Random(2), n=1, near=400, far=700, who=a.id)[0]
    _, _, c = CL.claim(world, log, a, x, y, "Farm")
    a.location = c.name
    okr, msg = A.start_business(world, log, a, "Refinery")
    ok("no refinery on your own claim", not okr and "refinery district" in msg, msg)
    a.location = places[0]
    okr, msg = A.start_business(world, log, a, "Refinery")
    ok("one at the district", okr, msg)
    ref = world.businesses[a.owned_businesses[-1]]
    ok("standing outside your borders", RB.outside(world, ref) == TR.OUTSIDE_BORDERS)
    # A farm at home is not.
    a.location = c.name
    A.start_business(world, log, a, "Farm")
    farm = world.businesses[a.owned_businesses[-1]]
    ok("a farm on your land is inside them", RB.outside(world, farm) == 1.0)


def test_an_old_refinery_keeps_working() -> None:
    world, log = _world()
    a = next(iter(world.agents.values()))
    a.denari = 9000
    x, y = CL.sample_sites(world, *CL.place_xy(world, a.home), random.Random(2), n=1, near=400, far=700, who=a.id)[0]
    _, _, c = CL.claim(world, log, a, x, y, "Farm")
    a.location = c.name
    real = TR.district_places
    TR.district_places = lambda w: [c.name]          # built before the rule
    A.start_business(world, log, a, "Refinery")
    TR.district_places = real
    ref = world.businesses[a.owned_businesses[-1]]
    okp, msg = A.set_production(world, log, a, ref.id, "Grain")
    ok("it still works", okp and not ref.closed, msg)


def test_checkpoint_keeps_the_land() -> None:
    world, log = _world()
    before = dict(TR.owners(world))
    with tempfile.TemporaryDirectory() as tmp:
        p = Path(tmp) / "w.json"
        CK.save(world, p)
        back = CK.load(p)
    ok("borders come back the same", TR.owners(back) == before)


def main() -> int:
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for t in tests:
        t()
    print(f"test_territory.py: {len(tests)} tests, {len(FAILURES)} failures")
    for f in FAILURES:
        print(f"  FAIL {f}")
    return 1 if FAILURES else 0


if __name__ == "__main__":
    raise SystemExit(main())
