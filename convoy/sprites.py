"""What every thing in the world LOOKS like.

One place binds game entities to art, so nothing has to guess. `data.py` is the
source of truth for what exists; this is the source of truth for how it is
drawn, and `check()` asserts that the two agree -- a good added to `data.py`
with no icon is a bug here, not a blank square discovered in a screenshot.

Two art sources:

  * `kenney_medieval-rts/` -- CC0, 259 top-down PNGs. Terrain, buildings, people.
  * `art/generated/` -- SVG drawn by `art/make_art.py` for what the pack lacks:
    all six vehicles, an icon per tradeable good, and ten action glyphs.

THE UNIT GRID. The pack's 24 people are not 24 characters, they are 4 faction
colours x 6 poses, and the colours do not start where the filenames do -- blue
begins at 23 and wraps. Determined by counting pixels, not by eye:

    blue #1ea7e1 -> 23  red #e27952 -> 5  green #1b914d -> 11  grey #acb8b8 -> 17

so `unit(faction, pose)` indexes the cycle instead of hard-coding 24 paths.
Agents get a faction colour from their MODEL, which makes a screenshot of a
mixed-model run readable at a glance, and a pose from what they currently ARE:
an owner is crowned, a hauler is cloaked, a smith is armoured.
"""

from __future__ import annotations

from pathlib import Path

from . import data as D
from . import world_map as M

ROOT = Path(__file__).resolve().parent.parent
KENNEY = ROOT / "kenney_medieval-rts" / "PNG" / "Retina"
GENERATED = ROOT / "art" / "generated"


def _slug(name: str) -> str:
    out = "".join(c.lower() if c.isalnum() else "-" for c in name)
    while "--" in out:
        out = out.replace("--", "-")
    return out.strip("-")


# ---------------------------------------------------------------------------
# PEOPLE
# ---------------------------------------------------------------------------

FACTION_BASE = {"blue": 23, "red": 5, "green": 11, "grey": 17}
POSES = ("owner", "hooded", "villager", "cloaked", "armed", "guard")


def unit(faction: str = "blue", pose: str = "villager") -> Path:
    base = FACTION_BASE.get(faction, FACTION_BASE["blue"])
    idx = ((base - 1 + POSES.index(pose)) % 24) + 1
    return KENNEY / "Unit" / f"medievalUnit_{idx:02d}.png"


# Model -> faction colour, so a 5-model run is legible without a legend.
FACTION_FOR_MODEL = {
    "openai/gpt-5.6-terra": "blue",
    "openai/gpt-5.6-luna": "green",
    "deepseek/deepseek-v4-flash-0731": "red",
    "x-ai/grok-4.3": "grey",
    "inclusionai/ling-3.0-flash": "blue",
}

# Role -> pose. Ordered: the FIRST match wins, so an owner reads as an owner even
# while working a shift somewhere else.
POSE_FOR_ROLE = {
    "Blacksmith": "armed",
    "Miner": "villager",
    "Farmhand": "villager",
    "Refinery Worker": "villager",
    "Store Clerk": "hooded",
    "Stablehand": "cloaked",
    "Laborer": "villager",
    "Researcher": "hooded",
}


RENDERED_CHARACTERS = GENERATED / "characters"

# Model -> rendered character variant. FIVE variants for five models, where the
# Kenney binding had to fold five models into four faction colours and always
# left two looking identical on the map. Kept explicit rather than derived from
# roster order, so re-ordering `MODEL_ROSTER` cannot silently repaint everyone;
# `check()` asserts every model has one.
CHARACTER_FOR_MODEL = {
    "openai/gpt-5.6-terra": 1,
    "deepseek/deepseek-v4-flash-0731": 2,
    "openai/gpt-5.6-luna": 3,
    "x-ai/grok-4.3": 4,
    "inclusionai/ling-3.0-flash": 5,
}


