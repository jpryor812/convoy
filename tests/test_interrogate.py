#!/usr/bin/env python3
"""Interrogating a finished run, and the checkpoint that makes it possible.

TWO THINGS ARE UNDER TEST HERE

1. CHECKPOINT COMPLETENESS. `save` encodes any dataclass generically; `load`
   needs the type registered in `_CLASSES`. A type added to `state.py` and not
   added there writes checkpoints that look perfect and cannot be read back.
   Nothing called `load` in production for three phases, so FOUR types had
   accumulated -- `ChatMessage`, `JobPosting`, `StolenStack`, `TradeOffer` --
   and every checkpoint written since chat landed was unrestorable. The test is
   written against the whole module rather than those four names, because the
   bug is the omission, not the omitted.

2. ANSWERING FROM THE RECORD. The point of storing reasoning (PHASE4 §9) was to
   stop "why did you do that?" being answered by invention. So the tests assert
   that a lookup returns the agent's OWN words, that a question the record
   cannot answer returns nothing rather than something, and that no model is
   called for either.
"""

from __future__ import annotations

import dataclasses
import inspect
import json
import pathlib
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from convoy import advice as ADV
from convoy import checkpoint
from convoy import interrogate as I
from convoy import state as S
from convoy.engine import Engine, EngineConfig
from convoy.events import EventLog
from convoy.state import Agent, ChatMessage, World

FAILURES: list[str] = []
TMP = Path(__file__).parent / "__pycache__"


def check(label, actual, expected) -> None:
    if actual != expected:
        FAILURES.append(f"{label}: got {actual!r}, expected {expected!r}")


def ok(label, condition, detail="") -> None:
    if not condition:
        FAILURES.append(f"{label}{': ' + detail if detail else ''}")


# ---------------------------------------------------------------------------
# checkpoint completeness
# ---------------------------------------------------------------------------

def test_every_state_dataclass_is_registered() -> None:
    """The guard. Adding a dataclass to state.py without registering it fails here."""
    check("nothing unregistered", checkpoint.check(), [])


def test_check_actually_detects_an_omission() -> None:
    """A check that cannot fail is not a check.

    `checkpoint.check()` returning [] is only reassuring if it would have
    returned something when the bug was present -- so the bug is recreated by
    removing a registration, and the check must notice.
    """
    saved = dict(checkpoint._CLASSES)
    try:
        del checkpoint._CLASSES["ChatMessage"]
        check("detects the omission", checkpoint.check(), ["ChatMessage"])
    finally:
        checkpoint._CLASSES.clear()
        checkpoint._CLASSES.update(saved)
    check("restored", checkpoint.check(), [])


def test_a_world_with_chat_round_trips() -> None:
    """The actual regression: every real run has chat in it, and none could be loaded."""
    w = World()
    w.sim_time = 5 * 3600.0
    a = Agent(id="A0001", name="Tester", model="test/model", location="Town")
    w.agents[a.id] = a
    w.chat.append(ChatMessage(
        sim_time=w.sim_time, channel="world", sender=a.id, sender_name="Tester",
        text="bronze for sale",
    ))

    path = TMP / "interrogate_checkpoint.json"
    checkpoint.save(w, path)
    restored = checkpoint.load(path)
    path.unlink(missing_ok=True)

    check("chat survived", len(restored.chat), 1)
    check("text intact", restored.chat[0].text, "bronze for sale")
    check("it is a ChatMessage, not a dict", type(restored.chat[0]).__name__, "ChatMessage")


# ---------------------------------------------------------------------------
# resuming a saved world -- "come back later and see what happened"
# ---------------------------------------------------------------------------

def test_checkpoint_clock_starts_from_the_worlds_hour_not_zero() -> None:
    """A world reloaded at hour 84 must not save 5,000 times catching up.

    `_next_checkpoint` was an absolute offset from zero, so a resumed world was
    already past it and the due-check fired every tick, advancing the counter
    one simulated HOUR per simulated MINUTE.
    """
    w = World()
    w.sim_time = 84 * 3600.0
    engine = Engine(w, EventLog(None, echo_min=99), None,
                    EngineConfig(duration_hours=0.0, checkpoint_every_hours=1.0))
    check("due one hour from NOW", engine._next_checkpoint, 85 * 3600.0)

    fresh = Engine(World(), EventLog(None, echo_min=99), None,
                   EngineConfig(duration_hours=0.0, checkpoint_every_hours=1.0))
    check("unchanged for a fresh world", fresh._next_checkpoint, 3600.0)


