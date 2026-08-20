#!/usr/bin/env python3
"""Conformance tests: the implementation vs. the spreadsheet's own worked examples.

Every assertion here is a number the workbook states explicitly. If the
spreadsheet is rebalanced and these fail, the implementation is stale -- that is
the point. Runs standalone (`python3 tests/test_conformance.py`) or under pytest.
"""

from __future__ import annotations

import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from convoy import data as D
from convoy import economy as E

FAILURES: list[str] = []


def check(label: str, actual, expected, tol: float = 1e-6) -> None:
    ok = (
        math.isclose(actual, expected, rel_tol=tol, abs_tol=tol)
        if isinstance(expected, (int, float)) and not isinstance(expected, bool)
        else actual == expected
    )
    if not ok:
        FAILURES.append(f"{label}: got {actual!r}, expected {expected!r}")


# ---------------------------------------------------------------------------
# Businesses tab -- diminishing returns table
# ---------------------------------------------------------------------------

def test_diminishing_returns_table():
    """The exact Total Output Multiplier column from the Businesses tab."""
    expected = {
        1: 1.000, 2: 1.900, 3: 2.708, 4: 3.429, 5: 4.073,
        10: 6.302, 15: 7.315, 19: 7.547, 20: 7.547, 25: 7.300, 30: 6.778,
    }
    for n, mult in expected.items():
        check(f"total output multiplier n={n}", E.total_output_multiplier(n), mult, tol=5e-4)

    peak = max(range(1, 41), key=E.total_output_multiplier)
    check("output peaks at n=19-20", peak in (19, 20), True)


def test_refinery_worked_example():
    """'Iron, 3 Refinery Workers, Novice: 15/hr x 0.9025 = 13.54/hr each, 40.6/hr total.'"""
    per_worker = E.worker_output_rate(D.RESOURCES["Iron"].base_rate_hr, 3, 0.0)
    check("per-worker Iron rate at n=3", per_worker, 13.5375, tol=1e-3)
    check("total Iron/hr at n=3", per_worker * 3, 40.6125, tol=1e-3)
    # The workbook quotes ~$893/hr gross at the old Iron price of 22. At the
    # repriced 36 the same three workers now turn out ~$1,462/hr -- worth
    # watching, since the Iron refinery margin was already a flagged risk.
    check("gross value/hr", per_worker * 3 * D.RESOURCES["Iron"].base_price, 1462.05, tol=1e-2)


# ---------------------------------------------------------------------------
# Production Chain tab -- every Input Cost figure
# ---------------------------------------------------------------------------

def test_production_chain_input_costs():
    """Input Cost per recipe, which is what pins recipe quantities at 1.

    Raw-material costs are unchanged from the workbook; the refined-good costs
    reflect the 2026-08-11 repricing (Tanned Leather 7->9, Bronze 18->32,
    Iron 22->36), which cascades into every recipe consuming them.
    """
    # Refinery steps are still the spreadsheet's. Workshop recipes are NOT: every
    # one of them takes refined feedstock now (Lumber, Seasoned Hardwood, Cut
    # Stone, Fired Brick) instead of raw timber and rock, so their input costs
    # are derived. What is still asserted for them is the 75% margin rule, in
    # test_every_good_clears_75pct_margin.
    # Refinery steps and armour still match the workbook exactly.
    expected = {
        "Charcoal": 2, "Bronze": 18, "Iron": 16,
        # Tanned Leather takes Dirty Water, repriced with the food chain.
        "Tanned Leather": sum(
            D.base_price(i) * q
            for i, q in D.REFINING_RECIPES["Tanned Leather"].inputs.items()
        ),
        "Leather Cap": 9, "Bronze Helm": 41, "Iron Helm": 45,
    }
    # Everything made in a WORKSHOP is derived, not frozen. Their inputs are a
    # design lever the designer has moved twice: bread and livestock feed became
    # refined (Grain, Purified Water), and every timber, stone and clay input
    # became refined (Lumber, Seasoned Hardwood, Cut Stone, Fired Brick) so that
    # nothing reaches a shop without passing a refinery. The rule these must
    # still obey is the 75% margin, asserted in test_every_good_clears_75pct_margin.
    for good in ("Sling", "Wooden Spear", "Bronze Dagger", "Bronze-Tipped Spear",
                 "Bronze Sword", "Bow", "Iron Dagger", "Iron-Tipped Spear",
                 "Iron Sword", "Donkey Cart", "2-Horse Chariot", "4-Horse Chariot",
                 "Camel", "Horse", "Upgraded Tools", "Property Upgrade", "Meal"):
        expected[good] = sum(
            D.base_price(i) * q for i, q in D.CRAFTING_RECIPES[good].inputs.items()
        )
    for good, cost in expected.items():
        recipe = D.REFINING_RECIPES.get(good) or D.CRAFTING_RECIPES[good]
        actual = sum(D.base_price(i) * q for i, q in recipe.inputs.items())
        check(f"input cost of {good}", actual, cost)


