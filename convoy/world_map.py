"""The world: one dangerous road, seven places on it, sixteen spurs hanging off it.

Geography comes from the World tab (seven named locations, a single road from
Refinery Row to Town, ~5 minutes end to end at Medium speed, spur roads that
dead-end and loop back to the same junction). Everything below that -- terrain,
elevation, per-segment danger, spur placement -- is the 2026-08-12 world design.

THE SHAPE OF IT

    Refinery Row ── North Protected ── The Hills ── The Crossing ── The Climb
    ── South Protected ── Town

Two protected waystations bracket the hazardous middle three. Production sits at
the north end (refineries, and the government mine and farm on the two spurs
closest to them); the market sits at the south end (Town). So goods must cross
all three dangerous segments to reach a buyer -- which is the whole game.

WHY EACH SEGMENT IS DANGEROUS IN ITS OWN WAY

Danger is not one number. An ambusher wants three different things, and each
stretch of road offers a different mix:

  * CONCEALMENT -- can I set up unseen? Beats Scouts, who watch the road.
  * VANTAGE     -- do I strike first, from above?
  * EXPOSURE    -- is the convoy unable to escape once committed?

The Hills are all concealment (broken ground, blind bends) but poor vantage. The
Crossing is all exposure (a bridge is a chokepoint with a river on both sides, so
Flee Off-Road is not an option) but easy to spot an ambusher on. The Climb is the
worst of all worlds for a convoy: slow going, and overlooked from above.
"""

from __future__ import annotations

from dataclasses import dataclass, field

# ---------------------------------------------------------------------------
# Named places on the main road
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Location:
    name: str
    kind: str            # hub | waystation | wilderness
    elevation: int       # metres above the valley floor -- flavour, and why climbs are slow
    protected: bool      # no combat, no theft, police present
    blurb: str


LOCATIONS_SPEC: list[Location] = [
    Location(
        "Refinery Row", "hub", 40, False,
        "Smoke and slag at the valley's north end. Every refinery in the world is "
        "here, and so is everything worth stealing before it has been sold.",
    ),
    Location(
        "North Protected Zone", "waystation", 55, True,
        "A walled garrison waystation. No blade may be drawn and no purse cut; "
        "police stand at the gate. The last safe ground heading south.",
    ),
    Location(
        "The Hills", "wilderness", 180, False,
        "Rolling broken country of boulders and blind bends. Nowhere on the road "
        "offers an ambusher better cover to set up unseen.",
    ),
    Location(
        "The Crossing", "wilderness", 20, False,
        "The river, and the only bridge over it. The lowest, narrowest point on "
        "the road -- and the one place a convoy cannot simply leave the road.",
    ),
    Location(
        "The Climb", "wilderness", 340, False,
        "Switchbacks up the mountain's shoulder. Carts crawl, and every metre of "
        "the ascent is overlooked from the rocks above.",
    ),
    Location(
        "South Protected Zone", "waystation", 90, True,
        "The southern garrison. Convoys that make it this far have made it. "
        "No combat, no theft, police at the gate.",
    ),
    Location(
        "Town", "hub", 30, True,
        "The market. Every store, the stables, the tavern and the town square "
        "where the dead reappear. Protected ground -- deals are struck, not taken.",
    ),
]

LOCATIONS: list[str] = [loc.name for loc in LOCATIONS_SPEC]
LOCATION_BY_NAME: dict[str, Location] = {loc.name: loc for loc in LOCATIONS_SPEC}
PROTECTED_ZONES: set[str] = {loc.name for loc in LOCATIONS_SPEC if loc.protected}

# ---------------------------------------------------------------------------
# The six road segments between them
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RoadSegment:
    a: str
    b: str
    name: str
    terrain: str
    base_seconds: float      # at Medium speed, before terrain
    speed_modifier: float    # <1 means slower going
    concealment: float       # 0-1: how well an ambusher hides from Scouts
    vantage: float           # 0-1: attacker's first-strike advantage
    exposure: float          # 0-1: how trapped the convoy is (blocks Flee Off-Road)
    blurb: str

    @property
    def seconds(self) -> float:
        """Actual traversal time at Medium speed, terrain included."""
        return self.base_seconds / self.speed_modifier

    @property
    def danger(self) -> float:
        """Single headline number for reports and agent context."""
        return round((self.concealment + self.vantage + self.exposure) / 3.0, 3)

    def can_flee_offroad(self) -> bool:
        """A bridge over a river has no off-road to flee to."""
        return self.exposure < 0.75


