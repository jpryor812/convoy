# Phase 1 — Core Engine, Zero LLM Calls

Status: **complete, ready for review.** No API calls of any kind.

```bash
python3 run_phase1.py            # 48 game-hours, 10 agents, ~0.3s wall clock
python3 tests/test_conformance.py
```

Outputs land in `runs/phase1/`: `events.jsonl` + `events.csv` (raw timestamped
log of every event, ~20.8k rows) and `state.json` (checkpoint).

## What's built

| Module | Contents |
|---|---|
| `convoy/data.py` | Every value transcribed from the workbook; derived figures computed from the Assumptions levers, not hardcoded |
| `convoy/state.py` | The 10 World State Schema entities as dataclasses |
| `convoy/economy.py` | Pricing, staffing/output math, wages, taxes, sustenance, net worth, travel, convoy pay, insurance |
| `convoy/actions.py` | The executable action layer — movement, labor, refining/crafting, trading, business management, survival |
| `convoy/engine.py` | Clock, continuous processes, decision scheduling (event-driven + 15-min re-evaluation), hourly diary |
| `convoy/rule_agents.py` | Deterministic Phase 1 policies |
| `convoy/checkpoint.py` | Atomic state save/load |

The engine talks to a `Policy` protocol with one method, `decide(world, agent,
reason)`. Phase 2 swaps the rule-based policy for an OpenRouter-backed one
behind that same interface — no engine changes.

## Verification

`tests/test_conformance.py` — 24 test groups, all passing. Each asserts a number
the workbook states explicitly, so a rebalance that isn't mirrored in code fails
loudly:

- Diminishing-returns table exactly (n=1→1.000x … 19→7.547x … 30→6.778x), and
  that output peaks at n=19–20
- Refinery worked example: 3 workers → 13.54 Iron/hr each, 40.6/hr total, ~$893/hr gross
- All 24 Production Chain Input Cost figures (this is what pins recipe quantities at 1)
- NPC buy/sell prices across all four markup rates
- All 8 wage rows (NPC / smart / floor) and the 5 skill tiers
- Research tiers and the "19 researchers → Tier 5 in ~58h" tension the tab calls out
- Sustenance windows, prices, penalties, and the tab's worked example
  (T4 bread at h10 → Hungry h34, Starving h46, death h58)
- Convoy worked example (driver 28.5, scout 12.5, bodyguard 14.3 on 1800 cargo)
- Hits-to-kill, swings-per-round, full armor set totals (−40% Bronze, −55% Iron)
- Progression Math hours, Net Worth definition, carrying capacity, taxes, insurance

`tests/test_staffing_load.py` — live-engine load test. Staffs one business with
n real agents on shift, runs an hour of simulated time, and compares measured
output against the Businesses tab. Reproduces the whole curve exactly (n=1 →
72/hr through n=19–20 → 543.4/hr and back down to n=30 → 488/hr), confirms the
peak is real and that output *declines* past it, and confirms the Hungry penalty
lands at exactly 90% through the real engine. This is the distinction the
conformance suite can't make: a correct formula applied to the wrong headcount
would still pass there.

Scale-tested at the real roster size: **75 agents, 48 game-hours, 1.2s wall
clock**, invariants clean — Phase 3 scaling is derisked before any money is spent.

Runtime behaviour confirmed in the log, not just asserted:

- **Sustenance escalation lands exactly on the spec.** The `never_eats` control
  goes Hungry at h12.00, Starving at h24.02 (HP 100→95), dead at h36.02.
- **Bankruptcy grace is exactly 24.00h** from warning to closure, across 9 businesses.
- **Checkpoint round-trips** the full nested object graph at hour 48.

Invariants asserted at end of run: no negative Denari, no phantom inventory, no
over-capacity carrying, no employment by a closed business, no negative treasury
or health, and — per the handoff — no starvation death without Hungry *and*
Starving warnings logged first.

## Resolved contradictions

Confirmed with the designer; each is marked in `data.py` where it applies.

1. **Staffing** — Businesses tab governs (uncapped, 0.95^(n-1)). The Assumptions
   rows "Employee Speed Bonus 0.4" / "Max Employees 3" are stale and unused;
   they're kept as `*_UNUSED` constants so the divergence is greppable.