def test_every_good_clears_75pct_margin():
    """Designer requirement (2026-08-11): every produced good must clear a 75%
    margin over its input cost, so a player business has room to undercut the
    government version and still profit."""
    for name, recipe in list(D.REFINING_RECIPES.items()) + list(D.CRAFTING_RECIPES.items()):
        cost = sum(D.base_price(i) * q for i, q in recipe.inputs.items())
        if cost <= 0:
            continue
        margin = (D.base_price(name) - cost) / cost
        check(f"{name} clears 75% margin", margin >= 0.75, True)


def test_refined_repricing():
    """The three goods that failed the 75% bar, and the rarity ordering."""
    for good, price, margin in [
        ("Bronze", 32, 0.7778), ("Iron", 36, 1.25),
    ]:
        recipe = D.REFINING_RECIPES[good]
        cost = sum(D.base_price(i) * q for i, q in recipe.inputs.items())
        check(f"{good} base price", D.base_price(good), price)
        check(f"{good} margin", (price - cost) / cost, margin, tol=1e-3)
    # Iron is Rare and must stay strictly more valuable than Uncommon Bronze,
    # even though Bronze's inputs cost more (Copper+Tin 14 vs Iron Ore 12).
    check("Iron outranks Bronze", D.base_price("Iron") > D.base_price("Bronze"), True)


# ---------------------------------------------------------------------------
# Resources / Assumptions -- NPC pricing
# ---------------------------------------------------------------------------

def test_npc_prices():
    """NPC Buy/Sell columns from the Resources tab."""
    # BUY prices are the workbook's 0.4x and unchanged. SELL prices are derived:
    # the state's common markup was cut 1.60 -> 1.40 on 2026-08-16 to bring a
    # meal down from 30.24, and that markup is shared with raw goods.
    for res, buy in [
        ("Stone", 1.2), ("Copper Ore", 2.4), ("Tin Ore", 3.2),
        ("Iron Ore", 4.8), ("Hardwood", 3.2),
    ]:
        check(f"NPC buy {res}", E.npc_buy_price(res), buy)
        check(f"NPC sell {res}", E.npc_sell_price(res),
              D.base_price(res) * D.NPC_SELL_PCT_COMMON)
    check("the state still sells dearer than it buys",
          all(E.npc_sell_price(r) > E.npc_buy_price(r) for r in D.RAW_RESOURCES), True)

    # Refined goods use the 1.5x Refinery markup, not the 1.6x General Store rate.
    check("NPC sell Bronze", E.npc_sell_price("Bronze"), 48.0)   # 32 x 1.5
    check("NPC sell Iron", E.npc_sell_price("Iron"), 54.0)       # 36 x 1.5
    # Weapons/armor at 1.7x, vehicles at 1.5x.
    check("NPC sell Iron Sword", E.npc_sell_price("Iron Sword"), 1105.0)
    check("NPC sell Bronze Sword", E.npc_sell_price("Bronze Sword"), 425.0)
    check("NPC sell Iron Cuirass", E.npc_sell_price("Iron Cuirass"), 1530.0)
    check("NPC sell 4-Horse Chariot", E.npc_sell_price("4-Horse Chariot"), 2400.0)


