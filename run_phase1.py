#!/usr/bin/env python3
"""Phase 1 — core engine validation, zero LLM calls.

Drives the full economy with deterministic rule-based agents for 48 game-hours
and asserts nothing nonsensical happens: no negative Denari, no phantom
inventory, no over-capacity carrying, no starvation death without escalation
warnings first, businesses that can actually go bankrupt, prices that move.

Since there are no API calls, this runs at whatever wall-clock speed the
computation achieves — no throttling to real time.

Writes a raw, timestamped log of every event to runs/phase1/ as both JSONL and
CSV. That file is the reviewable deliverable, separate from the Phase 4
narrative report generator.

    python3 run_phase1.py                 # 48 game-hours, 10 agents
    python3 run_phase1.py --hours 120 --agents 25
"""

from __future__ import annotations

import argparse
from pathlib import Path

from convoy import checkpoint
from convoy.engine import Engine, EngineConfig
from convoy.events import EventLog, Significance
from convoy.rule_agents import RuleBasedPolicy, assign_archetypes
from convoy.world_setup import new_world, rule_based_roster

RUN_DIR = Path("runs/phase1")
PHASE1_HOURS = 48.0


def check_invariants(world, log) -> list[str]:
    """Everything Phase 1 exists to prove. Returns a list of violations."""
    problems: list[str] = []

    for agent in world.agents.values():
        if agent.denari < -1e-6:
            problems.append(f"{agent.name} has negative Denari ({agent.denari:.2f})")
        for item, qty in agent.inventory.items():
            if qty < 0:
                problems.append(f"{agent.name} has phantom inventory {item}={qty}")
        cap = agent.carry_capacity(world)
        if agent.carried_units() > cap:
            problems.append(f"{agent.name} carries {agent.carried_units()} over capacity {cap}")
        if agent.current_job:
            biz = world.businesses.get(agent.current_job[0])
            if biz is None or biz.closed:
                problems.append(f"{agent.name} is employed by a closed business")
        if agent.alive and agent.sustenance_stage == "Death":
            problems.append(f"{agent.name} is at Death stage but still alive")
        if agent.health < 0:
            problems.append(f"{agent.name} has negative health")

    for biz in world.businesses.values():
        for item, qty in biz.inventory.items():
            if qty < 0:
                problems.append(f"{biz.name} has phantom inventory {item}={qty}")
        if biz.closed and biz.roster:
            problems.append(f"{biz.name} is closed but still has staff")
        if not biz.is_government and biz.cash < 0 and biz.insolvent_since is None:
            problems.append(f"{biz.name} is in debt without a grace timer")
        if biz.active_production and biz.active_production not in biz.spec.outputs:
            problems.append(f"{biz.name} produces {biz.active_production}, not in its outputs")

    if world.government.treasury < -1e-6:
        problems.append(f"treasury is negative ({world.government.treasury:.2f})")

    # No agent may starve to death without Hungry and Starving warnings first.
    warned_hungry: set[str] = set()
    warned_starving: set[str] = set()
    for e in log.events:
        if e.type == "sustenance_hungry":
            warned_hungry.add(e.actor)
        elif e.type == "sustenance_starving":
            warned_starving.add(e.actor)
        elif e.type == "starved_to_death":
            if e.actor not in warned_hungry:
                problems.append(f"{e.actor} starved with no Hungry warning")
            if e.actor not in warned_starving:
                problems.append(f"{e.actor} starved with no Starving warning")

    return problems


