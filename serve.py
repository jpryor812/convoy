#!/usr/bin/env python3
"""The interrogation backend: load a run, ask its agents questions, advise them.

    python3 serve.py                                  # newest run, port 8000
    python3 serve.py --run runs/phase2/20260818-124204 --port 8080
    python3 serve.py --no-model        # never call a model; recall only

    # THE PUBLIC FRONT DOOR: follow whatever is running, fall back to a chosen
    # past run when nothing is, take emails, and cap what strangers can spend.
    python3 serve.py --public --host 0.0.0.0 --port 8000 \
        --showcase runs/phase2/20260821-232951

    GET  /                           the map itself, talking back to this server
    GET  /status                     is a simulation running right now?
    GET  /replay                     the map's data, for a page keeping up live
    POST /waitlist                   {"email": "..."} -- notify me next time
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
import base64
import gzip
import hashlib
import hmac
import json
import os
import secrets
import re
import threading
import time
from collections import defaultdict, deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
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

# A run counts as LIVE while its event log is still being written. Twenty agents
# at 9x realtime write many events a minute; five quiet minutes means the engine
# has stopped, crashed, or lost its key -- and in every one of those cases
# telling a visitor "live" would be a lie.
LIVE_WINDOW_S = 300

# How long a built page or payload is reused for a run that is still changing.
# A live run's log changes every second; rebuilding the map for every visitor's
# every poll would spend the machine on serialising the same picture.
REBUILD_EVERY_S = 20

_EMAIL_RE = re.compile(r"^[^@\s]{1,64}@[^@\s]{1,189}\.[^@\s]{2,}$")

_AGENT_RE = re.compile(
    r"^/agent/([A-Za-z0-9_]+)(?:/(transcript|ask|advise|impact|conversation))?$"
)


class Backend:
    """Everything the handler needs, built once.

    The event log is reloaded per request rather than cached: a run that is
    still going should be answerable WHILE it goes, and an 84-hour run is a few
    megabytes. Correctness over a saved millisecond.
    """

    def __init__(self, run_path: Path | None, use_model: bool, model: str, *,
                 runs_root: Path | None = None, showcase: Path | None = None,
                 public: bool = False, allow_advise: bool = True,
                 waitlist: Path = Path("waitlist.jsonl"),
                 asks_per_day: int = 5, asks_per_ip_per_day: int = 100,
                 model_calls_per_day: int = 0,
                 live_window_s: int = LIVE_WINDOW_S) -> None:
        # A FIXED run, or FOLLOW the newest under `runs_root`. Following is what
        # a public site wants: start the next simulation and the page is on it,
        # with nobody restarting the server.
        self._fixed = run_path
        self.runs_root = runs_root
        self.showcase = showcase
        self.public = public
        self.allow_advise = allow_advise
        self.waitlist = waitlist
        self.asks_per_day = asks_per_day
        self.asks_per_ip_per_day = asks_per_ip_per_day
        self.model_calls_per_day = model_calls_per_day
        self._usage: dict | None = None
        self.live_window_s = live_window_s
        self._lock = threading.Lock()
        # RE-ENTRANT, and separate. Building the page builds the payload
        # through the same cache, so a plain Lock deadlocked on the very first
        # request; and a build that takes a second must not hold up someone
        # joining the waitlist.
        self._build_lock = threading.RLock()
        self._secret_lock = threading.Lock()
        self.trust_proxy = False
        # The run THIS request is about, when the page says. Thread-local
        # because the server is threaded and two visitors can be watching two
        # different runs at the same moment.
        self._req = threading.local()
        self._cache: dict[str, tuple[float, Any, Any]] = {}
        self._hits: dict[tuple[str, str], deque] = defaultdict(deque)
        self._model_day = (time.strftime("%Y-%m-%d"), 0)
        self.model = model
        self.policy = None
        if use_model:
            load_env()
            try:
                # A PUBLIC SERVER SPENDS FROM ITS OWN KEY when one is set.
                # The daily ceiling is this code's promise; a separate key with
                # a small limit on OpenRouter is the promise that holds even if
                # this code is wrong.
                public_key = os.environ.get("OPENROUTER_PUBLIC_API_KEY")
                if public and not public_key:
                    load_env()
                    public_key = os.environ.get("OPENROUTER_PUBLIC_API_KEY")
                self.policy = llm.LLMPolicy(
                    api_key=(public_key or None) if public else None,
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

    # -- which run, and whether it is live ---------------------------------

    def _newest(self) -> Path | None:
        root = self.runs_root
        if root is None or not root.exists():
            return None
        runs = [d for d in root.iterdir() if (d / "events.jsonl").exists()]
        return max(runs, key=lambda d: (d / "events.jsonl").stat().st_mtime,
                   default=None)

    def _is_live(self, run: Path | None) -> bool:
        if run is None:
            return False
        age = time.time() - (run / "events.jsonl").stat().st_mtime
        return age < self.live_window_s

    @property
    def run_path(self) -> Path:
        """The run every endpoint answers about.

        Fixed if `--run` was given. Otherwise the newest run while it is live,
        and the showcase -- the past run worth showing a stranger -- when nothing
        is. Falling back to "newest" would put whatever ten-minute smoke test ran
        last in front of the public.
        """
        pinned = getattr(self._req, "run", None)
        if pinned is not None:
            return pinned
        if self._fixed is not None:
            return self._fixed
        newest = self._newest()
        if self._is_live(newest):
            return newest
        if self.showcase is not None:
            return self.showcase
        if newest is None:
            raise SystemExit(f"no runs under {self.runs_root}")
        return newest

    def pin(self, name: str | None) -> bool:
        """Answer this request about the run the page is showing.

        WITHOUT THIS, A QUESTION COULD LAND IN THE WRONG WORLD. When a live run
        ends the server falls back to the showcase, and a visitor still watching
        the run that just finished would have their question answered by the
        showcase's agent of the same id -- ids are reused from run to run.

        Matched against the runs actually on disk by NAME, never joined onto a
        path, so `?run=../../etc` names nothing.
        """
        self._req.run = None
        if not name:
            return True
        known = []
        if self._fixed is not None:
            known.append(self._fixed)
        if self.showcase is not None:
            known.append(self.showcase)
        if self.runs_root is not None and self.runs_root.exists():
            known += [d for d in self.runs_root.iterdir()
                      if (d / "events.jsonl").exists()]
        for d in known:
            if d.name == name:
                self._req.run = d
                return True
        return False

    def _cached(self, key: str, stamp: Any, build):
        """Reuse a build while its source is unchanged, and for a short while
        even when it has changed, so a live run is rebuilt at most every few
        seconds however many people are watching."""
        with self._build_lock:
            hit = self._cache.get(key)
            now = time.time()
            if hit and (hit[1] == stamp or now - hit[0] < REBUILD_EVERY_S):
                return hit[2]
            value = build()
            self._cache[key] = (now, stamp, value)
            return value

    def _stamp(self, run: Path) -> tuple:
        ev = (run / "events.jsonl").stat()
        return (str(run), ev.st_mtime, ev.st_size)

    def run(self) -> I.Run:
        return I.Run.load(self.run_path)

    def status(self) -> dict[str, Any]:
        self._req.run = None
        newest = self._newest() if self._fixed is None else self._fixed
        live = self._is_live(newest)
        run = self.run_path
        payload = self.payload(run)
        return {
            "live": live,
            "run": run.name,
            "hour": payload.get("end_hour", 0),
            "agents": len(payload.get("agents", [])),
            "can_advise": self.allow_advise,
            "needs_pass": self.public,
            "seconds_since_activity": (
                round(time.time() - (newest / "events.jsonl").stat().st_mtime)
                if newest is not None else None
            ),
        }

    # -- the map ------------------------------------------------------------

    def payload(self, run: Path | None = None) -> dict[str, Any]:
        import preview_world as PW
        run = run or self.run_path
        return self._cached(f"payload:{run}", self._stamp(run),
                            lambda: PW.build_payload(run))

    def page(self) -> bytes:
        import preview_world as PW
        run = self.run_path
        return self._cached(
            f"page:{run}", self._stamp(run),
            lambda: PW.render_html(self.payload(run), served=True).encode("utf-8"),
        )

    def replay_bytes(self) -> bytes:
        run = self.run_path
        return self._cached(f"replay:{run}", self._stamp(run),
                            lambda: json.dumps(self.payload(run)).encode("utf-8"))

    # -- the public's limits ------------------------------------------------

    def allow(self, key: str, what: str, limit: int, window_s: int = 3600) -> bool:
        """A sliding window per visitor per kind of request. In memory: a
        restart forgives everyone, which is fine for a waitlist form and a
        per-connection backstop. The per-EMAIL question allowance is not kept
        here -- see `take_question`."""
        if not self.public or limit <= 0:
            return True
        with self._lock:
            q = self._hits[(key, what)]
            now = time.time()
            while q and now - q[0] > window_s:
                q.popleft()
            if len(q) >= limit:
                return False
            q.append(now)
            return True

    def take_question(self, email: str) -> int | None:
        """Spend one of this address's questions for today.

        Returns how many are left after this one, or None if it had none left.
        ON DISK, beside the waitlist, so "five a day" means five a day and not
        five per server restart -- `go_live.py` restarts the server every
        session. A calendar day on this machine's clock, not a sliding 24h:
        "come back tomorrow" should mean tomorrow.
        """
        if not self.public or self.asks_per_day <= 0:
            return self.asks_per_day
        path = self.waitlist.with_suffix(".usage.json")
        today = time.strftime("%Y-%m-%d")
        with self._lock:
            if self._usage is None:
                try:
                    self._usage = json.loads(path.read_text())
                except (OSError, ValueError):
                    self._usage = {}
            if self._usage.get("day") != today:
                self._usage = {"day": today, "used": {}}
            used = self._usage["used"].get(email, 0)
            if used >= self.asks_per_day:
                return None
            self._usage["used"][email] = used + 1
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(self._usage))
            return self.asks_per_day - used - 1

    def _take_model_call(self) -> bool:
        """An OPTIONAL daily ceiling on what all visitors together can spend
        (`--model-calls-per-day`; off by default). Past it, answers come from the
        record alone rather than the page going dead. It only ever counted
        visitors' questions -- simulations run in their own process with their
        own policy, and nothing here can slow or stop them."""
        if not self.public or self.model_calls_per_day <= 0:
            return True
        with self._lock:
            day, used = self._model_day
            today = time.strftime("%Y-%m-%d")
            if day != today:
                day, used = today, 0
            if used >= self.model_calls_per_day:
                self._model_day = (day, used)
                return False
            self._model_day = (day, used + 1)
            return True

    # -- the waitlist -------------------------------------------------------

    # -- the chat pass ------------------------------------------------------

    def _secret(self) -> bytes:
        """The key chat passes are signed with, kept beside the waitlist.

        On disk rather than made fresh at start-up, so restarting the server
        does not make every visitor type their email again. Its own lock:
        `join_waitlist` signs a pass while holding the waitlist's, and taking
        that one again here deadlocked the first signup.
        """
        path = self.waitlist.with_suffix(".secret")
        with self._secret_lock:
            if not path.exists():
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(secrets.token_hex(32))
                os.chmod(path, 0o600)
            return path.read_text().strip().encode()

    def chat_pass(self, email: str) -> str:
        """A pass that says "this browser gave us this address".

        Signed, not stored: the server checks it by recomputing the signature,
        so there is no session table to keep. It proves an email was given, NOT
        that it is real -- a fake address is free. It exists to grow the list
        and to give the per-visitor limit something steadier than an IP to
        count against; the daily ceiling is what protects the bill.
        """
        sig = hmac.new(self._secret(), email.encode(), hashlib.sha256).hexdigest()[:32]
        tag = base64.urlsafe_b64encode(email.encode()).decode().rstrip("=")
        return f"{tag}.{sig}"

    def check_pass(self, token: str) -> str | None:
        """The email a pass was issued to, or None if it is not ours."""
        try:
            tag, sig = str(token).split(".", 1)
            email = base64.urlsafe_b64decode(tag + "=" * (-len(tag) % 4)).decode()
        except (ValueError, UnicodeDecodeError):
            return None
        good = hmac.new(self._secret(), email.encode(), hashlib.sha256).hexdigest()[:32]
        return email if hmac.compare_digest(sig, good) else None

    def join_waitlist(self, email: str, source: str) -> dict[str, Any]:
        """Append an address to a local file, once.

        A file rather than a mailing service so nothing leaves this machine
        until you decide where it goes. It is personal data: `.gitignore`
        keeps it out of the repository, and nothing here ever serves it back.
        """
        email = email.strip().lower()
        if len(email) > 254 or not _EMAIL_RE.match(email):
            return {"error": "that does not look like an email address"}
        with self._lock:
            seen = set()
            if self.waitlist.exists():
                for line in self.waitlist.read_text(encoding="utf-8").splitlines():
                    try:
                        seen.add(json.loads(line)["email"])
                    except (ValueError, KeyError):
                        continue
            if email in seen:
                return {"ok": True, "already": True, "pass": self.chat_pass(email)}
            self.waitlist.parent.mkdir(parents=True, exist_ok=True)
            with self.waitlist.open("a", encoding="utf-8") as f:
                f.write(json.dumps({
                    "email": email,
                    "at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                    "source": source[:40],
                }) + "\n")
        return {"ok": True, "already": False, "pass": self.chat_pass(email)}

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
        policy = self.policy if self._take_model_call() else None
        ans = I.answer(
            run, agent_id, question,
            policy=policy, model=self.model,
            history=store.history(agent_id, who=who),
        )
        with self._lock:
            store = self.conversations()
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

        def _ip(self) -> str:
            # Behind a tunnel or a reverse proxy every request arrives from
            # 127.0.0.1, and per-visitor limits would become one shared limit.
            # Trusted ONLY when asked to: anyone can type these headers.
            if backend.trust_proxy:
                for h in ("CF-Connecting-IP", "X-Forwarded-For"):
                    v = self.headers.get(h)
                    if v:
                        return v.split(",")[0].strip()
            return self.client_address[0]

        def _raw(self, body: bytes, ctype: str, status: int = 200) -> None:
            if len(body) > 2048 and "gzip" in (self.headers.get("Accept-Encoding") or ""):
                body = gzip.compress(body, 5)
                gz = True
            else:
                gz = False
            self.send_response(status)
            self.send_header("Content-Type", ctype)
            if gz:
                self.send_header("Content-Encoding", "gzip")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(body)

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

        def _route(self) -> str:
            path, _, query = self.path.partition("?")
            run = None
            for part in query.split("&"):
                k, _, v = part.partition("=")
                if k == "run":
                    from urllib.parse import unquote
                    run = unquote(v)
            # A page asking about a run this server does not have gets told so.
            # Falling back to the current run would answer a question about
            # one world with another world's agent of the same id.
            if not backend.pin(run):
                self._send({"error": "this server does not have that run",
                            "run": run}, 404)
                return ""
            return path

        def do_GET(self) -> None:                           # noqa: N802
            path = self._route()
            if not path:
                return
            if path in ("/", "/index.html"):
                return self._raw(backend.page(), "text/html; charset=utf-8")
            if path == "/status":
                return self._send(backend.status())
            if path == "/replay":
                return self._raw(backend.replay_bytes(), "application/json")
            if path == "/run":
                return self._send(backend.run().summary())
            if path == "/cards":
                return self._send(backend.cards())
            m = _AGENT_RE.match(path)
            if not m:
                return self._send({"error": f"no route {path}"}, 404)
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

        def _body(self) -> dict | None:
            try:
                length = int(self.headers.get("Content-Length") or 0)
                if length > 16_384:
                    return None
                data = json.loads(self.rfile.read(length) or b"{}")
                return data if isinstance(data, dict) else None
            except (ValueError, json.JSONDecodeError):
                return None

        def do_POST(self) -> None:                          # noqa: N802
            path = self._route()
            if not path:
                return
            if path == "/waitlist":
                payload = self._body()
                if payload is None:
                    return self._send({"error": "bad request"}, 400)
                if payload.get("website"):
                    # The hidden field only a bot fills in. Thank it and move on.
                    return self._send({"ok": True, "already": False})
                if not backend.allow(self._ip(), "waitlist", 5):
                    return self._send({"error": "too many tries; wait a while"}, 429)
                source = "chat" if payload.get("source") == "chat" else "map"
                out = backend.join_waitlist(str(payload.get("email") or ""), source)
                return self._send(out, 400 if "error" in out else 200)

            m = _AGENT_RE.match(path)
            if not m or m.group(2) not in ("ask", "advise"):
                return self._send({"error": f"no route {path}"}, 404)
            agent_id, tail = m.group(1), m.group(2)
            payload = self._body()
            if payload is None:
                return self._send({"error": "bad JSON"}, 400)

            if tail == "advise" and not backend.allow_advise:
                return self._send({"error": "advice is switched off on this server"}, 403)
            visitor = self._ip()
            if backend.public:
                email = backend.check_pass(payload.get("pass") or "")
                if email is None:
                    return self._send({"error": "enter your email to talk to the agents",
                                       "needs_pass": True}, 401)
                # PER CONNECTION FIRST, generously: a classroom shares one IP,
                # so this is only a backstop against someone inventing a fresh
                # address for every question.
                if not backend.allow(visitor, "ask-ip", backend.asks_per_ip_per_day, 86400):
                    return self._send({"error": "This connection has asked a lot today "
                                                "-- try again tomorrow."}, 429)
                left = backend.take_question(email)
                if left is None:
                    return self._send({"error": f"You've used your {backend.asks_per_day} "
                                                "questions for today. Come back tomorrow!",
                                       "questions_left": 0}, 429)
                self._questions_left = left

            if tail == "advise":
                text = str(payload.get("text") or "")
                who = str(payload.get("from_who") or "a student")
                return self._send(backend.advise(agent_id, text, who))

            question = str(payload.get("question") or "").strip()
            if not question:
                return self._send({"error": "no question"}, 400)
            if backend.public and len(question) > 500:
                return self._send({"error": "keep it under 500 characters"}, 400)
            if agent_id not in backend.run().by_agent:
                return self._send({"error": f"no agent {agent_id} in this run"}, 404)
            who = str(payload.get("who") or "a student")[:40]
            out = backend.ask(agent_id, question, who)
            if backend.public:
                out["questions_left"] = getattr(self, "_questions_left", None)
            return self._send(out)

    return Handler


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--run", type=Path, default=None, help="run dir; default newest")
    ap.add_argument("--port", type=int, default=8000)
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--runs-root", type=Path, default=I.RUN_DIR,
                    help="with no --run, follow the newest run under here")
    ap.add_argument("--showcase", type=Path, default=None,
                    help="the past run to show when nothing is live")
    ap.add_argument("--public", action="store_true",
                    help="open to strangers: an email before chatting, a few "
                         "questions per email per day, short questions, no advice")
    ap.add_argument("--allow-advise", action="store_true",
                    help="with --public, let visitors advise agents anyway")
    ap.add_argument("--asks-per-day", type=int, default=5,
                    help="questions each email address may ask per day")
    ap.add_argument("--asks-per-ip-per-day", type=int, default=100,
                    help="backstop per connection; generous, since a class shares one")
    ap.add_argument("--model-calls-per-day", type=int, default=0,
                    help="optional ceiling on ALL visitors' model calls; 0 = none")
    ap.add_argument("--waitlist", type=Path, default=Path("waitlist.jsonl"))
    ap.add_argument("--trust-proxy", action="store_true",
                    help="read the visitor's address from CF-Connecting-IP / "
                         "X-Forwarded-For (behind cloudflared, Caddy, nginx)")
    ap.add_argument("--model", default="openai/gpt-6-luna")
    ap.add_argument(
        "--no-model", action="store_true",
        help="never call a model. Every lookup still works; synthesis questions "
             "return the retrieved record instead of a summary of it.",
    )
    args = ap.parse_args()

    backend = Backend(
        args.run, use_model=not args.no_model, model=args.model,
        runs_root=args.runs_root, showcase=args.showcase, public=args.public,
        allow_advise=(not args.public) or args.allow_advise,
        waitlist=args.waitlist, asks_per_day=args.asks_per_day,
        asks_per_ip_per_day=args.asks_per_ip_per_day,
        model_calls_per_day=args.model_calls_per_day,
    )
    backend.trust_proxy = args.trust_proxy
    run_path = backend.run_path
    summary = backend.run().summary()
    print(f"run      : {run_path}"
          + ("" if args.run else "  (following the newest; live when it is)"))
    print(f"           {summary['sim_hours']}h, {len(summary['agents'])} agents, "
          f"{summary['events']} events")
    print(f"model    : {'off (recall only)' if backend.policy is None else args.model}")
    if args.public:
        load_env()
        print("key      : " + ("OPENROUTER_PUBLIC_API_KEY (separate, capped)"
                               if os.environ.get("OPENROUTER_PUBLIC_API_KEY")
                               else "OPENROUTER_API_KEY -- your main key. Set "
                                    "OPENROUTER_PUBLIC_API_KEY in .env to cap "
                                    "public spend at OpenRouter too."))
        print(f"public   : {args.asks_per_day} questions/day per email, "
              + (f"{args.model_calls_per_day} model calls/day in total, "
                 if args.model_calls_per_day > 0 else "no overall ceiling, ")
              + "advice "
              f"{'ON' if backend.allow_advise else 'off'}")
    print(f"waitlist : {args.waitlist}")
    print(f"listening: http://{args.host}:{args.port}/\n")

    # THREADED. One visitor's model call takes seconds, and on the single-
    # threaded server it froze the map for everybody else while it ran.
    try:
        ThreadingHTTPServer((args.host, args.port), _handler(backend)).serve_forever()
    except KeyboardInterrupt:
        print("\nstopped.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
