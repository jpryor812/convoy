"""The simulation engine: clock, continuous processes, and decision scheduling.

Time model. The world clock runs in true real time for the actual 120-hour run
(no compression, per the handoff). For validation the clock takes a `speed`
multiplier so a full 120-hour economy can be exercised in seconds; the real run
uses speed=1.0 and sleeps against the wall clock.

Decision model matches the Agent Scheduling & Diary tab: decisions fire when an
activity concludes, on interrupt, and on a universal 15-simulated-minute
re-evaluation checkpoint that applies to every agent regardless of activity.
Phase 1 resolves decisions with deterministic policies; Phase 2 swaps the policy
for an OpenRouter call behind the same interface.
"""

from __future__ import annotations

import random
import threading
import time
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass
from typing import Callable, Protocol

from . import banditry as B
from . import combat as CB
from . import ground as GR
from . import raids as R
from . import data as D
from . import economy as E
from . import world_map as M
from .events import EventLog, Significance
from . import digest as DG
from . import reflexes as RX
from . import actions as A
from . import progress as PG
from . import family as FAM
from . import delivery as DL
from . import land as LAND
from . import discovery as DS
from .state import Activity, Agent, Business, Transaction, World

TICK_SECONDS = 60.0     # one simulated minute of continuous processes


class Policy(Protocol):
    """What the engine needs from a decision-maker.

    Phase 1: rule-based. Phase 2+: an OpenRouter-backed policy with the identical
    signature, so the engine is agnostic to which is driving.
    """

    def decide(self, world: World, agent: Agent, reason: str) -> None: ...


def _share_of(total: int, fraction: float) -> int:
    """How many units a robbery takes out of `total`.

    Always at least one -- "you were robbed and lost nothing" is a worse story
    than either outcome it sits between. There is no longer a unit held back at
    the top: `LOOT_FRACTION_MAX` is 1.0 and a total loss is meant to be
    reachable, so clamping one survivor would quietly make the worst case
    unreachable and the insurance that covers it pointless.
    """
    if total <= 0:
        return 0
    return max(1, min(round(total * fraction), total))


# See `Engine._stagger_opening`.
OPENING_WINDOW_MINUTES = 45.0


@dataclass
class EngineConfig:
    duration_hours: float = D.SIM_DURATION_HOURS
    speed: float = 3600.0                 # sim seconds per real second; 1.0 == real time
    checkpoint_every_hours: float = 1.0
    reeval_minutes: float = D.REEVALUATION_INTERVAL_MIN
    diary_hours: float = D.DIARY_INTERVAL_HOURS
    # BANDITRY IS THE FIRST RANDOMNESS IN THIS SIMULATION. Everything before it
    # was deterministic, which is worth not giving up by accident -- so the seed
    # is explicit and a run records it. A resumed run re-seeds: the checkpoint
    # holds plain dataclasses and a `random.Random` is not one, so storing the
    # generator would break `checkpoint.save`. Replaying a run reproduces its
    # events from the log, not by re-rolling.
    banditry: bool = True
    banditry_seed: int = 20260820
    # THE STATE WITHDRAWS at this simulated hour, or never if None. Scheduled
    # inside the engine rather than done by stopping and editing a checkpoint,
    # so it lands on the exact hour, needs no pause, and cannot smuggle in a
    # changed prompt halfway through -- which is what made the first attempt two
    # experiments instead of one.
    state_exits_at: float | None = None
    # Which city the state leaves at `state_exits_at`. None: every city at once,
    # as before. A city key: that city only, and the other keeps its government
    # for the whole run -- the controlled experiment a contest makes possible.
    state_exits_city: str | None = None
    # AGENTS DECIDING IN PARALLEL. 1 is the original behaviour, exactly: each
    # decision runs to completion inside the tick that asked for it, and the
    # clock waits. Above 1, a decision runs on a worker thread while the world
    # goes on; the agent acts when its answer arrives, the way a person who
    # stops to think does. Every test and scripted run uses 1, so nothing that
    # depends on order changes for them.
    #
    # Why it matters: the 2026-10-15 run took 31 wall hours for 60 simulated,
    # almost all of it one agent waiting on the model while 39 others waited on
    # that agent. A person playing alongside 59 agents cannot wait like that.
    decision_workers: int = 1
    # Make the one-answer moves (eat, load and go, keep working, keep waiting)
    # without asking the model. See `convoy/reflexes.py`. Off by default so
    # scripted policies and their tests see every wake; model runs turn it on.
    reflexes: bool = False
    # Owners buy the inputs their stalled businesses lack, every game hour,
    # without a model call (see reflexes.restock). Not for `manual_agents`:
    # the player runs their own purchasing.
    restock: bool = False
    manual_agents: frozenset = frozenset()
    # How far the clock may run ahead of the oldest decision still being
    # thought about, in simulated minutes. Small, so a decision lands close to
    # the moment it was asked for; large enough that many agents think at once.
    max_decision_lag_minutes: float = 5.0


