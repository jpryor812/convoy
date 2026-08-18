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
