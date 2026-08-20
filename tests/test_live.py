#!/usr/bin/env python3
"""A world you can hold open, advise, and push forward.

Until 2026-08-19 `Engine.run` went from hour zero to the end of the run and
exited, so a world could only be watched after it was over. Advice given to a
finished run changed nothing -- there was no future left for it to change -- and
no amount of UI work on top could have fixed that.

These tests drive `LiveSession` against a scripted transport, so they assert the
mechanism rather than a model's cooperation or a network being up.

The two that matter:

  * `test_branch_does_not_inherit_the_parents_future` -- a checkpoint is written
    hourly but the parent keeps running after it, so its log always overshoots
    the state a branch starts from. Copying it wholesale spliced 240 events from
    a future the branch will not have into the history it starts with. Nothing
    raises; the branch just quietly carries someone else's timeline.
  * `test_advice_reaches_a_LIVE_agent` -- the entire purpose of the class.
"""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from convoy import checkpoint
from convoy import live as LV
from convoy.events import EventLog
from convoy.state import Agent, World

FAILURES: list[str] = []
HOUR = 3600.0


def check(label, actual, expected) -> None:
    if actual != expected:
        FAILURES.append(f"{label}: got {actual!r}, expected {expected!r}")


def ok(label, condition, detail="") -> None:
    if not condition:
        FAILURES.append(f"{label}{': ' + detail if detail else ''}")


def make_run(d: Path, at_hour: float = 10.0, log_to_hour: float = 10.9) -> Path:
    """A saved run: a checkpoint at `at_hour`, a log that overshoots it."""
    d.mkdir(parents=True, exist_ok=True)
    w = World()
    w.sim_time = at_hour * HOUR
    for i in range(2):
        a = Agent(id=f"A000{i}", name=f"agent-{i}", model="test/model", location="Town")
        a.denari = 400.0
        w.agents[a.id] = a
    checkpoint.save(w, d / "checkpoint.json")

    rows = []
    for h in (at_hour - 2.0, at_hour - 0.5, at_hour, log_to_hour):
        rows.append({
            "sim_time": h * HOUR, "type": "llm_reasoning", "significance": 1,
            "actor": "A0000", "subject": None, "location": "Town",
            "detail": {"woken_because": "reevaluation", "text": f"at {h}", "did": "wait"},
        })
    (d / "events.jsonl").write_text(
        "\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")
    return d


class ScriptedSession(LV.LiveSession):
    """A session whose transport never leaves the process."""

    @staticmethod
    def patch(session: LV.LiveSession, replies: list[dict]) -> LV.LiveSession:
        queue = list(replies)

        def fake_call(agent, messages, tools):
            # Budget checked BEFORE counting, matching `BudgetedPolicy._call`.
            # Counting the attempt made a session with no budget report
            # thousands of calls spent, which is the opposite of the guarantee.
            if session.policy.calls_made >= session.policy.call_budget:
                return None
            session.policy.calls_made += 1
            return queue.pop(0) if queue else {"role": "assistant", "content": "thinking"}

        session.policy._call = fake_call        # type: ignore[assignment]
        return session


# ---------------------------------------------------------------------------
# resuming
# ---------------------------------------------------------------------------

def test_resume_restores_the_world_at_its_saved_hour() -> None:
    with tempfile.TemporaryDirectory() as t:
        run = make_run(Path(t) / "run")
        s = LV.LiveSession.open(run, call_budget=0)
        check("resumed at the checkpoint hour", round(s.world.sim_hour, 2), 10.0)
        check("agents restored", len(s.world.agents), 2)
        s.close()


def test_branch_leaves_the_parent_untouched() -> None:
    """Thirty students must not be able to edit the baseline between them."""
    with tempfile.TemporaryDirectory() as t:
        run = make_run(Path(t) / "run")
        before = (run / "checkpoint.json").read_text()
        s = LV.LiveSession.open(run, branch_to=Path(t) / "branch", call_budget=0)
        s.world.agents["A0000"].denari = 999999.0
        s.close()
        check("parent checkpoint unchanged", (run / "checkpoint.json").read_text(), before)
        ok("branch is its own directory", s.run_dir != run)
        ok("branch records its parent", (Path(t) / "branch" / "PARENT").exists())


