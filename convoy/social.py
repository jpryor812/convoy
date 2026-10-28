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
