"""Where everything physically IS -- the valley as geometry rather than a diagram.

WHY THIS IS A MODULE AND NOT A FEW LINES IN THE RENDERER

`render_world.py` used to lay the seven junctions down a straight vertical line
and hang spurs off alternating sides at a fixed offset. That is a graph drawing,
not a place: nothing is anywhere for a reason, a founded business is a dot on
top of another dot, and there is nowhere to put a tree. It also could not be
reused -- the 3D scene would have had to reinvent all of it.

So position lives here, once, as plain data in world metres. The 2D map and the
React Three Fiber scene consume the same coordinates, which is the only way the
two can ever agree about where Kiln Row is.

THE RULE THAT CONSTRAINS EVERY NUMBER BELOW

**The geometry may not contradict the simulation.** All six road segments are the
same distance -- `world_map` makes them differ by TERRAIN, not length -- and all
sixteen spurs are exactly ninety seconds deep. So segments are drawn equal, and
spurs are drawn equal. A map that shows one spur three times longer than another
is telling a student something the travel times deny, and they will believe the
picture over the table. This is VISUALS §8's argument about `ORTHO_SPAN_M` being
sized to the largest asset rather than per-asset, one level up: a drawing that
rescales things independently stops being able to describe the economy.

What IS free to vary is lateral wander, spur direction, and how sites sit on the
ground -- none of which the engine has an opinion about.

DETERMINISM

Everything random here is seeded off the place's own name, so re-rendering a run
never reshuffles the world, and adding a seventeenth spur does not move the
first sixteen. A world that looks different every time it is drawn cannot be
learned, and the demo depends on a student recognising Copper Gulch on sight.
"""

from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass, field

from . import world_map as M

# ---------------------------------------------------------------------------
# SCALE
# ---------------------------------------------------------------------------

# One world unit is one metre. Chosen so the numbers below are arguable against
# real ground rather than being arbitrary canvas pixels -- and so the 3D scene
# can use them unscaled.
#
# The road is ~2.6 km end to end. That is a fifteen-minute walk, against a road
# the engine crosses in ~5 simulated minutes at Medium -- so the map is NOT to
# scale with travel time, and could not be: a valley drawn at true walking scale
# would be mostly empty road. It is to scale with ITSELF, which is the property
# that matters, and every segment gets an equal share.
SEGMENT_LENGTH = 430.0          # metres between adjacent junctions, all equal
SPUR_DEPTH = 305.0              # metres from junction to the head of a spur
SPUR_LOOP_RADIUS = 78.0         # the turning circle a spur dead-ends in

ROAD_WIDTH = 9.0
SPUR_WIDTH = 6.0

# How far a junction may wander off the valley's centre line. Enough to read as
# a road following the ground, small enough that the road never doubles back and
# make a southward journey look northward.
MAX_WANDER = 110.0


@dataclass(frozen=True)
class Point:
    x: float
    y: float

    def __add__(self, other: "Point") -> "Point":
        return Point(self.x + other.x, self.y + other.y)


@dataclass
class Slot:
    """A place a building can stand, and which way it faces.

    `facing` is degrees clockwise from north, pointing at the road the building
    fronts onto. A settlement whose buildings all face the same way reads as a
    warehouse estate; one where they face the street reads as a village, and it
    costs nothing to store the angle now rather than guess it in two renderers.
    """

    x: float
    y: float
    facing: float
    kind: str = "site"          # site | store | civic | home


@dataclass
class Prop:
    """A tree, rock or piece of ground clutter."""

    kind: str                   # tree | rock | stump | bush
    x: float
    y: float
    scale: float
    rotation: float


@dataclass
class Place:
    """One named location, with everything needed to draw it."""

    name: str
    kind: str                   # hub | waystation | wilderness | spur
    center: Point
    junction: str | None
    elevation: int
    protected: bool
    path: list[Point] = field(default_factory=list)     # spur road, if any
    slots: list[Slot] = field(default_factory=list)
    props: list[Prop] = field(default_factory=list)


# ---------------------------------------------------------------------------
# SEEDED RANDOMNESS
# ---------------------------------------------------------------------------

