"""The player's advisors: what to do next, how they are doing, and what is where.

Designer request, 2026-10-17, after the first 3D playtest: "it is not
intuitive what I can do and how", and no way to see how you are performing.
Everything here is RULES over the world and the event log -- no model calls,
nothing the agents could not also have worked out from their own
observations. It is the strategy game's advisor screen, not a cheat.

  ledger    the numbers: net worth and rank over time, income, each business's
            takings and costs, you against the average, the best and the worst
  advice    one to three next moves, each with the button that does it
  goals     the first day's checklist, which teaches the game by playing it
  chains    what makes what, what it costs to build, what it sells for
  markers   what you can do at each building right now, and how yours are doing
  report    the end-of-day summary

`History` is the one piece of state: an hourly snapshot of everyone's worth,
cash and rank, which the ledger's charts and the per-hour figures read.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from . import actions as A
from . import data as D
from . import economy as E
from . import world_map as M

if TYPE_CHECKING:
    from .events import EventLog
    from .state import Agent, Business, World

FOOD_CHAIN = ("Wheat", "Dirty Water", "Grain", "Purified Water", "Meal")


# ---------------------------------------------------------------------------
# History
# ---------------------------------------------------------------------------

@dataclass
class History:
    """One row per game hour: every agent's [worth, cash, rank], every
    business's value. Small: 50 agents for a game week is a few hundred KB."""

    rows: list[dict[str, Any]] = field(default_factory=list)

    def record(self, world: "World") -> None:
        hour = int(world.sim_hour)
        if self.rows and self.rows[-1]["hour"] >= hour:
            return
        worth = {a.id: a.net_worth(world) for a in world.agents.values()}
        # Competition ranking: equals share a rank, as on the leaderboard.
        rank = {k: 1 + sum(1 for v in worth.values() if v > worth[k] + 1e-6) for k in worth}
        self.rows.append({
            "hour": hour,
            "agents": {a.id: [round(worth[a.id], 1), round(a.denari, 1), rank[a.id]]
                       for a in world.agents.values()},
            "biz": {b.id: round(b.valuation(world), 1) for b in world.businesses.values()
                    if not b.closed and not b.is_government},
        })

    def series(self, agent_id: str) -> list[list[float]]:
        return [[r["hour"], *r["agents"][agent_id]] for r in self.rows if agent_id in r["agents"]]

    def back(self, hours: float) -> dict[str, Any] | None:
        """The row about `hours` before the latest, or the oldest there is."""
        if not self.rows:
            return None
        want = self.rows[-1]["hour"] - hours
        best = self.rows[0]
        for r in self.rows:
            if r["hour"] <= want:
                best = r
        return best

    def to_json(self) -> list[dict[str, Any]]:
        return self.rows

    @classmethod
    def from_json(cls, rows: list[dict[str, Any]] | None) -> "History":
        return cls(rows=list(rows or []))


# ---------------------------------------------------------------------------
# Business books
# ---------------------------------------------------------------------------

_FOUNDED: dict[str, float] = {}


def founded_at(log: "EventLog", biz_id: str) -> float:
    """When a business was founded, from the log; remembered, because the
    ledger asks every few seconds and the log only grows."""
    if biz_id not in _FOUNDED:
        _FOUNDED[biz_id] = next((e.sim_time for e in log.events
                                 if e.type == "business_founded" and e.subject == biz_id), 0.0)
    return _FOUNDED[biz_id]


def business_books(world: "World", log: "EventLog", biz: "Business", hours: float = 24.0) -> dict[str, Any]:
    """Takings, supplies and wages over the last `hours`, from the log.

    The log has every sale by name, and every shift with its length; wages are
    the shift hours times the worker's rate. Not an audited P&L -- a business
    founded an hour ago has an hour of books -- but the right shape, and the
    same numbers anybody could add up from the trade board."""
    since = world.sim_time - hours * 3600.0
    revenue = supplies = wages = 0.0
    sold: dict[str, int] = defaultdict(int)
    rates = {e.agent_id: e.wage for e in biz.roster}
    for e in reversed(log.events):
        if e.sim_time < since:
            break
        d = e.detail
        if e.type == "sale":
            if d.get("seller") == biz.id:
                revenue += d.get("total") or 0.0
                sold[d.get("item")] += d.get("qty") or 0
            elif d.get("buyer") == biz.id:
                supplies += d.get("total") or 0.0
        elif e.type == "job_started" and e.subject == biz.id:
            wages += (d.get("hours") or 0.0) * rates.get(e.actor, 0.0)
    profit = revenue - supplies - wages
    cost = biz.spec.startup_cost if biz.spec else 0.0
    open_hours = max(1.0, min(hours, (world.sim_time - founded_at(log, biz.id)) / 3600.0))
    return {
        "id": biz.id, "type": biz.type, "location": biz.location,
        "revenue": round(revenue, 2), "supplies": round(supplies, 2), "wages": round(wages, 2),
        "profit": round(profit, 2), "profit_per_hour": round(profit / open_hours, 2),
        "cost": cost, "return_pct": round(100.0 * profit / cost, 1) if cost else 0.0,
        "value": round(biz.valuation(world), 1), "cash": round(biz.cash, 2),
        "sold": dict(sold), "staff": len(biz.roster), "health": health(world, biz, profit),
    }


