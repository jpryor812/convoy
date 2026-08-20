#!/usr/bin/env python3
"""Draw the valley with the art on it -- tiled ground, buildings, people, flags.

    python3 preview_world.py   ->  world_preview.html

WHAT THIS IS FOR. `preview_layout.py` answers "where does everything stand?" with
coloured squares and no art. This answers "what does it LOOK like?", which is a
different question and the one that decides whether the map reads as a place or
as a diagram. Neither needs a simulation run, so both are fast enough to look at
after every change.

It draws a PLAUSIBLE occupancy, not a real one -- every place filled to a share
of its slots, agents standing about, flags on the ground around each holding.
That is enough to judge the art, the scale and the density. Wiring the actual
run in is `render_world.py`'s job.

THE MAP RUNS LEFT TO RIGHT
-----------------------------------------------------------------------------
`layout` puts north at -y and the road runs down the screen, which is right for
the world model and wrong for looking at. The valley is 2.84:1, so drawn
vertically it uses 19.8% of a 1080p viewport against 62.5% drawn horizontally --
three times the pixels per agent, for free.

It also reads better. Refineries at the left, market at the right, extraction
strung between: that is raw material to finished good to sold, in the direction
the audience already reads. Vertically it is a list.

The rotation lives HERE, in the view, not in `layout`. The same coordinates feed
React Three Fiber later and north should stay north in the world model.
"""

from __future__ import annotations

import base64
import json
import random
from pathlib import Path

from convoy import layout as L
from convoy import sprites as SP
from convoy import world_map as M

ROOT = Path(__file__).resolve().parent
GENERATED = ROOT / "art" / "generated"
KENNEY = ROOT / "kenney_medieval-rts" / "PNG" / "Default size"

# THE GROUND AND THE SPRITES ARE DELIBERATELY NOT AT THE SAME SCALE.
#
# `art/pixelate.py` authors buildings at 8 pixels to the metre, which is honest:
# a 13m refinery comes out 109px and an 8m farm 52px, and the ratio between them
# is true. Drawing the GROUND at that scale as well does not work. A market
# square here is ~550m across -- the ground was scaled 1.8x so buildings would
# have room to expand into -- so at 8px/m a 1600px screen shows 200m and every
# building at Town is off the edge of it. The first version of this file did
# exactly that and rendered an empty field.
#
# So the ground is drawn at 3px/m and the sprites keep their authored size, which
# makes buildings about 2.7x oversized against the land they stand on. That is
# not a fudge, it is the genre: Stardew, Zelda and the reference screenshot all
# draw a house far larger than its footprint, because a map is for reading and
# a to-scale house is a roof you cannot identify. Sizes stay honest RELATIVE TO
# EACH OTHER, which is the part that carries information.
# ONE METRE IS ONE PIXEL, and everything else falls out of it.
#
# A site is a 2x2 block of 32m parcels, so a block is 64m -- which at 1px/m is
# exactly the 64x64 canvas a Kenney structure is drawn on. A building therefore
# fills its four plots precisely, with no scale factor anywhere and nothing to
# keep in sync. A Pipoya ground tile is 48px and so covers 48m.
#
# The earlier 1.25 was solved for a different problem: fitting reduced Meshy
# renders, which were ~76px for a building that occupied 62m. With the pack's
# art the sizes already agree, and the arithmetic gets to be trivial.
PIXELS_PER_METRE = 1.0
TILE_M = 48.0                        # one Pipoya tile

OUT = ROOT / "world_preview.html"


# ---------------------------------------------------------------------------
# ASSETS
# ---------------------------------------------------------------------------

def data_uri(path: Path) -> str:
    return "data:image/png;base64," + base64.b64encode(path.read_bytes()).decode()


TERRAIN = ROOT / "art" / "generated" / "terrain"

# Ground per place, from `art/terrain.py`. The wilderness stops are the only
# places whose NAME makes a claim about their ground, so they are the only ones
# that get anything but grass -- the hills and the climb are rock, the crossing
# is a river.
GROUND_FOR_PLACE = {
    "The Hills": "rock",
}


