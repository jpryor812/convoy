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
STARTING_DENARI = 200.0

NPC_BUY_PCT_RAW = 0.40          # Trading Post pays this % of base when buying from players
# 1.60 -> 1.40 (designer decision, 2026-08-16). The chain's own rules compound:
# raw prices set refined prices through the 75% rule, refined set the meal base
# through it again, and the state's markup lands on top of all of it. A meal was
# reaching the shopper at 30.24 -- two hours of the lowest wage every twelve.
# Trimming the state's cut is the one lever that does not distort a single
# margin upstream, because the state is a backstop rather than a merchant.
NPC_SELL_PCT_COMMON = 1.40
NPC_BUY_PCT_ORE = 0.40          # Refinery buying ore
NPC_SELL_PCT_REFINED = 1.50     # Refinery selling refined goods
NPC_SELL_PCT_WEAPONS = 1.70     # Weaponsmith / Armory
NPC_SELL_PCT_VEHICLES = 1.50    # Stables
NPC_INSURANCE_PREMIUM_PCT = 0.20
INSURANCE_PAYOUT_PCT = 0.70     # Government & Insurance tab
INSURANCE_RESERVE_PCT = 0.70    # reserve floor, derived from the payout rate

PLAYER_STORE_FLOOR_PCT = 0.60   # players cannot retail below this % of base price

MIN_WAGE_PCT_OF_SMART = 0.50
# NPC_WAGE_MULTIPLIER lives with the wage tables further down, next to the
# SMART_WAGES it multiplies. It was defined here AND there, and the second
# definition silently won.

# Stale Assumptions rows, retained only so the divergence from the spreadsheet is
# explicit and greppable. The Businesses tab's diminishing-returns model governs.
EMPLOYEE_SPEED_BONUS_UNUSED = 0.40
MAX_EMPLOYEES_PRODUCTION_UNUSED = 3

WORKER_DECAY_PER_HEAD = 0.95    # Businesses tab: per-worker rate x 0.95^(n-1)
STORE_MAX_EMPLOYEES = 2         # Businesses tab, store-type businesses only

# The state is an employer of last resort, not a career (designer decision,
# 2026-08-14). Capping it forces agents to choose between a small safe wage and
# founding something of their own, which is the behaviour the run exists to
# observe. Player-owned businesses are deliberately UNCAPPED so that out-hiring
# the government is a strategy that can actually be tried.
GOVERNMENT_MAX_EMPLOYEES = 2

# A business is worth its startup cost plus this multiple of its last 24 hours
# of sales (designer decision, 2026-08-15).
BUSINESS_REVENUE_MULTIPLE = 3.0

BANKRUPTCY_GRACE_HOURS = 24.0
# How long a job advert stays on the board before it lapses. Long enough that a
# posting outlives the poster's next few wake-ups, short enough that a wage
# nobody will take does not sit there all run.
JOB_POSTING_HOURS = 12.0
RP_PER_RESEARCHER_HOUR = 8.0

# INCOME TAX -- 3% of every paycheck (designer decision, 2026-08-12), down from
# the workbook's 5%. Withheld from gross wages before the worker is paid, so it
# lands on the earner rather than the employer. Applies to every wage the world
# pays, NPC hires included; an owner self-staffing draws no wage, so there is no
# paycheck to tax. The workbook calls this "Wage Tax" -- same thing, and the
# field keeps that name so it stays greppable against the Assumptions tab.
DEFAULT_WAGE_TAX = 0.03
DEFAULT_SALES_TAX = 0.05
TAX_MIN, TAX_MAX = 0.0, 0.25

# PROPERTY TAX is a WEEKLY rate, billed weekly (designer decision, 2026-08-12).
#
# The workbook's "5% charged every 24 real hours" made a starter home a pure
# loss: net-worth neutral to buy, then -125 Denari of tax across a 120-hour run
# for 20 units of storage nobody needed. This is 0.5% per week instead -- 2.50
# Denari a week on a 500 Denari home, and 10 a week on a fully upgraded one.
# Steep enough that idle property is a real carrying cost, ~50x lighter than the
# original daily rule.
#
# Note for the validation run: the first bill falls at hour 168, so a 120-hour
# run collects NO property tax at all. That is intended, not a bug -- the tax
# only bites on a horizon longer than this validation window.
DEFAULT_PROPERTY_TAX = 0.005         # WEEKLY rate (26% annual equivalent)
WEEKS_PER_YEAR = 52.0
PROPERTY_TAX_PERIOD_HOURS = 168.0    # billed weekly
PROPERTY_TAX_ANNUAL_EQUIVALENT = DEFAULT_PROPERTY_TAX * WEEKS_PER_YEAR