def _rng(*key: object) -> "_Stream":
    """A deterministic number stream keyed by name rather than by call order.

    Keyed by NAME on purpose. A single shared `random.Random` would make every
    place's appearance depend on how many places were drawn before it, so adding
    a spur would silently rearrange the trees at Town. Hashing the name means a
    place's look is a property of the place.
    """
    digest = hashlib.sha256("|".join(str(k) for k in key).encode()).digest()
    return _Stream(digest)


class _Stream:
    def __init__(self, digest: bytes) -> None:
        self._d = digest
        self._i = 0

    def _next(self) -> float:
        if self._i + 4 > len(self._d):
            self._d = hashlib.sha256(self._d).digest()
            self._i = 0
        chunk = self._d[self._i:self._i + 4]
        self._i += 4
        return int.from_bytes(chunk, "big") / 0xFFFFFFFF

    def uniform(self, lo: float, hi: float) -> float:
        return lo + (hi - lo) * self._next()

    def choice(self, seq):
        return seq[min(int(self._next() * len(seq)), len(seq) - 1)]


# ---------------------------------------------------------------------------
# THE MAIN ROAD
# ---------------------------------------------------------------------------

# Hand-authored lateral offsets, north to south -- this is VISUALS §9's
# "hand-designed layout" for the seven that matter, rather than a computed line.
# Read down the column and the road swings west through the hills, back east to
# take the bridge square-on, then west again up the switchbacks. The bridge is
# deliberately the straightest part: a crossing is a fixed point on a river, and
# a road meets it head on.
_WANDER: dict[str, float] = {
    "Refinery Row":          -40.0,
    "North Protected Zone":   35.0,
    "The Hills":            -105.0,
    "The Crossing":            0.0,
    "The Climb":             -85.0,
    "South Protected Zone":   50.0,
    "Town":                    0.0,
}


def junction_center(name: str) -> Point:
    """Where a main-road location sits. North is -y, so the road runs downward.

    The vertical drop is SHORTENED to absorb the lateral wander, so the straight
    line between consecutive junctions is exactly SEGMENT_LENGTH regardless of
    how far the road swings. Laying them out on a fixed vertical pitch and
    letting the wander lengthen the hypotenuse made the swing through The Hills
    6% longer than the run to the bridge -- small enough to look fine and still
    a drawing that contradicts the engine, which makes every segment the same
    distance. Six percent is not visible; being unable to say the map is honest
    is the cost that matters.
    """
    y = 0.0
    for i in range(1, M.LOCATIONS.index(name) + 1):
        dx = _WANDER[M.LOCATIONS[i]] - _WANDER[M.LOCATIONS[i - 1]]
        y += math.sqrt(max(SEGMENT_LENGTH ** 2 - dx ** 2, 1.0))
    return Point(_WANDER[name], y)


def main_road() -> list[Point]:
    """The road as a polyline through the seven junctions, with easing points.

    Two intermediate points per segment rather than a straight line, so the road
    curves between junctions instead of turning at sharp corners. Real roads
    bend; more to the point, a hard vertex at every junction makes a seven-stop
    road look like a flowchart.
    """
    pts: list[Point] = []
    for i, name in enumerate(M.LOCATIONS):
        here = junction_center(name)
        if i:
            prev = junction_center(M.LOCATIONS[i - 1])
            # Ease the lateral shift across the middle of the segment, so the
            # bend sits between junctions and each junction itself is square.
            for t in (0.33, 0.67):
                pts.append(Point(
                    prev.x + (here.x - prev.x) * _smooth(t),
                    prev.y + (here.y - prev.y) * t,
                ))
        pts.append(here)
    return pts


def _smooth(t: float) -> float:
    """Smoothstep. Flat at both ends, so a bend leaves and arrives square."""
    return t * t * (3.0 - 2.0 * t)


# ---------------------------------------------------------------------------
# SPURS
# ---------------------------------------------------------------------------