def collect_assets() -> dict[str, str]:
    """Every image the page needs, inlined so the file opens anywhere.

    Buildings and people come through `convoy.sprites` rather than off disk, so
    this page and the real renderer cannot disagree about which sprite stands
    for a Refinery. Flipping `sprites.PREFER_RENDERED` changes both at once.
    """
    art: dict[str, str] = {}
    for p in sorted(TERRAIN.glob("*.png")):
        art[f"ground:{p.stem}"] = data_uri(p)
    art["bridge:deck"] = data_uri(SP.BRIDGE_DECK)
    art["bridge:pier"] = data_uri(SP.BRIDGE_PIER)
    for kind, paths in SP.PROP_SPRITES.items():
        for i, path in enumerate(paths):
            art[f"prop:{kind}:{i}"] = data_uri(path)

    for btype in SP.STRUCTURE_FOR_BUSINESS:
        art[f"biz:{_slug(btype)}"] = data_uri(SP.structure_for(btype))
    for person in list(SP.PERSON_FOR_MODEL.values()) + [SP.HAULER]:
        for facing in ("S", "N", "W", "E"):
            path = SP.PEOPLE / f"{person}-{facing}-0.png"
            if path.exists():
                art[f"person:{person}:{facing}"] = data_uri(path)
    return art


def _slug(name: str) -> str:
    return name.lower().replace(" / ", "-").replace("/", "-").replace(" ", "-")


# Business type -> the sprite that stands for it. Falls back per TYPE, so art can
# land one building at a time; `convoy/sprites.py` owns the real binding and this
# mirrors its filenames.
# The run this map is built for.
AGENT_COUNT = 20

BUILDING_FOR_TYPE = {
    "Farm": "farm",
    "Mining Operation": "mining-operation",
    "Refinery": "refinery",
    "Tavern / Inn": "tavern-inn",
    "Weaponsmith / Armory": "weaponsmith-armory",
    "Vehicle Dealer / Stable": "vehicle-dealer-stable",
    "Home Improvement Store": "home-improvement-store",
    "Mining/Farming Equipment Store": "mining-farming-equipment-store",
}
STORE_TYPES = ["Home Improvement Store", "Mining/Farming Equipment Store",
               "Weaponsmith / Armory", "Vehicle Dealer / Stable"]
SITE_TYPES = ["Farm", "Mining Operation", "Refinery", "Tavern / Inn"]


# ---------------------------------------------------------------------------
# A PLAUSIBLE VALLEY
# ---------------------------------------------------------------------------

def starting_world(places: dict[str, L.Place]) -> dict:
    """The world at hour zero, built by the simulation rather than invented.

    THIS USED TO MAKE THINGS UP. It filled every place to a share of its slots
    with random businesses, which was the right thing while the question was
    "does the art read at map size" -- a full valley shows more than an empty
    one. It is the wrong thing now the question is "what does a run start from",
    and it was actively misleading: a demo whose whole point is that AGENTS
    develop the land opened on a map where the land was already developed.

    So it calls `world_setup.new_world` and draws what comes back. Every building
    on the map is a government branch, one per business type, because that is
    exactly what exists before anybody has done anything. The state is a backstop
    -- it proves each trade is possible and sets a price to undercut -- and every
    other block is ground still for sale.
    """
    from convoy.events import EventLog
    from convoy.world_setup import new_world

    roster = [(f"Agent{n}", "preview") for n in range(1, AGENT_COUNT + 1)]
    world = new_world(EventLog(None, echo_min=99), roster)

    # A slot per government branch, taken in the order `layout` lays them out --
    # centre first, so the state holds the ground fronting each settlement.
    next_slot: dict[str, int] = {}
    buildings, flags = [], []
    for biz in world.businesses.values():
        place = places.get(biz.location)
        if place is None:
            continue
        i = next_slot.get(biz.location, 0)
        if i >= len(place.slots):
            continue
        next_slot[biz.location] = i + 1
        slot = place.slots[i]
        buildings.append({
            "x": slot.x, "y": slot.y, "type": biz.type, "owner": "Government",
            "sprite": _slug(biz.type), "scale": L.building_scale(biz.plots),
            "plots": biz.plots, "place": biz.location,
        })
        near = sorted(place.parcels,
                      key=lambda q: (q.x - slot.x) ** 2 + (q.y - slot.y) ** 2)
        for n, parcel in enumerate(near[:biz.plots]):
            flags.append({"x": parcel.x, "y": parcel.y,
                          "owner": "Government", "home": n < 4})

    # Everyone starts in Town, so they are drawn milling about the market rather
    # than spread evenly over a valley nobody has walked into yet.
    rng = random.Random(20260820)
    people = []
    for agent in world.agents.values():
        place = places.get(agent.location)
        if place is None or not place.slots:
            continue
        slot = rng.choice(place.slots)
        people.append({
            "x": slot.x + rng.uniform(-46, 46),
            "y": slot.y + rng.uniform(34, 78),
            "person": rng.choice(list(SP.PERSON_FOR_MODEL.values())),
            # Facing the viewer mostly, so faces are visible; a few turned so
            # a standing crowd does not look like a chorus line.
            "facing": rng.choice(("S", "S", "S", "S", "W", "E", "N")),
            "owner": agent.id,
        })
    return {"buildings": buildings, "people": people, "flags": flags}


