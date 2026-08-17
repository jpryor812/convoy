# Phase 4 — consent, a labour market, and the full chain

Status: **the economy runs end to end under live models and no longer eats itself.**
On 2026-08-17 player businesses mined ore, refined it into Bronze and Iron, and
forged Bronze Daggers — every tier player-owned. 23 businesses were founded, 21
survived, and **not one went bankrupt** across ~40 insolvency events in three runs.

This supersedes PHASE3.md, PHASE2.5.md, PHASE2.md and PHASE1.md.

> **Ignore `convoy_bronze_age_economy.xlsx` and `convoy_reference.md`.** Both are
> 2026-08-12 snapshots, and `convoy_reference.md` states in its own header that
> the spreadsheet is authoritative — which is wrong and reads as current.

---

## 1. Where the truth lives

| what | file |
|---|---|
| Prices, recipes, wages, production times | `convoy/data.py` |
| Who may buy from / work for whom, escrow, hiring | `convoy/actions.py` |
| Production, payroll, solvency, haulage, taxes | `convoy/engine.py` |
| What agents are told | `convoy/observe.py` |

**Run `python3 run_phase1.py` after ANY change to `data.py`.**

---

## 2. The lesson, now at twelve

Almost every "the agents are being stupid" moment has been **the observation
failing to say something the code already knew.** Twelve documented:

| symptom | cause |
|---|---|
| every meal attempt failed | tavern in the wrong place in the briefing |
| 9 of 13 job applications rejected | agents never told which roles a business hires |
| everyone took the lowest-paid job | the wage table wasn't in the briefing |
| 15 vehicles bought, none used | `mount` needs an id the observation never carried |
| B2B unusable on arrival | seller ids only visible on-site |
| nobody founded anything for four runs | affordance line said only what could NOT be built |
| nobody founded even when told they could | a business's VALUE was never explained |
| a courier claimed two jobs, delivered neither | claimed jobs vanished from the courier's own view |
| 543 refusals, 36.8% of all actions | agents knew the 2-per-business cap, not which sites were full |
| a tavern idle 16h after founding | a new business reported zeros, never "you are making nothing" |
| four taverns bought 156 denari of unusable Dirty Water | stall message said "no feedstock" while stock sat visible, never naming the gap |
| **an owner sat on 4 applicants for 12h and let the advert lapse** | **the call-to-action read `hire_applicant('J0090', '<agent id>')` — a literal placeholder** |

The last two were written by the agent fixing the other ten. Being *technically
present* in a 30-line briefing block is not the same as being *present at the
decision*.

**When agents behave badly, suspect the observation before the model.**

---

## 3. The chain, and the rules that hold it together

```
farm / mine  ->  refinery  ->  shop  ->  person
```

Enforced on **both** doors — remote ordering (`order_from_business`) and
over-the-counter sale (`sell_to_business`):

| buyer | may buy from |
|---|---|
| Farm, Mining Operation | nothing — extraction has no inputs |
| Refinery | Farm, Mining Operation, other Refineries (Bronze/Iron need Charcoal) |
| every shop | **Refinery only** |

A player business also refuses items it cannot use. **The state buys anything**,
so nothing is unsellable.

### Employment requires the owner's consent

`apply_for_job` works at **government businesses and your own** only. To employ
anyone else you must advertise:

```
post_job(business, role, wage)   -> world chat + the board, lapses after 12h
apply_to_job(posting_id)         -> the owner still decides
hire_applicant(posting_id, agent)
close_job(posting_id)
```

Before this rule, `apply_for_job` appended straight to any player business's
roster at a wage the owner never set. On 2026-08-17 that bankrupted six of seven
businesses inside the first simulated hour — agents with no state job walked into
zero-cash businesses, became a 28.89/hr liability, went unpaid, walked, and walked
back in. One pair repeated it more than a dozen times. **That run was killed and
restarted.** With consent enforced: **47 player-business hires, zero walk-ins.**

