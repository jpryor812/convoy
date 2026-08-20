# Phase 5 — the interactive demo

Goal: **watch agents work, ask them why, and give them advice they can act on.**
Then show it to schools, and use the footage to market the game.

> **SUPERSEDED BY `PHASE6.md` — 2026-08-20.** This is the plan; PHASE6 is what
> was built, and it diverged. The world is now three places rather than seven,
> the art is Pipoya and isaiah658 rather than Meshy and Kenney, and the
> click-through UI described here as future work exists. Read PHASE6 for current
> state; read this for the reasoning that led to it.

PHASE4.md is still the state of the ECONOMY. VISUALS.md was the art plan and is
now partly superseded; this was the build order to get from those to a demo.

---

## The one thing that blocks everything

**There is still no run with reasoning in it.**

| run | agents | hours | reasoning events |
|---|---|---|---|
| 20260817-004401 | 20 | 84 | **2** |
| 20260817-161544 | 4 | 6 | 17 |
| 20260817-161958 | 4 | 6 | 7 |

Reasoning capture was fixed on 2026-08-17 (PHASE4 §9) and is verified working —
but every full-size run predates it. Transcripts, the chat feature, and the
recommendation feature all render empty against the only 84-hour run.

**Do the run early.** ~$3 and ~12h wall clock at 20 agents / 84h. It also
discharges PHASE4 §7 — three labour-market fixes that are unit-tested and have
never been exercised by a live model.

---

## Progress, 2026-08-18

| step | state |
|---|---|
| 1. a run with reasoning | **running** — 20 agents / 84h / `--advise`, started 12:42. Reasoning is firing on nearly every decision (28 in the first 0.02h, against 2 in the whole previous 84h run) |
| 2. recommendation channel | **done and proven live** — PHASE4 §13. 6/6 delivered after the wake fix; 0/6 before it |
| 3. interrogation backend | **done** — PHASE4 §14. `serve.py`, answers from the record, cites hours |
| — persistence / resume | **done, unplanned** — PHASE4 §15. `checkpoint.load()` had never worked; four types were unregistered |
| 4. the 3D world | not started |

Order was Step 2 before Step 1, per the note in Step 2 below — so the big run
carries the advice plumbing and one $3 run buys both.

---

## Step 1 — a real run

```bash
for t in tests/test_*.py; do python3 "$t" >/dev/null && echo "PASS $t" || echo "FAIL $t"; done
python3 run_phase1.py | grep INVARIANT      # must say "all clean"
python3 run_phase2.py --dry-run

nohup python3 run_phase2.py --agents 20 --hours 84 --decisions 400 \
  --rpm 10 --max-tokens 1024 --model openai/gpt-5.6-luna \
  > runs/phase2/live.log 2>&1 &
caffeinate -is -w $(pgrep -f "MacOS/Python run_phase2.py" | head -1)
```

Watch for: `llm_reasoning` volume (should be ~1 per decision, not 2 per run),
plus `job_posted` / `job_applied` / `hired` with `via` / `quit_job` with
`reason` for the §7 fixes.

**Budget by BUSINESS count, not agent count.** The last run cost $2.64 against a
$1.34 projection because 23 businesses generate far more decisions than 4.

---

## Step 2 — the recommendation channel  ← the risky one

**This is a simulation change, not a UI feature, and it is the part most likely
to go wrong.**

For an agent to act on advice, three things must exist:

1. somewhere to put a recommendation (a per-agent inbox on `Agent`)
2. `observe.py` must carry it **at the decision**, not merely somewhere in the
   briefing
3. the event log must record whether the agent followed it

Point 2 is PHASE4 §2 in advance. That table has thirteen entries and every one
is the observation failing to say something the code already knew. The
predictable failure here is "the agent ignored my advice" when in fact the
advice never reached the prompt. Build it expecting that.

Point 3 is what makes it a *teaching* tool rather than a toy. A student saying
"I told it to sell the ore and it didn't" needs to be checkable.

Build and test this against the existing 4-agent smoke run before Step 1's big
run, so the big run exercises the plumbing.

---

## Step 3 — the interrogation backend

A small server that loads a finished run and answers questions about it.

