#!/usr/bin/env python3
"""The convoy system end to end: hiring, the road, and who eats the loss.

`test_banditry.py` checks the SHAPE of the probability. This checks that it is
plumbed into a world that actually moves -- escorts get hired and paid and
disband, a journey resolves, goods really leave an inventory, and the agent is
told the odds before it sets off rather than the outcome afterwards.

The three things most likely to be wrong here are not arithmetic:

  * that robbery fires at all (an unreached branch looks exactly like a safe
    road);
  * that it fires ONLY where it should -- on foot must stay untouchable, or the
    bottom rung of the ladder is gone;
  * that the observation carries the number, because a risk an agent cannot see
    changes no decision. That is PHASE4 §2, and this system is a prime candidate
    to become its fifteenth entry.

No place is named. Routes are read off `world_map`.
"""

from __future__ import annotations

import sys
from itertools import combinations
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from convoy import actions as A
from convoy import banditry as B
from convoy import data as D
from convoy import observe as O
from convoy.engine import Engine, EngineConfig
from convoy.events import EventLog
from convoy.state import VehicleInstance, World
from convoy.world_setup import new_world
from convoy import world_map as M

FAILURES: list[str] = []


def ok(label: str, cond: bool, detail: str = "") -> None:
    print(f"  {'ok  ' if cond else 'FAIL'} {label}" + (f": {detail}" if detail else ""))
    if not cond:
        FAILURES.append(label)


def _longest_route() -> tuple[str, str]:
    best, n = (M.LOCATIONS[0], M.LOCATIONS[-1]), -1
    for a, b in combinations(M.LOCATIONS, 2):
        k = len(M.travel_path(a, b)[1])
        if k > n:
            best, n = (a, b), k
    return best


LONG = _longest_route()


class Idle:
    """A policy that decides nothing, so only the engine's own machinery runs."""
    def decide(self, world: World, agent, reason: str) -> None:
        return None


def _world(cargo: dict[str, int] | None = None, at: str | None = None):
    log = EventLog()
    w = new_world(log, [("hauler", "rb")])
    agent = next(iter(w.agents.values()))
    agent.location = at or LONG[0]
    agent.inventory = dict(cargo or {})
    return w, log, agent


def _give_cart(w: World, log: EventLog, agent, kind: str = "Donkey Cart") -> str:
    v = VehicleInstance(id=w.new_id("V"), type=kind, owner=agent.id, location=agent.location)
    w.vehicles[v.id] = v
    agent.owned_vehicles.append(v.id)
    A.mount(w, log, agent, v.id)
    return v.id


def _drive(w: World, log: EventLog, agent, destination: str, seed: int = 1) -> Engine:
    """Send the agent down the road and run the engine until it lands."""
    A.travel_to(w, log, agent, destination)
    eng = Engine(w, log, Idle(), EngineConfig(
        duration_hours=0.5, speed=1e9, checkpoint_every_hours=1e9, banditry_seed=seed,
    ))
    eng.step_until(w.sim_time + 3600.0)
    return eng


# ---------------------------------------------------------------------------

def test_hiring_costs_money_and_sticks() -> None:
    w, log, agent = _world({"Copper Ore": 100})
    _give_cart(w, log, agent)
    agent.denari = 500.0

    before = agent.denari
    okay, msg = A.hire_escort(w, log, agent, "Bodyguard", "Bronze Sword", "leather", 2)
    ok("two guards can be hired", okay, msg)
    ok("they are on the roster", len(agent.escorts) == 2)
    ok("and they were paid for", agent.denari < before, f"{before:.2f} -> {agent.denari:.2f}")
    ok("the message quotes the risk they bought", "->" in msg and "%" in msg, msg)

    dearer = B.hire_price("Bodyguard", "Iron Sword", A.ARMOR_SETS["iron"], 600)
    cheaper = B.hire_price("Bodyguard", "Wooden Spear", (), 600)
    ok("better kit costs more", dearer > cheaper, f"{cheaper:.2f} vs {dearer:.2f}")


def test_hiring_is_refused_for_the_right_reasons() -> None:
    w, log, agent = _world({"Copper Ore": 100})
    _give_cart(w, log, agent)
    agent.denari = 100000.0

    ok("a wage role is not an escort role",
       not A.hire_escort(w, log, agent, "Miner")[0])
    # Driver-own IS a valid escort role now (2026-08-20): agents and NPCs can
    # both fill every role on the Convoy tab.
    ok("but a driver is", A.hire_escort(w, log, agent, "Driver-own")[0])
    ok("an unknown weapon is refused",
       not A.hire_escort(w, log, agent, "Scout", "Excalibur")[0])
    ok("there is a limit on how many you can take",
       not A.hire_escort(w, log, agent, "Bodyguard", count=B.MAX_ESCORTS + 1)[0])

    poor_w, poor_log, poor = _world({"Copper Ore": 100})
    _give_cart(poor_w, poor_log, poor)
    poor.denari = 1.0
    refused, why = A.hire_escort(poor_w, poor_log, poor, "Bodyguard", "Iron Sword", "iron")
    ok("you cannot hire what you cannot pay for", not refused)
    ok("and the refusal says what would be cheaper", "cheaper" in why, why)

    moving_w, moving_log, moving = _world({"Copper Ore": 100})
    _give_cart(moving_w, moving_log, moving)
    moving.denari = 5000.0
    A.travel_to(moving_w, moving_log, moving, LONG[1])
    ok("you cannot hire guards from the middle of the road",
       not A.hire_escort(moving_w, moving_log, moving, "Bodyguard")[0])


