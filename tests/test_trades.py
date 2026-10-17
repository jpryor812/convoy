#!/usr/bin/env python3
"""Every sale is in the log, named on both sides.

Before 2026-10-16 each of the five places that sell things logged its own
partial event, and none said who sold to whom for how much. The 2026-10-15 run
made 134 free meal offers and there was no way to count how many were taken.
`actions._record_trade` now records every sale once, completely, and the
Trades page is built from it.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from convoy import actions as A
from convoy.events import EventLog
from convoy.world_setup import new_world

FAILURES: list[str] = []


def ok(label, condition, detail="") -> None:
    if not condition:
        FAILURES.append(f"{label}{': ' + detail if detail else ''}")


def check(label, actual, expected) -> None:
    if actual != expected:
        FAILURES.append(f"{label}: got {actual!r}, expected {expected!r}")


def _sales(log: EventLog) -> list:
    return [e for e in log.events if e.type == "sale"]


def test_a_gift_is_a_trade_at_no_price() -> None:
    log = EventLog(None, echo_min=99)
    world = new_world(log, [("giver", "m"), ("taker", "m")])
    giver, taker = list(world.agents.values())
    giver.add_item("Meal", 1)
    giver.location = taker.location
    okp, msg = A.offer_trade(world, log, giver, taker.id, {"Meal": 1}, 0.0)
    ok("a free offer can be made", okp, msg)
    offer = next(iter(world.trade_offers.values()))
    oka, msg = A.accept_trade(world, log, taker, offer.id)
    ok("and taken", oka, msg)
    sales = _sales(log)
    check("one sale logged", len(sales), 1)
    if sales:
        d = sales[0].detail
        check("marked a gift", d.get("kind"), "gift")
        check("seller named", d.get("seller"), giver.id)
        check("buyer named", d.get("buyer"), taker.id)
        check("at no price", d.get("total"), 0.0)


def test_a_purchase_names_the_shop_and_the_price() -> None:
    from convoy.state import Business
    log = EventLog(None, echo_min=99)
    world = new_world(log, [("smith", "m"), ("shopper", "m")])
    smith, shopper = list(world.agents.values())
    shopper.location = smith.location
    # An agent's own shop, staffed by the owner standing in it -- not the
    # state's, which sells from nothing and is going away.
    shop = Business(id=world.new_id("B"), type="Weaponsmith / Armory",
                    name="smith's Armory", owner=smith.id, location=smith.location)
    world.businesses[shop.id] = shop
    shop.add_item("Sling", 2)
    shopper.denari = 10_000
    okb, msg = A.buy_from_business(world, log, shopper, shop.id, "Sling", 1)
    ok("bought a sling", okb, msg)
    sales = _sales(log)
    check("one sale logged", len(sales), 1)
    if sales:
        d = sales[0].detail
        check("from the shop", d.get("seller"), shop.id)
        check("to the shopper", d.get("buyer"), shopper.id)
        check("bought from a business", d.get("kind"), "shop")
        ok("with a price", (d.get("total") or 0) > 0, str(d))


def main() -> int:
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for t in tests:
        t()
    print(f"test_trades.py: {len(tests)} tests, {len(FAILURES)} failures")
    for f in FAILURES:
        print(f"  FAIL {f}")
    return 1 if FAILURES else 0


if __name__ == "__main__":
    raise SystemExit(main())