def build_payload() -> dict:
    places = L.build()
    minx, miny, maxx, maxy = L.bounds(places)

    roads = [[(p.x, p.y) for p in L.main_road()]]
    roads += [[(p.x, p.y) for p in pl.path] for pl in places.values() if pl.path]

    return {
        "bounds": {"minx": minx, "miny": miny, "maxx": maxx, "maxy": maxy},
        "ppm": PIXELS_PER_METRE,
        "tile_m": TILE_M,
        "roads": roads,
        "parcel_m": L.PARCEL_PITCH,
        "block_m": L.BLOCK_PITCH,
        "stride_m": L.BLOCK_STRIDE,
        "river": {"axis": L.river_axis(), "half": L.RIVER_HALF_WIDTH},
        "places": [
            {
                "name": p.name, "kind": p.kind, "protected": p.protected,
                "x": p.center.x, "y": p.center.y,
                "ground": GROUND_FOR_PLACE.get(p.name, "grass"),
                "parcels": [{"x": q.x, "y": q.y} for q in p.parcels],
                "props": [{"kind": q.kind, "x": q.x, "y": q.y,
                           "scale": q.scale} for q in p.props],
            }
            for p in places.values()
        ],
        **starting_world(places),
    }


def main() -> int:
    payload = build_payload()
    art = collect_assets()
    html = (TEMPLATE
            .replace("__PROPS__", json.dumps(
                {k: len(v) for k, v in SP.PROP_SPRITES.items()}))
            .replace("__DATA__", json.dumps(payload))
            .replace("__ART__", json.dumps(art)))
    OUT.write_text(html, encoding="utf-8")
    b = payload["bounds"]
    print(f"wrote {OUT.name} -- "
          f"{(b['maxy'] - b['miny']) * PIXELS_PER_METRE:,.0f}"
          f"x{(b['maxx'] - b['minx']) * PIXELS_PER_METRE:,.0f}px world, "
          f"{len(payload['buildings'])} buildings, "
          f"{len(payload['people'])} people, {len(payload['flags'])} flags, "
          f"{len(art)} images ({OUT.stat().st_size / 1024:,.0f} KB)")
    return 0


TEMPLATE = r"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<title>Convoy -- the valley</title>
<style>
  html,body{margin:0;height:100%;background:#12160f;color:#e8e4d8;
            font:13px/1.5 ui-monospace,Menlo,monospace;overflow:hidden}
  canvas{display:block;cursor:grab;image-rendering:pixelated}
  canvas.drag{cursor:grabbing}
  #hud{position:fixed;left:12px;top:12px;background:#12160fdd;padding:9px 12px;
       border:1px solid #3a4030;border-radius:5px;pointer-events:none;z-index:2}
  #hud b{color:#c9d6a8}
  #keys{position:fixed;right:12px;top:12px;background:#12160fdd;padding:9px 12px;
        border:1px solid #3a4030;border-radius:5px;z-index:2;text-align:right}
  #keys span{color:#8d9c72}
