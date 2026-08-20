#!/usr/bin/env python3
"""The interrogation backend: load a run, ask its agents questions, advise them.

    python3 serve.py                                  # newest run, port 8000
    python3 serve.py --run runs/phase2/20260818-124204 --port 8080
    python3 serve.py --no-model        # never call a model; recall only

    GET  /run                        summary: hours, agents, decision counts
    GET  /agent/{id}                 milestones, counts, advice it was given
    GET  /agent/{id}/transcript      every recorded decision, with its reason
    GET  /agent/{id}/impact          what changed after advice landed
    GET  /agent/{id}/conversation    what has been said to this agent, and by whom
    POST /agent/{id}/ask             {"question": "...", "who": "..."}
    POST /agent/{id}/advise          {"text": "...", "from_who": "..."}

WHY STDLIB ONLY

This has to run on a school laptop from a git clone. A dependency install is a
failure mode in front of thirty students, and `http.server` is enough for a
read-mostly API serving one classroom.

WHAT `advise` DOES AND DOES NOT DO HERE

It writes a recommendation into the run's checkpoint world and saves it. It does
NOT make time pass -- a finished run is finished, and an endpoint that appeared
to advise a world that can never act on it would be the most misleading thing in
the codebase. Advice queued here is picked up when the world is next stepped
forward (`run_phase2.py --resume`), which is what makes "come back later and see
what changed" possible.
"""

from __future__ import annotations

import argparse
import json
import re
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any

from convoy import advice as ADV
from convoy import checkpoint
from convoy import conversation as CONV
from convoy import inspect as INSPECT
from convoy import interrogate as I
from convoy import llm
from convoy.config import load_env
from convoy.events import EventLog

_AGENT_RE = re.compile(
    r"^/agent/([A-Za-z0-9_]+)(?:/(transcript|ask|advise|impact|conversation))?$"
)


