# Handoff prompt

Copy everything below the line into a new chat window.

---

I'm continuing work on Convoy, a headless LLM-agent economic simulation in
`/Users/justinpryor/Downloads/convoy-main`.

**Read `PHASE4.md` first** — it is the current state of the world and supersedes
PHASE3.md, PHASE2.5.md, PHASE2.md and PHASE1.md. Then read `PHASE5.md` (the
build plan I'm working through now), `VISUALS.md` (the art plan) and
`art/PROMPTS.md` (Meshy prompt templates).

**Ignore `convoy_bronze_age_economy.xlsx`, `convoy_reference.md` and
`claude_code_handoff_prompt.md`** — all stale snapshots. `convoy/data.py` is the
source of truth.

**Read §2 of PHASE4.md carefully before debugging any agent behaviour.**
Thirteen times now, "the agents are being stupid" has turned out to be the
observation failing to tell them something the code already knew — including
several times by the agent that was fixing the others. Suspect the observation
before the model.

## Where things stand

The economy works. The 2026-08-17 run: 20 agents, 84 simulated hours, $2.64,
23 businesses, 134 deliveries, zero bankruptcies, the full chain player-owned
(ore → Bronze/Iron → Bronze Daggers). Owner consent for hiring proven live.

Since then:

- **Agents now record their reasoning** (PHASE4 §9). `llm.py` used to capture the
  model's text only on replies with NO tool calls — it fired twice in 6,916
  calls. Now every decision is recorded on `Agent.reasoning` and in the event
  log. This is what makes "why did you do that?" recall instead of confabulation.
- **A starvation death was misdiagnosed** (PHASE4 §10). An agent starved at hour
  81 while idle and rich. It was NOT a missing wake trigger — the agent had
  exhausted the run's per-agent decision cap at hour 45, and `CappedPolicy`
  silently swallowed every wake after that. Fixed with a survival reserve.
- **`render_world.py`** turns a finished run into a self-contained HTML map with
  a time scrubber and a click-an-agent transcript panel.
- **`convoy/sprites.py`** binds every entity to art, with a completeness check
  that runs inside `run_phase1.py` beside the economic invariants.
- **Art direction settled**: Fortnite rendering, Iron Age subject matter. I'm
  generating characters and buildings in Meshy now (`art/PROMPTS.md`). An earlier
  Blender pipeline (`art/blender_rig.py`, `art/blender_assets.py`) produced 24
  assets and is being superseded — but keep the rig, it is still the right tool
  for processing Meshy output.

## What I want next

Per `PHASE5.md`, in order:

1. **A run with reasoning in it.** Every full-size run predates the reasoning
   fix — the 84-hour run has 2 reasoning events. This blocks the transcript,
   chat and recommendation features. It also discharges PHASE4 §7 (three
   labour-market fixes, unit-tested, never exercised live).
2. **A recommendation channel** — I want to give an agent advice and have it
   able to act on it. This is a simulation change, not a UI feature: it needs an
   inbox on `Agent`, delivery through `observe.py` **at the decision**, and event
   evidence of whether the agent followed it. §2's lesson applies in advance.
3. **An interrogation backend** — load a finished run, ask an agent questions.
   Answer from `Agent.reasoning` first and only call a model when a question
   needs real synthesis; that is cheaper and more truthful.
4. **The 3D world** — Meshy → GLB → React Three Fiber. Note terrain, roads and
   grass are code, not Meshy assets.

The end state is a demo for schools where students watch agents work, interrogate
their decisions, and judge whether a choice was smart given the market — plus
footage for marketing the game.

## Harness checks before any run

```bash
for t in tests/test_*.py; do python3 "$t" >/dev/null && echo "PASS $t" || echo "FAIL $t"; done
python3 run_phase1.py | grep INVARIANT      # must say "all clean"
python3 run_phase2.py --dry-run
```

## Gotchas

- **Run `run_phase1.py` after ANY change to `convoy/data.py`.** Its invariant
  checker has caught bugs the unit tests missed, and it now also verifies that
  every entity has art.
- **Budget runs by expected BUSINESS count, not agent count.** The last run cost
  $2.64 and 12 hours against a $1.34/9h projection, because 23 businesses
  generate far more decisions than 4.
- **Watch `events.jsonl`, not the console.** Nothing calls `EventLog.flush()`, so
  both fill in ~8KB chunks. A quiet log is buffering, not a stall.
- **Match the interpreter path** when checking processes:
  `pgrep -f "MacOS/Python run_phase2.py"`. A bare `pgrep -f run_phase2.py` also
  matches your own monitors.
- `OPENROUTER_API_KEY` is in `.env`; there are credits on the account.
- Blender MCP is configured (`claude mcp list` → blender). It needs Blender open
  with the BlenderMCP panel started, and `uv` is routed to `~/.uv/` because
  `~/.local` is owned by root on this machine.
