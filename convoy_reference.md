# Convoy — Bronze & Iron Age Economy Reference

*Flattened text snapshot of `convoy_bronze_age_economy.xlsx`, regenerated 2026-08-12. All values are calculated results at export time, not live formulas. The spreadsheet is the source of truth; this is a searchable copy. Every tab and every non-empty row is included.*

Tabs (19): Read Me First, Master Overview, Assumptions, Resources, Production Chain, Research, Armor, Vehicles, Weapons, Businesses, Wages, Progression Math, Actions, Convoy, Government & Insurance, World State Schema, Combat & Heroes, Agent Scheduling & Diary, Sustenance

---

## Read Me First

How To Use This Workbook
WHAT CONVOY IS:
Convoy is a Mad Max-meets-Silk Road trading and piracy game. In the eventual human-facing version, players
mine and refine raw materials, form convoys to move goods along a single dangerous road connecting Refinery
Row to Town, and can either protect that trade or prey on it. Wealth, politics, crime, and reputation are
all governed by a player-driven economy rather than fixed NPC systems.
WHAT THIS BUILD IS:
This is NOT that game. It's an agent-only economic sandbox with no human players and no 3D rendering.
75 AI agents (15 each across 5 different models, accessed through OpenRouter) live in this Bronze Age
economy for 120 real hours, no time compression, making every decision themselves — mining, trading,
starting businesses, joining or robbing convoys, voting on policy, fighting. Every agent's single goal is
to maximize their own Net Worth by the end of the run — there is no other win condition.
WHY IT EXISTS:
Two purposes. First, validate that the economic rules in this workbook actually produce interesting,
legible behavior BEFORE any visual/Unity work begins on the real game — cheap to fix a wage rate now,
expensive to fix it after building animated environments around it. Second, generate genuine, unscripted
content (daily summaries, eventual video clips) as real marketing material for the future human game.
    GOVERNMENT-owned ones are always fully staffed regardless of real hires. Agents can own multiple
This workbook models the Bronze & Iron Age economy for Convoy, including the agent action list, convoy
system, government/insurance systems, and full world state schema for the agent-only sandbox build.
Simulation runs 120 real hours nonstop, no time compression.
  Actions — the full agent action/tool list, ~94 actions across 17 categories
COLOR KEY:
  Blue text = input cells you can edit (base prices, startup costs, NPC wages, assumption levers, tax rates)
  Black text = formulas that auto-calculate — don't hardcode over these
  Yellow fill = the global assumption levers on the Assumptions tab
    Convoy, Market, Guild, Bounty, Government, World) plus garage/storage upgrade pricing
TAB GUIDE:
  Assumptions — global % markups, wage multipliers, floors, Research RP rate, default 5% tax rates
  Resources — 15 raw + refined resources (Bronze & Iron tiers)
  Production Chain — how raw resources become refined resources become final goods, margins computed live
  Research — business-level speed/quality investment, 5 tiers, material consumption, quality stat pools
  Armor — 9 pieces across Leather/Bronze/Iron tiers, 3 slots each
  Vehicles — 6 vehicles: On Foot, Camel, Horse, Donkey Cart, 2-Horse Chariot, 4-Horse Chariot
  Weapons — 10 weapons with real combat numbers: numeric Damage, Attack Speed, Headshot/Backstab
    multiplier, and a live Hits-to-Kill formula (100 HP baseline, unarmored)
  Businesses — 11 businesses. Every PLAYER-owned one except Insurance Brokerage requires an active worker.
    GOVERNMENT-owned ones are always fully staffed regardless of real hires. Agents can own multiple
    businesses if they can afford startup costs and keep each staffed.
  Wages — 8 roles, NPC/Smart/Floor wages, plus the 5-tier Skill Progression table (speed only)
  Progression Math — hours of labor to afford each item, hours of Researcher employment per tier
  Actions — the full agent action/tool list, ~94 actions across 17 categories
  Convoy — the three convoy roles, government baseline pay formula with a live worked example, posting rules
  Government & Insurance — direct democracy policy catalog (tax-funded infrastructure/police, standalone
    tax nudges, bounty formula with police-witnessed detection), and the three insurance products
  World State Schema — the actual data structure: 10 entity types (Agent, Business, Vehicle, Property,
    Convoy, Market, Guild, Bounty, Government, World) plus garage/storage upgrade pricing
  Combat & Heroes — the zone-based tactical combat resolution mechanic (no hardcoded hit chance), respawn
    rules, and the 5-model hero agent roster
  Master Overview — everything on one page, pulled live from every other tab (longest tabs excluded)
KEY RULES WORTH REMEMBERING:
  Every PLAYER-owned business (except Insurance Brokerage) needs an active worker or produces nothing.
  GOVERNMENT-owned businesses are always staffed by exemption, so the market floor/ceiling never breaks.
  Wealth ranking = Net Worth (Denari + businesses + vehicles + property + inventory, all at base price),
    not liquid Denari alone. Agents' goal: maximize Net Worth by hour 120.
  Bounties require a police officer to witness or arrive in time — no police funding means no bounties ever.
  Combat has no random hit-chance number — it's a simultaneous zone-prediction game, so model quality
    itself determines accuracy over time.

---

## Master Overview

Convoy — Master Overview
One-glance summary of every tab. Edit source tabs to change values — everything here is a live formula.
CURRENCY & STARTING POINT
Currency Name | Denari | Starting Denari | 100
RESOURCES (15 — raw + refined, Bronze & Iron)
Resource | Rarity | Base Price | NPC Buy | NPC Sell | Source
Water | Common | 1 | 0.4 | 1.6 | Farms/Wells
Grain | Common | 2 | 0.8 | 3.2 | Farms
Wood | Common | 2 | 0.8 | 3.2 | Mines/Logging
Stone | Common | 3 | 1.2000000000000002 | 4.800000000000001 | Mines
Clay | Common | 2 | 0.8 | 3.2 | Mines
Hide | Common | 4 | 1.6 | 6.4 | Farms (livestock)
Copper Ore | Uncommon | 6 | 2.4000000000000004 | 9.600000000000001 | Mines
Tin Ore | Uncommon | 8 | 3.2 | 12.8 | Mines
Bronze (refined) | Uncommon | 18 | 7.2 | 28.8 | Refinery (Copper + Tin + Charcoal)
Charcoal (refined) | Uncommon | 4 | 1.6 | 6.4 | Refinery (Wood)
Tanned Leather (refined) | Uncommon | 7 | 2.8000000000000003 | 11.200000000000001 | Refinery (Hide + Water)
Iron Ore | Uncommon | 12 | 4.800000000000001 | 19.200000000000003 | Mines
Hardwood | Uncommon | 8 | 3.2 | 12.8 | Mines/Logging
Wool | Common | 5 | 2 | 8 | Farms
Iron (refined) | Rare | 22 | 8.8 | 35.2 | Refinery (Iron Ore + Charcoal)
VEHICLES (6)
Vehicle | Rarity | Speed | Cargo (units) | Base Price | NPC Sell Price
On Foot (backpack) | Common | Slowest | 5 | 0 | 0
Camel | Common | Slow | 20 | 150 | 225
Horse | Common | Medium | 15 | 200 | 300
Donkey Cart | Uncommon | Slow | 100 | 400 | 600
2-Horse Chariot | Rare | Fast | 80 | 700 | 1050
4-Horse Chariot | Rare | Fastest | 200 | 1600 | 2400
WEAPONS (10)
Weapon | Rarity | Type | Damage | Base Price | NPC Sell Price
Slingshot | Common | Ranged (starter) | 10 | 0 | 0
Sling | Common | Ranged | 14 | 50 | 85
Wooden Spear | Common | Melee | 22 | 60 | 102
Bronze Dagger | Uncommon | Melee | 16 | 120 | 204
Bronze-Tipped Spear | Uncommon | Melee | 28 | 220 | 374
Bronze Sword | Uncommon | Melee | 34 | 250 | 425
Bow | Rare | Ranged | 20 | 300 | 510
Iron Dagger | Rare | Melee | 24 | 350 | 595
Iron-Tipped Spear | Rare | Melee | 36 | 550 | 935
Iron Sword | Rare | Melee | 50 | 650 | 1105
ARMOR (9)
Armor Piece | Slot | Tier | Reduction | Base Price | NPC Sell Price
Leather Cap | Head | Leather | -0.05 | 80 | 136
Leather Vest | Chest | Leather | -0.1 | 150 | 255
Leather Leggings | Legs | Leather | -0.05 | 80 | 136
Bronze Helm | Head | Bronze | -0.1 | 300 | 510
Bronze Cuirass | Chest | Bronze | -0.2 | 550 | 935
Bronze Greaves | Legs | Bronze | -0.1 | 300 | 510
Iron Helm | Head | Iron | -0.15 | 500 | 850
Iron Cuirass | Chest | Iron | -0.25 | 900 | 1530
Iron Greaves | Legs | Iron | -0.15 | 500 | 850
BUSINESSES (11)
Business | Startup Cost | Employees Required? | Max Employees
Mining Operation | 350 | Required — zero output with no active worker (owner can self-staff) | Uncapped
Farm | 300 | Required — zero output with no active worker (owner can self-staff) | Uncapped
Refinery | 900 | Required — zero output with no active worker (owner can self-staff) | Uncapped
General Store | 500 | Required for extended hours | 2
Home Improvement Store | 500 | Required for extended hours | 2
Mining/Farming Equipment Store | 550 | Required for extended hours | 2
Weaponsmith / Armory | 700 | Required for extended hours | 2
Vehicle Dealer / Stable | 600 | Required for extended hours | 2
Tavern / Inn | 400 | Required for extended hours | 2
Private Security Contractor | 1000 | Guards ARE the employees | N/A
Insurance Brokerage | 1500 | None — capital reserve instead | 0
WAGES (per hour)
Role | NPC Wage | Smart Player Wage | Minimum Wage Floor
Laborer | 45 | 20 | 10
Miner (uncommon ore) | 65 | 28.88888888888889 | 14.444444444444445
Farmhand | 50 | 22.22222222222222 | 11.11111111111111
Refinery Worker | 85 | 37.77777777777778 | 18.88888888888889
Store Clerk | 40 | 17.77777777777778 | 8.88888888888889
Blacksmith | 80 | 35.55555555555556 | 17.77777777777778
Stablehand | 45 | 20 | 10
Researcher | 75 | 33.333333333333336 | 16.666666666666668
RESEARCH TIERS
Tier | Cumulative RP | Hours (1 Researcher) | Efficiency | Quality | Tag
Tier 1 | 150 | 18.75 | 0.05 | 0.05 | —
Tier 2 | 400 | 50 | 0.1 | 0.1 | —
Tier 3 | 900 | 112.5 | 0.15 | 0.15 | Fine
Tier 4 | 1800 | 225 | 0.2 | 0.2 | Masterwork
Tier 5 | 3500 | 437.5 | 0.25 | 0.25 | Legendary Craftsmanship
Full agent action/tool list (~94 actions across 17 categories) lives on its own Actions tab. Convoy roles/pay formula and Government/Insurance policy catalog & bounty rules live on their own tabs — all three too long to usefully summarize here.