class Backend:
    """Everything the handler needs, built once.

    The event log is reloaded per request rather than cached: a run that is
    still going should be answerable WHILE it goes, and an 84-hour run is a few
    megabytes. Correctness over a saved millisecond.
    """

    def __init__(self, run_path: Path, use_model: bool, model: str) -> None:
        self.run_path = run_path
        self.model = model
        self.policy = None
        if use_model:
            load_env()
            try:
                self.policy = llm.LLMPolicy(
                    log=EventLog(None, echo_min=99),
                    max_completion_tokens=I.ANSWER_TOKENS,
                    # Answering is interactive; a student waiting on a
                    # reply must not be held behind the simulation's
                    # per-model pacing.
                    requests_per_minute=0,
                )
            except RuntimeError as exc:
                # No key is a downgrade, not a failure: every lookup still works
                # and only synthesis is lost. Said out loud so it is not a
                # mystery when answers stop being summarised.
                print(f"  no model available ({exc}); recall-only")

    def run(self) -> I.Run:
        return I.Run.load(self.run_path)

    def conversations(self) -> CONV.ConversationStore:
        # Reloaded per request rather than held, so a second process (or a
        # restarted server) sees the same history. Small file, cheap read.
        return CONV.ConversationStore.load(self.run_path)

    def ask(self, agent_id: str, question: str, who: str) -> dict[str, Any]:
        """Answer, then remember having answered.

        The exchange is stored whatever the outcome, "nothing in my record"
        included: a follow-up needs to know the last question landed badly, and
        a teacher reviewing a session needs to see what was asked, not only what
        could be answered.
        """
        run = self.run()
        store = self.conversations()
        ans = I.answer(
            run, agent_id, question,
            policy=self.policy, model=self.model,
            history=store.history(agent_id, who=who),
        )
        store.add(agent_id, CONV.Exchange(
            hour=run.hours(), who=who, question=question,
            answer=ans.text, kind=ans.kind, model_called=ans.model_called,
        ))
        return {"agent": agent_id, "question": question, "who": who, **ans.as_dict()}

    # -- what the map shows when you click something -------------------------

    def cards(self) -> dict[str, Any]:
        """Every clickable panel, off the run's own checkpoint.

        The checkpoint rather than the event log, because a panel is a
        SNAPSHOT -- what this business holds and what that agent is doing right
        now -- and reconstructing present state by replaying events is both
        slower and a second implementation of something `checkpoint` already
        does exactly. `advise` reads the same file for the same reason.

        Loaded per request, not cached: a run that is still going should answer
        with where it has got to, not where it was when the server started.
        """
        path = self.run_path / "checkpoint.json"
        if not path.exists():
            return {"error": "this run has no checkpoint, so it has no state to show"}
        world = checkpoint.load(path)
        return {
            "hour": round(world.sim_hour, 2),
            "cards": INSPECT.cards(world),
        }

    # -- advice ------------------------------------------------------------

    def advise(self, agent_id: str, text: str, from_who: str) -> dict[str, Any]:
        path = self.run_path / "checkpoint.json"
        if not path.exists():
            return {"error": "this run has no checkpoint, so it cannot be advised"}
        world = checkpoint.load(path)
        log = EventLog(self.run_path / "events.jsonl", echo_min=99)
        rec = ADV.give(world, log, agent_id, text, from_who=from_who)
        log.flush()
        if rec is None:
            return {"error": f"{agent_id} cannot be advised (unknown, dead, or empty advice)"}
        checkpoint.save(world, path)
        return {
            "queued": True,
            "advice_id": rec.id,
            "agent": agent_id,
            "at_hour": rec.given_at_hour,
            "expires_at_hour": round(rec.expires_at_hour(), 2),
            "note": (
                "Queued into the saved world. It reaches the agent the next time "
                "the world is stepped forward; nothing has happened yet."
            ),
        }

    # -- impact ------------------------------------------------------------

    def impact(self, agent_id: str) -> dict[str, Any]:
        """What measurably changed after advice landed, and what did not.

        Built from `Snapshot`, taken at the instant each recommendation was
        given (see `convoy/state.py`). Reported as a DELTA and nothing more:
        this function does not claim the advice caused the change, because
        nothing here ran the world twice. A before and an after with the whole
        leaderboard in both is enough for a student to argue about, which is the
        exercise; a causal claim would be a fabrication wearing a number.
        """
        path = self.run_path / "checkpoint.json"
        if not path.exists():
            return {"error": "this run has no checkpoint"}
        world = checkpoint.load(path)
        agent = world.agents.get(agent_id)
        if agent is None:
            return {"error": f"no agent {agent_id}"}

        now = ADV.take_snapshot(world)
        out = []
        for rec in agent.inbox:
            before = rec.before
            if before is None:
                continue
            others = sorted(
                (
                    {
                        "id": oid,
                        "before": before.net_worth[oid],
                        "after": now.net_worth.get(oid),
                        "change": (
                            round(now.net_worth[oid] - before.net_worth[oid], 2)
                            if oid in now.net_worth else None
                        ),
                    }
                    for oid in before.net_worth if oid != agent_id
                ),
                key=lambda r: (r["change"] is None, -(r["change"] or 0)),
            )
            out.append({
                "advice_id": rec.id,
                "text": rec.text,
                "given_at_hour": rec.given_at_hour,
                "delivered": rec.times_seen > 0,
                "first_seen_hour": rec.first_seen_hour,
                "advised_agent": {
                    "before": before.net_worth.get(agent_id),
                    "after": now.net_worth.get(agent_id),
                    "change": (
                        round(now.net_worth[agent_id] - before.net_worth[agent_id], 2)
                        if agent_id in now.net_worth and agent_id in before.net_worth
                        else None
                    ),
                    "businesses_before": before.businesses.get(agent_id),
                    "businesses_after": now.businesses.get(agent_id),
                },
                # The honest ancestor of "would have gone bankrupt": how many
                # hours of payroll each business's cash covered at the moment
                # the advice landed. A projection, and labelled as one.
                "payroll_runway_at_the_time": before.runway_hours,
                "everyone_else": others,
                "caveat": (
                    "These are differences over the same period, not effects of "
                    "the advice. The world was not run twice, so nothing here "
                    "shows what would have happened otherwise."
                ),
            })
        return {"agent": agent_id, "hour_now": now.hour, "advice": out}


