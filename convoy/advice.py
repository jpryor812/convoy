"""Advice from outside the simulation, and the machinery that delivers it.

WHAT THIS IS FOR

A student watching a run should be able to lean in and say "sell the ore, the
refinery two junctions over is paying more" -- and then find out whether the
agent listened. That is the difference between a visualisation and a lesson.

WHERE THE PARTS LIVE

    state.py     `Recommendation`, `Agent.inbox`, `Agent.receive_advice`
    observe.py   `advice_for` -- delivery, and the record that it happened
    llm.py       `advice_outcome` -- what the agent did while holding it
    here         the way in, and a scripted advisor for unattended runs

THE FAILURE TO EXPECT

Not disobedience. PHASE4 §2 lists thirteen occasions on which an agent looked
stupid because the observation withheld something the code already knew, and
this feature is built to make exactly that mistake visible: `times_seen` is
written only by the function that puts the words in a prompt, so "it ignored me"
and "it never heard me" are different rows in the log rather than the same
shrug.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

from .events import EventLog, Significance
from .state import ADVICE_TTL_HOURS, Agent, Recommendation, Snapshot, World


def take_snapshot(world: World) -> Snapshot:
    """The valley, right now, in the few numbers a before/after claim needs.

    Cheap enough to take on every recommendation (20 agents is a few hundred
    floats) and impossible to reconstruct afterwards, which settles the
    trade-off. See `Snapshot` for why the whole leaderboard is taken rather than
    just the advised agent.

    `runway_hours` mirrors `observe._owned_business_view`'s
    `hours_of_payroll_left` on purpose: the projection shown to a student should
    be the same number the agent itself was looking at, or the two accounts of
    the same hour will disagree.
    """
    snap = Snapshot(hour=round(world.sim_hour, 2))
    for a in world.agents.values():
        if not a.alive:
            continue
        snap.net_worth[a.id] = round(a.net_worth(world), 2)
        snap.denari[a.id] = round(a.denari, 2)
        snap.businesses[a.id] = sum(
            1 for bid in a.owned_businesses
            if (b := world.businesses.get(bid)) is not None and not b.closed
        )
    for b in world.businesses.values():
        if b.closed or b.is_government:
            continue
        payroll = sum(e.wage for e in b.roster if e.wage > 0)
        # A business with no wage bill cannot run out of money for wages. Stored
        # as infinity rather than skipped, so "no payroll" and "not recorded"
        # stay distinguishable in the saved run.
        snap.runway_hours[b.id] = round(b.cash / payroll, 2) if payroll else float("inf")
    return snap


def give(
    world: World,
    log: EventLog,
    agent_id: str,
    text: str,
    *,
    from_who: str = "mentor",
    expires_after_hours: float = ADVICE_TTL_HOURS,
) -> Recommendation | None:
    """Queue advice for one agent. The single way in, for scripts and servers alike.

    Returns None if there is nobody to advise. A dead agent is a real case --
    the demo's ask box will happily be pointed at one -- and it is a refusal,
    not a crash.
    """
    agent = world.agents.get(agent_id)
    if agent is None or not agent.alive:
        return None
    text = (text or "").strip()
    if not text:
        return None

    rec = agent.receive_advice(
        world.sim_hour, from_who, text, expires_after_hours=expires_after_hours
    )
    rec.before = take_snapshot(world)
    # Queued, NOT delivered -- `observe.advice_for` emits `advice_delivered`
    # when the text actually reaches a prompt. Two events because they are two
    # facts, and the gap between them is the first thing to check when advice
    # appears to have been ignored.
    log.emit(
        world.sim_time, "advice_given", actor=agent_id, location=agent.location,
        significance=Significance.MEDIUM,
        advice_id=rec.id, from_who=from_who, text=rec.text,
        expires_at_hour=round(rec.expires_at_hour(), 2),
    )
    return rec


# ---------------------------------------------------------------------------
# SCRIPTED ADVISING -- for runs with nobody watching
# ---------------------------------------------------------------------------

# Who to advise, given the world. A callable rather than an id, because an
# 84-hour run cannot know at hour 0 which agent will own a refinery at hour 40 --
# and advice aimed at an agent for whom it is meaningless proves nothing about
# whether agents take advice.
Selector = Callable[[World], list[Agent]]


@dataclass
class ScriptedAdvice:
    """One entry in an advisor's schedule."""

    at_hour: float
    text: str
    select: Selector
    from_who: str = "mentor"
    expires_after_hours: float = ADVICE_TTL_HOURS
    max_agents: int = 1


