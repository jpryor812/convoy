#!/usr/bin/env python3
"""`agent.activity` is one slot, and losing what is in it costs real money.

Wages accrue ONLY while `activity.kind == "work"`, and the engine moves a
traveller and clears `in_transit` ONLY from its `kind == "travel"` branch. So
any action that overwrites a live activity does not merely change the agent's
plan -- it clocks them out, or strands them on a road they will never finish.

Both happened. In the 2026-08-14 72-hour run `wait` overwrote the activity
unconditionally, and because `wait` is terminal the model reached for it at the
end of almost every decision. 9 of 12 agents ended up permanently "in transit"
while standing at their origin, and the whole population earned a fraction of
its wage. Nothing caught it, because each action was correct in isolation --
only the SEQUENCE was wrong.

These tests exercise sequences.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from convoy import actions as A
from convoy.engine import Engine, EngineConfig
from convoy.events import EventLog
from convoy.world_setup import new_world

FAILURES: list[str] = []


class NullPolicy:
    """Agents make no new decisions; we are testing what the ENGINE does to
    an activity that was already committed."""

    def decide(self, world, agent, reason) -> None:
        return None


def ok(label: str, cond: bool, detail: str = "") -> None:
    print(f"  {label}" + (f": {detail}" if detail else ""))
    if not cond:
        FAILURES.append(f"{label}{': ' + detail if detail else ''}")


def setup():
    log = EventLog(None, echo_min=99)
    world = new_world(log, [("worker", "rule-based")])
    return world, log, next(iter(world.agents.values()))


def test_waiting_does_not_end_a_shift():
    """start_shift -> wait must leave the agent ON SHIFT and still earning."""
    world, log, a = setup()
    biz = [b for b in world.businesses.values() if b.type == "Vehicle Dealer / Stable"][0]
    a.location = biz.location
    A.apply_for_job(world, log, a, biz.id)
    A.start_shift(world, log, a, hours=8)

    A.wait(world, log, a, 1.0)
    ok("still working after a 1s wait", a.activity.kind == "work", a.activity.kind)

    A.wait(world, log, a, 28800.0)
    ok("still working after a long wait", a.activity.kind == "work", a.activity.kind)
    ok(
        "shift clock was not restarted",
        abs(a.activity.ends_at - 8 * 3600.0) < 1e-6,
        f"ends_at={a.activity.ends_at}",
    )


def test_waiting_does_not_cancel_a_journey():
    """travel_to -> wait must leave the agent EN ROUTE, not stranded."""
    world, log, a = setup()
    a.location = "Town"
    A.travel_to(world, log, a, "South Protected Zone")
    A.wait(world, log, a, 90.0)

    ok("still travelling after a wait", a.activity.kind == "travel", a.activity.kind)
    ok("in_transit still set", a.in_transit is not None, str(a.in_transit))


def test_a_waiting_traveller_actually_arrives():
    """The end-to-end version: the journey must complete under the engine."""
    world, log, a = setup()
    a.location = "Town"
    A.travel_to(world, log, a, "South Protected Zone")
    A.wait(world, log, a, 5.0)

    Engine(
        world, log, policy=NullPolicy(), config=EngineConfig(
            duration_hours=0.5, speed=1e9, checkpoint_every_hours=1e9,
        ),
    ).run()

    ok("arrived", a.location == "South Protected Zone", a.location)
    ok("in_transit cleared on arrival", a.in_transit is None, str(a.in_transit))


def test_engine_recovers_a_desynced_traveller():
    """Belt and braces: a stale in_transit must not strand an agent forever.

    Even if some future action clobbers the activity, the engine reconciles
    rather than leaving the agent 'travelling' while standing still.
    """
    world, log, a = setup()
    a.location = "Town"
    A.travel_to(world, log, a, "South Protected Zone")
    a.activity = A.Activity("idle", 0.0)          # simulate a bad overwrite

    Engine(
        world, log, policy=NullPolicy(), config=EngineConfig(
            duration_hours=0.2, speed=1e9, checkpoint_every_hours=1e9,
        ),
    ).run()

    ok("stale in_transit was cleared", a.in_transit is None, str(a.in_transit))


def test_wages_survive_a_waiting_shift():
    """The money version of the first test, through the engine."""
    world, log, a = setup()
    biz = [b for b in world.businesses.values() if b.type == "Refinery"][0]
    a.location = biz.location
    A.apply_for_job(world, log, a, biz.id)
    A.start_shift(world, log, a, hours=8)
    A.wait(world, log, a, 3600.0)
    start = a.denari

    Engine(
        world, log, policy=NullPolicy(), config=EngineConfig(
            duration_hours=4.0, speed=1e9, checkpoint_every_hours=1e9,
        ),
    ).run()

    earned = a.denari - start
    # 4h at the Refinery Worker rate, less income tax. Anything near zero means
    # the agent was clocked out by its own wait.
    ok("earned a real wage over 4h", earned > 50.0, f"{earned:.2f} denari")


def test_short_waits_are_clamped():
    """A wait under the re-evaluation interval must not buy an extra decision."""
    from convoy import data as D
    world, log, a = setup()
    floor = D.REEVALUATION_INTERVAL_MIN * 60.0

    for asked in (1.0, 5.0, 60.0):
        a.activity = A.Activity("idle", 0.0)
        A.wait(world, log, a, asked)
        ok(
            f"wait({asked:.0f}s) clamped to the {floor:.0f}s interval",
            abs(a.activity.ends_at - (world.sim_time + floor)) < 1e-6,
            f"ends_at={a.activity.ends_at}",
        )

    a.activity = A.Activity("idle", 0.0)
    A.wait(world, log, a, 7200.0)
    ok(
        "a long wait is left alone",
        abs(a.activity.ends_at - (world.sim_time + 7200.0)) < 1e-6,
        f"ends_at={a.activity.ends_at}",
    )


def test_setting_a_wage_does_not_poison_the_price_table():
    """A player business with a wage set must still be observable.

    Wages used to share `retail_prices` with item prices under a "wage:<role>"
    key. The observation walks that dict expecting tradeable items, so the
    first agent to stand next to a player-owned business that had set a wage
    killed the run with KeyError: no base price defined for 'wage:Miner'.
    """
    from convoy import observe as O
    world, log, a = setup()
    a.location = "Copper Gulch" if __import__("convoy.data", fromlist=["d"]).is_spur("Copper Gulch") else a.location
    a.denari = 5000.0

    okc, msg = A.start_business(world, log, a, "Mining Operation", seed_cash=100.0)
    ok("founded a business for the test", okc, msg)
    if not okc:
        return
    biz = world.businesses[a.owned_businesses[-1]]

    ok("wage set", A.set_wage(world, log, a, biz.id, "Miner", 30.0)[0])
    ok("wage is NOT in retail_prices", not any(k.startswith("wage:") for k in biz.retail_prices),
       str(biz.retail_prices))
    ok("wage is in its own dict", biz.wages.get("Miner") == 30.0, str(biz.wages))

    # The call that used to explode.
    try:
        O.render(O.observe(world, log, a, "reevaluation"))
        ok("observing a business with a wage set does not raise", True)
    except Exception as exc:                                  # noqa: BLE001
        ok("observing a business with a wage set does not raise", False, f"{type(exc).__name__}: {exc}")

    # And the wage must still actually be paid to a hire.
    from convoy.state import Agent
    hire = Agent(id="A9999", name="hire", model="rb", location=biz.location)
    world.agents[hire.id] = hire
    okh, msg = A.apply_for_job(world, log, hire, biz.id, "Miner")
    ok("hired at the set wage", okh and abs(hire.current_job[2] - 30.0) < 1e-6, msg)


def test_owned_vehicle_ids_are_observable():
    """An agent must be able to learn the id of a vehicle it owns.

    `mount` takes a vehicle_id and the tool schema tells the model never to
    invent an id -- but the observation never carried one, so all 12 mount
    attempts in the 2026-08-15 run failed with "not your vehicle" and every
    vehicle bought was dead capital.
    """
    from convoy import observe as O
    world, log, a = setup()
    a.denari = 5000.0
    a.location = "Town"
    A.buy_vehicle(world, log, a, "Camel")
    vid = a.owned_vehicles[0]

    rendered = O.render(O.observe(world, log, a, "reevaluation"))
    ok("the vehicle id appears in the observation", vid in rendered, vid)

    okm, msg = A.mount(world, log, a, vid)
    ok("the agent can mount what it can see", okm, msg)
    ok("capacity rose with the mount", a.carry_capacity(world) > 5, str(a.carry_capacity(world)))


def test_a_working_agent_is_not_interrupted():
    """A committed shift must not collect a decision every 15 minutes.

    75% of every action in the 2026-08-15 smoke was an agent answering "still
    working" to a re-evaluation it never needed. Hunger is the exception.
    """
    world, log, a = setup()
    biz = [b for b in world.businesses.values() if b.type == "Refinery"][0]
    a.location = biz.location
    A.apply_for_job(world, log, a, biz.id)
    A.start_shift(world, log, a, hours=8)

    asked: list[str] = []

    class Counting:
        def decide(self, world, agent, reason):
            asked.append(reason)

    Engine(
        world, log, Counting(), EngineConfig(
            duration_hours=6.0, speed=1e9, checkpoint_every_hours=1e9,
        ),
    ).run()
    ok("a fed worker is left alone for 6h", len(asked) == 0, f"{len(asked)} decisions")

    # Hunger must still get through. Drive it through the real clock -- the
    # engine recomputes the stage every tick, so setting the field is not enough.
    a.hours_since_last_meal = 13.0
    a.last_meal_window = 12.0
    asked.clear()
    Engine(
        world, log, Counting(), EngineConfig(
            duration_hours=7.0, speed=1e9, checkpoint_every_hours=1e9,
        ),
    ).run()
    ok("a HUNGRY worker is woken", len(asked) > 0, f"{len(asked)} decisions")


def test_a_finished_shift_can_be_restarted():
    """The guard against restarting a LIVE shift must not block the next one.

    An expired shift keeps kind == "work" until something replaces it, so a
    kind-only check locked an agent out of ever working again -- and the agent
    is woken precisely BECAUSE the shift ended.
    """
    world, log, a = setup()
    biz = [b for b in world.businesses.values() if b.type == "Refinery"][0]
    a.location = biz.location
    A.apply_for_job(world, log, a, biz.id)
    A.start_shift(world, log, a, hours=8)

    okr, msg = A.start_shift(world, log, a, hours=8)
    ok("mid-shift restart is still refused", not okr, msg)

    world.sim_time = 8 * 3600.0          # the shift has just resolved
    okr, msg = A.start_shift(world, log, a, hours=8)
    ok("a finished shift can be started again", okr, msg)
    ok("the new shift runs a full 8h",
       abs(a.activity.ends_at - (world.sim_time + 8 * 3600.0)) < 1e-6,
       f"ends_at={a.activity.ends_at}")


def main() -> int:
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in tests:
        print(f"\n--- {fn.__name__} ---")
        fn()
    print()
    if FAILURES:
        print(f"{len(FAILURES)} FAILURES:")
        for f in FAILURES:
            print(f"  ! {f}")
        return 1
    print("OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
