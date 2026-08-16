#!/usr/bin/env python3
"""Chat channel isolation, invite-only guilds, and player-to-player trade.

The isolation rules are the ones that must never silently break: a direct
message leaking into world chat, or guild chat being readable by a non-member,
would be invisible in a run report and would corrupt every downstream agent
decision that reads chat as context.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from convoy import actions as A
from convoy import data as D
from convoy.events import EventLog
from convoy.state import Agent, Property, VehicleInstance, World

FAILURES: list[str] = []


def check(label: str, actual, expected) -> None:
    if actual != expected:
        FAILURES.append(f"{label}: got {actual!r}, expected {expected!r}")


def world_with(n=3, location="Town"):
    w, log = World(), EventLog(None, echo_min=99)
    for i in range(n):
        a = Agent(id=f"A{i+1:04d}", name=f"Ag{i+1}", model="rb", location=location)
        a.denari = 500.0
        w.agents[a.id] = a
    return w, log, list(w.agents.values())


def test_channel_isolation():
    w, log, (a, b, c) = world_with(3)
    A.post_world_chat(w, log, a, "everyone can see this")
    A.send_direct_message(w, log, a, b.id, "just between us")
    A.create_guild(w, log, a, "Guild")
    A.invite_to_guild(w, log, a, b.id)
    A.accept_guild_invite(w, log, b, a.guild)
    A.post_guild_chat(w, log, a, "members only")

    def texts(agent):
        return [m.text for m in A.visible_chat(w, agent)]

    check("world chat is public to a", "everyone can see this" in texts(a), True)
    check("world chat is public to c", "everyone can see this" in texts(c), True)
    check("dm visible to sender", "just between us" in texts(a), True)
    check("dm visible to recipient", "just between us" in texts(b), True)
    check("dm NOT visible to bystander", "just between us" in texts(c), False)
    check("guild chat visible to member", "members only" in texts(b), True)
    check("guild chat NOT visible to outsider", "members only" in texts(c), False)

    # Leaving the guild cuts off its history immediately.
    A.leave_guild(w, log, b)
    check("guild history lost on leaving", "members only" in texts(b), False)


def test_guilds_are_invite_only():
    w, log, (a, b, c) = world_with(3)
    A.create_guild(w, log, a, "Closed Shop")
    gid = a.guild

    ok, _ = A.accept_guild_invite(w, log, b, gid)
    check("cannot join uninvited", ok, False)
    check("uninvited agent has no guild", b.guild, None)

    ok, _ = A.invite_to_guild(w, log, c, b.id)
    check("non-leader cannot invite", ok, False)

    A.invite_to_guild(w, log, a, b.id)
    ok, _ = A.accept_guild_invite(w, log, b, gid)
    check("invited agent can join", ok, True)
    check("member count", len(w.guilds[gid].members), 2)

    ok, _ = A.remove_guild_member(w, log, b, a.id)
    check("member cannot remove the leader", ok, False)
    A.remove_guild_member(w, log, a, b.id)
    check("leader can remove a member", b.guild, None)


def test_trade_requires_colocation_and_reachable_goods():
    w, log, (a, b, _c) = world_with(3)
    a.add_item("Grain", 4)

    b.location = "The Hills"
    ok, msg = A.offer_trade(w, log, a, b.id, {"Grain": 2}, 10.0)
    check("cannot trade across locations", ok, False)
    b.location = "Town"

    ok, _ = A.offer_trade(w, log, a, b.id, {"Grain": 99}, 10.0)
    check("cannot offer goods you lack", ok, False)

    ok, _ = A.offer_trade(w, log, a, b.id, {"Grain": 2}, 10.0)
    check("valid offer accepted", ok, True)
    offer_id = next(iter(w.trade_offers))

    ok, _ = A.accept_trade(w, log, a, offer_id)
    check("seller cannot accept their own offer", ok, False)

    before_b = b.denari
    ok, _ = A.accept_trade(w, log, b, offer_id)
    check("buyer can accept", ok, True)
    check("goods moved", b.inventory.get("Grain"), 2)
    check("seller kept the rest", a.inventory.get("Grain"), 2)
    # Incidence flipped 2026-08-15: the buyer pays exactly the marked price and
    # the SELLER remits the revenue tax out of what they receive.
    tax = 10.0 * w.government.sales_tax
    check("buyer paid exactly the marked price", round(before_b - b.denari, 2), 10.0)
    check("seller received the price less tax", round(a.denari, 2), round(510.0 - tax, 2))


def test_vehicle_and_home_extend_tradeable_pool():
    """You trade what you have ON you -- unless a vehicle or home is right here."""
    w, log, (a, b, _c) = world_with(3)
    a.add_item("Grain", 3)
    check("on-person only", A.accessible_goods(w, a), {"Grain": 3})

    veh = VehicleInstance(id="V1", type="Donkey Cart", owner=a.id, location="Town")
    veh.cargo = {"Iron": 10}
    w.vehicles["V1"] = veh
    a.owned_vehicles.append("V1")
    check("cart at same location counts", A.accessible_goods(w, a), {"Grain": 3, "Iron": 10})

    veh.location = "The Hills"
    check("cart elsewhere does not count", A.accessible_goods(w, a), {"Grain": 3})
    veh.location = "Town"

    prop = Property(id="P1", owner=a.id, location="Town")
    prop.stored = {"Wood": 25}
    w.properties["P1"] = prop
    a.owned_property = "P1"
    check("home storage counts when present",
          A.accessible_goods(w, a), {"Grain": 3, "Iron": 10, "Wood": 25})

    # Selling from the cart must actually draw down the cart.
    A.offer_trade(w, log, a, b.id, {"Iron": 4}, 20.0)
    A.accept_trade(w, log, b, next(iter(w.trade_offers)))
    check("cart cargo reduced", veh.cargo.get("Iron"), 6)
    check("buyer received it", b.inventory.get("Iron"), 4)


def test_offer_limits():
    w, log, agents = world_with(6)
    seller = agents[0]
    seller.add_item("Grain", 50)
    for buyer in agents[1:5]:
        A.offer_trade(w, log, seller, buyer.id, {"Grain": 1}, 5.0)
    open_offers = [o for o in w.trade_offers.values() if o.status == "open"]
    check("open offers capped per seller", len(open_offers), D.MAX_OPEN_OFFERS_PER_SELLER)

    ok, _ = A.offer_trade(w, log, seller, agents[1].id, {"Grain": 1}, 5.0)
    check("no duplicate offer to the same buyer", ok, False)


def test_government_has_no_research():
    from convoy.world_setup import build_government

    w, log, (a, _b, _c) = world_with(3)
    build_government(w, log)
    gov_farm = w.government_business("Farm")
    a.location = gov_farm.location
    ok, msg = A.apply_for_job(w, log, a, gov_farm.id, "Researcher", as_researcher=True)
    check("cannot research at a government business", ok, False)
    check("reason given", "government" in msg.lower(), True)


def main() -> int:
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for t in tests:
        t()
    print(f"Ran {len(tests)} social-layer tests.")
    if FAILURES:
        print(f"\n{len(FAILURES)} FAILURES:")
        for f in FAILURES:
            print(f"  ! {f}")
        return 1
    print("Chat isolation, invite-only guilds, and P2P trade all behave.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