def health(world: "World", biz: "Business", profit: float) -> str:
    """good: making and selling at a profit. idle: nothing happening.
    bad: stalled, unpaid staff, or losing money."""
    if biz.insolvent_since is not None:
        return "bad"
    making = biz.active_production
    staffed = biz.is_staffed(world)
    if profit < -1.0:
        return "bad"
    if making and staffed and profit > 0.5:
        return "good"
    if making and staffed:
        return "idle" if profit <= 0.5 else "good"
    return "idle"


# ---------------------------------------------------------------------------
# The ledger
# ---------------------------------------------------------------------------

def ledger(world: "World", log: "EventLog", me: "Agent", history: History) -> dict[str, Any]:
    """Every number a player needs to know whether they are winning."""
    agents = [a for a in world.agents.values()]
    worth = {a.id: a.net_worth(world) for a in agents}
    rank = 1 + sum(1 for v in worth.values() if v > worth[me.id] + 1e-6)

    def plots(a): return sum(1 for q in world.plots.values() if q.owner == a.id)
    def staff(a): return sum(len([e for e in world.businesses[b].roster if e.agent_id != a.id])
                             for b in a.owned_businesses if b in world.businesses)
    def stock(a): return E.realizable_value(world, a.inventory, M.city_of(a.location))
    def income(a):
        back = history.back(4)
        if not back or a.id not in back["agents"]:
            return 0.0
        span = max(1, history.rows[-1]["hour"] - back["hour"])
        return (worth[a.id] - back["agents"][a.id][0]) / span

    metrics = [
        ("Net worth", lambda a: worth[a.id], "everything you own, at what it would sell for"),
        ("Worth gained per hour", income, "over the last four game hours"),
        ("Cash", lambda a: a.denari, "in your pocket"),
        ("Businesses", lambda a: len([b for b in a.owned_businesses if b in world.businesses
                                      and not world.businesses[b].closed]), "that you own"),
        ("Employees", staff, "working for you"),
        ("Land", plots, "plots owned"),
        ("Goods carried", stock, "at what they would sell for"),
    ]
    rows = []
    for name, fn, note in metrics:
        vals = [fn(a) for a in agents]
        mine = fn(me)
        rows.append({"name": name, "you": round(mine, 1), "average": round(sum(vals) / len(vals), 1),
                     "best": round(max(vals), 1), "worst": round(min(vals), 1),
                     "rank": 1 + sum(1 for v in vals if v > mine), "note": note})

    books = [business_books(world, log, world.businesses[b]) for b in me.owned_businesses
             if b in world.businesses and not world.businesses[b].closed]
    city = world.city_of(me)
    standings = world.city_standings() if world.is_contest() else []
    city_total = next((r["total_net_worth"] for r in standings if r["city"] == city), sum(worth.values()))
    hour_ago, day_ago = history.back(1), history.back(24)
    def delta(row, idx):
        return None if not row or me.id not in row["agents"] else row["agents"][me.id][idx]
    return {
        "hour": round(world.sim_hour, 2),
        "rank": rank, "population": len(agents),
        "worth": round(worth[me.id], 1), "cash": round(me.denari, 1),
        "worth_per_hour": round(income(me), 1),
        "worth_change_1h": None if delta(hour_ago, 0) is None else round(worth[me.id] - delta(hour_ago, 0), 1),
        "cash_change_1h": None if delta(hour_ago, 1) is None else round(me.denari - delta(hour_ago, 1), 1),
        "rank_change_1h": None if delta(hour_ago, 2) is None else delta(hour_ago, 2) - rank,
        "worth_change_24h": None if delta(day_ago, 0) is None else round(worth[me.id] - delta(day_ago, 0), 1),
        "series": history.series(me.id),
        "average_series": [[r["hour"], round(sum(v[0] for v in r["agents"].values()) / max(1, len(r["agents"])), 1)]
                           for r in history.rows],
        "best_series": [[r["hour"], max((v[0] for v in r["agents"].values()), default=0)] for r in history.rows],
        "metrics": rows, "businesses": books,
        "city": {"key": city, "name": M.CITIES[city].name if city in M.CITIES else city,
                 "total": round(city_total, 1),
                 "your_share_pct": round(100.0 * worth[me.id] / city_total, 1) if city_total else 0.0,
                 "standings": [{"name": r["name"], "total": round(r["total_net_worth"], 1)} for r in standings]},
    }


