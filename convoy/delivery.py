"""Delivery runs: take goods to a buyer yourself, for more than the gate pays.

Designer request, 2026-10-18: "I'm stuck on what to do while I'm making goods.
Right now I'm just waiting for them to be produced to sell them. I think the
convoy action should happen early on, as in I should deliver them." After a
first farm and a first sale the game went quiet: a timer to watch and a Sell
button. A delivery is the thing to DO in that time -- load the donkey, ride out,
find the buyer, get paid -- and it is what the game is named for.

A DELIVERY OFFER is a buyer who wants goods brought to their door:

  * a citizen's business short of an input pays its standing bid plus a
    delivery premium (it saves them a courier);
  * the state's site in each town pays full book price for what it uses in
    another town, and less in your own -- against 0.4x for goods sold at its
    gate. Distance is what you are paid for.

Taking one moves the goods onto you (your donkey carries ten) as soon as you
are at the business that holds them; walking into the buyer's place hands
them over and pays you. What you carry can be raided on the road.

The buyer is only hinted at: which town, and roughly where. The page draws a
circle there and reveals the exact building when you ride into it.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from . import actions as A
from . import discovery as DS
from . import data as D
from . import economy as E
from . import world_map as M
from .events import Significance
from .state import Transaction

if TYPE_CHECKING:
    from .events import EventLog
    from .state import Agent, World

CITIZEN_PREMIUM = 1.20         # a citizen pays this times its bid for goods at its door
STATE_AWAY = 1.10              # the state's price, times book, in another town
STATE_HOME = 0.75              # ... and in your own
MAX_QTY = 20


def _uses(biz, item: str) -> bool:
    return any((r := (D.REFINING_RECIPES.get(o) or D.CRAFTING_RECIPES.get(o))) and item in r.inputs
               for o in (biz.spec.outputs or ()))


def offers(world: "World", agent: "Agent") -> list[dict[str, Any]]:
    """Every delivery this citizen could take now, for goods their businesses
    hold or make, best paying first."""
    mine = [world.businesses[b] for b in agent.owned_businesses
            if b in world.businesses and not world.businesses[b].closed]
    goods: dict[str, tuple[str, int]] = {}
    for b in mine:
        for item in set(b.spec.outputs or ()) | {i for i, q in b.inventory.items() if q > 0}:
            have = b.inventory.get(item, 0)
            if item not in goods or have > goods[item][1]:
                goods[item] = (b.id, have)
    home = world.city_of(agent)
    out = []
    for item, (src, have) in goods.items():
        state_towns: set[str] = set()
        # The state's site in each town that uses the good, else its store.
        state_sites = sorted((b for b in world.businesses.values() if b.is_government and not b.closed),
                             key=lambda b: (not _uses(b, item), b.type != "Tavern / Inn"))
        for biz in [b for b in world.businesses.values() if not b.is_government] + state_sites:
            if biz.closed or biz.owner == agent.id or M.city_of(biz.location) not in world.cities:
                continue
            if not DS.business_known(world, agent, biz):     # outposts: only people you have found
                continue
            if biz.is_government:
                if M.city_of(biz.location) in state_towns:
                    continue
                state_towns.add(M.city_of(biz.location))
                far = M.city_of(biz.location) != home
                unit = D.base_price(item) * (STATE_AWAY if far else STATE_HOME)
                qty = MAX_QTY
            else:
                bid = A.standing_bid(world, biz, item)
                if bid is None:
                    continue
                unit, qty = bid[0] * CITIZEN_PREMIUM, min(bid[1], MAX_QTY)
            out.append({
                "buyer": biz.id, "type": biz.type, "item": item, "unit": round(unit, 2),
                "qty": qty, "from": src, "have": have, "place": biz.location,
                "city": M.city_of(biz.location), "city_name": M.CITIES[M.city_of(biz.location)].name,
                "state": biz.is_government,
                "owner": "the state" if biz.is_government else world.agents[biz.owner].name,
                "gate": E.state_price(world, item),
            })
    out.sort(key=lambda o: -o["unit"])
    return out


def take(world: "World", log: "EventLog", agent: "Agent", business_id: str,
         buyer_business_id: str, item: str, qty: int = 0) -> tuple[bool, str]:
    """Take a delivery. The price is fixed now; the goods load when you are at
    your business (at once, if you are there)."""
    if agent.delivery:
        return False, "you are already on a delivery: finish it first"
    match = next((o for o in offers(world, agent)
                  if o["buyer"] == buyer_business_id and o["item"] == item), None)
    if match is None:
        return False, f"that buyer is not taking {item} delivered now"
    src = world.businesses.get(business_id)
    if not src or src.owner != agent.id:
        return False, "not your business"
    have = src.inventory.get(item, 0)
    if have <= 0:
        return False, f"your {src.type.split(' /')[0]} has no {item} yet: make some first"
    room = agent.carry_capacity(world) - agent.carried_units()
    want = min(int(qty) if qty and qty > 0 else match["qty"], match["qty"], room, have)
    if want <= 0:
        return False, f"you have no room: you carry {agent.carried_units()} of {agent.carry_capacity(world)}"
    agent.delivery = {"buyer": buyer_business_id, "item": item, "qty": want,
                      "unit": match["unit"], "from": business_id, "loaded": False,
                      "place": match["place"], "city": match["city"], "taken_at": world.sim_time}
    log.emit(world.sim_time, "delivery_taken", actor=agent.id, subject=buyer_business_id,
             item=item, qty=want, unit=match["unit"], place=match["place"])
    msg = (f"Deliver {want} {item} to a {match['type'].split(' /')[0]} in {match['city_name']} "
           f"for {match['unit'] * want:.0f}.")
    loaded = load(world, log, agent)
    return True, msg + (f" {loaded}" if loaded else
                        f" Ride to your {src.type.split(' /')[0]} at {src.location}: it loads the moment you arrive.")


def load(world: "World", log: "EventLog", agent: "Agent") -> str:
    """Load the delivery's goods if you stand at the business holding them."""
    d = agent.delivery
    if not d or d["loaded"]:
        return ""
    src = world.businesses.get(d["from"])
    if src is None or agent.location != src.location or agent.in_transit:
        return ""
    # The state's goods (a mission) are handed over without limit.
    have = d["qty"] if src.is_government else src.inventory.get(d["item"], 0)
    if have <= 0:
        return f"Your {src.type.split(' /')[0]} has no {d['item']} yet."
    n = min(have, d["qty"])
    if not src.is_government:
        src.remove_item(d["item"], n)
    agent.add_item(d["item"], n)
    d["qty"], d["loaded"] = n, True
    log.emit(world.sim_time, "delivery_loaded", actor=agent.id, item=d["item"], qty=n)
    return f"Loaded {n} {d['item']}: ride to {M.CITIES[d['city']].name}."


