#!/usr/bin/env python3
"""Agents must talk like agents, and must remember having talked.

Two changes are under test here, and they were made for the same reason.

An earlier `interrogate.answer` gated the model behind a keyword test and
returned the raw record for anything that did not look like a judgement, so
"why did you buy charcoal?" came back as
`At hour 12.0 I was woken because: reevaluation. I did: buy_item.` That is a
printout, not an answer. What was worth keeping from the design is GROUNDING --
the model must answer from the agent's retrieved decisions and nothing else --
not recall-instead-of-a-model. So the model now answers by default, and recall
is the fallback for no key and no budget.

And an agent that cannot remember you asked it something is not conversing, it
is answering a form. History goes back into the answering prompt so a follow-up
lands. The test that matters is `test_history_reaches_the_prompt`: everything
else here could pass while the history sat in a file nobody sent -- which is
PHASE4 §2's failure mode, one layer up from the observation.

Conversations are deliberately NOT world state. Advice is meant to change the
simulation; a question must not, or no answer about that world means anything
afterwards. `test_asking_does_not_touch_the_world` pins that.
"""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from convoy import conversation as C
from convoy import interrogate as I

FAILURES: list[str] = []


def check(label, actual, expected) -> None:
    if actual != expected:
        FAILURES.append(f"{label}: got {actual!r}, expected {expected!r}")


def ok(label, condition, detail="") -> None:
    if not condition:
        FAILURES.append(f"{label}{': ' + detail if detail else ''}")


def ex(q="q", a="a", who="Justin", hour=1.0) -> C.Exchange:
    return C.Exchange(hour=hour, who=who, question=q, answer=a)


# ---------------------------------------------------------------------------
# the store
# ---------------------------------------------------------------------------

def test_store_round_trips_through_disk() -> None:
    with tempfile.TemporaryDirectory() as d:
        s = C.ConversationStore.load(d)
        s.add("A0001", ex("why the refinery?", "because the wage was 25"))
        reloaded = C.ConversationStore.load(d)
        check("one exchange survived", len(reloaded.by_agent["A0001"]), 1)
        got = reloaded.by_agent["A0001"][0]
        check("question survived", got.question, "why the refinery?")
        check("answer survived", got.answer, "because the wage was 25")
        check("speaker survived", got.who, "Justin")


def test_history_is_per_speaker() -> None:
    """Thirty students questioning one agent must not inherit each other's turns."""
    with tempfile.TemporaryDirectory() as d:
        s = C.ConversationStore.load(d)
        s.add("A0001", ex("mine", "to Justin", who="Justin"))
        s.add("A0001", ex("theirs", "to Sam", who="Sam"))
        mine = s.history("A0001", who="Justin")
        check("only my turns", [e.question for e in mine], ["mine"])
        check("everything, unfiltered", len(s.history("A0001")), 2)


def test_history_is_bounded() -> None:
    with tempfile.TemporaryDirectory() as d:
        s = C.ConversationStore.load(d)
        for i in range(C.MAX_EXCHANGES_KEPT + 25):
            s.add("A0001", ex(f"q{i}"))
        rows = s.by_agent["A0001"]
        check("ring bounded", len(rows), C.MAX_EXCHANGES_KEPT)
        check("newest kept", rows[-1].question, f"q{C.MAX_EXCHANGES_KEPT + 24}")


def test_corrupt_history_does_not_take_the_session_down() -> None:
    """A lost conversation beats a server that refuses to answer anything."""
    with tempfile.TemporaryDirectory() as d:
        (Path(d) / "conversations.json").write_text("{not json", encoding="utf-8")
        s = C.ConversationStore.load(d)
        check("degrades to empty", s.by_agent, {})
        s.add("A0001", ex())          # and is still writable afterwards
        check("recovered", len(C.ConversationStore.load(d).by_agent["A0001"]), 1)


# ---------------------------------------------------------------------------
# answering
# ---------------------------------------------------------------------------

class ScriptedPolicy:
    """Stands in for an LLMPolicy, capturing what it was asked."""

    def __init__(self, text="I did it because the wage was better (h1.0)."):
        self.text = text
        self.seen: list[list[dict]] = []

    def _call(self, agent, messages, tools):
        self.seen.append(messages)
        return {"content": self.text}


