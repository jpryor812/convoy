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
# THE GROUND GREW; THE BUILDINGS DID NOT.
#
# Businesses now expand -- a site that develops twelve plots is drawn larger than
# one on its founding four (`building_scale` below). At the valley's original
# size there was nowhere to put that growth: the tightest surviving pair of
# building slots stood 43m apart against a 34m rule, and the two closest spur
# loops had THREE metres of clearance. Widening a square locally was not
# available, because every spur runs the same distance out and moving one moves
# all sixteen.
#
# So the ground was scaled instead, uniformly. Every distance in this section is
# multiplied; every FOOTPRINT -- road width, tree clearance, the building box
# itself -- is not. That is the whole trick: the valley is 1.8x roomier while a
# farmhouse is still a farmhouse, which is where the space to grow into comes
# from.
#
# Uniform is what keeps it honest. The module docstring's rule -- equal segments,
# equal spurs, because the engine makes them equal -- survives any scale factor
# applied to all of them at once. A local widening would not have survived it.
GROUND_SCALE = 1.8

SEGMENT_LENGTH = 430.0 * GROUND_SCALE   # metres between adjacent junctions, all equal

# SPURS GREW LESS THAN THE ROAD DID, and that is a drawing choice rather than a
# compromise. The docstring's rule is that all spurs are drawn EQUAL TO EACH
# OTHER, because the engine makes them all ninety seconds; it says nothing about
# how a spur compares to a road segment, and it cannot, because the map is
# already not to travel scale.
#
# The ratio had to give when the ends were cleared of spurs (see `SPURS` in
# `world_map`): sixteen spurs across five middle junctions puts four on The
# Crossing and three on each of its neighbours, and at the full 1.8x depth their
# turning loops reached into each other -- `check()` caught two. Shortening the
# spurs while the segments stay long is what opens the gap between neighbouring
# junctions, and it reads correctly too: a long valley road with short working
# lanes off it.
SPUR_DEPTH = 305.0 * 1.2                # metres from junction to the head of a spur
SPUR_LOOP_RADIUS = 78.0 * 1.4           # the turning circle a spur dead-ends in

# NOT scaled: a road is as wide as a cart, whatever the valley measures.
ROAD_WIDTH = 9.0
SPUR_WIDTH = 6.0

# How far a junction may wander off the valley's centre line. Enough to read as
# a road following the ground, small enough that the road never doubles back and
# make a southward journey look northward.
MAX_WANDER = 110.0 * GROUND_SCALE


# ---------------------------------------------------------------------------
# HOW BIG A BUILDING IS DRAWN
# ---------------------------------------------------------------------------

# A building occupies its block: `BLOCK_PITCH` metres, which at the map's one
# pixel to the metre is exactly the 64px canvas the pack draws a structure on.
BUILDING_BASE_M = 64.0

# Expansion shows. A business holds `SITE_BASE_PLOTS` when founded and may buy
# and develop more; each plot beyond the base draws it 10% larger.
#
# LINEAR, NOT COMPOUNDING. At 10% per plot compounding a site holding a whole
# spur's 40 plots would be drawn 45x its founding size; linear puts it at 4.6x.
#
# THE CLAMP CAME DOWN FROM 1.8 TO 1.15 when the land grid arrived, and the reason
# is worth stating because it looks like a retreat. A building fills its block
# almost exactly, so most of that 1.8 was always going to spill onto the
# neighbours. It no longer needs to: EXPANSION IS SHOWN BY LAND NOW. Twelve
# plots is twelve flagged squares against four, drawn on the ground, exactly
# countable -- which is a better report than a building 80% wider that the eye
# cannot measure anyway.
#
# What is left of the growth is a nudge. 1.3 was tried first and was too much:
# a building fills 63 of its block's 64 pixels, so at 1.3 a weaponsmith reached
# across the boundary and sat on the neighbouring holding's roof. 1.15 spills
# about four pixels, onto parcels the business owns anyway.
BUILDING_GROWTH_PER_PLOT = 0.10
MAX_BUILDING_SCALE = 1.15