```
GET  /run                     summary, agents, hours
GET  /agent/{id}              state, businesses, inventory
GET  /agent/{id}/transcript   its decisions, from Agent.reasoning
POST /agent/{id}/ask          a question
POST /agent/{id}/advise       a recommendation (Step 2)
```

**Answer from the stored record first.** "Why did you buy charcoal at hour 40?"
is already answered verbatim in `Agent.reasoning` — return it, with no model call
at all. Only call a model when a question genuinely needs synthesis across
several decisions.

That is both cheaper and more truthful. It is the entire reason reasoning capture
was fixed: regenerating an answer produces fluent confabulation, and the point of
the classroom exercise is that a student can check what the agent actually said.

**Cost control is a product risk, not a detail.** Thirty students × twenty
questions is 600 calls per session.

---

## Steps 1-3 — where they actually got to (2026-08-18)

**Step 1 is running.** 20 agents, 84h, started 12:42. At h17.4 it had **412
reasoning events and 0 API errors** — against 2 reasoning events in the whole
84-hour run this replaces. §7's labour market is being exercised live:
`job_posted`, `job_applied`, `hired`, `quit_job` all firing.

**Step 2 is built and proven live.** The channel is
`state.Recommendation` + `Agent.inbox` -> `observe.advice_for` ->
`llm.advice_outcome`, with `convoy/advice.py` as the way in and a scripted
`Advisor` so an unattended run exercises it. Delivery is recorded at the ONE
point where words enter a prompt, so "it ignored me" and "it never heard me" are
different rows — that is the whole design, and it is PHASE4 §2 answered in
advance rather than after the fact.

It worked on the first live firing. Advice at h6.00 to found a mine:

    h6.00  advice_given      A0014
    h6.18  advice_delivered  A0014
    h6.18  end_shift, travel_to, start_business (REFUSED - wrong location)
    h6.53  travel_to
    h6.68  start_business    <- founded
    h6.93  set_production, set_retail_price, quit_job

And A0011, h6.23, declining it in as many words: *"My mentor seems to have been
mistaken since all the [plots] I can't find."* An agent disagreeing with advice
and saying why is the artifact a classroom needs, and it is not something the
harness had to be asked for.

**Step 3 is built.** `convoy/interrogate.py` + `serve.py` + `conversation.py`.

Two corrections to the plan as written, both from Justin, both right:

1. **The model answers by DEFAULT now.** This document said "answer from the
   stored record first, call a model only for real synthesis", and the keyword
   gate that implemented it made "why did you buy charcoal?" return
   `At hour 12.0 I was woken because: reevaluation. I did: buy_item.` A printout,
   not an answer. The half worth keeping was never recall-instead-of-a-model, it
   was GROUNDING — the model is shown the agent's retrieved decisions, told to
   use nothing else, and the citations come back beside the answer so a student
   can check it. Recall is now the fallback for no key and no budget
   (`--no-model`), which is what a classroom losing its API key should get.
2. **Conversations persist and feed back.** An agent that cannot remember you
   asked it something is answering a form, not conversing.

Conversations live in `conversations.json` beside the run, **not** in the
checkpoint. Advice is meant to change the world; a question must not, or no
answer about that world means anything afterwards — you would be measuring the
interview. It also means a run can be questioned WHILE it runs without racing
the engine's hourly checkpoint write, which is how the above was tested.

Proven live against a real run:

> **Q.** was that a good idea, looking back?
> **A.** ...it seemed like a reasonable idea (h0.02, h3.18). **But I couldn't say
> whether it was actually a good decision looking back, because the record
> stopped while the shift was still underway** and didn't show the earnings.

That refusal is the product. And a follow-up with no keyword anchor —
*"you mentioned travel costs a moment ago, what did you mean?"* — resolved the
referent out of conversation history, grounded it at h0.02, and then bounded
itself: *"I didn't record a more precise fare, so that's all I can say."*

`tests/test_advice.py` (14), `tests/test_interrogate.py` (17),
`tests/test_conversation.py` (11). The one that matters is
`test_history_reaches_the_prompt` — history in a file nobody sends is not memory,
which is §2's failure mode one layer up.

### Dropped: the counterfactual

