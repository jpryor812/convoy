"""The world: one dangerous road, three places on it, four spurs off the middle.

THE DEMO MAP (2026-08-20), cut down from the seven-place valley twice.

First the protected zones went. They were waystations selling freedom from
combat, theft and insurance claims, none of which are built, so they were safe
from nothing -- and six spurs went with them.

Then everything but the middle went. What is left is the smallest world that
still contains the whole economy:

    Refinery Row  ──  The Hills  ──  Town
    (smelting)        (ore, grain,     (the market)
                       and everybody's
                       house)

SMALL ON PURPOSE, BECAUSE LAND IS SUPPOSED TO BIND. The full valley sold 864
plots to twenty agents and location cost nothing to choose; this sells 160, of
which the state already holds forty. Town has five free blocks for every shop
anybody wants to open, and the four spurs hold twenty sites between mines, farms
and the homes of twenty people. Somebody will have to buy a neighbour out, and
that is the point.

EVERY BUILDING TYPE EXISTS EXACTLY ONCE at hour zero, as a government branch.
The state is a backstop, not a participant: it proves each trade is possible and
sets a price to undercut. Everything else on the map is ground an agent bought.

`git checkout full-valley-map` is the world this was cut from -- seven places,
sixteen spurs, complete and passing, with a rendered page at
reference/full-valley-map.html.

Geography comes from the World tab (a single road from
Refinery Row to Town, ~5 minutes end to end at Medium speed, spur roads that
dead-end and loop back to the same junction). Everything below that -- terrain,
elevation, per-segment danger, spur placement -- is the 2026-08-12 world design.

THE SHAPE OF IT

    Refinery Row ── The Hills ── Town

Production sits at the north end and the market at the south, and NOTHING hangs
off either: all four spurs are on The Hills, so every mine, farm and house in the
world is in the middle. Ore travels north to be smelted, goods travel south to be
sold, and the southern leg is a bridge -- one chokepoint that every load reaching
a buyer has to cross. That is the whole game.

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


# ---------------------------------------------------------------------------
# TWO VALLEYS, GENERATED FROM ONE TEMPLATE (2026-09-03)
# ---------------------------------------------------------------------------
#
# The world used to be one valley. It is now a CONTEST between cities, and a
# contest between two economies is only readable if the two are structurally
# identical -- otherwise every difference in the result is arguable as a
# difference in the ground.
#
# So the valleys are not written twice. Everything structural -- elevations,
# segment lengths, terrain modifiers, concealment/vantage/exposure, plot
# supplies, which business type the state seats where -- is defined ONCE per
# ROLE below, and each city is that same template under its own names. A change
# to the shape of the world lands on both cities or on neither, by construction.
# `assert_cities_are_mirrors()` at the bottom of this file checks it every
# import, because "identical by construction" is a claim that rots the first
# time somebody special-cases one side.
#
# WHAT DIFFERS IS ONLY THE NAMES. Aldermarch keeps the demo map's names exactly
# -- Refinery Row, The Hills, Town, and the four spurs -- because they are what
# every existing run, checkpoint and test refers to. Cinderhold is the mirror.
#
# THE VALLEYS DO NOT TOUCH. There is no road between them: `road_path` refuses a
# cross-city journey and `travel_path` raises. That is deliberate (2026-09-03
# designer decision) -- the question being asked is how two populations under
# identical conditions diverge, and a trade route between them would make each
# city's result partly a function of the other's play. The cities meet in
# exactly one place: the scoreboard.

# THE THREE ROLES ON THE MAIN ROAD, north to south. A city is these three in
# this order, so `road_path` can index within one city's list the way it always
# indexed within the only one.
ROLE_REFINERY = "refinery"
ROLE_HILLS = "hills"
ROLE_MARKET = "market"
ROLE_SPUR = "spur"

MAIN_ROAD_ROLES: tuple[str, str, str] = (ROLE_REFINERY, ROLE_HILLS, ROLE_MARKET)

# What each main-road role IS, independent of what any city calls it. Shared by
# every city: this is the fairness guarantee.
_ROLE_SPEC: dict[str, dict] = {
    ROLE_REFINERY: {
        "kind": "hub", "elevation": 40, "protected": False,
        "blurb": (
            "Smoke and slag at the valley's north end. Every refinery in {city} is "
            "here, and so is everything worth stealing before it has been sold."
        ),
    },
    ROLE_HILLS: {
        "kind": "wilderness", "elevation": 180, "protected": False,
        "blurb": (
            "Rolling broken country of boulders and blind bends. Nowhere on the road "
            "offers an ambusher better cover to set up unseen."
        ),
    },
    ROLE_MARKET: {
        "kind": "hub", "elevation": 30, "protected": True,
        # The tavern IS here now (2026-08-20). This line has been wrong in both
        # directions: it once claimed a tavern the market did not have, and every
        # eat_best_available call in the 2026-08-14 runs failed with "no tavern
        # here" because the briefing sent agents to the wrong place. Read
        # `government_sites_for` rather than trusting either version of this
        # sentence.
        "blurb": (
            "The market of {city}. Every store, the tavern, the stables and the town "
            "square where the dead reappear. Protected ground -- deals are struck, "
            "not taken."
        ),
    },
}

# ---------------------------------------------------------------------------
# The two road segments between them
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

# The two legs of every valley, by the roles they join. Shared by both cities.
_SEGMENT_SPEC: list[dict] = [
    {
        "from": ROLE_REFINERY, "to": ROLE_HILLS,
        "terrain": "industrial flats to scrub",
        "base_seconds": _BASE, "speed_modifier": 1.00,
        "concealment": 0.30, "vantage": 0.15, "exposure": 0.20,
        "blurb": (
            "Straight and open where the refineries overlook it, thickening into scrub "
            "as they fall away behind. The mildest stretch on the road, which is not "
            "the same as safe."
        ),
    },
    {
        # THE ONLY WAY TO A BUYER. Both deleted junctions took a segment with
        # them, and of the two that remain this is the one every finished good
        # must cross, so it inherits the bridge: a chokepoint with water on both
        # sides, priced accordingly and impossible to run from.
        "from": ROLE_HILLS, "to": ROLE_MARKET,
        "terrain": "river crossing to market",
        "base_seconds": _BASE, "speed_modifier": 0.85,
        "concealment": 0.45, "vantage": 0.35, "exposure": 0.90,
        "blurb": (
            "One crossing between the hills and the market, water on both sides. "
            "Everything anyone has ever sold in {city} crossed it, and there is "
            "no off-road to flee onto."
        ),
    },
]

# ---------------------------------------------------------------------------
# Four spur roads, all on the hills
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
# SIZED TO BIND, NOT TO SUFFICE. The full valley sold 864 plots and location cost
# nothing to choose; the first cut sold 308, which was still roughly twice what
# twenty agents need and so still not a market. Each city sells 160.
#
# THE SUPPLY IS PER CITY, AND SO IS THE POPULATION. Twenty agents to a city and
# 160 plots to a city means the land is exactly as tight in a two-city world as
# it was in the one-city world these numbers were tuned for. That is the point
# of mirroring rather than sharing: if both cities drew on one pool of ground,
# the contest would be settled by who grabbed first rather than by who built
# better, and every number in PHASE7 and PHASE8 would need retuning.
#
# SPUR LAND IS THE TIGHT ONE and it is tight on purpose. Mines, farms AND homes
# are all spur-only (see PLOT_CONSUMING_BUSINESSES and `buy_property`), so four
# spurs at twenty plots hold twenty sites in total -- and the state mine and farm
# take two of them. Eighteen sites, twenty agents, each of whom would like a
# house AND somewhere to dig. Most of them cannot have both, which means buying a
# neighbour out or doing without, which is what a land market is.
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
# The refinery end and the market end used to carry three spurs each. That put
# mines, farms and homes AT both ends of the road as well as along it, and the
# two ends are the only places in the economy with a job: everything is refined
# at one and sold at the other. A mine on a refinery spur was a mine that never
# had to haul, and a workshop on a market spur was a seller that never had to
# travel -- the two shortcuts that let an agent opt out of the road entirely.
#
# So both ends are clear of spurs. Refineries at the far north, the market at
# the far south, and every extraction and housing spur strung between them on
# the hills. Every load of ore now travels to be smelted and every finished good
# travels to be sold, in opposite directions, which is the whole shape of the
# economy made geographic.
_SPUR_BLURBS: tuple[str, ...] = (
    "A dead-end draw in the hills. Good stone, bad neighbours.",
    "A scar of loose scree and boulders. Rich in stone and clay, and impossible to watch.",
    "Ore country, cut deep into the hills. The government mine works the head of it, "
    "and every load has to run the hill road north to be smelted.",
    "Irrigated silt bottoms fed by a mill race off the river. The government farm "
    "holds the best of it, on open ground.",
)

# ---------------------------------------------------------------------------
# Land supply on the main road (2026-08-19)
# ---------------------------------------------------------------------------
#
# Junctions used to be exempt from land entirely -- `plots_free` returned 10**6
# for anything not on a spur, so every refinery, store and tavern in the world
# stood on ground that could never run out. Fifteen of the twenty-four
# businesses in the 84-hour run sat on that exemption.
#
# Junction land is deliberately much scarcer than spur land. The market is where
# every store and the shortest haul to a buyer are, so its ground is the most
# contested thing in a city and ought to be.
#
# Sized AFTER the state is seated, not before. The government occupies five
# sites at the market and one at the refineries, four plots each -- so a market
# supply of 40 leaves 20, which is five shops for twenty agents, and the 84-hour
# run founded more than that at Town alone. These numbers leave roughly ten
# player businesses at the market before land starts binding, which is meant to
# be a mid-run squeeze rather than an opening-hour wall.
#
# This is the knob to turn after the next run, in either direction.
_JUNCTION_PLOTS_BY_ROLE: dict[str, int] = {
    # Ten blocks, of which the state holds five -- both stores, the weaponsmith,
    # the stables and the tavern. FIVE FREE BLOCKS, for every shop that twenty
    # agents might want to open next to the only buyers in their city. This is
    # the most contested ground on the map and the number to turn if it proves
    # too cruel.
    ROLE_MARKET: 40,
    # Six blocks, one of them the state refinery. Refining is where the value is
    # added, so there should be room for rivals -- but not much.
    ROLE_REFINERY: 24,
    # Four blocks, two already the state's tavern and security contractor. The
    # main-road frontage of a wilderness stop: nobody sensible builds in an
    # ambush, and there is barely anywhere to.
    ROLE_HILLS: 16,
}

# Where the government's own operations sit, by role. Mine and farm go on spurs,
# per the world design -- the state's supply chain is short, and everyone else
# has to beat it on price or distance.
#
# NO INSURANCE BROKERAGE (designer decision, 2026-08-20). Cut with the whole
# insurance line: a profitable underwriter must charge above expected loss and a
# net-worth-maximising agent declines above expected loss, so there is no price
# at which both sides trade. See PHASE7 §11.
_GOVERNMENT_SITES_BY_ROLE: dict[str, tuple[str, int]] = {
    "Refinery": (ROLE_REFINERY, -1),
    "Mining Operation": (ROLE_SPUR, 2),        # the ore gulch
    "Farm": (ROLE_SPUR, 3),                    # the irrigated bottoms
    "Home Improvement Store": (ROLE_MARKET, -1),
    "Mining/Farming Equipment Store": (ROLE_MARKET, -1),
    "Weaponsmith / Armory": (ROLE_MARKET, -1),
    "Vehicle Dealer / Stable": (ROLE_MARKET, -1),
    # The road house, in the market where an inn belongs -- beside the stalls, in
    # the one place everybody already comes to sell.
    "Tavern / Inn": (ROLE_MARKET, -1),
    # Guards belong where the road is worst, not where it is safest -- and with
    # the garrison gone, the worst ground is the hills.
    "Private Security Contractor": (ROLE_HILLS, -1),
}

# ---------------------------------------------------------------------------
# The cities themselves -- names only
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class City:
    """One valley, and the people who call it home.

    A city is a NAME over the shared template above. It owns three main-road
    stops in north-to-south order, four spurs off its middle stop, two road
    segments and one full set of government branches -- exactly what the
    one-city world had, because it IS the one-city world under a name.

    `key` is the stable identifier that goes in checkpoints, events and agent
    records; `name` is what an agent reads. They differ so that renaming a city
    for flavour never invalidates a saved world.
    """

    key: str
    name: str
    locations: tuple[str, str, str]      # north -> south: refinery, hills, market
    spurs: tuple[str, str, str, str]
    segments: tuple[str, str]
    blurb: str

    @property
    def refinery_row(self) -> str:
        return self.locations[0]

    @property
    def hills(self) -> str:
        return self.locations[1]

    @property
    def market(self) -> str:
        """Where agents spawn, where the dead reappear, where the job board is."""
        return self.locations[2]

    @property
    def places(self) -> list[str]:
        return list(self.locations) + list(self.spurs)


# ALDERMARCH IS THE DEMO MAP, NAME FOR NAME. Every existing run, checkpoint,
# test and rendered page refers to "Town", "The Hills", "Refinery Row" and the
# four spurs by those names; renaming them to make the mirror prettier would
# make every saved world unreadable and every geography test a rewrite, for
# nothing. Cinderhold is the new one, so it gets the new words.
_CITY_NAMES: list[dict] = [
    {
        "key": "aldermarch",
        "name": "Aldermarch",
        "locations": ("Refinery Row", "The Hills", "Town"),
        "spurs": ("Blindfold Draw", "Rockfall Cut", "Copper Gulch", "Millrace Farms"),
        "segments": ("Slagside Road", "The Bridge"),
        "blurb": "The older city. Smelters at the head of the valley, the market "
                 "at its foot, and a bridge between them that everything crosses.",
    },
    {
        "key": "cinderhold",
        "name": "Cinderhold",
        "locations": ("Cinder Row", "The Ashfells", "Cindergate"),
        "spurs": ("Gallows Draw", "Slate Cut", "Iron Gulch", "Windmill Fields"),
        "segments": ("Ashside Road", "The Causeway"),
        "blurb": "The rival city, a valley west of Aldermarch and its equal in "
                 "every measurable way. Same ore, same ground, same road, same "
                 "twenty pairs of hands.",
    },
]

CITIES: dict[str, City] = {
    spec["key"]: City(**spec) for spec in _CITY_NAMES
}
CITY_KEYS: list[str] = [c["key"] for c in _CITY_NAMES]

# The city a one-city world is. Everything module-level below that is NOT
# prefixed `EVERY_` describes this valley alone, which is why nothing outside
# this file had to change when the second one appeared.
HOME_CITY: str = CITY_KEYS[0]
HOME: City = CITIES[HOME_CITY]

# ---------------------------------------------------------------------------
# Generating each valley from the template
# ---------------------------------------------------------------------------

EVERY_LOCATION_SPEC: list[Location] = []
EVERY_SEGMENT: list[RoadSegment] = []
EVERY_SPUR: list[Spur] = []
EVERY_JUNCTION_PLOTS: dict[str, int] = {}
# place name -> city key, and place name -> role. Both are global lookups: a
# place belongs to exactly one city and has exactly one role, and every caller
# that has a place name but no city needs to be able to ask.
CITY_OF: dict[str, str] = {}
ROLE_OF: dict[str, str] = {}
# city key -> {business type: place}. The state seats one branch of every type
# in EVERY city, so each side starts with the same backstop.
GOVERNMENT_SITES_BY_CITY: dict[str, dict[str, str]] = {}
# city key -> its own ordered main-road list, for `road_path`.
_LOCATIONS_BY_CITY: dict[str, list[str]] = {}
_SPURS_BY_CITY: dict[str, list[Spur]] = {}
_SEGMENTS_BY_CITY: dict[str, list[RoadSegment]] = {}


def _build_valley(city: City) -> None:
    """One city's geography, from the shared spec and the city's own names."""
    for role, name in zip(MAIN_ROAD_ROLES, city.locations):
        spec = _ROLE_SPEC[role]
        EVERY_LOCATION_SPEC.append(Location(
            name, spec["kind"], spec["elevation"], spec["protected"],
            spec["blurb"].format(city=city.name),
        ))
        CITY_OF[name] = city.key
        ROLE_OF[name] = role
        EVERY_JUNCTION_PLOTS[name] = _JUNCTION_PLOTS_BY_ROLE[role]
    _LOCATIONS_BY_CITY[city.key] = list(city.locations)

    by_role = dict(zip(MAIN_ROAD_ROLES, city.locations))
    segs = [
        RoadSegment(
            by_role[spec["from"]], by_role[spec["to"]], seg_name, spec["terrain"],
            spec["base_seconds"], spec["speed_modifier"],
            spec["concealment"], spec["vantage"], spec["exposure"],
            spec["blurb"].format(city=city.name),
        )
        for spec, seg_name in zip(_SEGMENT_SPEC, city.segments)
    ]
    EVERY_SEGMENT.extend(segs)
    _SEGMENTS_BY_CITY[city.key] = segs

    spurs = [
        Spur(name, city.hills, SPUR_SECONDS, PLOTS_PER_SPUR, blurb)
        for name, blurb in zip(city.spurs, _SPUR_BLURBS)
    ]
    EVERY_SPUR.extend(spurs)
    _SPURS_BY_CITY[city.key] = spurs
    for spur in spurs:
        CITY_OF[spur.name] = city.key
        ROLE_OF[spur.name] = ROLE_SPUR

    sites: dict[str, str] = {}
    for btype, (role, index) in _GOVERNMENT_SITES_BY_ROLE.items():
        sites[btype] = city.spurs[index] if role == ROLE_SPUR else by_role[role]
    GOVERNMENT_SITES_BY_CITY[city.key] = sites


for _city in CITIES.values():
    _build_valley(_city)

EVERY_LOCATION: list[str] = [loc.name for loc in EVERY_LOCATION_SPEC]
EVERY_PLACE: list[str] = [p for c in CITIES.values() for p in c.places]

# GLOBAL LOOKUPS COVER EVERY CITY, because a place name is unique across the
# world and every caller holding one -- an agent's location, a plot's location,
# a consignment's destination -- needs an answer without also holding a city.
LOCATION_BY_NAME: dict[str, Location] = {l.name: l for l in EVERY_LOCATION_SPEC}
SPUR_BY_NAME: dict[str, Spur] = {s.name: s for s in EVERY_SPUR}
SEGMENT_BY_PAIR: dict[tuple[str, str], RoadSegment] = {}
for _s in EVERY_SEGMENT:
    SEGMENT_BY_PAIR[(_s.a, _s.b)] = _s
    SEGMENT_BY_PAIR[(_s.b, _s.a)] = _s
SPURS_BY_JUNCTION: dict[str, list[Spur]] = {}
for _sp in EVERY_SPUR:
    SPURS_BY_JUNCTION.setdefault(_sp.junction, []).append(_sp)

# ---------------------------------------------------------------------------
# The home valley, under the names the rest of the codebase already uses
# ---------------------------------------------------------------------------
#
# These are Aldermarch's, not the world's. Everything written before there were
# two cities reads these and keeps meaning what it meant: three locations, two
# segments, four spurs, 160 plots, one government branch of every type. Code
# that must see the whole world asks for `EVERY_*` or for a city by key.
LOCATIONS_SPEC: list[Location] = [LOCATION_BY_NAME[n] for n in HOME.locations]
LOCATIONS: list[str] = list(HOME.locations)
PROTECTED_ZONES: set[str] = {
    l.name for l in EVERY_LOCATION_SPEC if l.protected
}
SEGMENTS: list[RoadSegment] = _SEGMENTS_BY_CITY[HOME_CITY]
SPURS: list[Spur] = _SPURS_BY_CITY[HOME_CITY]
JUNCTION_PLOTS: dict[str, int] = {n: EVERY_JUNCTION_PLOTS[n] for n in HOME.locations}
GOVERNMENT_SITES: dict[str, str] = GOVERNMENT_SITES_BY_CITY[HOME_CITY]
ALL_PLACES: list[str] = HOME.places


def plots_at(place: str) -> int:
    """Total land at a place, spur or junction."""
    if place in SPUR_BY_NAME:
        return SPUR_BY_NAME[place].plots
    return EVERY_JUNCTION_PLOTS.get(place, 0)


# ---------------------------------------------------------------------------
# Asking a place which city it is in
# ---------------------------------------------------------------------------

def city_of(place: str) -> str:
    """The city key a place belongs to. Falls back to home for unknown ground.

    Unknown names reach here from replayed runs recorded on an older map, and
    the renderer already warns about those -- raising here would turn a warning
    into a crash on somebody else's saved world.
    """
    return CITY_OF.get(place, HOME_CITY)


def city_named(key_or_name: str) -> City:
    """A city by key or by display name, however the caller happens to hold it."""
    if key_or_name in CITIES:
        return CITIES[key_or_name]
    for city in CITIES.values():
        if city.name.lower() == key_or_name.lower():
            return city
    raise KeyError(key_or_name)


def same_city(a: str, b: str) -> bool:
    return city_of(a) == city_of(b)


def places_in(city: str) -> list[str]:
    return CITIES[city].places


def locations_in(city: str) -> list[str]:
    return list(CITIES[city].locations)


def spurs_in(city: str) -> list[Spur]:
    return list(_SPURS_BY_CITY[city])


def segments_in(city: str) -> list[RoadSegment]:
    return list(_SEGMENTS_BY_CITY[city])


def government_sites_for(city: str) -> dict[str, str]:
    return dict(GOVERNMENT_SITES_BY_CITY[city])


def market_of(city: str) -> str:
    """The city's market square: spawn point, job board, and where the dead return."""
    return CITIES[city].market


