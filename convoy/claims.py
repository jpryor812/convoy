"""Claiming open land anywhere on the map, joined to the roads by a dirt road.

Designer request, 2026-10-18: "all land on the map can be purchased if there
are four open squares there. Any land is fair game so that exploration becomes
a bigger part of the game ... to have a building that produces goods or
receives goods, it must be connected to a road system."

A CLAIM is four plots on open grass -- not river, not mountainside, clear of
every road and every other place -- made into a place of its own. It is joined
to the nearest road by a dirt road, laid at once and paid for by the claimant
at ROAD_COST_PER_M; its travel time is the distance at a track's pace. The
plots are the world's until somebody buys or builds on them, exactly as at any
other place. See `world_map.register_claims` for how it becomes a place.
"""

from __future__ import annotations

import math
from typing import TYPE_CHECKING

from . import layout as L
from . import world_map as M
from .events import Significance
from .state import Claim, Plot

if TYPE_CHECKING:
    from .events import EventLog
    from .state import Agent, World

ROAD_COST_PER_M = 0.12         # coins per metre of dirt road
TRACK_SPEED = 4.0              # metres a second along a track, at Medium
MIN_FROM_PLACE = 110.0         # metres from a named place's middle
MIN_FROM_CLAIM = 85.0          # two squares: neighbouring claims may touch, not overlap
MAX_ROAD_M = 1200.0
SUFFIX = {"Farm": "Fields", "Mining Operation": "Diggings", "Refinery": "Works"}


def _roads(world: "World") -> list[list[tuple[float, float]]]:
    cities = list(world.cities)
    lines = [[(p.x, p.y) for p in road] for road in L.main_roads(cities)]
    lines += [[(p.x, p.y) for p in road] for road in L.intercity_roads(cities)]
    lines += [[(p.x, p.y) for p in pl.path] for pl in L.places_cached(cities).values() if pl.path]
    lines += [[tuple(pt) for pt in c.road] for c in world.claims.values()]
    return [ln for ln in lines if len(ln) >= 2]


def _nearest_on(px: float, py: float, a, b) -> tuple[float, float, float]:
    ax, ay = a; bx, by = b
    dx, dy = bx - ax, by - ay
    t = 0.0 if dx == dy == 0 else max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / (dx * dx + dy * dy)))
    qx, qy = ax + t * dx, ay + t * dy
    return math.hypot(px - qx, py - qy), qx, qy


def nearest_road(world: "World", x: float, y: float) -> tuple[float, float, float]:
    """(distance, x, y) of the nearest point on any road or track."""
    best = (float("inf"), x, y)
    for line in _roads(world):
        for a, b in zip(line, line[1:]):
            d = _nearest_on(x, y, a, b)
            if d[0] < best[0]:
                best = d
    return best


def check(world: "World", x: float, y: float) -> str:
    """Why a claim cannot be made here, or "" if it can."""
    cities = list(world.cities)
    places = L.places_cached(cities)
    minx, miny, maxx, maxy = L.bounds(places)
    if not (minx - 250 <= x <= maxx + 250 and miny - 250 <= y <= maxy + 250):
        return "that is beyond the edge of the map"
    if abs(y - L.river_axis()) < L.RIVER_HALF_WIDTH + 30:
        return "that is in the river"
    for bx in L.border_rivers(cities):
        if abs(x - bx) < L.BORDER_RIVER_HALF_WIDTH + 30:
            return "that is in the river"
    for m in L.mountains(cities):
        if math.hypot(x - m["x"], y - m["y"]) < m["r"] + 25:
            return "that is on the mountainside"
    for p in places.values():
        if math.hypot(x - p.center.x, y - p.center.y) < MIN_FROM_PLACE:
            return f"that is part of {p.name}"
    for c in world.claims.values():
        if math.hypot(x - c.x, y - c.y) < MIN_FROM_CLAIM:
            return f"that is part of {c.name}"
    d, _, _ = nearest_road(world, x, y)
    if d < 30:
        return "that is on a road"
    if d > MAX_ROAD_M:
        return f"too far from any road ({d:.0f} m; at most {MAX_ROAD_M:.0f})"
    return ""


