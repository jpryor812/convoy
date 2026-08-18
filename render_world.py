#!/usr/bin/env python3
"""Turn a finished run into a map you can scrub through and interrogate.

Convoy is headless: a run leaves 31,000 JSON lines and nothing to look at. This
builds a single self-contained HTML file from `events.jsonl` -- the valley, its
businesses, every agent moving hour by hour, and, on click, that agent's own
account of why it did what it did.

    python3 render_world.py                      # newest run -> world.html
    python3 render_world.py --run runs/phase2/20260817-004401 --out valley.html

WHERE THE POSITIONS COME FROM. Nothing logs "agent X is at Y" on a schedule --
except the hourly diary, which carries `location` for every living agent every
simulated hour. That is the position backbone, refined by `travel` events, which
give a departure point, a destination and a duration, so an agent can be shown
ON THE ROAD between two places rather than teleporting.

WHY SELF-CONTAINED. Every sprite is inlined as a data URI. A classroom file that
breaks because a relative path moved is worse than no file, and the whole point
is that a teacher can mail this to a student.
"""

from __future__ import annotations

import argparse
import base64
import json
from collections import defaultdict
from pathlib import Path

from convoy import data as D
from convoy import sprites as SP
from convoy import world_map as M

RUN_DIR = Path("runs/phase2")

# The road runs north to south down the middle; spurs branch left and right.
ROAD_X = 600
TOP_Y = 150
JUNCTION_GAP = 210
SPUR_DX = 300
# Town, North PZ and Refinery Row carry THREE spurs; the third is pushed 1.55x
# out on the left, so the canvas has to clear 600 - 465 - half a card.
CANVAS_W = 1210


# ---------------------------------------------------------------------------
# ASSETS
# ---------------------------------------------------------------------------

def data_uri(path: Path) -> str:
    raw = path.read_bytes()
    mime = "image/svg+xml" if path.suffix == ".svg" else "image/png"
    return f"data:{mime};base64,{base64.b64encode(raw).decode('ascii')}"


def collect_assets() -> dict[str, str]:
    """Every sprite the page can need, keyed by the name the JS asks for.

    Uses the pack's `Default size` PNGs rather than `Retina`: at map scale the
    difference is invisible and the file is a third of the size, which decides
    whether this can be emailed.
    """
    assets: dict[str, str] = {}

    def add(key: str, path: Path) -> None:
        small = Path(str(path).replace("/Retina/", "/Default size/"))
        assets[key] = data_uri(small if small.exists() else path)

    # `structure_for` prefers a Blender-rendered PNG when one exists, so the art
    # can be replaced one building at a time rather than in a flag day.
    for btype in SP.STRUCTURE_FOR_BUSINESS:
        add(f"biz:{btype}", SP.structure_for(btype))
    add("biz:government", SP.GOVERNMENT_BADGE)

    # Keyed by MODEL, not by faction+pose. `agent_sprite` resolves a rendered
    # character when one exists and a Kenney unit when it does not, so the page
    # does not need to know which it got.
    for slot in D.MODEL_ROSTER:
        for owner in (False, True):
            key = f"agent:{slot.openrouter_id}:{'owner' if owner else 'plain'}"
            add(key, SP.agent_sprite(slot.openrouter_id, owns_business=owner))
    for faction in SP.FACTION_BASE:          # legend + fallback for stray models
        for pose in SP.POSES:
            add(f"unit:{faction}:{pose}", SP.unit(faction, pose))

    for kind, path in SP.GROUND_FOR_KIND.items():
        add(f"ground:{kind}", path)
    for place, decor in SP.DECOR_FOR_LOCATION.items():
        for i, path in enumerate(decor):
            add(f"decor:{place}:{i}", path)

    for name in D.VEHICLES:
        add(f"vehicle:{name}", SP.vehicle_sprite(name))
    for item in sorted(D.ALL_ITEMS):
        add(f"item:{item}", SP.item_icon(item))
    for glyph in set(SP.GLYPH_FOR_ACTION.values()) | set(SP.GLYPH_FOR_EVENT.values()):
        add(f"ui:{glyph}", SP.ui_glyph(glyph))
    return assets