def rival_of(city: str, among: list[str] | None = None) -> str | None:
    """The other city, when there is exactly one. None in a one-city world.

    `among` is the cities a given WORLD actually contains, which is not always
    every city this module can describe -- a one-city run still imports both.
    """
    others = [c for c in (among if among is not None else CITY_KEYS) if c != city]
    return others[0] if len(others) == 1 else (others[0] if others else None)


# ---------------------------------------------------------------------------
# Travel
# ---------------------------------------------------------------------------

class NoRoadThere(ValueError):
    """Raised for a journey between two cities. There is no road between them.

    A distinct type rather than a bare ValueError because `travel_to` has to
    tell the difference between "that place does not exist" and "that place
    exists and you cannot walk to it", and those are different things to say to
    an agent. Saying the second one badly is how PHASE4 §2 entries happen.
    """


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
    """Segments crossed travelling the main road from `a` to `b`.

    Both ends must be in the same city. The valleys do not touch: there is no
    road from one to the other, and a caller that got here with one end in each
    has a bug rather than a long journey.
    """
    if a == b:
        return []
    city = city_of(a)
    if city_of(b) != city:
        raise NoRoadThere(
            f"{a} is in {CITIES[city].name} and {b} is in "
            f"{CITIES[city_of(b)].name}. No road joins the two valleys."
        )
    road = _LOCATIONS_BY_CITY[city]
    i, j = road.index(a), road.index(b)
    step = 1 if j > i else -1
    return [
        SEGMENT_BY_PAIR[(road[k], road[k + step])]
        for k in range(i, j, step)
    ]


