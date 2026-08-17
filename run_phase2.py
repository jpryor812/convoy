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
import time
from collections import Counter
from pathlib import Path

from convoy import checkpoint, chronicle
from convoy import data as D
from convoy import llm
from convoy.config import load_env
from convoy.engine import Engine, EngineConfig
from convoy.events import EventLog, Significance
from convoy.state import Agent, World
from convoy.world_setup import new_world

RUN_DIR = Path("runs/phase2")
DEFAULT_MODEL = "openai/gpt-5.6-luna"     # cheapest model with structured outputs


# Decisions held back so that running out of budget cannot kill an agent.
# Small: this is enough to walk to a tavern and eat, not enough to keep playing.
SURVIVAL_RESERVE = 6


class CappedPolicy(llm.LLMPolicy):
    """LLMPolicy that stops spending once an agent hits its decision cap.

    A hard cap rather than a wall-clock limit, because the cap is what bounds
    the bill and it should be exact, not approximate.

    THE CAP MUST NOT BE ABLE TO KILL ANYONE. On 2026-08-17 agent A0029 hit
    400/400 at hour 45.20 and this method silently returned on every wake after
    that -- including the wakes for Hungry and Starving. It stood at Refinery
    Row with 1,540 denari, starved at hour 81, and `assets_wiped` destroyed 775
    denari of businesses. It had been the richest agent in the world at hour 58.

    That was read at the time as "idle agents have no wake trigger". They do:
    `Engine._decisions` woke it on schedule for all 36 hours. The wake was
    swallowed here, by the budget guard -- a harness artifact corrupting the
    leaderboard it exists to measure. So a starving agent keeps a small reserve
    it can only spend on staying alive, and is told that is what it is spending.
    """

    def __init__(self, *args, cap: int = 15, **kwargs):
        super().__init__(*args, **kwargs)
        self.cap = cap
        self.counts: Counter[str] = Counter()
        self.reserve_used: Counter[str] = Counter()
        self._announced: set[str] = set()

    def decide(self, world: World, agent: Agent, reason: str) -> None:
        if self.counts[agent.id] >= self.cap:
            if agent.id not in self._announced:
                self._announced.add(agent.id)
                self.log.emit(
                    world.sim_time, "decision_cap_reached", actor=agent.id,
                    significance=Significance.MEDIUM,
                    cap=self.cap, reserve=SURVIVAL_RESERVE,
                )
            # Out of budget for playing the game, but not for staying alive.
            if agent.sustenance_stage == "Normal":
                return
            if self.reserve_used[agent.id] >= SURVIVAL_RESERVE:
                return
            self.reserve_used[agent.id] += 1
            left = SURVIVAL_RESERVE - self.reserve_used[agent.id]
            # Say it plainly. An agent told only "reevaluation" would spend the
            # reserve on business admin and starve anyway -- the §2 lesson: the
            # observation has to carry what the harness already knows.
            reason = (
                f"you are {agent.sustenance_stage} AND OUT OF DECISIONS for this "
                f"run. You have {left} emergency decision(s) left, ever. Nothing "
                f"matters except eating: buy a meal or eat what you carry NOW. "
                f"Dying wipes every business, vehicle and coin you own."
            )
            print(f"  [{world.sim_hour:6.2f}h] {agent.name:<14} RESERVE {left} left ({agent.sustenance_stage})")
            super().decide(world, agent, reason)
            return

        self.counts[agent.id] += 1
        n = self.counts[agent.id]
        print(f"  [{world.sim_hour:6.2f}h] {agent.name:<14} decision {n:>2}/{self.cap} ({reason})")
        super().decide(world, agent, reason)

    @property
    def exhausted(self) -> bool:
        return bool(self.counts) and all(v >= self.cap for v in self.counts.values())