@dataclass
class Advisor:
    """Delivers a schedule of advice on the hourly beat, once each.

    Built for unattended runs. Its job is to put the channel under a live model
    before a classroom does, so that the first time real advice is given, the
    only unknown is whether the agent agreed with it -- not whether the plumbing
    works.

    Fires on the checkpoint hook, so it inherits that beat (hourly) and its
    rule that nothing here may take a twelve-hour run down.
    """

    log: EventLog
    schedule: list[ScriptedAdvice] = field(default_factory=list)
    fired: set[int] = field(default_factory=set)
    given: list[Recommendation] = field(default_factory=list)

    def __call__(self, world: World) -> None:
        for i, item in enumerate(self.schedule):
            if i in self.fired or world.sim_hour < item.at_hour:
                continue
            targets = item.select(world)[: item.max_agents]
            if not targets:
                continue          # nobody suitable YET -- try again next hour
            self.fired.add(i)
            for agent in targets:
                rec = give(
                    world, self.log, agent.id, item.text,
                    from_who=item.from_who,
                    expires_after_hours=item.expires_after_hours,
                )
                if rec is not None:
                    self.given.append(rec)
                    print(
                        f"  [{world.sim_hour:6.2f}h] ADVICE -> {agent.name:<14} "
                        f"{item.text[:70]}",
                        flush=True,
                    )

    def report(self, world: World) -> str:
        """Did the advice arrive, and what did the agent do while holding it?

        Delivery is reported first and separately. An advisor that reports only
        outcomes cannot tell "the agent weighed it and declined" apart from "the
        text never reached the prompt", and those need different fixes.
        """
        if not self.given:
            return "no advice was given"
        lines = [f"{'advice':<22}{'to':<16}{'seen':>6}  first seen"]
        unseen = 0
        for rec in self.given:
            owner = next(
                (a.name for a in world.agents.values()
                 if any(r.id == rec.id for r in a.inbox)),
                "?",
            )
            if rec.times_seen == 0:
                unseen += 1
            first = f"h{rec.first_seen_hour:.1f}" if rec.first_seen_hour else "NEVER"
            lines.append(f"{rec.id:<22}{owner:<16}{rec.times_seen:>6}  {first}")
        lines.append("")
        if unseen:
            lines.append(
                f"  ! {unseen} of {len(self.given)} recommendations NEVER REACHED A "
                f"PROMPT. That is a delivery bug, not an agent ignoring advice -- "
                f"check observe.advice_for and the TTL before blaming the model."
            )
        else:
            lines.append(
                f"  all {len(self.given)} recommendations reached the prompt; "
                f"see advice_outcome events for what each agent did about them"
            )
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# A default schedule
# ---------------------------------------------------------------------------

def _owners(world: World) -> list[Agent]:
    return [
        a for a in world.agents.values()
        if a.alive and a.owned_businesses
    ]


def _employed_not_owning(world: World) -> list[Agent]:
    return [
        a for a in world.agents.values()
        if a.alive and a.current_job and not a.owned_businesses
    ]


def _richest_without_business(world: World) -> list[Agent]:
    return sorted(
        (a for a in world.agents.values() if a.alive and not a.owned_businesses),
        key=lambda a: -a.denari,
    )


def _anyone(world: World) -> list[Agent]:
    return sorted(
        (a for a in world.agents.values() if a.alive), key=lambda a: a.id
    )


