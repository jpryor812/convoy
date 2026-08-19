# Phase 5 — the interactive demo

Goal: **watch agents work, ask them why, and give them advice they can act on.**
Then show it to schools, and use the footage to market the game.

This supersedes nothing. PHASE4.md is still the state of the world; VISUALS.md
is still the art plan; this is the build order to get from those to a demo.

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