# ---------------------------------------------------------------------------
# LAND PRICE (outposts, 2026-10-27): dear beside people, cheap far out
# ---------------------------------------------------------------------------
#
# There are no towns to price against at the start, so a plot's price is how
# close it is to what people have: the state's anchors, and land somebody has
# built on. Whichever pull is stronger sets it. Only worlds with outposts on
# charge it; a claim elsewhere costs just its road, as it always has.

LAND_FLOOR = 5.0               # a plot out where nobody is
LAND_PREMIUM = 60.0            # ... and how much more one beside people costs
ANCHOR_REACH_M = 400.0         # the anchor's pull falls by 1/e every this far
BUILT_RADIUS_M = 500.0         # built land counts within this far
BUILT_FULL = 32                # ... and this many built plots is as dear as it gets
MAX_SETTLE_LOAN = 400.0        # the most the state lends you to settle
LOAN_RATE_PER_DAY = 0.02       # interest on what you owe, each game day
LOAN_REPAY_SHARE = 0.20        # of what your businesses earn, until it is paid


def anchors(world: "World") -> dict[str, tuple[float, float]]:
    """Each city's market -- the state's trading post -- as {city: (x, y)}."""
    places = L.places_cached(list(world.cities))
    return {c: (places[M.market_of(c)].center.x, places[M.market_of(c)].center.y)
            for c in world.cities if M.market_of(c) in places}


def place_xy(world: "World", place: str) -> tuple[float, float] | None:
    c = world.claims.get(place)
    if c is not None:
        return c.x, c.y
    p = L.places_cached(list(world.cities)).get(place)
    return (p.center.x, p.center.y) if p else None


def nearest_anchor(world: "World", x: float, y: float) -> tuple[str, float]:
    """(city, metres) of the nearest anchor."""
    best = (world.cities[0], float("inf"))
    for city, (ax, ay) in anchors(world).items():
        d = math.hypot(x - ax, y - ay)
        if d < best[1]:
            best = (city, d)
    return best


def land_price(world: "World", x: float, y: float) -> float:
    """What one plot here costs. Charged only when the world has outposts."""
    if not world.outposts:
        return 0.0
    _, d = nearest_anchor(world, x, y)
    pull = math.exp(-d / ANCHOR_REACH_M)
    built = 0
    xy: dict[str, tuple[float, float] | None] = {}
    for q in world.plots.values():
        if not q.developed or q.owner == "Government":
            continue
        if q.location not in xy:
            xy[q.location] = place_xy(world, q.location)
        at = xy[q.location]
        if at and math.hypot(x - at[0], y - at[1]) <= BUILT_RADIUS_M:
            built += 1
    pull = max(pull, min(1.0, built / BUILT_FULL))
    return round(LAND_FLOOR + LAND_PREMIUM * pull, 2)


def quote(world: "World", x: float, y: float) -> dict:
    """What a claim here would cost and where its road would come from."""
    d, rx, ry = nearest_road(world, x, y)
    plot = land_price(world, x, y)
    road = round(d * ROAD_COST_PER_M, 2)
    return {"road_m": round(d), "road_cost": road, "from": [rx, ry],
            "plot_price": plot, "land_cost": round(plot * M.CLAIM_PLOTS, 2),
            "total": round(road + plot * M.CLAIM_PLOTS, 2),
            "why_not": check(world, x, y)}


def _nearest_junction(world: "World", x: float, y: float) -> str:
    places = L.places_cached(list(world.cities))
    juncs = [p for p in places.values() if p.kind != "spur"]
    return min(juncs, key=lambda p: math.hypot(x - p.center.x, y - p.center.y)).name


def _name(world: "World", agent: "Agent", purpose: str) -> str:
    stem = (agent.house or "House Newcomer").replace("House ", "")
    suffix = SUFFIX.get(purpose, "Steading")
    n = 1
    while True:
        name = f"{stem} {suffix}" + ("" if n == 1 else f" {n}")
        if name not in M.EVERY_PLACE and name not in world.claims:
            return name
        n += 1


