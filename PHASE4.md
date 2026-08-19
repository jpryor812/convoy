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
| Why agents did things | `Agent.reasoning` (§9), and `llm_reasoning` in the event log |
| Reading a run back | `python3 show_agent.py <agent id>` |
| What everything looks like | `convoy/sprites.py` (§11); `python3 render_world.py` |
| Advice given from outside | `convoy/advice.py`; `Agent.inbox` (§13) |
| Asking a finished run questions | `convoy/interrogate.py`; `python3 serve.py` (§14) |

**Run `python3 run_phase1.py` after ANY change to `data.py`.**

---

## 2. The lesson, now at fourteen

Almost every "the agents are being stupid" moment has been **the observation
failing to say something the code already knew.** Fourteen documented:

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
| an owner sat on 4 applicants for 12h and let the advert lapse | the call-to-action read `hire_applicant('J0090', '<agent id>')` — a literal placeholder |
| an agent bought 11 meals in 90 minutes, ~200 denari and ~11 of its 400 decisions | the affordance line spoke only when you were HUNGRY; nothing ever said "you are already fed for another 11.8h" |
| **6 of 6 recommendations expired unseen on the advice channel's first live run** | **not the observation this time but the SCHEDULE: advice reaches an agent only inside an observation, an observation is built only when the agent is asked, and a working agent is never asked. The advice was queued, logged and correct; its targets started shifts at h0.2 and were not spoken to again** |

Two of these were written by the agent fixing the other ten. Being *technically
present* in a 30-line briefing block is not the same as being *present at the
decision*.

The thirteenth is the one that killed A0029 — see §10. Its state block did say
`hunger: Normal, 0.2h since eating`. That is the fact, and it was still not the
*decision*: "Normal" does not read as "buying another meal now buys nothing."

The fourteenth widens the rule. The observation was perfect and the agent still
never saw the text, because nothing scheduled it a turn in which to look. So:

**When agents behave badly, suspect the observation before the model — and if
the observation is right, check that the agent was ever asked.**

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
denari of assets (a mine, a refinery, a vehicle). `assets_wiped` closed both
businesses without a bankruptcy event, which is why "21 open, 2 closed"
reconciles with "zero bankruptcies".

**It did not choose to stop eating — it ran out of decisions. See §10.**

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

Afterwards, read the decisions back:

```bash
python3 show_agent.py                 # list agents, decision counts, last seen
python3 show_agent.py A0013 --full    # one agent's transcript, with outcomes
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

## 9. Agents now record WHY (2026-08-17, after the 84h run)

**This was the hard blocker on interactivity, and it is cleared.**

`Agent.memory` is a list of indices into the event log — things that happened.
Nothing stored *why* an agent chose anything, so "why did you do that?" produced
fluent confabulation rather than recall. `llm.py` captured the model's text only
on replies carrying **no** tool calls, i.e. exactly the turns where the agent
decided *not* to act: **2 captures in 6,916 calls.**

What changed:

| | |
|---|---|
| `state.py` | new `Reasoning` dataclass (`hour`, `woken_because`, `text`, `actions`) and `Agent.reasoning`, a 40-entry ring buffer. Registered in `checkpoint.py`, so it survives a restart |
| `llm.py` | `_reasoning_text()` reads `content`, falling back to `reasoning` — most of the roster returns an empty `content` beside a tool call and puts its thinking in `reasoning`. Captured on **every** reply |
| `llm.py` | **one decision = one record.** A multi-step decision reasons on step 1 and then executes; recording per step made 7 of 11 entries in the first smoke read "acted without saying why" when the reason had been given one step earlier. Written in a `finally`, so a decision that half-happened is still recorded |
| `observe.py` | `thinking_for()` → a `YOUR LAST FEW DECISIONS, AND WHY YOU MADE THEM` block, last 5, 220 chars each |
| `show_agent.py` | prints one agent's transcript from a run, interleaving decisions with their outcomes |

**Reasoning is deliberately NOT folded into `memory_for`.** Memory has a fixed
line budget and rare, valuable contents; reasoning fires on nearly every
decision. Mixing them would let an agent's own chatter evict the news that a
rival opened a refinery next door — §2, freshly re-earned. Separate budgets.

Measured on a live 4-agent smoke: **7 decisions, 7 with real reasoning, 19
action calls correctly collapsed into them, refusals marked.**

`tests/test_reasoning.py` — 14 tests, driving `LLMPolicy` against a scripted
transport so the capture path itself is asserted, not a model's cooperation.

---

## 10. A0029 did not die of a missing wake trigger

The 84h run's only death was read as *"idle agents appear to have no wake
trigger, so hunger never prompts a decision."* **That diagnosis is wrong**, and
acting on it would have meant rewriting `Engine._decisions` for nothing.

The engine woke A0029 on schedule for all 36 hours, and already exempts hunger
from the "do not interrupt a busy agent" rule for precisely this case. The wake
was swallowed **one layer up**, by the harness's budget guard:

```
h45.20  decision 400/400   <- the run's per-agent cap, and its last meal
h57.20  sustenance_hungry     woken; CappedPolicy.decide returned silently
h69.22  sustenance_starving   woken; returned silently
h81.22  starved_to_death, assets_wiped: 2 businesses, 1 vehicle, 775 denari
```

Exactly one agent in the run hit the cap, at the exact hour A0029 last acted
(`grep "decision 400/400"`). It was the richest agent in the world at h58 and
finished at 0 — **a harness artifact silently corrupting the leaderboard it
exists to measure.**

Two fixes:

1. **`SURVIVAL_RESERVE = 6`** in `run_phase2.py`. Past the cap, an agent whose
   `sustenance_stage` is not `Normal` still gets up to six decisions, spendable
   only while it is hungry. The wake reason is rewritten to say so in words —
   it names the stage, says the budget is gone, counts what is left, and states
   that dying wipes every business and coin. An agent told only "reevaluation"
   would spend its last decisions on business admin and starve anyway. A
   `decision_cap_reached` event now marks exhaustion in the log.
2. **The observation now says when you are FED**, not only when you are hungry
   (§2, thirteenth). This is what actually killed A0029: it ate **11 times in 90
   minutes** — ~200 denari and ~11 of its 400 decisions — because nothing said a
   second meal inside the 12-hour window buys nothing. That waste is what
   exhausted the cap at h45.

With the reserve, A0029's first emergency wake lands at **h57.20 — 24 hours
before death**, standing at Refinery Row with 1,540 denari.

`tests/test_decision_cap.py` — 7 tests. Note the golden observation snapshot was
re-baselined for the FED line; it caught the change, which is its job.

---

## 11. The valley has a face (2026-08-17)

`render_world.py` turns a finished run into one self-contained HTML file: the
23-place valley, its businesses appearing as they are founded, every agent
moving hour by hour, and — on click — that agent's own account of why it acted.
It is §9 made visible; without stored reasoning the click would have nothing to
show.

```bash
python3 render_world.py                              # newest run -> world.html
python3 render_world.py --run runs/phase2/20260817-004401 --out valley.html
```

**Positions come from the hourly diary**, which is the only event that carries
`location` for every living agent on a schedule, refined by `travel` events —
those give a departure, a destination and a duration, so an agent is drawn ON
THE ROAD rather than teleporting. A stationary agent emits an identical diary
line every hour, so consecutive duplicates are collapsed before they reach the
page; A0029's 21 idle hours were 21 rows.

Everything is inlined as a data URI. A classroom file that breaks because a
relative path moved is worse than no file.

### Art

| what | where | licence |
|---|---|---|
| Terrain, buildings, people (259 PNGs) | `kenney_medieval-rts/` | CC0, Kenney |
| Vehicles, goods, glyphs (79 SVGs) | `art/generated/` | drawn here |
| The binding | `convoy/sprites.py` | — |

**No image model was involved — there was none available.** The new art is SVG
drawn in the pack's own idiom, using `art/palette.py`, whose colours were
sampled out of the pack's PNGs (898 distinct; the top ~25 carry it). Generated
raster art would have drifted in outline, palette and projection and read as two
games stapled together.

Goods are drawn as a **taxonomy** — one shape per category, tinted per material.
Ore is ore whether copper, tin or iron. That is how the pack gets 58 tiles from
about eight ideas, and it means a good added to `data.py` inherits sane art
rather than shipping as a blank square.

The three buildings the brief called missing were all in the pack, mislabelled
by filename: **Structure_20** is a house with a stone chimney (Refinery),
**Structure_19** a forge with a glowing furnace mouth (Weaponsmith),
**Structure_07** a stall hung with loaves (Tavern).

**The unit grid is 4 faction colours × 6 poses, and the colours do not start
where the filenames do** — blue begins at 23 and wraps past 24 to 1, measured by
counting pixels. Flattening it to a naive 0–23 repaints every agent the wrong
colour, silently. `tests/test_sprites.py` pins it.

`sprites.check()` asserts every item, vehicle, business type, location, role,
model and all 53 actions have art, and **runs inside `run_phase1.py` beside the
economic invariants** — same reason: it depends on `data.py`, and its failure
mode is a blank square discovered in front of an audience.

### What the map still needs

**A run with reasoning in it.** The 84h run predates §9 and carries 2 decisions
across 20 agents, so clicking an agent mostly shows an empty transcript. The
mechanism is verified on a 4-agent smoke (7 decisions, 7 with real reasoning);
what it has never had is a full run's worth. That is the same run §7 is waiting
for.

---

## 12. Open, in priority order

| decision | state |
|---|---|
| **The three §7 fixes under live models** | the next run's whole job. Watch `job_posted` / `job_applied` / `hired` with `via` / `quit_job` with `reason` |
| ~~The thin demo~~ | **backend done, §14** — `serve.py` answers questions from the record. Needs a front end |
| ~~Interrogation grounding~~ | **done, §14** — lookups never call a model, synthesis is grounded in retrieved decisions and cites hours, and a question the record cannot answer returns nothing |
| **NPC labour vs seed capital** | every payroll failure was NPC-staffed; only owner-at-0 never failed. Either NPCs are too dear or starting capital too thin. This is a design tension, not a bug: NPCs *should* cost more than agents |
| **Job board usage** | 3 postings across 84h and 23 businesses. Works when used; rarely used. §7's fixes may fix this by themselves — judge after |
| ~~Sustenance vs ambition~~ | **resolved, §10** — it was the decision cap, plus 11 redundant meals |
| **`already delivered` (124 failures)** | largest single failure class; couriers racing for jobs already taken |
| **Extraction on the production curve** | mining is still the highest-margin, lowest-complexity tier |
| **Concurrency** | not built. Calls are serial; 75 agents × 120h is ~47h wall clock |
| **Combat, theft, convoys, bounties, voting** | state classes exist, zero actions |

---

## 13. Advice from outside the simulation (2026-08-18)

A person can now tell an agent what to do, and the run records whether it
listened. `convoy/advice.py` is the way in; `Agent.inbox` holds it;
`observe.advice_for` delivers it; `advice_outcome` records what happened next.

Three facts are kept apart on purpose, because collapsing them is what makes
this kind of feature lie:

| event | means |
|---|---|
| `advice_given` | queued. Nobody has seen it |
| `advice_delivered` | the text entered a prompt. Written by the one function that builds prompts, and by nothing else |
| `advice_outcome` | what the agent did while holding it, plus its own words |

`times_seen` is therefore **evidence**, not an estimate. "It ignored me" and "it
never heard me" are different rows, and a student who says the first can be
shown which one actually happened.

**Nothing decides whether advice was "followed".** A model asked to grade its
own obedience says yes; a keyword match on action names would call
`sell_to_business` compliance with "sell the ore" even when it sold something
else. The log records what was said and what was done, and leaves the verdict to
the person asking — which is the exercise.

### The wake, which is the part that was missing

The first live smoke delivered **0 of 6**. Not a delivery bug: advice reaches an
agent only inside an observation, an observation exists only when the agent is
asked, and `Engine._decisions` deliberately does not ask an agent who is
mid-shift. All six targets started shifts at hour 0.2 and were never spoken to
again. The advice was queued, logged, correct, and invisible.

Hunger was already exempt from that guard, for exactly the same reason — an
agent that cannot react to hunger starves at its own bench. Unheard advice is
now the second exemption, and it forces **one** wake, not one per tick: only
advice with `times_seen == 0` qualifies, so `observe` marking it delivered ends
the interruption. The guard it sits inside exists because 75% of all actions in
one smoke were an agent reporting it was still busy; reopening that hole would
cost more than the feature is worth.

After the fix, the same command delivered **6 of 6, each within 0.2h**, and both
advised agents did what they were told at h1 — "say hello and name one good"
produced *"Hello everyone! I'm working at the Refinery and looking to buy or sell
refined goods—especially Charcoal or Bronze."*

### Advice expires, and the log nearly undid that

Advice about a market goes stale with the market, so a recommendation lapses
after `ADVICE_TTL_HOURS` (6 by default). That worked, and was defeated by its own
audit trail: `advice_given` and `advice_delivered` carry the full text and do not
expire, so `memory_for` served hour-10 advice back at hour 17 as a raw event
dump, reading as current. The three advice events are now engine bookkeeping and
excluded from memory — which also stops an advisor spending the 15-line memory
budget that reasoning was deliberately kept out of (§9).

`tests/test_advice.py` — 29 tests, weighted towards delivery and the wake rather
than storage.

---

## 14. Asking a finished run questions (2026-08-18)

`convoy/interrogate.py` and `serve.py`. Load a run, ask an agent why it did
something, get its own words back.

```bash
python3 serve.py                          # newest run, port 8000
python3 serve.py --no-model               # recall only; never calls out
```

| route | |
|---|---|
| `GET /run` | hours, agents, decisions, how many carry real reasoning |
| `GET /agent/{id}` | milestones, counts, every recommendation it was given |
| `GET /agent/{id}/transcript` | every recorded decision and its reason |
| `GET /agent/{id}/impact` | before/after around each piece of advice |
| `POST /agent/{id}/ask` | a question |
| `POST /agent/{id}/advise` | a recommendation, queued into the saved world |

Every answer carries **citations** — hour, action, verbatim text — and a `kind`
saying which of three things happened: `recall` (no model called),
`synthesis` (a model was called, over the cited decisions only), or `nothing`.

**`nothing` is a first-class outcome.** A tool that always produces an answer
teaches students that agents always have reasons, which is false.

### The retriever was the confabulation risk, not the model

Ranking decisions by keyword overlap and taking the top few *always* returns
something. Asked "why did you buy a camel?" about an agent that never saw one,
it returned the hour that agent bought **charcoal** — because "buy" matched — and
the answer read as the agent confirming a purchase that never happened. Worse
than a hallucinating model, because the words really were the agent's.

A decision must now match a strict **majority** of the question's content words.
Half is not enough: that is exactly the camel case. A named hour still qualifies
on its own, since an hour is an unambiguous request for a moment.

`tests/test_interrogate.py` — 18 tests.

---

## 15. Checkpointing was write-only for three phases (2026-08-18)

`checkpoint.load()` had never worked on a real run. `save` walks the object graph
generically and will happily encode a type `load` cannot decode, so a dataclass
added to `state.py` and not registered in `_CLASSES` produces checkpoints that
write cleanly, look right on disk, and raise `KeyError` on restore. Nothing
called `load` in production, so **four** types accumulated — `ChatMessage`,
`JobPosting`, `StolenStack`, `TradeOffer` — and every checkpoint written since
chat landed was unrestorable. Found by the first code that tried to read one.

`checkpoint.check()` now asserts every dataclass in `state` is registered, and
**runs inside `run_phase1.py`** beside the economic invariants and the sprite
check, for the same reason those do: cheap, dependent on a file people edit
often, and its failure mode is losing a twelve-hour run.

### Resuming a world

With `load` working, a saved world can be picked back up:

```bash
python3 run_phase2.py --resume runs/phase2/20260818-124204 --add-hours 12
```

This is what makes advice queued through `serve.py` actually actionable, and
what a "come back tomorrow and see what your agents did" product needs. Two
further things had to be fixed for it:

- **`Engine._next_checkpoint` was an absolute offset from zero.** A world
  reloaded at hour 84 was already past it, so the due-check fired every tick and
  the counter advanced one simulated *hour* per simulated *minute* — about 5,000
  redundant saves before it caught up. Now relative to the world's own clock,
  which is identical for a fresh world.
- **`EventLog.replay()`**, because `memory_for` answers "what has happened to me
  lately?" by walking `log.events`. A resumed run starting with an empty log
  would give every agent total amnesia at the moment it came back — the exact
  failure `memory_for` exists to prevent, reintroduced by the restart. A torn
  final line from a killed run is skipped rather than fatal.

Proven end to end: advice POSTed into a saved world at h6.0, world resumed,
delivered at **h6.02**, and the agent reasoned about it on the record —
*"I might need to quit soon since I have to travel for a mining opportunity."*