def test_a_journey_can_actually_lose_you_goods() -> None:
    """The branch that does the work. An unreached one looks like a safe road."""
    robbed_any, seeds = False, range(12)
    for seed in seeds:
        w, log, agent = _world({"Copper Ore": 100}, at=LONG[0])
        _give_cart(w, log, agent)
        before = sum(agent.inventory.values())
        _drive(w, log, agent, LONG[1], seed=seed)
        after = sum(agent.inventory.values())
        if after < before:
            robbed_any = True
            ok("goods really left the inventory", after < before, f"{before} -> {after}")
            ok("but never all of them", after > 0, f"{after} left")
            ok("and it was logged", any(e.type == "robbed" for e in log.events))
            break
    ok("an unguarded cart on the worst road does get robbed", robbed_any,
       f"tried {len(list(seeds))} seeds")


def test_a_walker_can_be_robbed_through_the_engine() -> None:
    """The exemption is gone. Verified through the ENGINE, not just the model.

    This test used to assert the opposite -- twenty-five walks, nothing taken.
    It was rewritten on 2026-08-21 after a live run showed agents splitting every
    haulage job into five-unit walks precisely to exploit it.
    """
    robbed = 0
    for seed in range(25):
        w, log, agent = _world({"Iron Sword": 4}, at=LONG[0])   # a walkable fortune
        before = sum(agent.inventory.values())
        _drive(w, log, agent, LONG[1], seed=seed)
        if sum(agent.inventory.values()) < before:
            robbed += 1
    ok("a walker carrying real value does get robbed", robbed > 0,
       f"{robbed} of 25 walks")
    ok("...but not every single time", robbed < 25, f"{robbed} of 25")


def test_escorts_are_hired_for_one_journey() -> None:
    w, log, agent = _world({"Copper Ore": 100}, at=LONG[0])
    _give_cart(w, log, agent)
    agent.denari = 5000.0
    A.hire_escort(w, log, agent, "Bodyguard", "Bronze Sword", "leather", 2)
    ok("guards are aboard before departure", len(agent.escorts) == 2)
    _drive(w, log, agent, LONG[1])
    ok("and gone once you arrive", not agent.escorts)
    ok("the agent did arrive", agent.location == LONG[1], agent.location)


def test_guards_measurably_move_the_odds() -> None:
    w, log, agent = _world({"Copper Ore": 100}, at=LONG[0])
    _give_cart(w, log, agent)
    agent.denari = 5000.0
    bare = B.risk_for(w, agent, LONG[1]).probability
    A.hire_escort(w, log, agent, "Bodyguard", "Iron Sword", "iron", 3)
    guarded = B.risk_for(w, agent, LONG[1]).probability
    ok("three armed guards cut the risk a long way", guarded < bare / 2,
       f"{bare:.0%} -> {guarded:.0%}")
    ok("but never to nothing", guarded >= B.MIN_SEGMENT_RISK, f"{guarded:.1%}")


def test_the_observation_carries_the_odds_before_the_decision() -> None:
    """PHASE4 §2. Nobody buys a cart because of a number they never saw."""
    w, log, agent = _world({"Copper Ore": 100}, at=LONG[0])
    obs = O.observe(w, log, agent, "test")
    walking = obs["you"].get("road_risk")
    ok("a walker is given real odds, not an exemption",
       bool(walking and walking.get("chance_of_being_robbed")), str(walking))
    ok("and told a cart and guards both help", walking is not None
       and "guards" in walking["note"], str(walking))

    _give_cart(w, log, agent)
    obs = O.observe(w, log, agent, "test")
    risk = obs["you"].get("road_risk")
    ok("a carter is given a number per destination",
       bool(risk and risk.get("chance_of_being_robbed")))
    ok("including the one they would actually go to",
       LONG[1] in (risk or {}).get("chance_of_being_robbed", {}))
    ok("and what the load is worth", (risk or {}).get("worth", 0) > 0)

    agent.denari = 5000.0
    A.hire_escort(w, log, agent, "Bodyguard", "Iron Sword", "iron", 2)
    after = O.observe(w, log, agent, "test")["you"]["road_risk"]
    ok("the number moves when guards are hired",
       after["chance_of_being_robbed"][LONG[1]]
       != risk["chance_of_being_robbed"][LONG[1]],
       f"{risk['chance_of_being_robbed'][LONG[1]]} -> "
       f"{after['chance_of_being_robbed'][LONG[1]]}")
    ok("and the guards are counted", after["guards_hired"] == 2)

    empty_w, empty_log, empty = _world({})
    ok("an empty-handed agent is not charged tokens for a risk line",
       "road_risk" not in O.observe(empty_w, empty_log, empty, "test")["you"])


def test_the_briefing_tells_the_truth_about_the_map() -> None:
    """It said "Sixteen spur roads" for two recuts after there were four."""
    text = O.static_briefing()
    ok("the spur count is the real one", f"{len(M.SPURS)} spur roads" in text,
       f"map has {len(M.SPURS)}")
    ok("bandits are explained at all", "BANDITS" in text)
    ok("the foot rule is stated", "ON FOOT" in text.upper())
    for seg in M.SEGMENTS:
        ok(f"{seg.name} carries a danger figure", f"danger {seg.danger:.2f}" in text)


