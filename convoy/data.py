"""Static game data, transcribed from convoy_bronze_age_economy.xlsx.

The spreadsheet is the source of truth. Every value here is a direct transcription
of a cell on the named tab; derived values are computed from the Assumptions levers
at import time rather than hardcoded, so rebalancing the spreadsheet means editing
ASSUMPTIONS here and nothing else.

Resolved contradictions (confirmed with the designer, 2026-08-09):
  * Staffing: the Businesses tab governs. Output uses uncapped 0.95^(n-1) decay.
    The Assumptions rows "Employee Speed Bonus 0.4" / "Max Employees 3" are stale
    and deliberately unused -- see EMPLOYEE_SPEED_BONUS_UNUSED below.
  * Carrying: the Vehicles tab governs. 5 units on foot, vehicle capacity mounted.
    The World State Schema's "max 5 whether on foot or mounted" note is stale.
  * Recipes: 1 unit per listed input unless an explicit quantity is given (Camel,
    Horse). Verified against every Input Cost figure on the Production Chain tab.
  * Bootstrap: no free public resource nodes. Government businesses (one per type)
    are the hour-zero employer and convoy organizer.
"""

from __future__ import annotations

from dataclasses import dataclass, field

# ---------------------------------------------------------------------------
# Assumptions tab -- the global rebalancing levers
# ---------------------------------------------------------------------------

CURRENCY_NAME = "Denari"
STARTING_DENARI = 100.0

NPC_BUY_PCT_RAW = 0.40          # Trading Post pays this % of base when buying from players
NPC_SELL_PCT_COMMON = 1.60      # General Store charges this % of base
NPC_BUY_PCT_ORE = 0.40          # Refinery buying ore
NPC_SELL_PCT_REFINED = 1.50     # Refinery selling refined goods
NPC_SELL_PCT_WEAPONS = 1.70     # Weaponsmith / Armory
NPC_SELL_PCT_VEHICLES = 1.50    # Stables
NPC_INSURANCE_PREMIUM_PCT = 0.20
INSURANCE_PAYOUT_PCT = 0.70     # Government & Insurance tab
INSURANCE_RESERVE_PCT = 0.70    # reserve floor, derived from the payout rate

PLAYER_STORE_FLOOR_PCT = 0.60   # players cannot retail below this % of base price

NPC_WAGE_MULTIPLIER = 2.25      # NPC wage / smart player wage
MIN_WAGE_PCT_OF_SMART = 0.50

# Stale Assumptions rows, retained only so the divergence from the spreadsheet is
# explicit and greppable. The Businesses tab's diminishing-returns model governs.
EMPLOYEE_SPEED_BONUS_UNUSED = 0.40
MAX_EMPLOYEES_PRODUCTION_UNUSED = 3

WORKER_DECAY_PER_HEAD = 0.95    # Businesses tab: per-worker rate x 0.95^(n-1)
STORE_MAX_EMPLOYEES = 2         # Businesses tab, store-type businesses only

BANKRUPTCY_GRACE_HOURS = 24.0
RP_PER_RESEARCHER_HOUR = 8.0

DEFAULT_WAGE_TAX = 0.05
DEFAULT_SALES_TAX = 0.05
TAX_MIN, TAX_MAX = 0.0, 0.25

# PROPERTY TAX is ANNUAL, billed weekly (designer decision, 2026-08-12). The
# workbook's "5% charged every 24 real hours" made a starter home a pure loss:
# net-worth neutral to buy, then -125 Denari of tax across a 120-hour run for 20
# units of storage. As an annual rate it is 5%/52 = ~0.096% per weekly bill --
# roughly half a Denari a week on a 500 Denari home.
#
# Note for the validation run: the first bill falls at hour 168, so a 120-hour
# run collects NO property tax at all. That is intended, not a bug.
DEFAULT_PROPERTY_TAX = 0.05          # ANNUAL rate; policy still bounds it 0-25%
WEEKS_PER_YEAR = 52.0
PROPERTY_TAX_PERIOD_HOURS = 168.0    # billed weekly


def property_tax_per_bill(annual_rate: float) -> float:
    """The fraction of assessed value taken by one weekly bill."""
    return annual_rate / WEEKS_PER_YEAR


# ---------------------------------------------------------------------------
# Stolen goods & safehouses
# ---------------------------------------------------------------------------