def test_replay_restores_history_so_agents_are_not_amnesiac() -> None:
    """`memory_for` walks the log. A resumed run starting empty means total amnesia."""
    path = TMP / "replay_events.jsonl"
    log = EventLog(path, echo_min=99)
    log.emit(3600.0, "business_founded", actor="A0001", name="Test Mine")
    log.emit(7200.0, "hired", actor="A0001", subject="A0002")
    log.close()

    reloaded = EventLog(None, echo_min=99)
    count = reloaded.replay(path)
    path.unlink(missing_ok=True)

    check("both events back", count, 2)
    check("types intact", [e.type for e in reloaded.events],
          ["business_founded", "hired"])
    check("detail intact", reloaded.events[0].detail["name"], "Test Mine")
    check("actor intact", reloaded.events[1].actor, "A0001")


def test_replay_survives_a_torn_line_from_a_killed_run() -> None:
    """A run killed mid-write leaves a half-line. Refusing to resume over it is worse."""
    path = TMP / "torn_events.jsonl"
    path.write_text(
        '{"sim_time": 3600.0, "type": "hired", "significance": 2, "detail": {}}\n'
        '{"sim_time": 7200.0, "type": "fir',
        encoding="utf-8",
    )
    log = EventLog(None, echo_min=99)
    count = log.replay(path)
    path.unlink(missing_ok=True)
    check("kept the good line", count, 1)


def test_advice_queued_into_a_saved_world_survives_the_round_trip() -> None:
    """The whole 'advise now, resume later' path, at the persistence layer.

    This is what a saved-and-returned-to world depends on: the recommendation a
    person left has to still be there, still undelivered, when the world is
    picked back up.
    """
    w, log = World(), EventLog(None, echo_min=99)
    w.sim_time = 6 * 3600.0
    a = Agent(id="A0001", name="Tester", model="test/model", location="Town")
    w.agents[a.id] = a
    ADV.give(w, log, "A0001", "Found a mine.", from_who="a student")

    path = TMP / "resume_checkpoint.json"
    checkpoint.save(w, path)
    restored = checkpoint.load(path)
    path.unlink(missing_ok=True)

    back = restored.agents["A0001"]
    check("advice survived", len(back.inbox), 1)
    check("still undelivered", back.inbox[0].times_seen, 0)
    check("attributed", back.inbox[0].from_who, "a student")
    check("still live on the other side", len(back.live_advice(6.0)), 1)


# ---------------------------------------------------------------------------
# a synthetic run to interrogate
# ---------------------------------------------------------------------------

def _run_dir(name: str, rows: list[dict]) -> Path:
    d = TMP / name
    d.mkdir(parents=True, exist_ok=True)
    (d / "events.jsonl").write_text(
        "\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8"
    )
    return d


def _decision(hour: float, did: str, text: str, woken: str = "reevaluation") -> dict:
    return {
        "sim_time": hour * 3600.0, "type": "llm_reasoning", "significance": 1,
        "actor": "A0001", "subject": None, "location": "Town",
        "detail": {"woken_because": woken, "text": text, "did": did},
    }


def _fixture() -> I.Run:
    return I.Run.load(_run_dir("interrogate_run", [
        {"sim_time": 0.0, "type": "sim_start", "significance": 3, "actor": None,
         "subject": None, "location": None, "detail": {"agents": 1}},
        _decision(12.0, "buy_item", "Charcoal is cheap at Kiln Row and my refinery is stalled without it."),
        _decision(20.0, "start_shift", "I will work the shift out rather than travel again."),
        _decision(40.0, "found_business", "I have 400 denari and mining has no input costs, so the margin is all mine."),
        _decision(52.0, "sell_to_business", "Selling the ore now; the state pays 0.4x but I need the cash for payroll."),
    ]))


# ---------------------------------------------------------------------------
# answering
# ---------------------------------------------------------------------------

def test_lookup_returns_the_agents_own_words_and_calls_no_model() -> None:
    ans = I.answer(_fixture(), "A0001", "why did you buy charcoal?")
    check("recall, not synthesis", ans.kind, "recall")
    check("no model call", ans.model_called, False)
    ok("quotes the agent", "Kiln Row" in ans.text, ans.text)
    ok("cites the hour", any(c.hour == 12.0 for c in ans.citations),
       str([c.hour for c in ans.citations]))


