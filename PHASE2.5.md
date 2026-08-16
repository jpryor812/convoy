# Phase 2.5 — the supply chain, and agents who use it

Status: **the full economic loop has been observed working under live models.**
An agent founded a business, funded it, priced its goods below the state, ordered
feedstock from a refinery, and another agent claimed the haulage job. That had
never happened before 2026-08-15.

Read this instead of PHASE2.md, which describes an earlier world. Where anything
here disagrees with `convoy_bronze_age_economy.xlsx`, **the code and this document
are right and the workbook is stale** — see §10.

---

## 1. How to run it

```bash
python3 run_phase2.py --dry-run                     # builds every prompt, calls nothing

# a realistic short test: 4 agents, one simulated day, production at 5x
python3 run_phase2.py --agents 4 --hours 24 --decisions 80 \
  --rpm 10 --max-tokens 1024 --time-scale 0.2

# a long unattended run
nohup python3 run_phase2.py --agents 12 --hours 72 --decisions 400 \
  --rpm 10 --max-tokens 1024 > runs/phase2/live.log 2>&1 &
```

| flag | why it exists |
|---|---|
| `--hours` | duration, decoupled from the decision cap |
| `--rpm` | new OpenRouter accounts are capped at 10 req/min per model |
| `--max-tokens` | without it OpenRouter reserves the model's FULL completion window against the key's balance and 402s every call |
| `--time-scale` | multiplies PRODUCTION times only — see §5 |
| `--day-hours` | simulated hours between narrated daily reports |
| `--model a,b` | comma-separated; agents dealt round-robin |

Verify before any long run:

```bash
for t in tests/test_*.py; do python3 "$t" >/dev/null && echo "PASS $t" || echo "FAIL $t"; done
python3 run_phase1.py | grep INVARIANT      # must say "all clean"
```

**Run `run_phase1.py` after ANY change to `data.py`.** Its invariant checker has caught
three mistakes the unit tests did not.

---

## 2. The single most important lesson

Almost every "the agents are being stupid" moment this project has had was **the
observation failing to tell them something the code already knew.** Eight times:

| symptom | actual cause |
|---|---|
| every meal attempt failed | the briefing said the tavern was in Town; it is at South Protected Zone |
| 9 of 13 job applications rejected | agents were never told which roles a business hires |
| everyone took the lowest-paid job in the world | the wage table was not in the briefing |
| 15 vehicles bought, none ever used | `mount` needs an id the observation never carried |
| B2B unusable on arrival | ordering is remote, but seller ids were only visible on-site |
| nobody founded anything for four runs | the affordance line said only what could NOT be built here |
| **nobody founded anything even when told they could** | **net worth was defined but a business's VALUE was never explained** |
| a courier claimed two jobs and delivered neither | a claimed job vanished from the courier's own observation |

That last one broke a four-run deadlock. Agents were told to maximise net worth and
that businesses count toward it — but not *how much*. Spending 200 denari on a tavern
looked like losing 200. The briefing now says plainly that a business is worth what you
paid plus 3× its last day of sales, so founding is net-worth-neutral and grows.
Businesses appeared in the very next run.

**When agents behave badly, suspect the observation before the model.**

---

## 3. The economy

Every chain runs **farm/mine → refinery → workshop → person**, and nothing skips a
step. A person may only buy finished goods; everything upstream moves business to
business and must be physically carried.

- **Extraction** (Farm, Mining Operation — spur roads only). Wheat, Dirty Water, Hide,
  Wood, Hardwood, Stone, Clay, Copper/Tin/Iron Ore. No inputs, so this is the only
  stage profitable with no supplier.
- **Refining** (Refinery — Refinery Row). Grain, Purified Water, Lumber, Seasoned
  Hardwood, Cut Stone, Fired Brick, Charcoal, Tanned Leather, Bronze, Iron.
- **Workshops** (Weaponsmith, Vehicle Dealer / Stable, Tavern / Inn, Equipment Store,
  Home Improvement Store). Refined feedstock only.
- **People.** Finished goods only.

### Rules that are easy to forget

- **A farm grows Wheat and draws Dirty Water.** Neither is edible. A refinery mills and
  purifies them. Bread is `2 Grain + 1 Purified Water`.
- **There is no General Store.** It produced nothing and therefore retailed everything,
  which is how agents were buying ore over a counter.