def _run(tmp: str) -> I.Run:
    """A one-agent run on disk, with two decisions in it."""
    d = Path(tmp)
    rows = [
        {"sim_time": 3600.0, "type": "llm_reasoning", "significance": 1,
         "actor": "A0001", "subject": None, "location": "Town",
         "detail": {"woken_because": "reevaluation",
                    "text": "Charcoal is the bottleneck, so I am buying it.",
                    "did": "buy_item"}},
        {"sim_time": 7200.0, "type": "llm_reasoning", "significance": 1,
         "actor": "A0001", "subject": None, "location": "Kiln Row",
         "detail": {"woken_because": "arrived",
                    "text": "Selling the ore here beats hauling it home.",
                    "did": "sell_to_business"}},
    ]
    (d / "events.jsonl").write_text(
        "\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8"
    )
    return I.Run.load(d)


def test_a_plain_why_question_gets_a_model_answer() -> None:
    """THE REGRESSION. This used to return a record printout."""
    with tempfile.TemporaryDirectory() as d:
        policy = ScriptedPolicy()
        ans = I.answer(_run(d), "A0001", "why did you buy charcoal?", policy=policy)
        check("model was called", ans.model_called, True)
        check("answered as synthesis", ans.kind, "synthesis")
        ok("the model's words came back", "wage was better" in ans.text, ans.text)
        ok("citations still returned for checking", len(ans.citations) > 0)


def test_history_reaches_the_prompt() -> None:
    """The one that matters. History in a file nobody sends is not memory."""
    with tempfile.TemporaryDirectory() as d:
        policy = ScriptedPolicy()
        I.answer(
            _run(d), "A0001", "what did you mean by that?", policy=policy,
            history=[ex("why the refinery?", "the wage was 25 an hour")],
        )
        sent = "\n".join(m["content"] for m in policy.seen[0])
        ok("prior question in the prompt", "why the refinery?" in sent, sent[:400])
        ok("prior answer in the prompt", "wage was 25 an hour" in sent, sent[:400])


def test_no_history_means_no_empty_heading() -> None:
    with tempfile.TemporaryDirectory() as d:
        policy = ScriptedPolicy()
        I.answer(_run(d), "A0001", "why?", policy=policy)
        sent = "\n".join(m["content"] for m in policy.seen[0])
        ok("no dangling conversation block", "EARLIER IN THIS CONVERSATION" not in sent)


def test_grounding_survives_the_flip() -> None:
    """The model is shown the record and told it is the only source."""
    with tempfile.TemporaryDirectory() as d:
        policy = ScriptedPolicy()
        I.answer(_run(d), "A0001", "why did you buy charcoal?", policy=policy)
        sent = "\n".join(m["content"] for m in policy.seen[0])
        ok("the agent's own words are in the prompt",
           "Charcoal is the bottleneck" in sent, sent[:400])
        ok("told not to invent", "never invent" in sent.lower(), sent[:400])


def test_recall_is_the_fallback_without_a_policy() -> None:
    """A classroom that loses its API key gets quotes, not an error page."""
    with tempfile.TemporaryDirectory() as d:
        ans = I.answer(_run(d), "A0001", "why did you buy charcoal?", policy=None)
        check("no model call", ans.model_called, False)
        check("fell back to recall", ans.kind, "recall")
        ok("still a true answer", "Charcoal is the bottleneck" in ans.text, ans.text)


def test_unanswerable_questions_are_refused_not_invented() -> None:
    with tempfile.TemporaryDirectory() as d:
        ans = I.answer(_run(d), "A0001", "why did you buy a camel?", policy=None)
        check("refused", ans.kind, "nothing")
        check("no model call", ans.model_called, False)


def test_asking_does_not_touch_the_world() -> None:
    """Conversations are not world state, and must not be reachable from it."""
    from convoy.state import Agent

    ok("no conversation field on Agent",
       not hasattr(Agent(id="A", name="a", model="m"), "conversation"))
    import convoy.checkpoint as CP
    ok("Exchange is not checkpointed", "Exchange" not in CP._CLASSES)


def main() -> int:
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for t in tests:
        t()
    print(f"test_conversation.py: {len(tests)} tests, {len(FAILURES)} failures")
    for f in FAILURES:
        print(f"  FAIL {f}")
    return 1 if FAILURES else 0


if __name__ == "__main__":
    raise SystemExit(main())
