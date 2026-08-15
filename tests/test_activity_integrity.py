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