def test_branch_does_not_inherit_the_parents_future() -> None:
    """THE BUG. A checkpoint lags the log, so a wholesale copy splices timelines."""
    with tempfile.TemporaryDirectory() as t:
        run = make_run(Path(t) / "run", at_hour=10.0, log_to_hour=10.9)
        s = LV.LiveSession.open(run, branch_to=Path(t) / "branch", call_budget=0)
        rows = [
            json.loads(x)
            for x in (s.run_dir / "events.jsonl").read_text().splitlines() if x.strip()
        ]
        after = [r for r in rows if r["sim_time"] > 10.0 * HOUR]
        check("no events from after the fork", len(after), 0)
        ok("but the history before it was kept", len(rows) >= 3, str(len(rows)))
        s.close()


# ---------------------------------------------------------------------------
# stepping
# ---------------------------------------------------------------------------

def test_advance_moves_the_clock_and_reports_only_the_delta() -> None:
    """A viewer polling wants what just happened, not the whole log again."""
    with tempfile.TemporaryDirectory() as t:
        run = make_run(Path(t) / "run")
        s = ScriptedSession.patch(LV.LiveSession.open(run, call_budget=0), [])
        first = s.advance(wall_seconds=0.4)
        second = s.advance(wall_seconds=0.4)
        ok("clock advanced", second["to_hour"] > first["from_hour"])
        check("slices are contiguous", second["from_hour"], first["to_hour"])
        ok("delta only", all(e["hour"] >= first["to_hour"] - 0.001
                             for e in second["events"]), "stale events returned")
        s.close()


def test_a_wall_budget_is_honoured_and_reported() -> None:
    """An HTTP handler cannot block for the eight minutes an hour really takes."""
    with tempfile.TemporaryDirectory() as t:
        run = make_run(Path(t) / "run")
        s = ScriptedSession.patch(LV.LiveSession.open(run, call_budget=0), [])
        r = s.advance(wall_seconds=0.3, sim_hours=500.0)
        check("did not reach an absurd target", r["reached_target"], False)
        ok("but it did move", r["sim_minutes"] > 0)
        s.close()


def test_the_world_keeps_running_when_the_call_budget_is_gone() -> None:
    """Out of budget is a world going quiet, not a world freezing."""
    with tempfile.TemporaryDirectory() as t:
        run = make_run(Path(t) / "run")
        s = ScriptedSession.patch(LV.LiveSession.open(run, call_budget=0), [])
        before = s.world.sim_time
        s.advance(wall_seconds=0.4)
        ok("clock still advanced with no budget", s.world.sim_time > before)
        check("nothing was spent", s.policy.calls_made, 0)
        s.close()


def test_state_is_saved_so_a_session_can_be_reopened() -> None:
    """The persistence model: coming back tomorrow reopens your branch."""
    with tempfile.TemporaryDirectory() as t:
        run = make_run(Path(t) / "run")
        s = LV.LiveSession.open(run, branch_to=Path(t) / "b", call_budget=0)
        s.advance(wall_seconds=0.4)
        moved_to = s.world.sim_time
        s.close()
        again = LV.LiveSession.open(Path(t) / "b", call_budget=0)
        check("reopened where it left off", again.world.sim_time, moved_to)
        again.close()


# ---------------------------------------------------------------------------
# the point of all of it
# ---------------------------------------------------------------------------

def test_advice_reaches_a_LIVE_agent() -> None:
    with tempfile.TemporaryDirectory() as t:
        run = make_run(Path(t) / "run")
        s = ScriptedSession.patch(
            LV.LiveSession.open(run, call_budget=50),
            [{"role": "assistant", "content": "Right, I'll do that."}] * 20,
        )
        rec = s.advise("A0000", "Sell the ore now, the price is peaking.", who="Justin")
        ok("queued", rec is not None)
        check("not seen before the world moves", rec.times_seen, 0)
        for _ in range(6):
            s.advance(wall_seconds=0.4)
            if rec.times_seen:
                break
        ok("the live agent actually saw it", rec.times_seen > 0,
           "advice never reached a prompt -- delivery, not disobedience")
        ok("delivery hour recorded", rec.first_seen_hour is not None)
        s.close()


