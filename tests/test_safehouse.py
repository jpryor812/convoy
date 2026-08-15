#!/usr/bin/env python3
"""Stolen goods, safehouses, and the weekly property tax.

The rule that must never silently break: hot goods cannot be sold or traded
until they have sat 24 hours in a safehouse. If that leaked, piracy would have
no cost and homes would lose the purpose this mechanic gives them.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from convoy import actions as A
from convoy import data as D
from convoy.engine import Engine, EngineConfig
from convoy.events import EventLog
from convoy.state import Agent, Property, VehicleInstance, World

FAILURES: list[str] = []
HOUR = 3600.0


def check(label, actual, expected) -> None:
    if actual != expected:
        FAILURES.append(f"{label}: got {actual!r}, expected {expected!r}")


def setup(with_home=True, denari=2000.0):
    w, log = World(), EventLog(None, echo_min=99)
    a = Agent(id="A0001", name="Thief", model="rb", location="Kiln Row")
    a.denari = denari
    w.agents[a.id] = a
    # A cart, so carrying capacity never masks a different failure.
    v = VehicleInstance(id="V1", type="Donkey Cart", owner=a.id, location="Kiln Row")
    w.vehicles["V1"] = v
    a.owned_vehicles.append("V1")
    a.mounted_vehicle = "V1"
    v.mounted_by = a.id
    prop = None
    if with_home:
        prop = Property(id="P1", owner=a.id, location="Kiln Row", plots=4)
        prop.storage_tier = 3          # roomy safehouse, 370 units
        w.properties[prop.id] = prop
        a.owned_property = prop.id
    return w, log, a, prop


def test_hot_goods_are_not_sellable():
    """Stolen goods sit outside inventory, so every sale path refuses them."""
    w, log, a, _p = setup()
    A.receive_stolen(w, log, a, "Iron", 10)
    check("hot goods held apart", a.stolen.get("Iron"), 10)
    check("not in normal inventory", a.inventory.get("Iron", 0), 0)
    check("but they weigh on you", a.carried_units(), 10)

    store = __import__("convoy.state", fromlist=["Business"]).Business(
        id="B1", type="Tavern / Inn", name="Store", owner="Government",
        location="Kiln Row",
    )
    w.businesses["B1"] = store
    ok, _ = A.sell_to_business(w, log, a, "B1", "Iron", 10)
    check("cannot sell hot goods", ok, False)

    buyer = Agent(id="A0002", name="Fence", model="rb", location="Kiln Row")
    buyer.denari = 5000.0
    w.agents[buyer.id] = buyer
    ok, _ = A.offer_trade(w, log, a, buyer.id, {"Iron": 10}, 100.0)
    check("cannot trade hot goods", ok, False)


def test_safehouse_cure_takes_24_hours():
    w, log, a, prop = setup()
    A.receive_stolen(w, log, a, "Iron", 10)
    ok, _ = A.stash_in_safehouse(w, log, a, "Iron", 10)
    check("stashed", ok, True)
    check("off your person", a.stolen.get("Iron", 0), 0)
    check("one stack in the safehouse", len(prop.safehouse), 1)

    ok, msg = A.collect_from_safehouse(w, log, a)
    check("nothing cured immediately", ok, False)

    w.sim_time = 23.9 * HOUR
    ok, _ = A.collect_from_safehouse(w, log, a)
    check("still hot at 23.9h", ok, False)

    w.sim_time = 24.0 * HOUR
    ok, _ = A.collect_from_safehouse(w, log, a)
    check("clean at exactly 24h", ok, True)
    check("now ordinary inventory", a.inventory.get("Iron"), 10)
    check("safehouse emptied", len(prop.safehouse), 0)

    # And now it sells like anything else.
    store = __import__("convoy.state", fromlist=["Business"]).Business(
        id="B1", type="Tavern / Inn", name="Store", owner="Government",
        location="Kiln Row",
    )
    w.businesses["B1"] = store
    ok, _ = A.sell_to_business(w, log, a, "B1", "Iron", 10)
    check("laundered goods sell fine", ok, True)


def test_no_home_means_nowhere_to_launder():
    """A thief without a safehouse holds goods they cannot spend."""
    w, log, a, _p = setup(with_home=False)
    A.receive_stolen(w, log, a, "Bronze", 5)
    ok, msg = A.stash_in_safehouse(w, log, a, "Bronze", 5)
    check("cannot stash without a property", ok, False)
    check("reason names the problem", "no property" in msg, True)
    check("still holding hot goods", a.stolen.get("Bronze"), 5)


def test_must_be_at_your_own_safehouse():
    w, log, a, _p = setup()
    A.receive_stolen(w, log, a, "Iron", 5)
    a.location = "Blindfold Draw"
    ok, _ = A.stash_in_safehouse(w, log, a, "Iron", 5)
    check("must be at the safehouse", ok, False)


def test_hot_goods_drop_on_death_and_stay_hot():
    w, log, a, _p = setup()
    A.receive_stolen(w, log, a, "Iron", 6)
    a.add_item("Grain", 4)
    eng = Engine(w, log, type("N", (), {"decide": lambda *x: None})(),
                 EngineConfig(speed=1e9))
    eng._kill(a, cause="test")
    pile = w.ground_loot["Kiln Row"]
    check("stolen goods dropped too", pile["items"].get("Iron"), 6)
    check("clean goods dropped", pile["items"].get("Grain"), 4)
    check("nothing left on the corpse", a.stolen, {})


def test_property_tax_is_weekly():
    """0.5% per week -- not 5% every 24 hours."""
    check("weekly rate", D.DEFAULT_PROPERTY_TAX, 0.005)
    check("billed weekly", D.PROPERTY_TAX_PERIOD_HOURS, 168.0)
    check("annual equivalent", round(D.PROPERTY_TAX_ANNUAL_EQUIVALENT, 2), 0.26)
    per_bill = D.property_tax_per_bill(D.DEFAULT_PROPERTY_TAX)
    check("per-bill fraction", per_bill, 0.005)
    # A 500 Denari home: 2.50 per weekly bill, not 25 per day.
    check("weekly bill on a 500 home", round(500 * per_bill, 2), 2.50)
    # Policy votes are bounded on the WEEKLY rate, not the old 0-25% daily bound.
    check("policy clamps high", D.property_tax_per_bill(0.25), D.PROPERTY_TAX_MAX)
    check("policy clamps low", D.property_tax_per_bill(-1.0), 0.0)

    w, log, a, prop = setup()
    start = a.denari
    eng = Engine(w, log, type("N", (), {"decide": lambda *x: None})(),
                 EngineConfig(speed=1e9))
    # Run past hour 120: under the old daily rule this cost 125 Denari.
    w.sim_time = 120 * HOUR
    eng._property_tax()
    check("no bill inside a 120-hour run", a.denari, start)

    w.sim_time = 168 * HOUR
    eng._property_tax()
    billed = start - a.denari
    check("first bill lands at hour 168", round(billed, 2),
          round(prop.assessed_value() * per_bill, 2))


def test_road_tax_is_daily_on_net_worth():
    """1% daily public-works levy, funding roads and police."""
    check("daily rate", D.ROAD_TAX_DAILY, 0.01)
    check("billed daily", D.ROAD_TAX_PERIOD_HOURS, 24.0)

    w, log, a, _p = setup(with_home=False, denari=1000.0)
    eng = Engine(w, log, type("N", (), {"decide": lambda *x: None})(),
                 EngineConfig(speed=1e9))
    nw = a.net_worth(w)
    w.sim_time = 24 * HOUR
    eng._road_tax()
    check("charged 1% of net worth", round(1000.0 - a.denari, 2), round(nw * 0.01, 2))
    check("treasury received it", round(w.government.treasury, 2), round(nw * 0.01, 2))

    # Never drives an agent negative -- there is no debt mechanic.
    a.denari = 0.5
    w.sim_time = 48 * HOUR
    eng._road_tax()
    check("cannot go negative", a.denari >= 0, True)


def test_road_policies_move_the_levy_and_the_service():
    """Upgrades cost more per day; reversing restores both rate and service."""
    from convoy.state import Government

    g = Government()
    check("baseline levy", g.road_tax, 0.01)
    check("no police until voted", g.police_tier, 0)

    ok, _ = g.enact("Police Tier 2")
    check("police tiers are cumulative", ok, False)

    g.enact("Police Tier 1")
    check("tier 1 in force", g.police_tier, 1)
    check("levy rose", round(g.road_tax, 4), 0.0125)

    g.enact("Better Roads")
    check("convoys 10% faster", round(g.convoy_speed_modifier, 2), 1.10)
    check("levy rose again", round(g.road_tax, 4), 0.015)

    ok, _ = g.enact("Better Roads")
    check("cannot enact twice", ok, False)

    g.reverse("Better Roads")
    check("speed restored", round(g.convoy_speed_modifier, 2), 1.00)
    check("levy restored", round(g.road_tax, 4), 0.0125)

    # Cutting funding below baseline is allowed, and slows the roads.
    g2 = Government()
    g2.enact("Less Road Funding")
    check("cheaper levy", round(g2.road_tax, 4), 0.0075)
    check("slower roads", round(g2.convoy_speed_modifier, 2), 0.90)

    g3 = Government()
    g3.enact("New Road Project")
    check("second route exists", g3.second_route, True)
    check("and it is expensive", round(g3.road_tax, 4), 0.0175)


def main() -> int:
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for t in tests:
        t()
    print(f"Ran {len(tests)} safehouse/tax tests.")
    if FAILURES:
        print(f"\n{len(FAILURES)} FAILURES:")
        for f in FAILURES:
            print(f"  ! {f}")
        return 1
    print("Hot goods need laundering; property tax weekly; road tax daily.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
