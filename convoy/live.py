"""Holding a world OPEN, so somebody can talk to it while it is still moving.

THE PROBLEM THIS SOLVES

Everything before this could only look backwards. `Engine.run` went from hour
zero to the end of the run and exited; `serve.py` read the wreckage off disk.
So advice could be given to a finished world and change nothing -- there was no
future left for it to change -- and "direct an agent and watch what happens" was
not a feature that could be built on top, at any amount of UI work.

A `LiveSession` is a world held open: loaded from a checkpoint, pushed forward
in small bites, advised mid-flight, and saved again. That is the whole idea.

BRANCHING, AND WHY IT IS THE DEFAULT

A session normally BRANCHES rather than resuming in place: the baseline run is
copied, and everything after that belongs to whoever is driving. Two reasons,
and the second is the important one.

  * A shared baseline stays intact. Thirty students in a classroom start from
    the same hour-53 valley -- a developed economy with businesses already
    standing -- instead of each waiting eight wall-minutes per simulated hour
    to grow one.
  * **A branch is what makes a person's advice legible.** If everyone edits one
    world, "what did MY advice change?" has no answer, because everyone else was
    changing it too. One world per person, forked from a known point, means the
    difference between the branch and its parent is theirs.

That is also, exactly, the persistence model: a signed-in user's world is their
branch directory, and coming back tomorrow means reopening it.

WHAT THIS DELIBERATELY DOES NOT DO

It does not speed the simulation up. The measured rate is ~7 simulated hours per
wall-clock hour, and that is set by how fast the model answers -- 82 API calls
per simulated hour at 2.8 calls a decision -- not by the sim clock, which has
been running unthrottled all along. Scaling production to compensate would make
labour artificially cheap, because wages are per simulated hour; `run_phase2`'s
`--time-scale` flag carries that warning already. The honest lever is request
throughput, and the honest framing is that the rate is already fast enough to
watch: a cart crossing the whole valley takes about 41 seconds of real time.
"""

from __future__ import annotations

import shutil
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from . import advice as ADV
from . import checkpoint
from .engine import Engine, EngineConfig
from .events import EventLog, Significance
from .llm import LLMPolicy
from .state import Agent, World

# A live session must not be able to empty an account while nobody is watching.
# Counted in API CALLS rather than decisions because calls are what is billed,
# and a decision averages 2.8 of them.
DEFAULT_CALL_BUDGET = 1500

# Simulated seconds per real second, as a CEILING. 60 means a minute of valley
# time per second of yours: a cart crossing the whole road takes 5 wall seconds,
# and an agent reconsiders every 15.
#
# A ceiling, not a rate. When agents are thinking, the models are slower than
# this and the world runs at whatever they manage -- ~7 sim-seconds per real
# second, measured. The ceiling only bites when nothing needs deciding, and
# without it those stretches run at the speed of a for-loop: a 0.4-second test
# slice advanced the world THREE HUNDRED simulated hours and starved everyone
# in it, repeatedly. A viewer would have watched the valley flicker past.
#
# This is also the honest answer to "make it real time". The sim clock was never
# the thing holding it back -- it has been unthrottled all along -- so the lever
# is here, and the floor underneath it is request throughput.
DEFAULT_SPEED = 60.0

# How much wall time one `advance` may spend before returning. Sized to sit
# comfortably inside an HTTP timeout while still being long enough for something
# to happen: at the measured rate, 20s of wall clock is ~2.4 simulated minutes,
# which covers a decision and the start of a journey.
DEFAULT_SLICE_S = 20.0


def _copy_history(src: Path, dest: Path, fork_at: float) -> None:
    """Copy the parent's log up to the fork, and NOT ONE EVENT PAST IT.

    A checkpoint is written every simulated hour but the parent kept running
    after the last one, so its log always overshoots the state a branch actually
    starts from. Copying the file wholesale put the parent's next 54 minutes into
    the child's history -- events from a future the branch is not going to have,
    sitting in the same file as the one it does, ordered by a clock that no
    longer means one thing.

    Nothing raises when that happens. The branch simply carries a stretch of
    somebody else's timeline, the map draws both, and "what did my advice
    change?" is answered against a history that already contains the answer to a
    different question. Truncating is one comparison, and it is the difference
    between a fork and a splice.
    """
    if not src.exists():
        return
    import json as _json

    kept = 0
    with src.open(encoding="utf-8") as fh, dest.open("w", encoding="utf-8") as out:
        for line in fh:
            if not line.strip():
                continue
            try:
                if _json.loads(line).get("sim_time", 0.0) > fork_at:
                    continue
            except ValueError:
                continue
            out.write(line)
            kept += 1