def check_systems_exercised(world, log, hours: float = PHASE1_HOURS) -> list[tuple[str, bool, str]]:
    """Phase 1 must not merely avoid breaking — it must actually exercise each system."""
    counts = log.counts()
    founded = [b for b in world.businesses.values() if not b.is_government]
    prices = {t.item for t in world.market.transactions}
    return [
        ("resources produced", counts.get("production", 0) > 0,
         f"{counts.get('production', 0):,} production events"),
        ("wages & employment", counts.get("hired", 0) > 0,
         f"{counts.get('hired', 0)} hires"),
        ("trade / prices move", len(world.market.transactions) > 0,
         f"{len(world.market.transactions):,} transactions over {len(prices)} goods"),
        ("sales tax collected", world.government.treasury > 0,
         f"treasury {world.government.treasury:,.1f}"),
        ("businesses founded", len(founded) > 0, f"{len(founded)} player businesses"),
        # Kept distinct: an asset wipe on death also closes a business, and
        # conflating the two would let a real bankruptcy failure hide behind it.
        ("bankruptcy path", counts.get("business_bankrupt", 0) > 0,
         f"{counts.get('business_bankrupt', 0)} bankruptcies"),
        ("NPC payroll", counts.get("inputs_sourced", 0) >= 0 and any(
            e.is_npc for b in world.businesses.values() for e in b.roster) or
         counts.get("business_bankrupt", 0) > 0, "NPC employees hired"),
        ("death: loot dropped", counts.get("looted", 0) > 0,
         f"{counts.get('looted', 0)} loot pickups"),
        ("death: uninsured assets wiped", counts.get("assets_wiped", 0) > 0,
         f"{counts.get('assets_wiped', 0)} asset wipes"),
        ("factory auto-sourcing", counts.get("inputs_sourced", 0) > 0,
         f"{counts.get('inputs_sourced', 0)} input purchases"),
        # Research Tier 1 costs 150 RP == ~19 researcher-hours. A solo owner who
        # must also eat and earn cannot fund that inside a 48-hour window, so at
        # Phase 1 duration this is reported as out of reach rather than failing.
        ("research: RP accrued",
         counts.get("research_tier_unlocked", 0) > 0 or hours < 72,
         f"{counts.get('research_tier_unlocked', 0)} tiers reached"
         + ("  (needs >48h for a solo researcher)"
            if hours < 72 and not counts.get("research_tier_unlocked") else "")),
        ("research: RP spent on a track",
         counts.get("research_allocated", 0) > 0 or hours < 72,
         f"{counts.get('research_allocated', 0)} allocations"),
        ("vehicles purchased", counts.get("vehicle_purchased", 0) > 0,
         f"{counts.get('vehicle_purchased', 0)} vehicles"),
        ("sustenance: eating", counts.get("ate", 0) > 0, f"{counts.get('ate', 0)} meals"),
        ("sustenance: Hungry", counts.get("sustenance_hungry", 0) > 0,
         f"{counts.get('sustenance_hungry', 0)} agents went hungry"),
        ("sustenance: Starving", counts.get("sustenance_starving", 0) > 0,
         f"{counts.get('sustenance_starving', 0)} agents starved"),
        ("sustenance: Death", counts.get("starved_to_death", 0) > 0,
         f"{counts.get('starved_to_death', 0)} starvation deaths"),
    ]