### The state is a backstop, not a participant

Government businesses hold every good at their listed price, always, without
couriers, and produce without consuming inputs. This is deliberate — the state
tavern is where most agents eat. The state buys at **0.4x** base and sells at
**1.4–1.5x**; that spread is the entire space player trade lives in.

---

## 4. Prices, times, wages

`hours_per_unit = CRAFT_TIME_COEFFICIENT × base_price^0.927`, with
**`CRAFT_TIME_COEFFICIENT = 0.0074`** (was 0.0296 until 2026-08-16 — at the old
rate a Refinery Worker produced ~18.7/hr of value against a 37.78 floor, so every
refinery lost money on every worker and only `--time-scale 0.2` hid it).

| good | per unit | units/hr |
|---|---|---|
| Purified Water | 0.8 min | 71.1 |
| Grain, Lumber, Charcoal | 1.6 min | 37.4 |
| Meal | 6.5 min | 9.3 |
| Bronze | 11.0 min | 5.4 |
| Iron | 12.3 min | 4.9 |
| Bronze Sword | 74 min | 0.81 |

**Extraction is off this curve** and keeps its own rates (Wheat 72/hr, ores 36/hr).
No inputs means its value added is its whole revenue — the highest-margin tier.

`SMART_WAGES` is the source; `NPC_WAGES = SMART × 1.50` (was 2.25).

| role | state | player floor | NPC |
|---|---|---|---|
| Store Clerk | 15.00 | 17.78 | 26.67 |
| Miner | 20.56 | 28.89 | 43.33 |
| Blacksmith | 23.89 | 35.56 | 53.33 |
| Refinery Worker | 25.00 | 37.78 | 56.67 |

Founding: Farm 150 · Mining 175 · Tavern 200 · Home Improvement 250 · Equipment
275 · Stable 300 · Weaponsmith 350 · Refinery 450. Agents start with **200**.

---

## 5. Payroll and solvency

**A business can never hold negative cash.** Before 2026-08-16 `_pay_wages` ran a
bare `cash -= gross`, and a 96-hour run's leading agent finished ranked 1,375
while owning two businesses 2,852 in the red.

- **NPCs are paid only while the business can actually produce.** No feedstock or
  a full yard stops the meter. Three NPCs in an empty refinery once cost 2,124 in
  11 simulated hours.
- **Agent employees are paid for every hour they work**, feedstock or not — the
  risk sits with the owner who hired them. Gating their pay too would make a
  player job strictly riskier than a state job, since state businesses always
  produce, and all labour would go to the state.
- **Cash floors at zero**; the unpaid worker leaves.
- **Missing payroll starts a 24h clock**, cleared by holding one hour of the
  payroll that was missed — captured *before* the staff walked, so firing
  everyone can't clear it.
- **The owner is told**: the amount owed, the countdown, and payroll per hour.

Valuation is `startup_cost + 3 × last-24h revenue + cash + inventory`.

**Result: ~40 insolvency events across three runs on 2026-08-17, zero
bankruptcies.** The floor caught every one.

---

## 6. What the 2026-08-17 runs showed

**Final run: 20 agents, 84 simulated hours, $2.64, 6,916 calls, 1 network error.**

| | 96h (pre-fix) | 72h | 48h | 84h (final) |
|---|---|---|---|---|
| businesses founded | 18 | 13 | 5 | **23** |
| bankruptcies | 7 | 0 | 0 | **0** |
| businesses in debt | 4 | 0 | 0 | **0** |
| deliveries | 24 | 39 | 17 | **134** |
| chat messages | 111 | 35 | 30 | **218** |
| walk-in hires at player businesses | n/a | n/a | n/a | **0** |

**Player production, final run:** 2,763 Copper Ore · 241 Iron Ore · 203 Lumber ·
64 Charcoal · 35 Iron · 10 Bronze · **8 Bronze Daggers** · 368 Meals · 26 Fine
Bread · 11 Legendary Bread.

