#!/usr/bin/env python3
"""Land quality: hidden ground under every farm and mine.

Designer decision, 2026-10-17. A farm or mine gets hidden land when founded --
about two in three make one of their goods 5-25% faster -- which applies at
once, is revealed by the first harvest, and is shown to the owner and on the
building's card from then on. Refineries and shops have none.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from convoy import actions as A
from convoy import inspect as I
from convoy import land as LAND
from convoy import observe as O
from convoy import world_map as M
from convoy.engine import Engine, EngineConfig
from convoy.events import EventLog
from convoy.world_setup import new_world

FAILURES: list[str] = []


def ok(label, condition, detail="") -> None:
    if not condition:
        FAILURES.append(f"{label}{': ' + detail if detail else ''}")


class Idle:
    def decide(self, world, agent, reason) -> None:
        return None


def _founded(kind="Farm", n=40, seed=1234):
    log = EventLog(None, echo_min=99)
    world = new_world(log, [(f"a{i}", "m") for i in range(n)], government=False)
    world.land_seed = seed
    spurs = [p for p in M.places_in(world.cities[0]) if p in M.SPUR_BY_NAME]
    out = []
    for i, a in enumerate(world.agents.values()):
        a.denari = 5000
        a.location = spurs[i % len(spurs)]
        okb, _ = A.start_business(world, log, a, kind)
        if okb:
            out.append(world.businesses[a.owned_businesses[0]])
    return world, log, out


def test_most_farms_and_mines_get_one_good_and_it_is_hidden() -> None:
    for kind, goods in (("Farm", LAND.FARM_GOODS), ("Mining Operation", LAND.MINE_GOODS)):
        world, log, bs = _founded(kind)
        lucky = [b for b in bs if b.land_bonus_item]
        ok(f"{kind}: some are lucky and some are not", 0 < len(lucky) < len(bs), f"{len(lucky)}/{len(bs)}")
        ok(f"{kind}: only its own goods", all(b.land_bonus_item in goods for b in lucky))
        ok(f"{kind}: 5 to 25 percent", all(0.05 <= b.land_bonus_pct <= 0.25 for b in lucky))
        ok(f"{kind}: none revealed yet", not any(b.land_revealed for b in bs))
        ok(f"{kind}: the card says nothing yet", all(I.business_card(world, b)["land"] is None for b in bs))


def test_the_same_game_keeps_its_land_and_another_does_not() -> None:
    _, _, a = _founded(seed=77)
    _, _, b = _founded(seed=77)
    _, _, c = _founded(seed=78)
    key = lambda bs: [(x.location, x.land_bonus_item, x.land_bonus_pct) for x in bs]
    ok("same seed, same land", key(a) == key(b))
    ok("another seed, other land", key(a) != key(c))


def test_refineries_have_no_land_luck() -> None:
    log = EventLog(None, echo_min=99)
    world = new_world(log, [("a", "m")], government=False)
    a = next(iter(world.agents.values()))
    a.denari = 5000
    a.location = M.CITIES[world.cities[0]].market
    A.start_business(world, log, a, "Refinery")
    biz = world.businesses[a.owned_businesses[0]]
    ok("no bonus", not biz.land_bonus_item and LAND.describe(biz) is None)


def test_rich_ground_is_faster_and_the_first_harvest_reveals_it() -> None:
    world, log, bs = _founded()
    biz = next(b for b in bs if b.land_bonus_item)
    owner = world.agents[biz.owner]
    eng = Engine(world, log, Idle(), EngineConfig(speed=1e9))
    A.set_production(world, log, owner, biz.id, biz.land_bonus_item)
    A.apply_for_job(world, log, owner, biz.id)
    A.start_shift(world, log, owner, 4)
    fast = eng.production_rate(biz)
    item, biz.land_bonus_item = biz.land_bonus_item, ""
    plain = eng.production_rate(biz)
    biz.land_bonus_item = item
    ok("the bonus good is made faster", abs(fast / plain - (1 + biz.land_bonus_pct)) < 1e-6, f"{fast} vs {plain}")
    seen = O.render(O.observe(world, log, owner, "x", record_delivery=False))
    ok("the owner is told it is unknown", "Unknown until it first produces" in seen)
    for _ in range(30):
        eng.tick(60)
        if biz.land_revealed:
            break
    ok("the first harvest reveals it", biz.land_revealed)
    ok("and says so in the log", any(e.type == "land_revealed" and e.subject == biz.id for e in log.events))
    seen = O.render(O.observe(world, log, owner, "x", record_delivery=False))
    ok("the owner now sees it", "RICH GROUND" in seen and item in seen)
    ok("and so does the building's card", I.business_card(world, biz)["land"]["item"] == item)
    eng.close()


def main() -> int:
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for t in tests:
        t()
    print(f"test_land.py: {len(tests)} tests, {len(FAILURES)} failures")
    for f in FAILURES:
        print(f"  FAIL {f}")
    return 1 if FAILURES else 0


if __name__ == "__main__":
    raise SystemExit(main())