def smoke_schedule() -> list[ScriptedAdvice]:
    """The same channel, compressed into the first few hours.

    `default_schedule` fires between hours 6 and 60 and aims at owners and the
    employed, none of which exist in a six-hour smoke -- so a smoke run with the
    default schedule would deliver nothing and report success, which is the
    worst possible outcome for a test whose entire job is to prove delivery.

    These aim at anybody and ask for something a fresh agent can actually do on
    its next turn, so the run either shows the advice arriving or shows that it
    did not.
    """
    return [
        ScriptedAdvice(
            at_hour=0.5, select=_anyone, max_agents=2, expires_after_hours=4.0,
            text=(
                "Say hello in world chat and name one good you would buy or sell. "
                "Nobody can trade with someone they have never heard from, and "
                "chat reaches every living agent in the valley."
            ),
        ),
        ScriptedAdvice(
            at_hour=1.5, select=_anyone, max_agents=2, expires_after_hours=4.0,
            text=(
                "Eat before you do anything else if you have not eaten. The state "
                "tavern always has meals in stock and never runs out. Do not buy a "
                "second meal while you are still fed -- it buys you nothing."
            ),
        ),
        ScriptedAdvice(
            at_hour=2.5, select=_anyone, max_agents=2, expires_after_hours=4.0,
            text=(
                "You start with 200 denari. A Mining Operation costs 175 and has no "
                "input costs at all, so every unit you dig is pure margin. Consider "
                "founding one and working it yourself."
            ),
        ),
    ]


def default_schedule() -> list[ScriptedAdvice]:
    """Advice chosen so that following it is VISIBLE in the event log.

    Each one names an action the engine records under its own event type, so
    "did it comply?" is answerable by reading rows rather than by interpreting
    prose. Vague encouragement -- "trade wisely" -- would deliver just as well
    and prove nothing, because no log entry could ever contradict it.

    They are also spread across the run and across kinds of agent, since the
    open question is whether advice reaches an agent at all, and an advisor that
    only ever spoke to business owners at hour 6 would answer it for one case.
    """
    return [
        ScriptedAdvice(
            at_hour=6.0,
            select=_richest_without_business,
            max_agents=2,
            text=(
                "You have capital sitting idle. Mining Operation costs 175 and "
                "extraction has no input costs at all, so every unit you dig is "
                "pure margin -- it is the highest-margin tier in this economy. "
                "Found one and work it yourself rather than hiring: an NPC costs "
                "43.33/hr and will outrun your cash in under ten hours."
            ),
        ),
        ScriptedAdvice(
            at_hour=18.0,
            select=_owners,
            max_agents=2,
            text=(
                "Post a job advert instead of hiring an NPC. Use post_job with a "
                "wage above the player floor for the role. NPCs cost roughly 1.5x "
                "what an agent will take, and every business that missed payroll "
                "in the last run was NPC-staffed -- not one owner-operated one was."
            ),
        ),
        ScriptedAdvice(
            at_hour=30.0,
            select=_employed_not_owning,
            max_agents=2,
            text=(
                "Check the job board before your next shift. You may be able to "
                "beat your current wage: adverts now show even while you are "
                "employed, and an owner can hire you away from where you are. "
                "Apply to the best-paying advert you can see."
            ),
        ),
        ScriptedAdvice(
            at_hour=44.0,
            select=_owners,
            max_agents=3,
            text=(
                "Do not let your business idle for want of feedstock. Use "
                "order_from_business to have stock delivered -- you do not have to "
                "travel, and a courier will carry it. An idle yard still owes "
                "wages to any agent you employ."
            ),
        ),
        ScriptedAdvice(
            at_hour=60.0,
            select=_owners,
            max_agents=2,
            text=(
                "Say your prices out loud in world chat. Nobody can buy from a "
                "shop whose prices they have never seen, and chat reaches every "
                "living agent in the valley -- it is how prices, wages and "
                "carriage jobs get known."
            ),
        ),
    ]
