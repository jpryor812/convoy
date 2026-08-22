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
from . import economy as E
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


# ---------------------------------------------------------------------------
# The three boards -- for people watching, not for agents
# ---------------------------------------------------------------------------
#
# Same rule as the cards above: ONE assembler, two consumers. The static page
# bakes these in and `serve.py` serves the same shapes, because two summaries of
# the same valley drift and the one somebody reads is whichever they opened.
#
# Unlike the cards, these are a SPECTATOR's view rather than an agent's. A card
# shows what one person could learn by walking up and asking; a leaderboard
# shows what nobody in the world can see. That is fine -- it is for the person
# at the keyboard, and none of it is ever put in a prompt.


def leaderboard(world: World) -> list[dict[str, Any]]:
    """Every agent, richest first, with where the money actually is.

    Net worth alone says who is winning and nothing about how, and "how" is the
    interesting half: 3,000 in cash and 3,000 tied up in a mine that cannot
    make payroll are the same number and completely different situations.
    """
    ranks = rankings(world)
    rows = []
    for agent in world.agents.values():
        businesses = [
            world.businesses[b] for b in agent.owned_businesses
            if b in world.businesses and not world.businesses[b].closed
        ]
        goods = E.inventory_value(agent.inventory)
        biz_value = sum(b.valuation(world) if hasattr(b, "valuation") else b.cash
                        for b in businesses)
        vehicles = [world.vehicles[v].type for v in agent.owned_vehicles
                    if v in world.vehicles]
        rank, worth = ranks.get(agent.id, (0, 0.0))
        rows.append({
            "id": agent.id,
            "name": agent.name,
            "model": agent.model,
            "rank": rank,
            "net_worth": round(worth, 2),
            "alive": agent.alive,
            "location": agent.location,
            "doing": doing_phrase(agent),
            "job": (
                f"{agent.current_job[1]} at "
                f"{world.businesses[agent.current_job[0]].name}"
                if agent.current_job and agent.current_job[0] in world.businesses
                else None
            ),
            "wage": round(agent.current_job[2], 2) if agent.current_job else None,
            "assets": {
                "cash": round(agent.denari, 2),
                "goods": round(goods, 2),
                "businesses": round(biz_value, 2),
                "vehicles": round(sum(D.base_price(v) for v in vehicles), 2),
                # `assessed_value` is what `Agent.net_worth` itself uses, so the
                # breakdown adds up to the ranked total instead of nearly to it.
                "property": round(
                    world.properties[agent.owned_property].assessed_value()
                    if agent.owned_property in world.properties else 0.0, 2
                ),
            },
            "businesses": [{"name": b.name, "type": b.type, "place": b.location,
                            "cash": round(b.cash, 2)} for b in businesses],
            "vehicles": vehicles,
            "has_home": bool(agent.owned_property),
        })
    rows.sort(key=lambda r: -r["net_worth"])
    return rows


def commodity_prices(world: World, window_hours: float | None = None) -> list[dict[str, Any]]:
    """The public ticker, busiest first. Anonymous -- see `economy.ticker`."""
    quotes = E.ticker(
        world, window_hours if window_hours is not None else E.TICKER_WINDOW_HOURS
    )
    rows = [
        {
            "item": q.item, "vwap": q.vwap, "last": q.last, "high": q.high,
            "low": q.low, "volume": q.volume, "trades": q.trades,
            "book": q.base, "premium": round(q.premium, 4),
            "last_hour": q.last_hour,
        }
        for q in quotes.values()
    ]
    rows.sort(key=lambda r: -r["volume"])
    return rows


