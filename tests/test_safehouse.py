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
        id="B1", type="General Store", name="Store", owner="Government",
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
        id="B1", type="General Store", name="Store", owner="Government",
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


def test_property_tax_is_annual_billed_weekly():
    """5% per year, billed weekly -- not 5% every 24 hours."""
    check("annual rate", D.DEFAULT_PROPERTY_TAX, 0.05)
    check("billed weekly", D.PROPERTY_TAX_PERIOD_HOURS, 168.0)
    per_bill = D.property_tax_per_bill(0.05)
    check("per-bill fraction", round(per_bill, 6), round(0.05 / 52, 6))
    # A 500 Denari home: ~0.48 per weekly bill, not 25 per day.
    check("weekly bill on a 500 home", round(500 * per_bill, 2), 0.48)

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
    print("Hot goods cannot be sold until laundered; property tax is annual.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
