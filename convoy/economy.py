"""Economic formulas: NPC pricing, staffing/output math, wages, taxes, net worth.

Every function here maps to a specific spreadsheet rule and is unit-tested against
the worked examples the workbook provides.
"""

from __future__ import annotations

from . import data as D


# ---------------------------------------------------------------------------
# NPC pricing (Assumptions tab)
# ---------------------------------------------------------------------------

def npc_buy_price(item: str) -> float:
    """What an NPC business pays a player for `item`.

    Trading Post and Refinery both buy at 0.4x base. Manufactured goods have no
    stated NPC buy rate; they fall back to the same raw rate.
    """
    return D.base_price(item) * D.NPC_BUY_PCT_RAW


def npc_sell_price(item: str) -> float:
    """What an NPC business charges a player for `item`.

    Markup depends on which NPC storefront carries it -- weapons and armor at the
    Weaponsmith (1.7x), vehicles at the Stables (1.5x), refined goods at the
    Refinery (1.5x), everything else at the General Store (1.6x).
    """
    price = D.base_price(item)
    if item in D.WEAPONS or item in D.ARMOR:
        return price * D.NPC_SELL_PCT_WEAPONS
    if item in D.VEHICLES:
        return price * D.NPC_SELL_PCT_VEHICLES
    if item in D.RESOURCES and D.RESOURCES[item].refined:
        return price * D.NPC_SELL_PCT_REFINED
    return price * D.NPC_SELL_PCT_COMMON


def player_price_floor(item: str) -> float:
    """Players cannot retail below 60% of base price (anti-undercutting rule)."""
    return D.base_price(item) * D.PLAYER_STORE_FLOOR_PCT


# ---------------------------------------------------------------------------
# Staffing & output (Businesses tab)
# ---------------------------------------------------------------------------

def per_worker_multiplier(headcount: int) -> float:
    """Each additional worker cuts every worker's individual rate by 5%, compounding.

    Per-Worker Rate at n = Base x Skill x 0.95^(n-1).
    """
    if headcount <= 0:
        return 0.0
    return D.WORKER_DECAY_PER_HEAD ** (headcount - 1)


def total_output_multiplier(headcount: int) -> float:
    """n x per-worker rate. Peaks at ~7.547x around n=19-20, then declines."""
    return headcount * per_worker_multiplier(headcount)


def skill_bonus(hours_worked: float) -> float:
    """Speed bonus from cumulative hours at a role name (Wages tab)."""
    bonus = 0.0
    for min_hours, value, _label in D.SKILL_TIERS:
        if hours_worked >= min_hours:
            bonus = value
    return bonus


def skill_label(hours_worked: float) -> str:
    label = "Novice"
    for min_hours, _value, name in D.SKILL_TIERS:
        if hours_worked >= min_hours:
            label = name
    return label


def worker_output_rate(
    base_rate_hr: float,
    headcount: int,
    skill_hours: float,
    efficiency_bonus: float = 0.0,
) -> float:
    """Units per hour produced by ONE worker.

    Skill and Research Efficiency stack additively on top of the base rate; the
    headcount decay multiplies the result (Wages tab: "Stacks additively with
    employee-count bonus and Research's Efficiency bonus").
    """
    additive = 1.0 + skill_bonus(skill_hours) + efficiency_bonus
    return base_rate_hr * additive * per_worker_multiplier(headcount)


def efficiency_bonus(tier: int) -> float:
    """Speed bonus from an ALLOCATED Efficiency tier (0 == none)."""
    return D.RESEARCH_TIERS[tier - 1].efficiency if 1 <= tier <= len(D.RESEARCH_TIERS) else 0.0


def quality_bonus(tier: int) -> float:
    """Stat-bonus pool from an ALLOCATED Quality tier (0 == none)."""
    return D.RESEARCH_TIERS[tier - 1].quality if 1 <= tier <= len(D.RESEARCH_TIERS) else 0.0