def travel_path(origin: str, destination: str) -> tuple[float, list[RoadSegment]]:
    """Seconds at Medium speed, plus the road segments actually crossed.

    A spur dead-ends, so any journey from one spur to another climbs back to its
    junction, runs the road, then goes back down. Spur time never counts as road
    time -- convoys never use spurs, only solo trips do.

    Raises `NoRoadThere` for a cross-city journey.
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
    """The worst stretch on a route, or None if there is no route at all.

    Returns None rather than raising for a cross-city pair: every caller here is
    asking "how bad is this trip" for display, and the honest answer for a trip
    that cannot be made is nothing, not an exception thrown through a prompt.
    """
    try:
        _s, segments = travel_path(origin, destination)
    except NoRoadThere:
        return None
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

# ~1.6 minutes end to end against the full valley's ~5. Two segments, and the
# spur detours (90s each way) now cost more than the road itself -- which is
# correct for a world where everything is close and the decisions are about
# WHERE to stand rather than how long it takes to get there.
assert 95 <= FULL_ROAD_SECONDS <= 115, FULL_ROAD_SECONDS
assert len(SPURS) == 4
assert len(LOCATIONS) == 3
assert TOTAL_PLOTS == 80, TOTAL_PLOTS
assert sum(JUNCTION_PLOTS.values()) + TOTAL_PLOTS == 160

# Every business type exists exactly once per city at hour zero, as a
# government branch.
assert all(p in ALL_PLACES for p in GOVERNMENT_SITES.values()), GOVERNMENT_SITES
# Every supply divides into whole 2x2 blocks; see PLOTS_PER_SPUR.
assert all(n % SITE_BASE_PLOTS == 0 for n in JUNCTION_PLOTS.values())
assert PLOTS_PER_SPUR % SITE_BASE_PLOTS == 0


def assert_cities_are_mirrors() -> None:
    """Every city is the same valley under different names.

    THIS IS THE FAIRNESS GUARANTEE, AND IT IS CHECKED RATHER THAN ASSERTED IN
    PROSE. The whole experiment -- two populations, identical conditions, which
    one gets richer -- is only readable if the two grounds are the same ground.
    Generation from one template makes that true today; this makes it stay true
    the first time somebody adds a spur to one side to see what happens.

    Compares the STRUCTURE and ignores the names: elevations, protection,
    segment timings and danger triples, plot supplies, and which role the state
    seats each branch on.
    """
    def shape(city: City) -> tuple:
        return (
            tuple((ROLE_OF[n], LOCATION_BY_NAME[n].kind,
                   LOCATION_BY_NAME[n].elevation, LOCATION_BY_NAME[n].protected,
                   EVERY_JUNCTION_PLOTS[n]) for n in city.locations),
            tuple((ROLE_OF[s.a], ROLE_OF[s.b], s.base_seconds, s.speed_modifier,
                   s.concealment, s.vantage, s.exposure)
                  for s in _SEGMENTS_BY_CITY[city.key]),
            tuple((s.seconds_deep, s.plots) for s in _SPURS_BY_CITY[city.key]),
            tuple(sorted(
                (btype, ROLE_OF[place])
                for btype, place in GOVERNMENT_SITES_BY_CITY[city.key].items()
            )),
        )

    shapes = {c.key: shape(c) for c in CITIES.values()}
    first = shapes[CITY_KEYS[0]]
    for key, s in shapes.items():
        if s != first:
            raise AssertionError(
                f"{CITIES[key].name} is not a mirror of "
                f"{CITIES[CITY_KEYS[0]].name}; the contest would not be fair."
            )
    # And no place name may appear in two cities, or `city_of` is a coin toss.
    seen: dict[str, str] = {}
    for city in CITIES.values():
        for place in city.places:
            if place in seen:
                raise AssertionError(
                    f"{place} is in both {seen[place]} and {city.name}"
                )
            seen[place] = city.name


assert_cities_are_mirrors()


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