def test_a_question_the_record_cannot_answer_returns_nothing() -> None:
    """The outcome that makes the tool trustworthy.

    A tool that always answers teaches students that agents always have reasons.
    """
    ans = I.answer(_fixture(), "A0001", "why did you buy a camel?")
    check("nothing", ans.kind, "nothing")
    check("no model call", ans.model_called, False)
    check("no citations", ans.citations, [])
    ok("says so plainly", "nothing in my record" in ans.text.lower(), ans.text)


def test_a_shared_verb_is_not_a_match() -> None:
    """The retriever must not answer about a camel with the hour it bought charcoal.

    "buy camel" and "buy charcoal" share a verb. A retriever that ranks and
    takes the top hit always returns something, which is the confabulation
    problem moved out of the model and into the search -- and worse there,
    because the words it returns are genuinely the agent's, so the answer reads
    as confirmation of a purchase that never happened.
    """
    ans = I.answer(_fixture(), "A0001", "why did you buy a camel?")
    check("no answer", ans.kind, "nothing")
    ans2 = I.answer(_fixture(), "A0001", "why did you buy charcoal?")
    check("the real one still works", ans2.kind, "recall")


def test_naming_an_hour_pulls_that_decision() -> None:
    ans = I.answer(_fixture(), "A0001", "what did you do at hour 40?")
    check("recall", ans.kind, "recall")
    ok("the h40 decision is cited", any(c.hour == 40.0 for c in ans.citations),
       str([c.hour for c in ans.citations]))


def test_synthesis_is_only_triggered_by_a_judgement_question() -> None:
    """Lookups are free and cannot misquote; judgements are neither. Bias to lookup."""
    for q in ("why did you buy charcoal?", "what did you do at hour 40?",
              "when did you found the mine?"):
        ok(f"lookup: {q}", not I.needs_synthesis(q))
    for q in ("was your overall strategy sound?", "compare your two businesses",
              "what was your biggest mistake?"):
        ok(f"synthesis: {q}", I.needs_synthesis(q))


def test_synthesis_without_a_model_degrades_to_the_record() -> None:
    """A classroom that loses its API key gets quotes, not an error page."""
    ans = I.answer(_fixture(), "A0001", "was your overall strategy sound?", policy=None)
    check("falls back to recall", ans.kind, "recall")
    check("no model call", ans.model_called, False)
    ok("citations still returned", len(ans.citations) > 0)


def test_synthesis_prompt_contains_only_retrieved_decisions() -> None:
    """Grounding. The model must not be free to invent an hour that never happened."""
    seen: dict = {}

    class Spy:
        def _call(self, agent, messages, tools):
            seen["user"] = messages[-1]["content"]
            seen["system"] = messages[0]["content"]
            return {"content": "I judged it reasonable (h40.0)."}

    ans = I.answer(_fixture(), "A0001", "was your overall strategy sound?", policy=Spy())
    check("synthesis", ans.kind, "synthesis")
    check("model was called", ans.model_called, True)
    ok("prompt carries the record", "Kiln Row" in seen["user"] or "denari" in seen["user"],
       seen["user"][:200])
    ok("system forbids invention", "invent" in seen["system"].lower(), seen["system"][:200])
    ok("citations returned alongside", len(ans.citations) > 0)


def test_a_dead_model_falls_back_to_the_record_rather_than_erroring() -> None:
    class Dead:
        def _call(self, agent, messages, tools):
            return None

    ans = I.answer(_fixture(), "A0001", "was your overall strategy sound?", policy=Dead())
    check("degraded to recall", ans.kind, "recall")
    ok("says why", "could not be reached" in ans.text, ans.text[:120])


# ---------------------------------------------------------------------------
# run and agent views
# ---------------------------------------------------------------------------

def test_summary_counts_decisions_and_reasoning_separately() -> None:
    """'2 reasoning events in 6,916 calls' must be visible at a glance, not inferred."""
    run = I.Run.load(_run_dir("interrogate_run2", [
        _decision(1.0, "buy_item", "a real reason"),
        _decision(2.0, "wait", "(acted without saying why)"),
    ]))
    agent = run.summary()["agents"][0]
    check("decisions", agent["decisions"], 2)
    check("only one has reasoning", agent["with_reasoning"], 1)


