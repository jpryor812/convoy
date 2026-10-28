#!/usr/bin/env python3
"""Outposts: nobody starts in a town.

Designer decision, 2026-10-27 (GAME_MODES.md, "Next: outposts and towns").
Everyone settles on open land around the state's trading posts; land costs
more beside people; the state lends to settle somewhere dear; food comes from
taverns, walked to or brought; the state buys at half the price between
players and sends its convoy to collect.
"""

from __future__ import annotations

import math
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from convoy import actions as A
from convoy import claims as CL
from convoy import economy as E
from convoy import observe as O
from convoy import reflexes as RX
from convoy import town as TOWN
from convoy import world_map as M
from convoy.engine import Engine, EngineConfig
from convoy.events import EventLog
from convoy.state import Transaction
from convoy.world_setup import new_world

FAILURES: list[str] = []


def ok(label, condition, detail="") -> None:
    if not condition:
        FAILURES.append(f"{label}{': ' + detail if detail else ''}")


class Idle:
    def decide(self, world, agent, reason) -> None:
        return None


class _S:
    model = "x/rule-based"
    cities = {"aldermarch": 6, "cinderhold": 6, "thornwick": 6}


def _world(seed: int = 7):
    log = EventLog(None, echo_min=99)
    world = new_world(log, [], TOWN._rosters(_S), government=False, starter_sites=True)
    world.land_seed = seed
    TOWN.populate_outposts(world, log, random.Random(seed))
    return world, log


def _open_spot(world, rng, near, far, city="aldermarch"):
    ax, ay = CL.anchors(world)[city]
    return CL.sample_sites(world, ax, ay, rng, n=1, near=near, far=far)[0]


def test_land_is_dear_near_the_anchors_and_cheap_far_out() -> None:
    world, _ = _world()
    rng = random.Random(1)
    near = _open_spot(world, rng, 130, 200)
    far = _open_spot(world, rng, 1000, 1100)
    pn, pf = CL.land_price(world, *near), CL.land_price(world, *far)
    ok("a plot by an anchor costs more than one far out", pn > pf * 2, f"{pn} vs {pf}")
    ok("far out it costs near the floor", pf < CL.LAND_FLOOR + 10, str(pf))
    world.outposts = False
    ok("worlds without outposts charge nothing for land", CL.land_price(world, *near) == 0.0)


def test_built_land_raises_the_price_nearby() -> None:
    world, log = _world()
    rng = random.Random(2)
    x, y = _open_spot(world, rng, 1000, 1100)
    before = CL.land_price(world, x, y)
    a = next(iter(world.agents.values()))
    a.denari = 10_000
    for i in range(6):
        for _ in range(20):
            ang = rng.uniform(0, 2 * math.pi)
            px, py = x + 200 * math.cos(ang), y + 200 * math.sin(ang)
            if not CL.check(world, px, py):
                break
        a.home = ""
        CL.settle(world, log, a, px, py)
    after = CL.land_price(world, x, y)
    ok("land beside new homes costs more", after > before, f"{before} -> {after}")


def test_everyone_settles_spread_over_the_anchors() -> None:
    world, _ = _world()
    homes = [a.home for a in world.agents.values()]
    ok("every agent has a home", all(homes), str(homes))
    ok("no two share one", len(set(homes)) == len(homes))
    by_city = {c: sum(1 for a in world.agents.values() if a.city == c) for c in world.cities}
    ok("each anchor has its settlers", all(n == 6 for n in by_city.values()), str(by_city))
    for a in world.agents.values():
        c = world.claims[a.home]
        home_plots = [p for p in world.plots.values() if p.location == a.home and p.owner == a.id and p.home]
        ok(f"{a.name} lives there", a.location == a.home and len(home_plots) == M.CLAIM_PLOTS)
        for b in world.claims.values():
            if b is not c:
                ok("claims do not overlap", math.hypot(b.x - c.x, b.y - c.y) >= CL.MIN_FROM_CLAIM - 1e-6)
    ok("only the state owns businesses at hour zero",
       all(b.is_government for b in world.businesses.values()))