Ore → refined metal → forged weapon, entirely inside player businesses.

### Staffing decides survival

47 player-business hires: **28 NPC, 17 owner-at-wage-0, 2 via the job board.**
Every business that failed payroll was NPC-staffed; owner-operated businesses
never failed. At 26.67 (clerk) to 56.67 (refinery worker), an NPC outruns a
typical 200–300 seed in 4–10 simulated hours.

### First death

A0029 starved at **81.2h**, twelve hours after hitting Starving, destroying 775
denari of assets (a mine, a refinery, a vehicle). It had taken a 15/hr job and
then a 10/hr one to fund its businesses — and stopped eating. `assets_wiped`
closed both businesses without a bankruptcy event, which is why "21 open, 2
closed" reconciles with "zero bankruptcies".

---

## 7. Built but NEVER TESTED LIVE

These three landed **after** the final run had already loaded its modules
(run started 00:44; edits at 09:14–09:16). They are unit-tested and unexercised:

1. **Employed agents see job adverts** that beat their current wage. Previously
   gated on `not agent.current_job` — so by hour 44 all 20 agents were employed
   and **nobody could see a single advert.** Refinery owners paid 56.67 for NPCs
   rather than advertise at 25 to an audience of no one.
2. **`hire_applicant` can poach** someone who already has a job, releasing them
   from the old employer. It used to refuse employed applicants outright.
3. **The hire prompt names a real applicant** instead of `'<agent id>'`.

The 35 `quit_job` events in the final run are **voluntary quits via the existing
action**, not poaching — none carry the `reason: "took a better offer"` stamp
that the new code emits. Do not read them as evidence the fix works.

---

## 8. How to run it

```bash
python3 run_phase2.py --dry-run
for t in tests/test_*.py; do python3 "$t" >/dev/null && echo "PASS $t" || echo "FAIL $t"; done
python3 run_phase1.py | grep INVARIANT          # must say "all clean"

nohup python3 run_phase2.py --agents 20 --hours 84 --decisions 400 \
  --rpm 10 --max-tokens 1024 --model openai/gpt-5.6-luna \
  > runs/phase2/live.log 2>&1 &
caffeinate -is -w $(pgrep -f "MacOS/Python run_phase2.py" | head -1)
```

**Cost scales with businesses, not just agents.** Measured: 3.10 calls/agent-hour
at 4–16 businesses, **5.9** at 23. The final run cost **$2.64 and 12 hours**
against a $1.34 / 9h projection. Budget from expected business count.

**Watch `events.jsonl`, not the console** — nothing calls `EventLog.flush()`, so
both fill in ~8KB chunks. A quiet log is buffering, not a stall. Confirm liveness
with `lsof -nP -p <pid> | grep TCP`.

**Match the interpreter path** when checking processes
(`pgrep -f "MacOS/Python run_phase2.py"`) — a bare `pgrep -f run_phase2.py` also
matches any shell whose command line mentions it, including your own monitors.

---

## 9. Open, in priority order

| decision | state |
|---|---|
| **The three §7 fixes under live models** | the next run's whole job |
| **NPC labour vs seed capital** | every payroll failure was NPC-staffed; only owner-at-0 never failed. Either NPCs are too dear or starting capital too thin. This is a design tension, not a bug: NPCs *should* cost more than agents |
| **Job board usage** | 3 postings across 84h and 23 businesses. Works when used; rarely used. §7's fixes may fix this by themselves — judge after |
| **Sustenance vs ambition** | an agent starved while working two jobs to fund its businesses. Nothing warned it |
| **`already delivered` (124 failures)** | largest single failure class; couriers racing for jobs already taken |
| **Extraction on the production curve** | mining is still the highest-margin, lowest-complexity tier |
| **Concurrency** | not built. Calls are serial; 75 agents × 120h is ~47h wall clock |
| **Combat, theft, convoys, bounties, voting** | state classes exist, zero actions |
