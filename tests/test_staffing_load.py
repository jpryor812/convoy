#!/usr/bin/env python3
"""Live-engine staffing load test — does the decay curve hold under real load?

The conformance suite checks the diminishing-returns FORMULA in isolation. This
drives the actual engine: it staffs one business with n real agents on shift,
runs an hour of simulated time, and compares measured output against the
Businesses tab's Total Output Multiplier column.

That distinction matters. A formula can be right while the engine applies it to
the wrong headcount, double-counts a worker, or misses the sustenance penalty.
Rule-based agents each found their own business, so they never stack high enough
to reach the n=19-20 peak on their own -- this reaches it directly.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from convoy import data as D
from convoy import economy as E
from convoy.engine import Engine, EngineConfig
from convoy.state import Plot
from convoy.events import EventLog
from convoy.state import Activity, Agent, Business, Employment, World

FAILURES: list[str] = []


class NullPolicy:
    """Agents hold whatever activity they were given; no decisions during the test."""

    def decide(self, world, agent, reason):
        return


def measure_output(headcount: int, hours: float = 1.0) -> float:
    """Units of Grain produced in `hours` by a Farm staffed with `headcount` workers."""
    world = World()
    log = EventLog(None, echo_min=99)

    biz = Business(
        id="B0001", type="Farm", name="Load Test Farm", owner="A0001",
        location="Town", cash=1e9, active_production="Wheat",
    )
    # A storehouse big enough that it never binds. This measures the LABOUR
    # curve, and from 2026-08-19 every business has a finite yard -- so at ten
    # workers the farm filled its 240-unit default part-way through the hour and
    # the numbers flattened at ~242 for every headcount above four. That is the
    # land system working correctly and the measurement being contaminated by it.
    biz.storage_tier = D.MAX_STORAGE_TIER
    world.businesses[biz.id] = biz

    for i in range(headcount):
        aid = f"A{i + 1:04d}"
        agent = Agent(id=aid, name=f"W{i}", model="rule-based", location="Town")
        # Long shift so nothing resolves mid-measurement, and a fresh meal so the
        # Sustenance penalty is not silently in play.
        agent.activity = Activity("work", 1e9, {"business": biz.id, "role": "Farmhand"})
        agent.hours_since_last_meal = 0.0
        agent.next_reeval_at = 1e9
        agent.next_diary_at = 1e9
        world.agents[aid] = agent
        biz.roster.append(Employment(aid, "Farmhand", 0.0))

    engine = Engine(world, log, NullPolicy(), EngineConfig(duration_hours=hours, speed=1e9))
    ticks = int(hours * 3600 / 60)
    for _ in range(ticks):
        engine.tick(60.0)

    return biz.inventory.get("Wheat", 0) + biz.production_buffer


def check(label: str, actual, expected, tol: float) -> None:
    if abs(actual - expected) > tol:
        FAILURES.append(f"{label}: got {actual:.3f}, expected {expected:.3f}")


def test_live_output_matches_table():
    """Measured engine output vs the Businesses tab multiplier, across the curve."""
    base = D.RESOURCES["Wheat"].base_rate_hr      # 72/hr for a single Novice worker
    print(f"{'n':>4} {'measured/hr':>12} {'expected/hr':>12} {'multiplier':>11} {'table':>8}")
    for n in (1, 2, 3, 4, 5, 10, 15, 19, 20, 25, 30):
        measured = measure_output(n)
        expected = base * E.total_output_multiplier(n)
        mult = measured / base
        print(f"{n:>4} {measured:>12.2f} {expected:>12.2f} {mult:>10.3f}x "
              f"{E.total_output_multiplier(n):>7.3f}x")
        check(f"live output at n={n}", measured, expected, tol=0.05)


def test_peak_is_reachable_and_declines():
    """Total output must actually peak at n=19-20 and fall off past it, live."""
    at_5 = measure_output(5)
    at_19 = measure_output(19)
    at_20 = measure_output(20)
    at_30 = measure_output(30)

    check("n=19 and n=20 are within a hair of each other", at_19, at_20, tol=0.6)
    if not at_19 > at_5:
        FAILURES.append("output at n=19 should exceed n=5")
    if not at_30 < at_20:
        FAILURES.append(
            f"output should DECLINE past the peak: n=30 gave {at_30:.1f}, "
            f"n=20 gave {at_20:.1f}"
        )
    print(f"\n  n=5 -> {at_5:.1f}/hr, n=19 -> {at_19:.1f}/hr, "
          f"n=20 -> {at_20:.1f}/hr, n=30 -> {at_30:.1f}/hr")
    print("  past the peak, hiring more workers actively reduces total output.")


def test_sustenance_penalty_applies_live():
    """A Hungry workforce must produce 10% less through the real engine."""
    world = World()
    log = EventLog(None, echo_min=99)
    biz = Business(
        id="B0001", type="Farm", name="Hungry Farm", owner="A0001",
        location="Town", cash=1e9, active_production="Wheat",
    )
    world.businesses[biz.id] = biz
    agent = Agent(id="A0001", name="W", model="rule-based", location="Town")
    agent.activity = Activity("work", 1e9, {"business": biz.id, "role": "Farmhand"})
    agent.next_reeval_at = agent.next_diary_at = 1e9
    # Already 13 hours past a 12-hour window: Hungry, not yet Starving.
    agent.hours_since_last_meal = 13.0
    agent.last_meal_window = 12.0
    agent.sustenance_stage = "Hungry"
    world.agents["A0001"] = agent
    biz.roster.append(Employment("A0001", "Farmhand", 0.0))

    engine = Engine(world, log, NullPolicy(), EngineConfig(speed=1e9))
    for _ in range(60):
        engine.tick(60.0)

    produced = biz.inventory.get("Wheat", 0) + biz.production_buffer
    check("hungry worker produces 90%", produced, 72 * 0.90, tol=0.05)
    print(f"  hungry worker: {produced:.2f}/hr vs 72.00 baseline "
          f"({produced / 72:.1%})")


def test_researcher_pool_is_uncapped_at_stores():
    """Research tab: "No cap on Researcher count."

    The Businesses tab's Max Employees column (2 for stores) governs PRODUCTION
    staff only. Applying it to researchers would block the high-research store
    strategy entirely -- which it did, until this was fixed.
    """
    from convoy import actions as A

    world = World()
    log = EventLog(None, echo_min=99)
    owner = Agent(id="A0001", name="Owner", model="rule-based", location="Town")
    world.agents["A0001"] = owner
    biz = Business(
        id="B0001", type="Weaponsmith / Armory", name="Store", owner="A0001",
        location="Town", cash=1e9,
    )
    world.businesses[biz.id] = biz
    assert D.BUSINESS_TYPES["Weaponsmith / Armory"].max_employees == 2

    hired = 0
    for _ in range(6):
        ok, msg = A.hire_npc_employee(world, log, owner, biz.id, "Researcher",
                                      as_researcher=True)
        if ok:
            hired += 1
    if hired != 6:
        FAILURES.append(f"researcher pool capped at {hired}, should be uncapped")

    # PRODUCTION staff are capped by LAND (2026-08-19). This used to assert the
    # opposite -- "player-owned production staff should be uncapped" -- which was
    # the designer decision of 2026-08-14 and held until land became the scarce
    # thing. A business now seats one employee per developed plot beyond its
    # building, so hiring is an act of construction.
    #
    # Researchers stay uncapped, and that separation is the point of this test:
    # the Research tab says "no cap on Researcher count", so land must gate the
    # people who take up floor space and not the ones who do not.
    prod = 0
    for _ in range(5):
        ok, _ = A.hire_npc_employee(world, log, owner, biz.id, "Blacksmith")
        if ok:
            prod += 1
    if prod != 0:
        FAILURES.append(
            f"a store on no developed land should seat nobody, hired {prod}"
        )

    # Give it ground, and it can hire exactly as much as the ground allows.
    for _ in range(D.STRUCTURE_PLOTS + 3):
        world.plots[world.new_id("L")] = Plot(
            id=f"L{len(world.plots):04d}", location="Town", owner=owner.id,
            business=biz.id, developed=True,
        )
    seats = E.employee_slots(world, biz)
    if seats != 3:
        FAILURES.append(f"5 developed plots should seat 3, got {seats}")
    prod = 0
    for _ in range(5):
        ok, _ = A.hire_npc_employee(world, log, owner, biz.id, "Blacksmith")
        if ok:
            prod += 1
    if prod != 3:
        FAILURES.append(f"land should cap production staff at 3, hired {prod}")

    # The government business of the same type still caps.
    gov = Business(
        id="G9001", type="Weaponsmith / Armory", name="Government Store",
        owner="Government", location="Town", cash=1e9,
    )
    world.businesses[gov.id] = gov
    if A.employee_cap(world, gov) != D.GOVERNMENT_MAX_EMPLOYEES:
        FAILURES.append(f"government cap should be {D.GOVERNMENT_MAX_EMPLOYEES}")
    print(f"  researchers hired at a 2-employee store: {hired} (uncapped)")
    print(f"  production staff hired at the same store: {prod} (capped)")


def test_research_efficiency_changes_output():
    """An allocated Efficiency tier must actually speed production up."""
    from convoy import actions as A

    def farm_output(efficiency_tier: int) -> float:
        world = World()
        log = EventLog(None, echo_min=99)
        biz = Business(
            id="B0001", type="Farm", name="F", owner="A0001", location="Town",
            cash=1e9, active_production="Wheat",
        )
        biz.research.efficiency_tier = efficiency_tier
        world.businesses[biz.id] = biz
        a = Agent(id="A0002", name="W", model="rule-based", location="Town")
        a.activity = Activity("work", 1e9, {"business": biz.id, "role": "Farmhand"})
        a.next_reeval_at = a.next_diary_at = 1e9
        world.agents[a.id] = a
        biz.roster.append(Employment(a.id, "Farmhand", 0.0))
        eng = Engine(world, log, NullPolicy(), EngineConfig(speed=1e9))
        for _ in range(60):
            eng.tick(60.0)
        return biz.inventory.get("Wheat", 0) + biz.production_buffer

    base = farm_output(0)
    check("no research == base rate", base, 72.0, tol=0.05)
    for tier, bonus in [(1, 0.05), (3, 0.15), (5, 0.25)]:
        out = farm_output(tier)
        check(f"efficiency tier {tier} gives +{bonus:.0%}", out, 72.0 * (1 + bonus), tol=0.05)
        print(f"  efficiency tier {tier}: {out:.2f}/hr vs {base:.2f} base "
              f"(+{(out / base - 1):.0%})")


def test_research_allocation_costs():
    """RP is a currency: each track advances independently and competes for it."""
    from convoy import actions as A

    world = World()
    log = EventLog(None, echo_min=99)
    owner = Agent(id="A0001", name="Owner", model="rule-based", location="Town")
    world.agents["A0001"] = owner
    biz = Business(id="B0001", type="Farm", name="F", owner="A0001", location="Town")
    world.businesses[biz.id] = biz

    biz.research.unspent_rp = 149.0
    ok, _ = A.allocate_research(world, log, owner, biz.id, "efficiency")
    if ok:
        FAILURES.append("tier 1 should cost 150 RP, allocated at 149")

    biz.research.unspent_rp = 150.0
    ok, _ = A.allocate_research(world, log, owner, biz.id, "efficiency")
    if not ok or biz.research.efficiency_tier != 1:
        FAILURES.append("tier 1 efficiency should unlock at exactly 150 RP")
    check("RP is spent, not just checked", biz.research.unspent_rp, 0.0, tol=1e-6)

    # Quality tier 1 costs its own 150 -- the tracks do not share progress.
    ok, _ = A.allocate_research(world, log, owner, biz.id, "quality")
    if ok:
        FAILURES.append("quality tier 1 should need its own 150 RP")
    biz.research.unspent_rp = 150.0
    A.allocate_research(world, log, owner, biz.id, "quality")
    check("quality advanced independently", biz.research.quality_tier, 1, tol=1e-9)

    # Tier 2 costs the DELTA (400 - 150 = 250), not the full cumulative figure.
    biz.research.unspent_rp = 249.0
    ok, _ = A.allocate_research(world, log, owner, biz.id, "efficiency")
    if ok:
        FAILURES.append("tier 2 should cost 250 RP (the 400-150 delta)")
    biz.research.unspent_rp = 250.0
    ok, _ = A.allocate_research(world, log, owner, biz.id, "efficiency")
    if not ok or biz.research.efficiency_tier != 2:
        FAILURES.append("tier 2 efficiency should unlock at the 250 RP delta")
    print("  tier 1 = 150 RP, tier 2 = 250 RP delta, tracks progress independently")


def main() -> int:
    for t in (test_live_output_matches_table, test_peak_is_reachable_and_declines,
              test_sustenance_penalty_applies_live,
              test_researcher_pool_is_uncapped_at_stores,
              test_research_efficiency_changes_output,
              test_research_allocation_costs):
        print(f"\n--- {t.__name__} ---")
        t()
    print()
    if FAILURES:
        print(f"{len(FAILURES)} FAILURES:")
        for f in FAILURES:
            print(f"  ! {f}")
        return 1
    print("Live engine output matches the Businesses tab across the whole curve.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
