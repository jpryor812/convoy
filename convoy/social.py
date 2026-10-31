"""Meeting people (designer request, 2026-10-28).

"If you find someone, and click on them -- you say hi, and players can opt to
share information with one another ... all of those can be discovered by
clicking on pre-determined actions, like in Civ ... and then there can also be
a share contact button which unlocks DMs with that player and the option to
invite them to group chats."

Finding someone (discovery.py) only shows you they exist. What you learn
about them beyond that, they choose to share -- one KIND at a time, given
freely or asked for and answered. With outposts:

- direct messages need the other's CONTACT, and so does inviting them to a
  group chat;
- public chat is heard only by people near the speaker;
- a marriage proposal needs the other house's FAMILY shared.

Worlds without outposts see everything, exactly as before.
"""

from __future__ import annotations

import math
import zlib
from typing import TYPE_CHECKING, Any

from . import discovery as DS

if TYPE_CHECKING:
    from .state import Agent, World

KINDS: dict[str, str] = {
    "standing": "net worth and rank",
    "holdings": "what they own",
    "locations": "where their land and buildings are",
    "trade": "what they are selling and buying now",
    "family": "their children, and who is of age to marry",
    "contact": "their contact: messages and group chats",
}


def sees(world: "World", viewer: "Agent", other: "Agent", kind: str) -> bool:
    """Whether `viewer` may see `kind` about `other`."""
    if not world.outposts or viewer.id == other.id:
        return True
    return kind in other.shared.get(viewer.id, [])


def share(world: "World", giver: "Agent", to: "Agent", kind: str) -> bool:
    """Record that `giver` shares `kind` with `to`. False if already shared."""
    have = giver.shared.setdefault(to.id, [])
    if kind in have:
        return False
    have.append(kind)
    return True


def contacts(world: "World", agent: "Agent") -> list[str]:
    """People whose contact `agent` holds: they shared it with `agent`."""
    return [a.id for a in world.agents.values()
            if a.id != agent.id and "contact" in a.shared.get(agent.id, [])]


def _rank(world: "World", agent: "Agent") -> tuple[int, int]:
    worth = sorted((a.net_worth(world) for a in world.agents.values() if a.alive), reverse=True)
    mine = agent.net_worth(world)
    return 1 + sum(1 for w in worth if w > mine + 1e-6), len(worth)


def places_of(world: "World", agent: "Agent") -> list[dict[str, Any]]:
    """Where an agent's home, claims and businesses are, with map metres."""
    from . import claims as CL
    out = []
    seen = set()
    rows = ([(agent.home, "home")] if agent.home else []) + [
        (world.businesses[b].location, world.businesses[b].type.split(" /")[0])
        for b in agent.owned_businesses if b in world.businesses and not world.businesses[b].closed]
    rows += [(c.name, "land") for c in world.claims.values() if c.owner == agent.id]
    for place, what in rows:
        if (place, what) in seen or not place:
            continue
        seen.add((place, what))
        xy = CL.place_xy(world, place)
        if xy:
            out.append({"place": place, "what": what, "x": round(xy[0], 1), "y": round(xy[1], 1)})
    # One row per place, the most telling label first (a business over "land").
    best: dict[str, dict[str, Any]] = {}
    for r in out:
        if r["place"] not in best or best[r["place"]]["what"] == "land":
            best[r["place"]] = r
    return list(best.values())