# Loot cannot be sold or traded straight off the road. Stolen goods must sit in
# a SAFEHOUSE -- a property you own -- for 24 continuous hours before they can be
# moved on. This does three things at once: it puts a real cost and delay on
# piracy, it gives home storage its first genuine purpose, and it means a thief
# without a home has nowhere to launder and must either sell to a fence with one
# or hold hot goods they cannot spend.
SAFEHOUSE_CURE_HOURS = 24.0

RESPAWN_SECONDS = 60.0
ON_FOOT_CAPACITY = 5

# Social layer limits. Without these, open trade offers and chat history grow
# without bound -- which is a state-size problem for checkpoints and, worse, a
# token problem once an agent's observation includes them.
TRADE_OFFER_TTL_MINUTES = 15.0
MAX_OPEN_OFFERS_PER_SELLER = 3
CHAT_HISTORY_LIMIT = 900        # total messages before a prune runs
CHAT_RETENTION = {"world": 300, "guild": 300, "direct": 300}
CHAT_VISIBLE_DEFAULT = 30       # messages shown to an agent per decision

# ---------------------------------------------------------------------------
# Sustenance tab -- eating, status escalation, death
# ---------------------------------------------------------------------------

# Two paths to a meal: SELF-PREP (free, consumes Grain + Water from own inventory,
# always the 12-hour base window) or a TAVERN MEAL (costs money, and a Tavern with
# Quality research unlocks longer-window breads). Rest is NOT a separate mechanic
# -- Sustenance is the only survival system.

SELF_PREP_INPUTS = {"Grain": 1, "Water": 1}
SELF_PREP_WINDOW_HOURS = 12.0


@dataclass(frozen=True)
class Meal:
    """A Tavern food item. Every variant uses the same Grain + Water recipe --
    Research changes what the meal DOES, never what it costs to make."""

    name: str
    window_hours: float      # how long the agent stays at Normal
    price: float
    required_tier: int       # Tavern Quality research tier needed to serve it
    heal: float = 0.0        # HP restored immediately on eating
    work_bonus: float = 0.0  # production speed bonus, for the meal's duration
    line: str = "duration"   # duration | hearty | laborer


# The Sustenance tab's duration ladder, verbatim.
_DURATION_LINE = [
    ("Meal", 12.0, 10.0, 0),
    ("Tier 1 Bread", 15.0, 15.0, 1),
    ("Tier 2 Bread", 18.0, 22.0, 2),
    ("Fine Bread", 21.0, 30.0, 3),
    ("Masterwork Bread", 24.0, 40.0, 4),
    ("Legendary Bread", 30.0, 55.0, 5),
]

# DESIGNER ADDITION (2026-08-12): researchable food variants.
#
# The Sustenance tab gave Food a single axis -- duration -- via its own fixed
# hour table. This adds the two other axes a Tavern can put its Quality tier
# into, so Food behaves like every other category on the Research tab: one
# bonus POOL, allocated across the stats available to that category.
#
#   duration -> the fixed hour table above (unchanged)
#   hearty   -> heals tier% of a 100 HP bar (5/10/15/20/25 HP), base 12h window
#   laborer  -> tier% production speed for the meal's duration, base 12h window
#
# A Tavern at Quality tier T can serve any variant up to T, so the tier is the
# unlock and the variant is the choice -- exactly how Melee/Ranged/Armor/Vehicle
# split a single tier pool across their own stats.
MEALS: dict[str, Meal] = {}
for _name, _win, _price, _tier in _DURATION_LINE:
    MEALS[_name] = Meal(_name, _win, _price, _tier, line="duration")

# Tier -> (quality %, price). The percentages mirror the Research tab's tier pool
# (5/10/15/20/25%); prices match the duration bread of the same tier.
_VARIANT_TIERS = [(1, 0.05, 15.0), (2, 0.10, 22.0), (3, 0.15, 30.0),
                  (4, 0.20, 40.0), (5, 0.25, 55.0)]
_MAX_HP = 100.0

for _tier, _pct, _price in _VARIANT_TIERS:
    MEALS[f"Hearty Bread T{_tier}"] = Meal(
        f"Hearty Bread T{_tier}", SELF_PREP_WINDOW_HOURS, _price, _tier,
        heal=_MAX_HP * _pct, line="hearty",
    )
    MEALS[f"Laborer's Bread T{_tier}"] = Meal(
        f"Laborer's Bread T{_tier}", SELF_PREP_WINDOW_HOURS, _price, _tier,
        work_bonus=_pct, line="laborer",
    )

