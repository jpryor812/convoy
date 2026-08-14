#!/usr/bin/env python3
"""Phase 2 — first real agents. A handful of them, on the cheapest model.

The point of this run is NOT economic outcomes. Three agents for a few hours
cannot tell you anything about the economy. It is a harness test, and it is
asking four questions:

  1. Do tool calls come back well-formed and dispatch into the engine?
  2. Does prompt caching actually engage? (The 120-hour run costs ~$66 cached
     and ~$293 uncached against a $94 budget, so this is the number that
     decides whether Phase 3 is affordable at all.)
  3. Do agents do anything COHERENT -- eat before starving, work before
     spending, travel somewhere for a reason?
  4. What do they reach for that does not exist yet?

Spend is bounded two ways: a hard per-agent decision cap, and a small default
roster. At Luna's prices 3 agents x 15 decisions is a fraction of a cent.

    python3 run_phase2.py --dry-run          # build prompts, call nothing
    python3 run_phase2.py                     # 3 agents, 15 decisions each
    python3 run_phase2.py --agents 2 --decisions 10 --model x-ai/grok-4.3

Requires OPENROUTER_API_KEY in the environment (except with --dry-run).
"""

from __future__ import annotations

import argparse
import json
import os
from collections import Counter
from pathlib import Path

from convoy import data as D
from convoy import llm
from convoy.engine import Engine, EngineConfig
from convoy.events import EventLog, Significance
from convoy.state import Agent, World
from convoy.world_setup import new_world

RUN_DIR = Path("runs/phase2")
DEFAULT_MODEL = "openai/gpt-5.6-luna"     # cheapest model with structured outputs


class CappedPolicy(llm.LLMPolicy):
    """LLMPolicy that stops spending once an agent hits its decision cap.

    A hard cap rather than a wall-clock limit, because the cap is what bounds
    the bill and it should be exact, not approximate.
    """

    def __init__(self, *args, cap: int = 15, **kwargs):
        super().__init__(*args, **kwargs)
        self.cap = cap
        self.counts: Counter[str] = Counter()

    def decide(self, world: World, agent: Agent, reason: str) -> None:
        if self.counts[agent.id] >= self.cap:
            return
        self.counts[agent.id] += 1
        n = self.counts[agent.id]
        print(f"  [{world.sim_hour:6.2f}h] {agent.name:<14} decision {n:>2}/{self.cap} ({reason})")
        super().decide(world, agent, reason)

    @property
    def exhausted(self) -> bool:
        return bool(self.counts) and all(v >= self.cap for v in self.counts.values())


def roster(n: int, model: str) -> list[tuple[str, str]]:
    short = model.split("/")[-1]
    return [(f"{short}-{i + 1:02d}", model) for i in range(n)]


def transcript(log: EventLog, world: World) -> None:
    """What each agent actually did, in order."""
    print("\n" + "=" * 74)
    print("WHAT THE AGENTS DID")
    print("=" * 74)
    for agent in world.agents.values():
        events = [
            e for e in log.events
            if e.actor == agent.id
            and e.type not in ("diary", "llm_dry_run")
            and e.significance >= Significance.MEDIUM
        ]
        print(f"\n{agent.name}  (net worth {agent.net_worth(world):,.1f}, "
              f"{agent.denari:,.1f} denari, at {agent.location}, "
              f"{agent.sustenance_stage})")
        if not events:
            print("    -- did nothing --")
        for e in events[:25]:
            bits = " ".join(f"{k}={v}" for k, v in e.detail.items() if k != "text")
            print(f"    [{e.sim_hour:6.2f}h] {e.type:<22} {bits[:90]}")


