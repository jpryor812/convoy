# Handoff — Convoy, 2026-08-20 (evening)

Copy everything below the line into a new chat window.

---

I'm continuing work on **Convoy**, a headless LLM-agent economic simulation in
`/Users/justinpryor/Downloads/convoy-main`.

**You are on the `demo-map` branch. Check that first — `git branch --show-current`.**
The world was cut down twice today and `main` is stale.

## Read these, in this order

1. **`PHASE6.md`** — today's work and the current state. Supersedes everything
   below it for anything about the map, the art, or the click-through UI.
2. **`PHASE4.md` §2** — read before debugging any agent behaviour. Thirteen
   times, "the agents are being stupid" turned out to be the observation failing
   to tell them something the code already knew. **Suspect the observation
   before the model.** That lesson recurred four more times today, in a new
   costume each time; PHASE6 records them.
3. **`PHASE5.md`** — the visual build plan. Historical now; PHASE6 says what
   actually got built and where it diverged.
4. **`VISUALS.md`** — the original art plan. Largely superseded; its header says
   what still holds.

**Ignore `convoy_bronze_age_economy.xlsx`, `convoy_reference.md`,
`claude_code_handoff_prompt.md` and `PHASE1–3`** — stale snapshots.
`convoy/data.py` is the source of truth for the economy.

## Harness — run these before anything

```bash
for t in tests/test_*.py; do python3 "$t" >/dev/null && echo "PASS $t" || echo "FAIL $t"; done
python3 run_phase1.py | grep INVARIANT      # must say "all clean"
python3 preview_world.py                    # hour zero -> world_preview.html
python3 preview_world.py --run latest       # play the newest run back
```

`preview_world.py` is the ONLY renderer. `render_world.py` was merged into it and
deleted on 2026-08-20 -- one could read a run and the other could draw the
valley, so the run you wanted to watch was only available in the old card
layout.

A replayed page is ~1MB, which is too big for some preview panes to open as a
file:// URL. Serve it instead: `.claude/launch.json` has a `map` config
(`python3 -m http.server 8777`), then open
`http://localhost:8777/world_preview.html`.

18 test files, all passing. `run_phase1.py` also checks that every entity has
art, every state dataclass is checkpointable, and the layout is drawable.

## The world, as it stands

    Refinery Row  ──  The Hills  ──  Town
     (smelting)      (ore, grain,     (the market)
                      every house)

Three places, two road segments, four spurs — all on The Hills. The southern leg
is **The Bridge**, the only segment you cannot flee off-road from, so every load
reaching a buyer crosses one chokepoint. Full road is ~98s, which makes a spur
detour (90s each way) cost more than the road itself.

**160 plots, and they bind.** Mines, farms *and* homes are all spur-only, so the
four spurs hold **18 free sites** against twenty agents who would each like a
house and somewhere to dig — 40 sites' worth of appetite. Town has **5 free
blocks** for every shop anyone wants to open. The state already holds 40 plots.

**Every business type exists exactly once at hour zero, as a government branch.**
Ten buildings, twenty agents in Town, everything else wooded and for sale.

### Land is geometry now

A site is a **2×2 block of 32m parcels** and the building is drawn on the shared
corner of its four plots. Every plot supply divides by four exactly, so "how much
land is here" and "how many businesses fit here" are one number counted twice.
`layout.check()` asserts the geometry seats what the land sells.

There is a one-parcel **lane between every block**, drawn as a street under built
holdings only — so the street network grows as the run does.

## Other maps, if this one proves too small

| branch / commit | world |
|---|---|
| `demo-map` (HEAD) | 3 places, 4 spurs, 160 plots, 40 sites — **current** |
| `demo-map` @ `b74fa49` | 5 places, 10 spurs, 308 plots — good for ~50 agents |
| `full-valley-map` | 7 places, 16 spurs, 864 plots — the full valley |

`reference/full-valley-map.html` is a rendered page of the full valley, committed
so it can be looked at without a rebuild.

## Art

- **Ground and buildings: Pipoya** (`art/pipoya.py` cuts the tileset). Its farm
  is a farmhouse with a ploughed field; its mine is a rock face with a timbered
  adit. Kenney had a windmill and a grey ramp.
- **People: isaiah658's pack** (`art/people.py`), re-clothed to medieval by
  naming only skin and hair to preserve and re-hueing everything else with
  luminance untouched. Front-on, with eyes, four facings, three-frame walk.
- **Meshy renders are kept but unused in 2D** — `sprites.PREFER_RENDERED` flips
  them back on. They are the 3D scene's assets; a photographed model carries its
  information in texture detail and a map sprite is 80 pixels.