def test_market_power_decides_who_can_insist() -> None:
    """Justin's rule: the abundant side pays, and only the scarce side can insist."""
    many_sellers = B.MarketPower("Copper Ore", sellers=3, buyers=1)
    ok("three mines, one refinery -> the mines pay",
       many_sellers.customary == "seller", many_sellers.explain())
    many_buyers = B.MarketPower("Copper Ore", sellers=1, buyers=3)
    ok("one mine, three refineries -> the refineries pay",
       many_buyers.customary == "buyer", many_buyers.explain())
    ok("evenly matched has no whip hand",
       B.MarketPower("Copper Ore", 2, 2).stronger == "neither")

    w, _log, _a = _world()
    live = B.market_power(w, "Copper Ore")
    ok("it counts real businesses in a real world",
       live.sellers >= 1 and live.buyers >= 1, live.explain())


def test_the_split_ladder_and_who_may_insist_on_what() -> None:
    """Cost and risk divide on a ladder, and scarcity decides the usual rung."""
    ok("the ladder is the one the designer named",
       D.CONVOY_SPLITS == (1.00, 0.75, 0.60, 0.50, 0.40, 0.25, 0.00),
       str(D.CONVOY_SPLITS))
    ok("three mines to one refinery -> the mines carry most",
       B.customary_split(B.MarketPower("Copper Ore", 3, 1)) == 0.75)
    ok("one mine to three refineries -> the refineries carry most",
       B.customary_split(B.MarketPower("Copper Ore", 1, 3)) == 0.25)
    ok("evenly matched splits it down the middle",
       B.customary_split(B.MarketPower("Copper Ore", 2, 2)) == 0.50)

    w, _log, _a = _world()
    power = B.market_power(w, "Copper Ore")
    usual = B.customary_split(power)

    share, why = A._settle_split(w, "Copper Ore", "seller", None)
    ok("asked for nothing, you get the customary rung", share == usual, why)

    ok("a rung that is not on the ladder is refused",
       A._settle_split(w, "Copper Ore", "seller", 0.33)[0] is None)

    ok("carrying MORE than customary is always allowed",
       A._settle_split(w, "Copper Ore", "seller", 1.00)[0] == 1.00)

    if power.stronger != "seller":
        share, why = A._settle_split(w, "Copper Ore", "seller", 0.25)
        ok("a seller with no leverage cannot push cost onto the buyer",
           share is None, why)
        ok("and is told the numbers behind the refusal",
           "not in a position" in why and str(power.sellers) in why, why)


def test_the_state_never_carries_a_share() -> None:
    """Total bargaining power, and the reason to found a rival.

    A government counterparty is why an agent-owned refinery offering 75/25 is
    worth shipping to instead. See `data.GOVERNMENT_BEARS_NOTHING`.
    """
    w, _log, _a = _world()
    gov_buyer = next(b for b in w.businesses.values()
                     if b.is_government and "Refinery" in b.type)
    gov_seller = next(b for b in w.businesses.values()
                      if b.is_government and "Mining" in b.type)

    share, why = A._settle_split(w, "Copper Ore", "seller", None, buyer_biz=gov_buyer)
    ok("selling to the state, you carry the whole convoy", share == 1.0, why)
    ok("and are told an agent buyer might split it", "agent-owned" in why, why)

    share, why = A._settle_split(w, "Copper Ore", "buyer", None, seller_biz=gov_seller)
    ok("buying from the state, likewise", share == 0.0, why)

    ok("and the state ignores even a demand it would otherwise refuse",
       A._settle_split(w, "Copper Ore", "seller", 0.0, buyer_biz=gov_buyer)[0] == 1.0)


def test_a_responsible_seller_actually_pays_up() -> None:
    """If agreeing terms moves no money, it is not a bargain.

    BOTH SIDES ARE AGENT-OWNED here, deliberately. The fixture used the state's
    own mine and refinery, and stopped meaning anything the moment the state
    stopped carrying a share -- a test that passes because nobody pays is not a
    test of paying. See `data.GOVERNMENT_BEARS_NOTHING`.
    """
    w, log, agent = _world()
    seller = next(b for b in w.businesses.values() if "Mining" in b.type)
    buyer = next(b for b in w.businesses.values() if "Refinery" in b.type)
    seller.owner = agent.id
    buyer.owner = "A0002"
    seller.cash, buyer.cash = 5000.0, 100.0

    from convoy.state import Consignment
    con = Consignment(
        id="C0001", seller_business=seller.id, buyer_business=buyer.id,
        item="Copper Ore", qty=100, goods_price=500.0, courier_fee=20.0,
        origin=seller.location, destination=buyer.location,
        created_at=0.0, seller_share=1.0,
    )
    w.consignments[con.id] = con
    agent.hauling = con.id
    agent.hauling_units = con.qty

    eng = Engine(w, log, Idle(), EngineConfig(duration_hours=1, speed=1e9))
    buyer_before, seller_before, qty_before = buyer.cash, seller.cash, con.qty
    lost, bearer = eng._rob_consignment(agent, 0.5)

    ok("half the load is gone", con.qty < qty_before, f"{qty_before} -> {con.qty}")
    ok("and the bearer is the side carrying the larger share",
       bearer == seller.owner, f"bearer={bearer}")
    ok("the loss has a value", lost > 0, f"{lost:.2f}")
    ok("the seller paid for it", seller.cash < seller_before,
       f"{seller_before:.2f} -> {seller.cash:.2f}")
    ok("the buyer was made whole", buyer.cash > buyer_before,
       f"{buyer_before:.2f} -> {buyer.cash:.2f}")
    ok("and it was recorded", any(e.type == "convoy_loss_covered" for e in log.events))

    # ...and the default, which is the behaviour Consignment always had.
    con2 = Consignment(
        id="C0002", seller_business=seller.id, buyer_business=buyer.id,
        item="Copper Ore", qty=100, goods_price=500.0, courier_fee=20.0,
        origin=seller.location, destination=buyer.location, created_at=0.0,
    )
    ok("a buyer-risk consignment is the default", con2.seller_share == 0.0)
    w.consignments[con2.id] = con2
    agent.hauling = con2.id
    seller_before, buyer_before = seller.cash, buyer.cash
    eng._rob_consignment(agent, 0.5)
    ok("nobody refunds a buyer who took the risk",
       seller.cash == seller_before and buyer.cash == buyer_before)