</style></head><body>
<canvas id="c"></canvas>
<div id="hud"></div>
<div id="keys"><span>drag</span> pan &nbsp; <span>wheel</span> zoom &nbsp;
  <span>1</span> close &nbsp; <span>2</span> place &nbsp; <span>0</span> whole valley</div>
<script>
const DATA = __DATA__, ART = __ART__;
const c = document.getElementById("c"), g = c.getContext("2d");
const hud = document.getElementById("hud");

/* Images decode asynchronously; nothing may draw until they are all in, or the
   first frames come out half-empty and it looks like a bug in the layout. */
const IMG = {}; let pending = 0, ready = false;
for (const [k, src] of Object.entries(ART)) {
  const im = new Image(); pending++;
  im.onload = im.onerror = () => { if (--pending === 0) { ready = true; draw(); } };
  im.src = src; IMG[k] = im;
}

const B = DATA.bounds, PPM = DATA.ppm, TILE = DATA.tile_m * PPM;
let ROAD_PATTERN = null, STREET_PATTERN = null, GRASS_PATTERN = null;
const PROP_COUNT = __PROPS__;
/* Filled by drawParcels each frame, drawn afterwards so a tree overlaps the
   square below it instead of being clipped by the next square's fill. */
let UNSOLD = [];

function drawScrubTrees(){
  for (const q of UNSOLD){
    const n = PROP_COUNT.tree || 1;
    /* Two thirds of them, so unsold land reads as woodland rather than as an
       orchard planted on a grid. */
    if (hash(q.x | 0, q.y | 0) > 0.68) continue;
    const im = IMG[`prop:tree:${Math.floor(hash(q.y | 0, q.x | 0) * n)}`];
    if (im) g.drawImage(im, Math.round(wx(q) - im.width / 2),
                        Math.round(wy(q) - im.height / 2), im.width, im.height);
  }
}

/* THE ROTATION. World +y (north to south) becomes screen +x, so the valley lies
   down. Kept to these two functions -- everything else works in world metres. */
const wx = (p) => (p.y - B.miny) * PPM;
const wy = (p) => (p.x - B.minx) * PPM;
const WORLD_W = (B.maxy - B.miny) * PPM, WORLD_H = (B.maxx - B.minx) * PPM;

let zoom = 1, panx = 0, pany = 0;

/* THE FIRST FRAMING WAITS FOR A REAL VIEWPORT. Centring the view divides by the
   canvas width, and at startup that width can still be zero -- the pane has not
   been laid out yet. The division then puts the chosen place at pixel (0,0) and
   the map opens on an empty corner of the valley, which looks exactly like a
   layout bug and is not one. */
let framed = false;
function resize(){
  c.width = innerWidth; c.height = innerHeight;
  if (!framed && c.width > 0 && c.height > 0){ framed = true; centreOn(OPEN_ON); }
  else clampPan();
  draw();
}
function clampPan(){
  /* Keep the world under the viewport -- but CENTRE it in any direction where
     the world is smaller than the view, rather than pinning it to zero. Zoomed
     out to the whole valley the map is much wider than it is tall, so the fit is
     decided by width and there is vertical slack; pinned at zero that slack all
     fell below the valley and two thirds of the screen was empty grass. */
  const vw = c.width / zoom, vh = c.height / zoom;
  panx = WORLD_W <= vw ? (vw - WORLD_W) / 2
       : Math.max(Math.min(panx, 0), -(WORLD_W - vw));
  pany = WORLD_H <= vh ? (vh - WORLD_H) / 2
       : Math.max(Math.min(pany, 0), -(WORLD_H - vh));
}
function view(level){
  if (level === 0) zoom = Math.min(c.width / WORLD_W, c.height / WORLD_H);
  if (level === 1) zoom = 1;            /* 8px per metre -- sprites 1:1 */
  if (level === 2) zoom = 0.4;
  clampPan(); draw();
}