# ---------------------------------------------------------------------------
# GEOGRAPHY
# ---------------------------------------------------------------------------

def build_places() -> dict[str, dict]:
    """Lay the 7 junctions down the road and hang their spurs off the sides."""
    places: dict[str, dict] = {}
    order = [loc.name for loc in M.LOCATIONS_SPEC]
    lo, hi = SP.ELEVATION_RANGE

    for i, name in enumerate(order):
        spec = M.LOCATION_BY_NAME[name]
        places[name] = {
            "name": name, "x": ROAD_X, "y": TOP_Y + i * JUNCTION_GAP,
            "kind": spec.kind, "elevation": spec.elevation,
            "protected": spec.protected, "junction": None,
            "climb": round((spec.elevation - lo) / (hi - lo), 3),
            "blurb": spec.blurb,
        }

    for junction, spurs in M.SPURS_BY_JUNCTION.items():
        base = places[junction]
        for k, spur in enumerate(spurs):
            # Alternate sides; a third spur is pushed further out on the left so
            # Town's three do not overlap.
            side = -1 if k % 2 == 0 else 1
            reach = SPUR_DX + (SPUR_DX * 0.55 if k >= 2 else 0)
            places[spur.name] = {
                "name": spur.name, "x": base["x"] + side * reach,
                "y": base["y"] + (28 if k >= 2 else 0),
                "kind": "spur", "elevation": base["elevation"],
                "protected": base["protected"], "junction": junction,
                "climb": base["climb"], "blurb": "working land",
            }
    return places


# ---------------------------------------------------------------------------
# THE RUN
# ---------------------------------------------------------------------------

def newest_run() -> Path:
    runs = [d for d in RUN_DIR.iterdir() if (d / "events.jsonl").exists()]
    if not runs:
        raise SystemExit(f"no runs with an events.jsonl under {RUN_DIR}")
    return max(runs, key=lambda d: d.stat().st_mtime)


def load_run(run: Path, places: dict[str, dict]) -> dict:
    with (run / "events.jsonl").open(encoding="utf-8") as fh:
        events = [json.loads(line) for line in fh if line.strip()]
    if not events:
        raise SystemExit(f"{run}/events.jsonl is empty")

    checkpoint = {}
    cp = run / "checkpoint.json"
    if cp.exists():
        checkpoint = json.loads(cp.read_text(encoding="utf-8"))

    end_hour = max(e["sim_time"] for e in events) / 3600.0
    known = set(places)

    agents: dict[str, dict] = {}
    tracks: dict[str, list] = defaultdict(list)
    decisions: dict[str, list] = defaultdict(list)
    businesses: dict[str, dict] = {}
    notable: list[dict] = []
    inventories: dict[str, dict] = {}

    names, models = agent_identity(checkpoint)

    for e in events:
        hour = e["sim_time"] / 3600.0
        actor, etype, detail = e.get("actor"), e["type"], e.get("detail", {})
        loc = e.get("location")

        if actor and actor.startswith("A"):
            a = agents.setdefault(actor, {
                "id": actor, "name": names.get(actor, actor),
                "model": models.get(actor, ""), "died": None,
            })
            # The hourly diary carries every living agent's location, which is
            # the only regular position signal in the log.
            if loc in known:
                tracks[actor].append([round(hour, 3), loc, None])
            if etype == "travel":
                dest = detail.get("destination")
                secs = float(detail.get("seconds") or 0)
                if dest in known:
                    # Departure and arrival, so the agent can be drawn moving
                    # along the road rather than jumping between two places.
                    tracks[actor].append([round(hour, 3), loc if loc in known else dest, dest])
                    tracks[actor].append([round(hour + secs / 3600.0, 3), dest, None])
            if etype in ("agent_died", "starved_to_death"):
                a["died"] = round(hour, 2)
            if etype == "llm_reasoning":
                decisions[actor].append({
                    "h": round(hour, 2),
                    "woken": detail.get("woken_because", ""),
                    "did": detail.get("did", ""),
                    "why": detail.get("text", ""),
                })

        if etype == "business_founded" and e.get("subject"):
            businesses[e["subject"]] = {
                "id": e["subject"], "type": detail.get("business_type", "?"),
                "place": loc, "owner": actor, "from": round(hour, 2),
                "to": None, "name": detail.get("name", ""),
            }
        elif etype in ("business_closed", "business_bankrupt") and e.get("subject"):
            if e["subject"] in businesses:
                businesses[e["subject"]]["to"] = round(hour, 2)

        glyph = SP.GLYPH_FOR_EVENT.get(etype)
        if glyph and e.get("significance", 1) >= 2 and etype != "llm_reasoning":
            notable.append({
                "h": round(hour, 2), "type": etype, "who": actor or "",
                "glyph": glyph, "where": loc or "",
                "detail": compact(detail),
            })

    government = government_businesses(checkpoint)
    if checkpoint:
        inventories = final_inventories(checkpoint)

    for track in tracks.values():
        track.sort(key=lambda row: row[0])

    return {
        "run": run.name,
        "end_hour": round(end_hour, 2),
        "places": list(places.values()),
        "agents": sorted(agents.values(), key=lambda a: a["id"]),
        "tracks": {k: dedupe(v) for k, v in tracks.items()},
        "decisions": decisions,
        "businesses": sorted(businesses.values(), key=lambda b: b["from"]),
        "government": government,
        "notable": notable,
        "inventories": inventories,
        "roles": {r: SP.POSE_FOR_ROLE.get(r, "villager") for r in D.WAGE_ROLES},
        "factions": SP.FACTION_FOR_MODEL,
    }