- **Food is sold at Taverns only.** `eat_self_prep` is retired.
- **Every good clears a 75% margin over its inputs.** This is a hard design rule and it
  is asserted in `test_conformance.py`. Change a recipe and prices must follow.
- **A player's shop only sells while its owner or an employee stands in it.** State shops
  are always staffed, always buy, and never go bankrupt.
- **The state hires at most 2 per business.** Player businesses are uncapped.
- **Government wages are 15.00–25.00** (`GOVERNMENT_WAGES`), separate from `SMART_WAGES`
  which sets player wage floors and NPC hire costs.
- **A business is worth `startup_cost + 3 × last-24h revenue`.**
- **The state marks up 1.4×, not 1.6×** (`NPC_SELL_PCT_COMMON`). A Meal therefore reaches
  a person at **25.20**. The markup was the one lever that fixed an unaffordable meal
  without distorting a single margin upstream — but it is the GENERIC common markup, so
  raw goods got cheaper from the state too (Iron Ore 19.20 → 16.80), which makes the state
  a slightly more competitive supplier than intended. Weapons (1.7×), vehicles and refined
  goods (1.5×) are untouched.
- **Sales tax is paid by the SELLER.** It is a 5% tax on business revenue: a buyer pays
  exactly the marked price and the seller remits 5% of what they take. Applies to shop
  sales, vehicles, meals, player-to-player trades and B2B orders alike.

### Founding costs

Farm 150 · Mining Operation 175 · Tavern 200 · Home Improvement 250 · Equipment 275 ·
Stable 300 · Weaponsmith 350 · Refinery 450 · Security 500 · Insurance 750.

Agents start with **200 denari**, so a Farm (150) is affordable immediately and the
cheapest Town business (Tavern, 200) takes about an hour of wages. That is deliberate:
the early game should be a choice about what to build, not a fight to survive.

---

## 4. Business-to-business trade and haulage

```
order_from_business(my_business, seller_business, item, qty, courier_fee)
accept_courier_job(id) → collect_consignment(id) → deliver_consignment(id)
cancel_consignment(id)
```

One `Consignment` carries both halves of the deal. **Ordering IS the purchase**: the
buyer pays, the goods leave the seller immediately, and what remains is a haulage job at
the seller's gate. The seller bears no delivery risk.

- **Money moves once, at order time.** The buyer pays for goods and **escrows the courier
  fee**, so anyone who completes a job is certain to be paid.
- **Ordering is remote.** A shop owner must not abandon their counter to buy stock.
- **The buyer pays from the BUSINESS's cash**, not their pocket — use `deposit` first.
- **A load moves whole or not at all**, so vehicle capacity decides which jobs an agent
  can take. On foot it is 5 units.
- **Cargo under carriage never enters the courier's inventory**, so it cannot be sold en
  route, but it does count against carry capacity.
- **A courier may hold ONE job at a time**, claimed or loaded. Claiming used to be
  unlimited, and one agent hoarded both outstanding jobs and delivered neither.
- **A claimed job stays on the courier's own board.** It leaves the public list the moment
  it is spoken for, and used to vanish from the courier's view as well — so an agent held
  a job with no id, no pickup point and no fee anywhere in its observation. It now shows
  as `your_haulage_job` with a `next` field naming the current step.

`_source_inputs` in the engine used to auto-buy missing recipe inputs at base price out of
nowhere — a Phase 1 shortcut that would have made this system decorative. Player
businesses now produce only from stock they hold; **government businesses keep the old
behaviour** so the backstop never stalls.

---

## 5. Production time, and `--time-scale`

`hours_per_unit = CRAFT_TIME_COEFFICIENT × base_price^0.927`, calibrated so cheap goods
are quick and valuable ones are slow. Before this, a flat 15 units/hour meant a Blacksmith
produced 16,575 denari of swords per worker-hour against a 24 denari wage.

| good | real | at `--time-scale 0.2` | units/hr real | units/hr scaled |
|---|---|---|---|---|
| Purified Water | 3 min | 1 min | 17.8 | 88.8 |
| Grain, Lumber, Charcoal, Fired Brick | 6 min | 1 min | 9.4 | 46.7 |
| Cut Stone | 9 min | 2 min | 6.4 | 32.1 |
| Tanned Leather | 14 min | 3 min | 4.4 | 22.0 |
| Seasoned Hardwood | 23 min | 5 min | 2.6 | 12.9 |
| Meal | 26 min | 5 min | 2.3 | 11.6 |
| Bronze | 44 min | 9 min | 1.4 | 6.8 |
| Iron | 49 min | 10 min | 1.2 | 6.1 |
| Bronze Sword | 4.9 h | 59 min | 0.20 | 1.01 |
| Iron Sword | 12.0 h | 2.4 h | 0.08 | 0.42 |