/* Deterministic per-position noise, so a tree never changes size between two
   renders of the same world.

   Math.imul, NOT `*`. The obvious version multiplies with `*` and it is subtly
   broken: JavaScript numbers are doubles, so `x * 374761393` for a coordinate in
   the thousands runs past 2^53 and loses the low bits the mix depends on. The
   result still LOOKS like noise -- it was not obviously wrong -- but every value
   landed between 0.23 and 0.36, so `Math.floor(hash * 3)` never returned 2 and
   the third variant of every prop was unreachable. Every bush in the valley was
   the same dark scrub. Math.imul keeps the multiply in int32 where the mix
   works. */
function hash(x, y){
  let h = (Math.imul(x | 0, 374761393) + Math.imul(y | 0, 668265263)) | 0;
  h = Math.imul(h ^ (h >>> 13), 1274126177);
  return ((h ^ (h >>> 16)) >>> 0) / 4294967296;
}

/* THE RIVER IS A BAND ACROSS THE VALLEY, not a pond at the junction.
   Its axis is The Crossing's own position, so the water is by definition where
   the crossing is. Because the map lies the valley down left-to-right, a band
   across the valley draws as a vertical stripe -- and the road meets it at one
   point, which is the bridge. A round pool at the junction, which is what the
   first version drew, reads as a village duck pond and explains nothing. */
const RIVER_X = (DATA.river.axis - B.miny) * PPM;
const RIVER_HALF = DATA.river.half * PPM;

/* Everything else is one terrain per place, nearest wins, grass otherwise.
   Cheap and good enough: places are far apart and the transition falls in open
   country where nobody is looking for a coastline. */
function groundAt(px, py){
  if (Math.abs(px - RIVER_X) < RIVER_HALF) return "water";
  let best = null, bd = Infinity;
  for (const p of DATA.places){
    if (p.ground === "grass" || p.ground === "water") continue;
    const d = (wx(p) - px) ** 2 + (wy(p) - py) ** 2;
    if (d < bd){ bd = d; best = p; }
  }
  return (best && bd < (330 * PPM) ** 2) ? best.ground : "grass";
}

/* The bridge: deck tiles laid along the road wherever it is over water, with
   the pier row tucked under the downstream edge. Placed by following the road
   rather than by drawing a straight span, so it stays on the road even though
   the road bends through the junction. */
function drawBridge(){
  const deck = IMG["bridge:deck"], pier = IMG["bridge:pier"];
  if (!deck || !deck.width) return;
  /* EVERY road that reaches the water, not just the valley road. Four spurs
     hang off The Crossing and two of them cross the channel; bridging only the
     main road left carts walking on the river. */
  const step = deck.width;
  for (const road of DATA.roads) for (let i = 0; i < road.length - 1; i++){
    const a = {x: road[i][0], y: road[i][1]}, b = {x: road[i+1][0], y: road[i+1][1]};
    const ax = wx(a), ay = wy(a), bx = wx(b), by = wy(b);
    const len = Math.hypot(bx - ax, by - ay);
    for (let t = 0; t < len; t += step){
      const x = ax + (bx - ax) * (t / len), y = ay + (by - ay) * (t / len);
      if (Math.abs(x - RIVER_X) > RIVER_HALF + step * 0.5) continue;
      if (pier && pier.width)
        g.drawImage(pier, Math.round(x - step / 2),
                    Math.round(y + deck.height / 2 - 4), pier.width, pier.height);
      g.drawImage(deck, Math.round(x - step / 2),
                  Math.round(y - deck.height / 2), deck.width, deck.height);
    }
  }
}