def complete(world: "World", log: "EventLog", agent: "Agent") -> str:
    """Hand over and get paid, if you are at the buyer's place with the goods."""
    d = agent.delivery
    if not d or not d["loaded"] or agent.in_transit:
        return ""
    buyer = world.businesses.get(d["buyer"])
    if buyer is None or buyer.closed:
        agent.delivery = None
        return "The buyer has closed; the goods are still yours to sell."
    if agent.location != buyer.location:
        return ""
    n = min(agent.inventory.get(d["item"], 0), d["qty"])
    if n <= 0:
        agent.delivery = None
        return "You no longer have the goods: the delivery is off."
    total = round(d["unit"] * n, 2)
    if buyer.is_government:
        world.government.treasury -= total
    else:
        owner = world.agents.get(buyer.owner)
        if owner is None or A._pay_for_business(buyer, owner, total):
            return f"{buyer.name} cannot pay {total:.0f} right now; keep the goods or sell them elsewhere."
    agent.remove_item(d["item"], n)
    buyer.add_item(d["item"], n)
    agent.denari += total
    A._record_trade(world, log, Transaction(world.sim_time, d["item"], n, d["unit"], agent.id, buyer.id,
                                            city=M.city_of(buyer.location)), "direct", buyer.location)
    log.emit(world.sim_time, "delivered", actor=agent.id, subject=buyer.id,
             significance=Significance.MEDIUM, item=d["item"], qty=n, paid=total,
             minutes=round((world.sim_time - d["taken_at"]) / 60.0))
    agent.delivery = None
    line = f"Delivered {n} {d['item']} to {buyer.name}: +{total:.0f}."
    # A mission completed by this delivery (convoy/missions.py).
    # Achievements this delivery earns (convoy/missions.py).
    from . import missions as MI
    src = world.businesses.get(d.get("from", ""))
    if (MI.is_active(world, agent, "harvest") and buyer.type == "Refinery" and src is not None
            and src.owner == agent.id and src.type in ("Farm", "Mining Operation")):
        line = MI.finish(world, log, agent, "harvest", line)
    elif MI.is_active(world, agent, "citizen") and not buyer.is_government:
        line = MI.finish(world, log, agent, "citizen", line)
    return line