**`--time-scale` is free throughput.** Production is continuous inside a shift and the
engine never wakes an agent per unit made, so speeding it up creates no extra decisions:
measured, 5× the goods for an identical 961 decisions. It lets a 24-hour test show a full
chain cycle.

**It is NOT for economics.** Wages accrue per simulated hour, so 5× output makes labour
artificially cheap. It is a runtime flag and never an edit to `data.py`, so the numbers in
this document keep describing the real economy. The run header prints when it is active.

**EXTRACTION IS DELIBERATELY OFF THE CURVE.** On it, every raw good is loss-making
against the state (−1.5 to −5.2/hr) and profitable only via B2B (+10 to +13/hr) — which
would make the whole economy depend on a mechanic that has only just been proven. Flip
it in `data.production_rate_hr` when ready.

---

## 6. Cost

| | tokens |
|---|---|
| static briefing | 4,588 |
| tool schemas (49 actions) | 7,242 |
| **cached prefix** | **11,830** |
| observation per decision | ~360 |

Cache hit rate is **94–97%** on every live run.

Two numbers drive cost, and both moved a lot on 2026-08-15:

- **API calls per decision: ~2.2–3.0.** Making `wait` terminal and refusing redundant
  `start_shift` removed 51% of all actions.
- **Decisions per agent-hour: 4.3 → 0.60.** The engine used to wake an agent every 15
  simulated minutes even mid-shift, so an 8-hour shift collected 32 re-evaluations whose
  only honest answer was "still working" — **75% of every action in a smoke run.** Agents
  are now left alone while working or travelling, and woken only when the activity
  resolves or hunger bites.

That takes a 12-agent, 72-hour run to roughly **$1** and a few hours of wall clock, and
drops the Phase 3 projection by an order of magnitude. **Treat the Phase 3 figure as
provisional** — it is extrapolated from a 4-agent, 24-hour sample.

Calls are strictly serial. At 10 rpm the pacing floor (6.0s) and Luna's latency (5.6s) are
nearly equal, so **lifting the rate limit alone buys almost nothing** — only concurrency
does, and 75 agents × 120 hours serially is 100+ hours of wall clock.

### Model notes, measured

| model | latency | cache | cost/call | verdict |
|---|---|---|---|---|
| Grok 4.3 (minimal) | 4.0s | 66% | $0.0066 | fastest, 38× Luna's cost |
| GPT-5.6 Luna | 5.6s | 97% | **$0.00018** | the workhorse |
| Ling 3.0 Flash | 21s | 43% | $0.00059 | tool calls fine, 3.3× Luna's cost |
| DeepSeek V4 Flash | **69.6s** | — | — | unusable; 21s even at `low` effort |

Ling and DeepSeek look cheap on headline price and are not. `reasoning_effort` from
`MODEL_ROSTER` is now actually sent; it used to be dead data.

---

## 7. Bugs, and why the tests missed them

Every one of these was invisible to unit tests and appeared only under live models.
Each now has a regression test **verified to fail against the original bug.**

**`wait` cancelled whatever the agent was already doing.** `agent.activity` is one slot.
Wages accrue only while `kind == "work"`, so an agent that started a shift then waited
clocked itself out; and `in_transit` is cleared only from the travel branch, so a
cancelled journey could neither arrive nor reset. **9 of 12 agents spent a 72-hour run
permanently "in transit" while standing still.**

**The guard that fixed it then blocked the next shift.** It checked `kind == "work"` but
not that the shift was still live — and an expired shift keeps that kind. Agents woken
*because* their shift ended were told "already working this shift, 0.0h left". 24 of 50
`start_shift` calls refused.

**Wages shared a dict with retail prices** under a `wage:<role>` key. The observation
walks that dict expecting tradeable items, so the first agent near a player business that
had set a wage killed the run with `KeyError: 'wage:Miner'`. It survived 60 simulated
hours because no player business had ever existed.