"Agent 4's refinery would have gone bankrupt" needs a control branch nobody is
going to run, and generated from a model it is exactly the confabulation
reasoning capture was fixed to prevent. Dropped by decision on 2026-08-18.

What survives is the `Snapshot` taken on every recommendation — the whole
leaderboard, every agent's net worth and cash, and each business's hours of
payroll runway, at the instant advice landed. Before/after is then arithmetic
over recorded facts. It is free, and it cannot be reconstructed later, which is
why it is taken now even though the feature it was for is gone.

### What a database would and would not fix

The decision-by-decision library already exists: `events.jsonl`, one row per
decision with hour, actor, location, the agent's verbatim reasoning and what it
did. A full 84-hour run is **6 MB**.

A database will not make agents remember better. An agent's memory is what
reaches the prompt — `Agent.reasoning` keeps 40 decisions and `thinking_for()`
shows the last **5**, so an agent at hour 80 cannot recall hour 12 whether those
rows sit in JSONL or Postgres. Storage was never the constraint; retrieval into
the prompt is. The feature that would actually extend agent memory is a TOOL the
agent can call to search its own history, and that works over either store.

**Assets at each decision — added 2026-08-18.** `Agent.assets(world)` rides on
every `llm_reasoning` event: cash, net worth, location, hunger, cargo against
capacity, vehicles, home, job, and every open business with its **cash and
payroll per hour** — the two numbers behind every insolvency in the last run.
"Founded a mine with 345 denari in hand" and "founded a mine with 175" are
different decisions to judge, and an append-only log cannot recover a balance
after the fact.

Three deliberate limits:

- **On the event, NOT on `Agent.reasoning`.** The ring buffer is what an agent
  carries in its own prompt, and it already reads its balances off the
  observation. Forty copies of a fact it can see is PHASE4 §9's separate-budgets
  argument one scope down. `test_assets_are_not_on_the_agents_own_ring_buffer`.
- **Optional everywhere it is read.** Every run already on disk predates this,
  the 84-hour run included, so `Citation.assets` is nullable and `position()`
  returns "" rather than guessing. A tool that only worked on runs made after
  the feature landed would be useless on the whole archive.
- **Counts and ids, not nested state.** It fires ~7,000 times in an 84-hour run.
  Measured: **+404 bytes per decision, +2.8 MB on a 6.0 MB log.** The static
  prompt prefix is untouched at 22,159 chars, so the cache contract holds.

The interrogator feeds it to the model as a `you held:` line under each cited
decision, and is told those numbers are real and that their ABSENCE means it
does not know — so "what could you afford?" is answered from the ledger rather
than estimated.

Where a database IS needed is multi-user worlds, sign-in and concurrency. That is
product infrastructure, not agent cognition. Mirror the event log into it rather
than replacing it, so the sim still runs offline on a school laptop.

---

## Step 6 — a world you can hold open (2026-08-19)

`Engine.run` was a closed loop from hour zero to the end of the run. A world
could only be watched after it was over, so advice given to a finished run
changed nothing — there was no future left for it to change, and no amount of UI
work on top could have fixed it.

`Engine.step_until(end, wall_budget_s=)` is the seam; `convoy/live.py` is what
sits on it. `LiveSession.open(run, branch_to=...)` resumes a checkpoint, and
`advance()` pushes the world forward a slice at a time and returns **only the
events from that slice** — a viewer polling wants the delta, not the history
redrawn every frame.

**Branching is the default, and it is also the persistence model.** A session
copies the baseline and everything after belongs to whoever is driving. The
shared hour-53 valley stays intact for the next person, and — the real reason —
*if everyone edits one world, "what did MY advice change?" has no answer.* A
signed-in user's world is their branch directory.

### Two bugs the tests caught, both silent

**The branch spliced two timelines.** A checkpoint is written hourly but the
parent keeps running after it, so its log always overshoots the state a branch
starts from. Copying it wholesale put **240 events from a future the branch will
not have** into the history it starts with. Nothing raises; the map just draws
both. `_copy_history` truncates at the fork.

**The world raced.** `speed=1e9` left the sim clock unthrottled — fine for a
batch run, where model latency was the only brake. With no calls to wait on, a
0.4-second slice advanced the world **300 simulated hours** and starved everyone
in it. `DEFAULT_SPEED = 60` is a CEILING: when agents are thinking the models are
slower and the world runs at whatever they manage.