def _handler(backend: Backend):
    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def _send(self, payload: Any, status: int = 200) -> None:
            body = json.dumps(payload, indent=1, default=str).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            # A classroom front end will be served from somewhere else.
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Access-Control-Allow-Headers", "Content-Type")
            self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, fmt: str, *args) -> None:
            print(f"  {self.address_string()} {fmt % args}")

        def do_OPTIONS(self) -> None:                       # noqa: N802
            self._send({}, 204)

        def do_GET(self) -> None:                           # noqa: N802
            if self.path in ("/", "/run"):
                return self._send(backend.run().summary())
            if self.path == "/cards":
                return self._send(backend.cards())
            m = _AGENT_RE.match(self.path)
            if not m:
                return self._send({"error": f"no route {self.path}"}, 404)
            agent_id, tail = m.group(1), m.group(2)
            run = backend.run()
            if agent_id not in run.by_agent:
                return self._send({"error": f"no agent {agent_id} in this run"}, 404)
            if tail == "transcript":
                return self._send({
                    "agent": agent_id,
                    "decisions": [c.as_dict() for c in run.decisions(agent_id)],
                })
            if tail == "impact":
                return self._send(backend.impact(agent_id))
            if tail == "conversation":
                store = backend.conversations()
                return self._send({
                    "agent": agent_id,
                    "exchanges": [
                        vars(e) for e in store.by_agent.get(agent_id, [])
                    ],
                })
            if tail in (None, ""):
                return self._send(run.agent_state(agent_id))
            return self._send({"error": f"{tail} is a POST"}, 405)

        def do_POST(self) -> None:                          # noqa: N802
            m = _AGENT_RE.match(self.path)
            if not m or m.group(2) not in ("ask", "advise"):
                return self._send({"error": f"no route {self.path}"}, 404)
            agent_id, tail = m.group(1), m.group(2)
            try:
                length = int(self.headers.get("Content-Length") or 0)
                payload = json.loads(self.rfile.read(length) or b"{}")
            except (ValueError, json.JSONDecodeError) as exc:
                return self._send({"error": f"bad JSON: {exc}"}, 400)

            if tail == "advise":
                text = str(payload.get("text") or "")
                who = str(payload.get("from_who") or "a student")
                return self._send(backend.advise(agent_id, text, who))

            question = str(payload.get("question") or "").strip()
            if not question:
                return self._send({"error": "no question"}, 400)
            if agent_id not in backend.run().by_agent:
                return self._send({"error": f"no agent {agent_id} in this run"}, 404)
            who = str(payload.get("who") or "a student")
            return self._send(backend.ask(agent_id, question, who))

    return Handler


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--run", type=Path, default=None, help="run dir; default newest")
    ap.add_argument("--port", type=int, default=8000)
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--model", default="openai/gpt-5.6-luna")
    ap.add_argument(
        "--no-model", action="store_true",
        help="never call a model. Every lookup still works; synthesis questions "
             "return the retrieved record instead of a summary of it.",
    )
    args = ap.parse_args()

    run_path = args.run or I.newest_run()
    backend = Backend(run_path, use_model=not args.no_model, model=args.model)
    summary = backend.run().summary()
    print(f"run      : {run_path}")
    print(f"           {summary['sim_hours']}h, {len(summary['agents'])} agents, "
          f"{summary['events']} events")
    print(f"model    : {'off (recall only)' if backend.policy is None else args.model}")
    print(f"listening: http://{args.host}:{args.port}/run\n")

    HTTPServer((args.host, args.port), _handler(backend)).serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
