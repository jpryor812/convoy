# Phase 3 — a solvent economy, and a chain that only runs one way

Status: **the supply chain has been observed working end to end, and businesses no
longer go bankrupt by accident.** On 2026-08-16 an agent founded a Mining Operation
and a Refinery, mined Tin Ore, refined it into Bronze, and finished the run worth
4,066 denari. Every player business ended the run solvent. Both of those were false
the day before.

This supersedes PHASE2.5.md, PHASE2.md and PHASE1.md.

> **Do not consult `convoy_bronze_age_economy.xlsx` or `convoy_reference.md`.**
> Both are 2026-08-12 snapshots of a world that no longer exists, and
> `convoy_reference.md` states in its own header that the spreadsheet is the
> source of truth — which is wrong, and is the more dangerous of the two because
> it reads as current. Prices, recipes, wages and times all moved on 2026-08-16.

---

## 1. Where the truth lives

| what you want | file |
|---|---|
| Prices, recipes, wages, production times, business definitions | `convoy/data.py` |
| Who may buy from whom, escrow, payment, hiring | `convoy/actions.py` |
| Production, payroll, solvency, haulage, taxes | `convoy/engine.py` |
| What agents are actually told | `convoy/observe.py` |
| Tool schemas exposed to the model | `convoy/schemas.py` |

**Run `python3 run_phase1.py` after ANY change to `data.py`.** Its invariant
checker has now caught four mistakes the unit tests missed.

---

## 2. The lesson that keeps being true

Almost every "the agents are being stupid" moment has been **the observation
failing to tell them something the code already knew.** The count is now eleven:

| symptom | actual cause |
|---|---|
| every meal attempt failed | the briefing put the tavern in the wrong place |
| 9 of 13 job applications rejected | agents were never told which roles a business hires |
| everyone took the lowest-paid job | the wage table was not in the briefing |
| 15 vehicles bought, none used | `mount` needs an id the observation never carried |
| B2B unusable on arrival | ordering is remote, seller ids were only visible on-site |
| nobody founded anything for four runs | the affordance line said only what could NOT be built |
| nobody founded even when told they could | a business's VALUE was never explained |
| a courier claimed two jobs, delivered neither | a claimed job vanished from its own courier's view |
| 543 refusals, 36.8% of all actions | agents knew the 2-per-business cap but not which sites were full |
| a tavern sat idle 16 hours after founding | a new business reported zeros, never "you are making nothing" |
| **four taverns bought 156 denari of unusable Dirty Water** | **the stall message said "no feedstock" while stock was visibly on the shelf, and never named the missing input** |

That last one was written on 2026-08-16 **by the agent fixing the other ten.** It
turned a single mistake into a four-order loop across two independent agents. The
briefing did contain the recipe; being *technically available* in a 30-line block
is not the same as being *present at the decision*.

**When agents behave badly, suspect the observation before the model.** Including
when you wrote the observation an hour ago.

---

## 3. The chain, and the rule that enforces it

```
farm / mine  ->  refinery  ->  shop  ->  person
```

**It only runs that way**, enforced in `actions.py` on both doors — remote ordering
(`order_from_business`) and over-the-counter sale (`sell_to_business`):

| buyer | may buy from |
|---|---|
| Farm, Mining Operation | nothing — extraction has no inputs |
| Refinery | Farm, Mining Operation, and other Refineries (Bronze and Iron need Charcoal) |
| every shop | **Refinery only** |

A player business also refuses any item it cannot use — a Tavern takes Grain and
Purified Water, not Iron Ore. **The state buys anything**, so nothing is ever
unsellable.

Blocking only the remote door was not enough: an agent could carry raw goods to a
shop and sell them over the counter, and the same dead stock arrived by a different
route. Both doors, or neither.

### State businesses are a backstop, not a participant

Government farms, mines, refineries and shops **hold every good at their listed
price, always, without couriers.** They produce without consuming inputs. This is
deliberate: 164 of 166 meals in one run came from the state tavern, so removing it
starves the population inside a day. The state is the supply of last resort, priced
so a player can undercut it.

**The state buys at 0.4x base and sells at 1.4–1.5x.** That spread is the whole
engine of player trade: a farm dumping Wheat to the state earns 57.6/hr, while
selling B2B just under the state's price earns 180/hr — 3.1x better for the seller
*and* cheaper for the buyer.

---

## 4. Prices and times

`hours_per_unit = CRAFT_TIME_COEFFICIENT × base_price^0.927`, with
`CRAFT_TIME_COEFFICIENT = 0.0074`.

**This was 0.0296 until 2026-08-16.** At the old rate a Refinery Worker produced
~18.7/hr of value against a 37.78 floor and an 85 NPC wage — every refinery lost
money on every worker, always. The economy only appeared to work because
`--time-scale 0.2` was multiplying output 5x while wages accrued per simulated
hour. Folding a 4x into the coefficient makes it close at time-scale 1.0, and the
flag went back to being a test tool.