def harness_report(log: EventLog, policy: CappedPolicy) -> int:
    print("\n" + "=" * 74)
    print("HARNESS")
    print("=" * 74)

    counts = log.counts()
    errors = counts.get("llm_error", 0)
    action_errors = counts.get("action_error", 0)
    reasoning = counts.get("llm_reasoning", 0)

    print(f"\n{policy.summary()}")

    total_actions = sum(u.actions for u in policy.usage.values())
    total_calls = sum(u.calls for u in policy.usage.values())
    print(f"\nactions dispatched : {total_actions}")
    print(f"API calls          : {total_calls}")
    print(f"tool-call failures : {action_errors}")
    print(f"API failures       : {errors}")
    print(f"turns with no action (model chose to think/wait): {reasoning}")

    problems: list[str] = []
    if errors:
        problems.append(f"{errors} API failures -- see llm_error events")
    if total_calls and total_actions == 0:
        problems.append("no actions dispatched at all -- tool calling is not working")

    cached = sum(u.cached_tokens for u in policy.usage.values())
    prompt = sum(u.prompt_tokens for u in policy.usage.values())
    if prompt:
        rate = cached / prompt
        print(f"\ncache hit rate     : {rate:.0%} ({cached:,} of {prompt:,} prompt tokens)")
        if rate < 0.3 and total_calls > 4:
            problems.append(
                f"cache hit rate is only {rate:.0%} -- at this rate the 120-hour run "
                f"costs ~$293 against a $94 budget. Check that the static prefix is "
                f"byte-identical across calls before running Phase 3."
            )
    if action_errors:
        print("\ntool-call failures (these are the schema's problem, not the model's):")
        for e in log.events:
            if e.type == "action_error":
                print(f"    {e.detail.get('action')}: {e.detail.get('error')}")

    if problems:
        print("\nPROBLEMS")
        for p in problems:
            print(f"  ! {p}")
        return 1
    print("\nharness OK")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--agents", type=int, default=3)
    ap.add_argument("--decisions", type=int, default=15, help="hard cap per agent")
    ap.add_argument("--model", default=DEFAULT_MODEL)
    ap.add_argument("--dry-run", action="store_true", help="build prompts, call nothing")
    ap.add_argument("--max-actions", type=int, default=llm.MAX_ACTIONS_PER_DECISION)
    args = ap.parse_args()

    if not args.dry_run and not os.environ.get("OPENROUTER_API_KEY"):
        print("OPENROUTER_API_KEY is not set.\n")
        print("  export OPENROUTER_API_KEY='sk-or-...'\n")
        print("Or run with --dry-run to build prompts without calling the API.")
        return 2

    RUN_DIR.mkdir(parents=True, exist_ok=True)
    log = EventLog(RUN_DIR / "events.jsonl", echo_min=Significance.HIGH)
    world = new_world(log, roster(args.agents, args.model))

    policy = CappedPolicy(
        log=log, cap=args.decisions, dry_run=args.dry_run, max_actions=args.max_actions
    )

    # Decisions land every REEVALUATION_INTERVAL_MIN, so this is the sim time the
    # cap needs. Activity completions wake agents too, hence the headroom -- the
    # cap, not the clock, is what actually stops the run.
    hours = args.decisions * D.REEVALUATION_INTERVAL_MIN / 60.0 * 1.5

    print(f"Phase 2 — {args.agents} agents on {args.model}")
    print(f"{args.decisions} decisions each, up to {args.max_actions} actions per decision")
    print(f"{'DRY RUN — no API calls' if args.dry_run else 'live'}\n")

    Engine(
        world, log, policy,
        EngineConfig(
            duration_hours=hours,
            speed=1e9,                    # no throttling; API latency sets the pace
            checkpoint_every_hours=1e9,
        ),
    ).run()

    transcript(log, world)
    log.export_csv(RUN_DIR / "events.csv")

    if args.dry_run:
        sample = next(
            (e for e in log.events if e.type == "llm_dry_run"), None
        )
        print(f"\ndry run OK — {log.counts().get('llm_dry_run', 0)} prompts built"
              + (f", {sample.detail['prompt_chars']:,} chars each" if sample else ""))
        return 0

    (RUN_DIR / "usage.json").write_text(
        json.dumps({m: vars(u) for m, u in policy.usage.items()}, indent=2),
        encoding="utf-8",
    )
    return harness_report(log, policy)


if __name__ == "__main__":
    raise SystemExit(main())
