# PHASE 6 — the world made visible, and clickable

2026-08-20. Six commits on `demo-map`, branched from `full-valley-map`.

PHASE5 planned the art. This is what happened when it was built, where the plan
was wrong, and what the world looks like now. Where the two disagree, this wins.

---

## 1. What exists now

Three places, two segments, four spurs, 160 plots, 40 business sites, and a page
you can click. 18 test files pass; `run_phase1.py` reports invariants clean.

    Refinery Row  ──  The Hills  ──  Town
     (smelting)      (ore, grain,     (the market)
                      every house)

`python3 preview_world.py` → `world_preview.html`. Open it and click something.

---

## 2. Land became geometry

The single most useful change, and it removed more code than it added.

**A site is a 2×2 block of 32m parcels, and the building stands on the shared
corner of its four plots.** So a founding business visibly occupies the four
plots `SITE_BASE_PLOTS` always said it did, and buying a fifth visibly adds one.

The arithmetic is what makes it trustworthy: **every plot supply in the world
divides by four with nothing left over.** "How much land is here" and "how many
businesses fit here" stopped being two numbers that had to be kept in agreement
and became one number counted twice.

That let three things go:

- the ring/arc slot placement (a market square, a spur loop, a garrison's rows),
- the collision-resolving pass that culled overlapping slots,
- the nudge search that tried to rescue them first.

**115 lines deleted.** Buildings land on grid corners by construction.

### What it cost

The arrangements had character the grid does not. A market square with frontage
on two arcs read as a market; a grid of blocks reads as a survey. The trade was
deliberate — the grid is what makes property lines legible, and legible property
lines were the point.

### The mismatch it fixed

`layout.py` predated the land system and gave each place a hand-set number of
building slots. Town sold 60 plots — fifteen businesses — and drew eleven. Four
businesses at a full Town had nowhere to stand, and **nothing errored**; they
simply were not drawn. Every spur had the same bug more quietly: 40 plots, ten
businesses, nine slots.

`slots_needed()` now reads capacity off the land, and `check()` asserts the
geometry seats it.

---

## 3. The world was cut down twice

The full valley was seven places, sixteen spurs, 864 plots — **216 businesses**
for twenty agents. Land that cannot run out is not a market, and it is why every
location decision in the 84-hour run was made as though ground were free: it was.

| cut | world | plots | why it was still wrong |
|---|---|---|---|
| — | 7 places, 16 spurs | 864 | 216 sites for 20 agents |
| first | 5 places, 10 spurs | 308 | still ~2x what they need |
| second | 3 places, 4 spurs | **160** | binds |

**Both protected zones went first.** They were waystations selling freedom from
combat, theft and insurance claims — none of which are built — so they were safe
from nothing, and six spurs hung off them.

**Then everything but the middle.** All four remaining spurs are on The Hills, so
every mine, farm and house is in one place, and the southern leg inherits the
bridge.

### Land now binds, which is the point

Mines, farms **and** homes are all spur-only (`PLOT_CONSUMING_BUSINESSES` and
`buy_property`). Four spurs hold **18 free sites** against twenty agents who
would each like a house and somewhere to dig — 40 sites of appetite. Town has
**5 free blocks** for every shop anybody wants to open.

**This is untested with real agents.** It is the interesting variable of the next
run and the likeliest source of a PHASE4-§2 bug.

### Two things the recuts taught

**The ends of the road should carry nothing.** Clearing spurs off Refinery Row
and Town means every mine and farm hauls north to be smelted and south to be
sold, in opposite directions. Before, a mine on a Refinery Row spur never had to
haul and a workshop on a Town spur never had to travel — the two shortcuts that
let an agent opt out of the road entirely.

**The river belongs where the engine already put it.** The obvious reading of
"The Crossing" is that the river is at that junction. It is not: exactly one
segment has `can_flee_offroad() == False`, it is named **The Bridge**, and the
stated reason is that a bridge has a river on both sides. Putting water on the
junction instead gave four spurs a first stretch over open water and grew a
starburst of bridge decks. On the segment, no junction and no spur touches water,
one road crosses it, and a rule the engine always enforced became visible.

*The code already knew where the river was.* PHASE4 §2, in a new costume.

---

## 4. Art: three packs, and why each lost or won

### Meshy models lost the 2D map

They are far better *models* than anything in either free pack. That is not the
test. A photogrammetry-style asset keeps its information in **texture detail**,
and a map sprite is about eighty pixels tall, where texture detail is noise. Side
by side the Meshy farm read as a brown mass and the pack's windmill read
instantly as a windmill.

**They are not wasted** — they are the 3D scene's assets, where the argument
reverses. `sprites.PREFER_RENDERED = True` brings them back.

Three findings from building the pipeline anyway (`art/build_sprites.py`,
`art/pixelate.py`), all worth keeping:

- **Freestyle outlines every crease.** Right for low-poly, catastrophic on a
  Meshy mesh — the first farm rendered as a solid brown silhouette.
- **Rotating a skinned model does nothing.** A Meshy character is a mesh parented
  to an armature, so `for o in objects if o.parent is None` finds nothing to
  turn. All four facings came out **byte-identical**, with no symptom but four
  files of the same size. Move the camera instead — which also keeps the sun
  fixed relative to the viewer.
- **Snapping to `art/palette.py` was wrong.** That ramp was sampled from flat
  vector art and has nothing to say about a photographed stone wall; it produced
  uniform brown mud. An adaptive per-sprite palette is what reads.

### Kenney lost the ground and the buildings

Its farm is a windmill and its mine a small grey ramp. Pipoya's are a farmhouse
with a ploughed field and a rock face with a timbered adit. For the two buildings
this economy is *about*, that is not close. Pipoya also has seven real terrain
autotiles against Kenney's one flat green square, and the ground is most of the
pixels on screen.

**Mixing them is worse than either.** Pipoya is painterly, Kenney is flat fills
with a hard keyline. Ground against buildings that clash is tolerable — ground is
background. Buildings against buildings is not.

### Kenney lost the people too, for a structural reason

Its units have no eyes, and it is not that they are badly drawn: they are drawn
**top-down**, so what you see is the crown of a head. There is nothing to
manipulate into a face. isaiah658's pack (CC0, `art/people.py`) is front-on with
eyes, arms, legs, four facings and a three-frame walk.

**Re-clothed by exclusion.** Listing every clothing colour per character is a lot
of data to get slightly wrong — one sheet carries sixty colours, most of them
one-pixel anti-aliasing. So the small list is the one easy to be right about,
**skin and hair**, and everything else rolls to an earthy hue with its
**luminance untouched**, which preserves the shading the artist drew.

**The pack is not a uniform grid.** Most sheets are 3×4; two are 3×3 at 24px a
frame. Cutting those on a four-row grid does not fail — it yields twelve frames
of a person sliced through the waist. Rows are now counted off the transparent
scanlines between bands.

---

## 5. Scale: three numbers, all solved rather than chosen

- **The ground grew 1.8×, the buildings did not.** Businesses expand, and at the
  original size there was nowhere to put it: the tightest pair of slots stood 43m
  apart against a 34m rule, and two spur loops had **three metres** of clearance.
  Scaling uniformly preserves the engine's promises (equal segments, equal
  spurs); a local widening would not have.