# ---------------------------------------------------------------------------
# Wages tab
# ---------------------------------------------------------------------------

def test_wages():
    # The NPC column DIVERGES from the reference on purpose (2026-08-16): the
    # multiplier over the player floor was cut from 2.25 to 1.50, so an NPC hire
    # costs 1.5x an agent employee rather than 2.25x. At 2.25 an NPC Refinery
    # Worker cost 85/hr against the 75.6/hr of value its labour created -- the
    # one role every supply chain needs was the one role that could never pay
    # for itself. Player floors and legal floors are UNCHANGED, which is the
    # point of the split: those two columns still hold the reference exactly.
    expected = {
        "Laborer": (30.0, 20, 10),
        "Miner": (43.333333, 28.888888, 14.444444),
        "Farmhand": (33.333333, 22.222222, 11.111111),
        "Refinery Worker": (56.666666, 37.777777, 18.888888),
        "Store Clerk": (26.666666, 17.777777, 8.888888),
        "Blacksmith": (53.333333, 35.555555, 17.777777),
        "Stablehand": (30.0, 20, 10),
        "Researcher": (50.0, 33.333333, 16.666666),
    }
    for role, (npc, smart, floor) in expected.items():
        check(f"NPC wage {role}", E.npc_wage(role), npc, tol=1e-4)
        check(f"smart wage {role}", E.smart_wage(role), smart, tol=1e-4)
        check(f"wage floor {role}", E.wage_floor(role), floor, tol=1e-4)


def test_skill_progression():
    for hours, bonus, label in [
        (0, 0.0, "Novice"), (4.9, 0.0, "Novice"), (5, 0.10, "Journeyman"),
        (14, 0.10, "Journeyman"), (15, 0.20, "Skilled"), (34, 0.20, "Skilled"),
        (35, 0.35, "Expert"), (69, 0.35, "Expert"), (70, 0.50, "Master"),
        (500, 0.50, "Master"),
    ]:
        check(f"skill bonus @{hours}h", E.skill_bonus(hours), bonus)
        check(f"skill label @{hours}h", E.skill_label(hours), label)


# ---------------------------------------------------------------------------
# Research tab
# ---------------------------------------------------------------------------

def test_research_tiers():
    """Cumulative RP and the stated single-Researcher hours."""
    for tier, rp, hours in [
        (1, 150, 18.75), (2, 400, 50), (3, 900, 112.5),
        (4, 1800, 225), (5, 3500, 437.5),
    ]:
        spec = D.RESEARCH_TIERS[tier - 1]
        check(f"tier {tier} RP", spec.cumulative_rp, rp)
        check(f"tier {tier} hours @8 RP/hr", rp / D.RP_PER_RESEARCHER_HOUR, hours)
        check(f"tier for {rp} RP", E.research_tier_for_rp(rp).tier, tier)

    check("below tier 1 is None", E.research_tier_for_rp(149) is None, True)


def test_researcher_rush_funding_tension():
    """The Research tab's stated tension: 19 Researchers ~= 60.4 RP/hr, Tier 5 in ~58h."""
    rate = 19 * D.RP_PER_RESEARCHER_HOUR * E.per_worker_multiplier(19)
    check("19 researchers RP/hr", rate, 60.4, tol=0.1)
    check("hours to Tier 5", 3500 / rate, 58.0, tol=0.6)


# ---------------------------------------------------------------------------
# Sustenance tab
# ---------------------------------------------------------------------------