def view_of(world: "World", viewer: "Agent", other: "Agent") -> dict[str, Any]:
    """What `viewer` may know about `other`, by kind."""
    out: dict[str, Any] = {"id": other.id, "name": other.name, "house": other.house,
                           "found": DS.knows(world, viewer, other.id),
                           "shared": sorted(k for k in KINDS if sees(world, viewer, other, k)),
                           "they_have_from_you": sorted(viewer.shared.get(other.id, []))}
    if sees(world, viewer, other, "standing"):
        rank, of = _rank(world, other)
        out["standing"] = {"worth": round(other.net_worth(world), 1), "rank": rank, "of": of}
    if sees(world, viewer, other, "holdings"):
        kinds: dict[str, int] = {}
        for b in other.owned_businesses:
            if b in world.businesses and not world.businesses[b].closed:
                t = world.businesses[b].type.split(" /")[0]
                kinds[t] = kinds.get(t, 0) + 1
        out["holdings"] = {"businesses": kinds,
                           "plots": sum(1 for p in world.plots.values() if p.owner == other.id)}
    if sees(world, viewer, other, "locations"):
        out["locations"] = places_of(world, other)
    if sees(world, viewer, other, "trade"):
        selling = []
        for b in other.owned_businesses:
            biz = world.businesses.get(b)
            if biz is None or biz.closed:
                continue
            for item, price in biz.retail_prices.items():
                if biz.inventory.get(item, 0) > 0:
                    selling.append({"item": item, "price": round(price, 2),
                                    "qty": biz.inventory[item], "at": biz.location})
        buying = [{"item": o.item, "price": round(o.price, 2), "qty": o.qty}
                  for o in world.buy_orders.values() if o.buyer == other.id and o.status == "open"]
        out["trade"] = {"selling": selling[:12], "buying": buying[:12]}
    if sees(world, viewer, other, "family"):
        now = world.sim_time
        out["family"] = [{"id": m.id, "name": m.name, "sex": m.sex, "role": m.role,
                          "grown": m.adult, "married": bool(m.spouse),
                          "grows_in_hours": (None if m.adult or not m.grown_at
                                             else round(max(0.0, (m.grown_at - now) / 3600), 1))}
                         for m in other.family]
    out["contact"] = sees(world, viewer, other, "contact")
    # Their answer to what you asked and did not get (2026-10-30): no, or their
    # price -- worked out now, so it follows anything you have traded since.
    asked = {r.kind for r in world.share_requests.values()
             if r.sender == viewer.id and r.target == other.id and r.status in ("priced", "declined")}
    out["terms"] = {k: terms(world, other, viewer, k) for k in sorted(asked) if not sees(world, viewer, other, k)}
    out["temper"] = temper(other) if other.id != world.human else ""
    return out


def hearers(world: "World", agent: "Agent") -> list[str]:
    """Who hears `agent` speak in public: everyone at the same place or
    within sight. Used for public chat with outposts."""
    me = DS.position(world, agent)
    out = []
    for a in world.agents.values():
        if a.id == agent.id or not a.alive:
            continue
        if a.location == agent.location and not a.in_transit and not agent.in_transit:
            out.append(a.id)
            continue
        p = DS.position(world, a)
        if me and p and math.hypot(me[0] - p[0], me[1] - p[1]) <= DS.SIGHT_M:
            out.append(a.id)
    return out


# ---------------------------------------------------------------------------
# WHAT IT TAKES (designer request, 2026-10-30)
# ---------------------------------------------------------------------------
#
# "Maybe it would be better if they're more deterministic in sharing info ...
# and maybe sometimes require me to negotiate with the AIs, such as not
# sharing their location, but I can offer them some resources to sell to them
# at a good price for information." Settlers answer at once, by rule, not by
# model: some things they share freely, some they will not, and for some they
# name a price -- in coins, or in goods they need sold to them cheap.

INFO_PRICE = {"contact": 20.0, "holdings": 25.0, "locations": 40.0}
GUARDED_MARKUP = 1.5            # a guarded house asks half as much again
TRADED_DISCOUNT = 0.5           # ... and anyone halves it for a trading partner
DEAL_SHARE = 0.5                # goods for information are sold at half of book


def temper(agent: "Agent") -> str:
    """Open or guarded: one house in three keeps itself to itself. Fixed by
    who they are, so the same settler answers the same way every time."""
    return "guarded" if zlib.crc32(agent.id.encode()) % 3 == 0 else "open"