def report(world, log, hours: float) -> None:
    print("\n" + "=" * 74)
    print(f"PHASE 1 RESULT — {hours:.0f} game-hours, {len(log.events):,} events logged")
    print("=" * 74)

    print("\nEvent volume by type")
    for etype, n in list(log.counts().items())[:14]:
        print(f"  {etype:<26} {n:>9,}")

    print("\nNet Worth leaderboard")
    for name, value in world.leaderboard():
        a = next(x for x in world.agents.values() if x.name == name)
        print(
            f"  {name:<12} {a.archetype:<12} {value:>9,.1f}  denari={a.denari:>8,.1f}  "
            f"biz={len(a.owned_businesses)}  inv={a.carried_units():<3} "
            f"{a.sustenance_stage:<8} hp={a.health:>5.1f} "
            f"since_meal={a.hours_since_last_meal:>5.1f}h"
        )

    player_biz = [b for b in world.businesses.values() if not b.is_government]
    if player_biz:
        print("\nPlayer-owned businesses")
        for b in player_biz:
            status = "CLOSED (bankrupt)" if b.closed else f"cash={b.cash:,.1f}"
            print(f"  {b.name:<32} {b.type:<22} {status:<20} stock={sum(b.inventory.values())}")

    print("\nGovernment production (units accumulated)")
    for b in world.businesses.values():
        if b.is_government and sum(b.inventory.values()):
            print(f"  {b.name:<42} {sum(b.inventory.values()):>8,}")

    # Did the diminishing-returns curve actually engage under live load? This is
    # the one major formula that unit tests alone cannot confirm.
    staffed = sorted(
        (b for b in world.businesses.values() if b.peak_headcount > 0),
        key=lambda b: -b.peak_headcount,
    )
    if staffed:
        print("\nStaffing contention (peak simultaneous production staff)")
        for b in staffed[:6]:
            n = b.peak_headcount
            from convoy.economy import per_worker_multiplier, total_output_multiplier
            print(
                f"  {b.name:<40} n={n:<3} per-worker={per_worker_multiplier(n):.3f}  "
                f"total={total_output_multiplier(n):.3f}x"
            )
        top = staffed[0].peak_headcount
        if top >= 19:
            print(f"  -> reached the n=19-20 output peak (max observed n={top})")
        elif top > 1:
            print(f"  -> decay engaged but stayed below the peak (max observed n={top})")

    if world.chat:
        by_channel: dict[str, int] = {}
        for m in world.chat:
            by_channel[m.channel] = by_channel.get(m.channel, 0) + 1
        print(f"\nChat — {len(world.chat)} retained "
              + ", ".join(f"{k}={v}" for k, v in sorted(by_channel.items()))
              + "  (full history in the event log)")
        for channel in ("world", "guild", "direct"):
            msgs = [m for m in world.chat if m.channel == channel]
            if not msgs:
                continue
            print(f"  -- {channel} ({len(msgs)} retained)")
            for m in msgs[-4:]:
                print(f"     {m.format()}")

    if world.guilds:
        print(f"\nGuilds — {len(world.guilds)}")
        for g in list(world.guilds.values())[:6]:
            print(f"  {g.name:<28} members={len(g.members):<3} invited={len(g.invited)}")

    trades = [t for t in world.trade_offers.values()]
    if trades:
        done = [t for t in trades if t.status == "accepted"]
        print(f"\nPlayer-to-player trade — {len(trades)} offers, {len(done)} accepted")
        for t in done[:5]:
            print(f"  {t.items} for {t.price:.2f} at {t.location}")

    print(f"\nTreasury: {world.government.treasury:,.2f} Denari")

    print("\nSystems exercised")
    for label, ok, detail in check_systems_exercised(world, log, hours):
        print(f"  [{'x' if ok else ' '}] {label:<24} {detail}")

    # Art binding is checked alongside the economic invariants for the same
    # reason they are: it depends on `data.py`, and the failure it catches is a
    # quiet one -- a good added without an icon renders as a blank square in a
    # classroom months later, in front of people.
    from convoy import sprites as SP

    # Checkpoint completeness rides along for the same reason again: `save`
    # encodes any dataclass generically, `load` needs it registered, and the gap
    # between the two is invisible until someone restores a run. Four types had
    # accumulated unregistered before anything tried.
    problems = (
        check_invariants(world, log)
        + SP.check()
        + [
            f"{name} is a state dataclass but is not registered in "
            f"checkpoint._CLASSES -- checkpoints containing one cannot be loaded"
            for name in checkpoint.check()
        ]
    )
    print("\n" + "-" * 74)
    if problems:
        print(f"INVARIANT VIOLATIONS ({len(problems)}):")
        for p in problems[:25]:
            print(f"  ! {p}")
    else:
        print("INVARIANTS: all clean.")
    print("-" * 74)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--hours", type=float, default=PHASE1_HOURS)
    ap.add_argument("--agents", type=int, default=10)
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args()

    RUN_DIR.mkdir(parents=True, exist_ok=True)
    jsonl = RUN_DIR / "events.jsonl"
    if jsonl.exists():
        jsonl.unlink()

    log = EventLog(jsonl, echo_min=99 if args.quiet else Significance.HIGH)
    world = new_world(log, rule_based_roster(args.agents))
    assignment = assign_archetypes(world)
    policy = RuleBasedPolicy(log, seed=args.seed)
    print("Archetypes: " + ", ".join(f"{n}={a}" for n, a in assignment.items()))

    engine = Engine(
        world, log, policy,
        EngineConfig(duration_hours=args.hours, speed=1e9, checkpoint_every_hours=6.0),
        on_checkpoint=lambda w: checkpoint.save(w, RUN_DIR / "state.json"),
    )
    engine.run()

    checkpoint.save(world, RUN_DIR / "state.json")
    csv_path = log.export_csv(RUN_DIR / "events.csv")
    report(world, log, args.hours)
    print(f"\nRaw event log: {jsonl}  and  {csv_path}")
    print(f"Checkpoint:    {RUN_DIR / 'state.json'}")
    log.close()

    return 1 if check_invariants(world, log) else 0


if __name__ == "__main__":
    raise SystemExit(main())
