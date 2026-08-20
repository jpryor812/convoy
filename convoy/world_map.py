"""The world: one dangerous road, five places on it, ten spurs hanging off it.

THE DEMO MAP (2026-08-20). This is the seven-place valley with both protected
zones cut out. They were waystations where no blade may be drawn and no purse
cut -- and combat, theft and insurance are all unbuilt, so the safety they sold
was safety from nothing. Six spurs hung off them and went with them.

What is left is tighter in every direction: four road segments instead of six,
so Refinery Row and Town are two thirds as far apart, and land supply cut to
suit twenty agents rather than the couple of hundred businesses the full valley
could seat. `git checkout full-valley-map` is the world this was cut from,
complete and passing, with a rendered page at reference/full-valley-map.html.

Geography comes from the World tab (a single road from
Refinery Row to Town, ~5 minutes end to end at Medium speed, spur roads that
dead-end and loop back to the same junction). Everything below that -- terrain,
elevation, per-segment danger, spur placement -- is the 2026-08-12 world design.

THE SHAPE OF IT

    Refinery Row ── The Hills ── The Crossing ── The Climb ── Town

Production sits at the north end (every refinery in the world) and the market at
the south end (Town). Nothing hangs off either: all ten spurs, and so every mine
and farm, sit on the three middle junctions. Ore travels north to be smelted and
the goods travel south to be sold, in opposite directions across the same
dangerous middle -- which is the whole game.

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
        "Town", "hub", 30, True,
        # The tavern is at South Protected Zone, not here -- see GOVERNMENT_SITES.
        # This line used to claim it was in Town, and agents believed it: every
        # eat_best_available call in the 2026-08-14 harness runs failed with
        # "no tavern here" because the briefing sent them to the wrong place.
        "The market. Every store, the stables and the town square where the dead "
        "reappear. Protected ground -- deals are struck, not taken.",
    ),
]

LOCATIONS: list[str] = [loc.name for loc in LOCATIONS_SPEC]
LOCATION_BY_NAME: dict[str, Location] = {loc.name: loc for loc in LOCATIONS_SPEC}
PROTECTED_ZONES: set[str] = {loc.name for loc in LOCATIONS_SPEC if loc.protected}

# ---------------------------------------------------------------------------
# The four road segments between them
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
        "Refinery Row", "The Hills", "Slagside Road", "industrial flats to scrub",
        _BASE, 1.00, 0.30, 0.15, 0.20,
        "Straight and open where the refineries overlook it, thickening into scrub "
        "as they fall away behind. The mildest stretch on the road, which is not "
        "the same as safe.",
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
        "The Climb", "Town", "The Switchbacks", "mountain ascent to market",
        _BASE, 0.65, 0.55, 0.90, 0.50,
        "Carts crawl up the switchbacks while anyone above picks their moment, "
        "then drop into the market. The slowest ground on the road and the most "
        "thoroughly overlooked.",
    ),
]

SEGMENT_BY_PAIR: dict[tuple[str, str], RoadSegment] = {}
for _s in SEGMENTS:
    SEGMENT_BY_PAIR[(_s.a, _s.b)] = _s
    SEGMENT_BY_PAIR[(_s.b, _s.a)] = _s

# ---------------------------------------------------------------------------
# Ten spur roads
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
# SIZED FOR TWENTY AGENTS. The full valley sold 864 plots -- 216 businesses --
# against twenty agents who between them want perhaps forty sites and forty
# homes. Land that cannot run out is not a market, and it is why every location
# decision in the 84-hour run was made as though ground were free: it was.
#
# The demo sells 308, roughly twice what twenty agents need. That is deliberate
# headroom rather than a squeeze -- enough that nobody is walled out in the
# opening hours, tight enough that Town fills and somebody has to either pay a
# holder for their ground or build further out.
#
# EVERY NUMBER HERE DIVIDES BY FOUR, because a site is a 2x2 block of plots and
# `layout` lays the ground out in blocks. A supply that does not divide leaves an
# orphan strip nothing can be built on.
PLOTS_PER_SPUR = 20
HOME_BASE_PLOTS = 4

# Plot COUNTS live here, with the geography, and `data.py` re-exports them --
# `data` already imports this module, so defining them the other way round is a
# circular import. They were briefly defined in both, 8 here and 4 there, which
# is exactly the split that shows up as a founding check passing and the
# resulting business seating the wrong number of people.
#
# The building itself, worked by the owner.
STRUCTURE_PLOTS = 2
# A new production site: the building plus two places to put people.
SITE_BASE_PLOTS = 4
# A store: the same, but its land is shelf space rather than standing room.
STORE_BASE_PLOTS = 4
SITE_EXPANSION_PLOTS = 1        # land is bought one plot at a time now

# Only extraction sites live on spur land. Refineries, stores, the tavern and the
# brokerage sit on the main road and consume no plots.
PLOT_CONSUMING_BUSINESSES = ("Mining Operation", "Farm")

# THE VALLEY IS A GRADIENT, AND THE ENDS ARE PURE (2026-08-20)
#
# Refinery Row and Town used to carry three spurs each. That put mines, farms and
# homes AT both ends of the road as well as along it, and the two ends are the
# only places in the economy with a job: everything is refined at one and sold at
# the other. A mine on a Refinery Row spur was a mine that never had to haul, and
# a workshop on a Town spur was a seller that never had to travel -- the two
# shortcuts that let an agent opt out of the road entirely.
#
# So both ends are now clear of spurs. Refineries at the far north, the market at
# the far south, and all sixteen extraction and housing spurs strung between them
# across the five middle junctions. Every load of ore now travels to be smelted
# and every finished good travels to be sold, in opposite directions, which is
# the whole shape of the economy made geographic.
#
# Spurs were matched to the ground they sit on rather than shuffled: ore went to
# the hills and the mountain, clay and water to the river crossing, farming to
# the two protected zones. Where a description used to name a neighbour it no
# longer has -- "minutes from the smelters" -- it says the new truth instead.
SPURS: list[Spur] = [
    # North Protected Zone -- safe ground behind the garrison wall, and the
    # valley's best farmland now that it is not competing with the smelters.
    Spur("Blindfold Draw", "The Hills", SPUR_SECONDS, PLOTS_PER_SPUR,
         "A dead-end draw in the hills. Good stone, bad neighbours."),
    Spur("Rockfall Cut", "The Hills", SPUR_SECONDS, PLOTS_PER_SPUR,
         "A scar of loose scree and boulders. Rich in stone and clay, and impossible to watch."),
    Spur("Copper Gulch", "The Hills", SPUR_SECONDS, PLOTS_PER_SPUR,
         "Ore country, cut deep into the hills. The government mine works the head of the gulch, "
         "and every load of it has to run the hill road north to be smelted."),
    # The Crossing -- the river and its flats. Clay, water, and the kilns that
    # want both.
    Spur("Ferryman's Bend", "The Crossing", SPUR_SECONDS, PLOTS_PER_SPUR,
         "River flats above the bridge. Clay, water, and a view of everyone who crosses."),
    Spur("Millrace Farms", "The Crossing", SPUR_SECONDS, PLOTS_PER_SPUR,
         "Irrigated silt bottoms fed by the mill race off the river -- the water the name refers "
         "to is right here. The government farm holds the best of it, on open ground."),
    Spur("Potters Yard", "The Crossing", SPUR_SECONDS, PLOTS_PER_SPUR,
         "Clay pits and drying sheds on the riverbank, where the good clay is."),
    Spur("Kiln Row", "The Crossing", SPUR_SECONDS, PLOTS_PER_SPUR,
         "Workshops and firing yards above the ford, sited for the clay and the water rather "
         "than for the buyers, who are a long cart south."),
    # The Climb -- the mountain shoulder. Iron in the rock, and the spoil of it.
    Spur("Eagle's Rest", "The Climb", SPUR_SECONDS, PLOTS_PER_SPUR,
         "Cut into the mountainside. Hard ground, hard living, and it sees everything."),
    Spur("Scree Terrace", "The Climb", SPUR_SECONDS, PLOTS_PER_SPUR,
         "Stepped ledges hacked from the slope. Iron in the rock and a long way down."),
    Spur("Slagfoot Yards", "The Climb", SPUR_SECONDS, PLOTS_PER_SPUR,
         "Tailings and cinder flats under the mountain. Cheap ground, filthy air, ore underfoot, "
         "and the whole length of the valley between it and a smelter."),
    # South Protected Zone -- the desirable southern addresses, and the last
    # ground before the market.
]

# ---------------------------------------------------------------------------
# Land supply on the main road (2026-08-19)
# ---------------------------------------------------------------------------
#
# Junctions used to be exempt from land entirely -- `plots_free` returned 10**6
# for anything not on a spur, so every refinery, store and tavern in the world
# stood on ground that could never run out. Fifteen of the twenty-four
# businesses in the 84-hour run sat on that exemption.
#
# Junction land is deliberately much scarcer than spur land (40 per spur, 640 in
# total). Town is the market -- every store, and the shortest haul to a buyer --
# so its ground is the most contested thing in the valley and ought to be. The
# wilderness stops get little: nobody sensible builds in an ambush.
#
# Sized AFTER the state is seated, not before. The government occupies five
# sites at Town and one at Refinery Row, four plots each -- so a Town supply of
# 40 leaves 20, which is five shops for twenty agents, and the 84-hour run
# founded more than that at Town alone. These numbers leave roughly ten player
# businesses at Town before land starts binding, which is meant to be a
# mid-run squeeze rather than an opening-hour wall.
#
# This is the knob to turn after the next run, in either direction.
JUNCTION_PLOTS: dict[str, int] = {
    # Twelve blocks, of which the state already holds five -- both stores, the
    # weaponsmith, the stables and the brokerage. Seven for everybody else, which
    # makes this the tightest ground in the world, as it should be.
    "Town": 48,
    # Six blocks, one of them the state refinery.
    "Refinery Row": 24,
    # Three blocks each. Nobody sensible builds in an ambush, and the two that
    # host a government site have two left over.
    "The Hills": 12,
    "The Crossing": 12,
    "The Climb": 12,
}


def plots_at(place: str) -> int:
    """Total land at a place, spur or junction."""
    if place in SPUR_BY_NAME:
        return SPUR_BY_NAME[place].plots
    return JUNCTION_PLOTS.get(place, 0)


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
    "Home Improvement Store": "Town",
    "Mining/Farming Equipment Store": "Town",
    "Weaponsmith / Armory": "Town",
    "Vehicle Dealer / Stable": "Town",
    # The bridge inn. It was at South Protected Zone, which no longer exists, and
    # The Crossing is the right heir: the one chokepoint everyone on the road has
    # to pass through, which is where an innkeeper would in fact stand.
    "Tavern / Inn": "The Crossing",
    # Guards belong where the road is worst, not where it is safest -- and with
    # the garrison gone, the worst ground is The Hills.
    "Private Security Contractor": "The Hills",
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

# ~3.5 minutes end to end, where the full valley was ~5. Four segments instead
# of six is most of it, and it is the point: a demo wants the road crossed often
# enough that somebody can be watched crossing it.
assert 200 <= FULL_ROAD_SECONDS <= 220, FULL_ROAD_SECONDS
assert len(SPURS) == 10
assert len(LOCATIONS) == 5
assert TOTAL_PLOTS == 200, TOTAL_PLOTS
assert sum(JUNCTION_PLOTS.values()) + TOTAL_PLOTS == 308
# Every supply divides into whole 2x2 blocks; see PLOTS_PER_SPUR.
assert all(n % SITE_BASE_PLOTS == 0 for n in JUNCTION_PLOTS.values())
assert PLOTS_PER_SPUR % SITE_BASE_PLOTS == 0


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
    """UNSOLD land at a place -- ground the world still has to sell.

    Junctions used to return 10**6 here, so every refinery, store and tavern in
    the valley stood on ground that could not run out. Fifteen of the
    twenty-four businesses in the 84-hour run sat on that exemption, and it is
    why location cost nothing to choose.

    Counts only plots nobody owns. Land somebody bought and left vacant is NOT
    free -- it is theirs, and the whole point of a market is that you have to
    deal with them for it.
    """
    supply = plots_at(place)
    if not supply:
        return 0
    taken = sum(1 for p in world.plots.values() if p.location == place)
    return max(supply - taken, 0)