def test_advising_someone_who_is_not_there_is_a_refusal_not_a_crash() -> None:
    with tempfile.TemporaryDirectory() as t:
        run = make_run(Path(t) / "run")
        s = LV.LiveSession.open(run, call_budget=0)
        check("no such agent", s.advise("NOBODY", "do something"), None)
        s.close()


def test_positions_describe_everyone_alive() -> None:
    with tempfile.TemporaryDirectory() as t:
        run = make_run(Path(t) / "run")
        s = LV.LiveSession.open(run, call_budget=0)
        pos = s.positions()
        check("both agents", len(pos), 2)
        ok("carries what a map needs",
           {"id", "location", "doing", "net_worth", "advice_waiting"} <= set(pos[0]))
        s.close()


# ---------------------------------------------------------------------------
# what a viewer sees, and talking to someone mid-shift
# ---------------------------------------------------------------------------

def test_countdown_targets_the_next_DECISION_not_the_activity() -> None:
    """A work shift's `ends_at` sits in the PAST while the agent keeps working.

    Shifts run until something ends them, so a countdown built on `ends_at`
    reads as permanently overdue. What a person needs is when the agent next
    LISTENS, because that is when anything they say takes effect.
    """
    from convoy.state import Activity

    with tempfile.TemporaryDirectory() as t:
        run = make_run(Path(t) / "run")
        s = LV.LiveSession.open(run, call_budget=0)
        a = s.world.agents["A0000"]
        a.activity = Activity("work", s.world.sim_time - 5 * HOUR, {"role": "Miner"})
        a.next_reeval_at = s.world.sim_time + 900.0

        row = next(r for r in s.status() if r["id"] == "A0000")
        ok("countdown is never negative", row["next_decision_in_sim_seconds"] >= 0)
        ok("describes the trade, not the enum", "Miner" in row["doing"], row["doing"])
        ok("says what will pull it in", bool(row["next_decision_because"]))
        s.close()


def test_unheard_advice_makes_a_busy_agent_interruptible() -> None:
    """The engine wakes a working agent for advice it has not seen. Say so."""
    from convoy.state import Activity

    with tempfile.TemporaryDirectory() as t:
        run = make_run(Path(t) / "run")
        s = LV.LiveSession.open(run, call_budget=0)
        a = s.world.agents["A0000"]
        a.activity = Activity("work", s.world.sim_time + 8 * HOUR, {"role": "Miner"})

        before = next(r for r in s.status() if r["id"] == "A0000")
        check("busy, so not interruptible", before["can_be_interrupted_now"], False)

        s.advise("A0000", "Sell the ore now.", who="Justin")
        after = next(r for r in s.status() if r["id"] == "A0000")
        check("advice makes it interruptible", after["can_be_interrupted_now"], True)
        check("and it is the next thing to happen",
              after["next_decision_in_sim_seconds"], 0.0)
        s.close()


def test_the_present_block_is_prose_a_model_can_answer_from() -> None:
    """Handed a dict, a model narrates the epoch timestamp back at you."""
    from convoy.state import Activity

    with tempfile.TemporaryDirectory() as t:
        run = make_run(Path(t) / "run")
        s = LV.LiveSession.open(run, call_budget=0)
        a = s.world.agents["A0000"]
        a.activity = Activity("work", s.world.sim_time + HOUR, {"role": "Miner"})
        a.inventory = {"Copper Ore": 7}
        text = s.present_for(a)
        ok("says what it is doing", "Miner" in text, text)
        ok("says where", "Town" in text, text)
        ok("says what it carries", "7x Copper Ore" in text, text)
        ok("says when it next chooses", "choose what to do next" in text, text)
        ok("no raw timestamp", str(int(a.activity.ends_at)) not in text, text)
        s.close()


