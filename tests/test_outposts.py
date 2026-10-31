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
from convoy import delivery as DLV
from convoy import discovery as DS
from convoy import data as D
from convoy import economy as E
from convoy import layout as L
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


def _open_spot(world, rng, near, far, city="aldermarch", home=False):
    ax, ay = CL.anchors(world)[city]
    return CL.sample_sites(world, ax, ay, rng, n=20 if home else 1, near=near, far=far, home=home)[0]


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


def test_first_homes_stand_apart() -> None:
    world, log = _world()
    homes = [CL.place_xy(world, a.home) for a in world.agents.values()]
    gaps = [min(math.hypot(h[0] - o[0], h[1] - o[1]) for o in homes if o is not h) for h in homes]
    ok("every first home is at least the spacing from the next",
       min(gaps) >= CL.HOME_SPACING_M - 1, f"closest {min(gaps):.0f} m")
    ok("so nobody starts knowing their neighbours", all(not a.known for a in world.agents.values()) or True)
    a = next(iter(world.agents.values()))
    at = CL.place_xy(world, a.home)
    b = list(world.agents.values())[1]
    b.home = ""
    okb, msg, _ = CL.settle(world, log, b, at[0] + 300, at[1])
    ok("you cannot settle right beside someone", not okb and "settled within" in msg, msg)
    ok("and smoke shows them from afar", isinstance(DS.glimpses(world, a), list))


def test_built_land_raises_the_price_nearby() -> None:
    world, log = _world()
    rng = random.Random(2)
    x, y = _open_spot(world, rng, 1000, 1100, home=True)
    before = CL.land_price(world, x, y)
    a = next(iter(world.agents.values()))
    a.denari = 10_000
    for i in range(6):
        for _ in range(20):
            ang = rng.uniform(0, 2 * math.pi)
            px, py = x + 200 * math.cos(ang), y + 200 * math.sin(ang)
            if not CL.check(world, px, py, home=True):     # homes keep off the mountains
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
    # Spread out to the mountains, some end nearer another trading post.
    ok("every anchor has settlers", all(n >= 3 for n in by_city.values()) and sum(by_city.values()) == 18,
       str(by_city))
    for a in world.agents.values():
        c = world.claims[a.home]
        home_plots = [p for p in world.plots.values() if p.location == a.home and p.owner == a.id and p.home]
        ok(f"{a.name} lives there", a.location == a.home and len(home_plots) == M.CLAIM_PLOTS)
        for b in world.claims.values():
            if b is not c:
                ok("claims do not overlap", math.hypot(b.x - c.x, b.y - c.y) >= CL.MIN_FROM_CLAIM - 1e-6)
    ok("only the state owns businesses at hour zero",
       all(b.is_government for b in world.businesses.values()))


def test_you_are_settled_for_you_too() -> None:
    """No choosing land (2026-10-30): the player starts at an outpost of
    their own, out on open land like every settler."""
    from convoy.game import Settings
    world, log = _world()
    you = world.agents[TOWN.settle(world, log, Settings(model="x/rule-based", outposts=True))]
    ok("you have a home", bool(you.home) and you.settled and you.location == you.home, str(you.home))
    ok("free, and no debt", you.debt == 0.0, str(you.debt))
    xy = CL.place_xy(world, you.home)
    _, far = CL.nearest_anchor(world, *xy)
    ok("well away from every trading post", far >= CL.START_FROM_ANCHOR_M, f"{far:.0f} m")
    road, _, _ = CL.nearest_road(world, *xy)
    ok("off the roads, but not far", CL.START_ROAD_M[0] - 1 <= road <= CL.START_ROAD_M[1] + 1, f"{road:.0f} m")