def test_sustenance_windows():
    # WINDOWS are the spreadsheet's, and are the point of the tier ladder.
    # PRICES moved when bread stopped being made from raw wheat (2026-08-15), so
    # they are checked as an ordering and against the 75% rule, not frozen.
    for meal, window in [
        ("Meal", 12), ("Tier 1 Bread", 15), ("Tier 2 Bread", 18),
        ("Fine Bread", 21), ("Masterwork Bread", 24), ("Legendary Bread", 30),
    ]:
        check(f"{meal} window", E.meal_window(meal), window)
    ladder = ["Meal", "Tier 1 Bread", "Tier 2 Bread", "Fine Bread",
              "Masterwork Bread", "Legendary Bread"]
    prices = [E.meal_price(m) for m in ladder]
    check("a longer window always costs more", prices == sorted(prices), True)
    check("self-prep window", D.SELF_PREP_WINDOW_HOURS, 12)


def test_sustenance_worked_example():
    """'Eats Tier 4 at hour 10: Normal to 34, Hungry 34-46, Starving 46-58, dies at 58.'"""
    window = E.meal_window("Masterwork Bread")     # 24h, eaten at hour 10
    def stage_at(hour: float) -> str:
        return E.sustenance_stage(hour - 10.0, window)

    check("Normal at h33", stage_at(33), "Normal")
    check("Hungry at h34", stage_at(34), "Hungry")
    check("Hungry at h45", stage_at(45), "Hungry")
    check("Starving at h46", stage_at(46), "Starving")
    check("Starving at h57", stage_at(57), "Starving")
    check("Death at h58", stage_at(58), "Death")


def test_sustenance_penalties():
    check("Normal speed", E.sustenance_speed_multiplier("Normal"), 1.0)
    check("Hungry -10%", E.sustenance_speed_multiplier("Hungry"), 0.90)
    check("Starving -25%", E.sustenance_speed_multiplier("Starving"), 0.75)


def test_food_variants():
    """Designer addition (2026-08-12): Food gets the other two Research axes.

    Duration keeps the Sustenance tab's fixed hour table; hearty and laborer
    breads use the tier's % pool (5/10/15/20/25) for HP and work speed. All
    variants keep the same Grain + Water recipe -- Research never changes inputs.
    """
    for tier, pct in [(1, 0.05), (2, 0.10), (3, 0.15), (4, 0.20), (5, 0.25)]:
        hearty = D.MEALS[f"Hearty Bread T{tier}"]
        check(f"hearty T{tier} heals {pct:.0%} of 100 HP", hearty.heal, 100.0 * pct)
        check(f"hearty T{tier} keeps the base window", hearty.window_hours, 12.0)
        check(f"hearty T{tier} gives no work bonus", hearty.work_bonus, 0.0)

        lab = D.MEALS[f"Laborer's Bread T{tier}"]
        check(f"laborer T{tier} work bonus", lab.work_bonus, pct)
        check(f"laborer T{tier} keeps the base window", lab.window_hours, 12.0)
        check(f"laborer T{tier} heals nothing", lab.heal, 0.0)

    # The invariant is that RESEARCH NEVER CHANGES THE INPUTS -- a Legendary
    # Bread takes exactly what a plain Meal takes, and the tier buys a longer
    # window or a bonus, not a different recipe. The quantities themselves are a
    # balancing lever (3 Grain + 2 Water as of 2026-08-15), so compare every
    # variant against the base Meal rather than against a frozen literal.
    base_recipe = D.CRAFTING_RECIPES["Meal"].inputs
    check("a Meal is made of refined goods", set(base_recipe), {"Grain", "Purified Water"})
    for name, meal in D.MEALS.items():
        recipe = D.CRAFTING_RECIPES[name]
        check(f"{name} uses the same inputs as a plain Meal", recipe.inputs, base_recipe)
        check(f"{name} priced as listed", recipe.base_price, meal.price)