function drawGround(x0, y0, x1, y1){
  const i0 = Math.floor(x0 / TILE), i1 = Math.ceil(x1 / TILE);
  const j0 = Math.floor(y0 / TILE), j1 = Math.ceil(y1 / TILE);
  for (let i = i0; i <= i1; i++) for (let j = j0; j <= j1; j++){
    const im = IMG["ground:" + groundAt(i * TILE + TILE / 2, j * TILE + TILE / 2)];
    if (im) g.drawImage(im, i * TILE, j * TILE, TILE, TILE);
  }
}

/* THE LAND GRID. Every parcel is drawn, owned or not, because the point is to
   show that the ground IS divided -- an economy where land is the scarce thing
   should look like somewhere land has been surveyed. Owned parcels take their
   holder's colour; a site's own four are filled more strongly than ground it
   bought later, so a founding block reads as a unit. */
/* THE STREETS, AND THEY FOLLOW DEVELOPMENT. A path square one stride across is
   laid under each BUILT holding -- wider than the 2x2 block standing on it, so
   the surplus shows as a lane on all four sides, and neighbouring squares
   overlap into a connected grid without anybody working out where a junction is.

   Under built holdings only, not under every surveyed block. Paving the whole
   lattice turned each settlement into a sand field with a few green squares in
   it, which is backwards: the valley is grass, and a street is something a town
   wears into it. Done this way the network grows as the run does, and a place
   with two businesses looks like two farmsteads on a lane rather than like a
   town waiting for occupants.

   Drawn before the parcels, so property squares sit ON the street and the lane
   is exactly the ground nobody owns. */
function drawStreets(){
  const S = DATA.stride_m * PPM;
  if (!STREET_PATTERN && IMG["ground:sand"])
    STREET_PATTERN = g.createPattern(IMG["ground:sand"], "repeat");
  g.fillStyle = STREET_PATTERN || "#e8dca4";
  for (const b of DATA.buildings)
    g.fillRect(Math.round(wx(b) - S / 2), Math.round(wy(b) - S / 2), S, S);
}

function drawParcels(){
  const P = DATA.parcel_m * PPM;
  const owned = {};
  for (const f of DATA.flags) owned[Math.round(f.x) + ":" + Math.round(f.y)] = f;

  for (const place of DATA.places) for (const q of place.parcels){
    const x = Math.round(wx(q) - P / 2), y = Math.round(wy(q) - P / 2);
    const f = owned[Math.round(q.x) + ":" + Math.round(q.y)];

    /* UNSOLD GROUND IS TREES. Land is the scarce thing in this economy, so a
       map that only draws the sold squares cannot show what is left -- which is
       the number an agent deciding where to build actually needs. Drawing the
       remainder as woodland says it without a legend: cleared ground is taken,
       trees are room to expand, and the settlement visibly eats into them as a
       run goes on.

       The square still gets its faint boundary, because the point is that this
       is a PLOT nobody has bought rather than open country. */
    if (!f){
      /* Painted back to GRASS, opaquely. The street square laid under the whole
         block is sand, and a translucent green wash over it left unsold plots
         looking like bare ground -- so a settlement read as a sand town with a
         few green patches instead of a green one with streets through it. Only
         the lanes should be path. */
      if (!GRASS_PATTERN && IMG["ground:grass"])
        GRASS_PATTERN = g.createPattern(IMG["ground:grass"], "repeat");
      g.fillStyle = GRASS_PATTERN || "#91cc49";
      g.fillRect(x + 1, y + 1, P - 2, P - 2);
      g.strokeStyle = "rgba(28,48,20,0.40)"; g.lineWidth = 1;
      g.strokeRect(x + 0.5, y + 0.5, P - 1, P - 1);
      UNSOLD.push({x: q.x, y: q.y});
      continue;
    }
    g.fillStyle = ownerColour(f.owner, f.home ? 0.40 : 0.22);
    g.fillRect(x + 1, y + 1, P - 2, P - 2);
    /* A site's founding four are ringed heavier than ground bought later, so a
       block reads as one holding rather than four separate squares. */
    g.strokeStyle = ownerColour(f.owner, f.home ? 0.95 : 0.6);
    g.lineWidth = f.home ? 2 : 1;
    g.strokeRect(x + 1, y + 1, P - 2, P - 2);
  }
  g.lineWidth = 1;
}

