#!/usr/bin/env python3
"""The spend cap must bound the bill without killing anybody.

On 2026-08-17, agent A0029 (gpt-5.6-luna-19) hit `decision 400/400` at hour
45.20 -- the same decision on which it last ate. `CappedPolicy.decide` then
returned silently on every wake for the next 36 simulated hours:

    h45.20  cap exhausted, last meal
    h57.20  sustenance_hungry     -- woken, swallowed
    h69.22  sustenance_starving   -- woken, swallowed
    h81.22  starved_to_death, assets_wiped: 2 businesses, 1 vehicle, 775 denari

It was standing at Refinery Row with 1,540 denari the whole time, and had been
the richest agent in the world at hour 58.

This was read at the time as "idle agents have no wake trigger". They have one:
`Engine._decisions` woke it on schedule for all 36 hours, and the engine even
exempts hunger from the "do not interrupt a busy agent" rule for exactly this
reason. The wake was swallowed by the BUDGET GUARD -- a harness artifact
silently corrupting the leaderboard it exists to measure.

So: an agent out of budget still gets a small reserve it may spend only on
staying alive, and is told in the wake reason that that is what it is spending.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from convoy.events import EventLog
from convoy.state import Agent, World

_spec = importlib.util.spec_from_file_location("run_phase2", ROOT / "run_phase2.py")
rp2 = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(rp2)          # type: ignore[union-attr]

FAILURES: list[str] = []
HOUR = 3600.0


def check(label, actual, expected) -> None:
    if actual != expected:
        FAILURES.append(f"{label}: got {actual!r}, expected {expected!r}")


def ok(label, condition, detail="") -> None:
    if not condition:
        FAILURES.append(f"{label}{': ' + detail if detail else ''}")


class RecordingCapped(rp2.CappedPolicy):
    """Counts the decisions that actually reach the model, and their reasons."""

    def __init__(self, log: EventLog, cap: int) -> None:
        super().__init__(log=log, api_key="test-key", cap=cap)
        self.reached: list[str] = []

    def _call(self, agent, messages, tools):
        return None                     # no transport; we only care about arrival

    # `LLMPolicy.decide` records once per decision in a `finally`, so this fires
    # for exactly the wakes the cap did NOT swallow -- carrying the reason string
    # the guard rewrote them to.
    def _remember(self, world, agent, reason, text, did, *, advised=None):
        self.reached.append(reason)


def setup(cap: int = 3):
    w, log = World(), EventLog(None, echo_min=99)
    w.sim_time = 10 * HOUR
    a = Agent(id="A0001", name="Tester", model="test/model", location="Town")
    w.agents[a.id] = a
    return w, log, a, RecordingCapped(log, cap)


def _exhaust(w, a, policy, cap):
    for _ in range(cap):
        policy.decide(w, a, "reevaluation")


def test_cap_still_bounds_normal_spending() -> None:
    w, _log, a, policy = setup(cap=3)
    for _ in range(10):
        policy.decide(w, a, "reevaluation")
    check("cap enforced", policy.counts["A0001"], 3)


def test_a_fed_agent_gets_nothing_past_the_cap() -> None:
    """The reserve is for survival only, not for extra play."""
    w, _log, a, policy = setup(cap=3)
    _exhaust(w, a, policy, 3)
    a.sustenance_stage = "Normal"
    for _ in range(10):
        policy.decide(w, a, "reevaluation")
    check("no reserve spent", policy.reserve_used["A0001"], 0)


def test_a_starving_agent_past_the_cap_is_still_woken() -> None:
    """The regression: this wake used to be swallowed, and the agent died."""
    w, _log, a, policy = setup(cap=3)
    _exhaust(w, a, policy, 3)
    reached_before = len(policy.reached)

    a.sustenance_stage = "Hungry"
    policy.decide(w, a, "reevaluation")

    ok("the wake got through", len(policy.reached) > reached_before)
    check("reserve spent", policy.reserve_used["A0001"], 1)


def test_the_reserve_wake_says_what_it_is_for() -> None:
    """§2: the observation has to carry what the harness already knows.

    An agent told only "reevaluation" would spend its last decisions on business
    admin and starve regardless.
    """
    w, _log, a, policy = setup(cap=3)
    _exhaust(w, a, policy, 3)
    a.sustenance_stage = "Starving"
    policy.decide(w, a, "reevaluation")

    said = policy.reached[-1]
    ok("names the condition", "Starving" in said, said)
    ok("says the budget is gone", "OUT OF DECISIONS" in said, said)
    ok("says how many are left", "emergency decision" in said, said)
    ok("names the stakes", "wipes every business" in said, said)


def test_the_reserve_is_itself_bounded() -> None:
    """A starving agent must not be able to spend the run's budget on panic."""
    w, _log, a, policy = setup(cap=3)
    _exhaust(w, a, policy, 3)
    a.sustenance_stage = "Starving"
    for _ in range(50):
        policy.decide(w, a, "reevaluation")
    check("reserve bounded", policy.reserve_used["A0001"], rp2.SURVIVAL_RESERVE)


def test_exhaustion_is_logged_once() -> None:
    """A statue in the market square should be visible in the log, not inferred."""
    w, log, a, policy = setup(cap=3)
    _exhaust(w, a, policy, 3)
    for _ in range(5):
        policy.decide(w, a, "reevaluation")

    events = [e for e in log.events if e.type == "decision_cap_reached"]
    check("logged exactly once", len(events), 1)
    check("attributed", events[0].actor, "A0001")


def test_reserve_does_not_count_against_exhausted() -> None:
    """`exhausted` ends the run; spending reserve must not un-end it."""
    w, _log, a, policy = setup(cap=3)
    _exhaust(w, a, policy, 3)
    a.sustenance_stage = "Starving"
    policy.decide(w, a, "reevaluation")
    ok("still exhausted", policy.exhausted)


def main() -> int:
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in tests:
        fn()
        print(f"  {fn.__name__}")
    if FAILURES:
        print(f"\nFAIL ({len(FAILURES)})")
        for f in FAILURES:
            print(f"  - {f}")
        return 1
    print(f"\nOK -- {len(tests)} decision-cap tests passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