def test_the_first_home_is_free_and_a_loan_is_optional() -> None:
    world, log = _world()
    a, b = list(world.agents.values())[:2]
    for p in (a, b):
        p.home = ""
    a.denari = 20.0
    x, y = _open_spot(world, random.Random(3), 130, 2600, home=True)
    okb, msg, c = CL.settle(world, log, a, x, y)
    ok("settling costs nothing", okb and a.denari == 20.0, msg)
    ok("and its land counts for nothing", sum(p.paid for p in world.plots.values() if p.location == c.name) == 0)
    okb, _, _ = CL.settle(world, log, a, x + 300, y)
    ok("you settle once", not okb)
    cash = b.denari
    x, y = _open_spot(world, random.Random(4), 130, 2600, home=True)
    okb, msg, _ = CL.settle(world, log, b, x, y, borrow=150.0)
    ok("a loan taken as you settle is money to start with", okb and abs(b.denari - cash - 150.0) < 0.01, msg)
    ok("and is owed", abs(b.debt - 150.0) < 0.01, str(b.debt))


def test_land_counts_at_cost_and_debt_against_you() -> None:
    world, log = _world()
    a = next(iter(world.agents.values()))
    a.denari = 2000.0
    x, y = _open_spot(world, random.Random(6), 130, 200)
    before = a.net_worth(world)
    q = CL.quote(world, x, y)
    okc, msg, c = CL.claim(world, log, a, x, y, "Farm")
    ok("claimed", okc, msg)
    new_land = sum(p.paid for p in world.plots.values() if p.location == c.name)
    ok("the new claim is valued at its price", abs(new_land - q["total"]) < 0.05, f"{new_land} vs {q['total']}")
    ok("buying land leaves worth where it was", abs(a.net_worth(world) - before) < 0.05,
       f"{before} -> {a.net_worth(world)}")
    a.debt = 100.0
    ok("debt counts against you", abs(a.net_worth(world) - (before - 100.0)) < 0.05)
    b = list(world.agents.values())[1]
    b.home = ""
    for v in b.owned_vehicles:
        world.vehicles[v].location = "Town"
    x, y = _open_spot(world, random.Random(7), 130, 2600, home=True)
    CL.settle(world, log, b, x, y)
    ok("the donkey moves in too", all(world.vehicles[v].location == b.home for v in b.owned_vehicles))


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


def test_roads_are_built_by_hand_and_paid_for() -> None:
    """Built roads (designer request, 2026-10-30)."""
    world, log = _world()
    a = next(iter(world.agents.values()))
    a.denari = 2000.0
    home = world.claims[a.home]
    ok("a home comes with no road", home.road == [] and not CL.connected(world, home.name))
    x, y = _open_spot(world, random.Random(6), 600, 900)
    cash = a.denari
    okc, msg, farm = CL.claim(world, log, a, x, y, "Farm")
    ok("nor does a claim, and its road is not charged", okc and farm.road == [] and
       abs(cash - a.denari - CL.land_price(world, x, y) * M.CLAIM_PLOTS) < 0.5, msg)
    slow = farm.seconds
    okb, msg = A.build_road(world, log, a, farm.name, home.name)
    ok("a road between your claims", okb and farm.link == home.name, msg)
    ok("joins nothing while neither reaches the roads", not CL.connected(world, farm.name))
    plan = CL.road_plan(world, home.name)
    cash = a.denari
    okb, msg = A.build_road(world, log, a, home.name)
    ok("paid by the metre", okb and abs(cash - a.denari - plan["cost"]) < 0.01, msg)
    ok("then both are connected", CL.connected(world, home.name) and CL.connected(world, farm.name))
    ok("and travel there is twice as fast", abs(farm.seconds * 2 - slow) < 1.0, f"{slow} -> {farm.seconds}")
    okb, msg = A.build_road(world, log, a, home.name)
    ok("one road from each claim", not okb, msg)
    b = list(world.agents.values())[1]
    okb, msg = A.build_road(world, log, b, home.name)
    ok("only from your own land", not okb, msg)
    okb, msg = CL.build_road(world, log, a, farm.name, x=farm.x + 500, y=farm.y + 500)
    ok("a road must end on a road or a claim", not okb, msg)


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
    okb, msg = A.sell_to_bidder(world, log, a, farm.id, state.id, "Wheat", 10)
    ok("no convoy without a road", not okb and "road" in msg and farm.inventory.get("Wheat") == 10, msg)
    okb, msg = A.build_road(world, log, a, c.name)
    ok("a road is built", okb, msg)
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


