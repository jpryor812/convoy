#!/usr/bin/env python3
"""Agents must record WHY, not just what.

`Agent.memory` is a list of indices into the event log -- things that happened.
Until 2026-08-17 nothing anywhere stored an agent's own account of its choices:
`LLMPolicy.decide` read the model's text only on replies that carried NO tool
calls, so reasoning was captured precisely on the turns where the agent decided
not to act. Across a 6,916-call run that fired TWICE.

The consequence is not cosmetic. Asking an agent "why did you do that?" with no
stored intent produces fluent post-hoc confabulation, which is worthless for the
thing this is meant to support -- a person interrogating an agent and judging
whether its decision was smart.

These tests drive `LLMPolicy` against a scripted transport, so they assert the
capture path itself rather than a model's cooperation. The cases that matter:

  * a reply with BOTH text and tool calls -- the common case, previously lost;
  * a reasoning model's reply, empty `content` and thinking in `reasoning`;
  * an action taken with no words at all -- still a decision, still recorded;
  * refusals marked as refusals, since "tried and was refused" and "did" are
    very different decisions to judge;
  * the ring buffer actually bounding, and reasoning surviving a checkpoint.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from convoy import llm as L
from convoy import observe as O
from convoy.events import EventLog
from convoy.checkpoint import load, save
from convoy.state import MAX_REASONING_KEPT, Agent, World

FAILURES: list[str] = []
HOUR = 3600.0


def check(label, actual, expected) -> None:
    if actual != expected:
        FAILURES.append(f"{label}: got {actual!r}, expected {expected!r}")


def ok(label, condition, detail="") -> None:
    if not condition:
        FAILURES.append(f"{label}{': ' + detail if detail else ''}")


class ScriptedPolicy(L.LLMPolicy):
    """An LLMPolicy whose transport replays canned replies instead of calling out.

    Subclassing at `_call` rather than stubbing the HTTP layer keeps every line
    of `decide` -- the tool dispatch, the refusal handling, the capture -- under
    test.
    """

    def __init__(self, log: EventLog, replies: list[dict]) -> None:
        super().__init__(log=log, api_key="test-key")
        self._replies = list(replies)
        self.calls_made = 0

    def _call(self, agent, messages, tools):
        self.calls_made += 1
        return self._replies.pop(0) if self._replies else None


def tool_call(name: str, args: dict, call_id: str = "c1") -> dict:
    return {
        "id": call_id,
        "type": "function",
        "function": {"name": name, "arguments": json.dumps(args)},
    }


def setup() -> tuple[World, EventLog, Agent]:
    w, log = World(), EventLog(None, echo_min=99)
    w.sim_time = 12 * HOUR
    a = Agent(id="A0001", name="Tester", model="test/model", location="Town")
    a.denari = 500.0
    w.agents[a.id] = a
    return w, log, a


# ---------------------------------------------------------------------------
# capture
# ---------------------------------------------------------------------------

def test_reasoning_captured_alongside_a_tool_call() -> None:
    """The regression. Text plus an action used to record nothing at all."""
    w, log, a = setup()
    policy = ScriptedPolicy(log, [{
        "role": "assistant",
        "content": "The refinery is stalled for want of charcoal, so I am walking to Kiln Row.",
        "tool_calls": [tool_call("post_world_chat", {"text": "buying charcoal"})],
    }])
    policy.decide(w, a, "reevaluation")

    check("one entry recorded", len(a.reasoning), 1)
    entry = a.reasoning[0]
    ok("text stored", "stalled for want of charcoal" in entry.text, entry.text)
    check("woken_because stored", entry.woken_because, "reevaluation")
    check("hour stored", entry.hour, 12.0)
    ok("action recorded against the reasoning", entry.actions == ["post_world_chat"], str(entry.actions))


def test_reasoning_model_thinking_field_is_read() -> None:
    """Most of the roster returns an empty `content` beside a tool call."""
    w, log, a = setup()
    policy = ScriptedPolicy(log, [{
        "role": "assistant",
        "content": "",
        "reasoning": "Wages at the state tavern beat my current job by 8/hr.",
        "tool_calls": [tool_call("post_world_chat", {"text": "hello"})],
    }])
    policy.decide(w, a, "arrived")

    check("entry recorded", len(a.reasoning), 1)
    ok("reasoning field used", "state tavern" in a.reasoning[0].text, a.reasoning[0].text)


def test_content_wins_over_reasoning_when_both_present() -> None:
    w, log, a = setup()
    policy = ScriptedPolicy(log, [{
        "role": "assistant",
        "content": "SPOKEN",
        "reasoning": "THOUGHT",
        "tool_calls": [tool_call("post_world_chat", {"text": "x"})],
    }])
    policy.decide(w, a, "reevaluation")
    check("content preferred", a.reasoning[0].text, "SPOKEN")


def test_silent_action_still_recorded() -> None:
    """No words is not no decision -- a gap in the transcript must be visible."""
    w, log, a = setup()
    policy = ScriptedPolicy(log, [{
        "role": "assistant",
        "content": "",
        "tool_calls": [tool_call("post_world_chat", {"text": "x"})],
    }])
    policy.decide(w, a, "reevaluation")

    check("entry recorded", len(a.reasoning), 1)
    check("no text", a.reasoning[0].text, "")
    check("action still known", a.reasoning[0].actions, ["post_world_chat"])


def test_text_only_reply_still_recorded() -> None:
    """The one case that already worked must keep working."""
    w, log, a = setup()
    policy = ScriptedPolicy(log, [{
        "role": "assistant",
        "content": "Waiting on production; nothing worth doing this hour.",
    }])
    policy.decide(w, a, "reevaluation")

    check("entry recorded", len(a.reasoning), 1)
    check("no actions", a.reasoning[0].actions, [])


def test_refusals_are_marked() -> None:
    """`quit_job` while unemployed is refused by the engine, not done."""
    w, log, a = setup()
    policy = ScriptedPolicy(log, [{
        "role": "assistant",
        "content": "Quitting a job I do not have.",
        "tool_calls": [tool_call("quit_job", {})],
    }])
    policy.decide(w, a, "reevaluation")

    entry = a.reasoning[0]
    ok("refusal marked", entry.actions and "refused" in entry.actions[0], str(entry.actions))


def test_nothing_recorded_when_the_call_fails() -> None:
    """A transport failure is not a decision and must not enter the record."""
    w, log, a = setup()
    policy = ScriptedPolicy(log, [])          # _call returns None
    policy.decide(w, a, "reevaluation")
    check("no phantom entry", len(a.reasoning), 0)


def test_one_decision_makes_one_record() -> None:
    """A multi-step decision is ONE decision, not three.

    Models reason on step 1 and then execute; recording per step made most of a
    live smoke run read "acted without saying why" when the reason had been
    given one step earlier.
    """
    w, log, a = setup()
    policy = ScriptedPolicy(log, [
        {"role": "assistant", "content": "First, announce it.",
         "tool_calls": [tool_call("post_world_chat", {"text": "one"}, "c1")]},
        {"role": "assistant", "content": "",          # bare execution, as models do
         "tool_calls": [tool_call("post_world_chat", {"text": "two"}, "c2")]},
        {"role": "assistant", "content": "Then say the price.",
         "tool_calls": [tool_call("post_world_chat", {"text": "three"}, "c3")]},
    ])
    policy.decide(w, a, "reevaluation")

    check("one record for the decision", len(a.reasoning), 1)
    entry = a.reasoning[0]
    ok("first step's words kept", "First, announce it." in entry.text, entry.text)
    ok("later words kept too", "Then say the price." in entry.text, entry.text)
    check("every action collected", len(entry.actions), 3)


def test_silent_follow_up_steps_inherit_the_decision(  ) -> None:
    """The bug the smoke run exposed: step 2 must not read as unexplained."""
    w, log, a = setup()
    policy = ScriptedPolicy(log, [
        {"role": "assistant", "content": "Stocking the refinery before prices move.",
         "tool_calls": [tool_call("post_world_chat", {"text": "one"}, "c1")]},
        {"role": "assistant", "content": "",
         "tool_calls": [tool_call("post_world_chat", {"text": "two"}, "c2")]},
    ])
    policy.decide(w, a, "reevaluation")

    events = [e for e in log.events if e.type == "llm_reasoning"]
    check("one event, not two", len(events), 1)
    ok(
        "no phantom 'acted without saying why'",
        "acted without saying why" not in events[0].detail["text"],
        events[0].detail["text"],
    )


# ---------------------------------------------------------------------------
# storage and surfacing
# ---------------------------------------------------------------------------

def test_event_is_logged_for_the_transcript() -> None:
    """The agent holds a working set; the log holds the whole run."""
    w, log, a = setup()
    policy = ScriptedPolicy(log, [{
        "role": "assistant", "content": "Because the price is right.",
        "tool_calls": [tool_call("post_world_chat", {"text": "x"})],
    }])
    policy.decide(w, a, "reevaluation")

    events = [e for e in log.events if e.type == "llm_reasoning"]
    check("one reasoning event", len(events), 1)
    check("attributed", events[0].actor, "A0001")
    ok("text in detail", "price is right" in events[0].detail.get("text", ""))
    ok("actions in detail", "post_world_chat" in events[0].detail.get("did", ""))


def test_ring_buffer_bounds_growth() -> None:
    """A 120-hour run asks some agents several hundred times."""
    _w, _log, a = setup()
    for i in range(MAX_REASONING_KEPT + 25):
        a.remember_reasoning(float(i), "reevaluation", f"thought {i}", ["post_world_chat"])

    check("bounded", len(a.reasoning), MAX_REASONING_KEPT)
    check("keeps the most recent", a.reasoning[-1].text, f"thought {MAX_REASONING_KEPT + 24}")


def test_thinking_surfaces_in_the_observation() -> None:
    """Stored but never shown is the §2 failure mode all over again."""
    w, log, a = setup()
    for i in range(8):
        a.remember_reasoning(float(i), "reevaluation", f"thought {i}", ["post_world_chat"])

    obs = O.observe(w, log, a, "reevaluation")
    lines = obs.get("your_thinking") or []
    check("capped for the prompt", len(lines), O.DEFAULT_THINKING_LIMIT)
    ok("most recent present", "thought 7" in lines[-1], lines[-1] if lines else "")

    rendered = O.render(obs)
    ok("rendered under a heading", "WHY YOU MADE THEM" in rendered.upper(), "heading missing")
    ok("reasoning reaches the prompt", "thought 7" in rendered)


def test_thinking_does_not_evict_memory() -> None:
    """Memory and reasoning hold separate budgets, so neither starves the other."""
    w, log, a = setup()
    for i in range(20):
        a.remember_reasoning(float(i), "reevaluation", f"thought {i}", ["post_world_chat"])
    log.emit(w.sim_time, "business_founded", actor=a.id, name="Test Mine")

    obs = O.observe(w, log, a, "reevaluation")
    ok(
        "the founding is still remembered",
        any("business_founded" in line for line in obs["memory"]),
        str(obs["memory"]),
    )


def test_reasoning_survives_a_checkpoint(tmp: Path | None = None) -> None:
    """A VM restart must not erase why anybody did anything."""
    w, _log, a = setup()
    a.remember_reasoning(4.0, "arrived", "Kiln Row had the cheaper charcoal.", ["buy_item"])

    path = Path(__file__).parent / "__pycache__" / "reasoning_checkpoint.json"
    save(w, path)
    restored = load(path)
    path.unlink(missing_ok=True)

    back = restored.agents["A0001"].reasoning
    check("round-tripped", len(back), 1)
    check("text intact", back[0].text, "Kiln Row had the cheaper charcoal.")
    check("actions intact", back[0].actions, ["buy_item"])


# ---------------------------------------------------------------------------
# what the agent HELD at the decision
# ---------------------------------------------------------------------------

def test_assets_are_pinned_to_the_decision() -> None:
    """A decision row records why and what; it must also record what with.

    "Founded a mine with 345 denari in hand" and "founded a mine with 175" are
    different decisions to judge, and nothing in an append-only log can recover
    a balance after the fact.
    """
    w, log, a = setup()
    a.denari = 345.5
    policy = ScriptedPolicy(log, [{
        "role": "assistant",
        "content": "Founding the mine.",
        "tool_calls": [tool_call("post_world_chat", {"text": "opening a mine"})],
    }])
    policy.decide(w, a, "reevaluation")

    ev = next(e for e in log.events if e.type == "llm_reasoning")
    assets = ev.detail.get("assets")
    ok("assets recorded on the event", assets is not None)
    check("cash recorded", assets["denari"], 345.5)
    check("location recorded", assets["location"], "Town")
    ok("net worth recorded", "net_worth" in assets)
    ok("hunger recorded", assets["hunger"] == "Normal", str(assets.get("hunger")))


def test_assets_are_not_on_the_agents_own_ring_buffer() -> None:
    """Balances belong in the log, not in the agent's prompt memory.

    An agent already sees its current cash in the observation. Carrying 40 past
    copies of a fact it can look at would spend prompt budget to tell it
    something it knows -- PHASE4 §9's separate-budgets argument, one scope down.
    """
    w, log, a = setup()
    policy = ScriptedPolicy(log, [{
        "role": "assistant", "content": "Working.",
        "tool_calls": [tool_call("post_world_chat", {"text": "hi"})],
    }])
    policy.decide(w, a, "reevaluation")
    ok("no assets on Reasoning", not hasattr(a.reasoning[0], "assets"))


def test_business_cash_and_payroll_ride_along() -> None:
    """The two numbers behind every insolvency in the last run."""
    from convoy.state import Business, Employment

    w, log, a = setup()
    biz = Business(
        id="B0001", name="Test Mine", type="Mining Operation",
        location="Town", owner=a.id,
    )
    biz.cash = 210.0
    biz.roster = [Employment(agent_id="NPC1", role="Miner", wage=43.33)]
    w.businesses[biz.id] = biz
    a.owned_businesses.append(biz.id)

    policy = ScriptedPolicy(log, [{
        "role": "assistant", "content": "Checking the mine.",
        "tool_calls": [tool_call("post_world_chat", {"text": "hi"})],
    }])
    policy.decide(w, a, "reevaluation")

    held = next(e for e in log.events if e.type == "llm_reasoning").detail["assets"]
    check("one business", len(held["businesses"]), 1)
    b = held["businesses"][0]
    check("cash", b["cash"], 210.0)
    check("payroll", b["payroll_per_hour"], 43.33)


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
    print(f"\nOK -- {len(tests)} reasoning tests passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