# ---------------------------------------------------------------------------
# The leaderboard, always on screen
# ---------------------------------------------------------------------------

def leaderboard(world: "World", me: "Agent", history: History, top: int = 5) -> dict[str, Any]:
    """The top few by net worth, you wherever you are, who is just above you
    and by how much, and how each moved in the last hour."""
    worth = {a.id: a.net_worth(world) for a in world.agents.values()}
    order = sorted(worth, key=lambda k: -worth[k])
    rank = {k: 1 + sum(1 for v in worth.values() if v > worth[k] + 1e-6) for k in worth}
    back = history.back(1)
    def row(aid):
        a = world.agents[aid]
        prev = back["agents"].get(aid) if back else None
        return {"id": aid, "name": a.name, "city": world.city_of(a), "worth": round(worth[aid], 1),
                "rank": rank[aid], "you": aid == me.id,
                "change": None if not prev else round(worth[aid] - prev[0], 1),
                "moved": None if not prev else prev[2] - rank[aid]}
    rows = [row(k) for k in order[:top]]
    mine = row(me.id)
    above = next((k for k in reversed(order[:order.index(me.id)])), None)
    below = order[order.index(me.id) + 1] if order.index(me.id) + 1 < len(order) else None
    standings = world.city_standings() if world.is_contest() else []
    return {
        "top": rows, "you": mine, "population": len(order),
        "chasing": None if above is None else {"name": world.agents[above].name, "gap": round(worth[above] - worth[me.id], 1)},
        "chased_by": None if below is None else {"name": world.agents[below].name, "gap": round(worth[me.id] - worth[below], 1)},
        "cities": [{"key": r["city"], "name": r["name"], "total": round(r["total_net_worth"], 1)} for r in standings],
    }


def overtakes(history: History, me_id: str, world: "World") -> list[str]:
    """Who passed you, and whom you passed, between the last two hourly rows."""
    if len(history.rows) < 2:
        return []
    a, b = history.rows[-2]["agents"], history.rows[-1]["agents"]
    if me_id not in a or me_id not in b:
        return []
    mine_then, mine_now = a[me_id][2], b[me_id][2]
    out = []
    for aid, row in b.items():
        if aid == me_id or aid not in a:
            continue
        then, now = a[aid][2], row[2]
        name = world.agents[aid].name if aid in world.agents else aid
        if then > mine_then and now < mine_now:
            out.append(f"{name} passed you: now #{now}, you #{mine_now}.")
        elif then < mine_then and now > mine_now:
            out.append(f"You passed {name}: you are #{mine_now}.")
    return out[:3]


# ---------------------------------------------------------------------------
# Titles
# ---------------------------------------------------------------------------

TITLED = ("Wheat", "Grain", "Purified Water", "Meal", "Iron", "Bronze", "Lumber", "Tanned Leather")


