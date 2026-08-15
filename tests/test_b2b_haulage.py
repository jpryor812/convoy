#!/usr/bin/env python3
"""Business-to-business trade and the haulage that carries it.

This is a MULTI-STEP flow across two businesses, a courier, and two locations,
and both of the worst bugs found on 2026-08-15 lived in flows exactly like it --
each action correct alone, the sequence wrong. So these tests run sequences and
check the invariants that money and goods must obey end to end:

  * nothing is created or destroyed -- what leaves a seller arrives at a buyer,
    or goes back to the seller on cancellation;
  * a courier who completes a job is always paid, because the fee was escrowed
    when the order was placed;
  * goods under carriage are NOT the courier's -- they cannot be sold en route,
    and they still take up room in the cart.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from convoy import actions as A
from convoy import data as D
from convoy.events import EventLog
from convoy.world_setup import new_world

FAILURES: list[str] = []


def ok(label: str, cond: bool, detail: str = "") -> None:
    print(f"  {label}" + (f": {detail}" if detail else ""))
    if not cond:
        FAILURES.append(f"{label}{': ' + detail if detail else ''}")


def setup():
    """A refinery owner, a tavern owner, and a courier."""
    log = EventLog(None, echo_min=99)
    world = new_world(log, [("refiner", "rb"), ("taverner", "rb"), ("courier", "rb")])
    refiner, taverner, courier = list(world.agents.values())
    for a in (refiner, taverner, courier):
        a.denari = 5000.0

    refiner.location = "Refinery Row"
    A.start_business(world, log, refiner, "Refinery", seed_cash=200.0)
    refinery = world.businesses[refiner.owned_businesses[0]]
    refinery.inventory = {"Grain": 60, "Purified Water": 40}
    refinery.retail_prices = {"Grain": 4.0, "Purified Water": 2.0}

    taverner.location = "South Protected Zone"
    A.start_business(world, log, taverner, "Tavern / Inn", seed_cash=1000.0)
    tavern = world.businesses[taverner.owned_businesses[0]]

    return world, log, refiner, refinery, taverner, tavern, courier


def test_a_full_delivery_conserves_goods_and_money():
    world, log, refiner, refinery, taverner, tavern, courier = setup()

    grain_before = refinery.inventory["Grain"]
    tavern_cash = tavern.cash
    refinery_cash = refinery.cash
    courier_denari = courier.denari

    okr, msg = A.order_from_business(
        world, log, taverner, tavern.id, refinery.id, "Grain", 20, courier_fee=50.0
    )
    ok("order placed", okr, msg)
    if not okr:
        return
    con = next(iter(world.consignments.values()))

    ok("goods left the seller at once", refinery.inventory["Grain"] == grain_before - 20,
       str(refinery.inventory.get("Grain")))
    ok("buyer paid for goods AND escrowed carriage", tavern.cash < tavern_cash - 50.0,
       f"{tavern.cash:.2f}")
    ok("seller was paid", refinery.cash > refinery_cash, f"{refinery.cash:.2f}")
    ok("nothing delivered yet", tavern.inventory.get("Grain", 0) == 0)

    # A courier with only a satchel cannot lift 20 units.
    courier.location = "Refinery Row"
    A.accept_courier_job(world, log, courier, con.id)
    okc, msg = A.collect_consignment(world, log, courier, con.id)
    ok("on foot, a 20-unit load is refused", not okc, msg)

    courier.location = "Town"
    A.buy_vehicle(world, log, courier, "Camel")
    A.mount(world, log, courier, courier.owned_vehicles[0])
    courier.location = "Refinery Row"
    okc, msg = A.collect_consignment(world, log, courier, con.id)
    ok("with a Camel it loads", okc, msg)
    ok("the load takes up room in the cart", courier.carried_units() == 20,
       str(courier.carried_units()))
    ok("goods are NOT the courier's inventory", "Grain" not in courier.inventory)

    okd, msg = A.deliver_consignment(world, log, courier, con.id)
    ok("cannot deliver at the wrong place", not okd, msg)

    courier.location = "South Protected Zone"
    paid_before = courier.denari
    okd, msg = A.deliver_consignment(world, log, courier, con.id)
    ok("delivered", okd, msg)
    ok("the tavern has its grain", tavern.inventory.get("Grain") == 20,
       str(tavern.inventory.get("Grain")))
    ok("courier was paid the escrowed fee", abs(courier.denari - paid_before - 50.0) < 1e-6,
       f"{courier.denari - paid_before:.2f}")
    ok("cart is empty again", courier.carried_units() == 0)
    ok("courier is free to take another job", courier.hauling is None)

    moved = 20
    ok("no grain was created or destroyed",
       refinery.inventory.get("Grain", 0) + tavern.inventory.get("Grain", 0) + moved
       == grain_before + moved,
       f"{refinery.inventory.get('Grain', 0)} + {tavern.inventory.get('Grain', 0)}")


def test_goods_under_carriage_cannot_be_sold():
    """A courier holding someone else's cargo must not be able to sell it."""
    world, log, refiner, refinery, taverner, tavern, courier = setup()
    A.order_from_business(world, log, taverner, tavern.id, refinery.id,
                          "Grain", 5, courier_fee=10.0)
    con = next(iter(world.consignments.values()))
    courier.location = "Refinery Row"
    A.accept_courier_job(world, log, courier, con.id)
    A.collect_consignment(world, log, courier, con.id)

    oks, msg = A.sell_to_business(world, log, courier, refinery.id, "Grain", 5)
    ok("cannot sell the cargo", not oks, msg)
    ok("still hauling it", courier.hauling == con.id)