def dedupe(track: list) -> list:
    """Drop consecutive samples that say the same thing.

    The diary fires hourly per agent; an agent that stands still for 21 hours
    produces 21 identical rows, and a 20-agent 84-hour run carries thousands of
    them straight into the page.
    """
    out: list = []
    for row in track:
        if out and out[-1][1] == row[1] and out[-1][2] == row[2]:
            continue
        out.append(row)
    return out


def agent_identity(checkpoint: dict) -> tuple[dict, dict]:
    names, models = {}, {}
    for entry in walk_dict(checkpoint.get("agents")):
        aid = entry.get("id")
        if aid:
            names[aid] = entry.get("name", aid)
            models[aid] = entry.get("model", "")
    return names, models


def government_businesses(checkpoint: dict) -> list[dict]:
    out = []
    for entry in walk_dict(checkpoint.get("businesses")):
        if entry.get("owner") == "Government":
            out.append({
                "id": entry.get("id"), "type": entry.get("type"),
                "name": entry.get("name"), "place": entry.get("location"),
            })
    if out:
        return out
    # No checkpoint: fall back to the spec, which is where they come from anyway.
    return [
        {"id": f"G{i:04d}", "type": btype, "name": f"Government {btype}", "place": place}
        for i, (btype, place) in enumerate(M.GOVERNMENT_SITES.items(), start=1)
    ]


def final_inventories(checkpoint: dict) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for entry in walk_dict(checkpoint.get("agents")):
        aid = entry.get("id")
        if not aid:
            continue
        inv = decode(entry.get("inventory")) or {}
        out[aid] = {
            "denari": round(float(entry.get("denari") or 0), 1),
            "items": {k: v for k, v in inv.items() if v},
            "vehicle": entry.get("mounted_vehicle") or "On Foot",
            "alive": bool(entry.get("alive", True)),
        }
    return out


def decode(node):
    """The checkpoint encodes dicts as {"__dict__": [[k, v], ...]} and lists as
    {"__seq__": [...]}. Unwrap just enough to read values out."""
    if isinstance(node, dict):
        if "__dict__" in node:
            return {decode(k): decode(v) for k, v in node["__dict__"]}
        if "__seq__" in node:
            return [decode(v) for v in node["__seq__"]]
        if "__type__" in node:
            return {k: decode(v) for k, v in node.items() if k != "__type__"}
    return node