### Talking to an agent that is still working (2026-08-19)

`LiveSession.status()` gives a viewer, per agent: what it is doing in words
("working as Miner", "travelling to Town"), road progress 0–1, and **when it
next gets a turn** — in simulated seconds and in real seconds, converted at the
rate the session has actually achieved rather than at `DEFAULT_SPEED`, which is
a ceiling the models are usually slower than. A countdown that promises a
decision in 20 seconds and delivers it in three minutes teaches a viewer to
ignore it.

**The countdown targets the next DECISION, not the end of the activity.** A work
shift's `ends_at` sits in the past — measured at −337 simulated minutes on the
saved run — because shifts run until something ends them. A bar built on it
reads as permanently overdue. What a person needs is when the agent next
*listens*, because that is when anything they say takes effect.

`LiveSession.ask()` answers from the record **and** the present. The
finished-run interrogator only knew the log, so asked what it was going to do
next it could only say nothing had happened yet; half of talking to someone
still moving is that they know where they are standing. The present is rendered
as prose, not handed over as a dict — a model given `{"ends_at": 185340.0}` will
narrate the epoch timestamp back at whoever asked. Asking does not wake the
agent or touch the world; `test_asking_a_live_agent_does_not_move_the_world`
pins that.

**You do not have to wait for the shift to end.** Unheard advice already forces a
wake — the engine does this because six recommendations once expired unseen
while their targets stood at a bench, which is §2 one layer down: not the
observation withholding a fact, but the schedule withholding the observation.

Proven live on the h53 branch, A0021 mid-shift as a Miner:

> **You:** what are you in the middle of right now?
> **A0021:** I'm part-way through my Miner shift at the Government Mining
> Operation, at Copper Gulch. I've got 1009 denari, I'm hungry, and I own my own
> Mining Operation, which has 460 cash; my wage is 20.56 per hour (h53.0).

> **You:** and what are you planning to do after that?
> **A0021:** I hadn't recorded a definite plan for after this shift. My last
> recorded plan was to eat first, then haul ore to the refinery and sell it
> (h17.75).

Advised to stop hauling and pay a courier, it was pulled off the shift, reasoned
*"Evaluating courier options — I'm considering whether to hire a courier or use a
hauling option for stone"*, ended the shift, and advertised in world chat:
*"My mine B0031 at Copper Gulch is full/stalled with Copper Ore. Refinery owner
please order 100+ Copper Ore at 5.04 and post a courier; stock ready."*

It took the SPIRIT of the advice and found its own route to it, rather than
calling the tool it was told to call. That is the behaviour worth showing a
classroom, and it is only legible because the advice and the actions are
recorded side by side.

### The production countdown (2026-08-19)

Asked for a time-based "how long until output", and it turned out to need no
mechanics change at all: **`biz.production_buffer` already exists.** Production
accrues fractionally at `Engine.production_rate` and pops a whole unit at 1.0, so

    time to next unit = (1 - production_buffer) / rate

was always derivable and had simply never been shown. Skill already feeds it too
— `worker_output_rate` takes `skill_hours`, so a practised miner genuinely has a
higher rate and a shorter countdown. That has been true since Phase 1 and was
invisible.

**`production_rate` was extracted out of `_produce` rather than reimplemented.**
A viewer that recomputes the rate works until one of the two copies changes, and
then the bar reaches zero at a moment nothing happens, with nothing raising. One
function, two callers. It takes `credit_skill_hours`, defaulted to 0, because a
viewer polling four times a second must not be able to train the whole valley to
mastery — `test_asking_for_the_rate_does_not_train_the_crew`.

Real cadences off the h53 branch, which are watchable at 7x:

| business | making | u/hr | next unit | status |
|---|---|---|---|---|
| luna-14's Mine | Copper Ore | 78.8 | 0.2 sim-min | **yard is full** |
| Government Refinery | Charcoal | 37.4 | 1.2 sim-min | running |
| luna-07's Tavern | Meal | 11.1 | 5.2 sim-min | **out of Purified Water** |
| luna-01's Weaponsmith | Bronze Dagger | 1.9 | 30.4 sim-min | **out of Lumber** |