def quality_tag(tier: int) -> str | None:
    return D.RESEARCH_TIERS[tier - 1].tag if 1 <= tier <= len(D.RESEARCH_TIERS) else None


def research_tier_for_rp(rp: float) -> D.ResearchTier | None:
    """Highest tier fully paid for by `rp` cumulative Research Points."""
    unlocked = None
    for tier in D.RESEARCH_TIERS:
        if rp >= tier.cumulative_rp:
            unlocked = tier
    return unlocked


# ---------------------------------------------------------------------------
# Wages & taxes
# ---------------------------------------------------------------------------

def wage_floor(role: str) -> float:
    return D.WAGE_FLOORS[role]


def smart_wage(role: str) -> float:
    return D.SMART_WAGES[role]


def government_wage(role: str) -> float:
    """What the state pays. A narrow band, well under the smart wage."""
    return D.GOVERNMENT_WAGES[role]


def npc_wage(role: str) -> float:
    return D.NPC_WAGES[role]


def clamp_tax(rate: float) -> float:
    return max(D.TAX_MIN, min(D.TAX_MAX, rate))


def apply_wage_tax(gross: float, wage_tax: float) -> tuple[float, float]:
    """Split a gross wage into (net to worker, tax to treasury)."""
    tax = gross * clamp_tax(wage_tax)
    return gross - tax, tax


def sales_tax_on(price: float, sales_tax: float) -> float:
    """What the SELLER owes the state on a sale of `price`.

    Incidence changed 2026-08-15: this is a tax on business revenue, not a
    surcharge on the shopper. A buyer pays exactly the marked price -- what you
    see is what you pay -- and the seller keeps the rest after remitting this.
    The workbook does not specify incidence; this is the designer's call.
    """
    return price * clamp_tax(sales_tax)


# ---------------------------------------------------------------------------
# Sustenance (Sustenance tab)
# ---------------------------------------------------------------------------

def sustenance_stage(hours_since_meal: float, window_hours: float) -> str:
    """Normal -> Hungry -> Starving -> Death.

    The meal's window governs how long the agent stays Normal; the escalation
    stages after it are fixed at 12 hours each regardless of meal tier.
    """
    if hours_since_meal < window_hours:
        return "Normal"
    overdue = hours_since_meal - window_hours
    if overdue < D.HUNGRY_STAGE_HOURS:
        return "Hungry"
    if overdue < D.HUNGRY_STAGE_HOURS + D.STARVING_STAGE_HOURS:
        return "Starving"
    return "Death"


def sustenance_speed_multiplier(stage: str) -> float:
    """Applies to production and combat speed only, per the tab's wording."""
    if stage == "Hungry":
        return 1.0 - D.HUNGRY_SPEED_PENALTY
    if stage in ("Starving", "Death"):
        return 1.0 - D.STARVING_SPEED_PENALTY
    return 1.0


def meal_window(meal: str) -> float:
    return D.MEALS[meal].window_hours


def meal_price(meal: str) -> float:
    return D.MEALS[meal].price


def meals_for_tier(quality_tier: int) -> list[D.Meal]:
    """Every variant a Tavern at this Quality research tier can serve."""
    return [m for m in D.MEALS.values() if m.required_tier <= quality_tier]


def best_meal_for_tier(quality_tier: int, prefer: str = "duration") -> str:
    """The best meal of a given line that this Tavern can serve.

    `prefer` picks the axis: 'duration' (longest window), 'hearty' (most HP), or
    'laborer' (biggest production bonus). Falls back to the plain Meal.
    """
    candidates = [m for m in meals_for_tier(quality_tier) if m.line == prefer]
    if not candidates:
        return "Meal"
    key = {
        "duration": lambda m: m.window_hours,
        "hearty": lambda m: m.heal,
        "laborer": lambda m: m.work_bonus,
    }[prefer]
    return max(candidates, key=key).name