# Which way each junction's spurs point, in degrees clockwise from north. Chosen
# so no spur crosses the main road or another spur, and so the three-spur
# junctions (Refinery Row, Town) fan rather than stack.
# MINIMUM SEPARATION IS GEOMETRY, NOT TASTE. Two spurs off one junction run the
# same distance out (they must -- see the module docstring), so the only thing
# keeping their turning loops apart is the angle between them. Two loops need
# 2r + clearance between centres; at SPUR_DEPTH that works out to ~57 degrees,
# and the first draft of this table had pairs 20 and 25 degrees apart. Six of
# the sixteen loops overlapped, which `check()` now refuses to let happen again.
_MIN_SPUR_SEPARATION = 57.0

_SPUR_HEADINGS: dict[str, list[float]] = {
    "Refinery Row":         [290.0, 70.0, 350.0],
    "North Protected Zone": [95.0, 265.0],
    "The Hills":            [240.0, 300.0],
    "The Crossing":         [62.0, 122.0],
    "The Climb":            [235.0, 295.0],
    "South Protected Zone": [62.0, 122.0],
    "Town":                 [250.0, 90.0, 170.0],
}


def spur_geometry(spur: M.Spur, index: int) -> tuple[list[Point], Point]:
    """A spur road: out from its junction, then a loop it dead-ends in.

    Returns the road polyline and the loop's centre. The loop is not decoration
    -- `world_map` says a spur "dead-ends and loops back to the same junction",
    so a cart down a spur turns around rather than passing through, and the
    drawing should say so. Everything on the spur is arranged around that loop.

    EVERY spur is the same depth, because every spur is 90 seconds deep in the
    engine. See the module docstring.
    """
    base = junction_center(spur.junction)
    heading = _SPUR_HEADINGS[spur.junction][index]
    rad = math.radians(heading)
    dx, dy = math.sin(rad), -math.cos(rad)

    # A gentle S so a spur does not read as a spoke on a wheel. The bend is
    # perpendicular to the heading and seeded by name, so each spur bends its
    # own way but always arrives the same distance out.
    r = _rng("spur", spur.name)
    bend = r.uniform(-46.0, 46.0)
    px, py = -dy, dx                      # perpendicular

    pts: list[Point] = [base]
    for t in (0.35, 0.7, 1.0):
        wobble = bend * math.sin(math.pi * t)
        pts.append(Point(
            base.x + dx * SPUR_DEPTH * t + px * wobble,
            base.y + dy * SPUR_DEPTH * t + py * wobble,
        ))
    head = pts[-1]
    return pts, head


# ---------------------------------------------------------------------------
# SITE SLOTS -- where buildings actually stand
# ---------------------------------------------------------------------------

# How many buildings each kind of place can show. Sized against the run that
# matters: 23 businesses were founded in 84 hours, and the land model allows ~40
# working sites plus ~75 homes. A place that runs out of slots would have to
# stack buildings on each other, which is how the old renderer drew everything.
SLOTS_PER_SPUR = 10
SLOTS_PER_HUB = 14
SLOTS_PER_WAYSTATION = 8
SLOTS_PER_WILDERNESS = 5


def _spur_slots(head: Point, approach: Point, name: str) -> list[Slot]:
    """Sites arranged around a spur's turning loop, facing inward onto it.

    Around the loop rather than in a row: a row of buildings beside a road is a
    high street, and a spur is a working dead-end -- a yard with holdings off it.
    Facing inward means the loop reads as the thing they are all there for.
    """
    r = _rng("slots", name)
    heading = math.degrees(math.atan2(head.x - approach.x, approach.y - head.y))
    out: list[Slot] = []
    for i in range(SLOTS_PER_SPUR):
        # Start behind the loop's mouth and work round, leaving the entry clear.
        a = math.radians(heading + 40.0 + i * (280.0 / SLOTS_PER_SPUR))
        ring = SPUR_LOOP_RADIUS + r.uniform(21.0, 44.0)
        x = head.x + math.sin(a) * ring
        y = head.y - math.cos(a) * ring
        out.append(Slot(x, y, facing=(math.degrees(a) + 180.0) % 360.0))
    return out


