# Convoy — Agent Sandbox Validation Build
## Handoff Prompt for Claude Code

---

## Read This First

Three files, not equal in authority:

1. **`convoy_bronze_age_economy.xlsx`** (17 tabs) — the actual source of truth. Every rule, number, and live
   formula in this build originates here. If anything anywhere ever disagrees with this file, this file wins.
2. **`convoy_reference.md`** — a flattened, plain-text snapshot of the same spreadsheet (calculated values, not
   formulas), generated for fast reading and searching. Use it to scan rules quickly without a tool call, but
   treat it as a convenience copy, not an independent source — it can go stale if the spreadsheet is edited
   after this snapshot was taken. When in doubt, or before finalizing any number that matters, check it against
   the live spreadsheet.
3. **This prompt** — orientation and build sequencing, not a third source of rules.

Read the spreadsheet's **Read Me First** tab before touching anything else — it explains what Convoy is and
why this specific build exists. Then read every other tab, or the equivalent sections of the reference doc.
Do not start writing code until you've read through the whole thing once.

---

## What You're Building

A **headless economic simulation**, not a game client. No rendering, no Unity, no player input of any kind.

75 AI agents (15 each across 5 models — see the **Combat & Heroes** tab for the exact roster and OpenRouter
model IDs) live inside the Bronze Age economy defined in the spreadsheet for **120 real hours, no time
compression**. Every agent's only goal is to maximize their own **Net Worth** (defined on the **World State
Schema** tab) by the end of the run. There is no other objective, no scripted narrative, no human player.

**Deployment: this needs to run unattended on a small cloud VM, not interactively on a laptop.** No GPU or
rendering is needed — a lightweight always-on box (AWS EC2, DigitalOcean, Hetzner, or whatever integrates most
easily) is enough, and costs a few dollars for the full 120-hour window. A laptop closing its lid, sleeping, or
losing wifi mid-run would kill the simulation partway through, which is entirely avoidable by not building this
as something that has to stay open on a personal machine. Build with this in mind from the start — checkpoint
state to disk periodically so a VM restart doesn't lose the run, and design it to be started, disconnected
from, and checked on periodically rather than watched continuously.

The deliverable is: a running simulation, a full event log, and daily + rollup text reports generated from
that log (significance-tagged per the design discussed during development — routine actions are low
significance, notable ones like a bankruptcy, a successful heist, or a passed policy are high significance).

---

## Tech Stack Recommendation

