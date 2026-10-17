"""What's working: a periodic look at the whole game, the same for everyone.

Designer request, 2026-10-16: "I want the agents to occasionally observe the
game to see what's working -- be very reactive." An agent's observation is its
own corner: its cash, its shop, the road it is on, the chat it can read. What it
never saw was the scoreboard of STRATEGIES: which businesses actually took money
in, what goods really sold for, who got richer and doing what, which city is
short of what. Without that, a run's first hour sets the plan and nobody revises
it -- in the 2026-10-16 smoke every agent founded a Tavern, and nothing they
could see told them a Refinery was the scarce, profitable link.

So every `DIGEST_EVERY_HOURS` the engine publishes one summary of the period
just gone, built from the event log and the world, and every observation
carries the latest one until the next replaces it. One text for everyone:
nothing in it is private (every sale, hire and robbery is public knowledge in a
town this size), and one string costs one build.

Pure function of (world, log, since); the engine stores and announces it.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from typing import TYPE_CHECKING, Any

from . import world_map as M

if TYPE_CHECKING:
    from .events import EventLog
    from .state import World

DIGEST_EVERY_HOURS = 4.0
TOP_BUSINESSES = 6
TOP_PEOPLE = 3
TOP_PRICES = 8
# Goods every city needs to eat, shown made-or-not for each city.
FOOD_CHAIN = ("Wheat", "Dirty Water", "Grain", "Purified Water", "Meal")


def _recent(log: "EventLog", since: float) -> list:
    """Events at or after `since`, oldest first. Walked from the end: the log is
    append-only in time order, and a long run's is hundreds of thousands long."""
    out = []
    for e in reversed(log.events):
        if e.sim_time < since:
            break
        out.append(e)
    out.reverse()
    return out


def _city_name(world: "World", key: str) -> str:
    return M.CITIES[key].name if key in M.CITIES else key.title()


def _where(world: "World", location: str | None) -> str:
    if not location:
        return ""
    city = M.city_of(location)
    return f"{location}, {_city_name(world, city)}" if world.is_contest() else location


def snapshot(world: "World") -> dict[str, Any]:
    """What the next digest measures change against."""
    return {
        "agents": {a.id: round(a.net_worth(world), 2) for a in world.agents.values()},
        "cities": {r["city"]: r["total_net_worth"] for r in world.city_standings()},
    }