def _hub_slots(center: Point, name: str) -> list[Slot]:
    """A settlement: a square with buildings fronting onto it.

    Town holds every store in the world plus the stables and the square where
    the dead reappear, so it gets a real market square -- an inner ring facing
    in, and an outer row along the road behind it. The old renderer drew Town as
    one dot, which is a strange way to draw the only market in the economy.
    """
    r = _rng("hub", name)
    out: list[Slot] = []
    inner, outer = 88.0, 142.0
    # TWO ARCS, NOT A RING. A full ring of shops puts a building on the road at
    # the north and south of the square, because the road runs through the
    # junction the square is centred on -- `check()` caught exactly that, twice.
    # A market square has frontage down both SIDES and the road up the middle,
    # which is both correct and what the place actually is.
    per_arc = 4
    for arc_start in (25.0, 205.0):
        for i in range(per_arc):
            a = math.radians(arc_start + i * (130.0 / (per_arc - 1)) + r.uniform(-5.0, 5.0))
            out.append(Slot(
                center.x + math.sin(a) * (inner + r.uniform(-8.0, 8.0)),
                center.y - math.cos(a) * (inner + r.uniform(-8.0, 8.0)),
                facing=(math.degrees(a) + 180.0) % 360.0,
                kind="store",
            ))
    for i in range(SLOTS_PER_HUB - per_arc * 2):
        side = -1 if i % 2 == 0 else 1
        row = i // 2
        out.append(Slot(
            center.x + side * outer + r.uniform(-14.0, 14.0),
            center.y - 60.0 + row * 74.0,
            facing=90.0 if side < 0 else 270.0,
            kind="site",
        ))
    return out


def _waystation_slots(center: Point, name: str) -> list[Slot]:
    """A garrison: two rows either side of the road, inside the wall."""
    r = _rng("way", name)
    out: list[Slot] = []
    for i in range(SLOTS_PER_WAYSTATION):
        side = -1 if i % 2 == 0 else 1
        row = i // 2
        out.append(Slot(
            center.x + side * (72.0 + r.uniform(0.0, 16.0)),
            center.y - 96.0 + row * 66.0,
            facing=90.0 if side < 0 else 270.0,
            kind="civic",
        ))
    return out


def _wilderness_slots(center: Point, name: str) -> list[Slot]:
    """Scattered, well off the road. Nobody builds a high street in an ambush."""
    r = _rng("wild", name)
    out: list[Slot] = []
    # Stepped down the valley rather than placed at random y. Two draws from the
    # same uniform land on top of each other often enough that `check()` found a
    # pair every run -- randomness scatters, it does not space.
    for i in range(SLOTS_PER_WILDERNESS):
        side = -1 if i % 2 == 0 else 1
        step = (i / max(SLOTS_PER_WILDERNESS - 1, 1)) - 0.5
        out.append(Slot(
            center.x + side * r.uniform(92.0, 138.0),
            center.y + step * 260.0 + r.uniform(-22.0, 22.0),
            facing=r.uniform(0.0, 360.0),
        ))
    return out


# ---------------------------------------------------------------------------
# SCATTER -- trees and rocks
# ---------------------------------------------------------------------------

# What grows where. Terrain in `world_map` is prose; this is the same fact as
# placement rules, so the ground under a name matches what the name says.
_SCATTER: dict[str, tuple[tuple[str, ...], int]] = {
    "Refinery Row":         (("rock", "stump", "rock"), 16),
    "North Protected Zone": (("tree", "bush"), 14),
    "The Hills":            (("rock", "rock", "tree", "bush"), 34),
    "The Crossing":         (("bush", "tree", "rock"), 20),
    "The Climb":            (("rock", "rock", "rock", "stump"), 30),
    "South Protected Zone": (("tree", "tree", "bush"), 18),
    "Town":                 (("tree", "bush"), 10),
}
_SPUR_SCATTER = (("tree", "bush", "rock"), 14)

# Nothing is scattered within this many metres of a road or a building slot.
# A tree growing through a cart track is the single fastest way to make a map
# read as generated rather than designed.
_CLEARANCE = 26.0