def agent_sprite(model: str, *, owns_business: bool = False,
                 hauling: bool = False, role: str | None = None,
                 dead: bool = False) -> Path:
    """The sprite for one agent, right now.

    Prefers a rendered character, falls back to the Kenney unit grid.

    ONE DISTINCTION IS LOST in the rendered set and it is worth naming: Kenney's
    24 sprites gave six poses, so a hauler could read as cloaked and a smith as
    armoured. The rendered characters have two states, plain and owner. Owner is
    kept because owning a business is a real economic fact worth seeing on a map;
    role and hauling are not, and belong in the status bubble (VISUALS section 1)
    where they can say what the agent is actually doing rather than what it is.
    """
    if dead:
        return GENERATED / "ui" / "death.svg"

    variant = CHARACTER_FOR_MODEL.get(model)
    if variant is not None:
        name = f"agent-{variant}" + ("-owner" if owns_business else "")
        rendered = RENDERED_CHARACTERS / f"{name}.png"
        if rendered.exists():
            return rendered

    faction = FACTION_FOR_MODEL.get(model, "blue")
    if owns_business:
        pose = "owner"
    elif hauling:
        pose = "cloaked"
    else:
        pose = POSE_FOR_ROLE.get(role or "", "villager")
    return unit(faction, pose)


# ---------------------------------------------------------------------------
# BUILDINGS
# ---------------------------------------------------------------------------
# Identified by rendering the pack at 5x and looking at it. The three the brief
# called missing are all here in substance: Structure_20 carries a stone chimney
# (Refinery), Structure_19 is a forge with a glowing furnace mouth
# (Weaponsmith), Structure_07 is a stall hung with loaves (Tavern).

def _structure(n: int) -> Path:
    return KENNEY / "Structure" / f"medievalStructure_{n:02d}.png"


STRUCTURE_FOR_BUSINESS = {
    "Mining Operation": _structure(8),            # a ramp cut into the ground
    "Farm": _structure(14),                       # windmill
    "Refinery": _structure(20),                   # house with a stone chimney
    "Weaponsmith / Armory": _structure(19),       # forge, furnace mouth glowing
    "Tavern / Inn": _structure(7),                # stall hung with loaves
    "Vehicle Dealer / Stable": _structure(16),    # open-fronted barn
    "Home Improvement Store": _structure(21),     # house with a timber lean-to
    "Mining/Farming Equipment Store": _structure(22),   # awninged market stall
    "Private Security Contractor": _structure(5),       # stone post, banner
    "Insurance Brokerage": _structure(4),               # civic hall
}

# Government branches use the same building with a stone-grey civic marker in
# the renderer, rather than a second sprite set: same trade, different owner.
GOVERNMENT_BADGE = _structure(6)                  # the town gatehouse

# Blender-rendered replacements, drawn by `art/blender_assets.py` through the
# rig in `art/blender_rig.py`.
RENDERED_BUILDINGS = GENERATED / "buildings"


def structure_for(business_type: str) -> Path:
    """The best available sprite for a business type.

    A rendered PNG wins over the Kenney stand-in, and the Kenney one is used
    until a rendered one exists. That is what lets the art be replaced ONE
    BUILDING AT A TIME without a flag day: render a refinery, and every refinery
    on the map is a refinery next time the page is built, while the other nine
    types carry on unchanged.
    """
    rendered = RENDERED_BUILDINGS / f"{_slug(business_type)}.png"
    if rendered.exists():
        return rendered
    return STRUCTURE_FOR_BUSINESS[business_type]


def is_rendered(business_type: str) -> bool:
    return (RENDERED_BUILDINGS / f"{_slug(business_type)}.png").exists()


# ---------------------------------------------------------------------------
# TERRAIN
# ---------------------------------------------------------------------------

def _tile(n: int) -> Path:
    return KENNEY / "Tile" / f"medievalTile_{n:02d}.png"


def _env(n: int) -> Path:
    return KENNEY / "Environment" / f"medievalEnvironment_{n:02d}.png"


# One road runs north to south, so every location sits on a road tile; what
# differs is the ground it is cut through and what grows on it.
GROUND_FOR_KIND = {
    "hub": _tile(57),           # plain grass, built over
    "waystation": _tile(58),    # grass
    "wilderness": _tile(47),    # grass with trees
}