def test_asking_a_live_agent_does_not_move_the_world() -> None:
    """Advice is meant to change things. A question must not."""
    with tempfile.TemporaryDirectory() as t:
        run = make_run(Path(t) / "run")
        s = ScriptedSession.patch(LV.LiveSession.open(run, call_budget=5), [])
        before_time, before_events = s.world.sim_time, len(s.log.events)
        s.ask("A0000", "what are you doing?", who="Justin")
        check("clock untouched", s.world.sim_time, before_time)
        check("no world events emitted", len(s.log.events), before_events)
        s.close()


def test_a_question_about_the_future_is_not_refused_for_lack_of_a_record() -> None:
    """"What will you do next?" cites nothing, because it has not happened."""
    with tempfile.TemporaryDirectory() as t:
        run = make_run(Path(t) / "run")
        s = LV.LiveSession.open(run, call_budget=0)      # no model: recall path
        r = s.ask("A0000", "what are you going to do next?", who="Justin")
        ok("answered rather than refused", r["kind"] != "nothing", str(r))
        ok("grounded in the present", "Right now" in r["text"], r["text"][:120])
        s.close()


# ---------------------------------------------------------------------------
# the production countdown
# ---------------------------------------------------------------------------

def _producing_world(t: Path):
    """A world with one staffed, unblocked mine.

    Capacity is read from `business_storage_capacity`, never from the plot
    count: storage stopped being plots x 30 on 2026-08-19 and is now the
    business's startup cost. A test that filled a yard by the old formula
    overshot the new one and reported a full mine as having room for nine.
    """
    from convoy.state import Business, Employment

    run = make_run(Path(t) / "run")
    s = LV.LiveSession.open(run, call_budget=0)
    biz = Business(id="B0001", name="Test Mine", type="Mining Operation",
                   location="Town", owner="A0000")
    biz.active_production = "Copper Ore"
    biz.plots = 8
    biz.roster = [Employment(agent_id="NPC1", role="Miner", wage=43.33, is_npc=True)]
    s.world.businesses[biz.id] = biz
    s.world.agents["A0000"].owned_businesses.append(biz.id)
    return s, biz


def test_countdown_is_the_engines_own_arithmetic() -> None:
    """The bar must fill at the rate the engine is about to apply, not a copy.

    Recomputing the rate in the viewer works until one of the two changes, and
    then the countdown reaches zero at a moment nothing happens -- with nothing
    raising anywhere.
    """
    with tempfile.TemporaryDirectory() as t:
        s, biz = _producing_world(t)
        biz.production_buffer = 0.25
        row = next(r for r in s.production() if r["id"] == biz.id)

        rate = s.engine.production_rate(biz)
        ok("engine reports a rate", rate > 0, str(rate))
        check("viewer agrees with the engine", row["units_per_hour"], round(rate, 3))
        expected = (1.0 - 0.25) / rate * 3600.0
        check("countdown is (1-buffer)/rate",
              row["next_unit_in_sim_seconds"], round(expected, 1))
        check("bar reads the buffer", row["progress"], 0.25)
        s.close()


def test_asking_for_the_rate_does_not_train_the_crew() -> None:
    """A viewer polling four times a second must not grind everyone to mastery."""
    with tempfile.TemporaryDirectory() as t:
        from convoy.state import Employment

        s, biz = _producing_world(t)
        biz.roster = [Employment(agent_id="A0000", role="Miner", wage=30.0)]
        a = s.world.agents["A0000"]
        from convoy.state import Activity
        a.activity = Activity("work", s.world.sim_time + HOUR, {"business": biz.id})
        before = a.skill_hours.get("Miner", 0.0)
        for _ in range(20):
            s.production()
        check("no skill credited for looking", a.skill_hours.get("Miner", 0.0), before)
        s.close()