def scatter_for(
    name: str, center: Point, roads: list[list[Point]], slots: list[Slot]
) -> list[Prop]:
    """Trees and rocks, kept off the roads and out of the doorways.

    Rejection sampling against the roads and slots rather than a tidy grid: a
    grid of trees looks planted, and this ground is not an orchard. Attempts are
    capped so a crowded place simply ends up sparser rather than looping.
    """
    kinds, count = _SCATTER.get(name, _SPUR_SCATTER)
    r = _rng("scatter", name)
    out: list[Prop] = []
    attempts = 0
    while len(out) < count and attempts < count * 12:
        attempts += 1
        x = center.x + r.uniform(-235.0, 235.0)
        y = center.y + r.uniform(-205.0, 205.0)
        if _too_close(x, y, roads, slots, out):
            continue
        out.append(Prop(
            kind=r.choice(kinds),
            x=x, y=y,
            scale=r.uniform(0.78, 1.28),
            rotation=r.uniform(0.0, 360.0),
        ))
    return out


def _too_close(
    x: float, y: float, roads: list[list[Point]], slots: list[Slot], placed: list[Prop]
) -> bool:
    for slot in slots:
        if math.hypot(x - slot.x, y - slot.y) < _CLEARANCE * 1.6:
            return True
    for prop in placed:
        if math.hypot(x - prop.x, y - prop.y) < _CLEARANCE * 0.7:
            return True
    for path in roads:
        for i in range(len(path) - 1):
            if _dist_to_segment(x, y, path[i], path[i + 1]) < _CLEARANCE:
                return True
    return False


def _dist_to_segment(px: float, py: float, a: Point, b: Point) -> float:
    dx, dy = b.x - a.x, b.y - a.y
    if dx == 0.0 and dy == 0.0:
        return math.hypot(px - a.x, py - a.y)
    t = max(0.0, min(1.0, ((px - a.x) * dx + (py - a.y) * dy) / (dx * dx + dy * dy)))
    return math.hypot(px - (a.x + t * dx), py - (a.y + t * dy))


# ---------------------------------------------------------------------------
# THE WHOLE VALLEY
# ---------------------------------------------------------------------------

def build() -> dict[str, Place]:
    """Every place in the world, positioned. The one entry point.

    Ordered junctions first so a spur can read its junction's centre. Roads are
    collected before scatter because scatter has to avoid them -- including the
    spur roads of NEIGHBOURING places, which is why the road list is global
    rather than per-place.
    """
    places: dict[str, Place] = {}
    roads: list[list[Point]] = [main_road()]

    for name in M.LOCATIONS:
        spec = M.LOCATION_BY_NAME[name]
        places[name] = Place(
            name=name, kind=spec.kind, center=junction_center(name),
            junction=None, elevation=spec.elevation, protected=spec.protected,
        )

    for junction, spurs in M.SPURS_BY_JUNCTION.items():
        for i, spur in enumerate(spurs):
            path, head = spur_geometry(spur, i)
            roads.append(path)
            parent = M.LOCATION_BY_NAME[junction]
            places[spur.name] = Place(
                name=spur.name, kind="spur", center=head, junction=junction,
                elevation=parent.elevation, protected=parent.protected,
                path=path,
                slots=_spur_slots(head, path[-2], spur.name),
            )

    for name in M.LOCATIONS:
        p = places[name]
        p.slots = (
            _hub_slots(p.center, name) if p.kind == "hub"
            else _waystation_slots(p.center, name) if p.kind == "waystation"
            else _wilderness_slots(p.center, name)
        )

    _resolve_slots(places, roads)

    for p in places.values():
        p.props = scatter_for(p.name, p.center, roads, p.slots)

    return places


# Two buildings closer than this would overlap once drawn at map scale.
MIN_SLOT_GAP = 34.0
# A building this close to a road is standing in it.
MIN_ROAD_GAP = 25.0


