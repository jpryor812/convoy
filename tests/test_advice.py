#!/usr/bin/env python3
"""Advice from outside the sim must REACH THE PROMPT, and be seen to.

The recommendation channel exists so a student can tell an agent what to do and
then find out whether it listened. The interesting failure is not an agent
refusing advice -- that is a legitimate outcome and the point of the exercise.
The failure to guard against is the one PHASE4 §2 documents thirteen times: the
observation withholding something the code already knew, so the agent is blamed
for ignoring words it was never shown.

So these tests are weighted towards DELIVERY, not storage:

  * the text appears in the rendered prompt, and near the TOP of it -- the
    observation runs past 20,000 characters and a block after the price tables
    is present in the prompt and absent from the decision;
  * `times_seen` is written only when a prompt is actually built, so "ignored"
    and "never delivered" are distinguishable after the fact;
  * a run that builds an observation WITHOUT sending it does not count as
    delivery, or the one number that settles the argument is corrupted;
  * expiry, so hour-12 advice cannot reappear as current at hour 60;
  * `advice_outcome` pairs the advice with what the agent actually did;
  * the whole thing survives a checkpoint, including the before-snapshot.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from convoy import advice as ADV
from convoy import llm as L
from convoy import observe as O
from convoy.checkpoint import load, save
from convoy.events import EventLog
from convoy.engine import Engine, EngineConfig
from convoy.state import MAX_ADVICE_KEPT, Activity, Agent, Business, World

FAILURES: list[str] = []
HOUR = 3600.0


def check(label, actual, expected) -> None:
    if actual != expected:
        FAILURES.append(f"{label}: got {actual!r}, expected {expected!r}")


def ok(label, condition, detail="") -> None:
    if not condition:
        FAILURES.append(f"{label}{': ' + detail if detail else ''}")


class ScriptedPolicy(L.LLMPolicy):
    """LLMPolicy with a replayed transport, so `decide` runs for real."""

    def __init__(self, log: EventLog, replies: list[dict]) -> None:
        super().__init__(log=log, api_key="test-key")
        self._replies = list(replies)
        self.prompts: list[str] = []

    def _call(self, agent, messages, tools):
        # The user turn is what the model is actually shown.
        self.prompts.append(
            next((m["content"] for m in messages if m.get("role") == "user"), "")
        )
        return self._replies.pop(0) if self._replies else None


def tool_call(name: str, args: dict, call_id: str = "c1") -> dict:
    return {
        "id": call_id,
        "type": "function",
        "function": {"name": name, "arguments": json.dumps(args)},
    }


def setup(hour: float = 12.0) -> tuple[World, EventLog, Agent]:
    w, log = World(), EventLog(None, echo_min=99)
    w.sim_time = hour * HOUR
    a = Agent(id="A0001", name="Tester", model="test/model", location="Town")
    a.denari = 500.0
    w.agents[a.id] = a
    return w, log, a


# ---------------------------------------------------------------------------
# delivery -- the whole feature
# ---------------------------------------------------------------------------

def test_advice_appears_in_the_rendered_prompt() -> None:
    """Storage is not the feature. The words reaching the model is the feature."""
    w, log, a = setup()
    ADV.give(w, log, "A0001", "Sell the copper ore at Kiln Row, it pays more.")

    rendered = O.render(O.observe(w, log, a, "reevaluation"))
    ok("advice text is in the prompt", "Sell the copper ore at Kiln Row" in rendered, rendered[:400])
    ok("the giver is named", "mentor" in rendered)


def test_advice_is_near_the_top_of_the_prompt() -> None:
    """A 20,000-character observation buries anything placed after the tables.

    Asserted as a position, not a presence, because "it is in there somewhere"
    is exactly the state every entry in the PHASE4 §2 table was in.
    """
    w, log, a = setup()
    ADV.give(w, log, "A0001", "MARKERTEXT open a mine")

    rendered = O.render(O.observe(w, log, a, "reevaluation"))
    at = rendered.index("MARKERTEXT")
    ok("advice precedes the YOU block", at < rendered.index("\nYOU\n"), f"at {at}")
    ok("advice is in the first 600 chars", at < 600, f"at {at} of {len(rendered)}")


def test_header_line_announces_the_advice() -> None:
    """Line one, before anything the model has to scroll past."""
    w, log, a = setup()
    ADV.give(w, log, "A0001", "Post a job advert.")
    first = O.render(O.observe(w, log, a, "reevaluation")).splitlines()[0]
    ok("header names advice", "ADVICE" in first, first)


def test_times_seen_counts_only_real_prompts() -> None:
    w, log, a = setup()
    rec = ADV.give(w, log, "A0001", "Buy charcoal.")
    check("not seen when merely queued", rec.times_seen, 0)
    check("first_seen_hour unset", rec.first_seen_hour, None)

    O.observe(w, log, a, "reevaluation")
    check("seen once", rec.times_seen, 1)
    check("first_seen_hour recorded", rec.first_seen_hour, 12.0)

    O.observe(w, log, a, "reevaluation")
    check("seen twice", rec.times_seen, 2)
    check("first_seen_hour is the FIRST", rec.first_seen_hour, 12.0)


def test_observation_built_but_not_sent_is_not_delivery() -> None:
    """A dry run must not be able to report advice as delivered.

    If it could, `times_seen` would stop being evidence, and the only way to
    tell "the agent ignored me" from "the agent never heard me" would be gone.
    """
    w, log, a = setup()
    rec = ADV.give(w, log, "A0001", "Buy charcoal.")
    O.observe(w, log, a, "reevaluation", record_delivery=False)
    check("dry build does not count", rec.times_seen, 0)
    check("no first_seen_hour", rec.first_seen_hour, None)


def test_dry_run_policy_does_not_mark_delivery() -> None:
    """The same guarantee through the path that actually builds dry-run prompts."""
    w, log, a = setup()
    rec = ADV.give(w, log, "A0001", "Buy charcoal.")
    L.LLMPolicy(log=log, api_key="test-key", dry_run=True).decide(w, a, "reevaluation")
    check("dry run did not deliver", rec.times_seen, 0)


def test_advice_delivered_event_fires_once() -> None:
    w, log, a = setup()
    ADV.give(w, log, "A0001", "Buy charcoal.")
    O.observe(w, log, a, "reevaluation")
    O.observe(w, log, a, "reevaluation")
    O.observe(w, log, a, "reevaluation")

    given = [e for e in log.events if e.type == "advice_given"]
    delivered = [e for e in log.events if e.type == "advice_delivered"]
    check("queued once", len(given), 1)
    check("delivery announced once, not per prompt", len(delivered), 1)
    check("carries the text", delivered[0].detail["text"], "Buy charcoal.")


# ---------------------------------------------------------------------------
# the wake -- advice is useless if the agent is never asked
# ---------------------------------------------------------------------------

class _Recorder:
    """A policy that records the wakes it is given, and builds the observation.

    It calls `observe` because that is what marks delivery; a policy that only
    counted wakes would pass while the real delivery path stayed broken.
    """

    def __init__(self, log: EventLog) -> None:
        self.log = log
        self.reasons: list[str] = []

    def decide(self, world: World, agent: Agent, reason: str) -> None:
        self.reasons.append(reason)
        O.observe(world, self.log, agent, reason)


def _busy_world(hour: float = 1.0):
    w, log = World(), EventLog(None, echo_min=99)
    w.sim_time = hour * HOUR
    a = Agent(id="A0001", name="Tester", model="test/model", location="Town")
    a.denari = 500.0
    # Mid-shift, hours from finishing, and not hungry: the exact state in which
    # the engine's busy-guard refuses to ask an agent anything.
    a.activity = Activity("work", w.sim_time + 8 * HOUR)
    a.next_reeval_at = 0.0
    w.agents[a.id] = a
    return w, log, a


def _engine(w, log, policy):
    return Engine(w, log, policy, EngineConfig(duration_hours=0.0, speed=1e9))


def test_a_working_agent_is_not_woken_without_advice() -> None:
    """The guard this exemption sits inside must still hold. Baseline."""
    w, log, a = _busy_world()
    policy = _Recorder(log)
    _engine(w, log, policy)._decisions()
    check("busy agent left alone", policy.reasons, [])


def test_unheard_advice_wakes_a_working_agent() -> None:
    """The regression from the first live smoke.

    Six recommendations were queued, logged and correct, and every one expired
    unseen -- because their targets started shifts at hour 0.2 and the engine
    never asked them anything again. Delivery cannot be tested without the wake.
    """
    w, log, a = _busy_world()
    ADV.give(w, log, "A0001", "Stop mining and sell what you have.")
    policy = _Recorder(log)
    _engine(w, log, policy)._decisions()

    check("woken once", len(policy.reasons), 1)
    check("and told why", policy.reasons[0], "advice_received")
    check("delivered", a.inbox[0].times_seen, 1)


def test_advice_wakes_the_agent_exactly_once() -> None:
    """One interruption, not one per tick for the whole TTL.

    The busy-guard exists because 75% of all actions in one smoke were an agent
    reporting it was still working. Advice must not reopen that hole.
    """
    w, log, a = _busy_world()
    ADV.give(w, log, "A0001", "Sell the ore.")
    policy = _Recorder(log)
    engine = _engine(w, log, policy)

    for i in range(6):
        w.sim_time += 0.5 * HOUR
        engine._decisions()
    check("interrupted once", policy.reasons.count("advice_received"), 1)


def test_expired_advice_never_seen_does_not_wake_forever() -> None:
    """Advice nobody could deliver must stop asking once it lapses."""
    w, log, a = _busy_world()
    ADV.give(w, log, "A0001", "Sell the ore.", expires_after_hours=0.1)
    w.sim_time += 1.0 * HOUR
    policy = _Recorder(log)
    _engine(w, log, policy)._decisions()
    check("lapsed advice does not wake", policy.reasons, [])


def test_hunger_still_interrupts_work() -> None:
    """The pre-existing exemption must survive the new one."""
    w, log, a = _busy_world()
    a.sustenance_stage = "Hungry"
    policy = _Recorder(log)
    _engine(w, log, policy)._decisions()
    check("still woken for hunger", policy.reasons, ["reevaluation"])


# ---------------------------------------------------------------------------
# expiry
# ---------------------------------------------------------------------------

def test_advice_expires() -> None:
    """Advice about a market goes stale with the market."""
    w, log, a = setup(hour=10.0)
    ADV.give(w, log, "A0001", "STALE ADVICE", expires_after_hours=6.0)
    ok("live at h10", "STALE ADVICE" in O.render(O.observe(w, log, a, "reevaluation")))

    w.sim_time = 17.0 * HOUR
    ok("gone at h17", "STALE ADVICE" not in O.render(O.observe(w, log, a, "reevaluation")))


def test_expiry_is_not_defeated_by_the_log_that_records_it() -> None:
    """The regression. Expiry removed the ADVICE block and the log put it back.

    `advice_given` and `advice_delivered` carry the full text and do not expire,
    so at hour 17 an agent was shown hour-10 advice again as a raw event dump in
    RECENTLY -- reading as current, six hours after it lapsed. Asserted against
    the WHOLE rendered prompt rather than against `obs["advice"]`, because
    `obs["advice"]` was correct the entire time this bug existed.
    """
    w, log, a = setup(hour=10.0)
    ADV.give(w, log, "A0001", "LAPSEDTEXT", expires_after_hours=2.0)
    O.observe(w, log, a, "reevaluation")          # deliver it, logging the event

    w.sim_time = 20.0 * HOUR
    rendered = O.render(O.observe(w, log, a, "reevaluation"))
    ok("nowhere in the prompt at all", "LAPSEDTEXT" not in rendered,
       rendered[rendered.find("RECENTLY"):][:300])


def test_advice_events_do_not_spend_the_memory_budget() -> None:
    """Memory is 15 lines and holds rare, valuable news. An advisor must not evict it."""
    w, log, a = setup()
    for i in range(12):
        ADV.give(w, log, "A0001", f"advice {i}")
        O.observe(w, log, a, "reevaluation")
    memory = O.memory_for(log, a, w.sim_time)
    leaked = [m for m in memory if "advice" in m]
    check("no advice events in memory", leaked, [])


def test_expired_advice_is_kept_for_the_transcript() -> None:
    """Delivered-then-expired must stay readable, or 'what were you told?' cannot be answered."""
    w, log, a = setup(hour=10.0)
    ADV.give(w, log, "A0001", "old advice", expires_after_hours=2.0)
    w.sim_time = 40.0 * HOUR
    check("still in the inbox", len(a.inbox), 1)
    check("but not live", len(a.live_advice(w.sim_hour)), 0)


def test_inbox_is_bounded() -> None:
    w, log, a = setup()
    for i in range(MAX_ADVICE_KEPT + 8):
        ADV.give(w, log, "A0001", f"advice {i}")
    check("inbox bounded", len(a.inbox), MAX_ADVICE_KEPT)
    ok("oldest dropped", a.inbox[0].text == "advice 8", a.inbox[0].text)


# ---------------------------------------------------------------------------
# refusals
# ---------------------------------------------------------------------------

def test_advising_the_dead_and_the_absent_is_refused_not_crashed() -> None:
    w, log, a = setup()
    check("unknown agent", ADV.give(w, log, "A9999", "hello"), None)
    a.alive = False
    check("dead agent", ADV.give(w, log, "A0001", "hello"), None)
    a.alive = True
    check("empty advice", ADV.give(w, log, "A0001", "   "), None)


# ---------------------------------------------------------------------------
# evidence of what happened next
# ---------------------------------------------------------------------------

def test_advice_outcome_pairs_advice_with_what_the_agent_did() -> None:
    w, log, a = setup()
    ADV.give(w, log, "A0001", "Say something in world chat.")
    policy = ScriptedPolicy(log, [{
        "role": "assistant",
        "content": "Good idea, advertising my prices.",
        "tool_calls": [tool_call("post_world_chat", {"text": "bronze for sale"})],
    }])
    policy.decide(w, a, "reevaluation")

    outcomes = [e for e in log.events if e.type == "advice_outcome"]
    check("one outcome", len(outcomes), 1)
    d = outcomes[0].detail
    check("the advice", d["advice"], "Say something in world chat.")
    check("what it did", d["did"], "post_world_chat")
    ok("its own words", "advertising my prices" in d["text"], d["text"])


def test_outcome_records_declining_as_readily_as_complying() -> None:
    """Disagreement is a legitimate outcome and must leave the same evidence."""
    w, log, a = setup()
    ADV.give(w, log, "A0001", "Found a mine right now.")
    policy = ScriptedPolicy(log, [{
        "role": "assistant",
        "content": "I have 500 denari and a mine is 175, but I would rather eat first.",
    }])
    policy.decide(w, a, "reevaluation")

    outcomes = [e for e in log.events if e.type == "advice_outcome"]
    check("still recorded", len(outcomes), 1)
    check("no action taken", outcomes[0].detail["did"], "nothing")
    ok("reason preserved", "rather eat first" in outcomes[0].detail["text"])


def test_no_advice_means_no_outcome_events() -> None:
    w, log, a = setup()
    policy = ScriptedPolicy(log, [{
        "role": "assistant", "content": "Nothing to do.",
    }])
    policy.decide(w, a, "reevaluation")
    check("no outcomes", len([e for e in log.events if e.type == "advice_outcome"]), 0)


def test_the_prompt_the_model_saw_contained_the_advice() -> None:
    """End to end: through `decide`, not through a hand-built observation."""
    w, log, a = setup()
    ADV.give(w, log, "A0001", "UNIQUEPHRASE sell the ore")
    policy = ScriptedPolicy(log, [{"role": "assistant", "content": "noted"}])
    policy.decide(w, a, "reevaluation")
    ok("advice was in the sent prompt", "UNIQUEPHRASE" in policy.prompts[0], policy.prompts[0][:300])


# ---------------------------------------------------------------------------
# the before-snapshot
# ---------------------------------------------------------------------------

def test_snapshot_captures_the_whole_leaderboard() -> None:
    """The interesting half of an intervention is what it did to everyone else."""
    w, log, a = setup()
    other = Agent(id="A0002", name="Rival", model="test/model", location="Town")
    other.denari = 900.0
    w.agents[other.id] = other

    rec = ADV.give(w, log, "A0001", "Open a second mine.")
    ok("snapshot taken", rec.before is not None)
    check("snapshot hour", rec.before.hour, 12.0)
    check("advised agent recorded", rec.before.denari["A0001"], 500.0)
    ok("unadvised agent ALSO recorded", "A0002" in rec.before.net_worth,
       str(rec.before.net_worth))


def test_snapshot_records_payroll_runway() -> None:
    """The honest ancestor of 'would have gone bankrupt'."""
    w, log, a = setup()
    b = Business(
        id="B0001", name="Test Mine", type="Mining Operation",
        owner="A0001", location="Town", cash=200.0,
    )
    b.roster.append(_employee("A0002", "Miner", 40.0))
    w.businesses[b.id] = b
    a.owned_businesses.append(b.id)

    rec = ADV.give(w, log, "A0001", "Order feedstock.")
    check("runway is cash over payroll", rec.before.runway_hours["B0001"], 5.0)


def _employee(agent_id: str, role: str, wage: float):
    from convoy.state import Employment
    return Employment(agent_id=agent_id, role=role, wage=wage)


# ---------------------------------------------------------------------------
# persistence
# ---------------------------------------------------------------------------

def test_advice_survives_a_checkpoint() -> None:
    """A saved world that forgets what it was told cannot be returned to."""
    w, log, a = setup()
    rec = ADV.give(w, log, "A0001", "Sell the ore at Kiln Row.")
    O.observe(w, log, a, "reevaluation")

    path = Path(__file__).parent / "__pycache__" / "advice_checkpoint.json"
    save(w, path)
    restored = load(path)
    path.unlink(missing_ok=True)

    back = restored.agents["A0001"].inbox
    check("round-tripped", len(back), 1)
    check("text intact", back[0].text, "Sell the ore at Kiln Row.")
    check("times_seen intact", back[0].times_seen, 1)
    check("first_seen intact", back[0].first_seen_hour, 12.0)
    ok("snapshot intact", back[0].before is not None)
    check("snapshot values intact", back[0].before.denari["A0001"], 500.0)
    ok("still live after restore", len(restored.agents["A0001"].live_advice(12.0)) == 1)


# ---------------------------------------------------------------------------
# the scripted advisor
# ---------------------------------------------------------------------------

def test_advisor_fires_once_per_entry() -> None:
    w, log, a = setup(hour=0.0)
    advisor = ADV.Advisor(log=log, schedule=[
        ADV.ScriptedAdvice(at_hour=5.0, text="advice one", select=lambda wd: list(wd.agents.values())),
    ])
    advisor(w)                        # h0 -- too early
    check("not yet", len(a.inbox), 0)

    w.sim_time = 6.0 * HOUR
    advisor(w)
    advisor(w)
    advisor(w)
    check("fired exactly once", len(a.inbox), 1)


def test_advisor_waits_for_a_suitable_target() -> None:
    """An entry whose selector finds nobody must retry, not be consumed.

    A schedule aimed at business owners at hour 18 proves nothing if it fires
    into an empty list at 18.0 and never speaks again.
    """
    w, log, a = setup(hour=0.0)
    advisor = ADV.Advisor(log=log, schedule=[
        ADV.ScriptedAdvice(
            at_hour=5.0, text="owners only",
            select=lambda wd: [x for x in wd.agents.values() if x.owned_businesses],
        ),
    ])
    w.sim_time = 6.0 * HOUR
    advisor(w)
    check("nobody to advise yet", len(a.inbox), 0)
    check("entry not consumed", len(advisor.fired), 0)

    w.businesses["B0001"] = Business(
        id="B0001", name="Test Mine", type="Mining Operation",
        owner="A0001", location="Town", cash=100.0,
    )
    a.owned_businesses.append("B0001")
    w.sim_time = 9.0 * HOUR
    advisor(w)
    check("fires once a target exists", len(a.inbox), 1)


def test_advisor_report_names_undelivered_advice_as_a_delivery_bug() -> None:
    """The report must not let a plumbing failure read as an agent ignoring advice."""
    w, log, a = setup(hour=0.0)
    advisor = ADV.Advisor(log=log, schedule=[
        ADV.ScriptedAdvice(at_hour=0.0, text="never seen", select=lambda wd: list(wd.agents.values())),
    ])
    advisor(w)
    text = advisor.report(w)
    ok("flags it", "NEVER REACHED A PROMPT" in text, text)

    O.observe(w, log, a, "reevaluation")
    ok("clears once delivered", "NEVER REACHED A PROMPT" not in advisor.report(w), advisor.report(w))


def test_default_schedule_targets_are_all_reachable() -> None:
    """Every entry must be able to select somebody, or it is dead weight in the run."""
    for item in ADV.default_schedule():
        ok(f"{item.at_hour}h has text", len(item.text) > 40)
        ok(f"{item.at_hour}h has a selector", callable(item.select))


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
    print(f"\nOK -- {len(tests)} advice tests passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