# Once the window expires the stages are FIXED at 12 hours each regardless of meal
# tier -- a higher tier buys a longer safe window, not slower decay.
HUNGRY_STAGE_HOURS = 12.0
STARVING_STAGE_HOURS = 12.0
HUNGRY_SPEED_PENALTY = 0.10      # -10% production/combat speed
STARVING_SPEED_PENALTY = 0.25    # -25% speed
STARVING_HP_HIT = 5.0            # -5 HP once, on entering Starving

# Stated assumptions, flagged for review (the tab does not specify either):
#   * respawn resets Hours Since Last Meal to 0 on a fresh 12-hour window,
#     otherwise an agent respawns already starving and dies in a loop.
#   * the Hungry/Starving penalty applies to production and combat only, per the
#     tab's wording -- not to travel time.
RESPAWN_RESETS_HUNGER = True

# ---------------------------------------------------------------------------
# Resources tab
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Resource:
    name: str
    rarity: str
    source: str
    base_price: float
    base_rate_hr: float   # per single Novice worker, before decay/skill
    refined: bool = False


RESOURCES: dict[str, Resource] = {
    r.name: r
    for r in [
        Resource("Water", "Common", "Farm", 1, 72),
        Resource("Grain", "Common", "Farm", 2, 72),
        Resource("Wood", "Common", "Mining Operation", 2, 72),
        Resource("Stone", "Common", "Mining Operation", 3, 72),
        Resource("Clay", "Common", "Mining Operation", 2, 72),
        Resource("Hide", "Common", "Farm", 4, 72),
        Resource("Copper Ore", "Uncommon", "Mining Operation", 6, 36),
        Resource("Tin Ore", "Uncommon", "Mining Operation", 8, 36),
        Resource("Iron Ore", "Uncommon", "Mining Operation", 12, 36),
        Resource("Hardwood", "Uncommon", "Mining Operation", 8, 36),
        # Wool is commented out (designer decision, 2026-08-12). The Resources tab
        # lists it as feeding "Clothing/cosmetics", but no clothing exists yet and
        # none is needed for this build -- so it was a farmable, sellable good
        # that nothing consumed. Restore this line when clothing is designed.
        # Resource("Wool", "Common", "Farm", 5, 72),
        Resource("Charcoal", "Uncommon", "Refinery", 4, 15, refined=True),
        Resource("Tanned Leather", "Uncommon", "Refinery", 9, 15, refined=True),
        Resource("Bronze", "Uncommon", "Refinery", 32, 15, refined=True),
        Resource("Iron", "Rare", "Refinery", 36, 15, refined=True),
    ]
}

RAW_RESOURCES = [n for n, r in RESOURCES.items() if not r.refined]
REFINED_RESOURCES = [n for n, r in RESOURCES.items() if r.refined]

# ---------------------------------------------------------------------------
# Production Chain tab -- recipes. Quantities are 1 unless stated.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Recipe:
    output: str
    inputs: dict[str, int]
    produced_at: str
    base_price: float


REFINING_RECIPES: dict[str, Recipe] = {
    "Charcoal": Recipe("Charcoal", {"Wood": 1}, "Refinery", 4),
    "Tanned Leather": Recipe("Tanned Leather", {"Hide": 1, "Water": 1}, "Refinery", 9),
    "Bronze": Recipe("Bronze", {"Copper Ore": 1, "Tin Ore": 1, "Charcoal": 1}, "Refinery", 32),
    "Iron": Recipe("Iron", {"Iron Ore": 1, "Charcoal": 1}, "Refinery", 36),
}