# The Government tab bounds property tax 0-25%. That bound was written for the
# old daily rate; as a WEEKLY rate 25% would be 1300% a year, so policy votes are
# bounded separately here. Flagged for review.
PROPERTY_TAX_MIN, PROPERTY_TAX_MAX = 0.0, 0.02   # 0-2% weekly == 0-104% annual


def property_tax_per_bill(weekly_rate: float) -> float:
    """Fraction of assessed value taken by one weekly bill.

    The stored rate is already per-week, so this is the identity -- it exists so
    the billing cadence has exactly one place to change.
    """
    return max(PROPERTY_TAX_MIN, min(PROPERTY_TAX_MAX, weekly_rate))


# ---------------------------------------------------------------------------
# ROAD TAX -- the daily levy that funds roads and police
# ---------------------------------------------------------------------------
#
# The three taxes now do distinct jobs (designer decision, 2026-08-12):
#
#   SALES TAX    5%, at the point of sale
#   WAGE TAX     5%, on wages paid
#   PROPERTY TAX 0.5% weekly, on assessed property -- a carrying cost
#   ROAD TAX     1% DAILY, the public-works levy
#
# This replaces the workbook's "bundled infrastructure policies move Wage +
# Sales + Property together". Roads and police now have their own funding line,
# so a vote to build something has a visible, single price rather than being
# smeared across three unrelated taxes.
#
# BASE: assessed on Net Worth, the metric the game already ranks agents by.
# STATED ASSUMPTION, FLAGGED -- see PHASE1.md. At 1% daily a 120-hour run costs
# an agent roughly 5% of their wealth, which is material without being ruinous.
ROAD_TAX_DAILY = 0.01
ROAD_TAX_PERIOD_HOURS = 24.0
ROAD_TAX_MIN, ROAD_TAX_MAX = 0.0, 0.05     # 0-5% daily, by vote


@dataclass(frozen=True)
class RoadPolicy:
    """A public work the population can vote for, and what it costs per day.

    Rate deltas are proportional quarter-points on the 1% base rather than the
    workbook's 1-percentage-point steps, which were sized for a 5% base and
    would double the levy in a single vote here.
    """

    name: str
    rate_delta: float          # added to the daily road tax
    convoy_speed: float = 0.0  # multiplier delta, e.g. +0.10 == 10% faster
    police_tier: int = 0       # sets police tier if higher than current
    second_route: bool = False
    blurb: str = ""


ROAD_POLICIES: dict[str, RoadPolicy] = {
    p.name: p
    for p in [
        RoadPolicy("Better Roads", +0.0025, convoy_speed=+0.10,
                   blurb="Graded and drained. Convoys move 10% faster."),
        RoadPolicy("Less Road Funding", -0.0025, convoy_speed=-0.10,
                   blurb="Let them wash out. Cheaper, and 10% slower going."),
        RoadPolicy("New Road Project", +0.0075, second_route=True,
                   blurb="A second route exists. Harder for pirates to predict."),
        RoadPolicy("Police Tier 1", +0.0025, police_tier=1,
                   blurb="One officer, 60 second response. Until this passes, no bounty is possible."),
        RoadPolicy("Police Tier 2", +0.0025, police_tier=2,
                   blurb="Two officers, 45 second response, two dispatches at once."),
        RoadPolicy("Police Tier 3", +0.0025, police_tier=3,
                   blurb="Three officers, 30 second response, three dispatches at once."),
    ]
}


def road_tax_per_bill(daily_rate: float) -> float:
    """Fraction of Net Worth taken by one daily road-tax bill."""
    return max(ROAD_TAX_MIN, min(ROAD_TAX_MAX, daily_rate))


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