def test_transcript_is_complete_and_ordered() -> None:
    decisions = _fixture().decisions("A0001")
    check("all four", len(decisions), 4)
    check("ordered", [c.hour for c in decisions], [12.0, 20.0, 40.0, 52.0])


def test_advice_trace_distinguishes_given_from_delivered() -> None:
    """The distinction the whole advice feature rests on."""
    run = I.Run.load(_run_dir("interrogate_run3", [
        {"sim_time": 3600.0, "type": "advice_given", "significance": 2, "actor": "A0001",
         "subject": None, "location": "Town",
         "detail": {"advice_id": "ADV001", "text": "sell the ore", "from_who": "a student"}},
        {"sim_time": 7200.0, "type": "advice_given", "significance": 2, "actor": "A0001",
         "subject": None, "location": "Town",
         "detail": {"advice_id": "ADV002", "text": "buy a camel", "from_who": "a student"}},
        {"sim_time": 5400.0, "type": "advice_delivered", "significance": 2, "actor": "A0001",
         "subject": None, "location": "Town",
         "detail": {"advice_id": "ADV001", "text": "sell the ore", "from_who": "a student"}},
    ]))
    trace = {r["id"]: r for r in run.advice("A0001")}
    check("delivered one", trace["ADV001"]["delivered"], True)
    check("first seen", trace["ADV001"]["first_seen_hour"], 1.5)
    check("undelivered one", trace["ADV002"]["delivered"], False)
    check("no first seen", trace["ADV002"]["first_seen_hour"], None)


# ---------------------------------------------------------------------------
# holdings on a citation
# ---------------------------------------------------------------------------

def test_runs_recorded_before_assets_existed_still_answer() -> None:
    """Every run already on disk predates the asset snapshot.

    An interrogation tool that only worked on runs made after the feature
    landed would be useless on the entire archive, including the 84-hour run.
    """
    c = I.Citation(hour=6.7, woken_because="reevaluation", did="start_business",
                   text="Founding the mine.")
    check("no holdings line", c.position(), "")
    ok("and no assets key in the payload", "assets" not in c.as_dict())


def test_holdings_render_for_a_prompt() -> None:
    c = I.Citation(
        hour=6.7, woken_because="reevaluation", did="start_business",
        text="Founding the mine.",
        assets={
            "denari": 170.5, "net_worth": 345.5,
            "businesses": [{"type": "Mining Operation", "cash": 210.0,
                            "payroll_per_hour": 43.33}],
            "vehicles": [{"id": "V1", "type": "Donkey Cart"}],
            "home": None,
            "job": {"role": "Miner", "wage": 28.89},
            "carrying": {"Copper Ore": 12},
        },
    )
    pos = c.position()
    ok("cash", "170d" in pos, pos)
    ok("net worth", "worth 346" in pos or "worth 345" in pos, pos)
    ok("business cash and payroll", "cash 210" in pos and "payroll 43/h" in pos, pos)
    ok("vehicles counted", "1 vehicle(s)" in pos, pos)
    ok("job", "Miner" in pos, pos)
    ok("cargo", "12x Copper Ore" in pos, pos)
    ok("no home claimed when there is none", "a home" not in pos, pos)


def test_holdings_reach_the_answering_prompt() -> None:
    """Recorded and not sent is the same as not recorded."""
    with tempfile.TemporaryDirectory() as d:
        rows = [{
            "sim_time": 24120.0, "type": "llm_reasoning", "significance": 1,
            "actor": "A0001", "subject": None, "location": "Copper Gulch",
            "detail": {"woken_because": "reevaluation", "did": "start_business",
                       "text": "Founding the mine.",
                       "assets": {"denari": 170.5, "net_worth": 345.5,
                                  "businesses": [], "vehicles": [],
                                  "home": None, "job": None, "carrying": {}}},
        }]
        pathlib.Path(d, "events.jsonl").write_text(
            "\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")
        run = I.Run.load(pathlib.Path(d))

        class P:
            def __init__(self): self.seen = []
            def _call(self, agent, messages, tools):
                self.seen.append(messages); return {"content": "I had 170 denari."}

        policy = P()
        I.answer(run, "A0001", "what could you afford when you founded it?",
                 policy=policy)
        sent = "\n".join(m["content"] for m in policy.seen[0])
        ok("holdings in the prompt", "you held" in sent and "170d" in sent, sent[-400:])


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
    print(f"\nOK -- {len(tests)} interrogation tests passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