def claim(world: "World", log: "EventLog", agent: "Agent", x: float, y: float,
          purpose: str = "") -> tuple[bool, str, Claim | None]:
    """Make a claim at (x, y): lay and pay for its road; its four plots are
    then for sale like any others. Returns (ok, message, claim)."""
    why = check(world, x, y)
    if why:
        return False, why, None
    d, rx, ry = nearest_road(world, x, y)
    road = round(d * ROAD_COST_PER_M, 2)
    land = round(land_price(world, x, y) * M.CLAIM_PLOTS, 2)
    cost = round(road + land, 2)
    if agent.denari < cost:
        what = f"the road here costs {road:.0f} ({d:.0f} m)" if not land else \
            f"this land costs {land:.0f} and its road {road:.0f} ({d:.0f} m)"
        return False, f"{what}; you have {agent.denari:.0f}", None
    junction = _nearest_junction(world, x, y)
    jp = L.places_cached(list(world.cities))[junction].center
    seconds = (math.hypot(x - jp.x, y - jp.y)) / TRACK_SPEED
    c = Claim(name=_name(world, agent, purpose), city=M.city_of(junction), junction=junction,
              x=round(x, 1), y=round(y, 1), road=[[round(rx, 1), round(ry, 1)], [round(x, 1), round(y, 1)]],
              road_m=round(d, 1), seconds=round(seconds, 1), owner=agent.id, created_at=world.sim_time)
    agent.denari -= cost
    world.claims[c.name] = c
    M.register_claims(world.claims.values())
    if world.outposts:
        # The land is bought with the claim: its four plots are the claimant's,
        # raw, and nobody else can build there unless they buy one.
        for _ in range(M.CLAIM_PLOTS):
            q = Plot(id=world.new_id("L"), location=c.name, owner=agent.id)
            world.plots[q.id] = q
        world.government.collect(land)
    log.emit(world.sim_time, "land_claimed", actor=agent.id, location=c.name,
             significance=Significance.MEDIUM, x=c.x, y=c.y, road_m=c.road_m, cost=cost,
             land=land, city=c.city)
    if world.outposts:
        return True, (f"Claimed {c.name}: four plots for {land:.0f} and a dirt road of {d:.0f} m "
                      f"for {road:.0f}. The land is yours to build on."), c
    return True, (f"Claimed {c.name}: a dirt road of {d:.0f} m from the nearest road, for {cost:.0f}. "
                  f"Its four plots are yours to buy or build on."), c


# ---------------------------------------------------------------------------
# SETTLING (outposts, 2026-10-27)
# ---------------------------------------------------------------------------

def settle(world: "World", log: "EventLog", agent: "Agent", x: float, y: float,
           borrow: float = 0.0) -> tuple[bool, str, Claim | None]:
    """Found your outpost: claim the land, put your home on all four plots and
    move in. `borrow` is lent by the state, up to MAX_SETTLE_LOAN, and only
    here -- it is how somebody starts somewhere dear."""
    if agent.home:
        return False, f"you have settled already, at {agent.home}", None
    borrow = max(0.0, min(MAX_SETTLE_LOAN, round(float(borrow or 0.0), 2)))
    q = quote(world, x, y)
    if q["why_not"]:
        return False, q["why_not"], None
    if agent.denari + borrow < q["total"]:
        return False, (f"this land and its road cost {q['total']:.0f}; you have "
                       f"{agent.denari:.0f}" + ("" if borrow >= MAX_SETTLE_LOAN else
                       f" -- borrow up to {MAX_SETTLE_LOAN:.0f} from the state to settle")), None
    agent.denari += borrow
    ok, msg, c = claim(world, log, agent, x, y, "home")
    if not ok or c is None:
        agent.denari -= borrow
        return False, msg, None
    agent.debt = round(agent.debt + borrow, 2)
    for p in world.plots.values():
        if p.location == c.name and p.owner == agent.id:
            p.home = True
            p.developed = True
    agent.home = c.name
    agent.location = c.name
    agent.in_transit = None
    agent.city = c.city
    agent.settled = True
    log.emit(world.sim_time, "settled", actor=agent.id, location=c.name,
             significance=Significance.MEDIUM, x=c.x, y=c.y, cost=q["total"],
             borrowed=borrow, city=c.city)
    owe = f" You owe the state {agent.debt:.0f}." if agent.debt else ""
    return True, f"You settled at {c.name}, {q['total']:.0f} for the land and its road.{owe}", c