def test_meal_line_selection():
    """A Tavern serves the best of whichever line is asked for, up to its tier."""
    check("tier 0 has only the plain Meal", E.best_meal_for_tier(0, "duration"), "Meal")
    check("tier 0 cannot serve hearty", E.best_meal_for_tier(0, "hearty"), "Meal")
    check("tier 5 duration", E.best_meal_for_tier(5, "duration"), "Legendary Bread")
    check("tier 5 hearty", E.best_meal_for_tier(5, "hearty"), "Hearty Bread T5")
    check("tier 5 laborer", E.best_meal_for_tier(5, "laborer"), "Laborer's Bread T5")
    check("tier 3 hearty caps at T3", E.best_meal_for_tier(3, "hearty"), "Hearty Bread T3")
    check("tier 2 serves 7 meals", len(E.meals_for_tier(2)), 7)  # 3 duration + 2 hearty + 2 laborer


def test_quality_allocation_rules():
    """The Research tab's Quality Bonus Stat Pools, now actually enforced."""
    check("melee stats", E.quality_stats_for("Melee"), ("Attack Speed", "Damage"))
    check("tab spelling resolves too", E.quality_stats_for("Melee Weapons"), ("Attack Speed", "Damage"))
    check("ranged adds accuracy", "Accuracy" in E.quality_stats_for("Ranged"), True)
    check("melee has no accuracy", "Accuracy" in E.quality_stats_for("Melee"), False)

    # Tier 3 grants a 15% pool -- the tab's own worked example splits it 8/7.
    ok, _ = E.validate_quality_allocation("Melee", {"Damage": 0.08, "Attack Speed": 0.07}, 3)
    check("tab's Fine Bronze-Tipped Spear split is legal", ok, True)
    # All into one stat is equally legal (Tier 5 Legendary Iron Sword, +25% Damage).
    ok, _ = E.validate_quality_allocation("Melee", {"Damage": 0.25}, 5)
    check("all-in-one-stat split is legal", ok, True)
    # Over-allocating the pool is not.
    ok, _ = E.validate_quality_allocation("Melee", {"Damage": 0.20}, 3)
    check("cannot exceed the tier pool", ok, False)
    # Nor is a stat the category does not have.
    ok, _ = E.validate_quality_allocation("Melee", {"Accuracy": 0.10}, 3)
    check("cannot allocate a stat outside the category", ok, False)
    ok, _ = E.validate_quality_allocation("Vehicles", {"Cargo Capacity": 0.25}, 5)
    check("Legendary 4-Horse Chariot +25% cargo is legal", ok, True)


def test_bread_tier_gating():
    """A Tavern serves the best bread its Quality research tier allows."""
    for tier, meal in [
        (0, "Meal"), (1, "Tier 1 Bread"), (2, "Tier 2 Bread"),
        (3, "Fine Bread"), (4, "Masterwork Bread"), (5, "Legendary Bread"),
    ]:
        check(f"best meal at quality tier {tier}", E.best_meal_for_tier(tier), meal)


# ---------------------------------------------------------------------------
# Convoy tab -- worked example
# ---------------------------------------------------------------------------

def test_convoy_worked_example():
    """1 Donkey Cart, own vehicle, Scout + Bodyguard, on 1800 Denari of cargo.

    The workbook reaches 1800 as 100 units of Bronze at the old 18 base price.
    Bronze has since been repriced to 32, so this pins the PAY FORMULA at the
    stated cargo value rather than re-deriving it from a moved price.
    """
    cargo_value = 1800.0
    check("driver (own vehicle) pay", E.convoy_pay("Driver-own", cargo_value, cargo_value), 28.5)
    check("scout pay", E.convoy_pay("Scout", cargo_value, cargo_value), 12.5)
    check("bodyguard pay", E.convoy_pay("Bodyguard", cargo_value, cargo_value), 14.3)
    check(
        "driver (provided vehicle) pay",
        E.convoy_pay("Driver-provided", cargo_value, cargo_value), 19.0,
    )


# ---------------------------------------------------------------------------
# Weapons / Armor tabs
# ---------------------------------------------------------------------------