class Engine:
    def __init__(
        self,
        world: World,
        log: EventLog,
        policy: Policy,
        config: EngineConfig | None = None,
        on_checkpoint: Callable[[World], None] | None = None,
    ):
        self.world = world
        self.log = log
        self.policy = policy
        self.config = config or EngineConfig()
        self.on_checkpoint = on_checkpoint
        # One lock over the world. The engine holds it for every tick; a worker
        # takes it to build an observation or to act, and lets go while it
        # waits for the model. See `EngineConfig.decision_workers`.
        self.world_lock = threading.RLock()
        self._pool: ThreadPoolExecutor | None = None
        self._pending: dict[str, tuple[Future, float]] = {}
        if self.config.decision_workers > 1:
            self._pool = ThreadPoolExecutor(
                max_workers=self.config.decision_workers, thread_name_prefix="decide"
            )
            if hasattr(self.policy, "world_lock"):
                self.policy.world_lock = self.world_lock
        self._rng = random.Random(self.config.banditry_seed)
        # A resumed world may already be past the withdrawal hour; the state is
        # gone if there is no open government business left to close.
        target = self.config.state_exits_city
        self._state_gone = (
            (world.state_gone_at(target) is not None) if target
            else world.state_withdrawn_at is not None
        ) or not any(
            b.is_government and not b.closed
            and (target is None or M.city_of(b.location) == target)
            for b in world.businesses.values()
        )
        # Relative to where the WORLD is, not to zero. Identical for a fresh
        # world, and the difference between working and not for a resumed one: a
        # world reloaded at hour 84 has already passed an absolute 1.0, so the
        # due-check fires on every tick and the counter creeps forward one hour
        # per simulated MINUTE -- 5,000 redundant saves before it catches up.
        self._next_checkpoint = (
            world.sim_time + self.config.checkpoint_every_hours * 3600.0
        )
        self._next_restock = world.sim_time + 3600.0
        # OUTPOSTS: when the frontier is next looked over for people finding
        # each other, and where anyone not on the road network really is (the
        # player, walking the 3D world). See `convoy/discovery.py`.
        self._next_discovery = world.sim_time
        self.positions: dict[str, tuple[float, float]] = {}

    # -- main loop ---------------------------------------------------------

    def run(self) -> None:
        w, cfg = self.world, self.config

        self.log.emit(
            w.sim_time, "sim_start",
            agents=len(w.agents), businesses=len(w.businesses),
            duration_hours=cfg.duration_hours,
            # Which cities this run contains, on line one of the log, so a
            # page drawing a run before its first save knows the map to draw.
            cities=list(w.cities), no_state=w.no_state,
        )
        if w.sim_time == 0.0:
            self._stagger_opening()
        self.step_until(cfg.duration_hours * 3600.0)
        self.drain()
        self.log.emit(
            w.sim_time, "sim_end",
            leaderboard=[(n, round(v, 1)) for n, v in w.leaderboard()[:10]],
            treasury=round(w.government.treasury, 1),
        )
        self.log.flush()

    def _stagger_opening(self) -> None:
        """Wake each city's citizens one after another at hour zero, not all at once.

        THE FIRST NO-STATE SMOKE (2026-10-16): twelve agents, four to a city,
        all asked at minute zero in parallel, all looking at the same empty
        valley -- and all twelve founded a Tavern, each announcing it as the
        city's first. None could see the others' choice, because none had been
        made yet. After that no one had the cash for the Refinery between farm
        and tavern, and nobody ate.

        So within a city the opening decisions are spaced further apart than
        the clock may run ahead of a pending decision (`max_decision_lag_
        minutes`): each citizen's first decision cannot start until the one
        before it has acted, so they see what has been founded and what has
        been said in chat. Cities open side by side; a citizen of one is no
        rival for the other's first tavern. With one decider at a time there is
        no overlap to space out.

        The whole opening is capped at `OPENING_WINDOW_MINUTES`, though: at the
        full gap the twentieth citizen of a city would wait nearly two hours of
        a twenty-four-hour ration for a first turn. A crowded city's gaps
        shrink, so two or three neighbours may overlap; the briefing's "say
        what you are founding before you found it" covers that.
        """
        if self.config.decision_workers <= 1:
            return
        full = (self.config.max_decision_lag_minutes + 1.0) * 60.0
        for city in self.world.cities:
            citizens = self.world.agents_in(city)
            gap = min(full, OPENING_WINDOW_MINUTES * 60.0 / max(1, len(citizens) - 1))
            for k, agent in enumerate(citizens):
                agent.activity = Activity("idle", k * gap)
                agent.next_reeval_at = k * gap

    def step_until(
        self, end_sim_time: float, *, wall_budget_s: float | None = None
    ) -> bool:
        """Advance to `end_sim_time`, or until `wall_budget_s` of real time is up.

        THE SEAM FOR WATCHING A WORLD LIVE. `run` was a closed loop from zero to
        the end of the run, so the only thing anyone could do with a world was
        start one and wait for it -- which is why advice could be given to a
        finished run and change nothing. There was no future left to change.
        Pulling the loop out here lets a caller hold a world open and push it
        forward a little at a time, which is what makes "tell an agent something
        and watch what it does" possible at all.

        `wall_budget_s` exists because the caller is usually answering an HTTP
        request. Stepping an hour takes about eight wall minutes at the measured
        rate, so a request that asked for an hour and got no reply until it had
        one would simply time out. With a budget the call returns whatever it
        managed and the caller comes back for more; the world is left in a
        perfectly valid state either way, since a tick is atomic.

        Returns True if it reached `end_sim_time`, False if the budget ran out
        first -- so a caller can tell "done" from "there is more to do".
        """
        w, cfg = self.world, self.config
        started_wall = time.monotonic()
        # Wall-clock pacing is relative to where this call STARTED, not to the
        # world's zero -- a session resumed at hour 53 would otherwise compute a
        # target hundreds of hours in the past and never sleep at all.
        base_sim = w.sim_time

        while w.sim_time < end_sim_time:
            with self.world_lock:
                self.tick(TICK_SECONDS)
            self._keep_up()

            if cfg.speed < 1000:  # real-time or near-real-time: pace to the clock
                drift = (
                    started_wall + (w.sim_time - base_sim) / cfg.speed
                    - time.monotonic()
                )
                if drift > 0:
                    time.sleep(drift)

            if (w.digest_at < 0.0
                    or w.sim_time >= w.digest_at + DG.DIGEST_EVERY_HOURS * 3600.0 - 1e-6):
                with self.world_lock:
                    self._publish_digest()

            if cfg.restock and w.sim_time >= self._next_restock:
                with self.world_lock:
                    self._next_restock = w.sim_time + 3600.0
                    for agent in list(w.agents.values()):
                        if agent.alive and agent.owned_businesses and agent.id not in cfg.manual_agents:
                            RX.restock(w, self.log, agent, self.production_rate)

            if w.sim_time >= self._next_checkpoint:
                with self.world_lock:
                    self._next_checkpoint += cfg.checkpoint_every_hours * 3600.0
                    self._record_standings()
                    self.log.flush()
                    if self.on_checkpoint:
                        self.on_checkpoint(w)

            if (
                wall_budget_s is not None
                and time.monotonic() - started_wall >= wall_budget_s
            ):
                self.log.flush()
                return False

        return True

    # -- one simulated minute ---------------------------------------------

    def tick(self, dt: float) -> None:
        w = self.world
        w.sim_time += dt
        hours = dt / 3600.0

        # Fires once, on the first tick at or past the hour. Before anything
        # else in the tick, so nobody is paid a wage by an employer that has
        # already shut.
        exit_at = self.config.state_exits_at
        if exit_at is not None and not self._state_gone and w.sim_hour >= exit_at:
            self._state_gone = True
            self._withdraw_the_state(self.config.state_exits_city)

        self._advance_travel(dt)
        self._finish_developments()
        self._sustenance(hours)
        self._produce(hours)
        self._pay_wages(hours)
        self._research(hours)
        # Projects, know-how and households: the countdowns. See progress, family.
        PG.tick_projects(w, self.log, hours)
        PG.tick_research(w, self.log, hours)
        FAM.tick(w, self.log)
        CB.regen(w, hours)
        GR.tick(w, hours)
        self._dispatches()
        self._debt_interest(hours)
        if w.outposts and w.sim_time >= self._next_discovery:
            self._next_discovery = w.sim_time + DS.EVERY_S
            DS.tick(w, self.log, self.positions)
        self._property_tax()
        self._road_tax()
        self._expire_social()
        self._expire_job_postings()
        self._check_solvency()
        self._respawn()
        self._decisions()
        self._diaries()

    # -- continuous processes ---------------------------------------------

    def _dispatches(self) -> None:
        """Meals a tavern sent out arrive in what their buyer carries; the
        state's convoy collects what it bought and pays for it. Outposts,
        2026-10-27; see `actions.order_meal` and `actions.sell_to_bidder`."""
        w = self.world
        for d in list(w.dispatches.values()):
            if d.status != "on_way" or d.arrives_at > w.sim_time:
                continue
            d.status = "done"
            if d.kind == "meal":
                a = w.agents.get(d.agent)
                if a is not None and a.alive:
                    a.add_item(d.item, d.qty)
                    self.log.emit(w.sim_time, "meal_delivered", actor=d.agent, subject=d.business,
                                  location=a.location, item=d.item)
            elif d.kind == "state_pickup":
                biz = w.businesses.get(d.business)
                total = round(d.unit_price * d.qty, 2)
                if biz is not None and not biz.closed:
                    A._income(w, biz, total)
                    w.government.treasury -= total
                    buyer = next((b.id for b in w.businesses.values()
                                  if b.is_government and not b.closed), "Government")
                    A._record_trade(w, self.log, Transaction(w.sim_time, d.item, d.qty, d.unit_price,
                                                             biz.id, buyer, city=M.city_of(biz.location)),
                                    "sell", biz.location)
                    self.log.emit(w.sim_time, "state_collected", actor=d.agent, subject=biz.id,
                                  location=biz.location, item=d.item, qty=d.qty, paid=total,
                                  significance=Significance.MEDIUM)
        done = [k for k, d in w.dispatches.items()
                if d.status == "done" and d.arrives_at < w.sim_time - 6 * 3600.0]
        for k in done:
            del w.dispatches[k]

    def _debt_interest(self, hours: float) -> None:
        """What people owe the state for settling grows each game day."""
        from .claims import LOAN_RATE_PER_DAY
        grow = (1.0 + LOAN_RATE_PER_DAY) ** (hours / 24.0)
        for a in self.world.agents.values():
            if a.debt > 0:
                a.debt = round(a.debt * grow, 4)

    def _withdraw_the_state(self, city: str | None = None) -> None:
        """Delete every government business and spill its stores onto the ground.

        DELETED, not merely closed. A closed business is still an object in
        `world.businesses`, and on 2026-08-30 that turned out to be the smaller
        half of the problem: the observation stopped listing them, but the
        cached prompt prefix went on promising a state tavern and a buyer of
        last resort for the remaining thirty-six hours. An agent walked to the
        government tavern at h43.7 -- nearly eight hours after it shut -- because
        the briefing said Town "guarantees access" to one. Removing the object
        makes the absence checkable from one place, `state_withdrawn_at`, which
        the briefing, the tool schemas and the refusals all now read.

        Stock would otherwise be entombed -- a vanished business's inventory is
        unreachable -- so it is dropped where any agent can `loot_ground` it.

        Announced at HIGH significance, and once per building, because the
        replay draws a building from its founding hour to its closing hour and
        the state's branches were never founded: without a close event apiece,
        nine government buildings stayed on the map for the whole run and the
        withdrawal was invisible in the footage.
        """
        w = self.world
        closed = fired = 0
        # ONE CITY OR ALL. With a city named, only its branches go; the other
        # valley's government is untouched and never hears of it.
        def here(location: str) -> bool:
            return city is None or M.city_of(location) == city
        doomed = [b for b in w.businesses.values()
                  if b.is_government and not b.closed and here(b.location)]
        for biz in doomed:
            for emp in list(biz.roster):
                worker = w.agents.get(emp.agent_id)
                if worker and worker.current_job and worker.current_job[0] == biz.id:
                    worker.current_job = None
                    if worker.activity.kind == "work":
                        worker.activity = Activity("idle", w.sim_time)
                    fired += 1
            biz.roster.clear()
            stock = {i: q for i, q in biz.inventory.items() if q > 0}
            if stock:
                w.drop_loot(biz.location, stock, 0.0)
            biz.inventory.clear()
            biz.cash = 0.0
            biz.closed = True
            closed += 1
            # Per building, carrying what the renderer needs to reconstruct it:
            # after deletion these are absent from the checkpoint, so the event
            # log is the only remaining record that they ever stood.
            self.log.emit(
                w.sim_time, "business_closed", subject=biz.id, location=biz.location,
                business_type=biz.type, name=biz.name, reason="state_withdrew",
                significance=Significance.MEDIUM,
            )

        gone = {b.id for b in doomed}
        for bid in gone:
            del w.businesses[bid]

        # Nothing should still point at a building that is not there. Deliveries
        # already guard for it (`deliver_consignment` looks businesses up with
        # .get and tolerates None), but a job advert does not -- it would be
        # listed to every jobseeker in Town for a shop that no longer exists.
        for jid, posting in list(w.job_postings.items()):
            if posting.business_id in gone:
                del w.job_postings[jid]
        for agent in w.agents.values():
            if agent.current_job and agent.current_job[0] in gone:
                agent.current_job = None
                if agent.activity.kind == "work":
                    agent.activity = Activity("idle", w.sim_time)

        # THE GROUND GOES BACK ON THE MARKET. Closing a business does not
        # release its plots, so the state's holdings stayed locked under an
        # owner that no longer existed: on 2026-08-21, twenty of Town's forty
        # plots. A starving agent with 1,380 denari was told "every one of 40
        # plots is owned" and had nowhere to build a tavern, while half the
        # square belonged to shuttered government stores.
        #
        # Released as RAW land, not developed. The buildings went with the
        # state; what remains is ground, at the ordinary price. Handing over
        # finished floor space would be a windfall, and this is meant to reopen
        # a market rather than hand somebody a free building.
        freed = 0
        for plot in w.plots.values():
            if not here(plot.location):
                continue
            biz = w.businesses.get(plot.business) if plot.business else None
            if plot.owner == "Government" or (biz is not None and biz.is_government):
                plot.owner = None
                plot.business = None
                plot.developed = False
                plot.for_sale_at = None
                freed += 1

        if city is None:
            w.state_withdrawn_at = w.sim_hour
        else:
            w.state_withdrawn_in[city] = w.sim_hour
        self.log.emit(
            w.sim_time, "state_withdrew", location=None,
            businesses_closed=closed, workers_released=fired,
            plots_released=freed, city=city or "all",
            note=(f"the government has left {M.CITIES[city].name} for good; "
                  f"it will not reopen" if city else
                  "the government has left the valley for good; it will not reopen"),
            significance=Significance.HIGH,
        )

    def _resolve_banditry(self, agent: Agent, origin: str, destination: str) -> None:
        """Roll for the road just travelled, and take the loss if it goes badly.

        Nothing here decides WHETHER there was risk -- `banditry.segment_risk`
        owns that, including the two rules that override it (nobody is robbed on
        foot, and nobody is ever perfectly safe). This only applies the outcome,
        so there is exactly one place in the codebase that knows the odds.
        """
        w = self.world
        if not self.config.banditry or not w.npc_bandits:
            return
        if agent.activity.detail.get("by_water"):
            return
        cargo_value, what = B.cargo_at_risk(w, agent)
        if cargo_value <= 0:
            return

        party = B.party_for(w, agent, cargo_value)
        risk = B.route_risk(origin, destination, party)
        if risk.probability <= 0.0 or self._rng.random() >= risk.probability:
            return
        fraction = self._rng.uniform(B.LOOT_FRACTION_MIN, B.LOOT_FRACTION_MAX)

        # Everything on the cart, not one kind of thing on it. A courier
        # hauling for somebody else while carrying its own stock loses a share
        # of both -- see `banditry.cargo_at_risk`.
        lost_value = 0.0
        # `_rob_consignment` still reports WHO bore the loss even though nothing
        # pays it out any more: the bearer is what a dashboard needs to say
        # whose shipment this was, and it is the hook a claim would use if
        # insurance is ever switched back on.
        bearer = None
        if agent.hauling and agent.hauling in w.consignments:
            value, bearer = self._rob_consignment(agent, fraction)
            lost_value += value
        lost_value += self._rob_inventory(agent, fraction)
        if lost_value <= 0:
            return

        self.log.emit(
            w.sim_time, "robbed", actor=agent.id, location=destination,
            origin=origin, destination=destination,
            segment=max(risk.per_segment, key=lambda s: s[1])[0] if risk.per_segment else "",
            risk=round(risk.probability, 3), fraction=round(fraction, 3),
            value_lost=round(lost_value, 2), escorts=len(agent.escorts),
            vehicle=party.vehicle, cargo=what, borne_by=bearer,
        )

    def _resolve_raids(self, agent: Agent, origin: str, destination: str) -> None:
        """Did anybody lie in wait on the road just travelled? See `raids`.

        One ambush per journey: the first road on the route with raiders on it,
        and the oldest raid there. Raiders never rob themselves or the convoy's
        own escorts, and a raid with a named target lets everyone else pass.
        """
        w = self.world
        if not w.raids:
            return
        # Not on the water, and not a newcomer still finding their feet.
        if agent.activity.detail.get("by_water") or agent.protected_until > w.sim_time:
            return
        cargo_value, what = B.cargo_at_risk(w, agent)
        if cargo_value <= 0:
            return                            # nothing worth taking
        try:
            _s, path = M.travel_path(origin, destination, w.cities)
        except M.NoRoadThere:
            return
        guards = {m.agent_id for m in agent.escorts}
        for seg in path:
            for raid in R.waiting_on(w, seg.name):
                if raid.target and raid.target != agent.id:
                    continue
                if agent.id in raid.members:
                    continue                  # a crew does not rob its own
                members = [m for m in R.live_members(w, raid)
                           if m != agent.id and m not in guards]
                if members:
                    self._raid(raid, members, agent, seg, cargo_value, what,
                               origin, destination)
                    return

    def _raid(self, raid, members: list[str], agent: Agent, seg, cargo_value: float,
              what: str, origin: str, destination: str) -> None:
        w, rng = self.world, self._rng
        party = B.party_for(w, agent, cargo_value)
        strength = R.raid_strength(w, members, seg)
        names = [w.agents[m].name for m in members]
        common = dict(raid=raid.id, segment=seg.name, raiders=names,
                      raid_strength=round(strength, 2),
                      convoy_strength=round(party.strength, 2),
                      vehicle=party.vehicle, escorts=len(agent.escorts))

        if rng.random() < R.p_spotted(seg, party):
            self.log.emit(w.sim_time, "raid_spotted", actor=agent.id,
                          location=destination, significance=Significance.MEDIUM, **common)
            return
        if rng.random() >= R.p_raiders_win(strength, party):
            # BEATEN OFF. Each raider may die; the survivors scatter.
            killed = [m for m in members if rng.random() < R.p_death(strength, party)]
            for m in killed:
                self._raid_death(w.agents[m], seg)
            for m in members:
                a = w.agents[m]
                if a.alive and a.activity.kind == "raid":
                    a.activity = Activity("idle", w.sim_time)
            raid.status = "over"
            self.log.emit(w.sim_time, "raid_repelled", actor=agent.id,
                          location=destination, significance=Significance.HIGH,
                          killed=[w.agents[m].name for m in killed], **common)
            return
        if rng.random() < B.p_escape(seg, party):
            self.log.emit(w.sim_time, "raid_outrun", actor=agent.id,
                          location=destination, significance=Significance.MEDIUM, **common)
            return

        # ROBBED. The goods go to the raiders, as stolen goods, as far as they
        # can carry them; the rest is left in the road for anyone to pick up.
        fraction = rng.uniform(B.LOOT_FRACTION_MIN, B.LOOT_FRACTION_MAX)
        taken: dict[str, int] = {}
        lost_value, bearer = 0.0, None
        if agent.hauling and agent.hauling in w.consignments:
            value, bearer = self._rob_consignment(agent, fraction, taken)
            lost_value += value
        lost_value += self._rob_inventory(agent, fraction, taken)
        if lost_value <= 0:
            return
        left = self._share_loot(members, taken)
        if left:
            w.drop_loot(seg.a, left, 0.0)
        raid.takings += lost_value
        self.log.emit(
            w.sim_time, "robbed", actor=agent.id, location=destination,
            origin=origin, destination=destination, segment=seg.name,
            risk=round(R.p_raiders_win(strength, party), 3),
            fraction=round(fraction, 3), value_lost=round(lost_value, 2),
            escorts=len(agent.escorts), vehicle=party.vehicle, cargo=what,
            borne_by=bearer, raiders=names, raid=raid.id, items=taken,
            significance=Significance.HIGH,
        )

    def _share_loot(self, members: list[str], taken: dict[str, int]) -> dict[str, int]:
        """Deal the take round the raiders as stolen goods, one unit at a time,
        to whoever still has room. Returns what nobody could carry."""
        w = self.world
        room = {m: max(0, w.agents[m].carry_capacity(w) - w.agents[m].carried_units())
                for m in members}
        left: dict[str, int] = {}
        i = 0
        for item, qty in taken.items():
            for _ in range(qty):
                placed = False
                for k in range(len(members)):
                    m = members[(i + k) % len(members)]
                    if room[m] > 0:
                        w.agents[m].add_stolen(item, 1)
                        room[m] -= 1
                        i = (i + k + 1) % len(members)
                        placed = True
                        break
                if not placed:
                    left[item] = left.get(item, 0) + 1
        return left

    def _raid_death(self, agent: Agent, seg) -> None:
        """Killed in a failed raid. You lose what was ON you -- cargo, stolen
        goods, the cart you rode, your weapons and armour -- dropped where you
        fell. Cash, businesses, land and your other vehicles are kept."""
        w = self.world
        items = dict(agent.inventory)
        for k, q in agent.stolen.items():
            items[k] = items.get(k, 0) + q
        agent.inventory.clear()
        agent.stolen.clear()
        lost_vehicle = None
        if agent.mounted_vehicle:
            lost_vehicle = agent.mounted_vehicle
            veh = w.vehicles.pop(lost_vehicle, None)
            if lost_vehicle in agent.owned_vehicles:
                agent.owned_vehicles.remove(lost_vehicle)
            agent.mounted_vehicle = None
            lost_vehicle = veh.type if veh else lost_vehicle
        weapon = agent.equipped_weapon
        armor = {k: v for k, v in agent.equipped_armor.items() if v}
        for v in armor.values():
            items[v] = items.get(v, 0) + 1
        if weapon and weapon in D.WEAPONS:
            items[weapon] = items.get(weapon, 0) + 1
        agent.equipped_weapon = ""
        agent.equipped_armor = {k: None for k in agent.equipped_armor}
        if items:
            w.drop_loot(seg.a, items, 0.0)
        agent.alive = False
        agent.health = 0.0
        agent.respawn_at = w.sim_time + D.RESPAWN_SECONDS
        agent.activity = Activity("dead", agent.respawn_at)
        self.log.emit(
            w.sim_time, "agent_died", actor=agent.id, location=seg.a,
            cause="killed in a raid", segment=seg.name, lost_items=items,
            lost_vehicle=lost_vehicle, significance=Significance.HIGH,
        )

    def _convoy_destination(self, agent: Agent) -> str:
        """Where this agent's convoy was headed; where it stands if it was not."""
        return agent.in_transit[1] if agent.in_transit else agent.location

    def _settle_escorts(
        self, agent: Agent, destination: str, from_estate: bool = False,
    ) -> None:
        """Pay off the convoy and disband it. Hired for one journey, and it is over.

        An agent escort is paid HERE and not at hiring, which is the whole
        difference between it and an NPC: the NPC takes its premium up front and
        the person carries the risk of the journey with you. If the employer
        cannot pay on arrival, the escort takes what there is -- an unpaid guard
        is a story, an escort trapped forever in a convoy is a bug.
        """
        w = self.world
        for member in agent.escorts:
            escort = w.agents.get(member.agent_id)
            if escort is None:
                continue                      # an NPC: nothing to release or pay
            paid = min(member.wage_paid, agent.denari)
            agent.denari -= paid
            # The treasury covers what a dead employer's estate cannot. See the
            # note in `_kill`: the escort did the work either way.
            if from_estate and paid < member.wage_paid:
                covered = member.wage_paid - paid
                w.government.treasury -= covered
                paid += covered
            escort.denari += paid
            escort.location = destination
            escort.in_transit = None
            escort.escorting = None
            escort.activity = Activity("idle", w.sim_time)
            if member.vehicle_id and member.vehicle_id in w.vehicles:
                w.vehicles[member.vehicle_id].location = destination
            self.log.emit(
                w.sim_time, "escort_paid", actor=agent.id, subject=escort.id,
                location=destination, role=member.role, amount=round(paid, 2),
                shortfall=round(member.wage_paid - paid, 2),
            )
        # Lent weapons go home with the job, like a lent vehicle.
        for post in w.escort_postings.values():
            if post.owner == agent.id and post.status == "taken":
                post.status = "done"
                if post.lent_weapon:
                    agent.inventory[post.lent_weapon] = (
                        agent.inventory.get(post.lent_weapon, 0) + 1
                    )
        agent.escorts.clear()

    def _rob_inventory(self, agent: Agent, fraction: float,
                       taken_out: dict[str, int] | None = None) -> float:
        """Take a share of what the agent owns, counted across the whole load.

        A SHARE OF THE LOAD, NOT A SHARE OF EACH STACK. Rounding per item took
        a whole one-unit stack whatever the roll said -- a lone Iron Sword was a
        total loss on the gentlest possible robbery, while the briefing promised
        "you lose part of the load, not all of it". The observation asserting
        something the code then contradicts is the failure this project keeps
        finding (PHASE4 §2), so the guarantee is now structural: with more than
        one unit aboard, `_share_of` never takes the last one.
        """
        total = sum(q for q in agent.inventory.values() if q > 0)
        if total <= 0:
            return 0.0
        taking = _share_of(total, fraction)
        lost_value = 0.0
        # Largest stacks first, so the split is proportional rather than
        # whatever order a dict happens to be in.
        order = sorted(agent.inventory.items(), key=lambda kv: -kv[1])
        for i, (item, qty) in enumerate(order):
            if taking <= 0:
                break
            remaining_stacks = sum(q for _n, q in order[i:])
            take = min(qty, taking if i == len(order) - 1
                       else round(taking * qty / max(1, remaining_stacks)))
            take = max(0, min(take, qty, taking))
            if not take:
                continue
            agent.inventory[item] = qty - take
            if agent.inventory[item] <= 0:
                del agent.inventory[item]
            taking -= take
            lost_value += D.base_price(item) * take
            if taken_out is not None:
                taken_out[item] = taken_out.get(item, 0) + take
        return lost_value

    def _rob_consignment(self, agent: Agent, fraction: float,
                         taken_out: dict[str, int] | None = None) -> float:
        """Take a share of a load being hauled for somebody else.

        The goods belong to the buyer, who has already paid for them -- so
        unless the seller took responsibility for the convoy, this is simply the
        buyer's loss, which is what `Consignment` has always said. When the
        SELLER is responsible, they refund what did not arrive: that is the
        whole substance of the bargain, and it has to move money or it is not a
        bargain at all.
        """
        w = self.world
        con = w.consignments[agent.hauling]
        taken = _share_of(con.qty, fraction)
        con.qty -= taken
        if taken_out is not None and taken:
            taken_out[con.item] = taken_out.get(con.item, 0) + taken
        agent.hauling_units = max(0, agent.hauling_units - taken)
        unit = con.goods_price / max(1, con.qty + taken)
        refund = unit * taken

        # THE LOSS SPLITS THE SAME WAY THE COST DOES. The goods are the buyer's
        # -- they paid at order time -- so the seller compensates them for
        # whatever share of the convoy the seller agreed to carry.
        seller = w.businesses.get(con.seller_business)
        buyer = w.businesses.get(con.buyer_business)
        owed = refund * con.seller_share
        if seller and buyer and owed > 0 and not seller.is_government:
            paid = self._draw(seller, owed, partial=True)
            A._income(w, buyer, paid)
            self.log.emit(
                w.sim_time, "convoy_loss_covered", actor=con.seller_business,
                subject=con.buyer_business, location=agent.location,
                amount=round(paid, 2), consignment=con.id,
                split=con.split_label(), shortfall=round(owed - paid, 2),
            )
        # Whoever carries the larger share is the one the loss really falls on.
        losing = (con.seller_business if con.seller_share >= 0.5
                  else con.buyer_business)
        owner = getattr(w.businesses.get(losing), "owner", None)
        return D.base_price(con.item) * taken, owner

    def _advance_travel(self, dt: float) -> None:
        for agent in self.world.agents.values():
            if agent.activity.kind != "travel" or not agent.in_transit:
                continue
            origin, dest, _p = agent.in_transit
            total = max(agent.activity.ends_at - self.world.sim_time, 0.0)
            remaining_frac = total / max(
                E.travel_seconds(origin, dest, self._vehicle_type(agent)), 1e-9
            )
            agent.in_transit = (origin, dest, max(0.0, min(1.0, 1.0 - remaining_frac)))

    def _sustenance(self, hours: float) -> None:
        """Hunger accrual and the Normal -> Hungry -> Starving -> Death escalation."""
        w = self.world
        for agent in w.agents.values():
            if not agent.alive:
                continue
            agent.hours_since_last_meal += hours
            previous = agent.sustenance_stage
            stage = E.sustenance_stage(agent.hours_since_last_meal, agent.last_meal_window)
            if stage == previous:
                continue
            agent.sustenance_stage = stage
            if stage != "Normal":
                agent.meal_work_bonus = 0.0   # the meal's effect ends with its window

            if stage == "Hungry":
                self.log.emit(
                    w.sim_time, "sustenance_hungry", actor=agent.id, location=agent.location,
                    hours_since_meal=round(agent.hours_since_last_meal, 1),
                    penalty=D.HUNGRY_SPEED_PENALTY,
                )
            elif stage == "Starving":
                # -5 HP once, on entering the stage.
                agent.health = max(0.0, agent.health - D.STARVING_HP_HIT)
                self.log.emit(
                    w.sim_time, "sustenance_starving", actor=agent.id, location=agent.location,
                    hours_since_meal=round(agent.hours_since_last_meal, 1),
                    health=agent.health, penalty=D.STARVING_SPEED_PENALTY,
                )
            elif stage == "Death":
                self._kill(agent, cause="starvation")

    def _kill(self, agent: Agent, cause: str) -> None:
        """Death rules (designer decision, 2026-08-11), superseding the tab's
        24-hour claimable-asset rule:

          * Whatever the agent was CARRYING (inventory + Denari) drops at the
            death location and anyone can walk up and take it.
          * Everything NOT on them -- businesses, vehicles, property -- is
            retained if they held Asset Insurance, and destroyed outright if
            they did not.
        """
        w = self.world
        # Hot goods drop with everything else -- and stay hot for whoever takes them.
        dropped_items = dict(agent.inventory)
        for item, qty in agent.stolen.items():
            dropped_items[item] = dropped_items.get(item, 0) + qty
        dropped_denari = agent.denari
        w.drop_loot(agent.location, dropped_items, dropped_denari)
        agent.inventory.clear()
        agent.stolen.clear()
        agent.denari = 0.0

        # A DYNASTY GOES ON (2026-10-18). With a grown member in the house, the
        # heir takes over where the dead left off: what was carried is lost,
        # everything owned stays in the family. See convoy/family.py.
        heir = FAM.succession(w, agent)
        if heir is not None:
            self._settle_escorts(agent, self._convoy_destination(agent), from_estate=True)
            agent.health = 100.0
            agent.hours_since_last_meal = 0.0
            agent.in_transit = None
            agent.activity = Activity("idle", w.sim_time)
            if agent.current_job:
                biz = w.businesses.get(agent.current_job[0])
                if biz:
                    biz.roster = [e for e in biz.roster if e.agent_id != agent.id]
                agent.current_job = None
            self.log.emit(
                w.sim_time, "succession", actor=agent.id, location=agent.location,
                significance=Significance.HIGH, cause=cause, heir=heir.name,
                house=agent.house, dropped_units=sum(dropped_items.values()),
                dropped_denari=round(dropped_denari, 2),
            )
            return

        payout = 0.0
        if agent.insurance.get("Life", 0.0) > 0:
            payout = E.insurance_payout(agent.insurance["Life"])
            agent.denari += payout
            broker = w.government_business("Insurance Brokerage")
            if broker and not broker.is_government:
                # Floors at zero like payroll: a player-owned broker cannot be
                # driven into debt by a claim it cannot cover.
                broker.cash = max(0.0, broker.cash - payout)
            self.log.emit(
                w.sim_time, "insurance_claim_paid", actor=agent.id,
                product="Life", amount=round(payout, 2),
            )

        # Off-person assets: protected by Asset Insurance, otherwise wiped.
        if agent.insurance.get("Asset", 0.0) <= 0:
            wiped = self._wipe_assets(agent)
            if wiped:
                self.log.emit(
                    w.sim_time, "assets_wiped", actor=agent.id,
                    businesses=wiped["businesses"], vehicles=wiped["vehicles"],
                    property=wiped["property"], value=round(wiped["value"], 2),
                )

        # A DEAD EMPLOYER MUST NOT STRAND ITS CONVOY (designer decision,
        # 2026-08-21). Escorts leave with their employer and are released on ITS
        # arrival -- and a corpse never arrives, so without this they sit in
        # transit with `activity == "convoy"` forever, unpaid and unable to act.
        #
        # The rule: the convoy completes. Escorts finish the journey, and are
        # paid out of the estate first and the treasury after, because a guard
        # who did the job is owed regardless of what happened to whoever hired
        # it. The state is the backstop of last resort here for the same reason
        # it is the buyer of last resort everywhere else.
        self._settle_escorts(agent, self._convoy_destination(agent), from_estate=True)
        agent.alive = False
        agent.health = 0.0
        agent.respawn_at = w.sim_time + D.RESPAWN_SECONDS
        agent.activity = Activity("dead", agent.respawn_at)
        if agent.current_job:
            biz = w.businesses.get(agent.current_job[0])
            if biz:
                biz.roster = [e for e in biz.roster if e.agent_id != agent.id]
            agent.current_job = None

        self.log.emit(
            w.sim_time,
            "starved_to_death" if cause == "starvation" else "agent_died",
            actor=agent.id, location=agent.location, cause=cause,
            dropped_units=sum(dropped_items.values()),
            dropped_denari=round(dropped_denari, 2), life_payout=round(payout, 2),
        )

    def _wipe_assets(self, agent: Agent) -> dict | None:
        """Destroy uninsured off-person assets outright."""
        w = self.world
        value = 0.0
        businesses = list(agent.owned_businesses)
        vehicles = list(agent.owned_vehicles)
        prop = agent.owned_property
        if not (businesses or vehicles or prop):
            return None

        for bid in businesses:
            biz = w.businesses.get(bid)
            if biz and not biz.closed:
                value += D.BUSINESS_TYPES[biz.type].startup_cost
                for emp in list(biz.roster):
                    worker = w.agents.get(emp.agent_id)
                    if worker and worker.current_job and worker.current_job[0] == biz.id:
                        worker.current_job = None
                        if worker.activity.kind == "work":
                            worker.activity = Activity("idle", w.sim_time)
                biz.roster.clear()
                biz.inventory.clear()
                biz.cash = 0.0
                biz.closed = True
        agent.owned_businesses.clear()

        for vid in vehicles:
            veh = w.vehicles.get(vid)
            if veh:
                value += D.VEHICLES[veh.type].base_price
                veh.condition = "destroyed"
                veh.owner = ""
        agent.owned_vehicles.clear()
        agent.mounted_vehicle = None

        if prop and prop in w.properties:
            value += w.properties[prop].assessed_value()
            del w.properties[prop]
        agent.owned_property = None

        return {
            "businesses": len(businesses), "vehicles": len(vehicles),
            "property": 1 if prop else 0, "value": value,
        }

    def _vehicle_type(self, agent: Agent) -> str | None:
        if agent.mounted_vehicle:
            return self.world.vehicles[agent.mounted_vehicle].type
        return None

    def _finish_developments(self) -> None:
        """Hand over plots whose build time is up.

        Development is deliberately a WAIT rather than a purchase, so that an
        owner choosing the cheap route has committed hours they cannot get back
        and the instant route is worth its premium. The engine is what makes
        that real: nothing else advances a build.
        """
        w = self.world
        for plot in w.plots.values():
            if plot.developing_until is None or w.sim_time < plot.developing_until:
                continue
            plot.developed = True
            plot.business = plot.developing_for
            plot.developing_until = None
            plot.developing_for = None
            biz = w.businesses.get(plot.business or "")
            self.log.emit(
                w.sim_time, "plot_developed", subject=plot.business,
                location=plot.location, significance=Significance.MEDIUM,
                plot=plot.id, instant=False,
                employee_slots=E.employee_slots(w, biz) if biz else 0,
            )

    def production_rate(
        self, biz: "Business", *, credit_skill_hours: float = 0.0
    ) -> float:
        """Units per simulated hour this business is currently making.

        PULLED OUT OF `_produce` SO A COUNTDOWN CANNOT LIE. `production_buffer`
        fills at this rate and pops a whole unit at 1.0, so "time until the next
        unit" is `(1 - buffer) / rate` -- but only if the viewer's rate is the
        SAME rate the engine is about to apply. Recomputing it alongside would
        work until somebody changed one of them, and then the bar would count
        down to a moment at which nothing happens, with nothing erroring. One
        function, two callers.

        `credit_skill_hours` is the practice a worker earns for the hours it just
        put in, and is 0 for anyone merely asking. A viewer polling four times a
        second must not be able to train the whole valley to mastery.
        """
        w = self.world
        output = biz.active_production
        if not output or biz.closed:
            return 0.0
        headcount = biz.active_headcount(w)
        if headcount == 0:
            return 0.0

        # Efficiency comes from the ALLOCATED tier, not from raw RP -- RP has
        # to be spent on a track before it speeds anything up.
        eff = E.efficiency_bonus(biz.research.efficiency_tier)
        base_rate = self._base_rate_for(output)

        if biz.is_government:
            # Always fully staffed by exemption; a stable one-worker market floor.
            return base_rate

        rate = 0.0
        for emp in biz.production_staff():
            if emp.is_npc:
                # NPC hires work at Novice skill, always on shift -- and slower
                # than a person; family members of the house do not.
                slow = 1.0 if emp.agent_id.startswith("family:") else D.NPC_WORK_RATE
                rate += E.worker_output_rate(base_rate, headcount, 0.0, eff) * slow
                continue
            agent = w.agents.get(emp.agent_id)
            if not (agent and agent.alive and agent.activity.kind == "work"
                    and agent.activity.detail.get("business") == biz.id):
                continue
            # Upgraded Tools speed up raw extraction only -- mining and
            # farming, per the Equipment Store's name.
            tools = (
                D.TOOL_EXTRACTION_BONUS
                if agent.equipped_tools and biz.type in D.EXTRACTION_BUSINESS_TYPES
                else 0.0
            )
            # Hungry/Starving cut production speed; a Laborer's Bread
            # adds a bonus for the meal's duration (Sustenance tab).
            rate += E.worker_output_rate(
                base_rate, headcount,
                agent.skill_hours.get(emp.role, 0.0), eff + tools,
            ) * E.sustenance_speed_multiplier(agent.sustenance_stage) \
                * (1.0 + agent.meal_work_bonus)
            if credit_skill_hours:
                agent.skill_hours[emp.role] = (
                    agent.skill_hours.get(emp.role, 0.0) + credit_skill_hours
                )
        # The owner's calling: a Farmer's farms, a Miner's mines... See data.CALLINGS.
        owner = self.world.agents.get(biz.owner)
        if owner is not None and D.calling_speeds(owner.calling, biz.type):
            rate *= 1.0 + D.CALLING_BONUS
        # Know-how and finished projects (convoy/progress.py).
        rate *= PG.production_bonus(self.world, biz, owner)
        # The ground: rich land makes one good faster. See `convoy/land.py`.
        # Worn ground and foul air slow it. See `convoy/ground.py`.
        return rate * LAND.multiplier(biz, output) * GR.multiplier(w, biz)

    def production_headroom(self, biz: "Business") -> tuple[float, str]:
        """How many more units this business could make before something stops it.

        The other half of an honest countdown, and the half a viewer cannot
        safely reimplement. The exemptions are not symmetrical: a state business
        sources its own inputs, so the FEEDSTOCK test skips it -- but it is not
        exempt from its yard, and reading "government" as "unconstrained" had the
        forecast promising 36 units an hour out of a mine the engine had already
        stalled for lack of anywhere to put them.

        Returns (units, why) with `inf` when nothing binds. `why` names the
        binding constraint in words, because "blocked" and "slow" look identical
        on a progress bar and need completely different things done about them.
        """
        w = self.world
        output = biz.active_production
        if not output or biz.closed:
            return 0.0, "nothing set to produce"

        caps: list[tuple[float, str]] = []
        if GR.spent(biz):
            caps.append((0.0, "the seam is worked out -- sink a Deeper shaft or dig somewhere else"))
        recipe = D.REFINING_RECIPES.get(output) or D.CRAFTING_RECIPES.get(output)
        if recipe and not biz.is_government:
            short = [i for i, q in recipe.inputs.items() if biz.inventory.get(i, 0) < q]
            caps.append((
                min((biz.inventory.get(i, 0) // q for i, q in recipe.inputs.items()),
                    default=0),
                "out of " + ", ".join(short) if short
                else "feedstock runs out (" + ", ".join(recipe.inputs) + ")",
            ))
        # EVERY business has a finite storehouse now. This used to be gated on
        # `biz.plots`, which only mines and farms ever had -- so refineries,
        # taverns and every store in the world stockpiled without limit.
        room = E.business_storage_capacity(w, biz) - sum(biz.inventory.values())
        caps.append((
            max(room, 0),
            "the yard is full -- nothing can be made until stock is moved out",
        ))
        return min(caps, default=(float("inf"), ""))

    def worker_shares(self, biz: "Business") -> list[dict]:
        """Each worker's share of the output, for an owner watching a crew.

        Output is POOLED. A business fills one buffer and pops whole units from
        it; individual workers do not each finish their own unit and carry it in,
        so "when will this miner deliver" has no answer -- what does is "this
        miner is a third of why the next one arrives when it does."

        Saying that plainly beats inventing a per-worker timer the engine would
        not honour. It is also the number an owner actually wants: it prices the
        crew.
        """
        total = self.production_rate(biz)
        out = []
        for emp in biz.production_staff():
            solo = self._solo_rate(biz, emp)
            out.append({
                "agent": emp.agent_id, "role": emp.role,
                "is_npc": emp.is_npc,
                "units_per_hour": round(solo, 3),
                "share": round(solo / total, 3) if total else 0.0,
                "wage": round(emp.wage, 2),
            })
        return out

    def _solo_rate(self, biz: "Business", emp) -> float:
        """One employee's contribution, on the same terms `production_rate` uses."""
        w = self.world
        output = biz.active_production
        if not output:
            return 0.0
        headcount = biz.active_headcount(w)
        if headcount == 0:
            return 0.0
        eff = E.efficiency_bonus(biz.research.efficiency_tier)
        base_rate = self._base_rate_for(output)
        if biz.is_government:
            # A state business produces `base_rate` flat, by exemption, however
            # many people stand in it -- so per-worker attribution is a fiction
            # and the only honest split is an equal one. Running the normal
            # per-worker maths here instead had two refinery workers credited
            # with 90% of the output EACH, which sums to 180% of a number the
            # engine holds fixed.
            staff = list(biz.production_staff())
            return base_rate / len(staff) if staff else 0.0
        if emp.is_npc:
            slow = 1.0 if emp.agent_id.startswith("family:") else D.NPC_WORK_RATE
            return E.worker_output_rate(base_rate, headcount, 0.0, eff) * slow
        agent = w.agents.get(emp.agent_id)
        if not (agent and agent.alive and agent.activity.kind == "work"
                and agent.activity.detail.get("business") == biz.id):
            return 0.0
        tools = (
            D.TOOL_EXTRACTION_BONUS
            if agent.equipped_tools and biz.type in D.EXTRACTION_BUSINESS_TYPES
            else 0.0
        )
        return E.worker_output_rate(
            base_rate, headcount, agent.skill_hours.get(emp.role, 0.0), eff + tools,
        ) * E.sustenance_speed_multiplier(agent.sustenance_stage) \
            * (1.0 + agent.meal_work_bonus)

    def _produce(self, hours: float) -> None:
        """Extraction, refining and crafting, at the Businesses tab decay rate."""
        w = self.world
        for biz in w.businesses.values():
            if biz.closed or not biz.active_production:
                # Nothing set to make is not "blocked" -- there is no attempt to
                # block. _pay_wages tests active_production separately, so clear
                # the flag rather than leave a stale one from an earlier tick.
                biz.production_blocked = False
                continue
            output = biz.active_production
            headcount = biz.active_headcount(w)
            biz.peak_headcount = max(biz.peak_headcount, headcount)
            if headcount == 0:
                continue    # zero workers == zero output, per the Businesses tab

            rate = self.production_rate(biz, credit_skill_hours=hours)

            recipe = D.REFINING_RECIPES.get(output) or D.CRAFTING_RECIPES.get(output)

            # Decide up front whether this business CAN make anything right now,
            # from its current stock and yard alone. This has to happen before
            # the buffer, not after: a unit only pops out once the buffer passes
            # 1.0, so testing blockage at that point leaves a window -- the whole
            # time the buffer is filling -- in which a business with no feedstock
            # at all still looks productive. NPC pay keys off this flag, and that
            # window was billing idle NPCs (caught by test_business_solvency).
            headroom, why = self.production_headroom(biz)
            blocked = headroom < 1
            if blocked and why and "yard" in why:
                self.log.emit(
                    w.sim_time, "site_full", subject=biz.id,
                    location=biz.location, business=biz.name,
                    capacity=E.business_storage_capacity(w, biz),
                )
            biz.production_blocked = blocked
            if blocked:
                biz.production_buffer = min(biz.production_buffer, 1.0)
                continue

            biz.production_buffer += rate * hours
            units = int(biz.production_buffer)
            if units <= 0:
                continue

            if recipe and not biz.is_government:
                # Raw materials are auto-shipped to factories (designer decision,
                # 2026-08-11) -- no hauling leg for production inputs yet. The
                # business buys what it lacks at BASE price from its own cash,
                # which is exactly the basis the Production Chain tab's Input Cost
                # column uses, so the designed margins hold.
                units = self._source_inputs(biz, recipe, units)
                if units <= 0:
                    # Stock covers fewer than the units the buffer earned; the
                    # blocked check above already cleared the full-shortage case.
                    biz.production_buffer = min(biz.production_buffer, 1.0)
                    biz.production_blocked = True
                    continue
                for i, q in recipe.inputs.items():
                    biz.remove_item(i, q * units)

            # A worked site can only stockpile so much. When the yard is full,
            # production stalls until someone hauls it away -- which is what
            # makes carts, expansion, and distance-to-market matter. The full
            # case is handled above; this only trims a batch to the room left.
            if biz.plots:
                units = min(
                    units,
                    E.business_storage_capacity(w, biz) - sum(biz.inventory.values()),
                )
                if units <= 0:
                    biz.production_buffer = min(biz.production_buffer, 1.0)
                    biz.production_blocked = True
                    continue

            biz.production_buffer -= units
            biz.production_blocked = False
            biz.add_item(output, units)
            GR.worked(w, self.log, biz, output, units)
            # THE FIRST HARVEST SHOWS WHAT THE GROUND IS. See `convoy/land.py`.
            if biz.land_rolled and not biz.land_revealed:
                biz.land_revealed = True
                self.log.emit(
                    w.sim_time, "land_revealed", actor=biz.owner, subject=biz.id,
                    location=biz.location, item=biz.land_bonus_item,
                    pct=biz.land_bonus_pct, significance=Significance.MEDIUM,
                )
            self.log.emit(
                w.sim_time, "production", subject=biz.id, location=biz.location,
                item=output, qty=units, workers=headcount,
            )

    def _source_inputs(self, biz: Business, recipe: D.Recipe, wanted: int) -> int:
        """How many units this business can actually make.

        A PLAYER business makes only what its own stock allows. Feedstock has to
        arrive by trade -- ordered from another business and hauled there -- so
        auto-buying it here would make the whole supply chain optional: a
        refinery with cash would never need a mine, and no courier would ever
        have work. That shortcut was fine while there was no hauling leg to use;
        there is one now (designer decision, 2026-08-15).

        GOVERNMENT businesses keep the old behaviour on purpose. They are the
        market's floor and ceiling and must never stall, so the state's refinery
        is abstracted as infinitely supplied.
        """
        on_hand = min(biz.inventory.get(i, 0) // q for i, q in recipe.inputs.items())
        if on_hand >= wanted:
            return wanted
        if not biz.is_government:
            return on_hand

        unit_cost = sum(D.base_price(i) * q for i, q in recipe.inputs.items())
        shortfall = wanted - on_hand
        affordable = int(biz.cash // unit_cost) if unit_cost > 0 else shortfall
        buy = max(0, min(shortfall, affordable))
        if buy:
            biz.cash -= buy * unit_cost
            for i, q in recipe.inputs.items():
                biz.add_item(i, q * buy)
            self.log.emit(
                self.world.sim_time, "inputs_sourced", subject=biz.id,
                location=biz.location, output=recipe.output, batches=buy,
                cost=round(buy * unit_cost, 2),
            )
        return on_hand + buy

    def _base_rate_for(self, output: str) -> float:
        # One rule for everything that is MADE: time per unit scales with value.
        # Extraction keeps the spreadsheet's own rates -- see production_rate_hr.
        return D.production_rate_hr(output)

    def _pay_wages(self, hours: float) -> None:
        """Payroll, with two rules added on 2026-08-16.

        NPC hires are paid only for hours the business can actually produce.
        They used to bill around the clock regardless: three NPC refinery
        workers standing in a refinery with no ore cost their owner 2,124
        denari in 11 simulated hours, which is most of how that agent finished
        the run 2,670 underwater while ranked first. An NPC is a machine, so
        charging for an idle one is charging for nothing. AGENT employees are
        NOT gated this way -- a player employee turns up, and whether feedstock
        arrived is the owner's problem, not theirs. Gating their pay too would
        make a player job strictly riskier than a state job, since government
        businesses source their own inputs and therefore always produce, and
        the labour would all go to the state.

        A business cannot pay what it does not have. Cash floors at zero and
        the unpaid worker leaves; missing payroll starts the insolvency clock.
        Before this, `cash -= gross` ran unguarded and a business could carry
        unbounded debt while its owner drew a wage out of it.
        """
        w = self.world
        gov = w.government
        for biz in w.businesses.values():
            if biz.closed:
                continue
            producing = bool(biz.active_production) and not biz.production_blocked
            missed = False
            payroll_before = self._hourly_payroll(biz)   # captured before anyone walks
            for emp in list(biz.roster):
                if emp.is_npc:
                    if not producing:
                        continue    # idle machine, no charge
                    gross = emp.wage * hours
                    if gross <= 0:
                        continue    # family works unpaid: nothing to draw, never "unpaid"
                    if not biz.is_government and not self._draw(biz, gross):
                        self._release_unpaid(biz, emp)
                        missed = True
                        continue
                    _net, tax = E.apply_wage_tax(gross, gov.wage_tax)
                    gov.collect(tax)
                    continue
                agent = w.agents.get(emp.agent_id)
                if not (agent and agent.alive and agent.activity.kind == "work"
                        and agent.activity.detail.get("business") == biz.id):
                    continue
                if emp.wage <= 0:
                    continue    # owner self-staffing draws no wage
                gross = emp.wage * hours
                if not biz.is_government:
                    if not self._draw(biz, gross):
                        self._release_unpaid(biz, emp)
                        missed = True
                        continue
                net, tax = E.apply_wage_tax(gross, gov.wage_tax)
                agent.denari += net
                gov.collect(tax)
            if missed and biz.insolvent_since is None:
                biz.insolvent_since = w.sim_time
                biz.insolvent_debt = payroll_before
                self.log.emit(
                    w.sim_time, "bankruptcy_warning", actor=biz.owner, subject=biz.id,
                    business=biz.name, cash=round(biz.cash, 2),
                    owed=round(payroll_before, 2),
                    grace_hours=D.BANKRUPTCY_GRACE_HOURS, reason="payroll unmet",
                )

    def _draw(self, biz: Business, amount: float, partial: bool = False) -> float:
        """Take `amount` for a business: its own cash first, then its owner's
        pocket (2026-10-18 -- an owner's money is theirs, not the business's).
        All or nothing, returning it (or 0.0); `partial` takes what there is."""
        owner = self.world.agents.get(biz.owner)
        pocket = owner.denari if owner is not None and owner.alive else 0.0
        have = max(0.0, biz.cash) + max(0.0, pocket)
        if have + 1e-9 < amount and not partial:
            return 0.0
        take = min(amount, have)
        from_biz = min(max(0.0, biz.cash), take)
        biz.cash -= from_biz
        if owner is not None and take > from_biz:
            owner.denari -= take - from_biz
        return take

    def _release_unpaid(self, biz: Business, emp) -> None:
        """An unpaid worker walks. This is the brake on a payroll death spiral:
        the roster shrinks the moment it cannot be met, so an NPC that cannot be
        paid also stops costing money instead of compounding."""
        w = self.world
        if emp in biz.roster:
            biz.roster.remove(emp)
        worker = w.agents.get(emp.agent_id) if not emp.is_npc else None
        if worker and worker.current_job and worker.current_job[0] == biz.id:
            worker.current_job = None
            if worker.activity.kind == "work":
                worker.activity = Activity("idle", w.sim_time)
        self.log.emit(
            w.sim_time, "wages_unpaid", actor=biz.owner, subject=biz.id,
            business=biz.name, role=emp.role,
            worker="NPC" if emp.is_npc else emp.agent_id,
            cash=round(biz.cash, 2),
        )

    def _research(self, hours: float) -> None:
        w = self.world
        for biz in w.businesses.values():
            if biz.closed or biz.is_government:
                continue
            n = biz.active_researchers(w)
            if n == 0:
                continue
            rp = 0.0
            for emp in biz.researchers():
                agent = w.agents.get(emp.agent_id)
                if not (agent and agent.alive and agent.activity.kind == "work"
                        and agent.activity.detail.get("business") == biz.id):
                    continue
                rp += D.RP_PER_RESEARCHER_HOUR * (
                    1.0 + E.skill_bonus(agent.skill_hours.get("Researcher", 0.0))
                ) * E.per_worker_multiplier(n)
                agent.skill_hours["Researcher"] = agent.skill_hours.get("Researcher", 0.0) + hours

            before = E.research_tier_for_rp(biz.research.rp)
            biz.research.rp += rp * hours
            biz.research.unspent_rp += rp * hours    # spendable pool, see allocate_research
            after = E.research_tier_for_rp(biz.research.rp)
            if after and (before is None or after.tier > before.tier):
                self.log.emit(
                    w.sim_time, "research_tier_unlocked", subject=biz.id,
                    business=biz.name, tier=after.tier, tag=after.tag,
                )

            # Researchers burn test material on top of wages.
            mat = D.RESEARCH_MATERIAL.get(biz.type)
            if mat:
                item, rate = mat
                biz.research_buffer += rate * n * hours
                burn = int(biz.research_buffer)
                if burn > 0 and biz.inventory.get(item, 0) >= burn:
                    biz.remove_item(item, burn)
                    biz.research_buffer -= burn

    def _property_tax(self) -> None:
        w = self.world
        if w.sim_time < w.next_property_tax_at:
            return
        w.next_property_tax_at += D.PROPERTY_TAX_PERIOD_HOURS * 3600.0
        # The stored rate is already per-week; this clamps it to policy bounds.
        rate = D.property_tax_per_bill(w.government.property_tax)
        for prop in w.properties.values():
            owner = w.agents.get(prop.owner)
            if not owner:
                continue
            due = prop.assessed_value() * rate
            owner.denari -= due
            w.government.collect(due)
            self.log.emit(
                w.sim_time, "tax_collected", actor=owner.id, kind="property",
                amount=round(due, 2),
            )

    def _expire_social(self) -> None:
        """Time out stale trade offers and cap retained chat.

        Both are unbounded otherwise. Offers matter most: an agent's observation
        will include the offers open to it, so a pile of dead ones is a direct
        token cost every single decision.
        """
        w = self.world
        ttl = D.TRADE_OFFER_TTL_MINUTES * 60.0
        for offer in w.trade_offers.values():
            if offer.status == "open" and w.sim_time - offer.offered_at > ttl:
                offer.status = "expired"

        # Drop resolved offers entirely -- they live on in the event log.
        if len(w.trade_offers) > 200:
            w.trade_offers = {
                oid: o for oid, o in w.trade_offers.items() if o.status == "open"
            }

        # Prune PER CHANNEL, not globally. Direct messages vastly outnumber the
        # other two, so a single global cap silently evicts all world and guild
        # history -- which is exactly the context an agent most needs.
        if len(w.chat) > D.CHAT_HISTORY_LIMIT:
            kept: list = []
            for channel, cap in D.CHAT_RETENTION.items():
                msgs = [m for m in w.chat if m.channel == channel]
                kept.extend(msgs[-cap:])
            kept.sort(key=lambda m: m.sim_time)
            w.chat = kept

    def _road_tax(self) -> None:
        """The daily public-works levy that funds roads and police.

        Charged on Net Worth, so it falls on illiquid wealth as well as cash --
        an agent sitting on assets still contributes to the road they use. Cash
        is drawn down first; the remainder is written off rather than driving an
        agent negative, since there is no debt mechanic.
        """
        w = self.world
        if w.sim_time < w.next_road_tax_at:
            return
        w.next_road_tax_at += D.ROAD_TAX_PERIOD_HOURS * 3600.0

        rate = D.road_tax_per_bill(w.government.road_tax)
        if rate <= 0:
            return

        collected = 0.0
        for agent in w.agents.values():
            if not agent.alive:
                continue
            due = agent.net_worth(w) * rate
            paid = min(due, max(agent.denari, 0.0))
            if paid <= 0:
                continue
            agent.denari -= paid
            collected += paid

        w.government.collect(collected)
        self.log.emit(
            w.sim_time, "road_tax_collected", kind="road", rate=rate,
            amount=round(collected, 2), police_tier=w.government.police_tier,
            policies=list(w.government.active_policies),
        )

    def _expire_job_postings(self) -> None:
        """A wage nobody will take should not sit on the board all run."""
        w = self.world
        for p in w.job_postings.values():
            if p.status == "open" and w.sim_time >= p.expires_at:
                p.status = "expired"
                self.log.emit(
                    w.sim_time, "job_expired", actor=p.owner, subject=p.business_id,
                    posting=p.id, role=p.role, wage=p.wage,
                    applicants=len(p.applicants),
                )

    def _check_solvency(self) -> None:
        """Grace period after payroll is first missed, then the business closes.

        The trigger used to be `cash < 0`, which cannot happen now that wages
        floor at zero -- so insolvency is declared by _pay_wages instead, and
        this only runs the clock. The clock clears when the business holds one
        hour of the payroll it FAILED to meet, captured before the unpaid staff
        walked. Measuring against the current roster instead would let an owner
        clear the clock by losing everyone, since an empty roster costs nothing
        an hour.
        """
        w = self.world
        for biz in list(w.businesses.values()):
            if biz.closed or biz.is_government:
                continue
            if biz.insolvent_since is None:
                continue
            owner = w.agents.get(biz.owner)
            if biz.cash + (owner.denari if owner is not None and owner.alive else 0.0) >= biz.insolvent_debt:
                biz.insolvent_since = None
                biz.insolvent_debt = 0.0
            elif w.sim_time - biz.insolvent_since >= D.BANKRUPTCY_GRACE_HOURS * 3600.0:
                self._close_business(biz)

    def _hourly_payroll(self, biz: Business) -> float:
        """What one more hour of the current roster costs. Zero for an empty one."""
        return sum(e.wage for e in biz.roster if e.wage > 0)

    def _close_business(self, biz: Business) -> None:
        w = self.world
        # Liquidate inventory at the NPC buy rate; proceeds settle against the debt,
        # remainder to the owner. Employees are released.
        proceeds = sum(E.npc_buy_price(i) * q for i, q in biz.inventory.items())
        biz.inventory.clear()
        settled = biz.cash + proceeds
        owner = w.agents.get(biz.owner)
        if owner:
            if settled > 0:
                owner.denari += settled
            if biz.id in owner.owned_businesses:
                owner.owned_businesses.remove(biz.id)
        for emp in list(biz.roster):
            worker = w.agents.get(emp.agent_id)
            if worker and worker.current_job and worker.current_job[0] == biz.id:
                worker.current_job = None
                if worker.activity.kind == "work":
                    worker.activity = Activity("idle", w.sim_time)
        biz.roster.clear()
        biz.closed = True
        biz.cash = 0.0
        self.log.emit(
            w.sim_time, "business_bankrupt", actor=biz.owner, subject=biz.id,
            business=biz.name, business_type=biz.type, liquidated=round(proceeds, 2),
        )

    def _respawn(self) -> None:
        w = self.world
        for agent in w.agents.values():
            if agent.alive or agent.respawn_at is None:
                continue
            if w.sim_time >= agent.respawn_at:
                agent.alive = True
                agent.health = 100.0
                agent.respawn_at = None
                if D.RESPAWN_RESETS_HUNGER:
                    agent.hours_since_last_meal = 0.0
                    agent.last_meal_window = D.SELF_PREP_WINDOW_HOURS
                    agent.sustenance_stage = "Normal"
                if agent.owned_property:
                    agent.location = w.properties[agent.owned_property].location
                else:
                    # Your OWN city's market square. Respawning in Aldermarch's
                    # Town was fine while there was only one; it would now
                    # teleport a dead Cinderholder across a border that has no
                    # road, stranding them in a valley where nothing they own
                    # exists and every travel_to home would be refused.
                    agent.location = M.market_of(w.city_of(agent))
                agent.activity = Activity("idle", w.sim_time)

    def _publish_digest(self) -> None:
        """The periodic "what's working" summary. See `convoy/digest.py`.

        The very first call only takes the baseline, at hour zero: there is no
        period behind it to report on. After that, every `DIGEST_EVERY_HOURS`.
        Reading it is left to each agent's next observation -- idle agents are
        asked every few minutes anyway, and pulling everyone off a shift to
        read a report would cost a decision each for no new choice.
        """
        w = self.world
        since = max(0.0, w.digest_at)
        if w.digest_at >= 0.0:
            w.digest = DG.build(w, self.log, since, w.digest_baseline)
            self.log.emit(
                w.sim_time, "digest", text=w.digest,
                since_hour=round(since / 3600.0, 2), significance=Significance.LOW,
            )
        w.digest_at = w.sim_time
        w.digest_baseline = DG.snapshot(w)

    def _record_standings(self) -> None:
        """The score, on the hour, into the log.

        WITHOUT THIS THE RACE IS NOT RECOVERABLE. There is one checkpoint file
        and it is overwritten hourly (PHASE8 §8), so the only surviving record
        of what a city was worth at hour 40 is whatever the log kept -- and
        `Snapshot` is written by the advisor, which most runs never enable.
        "Cinderhold pulled ahead at h37 and never gave it back" is the sentence
        this whole contest exists to be able to say, and it cannot be said from
        a final total.

        Cheap on purpose: one row per hour per city, ~72 rows a side for a full
        run, holding the numbers the boards plot and nothing else.
        """
        w = self.world
        if not w.is_contest():
            return
        for row in w.city_standings():
            self.log.emit(
                w.sim_time, "city_standings", subject=row["city"],
                city=row["city"], name=row["name"],
                total_net_worth=row["total_net_worth"],
                mean_net_worth=row["mean_net_worth"],
                living=row["living"], dead=row["dead"],
                businesses=row["businesses"],
                significance=Significance.LOW,
            )

    # -- decision scheduling ----------------------------------------------

    def _decisions(self) -> None:
        w = self.world
        reeval = self.config.reeval_minutes * 60.0
        for agent in w.agents.values():
            if not agent.alive:
                continue

            # `in_transit` and a 'travel' activity must agree. They are cleared
            # together below and nowhere else, so if anything ever leaves them
            # out of sync the agent is stranded: its location never updates and
            # `in_transit` never clears, leaving it "travelling" while standing
            # still. Recover instead of stranding -- an agent that is no longer
            # on the road is simply where it started.
            if agent.in_transit and agent.activity.kind != "travel":
                agent.in_transit = None

            if agent.activity.kind == "travel" and w.sim_time >= agent.activity.ends_at:
                origin, dest, _p = agent.in_transit or (agent.location, agent.location, 1.0)
                # Resolved BEFORE the location changes, because the risk is a
                # property of the road just travelled, and before `_ask`, so the
                # observation the agent wakes to already shows the empty cart
                # rather than telling it about the robbery an hour later.
                self._resolve_banditry(agent, origin, dest)
                self._resolve_raids(agent, origin, dest)
                agent.location = dest
                agent.in_transit = None
                if agent.mounted_vehicle:
                    w.vehicles[agent.mounted_vehicle].location = dest
                agent.activity = Activity("idle", w.sim_time)
                self._settle_escorts(agent, dest)
                if agent.delivery:                       # convoy/delivery.py
                    DL.load(w, self.log, agent)
                    DL.complete(w, self.log, agent)
                self._ask(agent, "arrived")
                continue

            if w.sim_time >= agent.activity.ends_at:
                self._ask(agent, "activity_complete")
                # If the decision left the agent idle, park it until the next
                # scheduled re-evaluation. Without this an idle agent satisfies
                # "activity complete" on EVERY tick and is asked once a simulated
                # minute instead of once per checkpoint -- invisible with rule
                # agents, which always assign an activity, but a 15x cost
                # multiplier the moment a real model decides to wait.
                if agent.activity.kind == "idle" and agent.activity.ends_at <= w.sim_time:
                    agent.activity = Activity("idle", agent.next_reeval_at)
                continue

            if w.sim_time >= agent.next_reeval_at:
                agent.next_reeval_at = w.sim_time + reeval
                # DO NOT interrupt an agent that is already committed. An eight
                # hour shift used to collect 32 re-evaluations, and the only
                # honest answer to each was "still working": 75% of every action
                # in the 2026-08-15 smoke was an agent reporting it was busy.
                # That is three quarters of the API bill spent on non-decisions,
                # and it means agents rarely get asked at a moment when they
                # could actually DO anything. `start_shift` always promised
                # "one decision, then silence until the session resolves" --
                # this is the engine finally keeping that promise.
                #
                # Hunger is one of two things allowed to interrupt work, because
                # an agent that cannot react to it starves at its own bench.
                #
                # UNHEARD ADVICE is the other, and for the same reason. A
                # recommendation reaches an agent only inside an observation, an
                # observation is built only when the agent is asked, and a
                # working agent is not asked -- so on the first live smoke of the
                # advice channel all six recommendations expired unseen while
                # their targets stood at a bench. The advice was queued, logged
                # and correct; the agent simply never got a turn. That is PHASE4
                # §2 one layer down: not the observation withholding a fact, but
                # the schedule withholding the observation.
                #
                # Only advice never SEEN forces a wake, and it forces exactly
                # one: `observe` marks it delivered, and the agent returns to
                # normal cadence. Waking for every live recommendation would
                # undo the guard this sits inside, which exists because 75% of
                # all actions in the 2026-08-15 smoke were an agent reporting it
                # was still busy.
                busy = (
                    agent.activity.kind in ("work", "travel", "raid")
                    and agent.activity.ends_at > w.sim_time
                )
                unheard = any(
                    r.times_seen == 0 for r in agent.live_advice(w.sim_hour)
                )
                if busy and agent.sustenance_stage == "Normal" and not unheard:
                    continue
                # Name it, so the model is not left to guess why it was pulled
                # off a shift -- and so the transcript shows the interruption.
                self._ask(agent, "advice_received" if unheard else "reevaluation")

    def _ask(self, agent: Agent, reason: str) -> None:
        agent.next_reeval_at = max(
            agent.next_reeval_at, self.world.sim_time + self.config.reeval_minutes * 60.0
        )
        # Already thinking: the wake is not lost, it is simply answered by the
        # decision in flight, which will see the world as it is when it acts.
        if agent.id in self._pending:
            return
        # The moves with one sensible answer are made here, without the model.
        # See `convoy/reflexes.py`.
        if self.config.reflexes and RX.handle(self.world, self.log, agent, reason):
            if agent.activity.kind == "idle" and agent.activity.ends_at <= self.world.sim_time:
                agent.activity = Activity("idle", agent.next_reeval_at)
            return
        agent.last_thought_at = self.world.sim_time
        if self._pool is None:
            self.policy.decide(self.world, agent, reason)
            self._after_thought(agent)
            return
        self._pending[agent.id] = (
            self._pool.submit(self._decide_safely, agent, reason),
            self.world.sim_time,
        )

    def _decide_safely(self, agent: Agent, reason: str) -> None:
        """A worker's whole job. Never lets an exception kill the thread pool
        silently: it is logged against the agent, at the hour, and the run goes
        on -- the same promise `schemas.dispatch` makes for a bad tool call."""
        try:
            self.policy.decide(self.world, agent, reason)
        except Exception as exc:                      # noqa: BLE001
            with self.world_lock:
                self.log.emit(
                    self.world.sim_time, "decision_error", actor=agent.id,
                    error=f"{type(exc).__name__}: {exc}",
                )
        with self.world_lock:
            self._after_thought(agent)

    def _after_thought(self, agent: Agent) -> None:
        """What the agent knows of its own state, taken AFTER it acted.

        Taken before, the agent's own decision looked like news: it paid
        someone, its cash moved, and the next quiet wake was not quiet. In the
        first reflex smoke not one "keep waiting" fired in 62 chances. Messages
        are judged by time instead (`reflexes.news_since`), so one arriving
        while the model was thinking still counts as unseen.
        """
        if self.config.reflexes:
            agent.thought_fingerprint = RX.fingerprint(self.world, agent)

    def _reap(self) -> None:
        for aid in [a for a, (f, _) in self._pending.items() if f.done()]:
            del self._pending[aid]

    def _keep_up(self) -> None:
        """Hold the clock within `max_decision_lag_minutes` of the oldest
        decision still being thought about. Without it a fast clock would run
        hours ahead while an agent was still deciding what to do at dawn."""
        if self._pool is None:
            return
        lag = self.config.max_decision_lag_minutes * 60.0
        while True:
            self._reap()
            oldest = min((t for _, t in self._pending.values()), default=None)
            if oldest is None or self.world.sim_time - oldest < lag:
                return
            time.sleep(0.02)

    def drain(self) -> None:
        """Wait for every decision in flight to land. Call before saving or
        ending a run, so nothing an agent decided is lost with the process."""
        if self._pool is None:
            return
        while self._pending:
            self._reap()
            time.sleep(0.02)

    def close(self) -> None:
        self.drain()
        if self._pool is not None:
            self._pool.shutdown(wait=True)
            self._pool = None

    def _diaries(self) -> None:
        """Fixed-cadence hourly reflection, separate from any real decision."""
        w = self.world
        for agent in w.agents.values():
            if w.sim_time < agent.next_diary_at:
                continue
            agent.next_diary_at += self.config.diary_hours * 3600.0
            if not agent.alive:
                continue
            entry = self._diary_text(agent)
            ev = self.log.emit(
                w.sim_time, "diary", actor=agent.id, location=agent.location,
                text=entry, net_worth=round(agent.net_worth(w), 1),
            )
            agent.memory.append(len(self.log.events) - 1)

    def _diary_text(self, agent: Agent) -> str:
        """Phase 1 placeholder. Phase 4 replaces this with a real model call."""
        act = agent.activity.kind
        if act == "work" and agent.current_job:
            biz = self.world.businesses.get(agent.current_job[0])
            return f"working as {agent.current_job[1]} at {biz.name if biz else '?'}"
        if act == "travel" and agent.in_transit:
            return f"en route {agent.in_transit[0]} to {agent.in_transit[1]}"
        return f"{act} at {agent.location}"