def traded(world: "World", a: "Agent", b: "Agent") -> bool:
    """Whether two houses have ever traded, either way round."""
    mine = {a.id, *a.owned_businesses}
    theirs = {b.id, *b.owned_businesses}
    return any((t.seller in mine and t.buyer in theirs) or (t.seller in theirs and t.buyer in mine)
               for t in world.market.transactions)


def _marriageable(world: "World", agent: "Agent") -> bool:
    soon = world.sim_time + 48 * 3600.0
    return any(m.role != "partner" and not m.spouse and (m.adult or (m.grown_at and m.grown_at <= soon))
               for m in agent.family)


def wants(world: "World", agent: "Agent") -> list[str]:
    """Goods a settler would take cheap: what its businesses use, then meals."""
    from . import data as D
    out: list[str] = []
    for b in agent.owned_businesses:
        biz = world.businesses.get(b)
        if biz is None or biz.closed:
            continue
        for out_item in [biz.active_production] if biz.active_production else []:
            r = D.REFINING_RECIPES.get(out_item) or D.CRAFTING_RECIPES.get(out_item)
            if r:
                out += [i for i in r.inputs if i not in out]
    return out + [m for m in ("Meal",) if m not in out]


def holding(world: "World", agent: "Agent", item: str) -> int:
    """How many of `item` a settler has: carried, and in its businesses."""
    n = agent.inventory.get(item, 0)
    for b in agent.owned_businesses:
        biz = world.businesses.get(b)
        if biz is not None and not biz.closed:
            n += biz.inventory.get(item, 0)
    return n


def terms(world: "World", holder: "Agent", asker: "Agent", kind: str) -> dict[str, Any]:
    """What `holder` wants before sharing `kind` with `asker`: {"free": why},
    {"no": why}, or {"price": coins, "goods": a cheap sale it would take
    instead (or None), "why": ...}."""
    from . import data as D
    if kind in asker.shared.get(holder.id, []):
        return {"free": "you shared yours"}
    if kind == "family":
        return ({"free": "they have someone to marry"} if _marriageable(world, holder)
                else {"no": "they have nobody of an age to marry yet"})
    if kind in ("standing", "trade"):
        return {"free": "nothing to hide"}
    guarded = temper(holder) == "guarded"
    partners = traded(world, holder, asker)
    if kind == "contact" and (not guarded or partners):
        return {"free": "glad to keep in touch"}
    if kind == "holdings" and not guarded:
        return {"free": "nothing to hide"}
    price = INFO_PRICE.get(kind, 20.0) * (GUARDED_MARKUP if guarded else 1.0)
    if partners:
        price *= TRADED_DISCOUNT
    price = float(round(price))
    goods = None
    have = [(i, holding(world, asker, i)) for i in wants(world, holder) if D.base_price(i) > 0]
    pick = max(have, key=lambda x: x[1] * D.base_price(x[0]), default=None)
    if pick:
        item = pick[0]
        book = D.base_price(item)
        unit = round(book * DEAL_SHARE, 2)
        qty = max(1, math.ceil(price / max(0.01, book - unit)))
        goods = {"item": item, "qty": qty, "unit": unit, "book": round(book, 2), "you_have": pick[1]}
    why = ("they keep to themselves" if guarded else "they would want something for it") + \
          (", though less from a trading partner" if partners else "")
    return {"price": price, "goods": goods, "why": why}


def describe_terms(holder: "Agent", kind: str, t: dict[str, Any]) -> str:
    if "free" in t:
        return f"{holder.name} shares their {kind} freely"
    if "no" in t:
        return f"{holder.name} will not share their {kind}: {t['no']}"
    g = t.get("goods")
    deal = (f", or sell them {g['qty']} {g['item']} at {g['unit']:.2f} each (book {g['book']:.2f})"
            if g else "")
    return (f"{holder.name} will share their {kind} for {t['price']:.0f} coins{deal} -- {t['why']}. "
            f"offer_for_info to pay")