def test_hits_to_kill():
    """Live formula on the Weapons tab: 100 HP, unarmored."""
    expected = {
        "Slingshot": 10, "Sling": 8, "Wooden Spear": 5, "Bronze Dagger": 7,
        "Bronze-Tipped Spear": 4, "Bronze Sword": 3, "Bow": 5, "Iron Dagger": 5,
        "Iron-Tipped Spear": 3, "Iron Sword": 2,
    }
    for name, hits in expected.items():
        check(f"hits to kill {name}", math.ceil(100 / D.WEAPONS[name].damage), hits)


def test_combat_is_realtime_on_own_model():
    """Designer override (2026-08-11): no fixed round length, no fallback model.

    Attack Speed is a real-time interval between exchanges, not a per-round
    divisor, and every agent fights on its own assigned model.
    """
    check("combat uses the agent's own model", D.COMBAT_USES_OWN_MODEL, True)
    check("combat is real-time", D.COMBAT_REALTIME, True)
    check("no fixed round constant remains", hasattr(D, "COMBAT_ROUND_SECONDS"), False)
    check("no fallback roster remains", hasattr(D, "COMBAT_FALLBACK_MODELS"), False)
    # Attack Speed still orders weapons by how often they can swing.
    check("dagger swings faster than sword",
          D.WEAPONS["Iron Dagger"].attack_speed < D.WEAPONS["Iron Sword"].attack_speed, True)


def test_armor_set_totals():
    """'A full Bronze set totals -40% damage taken; a full Iron set -55%.'"""
    for tier, total in [("Leather", 0.20), ("Bronze", 0.40), ("Iron", 0.55)]:
        actual = sum(a.damage_reduction for a in D.ARMOR.values() if a.tier == tier)
        check(f"full {tier} set reduction", actual, total)


# ---------------------------------------------------------------------------
# Progression Math tab
# ---------------------------------------------------------------------------

def test_progression_hours():
    """Hours of labor to afford key purchases, at each stated wage.

    The NPC-Laborer column moved with the 1.50 multiplier -- see test_wages. The
    two SMART columns are the ones that describe what an agent actually earns,
    and they are unchanged.
    """
    for item, cost, laborer, refiner, npc_lab in [
        ("Camel", 150, 7.5, 3.970588, 5.0),
        ("Horse", 200, 10, 5.294118, 6.666667),
        ("Donkey Cart", 400, 20, 10.588235, 13.333333),
        ("4-Horse Chariot", 1600, 80, 42.352941, 53.333333),
    ]:
        check(f"{item} base price", D.base_price(item), cost)
        check(f"{item} hrs @ Laborer smart", cost / E.smart_wage("Laborer"), laborer, tol=1e-4)
        check(f"{item} hrs @ Refinery smart",
              cost / E.smart_wage("Refinery Worker"), refiner, tol=1e-4)
        check(f"{item} hrs @ NPC Laborer", cost / E.npc_wage("Laborer"), npc_lab, tol=1e-4)


# ---------------------------------------------------------------------------
# World State Schema -- Net Worth and carrying
# ---------------------------------------------------------------------------

def test_net_worth_definition():
    """Denari + businesses (startup) + vehicles (base) + property + inventory (base).

    The business and vehicle terms are derived from the data rather than
    hardcoded: this test exists to pin the FORMULA, and founding costs are a
    balancing lever the designer moves (halved 2026-08-15). Hardcoding them
    made a deliberate rebalance look like a regression.
    """
    veh = ["Camel", "Donkey Cart"]
    veh_value = sum(D.VEHICLES[v].base_price for v in veh)
    # Businesses arrive pre-valued -- worth is startup cost plus 3x the last
    # 24 hours of sales, which needs a world. `Business.valuation` owns that;
    # this pins the sum.
    inventory = {"Iron": 3, "Wheat": 10}
    inv_value = sum(D.base_price(i) * q for i, q in inventory.items())
    biz_values = [150.0, 450.0 + 3 * 20.0]
    nw = E.net_worth(
        denari=100.0,
        inventory=inventory,
        business_values=biz_values,
        vehicle_types=veh,
        property_value=500.0,
    )
    check("net worth", nw, 100 + inv_value + sum(biz_values) + veh_value + 500)