def building_scale(developed_plots: int) -> float:
    """How many times its base size a business's building is drawn."""
    extra = max(developed_plots - M.SITE_BASE_PLOTS, 0)
    return min(1.0 + BUILDING_GROWTH_PER_PLOT * extra, MAX_BUILDING_SCALE)


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
class Parcel:
    """One plot of ground, positioned. A flag flies here when somebody owns it.

    `layout` knows where the plots ARE; `world_map` knows how many there are and
    `state.Plot` knows who holds each one. Position is kept apart from ownership
    on purpose -- ground does not move when it is sold, and a renderer that
    rebuilt positions from the run's plot list would shuffle the whole valley
    every time a plot changed hands.

    `index` is the parcel's rank in the place, centre outward. See `_parcels`.
    """

    x: float
    y: float
    index: int


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
    parcels: list[Parcel] = field(default_factory=list)  # one per plot of land


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


def _wander(name: str) -> float:
    """The hand-authored offset above, in scaled ground metres.

    Scaled on read rather than baked into the table, so the column above stays
    the readable shape of the road -- west through the hills, square onto the
    bridge -- instead of seven numbers nobody can eyeball against each other.
    """
    return _WANDER[name] * GROUND_SCALE


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
        dx = _wander(M.LOCATIONS[i]) - _wander(M.LOCATIONS[i - 1])
        y += math.sqrt(max(SEGMENT_LENGTH ** 2 - dx ** 2, 1.0))
    return Point(_wander(name), y)


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

# Which way each junction's spurs point, in degrees clockwise from north.
# MINIMUM SEPARATION IS GEOMETRY, NOT TASTE. Two spurs off one junction run the
# same distance out (they must -- see the module docstring), so the only thing
# keeping their turning loops apart is the angle between them. Two loops need
# 2r + clearance between centres; at SPUR_DEPTH that works out to ~57 degrees,
# and the first draft of this table had pairs 20 and 25 degrees apart. Six of
# the sixteen loops overlapped, which `check()` now refuses to let happen again.
_MIN_SPUR_SEPARATION = 62.0

# THE ENDS CARRY NOTHING. Refinery Row and Town have no spurs at all now -- see
# the note above `SPURS` in `world_map`. All sixteen hang off the five middle
# junctions, so every mine and farm is a haul away from a smelter in one
# direction and from a buyer in the other.
#
# TWO RULES SHAPE THIS TABLE, and the second one only appeared once the ends
# were cleared.
#
# First: nothing points near 0 or 180, because that is where the main road runs
# and a spur setting off along it would be drawn crossing it. East headings sit
# around 90, west around 270.
#
# Second: A JUNCTION FANS HEAVILY TO ONE SIDE, AND ITS NEIGHBOURS FAN TO THE
# OTHER. A pair of spurs 62 degrees apart straddles the perpendicular, so one of
# them tilts back up the road and one tilts down it -- toward the next junction's
# spurs. When two adjacent junctions both had a pair on the same side, those two
# tilted spurs met in the middle, which is precisely the pair of collisions
# `check()` reported. Alternating the heavy side means a tilted spur only ever
# meets a perpendicular one, which has no reach along the road at all.
#
# The Crossing is the exception and has to be: it carries four, so it fans both
# ways. Its neighbours are both weighted west, which is why the shortened
# SPUR_DEPTH above matters -- west pair against west pair is the one case left
# that has to clear on distance alone.
_EAST_PAIR = [59.0, 121.0]
_WEST_PAIR = [239.0, 301.0]
_DUE_EAST, _DUE_WEST = 90.0, 270.0

