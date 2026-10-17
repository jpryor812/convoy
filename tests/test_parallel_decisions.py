#!/usr/bin/env python3
"""Agents deciding at the same time, without breaking the world.

`EngineConfig.decision_workers` lets a decision run on a worker thread while the
clock goes on. What has to hold:

- they really do overlap -- otherwise the feature is a slower version of 1;
- no decision is lost, and none is run twice for the same agent at once;
- a decision lands within `max_decision_lag_minutes` of being asked for;
- the event log stays one valid JSON object per line, however many threads
  write to it;
- and 1 worker is still exactly the old, synchronous behaviour.

The "model" here is a stand-in that sleeps outside the world lock, the way a
real one waits on the network, and touches the world only under it.
"""

from __future__ import annotations

import json
import sys
import tempfile
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from convoy.engine import Engine, EngineConfig
from convoy.events import EventLog
from convoy.world_setup import new_world

FAILURES: list[str] = []


def ok(label, condition, detail="") -> None:
    if not condition:
        FAILURES.append(f"{label}{': ' + detail if detail else ''}")


class SlowThinker:
    """A policy that takes `think_s` of wall time per decision."""

    def __init__(self, think_s: float = 0.05):
        import contextlib
        self.world_lock = contextlib.nullcontext()
        self.think_s = think_s
        self.inflight = 0
        self.max_inflight = 0
        self.per_agent_inflight: dict[str, int] = {}
        self.overlap_same_agent = False
        self.records: list[tuple[str, float, float]] = []
        self._guard = threading.Lock()

    def decide(self, world, agent, reason) -> None:
        with self.world_lock:
            asked = world.sim_time
        with self._guard:
            self.inflight += 1
            self.max_inflight = max(self.max_inflight, self.inflight)
            n = self.per_agent_inflight.get(agent.id, 0) + 1
            self.per_agent_inflight[agent.id] = n
            if n > 1:
                self.overlap_same_agent = True
        time.sleep(self.think_s)                  # "waiting on the model"
        with self.world_lock:
            acted = world.sim_time
            agent.denari += 0.0                   # touch the world, under the lock
        with self._guard:
            self.inflight -= 1
            self.per_agent_inflight[agent.id] -= 1
            self.records.append((agent.id, asked, acted))


def _run(workers: int, hours: float = 1.0, think_s: float = 0.05):
    d = tempfile.mkdtemp()
    log = EventLog(Path(d) / "events.jsonl", echo_min=99)
    world = new_world(log, [(f"agent-{i:02d}", "m") for i in range(12)])
    policy = SlowThinker(think_s)
    eng = Engine(world, log, policy, EngineConfig(
        duration_hours=hours, speed=1e9, checkpoint_every_hours=1e9,
        banditry=False, decision_workers=workers, max_decision_lag_minutes=5.0,
    ))
    t0 = time.monotonic()
    try:
        eng.run()
    finally:
        eng.close()
    return policy, time.monotonic() - t0, Path(d) / "events.jsonl", world


def test_decisions_overlap_and_none_is_lost() -> None:
    policy, wall, path, world = _run(workers=8)
    ok("several agents think at once", policy.max_inflight >= 4,
       f"max in flight {policy.max_inflight}")
    ok("never the same agent twice at once", not policy.overlap_same_agent)
    ok("every agent decided at least once",
       {a for a, _, _ in policy.records} == set(world.agents), str(len(policy.records)))
    worst = max((acted - asked for _, asked, acted in policy.records), default=0.0)
    ok("a decision lands within the lag (plus a tick)", worst <= 5 * 60 + 60,
       f"worst lag {worst / 60:.1f} sim-minutes")
    bad = 0
    for line in path.read_text().splitlines():
        try:
            json.loads(line)
        except ValueError:
            bad += 1
    ok("the event log is intact", bad == 0, f"{bad} broken lines")


def test_parallel_is_faster_than_serial() -> None:
    _, serial, _, _ = _run(workers=1, hours=0.5)
    _, parallel, _, _ = _run(workers=8, hours=0.5)
    ok("8 workers beat 1", parallel < serial * 0.7,
       f"serial {serial:.2f}s, parallel {parallel:.2f}s")


def test_one_worker_is_the_old_behaviour() -> None:
    policy, _, _, _ = _run(workers=1, hours=0.5)
    ok("one at a time", policy.max_inflight == 1, str(policy.max_inflight))
    ok("and each decision acts at the moment it was asked",
       all(asked == acted for _, asked, acted in policy.records))


def main() -> int:
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for t in tests:
        t()
    print(f"test_parallel_decisions.py: {len(tests)} tests, {len(FAILURES)} failures")
    for f in FAILURES:
        print(f"  FAIL {f}")
    return 1 if FAILURES else 0


if __name__ == "__main__":
    raise SystemExit(main())