CRAFTING_RECIPES: dict[str, Recipe] = {
    r.output: r
    for r in [
        # Weapons -- Weaponsmith / Armory
        Recipe("Sling", {"Tanned Leather": 1, "Wood": 1}, "Weaponsmith / Armory", 50),
        Recipe("Wooden Spear", {"Wood": 1}, "Weaponsmith / Armory", 60),
        Recipe("Bronze Dagger", {"Bronze": 1, "Wood": 1}, "Weaponsmith / Armory", 120),
        Recipe("Bronze-Tipped Spear", {"Bronze": 1, "Wood": 1}, "Weaponsmith / Armory", 220),
        Recipe("Bronze Sword", {"Bronze": 1, "Wood": 1}, "Weaponsmith / Armory", 250),
        Recipe("Bow", {"Hardwood": 1, "Tanned Leather": 1}, "Weaponsmith / Armory", 300),
        Recipe("Iron Dagger", {"Iron": 1, "Hardwood": 1}, "Weaponsmith / Armory", 350),
        Recipe("Iron-Tipped Spear", {"Iron": 1, "Hardwood": 1}, "Weaponsmith / Armory", 550),
        Recipe("Iron Sword", {"Iron": 1, "Hardwood": 1}, "Weaponsmith / Armory", 650),
        # Armor -- Weaponsmith / Armory
        Recipe("Leather Cap", {"Tanned Leather": 1}, "Weaponsmith / Armory", 80),
        Recipe("Leather Vest", {"Tanned Leather": 1}, "Weaponsmith / Armory", 150),
        Recipe("Leather Leggings", {"Tanned Leather": 1}, "Weaponsmith / Armory", 80),
        Recipe("Bronze Helm", {"Bronze": 1, "Tanned Leather": 1}, "Weaponsmith / Armory", 300),
        Recipe("Bronze Cuirass", {"Bronze": 1, "Tanned Leather": 1}, "Weaponsmith / Armory", 550),
        Recipe("Bronze Greaves", {"Bronze": 1, "Tanned Leather": 1}, "Weaponsmith / Armory", 300),
        Recipe("Iron Helm", {"Iron": 1, "Tanned Leather": 1}, "Weaponsmith / Armory", 500),
        Recipe("Iron Cuirass", {"Iron": 1, "Tanned Leather": 1}, "Weaponsmith / Armory", 900),
        Recipe("Iron Greaves", {"Iron": 1, "Tanned Leather": 1}, "Weaponsmith / Armory", 500),
        # Vehicles -- Vehicle Dealer / Stable
        Recipe("Donkey Cart", {"Wood": 1, "Bronze": 1, "Tanned Leather": 1}, "Vehicle Dealer / Stable", 400),
        Recipe("2-Horse Chariot", {"Hardwood": 1, "Tanned Leather": 1}, "Vehicle Dealer / Stable", 700),
        Recipe("4-Horse Chariot", {"Iron": 1, "Hardwood": 1, "Tanned Leather": 1}, "Vehicle Dealer / Stable", 1600),
        Recipe("Camel", {"Water": 15, "Grain": 10, "Tanned Leather": 1}, "Vehicle Dealer / Stable", 150),
        Recipe("Horse", {"Water": 20, "Grain": 15, "Tanned Leather": 1}, "Vehicle Dealer / Stable", 200),
        # Other stores
        Recipe("Upgraded Tools", {"Wood": 1, "Bronze": 1}, "Mining/Farming Equipment Store", 130),
        Recipe("Property Upgrade", {"Stone": 1, "Clay": 1, "Wood": 1}, "Home Improvement Store", 50),
        # Tavern food. Every tier uses the same Grain + Water recipe -- Research
        # changes the Sustenance window and price, never the inputs (Research tab).
        *[
            Recipe(_m.name, {"Grain": 1, "Water": 1}, "Tavern / Inn", _m.price)
            for _m in MEALS.values()
        ],
    ]
}

# Crafting throughput. The spreadsheet gives per-hour rates only for extraction and
# refining; final assembly has no stated rate. Stated assumption, flagged for review:
# a final good takes the same worker-hour budget as one refined unit (15/hr base).
CRAFT_BASE_RATE_HR = 15.0

# ---------------------------------------------------------------------------
# Weapons / Armor / Vehicles tabs
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Weapon:
    name: str
    rarity: str
    kind: str
    damage: float
    base_price: float
    attack_speed: float       # seconds per swing
    crit_mult: float
    crit_kind: str


WEAPONS: dict[str, Weapon] = {
    w.name: w
    for w in [
        Weapon("Slingshot", "Common", "Ranged", 10, 0, 0.90, 2.0, "headshot"),
        Weapon("Sling", "Common", "Ranged", 14, 50, 0.80, 2.0, "headshot"),
        Weapon("Wooden Spear", "Common", "Melee", 22, 60, 0.70, 1.5, "backstab"),
        Weapon("Bronze Dagger", "Uncommon", "Melee", 16, 120, 0.40, 1.5, "backstab"),
        Weapon("Bronze-Tipped Spear", "Uncommon", "Melee", 28, 220, 0.75, 1.5, "backstab"),
        Weapon("Bronze Sword", "Uncommon", "Melee", 34, 250, 0.60, 1.5, "backstab"),
        Weapon("Bow", "Rare", "Ranged", 20, 300, 0.85, 2.0, "headshot"),
        Weapon("Iron Dagger", "Rare", "Melee", 24, 350, 0.40, 1.5, "backstab"),
        Weapon("Iron-Tipped Spear", "Rare", "Melee", 36, 550, 0.75, 1.5, "backstab"),
        Weapon("Iron Sword", "Rare", "Melee", 50, 650, 0.60, 1.5, "backstab"),
    ]
}