def test_a_courier_cannot_smuggle_its_own_goods_behind_a_job() -> None:
    """A bandit cannot tell whose crate is whose.

    `cargo_at_risk` used to return the consignment OR the inventory, which made
    "take a courier job, then carry your valuables along" a way to move your own
    stock at somebody else's risk and none of your own.
    """
    from convoy.state import Consignment

    w, log, agent = _world({"Bronze Sword": 3})
    seller = next(b for b in w.businesses.values() if "Mining" in b.type)
    buyer = next(b for b in w.businesses.values() if "Refinery" in b.type)
    con = Consignment(
        id="C0001", seller_business=seller.id, buyer_business=buyer.id,
        item="Copper Ore", qty=100, goods_price=500.0, courier_fee=20.0,
        origin=seller.location, destination=buyer.location, created_at=0.0,
    )
    w.consignments[con.id] = con
    agent.hauling = con.id

    value, what = B.cargo_at_risk(w, agent)
    own = sum(D.base_price(i) * q for i, q in agent.inventory.items())
    ok("the courier's own goods are counted too", value > own, f"{value:.0f}")
    ok("and the consignment as well",
       value >= own + D.base_price(con.item) * con.qty, f"{value:.0f}")
    ok("both are named to the agent",
       "carriage" in what and "your own" in what, what)

    eng = Engine(w, log, Idle(), EngineConfig(duration_hours=1, speed=1e9))
    before_own, before_con = sum(agent.inventory.values()), con.qty
    eng._rob_consignment(agent, 0.5)
    eng._rob_inventory(agent, 0.5)
    ok("a robbery takes from both", sum(agent.inventory.values()) < before_own
       and con.qty < before_con,
       f"own {before_own}->{sum(agent.inventory.values())}, "
       f"load {before_con}->{con.qty}")


def test_a_robbery_takes_a_share_of_the_whole_load() -> None:
    """The share is computed across the LOAD, not stack by stack.

    Per-item rounding used to take a whole one-unit stack whatever the roll
    said, so a lone Iron Sword was a total loss on the gentlest possible
    robbery. It is proportional now -- which matters more since the range
    moved to 50-100%, because a half-roll should mean half the cart and not
    "half of each pile, rounded up".
    """
    from convoy.engine import _share_of

    bad = [
        f"{t}@{f}->{_share_of(t, f)}"
        for t in range(1, 60)
        for f in (B.LOOT_FRACTION_MIN, 0.75, B.LOOT_FRACTION_MAX)
        if not 1 <= _share_of(t, f) <= t
    ]
    ok("always takes something, never more than there was", not bad,
       "; ".join(bad[:4]))
    ok("the share tracks the roll", _share_of(100, 1.0) > _share_of(100, 0.5),
       f"{_share_of(100, 0.5)} vs {_share_of(100, 1.0)}")

    w, log, agent = _world({"Iron Sword": 1, "Copper Ore": 20})
    eng = Engine(w, log, Idle(), EngineConfig(duration_hours=1, speed=1e9))
    before = sum(agent.inventory.values())
    eng._rob_inventory(agent, B.LOOT_FRACTION_MIN)
    after = sum(agent.inventory.values())
    ok("the gentlest robbery takes about half a mixed load",
       0 < after < before, f"{before} -> {after}")
    ok("it is proportional, not per-stack", after >= before // 3,
       f"{after} of {before} left")

    total_w, total_log, total = _world({"Iron Sword": 4})
    Engine(total_w, total_log, Idle(), EngineConfig())._rob_inventory(total, 1.0)
    ok("and a full roll really does clear the cart", not total.inventory,
       str(total.inventory))


def test_a_courier_does_not_claim_for_someone_elses_goods() -> None:
    """A claim is paid to whoever actually lost something."""
    from convoy.state import Consignment

    w, log, agent = _world(at=LONG[0])
    seller = next(b for b in w.businesses.values() if "Mining" in b.type)
    buyer = next(b for b in w.businesses.values() if "Refinery" in b.type)
    con = Consignment(
        id="C0001", seller_business=seller.id, buyer_business=buyer.id,
        item="Copper Ore", qty=100, goods_price=500.0, courier_fee=20.0,
        origin=seller.location, destination=buyer.location, created_at=0.0,
    )
    w.consignments[con.id] = con
    agent.hauling = con.id
    agent.insurance["Cargo"] = 5000.0

    eng = Engine(w, log, Idle(), EngineConfig(duration_hours=1, speed=1e9))
    _value, bearer = eng._rob_consignment(agent, 0.5)
    ok("the loss falls on the business, not the courier",
       bearer != agent.id, f"bearer={bearer}")
    ok("a buyer-risk load is borne by the buyer",
       bearer == buyer.owner, f"{bearer} vs buyer owner {buyer.owner}")

    con2 = Consignment(
        id="C0002", seller_business=seller.id, buyer_business=buyer.id,
        item="Copper Ore", qty=100, goods_price=500.0, courier_fee=20.0,
        origin=seller.location, destination=buyer.location,
        created_at=0.0, seller_share=1.0,
    )
    w.consignments[con2.id] = con2
    agent.hauling = con2.id
    _value, bearer2 = eng._rob_consignment(agent, 0.5)
    ok("and a seller-risk load by the seller",
       bearer2 == seller.owner, f"{bearer2} vs seller owner {seller.owner}")