def roster(n: int, models: list[str]) -> list[tuple[str, str]]:
    """Deal n agents round-robin across the models.

    Round-robin rather than blocked, so that a run cut short still has a
    balanced population instead of every agent of the last model missing.
    """
    out: list[tuple[str, str]] = []
    per: Counter[str] = Counter()
    for i in range(n):
        model = models[i % len(models)]
        per[model] += 1
        out.append((f"{model.split('/')[-1]}-{per[model]:02d}", model))
    return out


def _announce_done(run_dir: Path, status: str) -> None:
    """Say the run is over without anyone having to watch for it.

    A marker file is the durable signal; the desktop notification is the one
    that actually reaches someone. Neither may raise -- the run has already
    finished by the time this is called, and losing the results to a failed
    notification would be absurd.
    """
    try:
        (run_dir / "DONE").write_text(status + "\n", encoding="utf-8")
    except OSError:
        pass
    try:
        import subprocess
        subprocess.run(
            ["osascript", "-e",
             f'display notification "{status}" with title "Convoy run finished"'],
            check=False, capture_output=True, timeout=10,
        )
    except Exception:                                  # noqa: BLE001
        pass


def _checkpoint_hook(world: World, log: EventLog, run_dir: Path, day_hours: float):
    """Save state AND write the digest on the same hourly beat.

    Chronicling must never take the run down at hour 60, so a broken digest
    degrades to a note in the log while the checkpoint still lands.
    """
    chronicler = chronicle.Chronicler(
        world, log, run_dir / "chronicle.md", day_hours,
    )

    def hook(w: World) -> None:
        checkpoint.save(w, run_dir / "checkpoint.json")
        try:
            chronicler(w)
        except Exception as exc:                       # noqa: BLE001
            print(f"  [chronicle failed: {type(exc).__name__}: {exc}]", flush=True)

    return hook


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

    # Question 4 -- what agents REACH FOR. An engine refusal is not an error, so
    # it shows up nowhere else, and it is the most informative thing in the run:
    # it is an agent saying what it wanted and the world saying no.
    calls = [e for e in log.events if e.type == "action_call"]
    if calls:
        tried = Counter(e.detail["action"] for e in calls)
        print("\nwhat agents reached for:")
        for name, n in tried.most_common():
            refused = sum(
                1 for e in calls if e.detail["action"] == name and not e.detail["ok"]
            )
            mark = f"  ({refused} refused)" if refused else ""
            print(f"    {n:>4}  {name}{mark}")

        reasons = Counter(
            e.detail["detail_text"] for e in calls if not e.detail["ok"]
        )
        if reasons:
            print("\nwhy the world said no:")
            for reason, n in reasons.most_common():
                print(f"    {n:>4}  {reason}")

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
    ap.add_argument(
        "--model", default=DEFAULT_MODEL,
        help="comma-separated; agents are dealt round-robin across them",
    )
    ap.add_argument(
        "--hours", type=float, default=None,
        help="simulated duration. Default: whatever the decision cap needs.",
    )
    ap.add_argument(
        "--rpm", type=float, default=llm.REQUESTS_PER_MINUTE,
        help="request pacing; raise once the account is off new-account limits",
    )
    ap.add_argument(
        "--time-scale", type=float, default=1.0,
        help="multiply every PRODUCTION time by this (0.2 = five times faster). "
             "Costs nothing: production is continuous inside a shift, so it "
             "creates no extra decisions -- measured, 5x the goods for an "
             "identical 961 decisions. Use it to exercise the supply chain in a "
             "short run. NOT for economics: wages are per simulated hour, so "
             "scaling output makes labour artificially cheap.",
    )
    ap.add_argument(
        "--day-hours", type=float, default=24.0,
        help="simulated hours between full daily digests",
    )
    ap.add_argument("--dry-run", action="store_true", help="build prompts, call nothing")
    ap.add_argument("--max-actions", type=int, default=llm.MAX_ACTIONS_PER_DECISION)
    ap.add_argument(
        "--max-tokens", type=int, default=llm.MAX_COMPLETION_TOKENS,
        help="completion ceiling. OpenRouter reserves this against the key's "
             "remaining limit, so a high ceiling on a capped key causes 402s.",
    )
    args = ap.parse_args()

    load_env()
    if not args.dry_run and not os.environ.get("OPENROUTER_API_KEY"):
        print("OPENROUTER_API_KEY is not set.\n")
        print("Either create a .env file at the repo root:\n")
        print("    cp .env.example .env      # then edit it and paste your key\n")
        print("or export it for this shell:\n")
        print("    export OPENROUTER_API_KEY='sk-or-...'\n")
        print("Or run with --dry-run to build prompts without calling the API.")
        return 2

    models = [m.strip() for m in args.model.split(",") if m.strip()]

    if args.time_scale != 1.0:
        # Deliberately a runtime knob, never an edit to data.py: the numbers in
        # PHASE2.md and the generated reference must keep describing the real
        # economy, and a temporary multiplier left in a data file would not.
        D.CRAFT_TIME_COEFFICIENT *= args.time_scale

    # One directory per run. The log opens in append mode, so a shared file
    # silently interleaves runs with only sim_start to tell them apart -- which
    # made the first live runs painful to read back.
    stamp = time.strftime("%Y%m%d-%H%M%S")
    run_dir = RUN_DIR / stamp
    run_dir.mkdir(parents=True, exist_ok=True)
    log = EventLog(run_dir / "events.jsonl", echo_min=Significance.HIGH)
    world = new_world(log, roster(args.agents, models))

    policy = CappedPolicy(
        log=log, cap=args.decisions, dry_run=args.dry_run,
        max_actions=args.max_actions, requests_per_minute=args.rpm,
        max_completion_tokens=args.max_tokens,
    )

    # Decisions land every REEVALUATION_INTERVAL_MIN, so this is the sim time the
    # cap needs. Activity completions wake agents too, hence the headroom -- the
    # cap, not the clock, is what actually stops the run.
    hours = (
        args.hours if args.hours is not None
        else args.decisions * D.REEVALUATION_INTERVAL_MIN / 60.0 * 1.5
    )

    print(f"Phase 2 — {args.agents} agents on {', '.join(models)}")
    print(f"{args.decisions} decisions each, up to {args.max_actions} actions per decision")
    print(f"{hours:.1f} simulated hours, pacing {args.rpm:g} req/min")
    if args.time_scale != 1.0:
        print(f"PRODUCTION TIMES SCALED x{args.time_scale:g} -- throughput only, "
              f"not a balanced economy")
    print(f"{'DRY RUN — no API calls' if args.dry_run else 'live'}\n")

    Engine(
        world, log, policy,
        EngineConfig(
            duration_hours=hours,
            speed=1e9,                    # no throttling; API latency sets the pace
            # A multi-hour wall-clock run must survive a crash. Run 2 of the
            # first live session died to a connection reset at 1.5 sim-hours
            # with nothing recoverable.
            checkpoint_every_hours=1.0 if not args.dry_run else 1e9,
        ),
        on_checkpoint=None if args.dry_run else _checkpoint_hook(
            world, log, run_dir, args.day_hours
        ),
    ).run()

    transcript(log, world)
    log.export_csv(run_dir / "events.csv")

    if args.dry_run:
        sample = next(
            (e for e in log.events if e.type == "llm_dry_run"), None
        )
        print(f"\ndry run OK — {log.counts().get('llm_dry_run', 0)} prompts built"
              + (f", {sample.detail['prompt_chars']:,} chars each" if sample else ""))
        return 0

    (run_dir / "usage.json").write_text(
        json.dumps({m: vars(u) for m, u in policy.usage.items()}, indent=2),
        encoding="utf-8",
    )
    rc = harness_report(log, policy)
    spend = sum(u.cost for u in policy.usage.values())
    _announce_done(
        run_dir,
        f"{'harness OK' if rc == 0 else 'finished with problems'} — "
        f"{args.agents} agents, {hours:.0f}h, ${spend:.2f}",
    )
    print(f"\nrun directory: {run_dir}")
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