SELF_PREP_INPUTS = {"Grain": 1, "Purified Water": 1}   # unused: eat_self_prep is retired
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
# Prices raised across the ladder (2026-08-15). Bread is no longer milled from
# 3 denari of raw wheat and water: it takes 2 Grain + 1 Purified Water, both
# REFINED, worth 10 together. The 75% rule therefore puts a floor of 17.5 on
# every bread, so the whole line moves up and the tier spacing is preserved.
_DURATION_LINE = [
    ("Meal", 12.0, 18.0, 0),
    ("Tier 1 Bread", 15.0, 24.0, 1),
    ("Tier 2 Bread", 18.0, 32.0, 2),
    ("Fine Bread", 21.0, 44.0, 3),
    ("Masterwork Bread", 24.0, 58.0, 4),
    ("Legendary Bread", 30.0, 78.0, 5),
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
_VARIANT_TIERS = [(1, 0.05, 24.0), (2, 0.10, 32.0), (3, 0.15, 44.0),
                  (4, 0.20, 58.0), (5, 0.25, 78.0)]
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
        # EVERY chain runs farm/mine -> refinery -> store -> person (designer
        # decision, 2026-08-15). A farm therefore grows WHEAT and draws DIRTY
        # WATER; neither is edible. A refinery mills the one into Grain and
        # purifies the other, and only then can a tavern bake with them.
        Resource("Dirty Water", "Common", "Farm", 1, 72),
        Resource("Wheat", "Common", "Farm", 2, 72),
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
        # Timber, stone and clay used to go straight from a mine into a shop,
        # which broke the one-way chain (designer decision, 2026-08-15). A
        # refinery now stands between them and every workshop.
        Resource("Lumber", "Common", "Refinery", 4, 15, refined=True),
        Resource("Seasoned Hardwood", "Uncommon", "Refinery", 16, 15, refined=True),
        Resource("Cut Stone", "Common", "Refinery", 6, 15, refined=True),
        Resource("Fired Brick", "Common", "Refinery", 4, 15, refined=True),
        Resource("Purified Water", "Common", "Refinery", 2, 15, refined=True),
        Resource("Grain", "Common", "Refinery", 4, 15, refined=True),
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
    "Lumber": Recipe("Lumber", {"Wood": 1}, "Refinery", 4),
    "Seasoned Hardwood": Recipe("Seasoned Hardwood", {"Hardwood": 1}, "Refinery", 16),
    "Cut Stone": Recipe("Cut Stone", {"Stone": 1}, "Refinery", 6),
    "Fired Brick": Recipe("Fired Brick", {"Clay": 1}, "Refinery", 4),
    "Purified Water": Recipe("Purified Water", {"Dirty Water": 1}, "Refinery", 2),
    "Grain": Recipe("Grain", {"Wheat": 1}, "Refinery", 4),
    "Charcoal": Recipe("Charcoal", {"Wood": 1}, "Refinery", 4),
    "Tanned Leather": Recipe("Tanned Leather", {"Hide": 1, "Dirty Water": 1}, "Refinery", 9),
    "Bronze": Recipe("Bronze", {"Copper Ore": 1, "Tin Ore": 1, "Charcoal": 1}, "Refinery", 32),
    "Iron": Recipe("Iron", {"Iron Ore": 1, "Charcoal": 1}, "Refinery", 36),
}