A stalled yard reports WHY rather than showing a bar that never moves. "Blocked"
and "slow" look identical on a progress bar and need completely different things
done about them.

**Output is POOLED, and saying so beats faking it.** A business fills one buffer;
individual workers do not each finish their own unit and carry it in. So "when
will this miner deliver" has no answer, and inventing a per-worker timer the
engine would not honour would be a lie a demo tells for a whole session.
`worker_shares` gives what does exist and is what an owner actually wants: each
worker's units/hour and share of output beside their wage, which prices the crew.

**A bug the first render caught.** Two Government Refinery workers were credited
with 90% of output EACH — 180% of a number the engine holds flat. A state
business produces `base_rate` by exemption however many people stand in it, so
per-worker attribution there is a fiction and the only honest split is an equal
one. `test_a_state_business_splits_evenly_rather_than_double_counting`.

`tests/test_live.py` is now 20 tests.

### The owner's forecast (2026-08-19)

`LiveSession.forecast(minutes)` projects each business forward: units expected,
what they are worth, wage cost, cash at the end, per-worker contribution, and the
constraint that will bite first.

**Rate x time is not a forecast.** A mine running at 78.8 units an hour into a
yard with room for nine will make nine and stop. The horizon is clipped by
`Engine.production_headroom`, and the binding constraint is named.

**The payroll asymmetry is the point.** An NPC bills only for hours the business
can produce; an agent employee bills for every hour on shift, stalled or not
(PHASE4 §5). So a blocked business keeps paying its people and stops paying its
machines, and an owner could not see that anywhere. Every payroll failure in the
84-hour run was NPC-staffed. A wage of 0 is a third case — the owner working
their own business, the only arrangement that never failed — and a flat
"paid even if stalled" flag called all three the same thing.

**Producing is not earning.** Units land in the yard, not the till; `cash_at_end`
falls by payroll alone. Showing projected revenue as income would make a stalled,
cash-bleeding business look profitable.

**Two bugs, both mine, both the same mistake.** The first version worked the
constraints out inside the viewer and got the exemptions backwards — it read
"government" as "unconstrained" and promised 36 units an hour out of a mine the
engine had already stalled, then warned all three state sites their crews were
about to walk over a cash balance `_pay_wages` never touches. Fixed by extracting
`production_headroom` alongside `production_rate` and having the viewer read
both. **Anything a dashboard asserts about the world has to come from the code
that runs it.**

### What the forecast found immediately

Of 17 businesses set to produce at h53, **one will make anything in the next
hour**:

| | |
|---|---|
| producing | **1** |
| yard full, nothing can be made | 7 |
| out of feedstock | 6 |
| idle | 2 |

The valley is haulage-bound, not production-bound. Mines are full and refineries
are starved *at the same time*, which is a distribution failure — and it lines up
with `already delivered` being the largest refusal class in PHASE4 §12, and with
A0021 using world chat to beg someone to come and collect:
*"My mine B0031 at Copper Gulch is full/stalled with Copper Ore. Refinery owner
please order 100+ Copper Ore at 5.04 and post a courier; stock ready."*

That is a design question, not a bug, and the dashboard is what made it visible
in one screen.

`tests/test_live.py` is now 27 tests.

### On "make it real time"

Measured, and two of three proposed changes turned out to be unnecessary:

| | |
|---|---|
| decisions per simulated hour | 29.2 |
| API calls per decision | 2.8 |
| **calls per simulated hour** | **82** |
| at 10 rpm, serial | **8.2 wall minutes per sim hour → 7.3x** |
| whole valley end to end | 5 sim min = **41 wall seconds** |
| mine (spur) to town | 6.5 sim min = **53 wall seconds** |

- **Scaling production 5x: don't.** `--time-scale` exists and its own docstring
  says why — wages are per simulated hour, so 5x output makes labour 5x cheaper
  and the economy stops describing anything.
- **Paying every 10 minutes instead of hourly: already done.** `_pay_wages(hours)`
  runs every tick against `dt / 3600`. Payroll has always been continuous.
- **A tighter map: not needed.** A cart already crosses the whole valley in 41
  wall seconds.