# Every segment is the same distance; terrain is what makes them differ. Base is
# tuned so the full run still takes ~5 minutes at Medium once slow ground is
# accounted for (see SANITY CHECK at the bottom of this file).
_BASE = 45.0

SEGMENTS: list[RoadSegment] = [
    RoadSegment(
        "Refinery Row", "North Protected Zone", "Slagside Road", "industrial flats",
        _BASE, 1.00, 0.15, 0.10, 0.15,
        "Straight, open, overlooked by the refineries themselves. Little cover for "
        "anyone with bad intentions.",
    ),
    RoadSegment(
        "North Protected Zone", "The Hills", "Hollow Road", "scrubland",
        _BASE, 1.00, 0.40, 0.20, 0.25,
        "The garrison falls away behind and the scrub thickens. The first stretch "
        "where a convoy is genuinely alone.",
    ),
    RoadSegment(
        "The Hills", "The Crossing", "Broken Country", "boulders and blind bends",
        _BASE, 0.90, 0.85, 0.45, 0.35,
        "The classic ambush ground. A crew can sit in the rocks a spear's throw "
        "from the road and never be seen until the carts are level with them.",
    ),
    RoadSegment(
        "The Crossing", "The Climb", "The Bridge", "river crossing",
        _BASE, 1.00, 0.35, 0.30, 0.90,
        "One bridge, water on both sides. An ambusher here is easy to spot and "
        "impossible to escape -- there is no off-road to flee onto.",
    ),
    RoadSegment(
        "The Climb", "South Protected Zone", "The Switchbacks", "mountain ascent",
        _BASE, 0.65, 0.55, 0.90, 0.50,
        "Carts crawl up the switchbacks while anyone above picks their moment. "
        "The slowest ground on the road and the most thoroughly overlooked.",
    ),
    RoadSegment(
        "South Protected Zone", "Town", "Market Road", "farmland approach",
        _BASE, 1.00, 0.15, 0.10, 0.15,
        "Busy, open, patrolled at the edges. Trouble here is trouble in sight of "
        "the whole market.",
    ),
]

SEGMENT_BY_PAIR: dict[tuple[str, str], RoadSegment] = {}
for _s in SEGMENTS:
    SEGMENT_BY_PAIR[(_s.a, _s.b)] = _s
    SEGMENT_BY_PAIR[(_s.b, _s.a)] = _s

# ---------------------------------------------------------------------------
# Sixteen spur roads
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Spur:
    name: str
    junction: str        # the main-road location it branches from
    seconds_deep: float  # one way at Medium; dead-ends and loops back
    plots: int           # how many mines/farms/homes fit down it
    blurb: str


# Ninety seconds deep at Medium, dead-ending in a loop -- so a round trip down a
# spur costs three minutes, a full minute more than the entire road takes to
# cross. Distance from the market is a real cost, which is what makes northern
# ground cheap in effort but far from any buyer.
SPUR_SECONDS = 90.0

# PLOTS ARE LAND, NOT SLOTS. A spur holds a fixed acreage and different things
# take different amounts of it:
#
#   starter home        4 plots   (+1 per storage or garage tier)
#   starter mine/farm   8 plots   (+4 per expansion)
#
# 16 spurs x 40 plots = 640 plots. The state's mine and farm take 16, leaving
# 624 -- enough for ~40 working sites AND ~75 homes at once, so land stops being
# the binding constraint. At 320 plots the previous layout filled completely by
# hour 48 and squeezed homes out entirely; this leaves real headroom.
PLOTS_PER_SPUR = 40
HOME_BASE_PLOTS = 4
SITE_BASE_PLOTS = 8
SITE_EXPANSION_PLOTS = 4

# Only extraction sites live on spur land. Refineries, stores, the tavern and the
# brokerage sit on the main road and consume no plots.
PLOT_CONSUMING_BUSINESSES = ("Mining Operation", "Farm")