@dataclass(frozen=True)
class ArmorPiece:
    name: str
    slot: str
    tier: str
    damage_reduction: float
    base_price: float


ARMOR: dict[str, ArmorPiece] = {
    a.name: a
    for a in [
        ArmorPiece("Leather Cap", "Head", "Leather", 0.05, 80),
        ArmorPiece("Leather Vest", "Chest", "Leather", 0.10, 150),
        ArmorPiece("Leather Leggings", "Legs", "Leather", 0.05, 80),
        ArmorPiece("Bronze Helm", "Head", "Bronze", 0.10, 300),
        ArmorPiece("Bronze Cuirass", "Chest", "Bronze", 0.20, 550),
        ArmorPiece("Bronze Greaves", "Legs", "Bronze", 0.10, 300),
        ArmorPiece("Iron Helm", "Head", "Iron", 0.15, 500),
        ArmorPiece("Iron Cuirass", "Chest", "Iron", 0.25, 900),
        ArmorPiece("Iron Greaves", "Legs", "Iron", 0.15, 500),
    ]
}


@dataclass(frozen=True)
class Vehicle:
    name: str
    rarity: str
    speed_label: str
    speed_mult: float     # stated assumption -- see SPEED_MULTIPLIERS note
    cargo_capacity: int
    armor: str
    base_price: float


# The spreadsheet gives speed as adjectives only ("Slow", "Fastest") plus one
# anchor: ~5 min full transit at Medium speed. Numeric multipliers are a stated
# assumption, flagged for review before Phase 5.
SPEED_MULTIPLIERS = {"Slowest": 0.5, "Slow": 0.75, "Medium": 1.0, "Fast": 1.5, "Fastest": 2.0}

VEHICLES: dict[str, Vehicle] = {
    v.name: v
    for v in [
        Vehicle("On Foot", "Common", "Slowest", 0.5, ON_FOOT_CAPACITY, "None", 0),
        Vehicle("Camel", "Common", "Slow", 0.75, 20, "None", 150),
        Vehicle("Horse", "Common", "Medium", 1.0, 15, "None", 200),
        Vehicle("Donkey Cart", "Uncommon", "Slow", 0.75, 100, "None", 400),
        Vehicle("2-Horse Chariot", "Rare", "Fast", 1.5, 80, "Light", 700),
        Vehicle("4-Horse Chariot", "Rare", "Fastest", 2.0, 200, "Medium", 1600),
    ]
}

# ---------------------------------------------------------------------------
# Businesses tab
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class BusinessType:
    name: str
    startup_cost: float
    max_employees: int | None     # None == uncapped
    needs_worker: bool
    can_research: bool
    production_roles: tuple[str, ...]
    outputs: tuple[str, ...] = ()


BUSINESS_TYPES: dict[str, BusinessType] = {
    b.name: b
    for b in [
        BusinessType(
            "Mining Operation", 350, None, True, True, ("Laborer", "Miner"),
            ("Wood", "Stone", "Clay", "Copper Ore", "Tin Ore", "Iron Ore", "Hardwood"),
        ),
        BusinessType(
            "Farm", 300, None, True, True, ("Farmhand", "Laborer"),
            ("Water", "Grain", "Hide"),        # Wool removed with the resource
        ),
        BusinessType(
            "Refinery", 900, None, True, True, ("Refinery Worker",),
            ("Charcoal", "Tanned Leather", "Bronze", "Iron"),
        ),
        BusinessType("General Store", 500, STORE_MAX_EMPLOYEES, True, True, ("Store Clerk",)),
        BusinessType(
            "Home Improvement Store", 500, STORE_MAX_EMPLOYEES, True, True, ("Store Clerk",),
            ("Property Upgrade",),
        ),
        BusinessType(
            "Mining/Farming Equipment Store", 550, STORE_MAX_EMPLOYEES, True, True, ("Store Clerk",),
            ("Upgraded Tools",),
        ),
        BusinessType(
            "Weaponsmith / Armory", 700, STORE_MAX_EMPLOYEES, True, True, ("Blacksmith",),
            tuple(n for n, r in CRAFTING_RECIPES.items() if r.produced_at == "Weaponsmith / Armory"),
        ),
        BusinessType(
            "Vehicle Dealer / Stable", 600, STORE_MAX_EMPLOYEES, True, True, ("Stablehand", "Store Clerk"),
            tuple(n for n, r in CRAFTING_RECIPES.items() if r.produced_at == "Vehicle Dealer / Stable"),
        ),
        BusinessType(
            "Tavern / Inn", 400, STORE_MAX_EMPLOYEES, True, True, ("Store Clerk",),
            tuple(MEALS),
        ),
        BusinessType("Private Security Contractor", 1000, None, True, False, ()),
        BusinessType("Insurance Brokerage", 1500, 0, False, False, ()),
    ]
}