_SPUR_HEADINGS: dict[str, list[float]] = {
    "Refinery Row":         [],
    "North Protected Zone": [*_EAST_PAIR, _DUE_WEST],
    "The Hills":            [*_WEST_PAIR, _DUE_EAST],
    "The Crossing":         [*_EAST_PAIR, *_WEST_PAIR],
    "The Climb":            [*_WEST_PAIR, _DUE_EAST],
    "South Protected Zone": [*_EAST_PAIR, _DUE_WEST],
    "Town":                 [],
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
# THE LAND GRID -- parcels, and the buildings that stand on them
# ---------------------------------------------------------------------------

# ONE BUILDING IS FOUR PLOTS, AND THE MAP SHOWS IT.
#
# `SITE_BASE_PLOTS` has always been 4 -- a business is founded on the building
# plus two places to put people -- but nothing about the drawing said so. Slots
# were arranged on rings and arcs by one set of functions and parcels were tiled
# by another, so a building stood wherever the ring put it and the ground it
# supposedly occupied was somewhere else entirely. Two drawings of the same fact,
# agreeing nowhere.
#
# Now there is one drawing. The land is an even grid of square parcels; a site is
# a 2x2 BLOCK of them; and the building is drawn at the block's centre, which is
# the shared corner of its four plots. A founding business visibly sits on four
# squares of ground, and buying a fifth visibly adds one more.
#
# THE ARITHMETIC WORKS OUT EXACTLY, which is the reason to trust it. Every plot
# supply in `world_map` divides by four with nothing left over -- Town 60 into 15
# blocks, a spur 40 into 10, a protected zone 28 into 7 -- so "how much land is
# here" and "how many businesses fit here" stop being two numbers that have to be
# kept in agreement and become the same number counted two ways.
PARCEL_PITCH = 32.0
BLOCK_PITCH = PARCEL_PITCH * 2          # a site: two parcels by two

# A LANE BETWEEN EVERY HOLDING. Blocks used to be laid edge to edge, which made
# a settlement one continuous slab of property with no way through it -- correct
# about the land and wrong about the place. A town is holdings with streets
# between them, and the street is what makes the property lines read as property
# lines rather than as a grid drawn over a field.
#
# One parcel wide, so the lane is the same unit as everything else: two
# neighbouring blocks each give up half of it and the street between them comes
# out a full parcel across.
PATH_WIDTH = PARCEL_PITCH
BLOCK_STRIDE = BLOCK_PITCH + PATH_WIDTH


def slots_needed(name: str) -> int:
    """How many businesses the land at `name` seats, and so how many to draw."""
    return M.plots_at(name) // M.SITE_BASE_PLOTS


# ---------------------------------------------------------------------------
# THE RIVER
# ---------------------------------------------------------------------------

# THE CROSSING IS A CROSSING OF SOMETHING. `world_map` has always said so -- the
# bridge is the one road segment where `can_flee_offroad()` is False, "because a
# bridge has a river on both sides" -- but nothing drew the river, and the first
# attempt put a round pond at the junction, which reads as a village duck pond
# rather than as the reason the road narrows to a bridge.
#
# A river is a BAND, not a blob: it runs across the valley, the road meets it at
# one point, and that point is a bridge. Drawn that way it explains the map --
# why there is a settlement here at all, and why this is the segment you cannot
# run off the road from.
#
# It lives here rather than in the renderer because it takes up ground. Land at
# The Crossing is sold by the plot like anywhere else, and a parcel in the middle
# of a river is not a parcel; `_block_grid` treats the water as an obstacle
# exactly like a road, so the settlement grows on both banks instead of into the
# water.
RIVER_HALF_WIDTH = 72.0          # 144m bank to bank: three ground tiles
# Clearance from the water's edge before a building may stand. Rather more than
# the road's, because a bank is soft ground and because it leaves room for the
# bridge approach to read.
RIVER_BANK_CLEARANCE = 26.0


def river_axis() -> float:
    """The river's centre, as a position along the valley road (world y).

    ON THE BRIDGE SEGMENT, NOT AT THE CROSSING JUNCTION -- read off `world_map`
    rather than guessed. Exactly one road segment in the world has
    `can_flee_offroad()` False, it is named "The Bridge", and the reason given
    there is that a bridge has a river on both sides. So that segment IS the
    river, and this puts the water across the middle of it.
    
    Putting it on the junction instead was the obvious reading of the name "The
    Crossing" and it was wrong twice over. Four spurs radiate from that junction,
    so their first stretch ran over open water and the map grew a starburst of
    bridge decks; and it left the one segment the engine calls a bridge with
    nothing to cross. Here, no junction and no spur touches the water, exactly
    one road crosses it, and the rule that you cannot leave the road on this
    stretch is something a viewer can now see.
    """
    a = junction_center("The Crossing").y
    b = junction_center("The Climb").y
    return (a + b) / 2.0


def in_river(y: float, margin: float = 0.0) -> bool:
    """Is this position along the valley in the water?"""
    return abs(y - river_axis()) < RIVER_HALF_WIDTH + margin


def _block_grid(
    center: Point, name: str, roads: list[list[Point]],
    taken: list[Slot] | None = None,
) -> tuple[list[Slot], list[Parcel]]:
    """Lay out a place's blocks, nearest the centre first, and clear of the road.

    ORDER IS THE ECONOMIC CLAIM. Blocks are taken centre-outward, and plots are
    handed out in the order they are bought (`state.Plot` ids are sequential and
    never reused), so the first business to buy at Town gets the ground fronting
    the market and one arriving at hour 40 builds on the edge of the settlement.
    That is the right story about a scarce central resource and it costs nothing
    to order the list this way.

    A block is rejected whole. Half a site is not a site, and a building whose
    four plots straddle a road is exactly the picture this grid exists to stop.

    `taken` is every block already placed anywhere in the valley. Places are
    close enough to reach into each other -- The Crossing and Kiln Row collided
    the moment the river pushed The Crossing's blocks off the water and outward
    -- and a lattice that only knows its own place cannot see that coming.
    Main-road places are laid before spurs so a settlement keeps its ground and
    the dead-end lane gives way, which is the same precedence the old
    collision-resolving pass used.
    """
    need = slots_needed(name)
    if not need:
        return [], []

    candidates: list[tuple[float, float, float]] = []
    ring = 0
    # Widen until enough clear blocks are found. The radius grows rather than
    # being computed because the road removes an unpredictable number of them.
    while len(candidates) < need and ring < 30:
        ring += 1
        for gx in range(-ring, ring + 1):
            for gy in range(-ring, ring + 1):
                if max(abs(gx), abs(gy)) != ring:
                    continue          # only the new shell
                bx = center.x + gx * BLOCK_STRIDE
                by = center.y + gy * BLOCK_STRIDE
                if _block_on_road(bx, by, roads):
                    continue
                if taken and any(
                    math.hypot(bx - t.x, by - t.y) < BLOCK_STRIDE - 0.5
                    for t in taken
                ):
                    continue
                candidates.append((math.hypot(bx - center.x, by - center.y), bx, by))
        candidates.sort()

    slots: list[Slot] = []
    parcels: list[Parcel] = []
    half = PARCEL_PITCH / 2.0
    for i, (_, bx, by) in enumerate(sorted(candidates)[:need]):
        slots.append(Slot(bx, by, facing=_faces(bx, by, roads),
                          kind=_slot_kind(name, i)))
        # The four plots of the block, in a stable order so a plot's position
        # never changes once it has been drawn.
        for dx, dy in ((-half, -half), (half, -half), (-half, half), (half, half)):
            parcels.append(Parcel(x=bx + dx, y=by + dy, index=len(parcels)))
    return slots, parcels


def _slot_kind(name: str, index: int) -> str:
    """What sort of frontage this is -- used for colour in `preview_layout`."""
    kind = M.LOCATION_BY_NAME[name].kind if name in M.LOCATION_BY_NAME else "spur"
    if kind == "waystation":
        return "civic"
    if kind == "hub":
        # The blocks nearest the middle of a settlement are its shopfronts.
        return "store" if index < slots_needed(name) // 2 else "site"
    return "site"


def _faces(x: float, y: float, roads: list[list[Point]]) -> float:
    """Degrees clockwise from north, pointing at the nearest piece of road.

    Kept even though the 2D map ignores it -- a Kenney structure is drawn with a
    fixed front and cannot be turned. The 3D scene will want it, and working it
    out here means both views agree about which way a building faces.
    """
    best, angle = float("inf"), 180.0
    for path in roads:
        for i in range(len(path) - 1):
            d = _dist_to_segment(x, y, path[i], path[i + 1])
            if d < best:
                best = d
                mx = (path[i].x + path[i + 1].x) / 2.0
                my = (path[i].y + path[i + 1].y) / 2.0
                angle = math.degrees(math.atan2(mx - x, y - my)) % 360.0
    return angle


def _block_on_road(bx: float, by: float, roads: list[list[Point]]) -> bool:
    """Is any part of this 2x2 block in a road corridor, or in the river?"""
    half = PARCEL_PITCH / 2.0
    for dx in (-half, half):
        for dy in (-half, half):
            x, y = bx + dx, by + dy
            if in_river(y, RIVER_BANK_CLEARANCE):
                return True
            for path in roads:
                for i in range(len(path) - 1):
                    if _dist_to_segment(x, y, path[i], path[i + 1]) < MIN_ROAD_GAP:
                        return True
    return False


# ---------------------------------------------------------------------------
# SCATTER -- trees and rocks
# ---------------------------------------------------------------------------

# What grows where. Terrain in `world_map` is prose; this is the same fact as
# placement rules, so the ground under a name matches what the name says.
# NO BUSHES. They were a third of the ground clutter and drew as Pipoya's dark
# thorn scrub, which at map size is a smudge -- indistinguishable from a rock and
# adding nothing a tree does not add better. Trees read as trees at any zoom, so
# every bush is now a tree and the mix is trees against rock.
_SCATTER: dict[str, tuple[tuple[str, ...], int]] = {
    "Refinery Row":         (("rock", "stump", "rock"), 16),
    "North Protected Zone": (("tree", "tree"), 14),
    "The Hills":            (("rock", "rock", "tree", "tree"), 34),
    "The Crossing":         (("tree", "tree", "rock"), 20),
    "The Climb":            (("rock", "rock", "rock", "stump"), 30),
    "South Protected Zone": (("tree", "tree", "tree"), 18),
    "Town":                 (("tree", "tree"), 10),
}
_SPUR_SCATTER = (("tree", "tree", "rock"), 14)

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
        x = center.x + r.uniform(-235.0, 235.0) * GROUND_SCALE
        y = center.y + r.uniform(-205.0, 205.0) * GROUND_SCALE
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
    # Trees do not grow in rivers. Cheap to check and it was very visible: the
    # first render of the water had boulders and oaks standing mid-channel.
    if in_river(y):
        return True
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
            )

    # Buildings and land come out of ONE pass now, because they are one fact --
    # see the note above `PARCEL_PITCH`. Every road in the world is known by this
    # point, including neighbouring places' spurs, which is what stops a block
    # being laid across a road that belongs to somebody else.
    taken: list[Slot] = []
    for p in sorted(places.values(), key=lambda q: (q.kind == "spur", q.name)):
        p.slots, p.parcels = _block_grid(p.center, p.name, roads, taken)
        taken.extend(p.slots)

    for p in places.values():
        p.props = scatter_for(p.name, p.center, roads, p.slots)

    return places