SPURS: list[Spur] = [
    # Refinery Row -- three spurs, the industrial north. The state's mine and
    # farm sit on the first two, closest to the smelters.
    Spur("Copper Gulch", "Refinery Row", SPUR_SECONDS, PLOTS_PER_SPUR,
         "Ore country, minutes from the smelters. The government mine works the head of the gulch."),
    Spur("Millrace Farms", "Refinery Row", SPUR_SECONDS, PLOTS_PER_SPUR,
         "Irrigated bottomland fed by the mill race. The government farm holds the best of it."),
    Spur("Slagfoot Yards", "Refinery Row", SPUR_SECONDS, PLOTS_PER_SPUR,
         "Tailings and cinder flats below the refineries. Cheap ground, filthy air, ore underfoot."),
    # North Protected Zone -- safe ground behind the garrison wall.
    Spur("Garrison Fields", "North Protected Zone", SPUR_SECONDS, PLOTS_PER_SPUR,
         "Smallholdings under the garrison's eye. Safe, and priced like it."),
    Spur("Watchman's Lane", "North Protected Zone", SPUR_SECONDS, PLOTS_PER_SPUR,
         "A quiet row of holdings inside the northern writ. Nothing happens here, which is the point."),
    # The Hills -- broken country, the classic ambush ground.
    Spur("Blindfold Draw", "The Hills", SPUR_SECONDS, PLOTS_PER_SPUR,
         "A dead-end draw in the hills. Good stone, bad neighbours."),
    Spur("Rockfall Cut", "The Hills", SPUR_SECONDS, PLOTS_PER_SPUR,
         "A scar of loose scree and boulders. Rich in stone and clay, and impossible to watch."),
    # The Crossing -- the river and its flats.
    Spur("Ferryman's Bend", "The Crossing", SPUR_SECONDS, PLOTS_PER_SPUR,
         "River flats above the bridge. Clay, water, and a view of everyone who crosses."),
    Spur("Wash Hollow", "The Crossing", SPUR_SECONDS, PLOTS_PER_SPUR,
         "Silt bottoms below the ford. Floods in season, grows anything the rest of the year."),
    # The Climb -- the mountain shoulder.
    Spur("Eagle's Rest", "The Climb", SPUR_SECONDS, PLOTS_PER_SPUR,
         "Cut into the mountainside. Hard ground, hard living, and it sees everything."),
    Spur("Scree Terrace", "The Climb", SPUR_SECONDS, PLOTS_PER_SPUR,
         "Stepped ledges hacked from the slope. Iron in the rock and a long way down."),
    # South Protected Zone -- the desirable southern addresses.
    Spur("Southgate Commons", "South Protected Zone", SPUR_SECONDS, PLOTS_PER_SPUR,
         "Orchards and cottages behind the southern wall. The desirable address."),
    Spur("Orchard Walk", "South Protected Zone", SPUR_SECONDS, PLOTS_PER_SPUR,
         "Walled gardens and grain plots inside the southern writ. Safe, fertile, and sought after."),
    # Town -- three spurs, closest to every buyer in the world.
    Spur("Kiln Row", "Town", SPUR_SECONDS, PLOTS_PER_SPUR,
         "Workshops and yards on the town's edge. Closest to a buyer, dearest to hold."),
    Spur("Potters Yard", "Town", SPUR_SECONDS, PLOTS_PER_SPUR,
         "Clay pits and drying sheds a stone's throw from the market square."),
    Spur("Drovers End", "Town", SPUR_SECONDS, PLOTS_PER_SPUR,
         "Paddocks and grain stores where the carts come in. Crowded, and worth it."),
]

SPUR_BY_NAME: dict[str, Spur] = {s.name: s for s in SPURS}
SPURS_BY_JUNCTION: dict[str, list[Spur]] = {}
for _sp in SPURS:
    SPURS_BY_JUNCTION.setdefault(_sp.junction, []).append(_sp)