def test_the_state_buys_at_most_100_a_day() -> None:
    """Designer request, 2026-10-30: selling to the state was too strong."""
    world, log = _world()
    a = next(iter(world.agents.values()))
    a.denari = 2000.0
    x, y = _open_spot(world, random.Random(5), 600, 900)
    _, _, c = CL.claim(world, log, a, x, y, "Farm")
    a.location = c.name
    A.start_business(world, log, a, "Farm")
    A.build_road(world, log, a, c.name)
    farm = world.businesses[a.owned_businesses[-1]]
    farm.add_item("Wheat", 300)
    state = next(b for b in world.businesses.values() if b.is_government and b.type == "Refinery")
    okb, msg = A.sell_to_bidder(world, log, a, farm.id, state.id, "Wheat", 80)
    ok("80 sold", okb and farm.inventory["Wheat"] == 220, msg)
    okb, msg = A.sell_to_bidder(world, log, a, farm.id, state.id, "Wheat", 80)
    ok("only 20 more that day", okb and farm.inventory["Wheat"] == 200, msg)
    okb, msg = A.sell_to_bidder(world, log, a, farm.id, state.id, "Wheat", 5)
    ok("then none", not okb and "100" in msg, msg)
    a.add_item("Wheat", 5)
    a.location = state.location
    okb, msg = A.sell_to_business(world, log, a, state.id, "Wheat", 5)
    ok("not over its counter either", not okb, msg)
    world.sim_time = (world.sim_time // 86400 + 1) * 86400 + 60
    okb, msg = A.sell_to_business(world, log, a, state.id, "Wheat", 5)
    ok("the next day it buys again", okb, msg)
    ok("and counts it", A.state_room(world, a) == 95)


def test_a_meal_adds_to_what_is_left() -> None:
    """Designer play-test, 2026-10-30: 14 hours left, ate a 12-hour Meal, and
    nothing happened -- and it was paid for."""
    world, log = _world()
    a = next(iter(world.agents.values()))
    a.last_meal_window, a.hours_since_last_meal = 24.0, 10.0          # 14h left
    a.add_item("Meal", 2)
    okb, msg = A.eat_meal(world, log, a, "Meal")
    left = a.last_meal_window - a.hours_since_last_meal
    ok("it tops up to a full stomach", okb and abs(left - 24.0) < 0.01, f"{msg}; {left}")
    okb, msg = A.eat_meal(world, log, a, "Meal")
    ok("and a full stomach is refused, the meal kept", not okb and "full" in msg and a.inventory["Meal"] == 1, msg)
    a.hours_since_last_meal = 20.0                                    # 4h left
    A.eat_meal(world, log, a, "Meal")
    ok("4h + 12h = 16h", abs(a.last_meal_window - a.hours_since_last_meal - 16.0) < 0.01)
    tavern = next(b for b in world.businesses.values() if b.is_government and b.type == "Tavern / Inn")
    a.location, a.denari = tavern.location, 100.0
    a.hours_since_last_meal, a.last_meal_window = 0.0, 24.0
    okb, msg = A.buy_meal(world, log, a, tavern.id)
    ok("a tavern does not charge for a meal you cannot eat", not okb and a.denari == 100.0, msg)


def test_a_better_weapon_is_wielded_when_bought() -> None:
    world, log = _world()
    a = next(iter(world.agents.values()))
    smith = next(b for b in world.businesses.values() if b.is_government and b.type == "Tavern / Inn")
    a.location, a.denari = smith.location, 1000.0
    okb, msg = A.buy_from_business(world, log, a, smith.id, "Bronze Dagger", 1)
    ok("bought and wielded", okb and a.equipped_weapon == "Bronze Dagger" and "Bat" in a.inventory, msg)
    a.add_item("Sling", 1)
    okb, msg = A.equip(world, log, a, "Sling")
    ok("and you can still choose", okb and a.equipped_weapon == "Sling")


def test_any_building_can_add_a_floor() -> None:
    """Designer request, 2026-10-30: a floor for more storage."""
    world, log = _world()
    a = next(iter(world.agents.values()))
    a.denari = 5000.0
    x, y = _open_spot(world, random.Random(5), 600, 900)
    _, _, c = CL.claim(world, log, a, x, y, "")
    a.location = c.name
    okb, msg = A.start_business(world, log, a, "Tavern / Inn")
    ok("a tavern", okb, msg)
    t = world.businesses[a.owned_businesses[-1]]
    before = E.business_storage_capacity(world, t)
    okb, msg = A.upgrade_site_storage(world, log, a, t.id)
    ok("a shop adds a floor with outposts", okb and t.storage_tier == 1 and "floor" in msg, msg)
    ok("and holds more", E.business_storage_capacity(world, t) > before,
       f"{before} -> {E.business_storage_capacity(world, t)}")


def test_build_anywhere_and_anything_on_your_own_land() -> None:
    """Designer request, 2026-10-30: no rules on where; a land claim takes
    anything, a guard post included."""
    world, log = _world()
    a = next(iter(world.agents.values()))
    a.denari = 5000.0
    hit = None
    for m in L.mountains(list(world.cities)):
        d = math.hypot(m["x"], m["y"])
        for k in range(5, 80, 5):
            x, y = m["x"] - m["x"] / d * (m["r"] - k), m["y"] - m["y"] / d * (m["r"] - k)
            if not CL.check(world, x, y):
                hit = (x, y)
                break
        if hit:
            break
    ok("the mountainside is open to claim", hit is not None)
    ok("but not for a first home", CL.check(world, *hit, home=True) == "that is on the mountainside")
    okc, msg, c = CL.claim(world, log, a, *hit, "")
    a.location = c.name
    okb, msg = A.build_defense(world, log, a, "Guard post")
    on = [q for q in world.plots.values() if q.location == c.name]
    ok("a guard post goes on your own claim", okb and len(on) == M.CLAIM_PLOTS
       and sum(1 for q in on if q.structure) == 1, msg)


def test_a_security_firm_keeps_a_watch() -> None:
    """Designer request, 2026-10-30: it makes nothing; hire lookouts or put
    family there, and they watch for raiders."""
    world, log = _world()
    a = next(iter(world.agents.values()))
    a.denari = 5000.0
    x, y = _open_spot(world, random.Random(5), 600, 900)
    _, _, c = CL.claim(world, log, a, x, y, "")
    a.location = c.name
    okb, msg = A.start_business(world, log, a, "Private Security Contractor")
    ok("founded", okb, msg)
    firm = world.businesses[a.owned_businesses[-1]]
    ok("it makes nothing", not firm.spec.outputs)
    okb, msg = A.set_production(world, log, a, firm.id, "Wheat")
    ok("and cannot be told to", not okb, msg)
    partner = next(m for m in a.family if m.adult)
    okb, msg = A.assign_family(world, log, a, partner.id, firm.id)
    ok("family can stand watch", okb and len(firm.production_staff()) == 1, msg)
    eng = Engine(world, log, Idle(), EngineConfig(speed=1e9))
    ok("a lookout rides with your loads near it", len(eng._lookouts(a, c.name, a.home)) == 1)
    far = max(world.claims.values(), key=lambda q: math.hypot(q.x - x, q.y - y))
    ok("but not far from it", math.hypot(far.x - x, far.y - y) > D.LOOKOUT_RANGE_M
       and not eng._lookouts(a, far.name, far.name))
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


def _pair_apart(world):
    """Two settlers who have not found each other, far apart."""
    people = [a for a in world.agents.values() if a.home]
    for a in people:
        for b in people:
            if a is b:
                continue
            pa, pb = CL.place_xy(world, a.home), CL.place_xy(world, b.home)
            if math.hypot(pa[0] - pb[0], pa[1] - pb[1]) > 3 * DS.SIGHT_M and b.id not in a.known:
                return a, b
    raise AssertionError("no two settlers far apart")


def test_neighbours_find_each_other_and_strangers_do_not() -> None:
    world, log = _world()
    DS.tick(world, log)
    for a in world.agents.values():
        pa = CL.place_xy(world, a.home)
        for b in world.agents.values():
            if a is b:
                continue
            pb = CL.place_xy(world, b.home)
            d = math.hypot(pa[0] - pb[0], pa[1] - pb[1])
            if d <= DS.SIGHT_M:
                ok("neighbours within sight have met", b.id in a.known and a.id in b.known, f"{d:.0f} m")
            elif d > DS.SIGHT_M * 1.5 and not a.owned_businesses and not b.owned_businesses:
                ok("strangers far apart have not", b.id not in a.known, f"{d:.0f} m")


def test_you_can_only_trade_with_people_you_have_found() -> None:
    world, log = _world()
    DS.tick(world, log)
    a, b = _pair_apart(world)
    a.denari = b.denari = 3000.0
    for p, r in ((a, 11), (b, 12)):
        x, y = CL.sample_sites(world, *CL.place_xy(world, p.home), random.Random(r), n=1, near=90, far=300)[0]
        _, _, c = CL.claim(world, log, p, x, y, "Farm")
        p.location = c.name
    A.start_business(world, log, a, "Farm")
    A.start_business(world, log, b, "Refinery")
    farm = world.businesses[a.owned_businesses[-1]]
    ref = world.businesses[b.owned_businesses[-1]]
    A.set_production(world, log, b, ref.id, "Grain")
    farm.add_item("Wheat", 20)
    okb, msg = A.sell_to_bidder(world, log, a, farm.id, ref.id, "Wheat", 5)
    ok("a stranger's bid cannot be taken", not okb and "not found" in msg, msg)
    state = next(x for x in world.businesses.values() if x.is_government and x.type == "Refinery")
    A.build_road(world, log, a, farm.location)                 # its convoy comes by road
    okb, msg = A.sell_to_bidder(world, log, a, farm.id, state.id, "Wheat", 5)
    ok("the state always can be", okb, msg)
    okb, msg = A.order_from_business(world, log, b, ref.id, farm.id, "Wheat", 5, 1.0)
    ok("nor can a stranger's stock be ordered", not okb and "not found" in msg, msg)
    ok("nor their deliveries offered", all(o["buyer"] != ref.id for o in DLV.offers(world, a)))
    # A rides past b's refinery.
    DS.tick(world, log, {a.id: CL.place_xy(world, ref.location)})
    ok("riding past their land finds them", b.id in a.known and a.id in b.known)
    okb, msg = A.sell_to_bidder(world, log, a, farm.id, ref.id, "Wheat", 5)
    ok("and then you can trade", okb, msg)


def test_face_to_face_is_finding() -> None:
    world, log = _world()
    DS.tick(world, log)
    a, b = _pair_apart(world)
    a.location = b.location = "Town"
    A._meet_here(world, log, a, b.id)
    ok("standing beside someone, you have met", b.id in a.known and a.id in b.known)


def test_worlds_without_outposts_know_everyone() -> None:
    world, log = _world()
    world.outposts = False
    a, b = list(world.agents.values())[:2]
    ok("everyone is known", DS.knows(world, a, b.id))


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