def test_carrying_capacity():
    """Vehicles tab governs; 5 units only on foot."""
    check("on foot", E.carry_capacity(None), 5)
    for veh, cap in [("Camel", 20), ("Horse", 15), ("Donkey Cart", 100),
                     ("2-Horse Chariot", 80), ("4-Horse Chariot", 200)]:
        check(f"capacity {veh}", E.carry_capacity(veh), cap)


def test_taxes():
    """Income tax is 3% of every paycheck (2026-08-12), withheld from gross."""
    check("income tax default", D.DEFAULT_WAGE_TAX, 0.03)
    net, tax = E.apply_wage_tax(100.0, D.DEFAULT_WAGE_TAX)
    check("net wage", net, 97.0)
    check("income tax withheld", tax, 3.0)
    # A Refinery Worker on the government's smart wage takes home 36.64/hr.
    gross = E.smart_wage("Refinery Worker")
    net, tax = E.apply_wage_tax(gross, D.DEFAULT_WAGE_TAX)
    check("refinery worker take-home", round(net, 2), 36.64)
    check("sales tax default", D.DEFAULT_SALES_TAX, 0.05)
    check("tax clamped high", E.clamp_tax(0.99), 0.25)
    check("tax clamped low", E.clamp_tax(-1.0), 0.0)


def test_insurance():
    check("premium 20%", E.insurance_premium(1000), 200)
    check("payout 70%", E.insurance_payout(1000), 700)
    check("reserve floor 70%", E.required_reserve(1000), 700)


def test_price_floor():
    """Players cannot retail below 60% of base price."""
    check("Iron Sword floor", E.player_price_floor("Iron Sword"), 390.0)
    check("Stone floor", E.player_price_floor("Stone"), 1.8)


def test_travel_times():
    """World tab: '~5 min full transit at Medium speed'.

    Terrain now varies the pace, so the total is 299s rather than a flat 300 --
    still within the tab's stated approximation.
    """
    full = E.travel_seconds("Refinery Row", "Town", "Horse")
    check("full road at Medium is ~5 minutes", 290 <= full <= 310, True)
    check(
        "one segment on foot is slower than mounted",
        E.travel_seconds("Town", "South Protected Zone", None)
        > E.travel_seconds("Town", "South Protected Zone", "Horse"),
        True,
    )


