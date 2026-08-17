#!/usr/bin/env python3
"""Print one agent's decision transcript from a finished run.

This is the readable half of what an interrogation interface needs: the ordered
list of what an agent did, why it said it was doing it, and what the world did
back. Until reasoning capture landed on 2026-08-17 the "why" column did not
exist -- `llm_reasoning` fired on turns where the agent chose NOT to act, twice
in 6,916 calls -- so any answer to "why did you do that?" was confabulated.

    python3 show_agent.py                       # newest run, list the agents
    python3 show_agent.py A0013                 # newest run, one agent
    python3 show_agent.py A0013 --run runs/phase2/20260817-004401
    python3 show_agent.py A0013 --from 40 --to 60
    python3 show_agent.py A0013 --full          # untruncated reasoning
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

RUN_DIR = Path("runs/phase2")


def newest_run() -> Path:
    runs = [d for d in RUN_DIR.iterdir() if (d / "events.jsonl").exists()]
    if not runs:
        raise SystemExit(f"no runs with an events.jsonl under {RUN_DIR}")
    return max(runs, key=lambda d: d.stat().st_mtime)


def load(run: Path) -> list[dict]:
    with (run / "events.jsonl").open(encoding="utf-8") as fh:
        return [json.loads(line) for line in fh if line.strip()]


def list_agents(events: list[dict]) -> None:
    """Who is worth looking at, and how much there is to see."""
    seen: dict[str, dict] = {}
    for e in events:
        actor = e.get("actor")
        if not actor or not actor.startswith("A"):
            continue
        row = seen.setdefault(actor, {"decisions": 0, "actions": 0, "last": 0.0})
        if e["type"] == "llm_reasoning":
            row["decisions"] += 1
        elif e["type"] == "action_call":
            row["actions"] += 1
        row["last"] = max(row["last"], e["sim_time"] / 3600.0)

    print(f"{'agent':<8}{'decisions':>11}{'actions':>9}{'last seen':>11}")
    for agent, row in sorted(seen.items()):
        print(f"{agent:<8}{row['decisions']:>11}{row['actions']:>9}{row['last']:>10.2f}h")
    print("\nPick one:  python3 show_agent.py <agent id>")


def transcript(events: list[dict], agent: str, lo: float, hi: float, full: bool) -> None:
    # Notable outcomes are interleaved with the decisions that caused them, so a
    # reader can see intent and consequence in one pass rather than holding two
    # timelines in their head.
    outcomes = {
        "business_founded", "business_bankrupt", "business_closed", "hired", "fired",
        "quit_job", "job_started", "job_posted", "job_applied", "ate",
        "sustenance_hungry", "sustenance_starving", "starved_to_death",
        "assets_wiped", "decision_cap_reached", "bankruptcy_warning",
    }
    rows = [
        e for e in events
        if (e.get("actor") == agent or e.get("subject") == agent)
        and (e["type"] in ("llm_reasoning",) or e["type"] in outcomes)
        and lo <= e["sim_time"] / 3600.0 <= hi
    ]
    if not rows:
        print(f"nothing for {agent} in hours {lo}-{hi}")
        return

    decisions = 0
    for e in rows:
        hour = e["sim_time"] / 3600.0
        d = e.get("detail", {})
        if e["type"] != "llm_reasoning":
            print(f"  h{hour:6.2f}  ->  {e['type']}  {json.dumps(d)[:100]}")
            continue

        decisions += 1
        print(f"\nh{hour:6.2f}  DECISION {decisions}   (woken: {d.get('woken_because', '?')})")
        print(f"  did : {d.get('did', '')}")
        text = (d.get("text") or "").replace("\n", "\n        ")
        if not full and len(text) > 400:
            text = text[:400] + " ..."
        print(f"  why : {text}")

    print(f"\n{decisions} decisions for {agent} between hours {lo:g} and {hi:g}.")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("agent", nargs="?", help="agent id, e.g. A0013. Omit to list agents.")
    ap.add_argument("--run", type=Path, help="run directory; default is the newest")
    ap.add_argument("--from", dest="lo", type=float, default=0.0, help="first sim hour")
    ap.add_argument("--to", dest="hi", type=float, default=float("inf"), help="last sim hour")
    ap.add_argument("--full", action="store_true", help="do not truncate reasoning")
    args = ap.parse_args()

    run = args.run or newest_run()
    events = load(run)
    print(f"run: {run}  ({len(events)} events)\n")

    if not args.agent:
        list_agents(events)
        return 0
    transcript(events, args.agent, args.lo, args.hi, args.full)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