def test_settling_somewhere_dear_borrows_from_the_state() -> None:
    world, log = _world()
    a = next(iter(world.agents.values()))
    a.home = ""
    a.denari = 20.0
    x, y = _open_spot(world, random.Random(3), 130, 200)
    q = CL.quote(world, x, y)
    okb, msg, _ = CL.settle(world, log, a, x, y)
    ok("without a loan it is refused", not okb and "borrow" in msg, msg)
    need = q["total"] - a.denari
    okb, msg, _ = CL.settle(world, log, a, x, y, borrow=need + 1)
    ok("with one it is allowed", okb, msg)
    ok("and the debt is recorded", abs(a.debt - round(need + 1, 2)) < 0.01, str(a.debt))
    okb, _, _ = CL.settle(world, log, a, x + 300, y)
    ok("you settle once", not okb)


def test_land_counts_at_cost_and_debt_against_you() -> None:
    world, log = _world()
    a = next(iter(world.agents.values()))
    a.home = ""
    for v in a.owned_vehicles:
        world.vehicles[v].location = "Town"
    x, y = _open_spot(world, random.Random(6), 130, 200)
    before = a.net_worth(world) - a.land_value(world)
    q = CL.quote(world, x, y)
    okb, msg, _ = CL.settle(world, log, a, x, y, borrow=100.0)
    ok("settled", okb, msg)
    ok("the land is worth what it cost", abs(a.land_value(world) - sum(
        p.paid for p in world.plots.values() if p.owner == a.id)) < 0.01)
    new_land = sum(p.paid for p in world.plots.values() if p.location == a.home)
    ok("the new claim is valued at its price", abs(new_land - q["total"]) < 0.05, f"{new_land} vs {q['total']}")
    after = a.net_worth(world) - (a.land_value(world) - new_land)
    ok("buying land and borrowing leaves worth where it was", abs(after - before) < 0.05, f"{before} -> {after}")
    ok("the donkey moves in too", all(world.vehicles[v].location == a.home for v in a.owned_vehicles))


def test_debt_grows_and_is_paid_from_earnings() -> None:
    world, log = _world()
    a = next(iter(world.agents.values()))
    a.debt = 100.0
    eng = Engine(world, log, Idle(), EngineConfig(speed=1e9))
    eng._debt_interest(24.0)
    ok("it grows 2% a day", abs(a.debt - 102.0) < 0.01, str(a.debt))
    cash = a.denari
    A._income(world, type("B", (), {"owner": a.id, "is_government": False, "cash": 0.0})(), 50.0)
    ok("a fifth of what you earn pays it down", abs(a.debt - 92.0) < 0.01 and abs(a.denari - cash - 40.0) < 0.01,
       f"debt {a.debt}, got {a.denari - cash}")
    okb, _ = A.repay_debt(world, log, a)
    ok("and you can pay the rest", okb and a.debt == 0.0, str(a.debt))
    eng.close()


def test_a_claim_is_its_claimants_land() -> None:
    world, log = _world()
    a, b = list(world.agents.values())[:2]
    a.denari = b.denari = 2000.0
    x, y = _open_spot(world, random.Random(4), 600, 800)
    okc, msg, c = CL.claim(world, log, a, x, y, "Farm")
    ok("claimed", okc, msg)
    b.location = c.name
    okb, msg = A.start_business(world, log, b, "Farm")
    ok("someone else cannot found on it", not okb and "land" in msg, msg)
    a.location = c.name
    okb, msg = A.start_business(world, log, a, "Farm")
    ok("its claimant can", okb, msg)
    farm = world.businesses[a.owned_businesses[-1]]
    on = [p for p in world.plots.values() if p.business == farm.id]
    ok("on the claim's own four plots", len(on) == 4 and all(p.owner == a.id for p in on))
    ok("and no new plots were made there",
       sum(1 for p in world.plots.values() if p.location == c.name) == M.CLAIM_PLOTS)


def test_agents_can_claim_from_what_they_are_shown() -> None:
    world, log = _world()
    a = next(iter(world.agents.values()))
    a.denari = 2000.0
    obs = O.observe(world, log, a, "x", record_delivery=False)
    sites = obs.get("open_land_near_you") or []
    ok("an agent is shown open land", len(sites) >= 3, str(sites))
    text = O.render(obs)
    ok("and its outpost", "YOUR OUTPOST" in text and a.home in text)
    okc, msg = A.claim_land(world, log, a, sites[0]["site_id"], "Farm")
    ok("claim_land takes a listed site", okc, msg)
    okc, msg = A.claim_land(world, log, a, "nonsense", "")
    ok("and refuses an invented one", not okc)