# ONE STRIDE APART, BY CONSTRUCTION. Buildings used to be placed freely and then
# checked for overlap; now they sit on a grid and are exactly `BLOCK_STRIDE`
# apart, so this is no longer a spacing rule to satisfy -- it is a statement of
# what the grid guarantees, kept because `check()` asserting it is what would
# catch somebody changing the block arithmetic without meaning to.
MIN_SLOT_GAP = BLOCK_STRIDE
# A building this close to a road is standing in it: half a block, half a road,
# and clearance for the verge.
MIN_ROAD_GAP = (BUILDING_BASE_M + ROAD_WIDTH) / 2.0 + 8.0


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

    # CAPACITY IS AN INVARIANT, NOT AN AMBITION. The land system sells a place's
    # ground and the geometry has to seat everything that ground can hold, or
    # businesses stop being drawn without anything erroring -- see `slots_needed`.
    # Checked here rather than trusted, because the failure is silent and the
    # numbers move whenever anybody retunes a square or adds a spur.
    for name, place in places.items():
        need = slots_needed(name)
        if len(place.slots) < need:
            problems.append(
                f"{name} seats {len(place.slots)} buildings but sells land for "
                f"{need} -- {need - len(place.slots)} would not be drawn"
            )

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
            # Tolerance, because neighbouring blocks are EXACTLY one pitch
            # apart and floating point lands some of them a hair under it. The
            # rule being enforced is "no closer than adjacent", not "strictly
            # further apart than adjacent", which nothing on a grid can be.
            if math.hypot(sa.x - sb.x, sa.y - sb.y) < MIN_SLOT_GAP - 0.5:
                problems.append(f"building slots collide: {na} and {nb}")
        on_road = min(
            _dist_to_segment(sa.x, sa.y, path[j], path[j + 1])
            for path in roads for j in range(len(path) - 1)
        )
        if on_road < MIN_ROAD_GAP:
            problems.append(f"{na} has a building slot in the road ({on_road:.0f}m)")

    # Nothing stands in the water. `_block_grid` already refuses to put a block
    # there, so this catches the river being moved or widened without anybody
    # re-running the layout.
    for name, place in places.items():
        for slot in place.slots:
            if in_river(slot.y):
                problems.append(f"{name} has a building slot in the river")
                break
        for parcel in place.parcels:
            if in_river(parcel.y):
                problems.append(f"{name} sells a plot in the river")
                break

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