2. **Carrying** — Vehicles tab governs. 5 units on foot, vehicle capacity mounted.
   The World State Schema's "max 5 whether on foot or mounted" is stale.
3. **Recipes** — 1 unit per input unless stated (Camel, Horse). Verified against
   all 24 Input Cost figures.
4. **Bootstrap** — no free public nodes. Government businesses (one per type,
   always staffed) are the hour-zero employer and convoy organizer.

## Designer decisions of 2026-08-11 (now live in code)

These change live rules, so **the spreadsheet needs the same edits** or the two
will drift. `tests/test_conformance.py` pins every one of them.

| # | Decision | Spreadsheet edit needed |
|---|---|---|
| 1 | **Repricing for ≥75% margins.** Only 3 goods failed the bar; every final good already cleared it. Tanned Leather 7→**9**, Bronze 18→**32**, Iron 22→**36**. Iron stays above Bronze despite cheaper inputs, preserving the Rare/Uncommon ordering. | Resources tab, Base Price column |
| 2 | **Government pays the Smart Player Wage**, not the NPC wage — leaving headroom for player businesses to outbid the state. | Wages tab note |
| 3 | **Owners draw no wage** from their own business; they're paid by output and profit. | Businesses tab note |
| 4 | **Raw materials auto-ship to factories.** No hauling leg for production inputs; a business buys what it lacks at *base* price from its own cash, which is exactly the Production Chain tab's Input Cost basis, so the designed margins hold. | Production Chain note |
| 5 | **New death rules**, replacing the 24-hour claimable-asset rule: carried inventory and Denari drop at the death location for anyone to take; off-person assets (businesses, vehicles, property) are retained with Asset Insurance and **destroyed outright** without it. | Government & Insurance tab |
| 6 | **Combat has no round length and no fallback model.** Every agent fights on its own assigned model, and Attack Speed is a real-time interval — an agent acts as fast as it reacts. The swings-per-round table is dead. | Combat & Heroes tab |
| 7 | Spreadsheet hygiene: delete the stale Assumptions staffing rows, correct the Inventory field note, remove the Rest action. | Assumptions / World State Schema / Actions |
| 8 | **Researchable food variants** (2026-08-12). The Sustenance tab gave Food one axis — duration. Added the other two, so Food behaves like every other Research category: a tier grants a pool, the Tavern chooses the axis. `Hearty Bread T1–T5` heal 5/10/15/20/25 HP; `Laborer's Bread T1–T5` give +5/10/15/20/25% production speed for the meal's duration. All keep the 12h base window and the same Grain + Water recipe. | Sustenance tab, new variant rows |
| 9 | **Quality Bonus Stat Pools are now enforced** — allocations are validated against the category's available stats and cannot exceed the tier's pool. | none (was transcribed but unwired) |
| 10 | **Chat system** (2026-08-12): three channels — open **world**, one-to-one **direct**, and invite-only **guild**. Reading is ambient context every turn per the Actions tab; only posting is an action. Guilds cannot be joined without an invite, and leaving cuts off guild history immediately. | Actions tab already lists these |
| 11 | **Research is player-only.** Government businesses can never hire a Researcher or unlock a tier, so the state can't out-research the market it exists to backstop. | Businesses tab note |
| 12 | **Player-to-player trade.** Requires co-location. Tradeable pool = what you carry, plus a vehicle's hold or your home's storage **if either is at the same location** — so where a deal happens matters, and carts/homes gain a second purpose. Sales tax applies as on any sale. Stolen goods are **not** restricted to P2P: they can be fenced at stores too, so piracy pays. | Actions tab, black-market note |
| 13 | **General Store stays.** It is the only NPC seller of every raw resource, including the Water and Grain that 19 and 18 recipes depend on. It is already the "Trading Post" the Assumptions tab refers to; it just wasn't labelled. | label it Trading Post / General Store |
| 14 | **Upgraded Tools now do something** — +25% raw extraction speed while equipped, applying to Mining Operations and Farms only (matching the Equipment Store's name), stacking additively with skill and Research Efficiency. Bonus size is a stated assumption; the *existence* of the effect is what the Resources tab already claimed. | Production Chain note |
| 15 | **Property upgrades are now a real transaction.** Garage and storage tiers were fully specified on the World State Schema tab but had no implementing action. Each tier charges the cumulative-cost **delta** plus that tier's raw materials. A **Property Upgrade kit** from a Home Improvement Store substitutes for a tier's whole material bill — a poor deal at Tier 1 (materials cost 5) and fair at Tier 3 (41 with Iron), which finally gives that store a customer. | none |
| 16 | **Wool commented out** — the Resources tab fed it to "Clothing/cosmetics", which doesn't exist and isn't needed for this build. One line in `data.py`, restore when clothing is designed. | Resources tab |
| 17 | **The world** (`convoy/world_map.py`). Seven places on one road with elevation and terrain; six segments each carrying their own concealment / vantage / exposure; two protected waystations plus Town where combat and theft are impossible; eight spur roads 90 seconds deep holding 40 plots each. Production sits north, market sits south, so goods must cross all three dangerous segments to reach a buyer. | World tab, location graph |
| 18 | **Plots are land, not slots.** A starter home takes 4 plots (+1 per storage or garage tier), a starter mine or farm takes 8 (+4 per expansion at 250 Denari). 320 plots exist in total; the state's mine and farm take 16. Mines and farms exist only down spurs; every other business sits on the main road. | World State Schema |
| 19 | **Sites stockpile finitely** — 30 units of yard per plot, so a starter site holds 240. When the yard fills, production stalls until someone hauls it away. This is what makes carts, expansion, and distance-to-market matter. | none |

**Consequence of #6 worth watching:** combat becomes partly a latency contest. A
high-effort reasoning model that takes 8s to answer gets out-swung by a 1s model
regardless of tactical quality. That's a real roster finding rather than a bug,
but it means combat results and economic results measure different things.

## Stated assumptions — flagged, not silently chosen

Each is a spot the workbook doesn't specify. All are one-line changes in `data.py`.

- **Combat round = 3s, not 6s.** Prose says "~6-SECOND ROUNDS", but the
  swings-per-round table is computed at 3s and only reconciles at 3s. Phase 3.
- **Sales tax incidence**: buyer pays on top, seller remits, NPC and player alike.
- **Vehicle speeds**: the tab gives adjectives plus one anchor (~5 min full
  transit at Medium). Mapped to 0.5/0.75/1.0/1.5/2.0.
- **Location graph**: 7 locations as a linear chain, protected zones bracketing
  the hazardous middle; 50s per edge at Medium.
- **Crafting throughput**: no stated rate for final assembly; using 15/hr, the
  refining rate.
- **Respawn resets hunger** to a fresh 12h window — otherwise an agent respawns
  already starving and dies in a loop.
- **Hungry/Starving penalty** applies to production and combat only, per the
  tab's wording — not travel.
- **Bankruptcy resolution**: inventory liquidates at NPC buy price, proceeds
  settle debt then go to the owner, employees released.
- **Rest**: the Actions tab still lists a Rest action, but the Sustenance tab
  says "Rest is NOT a separate mechanic." Treating Rest as a no-op.

## Economic findings from the current run

Outputs of the run, not bugs — the kind of thing Phase 1 exists to surface.

1. **Owners with no wage can starve holding valuable stock.** The manufacturer
   archetype spent down to 4.5 Denari founding its store, then went Hungry at
   h44 because an owner draws no salary and its 17 finished Property Upgrades
   (≈850 Denari of stock) weren't liquid. Correct per the new rules, and a real
   dynamic: owners must *sell* to eat. Worth watching whether LLM agents manage
   the cash-flow gap or walk into it.
2. **The Iron refinery margin got larger, not smaller.** The workbook already
   flagged ~$893/hr gross for 3 refinery workers as a risk; at Iron 36 that's now
   ~$1,462/hr against ~113/hr of wages. Refineries are extremely profitable — which
   is what drives competition, but it's the number most likely to need another pass.
3. **Bootstrap roughly halved in speed**, as intended: the government wage drop
   from NPC to Smart pushed first-business founding from ~h7 to ~h15. Agents still
   comfortably fund a Farm well inside 48 hours.
4. **Death is currently cheap for carried goods.** The starved agent respawned and
   walked back to loot its own drop 6 minutes later. Mechanically correct — anyone
   may take it — but if you want death to sting, the drop needs a decay timer or a
   respawn far from the corpse.
5. **The state is a net money printer, and it worsens with population.**
   Government goods output is byte-identical at 10, 25 and 75 agents (Mining
   1,727 / Farm 3,455 / Refinery 720 — 20,152 Denari of value in every run),
   because "always fully staffed" is implemented as a fixed one-worker rate. The
   government *wage bill*, however, scales linearly with headcount:

   | agents | Denari the state creates | goods it makes | ratio |
   |---|---|---|---|
   | 10 | 5,678 | 20,152 | 0.28 |
   | 25 | 13,855 | 20,152 | 0.69 |
   | 75 | **42,246** | 20,152 | **2.10** |

   At the real roster size the state prints 2.10 Denari for every 1 Denari of
   goods it produces. **Recommendation:** keep "always staffed" as a floor so the
   market never breaks at zero hires, but let player hires add output on top via
   the normal decay curve — which also fits the tab's wording better, since
   "fully staffed" guarantees a minimum rather than capping output at one worker.
   One-line change; not blocking Phase 2.

   *Correction to an earlier draft of this doc:* this does **not** distort the
   Net Worth ranking. Net Worth per agent is flat across population sizes
   (663 / 673 / 666 at 10 / 25 / 75), because every agent has equal access to the
   faucet. The problem is absolute currency supply, not relative standing.

6. **Hauling capacity is what gates entrepreneurship — the most interesting
   finding in the run.** A Farm produces 72 units/hour; on foot an agent can move
   5 units per trip, so ~93% of output strands at the farm. Measured over 48
   hours:

   | strategy | Net Worth | stranded stock |
   |---|---|---|
   | wage labour only | 1,043 | 0 |
   | found a Farm, travel on foot | 588 | 888 |
   | found a Farm, buy a 225-Denari Camel | **1,065** | 303 |

   So running a business is *worse than a government job* until you buy a pack
   animal, at which point it wins. That makes the cheap early vehicle the real
   unlock of the early game — a nice piece of emergent structure that nobody
   designed explicitly, and a genuine test of whether an agent reasons its way to
   it. Worth watching specifically in Phase 3.

## Spreadsheet coverage — transcribed vs. wired

All 19 tabs are transcribed. "Wired" means the numbers actually drive mechanics
rather than sitting in `data.py` as unused constants.

| Tab | Transcribed | Wired | Note |
|---|---|---|---|
| Read Me First / Master Overview | n/a | n/a | orientation, no rules |
| Assumptions | yes | yes | two stale staffing rows deliberately unused |
| Resources | yes | yes | repriced per decision #1 |
| Production Chain | yes | yes | all 24 input costs asserted |
| Research | yes | yes | RP accrual, tier costs, allocation, material burn, stat pools |
| Armor / Weapons / Vehicles | yes | partial | prices and capacities live; combat stats await Phase 3 |
| Businesses | yes | yes | decay curve verified live n=1..30 |
| Wages | yes | yes | all 8 roles incl. Researcher (75 / 33.33 / 16.67) |
| Progression Math | yes | yes | asserted against the tab |
| Actions | yes | partial | economic subset live; convoy/combat/crime/politics are Phase 3 |
| Convoy | yes | formulas only | pay formula asserted; no convoy loop until Phase 3 |
| Government & Insurance | yes | partial | taxes live; bounty/police are Phase 3 |
| World State Schema | yes | yes | all 10 entities |
| Combat & Heroes | yes | roster only | combat superseded by decision #6, built in Phase 3 |
| Agent Scheduling & Diary | yes | yes | event-driven + 15-min re-eval + hourly diary |
| Sustenance | yes | yes | escalation verified; variants added per decision #8 |

Known unwired constants: `POLICE_TIERS`, `BOUNTY_MURDER`/`BOUNTY_SABOTAGE`
(Phase 3 by plan) and `SPEED_MULTIPLIERS` (redundant — the values are inlined on
each Vehicle record).

## Not built yet (by design)

Convoys, combat, theft, bounty enforcement, government voting, guilds, and
property upgrades have data structures and formulas in place but no agent-facing
loop — those are Phase 3. The diary is a placeholder string; Phase 4 makes it a
real model call.