---

## Assumptions

Convoy — Iron Age Economy Assumptions
Edit yellow cells to rebalance the entire economy. All other sheets pull from here.
Category | Assumption | Value | Notes
Currency | Currency Name | Denari | Bronze Age silver coin
Player Start | Starting Denari | 100
NPC Trading Post | NPC Buy % of Base Price (raw resources) | 0.4 | NPC pays this % of base price when buying from players
NPC General Store | NPC Sell % of Base Price (common goods) | 1.6 | NPC charges this % of base price when selling to players
NPC Refinery | NPC Buy % of Base Price (ore) | 0.4 | Same as Trading Post rate
NPC Refinery | NPC Sell % of Base Price (refined goods) | 1.5
NPC Weaponsmith | NPC Sell % of Base Price (weapons & armor) | 1.7 | Highest markup — biggest entrepreneurship incentive
NPC Stables | NPC Sell % of Base Price (vehicles) | 1.5
NPC Insurance | NPC Premium % of Cargo Value | 0.2 | Player brokers can undercut to ~8-12%
Player Store Floor | Minimum Retail % of Base Price | 0.6 | Players cannot undercut below this — prevents predatory pricing wars
Wages | NPC Employee Wage Multiplier (vs Smart Player Wage) | 2.25 | NPC employees cost this many times the smart player wage
Wages | Minimum Player Wage % of Smart Wage | 0.5 | Soft floor — owners can't pay below this
Production | Employee Speed Bonus (per employee) | 0.4 | +40% output speed per employee, up to 3 employees
Production | Max Employees per Production Business | 3
Business | Bankruptcy Grace Period (hours) | 24 | Time after cash hits zero before business closes
Research | RP Generated per Researcher per Hour | 8 | Stated assumption — no other data to derive this from
Taxes | Default Wage Tax % | 0.05 | Adjustable via Government policy — bounded 0-25%
Taxes | Default Sales Tax % | 0.05 | Adjustable via Government policy — bounded 0-25%
Taxes | Default Property Tax % | 0.05 | Charged every 24 real hours on assessed value. Adjustable via policy — bounded 0-25%

---

## Resources

Resources — Bronze & Iron
Base Price is the reference value. NPC Buy/Sell prices auto-calculate from Assumptions tab. Base Rate/hr is per single worker (Novice skill, no diminishing returns) — see Businesses tab for how output scales with employee count. See Production Chain tab for how raw resources become refined resources become final goods. Recipe quantities are fixed — Research changes speed and output quality, never these input amounts.
Resource | Rarity | Source | Base Price | NPC Buy Price
(Trading Post) | NPC Sell Price
(General Store) | Used For | Base Rate/hr
(1 worker)
Water | Common | Farms/Wells | 1 | 0.4 | 1.6 | Food/survival, Tanned Leather (refined) | 72
Grain | Common | Farms | 2 | 0.8 | 3.2 | Food/survival, Tavern meals | 72
Wood | Common | Mines/Logging | 2 | 0.8 | 3.2 | Charcoal (refined), weapon handles, cart frames, tools, property upgrades | 72
Stone | Common | Mines | 3 | 1.2000000000000002 | 4.800000000000001 | Property upgrades | 72
Clay | Common | Mines | 2 | 0.8 | 3.2 | Property upgrades | 72
Hide | Common | Farms (livestock) | 4 | 1.6 | 6.4 | Tanned Leather (refined) | 72
Copper Ore | Uncommon | Mines | 6 | 2.4000000000000004 | 9.600000000000001 | Bronze (refined) | 36
Tin Ore | Uncommon | Mines | 8 | 3.2 | 12.8 | Bronze (refined) | 36
Bronze (refined) | Uncommon | Refinery (Copper + Tin + Charcoal) | 18 | 7.2 | 28.8 | Bronze weapons/armor, cart reinforcement, tools | 15
Charcoal (refined) | Uncommon | Refinery (Wood) | 4 | 1.6 | 6.4 | Bronze and Iron smelting fuel | 15
Tanned Leather (refined) | Uncommon | Refinery (Hide + Water) | 7 | 2.8000000000000003 | 11.200000000000001 | Slings, bows, all armor tiers, harnesses, chariot tack | 15
Iron Ore | Uncommon | Mines | 12 | 4.800000000000001 | 19.200000000000003 | Iron (refined) | 36
Hardwood | Uncommon | Mines/Logging | 8 | 3.2 | 12.8 | Iron Age weapons, chariots, Bow | 36
Wool | Common | Farms | 5 | 2 | 8 | Clothing/cosmetics | 72
Iron (refined) | Rare | Refinery (Iron Ore + Charcoal) | 22 | 8.8 | 35.2 | Iron weapons, Iron armor, 4-Horse Chariot | 15

---

## Production Chain

Production Chain — Raw → Refined → Final Goods
Three stages: Mine/Farm extracts raw resources, Refinery processes them into refined resources, Store does final assembly and sells to players. Input Cost columns sum base prices from the Resources/Weapons/Vehicles/Armor tabs — edit those to see costs and margins update here automatically. These recipe quantities are fixed regardless of Research investment (see Research tab).
STAGE 1 — RAW (Mined or Farmed)
Resource | Source | Feeds Into
Water | Farms/Wells | Food/survival, Tanned Leather (refined)
Grain | Farms | Food/survival, Tavern meals
Wood | Mines/Logging | Charcoal (refined), weapon handles, cart frames, tools, property upgrades
Stone | Mines | Property upgrades
Clay | Mines | Property upgrades
Hide | Farms (livestock) | Tanned Leather (refined)
Copper Ore | Mines | Bronze (refined)
Tin Ore | Mines | Bronze (refined)
Iron Ore | Mines | Iron (refined)
Hardwood | Mines/Logging | Iron Age weapons, chariots, Bow
Wool | Farms | Clothing/cosmetics
STAGE 2 — REFINED (at Refinery)
Refined Good | Inputs Required | Input Cost
(sum of base prices) | Base Price
(this good) | Margin | Used For
Charcoal | Wood | 2 | 4 | 2 | Bronze and Iron smelting fuel
Tanned Leather | Hide + Water | 5 | 7 | 2 | Slings, bows, all armor tiers, harnesses, chariot tack
Bronze | Copper Ore + Tin Ore + Charcoal | 18 | 18 | 0 | Bronze weapons/armor, cart reinforcement, tools
Iron | Iron Ore + Charcoal | 16 | 22 | 6 | Iron weapons/armor, 4-Horse Chariot
STAGE 3 — FINAL GOODS (assembled + sold at Stores)
Final Good | Assembled At | Inputs Required | Input Cost
(sum of base prices) | Sell Price
(base, this good) | Margin
Sling | Weaponsmith | Tanned Leather + Wood | 9 | 50 | 41
Wooden Spear | Weaponsmith | Wood | 2 | 60 | 58
Bronze Dagger | Weaponsmith | Bronze + Wood | 20 | 120 | 100
Bronze-Tipped Spear | Weaponsmith | Bronze + Wood | 20 | 220 | 200
Bronze Sword | Weaponsmith | Bronze + Wood | 20 | 250 | 230
Bow | Weaponsmith | Hardwood + Tanned Leather | 15 | 300 | 285
Iron Dagger | Weaponsmith | Iron + Hardwood | 30 | 350 | 320
Iron-Tipped Spear | Weaponsmith | Iron + Hardwood | 30 | 550 | 520
Iron Sword | Weaponsmith | Iron + Hardwood | 30 | 650 | 620
Leather Cap/Vest/Leggings (each) | Weaponsmith | Tanned Leather | 7 | 80 | 73
Bronze Helm/Cuirass/Greaves (each) | Weaponsmith | Bronze + Tanned Leather | 25 | 300 | 275
Iron Helm/Cuirass/Greaves (each) | Weaponsmith | Iron + Tanned Leather | 29 | 500 | 471
Donkey Cart | Vehicle Dealer / Stable | Wood + Bronze + Tanned Leather | 27 | 400 | 373
2-Horse Chariot | Vehicle Dealer / Stable | Hardwood + Tanned Leather | 15 | 700 | 685
4-Horse Chariot | Vehicle Dealer / Stable | Iron + Hardwood + Tanned Leather | 37 | 1600 | 1563
Camel | Vehicle Dealer / Stable | 15 Water + 10 Grain + 1 Tanned Leather (feed + saddle) | 42 | 150 | 108
Horse | Vehicle Dealer / Stable | 20 Water + 15 Grain + 1 Tanned Leather (feed + saddle) | 57 | 200 | 143
Upgraded Tools | Mining/Farming Equipment Store | Wood + Bronze | 20 | 130 | 110
Property Upgrades | Home Improvement Store | Stone + Clay + Wood | 7 | 50 | 43
Food (resale) | General Store | Grain or Water | N/A | N/A — resold directly (see Resources tab) | —
Meal | Tavern | Grain + Water | 3 | 10 | 7
Note: Camel/Horse input cost assumes a stated feed-quantity estimate — raising time isn't otherwise modeled. Food (resale) intentionally has no separate final-good price. Armor rows show cost/price for ONE representative piece per tier (Head shown) — Chest and Legs use the same input types at different base prices; see the Armor tab for all nine pieces individually. 2-Horse Chariot uses no Iron (lighter build); 4-Horse Chariot adds Iron reinforcement, matching its higher price and 'strongest' billing.