ROAD_STRAIGHT = _tile(8)        # a north-south length of road, transparent bg
ROAD_JUNCTION = _tile(10)       # a crossroads

# Decor per location, keyed by name because elevation alone does not say whether
# a place is a quarry or a river crossing.
DECOR_FOR_LOCATION = {
    "Refinery Row": [_env(9), _env(12)],       # spoil heaps and ore-flecked rock
    "North Protected Zone": [_env(2), _env(4)],
    "The Hills": [_env(18), _env(19)],         # copper-bearing rock
    "The Crossing": [_env(6), _env(8)],        # a fallen log, a boulder
    "The Climb": [_env(10), _env(11)],         # grey rock with metal flecks
    "South Protected Zone": [_env(1), _env(3)],
    "Town": [_env(13), _env(20)],              # kept shrubs
}

# Elevation drives the ground tint in the renderer: the valley runs 20m at The
# Crossing to 340m at The Climb, and that gradient is the whole reason haulage
# costs what it does.
ELEVATION_RANGE = (20, 340)


# ---------------------------------------------------------------------------
# VEHICLES AND GOODS
# ---------------------------------------------------------------------------

def vehicle_sprite(name: str) -> Path:
    """Rendered vehicle if there is one, else the hand-drawn SVG.

    The rendered set lives in `vehicles-3d/` rather than overwriting
    `vehicles/`, so the SVGs stay as a working fallback and the two can be
    compared side by side instead of one being destroyed to try the other.
    """
    rendered = GENERATED / "vehicles-3d" / f"{_slug(name)}.png"
    if rendered.exists():
        return rendered
    return GENERATED / "vehicles" / f"{_slug(name)}.svg"


def item_icon(name: str) -> Path:
    return GENERATED / "items" / f"{_slug(name)}.svg"


def ui_glyph(name: str) -> Path:
    return GENERATED / "ui" / f"{name}.svg"


# ---------------------------------------------------------------------------
# ACTIONS AND EVENTS
# ---------------------------------------------------------------------------
# 53 actions, ten families. A timeline needs "that was a trade, that was a hire"
# at a glance; 53 bespoke glyphs would be noise and most would be
# indistinguishable at 16px anyway.

ACTION_FAMILY = {
    "coin": (
        "buy_from_business", "sell_to_business", "order_from_business", "buy_meal",
        "buy_vehicle", "buy_property", "buy_insurance", "deposit", "withdraw",
        "set_retail_price", "offer_trade", "accept_trade", "decline_trade",
        "collect_business_inventory", "stock_business_inventory", "store_at_home",
    ),
    "travel": (
        "travel_to", "mount", "dismount", "accept_courier_job",
        "deliver_consignment", "collect_consignment", "cancel_consignment",
    ),
    "work": (
        "start_shift", "end_shift", "set_production", "equip_tools",
        "allocate_research", "collect_from_safehouse", "stash_in_safehouse",
        "loot_ground",
    ),
    "hire": (
        "apply_for_job", "apply_to_job", "post_job", "close_job", "hire_applicant",
        "hire_npc_employee", "quit_job", "set_wage",
    ),
    "build": (
        "start_business", "expand_site", "upgrade_garage", "upgrade_storage",
    ),
    "chat": (
        "post_world_chat", "post_guild_chat", "send_direct_message",
        "create_guild", "invite_to_guild", "accept_guild_invite", "leave_guild",
        "remove_guild_member",
    ),
    "food": ("eat_best_available",),
    "warning": ("wait",),
}

GLYPH_FOR_ACTION = {
    action: family for family, actions in ACTION_FAMILY.items() for action in actions
}