def test_being_caught_can_cost_you_everything() -> None:
    """50-100%, flat. Total loss has to be genuinely reachable."""
    from convoy.engine import _share_of

    ok("the floor is half the load", B.LOOT_FRACTION_MIN == 0.50)
    ok("the ceiling is all of it", B.LOOT_FRACTION_MAX == 1.00)
    ok("a full roll takes the lot", _share_of(40, 1.0) == 40)
    ok("the gentlest roll still takes half", _share_of(40, 0.5) == 20)
    ok("something is always taken", _share_of(1, 0.5) >= 1)

    bad = [
        f"{t}@{f}" for t in range(1, 40) for f in (0.5, 0.75, 1.0)
        if not 1 <= _share_of(t, f) <= t
    ]
    ok("never more than there was, never nothing", not bad, "; ".join(bad[:3]))


def test_a_robbery_never_takes_the_cart() -> None:
    """Cargo only, in this mode. True by omission until it was pinned here.

    Nothing in `banditry` mentions vehicles, so nothing takes one -- which is
    the correct behaviour and also exactly the kind of invariant a later edit
    removes without anybody noticing. A driver on a convoy is not risking its
    cart, and if that is ever to change it should change deliberately.
    """
    worst_seeds = range(15)
    checked = 0
    for seed in worst_seeds:
        w, log, agent = _world({"Copper Ore": 100}, at=LONG[0])
        vid = _give_cart(w, log, agent)
        before = sum(agent.inventory.values())
        _drive(w, log, agent, LONG[1], seed=seed)
        veh = w.vehicles[vid]
        if sum(agent.inventory.values()) < before:
            checked += 1
            ok(f"seed {seed}: robbed, and the cart is still owned",
               vid in agent.owned_vehicles and veh.owner == agent.id)
            ok(f"seed {seed}: and still intact",
               veh.condition != "destroyed", veh.condition)
    ok("at least one of those journeys actually was robbed", checked > 0,
       f"{checked} robberies over {len(list(worst_seeds))} seeds")

    ok("no vehicle is ever destroyed by the road",
       all(v.condition != "destroyed" for v in w.vehicles.values()))


def test_a_lent_vehicle_comes_home_even_from_a_robbery() -> None:
    """Lending is riskless BY CONSTRUCTION, which is why it needs no trust."""
    from convoy.state import Consignment

    w, log, agent = _world(at=LONG[0])
    owner = next(iter(w.agents.values()))
    vid = _give_cart(w, log, agent)
    seller = next(b for b in w.businesses.values() if "Mining" in b.type)
    buyer = next(b for b in w.businesses.values() if "Refinery" in b.type)
    con = Consignment(
        id="C0001", seller_business=seller.id, buyer_business=buyer.id,
        item="Copper Ore", qty=100, goods_price=500.0, courier_fee=20.0,
        origin=LONG[0], destination=LONG[1], created_at=0.0,
        lent_vehicle=vid,
    )
    w.consignments[con.id] = con
    agent.hauling = con.id
    agent.hauling_units = con.qty

    eng = Engine(w, log, Idle(), EngineConfig(duration_hours=1, speed=1e9))
    eng._rob_consignment(agent, 1.0)
    ok("the load can be taken entirely", con.qty == 0, f"{con.qty} left")
    ok("the lent cart is untouched", w.vehicles[vid].condition != "destroyed")
    ok("and still bound to the job, not lost", con.lent_vehicle == vid)
    ok("still owned by whoever lent it", w.vehicles[vid].owner == owner.id)


def _two(cargo=None):
    """A world with an employer and somebody who might guard them."""
    log = EventLog()
    w = new_world(log, [("owner", "rb"), ("hand", "rb")])
    owner, hand = list(w.agents.values())[:2]
    for a in (owner, hand):
        a.location = LONG[0]
    owner.inventory = dict(cargo or {"Copper Ore": 100})
    owner.denari = 2000.0
    return w, log, owner, hand


def test_an_npc_costs_half_again_what_a_person_does() -> None:
    """The reason an escort labour market can exist at all.

    If an NPC were the cheap option nobody would ever hire an agent, and
    `post_escort_job` would be a tool nobody used -- the same trap
    `NPC_WAGE_MULTIPLIER` was cut from 2.25 to 1.50 to escape.
    """
    for role in D.CONVOY_PAY:
        person = B.hire_price(role, "Wooden Spear", (), 600)
        npc = B.hire_price(role, "Wooden Spear", (), 600, npc=True)
        ok(f"{role}: an NPC costs more", npc > person, f"{person:.2f} vs {npc:.2f}")
        ok(f"{role}: by exactly the multiplier",
           abs(npc / person - B.ESCORT_NPC_MULTIPLIER) < 1e-9)
    ok("driving your own cart pays best of all",
       B.suggested_fee("Driver-own", 600) > B.suggested_fee("Bodyguard", 600),
       f"{B.suggested_fee('Bodyguard', 600):.2f} -> {B.suggested_fee('Driver-own', 600):.2f}")


def test_every_role_is_open_to_agents_and_npcs_alike() -> None:
    w, log, owner, hand = _two()
    _give_cart(w, log, owner)
    for role in D.CONVOY_PAY:
        okay, msg = A.hire_escort(w, log, owner, role, "Wooden Spear", "none", 1)
        ok(f"an NPC can be hired as {role}", okay, msg)
    owner.escorts.clear()
    for role in D.CONVOY_PAY:
        okay, msg = A.post_escort_job(w, log, owner, role, 25.0, LONG[1])
        ok(f"a job can be posted for {role}", okay, msg)


