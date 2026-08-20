# Handoff — Convoy, 2026-08-19

Copy everything below the line into a new chat window.

---

I'm continuing work on **Convoy**, a headless LLM-agent economic simulation in
`/Users/justinpryor/Downloads/convoy-main`. The next job is **putting the art on
the map**.

## Read these, in this order

1. **`PHASE4.md`** — the state of the world. Supersedes PHASE3/2.5/2/1.
2. **`PHASE5.md`** — the build plan, and the record of everything done since.
   Steps 6 and 7 at the bottom are the newest and the most relevant.
3. **`VISUALS.md`** — the art plan. §1, §2 and §9 matter most now.
4. **`art/PROMPTS.md`** — the Meshy prompt templates that produced the assets.

**Ignore `convoy_bronze_age_economy.xlsx`, `convoy_reference.md` and
`claude_code_handoff_prompt.md`** — all stale snapshots. `convoy/data.py` is the
source of truth for the economy.

**Read §2 of PHASE4.md before debugging any agent behaviour.** Thirteen times,
"the agents are being stupid" has turned out to be the observation failing to
tell them something the code already knew — several times by the agent fixing the
others. Suspect the observation before the model. That lesson recurred twice
more this week in new forms, both recorded in PHASE5.

---

## THE JOB: put the art on the 2D map

**Decision made: 2D first.** This phase is about *observation* — watching agents
work and talking to them about what they did. 3D comes later; the same GLB files
feed React Three Fiber when it does, so nothing generated is wasted.

