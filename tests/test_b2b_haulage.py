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
from convoy import economy as E
from convoy import data as D
from convoy import world_map as M
from convoy.events import EventLog
from convoy.world_setup import new_world

FAILURES: list[str] = []

# Where a tavern belongs on this map, read off `world_map` rather than named --
# it moved from South Protected Zone to The Crossing when the demo map cut the
# protected zones, and a hard-coded location made that look like a haulage bug.
TAVERN_TOWN = M.GOVERNMENT_SITES["Tavern / Inn"]


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

    taverner.location = TAVERN_TOWN
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

    courier.location = TAVERN_TOWN
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


def test_a_courier_can_only_claim_one_job():
    """Claiming must be exclusive, or one agent hoards jobs it cannot do.

    `hauling` is only set on COLLECT, so claiming used to be unlimited: a
    claimed job is hidden from other couriers, and a consignment moves whole
    and one at a time, so a second claim can never be acted on.
    """
    world, log, refiner, refinery, taverner, tavern, courier = setup()
    A.order_from_business(world, log, taverner, tavern.id, refinery.id,
                          "Grain", 5, courier_fee=10.0)
    A.order_from_business(world, log, taverner, tavern.id, refinery.id,
                          "Purified Water", 5, courier_fee=10.0)
    jobs = list(world.consignments.values())

    ok1, _ = A.accept_courier_job(world, log, courier, jobs[0].id)
    ok("first claim accepted", ok1)
    ok2, msg = A.accept_courier_job(world, log, courier, jobs[1].id)
    ok("second claim refused", not ok2, msg)
    ok("the refusal names the held job", jobs[0].id in msg, msg)

    # The second job must still be visible to somebody else.
    ok("the unclaimed job is still on the board",
       any(j["id"] == jobs[1].id for j in A.open_courier_jobs(world, refiner)))


def test_a_claimed_job_stays_visible_to_its_courier():
    """A job vanishes from the public board once claimed -- it must not vanish
    from the courier who claimed it.

    In the 2026-08-15 smoke an agent claimed two jobs and walked to the far end
    of the valley: after claiming, nothing in its observation carried the id,
    the pickup point or the fee.
    """
    from convoy import observe as O
    world, log, refiner, refinery, taverner, tavern, courier = setup()
    A.order_from_business(world, log, taverner, tavern.id, refinery.id,
                          "Grain", 5, courier_fee=40.0)
    con = next(iter(world.consignments.values()))

    A.accept_courier_job(world, log, courier, con.id)
    seen = O.render(O.observe(world, log, courier, "reevaluation"))
    ok("the claimed job is still visible", con.id in seen)
    ok("it says where to collect", con.origin in seen, con.origin)
    ok("it says what it pays", "40" in seen)
    ok("it is gone from the public board",
       not any(j["id"] == con.id for j in A.open_courier_jobs(world, refiner)))

    courier.location = con.origin
    A.collect_consignment(world, log, courier, con.id)
    seen = O.render(O.observe(world, log, courier, "reevaluation"))
    ok("after loading it says where to deliver", con.destination in seen)


# ---------------------------------------------------------------------------
# SELLER-POSTED HAULAGE (2026-08-19)
# ---------------------------------------------------------------------------

def _full_mine():
    """An owner whose mine is stalled on a full yard, and a courier on foot."""
    log = EventLog(None, echo_min=99)
    world = new_world(log, [("owner", "rb"), ("courier", "rb")])
    owner, courier = list(world.agents.values())
    owner.denari = 3000.0
    owner.location = "Copper Gulch"
    A.start_business(world, log, owner, "Mining Operation")
    mine = world.businesses[owner.owned_businesses[0]]
    mine.cash = 500.0
    mine.active_production = "Copper Ore"
    mine.inventory["Copper Ore"] = E.business_storage_capacity(world, mine)
    gov = next(b for b in world.businesses.values()
               if b.type == "Refinery" and b.is_government)
    return world, log, owner, courier, mine, gov


def test_a_seller_can_push_stock_without_a_buyer():
    """THE MISSING PRIMITIVE.

    `order_from_business` is a PULL, paid upfront by the buyer -- so a mine with
    a full yard could only wait for someone solvent to want its ore. At hour 53
    of the 2026-08-18 run that was the whole jam: seven yards full, six
    businesses starved of exactly what those yards held, and the buyers holding
    40, 52 and 0.2 denari between them.
    """
    world, log, owner, _c, mine, gov = _full_mine()
    before = mine.inventory["Copper Ore"]
    good, msg = A.post_delivery_job(world, log, owner, mine.id, "Copper Ore",
                                    100, gov.id, 40.0)
    ok("seller can post haulage", good, msg)
    ok("goods leave the yard AT ONCE, so production restarts",
       mine.inventory["Copper Ore"] == before - 100,
       f"{before} -> {mine.inventory['Copper Ore']}")
    ok("the fee is escrowed", mine.cash == 500.0 - 40.0, f"{mine.cash}")