GLYPH_FOR_EVENT = {
    "business_founded": "build", "business_bankrupt": "warning",
    "business_closed": "warning", "bankruptcy_warning": "warning",
    "agent_died": "death", "starved_to_death": "death", "assets_wiped": "warning",
    "sustenance_hungry": "food", "sustenance_starving": "warning", "ate": "food",
    "hired": "hire", "fired": "hire", "quit_job": "hire", "job_started": "hire",
    "job_posted": "hire", "job_applied": "hire",
    "chat": "chat", "trade": "coin", "trade_accepted": "coin",
    "production": "work", "wages_paid": "coin", "travel": "travel",
    "vehicle_purchased": "travel", "property_purchased": "build",
    "convoy_ambushed": "combat", "heist_success": "combat",
    "decision_cap_reached": "warning", "llm_reasoning": "chat",
}


# ---------------------------------------------------------------------------
# THE CHECK
# ---------------------------------------------------------------------------

def check() -> list[str]:
    """Every entity in `data.py` has art, and every path resolves.

    Run from `run_phase1.py` alongside the economic invariants. The failure this
    prevents is the quiet one: a good added to `data.py` renders as a blank
    square in a classroom, months later, in front of people.
    """
    problems: list[str] = []

    def exists(path: Path, what: str) -> None:
        if not path.exists():
            problems.append(f"{what}: missing art file {path.relative_to(ROOT)}")

    for item in D.ALL_ITEMS:
        exists(item_icon(item), f"item {item!r}")
    for name in D.VEHICLES:
        exists(vehicle_sprite(name), f"vehicle {name!r}")

    for btype in D.BUSINESS_TYPES:
        if btype not in STRUCTURE_FOR_BUSINESS:
            problems.append(f"business type {btype!r} has no structure sprite")
        else:
            exists(STRUCTURE_FOR_BUSINESS[btype], f"business {btype!r}")

    for loc in M.LOCATIONS_SPEC:
        if loc.name not in DECOR_FOR_LOCATION:
            problems.append(f"location {loc.name!r} has no decor")
        if loc.kind not in GROUND_FOR_KIND:
            problems.append(f"location kind {loc.kind!r} has no ground tile")
        for path in DECOR_FOR_LOCATION.get(loc.name, []):
            exists(path, f"decor for {loc.name!r}")

    for role in D.WAGE_ROLES:
        if role not in POSE_FOR_ROLE:
            problems.append(f"role {role!r} has no pose")
    for faction in FACTION_BASE:
        for pose in POSES:
            exists(unit(faction, pose), f"unit {faction}/{pose}")

    for slot in D.MODEL_ROSTER:
        if slot.openrouter_id not in FACTION_FOR_MODEL:
            problems.append(f"model {slot.openrouter_id!r} has no faction colour")
        if slot.openrouter_id not in CHARACTER_FOR_MODEL:
            problems.append(f"model {slot.openrouter_id!r} has no character variant")
        for owner in (False, True):
            exists(agent_sprite(slot.openrouter_id, owns_business=owner),
                   f"agent sprite for {slot.openrouter_id!r}")

    # Two models sharing a look means a mixed run cannot be read by model, which
    # is most of the point of running five.
    variants = {CHARACTER_FOR_MODEL.get(s.openrouter_id) for s in D.MODEL_ROSTER}
    if len(variants) < len(D.MODEL_ROSTER):
        problems.append("two models share a character variant")

    # Every action an agent can actually take needs a glyph. Imported here
    # rather than at module scope: `schemas` reaches `actions` -> `state`, and
    # this module is imported BY the renderer, which must stay cheap.
    from . import schemas as S

    for tool in S.tool_schemas():
        name = tool["function"]["name"]
        if name not in GLYPH_FOR_ACTION:
            problems.append(f"action {name!r} has no glyph")

    for family in set(GLYPH_FOR_ACTION.values()) | set(GLYPH_FOR_EVENT.values()):
        exists(ui_glyph(family), f"glyph {family!r}")
    exists(GOVERNMENT_BADGE, "government badge")
    for path in (ROAD_STRAIGHT, ROAD_JUNCTION, *GROUND_FOR_KIND.values()):
        exists(path, "terrain")

    return problems


if __name__ == "__main__":
    issues = check()
    if issues:
        print(f"SPRITES: {len(issues)} problem(s)")
        for line in issues:
            print(f"  - {line}")
        raise SystemExit(1)
    print("SPRITES: all bound.")
