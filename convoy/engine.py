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

import time
from dataclasses import dataclass
from typing import Callable, Protocol

from . import data as D
from . import economy as E
from .events import EventLog, Significance
from .state import Activity, Agent, Business, World

TICK_SECONDS = 60.0     # one simulated minute of continuous processes


class Policy(Protocol):
    """What the engine needs from a decision-maker.

    Phase 1: rule-based. Phase 2+: an OpenRouter-backed policy with the identical
    signature, so the engine is agnostic to which is driving.
    """

    def decide(self, world: World, agent: Agent, reason: str) -> None: ...


@dataclass
class EngineConfig:
    duration_hours: float = D.SIM_DURATION_HOURS
    speed: float = 3600.0                 # sim seconds per real second; 1.0 == real time
    checkpoint_every_hours: float = 1.0
    reeval_minutes: float = D.REEVALUATION_INTERVAL_MIN
    diary_hours: float = D.DIARY_INTERVAL_HOURS


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
        self._next_checkpoint = self.config.checkpoint_every_hours * 3600.0

    # -- main loop ---------------------------------------------------------

    def run(self) -> None:
        w, cfg = self.world, self.config
        end = cfg.duration_hours * 3600.0
        started_wall = time.monotonic()

        self.log.emit(
            w.sim_time, "sim_start",
            agents=len(w.agents), businesses=len(w.businesses),
            duration_hours=cfg.duration_hours,
        )

        while w.sim_time < end:
            self.tick(TICK_SECONDS)

            if cfg.speed < 1000:  # real-time or near-real-time: pace against wall clock
                target_wall = started_wall + w.sim_time / cfg.speed
                drift = target_wall - time.monotonic()
                if drift > 0:
                    time.sleep(drift)

            if w.sim_time >= self._next_checkpoint:
                self._next_checkpoint += cfg.checkpoint_every_hours * 3600.0
                self.log.flush()
                if self.on_checkpoint:
                    self.on_checkpoint(w)

        self.log.emit(
            w.sim_time, "sim_end",
            leaderboard=[(n, round(v, 1)) for n, v in w.leaderboard()[:10]],
            treasury=round(w.government.treasury, 1),
        )
        self.log.flush()

    # -- one simulated minute ---------------------------------------------

    def tick(self, dt: float) -> None:
        w = self.world
        w.sim_time += dt
        hours = dt / 3600.0

        self._advance_travel(dt)
        self._sustenance(hours)
        self._produce(hours)
        self._pay_wages(hours)
        self._research(hours)
        self._property_tax()
        self._road_tax()
        self._expire_social()
        self._check_solvency()
        self._respawn()
        self._decisions()
        self._diaries()

    # -- continuous processes ---------------------------------------------

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

        payout = 0.0
        if agent.insurance.get("Life", 0.0) > 0:
            payout = E.insurance_payout(agent.insurance["Life"])
            agent.denari += payout
            broker = w.government_business("Insurance Brokerage")
            if broker and not broker.is_government:
                broker.cash -= payout
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

    def _produce(self, hours: float) -> None:
        """Extraction, refining and crafting, at the Businesses tab decay rate."""
        w = self.world
        for biz in w.businesses.values():
            if biz.closed or not biz.active_production:
                continue
            output = biz.active_production
            headcount = biz.active_headcount(w)
            biz.peak_headcount = max(biz.peak_headcount, headcount)
            if headcount == 0:
                continue    # zero workers == zero output, per the Businesses tab

            # Efficiency comes from the ALLOCATED tier, not from raw RP -- RP has
            # to be spent on a track before it speeds anything up.
            eff = E.efficiency_bonus(biz.research.efficiency_tier)

            base_rate = self._base_rate_for(output)
            role = D.ROLE_FOR_OUTPUT.get(output, "Laborer")

            if biz.is_government:
                # Always fully staffed by exemption; a stable one-worker market floor.
                rate = base_rate
            else:
                rate = 0.0
                for emp in biz.production_staff():
                    if emp.is_npc:
                        # NPC hires work at Novice skill, always on shift.
                        rate += E.worker_output_rate(base_rate, headcount, 0.0, eff)
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
                    agent.skill_hours[emp.role] = agent.skill_hours.get(emp.role, 0.0) + hours

            biz.production_buffer += rate * hours
            units = int(biz.production_buffer)
            if units <= 0:
                continue

            recipe = D.REFINING_RECIPES.get(output) or D.CRAFTING_RECIPES.get(output)
            if recipe and not biz.is_government:
                # Raw materials are auto-shipped to factories (designer decision,
                # 2026-08-11) -- no hauling leg for production inputs yet. The
                # business buys what it lacks at BASE price from its own cash,
                # which is exactly the basis the Production Chain tab's Input Cost
                # column uses, so the designed margins hold.
                units = self._source_inputs(biz, recipe, units)
                if units <= 0:
                    biz.production_buffer = min(biz.production_buffer, 1.0)
                    continue
                for i, q in recipe.inputs.items():
                    biz.remove_item(i, q * units)

            # A worked site can only stockpile so much. When the yard is full,
            # production stalls until someone hauls it away -- which is what
            # makes carts, expansion, and distance-to-market matter.
            if biz.plots:
                room = E.site_storage_capacity(biz.plots) - sum(biz.inventory.values())
                if room <= 0:
                    if biz.active_production:
                        self.log.emit(
                            w.sim_time, "site_full", subject=biz.id,
                            location=biz.location, business=biz.name,
                            capacity=E.site_storage_capacity(biz.plots),
                        )
                    biz.production_buffer = min(biz.production_buffer, 1.0)
                    continue
                units = min(units, room)

            biz.production_buffer -= units
            biz.add_item(output, units)
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
        w = self.world
        gov = w.government
        for biz in w.businesses.values():
            if biz.closed:
                continue
            for emp in biz.roster:
                if emp.is_npc:
                    # NPC hires are always on shift and always cost the NPC wage.
                    gross = emp.wage * hours
                    biz.cash -= gross
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
                    biz.cash -= gross
                net, tax = E.apply_wage_tax(gross, gov.wage_tax)
                agent.denari += net
                gov.collect(tax)

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

    def _check_solvency(self) -> None:
        """24-hour grace period after cash hits zero, then the business closes."""
        w = self.world
        for biz in list(w.businesses.values()):
            if biz.closed or biz.is_government:
                continue
            if biz.cash < 0:
                if biz.insolvent_since is None:
                    biz.insolvent_since = w.sim_time
                    self.log.emit(
                        w.sim_time, "bankruptcy_warning", actor=biz.owner, subject=biz.id,
                        business=biz.name, cash=round(biz.cash, 2),
                        grace_hours=D.BANKRUPTCY_GRACE_HOURS,
                    )
                elif w.sim_time - biz.insolvent_since >= D.BANKRUPTCY_GRACE_HOURS * 3600.0:
                    self._close_business(biz)
            else:
                biz.insolvent_since = None

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
                    agent.location = "Town"
                agent.activity = Activity("idle", w.sim_time)

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
                _o, dest, _p = agent.in_transit or (agent.location, agent.location, 1.0)
                agent.location = dest
                agent.in_transit = None
                if agent.mounted_vehicle:
                    w.vehicles[agent.mounted_vehicle].location = dest
                agent.activity = Activity("idle", w.sim_time)
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
                self._ask(agent, "reevaluation")

    def _ask(self, agent: Agent, reason: str) -> None:
        agent.next_reeval_at = max(
            agent.next_reeval_at, self.world.sim_time + self.config.reeval_minutes * 60.0
        )
        self.policy.decide(self.world, agent, reason)

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