def test_the_job_is_announced_in_world_chat():
    """A job nobody hears about is a job nobody takes."""
    world, log, owner, _c, mine, gov = _full_mine()
    before = len(world.chat)
    A.post_delivery_job(world, log, owner, mine.id, "Copper Ore", 100, gov.id, 40.0)
    ok("chat carries it", len(world.chat) == before + 1)
    text = world.chat[-1].text
    ok("names the pay", "40.00" in text, text)
    ok("carries the id to act on", "accept_courier_job" in text, text)


def test_carriage_is_priced_on_cargo_value_and_danger():
    """Time alone prices every job in this valley at four denari.

    The whole road crosses in five simulated minutes, so a time-based fee makes
    haulage never worth a decision AND prices a cart of daggers like a cart of
    stone. Distance still has to matter, though -- that is what makes where you
    build a decision rather than a detail.

    WHAT LOCATION BUYS YOU CHANGED TWICE. It first meant nearness to a refinery,
    while the state mine and farm sat minutes from the smelters. Clearing both
    ends of the road moved every mine and farm into the middle, so it became
    which END you served cheaply. On the demo map, with four segments instead of
    six and no safe approach to the market, it is neither -- and the reason is
    worth pinning down, because it is the model working rather than failing.

    DANGER DOMINATES DISTANCE. The fee is priced on the worst road a load
    crosses, so every route into Town pays the Switchbacks premium and they all
    land within a denarius of each other whether the haul is one segment or four.
    Reaching the market costs what it costs; only the northbound run to the
    smelters, over the mild Slagside Road, is cheap.

    So the property worth guarding is no longer about distance at all. It is that
    the road's CHARACTER prices the load, and these two assertions say so
    directly: mild ground is meaningfully cheaper than bad ground, and a short
    haul over bad ground beats a long one that avoids it.
    """
    value = D.base_price("Copper Ore") * 100
    mild = E.suggested_courier_fee(M.LOCATIONS[1], M.LOCATIONS[0], value)
    bad = E.suggested_courier_fee(M.LOCATIONS[1], M.LOCATIONS[-1], value)
    ok("the bad road pays meaningfully more", bad > mild * 1.2,
       f"mild {mild:.2f} vs bad {bad:.2f}")

    # One segment over the worst ground against three that avoid it.
    short_bad = E.suggested_courier_fee(M.LOCATIONS[-2], M.LOCATIONS[-1], value)
    long_mild = E.suggested_courier_fee(M.LOCATIONS[-2], M.LOCATIONS[0], value)
    ok("danger outweighs distance", short_bad > long_mild,
       f"1 bad segment {short_bad:.2f} vs 3 milder ones {long_mild:.2f}")

    spur = M.SPURS[0].name
    cheap = E.suggested_courier_fee(spur, "Town", 100.0)
    dear = E.suggested_courier_fee(spur, "Town", 2000.0)
    ok("valuable cargo pays more on the same road", dear > cheap * 4,
       f"{cheap:.2f} vs {dear:.2f}")


def test_a_lowball_fee_is_refused_with_the_number():
    world, log, owner, _c, mine, gov = _full_mine()
    good, msg = A.post_delivery_job(world, log, owner, mine.id, "Copper Ore",
                                    100, gov.id, 2.0)
    ok("refused", not good)
    ok("and says what would work", "Suggested" in msg, msg)


def test_a_lent_vehicle_makes_a_load_haulable_and_comes_back():
    """A consignment moves WHOLE, so on foot (capacity 5) a 100-unit job is
    unclaimable. Lending is what lets an owner hire a courier without a cart."""
    from convoy.state import VehicleInstance

    world, log, owner, courier, mine, gov = _full_mine()
    v = VehicleInstance(id=world.new_id("V"), type="Donkey Cart",
                        owner=owner.id, location="Copper Gulch")
    world.vehicles[v.id] = v
    owner.owned_vehicles.append(v.id)
    A.post_delivery_job(world, log, owner, mine.id, "Copper Ore", 100, gov.id,
                        40.0, lend_vehicle=v.id)
    job = A.open_courier_jobs(world, courier)[0]
    ok("the listing says a vehicle comes with it",
       job["vehicle_provided"] == "Donkey Cart", str(job))
    ok("and that this courier can therefore lift it", job["you_can_carry_it"])
    ok("without disclosing how much that is", "qty" not in job, str(job))

    A.accept_courier_job(world, log, courier, job["id"])
    courier.location = "Copper Gulch"
    good, msg = A.collect_consignment(world, log, courier, job["id"])
    ok("loaded using the lent cart", good, msg)
    ok("courier is riding it", courier.mounted_vehicle == v.id)

    courier.location = gov.location
    A.deliver_consignment(world, log, courier, job["id"])
    ok("cart handed back", courier.mounted_vehicle is None)
    ok("and cannot be kept", world.vehicles[v.id].owner == owner.id)


