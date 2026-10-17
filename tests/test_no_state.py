#!/usr/bin/env python3
"""A world with no government at all, and a labour market that poaches.

Designer decisions of 2026-10-16: no state businesses, no fixed prices, no
state jobs, no tax; everyone starts fed for a day and is told what the valley
must build to eat after that. And an owner can offer a named person a job --
including someone working for somebody else -- who can take it outright.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from convoy import actions as A
from convoy import data as D
from convoy import observe as O
from convoy import world_map as M
from convoy.events import EventLog
from convoy.world_setup import new_world

FAILURES: list[str] = []


def ok(label, condition, detail="") -> None:
    if not condition:
        FAILURES.append(f"{label}{': ' + detail if detail else ''}")


def check(label, actual, expected) -> None:
    if actual != expected:
        FAILURES.append(f"{label}: got {actual!r}, expected {expected!r}")


def _world(n: int = 3):
    log = EventLog(None, echo_min=99)
    world = new_world(log, [(f"citizen-{i}", "m") for i in range(n)], government=False)
    return world, log


def test_there_is_no_government() -> None:
    world, _ = _world()
    ok("flagged", world.no_state)
    check("no state businesses", sum(b.is_government for b in world.businesses.values()), 0)
    g = world.government
    check("no tax of any kind", (g.wage_tax, g.sales_tax, g.property_tax, g.road_tax),
          (0.0, 0.0, 0.0, 0.0))
    check("every reader is told the state is gone", world.state_gone_at(world.cities[0]), 0.0)


def test_everyone_starts_fed_for_a_day() -> None:
    world, _ = _world()
    ok("a 24-hour first meal window",
       all(a.last_meal_window == D.START_FED_HOURS_NO_STATE for a in world.agents.values()))
    check("which is a day", D.START_FED_HOURS_NO_STATE, 24.0)


def test_they_are_told_what_to_build() -> None:
    world, log = _world()
    agent = next(iter(world.agents.values()))
    brief = O.briefing_for(world, agent)
    ok("no government, said plainly", "THERE IS NO GOVERNMENT" in brief)
    ok("how long they are fed", "START FED FOR 24 HOURS" in brief)
    ok("the food chain, link by link",
       all(w in brief for w in ("Tavern", "Grain and Purified Water", "Refinery", "Farm")))
    ok("that nobody makes it yet", "NOBODY MAKES ANY OF IT" in brief)
    ok("and the same for carts and weapons", "Stable" in brief and "Weaponsmith" in brief)
    ok("no price table offering state prices", "NPC sells to you" not in brief)
    obs = O.render(O.observe(world, log, agent, "reevaluation"))
    ok("and every observation reminds them", "THERE IS NO GOVERNMENT" in obs.splitlines()[1])


def test_a_worker_can_be_poached_with_a_better_offer() -> None:
    world, log = _world(3)
    owner_a, owner_b, worker = list(world.agents.values())
    market = M.CITIES[world.cities[0]].market
    for a in (owner_a, owner_b, worker):
        a.location = market
        a.denari = 2_000
    ok_a, msg = A.start_business(world, log, owner_a, "Tavern / Inn")
    ok("first tavern founded", ok_a, msg)
    ok_b, msg = A.start_business(world, log, owner_b, "Tavern / Inn")
    ok("second tavern founded", ok_b, msg)
    tav_a = world.businesses[owner_a.owned_businesses[0]]
    tav_b = world.businesses[owner_b.owned_businesses[0]]
    role = tav_a.spec.production_roles[0]
    floor = D.WAGE_FLOORS[role]

    okj, msg = A.offer_job(world, log, owner_a, tav_a.id, worker.id, floor + 1)
    ok("an owner can offer a named person a job", okj, msg)
    first = next(p for p in world.job_postings.values() if p.invitee == worker.id)
    oka, msg = A.accept_job_offer(world, log, worker, first.id)
    ok("and they can take it", oka, msg)
    check("employed by A", worker.current_job[0] if worker.current_job else None, tav_a.id)

    okj, msg = A.offer_job(world, log, owner_b, tav_b.id, worker.id, floor + 3)
    ok("a rival can offer them more", okj, msg)
    better = next(p for p in world.job_postings.values()
                  if p.invitee == worker.id and p.status == "open")
    shown = O.affordances(world, worker)
    ok("they see the offer, with the rise",
       any("JOB OFFERS TO YOU" in line and better.id in line and "+2.00" in line for line in shown),
       str(shown))
    oka, msg = A.accept_job_offer(world, log, worker, better.id)
    ok("and can leave for it", oka, msg)
    check("now employed by B", worker.current_job[0] if worker.current_job else None, tav_b.id)
    ok("off A's roster", all(e.agent_id != worker.id for e in tav_a.roster))
    ok("an offer is not a public advert",
       not any(better.id in line and "JOBS ON THE BOARD" in line
               for line in O.affordances(world, owner_a)))
    oko, msg = A.accept_job_offer(world, log, owner_a, better.id)
    ok("nobody else can take somebody's offer", not oko, msg)


def test_citizens_can_pool_cash_for_a_refinery() -> None:
    world, log = _world(2)
    a, b = list(world.agents.values())
    cost = D.BUSINESS_TYPES["Refinery"].startup_cost
    ok("a refinery costs more than anyone starts with", cost > D.STARTING_DENARI)
    okp, msg = A.pay(world, log, b, a.id, 200, note="stake in the refinery")
    ok("one can pay another", okp, msg)
    check("the money moved", (a.denari, b.denari),
          (D.STARTING_DENARI + 200, D.STARTING_DENARI - 200))
    paid = [e for e in log.events if e.type == "payment"]
    ok("and it is logged, with its note",
       len(paid) == 1 and paid[0].detail["note"] == "stake in the refinery")
    ok("a refinery is now within reach", a.denari >= cost)
    okp, _ = A.pay(world, log, b, a.id, 10_000)
    ok("not more than you have", not okp)
    okp, _ = A.pay(world, log, b, b.id, 1)
    ok("not to yourself", not okp)
    brief = O.briefing_for(world, a)
    ok("the briefing names the costs and says to pool",
       f"Refinery {cost:.0f}" in brief and "POOL" in brief, brief[-600:])


def test_every_worker_is_a_citizen() -> None:
    from convoy import schemas as S
    world, log = _world(1)
    owner = next(iter(world.agents.values()))
    owner.location = M.CITIES[world.cities[0]].market
    A.start_business(world, log, owner, "Tavern / Inn")
    biz = world.businesses[owner.owned_businesses[0]]
    tools = {t["function"]["name"]: t["function"]["description"]
             for t in S.tool_schemas(state_gone=True, no_state=True)}
    ok("no NPC hiring offered", "hire_npc_employee" not in tools)
    ok("and with a government it still is",
       "hire_npc_employee" in {t["function"]["name"] for t in S.tool_schemas()})
    okh, msg = A.hire_npc_employee(world, log, owner, biz.id, biz.spec.production_roles[0])
    ok("named anyway, it is refused", not okh, msg)
    ok("apply_for_job says it is for your own business", "YOUR OWN" in tools["apply_for_job"])
    okj, msg = A.apply_for_job(world, log, owner, biz.id)
    ok("and an owner can still staff their own", okj, msg)


def test_a_city_opens_one_decision_at_a_time() -> None:
    from convoy.engine import Engine, EngineConfig

    class Idle:
        def decide(self, world, agent, reason):
            return None

    log = EventLog(None, echo_min=99)
    cities = M.CITY_KEYS[:2]
    world = new_world(log, [], {c: [(f"{c}-{i}", "m") for i in range(3)] for c in cities},
                      government=False)
    eng = Engine(world, log, Idle(), EngineConfig(decision_workers=4, speed=1e9))
    eng._stagger_opening()
    lag = eng.config.max_decision_lag_minutes * 60.0
    for c in cities:
        wakes = [a.next_reeval_at for a in world.agents_in(c)]
        check(f"{c}: the first citizen decides at once", wakes[0], 0.0)
        ok(f"{c}: the next only after the last could have acted",
           all(b - a > lag for a, b in zip(wakes, wakes[1:])), str(wakes))
    eng.close()

    # A crowded city still opens within the window, gaps shrinking to fit.
    from convoy.engine import OPENING_WINDOW_MINUTES
    world = new_world(log, [(f"c-{i}", "m") for i in range(20)], government=False)
    eng = Engine(world, log, Idle(), EngineConfig(decision_workers=4, speed=1e9))
    eng._stagger_opening()
    wakes = [a.next_reeval_at for a in world.agents_in(world.cities[0])]
    ok("twenty citizens all open within the window",
       max(wakes) <= OPENING_WINDOW_MINUTES * 60.0 + 1e-6 and wakes == sorted(set(wakes)),
       str(wakes))
    eng.close()


def main() -> int:
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for t in tests:
        t()
    print(f"test_no_state.py: {len(tests)} tests, {len(FAILURES)} failures")
    for f in FAILURES:
        print(f"  FAIL {f}")
    return 1 if FAILURES else 0


if __name__ == "__main__":
    raise SystemExit(main())