function drawRoads(){
  /* Drawn, not tiled. Kenney ships a full set of road pieces, but fitting them
     needs an autotiler that knows which neighbours are road, and the roads here
     are smooth polylines that do not land on tile centres. A stroked path with
     a darker verge gets the same look and follows the real geometry exactly. */
  /* A verge, then the road surface itself as a repeating Pipoya earth tile --
     Kenney's flat tan stripe sat on textured ground looking like tape. */
  if (!ROAD_PATTERN && IMG["ground:earth"])
    ROAD_PATTERN = g.createPattern(IMG["ground:earth"], "repeat");
  const passes = [{w: 32, col: "#4a5a30"}, {w: 24, col: ROAD_PATTERN || "#918d4d"}];
  for (const p of passes){
    g.lineWidth = p.w; g.strokeStyle = p.col;
    g.lineCap = "round"; g.lineJoin = "round";
    for (const road of DATA.roads){
      g.beginPath();
      road.forEach(([x, y], k) => {
        const P = {x, y};
        k ? g.lineTo(wx(P), wy(P)) : g.moveTo(wx(P), wy(P));
      });
      g.stroke();
    }
  }
}

function sprite(key, x, y, scale){
  const im = IMG[key]; if (!im || !im.width) return;
  const w = im.width * (scale || 1), h = im.height * (scale || 1);
  /* People are anchored at the FOOT, so a figure stands ON the ground it is at
     rather than hovering with the square centred on its waist. */
  g.drawImage(im, Math.round(x - w / 2), Math.round(y - h), w, h);
}

function building(b){
  const im = IMG["biz:" + b.sprite]; if (!im || !im.width) return;
  /* CENTRED, unlike people. A slot IS the shared corner of four parcels, so a
     building centred on it covers a quarter of each -- which is the whole point
     of the grid: a founding business visibly sits on its four plots. */
  const w = im.width * b.scale, h = im.height * b.scale;
  g.drawImage(im, Math.round(wx(b) - w / 2), Math.round(wy(b) - h / 2), w, h);
}

const OWNER_HUE = {};
function ownerColour(id, alpha){
  if (OWNER_HUE[id] === undefined){
    const n = [...id].reduce((a, ch) => a + ch.charCodeAt(0), 0);
    OWNER_HUE[id] = (n * 47) % 360;
  }
  return `hsl(${OWNER_HUE[id]} 70% 52% / ${alpha === undefined ? 1 : alpha})`;
}

function drawFlags(){
  /* One flag per parcel, in the corner of the square so it never sits under the
     building standing in the middle of the block. */
  const P = DATA.parcel_m * PPM;
  for (const f of DATA.flags){
    const x = Math.round(wx(f) - P / 2) + 4, y = Math.round(wy(f) + P / 2) - 3;
    g.strokeStyle = "#22301a"; g.lineWidth = 1;
    g.beginPath(); g.moveTo(x + 0.5, y); g.lineTo(x + 0.5, y - 11); g.stroke();
    g.fillStyle = ownerColour(f.owner);
    g.beginPath(); g.moveTo(x + 1, y - 11); g.lineTo(x + 8, y - 8.5);
    g.lineTo(x + 1, y - 6); g.closePath(); g.fill(); g.stroke();
  }
}

