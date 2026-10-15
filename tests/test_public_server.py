#!/usr/bin/env python3
"""The public front door: is anything live, which run answers, and what
strangers are allowed to do.

`serve.py --public` is the first thing in this codebase meant for people who
are not the person who ran the simulation. What is under test is what a
stranger would notice going wrong:

- a page that says LIVE about a dead run (`test_liveness_is_the_log_moving`);
- a smoke test shown to the public as "the last run" when a showcase was named
  (`test_showcase_is_shown_when_nothing_is_live`);
- a question about the run you are watching answered by a DIFFERENT run's agent
  of the same id, after the server has moved on (`test_a_page_can_pin_its_run`);
- an email list that double-counts, or takes junk (`test_the_waitlist_*`);
- a bill run up by one visitor (`test_limits_*`).

Nothing here starts a server or calls a model. The handler is a thin router
over `Backend`, and `Backend` is where every one of those decisions is made.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import serve as S

FAILURES: list[str] = []


def check(label, actual, expected) -> None:
    if actual != expected:
        FAILURES.append(f"{label}: got {actual!r}, expected {expected!r}")


def ok(label, condition, detail="") -> None:
    if not condition:
        FAILURES.append(f"{label}{': ' + detail if detail else ''}")


def make_run(root: Path, name: str, age_s: float) -> Path:
    """A run directory whose log was last written `age_s` seconds ago."""
    d = root / name
    d.mkdir(parents=True)
    log = d / "events.jsonl"
    log.write_text("{}\n")
    t = time.time() - age_s
    os.utime(log, (t, t))
    return d


def backend(root: Path, **kw) -> S.Backend:
    return S.Backend(None, use_model=False, model="none", runs_root=root, **kw)


# ---------------------------------------------------------------------------
# which run, and whether it is live
# ---------------------------------------------------------------------------

def test_liveness_is_the_log_moving() -> None:
    with tempfile.TemporaryDirectory() as d:
        root = Path(d)
        old = make_run(root, "old", age_s=3 * 3600)
        b = backend(root)
        ok("an hours-old log is not live", not b._is_live(old))
        fresh = make_run(root, "fresh", age_s=5)
        ok("a log written seconds ago is live", b._is_live(fresh))
        check("the live run is the one answering", b.run_path, fresh)
        ok("no run is never live", not b._is_live(None))


def test_showcase_is_shown_when_nothing_is_live() -> None:
    """The newest run is often a ten-minute smoke test. When a showcase is
    named, that is what a stranger sees between simulations -- and the moment
    a new run goes live, the live run wins."""
    with tempfile.TemporaryDirectory() as d:
        root = Path(d)
        show = make_run(root, "the-good-one", age_s=30 * 86400)
        smoke = make_run(root, "smoke", age_s=3600)
        check("showcase, not the newer smoke run",
              backend(root, showcase=show).run_path, show)
        check("with no showcase, the previous run is the newest",
              backend(root).run_path, smoke)
        live = make_run(root, "live", age_s=1)
        check("a live run beats the showcase",
              backend(root, showcase=show).run_path, live)


def test_a_page_can_pin_its_run() -> None:
    with tempfile.TemporaryDirectory() as d:
        root = Path(d)
        show = make_run(root, "showcase", age_s=86400)
        ended = make_run(root, "just-ended", age_s=3600)
        b = backend(root, showcase=show)
        check("unpinned answers from the showcase", b.run_path, show)
        ok("a known run pins", b.pin("just-ended"))
        check("pinned answers from the run on the page", b.run_path, ended)
        ok("a path is not a run name", not b.pin("../../etc"))
        check("...and pins nothing", b.run_path, show)
        ok("an unknown name is refused, not swapped", not b.pin("no-such-run"))
        ok("no pin is fine", b.pin(None))
        check("no pin means the current run", b.run_path, show)


# ---------------------------------------------------------------------------
# the waitlist
# ---------------------------------------------------------------------------

def test_the_waitlist_takes_each_address_once() -> None:
    with tempfile.TemporaryDirectory() as d:
        wl = Path(d) / "waitlist.jsonl"
        b = backend(Path(d), waitlist=wl)
        first = b.join_waitlist("Ann@Example.com", "map")
        check("first time", (first["ok"], first["already"]), (True, False))
        again = b.join_waitlist("  ann@example.COM ", "map")
        check("same address, other case", (again["ok"], again["already"]), (True, True))
        rows = [json.loads(x) for x in wl.read_text().splitlines()]
        check("one row on disk", len(rows), 1)
        check("stored lower-case", rows[0]["email"], "ann@example.com")
        ok("stored with a time", "at" in rows[0])


def test_the_waitlist_refuses_junk() -> None:
    with tempfile.TemporaryDirectory() as d:
        wl = Path(d) / "waitlist.jsonl"
        b = backend(Path(d), waitlist=wl)
        for bad in ("", "nope", "a@b", "a b@c.com", "@x.com",
                    "x" * 250 + "@example.com"):
            ok(f"refused {bad[:20]!r}", "error" in b.join_waitlist(bad, "map"))
        ok("nothing written", not wl.exists())


def test_the_chat_pass() -> None:
    """Issued for an email, checked by signature, and useless if forged."""
    with tempfile.TemporaryDirectory() as d:
        wl = Path(d) / "waitlist.jsonl"
        b = backend(Path(d), waitlist=wl, public=True)
        got = b.join_waitlist("bo@example.com", "chat")
        check("a pass comes back", b.check_pass(got["pass"]), "bo@example.com")
        again = b.join_waitlist("bo@example.com", "map")
        check("the same pass on a repeat signup", again["pass"], got["pass"])
        tag, sig = got["pass"].split(".")
        check("a forged signature fails", b.check_pass(tag + "." + "0" * 32), None)
        other = b.chat_pass("eve@example.com").split(".")[1]
        check("another address's signature fails", b.check_pass(tag + "." + other), None)
        check("junk fails", b.check_pass("not a pass"), None)
        ok("the secret is not world-readable",
           (wl.with_suffix(".secret").stat().st_mode & 0o077) == 0)
        restarted = backend(Path(d), waitlist=wl, public=True)
        check("a restart keeps passes valid",
              restarted.check_pass(got["pass"]), "bo@example.com")


# ---------------------------------------------------------------------------
# limits
# ---------------------------------------------------------------------------

def test_limits_are_per_visitor_and_only_in_public() -> None:
    with tempfile.TemporaryDirectory() as d:
        pub = backend(Path(d), public=True)
        got = [pub.allow("1.1.1.1", "ask", 3) for _ in range(4)]
        check("three allowed, the fourth refused", got, [True, True, True, False])
        ok("another visitor has their own allowance", pub.allow("2.2.2.2", "ask", 3))
        ok("another kind of request has its own", pub.allow("1.1.1.1", "waitlist", 3))
        private = backend(Path(d))
        ok("a private server never limits",
           all(private.allow("1.1.1.1", "ask", 1) for _ in range(10)))


def test_limits_five_questions_per_email_per_day() -> None:
    """Counted on disk, so restarting the server (which `go_live.py` does every
    session) does not hand everyone a fresh five."""
    with tempfile.TemporaryDirectory() as d:
        wl = Path(d) / "waitlist.jsonl"
        b = backend(Path(d), waitlist=wl, public=True)
        got = [b.take_question("a@example.com") for _ in range(6)]
        check("five, counting down, then none", got, [4, 3, 2, 1, 0, None])
        check("another address has its own five", b.take_question("b@example.com"), 4)
        restarted = backend(Path(d), waitlist=wl, public=True)
        check("a restart does not refill", restarted.take_question("a@example.com"), None)
        restarted._usage["day"] = "1999-01-01"
        check("tomorrow refills", restarted.take_question("a@example.com"), 4)
        ok("no overall ceiling by default", all(b._take_model_call() for _ in range(1000)))


def test_limits_the_daily_model_ceiling() -> None:
    """Past the ceiling, answers fall back to the record rather than failing:
    the page keeps working and the bill stops."""
    with tempfile.TemporaryDirectory() as d:
        b = backend(Path(d), public=True, model_calls_per_day=2)
        check("two calls, then none",
              [b._take_model_call() for _ in range(3)], [True, True, False])
        b._model_day = ("1999-01-01", 99)
        ok("a new day resets the ceiling", b._take_model_call())


def main() -> int:
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for t in tests:
        t()
    print(f"test_public_server.py: {len(tests)} tests, {len(FAILURES)} failures")
    for f in FAILURES:
        print(f"  FAIL {f}")
    return 1 if FAILURES else 0


if __name__ == "__main__":
    raise SystemExit(main())