# ---------------------------------------------------------------------------
# Wages tab
# ---------------------------------------------------------------------------

NPC_WAGES: dict[str, float] = {
    "Laborer": 45,
    "Miner": 65,
    "Farmhand": 50,
    "Refinery Worker": 85,
    "Store Clerk": 40,
    "Blacksmith": 80,
    "Stablehand": 45,
    "Researcher": 75,
}

SMART_WAGES = {r: w / NPC_WAGE_MULTIPLIER for r, w in NPC_WAGES.items()}
WAGE_FLOORS = {r: w * MIN_WAGE_PCT_OF_SMART for r, w in SMART_WAGES.items()}

WAGE_ROLES = tuple(NPC_WAGES)

# Skill Progression -- (min_hours, speed_bonus, label); speed only.
SKILL_TIERS: list[tuple[float, float, str]] = [
    (0, 0.00, "Novice"),
    (5, 0.10, "Journeyman"),
    (15, 0.20, "Skilled"),
    (35, 0.35, "Expert"),
    (70, 0.50, "Master"),
]

# Which role a business assigns for producing a given output.
ROLE_FOR_OUTPUT: dict[str, str] = {}
for _res in ("Wood", "Stone", "Clay"):
    ROLE_FOR_OUTPUT[_res] = "Laborer"
for _res in ("Copper Ore", "Tin Ore", "Iron Ore", "Hardwood"):
    ROLE_FOR_OUTPUT[_res] = "Miner"
for _res in ("Water", "Grain", "Hide", "Wool"):
    ROLE_FOR_OUTPUT[_res] = "Farmhand"
for _res in REFINED_RESOURCES:
    ROLE_FOR_OUTPUT[_res] = "Refinery Worker"
for _good, _r in CRAFTING_RECIPES.items():
    ROLE_FOR_OUTPUT[_good] = {
        "Weaponsmith / Armory": "Blacksmith",
        "Vehicle Dealer / Stable": "Stablehand",
    }.get(_r.produced_at, "Store Clerk")

# ---------------------------------------------------------------------------
# Research tab
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ResearchTier:
    tier: int
    cumulative_rp: float
    efficiency: float
    quality: float
    tag: str | None


RESEARCH_TIERS: list[ResearchTier] = [
    ResearchTier(1, 150, 0.05, 0.05, None),
    ResearchTier(2, 400, 0.10, 0.10, None),
    ResearchTier(3, 900, 0.15, 0.15, "Fine"),
    ResearchTier(4, 1800, 0.20, 0.20, "Masterwork"),
    ResearchTier(5, 3500, 0.25, 0.25, "Legendary Craftsmanship"),
]

# Researcher material burn, per researcher-hour, on top of wages.
RESEARCH_MATERIAL: dict[str, tuple[str, float]] = {
    "Mining Operation": ("Wood", 0.5),
    "Farm": ("Grain", 0.5),
    "Refinery": ("Charcoal", 0.5),
    "General Store": ("Wood", 0.3),
    "Home Improvement Store": ("Stone", 0.5),
    "Mining/Farming Equipment Store": ("Wood", 0.5),
    "Weaponsmith / Armory": ("Bronze", 0.3),
    "Vehicle Dealer / Stable": ("Tanned Leather", 0.3),
    "Tavern / Inn": ("Grain", 0.5),
}

# Category names follow the Research tab's "Quality Bonus Stat Pools" table.
# The tab's examples table abbreviates them (Melee / Ranged / Vehicle), so both
# spellings resolve -- see QUALITY_CATEGORY_ALIASES.
QUALITY_STAT_POOLS: dict[str, tuple[str, ...]] = {
    "Melee Weapons": ("Attack Speed", "Damage"),
    "Ranged Weapons": ("Attack Speed", "Damage", "Accuracy"),
    "Armor": ("Damage Reduction", "Inventory Capacity"),
    "Vehicles": ("Cargo Capacity", "Speed", "Damage Resistance"),
    # Food uses its OWN fixed hour table for duration rather than the % pool
    # (Research tab), plus the two variant axes added 2026-08-12.
    "Food (Tavern Meals)": ("Sustenance Duration", "Health", "Work Speed"),
}