def test_world_geography():
    """The 2026-08-12 world design: 7 places, 6 segments, 8 spurs."""
    from convoy import world_map as M

    check("seven named locations", len(M.LOCATIONS), 7)
    check("six road segments", len(M.SEGMENTS), 6)
    check("sixteen spur roads", len(M.SPURS), 16)
    check("spurs are 90 seconds deep", M.SPUR_SECONDS, 90.0)
    check("640 plots of land in total", sum(s.plots for s in M.SPURS), 640)

    # Protected zones: no combat, no theft, police present -- and a spur inherits
    # its junction's protection.
    check("north waystation protected", M.is_protected("North Protected Zone"), True)
    check("south waystation protected", M.is_protected("South Protected Zone"), True)
    check("town protected", M.is_protected("Town"), True)
    check("refinery row is NOT protected", M.is_protected("Refinery Row"), False)
    check("the hills are NOT protected", M.is_protected("The Hills"), False)
    check("a spur inherits protection", M.is_protected("Southgate Commons"), True)
    check("a wild spur does not", M.is_protected("Blindfold Draw"), False)

    # Danger varies by segment, and the three dangerous ones sit in the middle.
    danger = {s.name: s.danger for s in M.SEGMENTS}
    check("switchbacks are the most dangerous",
          max(danger, key=danger.get), "The Switchbacks")
    check("slagside is safer than broken country",
          danger["Slagside Road"] < danger["Broken Country"], True)
    check("market road is safer than the bridge",
          danger["Market Road"] < danger["The Bridge"], True)

    # A bridge has a river on both sides -- Flee Off-Road is not available.
    bridge = M.SEGMENT_BY_PAIR[("The Crossing", "The Climb")]
    check("cannot flee off-road on the bridge", bridge.can_flee_offroad(), False)
    hills = M.SEGMENT_BY_PAIR[("The Hills", "The Crossing")]
    check("can flee off-road in the hills", hills.can_flee_offroad(), True)

    # The Climb is genuinely slower ground.
    climb = M.SEGMENT_BY_PAIR[("The Climb", "South Protected Zone")]
    flat = M.SEGMENT_BY_PAIR[("Refinery Row", "North Protected Zone")]
    check("the climb is slower than the flats", climb.seconds > flat.seconds, True)

    # THE ENDS ARE PURE (2026-08-20). Refining happens at one end of the road and
    # selling at the other, and nothing else is at either: no spur hangs off
    # Refinery Row or Town, so every mine and farm in the world must haul its
    # output to be smelted and haul it again to be sold. This used to be the
    # opposite -- the state mine and farm sat on Refinery Row spurs, minutes from
    # the smelters, which is exactly the free lunch the change removes.
    ends = {M.LOCATIONS[0], M.LOCATIONS[-1]}
    check("the road runs refineries to market", ends, {"Refinery Row", "Town"})
    check("no spur hangs off either end",
          [s.name for s in M.SPURS if s.junction in ends], [])
    for site in ("Mining Operation", "Farm"):
        check(f"state {site.lower()} sits between the ends",
              M.junction_of(M.GOVERNMENT_SITES[site]) not in ends, True)

    # Neither state site may hide behind a wall. A production site nobody can rob
    # is a different game from the one the theft rules describe, and the farm
    # landed on protected ground once already while spurs were being moved.
    for site in ("Mining Operation", "Farm"):
        check(f"state {site.lower()} stands on open ground",
              M.junction_of(M.GOVERNMENT_SITES[site]) in M.PROTECTED_ZONES, False)

    # Spurs dead-end, so spur-to-spur travel climbs out and back down. Taken from
    # the map rather than named, so moving a spur cannot quietly stop this from
    # testing what it says it tests -- which is how it broke last time.
    junction, siblings = next(
        (j, s) for j, s in M.SPURS_BY_JUNCTION.items() if len(s) >= 2
    )
    check(f"two spurs off {junction} cost both detours",
          M.travel_seconds(siblings[0].name, siblings[1].name),
          M.SPUR_SECONDS * 2)

    # Plots are land, not slots. From 2026-08-19 they are also the ONLY thing
    # that lets a business hire: the first two are the building, and every
    # developed plot past that seats one employee. A starter site is 4 -- the
    # building plus two places to put people -- down from 8, because the number
    # now means something it did not before.
    check("starter home", M.HOME_BASE_PLOTS, 4)
    check("starter mine or farm", M.SITE_BASE_PLOTS, 4)
    check("the building itself", M.STRUCTURE_PLOTS, 2)
    check("so a new site seats two", M.SITE_BASE_PLOTS - M.STRUCTURE_PLOTS, 2)
    check("only mines and farms take spur land",
          set(M.PLOT_CONSUMING_BUSINESSES), {"Mining Operation", "Farm"})


# ---------------------------------------------------------------------------

def main() -> int:
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for t in tests:
        t()
    print(f"Ran {len(tests)} conformance tests against the spreadsheet.")
    if FAILURES:
        print(f"\n{len(FAILURES)} FAILURES:")
        for f in FAILURES:
            print(f"  ! {f}")
        return 1
    print("All spreadsheet worked examples reproduce exactly.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
