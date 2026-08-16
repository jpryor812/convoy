#!/usr/bin/env python3
"""What the agent sees.

Two things here must never silently break.

The STATIC/DYNAMIC split: `static_briefing()` is what gets cached, so it must be
byte-identical on every call and must never reach into a world or an agent. If
anything world-dependent leaks into it, the cache stops hitting and the run gets
several times more expensive without any visible failure.

The stolen-goods boundary: hot goods live outside `inventory` precisely so no
sell path can touch them. If they ever showed up under `carrying`, an agent
would plan around inventory it cannot legally sell.

Also included is a golden snapshot of the rendered observation. It exists so
that changing the prompt is a visible diff rather than a silent behaviour shift
in the middle of a 120-hour run.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from convoy import data as D
from convoy import world_map as M
from convoy import observe as O
from convoy.events import EventLog, Significance
from convoy.state import Agent, Business, Property, VehicleInstance, World

FAILURES: list[str] = []
HOUR = 3600.0

GOLDEN = Path(__file__).parent / "golden_observation.txt"


def check(label, actual, expected) -> None:
    if actual != expected:
        FAILURES.append(f"{label}: got {actual!r}, expected {expected!r}")


def ok(label, condition, detail="") -> None:
    if not condition:
        FAILURES.append(f"{label}{': ' + detail if detail else ''}")


def setup():
    """A fixed world -- no engine run, so the snapshot is deterministic."""
    w, log = World(), EventLog(None, echo_min=99)
    w.sim_time = 20 * HOUR

    a = Agent(id="A0001", name="Tester", model="rb", location="Kiln Row")
    a.denari = 500.0
    a.inventory = {"Iron": 4, "Grain": 2}
    w.agents[a.id] = a

    other = Agent(id="A0002", name="Neighbour", model="rb", location="Kiln Row")
    w.agents[other.id] = other

    v = VehicleInstance(id="V1", type="Donkey Cart", owner=a.id, location="Kiln Row")
    w.vehicles["V1"] = v
    a.owned_vehicles.append("V1")
    a.mounted_vehicle = "V1"

    biz = Business(
        id="B0001", type="Farm", name="Tester's Farm", owner=a.id, location="Kiln Row",
        cash=120.0, plots=M.SITE_BASE_PLOTS,
    )
    biz.inventory = {"Grain": 30}
    w.businesses[biz.id] = biz
    a.owned_businesses.append(biz.id)

    return w, log, a


# ---------------------------------------------------------------------------

def test_static_is_pure_and_stable():
    """The cached prefix must not vary -- that is the whole basis of caching."""
    first, second = O.static_briefing(), O.static_briefing()
    check("briefing is deterministic", first, second)

    # It must not depend on world state, so building a world and mutating the
    # government's tax rates cannot move it.
    w, _log, _a = setup()
    w.government.road_tax = 0.04
    w.government.sales_tax = 0.19
    check("briefing ignores world state", O.static_briefing(), first)

    for fact in ["The Switchbacks", "No escape off-road", "Copper Gulch", "Iron"]:
        ok(f"briefing mentions {fact}", fact in first)

    # Tax RATES are dynamic and must not be baked into the cached prefix.
    ok("briefing states no tax rate", "0.5%" not in first and "1%/day" not in first)


def test_npc_prices_are_static_only():
    """NPC prices are in the briefing, so repeating them per call is waste."""
    brief = O.static_briefing()
    ok("briefing carries the NPC price table", "NPC sells to you" in brief)

    w, log, a = setup()
    obs = O.observe(w, log, a, "reevaluation")
    ok("observation omits the NPC price table", "npc_prices" not in obs)
    ok("observation omits blanket prices", "prices" not in obs)


def test_player_prices_appear_only_when_they_deviate():
    from convoy import economy as E

    w, log, a = setup()
    rival = Business(
        id="B0002", type="Tavern / Inn", name="Rival Store", owner="A0002",
        location="Kiln Row",
    )
    w.businesses[rival.id] = rival

    rival.retail_prices = {"Iron": E.npc_sell_price("Iron")}
    obs = O.observe(w, log, a, "reevaluation")
    ok("matching NPC price is not reported", "player_prices_here" not in obs)

    rival.retail_prices = {"Iron": E.npc_sell_price("Iron") * 0.7}
    obs = O.observe(w, log, a, "reevaluation")
    ok("undercutting price is reported", "player_prices_here" in obs)


def test_stolen_goods_never_appear_as_inventory():
    w, log, a = setup()
    a.add_stolen("Bronze", 6)
    obs = O.observe(w, log, a, "reevaluation")

    ok("stolen not in carrying", "Bronze" not in obs["you"]["carrying"])
    check("stolen reported separately", obs["you"]["stolen_uncured"], {"Bronze": 6})
    ok(
        "affordances flag the cure requirement",
        any("safehouse" in line for line in obs["you_can"]),
    )


def test_memory_prefers_events_over_diaries():
    """An idle agent writes the same diary hourly; it must not evict real history."""
    w, log, a = setup()
    for h in range(12):
        log.emit(h * HOUR, "diary", actor=a.id, text="idling at Kiln Row")
    log.emit(13 * HOUR, "business_founded", actor=a.id, business_type="Farm")
    log.emit(14 * HOUR, "vehicle_purchased", actor=a.id, vehicle_type="Donkey Cart")

    mem = O.memory_for(log, a, w.sim_time, limit=15)
    ok("real events survive", any("business_founded" in m for m in mem))
    ok("purchase survives", any("vehicle_purchased" in m for m in mem))

    diary_lines = [m for m in mem if "diary" in m]
    check("repeated diaries collapse to one line", len(diary_lines), 1)
    ok("collapsed line is counted", "x" in diary_lines[0].split("(")[-1])


def test_memory_excludes_engine_bookkeeping():
    w, log, a = setup()
    log.emit(1 * HOUR, "sim_start", actor=None)
    log.emit(2 * HOUR, "hired", actor=a.id, role="Miner")
    mem = O.memory_for(log, a, w.sim_time, limit=15)

    ok("sim_start hidden", not any("sim_start" in m for m in mem))
    ok("real event kept", any("hired" in m for m in mem))


def test_memory_carries_recent_public_news_only():
    """A death is news for an hour; a stale one is not."""
    w, log, a = setup()
    log.emit(1 * HOUR, "agent_died", actor="A0099", location="The Climb")     # stale
    log.emit(w.sim_time - 600, "heist_success", actor="A0098", location="The Hills")

    mem = O.memory_for(log, a, w.sim_time, limit=15)
    ok("fresh public news included", any("heist_success" in m for m in mem))
    ok("stale public news dropped", not any("agent_died" in m for m in mem))


def test_memory_respects_limit_and_ordering():
    w, log, a = setup()
    for h in range(40):
        log.emit(h * 600.0, "hired", actor=a.id, role=f"Role{h}")
    mem = O.memory_for(log, a, w.sim_time, limit=15)

    check("limit honoured", len(mem) <= 15, True)
    ok("most recent kept", any("Role39" in m for m in mem))
    ok("oldest dropped", not any("Role0 " in m for m in mem))


def test_affordances_track_the_ground_underfoot():
    w, log, a = setup()

    a.location = "Kiln Row"                      # spur, off protected Town
    lines = O.observe(w, log, a, "reevaluation")["you_can"]
    ok("spur land offered", any("spur land" in x for x in lines))
    ok("protected spur is not flagged unsafe", not any("attacked" in x for x in lines))

    a.location = "The Hills"                     # main road, unprotected
    lines = O.observe(w, log, a, "reevaluation")["you_can"]
    # The line must say mines/farms need spur land AND name what could be founded
    # here instead. Stating only the prohibition read as "you cannot build", and
    # agents with ample money never tried.
    ok("main road explains the spur rule", any("need spur land" in x for x in lines))
    ok("main road still points somewhere", any("found" in x for x in lines))
    ok("danger flagged", any("attacked" in x for x in lines))


def test_travelling_agent_is_told_it_cannot_act():
    w, log, a = setup()
    a.in_transit = ("Town", "Refinery Row", 0.4)
    a.activity.kind = "travel"
    a.activity.ends_at = w.sim_time + 120.0

    lines = O.observe(w, log, a, "reevaluation")["you_can"]
    check("only the transit line is offered", len(lines), 1)
    ok("transit explained", "cannot trade or work" in lines[0])


def test_here_lists_are_bounded():
    """A crowded junction must not blow up the payload."""
    w, log, a = setup()
    for i in range(40):
        extra = Agent(id=f"A1{i:03d}", name=f"Crowd-{i}", model="rb", location="Kiln Row")
        w.agents[extra.id] = extra

    obs = O.observe(w, log, a, "reevaluation")
    others = 40 + 1              # the crowd, plus the neighbour setup() places
    check("agent list capped", len(obs["here"]["agents"]), O.HERE_LIMIT)
    check("overflow counted", obs["here"]["more_agents"], others - O.HERE_LIMIT)


def test_reason_leads_the_payload():
    w, log, a = setup()
    obs = O.observe(w, log, a, "convoy_ambushed")
    check("reason carried", obs["woken_because"], "convoy_ambushed")
    ok("reason leads the render", "convoy_ambushed" in O.render(obs).splitlines()[0])


def test_current_tax_rates_are_dynamic():
    w, log, a = setup()
    w.government.road_tax = 0.025
    obs = O.observe(w, log, a, "reevaluation")
    check("road tax reflects policy", obs["taxes_now"]["road_daily"], 0.025)


def test_golden_render():
    """Snapshot, so prompt changes show up as a diff instead of drifting silently."""
    w, log, a = setup()
    log.emit(18 * HOUR, "hired", actor=a.id, role="Farmhand", wage=12.0)
    log.emit(19 * HOUR, "business_founded", actor=a.id, business_type="Farm", cost=300)
    rendered = O.render(O.observe(w, log, a, "reevaluation"))

    if not GOLDEN.exists():
        GOLDEN.write_text(rendered, encoding="utf-8")
        print(f"  (wrote new golden file {GOLDEN.name})")
        return
    expected = GOLDEN.read_text(encoding="utf-8")
    if rendered != expected:
        FAILURES.append(
            f"golden render drifted -- review the diff, then delete {GOLDEN.name} "
            f"to re-baseline if the change is intended"
        )
        for i, (got, want) in enumerate(
            zip(rendered.splitlines(), expected.splitlines())
        ):
            if got != want:
                FAILURES.append(f"  line {i + 1}: got {got!r} want {want!r}")
                break


def test_payload_stays_within_budget():
    """Guards the cost model the tier decision was made on."""
    w, log, a = setup()
    brief = O.static_briefing()
    rendered = O.render(O.observe(w, log, a, "reevaluation"))

    # Raised from 4,000 to 4,400 on 2026-08-14. The briefing grew from 3,425 by
    # ~575 tokens, and every addition was a fix for a measured failure in the
    # live runs: business locations (agents ate in a Town with no tavern), the
    # role table (9 of 13 job applications rejected), and the wage table
    # (everyone took the lowest-paid role in the world without knowing it).
    # Measured cache hit rate is 96-97%, so the marginal cost of the extra
    # tokens is roughly 4% of them -- about 23 tokens per call. The guard is
    # still here to catch drift, just calibrated to what the briefing now does.
    # 4,400 -> 4,800 on 2026-08-15. Four refined goods (Lumber, Seasoned
    # Hardwood, Cut Stone, Fired Brick) were added so that nothing reaches a
    # workshop without passing a refinery, and each one costs a price-table row
    # and a recipe line. The designer accepted the token cost explicitly. Still
    # a guard against drift, just at the size the briefing now is.
    # 4,800 -> 5,000 on 2026-08-16, for the job board and the one-way chain rule.
    # Both are things the briefing MUST carry: a player job advert is invisible
    # unless agents know post_job/apply_to_job exist, and the chain rule now
    # refuses purchases, so an agent that does not know it will be refused. The
    # 2026-08-16 run is the argument -- four taverns spent 156 denari on Dirty
    # Water that the rule now forbids outright.
    ok(
        "briefing under 5k tokens",
        len(brief) // 4 < 5000,
        f"~{len(brief) // 4} tokens",
    )
    ok(
        "observation under 2k tokens",
        len(rendered) // 4 < 2000,
        f"~{len(rendered) // 4} tokens",
    )


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
    print(f"\nOK -- {len(tests)} observation tests passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