### The pipeline

    art/Meshy/*.glb  ->  art/blender_rig.py  ->  128px top-down PNG  ->  convoy/sprites.py  ->  the map

`blender_rig.py` already exists and is tuned: orthographic camera at **48°**
(not 60, not 30 — measured), 128px, transparent PNG, Freestyle outline pass, sun
plus heavy ambient, **`Standard` view transform — never AgX**, which silently
desaturates everything. Read VISUALS §8 before touching it; two of its settings
are load-bearing and non-obvious.

**Characters render at 10°, not 48°** — near eye level. Vehicles at 14° and
broadside into a 192x96 canvas. Those angles are per-category and deliberate;
VISUALS §11 and §13 explain why each one is what it is.

### The assets, measured

`art/Meshy/` — 16 GLB files, **177,596 triangles, 229 MB**. No duplicates
(there was one; it is fixed).

| kind | file | maps to |
|---|---|---|
| building | `farm-meshy.glb` | Farm |
| building | `Meshy_AI_Cliffside_Chapel_Mine_...glb` | Mining Operation |
| building | `refinery.glb` | Refinery |
| building | `tavern-meshy.glb` | Tavern / Inn |
| building | `blacksmith-meshy.glb` | **Weaponsmith / Armory** |
| building | `stable-meshy.glb` | Vehicle Dealer / Stable |
| **characters (10)** | african-man, african-woman, asian-girl, asian-man, indian-man, indian-woman, persian-girl, persian-man, viking-girl, `Meshy_AI_Redbeard_Ironfoot_...glb` | |

The split is corroborated by the files themselves: **all six buildings carry zero
animations, and nine of the ten characters carry three each.** The exception is
`Redbeard_Ironfoot`, a character with no animation clips — irrelevant for static
top-down sprites, but he will be the only one who cannot walk when 3D arrives.

**Ten characters for five models.** `convoy/sprites.py` binds one look per model
(`D.EFFORT_BY_MODEL`'s roster), so there is more variety here than the sim
currently asks for. Two obvious uses: a second look per model so twenty agents
are not five faces repeated four times, or plain/owner pairs as VISUALS §13
describes. That binding is a decision for whoever picks this up.

**Poly count is a non-issue** — well under the 500k scene budget, and the
1.94M-triangle refinery problem in `art/PROMPTS.md` is solved. Meshy's
game-ready export works.

**96% of the 229 MB is PNG textures**, mostly 4K. Geometry is ~11 MB.
*For the 2D route this barely matters* — textures get baked into a 128px sprite
and thrown away. **Do not spend time compressing textures for the 2D map.** It
becomes the top priority the day 3D starts, and `blender_rig.py` has the tooling.

`blacksmith-meshy.glb` also exported as JPEG while the rest are PNG — Meshy's
settings varied between sessions. Harmless here.

Note `blacksmith-meshy.glb` is a BUILDING (the Weaponsmith), not a person — the
name misleads, and it is the one file in the folder whose contents are not
obvious from its filename.

### Business types WITHOUT a Meshy building — this is intentional

Only two that a player actually builds: **Home Improvement Store** and
**Mining/Farming Equipment Store** (two of each were founded in the last run).
Private Security Contractor and Insurance Brokerage are also unmodelled and were
deliberately skipped long ago — combat, theft and insurance claims are unbuilt,
so there is nothing for a player to do at either.

`sprites.structure_for()` falls back to a Kenney stand-in **per building type**,
so art lands one asset at a time, nothing breaks, and `run_phase1.py` reports
what is still missing. Six of the seven building types a player will realistically
occupy are covered.

### THE LAND RULES — read before drawing anything

Land became the scarce resource on 2026-08-19 and it has spatial consequences
the renderer does not yet know about.

**The numbers**

| rule | value |
|---|---|
| a business's building | **2 plots** (`STRUCTURE_PLOTS`), worked by the owner for no wage |
| a new business | **4 plots** (`SITE_BASE_PLOTS`) — the building plus two employee places |
| a new store | **4 plots** (`STORE_BASE_PLOTS`) |
| a home | **4 plots** (`HOME_BASE_PLOTS`) |
| employees a business may hire | **one per developed plot beyond the building** |
| raw land, from the world | **100 Denari/plot** (`buy_land`) |
| developing a plot | **75 Denari + 1h**, or **2x the money** to finish instantly |
| both of those | **+50% per plot the site already holds** (plot 5 = 75/1h, plot 6 = 112.50/1.5h, plot 7 = 168.75/2.25h) |
| resale | any price the owner asks (`list_land` / `buy_listed_land`) |

**Storage is the startup cost**, not the plot count: Farm 150, Mining 175,
Refinery 450, each tier adding half the base again (`upgrade_site_storage`).
Stores are the exception — they hold **100 per developed plot**, because a
store's land IS its shelf space and its stock is what it sells.

**Land supply per place**

| | plots |
|---|---|
| every spur (x16) | 40 |
| Town | **60** — the market, the most contested ground in the valley |
| Refinery Row | 48 |
| protected zones | 28 each |
| wilderness stops | 20 each |
| **total** | **864**, of which the state holds 40 |

Mines and farms exist on spurs only; everything else is on the main road. At 20
agents with one business and one home each (160 plots) land does not bind —
spurs 18% used, junctions 23%. It binds **at Town specifically** and on
expansion.

**THE MISMATCH THE RENDERER HAS TO RESOLVE**

`layout.py` was written before the land system and gives each place a fixed
number of *building slots*. Land gives each place a number of *plots*. They
mostly agree by luck, but not everywhere:

| place | plots | businesses that fit (plots/4) | slots `layout.py` draws |
|---|---|---|---|
| **Town** | 60 | **15** | **11** |
| Refinery Row | 48 | 12 | 11 |
| a spur | 40 | 10 | 9 |
| **whole valley** | 864 | **216** | **191** |

So a fully built-out Town has four businesses with **nowhere to stand**. Nothing
errors; they simply do not get drawn, which is the worst possible failure mode
for a demo.

Two questions to settle before rendering, neither of which I decided:

1. **Reconcile the counts.** Either raise `SLOTS_PER_HUB` and re-run
   `layout.check()` (it enforces that no two buildings overlap and none stands
   in a road, and it will refuse a layout that cannot fit them), or lower Town's
   plot supply to match what can be drawn. The first is more honest to the
   economy; the second is less work.
2. **Does expansion show?** A business that buys and develops twelve plots is
   three times the operation of a new one, and currently gets exactly one slot
   and one sprite. Options: draw one building and let the *number* carry it;
   scale the sprite with `developed_plots`; or add outbuildings from the props
   set. This is a real design choice and it is the difference between a map that
   describes the economy and one that decorates it.

### What is already built and waiting

- **`convoy/layout.py`** — the valley as real geometry in world metres, 1347m x
  3680m, **191 building slots** and **366 prop positions**, each with x, y and a
  facing angle. Deterministic: everything is seeded off the place's own NAME, so
  re-rendering never reshuffles the world and adding a spur cannot move existing
  ones. `layout.check()` runs inside `run_phase1.py`.
- **`preview_layout.py`** — draws the plan with no art and no run, colour-coded
  by slot purpose. `python3 preview_layout.py` -> `layout.html`. Use it to see
  where buildings will stand before rendering a single sprite.
- **`convoy/sprites.py`** — the entity -> asset binding, with `check()` asserting
  every item, vehicle, business type, location, role, model and all 58 actions
  have art. It runs inside `run_phase1.py`.

**`layout.py` is NOT yet wired into `render_world.py`.** The renderer still lays
junctions down a straight line with spurs at fixed offsets. Wiring it in is
probably the first move — you get the real valley shape and the art in one pass.

---

## Where the simulation is

The economy works end to end and is considerably deeper than PHASE4 describes.
**17 test files pass, invariants clean, 58 actions.**

### Harness — run these before anything

```bash
for t in tests/test_*.py; do python3 "$t" >/dev/null && echo "PASS $t" || echo "FAIL $t"; done
python3 run_phase1.py | grep INVARIANT      # must say "all clean"
python3 run_phase2.py --dry-run
```

### Built this week, in rough order of importance to the visuals job

**A live, resumable world (`convoy/live.py`).** `Engine.run` used to be a closed
loop from hour zero to the end; a world could only be watched after it was over,
so advice given to a finished run changed nothing. `Engine.step_until(end,
wall_budget_s=)` is the seam. `LiveSession.open(run, branch_to=...)` resumes a
checkpoint and **branches** it — each user gets their own world forked from a
shared baseline, which is also the persistence model for sign-in. `advance()`
returns only that slice's events, so a viewer polls for the delta rather than
redrawing history every frame. `status()` gives per-agent: what they are doing in
words, road progress 0-1, and **when they next get a turn** in both simulated and
real seconds.

**Talking to agents.** `convoy/interrogate.py` + `serve.py` + a per-agent,
per-speaker conversation history in `convoy/conversation.py`. The model answers
**in the agent's own voice by default**, grounded in its retrieved decisions with
hours cited; verbatim recall is the fallback when there is no key. Conversations
live *beside* the run in `conversations.json`, never in the checkpoint — advice
is meant to change the world, a question must not.

**Advice that agents act on.** `Agent.inbox` -> `observe.advice_for` ->
`advice_outcome` events. Delivery is recorded at the single point where words
enter a prompt, so "it ignored me" and "it never heard me" are different log
rows. Proven live: 9 of 9 recommendations reached a prompt. **Unheard advice
interrupts a working agent** — the engine pulls them off the bench for exactly
one decision.

**Land is now the scarce thing.** Plots are owned, tradeable assets. A business
stands on 2 plots worked by the owner and **seats one employee per developed plot
beyond that** — the first enforced employee cap in the game. Junctions have
finite land (Town 60, the most contested). Buy at 100/plot, develop for 75 + 1h
or 2x to skip the wait, both +50% per plot already held. Sell to anyone at any
price.

**Storage is the startup cost.** Farm 150, Mining 175, Refinery 450, tiers add
half the base again. Stores instead hold 100 per developed plot — their land IS
their shelf space.

**Sellers can push goods.** `post_delivery_job` — pay a courier to move YOUR
stock; goods leave the yard at once so a stalled site produces again. Announced
in world chat. Carriage is priced on **cargo value** (~10%, half again through
dangerous country), not time. **The load is sealed**: couriers see a price, a
route, who is asking, and whether they can lift it — never the item, quantity or
value. Owners may lend a vehicle, which is bound to the job and cannot be kept.

**Per-decision asset snapshots.** Every `llm_reasoning` event carries what the
agent owned at that moment — cash, cargo, vehicles, businesses with their cash
and payroll. +404 bytes per decision.

### The run to render

`runs/phase2/20260818-124204/` — 7.4 MB, **27,092 events through h53.9**.

| | |
|---|---|
| reasoning events | **1,365**, across all 20 agents |
| businesses founded | 14 |
| advice delivered / outcomes | 9 / 141 |
| couriers: claimed / delivered | 30 / **30** |
| deaths | 0 |

This is the first run with real reasoning in it — every earlier full-size run
predates the capture fix and has 2. Clicking an agent finally shows something.

**It died at hour 47** to `Prompt tokens limit exceeded`. Not a bug: OpenRouter
scales a hard per-request prompt ceiling with the key's **remaining credit**, and
it fell through our prefix as the run spent money. Credit has since been topped
up and a 14,081-token prompt goes through. The run has **no per-decision asset
snapshots** (that landed after) and its businesses **predate the land system**.

---

## Gotchas

- **Run `python3 run_phase1.py` after ANY change to `convoy/data.py`.** Its
  invariant checker has caught bugs the unit tests missed, and it also verifies
  every entity has art, every state dataclass is checkpointable, and the layout
  is drawable.
- **The prompt prefix has a hard ceiling.** Currently ~13,565 tokens against a
  self-imposed 14,000 guard in `tests/test_schemas.py`. That guard is ours and
  documents its own protocol — raise it alongside a feature and say which one.
  The *real* ceiling is OpenRouter's and moves with your balance. ~1,900 tokens
  of headroom exist in the repeated `item` enum; spending it risks invented item
  names, so do it deliberately with a run to measure refusals after.
- **Budget runs by expected BUSINESS count, not agent count.** 23 businesses
  generate far more decisions than 4.
- **Watch `events.jsonl`, not the console.** Nothing calls `EventLog.flush()`
  outside checkpoints, so both fill in ~8KB chunks. A quiet log is buffering.
- **Match the interpreter path** when checking processes:
  `pgrep -f "MacOS/Python run_phase2.py"`.
- `OPENROUTER_API_KEY` is in `.env`.
- **~7 simulated hours per wall-clock hour** at 20 agents / 10 rpm, set by API
  throughput, not the sim clock. Fewer agents concentrate the same throughput, so
  each one acts more often — 5 agents gives a decision per agent every ~1.4
  minutes, which is what makes a demo watchable.
- Blender MCP is configured (`claude mcp list` -> blender). Needs Blender open
  with the BlenderMCP panel started; `uv` is routed to `~/.uv/` because
  `~/.local` is owned by root on this machine.

## Suggested order

1. **Wire `layout.py` into `render_world.py`** — real valley shape, no new art
   needed. Verify against `preview_layout.py`.
2. **Render the 6 buildings and 10 characters** through `blender_rig.py` at the
   per-category angles (buildings 48°, characters 10°), into `art/generated/`.
3. **Bind them in `sprites.py`** — per-type fallback means they can land one at
   a time and `run_phase1.py` will tell you what is still missing.
4. **VISUALS §1 and §2** — status and chat bubbles. Called the highest-payoff
   item in that document and nearly the cheapest; the run above has the
   `llm_reasoning` volume to make them worth drawing at last.
5. Then the live viewer: `status()`, `ask()` and `advise()` behind HTTP.