class BudgetedPolicy(LLMPolicy):
    """An LLMPolicy that stops calling out once the session's budget is spent.

    Stops at the TRANSPORT, not at `decide`, so a session that runs out mid
    decision still records what the agent said and did up to that point --
    `LLMPolicy.decide` writes its reasoning in a `finally`, and short-circuiting
    higher up would throw that away.

    The world keeps running when the budget is gone. Agents stop deciding, but
    production, wages, hunger and travel all continue, so a session that runs
    out is a world that goes quiet rather than one that freezes -- and the
    difference is visible on the map, which is the point.
    """

    def __init__(self, *args, call_budget: int = DEFAULT_CALL_BUDGET, **kwargs):
        super().__init__(*args, **kwargs)
        self.call_budget = call_budget
        self.calls_made = 0
        self.exhausted_announced = False

    def _call(self, agent, messages, tools):
        if self.calls_made >= self.call_budget:
            return None
        self.calls_made += 1
        return super()._call(agent, messages, tools)

    @property
    def budget_left(self) -> int:
        return max(self.call_budget - self.calls_made, 0)


@dataclass
class LiveSession:
    """One world, held open and pushed forward on demand."""

    run_dir: Path
    world: World
    log: EventLog
    policy: BudgetedPolicy
    engine: Engine
    parent: Path | None = None
    opened_at: float = field(default_factory=time.monotonic)
    _opened_sim_time: float = 0.0

    # -- opening -----------------------------------------------------------

    @classmethod
    def open(
        cls,
        source: Path | str,
        *,
        branch_to: Path | str | None = None,
        model: str | None = None,
        rpm: float = 10.0,
        max_tokens: int = 1024,
        call_budget: int = DEFAULT_CALL_BUDGET,
        speed: float = DEFAULT_SPEED,
    ) -> "LiveSession":
        """Resume a saved run, branching it first unless told not to.

        `branch_to=None` resumes IN PLACE, which is for a single operator poking
        at their own run. Anything user-facing should branch -- see the module
        docstring.

        The event log is copied along with the checkpoint so a branch is
        self-contained: the map needs the whole history to draw the world, and a
        branch that could only be rendered next to its parent would be a
        footgun the first time one was moved.
        """
        source = Path(source)
        cp = source / "checkpoint.json"
        if not cp.exists():
            raise FileNotFoundError(f"no checkpoint.json in {source}")

        parent = None
        if branch_to is not None:
            parent = source
            source = Path(branch_to)
            source.mkdir(parents=True, exist_ok=True)
            shutil.copy2(cp, source / "checkpoint.json")
            fork_at = checkpoint.load(cp).sim_time
            _copy_history(parent / "events.jsonl", source / "events.jsonl", fork_at)
            (source / "PARENT").write_text(
                f"{parent}\nforked_at_hour={fork_at / 3600.0:.3f}\n", encoding="utf-8"
            )

        world = checkpoint.load(source / "checkpoint.json")
        # Append, never truncate -- the branch's history is the parent's history
        # plus whatever happens next, and a truncating open would silently throw
        # away the economy the session is meant to start from.
        log = EventLog(source / "events.jsonl", echo_min=Significance.HIGH)

        policy = BudgetedPolicy(
            log=log, requests_per_minute=rpm, max_completion_tokens=max_tokens,
            call_budget=call_budget,
        )
        if model:
            for a in world.agents.values():
                a.model = model

        engine = Engine(
            world, log, policy,
            EngineConfig(
                duration_hours=float("inf"),   # a live world has no end
                speed=speed,
                checkpoint_every_hours=1.0,
            ),
            on_checkpoint=lambda w: checkpoint.save(w, source / "checkpoint.json"),
        )
        session = cls(
            run_dir=source, world=world, log=log, policy=policy,
            engine=engine, parent=parent, _opened_sim_time=world.sim_time,
        )
        log.emit(
            world.sim_time, "session_opened",
            significance=Significance.HIGH,
            parent=str(parent) if parent else None,
            agents=sum(1 for a in world.agents.values() if a.alive),
            call_budget=call_budget,
        )
        return session

    # -- driving -----------------------------------------------------------

    def advance(
        self, wall_seconds: float = DEFAULT_SLICE_S, *, sim_hours: float | None = None
    ) -> dict[str, Any]:
        """Push the world forward, and report what happened while it moved.

        Returns the events produced by THIS slice, not the whole log. A viewer
        polling every few seconds wants the delta; handing it the history again
        each time is how a live map ends up redrawing an hour of the past on
        every frame.
        """
        start_index = len(self.log.events)
        start_hour = self.world.sim_hour

        target = (
            self.world.sim_time + sim_hours * 3600.0
            if sim_hours is not None else float("inf")
        )
        reached = self.engine.step_until(target, wall_budget_s=wall_seconds)
        checkpoint.save(self.world, self.run_dir / "checkpoint.json")

        fresh = self.log.events[start_index:]
        return {
            "from_hour": round(start_hour, 3),
            "to_hour": round(self.world.sim_hour, 3),
            "sim_minutes": round((self.world.sim_hour - start_hour) * 60.0, 2),
            "reached_target": reached,
            "calls_left": self.policy.budget_left,
            "budget_spent": self.policy.calls_made,
            "events": [
                {
                    "hour": round(e.sim_hour, 3), "type": e.type, "actor": e.actor,
                    "location": e.location, "detail": e.detail,
                }
                for e in fresh
            ],
        }

    def present_for(self, agent: Agent) -> str:
        """This agent's situation this second, as a sentence it can answer from.

        Written as prose rather than handed over as a dict because it goes into
        a prompt. A model given `{"activity": "work", "ends_at": 185340.0}` will
        cheerfully narrate the epoch timestamp back at whoever asked.
        """
        w = self.world
        when, why = self.next_decision_at(agent)
        mins = max(when - w.sim_time, 0.0) / 60.0
        detail = agent.activity.detail or {}
        if agent.in_transit:
            doing = f"on the road to {agent.in_transit[1]} ({agent.in_transit[2]*100:.0f}% of the way)"
        elif agent.activity.kind == "work" and detail.get("role"):
            biz = w.businesses.get(detail.get("business", ""))
            doing = f"part-way through a shift as {detail['role']}" + (
                f" at {biz.name}" if biz else "")
        else:
            doing = f"{agent.activity.kind} at {agent.location}"

        bits = [
            f"You are {doing}.",
            f"You are at {agent.location} with {agent.denari:.0f} denari.",
            f"You are {agent.sustenance_stage.lower()}.",
        ]
        if agent.inventory:
            bits.append("You are carrying " + ", ".join(
                f"{v}x {k}" for k, v in agent.inventory.items()) + ".")
        owned = [w.businesses[b] for b in agent.owned_businesses
                 if b in w.businesses and not w.businesses[b].closed]
        if owned:
            bits.append("You own " + ", ".join(
                f"{b.name} ({b.type}, {b.cash:.0f} cash)" for b in owned) + ".")
        if agent.current_job:
            bits.append(f"You are employed as {agent.current_job[1]} at "
                        f"{agent.current_job[2]:.2f}/hr.")
        bits.append(
            f"You get to choose what to do next in about {mins:.0f} simulated "
            f"minutes, when {why} pulls you in."
        )
        return " ".join(bits)

    def ask(self, agent_id: str, question: str, who: str = "a student") -> dict[str, Any]:
        """Question a LIVE agent -- answered from its record AND its situation.

        The finished-run interrogator only ever knew the log, so asked what it
        was going to do next it could only say nothing had happened yet. Half of
        talking to someone who is still moving is that they know where they are
        standing.

        Asking does NOT wake the agent or touch the world. Advice is meant to
        change what happens; a question must not, or the interview becomes part
        of what is being observed.
        """
        from . import conversation as CONV
        from . import interrogate as I

        agent = self.world.agents.get(agent_id)
        if agent is None:
            return {"error": f"no agent {agent_id}"}
        run = I.Run.load(self.run_dir)
        store = CONV.ConversationStore.load(self.run_dir)
        ans = I.answer(
            run, agent_id, question,
            policy=self.policy, model=agent.model,
            history=store.history(agent_id, who=who),
            present=self.present_for(agent),
        )
        store.add(agent_id, CONV.Exchange(
            hour=round(self.world.sim_hour, 2), who=who, question=question,
            answer=ans.text, kind=ans.kind, model_called=ans.model_called,
        ))
        return {"agent": agent_id, "question": question, "who": who, **ans.as_dict()}

    def advise(self, agent_id: str, text: str, who: str = "a student"):
        """Put advice in front of a LIVE agent. The whole point of the class."""
        return ADV.give(self.world, self.log, agent_id, text, from_who=who)

    # -- what a viewer needs to render ------------------------------------

    def observed_rate(self) -> float:
        """Simulated seconds per real second, as actually achieved so far.

        Reported rather than assumed. `DEFAULT_SPEED` is a ceiling and the models
        are usually slower than it, so a countdown computed from the ceiling
        would promise a decision in 20 seconds and deliver it in three minutes.
        A progress bar that lies is worse than no progress bar: it teaches a
        viewer to ignore it.
        """
        wall = max(time.monotonic() - self.opened_at, 1e-6)
        return max((self.world.sim_time - self._opened_sim_time) / wall, 1e-6)

    def next_decision_at(self, agent: Agent) -> tuple[float, str]:
        """When this agent next gets a turn, and what will pull it in.

        THE NUMBER THAT MATTERS FOR TALKING TO AN AGENT. Not "when does the
        activity end" -- a work shift's `ends_at` sits in the PAST while the
        agent keeps working, because shifts run until something ends them, so a
        countdown built on it reads as permanently overdue. What a person
        actually wants to know is when the agent will next listen, because that
        is when anything they say takes effect.

        Mirrors `Engine._decisions` deliberately. If the two disagree the bar
        counts down to a moment nothing happens at, which is exactly the class
        of bug that makes a demo feel broken without anything erroring.
        """
        w = self.world
        # Unheard advice interrupts a busy agent -- the engine says so, and it
        # is the whole reason you can talk to someone mid-shift.
        if any(r.times_seen == 0 for r in agent.live_advice(w.sim_hour)):
            return w.sim_time, "your message, as soon as the world ticks"
        if agent.sustenance_stage != "Normal":
            return w.sim_time, "hunger"
        busy = (
            agent.activity.kind in ("work", "travel")
            and agent.activity.ends_at > w.sim_time
        )
        if busy:
            return agent.activity.ends_at, (
                "arriving" if agent.activity.kind == "travel" else "finishing this shift"
            )
        return max(agent.next_reeval_at, w.sim_time), "its next scheduled think"

    def status(self) -> list[dict[str, Any]]:
        """Every living agent: what it is doing, and when it will next listen."""
        w = self.world
        rate = self.observed_rate()
        out = []
        for a in w.agents.values():
            if not a.alive:
                continue
            when, why = self.next_decision_at(a)
            sim_left = max(when - w.sim_time, 0.0)
            detail = a.activity.detail or {}
            doing = a.activity.kind
            if doing == "work" and detail.get("role"):
                doing = f"working as {detail['role']}"
            elif doing == "travel" and a.in_transit:
                doing = f"travelling to {a.in_transit[1]}"
            unheard = [r for r in a.live_advice(w.sim_hour) if r.times_seen == 0]
            out.append({
                "id": a.id, "name": a.name,
                "doing": doing,
                "at": a.location,
                # 0-1 along the road, straight off the engine's own tracker.
                "travel_progress": a.in_transit[2] if a.in_transit else None,
                "next_decision_in_sim_seconds": round(sim_left, 1),
                # The one a countdown should actually show.
                "next_decision_in_real_seconds": round(sim_left / rate, 1),
                "next_decision_because": why,
                "denari": round(a.denari, 2),
                "hunger": a.sustenance_stage,
                "unheard_advice": len(unheard),
                "can_be_interrupted_now": bool(unheard),
            })
        return out

    def production(self) -> list[dict[str, Any]]:
        """Every working business: what it is making, and when the next one lands.

        The countdown is real, not decorative. `production_buffer` fills at
        `Engine.production_rate` and pops a whole unit at 1.0, so the time to the
        next unit is `(1 - buffer) / rate` -- and the rate is read from the
        engine rather than recomputed, so the bar and the world cannot drift
        apart.

        This is also where a skill difference becomes VISIBLE. Two miners on the
        same seam with different `skill_hours` have different rates and therefore
        different countdowns, which has always been true and has never been
        anything a person could see.
        """
        w = self.world
        rate_sim = self.observed_rate()
        out = []
        for biz in w.businesses.values():
            if biz.closed or not biz.active_production:
                continue
            rate = self.engine.production_rate(biz)
            buffer_left = max(1.0 - biz.production_buffer, 0.0)
            sim_seconds = (buffer_left / rate * 3600.0) if rate > 0 else None
            out.append({
                "id": biz.id, "name": biz.name, "type": biz.type,
                "at": biz.location,
                "owner": biz.owner,
                "making": biz.active_production,
                "units_per_hour": round(rate, 3),
                # 0-1 toward the next whole unit -- the bar itself.
                "progress": round(min(biz.production_buffer, 1.0), 3),
                "next_unit_in_sim_seconds": (
                    round(sim_seconds, 1) if sim_seconds is not None else None
                ),
                "next_unit_in_real_seconds": (
                    round(sim_seconds / rate_sim, 1) if sim_seconds is not None else None
                ),
                # A stalled yard must say so rather than showing a bar that
                # never moves. "Blocked" and "slow" look identical otherwise,
                # and they need completely different things done about them.
                "blocked": biz.production_blocked,
                "blocked_reason": self._blocked_reason(biz),
                "stock": dict(biz.inventory),
                "crew": self.engine.worker_shares(biz),
            })
        return out

    def forecast(self, minutes: float = 60.0) -> list[dict[str, Any]]:
        """What each business will COST and PRODUCE over the next `minutes`.

        The instantaneous rate is not a forecast. A mine running at 78.8 units an
        hour into a yard with room for nine more will produce nine and then
        stop, and a dashboard that multiplies rate by time tells its owner to
        expect seventy-nine. So the horizon is clipped by whichever constraint
        binds first -- the yard filling, the feedstock running out, or the cash
        running out -- and the binding one is named.

        THE PAYROLL ASYMMETRY IS THE POINT. An NPC is paid only for hours the
        business can actually produce; an agent employee is paid for every hour
        it turns up, feedstock or not, because the risk sits with the owner who
        hired it (PHASE4 §5). So a blocked business keeps billing for its people
        and stops billing for its machines, and an owner cannot see that
        anywhere. It is the single most expensive thing to not know here: every
        payroll failure in the 84-hour run was NPC-staffed.

        Producing is NOT earning. Units land in inventory, not in cash -- only a
        sale moves money -- so `cash_at_end` falls by payroll and says nothing
        about the goods piling up. Showing projected revenue as income would
        make a stalled, cash-bleeding business look profitable.
        """
        from . import data as D
        from . import economy as E

        w = self.world
        hours = minutes / 60.0
        out = []
        for biz in w.businesses.values():
            if biz.closed or not biz.active_production:
                continue
            item = biz.active_production
            rate = self.engine.production_rate(biz)

            # Read from the engine, never recomputed. A first version worked the
            # exemptions out here and got them backwards -- it read "government"
            # as "unconstrained" and promised 36 units an hour out of a mine the
            # engine had already stalled for lack of anywhere to put them.
            limit, limit_why = self.engine.production_headroom(biz)
            uncapped = rate * hours
            units = min(uncapped, limit)
            productive_h = (units / rate) if rate > 0 else 0.0

            # A state business pays its people from the treasury, not from a
            # balance that can hit zero -- `_pay_wages` never touches `cash` for
            # one and never releases its staff. Forecasting it like a player
            # business had all three government sites reporting that their crew
            # were about to walk.
            state = biz.is_government

            npc_hourly = sum(e.wage for e in biz.roster if e.is_npc)
            agent_hourly = sum(
                e.wage for e in biz.roster
                if not e.is_npc and e.wage > 0
                and (a := w.agents.get(e.agent_id)) is not None
                and a.alive and a.activity.kind == "work"
                and a.activity.detail.get("business") == biz.id
            )
            # NPCs bill only while the line moves; people bill for turning up.
            cost = npc_hourly * productive_h + agent_hourly * hours
            payroll_hourly = npc_hourly + agent_hourly

            warnings = []
            if units < uncapped and limit_why:
                stops_in = productive_h * 60.0
                warnings.append(
                    f"production stops in {stops_in:.0f} sim-min -- {limit_why}"
                )
            if not state and payroll_hourly > 0 and biz.cash < payroll_hourly * hours:
                warnings.append(
                    f"cash runs out in {biz.cash / payroll_hourly * 60.0:.0f} sim-min "
                    f"-- unpaid staff walk and the insolvency clock starts"
                )
            if biz.production_blocked:
                warnings.append(f"stalled right now: {self._blocked_reason(biz)}")

            crew = []
            for m in self.engine.worker_shares(biz):
                agent = w.agents.get(m["agent"])
                on_shift = m["is_npc"] or bool(
                    agent and agent.alive and agent.activity.kind == "work"
                    and agent.activity.detail.get("business") == biz.id
                )
                # Three different ways to cost nothing, and they mean opposite
                # things to an owner. A wage of 0 is the OWNER working their own
                # business -- the single most reliable arrangement in the
                # economy, since every payroll failure in the 84-hour run was
                # NPC-staffed and no owner-operated business ever missed one.
                # An off-shift employee costs nothing because they are not there.
                # A stalled NPC costs nothing because the machine is idle. A flat
                # "paid even if stalled" flag called all three the same thing.
                if not on_shift:
                    basis = "not on shift -- costs nothing and produces nothing"
                elif m["wage"] <= 0:
                    basis = "the owner, working unpaid"
                elif m["is_npc"]:
                    basis = "NPC -- billed only while the line is moving"
                else:
                    basis = "employee -- billed for every hour on shift, stalled or not"
                worker_h = 0.0 if not on_shift else (
                    productive_h if m["is_npc"] else hours
                )
                crew.append({
                    **m,
                    "on_shift": on_shift,
                    "units_in_window": round(m["units_per_hour"] * productive_h, 2),
                    "wage_cost_in_window": round(max(m["wage"], 0.0) * worker_h, 2),
                    "pay_basis": basis,
                })

            out.append({
                "id": biz.id, "name": biz.name, "type": biz.type,
                "owner": biz.owner, "at": biz.location,
                "window_minutes": minutes,
                "making": item,
                "units_expected": round(units, 2),
                "units_if_nothing_stopped_it": round(uncapped, 2),
                "unit_price": round(biz.price_for(item), 2),
                "stock_value_added": round(units * biz.price_for(item), 2),
                "payroll_per_hour": round(payroll_hourly, 2),
                "wage_cost": round(cost, 2),
                "cash_now": round(biz.cash, 2),
                # Payroll only. Goods go to the yard, not the till.
                "cash_at_end": round(biz.cash, 2) if state else round(biz.cash - cost, 2),
                "paid_from_treasury": state,
                "hours_of_payroll_left": (
                    None if state or not payroll_hourly
                    else round(biz.cash / payroll_hourly, 2)
                ),
                "crew": crew,
                "warnings": warnings,
            })
        return out

    def _blocked_reason(self, biz) -> str | None:
        """Why nothing is coming out, in words an owner can act on."""
        if not biz.production_blocked:
            return None
        _units, why = self.engine.production_headroom(biz)
        return why or "stalled"

    def positions(self) -> list[dict[str, Any]]:
        """Where everyone is right now, for the map."""
        out = []
        for a in self.world.agents.values():
            if not a.alive:
                continue
            out.append({
                "id": a.id, "name": a.name, "location": a.location,
                "in_transit": a.in_transit, "doing": a.activity.kind,
                "denari": round(a.denari, 2),
                "net_worth": round(a.net_worth(self.world), 2),
                "hunger": a.sustenance_stage,
                "businesses": [
                    b for b in a.owned_businesses
                    if (biz := self.world.businesses.get(b)) and not biz.closed
                ],
                "advice_waiting": len(a.live_advice(self.world.sim_hour)),
            })
        return out

    def close(self) -> None:
        checkpoint.save(self.world, self.run_dir / "checkpoint.json")
        self.log.emit(
            self.world.sim_time, "session_closed",
            significance=Significance.HIGH,
            calls_spent=self.policy.calls_made,
        )
        self.log.flush()
        self.log.close()
