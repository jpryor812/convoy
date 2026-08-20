> **SUPERSEDED IN PART — 2026-08-20. Read `PHASE6.md` first.**
>
> This was the art plan. Most of its *reasoning* still holds; several of its
> *conclusions* were overturned by building them.
>
> **What changed:**
> - **Kenney is no longer the target style.** Ground and buildings are Pipoya;
>   people are isaiah658's, re-clothed. Kenney's farm is a windmill and its mine
>   a grey ramp, and its people have no faces because they are drawn top-down.
> - **The Meshy pipeline works and is not used in 2D.** §8's rig notes are still
>   accurate; the conclusion is not. A photographed model keeps its information
>   in texture detail and a map sprite is 80 pixels. It is the 3D scene's art.
> - **Per-category camera angles (§11, §13) are moot for the 2D map** — nothing
>   is Blender-rendered on it any more.
> - **Agent state on the map rather than a side panel (§1, §2) was built** — as
>   white cards floating above the thing you clicked. See PHASE6 §6.
>
> **What still holds:** the argument for flat top-down over a perspective camera;
> the Smallville reference; sizing framing to the largest asset rather than
> per-asset; and §8's warning that `Standard` view transform matters and AgX
> silently desaturates everything.

# Visuals — what to build, easiest first

Target: **Kenney's shape language, better executed.** Reference points are the
Kenney Medieval RTS pack (what the map already uses) and Smallville from the
[Generative Agents paper](https://arxiv.org/abs/2304.03442) — flat, straight
top-down, tile-based, with agent state shown *on* the map rather than in a side
panel.

Civilization VI was considered and rejected as a reference: it is a low-angle
perspective camera with real-time shadows and a rotatable view, none of which
survives a fixed-camera 2D pipeline. What was worth taking from it — saturated
palette, high value contrast, chunky proportions, unambiguous silhouettes — is
already true of Smallville, which is far cheaper to reach.

**Camera: straight top-down, orthographic.** Matches Kenney, matches Smallville,
and keeps the existing 24 people usable.

---

## How this list is ordered

By **build effort, cheapest first** — that is what was asked for. But effort and
payoff diverge in two places, so they are flagged:

- **§1 is the highest-value item in the document and also nearly the cheapest.**
  Do it first regardless of anything else here.
- **§13 is cheap-looking and expensive-in-truth.** It is at the bottom on
  purpose, with an argument for not building it at all.

Effort buckets are rough: **XS** under an hour · **S** a few hours · **M** a day
· **L** multiple days · **XL** a week or more.

---

# Tier 1 — no new art, data already exists

## 1. Agent status bubbles · XS · highest payoff in this doc

Smallville's signature: a small bubble over each agent showing what they are
doing. Convoy already has everything needed and shows none of it on the map.

- `llm_reasoning.did` — the actions the agent just took
- `GLYPH_FOR_ACTION` in `convoy/sprites.py` — already maps all 53 actions to ten
  glyph families, already rendered, already embedded in the page
- Smallville uses emoji; we have the equivalent art (`ui:work`, `ui:coin`,
  `ui:travel`, `ui:food`, `ui:hire`, `ui:build`, `ui:chat`, `ui:warning`)

Render the current action's glyph in a bubble above each figure. One function in
`render_world.py`. It turns a map of static dots into a legible board, and it is
the single change that most makes the thing look like the reference.

## 2. Chat bubbles · XS

The 84-hour run produced **218 chat messages** and they are currently visible
only as ticker lines. Chat is how prices, wages and carriage jobs get known —
it is the most interesting thing agents do — and the map does not show it.

Same mechanism as §1: bubble above the speaker, text on hover or on click.
Smallville puts the dialogue in a callout panel; §6 is that.

## 3. Bigger, sharper sprites · XS

`collect_assets()` deliberately downgrades to the pack's `Default size` PNGs to
keep the file small. Now that a build is 451KB, spend some of that budget:
switch buildings and agents to `Retina`, raise map sprite sizes. Pure win.

## 4. Reference folder and a sampled palette · XS

```
art/reference/
  README.md        <- the spec: camera, sun, palette, sizes, silhouette rules
  smallville/      <- screenshots
  kenney/          <- contact sheets of what exists
  wip/             <- renders, for side-by-side
```

Drop reference images in and sample them the way `art/palette.py` was built —
count every pixel, rank the colours. That is the difference between "warm
greens" and `#8fa832`. Keep the screenshots local; they are not ours.

## 5. Elevation and danger on the map · XS

The valley runs 20m to 340m and segment danger runs 0.133 to 0.65 — that
gradient is the entire reason haulage is worth paying for, and only elevation is
currently drawn (as a shadow). Colour the road by danger and the map starts
explaining its own economy.

---

# Tier 2 — renderer work, still no new art

## 6. Callout panels · S

Smallville's zoomed insets. Click a place → a panel showing that location
enlarged, its buildings, who is standing there, and the last few things said.
Mostly a re-layout of data already in the payload.

## 7. Walk cycle and road motion · S

Position interpolation along roads already works. Add a two-frame bob, orient
the sprite along the direction of travel, and drop a faint trail. Cheap, and it
is most of what makes a map feel alive rather than stepped.

## 8. Blender render rig · ~~M~~ **DONE** · gates everything in Tier 3

`art/blender_rig.py`. Orthographic camera at **48°** (not the 60 it started at,
and not RCT's 30 — measured against `medievalStructure_20`, where 60 let the
roof swallow the walls). 128px, transparent PNG, Freestyle outline pass, sun
plus heavy ambient, `Standard` view transform.

Two settings that are load-bearing and non-obvious:

- **Never AgX.** Blender 5.x defaults its view transform to AgX, which tonemaps
  and desaturates. Left on, every sprite drifts pale and quietly stops matching
  the palette — the kind of failure that survives a long way before anyone
  spots it.
- **`ORTHO_SPAN_M` is sized to the LARGEST asset, not per-asset.** 11m, set by
  the refinery. A refinery is genuinely bigger than a cottage; if each asset got
  its own framing they would all arrive at the map the same size and the map
  would be lying about the economy.

`check_fit()` prints a CROPPED warning when a model overflows the frame. It
caught the refinery growing past 8.5m after a hand-edit in Blender.

## 9. Hand-designed layout · ~~S–M~~ **DONE (2026-08-19)** — `convoy/layout.py`

Was: junctions down a straight line, spurs at fixed ±300px offsets. Fine for a
diagram, not for a place anyone believes in.

Now `convoy/layout.py` — position as plain data in world metres, so the 2D map
and the React Three Fiber scene consume the same coordinates. Tiled was not
needed: the valley is 23 places on a fixed topology, so authoring the seven
lateral offsets and the sixteen spur headings by hand is the whole job.

**1347m x 3680m · 191 building slots · 366 props.** Each place carries a road
path, `Slot`s (x, y, facing, kind) and `Prop`s (kind, position, scale,
rotation). Preview it with no art and no run: `python3 preview_layout.py`.

**The rule every number obeys: the geometry may not contradict the simulation.**
All six road segments are the same distance in `world_map` — terrain is what
makes them differ — and all sixteen spurs are 90 seconds deep. So the drawing
makes them equal. The first version put junctions on a fixed vertical pitch and
let the lateral wander lengthen the hypotenuse, which made the swing through The
Hills 6% longer than the run to the bridge. Six percent is invisible; a map that
cannot be called honest is not. Junction spacing now shortens the drop to absorb
the wander, and `check()` holds it to 0.5m.

**Three failures worth keeping.** All were found by measuring, not by looking:

| symptom | cause |
|---|---|
| 6 of 16 spur loops overlapped | headings 20–25° apart. Equal-depth spurs are kept apart by ANGLE alone, and two loops need ~57° between them |
| 26 building slots on top of each other | tuned constants. Replaced by a resolution pass that drops any slot standing on a road or another building — an invariant, not an approximation |
| shops standing in the road at Refinery Row and Town | a full ring of market frontage, drawn round a junction the road runs through. A market square has frontage down both SIDES and the road up the middle |

`layout.check()` runs inside `run_phase1.py` beside the economic invariants and
`sprites.check()`, for the third instance of the same argument: it derives from
`world_map`, and its failure mode is a quietly wrong picture rather than an
exception.

Everything seeded off the place's own NAME, never call order — so re-rendering
never reshuffles the world, and adding a seventeenth spur cannot move the first
sixteen. A world that looks different every time it is drawn cannot be learned,
and the demo depends on a student recognising Copper Gulch on sight.

---

# Tier 3 — art production, gated on §8

Ordered by how well each suits Blender-MCP, whose documented strength is
hard-surface modular geometry and whose documented weakness is organic form.

## 10. The business buildings · ~~M–L~~ **DONE (8 of 10) — awaiting review**

`art/blender_assets.py`, one function per asset, plus `player_home`.
Rendered: Refinery, Farm, Mining Operation, Tavern/Inn, Weaponsmith/Armory,
Vehicle Dealer/Stable, Home Improvement Store, Mining/Farming Equipment Store.

**Private Security Contractor and Insurance Brokerage deliberately skipped** —
combat, theft and insurance claims are unbuilt (§12), so there is nothing for a
player to do at either. `sprites.structure_for()` keeps serving the Kenney
stand-in until there is.

Each asset is designed around **one** silhouette cue, because at 31px that is
all that survives. Three needed rebuilding when the first render failed, and the
reasons are recorded in the docstrings rather than lost:

| asset | first attempt read as | fix |
|---|---|---|
| Farm | windmill sails overlapped into an asterisk | barn + silo; Kenney gets away with sails only because they are the *whole* sprite |
| Mining Operation | a catapult, then a bathtub, then a crate | a hole must be a GAP between masses, never a dark object — a lit cube is a cube |
| Equipment Store | a fence | open stalls need mass behind them or the outline pass draws a row of uprights |

The swap is **per-building, not a flag day**: `sprites.structure_for()` prefers a
rendered PNG and falls back to Kenney per type, so art can land one asset at a
time.

Still weakest: the farm. Silo and crop rows read, the barn mass is bland.

## 11. The 6 vehicles · ~~M~~ **DONE**

All six in `art/generated/vehicles-3d/`. Rendered PNGs win over the SVGs via
`sprites.vehicle_sprite()`, and the SVGs are kept rather than overwritten so the
two can be compared instead of one being destroyed to try the other.

**Vehicles break three conventions, each on purpose.** They are BROADSIDE where
everything else faces the camera; they render at **14°** where everything else
is 48°; and they render into a **192x96** canvas where everything else is square.

All three follow from the reference (a side-on pixel-art wagon). Spoked wheels,
plank sides and the line of a horse's back are profile features that a high
camera flattens away — and a 5.2 x 1.8m wagon in a square frame used 81% of the
width but 28% of the height, so two thirds of every sprite was empty alpha and
the art rendered at under half the resolution it should have.

Rebuilt from the boxy first version to match: 6-spoke wheels with rim and hub,
plank sides with vertical posts, a long shaft, and animals with arched necks,
sloping shoulders and jointed legs. Donkey smaller and grey (scale 0.78), camel
larger and yellow (1.15) — sizes are real, not implied.

Two bugs found doing it, both silent:

- **`flat_material()` cached by NAME only.** Every animal asked for a material
  called `"coat"`, so the first one rendered set the colour and all the rest
  inherited it — the grey donkey and yellow camel both came out the colour of
  the first horse. Nothing errored. Now keyed on name AND colour.
- **The camera aimed at the world origin** while models stand on the ground
  plane. Slack in a big square frame hid it; the moment vehicles moved to a 2:1
  canvas the vertical window shrank to 3.2m and every animal lost its head off
  the top. `aim_camera_at_assets()` now centres on the asset's own bounding box,
  which fixes it for every category at once.

Also: a 2- and a 4-horse team rendered IDENTICALLY, because in true profile
horses abreast occupy the same silhouette. They are staggered along X now.

## 12. Terrain and props · M

Ground tiles, road pieces, rocks, trees. Straightforward but numerous. Kenney's
are genuinely good — only worth redoing once buildings are replaced and the
mismatch starts to show.

## 13. Characters · ~~L · consider not doing this~~ **DONE — rebuilt twice**

Built chibi first, then rebuilt as **adult tradespeople** against a reference of
detailed pixel-art NPCs. Five variants (`art/generated/characters/`), one per
model, each x {plain, owner}.

**The two versions are the same decision made twice, opposite ways.** Chibi is
~3 heads tall with an oversized head, which is what makes a 24px figure legible.
Adult is ~7 heads, where at 27px the head is 3px and every bit of detail is
invisible. Sprite size and figure proportion are one choice, not two.

Then shortened and coarsened again for an old-school look:

- **legs squashed to 72%** after building, upper body dropped to match. Shrinking
  the legs rather than the whole figure is what makes a sprite read as stocky
  rather than merely small -- the head keeps its size, so head-to-body falls from
  ~6.4 to ~5.4, the classic 16-bit RPG build.
- **rendered at 54x80**, down from 96x160. Pixel art looks pixellated because
  there are FEWER PIXELS, not because a filter ran over it; rendering big and
  scaling down just yields a smooth small picture.
- the map draws agents at **27x40** -- exactly half the source, so the downscale
  drops whole pixels -- with `image-rendering: pixelated`, or the browser
  smooths them straight back out and undoes the whole point.

Camera is **10 degrees**, near eye level (buildings 48, vehicles 14).

Each variant is a TRADE rather than a palette swap -- smith with bare arms and a
hammer, server with a tray, keeper in an apron with crossed arms and a mug,
ranger hand-on-hip in a vest, miner with a pick. Clothing and props do the
identifying work that a 3px face cannot.

Three renders were needed and the failures were all about pixel budget:

| attempt | problem |
|---|---|
| 1 | face was two 2cm dots on a 21cm head -- about 1.6px, i.e. nothing |
| 2 | added brows, nose, mouth: they merged into one dark smear across every face |
| 3 | head enlarged 25cm -> 28cm, features cut back to eyes and a nose |

Also: the smith's beard was sized like a full beard and rendered as a pale mask
over the whole face.

**Three bugs surfaced during this work, all silent.**

- `person()` rotated EVERY object in the collection to get its three-quarter
  turn, not just the figure being built. Rendering never showed it -- the scene
  is cleared before each asset, so there was only ever one figure. It appeared
  only in `showcase_all()`, where each new person re-rotated everything already
  placed and flung the scene across 108m.
- **`matrix_world` is cached until the dependency graph re-evaluates.** After
  moving or scaling a model from Python, objects still report their OLD world
  position. The render triggers an evaluation and comes out right, which is what
  makes it nasty: the picture is correct while `aim_camera_at_assets()` and the
  CROPPED check both run against a figure that no longer exists.
  `bpy.context.view_layer.update()` now runs before either.
- A dead `render_characters()` from the chibi era survived the rebuild, still
  calling deleted names -- a `NameError` waiting for anyone who typed the old
  function.

**A regression was also caught mid-rebuild.** `render_people()` initially produced no
`-owner` variants, so business owners would have silently fallen back to Kenney
sprites -- a map showing two art styles at once, with nothing failing and no
test catching it. Owners now get a brimmed hat and cloak.

# Tier 4 — bigger systems

## 14. Item icons re-render · S · probably skip

The 63 SVGs are consistent because they were generated as a taxonomy. Rendering
63 models would cost days to reach parity. Only worth it if the flat SVG style
clashes badly with rendered buildings — judge after §10, not before.

## 15. Building interiors · XL · argued against

Smallville's cutaway floor plans are its most striking feature and the worst fit
here. In Smallville they matter because agents move *within* buildings and
interact with objects. **Convoy has no such state.** An agent is "at Refinery
Row"; there is no standing-next-to-the-furnace. Drawing interiors would mean
inventing game state purely for decoration, and the sim would not know about it.

If interiority is wanted later, the honest version is to add it to the *sim*
first — and that is a `data.py`/`engine.py` decision, not an art one.

---

# The thing that is not art, and blocks the demo

**A run with reasoning in it.** The 84-hour run predates reasoning capture and
holds 2 decisions across 20 agents, so §1, §2 and §6 would all render mostly
empty against it. The mechanism is verified — 7/7 on a 4-agent smoke — but it
has never had a full run's worth of content.

That run is also what PHASE4 §7 has been waiting on (the three untested
labour-market fixes). One run settles both.

Roughly $3 and ~12h wall clock at 20 agents / 84h. Nothing above it in this
document is blocked by it, but §1–§7 are all judged against it, so doing it
early means building against real content rather than a nearly empty log.