**The sim clock was never the bottleneck — it has been unthrottled all along.**
The limiter is request throughput, so the levers are the account's rpm and
concurrency (PHASE4 §12, still unbuilt: calls are serial).

`tests/test_live.py` — 10 tests against a scripted transport. The two that matter
are `test_branch_does_not_inherit_the_parents_future` and
`test_advice_reaches_a_LIVE_agent`.

**Blocked on credit.** Verified live: resumed h53, branched, advice delivered
(seen 3x from h53.02), checkpoint saved, reopened where it left off. Agents took
zero actions — every call returned `Prompt tokens limit exceeded: 14002 > 4801`.
The ceiling scales with the remaining balance and fell from 7,044 to 4,801 during
one afternoon's testing.

---

## Step 7 — land, and the seller's side of haulage (2026-08-19)

### Land

Plots became an owned, tradeable asset and **headcount became a property of
land**. A business stands on `STRUCTURE_PLOTS` (2), worked by the owner unpaid,
and seats one employee per developed plot beyond that. Founding gives 4, so two
hires; a third means buying ground and building on it (75 + 1h, or 2x to skip
the wait, both +50% per plot already held).

`employee_cap` returned None for every player business until now, so hiring was
limited by cash alone. `BusinessType.max_employees` had existed since Phase 1,
was set to 2 on every store, and was read by nothing — there is still a constant
called `MAX_EMPLOYEES_PRODUCTION_UNUSED`.

Junctions had land added: they returned `10**6` free plots, and **15 of the 24
businesses in the 84-hour run stood on that exemption**. Town 60, Refinery Row
48, waystations 28, wilderness 20. At 20 agents with a business and a home each
(160 plots) land does NOT bind — spurs 18% used, junctions 23%. It binds at
**Town specifically** (10 businesses after the state seats itself) and on
expansion. Town's 60 is the knob, not the total.

**Storage is the startup cost.** A flat 240 said a farm and a refinery are the
same building. Farm 150, Mining 175, Refinery 450; tiers add half the base again
so the ratio survives upgrading. This SHRINKS a farm from 240 — at 72 Wheat an
hour, a full yard in 2h05m rather than 3h20m. Deliberate: the pressure to move
goods is why carts and couriers exist.

Stores keep the per-plot rule (100/plot) — their land IS their shelf space.

### Two corrections to what this document said

**Inputs already required hauling.** Auto-sourcing was removed for player
businesses on 2026-08-15; only government sites still auto-source, as the market
floor. The comment in `_produce` describing auto-shipped raw materials is stale
and was believed for most of a session.

**The courier market is not broken.** In the 2026-08-18 run: 30 claimed, 30
collected, **30 delivered**, one refusal on delivery and zero on capacity. The
124 `already delivered` failures in PHASE4 §12 are from the older run.

### The actual jam, and the primitive that fixes it

**Only a BUYER could create haulage.** `order_from_business` is a pull, paid
upfront. So a mine with a full yard had no way to push — it could only wait for
someone solvent to want its ore. The stalled refineries at h53 held 40, 52 and
0.2 denari. Mines full of exactly what they needed; nobody able to pay to move
it.

`post_delivery_job` is the seller's side: pay a courier to move YOUR stock to a
government business or one you own. **The goods leave the yard at once**, so a
full site produces again the moment the load is posted. Announced in world chat.
Delivery to a state site is a sale on arrival at the standing price, which makes
"post it and get producing again" a move an owner can always make.

Third-party delivery is deliberately refused and points at
`order_from_business` — a delivery to someone else is a sale, and a sale needs
the other side to agree a price and hold the cash on the day.

### Carriage is priced on cargo value, not time — and the load is SEALED

The valley crosses in five simulated minutes, so a time-based fee prices every
job at four denari and prices a cart of daggers like a cart of stone.

The **owner** is recommended roughly a tenth of what the load is worth, half
again through the worst country — `value x (10% + 8% x danger)` plus handling
and a small time term. It is a recommendation: they may offer anything above the
floor, and a load nobody will take at the asking price is information too.