- **One metre is one pixel.** A block is 64m, exactly the canvas a Kenney
  structure is drawn on. No scale factor left to keep in sync. This also forced
  **Default size, not Retina** — a Retina structure carries 125px of content for
  a 64px plot, and scaling it down resamples pixel art.
- **Growth clamp 1.8 → 1.15.** A building fills 63 of its block's 64 pixels, so
  at 1.3 a weaponsmith sat on its neighbour's roof. It does not need the size any
  more: **expansion is shown by land**, and twelve countable squares beats a
  building 80% wider that the eye cannot measure.

An earlier attempt at 8px/m rendered an **empty field** — the viewport showed
91m and Town's square is 550m across, so every building was off the edge.

---

## 6. The click-through UI

Every building carries a circled **i**. Clicking anything eases the camera to
2.5× and opens a **white card above it**.

`convoy/inspect.py` is **one assembler with two consumers** — the static page
bakes the cards in, `serve.py` serves the same shapes at `/cards`. Written once
because two summaries of the same business drift, and the one a student reads is
whichever they opened. Nothing is computed there that the world does not know;
the work is **joining** — an inventory dict and a price dict are two halves of
"what is it selling and for how much" and no object holds both.

It also let a live duplication go: `live.status()` had its own copy of the
"working as Miner" phrasing, so the status feed and the panel could disagree
about what an agent was doing. Both now call `inspect.doing_phrase`.

**The panels are the public view.** A business card does not carry its owner's
cash; an agent card does not carry another agent's plans. Anything private is
something to **ask** about, and the agent may decline.

### Four things that only showed up by looking

- **A click is a mouseup that travelled under four pixels.** Without the
  threshold every pan ending over a building opened its panel, and the map felt
  like it was grabbing at you.
- **Centring the clicked thing put the card on top of it.** The card is drawn
  above, so the camera lands its target two-thirds down the screen instead.
- **Clamping the card to a screen edge left its tail pointing at empty grass.**
  The tail now slides along the card's edge to stay over the target.
- **Expired job postings must be filtered.** A card advertising a job nobody can
  take sends an agent across the valley for nothing.

---

## 7. Bugs worth remembering

**A position hash that looked like noise.** Prop variety was broken and did not
look broken: every bush in the valley was the same dark scrub, because the hash
used `*` instead of `Math.imul` and `x * 374761393` for a coordinate in the
thousands runs past 2^53, losing the low bits the mix depends on. Output still
*looked* random but every value landed between 0.23 and 0.36, so
`Math.floor(hash * 3)` could never return 2 and the third variant of every prop
was unreachable.

**Framing against a zero-width canvas.** Centring divides by the canvas width,
and at startup that can still be zero — the map opened on an empty corner of the
valley, which looks exactly like a layout bug and is not one.

**Cross-place collisions came back when the resolver went.** Each place's lattice
only knew about itself, so pushing The Crossing's blocks clear of the water moved
them into Kiln Row's. Blocks are now placed against every block already laid,
main-road places before spurs.

**Hard-coded place names broke the suite four times.** `Kiln Row` as a generic
spur fixture, `South Protected Zone` as a convenient second location, `The Climb`
and `The Switchbacks` as road facts. Every fixture now reads its places off
`world_map`. **Keep it that way.**

---

## 8. What is not done

- **No run exists on this map.** Everything above is verified against a
  synthetic hour-zero world and unit tests.
- **The live path has never been exercised end to end.** `serve.py --run <dir>`
  → `/cards` → the page with `?server=` is built but unproven.
- **`render_world.py` still draws the old card layout** and has not been touched.
  `preview_world.py` is where the map lives now. Either wire the real run into
  the preview or port the preview's drawing into the renderer; the former is
  less work and the two would then be one thing.
- **The saved 27k-event run belongs to the seven-place valley** and cannot be
  replayed here. `tests/test_sprites.py` detects a foreign map and skips.
- **Walk cycles are cut but unused.** Three frames per direction exist in
  `art/generated/people/`; the map draws frame 0. Animating them needs the
  renderer to know an agent is moving, which the live feed already reports.