def convoy_schedule(world: World, events: list | None = None) -> dict[str, Any]:
    """Loads on the road now, and how the ones already run turned out.

    The history is read off the EVENT LOG rather than off live consignments,
    because a delivered consignment is the only record that it ever existed and
    a robbed one leaves no trace in the world state at all. `robbed`,
    `consignment_posted`, `consignment_delivered` and `escort_hired` between
    them carry the value, the vehicle, the guard count and the outcome.
    """
    live = []
    for con in world.consignments.values():
        if con.status not in ("awaiting_courier", "claimed"):
            continue
        courier = world.agents.get(con.courier) if con.courier else None
        live.append({
            "id": con.id, "item": con.item, "qty": con.qty,
            "value": round(D.base_price(con.item) * con.qty, 2),
            "from": con.origin, "to": con.destination,
            "fee": round(con.courier_fee, 2),
            "status": con.status,
            "courier": courier.name if courier else None,
            "convoy_split": con.split_label(),
            "vehicle_lent": con.lent_vehicle and world.vehicles[con.lent_vehicle].type
                            if con.lent_vehicle in world.vehicles else None,
            "posted_hour": round(con.created_at / 3600.0, 2),
        })
    live.sort(key=lambda r: r["posted_hour"])

    history: list[dict[str, Any]] = []
    for ev in events or []:
        if ev.type not in ("consignment_delivered", "robbed"):
            continue
        d = ev.detail
        if ev.type == "robbed":
            history.append({
                "hour": round(ev.sim_hour, 2), "outcome": "robbed",
                "actor": ev.actor, "route": f"{d.get('origin')} to {d.get('destination')}",
                "where": d.get("segment"), "value": d.get("value_lost"),
                "share_lost": d.get("fraction"), "vehicle": d.get("vehicle"),
                "escorts": d.get("escorts"), "risk": d.get("risk"),
                "cargo": d.get("cargo"),
            })
        else:
            history.append({
                "hour": round(ev.sim_hour, 2), "outcome": "delivered",
                "actor": ev.actor, "route": None, "where": ev.location,
                "value": round(D.base_price(d["item"]) * d["qty"], 2)
                         if d.get("item") in D.ALL_ITEMS else None,
                "units": d.get("qty"), "item": d.get("item"),
                "fee": d.get("fee"),
            })
    history.sort(key=lambda r: -r["hour"])

    delivered = sum(1 for h in history if h["outcome"] == "delivered")
    robbed = sum(1 for h in history if h["outcome"] == "robbed")
    return {
        "live": live,
        "history": history[:200],
        "totals": {
            "delivered": delivered,
            "robbed": robbed,
            "value_lost": round(sum(h["value"] or 0 for h in history
                                    if h["outcome"] == "robbed"), 2),
            "success_rate": round(delivered / max(1, delivered + robbed), 3),
        },
    }


def advice_report(world: World, events: list | None = None) -> list[dict[str, Any]]:
    """Every piece of advice, whether it landed, and what happened after.

    THIS IS THE TEACHING ARTEFACT, and the reason `Snapshot` is taken at the
    instant advice is given rather than reconstructed later: after the fact
    there is no way to recover what the valley looked like at hour 44.

    Two things it separates that look identical from outside:

      * "IT IGNORED ME" -- the agent read the advice and did something else.
      * "IT NEVER HEARD ME" -- the words never entered a prompt. `times_seen`
        is written by `observe.py` at the moment text enters a prompt and by
        nothing else, so a zero here is a fact about delivery, not a judgement
        about obedience. Six recommendations once expired unseen this way
        (PHASE4 §2, fourteenth entry).

    And it scores against THE FIELD, not against the agent alone. An agent whose
    net worth rose 200 in a valley that all rose 200 was not helped; the whole
    leaderboard is captured precisely so that subtraction is possible.
    """
    ranks = rankings(world)
    outcomes: dict[str, list[dict]] = {}
    for ev in events or []:
        if ev.type == "advice_outcome":
            outcomes.setdefault(ev.detail.get("advice_id"), []).append(ev.detail)

    rows: list[dict[str, Any]] = []
    for agent in world.agents.values():
        for rec in agent.inbox:
            before = rec.before
            now_rank, now_worth = ranks.get(agent.id, (0, 0.0))
            then_worth = (before.net_worth or {}).get(agent.id) if before else None
            # Where the agent stood in the pack when the advice landed.
            then_rank = None
            if before and before.net_worth:
                order = sorted(before.net_worth.items(), key=lambda kv: -kv[1])
                for i, (aid, _w) in enumerate(order, 1):
                    if aid == agent.id:
                        then_rank = i
            # What EVERYONE ELSE did over the same stretch, so a rising tide is
            # not mistaken for good advice.
            field = None
            if before and before.net_worth:
                moves = [
                    ranks[a][1] - w for a, w in before.net_worth.items()
                    if a in ranks and a != agent.id
                ]
                if moves:
                    field = round(sorted(moves)[len(moves) // 2], 2)
            gained = round(now_worth - then_worth, 2) if then_worth is not None else None
            acted = outcomes.get(rec.id, [])
            rows.append({
                "id": rec.id,
                "agent": agent.name,
                "agent_id": agent.id,
                "from_who": rec.from_who,
                "text": rec.text,
                "hour": round(rec.given_at_hour, 2),
                "heard": rec.times_seen > 0,
                "times_seen": rec.times_seen,
                "first_seen_hour": rec.first_seen_hour,
                "rank_then": then_rank,
                "rank_now": now_rank,
                "worth_then": round(then_worth, 2) if then_worth is not None else None,
                "worth_now": round(now_worth, 2),
                "gained": gained,
                "field_gained": field,
                # Beat the field, or merely floated up with it.
                "beat_field": (None if gained is None or field is None
                               else round(gained - field, 2)),
                "did_after": [a.get("did") for a in acted if a.get("did")][:3],
            })
    rows.sort(key=lambda r: r["hour"])
    return rows


def boards(world: World, events: list | None = None) -> dict[str, Any]:
    """All three, for whichever consumer is asking."""
    return {
        "leaderboard": leaderboard(world),
        "commodities": commodity_prices(world),
        "convoys": convoy_schedule(world, events),
        "advice": advice_report(world, events),
    }