def test_hiring_an_agent_escort_end_to_end() -> None:
    w, log, owner, hand = _two()
    _give_cart(w, log, owner)
    hand.denari = 10.0
    bare = B.risk_for(w, owner, LONG[1]).probability

    okay, msg = A.post_escort_job(w, log, owner, "Bodyguard", 30.0, LONG[1])
    ok("the job is posted", okay, msg)
    job = next(iter(w.escort_postings.values()))
    ok("and announced in world chat",
       any(e.type == "chat" and "ESCORT WANTED" in str(e.detail) for e in log.events))

    ok("the employer cannot take their own job",
       not A.accept_escort_job(w, log, owner, job.id)[0])
    okay, msg = A.accept_escort_job(w, log, hand, job.id)
    ok("another agent can take it", okay, msg)
    ok("it leaves the board", job.status == "taken")
    ok("the escort is bound", hand.escorting == owner.id)
    ok("and on the roster", len(owner.escorts) == 1)
    ok("nobody can take it twice",
       not A.accept_escort_job(w, log, hand, job.id)[0])

    guarded = B.risk_for(w, owner, LONG[1]).probability
    ok("a real guard moves the odds like an NPC would",
       guarded < bare, f"{bare:.0%} -> {guarded:.0%}")

    A.travel_to(w, log, owner, LONG[1])
    ok("the escort leaves with the convoy", hand.in_transit is not None)
    ok("...as a convoy, not as its own errand", hand.activity.kind == "convoy",
       hand.activity.kind)

    owner_cash, hand_cash = owner.denari, hand.denari
    eng = Engine(w, log, Idle(), EngineConfig(
        duration_hours=0.5, speed=1e9, checkpoint_every_hours=1e9, banditry=False))
    eng.step_until(w.sim_time + 3600.0)

    ok("both arrive", owner.location == LONG[1] and hand.location == LONG[1],
       f"{owner.location} / {hand.location}")
    ok("the escort is paid on arrival", hand.denari > hand_cash,
       f"{hand_cash:.2f} -> {hand.denari:.2f}")
    ok("out of the employer's pocket", owner.denari < owner_cash,
       f"{owner_cash:.2f} -> {owner.denari:.2f}")
    ok("and released", hand.escorting is None and not owner.escorts)
    ok("free to act again", hand.activity.kind == "idle", hand.activity.kind)
    ok("it is on the record", any(e.type == "escort_paid" for e in log.events))


def test_a_lent_weapon_comes_back() -> None:
    """Same argument as a lent vehicle: it cannot be kept, so it needs no trust."""
    w, log, owner, hand = _two()
    _give_cart(w, log, owner)
    owner.inventory["Iron Sword"] = 1

    okay, _msg = A.post_escort_job(w, log, owner, "Bodyguard", 30.0, LONG[1], "Iron Sword")
    ok("a weapon can be lent with the job", okay)
    ok("and leaves the employer's hands now",
       "Iron Sword" not in owner.inventory, str(owner.inventory))
    job = next(iter(w.escort_postings.values()))
    A.accept_escort_job(w, log, hand, job.id)
    ok("the escort carries it",
       owner.escorts[0].weapon == "Iron Sword", owner.escorts[0].weapon)

    A.travel_to(w, log, owner, LONG[1])
    Engine(w, log, Idle(), EngineConfig(
        duration_hours=0.5, speed=1e9, checkpoint_every_hours=1e9, banditry=False)
    ).step_until(w.sim_time + 3600.0)
    ok("and it comes home on arrival",
       owner.inventory.get("Iron Sword", 0) == 1, str(owner.inventory))
    ok("the escort does not keep it",
       "Iron Sword" not in hand.inventory, str(hand.inventory))


def test_driver_own_must_actually_bring_a_cart() -> None:
    """The top rate is paid for putting your own vehicle on the road."""
    w, log, owner, hand = _two()
    _give_cart(w, log, owner)
    A.post_escort_job(w, log, owner, "Driver-own", 40.0, LONG[1])
    job = next(iter(w.escort_postings.values()))

    refused, why = A.accept_escort_job(w, log, hand, job.id)
    ok("a driver with no cart is refused", not refused)
    ok("and pointed at the role that fits", "Driver-provided" in why, why)

    vid = _give_cart(w, log, hand, "4-Horse Chariot")
    okay, _msg = A.accept_escort_job(w, log, hand, job.id)
    ok("with a cart, they can take it", okay)
    ok("the roster records whose cart it is",
       owner.escorts[0].vehicle_id == vid)
    ok("and the convoy travels at the BEST cart's speed",
       B.party_for(w, owner).vehicle == "4-Horse Chariot",
       B.party_for(w, owner).vehicle)