def test_delivering_to_the_state_pays_the_seller():
    # 4 units, not 100: this courier is on foot with a capacity of 5 and no cart
    # was lent, and a consignment moves WHOLE. The load simply never loads.
    world, log, owner, courier, mine, gov = _full_mine()
    A.post_delivery_job(world, log, owner, mine.id, "Copper Ore", 4, gov.id, 40.0)
    job = A.open_courier_jobs(world, courier)[0]
    A.accept_courier_job(world, log, courier, job["id"])
    courier.location = "Copper Gulch"
    A.collect_consignment(world, log, courier, job["id"])
    courier.location = gov.location
    before_mine, before_courier = mine.cash, courier.denari
    A.deliver_consignment(world, log, courier, job["id"])
    ok("the state paid the seller", mine.cash > before_mine,
       f"{before_mine} -> {mine.cash}")
    ok("the courier was paid the fee",
       abs(courier.denari - before_courier - 40.0) < 1e-6,
       f"{courier.denari - before_courier}")


def test_you_cannot_post_a_delivery_to_someone_elses_business():
    """That is a SALE, and a sale needs the other side to agree a price."""
    world, log, owner, courier, mine, _gov = _full_mine()
    courier.denari = 3000.0
    courier.location = "Refinery Row"
    A.start_business(world, log, courier, "Refinery", seed_cash=50.0)
    theirs = world.businesses[courier.owned_businesses[0]]
    good, msg = A.post_delivery_job(world, log, owner, mine.id, "Copper Ore",
                                    100, theirs.id, 40.0)
    ok("refused", not good)
    ok("and points at the action that does work",
       "order_from_business" in msg, msg)


def test_cancelling_returns_the_goods_and_the_fee():
    world, log, owner, _c, mine, gov = _full_mine()
    before_stock, before_cash = mine.inventory["Copper Ore"], mine.cash
    A.post_delivery_job(world, log, owner, mine.id, "Copper Ore", 100, gov.id, 40.0)
    cid = next(iter(world.consignments))
    good, msg = A.cancel_consignment(world, log, owner, cid)
    ok("cancelled", good, msg)
    ok("stock back", mine.inventory["Copper Ore"] == before_stock, str(mine.inventory))
    ok("fee refunded", abs(mine.cash - before_cash) < 1e-6, f"{mine.cash}")


def test_the_load_is_sealed():
    """A courier is quoted a price and a route, not an inventory.

    Publishing what every load is worth makes a board where the valuable jobs
    go instantly and everything else rots. What is in the cart becomes apparent
    at pickup, which is where it should.
    """
    world, log, owner, courier, mine, gov = _full_mine()
    A.post_delivery_job(world, log, owner, mine.id, "Copper Ore", 4, gov.id, 40.0)
    job = A.open_courier_jobs(world, courier)[0]
    for hidden in ("item", "qty", "cargo_worth"):
        ok(f"{hidden} is not published", hidden not in job, str(job))
    for shown in ("pays", "from", "to", "hired_by"):
        ok(f"{shown} is", shown in job, str(job))
    ok("and it names who is asking", job["hired_by"] == owner.name, str(job))

    text = world.chat[-1].text
    ok("the advert names no cargo", "Copper Ore" not in text, text)
    ok("nor a quantity", " 4x" not in text and "4x " not in text, text)
    ok("but does name the price", "40.00" in text, text)


def test_a_job_you_cannot_lift_sorts_last():
    """A job this courier cannot carry is not an opportunity, it is a wasted turn."""
    world, log, owner, courier, mine, gov = _full_mine()
    A.post_delivery_job(world, log, owner, mine.id, "Copper Ore", 100, gov.id, 90.0)
    A.post_delivery_job(world, log, owner, mine.id, "Copper Ore", 4, gov.id, 20.0)
    jobs = A.open_courier_jobs(world, courier)
    ok("the liftable one is offered first", jobs[0]["you_can_carry_it"], str(jobs))
    ok("even though it pays less", jobs[0]["pays"] < jobs[1]["pays"])
    ok("and the big one is still listed", not jobs[1]["you_can_carry_it"])


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
