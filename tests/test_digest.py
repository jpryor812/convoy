#!/usr/bin/env python3
"""The periodic "what's working" summary every agent reads.

Designer request, 2026-10-16: agents should now and then look at the whole game
and react to what is working. The digest is built from the log and the world on
a fixed cadence, carried in every observation until replaced, and flagged on
line one the first time an agent sees it.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from convoy import actions as A
from convoy import digest as DG
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


def _world():
    log = EventLog(None, echo_min=99)
    cities = M.CITY_KEYS[:2]
    world = new_world(log, [], {c: [(f"{c}-{i}", "m") for i in range(2)] for c in cities},
                      government=False)
    return world, log


def test_it_reports_what_sold_and_what_is_missing() -> None:
    world, log = _world()
    seller, buyer = world.agents_in(world.cities[0])
    seller.location = buyer.location = M.CITIES[world.cities[0]].market
    A.start_business(world, log, seller, "Tavern / Inn")
    tavern = world.businesses[seller.owned_businesses[0]]
    base = DG.snapshot(world)
    from convoy.state import Transaction
    A._record_trade(world, log, Transaction(world.sim_time, "Meal", 2, 12.0, tavern.id,
                                            buyer.id, world.cities[0]), "meal", tavern.location)
    A.pay(world, log, buyer, seller.id, 50)
    text = DG.build(world, log, 0.0, base)
    ok("names the business that took money", tavern.name in text and "took in 24" in text, text)
    ok("and the price goods went for", "Meal" in text and "12.00 each" in text, text)
    ok("says who got richer", seller.id in text and "owns Tavern / Inn" in text, text)
    ok("and what a city is not making", "NOT MADE" in text, text)


def test_the_engine_publishes_it_and_agents_see_it_once_as_new() -> None:
    world, log = _world()
    eng = Engine(world, log, Idle(), EngineConfig(speed=1e9, checkpoint_every_hours=1e9,
                                                  duration_hours=DG.DIGEST_EVERY_HOURS + 0.5))
    eng.run()
    ok("one digest published", sum(e.type == "digest" for e in log.events) == 1)
    ok("and kept on the world", bool(world.digest))
    agent = next(iter(world.agents.values()))
    first = O.render(O.observe(world, log, agent, "reevaluation"))
    ok("flagged as new on line one", "A NEW report" in first.splitlines()[0])
    ok("and shown in full", "WHAT'S WORKING ACROSS THE WORLD" in first)
    again = O.render(O.observe(world, log, agent, "reevaluation"))
    ok("not new the second time", "A NEW report" not in again.splitlines()[0])
    ok("but still there", "WHAT'S WORKING ACROSS THE WORLD" in again)
    eng.close()


def main() -> int:
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for t in tests:
        t()
    print(f"test_digest.py: {len(tests)} tests, {len(FAILURES)} failures")
    for f in FAILURES:
        print(f"  FAIL {f}")
    return 1 if FAILURES else 0


if __name__ == "__main__":
    raise SystemExit(main())