def test_escort_work_is_visible_to_somebody_who_could_take_it() -> None:
    """A board nobody can see is not a market. PHASE4 §2, second entry."""
    w, log, owner, hand = _two()
    _give_cart(w, log, owner)
    A.post_escort_job(w, log, owner, "Bodyguard", 30.0, LONG[1])
    A.post_escort_job(w, log, owner, "Driver-own", 55.0, LONG[1])

    jobs = O.observe(w, log, hand, "test").get("escort_jobs")
    ok("the jobs reach another agent", jobs and len(jobs) == 2, str(jobs))
    ok("with what they pay", all("pays" in j for j in jobs or []))
    byrole = {j["role"]: j for j in jobs or []}
    ok("a bodyguard job is takeable on foot", byrole["Bodyguard"]["you_can_take_it"])
    ok("a driver-own job is NOT, with no cart",
       not byrole["Driver-own"]["you_can_take_it"])
    ok("takeable jobs sort first", (jobs or [{}])[0]["role"] == "Bodyguard")

    ok("the employer is not shown its own advert",
       not O.observe(w, log, owner, "test").get("escort_jobs"))
    ok("and with nobody hired yet, has no convoy to be told about",
       "your_convoy" not in O.observe(w, log, owner, "test")["you"])

    A.accept_escort_job(w, log, hand, byrole["Bodyguard"]["id"])
    crew = O.observe(w, log, owner, "test")["you"].get("your_convoy")
    ok("once hired, the employer sees its crew", crew and len(crew) == 1, str(crew))
    ok("with who, what they carry, and what they cost",
       crew and {"who", "role", "carrying", "costs"} <= set(crew[0]), str(crew))
    ok("and the escort is told who it is guarding",
       "escorting" in O.observe(w, log, hand, "test")["you"])
    ok("a bound escort is not offered more work",
       not O.observe(w, log, hand, "test").get("escort_jobs", [{}])[0].get("you_can_take_it"))


def test_a_courier_is_paid_for_what_arrives() -> None:
    """The courier picks the cart and the guards; it must have a stake.

    Before this the fee was paid in full however much was stolen, so the one
    agent who decides how safe a journey is had no reason to make it safe. That
    is why removing foot immunity alone would have changed nothing.
    """
    from convoy.state import Consignment

    w, log, agent = _world(at=LONG[0])
    seller = next(b for b in w.businesses.values() if "Mining" in b.type)
    buyer = next(b for b in w.businesses.values() if "Refinery" in b.type)
    seller.owner = agent.id
    con = Consignment(
        id="C0001", seller_business=seller.id, buyer_business=buyer.id,
        item="Copper Ore", qty=100, goods_price=0.0, courier_fee=60.0,
        origin=LONG[0], destination=LONG[1], created_at=0.0,
        seller_posted=True, qty_posted=100, seller_share=1.0,
    )
    w.consignments[con.id] = con
    ok("a whole load earns the whole fee", con.delivered_fraction() == 1.0)

    eng = Engine(w, log, Idle(), EngineConfig(duration_hours=1, speed=1e9))
    agent.hauling = con.id
    eng._rob_consignment(agent, 0.65)
    frac = con.delivered_fraction()
    ok("a robbed load earns proportionally less", 0.0 < frac < 1.0,
       f"{frac:.0%} of the load arrived")
    ok("and the fee follows it", abs(60.0 * frac - 60.0) > 1.0,
       f"earns {60.0 * frac:.2f} of 60.00")

    ok("an old consignment with no posted size still pays in full",
       Consignment(id="C9", seller_business=seller.id, buyer_business=buyer.id,
                   item="Copper Ore", qty=10, goods_price=0.0, courier_fee=20.0,
                   origin=LONG[0], destination=LONG[1],
                   created_at=0.0).delivered_fraction() == 1.0)


def test_a_dead_employer_does_not_strand_its_convoy() -> None:
    """The convoy completes and the guard gets paid, estate first, state after.

    Escorts are released on their EMPLOYER's arrival, and a corpse never
    arrives -- so before this they sat in transit with activity "convoy"
    forever, unpaid and unable to act.
    """
    w, log, owner, hand = _two()
    _give_cart(w, log, owner)
    A.post_escort_job(w, log, owner, "Bodyguard", 30.0, LONG[1])
    job = next(iter(w.escort_postings.values()))
    A.accept_escort_job(w, log, hand, job.id)
    A.travel_to(w, log, owner, LONG[1])
    ok("the escort is on the road", hand.in_transit is not None)

    eng = Engine(w, log, Idle(), EngineConfig(duration_hours=1, speed=1e9))
    owner.denari = 0.0                       # an estate that cannot pay
    treasury_before, hand_before = w.government.treasury, hand.denari
    eng._kill(owner, cause="starvation")

    ok("the escort is released", hand.escorting is None and not owner.escorts)
    ok("and is standing where the convoy was going",
       hand.location == LONG[1], hand.location)
    ok("free to act again", hand.activity.kind == "idle", hand.activity.kind)
    ok("it was paid even so", hand.denari > hand_before,
       f"{hand_before:.2f} -> {hand.denari:.2f}")
    ok("out of the treasury, the estate being empty",
       w.government.treasury < treasury_before,
       f"{treasury_before:.2f} -> {w.government.treasury:.2f}")


