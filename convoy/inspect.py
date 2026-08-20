"""What a viewer sees when they click something on the map.

ONE ASSEMBLER, TWO CONSUMERS. `preview_world.py` bakes these into a static page
and the live server serves the same shapes over HTTP. Written once here because
the alternative -- the map building its own summary and the server building
another -- is two descriptions of the same business that drift apart, and the
one a student reads is whichever they happened to open.

NOTHING IS COMPUTED HERE THAT THE WORLD DOES NOT ALREADY KNOW. Every field is a
read off `state`: stock is `Business.inventory`, prices are `retail_prices`,
staff are `roster`, vacancies are the live `JobPosting`s. The job of this module
is joining them -- an inventory dict and a price dict are two halves of "what is
it selling and for how much", and no single object holds both.

WHAT IS DELIBERATELY NOT SHOWN. A business card does not carry its owner's cash,
and an agent card does not carry another agent's plans. The map is a public
view: it shows what someone standing in the street could see -- who owns the
place, what is on the shelf, what it pays, who is working. Anything private is
something to ASK the agent about, which is what the chat box is for, and the
agent can decline.
"""

from __future__ import annotations

from typing import Any

from . import data as D
from .state import Agent, Business, World


def doing_phrase(agent: Agent) -> str:
    """What an agent is doing, in words rather than an activity kind.

    The canonical version. `live.LiveSession.status` calls this rather than
    keeping its own copy -- two phrasings of the same activity is exactly the
    kind of drift that makes a status panel and a status feed disagree about
    whether somebody is working or travelling.
    """
    detail = agent.activity.detail or {}
    kind = agent.activity.kind
    if kind == "work" and detail.get("role"):
        return f"working as {detail['role']}"
    if kind == "travel" and agent.in_transit:
        return f"travelling to {agent.in_transit[1]}"
    if kind == "idle":
        return "idle"
    return kind


def _staff(world: World, biz: Business) -> list[dict[str, Any]]:
    """Everyone on the payroll, and what each is doing right now."""
    out = []
    for job in biz.roster:
        if job.is_npc:
            out.append({
                "who": "a hired hand", "id": None, "role": job.role,
                "wage": round(job.wage, 2), "doing": "on shift", "npc": True,
            })
            continue
        agent = world.agents.get(job.agent_id)
        out.append({
            "who": agent.name if agent else job.agent_id,
            "id": job.agent_id,
            "role": job.role,
            "wage": round(job.wage, 2),
            # An employee can be anywhere -- on a shift, on the road, or asleep
            # at home. Reporting the roster without it implies everyone is at
            # their post, which is the thing a viewer most wants to check.
            "doing": doing_phrase(agent) if agent else "unknown",
            "npc": False,
        })
    return out


def business_card(world: World, biz: Business) -> dict[str, Any]:
    """The public face of one business."""
    owner = world.agents.get(biz.owner)
    stock = []
    for item, qty in sorted(biz.inventory.items()):
        if qty <= 0:
            continue
        stock.append({
            "item": item,
            "qty": qty,
            # None means "holds it but is not selling it", which is a real and
            # visible state: stock with no price is stock nobody can buy.
            "price": round(biz.retail_prices[item], 2)
                     if item in biz.retail_prices else None,
        })

    jobs = [
        {
            "role": p.role,
            "wage": round(p.wage, 2),
            "applicants": len(p.applicants),
            "hours_open": round(p.hours_open(world.sim_time), 1),
            "researcher": p.as_researcher,
        }
        for p in world.job_postings.values()
        if p.business_id == biz.id and p.is_live(world.sim_time)
    ]

    return {
        "kind": "business",
        "id": biz.id,
        "name": biz.name or biz.type,
        "type": biz.type,
        "place": biz.location,
        "owner": "the state" if owner is None else owner.name,
        "owner_id": None if owner is None else owner.id,
        "owner_doing": None if owner is None else doing_phrase(owner),
        "government": owner is None,
        "cash": round(biz.cash, 2),
        "producing": biz.active_production,
        "blocked": biz.production_blocked,
        "closed": biz.closed,
        "plots": biz.plots,
        "stock": stock,
        "staff": _staff(world, biz),
        "jobs": jobs,
    }


def rankings(world: World) -> dict[str, tuple[int, float]]:
    """agent id -> (rank by net worth, net worth). Rank 1 is richest."""
    scored = sorted(
        ((a.id, a.net_worth(world)) for a in world.agents.values() if a.alive),
        key=lambda kv: -kv[1],
    )
    return {aid: (i + 1, worth) for i, (aid, worth) in enumerate(scored)}


def agent_card(world: World, agent: Agent,
               ranks: dict[str, tuple[int, float]] | None = None) -> dict[str, Any]:
    """The public face of one agent, plus where they stand."""
    ranks = rankings(world) if ranks is None else ranks
    rank, worth = ranks.get(agent.id, (0, 0.0))

    businesses = [
        {
            "id": b, "name": world.businesses[b].name or world.businesses[b].type,
            "type": world.businesses[b].type,
            "place": world.businesses[b].location,
        }
        for b in agent.owned_businesses if b in world.businesses
    ]
    return {
        "kind": "agent",
        "id": agent.id,
        "name": agent.name,
        "model": agent.model,
        "alive": agent.alive,
        "at": agent.location,
        "doing": doing_phrase(agent),
        "travel_progress": agent.in_transit[2] if agent.in_transit else None,
        "denari": round(agent.denari, 2),
        # Net worth is cash plus goods plus businesses plus vehicles plus
        # property -- see `Agent.net_worth`. Shown with the rank because the
        # number alone says nothing: 4,000 is either winning or last.
        "net_worth": round(worth, 2),
        "rank": rank,
        "of": len(ranks),
        "carrying": {k: v for k, v in sorted(agent.inventory.items()) if v > 0},
        "vehicles": [world.vehicles[v].type for v in agent.owned_vehicles
                     if v in world.vehicles],
        "businesses": businesses,
        "employed_by": [
            {"business": b.name or b.type, "role": job.role,
             "wage": round(job.wage, 2)}
            for b in world.businesses.values()
            for job in b.roster
            if job.agent_id == agent.id
        ],
        "has_home": agent.owned_property is not None,
    }


def cards(world: World) -> dict[str, dict[str, Any]]:
    """Every clickable thing in the world, keyed by id.

    Assembled in one pass so a page can embed the lot and open a panel without
    another round trip -- at twenty agents and a few dozen businesses the whole
    thing is a few tens of kilobytes, far cheaper than a request per click.
    """
    ranks = rankings(world)
    out: dict[str, dict[str, Any]] = {}
    for biz in world.businesses.values():
        out[biz.id] = business_card(world, biz)
    for agent in world.agents.values():
        out[agent.id] = agent_card(world, agent, ranks)
    return out