CRAFTING_RECIPES: dict[str, Recipe] = {
    r.output: r
    for r in [
        # Weapons -- Weaponsmith / Armory
        Recipe("Sling", {"Tanned Leather": 1, "Lumber": 1}, "Weaponsmith / Armory", 50),
        Recipe("Wooden Spear", {"Lumber": 1}, "Weaponsmith / Armory", 60),
        Recipe("Bronze Dagger", {"Bronze": 1, "Lumber": 1}, "Weaponsmith / Armory", 120),
        Recipe("Bronze-Tipped Spear", {"Bronze": 1, "Lumber": 1}, "Weaponsmith / Armory", 220),
        Recipe("Bronze Sword", {"Bronze": 1, "Lumber": 1}, "Weaponsmith / Armory", 250),
        Recipe("Bow", {"Seasoned Hardwood": 1, "Tanned Leather": 1}, "Weaponsmith / Armory", 300),
        Recipe("Iron Dagger", {"Iron": 1, "Seasoned Hardwood": 1}, "Weaponsmith / Armory", 350),
        Recipe("Iron-Tipped Spear", {"Iron": 1, "Seasoned Hardwood": 1}, "Weaponsmith / Armory", 550),
        Recipe("Iron Sword", {"Iron": 1, "Seasoned Hardwood": 1}, "Weaponsmith / Armory", 650),
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
        Recipe("Donkey Cart", {"Lumber": 1, "Bronze": 1, "Tanned Leather": 1}, "Vehicle Dealer / Stable", 400),
        Recipe("2-Horse Chariot", {"Seasoned Hardwood": 1, "Tanned Leather": 1}, "Vehicle Dealer / Stable", 700),
        Recipe("4-Horse Chariot", {"Iron": 1, "Seasoned Hardwood": 1, "Tanned Leather": 1}, "Vehicle Dealer / Stable", 1600),
        Recipe("Camel", {"Purified Water": 15, "Grain": 10, "Tanned Leather": 1}, "Vehicle Dealer / Stable", 150),
        Recipe("Horse", {"Purified Water": 20, "Grain": 15, "Tanned Leather": 1}, "Vehicle Dealer / Stable", 200),
        # Other stores
        Recipe("Upgraded Tools", {"Lumber": 1, "Bronze": 1}, "Mining/Farming Equipment Store", 130),
        Recipe("Property Upgrade", {"Cut Stone": 1, "Fired Brick": 1, "Lumber": 1}, "Home Improvement Store", 50),
        # Tavern food. Every tier uses the same recipe -- Research changes the
        # Sustenance window and price, never the inputs (Research tab).
        #
        # 3 Grain + 2 Water, up from 1 + 1 (designer decision, 2026-08-15). At
        # one of each, a Meal turned 3 denari of input into a base price of 10
        # and, being the fastest thing in the game to make, earned 23/hr against
        # 5-12/hr for the refining chain -- the most profitable good in the world
        # was bread. The heavier recipe also gives farms a real customer.
        *[
            Recipe(_m.name, {"Grain": 2, "Purified Water": 1}, "Tavern / Inn", _m.price)
            for _m in MEALS.values()
        ],
    ]
}

# Crafting throughput. The spreadsheet gives per-hour rates only for extraction and
# refining; final assembly has no stated rate. Stated assumption, flagged for review:
# a final good takes the same worker-hour budget as one refined unit (15/hr base).
CRAFT_BASE_RATE_HR = 15.0            # superseded by the curve below; kept greppable

# PRODUCTION TIME SCALES WITH VALUE (designer decision, 2026-08-15).
#
# A flat 15 units/hour for everything meant a Blacksmith produced 15 Iron Swords
# an hour -- 16,575 denari of output per worker-hour against a 24 denari wage,
# roughly 700x anything else in the economy. One Weaponsmith out-earned the rest
# of the world combined.
#
# Time per unit is now a power law on base price, calibrated to two anchors the
# designer set: a Meal (base 10) takes 15 minutes, an Iron Sword (base 650)
# takes 12 hours. That gives an exponent of ~0.93 -- very nearly proportional to
# value, which is what flattens profit-per-hour across the whole chain.
#
# EXTRACTION IS DELIBERATELY EXCLUDED. Raw resources have no inputs, so under
# this curve they earn less per hour than the state pays for them and a mine
# could not survive on state sales alone. Extraction moves onto the curve in the
# same change as business-to-business trade, not before -- otherwise nothing can
# bootstrap.
# 2026-08-16: divided by 4 (was 0.0296). At the old rate a worker generated less
# VALUE ADDED per hour than any wage in the game could be paid from -- a Refinery
# Worker produced ~18.7/hr against a 37.78 player floor and an 85 NPC wage, so a
# refinery lost money on every worker no matter how well it was run. The 96-hour
# run of 2026-08-16 only looked solvent because `--time-scale 0.2` multiplied
# output 5x while wages accrue per SIMULATED hour, which is exactly the distortion
# section 5 warns that flag creates. Folding a 4x into the coefficient makes the
# economy close at time-scale 1.0, so the flag goes back to being a test tool and
# the numbers in the docs describe the real world again.
CRAFT_TIME_COEFFICIENT = 0.0074
CRAFT_TIME_EXPONENT = 0.927