def sample_sites(world: "World", cx: float, cy: float, rng, n: int = 40,
                 near: float = 150.0, far: float = 1100.0) -> list[tuple[float, float]]:
    """Valid open land in a ring around (cx, cy), nearest first."""
    out = []
    for _ in range(n * 6):
        if len(out) >= n:
            break
        r = rng.uniform(near, far)
        a = rng.uniform(0.0, 2 * math.pi)
        x, y = cx + r * math.cos(a), cy + r * math.sin(a)
        if not check(world, x, y):
            out.append((round(x, 1), round(y, 1)))
    out.sort(key=lambda p: math.hypot(p[0] - cx, p[1] - cy))
    return out


def auto_settle(world: "World", log: "EventLog", agent: "Agent", city: str, rng) -> bool:
    """Settle an agent near its roster city's anchor. Each picks how far out
    it wants to be -- most a good way out where land is cheap, some close in,
    borrowing to afford it -- and takes the nearest open land at that distance."""
    ax, ay = anchors(world).get(city, next(iter(anchors(world).values())))
    want = rng.choice([200.0, 350.0, 500.0, 650.0, 800.0, 950.0])
    for attempt in range(4):
        sites = sample_sites(world, ax, ay, rng, n=30, near=max(130.0, want - 150), far=want + 150)
        for x, y in sites:
            cost = quote(world, x, y)["total"]
            keep = 80.0                     # enough to eat and start
            borrow = max(0.0, cost + keep - agent.denari)
            if borrow > MAX_SETTLE_LOAN:
                continue
            ok, _, _ = settle(world, log, agent, x, y, borrow=borrow)
            if ok:
                return True
        want += 200.0
    return False


def ground_hint(world: "World", x: float, y: float) -> str:
    """What the land here is good for, as the hologram and agents are told."""
    from . import land as LAND
    farm = LAND.affinity_at(world, x, y, "Farm")
    mine = LAND.affinity_at(world, x, y, "Mining Operation")
    if max(farm, mine) < 0.25:
        return "plain ground"
    if farm >= mine:
        return "near water: good for farms" if farm >= 0.6 else "fair farmland"
    return "near the mountains: good for mines" if mine >= 0.6 else "fair mining ground"


def sites_near(world: "World", agent: "Agent", n: int = 5) -> list[dict]:
    """Open land an agent could claim now: a few sites around its outpost and
    its nearest anchor, the same for six game hours so a plan survives a turn.
    Each site's id carries its position (`actions.claim_land`)."""
    import random
    home = place_xy(world, agent.home) if agent.home else None
    city = agent.city or world.cities[0]
    anchor = anchors(world).get(city)
    rng = random.Random(f"{world.land_seed}:{agent.id}:{int(world.sim_hour // 6)}")
    spots: list[tuple[float, float]] = []
    if home:
        spots += sample_sites(world, home[0], home[1], rng, n=3, near=90.0, far=450.0)
    if anchor:
        spots += sample_sites(world, anchor[0], anchor[1], rng, n=n - len(spots), near=150.0, far=700.0)
    out = []
    for x, y in spots[:n]:
        q = quote(world, x, y)
        if q["why_not"]:
            continue
        acity, ad = nearest_anchor(world, x, y)
        row = {"site_id": f"S_{x:.0f}_{y:.0f}", "cost": q["total"],
               "from_trading_post": f"{ad:.0f} m from {M.market_of(acity)}",
               "ground": ground_hint(world, x, y)}
        if home:
            row["from_your_home"] = f"{math.hypot(x - home[0], y - home[1]):.0f} m"
        out.append(row)
    return out