def test_the_state_can_withdraw_on_schedule() -> None:
    """The government closes at an appointed hour and leaves its stores behind.

    Scheduled in the engine rather than done by stopping and editing a
    checkpoint: the first attempt at this paused the run, which let a changed
    prompt in halfway and made it two experiments rather than one.
    """
    w, log, agent = _world()
    gov = [b for b in w.businesses.values() if b.is_government]
    stocked = next(b for b in gov if b.type == "Farm")
    stocked.inventory = {"Wheat": 120}
    # ON THE ROSTER, not just holding a job tuple. Closure walks the roster, so
    # an agent that only claims to work somewhere is never released -- which is
    # a fixture mistake, not a bug, but it made this test lie.
    from convoy.state import Employment
    gov[0].roster.append(Employment(agent.id, "Laborer", 15.0))
    agent.current_job = (gov[0].id, "Laborer", 15.0)

    eng = Engine(w, log, Idle(), EngineConfig(
        duration_hours=0.2, speed=1e9, checkpoint_every_hours=1e9,
        banditry=False, state_exits_at=0.05,
    ))
    ok("the state is open before the hour",
       all(not b.closed for b in gov), "")
    eng.step_until(w.sim_time + 1800.0)

    ok("every government business closed", all(b.closed for b in gov),
       f"{sum(1 for b in gov if b.closed)} of {len(gov)}")
    ok("its staff were released", agent.current_job is None)
    # At least what it held: the farm keeps producing right up to the moment it
    # shuts, so pinning an exact number tests the tick rate, not the transfer.
    ok("its stores went to the ground, not into the void",
       w.ground_loot.get(stocked.location, {}).get("items", {}).get("Wheat", 0) >= 120,
       str(w.ground_loot.get(stocked.location)))
    ok("it left no cash behind", all(b.cash == 0 for b in gov))
    ok("and its ground went back on the market",
       not any(p.owner == "Government" for p in w.plots.values()),
       f"{sum(1 for p in w.plots.values() if p.owner == 'Government')} still held")
    ok("released as raw land, not free floor space",
       not any(p.developed for p in w.plots.values() if p.owner is None))
    ok("and it was announced",
       any(e.type == "state_withdrew" for e in log.events))

    before = len(log.events)
    eng.step_until(w.sim_time + 1800.0)
    ok("it happens exactly once",
       sum(1 for e in log.events if e.type == "state_withdrew") == 1)

    quiet_w, quiet_log, _a = _world()
    Engine(quiet_w, quiet_log, Idle(), EngineConfig(
        duration_hours=0.2, speed=1e9, checkpoint_every_hours=1e9, banditry=False,
    )).step_until(quiet_w.sim_time + 1800.0)
    ok("and never at all when unscheduled",
       all(not b.closed for b in quiet_w.businesses.values() if b.is_government))


def test_the_same_seed_gives_the_same_road() -> None:
    """Banditry is the first randomness in this sim. It has to stay replayable."""
    # SEED 1 IS ONE THAT ROBS. Pinning determinism on a seed where nothing
    # happens proves only that nothing kept happening -- three identical
    # untouched loads look exactly like a working generator and like a dead
    # code path, which is the bug this file exists to catch elsewhere.
    outcomes = []
    for _ in range(3):
        w, log, agent = _world({"Copper Ore": 100}, at=LONG[0])
        _give_cart(w, log, agent)
        _drive(w, log, agent, LONG[1], seed=1)
        outcomes.append(sum(agent.inventory.values()))
    ok("three identical runs, one outcome", len(set(outcomes)) == 1, str(outcomes))
    ok("...on a road that actually robbed them", outcomes[0] < 100, f"{outcomes[0]} left")

    w2, log2, agent2 = _world({"Copper Ore": 100}, at=LONG[0])
    _give_cart(w2, log2, agent2)
    _drive(w2, log2, agent2, LONG[1], seed=99999)
    ok("a different seed is a different road",
       sum(agent2.inventory.values()) != outcomes[0],
       f"{outcomes[0]} vs {sum(agent2.inventory.values())}")

    # Off is off: the switch exists so an experiment can isolate the economy
    # from the road, and so every pre-banditry test keeps its determinism.
    off_w, off_log, off = _world({"Copper Ore": 100}, at=LONG[0])
    _give_cart(off_w, off_log, off)
    A.travel_to(off_w, off_log, off, LONG[1])
    Engine(off_w, off_log, Idle(), EngineConfig(
        duration_hours=0.5, speed=1e9, checkpoint_every_hours=1e9,
        banditry=False, banditry_seed=1,
    )).step_until(off_w.sim_time + 3600.0)
    ok("switched off, the same robbing seed takes nothing",
       sum(off.inventory.values()) == 100, f"{sum(off.inventory.values())} left")


def main() -> int:
    tests = [
        test_hiring_costs_money_and_sticks,
        test_hiring_is_refused_for_the_right_reasons,
        test_a_journey_can_actually_lose_you_goods,
        test_a_walker_can_be_robbed_through_the_engine,
        test_escorts_are_hired_for_one_journey,
        test_guards_measurably_move_the_odds,
        test_the_observation_carries_the_odds_before_the_decision,
        test_the_briefing_tells_the_truth_about_the_map,
        test_market_power_decides_who_can_insist,
        test_the_split_ladder_and_who_may_insist_on_what,
        test_the_state_never_carries_a_share,
        test_a_responsible_seller_actually_pays_up,
        test_a_courier_cannot_smuggle_its_own_goods_behind_a_job,
        test_a_robbery_takes_a_share_of_the_whole_load,
        test_a_courier_does_not_claim_for_someone_elses_goods,
        test_being_caught_can_cost_you_everything,
        test_an_npc_costs_half_again_what_a_person_does,
        test_every_role_is_open_to_agents_and_npcs_alike,
        test_hiring_an_agent_escort_end_to_end,
        test_a_lent_weapon_comes_back,
        test_driver_own_must_actually_bring_a_cart,
        test_escort_work_is_visible_to_somebody_who_could_take_it,
        test_a_courier_is_paid_for_what_arrives,
        test_the_state_can_withdraw_on_schedule,
        test_a_dead_employer_does_not_strand_its_convoy,
        test_a_robbery_never_takes_the_cart,
        test_a_lent_vehicle_comes_home_even_from_a_robbery,
        test_the_same_seed_gives_the_same_road,
    ]
    print(f"convoy system — longest road {LONG[0]} -> {LONG[1]}")
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