| good | per unit | units/hr |
|---|---|---|
| Purified Water | 0.8 min | 71.1 |
| Grain, Lumber, Charcoal | 1.6 min | 37.4 |
| Cut Stone | 2.3 min | 25.7 |
| Tanned Leather | 3.4 min | 17.6 |
| Seasoned Hardwood | 5.8 min | 10.3 |
| Meal | 6.5 min | 9.3 |
| Bronze | 11.0 min | 5.4 |
| Iron | 12.3 min | 4.9 |
| Bronze Sword | 74 min | 0.81 |
| Iron Sword | 180 min | 0.33 |

**Extraction is off this curve** and keeps its own rates (Wheat 72/hr, ores 36/hr).
It has no inputs, so its value added is its whole revenue — which is why mining is
the highest-margin tier in the game and needs no supplier.

### Founding costs

Farm 150 · Mining 175 · Tavern 200 · Home Improvement 250 · Equipment 275 ·
Stable 300 · Weaponsmith 350 · Refinery 450 · Security 500 · Insurance 750.

Agents start with **200**.

---

## 5. Wages

`SMART_WAGES` is the source; `NPC_WAGES = SMART × 1.50`. **The derivation used to
run the other way**, which meant cutting an NPC wage dragged the player floor down
with it — taking a Refinery Worker's floor below the state's own rate, so no agent
would ever have taken a player refinery job.

| role | state | player floor | NPC |
|---|---|---|---|
| Store Clerk | 15.00 | 17.78 | 26.67 |
| Laborer / Stablehand | 16.11 | 20.00 | 30.00 |
| Farmhand | 17.22 | 22.22 | 33.33 |
| Miner | 20.56 | 28.89 | 43.33 |
| Researcher | 22.78 | 33.33 | 50.00 |
| Blacksmith | 23.89 | 35.56 | 53.33 |
| Refinery Worker | 25.00 | 37.78 | 56.67 |

The multiplier was **2.25** until 2026-08-16. At that level an NPC Refinery Worker
cost 85/hr against the 75.6/hr its labour created — the one role every supply chain
needs was the only one that could never pay for itself.

### Every tier now clears its own wage

Surplus per worker-hour, selling B2B just under the state's price:

| business | surplus/hr | NPC | ratio |
|---|---|---|---|
| Mining Operation | 291.6 | 43.33 | 6.7x |
| Weaponsmith | 300.3 | 53.33 | 5.6x |
| Tavern | 191.1 | 26.67 | 7.2x |
| Farm | 180.0 | 33.33 | 5.4x |
| **Refinery** | **119.6** | **56.67** | **2.1x** |

Refining is thinnest **only in its laziest configuration** — NPC labour plus state
inputs. Buying Wheat from a player farm takes it to 2.8x; hiring an agent instead
of an NPC takes it to 2.9x; doing both reaches **4.2x**. That gradient is the
incentive to build the chain, and is why the refinery NPC wage was deliberately
left alone.

---

## 6. Payroll and solvency

**A business can never hold negative cash.** Before 2026-08-16 `_pay_wages` ran a
bare `cash -= gross`, and the leading agent of a 96-hour run finished ranked at
1,375 while owning two businesses 2,852 in the red.

- **NPC hires are paid only while the business can actually produce.** No feedstock
  or a full yard means the meter stops. Three NPCs in an empty refinery cost their
  owner 2,124 denari in 11 simulated hours under the old rule.
- **Agent employees are paid for every hour they work**, feedstock or not. The risk
  belongs to the owner who hired them, not the worker. Gating their pay too would
  make a player job strictly riskier than a state job — state businesses always
  produce — and the labour would all go to the state.
- **Cash floors at zero.** An unpaid worker leaves, which stops a payroll spiral
  compounding.
- **Missing payroll starts a 24h clock.** It clears when the business holds one
  hour of the payroll it missed, captured *before* the unpaid staff walked —
  otherwise firing everyone would clear the clock automatically.
- **The owner is told.** Insolvency, the amount owed, the countdown and the
  business's payroll per hour are all in the observation. In the 96-hour run 30
  bankruptcy warnings were logged and **none reached an agent.**

A business is worth `startup_cost + 3 × last-24h revenue + cash + inventory`.
Cash and stock were added on 2026-08-16; without cash the score agents were told to
maximise had come loose from solvency, and without stock, buying feedstock would
have looked like destroying value.

---

## 7. The job board

Owners advertise; every agent sees it; the owner picks.

```
post_job(business, role, wage)   -> world chat + the board, lapses after 12h
apply_to_job(posting_id)         -> the owner still decides
hire_applicant(posting_id, agent)
close_job(posting_id)            -> to repost at a different wage
```