# Where the government's own operations sit. Mine and farm go on the two spurs
# closest to the refineries, per the world design -- the state's supply chain is
# short, and everyone else has to beat it on price or distance.
GOVERNMENT_SITES: dict[str, str] = {
    "Refinery": "Refinery Row",
    "Mining Operation": "Copper Gulch",
    "Farm": "Millrace Farms",
    "General Store": "Town",
    "Home Improvement Store": "Town",
    "Mining/Farming Equipment Store": "Town",
    "Weaponsmith / Armory": "Town",
    "Vehicle Dealer / Stable": "Town",
    "Tavern / Inn": "South Protected Zone",
    "Private Security Contractor": "North Protected Zone",
    "Insurance Brokerage": "Town",
}

ALL_PLACES: list[str] = LOCATIONS + [s.name for s in SPURS]


# ---------------------------------------------------------------------------
# Travel
# ---------------------------------------------------------------------------

def is_spur(place: str) -> bool:
    return place in SPUR_BY_NAME


def junction_of(place: str) -> str:
    """The main-road location a place sits on or hangs off."""
    return SPUR_BY_NAME[place].junction if is_spur(place) else place


def is_protected(place: str) -> bool:
    """No combat, no theft, police present.

    A spur inherits the protection of its junction -- the garrison's writ runs
    down the lanes behind its walls.
    """
    return junction_of(place) in PROTECTED_ZONES


def road_path(a: str, b: str) -> list[RoadSegment]:
    """Segments crossed travelling the main road from `a` to `b`."""
    i, j = LOCATIONS.index(a), LOCATIONS.index(b)
    if i == j:
        return []
    step = 1 if j > i else -1
    return [
        SEGMENT_BY_PAIR[(LOCATIONS[k], LOCATIONS[k + step])]
        for k in range(i, j, step)
    ]


def travel_path(origin: str, destination: str) -> tuple[float, list[RoadSegment]]:
    """Seconds at Medium speed, plus the road segments actually crossed.

    A spur dead-ends, so any journey from one spur to another climbs back to its
    junction, runs the road, then goes back down. Spur time never counts as road
    time -- convoys never use spurs, only solo trips do.
    """
    if origin == destination:
        return 0.0, []

    seconds = 0.0
    if is_spur(origin):
        seconds += SPUR_BY_NAME[origin].seconds_deep
    if is_spur(destination):
        seconds += SPUR_BY_NAME[destination].seconds_deep

    segments = road_path(junction_of(origin), junction_of(destination))
    seconds += sum(s.seconds for s in segments)
    return seconds, segments


def travel_seconds(origin: str, destination: str, speed_mult: float = 1.0) -> float:
    """Travel time for a given vehicle speed multiplier (1.0 == Medium)."""
    seconds, _ = travel_path(origin, destination)
    return seconds / max(speed_mult, 1e-9)


def most_dangerous_segment(origin: str, destination: str) -> RoadSegment | None:
    _s, segments = travel_path(origin, destination)
    return max(segments, key=lambda s: s.danger) if segments else None


def describe(place: str) -> str:
    if is_spur(place):
        sp = SPUR_BY_NAME[place]
        return f"{sp.name} (spur off {sp.junction}) — {sp.blurb}"
    loc = LOCATION_BY_NAME[place]
    guard = "protected" if loc.protected else "unprotected"
    return f"{loc.name} ({guard}, {loc.elevation}m) — {loc.blurb}"


# ---------------------------------------------------------------------------
# SANITY CHECK -- the World tab's "~5 min full transit at Medium speed"
# ---------------------------------------------------------------------------

FULL_ROAD_SECONDS = sum(s.seconds for s in SEGMENTS)
TOTAL_PLOTS = sum(s.plots for s in SPURS)

assert 290 <= FULL_ROAD_SECONDS <= 310, FULL_ROAD_SECONDS
assert len(SPURS) == 16
assert len(LOCATIONS) == 7
assert TOTAL_PLOTS == 640, TOTAL_PLOTS


def plots_used(world, spur_name: str) -> int:
    """Land taken on a spur by homes and extraction sites."""
    used = 0
    for prop in world.properties.values():
        if prop.location == spur_name:
            used += prop.plots
    for biz in world.businesses.values():
        if biz.location == spur_name and not biz.closed:
            used += biz.plots
    return used


def plots_free(world, place: str) -> int:
    """Plots left on a spur. Main-road places are not plot-limited."""
    if place not in SPUR_BY_NAME:
        return 10 ** 6
    return SPUR_BY_NAME[place].plots - plots_used(world, place)