def quality_stats_for(category: str) -> tuple[str, ...]:
    """Which stats a Quality tier's pool may be split across (Research tab).

    Accepts either the stat-pool table's category names or the abbreviations the
    tab's examples table uses.
    """
    canonical = D.QUALITY_CATEGORY_ALIASES.get(category, category)
    return D.QUALITY_STAT_POOLS.get(canonical, ())


def validate_quality_allocation(category: str, allocation: dict[str, float],
                                tier: int) -> tuple[bool, str]:
    """A tier grants a bonus POOL; the business splits it across that category's
    available stats, either all into one or divided. This enforces both rules."""
    available = quality_stats_for(category)
    if not available:
        return False, f"unknown category {category!r}"
    for stat in allocation:
        if stat not in available:
            return False, f"{category} cannot allocate into {stat!r}"
    pool = quality_bonus(tier)
    total = sum(allocation.values())
    if total > pool + 1e-9:
        return False, f"allocated {total:.0%} exceeds the tier {tier} pool of {pool:.0%}"
    return True, "ok"


# ---------------------------------------------------------------------------
# Carrying capacity (Vehicles tab governs)
# ---------------------------------------------------------------------------

def site_storage_capacity(plots: int) -> int:
    """How much a worked site can stockpile before production stalls."""
    return int(plots * D.SITE_STORAGE_PER_PLOT)


def carry_capacity(vehicle_type: str | None) -> int:
    if vehicle_type is None:
        return D.ON_FOOT_CAPACITY
    return D.VEHICLES[vehicle_type].cargo_capacity


# ---------------------------------------------------------------------------
# Net Worth -- THE ranking metric (World State Schema tab)
# ---------------------------------------------------------------------------

def inventory_value(inventory: dict[str, int]) -> float:
    return sum(D.base_price(item) * qty for item, qty in inventory.items() if qty)


def net_worth(
    denari: float,
    inventory: dict[str, int],
    business_values: list[float],
    vehicle_types: list[str],
    property_value: float = 0.0,
) -> float:
    """Denari + businesses + vehicles (base price)
    + property (purchase + upgrades) + inventory (base price).

    Businesses arrive already valued, because their worth depends on trade over
    the last 24 hours and this function is deliberately world-free. See
    `Business.valuation`.
    """
    return (
        denari
        + sum(business_values)
        + sum(D.VEHICLES[v].base_price for v in vehicle_types)
        + property_value
        + inventory_value(inventory)
    )


# ---------------------------------------------------------------------------
# Travel (World tab location graph)
# ---------------------------------------------------------------------------

def travel_seconds(origin: str, destination: str, vehicle_type: str | None) -> float:
    """Time from one place to another, terrain and spurs included.

    Slow ground (the Climb's switchbacks) and spur detours are handled by
    world_map; this only applies the vehicle's speed on top.
    """
    from . import world_map as M

    speed = D.VEHICLES[vehicle_type].speed_mult if vehicle_type else D.VEHICLES["On Foot"].speed_mult
    return M.travel_seconds(origin, destination, speed)


# ---------------------------------------------------------------------------
# Convoy pay (Convoy tab)
# ---------------------------------------------------------------------------

def convoy_pay(role: str, vehicle_cargo_value: float, convoy_cargo_value: float) -> float:
    terms = D.CONVOY_PAY[role]
    basis = vehicle_cargo_value if terms["basis"] == "vehicle" else convoy_cargo_value
    return terms["flat"] + basis * terms["commission"]


# ---------------------------------------------------------------------------
# Insurance (Government & Insurance tab)
# ---------------------------------------------------------------------------

def insurance_premium(insured_value: float, rate: float = D.NPC_INSURANCE_PREMIUM_PCT) -> float:
    return insured_value * rate


def insurance_payout(insured_value: float) -> float:
    return insured_value * D.INSURANCE_PAYOUT_PCT


def required_reserve(outstanding_insured_value: float) -> float:
    """A brokerage must hold >= 70% of outstanding insured value to issue new policies."""
    return outstanding_insured_value * D.INSURANCE_RESERVE_PCT