# WHO A GOOD IS FOR (designer decision, 2026-08-15).
#
# INTERMEDIATE goods -- ore, grain, hide, bronze, iron -- are feedstock. They
# move business to business: a mine sells ore to a refinery, a refinery sells
# metal to a weaponsmith. A person has no use for a lump of Tin Ore, and letting
# them buy one is why agents spent the last run purchasing Grain they could not
# cook and selling it back at a 76% loss.
#
# FINAL goods -- weapons, armour, meals, vehicles, tools, property upgrades --
# are what a person walks into a shop and buys.
INTERMEDIATE_GOODS: frozenset[str] = frozenset(RAW_RESOURCES) | frozenset(REFINED_RESOURCES)
# FINAL_GOODS is derived once ALL_ITEMS exists, further down this file.


def is_intermediate(item: str) -> bool:
    return item in INTERMEDIATE_GOODS


def production_hours(item: str) -> float:
    """Worker-hours to make one unit."""
    return CRAFT_TIME_COEFFICIENT * base_price(item) ** CRAFT_TIME_EXPONENT


def production_rate_hr(item: str) -> float:
    """Units one Novice worker makes per hour, before skill and crowding."""
    if item in RAW_RESOURCES:
        return RESOURCES[item].base_rate_hr        # extraction, unchanged
    return 1.0 / production_hours(item)

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


# Founding costs HALVED from the spreadsheet's figures (designer decision,
# 2026-08-15). In the first 72-hour run only one agent in twelve managed to
# found anything, on its fifth attempt at simulated hour 60 of 72 -- the
# entry price was absorbing the whole run. Halving it is meant to move
# ownership into the first day so the run can observe what owners DO.
BUSINESS_TYPES: dict[str, BusinessType] = {
    b.name: b
    for b in [
        BusinessType(
            "Mining Operation", 175, None, True, True, ("Laborer", "Miner"),
            ("Wood", "Stone", "Clay", "Copper Ore", "Tin Ore", "Iron Ore", "Hardwood"),
        ),
        BusinessType(
            "Farm", 150, None, True, True, ("Farmhand", "Laborer"),
            ("Dirty Water", "Wheat", "Hide"),  # Wool removed with the resource
        ),
        BusinessType(
            "Refinery", 450, None, True, True, ("Refinery Worker",),
            ("Purified Water", "Grain", "Lumber", "Seasoned Hardwood", "Cut Stone",
             "Fired Brick", "Charcoal", "Tanned Leather", "Bronze", "Iron"),
        ),
        # The General Store is REMOVED (designer decision, 2026-08-15). It
        # produced nothing and therefore retailed everything -- it is how agents
        # were buying ore and wheat over a counter. Every finished good now has
        # a shop that actually makes it: meals at a Tavern, weapons at the
        # Weaponsmith, vehicles at the Stable, tools at the Equipment Store,
        # upgrades at Home Improvement.
        BusinessType(
            "Home Improvement Store", 250, STORE_MAX_EMPLOYEES, True, True, ("Store Clerk",),
            ("Property Upgrade",),
        ),
        BusinessType(
            "Mining/Farming Equipment Store", 275, STORE_MAX_EMPLOYEES, True, True, ("Store Clerk",),
            ("Upgraded Tools",),
        ),
        BusinessType(
            "Weaponsmith / Armory", 350, STORE_MAX_EMPLOYEES, True, True, ("Blacksmith",),
            tuple(n for n, r in CRAFTING_RECIPES.items() if r.produced_at == "Weaponsmith / Armory"),
        ),
        BusinessType(
            "Vehicle Dealer / Stable", 300, STORE_MAX_EMPLOYEES, True, True, ("Stablehand", "Store Clerk"),
            tuple(n for n, r in CRAFTING_RECIPES.items() if r.produced_at == "Vehicle Dealer / Stable"),
        ),
        BusinessType(
            "Tavern / Inn", 200, STORE_MAX_EMPLOYEES, True, True, ("Store Clerk",),
            tuple(MEALS),
        ),
        BusinessType("Private Security Contractor", 500, None, True, False, ()),
        BusinessType("Insurance Brokerage", 750, 0, False, False, ()),
    ]
}

# ---------------------------------------------------------------------------
# Wages tab
# ---------------------------------------------------------------------------

