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
# FIRST HOMES (2026-10-28): free, and far apart -- "far enough that you can
# see some in the distance, but not close enough that you can see many clear
# as day right next to you". Beyond discovery's sight, so nobody starts
# already knowing their neighbours, and with a long free road to reach the
# open land between the trading posts and the mountains.
HOME_SPACING_M = 650.0
HOME_MAX_ROAD_M = 2600.0
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


def check(world: "World", x: float, y: float, home: bool = False) -> str:
    """Why a claim cannot be made here, or "" if it can. `home`: a first
    home, which may have a longer road and must stand apart from others."""
    cities = list(world.cities)
    places = L.places_cached(cities)
    minx, miny, maxx, maxy = L.bounds(places)
    edge = L.MOUNTAIN_OFFSET - 150.0           # up to the foot of the ranges
    if not (minx - edge <= x <= maxx + edge and miny - edge <= y <= maxy + edge):
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
    reach = HOME_MAX_ROAD_M if home else MAX_ROAD_M
    if d > reach:
        return f"too far from any road ({d:.0f} m; at most {reach:.0f})"
    if home and world.outposts:
        for a in world.agents.values():
            at = place_xy(world, a.home) if a.home else None
            if at and math.hypot(x - at[0], y - at[1]) < HOME_SPACING_M:
                return (f"someone has settled within {HOME_SPACING_M:.0f} m of here: "
                        f"first homes stand further apart")
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


def quote(world: "World", x: float, y: float, home: bool = False) -> dict:
    """What a claim here would cost and where its road would come from.
    `home`: as a first home (a longer road, apart from other homes)."""
    d, rx, ry = nearest_road(world, x, y)
    plot = land_price(world, x, y)
    road = round(d * ROAD_COST_PER_M, 2)
    return {"road_m": round(d), "road_cost": road, "from": [rx, ry],
            "plot_price": plot, "land_cost": round(plot * M.CLAIM_PLOTS, 2),
            "total": round(road + plot * M.CLAIM_PLOTS, 2),
            "why_not": check(world, x, y, home=home)}


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
          purpose: str = "", free: bool = False) -> tuple[bool, str, Claim | None]:
    """Make a claim at (x, y): lay and pay for its road; its four plots are
    then for sale like any others. Returns (ok, message, claim)."""
    why = check(world, x, y, home=(purpose == "home"))
    if why:
        return False, why, None
    d, rx, ry = nearest_road(world, x, y)
    road = round(d * ROAD_COST_PER_M, 2)
    land = round(land_price(world, x, y) * M.CLAIM_PLOTS, 2)
    if free:
        road = land = 0.0
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
            q = Plot(id=world.new_id("L"), location=c.name, owner=agent.id,
                     paid=round(cost / M.CLAIM_PLOTS, 2))
            world.plots[q.id] = q
        world.government.collect(land)
    log.emit(world.sim_time, "land_claimed", actor=agent.id, location=c.name,
             significance=Significance.MEDIUM, x=c.x, y=c.y, road_m=c.road_m, cost=cost,
             land=land, city=c.city)
    if world.outposts:
        return True, (f"Claimed {c.name}: four plots for {land:.0f} and a dirt road of {d:.0f} m "
                      f"for {road:.0f}. The land is yours: travel_to {c.name} and "
                      f"start_business there."), c
    return True, (f"Claimed {c.name}: a dirt road of {d:.0f} m from the nearest road, for {cost:.0f}. "
                  f"Its four plots are yours to buy or build on."), c


# ---------------------------------------------------------------------------
# SETTLING (outposts, 2026-10-27)
# ---------------------------------------------------------------------------

def settle(world: "World", log: "EventLog", agent: "Agent", x: float, y: float,
           borrow: float = 0.0) -> tuple[bool, str, Claim | None]:
    """Found your outpost: claim the land, put your home on all four plots and
    move in. THE FIRST HOME IS FREE (designer decision, 2026-10-28): paying
    for it left nothing to build a farm with, and a start spent waiting on
    wages is a dull one. `borrow` is lent by the state, up to MAX_SETTLE_LOAN,
    and only here -- money for a first business."""
    if agent.home:
        return False, f"you have settled already, at {agent.home}", None
    borrow = max(0.0, min(MAX_SETTLE_LOAN, round(float(borrow or 0.0), 2)))
    why = check(world, x, y, home=True)
    if why:
        return False, why, None
    agent.denari += borrow
    ok, msg, c = claim(world, log, agent, x, y, "home", free=True)
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
    for vid in agent.owned_vehicles:              # the donkey comes too
        if vid in world.vehicles:
            world.vehicles[vid].location = c.name
    agent.city = c.city
    agent.settled = True
    log.emit(world.sim_time, "settled", actor=agent.id, location=c.name,
             significance=Significance.MEDIUM, x=c.x, y=c.y, borrowed=borrow, city=c.city)
    owe = f" You borrowed {borrow:.0f} from the state." if borrow else ""
    return True, f"You settled at {c.name}. Your first home and its road are free.{owe}", c


def sample_sites(world: "World", cx: float, cy: float, rng, n: int = 40,
                 near: float = 150.0, far: float = 1100.0,
                 home: bool = False) -> list[tuple[float, float]]:
    """Valid open land in a ring around (cx, cy), nearest first."""
    out = []
    for _ in range(n * 6):
        if len(out) >= n:
            break
        r = rng.uniform(near, far)
        a = rng.uniform(0.0, 2 * math.pi)
        x, y = cx + r * math.cos(a), cy + r * math.sin(a)
        if not check(world, x, y, home=home):
            out.append((round(x, 1), round(y, 1)))
    out.sort(key=lambda p: math.hypot(p[0] - cx, p[1] - cy))
    return out


def auto_settle(world: "World", log: "EventLog", agent: "Agent", city: str, rng) -> bool:
    """Settle an agent near its roster city's anchor. Each picks how far out
    it wants to be and takes the nearest open land at that distance. The
    first home is free, so nobody borrows to settle."""
    ax, ay = anchors(world).get(city, next(iter(anchors(world).values())))
    want = rng.choice([450.0, 700.0, 950.0, 1200.0, 1450.0, 1700.0, 1950.0])
    for attempt in range(8):
        sites = sample_sites(world, ax, ay, rng, n=40, near=max(150.0, want - 250), far=want + 250,
                             home=True)
        for x, y in sites:
            ok, _, _ = settle(world, log, agent, x, y)
            if ok:
                return True
        want += 250.0
    # Crowded: anywhere on the frontier, then -- rather than nowhere -- closer in.
    global HOME_SPACING_M
    spacing = HOME_SPACING_M
    try:
        for gap in (spacing, spacing * 0.6):
            HOME_SPACING_M = gap
            for bx, by in anchors(world).values():
                for x, y in sample_sites(world, bx, by, rng, n=60, near=200.0, far=2600.0, home=True):
                    ok, _, _ = settle(world, log, agent, x, y)
                    if ok:
                        return True
    finally:
        HOME_SPACING_M = spacing
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