def test_cancelling_returns_the_fee_and_the_goods():
    world, log, refiner, refinery, taverner, tavern, courier = setup()
    grain_before = refinery.inventory["Grain"]
    A.order_from_business(world, log, taverner, tavern.id, refinery.id,
                          "Grain", 10, courier_fee=25.0)
    con = next(iter(world.consignments.values()))
    cash_after_order = tavern.cash

    okc, msg = A.cancel_consignment(world, log, taverner, con.id)
    ok("cancelled", okc, msg)
    ok("carriage fee refunded", abs(tavern.cash - cash_after_order - 25.0) < 1e-6,
       f"{tavern.cash - cash_after_order:.2f}")
    ok("goods are back with the seller", refinery.inventory.get("Grain") == grain_before,
       str(refinery.inventory.get("Grain")))


def test_a_loaded_consignment_cannot_be_cancelled():
    world, log, refiner, refinery, taverner, tavern, courier = setup()
    A.order_from_business(world, log, taverner, tavern.id, refinery.id,
                          "Grain", 5, courier_fee=10.0)
    con = next(iter(world.consignments.values()))
    courier.location = "Refinery Row"
    A.accept_courier_job(world, log, courier, con.id)
    A.collect_consignment(world, log, courier, con.id)

    okc, msg = A.cancel_consignment(world, log, taverner, con.id)
    ok("cannot cancel goods already on the road", not okc, msg)


def test_a_courier_hauls_one_job_at_a_time():
    world, log, refiner, refinery, taverner, tavern, courier = setup()
    A.order_from_business(world, log, taverner, tavern.id, refinery.id,
                          "Grain", 5, courier_fee=10.0)
    A.order_from_business(world, log, taverner, tavern.id, refinery.id,
                          "Purified Water", 5, courier_fee=10.0)
    jobs = list(world.consignments.values())
    courier.location = "Refinery Row"
    A.accept_courier_job(world, log, courier, jobs[0].id)
    A.collect_consignment(world, log, courier, jobs[0].id)
    oka, msg = A.accept_courier_job(world, log, courier, jobs[1].id)
    ok("a second job is refused while loaded", not oka, msg)


def test_same_location_needs_no_courier():
    """Buying from a business in the same place should just hand the goods over."""
    world, log, refiner, refinery, taverner, tavern, courier = setup()
    # A second refinery at Refinery Row, buying from the first.
    refiner.location = "Refinery Row"
    A.deposit(world, log, refiner, refinery.id, 500.0)
    gov_ref = [b for b in world.businesses.values()
               if b.is_government and b.type == "Refinery"][0]
    okr, msg = A.order_from_business(
        world, log, refiner, refinery.id, gov_ref.id, "Charcoal", 4, courier_fee=99.0
    )
    ok("same-site order succeeds", okr, msg)
    ok("delivered immediately", refinery.inventory.get("Charcoal", 0) == 4,
       str(refinery.inventory.get("Charcoal")))
    ok("no consignment was created", not world.consignments)


def test_open_jobs_are_visible_to_everyone():
    world, log, refiner, refinery, taverner, tavern, courier = setup()
    A.order_from_business(world, log, taverner, tavern.id, refinery.id,
                          "Grain", 10, courier_fee=40.0)
    jobs = A.open_courier_jobs(world, courier)
    ok("a stranger can see the job", len(jobs) == 1, str(jobs))
    ok("the pay is stated", jobs and jobs[0]["pays"] == 40.0, str(jobs))


def test_a_business_cannot_order_beyond_its_cash():
    world, log, refiner, refinery, taverner, tavern, courier = setup()
    tavern.cash = 10.0
    okr, msg = A.order_from_business(
        world, log, taverner, tavern.id, refinery.id, "Grain", 20, courier_fee=50.0
    )
    ok("under-funded order refused", not okr, msg)
    ok("the refusal says what is needed", "needs" in msg, msg)


def main() -> int:
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in tests:
        print(f"\n--- {fn.__name__} ---")
        fn()
    print()
    if FAILURES:
        print(f"{len(FAILURES)} FAILURES:")
        for f in FAILURES:
            print(f"  ! {f}")
        return 1
    print("OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