def test_crew_shares_sum_to_the_whole() -> None:
    with tempfile.TemporaryDirectory() as t:
        from convoy.state import Employment

        s, biz = _producing_world(t)
        biz.roster = [
            Employment(agent_id="NPC1", role="Miner", wage=43.33, is_npc=True),
            Employment(agent_id="NPC2", role="Miner", wage=43.33, is_npc=True),
        ]
        row = next(r for r in s.production() if r["id"] == biz.id)
        total = sum(m["share"] for m in row["crew"])
        ok("shares account for all output", abs(total - 1.0) < 0.02, f"{total:.3f}")
        s.close()


def test_a_state_business_splits_evenly_rather_than_double_counting() -> None:
    """State output is fixed by exemption, so per-worker attribution is a fiction.

    Running the normal maths gave two refinery workers 90% of the output EACH --
    180% of a number the engine holds flat at `base_rate`.
    """
    with tempfile.TemporaryDirectory() as t:
        from convoy.state import Employment

        s, biz = _producing_world(t)
        biz.owner = "Government"      # `is_government` is derived from this
        biz.roster = [
            Employment(agent_id="NPC1", role="Miner", wage=20.0, is_npc=True),
            Employment(agent_id="NPC2", role="Miner", wage=20.0, is_npc=True),
        ]
        row = next(r for r in s.production() if r["id"] == biz.id)
        total = sum(m["share"] for m in row["crew"])
        ok("still sums to one", abs(total - 1.0) < 0.02, f"{total:.3f}")
        ok("and splits evenly", all(abs(m["share"] - 0.5) < 0.02 for m in row["crew"]))
        s.close()


def test_a_stalled_yard_says_why_instead_of_showing_a_frozen_bar() -> None:
    """"Blocked" and "slow" look identical on a bar and need different fixes."""
    with tempfile.TemporaryDirectory() as t:
        s, biz = _producing_world(t)
        from convoy import economy as E
        biz.inventory = {"Copper Ore": E.business_storage_capacity(s.world, biz)}
        s.engine._produce(0.01)          # let the engine set the flag
        row = next(r for r in s.production() if r["id"] == biz.id)
        check("flagged", row["blocked"], True)
        ok("and named", "yard is full" in (row["blocked_reason"] or ""),
           str(row["blocked_reason"]))
        s.close()


# ---------------------------------------------------------------------------
# the owner's forecast
# ---------------------------------------------------------------------------

def test_forecast_is_clipped_by_what_actually_stops_it() -> None:
    """Rate x time is not a forecast.

    A mine running at 78.8 units an hour into a yard with room for nine will
    produce nine and stop. Multiplying tells its owner to expect seventy-nine.
    """
    with tempfile.TemporaryDirectory() as t:
        s, biz = _producing_world(t)
        from convoy import economy as E
        room = 9
        biz.inventory = {"Copper Ore": E.business_storage_capacity(s.world, biz) - room}
        r = next(x for x in s.forecast(minutes=60) if x["id"] == biz.id)
        ok("uncapped figure is much larger",
           r["units_if_nothing_stopped_it"] > room, str(r["units_if_nothing_stopped_it"]))
        check("clipped to the room left", r["units_expected"], float(room))
        ok("and says why", any("yard" in w for w in r["warnings"]), str(r["warnings"]))
        s.close()


def test_an_npc_stops_costing_when_the_line_stops() -> None:
    """NPCs bill only for hours the business can produce; people bill regardless."""
    with tempfile.TemporaryDirectory() as t:
        from convoy import economy as E

        s, biz = _producing_world(t)
        biz.cash = 10_000.0
        biz.inventory = {"Copper Ore": E.business_storage_capacity(s.world, biz)}   # full
        r = next(x for x in s.forecast(minutes=60) if x["id"] == biz.id)
        npc = next(m for m in r["crew"] if m["is_npc"])
        check("idle machine, no charge", npc["wage_cost_in_window"], 0.0)
        s.close()