| route | danger | cargo | fee | % |
|---|---|---|---|---|
| Millrace Farms -> Refinery Row | 0.00 | 200 | **22.38** | 11.2% |
| Millrace Farms -> Town | 0.65 | 200 | **34.02** | 17.0% |
| Copper Gulch -> Refinery Row | 0.00 | 600 | **62.38** | 10.4% |
| Copper Gulch -> Town | 0.65 | 600 | **94.82** | 15.8% |

Same cargo, half again as much to cross the Broken Country — the distance
advantage, visible in the price. The per-segment danger model has existed since
Phase 1 and had never priced anything.

**The COURIER sees none of that.** A carriage advert names a price, a route and
a name — not an inventory:

    CARRIAGE WANTED: a load from Copper Gulch to Refinery Row, pays 62.00.
    A Donkey Cart comes with it. accept_courier_job("C0059") to take it.

    {"id": "C0059", "from": "Copper Gulch", "to": "Refinery Row", "pays": 62.0,
     "travel_minutes": 1.5, "worst_road": "no open road -- same junction",
     "hired_by": "Marcus", "vehicle_provided": "Donkey Cart",
     "you_can_carry_it": true}

A courier is hired to move a cart, not to appraise it. A board that published
what every load was worth would be one where the valuable jobs go instantly and
everything else rots. What is in the cart becomes apparent at pickup.

`you_can_carry_it` is DERIVED, never disclosed — a consignment moves whole, so a
courier on foot would otherwise burn a decision finding out it cannot lift the
load. It answers for that agent, counting any lent vehicle, and leaks no
quantity. Route danger stays public because it already is: it is in the static
briefing, and withholding it would only make the price unreadable.

### Lent vehicles

A consignment moves WHOLE, so a courier on foot (capacity 5) cannot take a
100-unit load at all. An owner may lend a vehicle with the job; it is bound to
the consignment, never transferred, and returns on delivery, cancellation or
abandonment. It cannot be stolen by construction, so lending needs no trust
system.

Jobs a courier cannot carry sort last however well they pay: an unliftable job
is not an opportunity, it is a wasted decision.

### Still true, and worth knowing

Production stops when the owner hauls — `production_rate` requires
`activity.kind == "work"` at that business — and employees can haul while the
owner keeps producing. Both were already the case; no change needed.

`tests/test_b2b_haulage.py` gained 9 tests.

---

## Step 4 — the 3D world

Stack: **Meshy → GLB → React Three Fiber** (see `art/PROMPTS.md`).

**Terrain, roads and grass are NOT Meshy work.** Meshy makes discrete objects.
Ground is a plane or heightmap with a tiling texture; roads are geometry along a
spline between the seven junctions; grass is instanced billboards or a shader.
That is code, and it can be built before any asset arrives.

Agent positions already exist. `render_world.py` reconstructs a per-agent
position track from the hourly diary plus `travel` events, and interpolates along
roads. That logic ports directly — the 3D scene consumes the same payload.

**Poly budget.** Characters came back at ~10k triangles (fine). The first
refinery was **1.94M** (unusable). Target 2k–10k per building, ~500k for the
whole scene. Find Meshy's game-ready export before generating a library.

---

## Step 5 — demo and content

One finished run, the 3D world, the ask box, the advise box. Record footage for
marketing while the demo is being shown to teachers — the same asset serves both.

---

## Division of labour

While characters and buildings are being generated in Meshy, the work that has
no art dependency is:

- **Step 2** — the recommendation channel (pure `convoy/` Python)
- **Step 3** — the interrogation backend
- **Step 4's terrain/road/grass code** — no assets needed
- Status and chat bubbles in the 2D viewer (VISUALS.md §1, §2) — cheap, and they
  keep an interim demo usable while the 3D world is built

---

## What carries forward, and what does not

**Carries forward:**
- the whole simulation — untouched by any of this
- `convoy/sprites.py` — engine-agnostic entity → asset binding; the same job for
  GLB as for PNG, with per-asset fallback so art can land one piece at a time
- `render_world.py`'s position reconstruction and payload shape
- the silhouette cues worked out in Blender, now encoded in `art/PROMPTS.md`

**Superseded by Meshy:**
- `art/blender_assets.py` models. Keep the file — `blender_rig.py` is still the
  best tool for *processing* Meshy output (decimate, normalise scale, Draco
  compress), and both compressors are confirmed working in this install.