def build(world: "World", log: "EventLog", since: float,
          baseline: dict[str, Any] | None = None) -> str:
    events = _recent(log, since)
    baseline = baseline or {}
    h0, h1 = since / 3600.0, world.sim_time / 3600.0
    lines = [
        f"Hours {h0:.0f}-{h1:.0f}. The same summary goes to every citizen; it "
        f"reports what happened, not what to do. Copy what works, avoid what "
        f"did not, and fill what is missing.",
    ]

    def biz_name(bid: str) -> str:
        b = world.businesses.get(bid)
        return b.name if b else bid

    # -- MONEY: which businesses took money in, from what ------------------
    takings: dict[str, float] = defaultdict(float)
    spend: dict[str, float] = defaultdict(float)
    sold: dict[str, Counter] = defaultdict(Counter)
    prices: dict[tuple[str, str], list[float]] = defaultdict(lambda: [0.0, 0.0])
    for e in events:
        if e.type != "sale":
            continue
        d = e.detail
        seller, buyer, total = d.get("seller"), d.get("buyer"), d.get("total") or 0.0
        if seller in world.businesses:
            takings[seller] += total
            sold[seller][d.get("item")] += d.get("qty") or 0
        if buyer in world.businesses:
            spend[buyer] += total
        if d.get("kind") != "gift" and d.get("qty"):
            p = prices[(d.get("item"), d.get("city") or "")]
            p[0] += total
            p[1] += d["qty"]
    if takings:
        lines.append("")
        lines.append("BUSINESSES THAT TOOK MONEY IN:")
        for bid, got in sorted(takings.items(), key=lambda kv: -kv[1])[:TOP_BUSINESSES]:
            b = world.businesses[bid]
            what = ", ".join(f"{q} {i}" for i, q in sold[bid].most_common(3))
            spent = f"; spent {spend[bid]:.0f} on supplies" if spend.get(bid) else ""
            lines.append(f"  {b.name} ({b.type}, {_where(world, b.location)}): "
                         f"took in {got:.0f} selling {what}{spent}")
    else:
        lines.append("")
        lines.append("BUSINESSES THAT TOOK MONEY IN: none. Nothing was sold.")
    idle = [b for b in world.businesses.values()
            if not b.closed and not b.is_government and b.id not in takings]
    if idle:
        by_type = Counter(b.type for b in idle)
        lines.append("  Sold nothing at all: " + ", ".join(
            f"{n} x {t}" for t, n in by_type.most_common()))

    # -- PRICES: what goods really sold for ----------------------------------
    if prices:
        lines.append("")
        lines.append("WHAT GOODS SOLD FOR (average price, units sold):")
        top = sorted(prices.items(), key=lambda kv: -kv[1][0])[:TOP_PRICES]
        for (item, city), (value, qty) in top:
            at = f" in {_city_name(world, city)}" if world.is_contest() and city else ""
            lines.append(f"  {item}{at}: {value / qty:.2f} each, {qty:.0f} sold")

    # -- PEOPLE: who got richer, and doing what ------------------------------
    before = baseline.get("agents") or {}
    if before:
        moved = []
        for a in world.agents.values():
            if a.id in before:
                moved.append((a.net_worth(world) - before[a.id], a))
        moved.sort(key=lambda m: -m[0])

        def doing(a) -> str:
            owns = [world.businesses[b].type for b in a.owned_businesses
                    if b in world.businesses and not world.businesses[b].closed]
            job = a.current_job
            bits = []
            if owns:
                bits.append("owns " + ", ".join(owns))
            if job and job[0] in world.businesses and world.businesses[job[0]].owner != a.id:
                bits.append(f"works as {job[1]} at {biz_name(job[0])} for {job[2]:.2f}/hr")
            if sum(a.stolen.values()):
                bits.append("holds stolen goods")
            return "; ".join(bits) or "no business, no job"

        if moved:
            lines.append("")
            lines.append("WHO GOT RICHER, AND DOING WHAT:")
            for gain, a in moved[:TOP_PEOPLE]:
                if gain <= 0:
                    break
                lines.append(f"  {a.name} ({a.id}): +{gain:.0f} -- {doing(a)}")
            losers = [m for m in moved[::-1] if m[0] < 0][:2]
            for loss, a in losers:
                lines.append(f"  LOST: {a.name} ({a.id}): {loss:.0f} -- {doing(a)}")

    # -- CITIES: score, food, gaps -------------------------------------------
    made: dict[str, Counter] = defaultdict(Counter)
    for e in events:
        if e.type == "production" and e.location:
            made[M.city_of(e.location)][e.detail.get("item")] += e.detail.get("qty") or 0
    city_before = baseline.get("cities") or {}
    lines.append("")
    lines.append("EACH CITY:")
    for row in world.city_standings() if world.is_contest() else [
            {"city": world.cities[0], "name": _city_name(world, world.cities[0]),
             "total_net_worth": None}]:
        c = row["city"]
        head = f"  {row['name']}"
        if row.get("total_net_worth") is not None:
            head += f": total {row['total_net_worth']:,.0f}"
            if c in city_before:
                head += f" ({row['total_net_worth'] - city_before[c]:+,.0f})"
        people = world.agents_in(c)
        hungry = sum(1 for a in people if a.alive and a.sustenance_stage != "Normal")
        if hungry:
            head += f"; {hungry} of {len(people)} citizens hungry or starving"
        lines.append(head)
        got = made.get(c, Counter())
        food = [f"{i} {got[i]}" for i in FOOD_CHAIN if got[i]]
        missing = [i for i in FOOD_CHAIN if not got[i]]
        lines.append("    food chain made: " + (", ".join(food) or "nothing")
                     + (f"; NOT MADE: {', '.join(missing)}" if missing else ""))
        other = [(i, q) for i, q in got.most_common() if i not in FOOD_CHAIN][:6]
        if other:
            lines.append("    also made: " + ", ".join(f"{i} {q}" for i, q in other))

    # -- LABOUR --------------------------------------------------------------
    hires = [e for e in events if e.type == "hired"]
    paid = [e.detail.get("wage") or 0.0 for e in hires if (e.detail.get("wage") or 0) > 0]
    poached = [e for e in events if e.type == "quit_job"
               and e.detail.get("reason") == "took a better offer"]
    unpaid = sum(1 for e in events if e.type == "wages_unpaid")
    open_jobs = [p for p in world.job_postings.values()
                 if p.is_live(world.sim_time) and not getattr(p, "invitee", "")]
    if hires or open_jobs or unpaid:
        lines.append("")
        bits = [f"{len(hires)} hired"]
        if paid:
            bits.append(f"paid wages {min(paid):.2f}-{max(paid):.2f}/hr")
        if poached:
            bits.append(f"{len(poached)} left a job for a better offer")
        if unpaid:
            bits.append(f"{unpaid} shifts went UNPAID (an employer ran out of cash)")
        if open_jobs:
            best = max(open_jobs, key=lambda p: p.wage)
            bits.append(f"{len(open_jobs)} adverts open, best {best.wage:.2f}/hr "
                        f"({best.role} at {biz_name(best.business_id)})")
        lines.append("LABOUR: " + "; ".join(bits) + ".")

    # -- ROADS ---------------------------------------------------------------
    robbed = [e for e in events if e.type == "robbed"]
    repelled = [e for e in events if e.type == "raid_repelled"]
    slipped = [e for e in events if e.type in ("raid_spotted", "raid_outrun")]
    killed = sum(len(e.detail.get("killed") or []) for e in repelled)
    if robbed or repelled or slipped:
        lines.append("")
        taken = sum(e.detail.get("value_lost") or 0.0 for e in robbed)
        segs = Counter(e.detail.get("segment") for e in robbed + repelled)
        lines.append(
            f"ROADS: {len(robbed)} loads robbed (about {taken:.0f} taken), "
            f"{len(repelled)} raids beaten off ({killed} raiders killed), "
            f"{len(slipped)} convoys slipped an ambush. Busiest: "
            + ", ".join(f"{s} {n}" for s, n in segs.most_common(3) if s) + "."
        )

    deaths = [e for e in events if e.type in ("agent_died", "starved_to_death")]
    if deaths:
        causes = Counter(e.detail.get("cause") or e.type for e in deaths)
        lines.append("DEATHS: " + ", ".join(f"{n} {c}" for c, n in causes.items()) + ".")
    return "\n".join(lines)