QUALITY_CATEGORY_ALIASES: dict[str, str] = {
    "Melee": "Melee Weapons",
    "Ranged": "Ranged Weapons",
    "Vehicle": "Vehicles",
    "Food": "Food (Tavern Meals)",
}

# Which category each craftable item belongs to, for quality allocation.
QUALITY_CATEGORY_FOR_ITEM: dict[str, str] = {}
for _w, _spec in WEAPONS.items():
    QUALITY_CATEGORY_FOR_ITEM[_w] = (
        "Ranged Weapons" if _spec.kind.startswith("Ranged") else "Melee Weapons"
    )
for _a in ARMOR:
    QUALITY_CATEGORY_FOR_ITEM[_a] = "Armor"
for _v in VEHICLES:
    QUALITY_CATEGORY_FOR_ITEM[_v] = "Vehicles"
for _m in MEALS:
    QUALITY_CATEGORY_FOR_ITEM[_m] = "Food (Tavern Meals)"

# ---------------------------------------------------------------------------
# Convoy tab
# ---------------------------------------------------------------------------

CONVOY_PAY = {
    "Driver-provided": {"flat": 10.0, "commission": 0.005, "basis": "vehicle"},
    "Driver-own": {"flat": 15.0, "commission": 0.0075, "basis": "vehicle"},
    "Scout": {"flat": 8.0, "commission": 0.0025, "basis": "convoy"},
    "Bodyguard": {"flat": 8.0, "commission": 0.0035, "basis": "convoy"},
}

CONVOY_MAX_VEHICLES = 10
CONVOY_RECRUIT_WINDOW_MIN = 15.0
CONVOY_MAX_EXTENSIONS = 3
CONVOY_POST_COOLDOWN_HOURS = 1.0

# ---------------------------------------------------------------------------
# Government & Insurance tab
# ---------------------------------------------------------------------------

BOUNTY_MURDER = 300.0
BOUNTY_SABOTAGE = 150.0
BOUNTY_THEFT_PCT = 0.25
POLICE_EVIDENCE_WINDOW_MIN = 10.0
POLICE_TIERS = {0: (None, 0), 1: (60.0, 1), 2: (45.0, 2), 3: (30.0, 3)}

# ---------------------------------------------------------------------------
# World tab -- named location graph
# ---------------------------------------------------------------------------

# The geography now lives in world_map.py -- seven places on one road, six
# segments with their own terrain and danger, and eight spur roads. Re-exported
# here so existing imports keep working.
from .world_map import (  # noqa: E402
    ALL_PLACES,
    FULL_ROAD_SECONDS,
    LOCATIONS,
    PROTECTED_ZONES,
    SEGMENTS,
    SPURS,
    is_protected,
    is_spur,
    junction_of,
)

FULL_TRANSIT_SECONDS_AT_MEDIUM = FULL_ROAD_SECONDS

# Garage & storage upgrade pricing (World State Schema tab)
# Costs are CUMULATIVE totals per the schema, so stepping up a tier charges the
# delta. Each tier also consumes the raw materials the Inputs column lists --
# that is the Property Upgrade transaction.
PROPERTY_BASE_COST = 500.0
PROPERTY_BASE_STORAGE = 20
GARAGE_TIERS = {1: (200.0, 1), 2: (450.0, 2), 3: (800.0, 3)}
STORAGE_TIERS = {1: (150.0, 70), 2: (350.0, 170), 3: (700.0, 370)}

GARAGE_TIER_INPUTS: dict[int, dict[str, int]] = {
    1: {"Stone": 1, "Wood": 1},
    2: {"Stone": 1, "Wood": 1, "Bronze": 1},
    3: {"Stone": 1, "Iron": 1, "Wood": 1},
}
STORAGE_TIER_INPUTS: dict[int, dict[str, int]] = {
    1: {"Stone": 1, "Clay": 1},
    2: {"Stone": 1, "Clay": 1, "Wood": 1},
    3: {"Stone": 1, "Clay": 1, "Iron": 1},
}

# One "Property Upgrade" kit from a Home Improvement Store substitutes for a
# tier's entire raw-material requirement. Deliberately a poor deal at Tier 1
# (materials cost 5) and a fair one at Tier 3 (materials cost 41 with Iron) --
# a convenience good priced for the high end, which is what finally gives the
# Home Improvement Store a customer.
PROPERTY_UPGRADE_KIT = "Property Upgrade"