def walk_dict(node) -> list[dict]:
    decoded = decode(node)
    if isinstance(decoded, dict):
        return [v for v in decoded.values() if isinstance(v, dict)]
    if isinstance(decoded, list):
        return [v for v in decoded if isinstance(v, dict)]
    return []


def compact(detail: dict) -> str:
    bits = []
    for k, v in list(detail.items())[:4]:
        if isinstance(v, float):
            v = round(v, 1)
        bits.append(f"{k}={v}")
    return " ".join(bits)[:120]


# ---------------------------------------------------------------------------
# THE PAGE
# ---------------------------------------------------------------------------

def build_html(payload: dict, assets: dict[str, str]) -> str:
    height = TOP_Y + len(M.LOCATIONS_SPEC) * JUNCTION_GAP
    blob = json.dumps(payload, separators=(",", ":"))
    art = json.dumps(assets, separators=(",", ":"))
    return (
        TEMPLATE
        .replace("__DATA__", blob)
        .replace("__ART__", art)
        .replace("__W__", str(CANVAS_W))
        .replace("__H__", str(height))
    )


TEMPLATE = r"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Convoy — the valley</title>
<style>
  :root{
    --ink:#1d2b24; --muted:#5d6f66; --line:#c9d8cf;
    --bg:#eef4ef; --panel:#ffffff; --accent:#1b914d; --warn:#d97a2b;
  }
  *{box-sizing:border-box}
  body{margin:0;background:var(--bg);color:var(--ink);
    font:14px/1.5 ui-sans-serif,system-ui,-apple-system,"Segoe UI",Roboto,sans-serif}
  header{padding:14px 20px;background:var(--panel);border-bottom:1px solid var(--line);
    display:flex;gap:18px;align-items:center;flex-wrap:wrap;position:sticky;top:0;z-index:10}
  h1{font-size:16px;margin:0;letter-spacing:.02em}
  .sub{color:var(--muted);font-size:12px}
  .wrap{display:flex;gap:0;align-items:flex-start}
  .mapwrap{flex:1;min-width:0;overflow:auto;padding:16px}
  aside{width:390px;flex:none;height:calc(100vh - 64px);overflow:auto;
    background:var(--panel);border-left:1px solid var(--line);padding:16px}
  input[type=range]{width:340px;accent-color:var(--accent)}
  button{font:inherit;padding:5px 11px;border:1px solid var(--line);background:#fff;
    border-radius:7px;cursor:pointer}
  button:hover{border-color:var(--accent)}
  button.on{background:var(--accent);color:#fff;border-color:var(--accent)}
  .hour{font-variant-numeric:tabular-nums;font-weight:600;min-width:74px}
  .place{cursor:default}
  .plot{fill:#dff0e4;stroke:#b9d3c2;stroke-width:1.5}
  .plot.protected{stroke:var(--accent);stroke-width:2.5}
  .plabel{font-size:12.5px;font-weight:600;fill:#1d2b24}
  .pmeta{font-size:10.5px;fill:#5d6f66}
  .road{stroke:#d9a24d;stroke-width:26;stroke-linecap:round;fill:none}
  .road.spur{stroke-width:14;opacity:.8}
  .agent{cursor:pointer}
  .agent:hover .halo{opacity:.5}
  .halo{opacity:0;fill:var(--accent)}
  /* Nearest-neighbour, always. The character sprites are rendered at 54x80 on
     purpose; letting the browser smooth them on the way to the screen undoes
     the entire reason for rendering them small. Drawn at exactly half size, so
     the downscale drops whole pixels rather than blending them. */
  .px{image-rendering:pixelated;image-rendering:crisp-edges}
  .agent.sel .halo{opacity:.85}
  .card{border:1px solid var(--line);border-radius:9px;padding:11px;margin-bottom:11px}
  .card h3{margin:0 0 3px;font-size:14px}
  .dec{border-left:3px solid var(--accent);padding:7px 0 7px 10px;margin:9px 0}
  .dec .h{font-weight:600;font-variant-numeric:tabular-nums}
  .dec .did{color:var(--accent);font-size:12.5px;margin:2px 0}
  .dec .why{color:var(--muted);font-size:12.5px;white-space:pre-wrap}
  .row{display:flex;gap:7px;align-items:center;margin:3px 0}
  .row img{width:22px;height:22px}
  .tick{display:flex;gap:7px;align-items:flex-start;font-size:12px;margin:5px 0}
  .tick img{width:16px;height:16px;flex:none;margin-top:2px}
  .tick .t{color:var(--muted);font-variant-numeric:tabular-nums;flex:none;width:46px}
  .empty{color:var(--muted);font-style:italic}
  .legend{display:grid;grid-template-columns:repeat(2,1fr);gap:5px;font-size:11.5px}
  .legend div{display:flex;gap:5px;align-items:center}
  .legend img{width:19px;height:19px}
  .dec .why b{color:var(--ink)}
  /* A teacher opening this on a laptop half-screen must still get both halves;
     below this the sidebar goes under the map rather than crushing it. */
  @media (max-width:1120px){
    .wrap{flex-direction:column}
    aside{width:100%;height:auto;border-left:none;border-top:1px solid var(--line)}
    input[type=range]{width:200px}
  }
  .pill{display:inline-block;padding:1px 7px;border-radius:99px;font-size:11px;
    background:#e6f2ea;color:#14603a;margin-left:5px}
  .pill.dead{background:#fbe3e3;color:#8c2b2b}
</style></head><body>
<header>
  <h1>Convoy — the valley</h1>
  <span class="sub" id="runid"></span>
  <span class="hour" id="hourlabel">h0.0</span>
  <input type="range" id="slider" min="0" value="0" step="0.25">
  <button id="play">▶ Play</button>
  <button id="fit" class="on">Follow selection</button>
  <span class="sub" id="counts"></span>
</header>
<div class="wrap">
  <div class="mapwrap"><svg id="map" width="__W__" height="__H__"
       viewBox="0 0 __W__ __H__" xmlns="http://www.w3.org/2000/svg"></svg></div>
  <aside id="side"></aside>
</div>
<script>
const DATA = __DATA__;
const ART  = __ART__;
const SVG = "http://www.w3.org/2000/svg";
const CARD_W = 226, CARD_H = 132;
const PLACE = Object.fromEntries(DATA.places.map(p => [p.name, p]));
let hour = 0, selected = null, playing = null;

function el(tag, attrs, parent){
  const n = document.createElementNS(SVG, tag);
  for (const k in attrs) n.setAttribute(k, attrs[k]);
  if (parent) parent.appendChild(n);
  return n;
}
function img(href, x, y, w, h, parent, cls){
  const n = el("image", {x, y, width:w, height:h, href, class:cls||""}, parent);
  n.setAttribute("preserveAspectRatio","xMidYMid meet");
  return n;
}

/* An agent's position at `h`: the last sample at or before it. If that sample
   names a destination the agent is ON THE ROAD, so interpolate between the two
   places instead of parking it at the origin -- a 6-hour haul otherwise looks
   like the agent stood still and then teleported. */
function positionAt(id, h){
  const track = DATA.tracks[id];
  if (!track || !track.length) return null;
  let lo = 0, hi = track.length - 1, at = -1;
  while (lo <= hi){
    const mid = (lo + hi) >> 1;
    if (track[mid][0] <= h){ at = mid; lo = mid + 1; } else hi = mid - 1;
  }
  /* Before the first sample the agent already exists and is standing where it
     started -- returning a null position hid every agent at hour 0. */
  if (at < 0){
    const start = PLACE[track[0][1]];
    return start ? {place: track[0][1], x: start.x, y: start.y, moving:false} : null;
  }
  const [t0, from, dest] = track[at];
  const here = PLACE[from];
  if (!here) return null;
  if (dest && track[at+1]){
    const [t1, to] = track[at+1];
    const there = PLACE[to];
    if (there && t1 > t0){
      const k = Math.max(0, Math.min(1, (h - t0) / (t1 - t0)));
      return {place: k < .5 ? from : to, moving: true,
              x: here.x + (there.x - here.x) * k,
              y: here.y + (there.y - here.y) * k};
    }
  }
  return {place: from, x: here.x, y: here.y, moving:false};
}

function livingAt(a, h){ return a.died === null || h < a.died; }
function bizAt(b, h){ return b.from <= h && (b.to === null || h < b.to); }

function factionOf(model){ return DATA.factions[model] || "blue"; }
function poseOf(agent, h, owns){
  if (owns) return "owner";
  const p = positionAt(agent.id, h);
  return (p && p.moving) ? "cloaked" : "villager";
}

function draw(){
  const map = document.getElementById("map");
  map.textContent = "";
  const order = DATA.places.filter(p => p.junction === null);

  /* road + spur stubs, under everything */
  const roads = el("g", {}, map);
  for (let i = 0; i < order.length - 1; i++){
    el("path", {class:"road",
      d:`M${order[i].x} ${order[i].y} L${order[i+1].x} ${order[i+1].y}`}, roads);
  }
  for (const p of DATA.places){
    if (!p.junction) continue;
    const j = PLACE[p.junction];
    el("path", {class:"road spur", d:`M${j.x} ${j.y} L${p.x} ${p.y}`}, roads);
  }

  /* one card per place */
  const liveBiz = DATA.businesses.filter(b => bizAt(b, hour));
  const byPlace = {};
  for (const b of liveBiz) (byPlace[b.place] = byPlace[b.place] || []).push(b);
  for (const g of DATA.government) (byPlace[g.place] = byPlace[g.place] || []).push(g);

  for (const p of DATA.places){
    const g = el("g", {class:"place"}, map);
    const w = CARD_W, h = CARD_H, x = p.x - w/2, y = p.y - h/2;
    el("rect", {x, y, width:w, height:h, rx:12,
      class:"plot" + (p.protected ? " protected" : "")}, g);
    /* elevation reads as a shadow: the valley runs 20m to 340m and that
       gradient is the whole reason haulage costs what it does. */
    el("rect", {x, y, width:w, height:h, rx:12, fill:"#0d3b25",
      opacity:(p.climb * 0.22).toFixed(3)}, g);

    const decor = ART[`decor:${p.name}:0`] || ART[`decor:${p.junction}:1`];
    if (decor) img(decor, x + w - 30, y + h - 30, 26, 26, g);

    el("text", {x: x + 10, y: y + 20, class:"plabel"}, g).textContent = p.name;
    const meta = el("text", {x: x + 10, y: y + 34, class:"pmeta"}, g);
    meta.textContent = `${p.elevation}m${p.protected ? " · protected" : ""}`;

    /* buildings */
    const biz = (byPlace[p.name] || []);
    biz.slice(0, 6).forEach((b, i) => {
      const key = b.owner === undefined ? "biz:government" : `biz:${b.type}`;
      const node = img(ART[key] || ART["biz:government"],
        x + 10 + i*34, y + 42, 31, 31, g);
      node.appendChild(document.createElementNS(SVG,"title"))
          .textContent = `${b.name || b.type}${b.owner ? " · owner " + b.owner : " · state"}`;
      /* A grey dot marks a state branch. The state is a backstop, not a
         participant, and a map that cannot tell the two apart is misleading
         about who actually built this economy. */
      if (b.owner === undefined)
        el("circle", {cx:x + 14 + i*34, cy:y + 46, r:3.5, fill:"#686d6d"}, g);
    });
    if (biz.length > 6){
      el("text", {x: x + 10 + 6*34, y: y + 62, class:"pmeta"}, g)
        .textContent = `+${biz.length - 6}`;
    }
  }

  /* agents, drawn last so they sit on top */
  let alive = 0;
  for (const a of DATA.agents){
    if (!livingAt(a, hour)) continue;
    alive++;
    const pos = positionAt(a.id, hour);
    if (!pos || pos.x === null) continue;
    const owns = DATA.businesses.some(b => b.owner === a.id && bizAt(b, hour));
    /* Rendered character when the run's model has one, Kenney unit otherwise --
       resolved on the Python side, so this only has to pick owner vs plain. */
    const key = ART[`agent:${a.model}:${owns ? "owner" : "plain"}`]
      ? `agent:${a.model}:${owns ? "owner" : "plain"}`
      : `unit:${factionOf(a.model)}:${poseOf(a, hour, owns)}`;
    const idx = DATA.agents.indexOf(a);
    /* Fan agents around the lower half of their card so a crowd stays
       countable. The golden angle keeps successive agents apart instead of
       stacking them, and both radii are bounded by the card so nobody stands
       outside the place they are supposedly in. */
    const ang = idx * 2.399;
    const spread = pos.moving ? 0 : 1;
    const cx = pos.x + Math.cos(ang) * spread * (CARD_W/2 - 34);
    const cy = pos.y + (pos.moving ? 0 : 26 + Math.sin(ang) * 16);

    const g = el("g", {class:"agent" + (selected === a.id ? " sel" : "")}, map);
    /* A pale disc behind every figure. The units are small and their palette is
       the same family as the grass they stand on, so without it a crowd of
       agents on a green card is unreadable. */
    /* Agents are drawn TALL (0.6 aspect), matching the 96x160 character
       renders. Squeezing a standing figure into the old 22x27 box distorted it,
       and the detail those sprites carry only pays off at a size where a face
       is more than three pixels. */
    el("ellipse", {cx, cy:cy + 15, rx:13, ry:6, fill:"#ffffff", opacity:.72}, g);
    el("circle", {class:"halo", cx, cy:cy + 2, r:20}, g);
    img(ART[key], cx - 13.5, cy - 20, 27, 40, g, "px");
    g.appendChild(document.createElementNS(SVG,"title")).textContent =
      `${a.name} (${a.id})${owns ? " · owner" : ""}`;
    g.addEventListener("click", () => { selected = a.id; render(); });
  }

  document.getElementById("counts").textContent =
    `${alive} alive · ${liveBiz.length} player businesses`;
}

function esc(s){ return (s||"").replace(/[&<>]/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;"}[c])); }

/* Reasoning-model output arrives as light markdown -- a bolded lead line, then
   prose. Escaped and then re-marked, so the model's own emphasis survives
   without letting its text inject anything into the page. */
function reason(s){
  return esc(s).replace(/\*\*(.+?)\*\*/g, "<b>$1</b>").trim();
}

function sidebar(){
  const side = document.getElementById("side");
  if (!selected){
    const ticks = DATA.notable.filter(n => n.h <= hour).slice(-40).reverse();
    side.innerHTML =
      `<div class="card"><h3>What is happening</h3>
        <div class="sub">Click any figure on the map to read that agent's own
        account of its decisions.</div></div>
       <div class="card"><h3>Recent events</h3>${
        ticks.length ? ticks.map(n =>
         `<div class="tick"><span class="t">h${n.h.toFixed(1)}</span>
          <img src="${ART["ui:"+n.glyph]}" alt="">
          <span><b>${esc(n.type)}</b> ${esc(n.who)} ${esc(n.detail)}</span></div>`
        ).join("") : '<div class="empty">nothing yet</div>'}</div>
       <div class="card"><h3>Legend</h3><div class="legend">${
        Object.keys(DATA.factions).map(m =>
         `<div><img src="${ART["agent:"+m+":plain"] || ART["unit:"+DATA.factions[m]+":villager"]}" alt="">
          ${esc(m.split("/").pop())}</div>`).join("")
        }</div>
        <div class="sub" style="margin-top:8px">A grey dot marks a state
        business. The state is a backstop, not a participant.</div></div>
       <div class="card"><div class="sub">Terrain, buildings and people from the
        <b>Medieval RTS</b> pack by Kenney (kenney.nl), CC0. Vehicles, goods and
        action glyphs drawn for Convoy in the same palette.</div></div>`;
    return;
  }

  const a = DATA.agents.find(x => x.id === selected);
  const decs = (DATA.decisions[a.id] || []).filter(d => d.h <= hour).slice(-25).reverse();
  const owned = DATA.businesses.filter(b => b.owner === a.id && bizAt(b, hour));
  const inv = DATA.inventories[a.id];
  const pos = positionAt(a.id, hour);
  const dead = !livingAt(a, hour);

  side.innerHTML =
    `<div class="card">
      <h3>${esc(a.name)} <span class="pill${dead ? " dead" : ""}">${
        dead ? "died h" + a.died : esc(a.id)}</span></h3>
      <div class="sub">${esc(a.model)}</div>
      <div class="row"><img src="${ART["ui:travel"]}" alt="">
        ${pos ? esc(pos.place) + (pos.moving ? " (on the road)" : "") : "—"}</div>
      ${owned.length ? owned.map(b =>
        `<div class="row"><img src="${ART["biz:"+b.type]}" alt="">${esc(b.name || b.type)}</div>`
       ).join("") : '<div class="sub">owns no business</div>'}
      ${inv ? `<div class="row"><img src="${ART["ui:coin"]}" alt="">${inv.denari} denari
        <span class="sub">(at end of run)</span></div>
        <div class="row">${Object.entries(inv.items).slice(0,10).map(([k,v]) =>
          `<span title="${esc(k)} x${v}"><img src="${ART["item:"+k]}" alt="${esc(k)}">
           <small>${v}</small></span>`).join("")}</div>` : ""}
     </div>
     <div class="card"><h3>Why it did things</h3>
      <div class="sub">Its own words at the time, newest first — not a summary
      written afterwards.</div>
      ${decs.length ? decs.map(d =>
        `<div class="dec"><div class="h">h${d.h.toFixed(2)}
          <span class="sub">woken: ${esc(d.woken)}</span></div>
         <div class="did">did: ${esc(d.did) || "nothing"}</div>
         <div class="why">${reason(d.why) || "(acted without saying why)"}</div></div>`
       ).join("") : '<div class="empty">no recorded decisions before this hour</div>'}
     </div>
     <div class="card"><button onclick="selected=null;render()">← everything</button></div>`;
}

function render(){
  document.getElementById("hourlabel").textContent = "h" + hour.toFixed(1);
  document.getElementById("slider").value = hour;
  draw(); sidebar();
}

function boot(){
  document.getElementById("runid").textContent =
    `${DATA.run} · ${DATA.agents.length} agents · ${DATA.end_hour}h`;
  const s = document.getElementById("slider");
  s.max = DATA.end_hour;
  s.addEventListener("input", e => { hour = +e.target.value; render(); });
  document.getElementById("play").addEventListener("click", e => {
    if (playing){ clearInterval(playing); playing = null; e.target.textContent = "▶ Play"; return; }
    e.target.textContent = "⏸ Pause";
    playing = setInterval(() => {
      hour = hour >= DATA.end_hour ? 0 : Math.min(DATA.end_hour, hour + 0.5);
      render();
    }, 110);
  });
  render();
}
boot();
</script></body></html>
"""


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--run", type=Path, help="run directory; default is the newest")
    ap.add_argument("--out", type=Path, default=Path("world.html"))
    args = ap.parse_args()

    run = args.run or newest_run()
    places = build_places()

    problems = SP.check()
    if problems:
        print(f"art binding has {len(problems)} problem(s):")
        for line in problems[:10]:
            print(f"  - {line}")
        return 1

    payload = load_run(run, places)
    assets = collect_assets()
    args.out.write_text(build_html(payload, assets), encoding="utf-8")

    size = args.out.stat().st_size / 1024
    print(f"{args.out}  ({size:,.0f} KB)")
    print(f"  run       {payload['run']}  {payload['end_hour']}h")
    print(f"  agents    {len(payload['agents'])}")
    print(f"  places    {len(payload['places'])}")
    print(f"  business  {len(payload['businesses'])} player, "
          f"{len(payload['government'])} state")
    print(f"  decisions {sum(len(v) for v in payload['decisions'].values())}")
    print(f"  sprites   {len(assets)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