function draw(){
  if (!ready) return;
  g.setTransform(1, 0, 0, 1, 0, 0);
  g.imageSmoothingEnabled = false;
  g.fillStyle = "#2f7d43"; g.fillRect(0, 0, c.width, c.height);
  g.setTransform(zoom, 0, 0, zoom, panx * zoom, pany * zoom);

  const x0 = -panx, y0 = -pany;
  const x1 = x0 + c.width / zoom, y1 = y0 + c.height / zoom;

  drawGround(x0, y0, x1, y1);
  drawStreets();
  UNSOLD = [];
  drawParcels();
  drawScrubTrees();
  drawRoads();
  drawBridge();

  /* Trees and rocks. Which variant a given prop uses is hashed off its own
     position, so a tree never changes size between renders of the same world. */
  for (const p of DATA.places) for (const q of p.props){
    const n = PROP_COUNT[q.kind] || 1;
    const im = IMG[`prop:${q.kind}:${Math.floor(hash(q.x | 0, q.y | 0) * n)}`];
    if (im) g.drawImage(im, Math.round(wx(q) - im.width / 2),
                        Math.round(wy(q) - im.height), im.width, im.height);
  }

  drawFlags();

  /* PAINTER'S ORDER. Everything that stands up is sorted by its screen y, so a
     building further down the screen is drawn over one behind it and the map
     gets depth for free. Sorting by world position instead would be wrong the
     moment the view rotated. */
  const standing = [];
  for (const b of DATA.buildings)
    standing.push({y: wy(b), f: () => building(b)});
  for (const p of DATA.people)
    standing.push({y: wy(p), f: () => sprite(`person:${p.person}:${p.facing}`,
                                             wx(p), wy(p), 1)});
  standing.sort((a, b) => a.y - b.y).forEach(s => s.f());

  /* Labels last, and only when zoomed out far enough that they are not clutter. */
  if (zoom < 0.75){
    g.font = `${Math.round(13 / zoom)}px ui-monospace,monospace`;
    g.textAlign = "center";
    for (const p of DATA.places){
      g.fillStyle = "#0d1108cc";
      const w = g.measureText(p.name).width + 10 / zoom;
      g.fillRect(wx(p) - w / 2, wy(p) - 26 / zoom, w, 18 / zoom);
      g.fillStyle = p.kind === "spur" ? "#c9d6a8" : "#f2e9c9";
      g.fillText(p.name, wx(p), wy(p) - 12 / zoom);
    }
  }

  hud.innerHTML =
    `<b>${DATA.places.length}</b> places &middot; ` +
    `<b>${DATA.buildings.length}</b> buildings &middot; ` +
    `<b>${DATA.people.length}</b> people &middot; ` +
    `<b>${DATA.flags.length}</b> plots flagged<br>` +
    `${(WORLD_W / PPM / 1000).toFixed(1)}km valley &middot; ` +
    `zoom ${zoom.toFixed(2)}x &middot; ` +
    `${Math.round(c.width / zoom / PPM)}m across`;
}

let dragging = false, lx = 0, ly = 0;
c.addEventListener("mousedown", e => {
  dragging = true; lx = e.clientX; ly = e.clientY; c.classList.add("drag");
});
addEventListener("mouseup", () => { dragging = false; c.classList.remove("drag"); });
addEventListener("mousemove", e => {
  if (!dragging) return;
  panx += (e.clientX - lx) / zoom; pany += (e.clientY - ly) / zoom;
  lx = e.clientX; ly = e.clientY; clampPan(); draw();
});
c.addEventListener("wheel", e => {
  e.preventDefault();
  const before = {x: -panx + e.clientX / zoom, y: -pany + e.clientY / zoom};
  zoom = Math.max(0.03, Math.min(3, zoom * (e.deltaY < 0 ? 1.12 : 1 / 1.12)));
  panx = -(before.x - e.clientX / zoom); pany = -(before.y - e.clientY / zoom);
  clampPan(); draw();
}, {passive: false});
addEventListener("keydown", e => {
  if (e.key === "0") view(0); if (e.key === "1") view(1); if (e.key === "2") view(2);
});
addEventListener("resize", resize);

/* Open on Town -- the market end, and the busiest ground in the valley. Centred
   on the place itself rather than on a corner of the world box: the box includes
   every spur's outermost tree, so its centre is open country and the first thing
   you saw was an empty field. */
const OPEN_ON = "Town";
function centreOn(name){
  const p = DATA.places.find(q => q.name === name) || DATA.places[0];
  panx = -(wx(p) - c.width / 2 / zoom);
  pany = -(wy(p) - c.height / 2 / zoom);
  clampPan();
}
zoom = 1;
resize();
</script></body></html>
"""


if __name__ == "__main__":
    raise SystemExit(main())