# SMART_WAGES is the SOURCE and NPC hires are priced off it -- the derivation
# used to run the other way (2026-08-16). It was inverted because the two
# numbers need to move independently: player floors are calibrated against
# GOVERNMENT_WAGE_RANGE and against what a worker actually produces, while the
# NPC premium is a separate question about how much a business pays for a hire
# that is always on shift. With NPC_WAGES as the source, cutting an NPC wage
# dragged the player floor down with it -- taking a Refinery Worker's floor from
# 37.78 to 17.78, below the state's own 25.00, so no agent would ever have taken
# a player refinery job. These values are unchanged; only the direction is.
SMART_WAGES: dict[str, float] = {
    "Laborer": 20.0,
    "Miner": 28.888888888888889,
    "Farmhand": 22.222222222222221,
    "Refinery Worker": 37.777777777777779,
    "Store Clerk": 17.777777777777779,
    "Blacksmith": 35.555555555555557,
    "Stablehand": 20.0,
    "Researcher": 33.333333333333336,
}

# An NPC costs this much more than the player floor. Cut from 2.25 to 1.50 on
# 2026-08-16: at 2.25 an NPC Refinery Worker cost 85/hr against the 75.6/hr of
# value its labour created, so the ONE role most businesses need was the one
# role that could never pay for itself, and a thin agent population left owners
# with no alternative. At 1.50 every role clears its own wage -- Refinery Worker
# only just, at 1.33x, and the rest between 2.8x and 5x -- while an NPC still
# costs half again what an agent employee does, so a real hire stays the better
# deal whenever one is available.
NPC_WAGE_MULTIPLIER = 1.50
NPC_WAGES: dict[str, float] = {r: w * NPC_WAGE_MULTIPLIER for r, w in SMART_WAGES.items()}
WAGE_FLOORS = {r: w * MIN_WAGE_PCT_OF_SMART for r, w in SMART_WAGES.items()}

# What the STATE pays (designer decision, 2026-08-14). Deliberately a narrow
# band, and deliberately separate from SMART_WAGES -- which still sets the
# reference rate and the legal floor for player employers, and still prices NPC
# hires. The state used to pay 17.78-37.78, so a Refinery Worker could out-earn
# most ventures by standing still; compressing it leaves the top end of the
# labour market for players to compete over.
GOVERNMENT_WAGE_RANGE = (15.0, 25.0)


def _government_scale() -> dict[str, float]:
    """Linearly rescale the smart wages into the state's band, order intact."""
    lo_pay, hi_pay = GOVERNMENT_WAGE_RANGE
    lo, hi = min(SMART_WAGES.values()), max(SMART_WAGES.values())
    span = hi - lo
    return {
        role: round(lo_pay + (0.0 if span == 0 else (w - lo) / span) * (hi_pay - lo_pay), 2)
        for role, w in SMART_WAGES.items()
    }