# Upgraded Tools -- the Equipment Store's only product, wired to the effect the
# Resources tab already claims for it ("tools" / mining-farming speed). The bonus
# size is a stated assumption; it stacks additively with skill and Research
# Efficiency, and applies to raw EXTRACTION only (Mining Operation and Farm),
# matching the "Mining/Farming Equipment Store" name.
TOOL_EXTRACTION_BONUS = 0.25

# Land and stockpiles. A worked site holds only so much output before production
# stalls for want of anywhere to put it -- which is what forces hauling runs and
# makes a vehicle worth owning. Base capacity is per starter site (8 plots).
SITE_STORAGE_PER_PLOT = 30      # units of on-site stockpile per plot of land
SITE_EXPANSION_COST = 250.0     # Denari per +4-plot expansion
EXTRACTION_BUSINESS_TYPES = ("Mining Operation", "Farm")

# ---------------------------------------------------------------------------
# Combat & Heroes tab -- model roster
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ModelSlot:
    label: str
    openrouter_id: str
    agents: int
    reasoning_effort: str | None
    supports_structured_outputs: bool
    price_in_per_mtok: float
    price_out_per_mtok: float


# Verified against the live OpenRouter catalog on 2026-08-09. Prices below are the
# real catalog figures, which differ from the spreadsheet's estimates (Terra is 5x
# cheaper than budgeted, Luna 2x). Ling 3.0 Flash does NOT support structured
# outputs or response_format -- it must be driven via tool-calling.
MODEL_ROSTER: list[ModelSlot] = [
    ModelSlot("GPT-5.6 Terra", "openai/gpt-5.6-terra", 15, "high", True, 1.00, 6.00),
    ModelSlot("Ling 3.0 Flash", "inclusionai/ling-3.0-flash", 15, None, False, 0.021, 0.063),
    # Pinned rather than floating, so the model cannot change mid-run and poison
    # a 120-hour comparison (designer decision, 2026-08-11).
    ModelSlot("DeepSeek V4 Flash 0731", "deepseek/deepseek-v4-flash-0731", 15, "max", True, 0.09, 0.18),
    ModelSlot("Grok 4.3", "x-ai/grok-4.3", 15, "minimal", True, 1.25, 2.50),
    ModelSlot("GPT-5.6 Luna", "openai/gpt-5.6-luna", 15, "medium", True, 0.10, 0.60),
]

# COMBAT MODEL -- designer override of the Combat & Heroes tab (2026-08-11).
#
# The tab specified fixed ~6-second rounds and routed combat through a fast
# non-reasoning fallback model. Both are superseded: there is NO round length and
# NO fallback. Every agent fights on its OWN assigned model, and exchanges resolve
# in continuous time on each weapon's Attack Speed interval -- an agent acts as
# fast as it actually reacts. The swings-per-round table on that tab is therefore
# dead; Attack Speed is now a real-time interval, not a per-round divisor.
#
# Consequence worth watching in Phase 3: combat performance becomes partly a
# latency contest. A high-effort reasoning model that takes 8s to answer will be
# out-swung by a 1s model regardless of tactical quality. That is a real finding
# the roster comparison will surface rather than a bug to design around.
COMBAT_USES_OWN_MODEL = True
COMBAT_REALTIME = True

# An agent that has not answered by the time its weapon's interval elapses simply
# does not swing -- reaction speed is the limiter, not a scheduler.
COMBAT_MISSED_INTERVAL_IS_NO_SWING = True

# ---------------------------------------------------------------------------
# Agent Scheduling & Diary tab
# ---------------------------------------------------------------------------

REEVALUATION_INTERVAL_MIN = 15.0
DIARY_INTERVAL_HOURS = 1.0
SIM_DURATION_HOURS = 120.0


def base_price(item: str) -> float:
    """Base price for any tradeable item, from whichever tab defines it."""
    if item in RESOURCES:
        return RESOURCES[item].base_price
    if item in WEAPONS:
        return WEAPONS[item].base_price
    if item in ARMOR:
        return ARMOR[item].base_price
    if item in VEHICLES:
        return VEHICLES[item].base_price
    if item in CRAFTING_RECIPES:
        return CRAFTING_RECIPES[item].base_price
    raise KeyError(f"no base price defined for {item!r}")


ALL_ITEMS = sorted(
    set(RESOURCES) | set(WEAPONS) | set(ARMOR) | set(VEHICLES) | set(CRAFTING_RECIPES)
)