def test_an_employee_keeps_costing_while_the_yard_is_full() -> None:
    """The asymmetry an owner most needs to see, and cannot see anywhere else."""
    with tempfile.TemporaryDirectory() as t:
        from convoy import economy as E
        from convoy.state import Activity, Employment

        s, biz = _producing_world(t)
        biz.cash = 10_000.0
        biz.roster = [Employment(agent_id="A0000", role="Miner", wage=30.0)]
        a = s.world.agents["A0000"]
        a.activity = Activity("work", s.world.sim_time + 8 * HOUR, {"business": biz.id})
        biz.inventory = {"Copper Ore": E.business_storage_capacity(s.world, biz)}   # full
        r = next(x for x in s.forecast(minutes=60) if x["id"] == biz.id)
        m = next(x for x in r["crew"] if x["agent"] == "A0000")
        check("billed for the whole hour anyway", m["wage_cost_in_window"], 30.0)
        check("makes nothing for it", m["units_in_window"], 0.0)
        s.close()


def test_an_owner_working_their_own_business_is_not_billed() -> None:
    """A wage of 0 is the owner, and it is the most reliable arrangement here."""
    with tempfile.TemporaryDirectory() as t:
        from convoy.state import Activity, Employment

        s, biz = _producing_world(t)
        biz.roster = [Employment(agent_id="A0000", role="Miner", wage=0.0)]
        a = s.world.agents["A0000"]
        a.activity = Activity("work", s.world.sim_time + 8 * HOUR, {"business": biz.id})
        r = next(x for x in s.forecast(minutes=60) if x["id"] == biz.id)
        m = next(x for x in r["crew"] if x["agent"] == "A0000")
        check("costs nothing", m["wage_cost_in_window"], 0.0)
        ok("and says why", "owner" in m["pay_basis"], m["pay_basis"])
        s.close()


def test_a_state_business_is_not_warned_that_its_staff_will_walk() -> None:
    """`_pay_wages` never touches a state business's cash and never releases it.

    Forecasting one like a player business had all three government sites
    reporting their crew were about to leave over a cash balance of zero.
    """
    with tempfile.TemporaryDirectory() as t:
        from convoy.state import Employment

        s, biz = _producing_world(t)
        biz.owner = "Government"
        biz.cash = 0.0
        biz.roster = [Employment(agent_id="NPC1", role="Miner", wage=40.0, is_npc=True)]
        r = next(x for x in s.forecast(minutes=60) if x["id"] == biz.id)
        check("marked", r["paid_from_treasury"], True)
        check("cash is not drawn down", r["cash_at_end"], 0.0)
        ok("no walkout warning", not any("walk" in w for w in r["warnings"]),
           str(r["warnings"]))
        s.close()


def test_a_state_business_is_still_capped_by_its_own_yard() -> None:
    """The exemptions are not symmetrical: own inputs, yes; infinite yard, no."""
    with tempfile.TemporaryDirectory() as t:
        from convoy import economy as E

        s, biz = _producing_world(t)
        biz.owner = "Government"
        biz.inventory = {"Copper Ore": E.business_storage_capacity(s.world, biz)}
        r = next(x for x in s.forecast(minutes=60) if x["id"] == biz.id)
        check("stalled despite being the state", r["units_expected"], 0.0)
        s.close()


def test_producing_is_not_earning() -> None:
    """Goods land in the yard, not the till. Only a sale moves money."""
    with tempfile.TemporaryDirectory() as t:
        from convoy.state import Employment

        s, biz = _producing_world(t)
        biz.cash = 500.0
        biz.roster = [Employment(agent_id="NPC1", role="Miner", wage=40.0, is_npc=True)]
        r = next(x for x in s.forecast(minutes=60) if x["id"] == biz.id)
        ok("value is produced", r["stock_value_added"] > 0)
        ok("and cash still only falls", r["cash_at_end"] < r["cash_now"],
           f"{r['cash_now']} -> {r['cash_at_end']}")
        s.close()


def main() -> int:
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for t in tests:
        t()
    print(f"test_live.py: {len(tests)} tests, {len(FAILURES)} failures")
    for f in FAILURES:
        print(f"  FAIL {f}")
    return 1 if FAILURES else 0


if __name__ == "__main__":
    raise SystemExit(main())