def titles(world: "World", log: "EventLog", hours: float = 12.0) -> dict[str, list[str]]:
    """Whoever made the most of a key good in their city over the last half
    day holds its title: "Grain Baron of Aldermarch". A milestone that can be
    won, held and lost -- the open world's version of a medal."""
    since = world.sim_time - hours * 3600.0
    made: dict[tuple[str, str], dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for e in reversed(log.events):
        if e.sim_time < since:
            break
        if e.type != "production" or e.detail.get("item") not in TITLED:
            continue
        biz = world.businesses.get(e.subject)
        if biz is None or biz.is_government:
            continue
        made[(M.city_of(biz.location), e.detail["item"])][biz.owner] += e.detail.get("qty") or 0
    out: dict[str, list[str]] = defaultdict(list)
    for (city, item), by in made.items():
        owner, qty = max(by.items(), key=lambda kv: kv[1])
        if qty >= 5:
            name = M.CITIES[city].name if city in M.CITIES else city
            out[owner].append(f"{item} Baron of {name}")
    return dict(out)


# ---------------------------------------------------------------------------
# Next moves
# ---------------------------------------------------------------------------

def _move(text: str, why: str, label: str, kind: str, **target) -> dict[str, Any]:
    """One suggestion. `kind` says what the button does: act (run an action),
    form (open an action's form, pre-filled), walk (go to a place), building
    (open a building), tab (open a menu)."""
    return {"text": text, "why": why, "button": {"label": label, "kind": kind, **target}}


def _city_businesses(world, city, **kw):
    out = []
    for b in world.businesses.values():
        if b.closed or b.is_government or M.city_of(b.location) != city:
            continue
        out.append(b)
    return out


def _free_plots(world, place) -> int:
    owned = sum(1 for q in world.plots.values() if q.location == place and q.owner)
    return max(0, M.plots_at(place) - owned)


def advice(world: "World", log: "EventLog", me: "Agent", history: History) -> list[dict[str, Any]]:
    """Up to three next moves, most urgent first."""
    out: list[dict[str, Any]] = []
    city = world.city_of(me)
    here = me.location
    local = _city_businesses(world, city)
    fed_left = me.last_meal_window - me.hours_since_last_meal
    working = me.activity.kind == "work" and me.activity.ends_at > world.sim_time
    mine = [world.businesses[b] for b in me.owned_businesses
            if b in world.businesses and not world.businesses[b].closed]

    # 1. FOOD. Nothing else matters if you starve.
    if me.sustenance_stage != "Normal" or fed_left < 4:
        open_taverns = [b for b in local if b.type == "Tavern / Inn" and b.inventory.get("Meal", 0) > 0
                        and "Meal" in b.retail_prices]
        staffed = [b for b in open_taverns if b.is_staffed(world)]
        pick = (staffed or open_taverns)
        if pick:
            b = min(pick, key=lambda x: (x.location != here, x.price_for("Meal")))
            if b.location == here and b.is_staffed(world):
                out.append(_move(f"Eat at {b.name} ({b.price_for('Meal'):.0f})",
                                 "You must eat soon or start to starve.", "Eat now", "act",
                                 action="buy_meal", args={"business_id": b.id}))
            else:
                out.append(_move(f"Go and eat at {b.name}, {b.location} ({b.price_for('Meal'):.0f})",
                                 "You must eat soon. Taverns only serve while someone is on shift.",
                                 "Walk there", "building", id=b.id))
        else:
            out.append(_move("No tavern in your city has Meals. Feed the chain: grain and water go to a tavern.",
                             "A Meal needs 2 Grain and 1 Purified Water, cooked at a Tavern.",
                             "Open the guide", "tab", tab="guide"))

    # 2. OFFERS AND APPLICANTS waiting on you.
    for p in world.job_postings.values():
        if not p.is_live(world.sim_time):
            continue
        if getattr(p, "invitee", "") == me.id:
            biz = world.businesses.get(p.business_id)
            out.append(_move(f"{biz.name if biz else p.business_id} offered you {p.role} at {p.wage:.2f}/hr",
                             "An offer is private to you and lapses if you leave it.",
                             "Accept", "act", action="accept_job_offer", args={"posting_id": p.id}))
        elif p.owner == me.id and p.applicants:
            out.append(_move(f"{len(p.applicants)} applied for your {p.role} advert",
                             "Hire one to put your business to work while you do something else.",
                             "See applicants", "tab", tab="jobs"))

    # 2a. YOUR FAMILY IDLE while a business of yours has room (2026-10-18):
    # the cheapest worker there is, and the first thing a new owner misses.
    idle = [m for m in me.family if m.adult and not m.works_at]
    if idle and mine:
        for b in mine:
            if not b.spec.production_roles:
                continue
            cap = A.employee_cap(world, b)
            if cap is None or len(b.production_staff()) < cap:
                m = idle[0]
                who = "your partner" if m.role == "partner" else f"your {m.role or 'family'}"
                out.append(_move(f"Put {m.name} ({who}) to work at your {b.type.split(' /')[0]}",
                                 "Family work for nothing and never go off shift.",
                                 f"Put {m.name} to work", "act", action="assign_family",
                                 args={"member_id": m.id, "business_id": b.id}))
                break

    # 2e. A DELIVERY UNDER WAY: load it, then follow the compass.
    d = me.delivery
    if d:
        src = world.businesses.get(d["from"])
        if not d["loaded"] and src is not None:
            out.insert(0, _move(f"Load {d['qty']} {d['item']} at your {src.type.split(' /')[0]}",
                                f"It loads the moment you stand at {src.location} with the goods there.",
                                f"Walk to {src.location}", "walk", place=src.location))
        elif d["loaded"]:
            out.insert(0, _move(f"Carry {d['qty']} {d['item']} to {M.CITIES[d['city']].name}",
                                "Follow the compass to the yellow circle; the building lights up when you are close.",
                                "Delivery details", "tab", tab="market"))

    # 2d. MISSIONS (2026-10-18): the one under way, or the next to take.
    from . import missions as MI
    m = me.mission
    if m and m.get("id") == "bounty":
        if me.location == m["place"]:
            out.insert(0, _move(f"Attack the bandits at {m['place']} ({MI.odds(world, me):.0%} odds)",
                                "Win and the mission pays; lose and you are hurt, not killed.",
                                "Attack", "mission", mission_action="attack"))
        else:
            out.append(_move(f"Mission: ride to the bandit camp at {m['place']}",
                             "The compass points the way.", f"Walk to {m['place']}", "walk", place=m["place"]))
    elif not m:
        rows = MI.board(world, me)
        nxt = next((r for r in rows if r["status"] in ("open", "active")), None)
        if nxt and nxt["status"] == "open":
            out.append(_move(f"Mission: {nxt['title']} (+{nxt['reward']:.0f})", nxt["does"],
                             "Start it", "mission", mission_action="start", mission_id=nxt["id"]))
        elif nxt and nxt.get("auto"):
            out.append(_move(f"Achievement: {nxt['title']} (+{nxt['reward']:.0f})", nxt["does"],
                             "See delivery jobs", "tab", tab="market"))

    # 2c. A DELIVERY RUN worth making (2026-10-18): goods in the yard and a
    # buyer who pays more at their door than the gate does.
    if not me.delivery and not me.hauling:
        from . import delivery as DL
        best = next((o for o in DL.offers(world, me) if o["have"] >= 5 and o["unit"] > o["gate"]), None)
        if best:
            n = min(best["have"], best["qty"], me.carry_capacity(world))
            out.append(_move(f"Deliver {n} {best['item']} to {best['city_name']} for {best['unit'] * n:.0f}",
                             f"{best['unit']:.2f} each at their door, against {best['gate']:.2f} at the state's gate. "
                             f"Your donkey carries {me.carry_capacity(world)}.",
                             "See delivery jobs", "tab", tab="market"))

    # 2b. GOODS IN TRANSIT that are yours to move: carrying, claimed, or an
    # order of yours nobody has come for (a no-fee order is fetched by you).
    hauling = world.consignments.get(me.hauling) if me.hauling else None
    claimed = next((c for c in world.consignments.values()
                    if c.courier == me.id and c.status == "claimed"), None)
    # Work already under way comes first.
    if hauling:
        out.insert(0, _move(f"Carry {hauling.qty} {hauling.item} to {hauling.destination}",
                         "It is handed over the moment you walk in.",
                         f"Walk to {hauling.destination}", "walk", place=hauling.destination))
    elif claimed:
        out.insert(0, _move(f"Pick up {claimed.qty} {claimed.item} at {claimed.origin}",
                         f"It loads the moment you walk in; then carry it to {claimed.destination}.",
                         f"Walk to {claimed.origin}", "walk", place=claimed.origin))
    else:
        mine_ids = {b.id for b in mine}
        waiting = [c for c in world.consignments.values()
                   if c.status == "awaiting_courier" and c.buyer_business in mine_ids]
        if waiting:
            c = waiting[0]
            out.append(_move(f"Your {c.qty} {c.item} waits at {c.origin}",
                             ("Nobody is paid to bring it, so fetch it yourself."
                              if c.courier_fee <= 0 else
                              f"{c.courier_fee:.0f} is offered to a courier, or fetch it yourself."),
                             "Fetch it myself", "fetch", consignment_id=c.id))

    # 3. YOUR BUSINESSES: the first thing stopping each one. Money before all:
    # an unpaid worker walks off, and an unpaid business closes.
    for b in mine:
        payroll = sum(e.wage for e in b.roster if e.agent_id != me.id and not e.is_researcher)
        # Wages come from the business's purse, then your pocket (2026-10-18).
        if b.insolvent_since is not None or (payroll > 0 and b.cash + me.denari < payroll):
            need = max(b.insolvent_debt, payroll * 4 - b.cash, payroll, 1.0)
            left = ""
            if b.insolvent_since is not None:
                hours = max(0.0, D.BANKRUPTCY_GRACE_HOURS - (world.sim_time - b.insolvent_since) / 3600.0)
                left = f" It closes in {hours:.0f}h unless you do."
            out.append(_move(f"Your {b.type} can't pay wages: deposit {need:.0f}",
                             f"Wages come from its purse ({b.cash:.0f}), then your pocket ({me.denari:.0f}); unpaid workers leave.{left}",
                             f"Deposit {need:.0f}", "act", action="deposit",
                             args={"business_id": b.id, "amount": round(min(need, me.denari), 2)}))
            continue
        prod = b.active_production
        staffed = b.is_staffed(world) or any(e.agent_id != me.id for e in b.roster)
        recipe = (D.REFINING_RECIPES.get(prod) or D.CRAFTING_RECIPES.get(prod)) if prod else None
        if not prod:
            out.append(_move(f"Your {b.type} is making nothing",
                             f"Choose what it makes: {', '.join(b.spec.outputs[:4])}.",
                             "Set production", "form", action="set_production", args={"business_id": b.id}))
        elif recipe and any(b.inventory.get(i, 0) < q for i, q in recipe.inputs.items()):
            need = next(i for i, q in recipe.inputs.items() if b.inventory.get(i, 0) < q)
            sellers = [s for s in local if need in s.spec.outputs and s.inventory.get(need, 0) > 0 and s.id != b.id]
            if sellers:
                s = max(sellers, key=lambda x: x.inventory.get(need, 0))
                out.append(_move(f"Your {b.type} is out of {need}. {s.name} has {s.inventory[need]}",
                                 "Order it delivered; a courier brings it to your door.",
                                 "Order it", "form", action="order_from_business",
                                 args={"my_business_id": b.id, "seller_business_id": s.id, "item": need}))
            else:
                maker = next((t for t, sp in D.BUSINESS_TYPES.items() if need in sp.outputs), "someone")
                out.append(_move(f"Your {b.type} needs {need} and nobody in your city has any",
                                 f"A {maker} makes it. Found one, or ask in chat who will.",
                                 "Open chat", "tab", tab="chat"))
        elif sum(b.inventory.values()) >= E.business_storage_capacity(world, b) * 0.95:
            out.append(_move(f"Your {b.type}'s yard is full: it has stopped producing",
                             "Sell or move the stock: set a price, or hire a courier to deliver an order.",
                             "Set a price", "form", action="set_retail_price", args={"business_id": b.id}))
        elif not staffed:
            out.append(_move(f"Nobody is working your {b.type}",
                             "A business only produces and sells while someone is on shift.",
                             "Work it yourself" if here == b.location else "Go and work it",
                             "act" if here == b.location else "building",
                             **({"action": "apply_for_job", "args": {"business_id": b.id}} if here == b.location
                                else {"id": b.id})))
        elif any(o in D.FINAL_GOODS for o in b.spec.outputs) and not b.retail_prices:
            out.append(_move(f"Your {b.type} has no prices set, so it sells nothing over the counter",
                             "Set a price for what it makes.", "Set a price", "form",
                             action="set_retail_price", args={"business_id": b.id, "item": prod}))

    # 4. GET STARTED: found the business your city most needs.
    if not mine:
        made = {o for b in local if b.active_production for o in [b.active_production]}
        gaps = [i for i in FOOD_CHAIN if i not in made]
        wanted = None
        for item in gaps:
            wanted = next((t for t, sp in D.BUSINESS_TYPES.items() if item in sp.outputs), None)
            if wanted:
                break
        wanted = wanted or "Farm"
        spec = D.BUSINESS_TYPES[wanted]
        spur = wanted in D.EXTRACTION_BUSINESS_TYPES
        sites = [p for p in M.places_in(city)
                 if (p in M.SPUR_BY_NAME) == spur and _free_plots(world, p) >= D.SITE_BASE_PLOTS]
        site = min(sites, key=lambda p: (p != here, p)) if sites else None
        if me.denari >= spec.startup_cost and site:
            gap = f"Nobody in {M.CITIES[city].name} is making {gaps[0]}." if gaps else "It feeds the food chain."
            if site == here:
                out.append(_move(f"Found a {wanted} here ({spec.startup_cost:.0f})", gap,
                                 "Found it", "form", action="start_business", args={"type": wanted}))
            else:
                out.append(_move(f"Found a {wanted} at {site} ({spec.startup_cost:.0f})", gap,
                                 f"Walk to {site}", "walk", place=site))
        else:
            jobs = sorted((p for p in world.job_postings.values() if p.is_live(world.sim_time)
                           and not getattr(p, "invitee", "")), key=lambda p: -p.wage)
            if jobs:
                p = jobs[0]
                out.append(_move(f"Take a job: {p.role} at {p.wage:.2f}/hr",
                                 f"A {wanted} costs {spec.startup_cost:.0f}; you have {me.denari:.0f}. Earn the rest, or pool cash with someone.",
                                 "Apply", "act", action="apply_to_job", args={"posting_id": p.id}))
            else:
                out.append(_move(f"You need {spec.startup_cost - me.denari:.0f} more for a {wanted}",
                                 "Nobody is advertising work. Pool cash with a neighbour (pay) or offer your labour in chat.",
                                 "Open chat", "tab", tab="chat"))

    # 5. ANYTHING YOU CARRY that a business here would buy.
    if me.inventory:
        for b in [x for x in local if x.location == here and not x.closed]:
            item = next((i for i in me.inventory if A._business_can_use(b, i)), None)
            if item:
                out.append(_move(f"{b.name} here would buy your {item}",
                                 "Selling turns stock into cash.", "Sell", "form",
                                 action="sell_to_business", args={"business_id": b.id, "item": item}))
                break

    # 6. IDLE WITH A JOB.
    if me.current_job and not working and len(out) < 3:
        biz = world.businesses.get(me.current_job[0])
        if biz and biz.location == here:
            out.append(_move("Start your shift", "You are paid, or your business produces, only while you work.",
                             "Work 4 hours", "act", action="start_shift", args={"hours": 4}))
        elif biz:
            out.append(_move(f"Go to work at {biz.location}", "Your job is there.", "Walk there", "building", id=biz.id))

    if not out:
        out.append(_move("Things are running. Look for what is missing.",
                         "The rankings show what earned money in the last few hours.",
                         "What's working", "tab", tab="ranks"))
    return out[:3]


# ---------------------------------------------------------------------------
# The first day's goals
# ---------------------------------------------------------------------------

def goals(world: "World", log: "EventLog", me: "Agent") -> list[dict[str, Any]]:
    mine_ids = set(me.owned_businesses)
    ate = sold = hired = worked = False
    for e in log.events:
        if e.type == "ate" and e.actor == me.id:
            ate = True
        elif e.type == "sale" and (e.detail.get("seller") in mine_ids or e.detail.get("seller") == me.id):
            sold = True
        elif e.type == "hired" and e.subject in mine_ids and e.actor != me.id:
            hired = True
        elif e.type == "job_started" and e.actor == me.id:
            worked = True
    founded = bool(mine_ids)
    producing = any(world.businesses[b].active_production for b in mine_ids if b in world.businesses)
    profitable = any(business_books(world, log, world.businesses[b])["profit"] > 0
                     for b in mine_ids if b in world.businesses)
    # THE FIRST-DAY ARC (2026-10-18): your family to work, a farm or mine,
    # a first sale to the best bidder, a first study, a match for a child.
    extraction = any(world.businesses[b].type in D.EXTRACTION_BUSINESS_TYPES
                     for b in mine_ids if b in world.businesses)
    family_working = any(m.works_at for m in me.family)
    studied = bool(me.tech or me.researching)
    proposed = any(o.proposer == me.id for o in world.marriage_offers.values()) or bool(me.allies)
    return [
        {"goal": "Found a farm or a mine", "done": extraction,
         "how": "Build menu, left: a Farm or Mine goes down a spur road. Pick its 2x2 squares."},
        {"goal": "Put your family to work there", "done": family_working,
         "how": "Your house (house button): set your partner to work at it -- unpaid, always on shift."},
        {"goal": "Set it producing", "done": founded and producing,
         "how": "Open the business and choose what it makes; rich ground shows at the first harvest."},
        {"goal": "Sell your first goods to the best bidder", "done": sold,
         "how": "Market, Sell: refineries in every town bid for raw goods. Pick the best price."},
        {"goal": "Start learning something", "done": studied,
         "how": "Know-how (light bulb): your first study lands in six hours."},
        {"goal": "Eat before your first day's food runs out", "done": ate,
         "how": "The state's Tavern in your square always serves Meals."},
        {"goal": "Propose a match for one of your children", "done": proposed,
         "how": "Your house: when a child comes of age, propose them to another house -- allies follow."},
    ]


# ---------------------------------------------------------------------------
# What makes what
# ---------------------------------------------------------------------------

def chains(world: "World", city: str) -> dict[str, Any]:
    """Each business type: what it costs, where it stands, what it makes from
    what, and what those things are selling for in this city now."""
    def price(item):
        return round(E.realizable_price(world, item, city), 2)
    makers: dict[str, str] = {}
    for t, sp in D.BUSINESS_TYPES.items():
        for o in sp.outputs:
            makers.setdefault(o, t)
    types = []
    for t, sp in D.BUSINESS_TYPES.items():
        made = []
        for o in sp.outputs:
            recipe = D.REFINING_RECIPES.get(o) or D.CRAFTING_RECIPES.get(o)
            made.append({"item": o, "price": price(o),
                         "from": {i: q for i, q in recipe.inputs.items()} if recipe else {},
                         "from_makers": sorted({makers.get(i, "?") for i in (recipe.inputs if recipe else {})})})
        count = sum(1 for b in world.businesses.values()
                    if b.type == t and not b.closed and M.city_of(b.location) == city)
        types.append({"type": t, "cost": sp.startup_cost, "spur": t in D.EXTRACTION_BUSINESS_TYPES,
                      "makes": made, "in_your_city": count})
    paths = [
        {"name": "Food", "steps": ["Farm: Wheat + Dirty Water", "Refinery: Grain + Purified Water", "Tavern: Meal"]},
        {"name": "Weapons", "steps": ["Mine: Copper/Tin/Iron Ore + Wood", "Refinery: Charcoal, Bronze, Iron, Lumber",
                                     "Weaponsmith: spears, blades, armour"]},
        {"name": "Carts and animals", "steps": ["Farm: Hide + Wheat + Dirty Water", "Refinery: Tanned Leather, Grain, Purified Water",
                                               "Stable: Donkey Cart, Camel, Horse, Chariots"]},
    ]
    return {"types": types, "paths": paths}


# ---------------------------------------------------------------------------
# Markers over buildings
# ---------------------------------------------------------------------------

def markers(world: "World", log: "EventLog", me: "Agent") -> dict[str, dict[str, Any]]:
    """For each open business: the icons that say what you could do there now,
    and for your own, how it is doing."""
    out: dict[str, dict[str, Any]] = {}
    hiring = {p.business_id for p in world.job_postings.values()
              if p.is_live(world.sim_time) and (not getattr(p, "invitee", "") or p.invitee == me.id)}
    for b in world.businesses.values():
        if b.closed or b.is_government:
            continue
        icons = []
        staffed = b.is_staffed(world)
        if b.type == "Tavern / Inn" and b.inventory.get("Meal", 0) > 0 and "Meal" in b.retail_prices and staffed:
            icons.append({"icon": "meal", "tip": f"Meals {b.price_for('Meal'):.0f}"})
        if b.owner != me.id and any(A._business_can_use(b, i) for i in me.inventory):
            icons.append({"icon": "buys", "tip": "would buy what you carry"})
        if b.owner != me.id and staffed and any(q > 0 and i in b.retail_prices for i, q in b.inventory.items()):
            icons.append({"icon": "shop", "tip": "has goods for sale"})
        if b.id in hiring:
            icons.append({"icon": "hiring", "tip": "hiring"})
        if me.current_job and me.current_job[0] == b.id:
            icons.append({"icon": "work", "tip": "your job"})
        row: dict[str, Any] = {"icons": icons}
        if b.owner == me.id:
            books = business_books(world, log, b)
            row["health"] = books["health"]
            row["profit_per_hour"] = books["profit_per_hour"]
        out[b.id] = row
    return out


# ---------------------------------------------------------------------------
# The day's report
# ---------------------------------------------------------------------------

def daily_report(world: "World", log: "EventLog", me: "Agent", history: History, day: int) -> dict[str, Any]:
    now = history.rows[-1] if history.rows else None
    then = history.back(24)
    def mine(row, i):
        return row["agents"][me.id][i] if row and me.id in row["agents"] else None
    worth_now, worth_then = me.net_worth(world), mine(then, 0)
    rank_now = mine(now, 2)
    books = [business_books(world, log, world.businesses[b]) for b in me.owned_businesses
             if b in world.businesses and not world.businesses[b].closed]
    best = max(books, key=lambda x: x["profit"], default=None)
    worst = min(books, key=lambda x: x["profit"], default=None)
    # One missed opportunity: the best-selling good nobody in your city makes.
    city = world.city_of(me)
    made_here = {b.active_production for b in world.businesses.values()
                 if not b.closed and M.city_of(b.location) == city and b.active_production}
    prices: dict[str, list[float]] = defaultdict(lambda: [0.0, 0.0])
    since = world.sim_time - 24 * 3600
    for e in reversed(log.events):
        if e.sim_time < since:
            break
        if e.type == "sale" and e.detail.get("qty"):
            p = prices[e.detail.get("item")]
            p[0] += e.detail.get("total") or 0.0
            p[1] += e.detail["qty"]
    missed = sorted(((i, v[0], v[0] / v[1]) for i, v in prices.items() if i not in made_here and v[1]),
                    key=lambda x: -x[1])
    return {
        "day": day,
        "worth": round(worth_now, 1),
        "worth_change": None if worth_then is None else round(worth_now - worth_then, 1),
        "rank": rank_now, "rank_change": None if mine(then, 2) is None or rank_now is None else mine(then, 2) - rank_now,
        "best": best, "worst": worst if worst is not best else None,
        "missed": ({"item": missed[0][0], "traded": round(missed[0][1], 1), "price": round(missed[0][2], 2)}
                   if missed else None),
    }
