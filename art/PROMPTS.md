# Meshy prompt templates

Target look: **Fortnite rendering, European Iron Age subject matter.**

Three reference points settled this:

| reference | what to take | what to drop |
|---|---|---|
| dwarf character | chunky forms, warm palette, soft toon shading | the ~4-head dwarf build — that is a species, not a style |
| stone refinery | multi-stack industrial silhouette, solid massing | gothic arch, photoreal grime, carved text |
| Fortnite | readable silhouettes, hand-painted textures, saturated but not garish | nothing |

**Separate style from proportion.** Basing every character on the dwarf produces a
valley staffed entirely by dwarves. Fortnite's own spec is heroic-but-human:
~6.5 heads, oversized hands and boots, normal adult build.

---

## THE STYLE BLOCK

Paste this into **every** prompt, unchanged. It is the whole point — consistency
comes from the template being identical, not from remembering to describe things
the same way.

```
stylized game asset, Fortnite-style rendering: clean readable silhouette,
slightly exaggerated chunky proportions, hand-painted textures, soft shading
with gentle ambient occlusion, warm saturated palette, matte surfaces, no
photorealism, no grime or weathering, no hard black outlines, game-ready
low-poly topology.

European Iron Age, c. 800 BCE: timber frames, thatch, wattle-and-daub, wool,
leather, bronze and iron fittings, Celtic La Tene knotwork ornament.

NO text, NO lettering, NO signage, NO runes, NO numbers.
NO medieval castles, NO gothic arches, NO plate armour, NO fantasy creatures.
```

The no-text clause is not optional. Generated lettering produces text-shaped
shapes rather than words — the first refinery came out labelled "FRONT WORKFHOP",
which is legible enough to read as wrong.

---

## CHARACTERS

Convoy runs on five models, so five people. Each is a **trade**, not a palette
swap: at any distance the clothing and the tool identify someone long before the
face does.

Prefix every one with:

```
Full-body 3D character, T-pose, heroic human proportions about 6.5 heads tall,
oversized hands and boots, adult build.
```

Then the subject, then the style block.

### 1. Smith
```
An older ironsmith. Weathered tanned skin, long white hair tied back, full white
beard. Sleeveless undyed wool tunic showing heavy forearms, thick leather apron,
wide leather belt with iron tools hanging from it, cross-gartered trousers,
heavy leather boots. Holding a bronze-headed hammer.
```

### 2. Tavern keeper
```
A woman running a tavern. Fair skin, long copper-red hair in a loose braid.
Deep red-brown wool dress with a woven knotwork border, linen underdress,
leather belt with a bronze ring-brooch, plain leather shoes. Carrying a wooden
tray with a clay jug and a loaf.
```

### 3. Refinery worker
```
A furnace worker. Medium brown skin, shaved head, thick copper-red beard.
Soot-marked linen shirt with sleeves rolled to the elbow, long heavy leather
apron, bronze arm-ring, wrapped leg bindings, sturdy boots. Holding a clay
crucible in tongs.
```

### 4. Trader
```
A travelling trader. Dark brown skin, short black hair, clean shaven.
Green-dyed wool tunic with knotwork trim, sleeveless leather jerkin over it,
heavy cloak pinned at one shoulder with a bronze brooch, satchel across the
body, laced leather boots. One hand resting on the satchel.
```

### 5. Miner
```
A miner. Deep brown skin, dark hair under a wrapped cloth head covering,
short beard. Undyed coarse wool tunic belted at the waist, leather shoulder
pad, forearm wraps, knee-length trousers, heavy boots. Carrying an iron pick
over one shoulder.
```

**Owner variant.** The map marks business owners. Append to any character:

```
Wearing a heavy dyed cloak pinned with a large bronze brooch and a wide-brimmed
travelling hat.
```

---

## BUILDINGS

Each is designed around **one** silhouette cue — the thing that survives when the
building is small on a map. These cues were proved in the Blender pass; they
carry over unchanged.

Prefix every one with:

```
3D building asset for a game map, viewed from outside, complete structure on a
small patch of ground.
```

### Refinery — MULTIPLE TALL SMOKING STACKS
```
An Iron Age bloomery smelting works. Three tall tapering clay-and-stone furnace
chimneys with smoke rising, grouped beside a low timber-framed workshop with a
thatched roof and an open front. Charcoal piles and stacked ore baskets outside.
```

### Farm — ROUND THATCHED HOUSE PLUS GRANARY
```
An Iron Age farmstead. A large round house with wattle-and-daub walls and a tall
conical thatched roof, beside a small raised timber granary on stilts. Ploughed
crop rows and a low woven fence in front.
```

### Mining Operation — DARK TIMBERED MOUTH IN ROCK
```
An Iron Age mine entrance. A dark tunnel mouth cut into a rocky outcrop, framed
by a heavy timber portal of posts and a lintel. Spoil heaps of copper-coloured
ore and a small wooden hand-cart outside. No building.
```

### Tavern / Inn — LONGHOUSE WITH AN AWNING
```
An Iron Age drinking hall. A long timber longhouse with a thatched roof and a
wide open doorway, a striped woven awning stretched over trestle tables outside,
wooden barrels and benches. Warm and inviting.
```

### Weaponsmith — GLOWING OPEN FORGE
```
An Iron Age weaponsmith. A small timber-framed workshop with a thatched roof and
one wide open forge front glowing orange from the fire inside, a single squat
stone chimney, an anvil on a wooden block outside, weapon racks against the wall.
```

### Vehicle Dealer / Stable — WIDE DARK OPEN BAY
```
An Iron Age stable. A wide low timber byre with a thatched roof and a large open
bay big enough for a cart, dark inside. A post-and-rail paddock fence in front,
hay bales stacked to one side.
```

### Home Improvement Store — STACKED TIMBER UNDER A LEAN-TO
```
An Iron Age carpenter's yard. A small wattle-and-daub workshop with a thatched
roof, beside an open lean-to shelter with neat stacks of cut timber planks and
logs underneath. Woodworking tools on a bench.
```

### Equipment Store — AWNINGED SHOPFRONT COUNTER
```
An Iron Age tool merchant. A small timber shopfront with a thatched roof and an
open counter facing out, a striped woven awning above it, iron and bronze tools
hanging on a rack behind the counter — picks, sickles, axes.
```

### Player Home — SMALL ROUND HOUSE
```
A small Iron Age dwelling. A modest round house with wattle-and-daub walls, a
conical thatched roof, one low wooden door and a single small window. Noticeably
smaller and simpler than a farm or workshop.
```

---

## BEFORE GENERATING VOLUME

**Poly budget.** The first refinery came back at **1,939,888 triangles**. The
characters were 10,403. A building at map scale needs roughly **2,000–10,000**,
and a comfortable total scene budget for smooth browser rendering is around
**500,000** — ten buildings at 1.9M each would exceed that forty times over.

Find Meshy's low-poly / game-ready export before generating a library. The
`Printability` badge suggests the default preview is tuned for 3D printing,
which deliberately wants dense meshes. Fallback: Blender Decimate plus Draco,
both confirmed working in this install.

**Test three first.** Generate **refinery, tavern, farm** as a set and judge them
side by side. If those three read as one village, the template works and the
other six are safe. If they do not, fix the style block — not the buildings.

Buildings are where drift shows most: characters are scattered and mismatch
reads as variety, but buildings sit adjacent in a settlement where two styles
are immediately obvious.