def _resolve_slots(places: dict[str, Place], roads: list[list[Point]]) -> None:
    """Drop any slot that stands on a road or on another building.

    A PASS RATHER THAN TUNED CONSTANTS. Getting the headings and radii right by
    hand took the collision count from 26 to 3, and the last three were places
    whose neighbours happened to reach toward them -- a class of problem that
    comes back the moment anybody adds a spur or widens the market square. So
    the invariant is enforced instead of approximated, and `check()` asserts it.

    Losing a few slots is the right trade: the valley offers 219 of them against
    23 businesses founded in the longest run so far, so capacity is nowhere near
    binding, while two buildings drawn on top of each other are visible from
    across a classroom.

    Main-road places are resolved before spurs so that a hub keeps its frontage
    and the dead-end yard gives way -- the market square is the more load-bearing
    piece of the drawing. Within that, order is by name, so the outcome does not
    depend on dictionary insertion.
    """
    kept: list[Slot] = []
    ordered = sorted(
        places.values(), key=lambda p: (p.kind == "spur", p.name)
    )
    for place in ordered:
        survivors: list[Slot] = []
        for slot in place.slots:
            if any(
                math.hypot(slot.x - k.x, slot.y - k.y) < MIN_SLOT_GAP for k in kept
            ):
                continue
            if any(
                _dist_to_segment(slot.x, slot.y, path[i], path[i + 1]) < MIN_ROAD_GAP
                for path in roads
                for i in range(len(path) - 1)
            ):
                continue
            survivors.append(slot)
            kept.append(slot)
        place.slots = survivors


def check() -> list[str]:
    """Assert the valley is drawable. Runs in `run_phase1.py`.

    Beside the economic invariants and `sprites.check()` for the same reason
    they are: it depends on `world_map`, and its failure mode is not an
    exception but a picture that is quietly wrong -- two buildings in one spot,
    a shop in the middle of the road -- discovered in front of an audience.
    """
    problems: list[str] = []
    places = build()
    roads = [main_road()] + [p.path for p in places.values() if p.path]

    for name in M.ALL_PLACES:
        if name not in places:
            problems.append(f"{name} has no position")

    loops = [(p.name, p.center) for p in places.values() if p.kind == "spur"]
    need = SPUR_LOOP_RADIUS * 2 + 90.0
    for i, (a, ca) in enumerate(loops):
        for b, cb in loops[i + 1:]:
            d = math.hypot(ca.x - cb.x, ca.y - cb.y)
            if d < need:
                problems.append(
                    f"spur loops overlap: {a} and {b} are {d:.0f}m apart, need {need:.0f}"
                )

    slots = [(p.name, s) for p in places.values() for s in p.slots]
    for i, (na, sa) in enumerate(slots):
        for nb, sb in slots[i + 1:]:
            if math.hypot(sa.x - sb.x, sa.y - sb.y) < MIN_SLOT_GAP:
                problems.append(f"building slots collide: {na} and {nb}")
        on_road = min(
            _dist_to_segment(sa.x, sa.y, path[j], path[j + 1])
            for path in roads for j in range(len(path) - 1)
        )
        if on_road < MIN_ROAD_GAP:
            problems.append(f"{na} has a building slot in the road ({on_road:.0f}m)")

    for p in places.values():
        for q in p.props:
            d = min(
                _dist_to_segment(q.x, q.y, path[j], path[j + 1])
                for path in roads for j in range(len(path) - 1)
            )
            if d < _CLEARANCE * 0.8:
                problems.append(f"{p.name} has a {q.kind} growing in the road")

    # Equal distances are the promise the engine makes; see the module docstring.
    lengths = {
        M.LOCATIONS[i]: math.hypot(
            junction_center(M.LOCATIONS[i + 1]).x - junction_center(M.LOCATIONS[i]).x,
            junction_center(M.LOCATIONS[i + 1]).y - junction_center(M.LOCATIONS[i]).y,
        )
        for i in range(len(M.LOCATIONS) - 1)
    }
    if lengths and (max(lengths.values()) - min(lengths.values())) > 0.5:
        problems.append(
            f"road segments are drawn unequal ({min(lengths.values()):.0f}-"
            f"{max(lengths.values()):.0f}m) -- the engine makes them the same distance"
        )
    return problems


def bounds(places: dict[str, Place]) -> tuple[float, float, float, float]:
    """(min_x, min_y, max_x, max_y) with room for the widest thing drawn."""
    xs, ys = [], []
    for p in places.values():
        for pt in [p.center, *p.path]:
            xs.append(pt.x); ys.append(pt.y)
        for s in p.slots:
            xs.append(s.x); ys.append(s.y)
        for q in p.props:
            xs.append(q.x); ys.append(q.y)
    pad = 90.0
    return min(xs) - pad, min(ys) - pad, max(xs) + pad, max(ys) + pad