Source packs are gitignored (`art/Meshy/`, `art/source/`, `Pipoya .../`); the cut
output in `art/generated/` is committed because it is what the renderer loads.

## The click-through UI

Click any building (each has a circled **i**) or any person: the camera eases to
2.5x and a **white card** opens above it.

- **Buildings**: owner, cash, land, what it is making, stock with prices, who is
  working there *and what each of them is doing*, live job postings.
- **People**: activity, location, cash, **net worth with rank**, what they carry,
  what they own, who they work for, an **Ask / Advise** box, and -- when a run is
  loaded -- **what they said**, quoted from their own reasoning up to the
  slider's hour.

### Replay mode

`--run` adds a time slider. Agents interpolate **along the road** between places
rather than teleporting, and wear the hooded cloak while in transit. Businesses
appear at the hour they were founded.

Two things it is honest about: **cards and flags come from the checkpoint** (the
end of the run), not the slider's hour -- the card footer says so -- and only the
quotes are per-hour. And **a run belongs to the map it was recorded on**: the
27k-event run names three places this world does not have, which are reported by
name and dropped rather than drawn at nowhere.

`convoy/inspect.py` assembles those cards. **One assembler, two consumers**: the
static page bakes them in and `serve.py` serves the same shapes at `/cards`.

### Going live

```bash
python3 serve.py --run runs/phase2/<run> --port 8000
```

Then open the page with `?server=http://localhost:8000`. Panels refresh from
`/cards`, the footer switches from "hour 0 · static snapshot" to the live hour,
and Ask/Advise POST to the existing endpoints. **This path has never been
exercised end to end** — see "the next step" below.

## THE NEXT STEP

A run, but **rehearse it for free first**. Two things, in order:

1. **A no-LLM smoke.** `python3 run_phase2.py --dry-run` builds prompts and calls
   nothing. Then a tiny real run, or point `serve.py` at whatever checkpoint that
   produces, open the map with `?server=`, and click something. That proves
   run → checkpoint → `/cards` → popup without spending anything. It has never
   been done.
2. **Then the real run**, ~20 agents.

What I checked already, so you do not have to: **no stale place name reaches the
agents.** The cached briefing (18,485 chars) and all 58 tool schemas are clean of
the deleted locations. Comments and docstrings still mention them; that is
history, not prompt surface.

### Budget and gotchas for the run

- **Budget by expected BUSINESS count, not agent count.** 23 businesses generate
  far more decisions than 4.
- **~7 simulated hours per wall-clock hour** at 20 agents / 10 rpm — set by API
  throughput, not the sim clock. Fewer agents concentrate the same throughput, so
  5 agents gives a decision each ~1.4 minutes, which is what makes a demo
  watchable.
- **Watch `events.jsonl`, not the console.** Nothing calls `EventLog.flush()`
  outside checkpoints, so both fill in ~8KB chunks. A quiet log is buffering.
- **The prompt prefix has a hard ceiling.** ~13.5k tokens against a self-imposed
  14,000 guard in `tests/test_schemas.py`. The *real* ceiling is OpenRouter's and
  **scales with the key's remaining credit** — a previous run died at hour 47
  with `Prompt tokens limit exceeded` for exactly that reason, not a bug.
- `OPENROUTER_API_KEY` is in `.env`.
- Match the interpreter path when checking processes:
  `pgrep -f "MacOS/Python run_phase2.py"`.

### What to watch for in the results

Land binds for the first time. That is the interesting variable and also the
likeliest source of a PHASE4-§2 bug: if agents do not compete for ground, check
that the observation is telling them ground is scarce **before** concluding they
are ignoring it. The `LAND HERE:` line in the observation carries the numbers.

**The saved 27k-event run (`runs/phase2/20260818-124204/`) belongs to the
seven-place valley and cannot be replayed here.** `tests/test_sprites.py` detects
that and skips with a message rather than failing.

## Standing gotchas

- **Run `python3 run_phase1.py` after ANY change to `convoy/data.py`.**
- **Hard-coded place names in tests have broken the suite four times** across
  today's recuts. Every fixture now reads its places off `world_map`. Keep it
  that way.
- **`art/generated/` is committed; the source packs are not.** Re-cutting is
  `art/pipoya.py`, `art/people.py`, `art/pixelate.py`.
- Blender MCP is configured but the 2D pipeline no longer needs it. Headless
  works: `/Applications/Blender.app/Contents/MacOS/Blender -b --python <script>`.