**A claimed haulage job became invisible to its own courier.** It leaves the public board
when claimed, and the observation's haulage block only filled on COLLECT. An agent claimed
two jobs and walked to the opposite end of the valley.

**Three helpers were auto-exposed as callable tools** — introspection publishes every
public function in `actions.py`. Anything that is not an action must go in `_NOT_ACTIONS`
or start with `_`.

**A connection reset killed a run at hour 1.5.** The retry loop caught `URLError` but a
reset mid-body arrives as a bare `OSError` during `resp.read()`.

The lesson: **test sequences, not calls.** See `tests/test_activity_integrity.py` and
`tests/test_b2b_haulage.py`.

---

## 8. What agents actually do

Latest smoke — 4 agents, 24 simulated hours, `--time-scale 0.2`, $0.04:

```
[11.6h] luna-02  founded a Mining Operation
[12.1h] luna-04  founded a Tavern / Inn
[20.2h] luna-04  deposited 250 into it
[20.2h] luna-04  set production to Meal
[20.2h] luna-04  priced Meal at 25.00      <- undercutting the state's 30.24
[20.2h] luna-04  ordered 10x Grain from a refinery, 20.00 carriage
[20.2h] luna-04  ordered 10x Purified Water, 20.00 carriage
[21.2h] luna-01  claimed both haulage jobs
```

Another agent then tried to buy a meal from luna-04's tavern and was refused —
*"unattended, nobody is serving"* and later *"out of Meal"*. That is player-to-player
commerce being attempted, the staffing rule working, and the supply chain mattering, all
in one refusal.

**Agents also began to talk**, for the first time in six runs — and it emerged from need
rather than instruction. Every message was about food:

> *"I'm at South Protected Tavern with 23.82; meal costs 30.24 tax-in. Can you send 7
> denari urgently?"*

That run doubled as the evidence that food was mispriced, which is what the 1.4× markup
and the 200 denari purse fix.

**What has still never happened: a COMPLETED DELIVERY.** `collect_consignment` and
`deliver_consignment` have only ever been exercised by tests. Everything up to and
including `accept_courier_job` is proven live.

---

## 9. Open decisions

| decision | state |
|---|---|
| **Extraction on the production curve** | held until B2B is proven end to end |
| **A completed delivery** | never yet observed; the last step of the chain |
| **Chat** | zero messages in five runs, cold-start now fixed but unproven |
| **Iron Sword margin** | 1,150% over inputs; Bronze Sword 594%, Donkey Cart 789% |
| **Concurrency** | not built; Phase 3 is not viable serially |
| **Combat, theft, convoys, bounties, voting** | state classes exist, zero actions, zero engine support |
| **Road danger figures** | removed from the briefing — inputs to an ambush model that does not exist. Restore with combat |
| **Bread timing** | 26 min, not the 15 min anchor, after the reprice |

---

## 10. The spreadsheet is stale

`convoy_bronze_age_economy.xlsx` has not been touched since 2026-08-12 and does not
describe this world: no Wheat, no Purified Water, no Lumber, no couriers, a General Store
that no longer exists, and a cost model off by an order of magnitude. PHASE1.md already
recorded 23 edits never applied to it.

**`convoy/data.py` is the source of truth.** A full visual reference — every business,
good, recipe, time and price — is generated directly from it rather than maintained by
hand.

---

## 11. What to do next

The recommended run, measured from the busiest smoke (1.06 decisions/agent-hour,
2.95 calls/decision, $0.00022/call):

```bash
nohup python3 run_phase2.py --agents 16 --hours 96 --decisions 400 \
  --rpm 10 --max-tokens 1024 --time-scale 0.2 \
  --model openai/gpt-5.6-luna > runs/phase2/live-96h.log 2>&1 &
caffeinate -is -w $(pgrep -f run_phase2.py | head -1)      # then leave the lid open
```

≈1,600 decisions, ≈4,800 calls, **about $1 and 8 hours of wall clock.**

**The one thing to watch for: a COMPLETED DELIVERY.** `collect_consignment` and
`deliver_consignment` are the only actions in the chain no live model has ever performed.
If the run ends with consignments stuck at `claimed`, read the courier's observation
before assuming the model is at fault — that has been the cause eight times out of eight.

Also worth watching: whether anyone speaks now that food is affordable (the only chat so
far was hunger), and whether a player shop ever actually sells to another agent.

After that: **extraction onto the production curve** (§5), then the five-model comparison.