GOVERNMENT_WAGES: dict[str, float] = _government_scale()

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
for _res in ("Dirty Water", "Wheat", "Hide", "Wool"):
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
    "Farm": ("Wheat", 0.5),
    "Refinery": ("Charcoal", 0.5),
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
    SITE_BASE_PLOTS,
    STORE_BASE_PLOTS,
    STRUCTURE_PLOTS,
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
    1: {"Cut Stone": 1, "Lumber": 1},
    2: {"Cut Stone": 1, "Lumber": 1, "Bronze": 1},
    3: {"Cut Stone": 1, "Iron": 1, "Lumber": 1},
}
STORAGE_TIER_INPUTS: dict[int, dict[str, int]] = {
    1: {"Cut Stone": 1, "Fired Brick": 1},
    2: {"Cut Stone": 1, "Fired Brick": 1, "Lumber": 1},
    3: {"Cut Stone": 1, "Fired Brick": 1, "Iron": 1},
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

# ---------------------------------------------------------------------------
# LAND (2026-08-19)
# ---------------------------------------------------------------------------
#
# Land is the scarce thing. Before this, plots were a number on a mine and every
# other business sat on ground that returned 10**6 free plots -- so cash was the
# only constraint on growth, and there was no reason to care WHERE anything was.
# Now a plot is an owned, tradeable asset, and headcount is a property of land
# rather than of the balance sheet.
#
# THE SHAPE: a site's first `STRUCTURE_PLOTS` are the building itself, worked by
# the owner. Every developed plot beyond that is one employee's place to stand.
# So hiring is an act of construction, not of recruitment, and an owner who
# wants a bigger crew has to go and buy ground for them.

# What the world sells raw, unimproved land for. Agents may resell at any price
# they can get -- this is the floor the market forms around, not a fixed value.
LAND_BASE_PRICE = 100.0

# STRUCTURE_PLOTS, SITE_BASE_PLOTS and STORE_BASE_PLOTS are geography and live
# in world_map.py; they are re-exported below with the rest of it.

# Turning raw land into usable ground. Takes time OR money, never neither.
DEVELOPMENT_COST = 75.0
DEVELOPMENT_HOURS = 1.0
# Paying to skip the wait. A flat multiple of the standard cost, so one number
# drives both routes and they cannot drift apart as the scaling compounds.
DEVELOPMENT_INSTANT_MULTIPLIER = 2.0
# Each plot past the starter costs half again as much, and takes half again as
# long, as the one before it. Compounding is what stops a rich agent simply
# buying the whole valley: the tenth plot costs 1,922 and takes 25 hours.
DEVELOPMENT_SCALING = 1.5

# Stores hold rather than make, so their land IS their warehouse.
STORE_STORAGE_PER_PLOT = 100

# Production sites grow UPWARD instead. A taller barn stores more without taking
# more ground, which is what keeps a farm's land budget spent on people.
#
# BASE STORAGE IS THE STARTUP COST. A flat 240 for everything said a farm and a
# refinery are the same building, and they are not: the startup cost is already
# this economy's own statement of how substantial a thing is, so reusing it
# needs no second table to keep in step. A refinery buffers two input streams
# AND an output where a farm buffers one output, and at 450 against 150 it now
# holds three times as much.
#
# Note this SHRINKS a farm, from 240 to 150 -- at 72 Wheat an hour that is a
# full yard in 2h05m rather than 3h20m. Deliberate: the pressure to move goods
# is the reason carts and couriers exist at all.
STORAGE_PER_STARTUP_DENARI = 1.0
# Each storehouse tier adds half the base again, so the ratio between a farm and
# a refinery survives being upgraded. A flat increment would quietly compress
# them together at the top.
STORAGE_TIER_FRACTION = 0.5
STORAGE_UPGRADE_COST = 150.0
STORAGE_UPGRADE_SCALING = 1.5
MAX_STORAGE_TIER = 6

# Only for a business whose type carries no startup cost -- the state's own.
FALLBACK_BASE_STORAGE = 240

SITE_STORAGE_PER_PLOT = 30      # legacy: pre-land-system saves only
SITE_EXPANSION_COST = 250.0     # legacy: superseded by buy_land + develop_plot
EXTRACTION_BUSINESS_TYPES = ("Mining Operation", "Farm")

# Business types whose land is warehouse rather than workshop.
STORE_BUSINESS_TYPES = (
    "Home Improvement Store", "Mining/Farming Equipment Store",
    "Weaponsmith / Armory", "Vehicle Dealer / Stable", "Tavern / Inn",
    "Private Security Contractor", "Insurance Brokerage",
)


def development_cost(existing_plots: int) -> float:
    """What the next plot costs to develop, given how many a site already has.

    Scaling is counted from the STARTER size, so the first expansion past a new
    site costs the base rate. An owner who never expands never meets the curve.
    """
    steps = max(existing_plots - SITE_BASE_PLOTS, 0)
    return round(DEVELOPMENT_COST * (DEVELOPMENT_SCALING ** steps), 2)


def development_hours(existing_plots: int) -> float:
    steps = max(existing_plots - SITE_BASE_PLOTS, 0)
    return round(DEVELOPMENT_HOURS * (DEVELOPMENT_SCALING ** steps), 3)


def storage_upgrade_cost(tier: int) -> float:
    return round(STORAGE_UPGRADE_COST * (STORAGE_UPGRADE_SCALING ** tier), 2)

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

# The roster pins a reasoning effort per model, and it is part of the experiment
# -- it must actually reach the API. Measured 2026-08-14, one real decision each:
# DeepSeek default 69.6s vs 21.0s at "low"; Grok default 5.9s vs 4.0s at
# "minimal". Sending nothing means every model silently runs at its provider
# default, which matches the spec for none of them.
EFFORT_BY_MODEL: dict[str, str] = {
    s.openrouter_id: s.reasoning_effort
    for s in MODEL_ROSTER if s.reasoning_effort
}

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

# Everything that is not feedstock is something a person buys. Derived here
# rather than beside INTERMEDIATE_GOODS because ALL_ITEMS only exists by now.
FINAL_GOODS: frozenset[str] = frozenset(ALL_ITEMS) - INTERMEDIATE_GOODS
