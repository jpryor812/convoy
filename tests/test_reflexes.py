#!/usr/bin/env python3
"""Reflexes: the one-answer moves made without asking the model.

Designer decision, 2026-10-16 (hybrid option A). A courier at the pickup loads
and goes; at the drop it delivers; a hungry agent in a stocked tavern eats; a
shift with nothing new to think about runs again; an idle agent with nothing new
keeps waiting. Anything new -- and a few hours' silence -- goes to the model.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from convoy import actions as A
from convoy import reflexes as RX
from convoy.engine import Engine, EngineConfig
from convoy.events import EventLog
from convoy.state import Activity, Reasoning
from convoy.world_setup import new_world

FAILURES: list[str] = []


def ok(label, condition, detail="") -> None:
    if not condition:
        FAILURES.append(f"{label}{': ' + detail if detail else ''}")


class Counting:
    """Stands in for the model: counts how often it is asked."""

    def __init__(self):
        self.asked: list[str] = []

    def decide(self, world, agent, reason) -> None:
        self.asked.append(reason)


def _engine(world, log):
    policy = Counting()
    eng = Engine(world, log, policy, EngineConfig(speed=1e9, reflexes=True))
    return eng, policy


def _world(n=3):
    log = EventLog(None, echo_min=99)
    world = new_world(log, [(f"a{i}", "m") for i in range(n)], government=False)
    for a in world.agents.values():
        a.denari = 2_000.0
    return world, log


def _thought(world, agent, did=("wait",)):
    """As if the model had just decided, and chosen `did`."""
    agent.last_thought_at = world.sim_time
    agent.thought_fingerprint = RX.fingerprint(world, agent)
    agent.reasoning.append(Reasoning(world.sim_hour, "reevaluation", "", list(did)))


def test_a_courier_loads_and_goes_then_delivers() -> None:
    world, log = _world()
    refiner, taverner, courier = list(world.agents.values())
    refiner.location = "Refinery Row"
    A.start_business(world, log, refiner, "Refinery", seed_cash=200.0)
    refinery = world.businesses[refiner.owned_businesses[0]]
    refinery.inventory = {"Grain": 10}
    refinery.retail_prices = {"Grain": 4.0}
    taverner.location = "Town"
    A.start_business(world, log, taverner, "Tavern / Inn", seed_cash=500.0)
    tavern = world.businesses[taverner.owned_businesses[0]]
    okr, msg = A.order_from_business(world, log, taverner, tavern.id, refinery.id,
                                     "Grain", 4, courier_fee=10.0)
    ok("order placed", okr, msg)
    con = next(iter(world.consignments.values()))
    courier.location = "Refinery Row"
    okc, msg = A.accept_courier_job(world, log, courier, con.id)
    ok("claimed", okc, msg)
    eng, policy = _engine(world, log)

    eng._ask(courier, "arrived")
    ok("the model was not asked at the pickup", not policy.asked, str(policy.asked))
    ok("the load is on board", courier.hauling == con.id)
    ok("and it set off for the drop",
       courier.activity.kind == "travel" and courier.in_transit
       and courier.in_transit[1] == con.destination, str(courier.in_transit))

    courier.activity = Activity("idle", world.sim_time)
    courier.in_transit = None
    courier.location = con.destination
    eng._ask(courier, "arrived")
    ok("delivered", world.consignments[con.id].status == "delivered")
    ok("and with nothing else claimed, the model decides what next",
       policy.asked == ["arrived"], str(policy.asked))
    ok("each move is in the log, for its memory",
       {e.detail["reflex"] for e in log.events if e.type == "reflex"}
       >= {"collect", "set off", "deliver"})
    eng.close()


def test_a_hungry_worker_in_a_stocked_tavern_eats_and_carries_on() -> None:
    world, log = _world(2)
    owner, worker = list(world.agents.values())
    owner.location = worker.location = "Town"
    A.start_business(world, log, owner, "Tavern / Inn", seed_cash=200.0)
    tavern = world.businesses[owner.owned_businesses[0]]
    A.apply_for_job(world, log, owner, tavern.id)
    A.start_shift(world, log, owner, 8)
    tavern.inventory = {"Meal": 3}
    tavern.retail_prices = {"Meal": 10.0}
    worker.sustenance_stage = "Hungry"
    worker.activity = Activity("work", world.sim_time + 3600, {})
    eng, policy = _engine(world, log)
    eng._ask(worker, "reevaluation")
    ok("it ate", any(e.type == "ate" and e.actor == worker.id for e in log.events))
    ok("and was not pulled off its work to think about it", not policy.asked,
       str(policy.asked))
    eng.close()


def test_a_shift_runs_again_only_while_nothing_has_changed() -> None:
    world, log = _world(2)
    owner, other = list(world.agents.values())
    owner.location = "Millrace Farms"
    oks, msg = A.start_business(world, log, owner, "Farm")
    ok("farm founded", oks, msg)
    farm = world.businesses[owner.owned_businesses[0]]
    A.set_production(world, log, owner, farm.id, "Wheat")
    A.apply_for_job(world, log, owner, farm.id)
    A.start_shift(world, log, owner, 4)
    _thought(world, owner, ("start_shift",))
    eng, policy = _engine(world, log)
    world.sim_time = owner.activity.ends_at
    eng._ask(owner, "activity_complete")
    ok("nothing new: the same shift again, no model call",
       not policy.asked and owner.activity.kind == "work"
       and owner.activity.ends_at > world.sim_time, str(policy.asked))

    world.sim_time = owner.activity.ends_at
    A.send_direct_message(world, log, other, owner.id, "want to sell me your wheat?")
    eng._ask(owner, "activity_complete")
    ok("a message arrived: the model is asked", policy.asked == ["activity_complete"],
       str(policy.asked))
    eng.close()


def test_waiting_with_nothing_new_costs_nothing_but_not_for_long() -> None:
    world, log = _world(2)
    idle, other = list(world.agents.values())
    _thought(world, idle, ("wait",))
    eng, policy = _engine(world, log)
    world.sim_time += 900
    eng._ask(idle, "reevaluation")
    ok("nothing new: it keeps waiting without a model call", not policy.asked)

    world.sim_time += RX.MAX_SILENCE_HOURS * 3600
    eng._ask(idle, "reevaluation")
    ok("but after a long silence the model is asked anyway",
       policy.asked == ["reevaluation"], str(policy.asked))

    _thought(world, idle, ("wait",))
    world.sim_time += 900
    A.pay(world, log, other, idle.id, 100)
    eng._ask(idle, "reevaluation")
    ok("and money arriving is news", len(policy.asked) == 2, str(policy.asked))

    _thought(world, idle, ("send_direct_message", "wait"))
    world.sim_time += 900
    eng._ask(idle, "activity_complete")
    ok("a message then a wait, its own timer up, nothing new: keeps waiting",
       len(policy.asked) == 2, str(policy.asked))
    world.sim_time += 60
    A.post_world_chat(world, log, other, f"{idle.id}, I can pay 9 a sack -- deal?")
    eng._ask(idle, "reevaluation")
    ok("named in world chat is news", len(policy.asked) == 3, str(policy.asked))
    eng.close()


def test_supplies_appearing_in_town_are_news_to_a_buyer() -> None:
    world, log = _world(2)
    taverner, refiner = list(world.agents.values())
    taverner.location, refiner.location = "Town", "Refinery Row"
    A.start_business(world, log, taverner, "Tavern / Inn")
    A.start_business(world, log, refiner, "Refinery")
    refinery = world.businesses[refiner.owned_businesses[0]]
    _thought(world, taverner, ("wait",))
    eng, policy = _engine(world, log)
    world.sim_time += 900
    eng._ask(taverner, "reevaluation")
    ok("nothing in stock anywhere: keeps waiting", not policy.asked)
    refinery.inventory["Grain"] = 12
    world.sim_time += 900
    eng._ask(taverner, "reevaluation")
    ok("grain at the refinery: the taverner is asked", policy.asked == ["reevaluation"],
       str(policy.asked))
    eng.close()


def test_off_by_default_so_scripted_policies_see_every_wake() -> None:
    ok("off unless asked for", EngineConfig().reflexes is False)


def main() -> int:
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for t in tests:
        t()
    print(f"test_reflexes.py: {len(tests)} tests, {len(FAILURES)} failures")
    for f in FAILURES:
        print(f"  FAIL {f}")
    return 1 if FAILURES else 0


if __name__ == "__main__":
    raise SystemExit(main())