Before this the player labour market was invisible. A mine offering a Miner
**35.00/hr** could not attract a single agent — a jobseeker standing on the same
tile saw only "1 player-owned and may hire", with no role, rate, or sign it was
hiring — and fell back on an NPC at 43.33 while agents queued for the state's 20.56.

Postings are visible **world-wide, not only in the chat scroll**, sorted best-paid
first, because chat ages out and an agent that wakes later would never see it. An
owner with no applicants is told so explicitly, with the hours elapsed:

```
NOBODY has applied in 4.0h. close_job('J0013') and post_job again at a
higher wage, or hire_npc_employee instead.
```

Applications do not auto-hire, so reposting lower — or higher — is a real decision.

---

## 8. What the 2026-08-16 runs showed

**16 agents, 72 simulated hours, no `--time-scale`, $0.80, 3,195 calls, 0 errors.**

| | 96h run (pre-fix) | 72h run (post-fix) |
|---|---|---|
| businesses founded | 18 | 13 |
| **businesses with negative cash** | **4 (one at −2,124)** | **0** |
| bankruptcies | 7 | **0** |
| foundings with zero working capital | 8 of 18 (44%) | **0** |
| deliveries completed | 24 | **39** |
| courier fees paid | 749 | **970** |
| player-made goods | Upgraded Tools only | Bronze, Meal, Fine Bread, ores |

**A player refinery was built** — founded at 68.2h, producing its first Bronze at
69.5h. Its owner also ran a Mining Operation feeding it Tin Ore and finished first
at 4,066 net worth: the farm/mine → refinery link, vertically integrated by one
agent. That is the tier the numbers said was least attractive to build.

**Nothing went bankrupt and nothing went into debt**, and the solvency machinery
never had to fire once — `wages_unpaid` count was zero. Businesses stayed solvent
rather than being rescued.

Measured cost and pace, for planning:

- **3.14 calls per agent-hour**, 6.14s per call — the run is pacing-bound
- **$0.00025/call**; 16 agents × 72h = ~$0.80 and ~4.8h wall clock
- cache hit **96%**

---

## 9. How to run it

```bash
python3 run_phase2.py --dry-run                      # builds every prompt, calls nothing

for t in tests/test_*.py; do python3 "$t" >/dev/null && echo "PASS $t" || echo "FAIL $t"; done
python3 run_phase1.py | grep INVARIANT               # must say "all clean"

nohup python3 run_phase2.py --agents 16 --hours 72 --decisions 400 \
  --rpm 10 --max-tokens 1024 --model openai/gpt-5.6-luna \
  > runs/phase2/live.log 2>&1 &
caffeinate -is -w $(pgrep -f "MacOS/Python run_phase2.py" | head -1)
```

| flag | why it exists |
|---|---|
| `--hours` | duration, decoupled from the decision cap |
| `--rpm` | new OpenRouter accounts cap at 10 req/min per model |
| `--max-tokens` | without it OpenRouter reserves the model's FULL completion window and 402s |
| `--time-scale` | multiplies PRODUCTION only. **Not needed now** — the 4x is in `data.py`. A test tool, never an economic setting |
| `--day-hours` | simulated hours between narrated daily reports |

**Watch the run through `events.jsonl`, not the console log.** Nothing calls
`EventLog.flush()`, so both sinks fill in ~8KB chunks; a quiet log is buffering,
not a stall. Confirm liveness with `lsof -nP -p <pid> | grep TCP`.

When matching processes, match the interpreter path
(`MacOS/Python run_phase2.py --agents 16`) — a bare `pgrep -f "run_phase2.py"`
also matches any shell whose command line mentions it.

---

## 10. Open, in the order I would take them

| decision | state |
|---|---|
| **The job board under live models** | built and unit-tested, **never seen by an agent**. Five new actions; agents may not reach for them at all |
| **The chain rule under live models** | it turns previously-legal purchases into refusals, and every past agent deadlock began with a wall they did not understand |
| **Refinery throughput** | refining runs at half a farm's rate. If refineries still do not get built, raise throughput rather than cutting the NPC wage — cutting the wage rewards *not* hiring agents and flattens the gradient in §5 |
| **State prices for intermediates** | currently 1.4–1.5x. Raising them to 2.0–2.5x would widen player refining margins and push refiners toward player farms. Held deliberately so the observation fixes can be judged alone |
| **Extraction onto the production curve** | mining is the highest-margin tier and needs no supplier. Still the most likely thing to short-circuit the chain |
| **Concurrency** | not built. Calls are serial and the run is pacing-bound, so 75 agents × 120h is ~47 hours of wall clock. This caps run size, not cost |
| **Combat, theft, convoys, bounties, voting** | state classes exist, zero actions, zero engine support |

**The next run's job is to answer the first two.** Everything else is calibration
and can wait for evidence.