Python is the natural fit here — data-heavy simulation logic plus API orchestration is exactly what it's good
at, and the whole thing can run as a single long-lived process with in-memory state, checkpointed to disk
periodically (don't lose 100 hours of a run to a crash). Node is a reasonable alternative if you have a strong
preference, but nothing about this build requires it.

All 5 models are accessed through **OpenRouter** — one account, one API key, one request shape, just a
different `model` string per agent. **Verify the exact OpenRouter model-ID strings against their live catalog
before hardcoding anything** — the ones on the Combat & Heroes tab are current as of this handoff but model
naming shifts.

---

## Build Phases — Do Not Skip Ahead

This mirrors how the Snowbrawl and Convoy Unity builds were sequenced: prove the smallest slice works before
spending real money or engineering time on the full thing.

### Phase 1 — Core Engine, Zero LLM Calls
Build the actual simulation: the 10 entities from the World State Schema tab as real data structures, the
production chain, the market/pricing formulas, the business staffing rule, the tax/bounty/insurance systems,
and the **Sustenance system** (Sustenance tab — eating, the Hungry/Starving/Death escalation, and the
Research-driven Tavern bread tiers). Drive it with 3-5 **simple rule-based agents** — no API calls, no
reasoning, just fixed logic that always produces the same output for the same input. These are throwaway test
tools, not a preview of the real roster. A concrete starting rule set, enough to actually exercise every system
above rather than leaving gaps:

- If Hours Since Last Meal > 8: eat (self-prep from inventory if holding Grain + Water, otherwise buy a meal
  at the nearest Tavern if affordable) — this is the one non-negotiable rule, since it's the only way to prove
  Sustenance actually triggers Hungry/Starving/Death correctly
- If not currently employed and Denari is low: travel to the nearest resource node and mine/farm
- If inventory is full or holding sellable goods: travel to the nearest business and sell
- If Denari crosses a fixed threshold (e.g., enough to afford the cheapest business): buy one, to exercise
  business ownership, staffing, and the bankruptcy path

Goal: prove resources flow, businesses can go bankrupt, prices update, Sustenance escalates and resolves
correctly, and nothing produces nonsensical state (negative Denari, phantom inventory, an agent starving to
death mid-mining-session with no warning, etc.)

**Duration:** simulate 48 game-hours. Since Phase 1 makes zero API calls, nothing is waiting on network
latency — let it run at whatever wall-clock speed the computation naturally achieves, no need to throttle it
to real time.

**Required output: a raw, timestamped log of every single event** (every action, every state change), saved
to a plain file (CSV or JSON, not just printed to console and lost) — this is what you'll actually review
before approving Phase 2. This is separate from and comes before the narrative daily-report generator (Phase
4) — don't wait for that to exist to get reviewable output here.

### Phase 2 — One Real Model, Small Scale
Wire in **one** model (start with the cheapest — GPT-5.6 Luna) for just 2-3 agents. Prove the full loop
end-to-end: world state → prompt → model call via OpenRouter → parsed action → executed against the
simulation → logged. This is where you'll find prompt-construction and action-parsing bugs — find them here,
not after paying for 75 agents.

**Duration:** run for 4 real hours, or stop early once every agent has completed at least 15 real decisions,
whichever comes first — this is bound by actual API latency, so it should run close to true real time, unlike
Phase 1.

**Required output:** same raw, timestamped event log as Phase 1, saved to a file — review this before
approving Phase 3.

### Phase 3 — Full Roster, Full Population
Scale to all 75 agents across all 5 models per the Combat & Heroes tab roster. Confirm the event-driven
scheduling model (see the **Agent Scheduling & Diary** tab — decisions trigger immediately on task completion
or an interrupt, plus a universal 15-simulated-minute re-evaluation checkpoint for every agent regardless of
current activity, not a fixed clock) is actually producing sensible request volume and cost in practice. Watch
actual token usage against the estimate for the first few hours of every model, not just one — this roster mixes
genuinely different providers and there's no guarantee they all behave identically under real load.

### Phase 4 — Memory & Reporting Layer
Add the significance-tagged memory log per agent and the daily/rollup report generator. This can reuse the
same log the simulation already needs to produce for debugging — don't build two separate logging systems.

### Phase 5 — The Real 120-Hour Run
Only after Phases 1-4 are each individually confirmed working. Let it run nonstop, no compression, and check
in periodically rather than waiting for the end — see something economically broken (a business type nobody
ever touches, a wage rate that's clearly wrong) and you may want to pause, adjust the spreadsheet, and resume
rather than discovering it only in a hindsight report.

---

## What NOT To Build Right Now

- No rendering, no Unity, no camera logic, no visuals of any kind
- No human-facing onboarding flow (the camel-rental sequence is for the real game, not this sandbox)
- No racing, no black market posting screen, no elected government — all explicitly out of scope per the
  Actions and Government & Insurance tabs
- No hero-camera-cutting logic — that's a presentation concern for a later, separate visual build

---

## A Note On How To Work

This spec is unusually complete — nearly every number, formula, and rule already has a defined value. That
means your job here is mostly **faithful, bounded implementation against a clear spec**, not open-ended
exploration or design decision-making. Given that, prefer focused, checkpointed sessions per phase over one
large autonomous run — review the output of each phase before moving to the next, the same way the Snowbrawl
build worked. This build doesn't need heavy multi-agent orchestration or an extended unsupervised loop to
succeed; it needs correct, careful translation of what's already fully specified.

If you hit a genuine ambiguity the spreadsheet doesn't resolve, stop and ask rather than guessing — the whole
point of this run is to test whether the *actual designed rules* produce interesting behavior, not whether an
improvised interpretation of them does.