---

## Research

Research — Business-Level Investment (Speed & Quality, Never Recipes)
A hired Researcher generates Research Points (RP) for their business over time — base rate on the Assumptions tab, subject to the SAME diminishing-returns decay as production employees (see Businesses tab), tracked as a separate headcount pool from production staff. No cap on Researcher count. The owner spends accumulated RP on either track below. Research NEVER changes what a recipe requires — only how fast a business produces, and how strong its crafted output is. Applies to all businesses except Private Security Contractor and Insurance Brokerage.
THE TWO TRACKS
Efficiency | Speeds up this business's mining/farming/refining/crafting time. Stacks with the +40%/employee speed bonus (Assumptions tab).
Quality | Improves the stats of crafted output without changing input requirements. Each tier grants a total bonus POOL — the crafting business allocates it across whichever stats are available to that item's category (see 'Quality Bonus Stat Pools' below), either all into one stat or split. A Weaponsmith could craft one sword that's all-speed and another that's all-damage, from the same Tier.
RESEARCH TIERS
Tier | Cumulative RP Required | Hours
(1 Researcher, at RP rate above) | Efficiency Bonus | Quality Bonus | Quality Tag
Tier 1 | 150 | 18.75 | 0.05 | 0.05 | —
Tier 2 | 400 | 50 | 0.1 | 0.1 | —
Tier 3 | 900 | 112.5 | 0.15 | 0.15 | Fine
Tier 4 | 1800 | 225 | 0.2 | 0.2 | Masterwork
Tier 5 | 3500 | 437.5 | 0.25 | 0.25 | Legendary Craftsmanship
WHY THIS DOESN'T CHANGE RECIPES
A Weaponsmith at Tier 4 Quality still needs exactly 'Bronze + Wood' to craft a Bronze Sword — the Production Chain tab's input costs are untouched. What changes is that the sword it produces deals +20% damage and carries a visible 'Masterwork' tag, making it a real status item without needing a separate Epic/Legendary cosmetic catalog to be built. Efficiency research similarly never reduces how much Bronze or Wood a craft consumes — only how long it takes.
MATERIAL CONSUMPTION DURING RESEARCH (per hour, on top of wages)
A Researcher doesn't just cost wages — they burn a small quantity of the business's own material while testing techniques. This is separate from, and never touches, the crafting recipes on the Production Chain tab. Rate is a stated assumption (units/hour), flat regardless of Research tier.
Business | Test Material | Consumption Rate
(units/hr) | Material Cost/hr | Total Hourly Cost
(NPC Researcher) | Total Hourly Cost
(Player Researcher, Smart Wage)
Mining Operation | Wood | 0.5 | 1 | 76 | 34.333333333333336
Farm | Grain | 0.5 | 1 | 76 | 34.333333333333336
Refinery | Charcoal | 0.5 | 2 | 77 | 35.333333333333336
General Store | Wood | 0.3 | 0.6 | 75.6 | 33.93333333333334
Home Improvement Store | Stone | 0.5 | 1.5 | 76.5 | 34.833333333333336
Mining/Farming Equipment Store | Wood | 0.5 | 1 | 76 | 34.333333333333336
Weaponsmith / Armory | Bronze | 0.3 | 0.6 | 75.6 | 33.93333333333334
Vehicle Dealer / Stable | Tanned Leather | 0.3 | 1.7999999999999998 | 76.8 | 35.13333333333333
Tavern / Inn | Grain | 0.5 | 1 | 76 | 34.333333333333336
QUALITY BONUS STAT POOLS — WHAT EACH CATEGORY CAN ALLOCATE INTO
Category | Items | Available Stats (tier's % pool splits across these)
Melee Weapons | Wooden Spear, Bronze/Iron Dagger, Bronze/Iron-Tipped Spear, Bronze/Iron Sword | Attack Speed, Damage
Ranged Weapons | Slingshot, Sling, Bow | Attack Speed, Damage, Accuracy
Armor | Leather / Bronze / Iron Head, Chest, Legs | Damage Reduction, Inventory Capacity
Vehicles | Camel, Horse, Donkey Cart, 2-Horse Chariot, 4-Horse Chariot | Cargo Capacity, Speed, Damage Resistance
Food (Tavern Meals) | Base Meal, Tier 1-5 Bread | Sustenance Duration — uses its OWN fixed hour table (12/15/18/21/24/30 hrs), not the generic 5/10/15/20/25% pool used by other categories. See Sustenance tab for the full table and status effects.
HYPOTHETICAL UPGRADE EXAMPLES — ONE ILLUSTRATIVE ITEM PER TIER PER CATEGORY
These are examples of how a business might choose to allocate its pool, not the only valid split. Base item stats (from Weapons/Vehicles/Armor tabs) are unaffected — this is the bonus layered on top.
Tier | Category | Example Name | Base Item | Stat Allocation
Tier 1 (5%) | Melee | Sharpened Bronze Sword | Bronze Sword | +5% Damage
Tier 2 (10%) | Melee | Swift Bronze Dagger | Bronze Dagger | +10% Attack Speed
Tier 3 — Fine (15%) | Melee | Fine Bronze-Tipped Spear | Bronze-Tipped Spear | +8% Damage / +7% Attack Speed
Tier 4 — Masterwork (20%) | Melee | Swift Masterwork Iron Sword | Iron Sword | +20% Attack Speed
Tier 5 — Legendary (25%) | Melee | Legendary Iron Sword | Iron Sword | +25% Damage
Tier 1 (5%) | Ranged | Sharpened Sling | Sling | +5% Damage
Tier 2 (10%) | Ranged | Quick Bow | Bow | +10% Attack Speed
Tier 3 — Fine (15%) | Ranged | Fine Bow | Bow | +15% Accuracy
Tier 4 — Masterwork (20%) | Ranged | Masterwork Bow | Bow | +10% Accuracy / +10% Damage
Tier 5 — Legendary (25%) | Ranged | Legendary Bow | Bow | +9% Accuracy / +8% Damage / +8% Attack Speed
Tier 1 (5%) | Armor | Sturdy Leather Chestpiece | Leather Vest | +5% Damage Reduction
Tier 2 (10%) | Armor | Roomy Leather Vest | Leather Vest | +10% Inventory Capacity
Tier 3 — Fine (15%) | Armor | Fine Iron Helm | Iron Helm | +15% Damage Reduction
Tier 4 — Masterwork (20%) | Armor | Masterwork Iron Cuirass | Iron Cuirass | +10% Damage Reduction / +10% Inventory Capacity
Tier 5 — Legendary (25%) | Armor | Legendary Iron Greaves | Iron Greaves | +25% Inventory Capacity
Tier 1 (5%) | Vehicle | Reinforced Donkey Cart | Donkey Cart | +5% Damage Resistance
Tier 2 (10%) | Vehicle | Swift Camel | Camel | +10% Speed
Tier 3 — Fine (15%) | Vehicle | Fine 2-Horse Chariot | 2-Horse Chariot | +15% Speed
Tier 4 — Masterwork (20%) | Vehicle | Masterwork 4-Horse Chariot | 4-Horse Chariot | +10% Cargo Capacity / +10% Damage Resistance
Tier 5 — Legendary (25%) | Vehicle | Legendary 4-Horse Chariot | 4-Horse Chariot | +25% Cargo Capacity
KNOWN TENSION — UNCAPPED RESEARCHERS VS. INTENDED RESEARCH PACING
Tier 5 (3,500 RP) was paced assuming ONE Researcher (437.5 hours). With uncapped hiring, a business staffing 19 Researchers (the same output-peak point as production labor) generates ~60.4 RP/hour — reaching Tier 5 in roughly 58 hours, well inside a 120-hour run. This means a wealthy business could realistically rush-fund Legendary Craftsmanship items much faster than the original single-Researcher design intended. This is left intentional rather than re-capped — it's a legitimate, dramatic outcome worth observing in the validation run, not a bug to pre-solve. Watch for it specifically when reviewing results: is 'a monopoly rush-funded Legendary gear in week one' an exciting story, or does it need a slower curve after seeing it happen once?

---

## Armor

Armor — Leather, Bronze & Iron
Three slots (Head/Chest/Legs) stack additively. A full Bronze set totals -40% damage taken; a full Iron set totals -55%. NPC Sell Price uses the same Weaponsmith/Armory markup as weapons. Quality Research (see Research tab) adds a further stat bonus on top of these base values without changing these recipes.
Armor Piece | Slot | Tier | Damage Reduction | Inputs Required | Base Price | NPC Sell Price
(Weaponsmith)
Leather Cap | Head | Leather | -0.05 | Tanned Leather | 80 | 136
Leather Vest | Chest | Leather | -0.1 | Tanned Leather | 150 | 255
Leather Leggings | Legs | Leather | -0.05 | Tanned Leather | 80 | 136
Bronze Helm | Head | Bronze | -0.1 | Bronze + Tanned Leather | 300 | 510
Bronze Cuirass | Chest | Bronze | -0.2 | Bronze + Tanned Leather | 550 | 935
Bronze Greaves | Legs | Bronze | -0.1 | Bronze + Tanned Leather | 300 | 510
Iron Helm | Head | Iron | -0.15 | Iron + Tanned Leather | 500 | 850
Iron Cuirass | Chest | Iron | -0.25 | Iron + Tanned Leather | 900 | 1530
Iron Greaves | Legs | Iron | -0.15 | Iron + Tanned Leather | 500 | 850

---

## Vehicles

Vehicles — Bronze & Iron
NPC Sell Price auto-calculates from Assumptions tab (Government Stables markup). Cargo Capacity is in real units (matches the 'units' resource prices are quoted in) — Donkey Cart is the 100-unit baseline everything else scales against.
Vehicle | Rarity | Speed | Cargo Capacity
(units) | Armor | Base Price | NPC Sell Price
(Stables)
On Foot (backpack) | Common | Slowest | 5 | None | 0 | 0
Camel | Common | Slow | 20 | None | 150 | 225
Horse | Common | Medium | 15 | None | 200 | 300
Donkey Cart | Uncommon | Slow | 100 | None | 400 | 600
2-Horse Chariot | Rare | Fast | 80 | Light | 700 | 1050
4-Horse Chariot | Rare | Fastest | 200 | Medium | 1600 | 2400

---

## Weapons

Weapons — Bronze & Iron
NPC Sell Price auto-calculates from Assumptions tab (Government Weaponsmith markup). Damage is against 100 HP, unarmored. Hits to Kill is a live formula — edit Damage and it recalculates.
Weapon | Rarity | Type | Damage | Base Price | NPC Sell Price
(Weaponsmith) | Attack Speed | Headshot /
Backstab | Hits to Kill
(unarmored, 100 HP)
Slingshot | Common | Ranged (starter) | 10 | 0 | 0 | 1 per 0.9s | 2x headshot | 10
Sling | Common | Ranged | 14 | 50 | 85 | 1 per 0.8s | 2x headshot | 8
Wooden Spear | Common | Melee | 22 | 60 | 102 | 1 per 0.7s | 1.5x backstab | 5
Bronze Dagger | Uncommon | Melee | 16 | 120 | 204 | 1 per 0.4s | 1.5x backstab | 7
Bronze-Tipped Spear | Uncommon | Melee | 28 | 220 | 374 | 1 per 0.75s | 1.5x backstab | 4
Bronze Sword | Uncommon | Melee | 34 | 250 | 425 | 1 per 0.6s | 1.5x backstab | 3
Bow | Rare | Ranged | 20 | 300 | 510 | 1 per 0.85s | 2x headshot | 5
Iron Dagger | Rare | Melee | 24 | 350 | 595 | 1 per 0.4s | 1.5x backstab | 5
Iron-Tipped Spear | Rare | Melee | 36 | 550 | 935 | 1 per 0.75s | 1.5x backstab | 3
Iron Sword | Rare | Melee | 50 | 650 | 1105 | 1 per 0.6s | 1.5x backstab | 2

---

## Businesses

Bronze & Iron Age Businesses
Startup Cost is an input (blue). EVERY player-owned business except Insurance Brokerage requires at least one active worker — owner or employee — to produce/operate at all; zero workers = zero output for that period. NO CAP on employee count — output scales via diminishing returns instead of a hard ceiling (see table below). GOVERNMENT-owned businesses are the one exception: always considered fully staffed regardless of actual hires. Owner can personally cover exactly one shift across their entire portfolio. Insurance Brokerage needs capital reserve instead of labor.
Business | Startup Cost | Income Model | Employees Required? | Max Employees | Notes
Mining Operation | 350 | Sells raw resources (ore/wood/stone/clay) to Refinery or Trading Post | Required — zero output with no active worker (owner can self-staff) | Uncapped | Owner counts as a worker if personally staffing it. Output scales with worker count/skill, zero at zero workers. Can hire a Researcher.
Farm | 300 | Sells Water/Grain/Hide/Wool to Trading Post or Tavern | Required — zero output with no active worker (owner can self-staff) | Uncapped | Owner counts as a worker if personally staffing it. Output scales with worker count/skill, zero at zero workers. Can hire a Researcher.
Refinery | 900 | Buys raw resources, sells refined goods (Bronze, Iron, Charcoal, Tanned Leather) at markup | Required — zero output with no active worker (owner can self-staff) | Uncapped | Owner counts as a worker if personally staffing it. Output scales with worker count/skill, zero at zero workers. Can hire a Researcher.
General Store | 500 | Buys/sells common goods at player-set retail markup | Required for extended hours | 2 | 1 shift free (owner), 2 more shifts need employees. Can hire a Researcher.
Home Improvement Store | 500 | Buys Stone/Clay/Wood, assembles and sells Property Upgrades | Required for extended hours | 2 | Can hire a Researcher.
Mining/Farming Equipment Store | 550 | Buys Wood/Bronze, assembles and sells Upgraded Tools | Required for extended hours | 2 | Can hire a Researcher.
Weaponsmith / Armory | 700 | Buys refined goods, assembles and sells weapons and armor (all tiers) at markup | Required for extended hours | 2 | Blacksmith employee also speeds crafting. Can hire a Researcher.
Vehicle Dealer / Stable | 600 | Sells/raises Camels/Horses; assembles and sells Donkey Carts and Chariots | Required for extended hours | 2 | Can hire a Researcher.
Tavern / Inn | 400 | Sells meals — see Sustenance tab for pricing and Research-driven duration tiers | Required for extended hours | 2 | Alternative to self-prepared Grain+Water. Research (Quality track) unlocks higher-tier breads with longer Sustenance Duration — see Sustenance and Research tabs. Higher tier = higher price. Can hire a Researcher.
Private Security Contractor | 1000 | Supplies hired guards to convoys; takes a cut of guard pay | Guards ARE the employees | N/A | No separate staffing beyond the guards themselves. No Research track.
Insurance Brokerage | 1500 | Sells cargo/vehicle policies; pays out claims | None — capital reserve instead | 0 | No employees needed. Must maintain cash reserve ≥ 70% of total outstanding insured value to issue new policies (matches the 70% payout rate). Funded by owner capital and/or investors — pitched and negotiated directly in chat, revenue-share terms set between the parties. See Government & Insurance tab.
DIMINISHING RETURNS — HOW OUTPUT SCALES WITH EMPLOYEE COUNT (uncapped, no hard ceiling)
Each additional employee reduces every worker's individual rate by 5%, compounding: Per-Worker Rate at n employees = Base Rate × Skill Multiplier × 0.95^(n-1). Total Business Output = n × Per-Worker Rate. This applies to production employees AND Researchers, tracked as SEPARATE headcount pools — a business can staff both simultaneously, each decaying against only its own pool. No hard cap on either pool; the math itself creates a natural soft ceiling instead (see table below).
Employees (n) | Per-Worker Rate
(% of base) | Total Output
Multiplier
1 | 1 | 1.000x
2 | 0.95 | 1.900x
3 | 0.9025 | 2.708x
4 | 0.8574 | 3.429x
5 | 0.8145 | 4.073x
10 | 0.6302 | 6.302x
15 | 0.4877 | 7.315x
19 | 0.3972 | 7.547x
20 | 0.3774 | 7.547x
25 | 0.292 | 7.300x
30 | 0.2259 | 6.778x
Total output PEAKS at n=19-20 (≈7.55x a single worker) and then declines — past ~20 employees, hiring more people actively hurts total output, not just per-worker efficiency. This is why no hard cap is needed: the formula creates its own soft ceiling around 20 workers per pool without an arbitrary rule. A monopoly can still dominate — it does so by owning MULTIPLE businesses near their individual peaks, or by investing in Research's Efficiency track (uncapped, hours-driven, stacks on top of this), not by mass-hiring into one location.
Worked example — Iron, 3 Refinery Workers, Novice skill: Base Rate 15/hr (Resources tab) × 0.9025 (3-worker decay) = 13.54/hr per worker × 3 workers = 40.6 Iron/hour total. At Base Price 22/unit (Resources tab), that's roughly $893/hour of Iron produced before wages, input costs, or the NPC buy/sell spread are applied.

---

## Wages

Wages (per real-time hour)
NPC Wage is an input (blue). Smart Player Wage and Minimum Wage Floor auto-calculate from Assumptions tab.
Role | NPC Employee Wage/hr | Smart Player Wage/hr
(recommended) | Minimum Wage Floor/hr
(enforced) | Used In
Laborer | 45 | 20 | 10 | Mining Operation, Farm
Miner (uncommon ore) | 65 | 28.88888888888889 | 14.444444444444445 | Mining Operation
Farmhand | 50 | 22.22222222222222 | 11.11111111111111 | Farm
Refinery Worker | 85 | 37.77777777777778 | 18.88888888888889 | Refinery
Store Clerk | 40 | 17.77777777777778 | 8.88888888888889 | General Store, Home Improvement Store, Equipment Store, Vehicle Dealer, Tavern
Blacksmith | 80 | 35.55555555555556 | 17.77777777777778 | Weaponsmith / Armory
Stablehand | 45 | 20 | 10 | Vehicle Dealer / Stable
Researcher | 75 | 33.333333333333336 | 16.666666666666668 | Any business except Private Security Contractor / Insurance Brokerage — see Research tab
SKILL PROGRESSION (per role name, tracked across all businesses)
Speed only — Research already owns the quality bonus at the business level, so personal skill stays scoped to how fast an individual works. XP = cumulative hours actively worked at that role name, shared across every business of that type (e.g., hours as Laborer at a Mine and at a Farm add together).
Tier | Cumulative Hours Worked | Speed Bonus
Novice | 0 - 4 | 0
Journeyman | 5 - 14 | 0.1
Skilled | 15 - 34 | 0.2
Expert | 35 - 69 | 0.35
Master | 70+ | 0.5
Stacks additively with employee-count bonus and Research's Efficiency bonus. Applies to all 8 wage roles, including Researcher — a skilled Researcher generates more RP/hour, not just faster labor.

---

## Progression Math

Progression Math — Hours of Labor to Afford Key Purchases
Shows how many real-time hours of work (at each wage tier) it takes to save for each item. Recalculates automatically from Wages, Vehicles, Weapons, Armor, and Businesses tabs.
Item | Cost | Hrs @ Laborer Wage
(Smart Rate) | Hrs @ Refinery Worker Wage
(Smart Rate) | Hrs @ NPC Laborer Wage
(for comparison)
VEHICLES (Base Price)
On Foot (backpack) | 0 | 0 | 0 | 0
Camel | 150 | 7.5 | 3.9705882352941178 | 3.3333333333333335
Horse | 200 | 10 | 5.294117647058823 | 4.444444444444445
Donkey Cart | 400 | 20 | 10.588235294117647 | 8.88888888888889
2-Horse Chariot | 700 | 35 | 18.52941176470588 | 15.555555555555555
4-Horse Chariot | 1600 | 80 | 42.35294117647059 | 35.55555555555556
WEAPONS (Base Price)
Slingshot | 0 | 0 | 0 | 0
Sling | 50 | 2.5 | 1.3235294117647058 | 1.1111111111111112
Wooden Spear | 60 | 3 | 1.588235294117647 | 1.3333333333333333
Bronze Dagger | 120 | 6 | 3.176470588235294 | 2.6666666666666665
Bronze-Tipped Spear | 220 | 11 | 5.823529411764706 | 4.888888888888889
Bronze Sword | 250 | 12.5 | 6.617647058823529 | 5.555555555555555
Bow | 300 | 15 | 7.9411764705882355 | 6.666666666666667
Iron Dagger | 350 | 17.5 | 9.26470588235294 | 7.777777777777778
Iron-Tipped Spear | 550 | 27.5 | 14.558823529411764 | 12.222222222222221
Iron Sword | 650 | 32.5 | 17.205882352941178 | 14.444444444444445
ARMOR (Base Price)
Leather Cap | 80 | 4 | 2.1176470588235294 | 1.7777777777777777
Leather Vest | 150 | 7.5 | 3.9705882352941178 | 3.3333333333333335
Leather Leggings | 80 | 4 | 2.1176470588235294 | 1.7777777777777777
Bronze Helm | 300 | 15 | 7.9411764705882355 | 6.666666666666667
Bronze Cuirass | 550 | 27.5 | 14.558823529411764 | 12.222222222222221
Bronze Greaves | 300 | 15 | 7.9411764705882355 | 6.666666666666667
Iron Helm | 500 | 25 | 13.235294117647058 | 11.11111111111111
Iron Cuirass | 900 | 45 | 23.823529411764707 | 20
Iron Greaves | 500 | 25 | 13.235294117647058 | 11.11111111111111
BUSINESSES (Startup Cost)
Mining Operation | 350 | 17.5 | 9.26470588235294 | 7.777777777777778
Farm | 300 | 15 | 7.9411764705882355 | 6.666666666666667
Refinery | 900 | 45 | 23.823529411764707 | 20
General Store | 500 | 25 | 13.235294117647058 | 11.11111111111111
Home Improvement Store | 500 | 25 | 13.235294117647058 | 11.11111111111111
Mining/Farming Equipment Store | 550 | 27.5 | 14.558823529411764 | 12.222222222222221
Weaponsmith / Armory | 700 | 35 | 18.52941176470588 | 15.555555555555555
Vehicle Dealer / Stable | 600 | 30 | 15.882352941176471 | 13.333333333333334
Tavern / Inn | 400 | 20 | 10.588235294117647 | 8.88888888888889
Private Security Contractor | 1000 | 50 | 26.470588235294116 | 22.22222222222222
Insurance Brokerage | 1500 | 75 | 39.705882352941174 | 33.333333333333336
RESEARCH TIERS (Hours of Researcher Employment, Independent of Wage Paid)
Tier 1 | 150 | 18.75 | — | —
Tier 2 | 400 | 50 | — | —
Tier 3 (Fine) | 900 | 112.5 | — | —
Tier 4 (Masterwork) | 1800 | 225 | — | —
Tier 5 (Legendary Craftsmanship) | 3500 | 437.5 | — | —
Note: 'Smart Rate' pulls from the recommended player wage on the Wages tab, not the inflated NPC wage. Research hours are independent of wage paid.
KNOWN BALANCE RISKS — WATCH THESE SPECIFICALLY IN THE VALIDATION RUN
• | Convoy pay vs. mining wages: a Driver earns roughly 17x per-minute what a Laborer earns — intentional, but could pull agents away from mining entirely if the gap proves too strong. Cargo can't exist without someone mining it first.
• | Iron Refinery margin: 3 Refinery Workers producing ~40.6 Iron/hour at $22/unit base price is roughly $893/hour of output before costs — a large number worth checking against real wages and input costs once the run is live, not just trusting the formula in isolation.
• | Researcher rush-funding: uncapped Researcher hiring can reach Research Tier 5 in ~58 hours instead of the 437.5 hours a single-Researcher design assumed — see Research tab for full detail. Not necessarily wrong, but worth watching whether it happens and whether it's a good story or too fast.
• | Diminishing returns peak (~19-20 workers per pool): untested whether agents actually discover this peak and staff toward it, overshoot past it, or never approach it at all — a genuine behavioral question the validation run is specifically positioned to answer.

---

## Actions

Agent Action / Tool List
Every callable action an agent's turn can consist of. Read access to server-wide and guild chat is available context every turn, not a callable action itself. Skill growth from Mining/Farming/Refining/Crafting is a passive side-effect, not a separate action.
Category | Action | Notes
MOVEMENT
Travel to a location | Time-based, proportional to distance and vehicle speed — no teleportation
Mount / Dismount vehicle
Wait / Idle | Explicit no-op, needed especially for the simplest agent tier
LABOR
Begin mining at a resource node | Passive — runs until stopped, not a repeated per-tick action
Stop mining
Begin farming at a resource node | Passive
Stop farming
Begin a work shift at a business | Passive wage labor
End work shift
Apply for a job
Quit a job
REFINING & CRAFTING
Begin refining at a Refinery | Passive — runs until stopped
Stop refining
Craft a final good | Discrete choice, resolves over time
Choose quality stat allocation when crafting | Only if the business has an unlocked Research tier
TRADING & MARKET
Buy from a business
Sell to a business
Set retail price | Business owner only
Buy an existing business from another player
Direct trade with another player | The only channel for stolen/rare goods — no anonymous black market screen
BUSINESS MANAGEMENT
Start a business
Hire employee
Fire employee
Set wage for a role
Deposit cash into business
Withdraw profit
Sell business to another player
Invest in another player's business | Silent investor, no labor
Hire a Researcher
Allocate Research Points | Efficiency vs Quality track
CONVOY SYSTEM
Post a convoy job | Organizer only — max 1 per rolling hour per business, see Convoy tab
Cancel a posted convoy
Join a convoy | As Driver, Scout, or Bodyguard
Leave a convoy mid-run | Risky
Load cargo onto a convoy
Depart a convoy | Organizer decides to depart short-handed or extend recruiting — see Convoy tab
Actively drive a convoy vehicle
Claim convoy pay / commission | After completion — see Convoy tab for the pay formula
COMBAT
Melee attack | Distinct swing animation for spectator visibility
Ranged attack — quick shot
Ranged attack — charge and release | Bow / Sling
Block / defend | For visual variety
Flee combat
Ram a target with a vehicle
Fight from a moving vehicle
THEFT & CRIME
Steal cargo from a convoy | Hold-to-siphon
Pickpocket another player
Steal an unattended vehicle
Rob an unstaffed business till
Destroy a vehicle
Loot a killed player's dropped items
Loot a convoy wreck
Sabotage | Vandalize a business or refinery
BOUNTY & LAW
Report a witnessed crime
Pay off own bounty at police station
Place a bounty on another player
Hunt an active bounty target
Claim a bounty | After a successful kill
SCOUTING & INTELLIGENCE
Scout ahead of a convoy
Place a location marker | Last-seen sighting, not a live tracker
Report intel to a convoy organizer
Use the tracking shot | Sniper-mark mechanic
Post a decoy convoy
PROPERTY & REAL ESTATE
Buy property | Auction or direct
Sell property
Build a structure | Free-build, resource-gated
Buy a Property Upgrade
Store a vehicle | Garage
Store resources | Home storage
Rent a property from a landlord
Collect rent | Landlord only
GOVERNMENT & POLITICS
Propose a policy | Tax rate, infrastructure funding, etc. — pure direct democracy, no elected office
Co-sign a proposal | Needed to reach the ballot threshold
Vote on a proposal | 2/3 majority required to enact — executes immediately once threshold is reached
Vote to reverse an enacted policy | 2/3 majority required to reverse
ALLIANCES & SOCIAL
Post to server-wide chat
Create a guild
Invite player to guild
Accept guild invite
Leave guild
Remove a guild member | Guild leader only
Post to guild chat | Private to guild members
Form or join a pirate crew
SURVIVAL
Eat | Consume Grain, Water, or a Meal
Rest | At a property or Tavern
Buy a meal
VEHICLES
Buy a vehicle
Repair a vehicle
Scrap a vehicle for parts
Customize a vehicle | Cosmetic only
INSURANCE
Buy an insurance policy | Cargo, vehicle, or business
File an insurance claim
Offer insurance terms | Only if the agent owns the Insurance Brokerage
ONBOARDING-SPECIFIC
Rent a camel | Starter station
Buy starter gear upgrade | Slingshot to Sling
Removed for this build: Racing (no side-betting mechanic needed for agent-only content), Black Market posting screen (replaced entirely by direct player-to-player trade), Running for elected office (pure direct democracy — no government figurehead).

---

## Convoy

Convoy System — Roles, Pay Formula & Rules
Pay rates below are the GOVERNMENT BASELINE — used by every government-owned business's convoys. Once a player owns that business, they set their own convoy pay terms when organizing, exactly like player stores set their own retail prices instead of the NPC markup. Cargo is filled before departure by whoever mined/farmed/refined it — Miner is not a role during the transport leg itself.
THE THREE CONVOY ROLES
Driver | Required, one per vehicle in the convoy. Physically hauls the cargo.
Scout | Optional. Rides ahead of the convoy, reduces ambush risk.
Bodyguard | Optional. Rides with the convoy, defends it directly if attacked.
GOVERNMENT BASELINE PAY FORMULA
Role | Flat Fee (Denari) | Commission % | Commission Basis | Notes
Driver — organizer-provided vehicle | 10 | 0.005 | That vehicle's own cargo value | Commission forfeited on failure
Driver — own vehicle | 15 | 0.0075 | That vehicle's own cargo value | Higher rate — compensates for risking a personal asset
Scout | 8 | 0.0025 | Total convoy cargo value | Protects the whole convoy, not just one vehicle
Bodyguard | 8 | 0.0035 | Total convoy cargo value | Protects the whole convoy, not just one vehicle
WORKED EXAMPLE — LIVE, RECALCULATES FROM RESOURCES + RATE TABLE ABOVE
Scenario: 1 Donkey Cart, fully loaded with Bronze, own vehicle, Scout + Bodyguard hired
Cargo Good | Bronze
Cargo Base Price (per unit) | 18
Quantity Hauled (units) | 100
Total Cargo Value | 1800
Role | Flat Fee | Commission Earned | Total Pay (this run)
Driver (own vehicle) | 15 | 13.5 | 28.5
Scout | 8 | 4.5 | 12.5
Bodyguard | 8 | 6.3 | 14.3
For comparison: 5 minutes of Laborer wages at the Smart Rate (Wages!C5) earns roughly $1.67 — a Driver on this run earns over 17x more per minute than mining, which is the intended gap.
POSTING & RECRUITMENT RULES
• | One new convoy job per organizing business per rolling hour (not a fixed clock reset — 60 minutes from that business's last post).
• | No global convoy cap. Any number of convoys can run simultaneously across the world.
• | Maximum 10 vehicles per convoy. No cap on total crew size (Scouts/Bodyguards) — market and cost are the only limiters.
• | Convoy can depart with just a Driver — Scout and Bodyguard are both fully optional.
• | Initial recruiting window: 15 minutes. If unfilled, the organizer decides: depart short-handed, or extend 15 more minutes — capped at 3 extensions (60 minutes total) before a decision is forced.
• | A business must always be staffed. The owner can only join their own convoy (as Driver, Scout, or Bodyguard) if at least one employee remains covering the shop.
• | If the organizing business goes bankrupt before departure, the convoy is cancelled. A convoy already in transit completes normally regardless of what happens to the business.
• | Agents should weight an available convoy role heavily in their decision-making — convoy pay is designed to far exceed solo Labor wages per minute (see worked example above) — but this is not a hard override; an agent can rationally decline.
When a convoy is ambushed mid-transit, each vehicle's Driver gets a three-way choice (Fight / Push Through / Flee Off-Road), decided independently per vehicle — see Combat & Heroes tab for full detail.

---

## Government & Insurance

Government, Taxes, Bounties & Insurance
Pure direct democracy — no elected office. Proposals need co-signers to reach the ballot, 2/3 majority to enact, 2/3 to reverse (reversing restores both the service level and its tax delta). Enacted policies execute immediately. All tax rates start at 5% (Assumptions tab) and are bounded 0-25% by any combination of policies.
BUNDLED INFRASTRUCTURE & POLICE POLICIES (move Wage + Sales + Property tax together)
Policy | Effect | Wage/Sales/Property Tax | Notes
Better Roads | Convoy speed +10% | 5% → 6% | Reversible
Less Road Funding | Convoy speed -10% | 5% → 4% | Reversible
New Road Project | Second route exists, harder for pirates to track/predict | 5% → 8% | "Massive" tax increase by design
Police Tier 1 | 60 sec response time, 1 officer | 5% → 6% | No police exist at all until this passes
Police Tier 2 | 45 sec response time, 2 officers (parallel capacity) | 6% → 7% | Cumulative on top of Tier 1
Police Tier 3 | 30 sec response time, 3 officers (parallel capacity) | 7% → 8% | Cumulative on top of Tier 1+2
STANDALONE TAX POLICIES (single tax type, independent of any service)
• | Raise / Lower Wage Tax — ±1% per vote, bounded 0-25%
• | Raise / Lower Sales Tax — ±1% per vote, bounded 0-25%
• | Raise / Lower Property Tax — ±1% per vote, bounded 0-25%
• | Progressive Taxation (toggle) — wage/sales tax scales with agent Net Worth instead of a flat rate for everyone
BOUNTY POLICIES & FORMULA
Higher / Lower Bounties (toggle) | ±50% multiplier applied to all three base bounty amounts below
Crime | Base Bounty | Stacks?
Theft (cargo/pickpocket/till/vehicle) | 25% of stolen value | Yes — each theft adds its own bounty
Murder | 300 Denari | Yes, per instance — 3 murders = 900 Denari total
Sabotage | 150 Denari | Yes — each instance adds its own bounty
CRIME DETECTION — POLICE-WITNESSED ONLY
• | A bounty is only ever confirmed by a POLICE OFFICER witnessing or arriving in time — other agents seeing a crime cannot place a government bounty directly (no 'proof').
• | Any agent can 'Call the police' when a crime occurs, logging a dispatch with location and timestamp.
• | At zero police funding (the default), no bounty is ever possible regardless of witnesses.
• | Once police exist, they must arrive within a 10-minute evidence window from the crime for the bounty to be confirmed. A stale report (police too slow, or busy with another dispatch) means no bounty.
• | Police capacity is parallel by tier (1/2/3 simultaneous dispatches) — a real crime wave can overwhelm a low tier even if its response time looks fine on paper.
• | Player-added bounties (funded directly by any agent, uncapped) still stack on top of any confirmed government bounty regardless of police involvement.
INSURANCE PRODUCTS
Product | Protects | Premium (NPC) | Payout | Notes
Cargo / Vehicle-in-Transit | A single convoy run | 20% of insured value | 70% of insured value | Player brokers can undercut to ~8-12%
Life Insurance | Carried Denari + inventory on death | 20% of declared coverage, paid hourly | 70% of coverage on death | Ongoing policy, not per-trip
Asset Insurance | Ownership of vehicle/property/business on death | 20% of combined insured asset value, paid hourly | Guaranteed retention (in-kind, no Denari payout) | Without it: assets become claimable by others 24 hrs after owner's death unless reclaimed first
An Insurance Brokerage (government-owned by default, player-ownable later) must maintain a cash reserve ≥ 70% of its total outstanding insured value to issue new policies — directly derived from the 70% payout rate, ensuring claims can actually be honored.

---

## World State Schema

World State Schema
The actual data structure every rule in this workbook reads and writes to. Ten entity types, each with the fields an agent's turn (or the daily report generator) needs. This is the reference for building the headless sandbox backend.
1. AGENT
Field | Type / Format | Notes
Agent ID | unique ID
Name | string
Model / Tier | enum | See Combat & Heroes tab — one of the 5 models in the current roster — see Combat & Heroes tab for the exact list and agent counts
Denari Balance | number | Liquid currency on hand
Net Worth | computed | Denari + owned businesses (startup cost) + vehicles (base price) + property (purchase + upgrades) + inventory (base price). THE wealth-ranking metric — agents' goal is maximizing this by hour 120, not liquid Denari alone
Current Location | named location or transit state | e.g. 'The Crossing' or 'en route: Refinery Row→Town at 40%' — see World entity for the location graph
Inventory | list, max 5 units | Same 5-unit cap whether on foot or mounted on a vehicle
Equipped Weapon | item ref
Equipped Armor | 3 slots: Head/Chest/Legs
Owned Vehicles | list of Vehicle IDs
Owned Businesses | list of Business IDs | Agents can own multiple, limited only by startup cost and staffing (see Business entity)
Owned Property | Property ID or none | Max 1
Current Job | business, role, wage | At most ONE personal shift across the agent's entire portfolio at a time
Per-Role Skill Hours | 8 counters (one per wage role) | Cumulative hours worked at that role name, shared across every business of that type — see Wages tab Skill Progression
Reputation / Bounty Status | clean/wanted, total stacked amount, contributing crimes list | Only confirmed via police witness — see Government & Insurance tab
Guild Membership | Guild ID + is-leader flag
Health | 0-100
Alive / Dead + Respawn Timer | boolean + countdown | 60 sec respawn delay — see Combat & Heroes tab
Insurance Policies Held | Life / Asset, coverage amounts | See Government & Insurance tab
Memory Log | significance-tagged event history | Feeds the daily/rollup report generator
2. BUSINESS
Field | Type / Format | Notes
Business ID | unique ID
Name / Type | enum | One of 11 types — see Businesses tab
Owner | Agent ID or 'Government' | Government-owned = always fully staffed regardless of actual employee count (see note below)
Cash Balance | number | Drives the 24-hr bankruptcy grace period. N/A for Government-owned
Employee Roster | list: agent, role, wage
Current Inventory Held | list
Retail Prices Set | per-good price | Player-owned only — NPC businesses use the fixed Assumptions-tab formula
Research State | RP accumulated, tier per track, Quality pool allocation | See Research tab
Active Production State | what's being produced, by whom
Insurance Brokerage Only: Cash Reserve | number | Must stay ≥ 70% of total outstanding insured value to issue new policies
3. VEHICLE
Field | Type / Format | Notes
Vehicle ID | unique ID
Type | enum | One of 6 — see Vehicles tab
Owner | Agent ID
Current Location | named location or transit state
Current Cargo Load | 0 to max capacity | Capacity by type — see Vehicles tab
Condition | functional / damaged / destroyed
Currently Mounted By | Agent ID or none
4. PROPERTY
Field | Type / Format | Notes
Property ID | unique ID
Owner | Agent ID
Location | named location
Garage Tier | 0-3 | Vehicle slot count — see pricing table below
Storage Tier | 0-3 | Unit capacity — see pricing table below
Structures / Upgrades Built | list
Rental Status | rented to whom, if any
5. CONVOY (only exists while active)
Field | Type / Format | Notes
Convoy ID | unique ID
Organizer | Business ID + Agent ID
Status | enum | Recruiting (elapsed time, extension count) / Loading / In-Transit (%) / Arrived / Ambushed / Destroyed / Cancelled
Roster | list: agent, role, vehicle | Driver required per vehicle; Scout/Bodyguard optional
Cargo Manifest | good, quantity, value, owner attribution | Aggregated before departure — convoys never visit individual farms/mines directly
Pay Terms | flat fee + commission per role | Government baseline or custom if a player owns the organizing business — see Convoy tab
Vehicles Used | count | Max 10
Event Log | this run only | Feeds the daily report
6. MARKET
Field | Type / Format | Notes
Listed Price | per good, per business | Player-owned only — NPC follows the fixed Assumptions formula
Transaction Log | list | Feeds price-trend reporting
7. GUILD
Field | Type / Format | Notes
Guild ID | unique ID
Name | string
Leader | Agent ID | Can remove any member
Member List | list of Agent IDs | Uncapped size
Chat Log | list | Private to members
8. BOUNTY
Field | Type / Format | Notes
Target Agent ID | Agent ID
Total Stacked Amount | number | Sum of every confirmed crime bounty against this agent, plus player contributions
Contributing Crimes | list: type, base amount, timestamp, police-confirmed flag | Theft 25% of value / Murder 300 (stacks per instance) / Sabotage 150 — see Government & Insurance tab
Player-Added Contributions | list: contributor, amount | Uncapped
Status | active / paid
9. GOVERNMENT
Field | Type / Format | Notes
Current Tax Rates | Wage % / Sales % / Property % | Start at 5% each, bounded 0-25% — see Assumptions tab and Government & Insurance tab
Active Policies Enacted | list, typed | Bundled infrastructure/police (moves all 3 taxes together) / standalone tax nudge / bounty multiplier
Police Tier | 0-3 | Current dispatch capacity and response time — see Government & Insurance tab
Treasury Balance | number | Tracked for reporting only — enacted policies are funded by the ongoing tax RATE, not by drawing this down
Active Proposals | proposer, co-signers, vote tally, status | Needs co-signers to reach ballot, 2/3 to enact
Policy History | enacted/reversed log | 2/3 to reverse — restores both service level and tax delta together
10. WORLD
Field | Type / Format | Notes
Simulation Clock | hour 0-120 | Real time, no compression
Government-Owned Businesses | fixed list, one per type | Exist from hour zero, always fully staffed regardless of real hires — agents are expected to recognize they can undercut them
Global Event Log | raw feed | Source for daily + rollup reports
Named Location Graph | Refinery Row, North Protected Zone, The Hills, The Crossing, The Climb, South Protected Zone, Town | ~5 min full transit at Medium speed. Offshoot spur roads (30-60 sec, dead-end loops back to the same point) connect individual mines/farms/homes — convoys never use these, only individual solo trips do
GARAGE & STORAGE UPGRADE PRICING (referenced by Property entity)
Item | Cost | Capacity | Inputs
Property Plot (base) | 500 | 20-unit storage, 0 garage slots included | —
Garage Tier 1 | 200 | 1 vehicle slot | Stone + Wood
Garage Tier 2 (cumulative) | 450 | 2 vehicle slots | Stone + Wood + Bronze
Garage Tier 3 (cumulative) | 800 | 3 vehicle slots | Stone + Iron + Wood
Storage Tier 1 | 150 | +50 units (70 total) | Stone + Clay
Storage Tier 2 (cumulative) | 350 | +100 units (170 total) | Stone + Clay + Wood
Storage Tier 3 (cumulative) | 700 | +200 units (370 total) | Stone + Clay + Iron
AGENT ENTITY — ADDITIONAL FIELDS (Sustenance, added after initial schema)
These belong to the AGENT entity (section 1, earlier in this tab) — appended here rather than inserted mid-table to avoid disturbing existing rows. See Sustenance tab for the full mechanic.
Field | Type / Format | Notes
Hours Since Last Meal | counter, real hours | Resets to 0 on eating any meal
Current Sustenance Stage | Normal / Hungry / Starving | Derived from Hours Since Last Meal vs. the last-eaten meal's window — see Sustenance tab
Last Meal's Sustenance Window | 12-30 hrs | Set by meal tier eaten (self-prep/base = 12, up to Legendary Bread = 30) — see Sustenance tab

---

## Combat & Heroes

Combat Resolution & Hero Model Roster
No hardcoded hit-chance percentage. Combat resolves in ~6-SECOND ROUNDS — both agents commit to one choice that holds for the whole round, and the weapon's real Attack Speed stat determines how many swings land inside that round. COMBAT DECISIONS SPECIFICALLY ROUTE THROUGH EACH AGENT'S FAST/NON-REASONING FALLBACK (GPT-5.6 Luna or Grok 4.3, both non-reasoning, ~3.5-5s response), regardless of which model that agent normally uses for economic decisions — every other decision type stays on the agent's full assigned model, since only combat has a tight latency requirement. TREAT 6 SECONDS AS A PROPOSAL, NOT FINAL — verify real round-trip latency for the fallback models during Phase 2 before locking it in.
COMBAT RESOLUTION — ZONE-BASED, SIMULTANEOUS CHOICE
• | Each exchange occurs on the ATTACKER's weapon Attack Speed interval (see Weapons tab).
• | ATTACKER chooses a Target Zone: High / Center / Low — no visibility into the Defender's choice that exchange.
• | DEFENDER simultaneously chooses a Reaction: Block-High / Block-Center / Block-Low / Dodge / Counter-Attack.
Defender's Choice | vs. Attacker's Target Zone | Result
Block (matching zone) | Same zone as attack | Fully blocked — 0 damage
Block (wrong zone) | Different zone than guarded | Full damage lands
Dodge | Any zone | Fully evaded — 0 damage, but Defender forfeits their own attack this exchange
Counter-Attack | Any zone | No defensive bonus — both agents' attacks land simultaneously (a genuine trade)
Damage, Attack Speed, and Headshot/Backstab multipliers per weapon are on the Weapons tab and apply whenever a hit lands under this resolution. Armor's damage reduction (Armor tab) applies multiplicatively on top of whatever raw damage lands.
RESPAWN
• | 60 second respawn delay on death.
• | Spawns at the agent's own Property, if they own one.
• | If no owned Property: spawns at Town (Town Square, near the Stores).
• | Carried inventory/Denari is lost at the death location (lootable by others) unless Life Insurance is held — see Government & Insurance tab for the 70% payout.
• | Owned vehicle/property/business ownership is unaffected by death UNLESS uninsured and left unclaimed for 24 hours (Asset Insurance rule).
AGENT POPULATION & MODEL ROSTER
75 agents total, 15 per model, running 120 real hours nonstop (no time compression) for the validation sandbox — a smaller, cheaper population than the eventual full content-generation run, but large enough that all 11 business types have a real chance at genuine player-owned competition, not just the lone NPC version. All 5 models accessed through OpenRouter (one account, one API key). Note: 'low/medium/xhigh/max' labels are REASONING-EFFORT PARAMETERS on the underlying model, not separate model IDs — set via the API request, not the model string. One slot (Grok 4.3) is a deliberately weak, fast, cheap baseline included on purpose — see Role column.
Model | Agents | Rate (per MTok) | OpenRouter ID (verify at build time) | Role in Test
GPT-5.6 Terra (high) | 15 | $5 / $30 (high effort) | openai/gpt-5.6-terra | High-intelligence anchor — Intelligence 50, ~half the cost and half the response time of Opus 5 (low) for nearly identical intelligence. Strict upgrade.
Ling 3.0 Flash | 15 | $0.04/task (exact input/output MTok split not available — verify on OpenRouter listing) | inclusionai/ling-3.0-flash | Second deliberately weaker/cheap/fast baseline — Intelligence 38, complements Grok 4.3 (Intelligence 25) as a second lower-capability comparison point, since GPT-5.6 Terra and DeepSeek V4 Flash already cover intelligence in this roster. 404 tokens/s median, 8.19s total response.
DeepSeek V4 Flash 0731 (max) | 15 | ~$0.03/task equiv. | deepseek/deepseek-v4-flash | Intelligence 52 at a fraction of Opus's cost — best value in the roster
Grok 4.3 (Non-reasoning) | 15 | $1.25 / $2.50 | x-ai/grok-4.3 | DELIBERATE WEAK BASELINE — Intelligence 25, fast and cheap, included specifically to see how a clearly weaker model performs against the other four
GPT-5.6 Luna (medium) | 15 | $0.20 / $1.20 | openai/gpt-5.6-luna | Best overall value in the full comparison table — cheap, fast, solid mid-tier intelligence (39)
Cost estimate: see Agent Scheduling & Diary tab — decision frequency is now event-driven with a universal 15-minute re-evaluation checkpoint, so cost is usage-dependent rather than a single precise number. The old $144/$94 figures (75 agents, 120 hours) should be treated as a rough reference point, close to but not precisely the real figure. Exact OpenRouter model-ID strings should be verified against the live catalog before building — naming and pricing can shift as providers update.
Background population note: at this 75-agent validation scale, every agent runs a real model — there is no separate cheap rule-based tier the way the original 100-agent content-generation design used. The 5-hero, camera-focused, high-effort flagship roster (for streaming/marketing) is a SEPARATE later run, not this one.
COMBAT ROUND MECHANICS — SWINGS PER ROUND
Swings landed in one round = ROUND LENGTH ÷ Weapon Attack Speed (rounded down). Both fighters hold their Target Zone / Reaction choice for every swing in the round — one correct-or-wrong read is repeated, not re-decided per swing. A faster weapon means MORE swings riding on that single read, not more decisions.
Weapon | Attack Speed | Swings per 3-sec Round
Bronze Dagger / Iron Dagger | 0.4s | 7
Bronze Sword / Iron Sword | 0.6s | 5
Wooden Spear | 0.7s | 4
Bronze-Tipped / Iron-Tipped Spear | 0.75s | 4
Sling | 0.8s | 3
Bow | 0.85s | 3
Slingshot | 0.9s | 3
CONVOY AMBUSH — DRIVER'S THREE-WAY CHOICE
When a convoy is ambushed, Guards/Bodyguards enter the round-based combat loop above directly — that's their job. Each vehicle's DRIVER instead gets a real three-way choice, decided independently per vehicle (a 10-vehicle convoy can fragment under attack, with different Drivers choosing differently):
Choice | Effect
Fight | Driver joins combat directly using the round mechanic above, same as a Guard — vehicle stops moving.
Push Through | Vehicle keeps moving toward its destination at normal speed. Driver takes FULL, UNMITIGATED combat damage each round — no defensive reduction of any kind. Prioritizes cargo delivery over survival, full stop.
Flee Off-Road | Vehicle leaves the road at 50% speed (existing off-road rule). Unpredictable but slower, likely reduces Scout tracking effectiveness since Scouts watch the road, not open terrain.

---

## Agent Scheduling & Diary

Agent Decision Scheduling & Hourly Diary
Every agent's underlying objective is always maximizing Net Worth. Decisions trigger two ways: IMMEDIATELY on task completion or an interrupt, and on a UNIVERSAL 15-simulated-minute re-evaluation checkpoint that applies to every agent regardless of current activity — not just idle ones. This replaces the earlier 'idle-only heartbeat' concept, which missed a real scenario: an agent 20 minutes into a 2-hour mining commitment needs a real chance to notice a much better convoy job posting, not just wait for mining to finish on its own. The underlying world clock still runs continuously in true real time (no compression); this only governs how often an AGENT gets a fresh decision point, not any time-based game rule.
WHAT TRIGGERS A NEW DECISION
• | Current activity concludes — a mining/farming/refining session ends, travel arrives at its destination, a craft finishes. A 4-hour mining session is ONE decision followed by silence until it resolves, not repeated check-ins.
• | An interrupt occurs — the agent is attacked, robbed, witnesses a crime, is invited to a convoy, or a vote opens that affects them.
• | A short errand naturally chains — travel to town, buy an item, equip it can all happen back-to-back within a minute, each a real fast decision, with no artificial gap enforced between them.
• | Universal 15-minute re-evaluation checkpoint — EVERY agent, regardless of current task, gets a 'is what I'm doing still my best move, given anything new?' check every 15 simulated minutes. This can run as a lightweight, cheap check through the agent's fast fallback model (continue current task: yes/no) rather than a full expensive reasoning call every time — it only escalates to a full re-plan when the answer is genuinely 'no, something better exists now.'
HOURLY DIARY
Every agent writes a SHORT reflection every simulated hour, regardless of what else happened — even a 'mining, nothing notable, 3 hours left' entry during a long passive stretch. This is a SEPARATE, fixed-cadence call — it does not replace or compete with a real game decision, and it is the backbone the daily/rollup report generator draws from, so reports don't have to reconstruct a narrative from a ragged, variable-density action log. Feeds the Agent entity's Memory Log field (World State Schema tab).
COST IMPACT — NO LONGER A FIXED FORMULA
The universal 15-minute re-evaluation checkpoint brings real cost estimates back CLOSE TO the original $144 uncached / $94 cached ceiling (75 agents, 120 hours) — NOT clearly below it, correcting an earlier claim in this design process that event-driven scheduling would obviously undercut that number. What keeps cost reasonable is that most 15-minute checkpoints can be a lightweight, cheap continue-or-replan check via the fast fallback model rather than a full reasoning call every time, only escalating to the agent's full assigned model when something genuinely changed. Treat the real figure as something the validation run itself will reveal.

---

## Sustenance

Sustenance — Eating, Status Effects & Death
Every agent must eat periodically or suffer escalating penalties, then death. Two paths: SELF-PREP (free, DIY, Grain + Water consumed directly from own inventory, always resets to the 12-hour base window) or a TAVERN MEAL (costs money, can be a higher Research tier for a longer window). Rest is NOT a separate mechanic — Sustenance is the only survival system.
SUSTENANCE WINDOW — HOW LONG ONE MEAL LASTS BEFORE PENALTIES BEGIN
Meal Type | Duration | Price
Self-Prep (Grain + Water, own inventory) | 12 hrs | Free
Base Tavern Meal (no Research) | 12 hrs | $10
Tier 1 Bread | 15 hrs | $15
Tier 2 Bread | 18 hrs | $22
Tier 3 — Fine Bread | 21 hrs | $30
Tier 4 — Masterwork Bread | 24 hrs | $40
Tier 5 — Legendary Bread | 30 hrs | $55
STATUS ESCALATION — FIXED 12-HOUR STAGES ONCE THE WINDOW RUNS OUT
The window (12-30 hrs depending on meal tier eaten) determines how long an agent stays at Normal status. Once it expires, the escalation stages themselves are FIXED at 12 hours each regardless of meal tier — a higher tier buys a longer safe window, not slower decay once hungry. Eating any meal, of any tier, resets the timer to 0 and re-applies that meal's window.
Stage | Duration | Effect
Normal | 0 to [meal's window] | No penalty
Hungry | Next 12 hrs after window expires | -10% production/combat speed
Starving | Next 12 hrs after that | -25% speed, -5 HP once on entering this stage
Death | After Hungry + Starving fully elapse | Standard respawn — 60 sec delay, spawn at owned Property or Town, inventory lost unless Life Insurance held
WORKED EXAMPLE
An agent eats Tier 4 Masterwork Bread at hour 10. They stay Normal until hour 34 (10 + 24-hr window). If they don't eat again, Hungry runs hours 34-46, Starving runs hours 46-58, and they die of starvation at hour 58 if still unfed. Eating ANY meal at any point during this resets the clock to a fresh window.