def test_the_state_pays_half_the_price_between_players() -> None:
    world, log = _world()
    item = "Wheat"
    ok("with no trades, half of book", E.state_price(world, item) == round(E.D.base_price(item) * 0.5, 2))
    a, b = list(world.agents.values())[:2]
    world.market.record(Transaction(world.sim_time, item, 10, 8.0, a.id, b.id))
    world.market.record(Transaction(world.sim_time, item, 10, 12.0, a.id, b.id))
    gov = next(x for x in world.businesses.values() if x.is_government)
    world.market.record(Transaction(world.sim_time, item, 100, 1.0, a.id, gov.id))
    ok("half the players' average, ignoring the state's own buying", E.state_price(world, item) == 5.0,
       str(E.state_price(world, item)))
    world.sim_time += 25 * 3600.0
    ok("a day later it forgets", E.state_price(world, item) == round(E.D.base_price(item) * 0.5, 2))


def test_the_states_convoy_pays_when_it_collects() -> None:
    world, log = _world()
    a = next(iter(world.agents.values()))
    a.denari = 2000.0
    x, y = _open_spot(world, random.Random(5), 600, 900)
    _, _, c = CL.claim(world, log, a, x, y, "Farm")
    a.location = c.name
    A.start_business(world, log, a, "Farm")
    farm = world.businesses[a.owned_businesses[-1]]
    farm.add_item("Wheat", 10)
    state = next(b for b in world.businesses.values() if b.is_government and b.type == "Refinery")
    cash = a.denari
    okb, msg = A.sell_to_bidder(world, log, a, farm.id, state.id, "Wheat", 10)
    ok("the convoy is called", okb and "convoy" in msg, msg)
    ok("the goods leave the yard", farm.inventory.get("Wheat", 0) == 0)
    ok("nothing is paid yet", a.denari == cash)
    eng = Engine(world, log, Idle(), EngineConfig(speed=1e9))
    d = next(iter(world.dispatches.values()))
    world.sim_time = d.arrives_at + 1
    eng._dispatches()
    ok("paid on collection, with no fee", abs(a.denari - cash - d.unit_price * 10) < 0.01,
       f"{a.denari - cash} vs {d.unit_price * 10}")
    ok("and the sale is in the price feed", any(t.seller == farm.id and t.item == "Wheat"
                                                for t in world.market.transactions))
    eng.close()


def test_a_meal_is_brought_and_eaten_when_hungry() -> None:
    world, log = _world()
    a = next(iter(world.agents.values()))
    a.denari = 200.0
    tavern = next(b for b in world.businesses.values() if b.is_government and b.type == "Tavern / Inn")
    okb, msg = A.order_meal(world, log, a, tavern.id)
    ok("ordered", okb, msg)
    d = next(iter(world.dispatches.values()))
    ok("it costs the meal and a fee", d.fee > 0)
    ok("it takes time to come", d.arrives_at > world.sim_time)
    eng = Engine(world, log, Idle(), EngineConfig(speed=1e9))
    world.sim_time = d.arrives_at + 1
    eng._dispatches()
    ok("it arrives in what you carry", a.inventory.get(d.item, 0) == 1)
    a.sustenance_stage = "Hungry"
    ok("and is eaten when hungry", RX._eat(world, log, a) and a.inventory.get(d.item, 0) == 0)
    eng.close()


def test_a_hungry_agent_away_from_a_tavern_sends_for_one() -> None:
    world, log = _world()
    a = next(iter(world.agents.values()))
    a.denari = 200.0
    a.sustenance_stage = "Hungry"
    ok("it orders", RX._eat(world, log, a))
    ok("one meal on the way", sum(1 for d in world.dispatches.values() if d.agent == a.id) == 1)
    ok("and not a second", not RX._eat(world, log, a))


def main() -> int:
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for t in tests:
        t()
    print(f"test_outposts.py: {len(tests)} tests, {len(FAILURES)} failures")
    for f in FAILURES:
        print(f"  FAIL {f}")
    return 1 if FAILURES else 0


if __name__ == "__main__":
    raise SystemExit(main())
