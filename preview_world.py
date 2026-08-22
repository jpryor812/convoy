#!/usr/bin/env python3
"""The map: the valley drawn, and a run played back on it.

    python3 preview_world.py                      # hour zero, no run needed
    python3 preview_world.py --run latest         # play back the newest run
    python3 preview_world.py --run runs/phase2/X  # play back a particular one

Both modes write `world_preview.html`, a single self-contained file.

ONE RENDERER, NOT TWO. Until 2026-08-20 there were two: `render_world.py` could
read a run but drew the valley as cards in a row, and this file drew the valley
properly but had never seen a run. So the run you actually wanted to watch was
only ever available in the old layout. They are merged; the reading was ~200
lines and the drawing ~800, so the reading moved here and the other file is
gone.

WITHOUT A RUN it draws hour zero, built by `world_setup.new_world` rather than
invented: ten government branches, twenty agents in Town, every other block
wooded and for sale. That is what a run starts from, and it is enough to judge
the art, the scale and the density.

WITH A RUN it plays the thing back -- agents moving along the road between
places, businesses appearing at the hour they were founded, and every agent's
own account of why, quoted in their card up to wherever the slider sits.

`preview_layout.py` is still separate and still useful: it answers "where does
everything stand" with coloured squares and no art, which is the question to ask
when `layout.check()` fails.

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

import argparse
import base64
import json
import random
import re
from collections import defaultdict
from pathlib import Path

from convoy import checkpoint as CP
from convoy import inspect as I
from convoy import layout as L
from convoy import data as D
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
RUN_DIR = ROOT / "runs" / "phase2"


# ---------------------------------------------------------------------------
# ASSETS
# ---------------------------------------------------------------------------

# Everything here was PNG until the vehicles arrived, so the mime type was
# hard-coded. An SVG served as image/png does not error -- it loads as a
# zero-by-zero image and draws nothing, which looks exactly like art that was
# never wired up.
_MIME = {".png": "image/png", ".svg": "image/svg+xml",
         ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp"}


def data_uri(path: Path) -> str:
    mime = _MIME.get(path.suffix.lower(), "application/octet-stream")
    return f"data:{mime};base64," + base64.b64encode(path.read_bytes()).decode()


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
    for person in sorted(set(SP.PERSON_FOR_MODEL.values()) | {SP.HAULER}):
        for facing in ("S", "N", "W", "E"):
            path = SP.PEOPLE / f"{person}-{facing}-0.png"
            if path.exists():
                art[f"person:{person}:{facing}"] = data_uri(path)
    # Vehicles. Drawn under a moving agent, so a delivery reads as a cart on the
    # road rather than a person who happens to be walking quickly. Through
    # `sprites.vehicle_sprite` like everything else, so the 3D set can be
    # swapped in by dropping files into `vehicles-3d/`.
    # THE HAND-DRAWN SVGs, NOT `sprites.vehicle_sprite`. That helper prefers the
    # Blender renders in `vehicles-3d/`, which are 192x96 against a 32-pixel
    # person -- six times too wide, and exactly the "brown mass at map scale"
    # PHASE6 §4 recorded when it dropped Meshy from the 2D map. The SVGs are
    # 64x64 flat top-down shapes: less impressive alone, legible at 35 pixels.
    for name in D.VEHICLES:
        if name == "On Foot":
            continue
        path = SP.GENERATED / "vehicles" / f"{_slug(name)}.svg"
        if path.exists():
            art[f"vehicle:{_slug(name)}"] = data_uri(path)
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
            "id": biz.id,
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
            "id": agent.id,
            "name": agent.name,
            "person": rng.choice(list(SP.PERSON_FOR_MODEL.values())),
            # Facing the viewer mostly, so faces are visible; a few turned so
            # a standing crowd does not look like a chorus line.
            "facing": rng.choice(("S", "S", "S", "S", "W", "E", "N")),
            "owner": agent.id,
        })
    # Every panel the page can open, assembled once. See `convoy/inspect`.
    return {"buildings": buildings, "people": people, "flags": flags,
            "cards": I.cards(world), "boards": I.boards(world, [])}


# ---------------------------------------------------------------------------
# A REAL RUN
# ---------------------------------------------------------------------------
#
# Ported from `render_world.py`, which is now deleted. That file could read a run
# and this one could draw a world, and neither could do both -- so the run you
# wanted to watch was only ever available in the old card layout. The reading is
# ~200 lines and the drawing is ~800, so the reading moved.

def newest_run() -> Path:
    runs = [d for d in RUN_DIR.iterdir() if (d / "events.jsonl").exists()]
    if not runs:
        raise SystemExit(f"no runs with an events.jsonl under {RUN_DIR}")
    return max(runs, key=lambda d: d.stat().st_mtime)


def decode(node):
    """Checkpoints encode dicts as {"__dict__": [[k, v], ...]}. Unwrap enough
    to read values out without importing the whole state model."""
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


# The model titles its own reasoning. Every entry in this run opens with a bold
# header -- "**Planning refinery deliveries**", "**Evaluating transport
# options**" -- which is a two-or-three word summary written by the only party
# that knows what it was thinking. Cheaper and truer than anything we could
# summarise from the actions afterwards.
_GIST = re.compile(r"^\s*\*\*(.+?)\*\*")

# When there is no header, the first action is the honest fallback: it says what
# the agent DID, which is at least a fact, rather than guessing at intent.
_GIST_FOR_ACTION = {
    "travel_to": "on the road", "wait": "thinking", "start_shift": "starting work",
    "end_shift": "knocking off", "apply_for_job": "job hunting",
    "start_business": "opening up", "buy_vehicle": "buying a cart",
    "accept_courier_job": "taking a job", "collect_consignment": "loading up",
    "deliver_consignment": "delivering", "post_delivery_job": "hiring a courier",
    "hire_escort": "hiring guards", "post_escort_job": "seeking guards",
    "accept_escort_job": "guarding", "buy_meal": "eating",
    "sell_to_business": "selling", "buy_from_business": "buying",
    "buy_land": "buying land", "post_world_chat": "talking",
}


def _gist(text: str, did: str) -> str:
    """Three words for a bubble over someone's head."""
    m = _GIST.match(text or "")
    if m:
        words = m.group(1).strip().split()
        return " ".join(words[:3])
    first = (did or "").split(",")[0].strip().split(" ")[0]
    return _GIST_FOR_ACTION.get(first, first.replace("_", " ") or "thinking")


# WHAT IS WORTH A LINE IN THE TICKER.
#
# Deliberately short. A feed that reports everything reports nothing -- a job
# taken, a meal eaten and a five-unit parcel delivered are the texture of the
# day, not events, and a reader who scrolls past forty of them stops reading the
# one that mattered. So: violence, real money, and anything that changes who
# owns what.
HEADLINE_DELIVERY_VALUE = 100.0


def _headlines(events: list[dict], names: dict[str, str]) -> list[dict]:
    from convoy import data as _D

    out: list[dict] = []
    def who(a): return names.get(a, a or "someone")

    for e in events:
        t, d = e["type"], e.get("detail") or {}
        hour, actor = round(e["sim_time"] / 3600.0, 2), e.get("actor")
        if t == "robbed":
            out.append({"h": hour, "kind": "robbed", "who": actor,
                        "text": f"{who(actor)} robbed on {d.get('segment')} "
                                f"-- {d.get('value_lost', 0):.0f}d taken"})
        elif t == "business_founded":
            out.append({"h": hour, "kind": "founded", "who": actor,
                        "text": f"{who(actor)} opened a {d.get('business_type')}"})
        elif t == "vehicle_purchased":
            out.append({"h": hour, "kind": "bought", "who": actor,
                        "text": f"{who(actor)} bought a {d.get('vehicle_type')}"})
        elif t in ("buy_land", "land_bought", "property_purchased"):
            out.append({"h": hour, "kind": "bought", "who": actor,
                        "text": f"{who(actor)} bought land"})
        elif t == "consignment_delivered":
            item, qty = d.get("item"), d.get("qty") or 0
            try:
                value = _D.base_price(item) * qty
            except KeyError:
                value = 0.0
            if value >= HEADLINE_DELIVERY_VALUE:
                out.append({"h": hour, "kind": "delivered", "who": actor,
                            "text": f"{who(actor)} delivered {qty}x {item} "
                                    f"-- {value:.0f}d"})
        elif t in ("business_bankrupt", "starved_to_death", "agent_died"):
            out.append({"h": hour, "kind": "bad", "who": actor,
                        "text": f"{who(actor)} "
                                + ("went bankrupt" if t == "business_bankrupt"
                                   else "died")})
    out.sort(key=lambda r: r["h"])
    return out


def dedupe(track: list) -> list:
    """Order the samples, then drop consecutive ones that say the same thing.

    THE SORT IS WHY ANYTHING MOVES. A travel decision emits several events at
    one timestamp -- the action, the travel, the diary -- and each appends a
    plain "standing at X" row. So a departure row, the only kind carrying a
    DESTINATION, could be followed by a same-second row without one. `positionAt`
    binary-searches for the last row at or before the hour, landed on that
    trailing row every time, and took the "not moving" branch.
    
    The effect was total: measured on the 2026-08-21 run, 3,160 samples across
    16 simulated hours produced ZERO frames in which any agent was moving.
    Every replay ever rendered teleported its agents, while PHASE6 recorded that
    they interpolated along the road. Nobody had looked.

    Sorting is stable and keyed on "carries a destination", so at equal times a
    departure sorts last and is what the search finds.

    The diary fires hourly per agent, so one standing still for 21 hours emits
    21 identical rows and a 20-agent 84-hour run carries thousands of them
    straight into the page.
    """
    track = sorted(track, key=lambda r: (r[0], 1 if r[2] else 0))
    out: list = []
    for row in track:
        if out and out[-1][1] == row[1] and out[-1][2] == row[2]:
            continue
        out.append(row)
    return out


def replay(run: Path, places: dict[str, L.Place]) -> dict:
    """Read a run into everything the page needs to play it back."""
    with (run / "events.jsonl").open(encoding="utf-8") as fh:
        events = [json.loads(line) for line in fh if line.strip()]
    if not events:
        raise SystemExit(f"{run}/events.jsonl is empty")

    known = set(places)
    end_hour = max(e["sim_time"] for e in events) / 3600.0

    names: dict[str, str] = {}
    models: dict[str, str] = {}
    cp_path = run / "checkpoint.json"
    raw_cp = json.loads(cp_path.read_text(encoding="utf-8")) if cp_path.exists() else {}
    for entry in walk_dict(raw_cp.get("agents")):
        if entry.get("id"):
            names[entry["id"]] = entry.get("name", entry["id"])
            models[entry["id"]] = entry.get("model", "")

    agents: dict[str, dict] = {}
    robberies: list[dict] = []
    tracks: dict[str, list] = defaultdict(list)
    decisions: dict[str, list] = defaultdict(list)
    founded: dict[str, dict] = {}
    foreign: set[str] = set()

    for e in events:
        hour = e["sim_time"] / 3600.0
        actor, etype = e.get("actor"), e["type"]
        detail, loc = e.get("detail", {}), e.get("location")
        if loc and loc not in known:
            foreign.add(loc)

        if actor and actor.startswith("A"):
            a = agents.setdefault(actor, {
                "id": actor, "name": names.get(actor, actor),
                "model": models.get(actor, ""), "died": None,
            })
            if loc in known:
                tracks[actor].append([round(hour, 3), loc, None])
            if etype == "travel":
                dest = detail.get("destination")
                secs = float(detail.get("seconds") or 0)
                if dest in known:
                    # Departure AND arrival, so an agent is drawn moving along
                    # the road rather than teleporting between two places.
                    tracks[actor].append(
                        [round(hour, 3), loc if loc in known else dest, dest])
                    tracks[actor].append([round(hour + secs / 3600.0, 3), dest, None])
            # CARRYING SOMEBODY ELSE'S GOODS, as opposed to merely walking.
            # The page drew a hooded cloak for anyone in transit, which
            # conflated "travelling" with "hauling" and made every journey look
            # like a smuggling run. A courier is someone between COLLECTING a
            # consignment and DELIVERING it, and that is exactly what the log
            # records.
            if etype in ("consignment_collected", "courier_claimed"):
                legs = a.setdefault("carrying", [])
                if not legs or legs[-1][1] is not None:
                    legs.append([round(hour, 3), None])
            if etype in ("consignment_delivered", "consignment_cancelled"):
                legs = a.setdefault("carrying", [])
                if legs and legs[-1][1] is None:
                    legs[-1][1] = round(hour, 3)
            # SHIFTS, so a worker can be drawn AT the bench rather than at the
            # centre of the settlement. `job_started` carries the employer and
            # how long the shift runs; nothing logs the end, so the window is
            # start + hours, which is what the engine scheduled anyway.
            if etype == "job_started":
                hrs = float(detail.get("hours") or 4.0)
                a.setdefault("shifts", []).append(
                    [round(hour, 3), round(hour + hrs, 3), detail.get("subject")
                     or e.get("subject")]
                )
            if etype == "vehicle_purchased":
                # WHAT AN AGENT IS RIDING IS RECONSTRUCTED, NOT RECORDED.
                # `mount` emits no event, so the log cannot say what anybody is
                # actually sitting on. What it does say is what they BOUGHT and
                # when, so a moving agent is drawn with the best cart it owned
                # by that hour. An approximation, and the honest one available.
                a.setdefault("bought", []).append(
                    [round(hour, 3), detail.get("vehicle_type")]
                )
            if etype == "robbed":
                robberies.append({
                    "hour": round(hour, 3), "victim": actor,
                    "segment": detail.get("segment"),
                    "share": detail.get("fraction"),
                    "value": detail.get("value_lost"),
                    "vehicle": detail.get("vehicle"),
                    "escorts": detail.get("escorts"),
                    "risk": detail.get("risk"),
                })
            if etype in ("agent_died", "starved_to_death"):
                a["died"] = round(hour, 2)
            if etype == "llm_reasoning":
                decisions[actor].append({
                    "h": round(hour, 2),
                    "woken": detail.get("woken_because", ""),
                    "did": detail.get("did", ""),
                    "why": detail.get("text", ""),
                    "gist": _gist(detail.get("text", ""), detail.get("did", "")),
                })

        if etype == "business_founded" and e.get("subject"):
            founded[e["subject"]] = {
                "id": e["subject"], "type": detail.get("business_type", "?"),
                "place": loc, "owner": actor, "from": round(hour, 2),
                "to": None, "name": detail.get("name", ""),
            }
        elif etype in ("business_closed", "business_bankrupt") and e.get("subject"):
            if e["subject"] in founded:
                founded[e["subject"]]["to"] = round(hour, 2)

    for track in tracks.values():
        track.sort(key=lambda row: row[0])

    # A RUN BELONGS TO THE MAP IT WAS RECORDED ON. Said out loud rather than
    # drawn wrong: a run from a bigger valley names ground this world does not
    # have, and its agents would silently vanish at those places.
    if foreign:
        print(f"  !! {run.name} names {len(foreign)} places this world does not "
              f"have ({', '.join(sorted(foreign)[:3])}...). It was recorded on a "
              f"different map; positions there cannot be drawn.")

    # The state's branches exist from hour zero; everything else is founded.
    world = CP.load(cp_path) if cp_path.exists() else None
    buildings: list[dict] = []
    used: dict[str, int] = {}
    government = [
        {"id": b.id, "type": b.type, "place": b.location, "owner": None,
         "from": 0.0, "to": None, "name": b.name}
        for b in (world.businesses.values() if world else [])
        if b.owner == "Government"
    ]
    for spec in government + sorted(founded.values(), key=lambda b: b["from"]):
        place = places.get(spec["place"])
        if place is None:
            continue
        i = used.get(spec["place"], 0)
        if i >= len(place.slots):
            # The land model guarantees a slot per business the ground can hold;
            # more than that means the run outgrew this map, not a drawing bug.
            print(f"  !! {spec['place']} has no slot left for {spec['type']}")
            continue
        used[spec["place"]] = i + 1
        slot = place.slots[i]
        buildings.append({**spec, "x": slot.x, "y": slot.y,
                          "sprite": _slug(spec["type"]), "scale": 1.0,
                          "plots": 0})

    flags = []
    if world:
        for plot in world.plots.values():
            place = places.get(plot.location)
            if place is None or not place.parcels:
                continue
            idx = len([f for f in flags if f["place"] == plot.location])
            if idx >= len(place.parcels):
                continue
            parcel = place.parcels[idx]
            flags.append({"x": parcel.x, "y": parcel.y, "place": plot.location,
                          "owner": plot.owner or "unsold", "home": plot.developed})

    return {
        "mode": "replay",
        "run": run.name,
        "end_hour": round(end_hour, 2),
        # The cards and the flags come from the CHECKPOINT, which is the end of
        # the run -- not the slider's hour. Labelled as such in the popup rather
        # than quietly implying a business held that stock all along.
        "checkpoint_hour": round(world.sim_hour, 2) if world else None,
        "buildings": buildings,
        "flags": flags,
        "people": [],
        "agents": sorted(agents.values(), key=lambda a: a["id"]),
        "tracks": {k: dedupe(v) for k, v in tracks.items()},
        "decisions": decisions,
        # Every robbery, with the hour and the road it happened on. The page
        # stages an interception from these -- see AMBUSH in the template.
        "robberies": robberies,
        # The things worth interrupting somebody to mention. See `_headlines`.
        "headlines": _headlines(events, names),
        "cards": I.cards(world) if world else {},
        # The boards read the EVENT LOG, not the checkpoint, which is why the
        # convoy history survives at all: a delivered consignment is deleted
        # from the world and a robbed one never existed there. `EventLog.replay`
        # rather than the raw dicts above, because it is the one loader that
        # already tolerates a torn final line from a killed run.
        "boards": I.boards(world, _events_for_boards(run)) if world else {},
    }


def _events_for_boards(run: Path) -> list:
    from convoy.events import EventLog

    log = EventLog(None, echo_min=99)
    log.replay(run / "events.jsonl")
    return log.events


def build_payload(run: Path | None = None) -> dict:
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
        # `wx`/`wy` turn these into screen pixels; the replay interpolates an
        # agent between two of them to draw it moving along the road.
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
        **(replay(run, places) if run else
           {"mode": "snapshot", **starting_world(places)}),
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--run", nargs="?", const="latest", default=None,
                    help="a run directory, or 'latest'; omit for hour zero")
    args = ap.parse_args()

    run = None
    if args.run:
        run = newest_run() if args.run == "latest" else Path(args.run)
        if not (run / "events.jsonl").exists():
            raise SystemExit(f"no events.jsonl in {run}")

    payload = build_payload(run)
    art = collect_assets()
    html = (TEMPLATE
            .replace("__PROPS__", json.dumps(
                {k: len(v) for k, v in SP.PROP_SPRITES.items()}))
            .replace("__PEOPLE__", json.dumps(SP.PERSON_FOR_MODEL))
            .replace("__DEFAULT_PERSON__", json.dumps(
                next(iter(SP.PERSON_FOR_MODEL.values()))))
            .replace("__HAULER__", json.dumps(SP.HAULER))
            .replace("__DATA__", json.dumps(payload))
            .replace("__ART__", json.dumps(art)))
    OUT.write_text(html, encoding="utf-8")
    b = payload["bounds"]
    if payload["mode"] == "replay":
        print(f"wrote {OUT.name} -- replaying {payload['run']} to hour "
              f"{payload['end_hour']}, {len(payload['agents'])} agents, "
              f"{len(payload['buildings'])} buildings, "
              f"{sum(len(d) for d in payload['decisions'].values())} decisions "
              f"({OUT.stat().st_size / 1024:,.0f} KB)")
        return 0
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
  /* THE TICKER. Bottom-right, out of the way of the boards, and only the
     things worth interrupting somebody for. Each line jumps to its moment. */
  #ticker{position:fixed;right:12px;bottom:64px;z-index:5;width:284px;
          max-height:210px;overflow:hidden;pointer-events:none}
  #ticker-rows{display:flex;flex-direction:column;justify-content:flex-end;
               gap:3px;pointer-events:auto}
  .tick{background:#12160fe8;border:1px solid #3a4030;border-left-width:3px;
        border-radius:4px;padding:4px 8px;font-size:11px;color:#c9d6a8;
        cursor:pointer;line-height:1.35}
  .tick:hover{background:#1e2616;color:#fffdf7}
  .tick b{color:#8d9c72;font-weight:400;margin-right:5px}
  .tick.robbed{border-left-color:#e0603d}
  .tick.bad{border-left-color:#e0603d}
  .tick.founded{border-left-color:#7aa9d1}
  .tick.bought{border-left-color:#c58fd1}
  .tick.delivered{border-left-color:#9dd17a}

  /* A thought, over the head of whoever is having it. */
  .bubble-canvas{}

  #hud{position:fixed;left:12px;top:166px;background:#12160fdd;padding:9px 12px;
       border:1px solid #3a4030;border-radius:5px;pointer-events:none;z-index:2}

  /* THE BOARDS. Three stacked buttons top-left, and a dark panel behind them.
     Deliberately NOT the white card the map uses: a card is what one person in
     the valley could tell you if you walked up and asked, and these are things
     nobody in the world can see -- a leaderboard, a price feed, a shipping
     ledger. Different source of knowledge, different surface. */
  /* Wide enough that no label wraps: a wrapped button grows the stack and
     shoves the panel down onto the button below it. */
  #boards-nav{position:fixed;left:12px;top:12px;z-index:7;display:flex;
              flex-direction:column;gap:3px;width:158px}
  #board code{background:#23291a;padding:0 4px;border-radius:3px;color:#c9d6a8}
  #boards-nav button{background:#12160fdd;color:#c9d6a8;border:1px solid #3a4030;
                     border-radius:5px;padding:6px 9px;font:inherit;cursor:pointer;
                     text-align:left;letter-spacing:.04em;white-space:nowrap}
  #boards-nav button:hover{background:#1e2616;color:#e8e4d8}
  #boards-nav button.on{background:#44562f;color:#fffdf7;border-color:#6d8449}
  #board{position:fixed;left:12px;top:166px;z-index:6;display:none;
         width:min(760px,calc(100vw - 24px));max-height:calc(100vh - 162px);
         overflow:auto;background:#12160ff2;border:1px solid #46502f;
         border-radius:7px;padding:13px 15px 15px;
         box-shadow:0 8px 30px #000a}
  #board.open{display:block}
  #board h2{margin:0 0 2px;font-size:14px;color:#e8e4d8;letter-spacing:.04em}
  #board .sub{color:#8d9c72;font-size:11px;margin-bottom:11px}
  #board table{border-collapse:collapse;width:100%;font-size:11.5px}
  /* Sticky, because twenty agents scroll and a column of bare numbers with the
     headings gone is unreadable. */
  #board th{text-align:left;color:#8d9c72;font-weight:400;letter-spacing:.07em;
            text-transform:uppercase;font-size:9.5px;padding:6px 8px 4px 0;
            border-bottom:1px solid #3a4030;white-space:nowrap;
            position:sticky;top:0;background:#12160f;z-index:1}
  #board td{padding:3px 8px 3px 0;border-bottom:1px solid #23291a;
            vertical-align:top}
  #board td.n,#board th.n{text-align:right}
  #board tr:hover td{background:#1c2315}
  #board tr.jump{cursor:pointer}
  #board tr.jump:hover td{background:#2c3720}
  #board .who{color:#e8e4d8}
  #board .dim{color:#7c8a63}
  #board .up{color:#9dd17a}
  #board .down{color:#d99a72}
  #board .bad{color:#e08a6a}
  /* Carts and homes are tagged rather than listed as plain text, so a glance
     down the column separates "runs two businesses" from "owns two donkeys". */
  #board .cart{display:inline-block;background:#2a2f1d;border:1px solid #46502f;
               border-radius:3px;padding:0 5px;color:#c58fd1}
  #board .home{display:inline-block;background:#2a2f1d;border:1px solid #46502f;
               border-radius:3px;padding:0 5px;color:#d1937a}
  #board .good{color:#9dd17a}
  /* The asset breakdown, as a bar rather than five more numbers. Where the
     money IS matters as much as how much: 3,000 in cash and 3,000 sunk in a
     mine that cannot make payroll rank identically and are not alike. */
  #board .bar{display:flex;height:7px;border-radius:2px;overflow:hidden;
              background:#23291a;min-width:96px;max-width:210px;margin-bottom:3px}
  #board .bar i{display:block}
  #board .key{display:flex;gap:11px;margin:0 0 10px;font-size:10px;
              color:#8d9c72;flex-wrap:wrap}
  #board .key i{display:inline-block;width:8px;height:8px;border-radius:2px;
                margin-right:4px;vertical-align:-1px}
  #board .empty{color:#7c8a63;font-style:italic;padding:10px 0}
  #hud b{color:#c9d6a8}
  #keys{position:fixed;right:12px;top:12px;background:#12160fdd;padding:9px 12px;
        border:1px solid #3a4030;border-radius:5px;z-index:2;text-align:right}
  #keys span{color:#8d9c72}
  canvas.pointing{cursor:pointer}

  /* THE POPUP. A white card floating over the map, anchored above whatever was
     clicked, rather than a panel down the side. A side panel is a separate
     place to look: you click a farm, your eye travels to the edge of the screen,
     and the farm you were asking about is no longer where you are looking. A
     card above the building keeps the question and the answer in one glance --
     and white on a green valley needs no border to be found. */
  #popup{position:fixed;z-index:6;width:290px;max-height:62vh;overflow-y:auto;
         background:#fffdf7;color:#20241a;border-radius:9px;
         box-shadow:0 6px 22px #0009, 0 0 0 2px #2b2416;
         padding:12px 14px 13px;display:none;
         font:12px/1.45 ui-monospace,Menlo,monospace}
  #popup.open{display:block}
  /* The tail. Small, and the reason the card reads as belonging to the thing
     under it rather than merely being near it. */
  #popup::after{content:"";position:absolute;left:var(--tail,50%);bottom:-9px;
                margin-left:-8px;border:8px solid transparent;
                border-top-color:#2b2416;border-bottom:0}
  #popup.below::after{bottom:auto;top:-9px;
                      border-top:0;border-bottom:8px solid #2b2416}
  #popup h2{margin:0 0 1px;font-size:14px;color:#12160f}
  #popup .sub{color:#6d7a55;margin-bottom:9px;font-size:11px}
  #popup h3{margin:12px 0 4px;font-size:10px;letter-spacing:.09em;
            text-transform:uppercase;color:#5d6b3f;
            border-bottom:1px solid #ddd8c4;padding-bottom:2px}
  #popup .row{display:flex;justify-content:space-between;gap:9px;padding:1px 0}
  #popup .row span:last-child{color:#12160f;text-align:right}
  #popup .none{color:#8d9779;font-style:italic}
  #popup a.track{color:#3f6ea8;text-decoration:none;border-bottom:1px dotted #3f6ea8}
  #popup a.track:hover{color:#20241a;border-color:#20241a}
  #popup .tag{display:inline-block;background:#eee9d6;border:1px solid #cfc9b0;
              border-radius:3px;padding:0 5px;margin:2px 3px 0 0;font-size:11px}
  #close{position:absolute;right:7px;top:5px;cursor:pointer;color:#8d9779;
         font-size:17px;line-height:1;background:none;border:0;padding:2px 4px}
  #close:hover{color:#20241a}
  .chat textarea{width:100%;box-sizing:border-box;background:#fff;
                 color:#20241a;border:1px solid #cfc9b0;border-radius:4px;
                 padding:6px;font:inherit;resize:vertical;min-height:46px}
  .chat .btns{display:flex;gap:6px;margin-top:6px}
  .chat button{flex:1;background:#2c3720;color:#f2efe2;border:0;
               border-radius:4px;padding:6px;font:inherit;cursor:pointer}
  .chat button:hover{background:#44562f}
  .chat button:disabled{opacity:.45;cursor:not-allowed}
  #reply{margin-top:8px;padding:7px;background:#f1eede;border-radius:4px;
         border:1px solid #ddd8c4;white-space:pre-wrap;display:none}
  #reply.show{display:block}

  /* Only in replay mode; `snapshot` has no time to move through. */
  #clock{position:fixed;left:50%;transform:translateX(-50%);bottom:14px;z-index:4;
         background:#12160fe8;border:1px solid #46502f;border-radius:6px;
         padding:8px 14px;display:none;align-items:center;gap:11px}
  #clock.on{display:flex}
  #playbtn{background:#2c3720;color:#e8e4d8;border:1px solid #46502f;
           border-radius:4px;width:28px;height:24px;cursor:pointer;
           font:13px/1 ui-monospace,monospace;flex:none}
  #playbtn:hover{background:#44562f}
  #clock input[type=range]{width:min(46vw,460px);accent-color:#c9d6a8}
  #clocktext{color:#f2e9c9;min-width:120px}
</style></head><body>
<canvas id="c"></canvas>
<div id="boards-nav">
  <button data-board="leaderboard">Leaderboard</button>
  <button data-board="convoys">Convoy schedule</button>
  <button data-board="commodities">Commodity prices</button>
  <button data-board="advice">Advice report</button>
</div>
<div id="board"></div>
<div id="ticker"><div id="ticker-rows"></div></div>
<div id="hud"></div>
<div id="clock"><button id="playbtn" title="play / pause">&#9654;</button>
  <input type="range" id="slider" min="0" step="0.25">
  <span id="clocktext"></span></div>
<div id="popup"><button id="close" title="close">&times;</button>
  <div id="popup-body"></div></div>
<div id="keys"><span>click</span> a building or a person &nbsp; <span>drag</span> pan
  &nbsp; <span>wheel</span> zoom &nbsp; <span>0</span> whole valley</div>
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
const REPLAY = DATA.mode === "replay";
const HAULER = __HAULER__;

/* Place name -> world position, so a replayed agent can be put BETWEEN two of
   them rather than snapped to whichever it left. */
const PLACE = {};
for (const p of DATA.places) PLACE[p.name] = p;

let HOUR = REPLAY ? DATA.end_hour : 0;
let ROAD_PATTERN = null, STREET_PATTERN = null, GRASS_PATTERN = null;

/* ------------------------------------------------------------ replay time */

function livingAt(a, h){ return a.died === null || h < a.died; }
function bizAt(b, h){ return b.from <= h && (b.to === null || h < b.to); }

/* Where an agent is at hour h. Binary search for the last sample at or before
   h, then interpolate if that sample was a departure. */
function positionAt(id, h){
  const track = DATA.tracks[id];
  if (!track || !track.length) return null;
  let lo = 0, hi = track.length - 1, at = -1;
  while (lo <= hi){
    const mid = (lo + hi) >> 1;
    if (track[mid][0] <= h){ at = mid; lo = mid + 1; } else hi = mid - 1;
  }
  /* Before the first sample an agent already EXISTS and is standing where it
     started. Returning null here hid every agent at hour 0. */
  if (at < 0){
    const start = PLACE[track[0][1]];
    return start ? {x: start.x, y: start.y, moving: false} : null;
  }
  const [t0, from, dest] = track[at];
  const here = PLACE[from];
  if (!here) return null;
  if (dest && track[at + 1]){
    const [t1, to] = track[at + 1];
    const there = PLACE[to];
    if (there && t1 > t0){
      const k = Math.max(0, Math.min(1, (h - t0) / (t1 - t0)));
      return {x: here.x + (there.x - here.x) * k,
              y: here.y + (there.y - here.y) * k,
              moving: true, dx: there.x - here.x, dy: there.y - here.y};
    }
  }
  return {x: here.x, y: here.y, moving: false};
}

/* Which way a walking figure faces. The map lies the valley down, so world +y
   is screen RIGHT and world +x is screen DOWN -- the axes swap. */
/* Fastest cart an agent had bought by this hour. Ranked by the same order the
   economy prices them in, so "best" means the one it would actually harness. */
const VEHICLE_RANK = ["Camel", "Horse", "Donkey Cart", "2-Horse Chariot", "4-Horse Chariot"];
/* Mirrors `_slug` in preview_world.py -- the two must agree or the key misses. */
const vslug = (n) => String(n).toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "");
function bestVehicleAt(a, hour){
  const bought = a.bought || [];
  let best = null, rank = -1;
  for (const [h, type] of bought){
    if (h > hour) continue;
    const r = VEHICLE_RANK.indexOf(type);
    if (r > rank){ rank = r; best = type; }
  }
  return best;
}

/* Between collecting a consignment and delivering it. Drawn as a PACK on the
   agent's back rather than as a different person: a courier is the same
   villager doing a job, and swapping their whole sprite for a hooded figure
   said "someone else" when it meant "carrying something". */
function carryingAt(a, hour){
  for (const [from, to] of (a.carrying || []))
    if (hour >= from && (to === null || hour <= to)) return true;
  return false;
}

/* ---------------------------------------------------------------------------
   THE AMBUSH.

   HONESTY FIRST: the simulation has no bandits. A robbery is ONE event recorded
   on arrival -- an hour, a road segment, the share of the load taken, the cart,
   the guard count. There is no bandit position, no approach, no moment of
   interception, because none of that was ever computed.

   So this is a DRAMATISATION anchored to facts, not a replay of one. What is
   real: that it happened, when, on which road, to whom, with what cart and how
   many guards, and how much was lost. What is invented: the figures walking in.
   They are drawn converging on the victim over the seconds before the recorded
   hour, from off the road -- which is at least the right story, since
   `concealment` is the segment's measure of how well an ambusher hides.

   They wear the hood the couriers just stopped wearing. It was the wrong signal
   for someone doing a job and is the right one for someone lying in wait.
--------------------------------------------------------------------------- */
const AMBUSH_LEAD_HOURS = 0.03;      // how long before the event they close in
const AMBUSH_HOLD_HOURS = 0.02;      // and how long they linger after

function ambushesAt(hour){
  const out = [];
  for (const r of (DATA.robberies || [])){
    const from = r.hour - AMBUSH_LEAD_HOURS, to = r.hour + AMBUSH_HOLD_HOURS;
    if (hour < from || hour > to) continue;
    const pos = positionAt(r.victim, Math.min(hour, r.hour));
    if (!pos) continue;
    // 1 at first sight, 0 once they are on top of the cart.
    const k = Math.max(0, Math.min(1, (r.hour - hour) / AMBUSH_LEAD_HOURS));
    // EVERYTHING HERE IS IN PIXELS. `wx`/`wy` convert metres to screen AND swap
    // the axes, so a heading computed in world coordinates points somewhere
    // else entirely once drawn -- which is how the first version put its
    // raiders several valleys away and drew nothing at all.
    const ax = wx(pos), ay = wy(pos);
    const hx = (pos.dy || 0), hy = (pos.dx || 1);   // heading, already swapped
    const len = Math.hypot(hx, hy) || 1;
    const px = -hy / len, py = hx / len;            // perpendicular to the road
    const reach = 52;
    const raiders = [];
    for (let i = 0; i < 3; i++){
      const side = i === 1 ? -1 : 1;
      const spread = (i - 1) * 14;
      raiders.push({
        x: ax + px * reach * k * side + spread * (hx / len),
        y: ay + py * reach * k * side + spread * (hy / len),
        facing: Math.abs(px) > Math.abs(py) ? (px * side > 0 ? "W" : "E")
                                            : (py * side > 0 ? "N" : "S"),
      });
    }
    out.push({raiders, victim: r, closing: k, at: {x: ax, y: ay}});
  }
  return out;
}

/* ---------------------------------------------------------------------------
   WHERE THE TWENTY OF THEM ACTUALLY ARE.

   `positionAt` returns the CENTRE of a place, so every agent standing in Town
   was drawn on the same pixel -- twenty people rendered as one. You could not
   see the population because it was stacked.

   Two fixes, both deterministic so nobody jitters between frames:

   AT WORK, an agent stands on one of the four plots of the business employing
   it, owner or not. That is the question "who works here" answered by looking
   rather than by opening a card.

   OTHERWISE it takes a fixed seat around the centre of wherever it is, spread
   on a ring so a crowded market reads as a crowd.
--------------------------------------------------------------------------- */
const BUILDING_BY_ID = {};
for (const b of (DATA.buildings || [])) BUILDING_BY_ID[b.id] = b;

/* Small stable hash of an id -> 0..1. Math.imul, not `*`: an id hashed with
   plain multiplication overflows 2^53 and collapses its range, which is how
   every bush in the valley ended up the same shade (PHASE6 §7). */
function hash01(str){
  let h = 2166136261;
  for (let i = 0; i < str.length; i++){
    h ^= str.charCodeAt(i);
    h = Math.imul(h, 16777619);
  }
  return ((h >>> 0) % 10000) / 10000;
}

function shiftAt(a, hour){
  for (const [from, to, biz] of (a.shifts || []))
    if (hour >= from && hour <= to) return biz;
  return null;
}

/* A worker hops now and then. Idle people stand still, so the hop IS the
   signal -- "this one is earning" without a label or a colour. Phase is per
   agent so twenty workers do not bounce in lockstep like a chorus line. */
const HOP_PERIOD_MS = 5000, HOP_MS = 420, HOP_HEIGHT = 5;
function hopOffset(id){
  const t = (performance.now() + hash01(id) * HOP_PERIOD_MS) % HOP_PERIOD_MS;
  if (t > HOP_MS) return 0;
  return -Math.sin((t / HOP_MS) * Math.PI) * HOP_HEIGHT;
}

/* Screen position for one agent: on a plot of its employer if it is working,
   otherwise a fixed seat near where it stands. Returns PIXELS, because the
   offsets are pixel-sized and `wx`/`wy` swap the axes on the way. */
function seatFor(id, pos, biz){
  const b = biz && BUILDING_BY_ID[biz];
  const r = hash01(id);
  if (b){
    // The building sits on the shared corner of its four plots, so the four
    // diagonals ARE the four boxes. One agent per corner, then a small ring
    // beyond that if a business somehow seats more than four.
    const step = (DATA.parcel_m || 32) * DATA.ppm * 0.5;
    const i = Math.floor(r * 4);
    const dx = (i === 0 || i === 3) ? -step : step;
    const dy = (i < 2) ? -step : step;
    const extra = r * 6 - 3;
    return {sx: wx(b) + dx + extra, sy: wy(b) + dy + extra};
  }
  if (pos.moving) return {sx: wx(pos), sy: wy(pos)};
  // A fixed seat on a ring, so a market square reads as twenty people rather
  // than as one person drawn twenty times.
  const ang = r * Math.PI * 2, rad = 22 + r * 30;
  return {sx: wx(pos) + Math.cos(ang) * rad, sy: wy(pos) + Math.sin(ang) * rad * 0.6};
}

/* ---------------------------------------------------------------------------
   THOUGHT BUBBLES, THE TICKER, AND WHO IS WORTH LOOKING AT
--------------------------------------------------------------------------- */

/* A decision hangs over an agent's head for a while after it is made. Long
   enough to read at a glance, short enough that a paused map is not a wall of
   text. `gist` is the model's own bold header -- it titles its reasoning, so
   the summary is written by the only party that knew what it was thinking. */
const BUBBLE_HOURS = 0.45;
function thoughtAt(id, hour){
  const list = DATA.decisions[id];
  if (!list) return null;
  let best = null;
  for (const d of list){
    if (d.h > hour) break;
    if (hour - d.h <= BUBBLE_HOURS) best = d;
  }
  return best;
}

/* Green for whoever is winning, yellow for whoever is losing, blue for whoever
   you chose to follow. Three colours is the limit -- a map where everyone is
   highlighted has highlighted nobody. */
const RANK_TOP = "#9dd17a", RANK_BOTTOM = "#e8d06a", RANK_TRACKED = "#6fa8dc";
function rankColour(id){
  if (id === FOLLOW) return RANK_TRACKED;
  const lb = (BOARDS.leaderboard || []);
  if (!lb.length) return null;
  if (lb[0] && lb[0].id === id) return RANK_TOP;
  const last = lb[lb.length - 1];
  if (last && last.id === id) return RANK_BOTTOM;
  return null;
}

function facingOf(pos){
  if (!pos || !pos.moving) return "S";
  return Math.abs(pos.dy) > Math.abs(pos.dx)
       ? (pos.dy > 0 ? "E" : "W")
       : (pos.dx > 0 ? "S" : "N");
}

/* The people on screen right now. In snapshot mode this is a fixed list; in
   replay it is recomputed per frame from the tracks. */
/* A business exists from the hour it was founded to the hour it closed. In
   snapshot mode every one of them is simply there. */
function visibleBuildings(){
  return REPLAY ? DATA.buildings.filter(b => bizAt(b, HOUR)) : DATA.buildings;
}

function peopleNow(){
  if (!REPLAY) return DATA.people;
  const out = [];
  for (const a of DATA.agents){
    if (!livingAt(a, HOUR)) continue;
    const pos = positionAt(a.id, HOUR);
    if (!pos) continue;
    const biz = pos.moving ? null : shiftAt(a, HOUR);
    const seat = seatFor(a.id, pos, biz);
    out.push({
      id: a.id, name: a.name, x: pos.x, y: pos.y,
      sx: seat.sx, sy: seat.sy,
      person: PERSON_FOR_MODEL[a.model] || DEFAULT_PERSON,
      facing: facingOf(pos), hauling: pos.moving,
      courier: carryingAt(a, HOUR),
      working: !!biz,
      vehicle: bestVehicleAt(a, HOUR),
    });
  }
  return out;
}
const PROP_COUNT = __PROPS__;
const PERSON_FOR_MODEL = __PEOPLE__, DEFAULT_PERSON = __DEFAULT_PERSON__;
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
/* ------------------------------------------------------------- the clock */

const clock = document.getElementById("clock");
const slider = document.getElementById("slider");
const clocktext = document.getElementById("clocktext");

/* PLAYBACK. The slider alone makes movement something you have to scrub for by
   hand, and an agent crossing the valley is the one thing on this map that only
   reads as motion if it actually moves. Pressing play walks the clock forward
   in real time at PLAY_HOURS_PER_SECOND, which is slow enough to follow a cart
   down a spur and fast enough that a 72-hour run is a couple of minutes. */
const PLAY_HOURS_PER_SECOND = 0.6;
const playbtn = document.getElementById("playbtn");
let playing = false, lastFrame = 0;

/* An agent the camera keeps in frame. Cleared the moment the viewer drags,
   because a camera that fights the hand is worse than one that never moved. */
let FOLLOW = null;
function followFrame(){
  if (!FOLLOW) return;
  const pos = positionAt(FOLLOW, HOUR);
  if (!pos) return;
  panx = -(pos.x - c.width / 2 / zoom);
  pany = -(pos.y - c.height / 2 / zoom) + 90 / zoom;
  clampPan();
}

/* Jump to a recorded moment and watch it happen. The board lists the hour of
   every robbery and delivery, and a row you cannot travel to is a row that
   makes you go looking with the slider. */
function goToMoment(hour, who, lead){
  showBoard(null);
  FOLLOW = who || null;
  zoom = 2.4;
  setHour(Math.max(0, hour - (lead === undefined ? AMBUSH_LEAD_HOURS : lead)));
  followFrame(); draw();
  setPlaying(true);
}

function setHour(h){
  HOUR = Math.max(0, Math.min(DATA.end_hour, h));
  slider.value = HOUR;
  if (SELECTED && SELECTED.kind === "building" && !bizAt(SELECTED.ref, HOUR)) closePanel();
  else if (SELECTED) openPanel(SELECTED);
  followFrame();
  draw();
  drawTicker();
}

function tick(ts){
  if (!playing) return;
  const dt = lastFrame ? (ts - lastFrame) / 1000 : 0;
  lastFrame = ts;
  if (HOUR >= DATA.end_hour) { setPlaying(false); return; }
  setHour(HOUR + dt * PLAY_HOURS_PER_SECOND);
  requestAnimationFrame(tick);
}

function setPlaying(on){
  playing = on;
  playbtn.innerHTML = on ? "&#10073;&#10073;" : "&#9654;";
  lastFrame = 0;
  // Restarting from the end replays from the beginning rather than sitting
  // still and looking broken.
  if (on && HOUR >= DATA.end_hour) HOUR = 0;
  if (on) requestAnimationFrame(tick);
}

if (REPLAY){
  clock.classList.add("on");
  slider.max = DATA.end_hour;
  slider.value = DATA.end_hour;
  playbtn.onclick = () => setPlaying(!playing);
  slider.oninput = () => {
    setPlaying(false);
    HOUR = parseFloat(slider.value);
    /* An open card describes a thing that may not exist at the new hour, and a
       card pointing at a building founded four hours from now is worse than no
       card. */
    if (SELECTED && SELECTED.kind === "building" &&
        !bizAt(SELECTED.ref, HOUR)) closePanel();
    else if (SELECTED) openPanel(SELECTED);
    draw();
  };
}

function updateClock(){
  if (!REPLAY) return;
  const live = DATA.agents.filter(a => livingAt(a, HOUR)).length;
  const built = visibleBuildings().length;
  clocktext.textContent =
    `hour ${HOUR.toFixed(1)} / ${DATA.end_hour} · ${live} alive · ${built} built`;
}

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
  for (const b of visibleBuildings())
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

/* A courier's pack. Drawn rather than shipped as art because it has to sit
   correctly on four facings of twenty-odd re-hued villagers, and compositing it
   here costs nothing and stays in register with whatever the person sprite is.
   Hidden when facing the viewer -- a pack is on your BACK, and drawing it over
   someone's chest is how you get a fanny pack. */
function pack(x, y, facing){
  if (facing === "S") return;
  const w = 7, h = 8;
  const dx = facing === "W" ? 4 : facing === "E" ? -4 : 0;
  g.fillStyle = "#6b4a2a";
  g.fillRect(Math.round(x - w / 2 + dx), Math.round(y - 22), w, h);
  g.fillStyle = "#8a6236";
  g.fillRect(Math.round(x - w / 2 + dx), Math.round(y - 22), w, 2);
}

/* Drawn on the canvas rather than as DOM, so it pans and zooms with the map and
   cannot drift out of register with the head it belongs to. Scaled INVERSELY to
   the zoom, because a thought should stay readable when you pull back to look at
   the whole valley -- the same reasoning as the info badges. */
function bubble(x, y, text){
  // FIXED SCREEN SIZE, like the badges. `Math.max(9, 11/zoom)` clamped the
  // wrong way: at 6x the floor won and the bubble was drawn 9 WORLD units tall,
  // which is 54 pixels -- one thought filling the viewport. Dividing by zoom
  // with no floor keeps it 11px on screen at every camera height.
  const fs = 11 / zoom;
  g.font = `${fs}px ui-monospace,Menlo,monospace`;
  const w = g.measureText(text).width + 10 / zoom;
  const h = fs + 7 / zoom, rx = x - w / 2, ry = y - h;
  g.fillStyle = "#fffdf7ee";
  g.strokeStyle = "#2b2416";
  g.lineWidth = 1.2 / zoom;
  if (g.roundRect){ g.beginPath(); g.roundRect(rx, ry, w, h, 4 / zoom); g.fill(); g.stroke(); }
  else { g.fillRect(rx, ry, w, h); g.strokeRect(rx, ry, w, h); }
  // The tail, so the thought belongs to a person rather than floating near one.
  g.beginPath();
  g.moveTo(x - 3 / zoom, ry + h); g.lineTo(x, ry + h + 4 / zoom); g.lineTo(x + 3 / zoom, ry + h);
  g.fillStyle = "#fffdf7ee"; g.fill();
  g.fillStyle = "#20241a"; g.textAlign = "center"; g.textBaseline = "alphabetic";
  g.fillText(text, x, ry + h - 5 / zoom);
}

function sprite(key, x, y, scale){
  const im = IMG[key]; if (!im || !im.width) return;
  const w = im.width * (scale || 1), h = im.height * (scale || 1);
  /* People are anchored at the FOOT, so a figure stands ON the ground it is at
     rather than hovering with the square centred on its waist. */
  g.drawImage(im, Math.round(x - w / 2), Math.round(y - h), w, h);
}

/* THE BADGE. A circled "i" on the near corner of every building, because a map
   that is clickable and does not say so is a map nobody clicks. It sits at a
   FIXED SCREEN SIZE rather than scaling with the zoom -- an affordance should be
   the same size to the hand whatever the camera is doing, and at 0.2x a scaled
   badge would be two pixels wide.

   Kept out of the sprite so it can pulse and light on hover without anybody
   redrawing the art. */
const BADGE_R = 9;
function badgeAt(b){
  const im = IMG["biz:" + b.sprite];
  const w = im && im.width ? im.width * b.scale : 48;
  const h = im && im.height ? im.height * b.scale : 48;
  return {x: wx(b) + w / 2 - 2, y: wy(b) - h / 2 + 2};
}

function drawBadges(){
  g.save();
  g.setTransform(1, 0, 0, 1, 0, 0);        /* screen space: fixed size */
  for (const b of visibleBuildings()){
    const p = badgeAt(b);
    const x = (p.x + panx) * zoom, y = (p.y + pany) * zoom;
    if (x < -20 || y < -20 || x > c.width + 20 || y > c.height + 20) continue;
    const hot = HOVER && HOVER.kind === "building" && HOVER.ref.id === b.id;
    g.beginPath(); g.arc(x, y, BADGE_R + (hot ? 2 : 0), 0, 7);
    g.fillStyle = hot ? "#ffd75e" : "#f6f2e2";
    g.fill();
    g.lineWidth = 2; g.strokeStyle = "#2b2416"; g.stroke();
    g.fillStyle = "#2b2416";
    g.font = `bold ${BADGE_R + 3}px ui-serif, Georgia, serif`;
    g.textAlign = "center"; g.textBaseline = "middle";
    g.fillText("i", x, y + 0.5);
  }
  g.restore();
}

/* What is under the pointer, in world pixels. People beat buildings: a figure
   standing in a doorway is smaller and on top, so it is what the eye means. */
function hitTest(px, py){
  for (const p of peopleNow()){
    const im = IMG[`person:${p.person}:${p.facing}`];
    if (!im || !im.width) continue;
    const x = p.sx, y = p.sy;
    if (px >= x - im.width / 2 && px <= x + im.width / 2 &&
        py >= y - im.height && py <= y)
      return {kind: "agent", ref: p};
  }
  for (const b of visibleBuildings()){
    const bp = badgeAt(b);
    if (Math.hypot(px - bp.x, py - bp.y) <= (BADGE_R + 3) / zoom)
      return {kind: "building", ref: b};
    const im = IMG["biz:" + b.sprite];
    if (!im || !im.width) continue;
    const w = im.width * b.scale, h = im.height * b.scale;
    if (px >= wx(b) - w / 2 && px <= wx(b) + w / 2 &&
        py >= wy(b) - h / 2 && py <= wy(b) + h / 2)
      return {kind: "building", ref: b};
  }
  return null;
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
  for (const b of visibleBuildings())
    standing.push({y: wy(b), f: () => building(b)});
  for (const p of peopleNow())
    standing.push({y: p.sy, f: () => {
      // The cart is laid down FIRST and slightly low, so the driver stands in
      // front of it rather than being hidden behind a donkey. Only while
      // MOVING: a parked cart drawn under everyone standing in Town turns the
      // market square into a car park.
      const hop = p.working ? hopOffset(p.id) : 0;
      const ring = rankColour(p.id);
      if (ring){
        // Filled AND stroked: a hairline ellipse on grass at low zoom is
        // invisible, which is the only zoom where you need it to pick someone
        // out of twenty.
        g.beginPath(); g.ellipse(p.sx, p.sy + 1, 12, 5.5, 0, 0, Math.PI * 2);
        g.fillStyle = ring; g.globalAlpha = 0.30; g.fill(); g.globalAlpha = 1;
        g.strokeStyle = ring; g.lineWidth = 2 / zoom; g.stroke();
      }
      if (p.vehicle && p.hauling){
        const key = `vehicle:${vslug(p.vehicle)}`;
        // 64px art beside a 32px villager: a cart should read as a bit bigger
        // than the person leading it, not as a barn.
        if (IMG[key]) sprite(key, p.sx, p.sy + 4, 0.55);
      }
      sprite(`person:${p.person}:${p.facing}`, p.sx, p.sy + hop, 1);
      if (p.courier) pack(p.sx, p.sy + hop, p.facing);
      const th = thoughtAt(p.id, HOUR);
      if (th && th.gist) bubble(p.sx, p.sy + hop - 34, th.gist);
    }});
  for (const amb of ambushesAt(HOUR)){
    for (const r of amb.raiders)
      standing.push({y: r.y, f: () => sprite(`person:${HAULER}:${r.facing}`, r.x, r.y, 1)});
    standing.push({y: amb.at.y - 1, f: () => {
      // A ring that tightens as they close, so the eye is pulled to the cart
      // rather than to whichever hooded figure happens to be nearest.
      g.strokeStyle = "#d94f3d";
      g.lineWidth = 2 / zoom;
      g.globalAlpha = 0.35 + 0.5 * (1 - amb.closing);
      g.beginPath();
      g.arc(amb.at.x, amb.at.y - 10, 14 + 30 * amb.closing, 0, Math.PI * 2);
      g.stroke();
      g.globalAlpha = 1;
    }});
  }
  standing.sort((a, b) => a.y - b.y).forEach(s => s.f());

  drawBadges();

  /* Labels last, and only when zoomed out far enough that they are not clutter. */
  if (zoom < 0.75){
    g.font = `${Math.round(13 / zoom)}px ui-monospace,monospace`;
    g.textAlign = "center";
    for (const p of DATA.places){
      g.fillStyle = "#0d1108cc";
      const w = g.measureText(p.name).width + 10 / zoom;
      g.fillRect(wx(p) - w / 2, wy(p) - 26 / zoom, w, 18 / zoom);
      g.fillStyle = p.kind === "spur" ? "#c9d6a8" : "#f2e9c9";
      g.fillText(p.name, p.sx, p.sy - 12 / zoom);
    }
  }

  positionPopup();
  updateClock();

  hud.innerHTML =
    (REPLAY ? `<b>${esc(DATA.run)}</b> &middot; ` : "") +
    `<b>${DATA.places.length}</b> places &middot; ` +
    `<b>${visibleBuildings().length}</b> buildings &middot; ` +
    `<b>${peopleNow().length}</b> people &middot; ` +
    `<b>${DATA.flags.length}</b> plots flagged<br>` +
    `${(WORLD_W / PPM / 1000).toFixed(1)}km valley &middot; ` +
    `zoom ${zoom.toFixed(2)}x &middot; ` +
    `${Math.round(c.width / zoom / PPM)}m across`;
}

/* ---------------------------------------------------------------- panels */

const panel = document.getElementById("popup");
const panelBody = document.getElementById("popup-body");

/* How close the map pulls in when something is clicked. Chosen so a building
   and the card above it both sit comfortably on screen at once -- further in
   and the card covers what it is describing. */
const FOCUS_ZOOM = 2.5;

/* Where on screen the clicked thing lands. NOT the centre: the card is drawn
   ABOVE it, so centring the building leaves no room and the card ends up laid
   over the very thing it is describing -- which is what the first version did.
   Two thirds down leaves the upper screen free for the card and still keeps the
   building comfortably in view. */
const FOCUS_Y = 0.68;
let HOVER = null, SELECTED = null;

/* Where a live server is, if there is one. The static page has no back end, so
   the chat box says so plainly rather than posting into the void and failing
   silently -- an "Ask" button that does nothing is worse than one that explains
   it cannot. Point this at a running `serve.py` and the same UI works live. */
const SERVER = new URLSearchParams(location.search).get("server") || null;

const esc = (t) => String(t).replace(/[&<>"]/g,
  ch => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[ch]));
/* NEITHER SIDE IS ESCAPED HERE -- every caller escapes its own dynamic parts
   and then adds markup of its own. Escaping again turned the separator in
   "Weaponsmith / Armory &middot; Blacksmith" into visible "&middot;". */
const row = (k, v) => `<div class="row"><span>${k}</span><span>${v}</span></div>`;
const money = (n) => `${Number(n).toLocaleString(undefined,
  {minimumFractionDigits: 2, maximumFractionDigits: 2})} D`;

function businessPanel(card){
  let h = `<h2>${esc(card.name)}</h2>`
        + `<div class="sub">${esc(card.type)} &middot; ${esc(card.place)}</div>`;
  h += row("Owner", esc(card.owner) + (card.government ? " (state)" : ""));
  if (card.owner_doing) h += row("Owner is", esc(card.owner_doing));
  h += row("Business cash", money(card.cash));
  h += row("Land", card.plots ? `${card.plots} plots` : "main road");
  if (card.producing) h += row("Making", esc(card.producing)
      + (card.blocked ? " &mdash; stalled" : ""));
  if (card.closed) h += row("Status", "closed");

  h += `<h3>On the shelf</h3>`;
  h += card.stock.length
     ? card.stock.map(s => row(`${esc(s.item)} x${s.qty}`,
         s.price === null ? '<span class="none">not for sale</span>' : money(s.price))
       ).join("")
     : '<div class="none">nothing in stock</div>';

  h += `<h3>Working here</h3>`;
  h += card.staff.length
     ? card.staff.map(p => row(`${esc(p.who)} &middot; ${esc(p.role)}`,
         `${money(p.wage)}/h<br><span class="none">${esc(p.doing)}</span>`)).join("")
     : '<div class="none">nobody &mdash; the owner works it alone</div>';

  h += `<h3>Hiring</h3>`;
  h += card.jobs.length
     ? card.jobs.map(j => row(
         `${esc(j.role)}${j.researcher ? " (research)" : ""}`,
         `${money(j.wage)}/h<br><span class="none">${j.applicants} applied &middot; `
         + `open ${j.hours_open}h</span>`)).join("")
     : '<div class="none">no jobs posted</div>';

  if (card.owner_id) h += chatBox(card.owner_id, card.owner, "the owner");
  return h;
}

function agentPanel(card){
  const tracked = FOLLOW === card.id;
  let h = `<h2>${esc(card.name)}</h2>`
        + `<div class="sub">${esc(card.model)}`
        + ` &middot; <a href="#" class="track" data-id="${esc(card.id)}">`
        + `${tracked ? "stop following" : "follow"}</a></div>`;
  h += row("Doing", esc(card.doing));
  h += row("At", esc(card.at) + (card.travel_progress !== null
        ? ` <span class="none">(${Math.round(card.travel_progress * 100)}% there)</span>`
        : ""));
  h += row("Cash", money(card.denari));
  /* Rank beside the number, because the number alone says nothing: 4,000 denari
     is either winning or last, and which one is the interesting part. */
  h += row("Net worth", `${money(card.net_worth)}<br>`
        + `<span class="none">rank ${card.rank} of ${card.of}</span>`);

  h += `<h3>Carrying</h3>`;
  const carry = Object.entries(card.carrying);
  h += carry.length
     ? carry.map(([k, v]) => `<span class="tag">${esc(k)} x${v}</span>`).join("")
     : '<div class="none">empty-handed</div>';

  h += `<h3>Owns</h3>`;
  let owns = card.businesses.map(b =>
      row(esc(b.name), `<span class="none">${esc(b.place)}</span>`)).join("");
  owns += card.vehicles.map(v => `<span class="tag">${esc(v)}</span>`).join("");
  if (card.has_home) owns += `<span class="tag">a home</span>`;
  h += owns || '<div class="none">nothing yet</div>';

  if (card.employed_by.length){
    h += `<h3>Works for</h3>`;
    h += card.employed_by.map(e => row(
      `${esc(e.business)} &middot; ${esc(e.role)}`, `${money(e.wage)}/h`)).join("");
  }

  /* WHAT THEY SAID, and the reason a replay is worth watching at all. The rest
     of the card is state; this is the agent's own account of why. Filtered to
     the slider's hour, because a decision it has not made yet is not something
     it can be asked about. */
  const said = (DATA.decisions && DATA.decisions[card.id] || [])
    .filter(d => d.h <= HOUR).slice(-4).reverse();
  if (said.length){
    h += `<h3>What they said</h3>`;
    h += said.map(d =>
      `<div style="margin-bottom:7px">`
      + `<b>h${d.h}</b> ${esc(d.did || "thought about it")}`
      + `<div class="none" style="font-style:normal;color:#4a5340">`
      + `${esc(d.why).slice(0, 260)}</div></div>`).join("");
  }

  h += chatBox(card.id, card.name, "them");
  return h;
}

function chatBox(agentId, who, label){
  return `<h3>Talk to ${esc(who)}</h3>
    <div class="chat" data-agent="${esc(agentId)}">
      <textarea placeholder="Ask ${esc(label)} a question, or suggest what to do next."></textarea>
      <div class="btns">
        <button data-act="ask">Ask</button>
        <button data-act="advise">Advise</button>
      </div>
      <div id="reply"></div>
    </div>`;
}

/* LIVE CARDS WIN OVER BAKED ONES. The page ships a snapshot of hour zero so it
   works with no server at all; when `?server=` is given it refreshes them from
   the running simulation, and every panel opened after that is current. Same
   page, same shapes -- `convoy/inspect` builds both. */
async function refreshCards(){
  if (!SERVER) return;
  try {
    const res = await fetch(`${SERVER}/cards`);
    const data = await res.json();
    if (data.cards){
      DATA.cards = data.cards;
      LIVE_HOUR = data.hour;
    }
  } catch (err) { /* keep the baked cards; the panel says which it is showing */ }
}
let LIVE_HOUR = null;

/* Where the card should point: the top-centre of the thing, in world pixels.
   Buildings are drawn centred on their block and people stand on their feet, so
   "the top" is a different sum for each. */
function anchorOf(hit){
  const r = hit.ref;
  if (hit.kind === "building"){
    const im = IMG["biz:" + r.sprite];
    const h = im && im.height ? im.height * r.scale : 48;
    return {x: wx(r), y: wy(r) - h / 2};
  }
  const im = IMG[`person:${r.person}:${r.facing}`];
  return {x: wx(r), y: wy(r) - (im && im.height ? im.height : 32)};
}

/* Ease the camera in rather than jumping. A cut leaves you hunting for what you
   just clicked; a quarter-second move keeps the thing under your eye the whole
   way, which is the entire reason to zoom to it at all. */
let FLIGHT = null;
function flyTo(x, y, targetZoom){
  const from = {zoom: zoom, panx: panx, pany: pany};
  const t0 = performance.now(), ms = 260;
  FLIGHT = t0;
  function step(now){
    if (FLIGHT !== t0) return;                 /* a newer click took over */
    const k = Math.min((now - t0) / ms, 1);
    const e = k < 0.5 ? 2 * k * k : 1 - Math.pow(-2 * k + 2, 2) / 2;
    zoom = from.zoom + (targetZoom - from.zoom) * e;
    const wantX = -(x - c.width / 2 / zoom);
    const wantY = -(y - c.height * FOCUS_Y / zoom);
    panx = from.panx + (wantX - from.panx) * e;
    pany = from.pany + (wantY - from.pany) * e;
    clampPan(); draw();
    if (k < 1) requestAnimationFrame(step); else FLIGHT = null;
  }
  requestAnimationFrame(step);
}

async function openPanel(hit){
  SELECTED = hit;
  panel.classList.add("open");
  const a = anchorOf(hit);
  flyTo(a.x, a.y, FOCUS_ZOOM);

  /* DRAW WHAT WE ALREADY KNOW, THEN REFRESH.
     This opened the popup and only then awaited `/cards`, so the first click of
     a session showed an EMPTY white bubble for as long as the round-trip took,
     and later clicks showed the PREVIOUS agent until the answer came back.
     Invisible without `?server=`, because the await returns instantly with no
     server to ask -- and very visible with one, since `serve.py` is a
     single-threaded stdlib server that a model call can block for seconds. */
  renderPanel(hit);
  if (!SERVER) return;
  await refreshCards();
  // The viewer may have clicked something else while that was in flight; a
  // late answer must not redraw the panel over a newer selection.
  if (SELECTED === hit) renderPanel(hit);
}

function renderPanel(hit){
  const card = DATA.cards[hit.ref.id];
  if (!card){
    // Not "nothing on record" while a fetch is still in flight -- that reads
    // as an answer when it is only a wait.
    panelBody.innerHTML = `<h2>${esc(hit.ref.name || hit.ref.type || "?")}</h2>`
      + `<div class="sub">${SERVER ? "asking the server&hellip;"
                                   : "nothing on record for " + esc(hit.ref.id)}</div>`;
    draw();
    return;
  }
  panelBody.innerHTML =
    (card.kind === "business" ? businessPanel(card) : agentPanel(card))
    + `<div class="sub" style="margin-top:12px;margin-bottom:0">`
    + (LIVE_HOUR !== null ? `hour ${LIVE_HOUR} &middot; live`
       : REPLAY ? `stock and staff as at hour ${DATA.checkpoint_hour} `
                  + `(end of run) &middot; quotes to hour ${HOUR.toFixed(1)}`
       : "hour 0 &middot; static snapshot")
    + `</div>`;
  wireChat();
  panelBody.querySelectorAll("a.track").forEach(el =>
    el.addEventListener("click", ev => {
      ev.preventDefault();
      trackAgent(el.dataset.id);
      openPanel(hit);          // redraw the link's label
    }));
  draw();
}

/* Called from `draw`, so the card rides the map: pan and it follows the
   building, zoom out and it keeps pointing at it. */
function positionPopup(){
  if (!SELECTED || !panel.classList.contains("open")) return;
  const a = anchorOf(SELECTED);
  const sx = (a.x + panx) * zoom, sy = (a.y + pany) * zoom;
  const w = panel.offsetWidth, h = panel.offsetHeight;
  const GAP = 14;

  /* Above by preference, below when there is no room -- and the tail flips with
     it, so the card never points away from the thing it describes. */
  const below = sy - h - GAP < 6;
  panel.classList.toggle("below", below);
  let top = below ? sy + GAP + 22 : sy - h - GAP;
  let left = sx - w / 2;

  /* Kept on screen, with the tail sliding along the card's edge to stay over
     the target. Without that the card clamps at the edge and its tail points
     confidently at empty grass. */
  const clampedLeft = Math.max(8, Math.min(left, innerWidth - w - 8));
  panel.style.setProperty("--tail",
    `${Math.max(14, Math.min(sx - clampedLeft, w - 14))}px`);
  panel.style.left = `${clampedLeft}px`;
  panel.style.top = `${Math.max(6, Math.min(top, innerHeight - h - 6))}px`;
}

function closePanel(){
  SELECTED = null; panel.classList.remove("open"); draw();
}
document.getElementById("close").onclick = closePanel;

function wireChat(){
  const box = panelBody.querySelector(".chat");
  if (!box) return;
  const area = box.querySelector("textarea");
  const reply = box.querySelector("#reply");
  for (const btn of box.querySelectorAll("button")) btn.onclick = async () => {
    const text = area.value.trim();
    if (!text) return;
    if (!SERVER){
      reply.textContent =
        "This is a static snapshot, so there is nobody to answer.\n\n"
        + "Start the server (python3 serve.py) and open this page with "
        + "?server=http://localhost:8000 to talk to the agents for real.";
      reply.classList.add("show");
      return;
    }
    const act = btn.dataset.act;
    for (const b of box.querySelectorAll("button")) b.disabled = true;
    reply.textContent = act === "ask" ? "asking..." : "sending..."; reply.classList.add("show");
    try {
      const res = await fetch(`${SERVER}/agent/${box.dataset.agent}/${act}`, {
        method: "POST", headers: {"Content-Type": "application/json"},
        body: JSON.stringify(act === "ask"
          ? {question: text, who: "a viewer"}
          : {text: text, from_who: "a viewer"}),
      });
      const data = await res.json();
      reply.textContent = data.error ? `error: ${data.error}`
        : (data.text || data.answer || JSON.stringify(data, null, 1));
      if (!data.error) area.value = "";
    } catch (err) {
      reply.textContent = `could not reach ${SERVER}: ${err}`;
    }
    for (const b of box.querySelectorAll("button")) b.disabled = false;
  };
}

/* --------------------------------------------------------------- pointer */

function worldFromEvent(e){
  const r = c.getBoundingClientRect();
  return {x: (e.clientX - r.left) / zoom - panx,
          y: (e.clientY - r.top) / zoom - pany};
}

let dragging = false, lx = 0, ly = 0, moved = 0;
c.addEventListener("mousedown", e => {
  // Taking hold of the map gives you the camera back. See FOLLOW.
  FOLLOW = null;
  dragging = true; moved = 0; lx = e.clientX; ly = e.clientY;
  c.classList.add("drag");
});
addEventListener("mouseup", e => {
  const wasDragging = dragging;
  dragging = false; c.classList.remove("drag");
  /* A CLICK IS A MOUSEUP THAT DID NOT TRAVEL. Without the threshold every pan
     that ended over a building opened its panel, which made the map feel like
     it was grabbing at you. Four pixels is below what a hand does by accident
     and well under what a deliberate drag does. */
  if (!wasDragging || moved > 4) return;
  const hit = hitTest(worldFromEvent(e).x, worldFromEvent(e).y);
  hit ? openPanel(hit) : closePanel();
});
addEventListener("mousemove", e => {
  if (dragging){
    moved += Math.abs(e.clientX - lx) + Math.abs(e.clientY - ly);
    panx += (e.clientX - lx) / zoom; pany += (e.clientY - ly) / zoom;
    lx = e.clientX; ly = e.clientY; clampPan(); draw();
    return;
  }
  const w = worldFromEvent(e);
  const hit = hitTest(w.x, w.y);
  const changed = (hit && hit.ref.id) !== (HOVER && HOVER.ref.id);
  HOVER = hit;
  c.classList.toggle("pointing", !!hit);
  if (changed) draw();
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
/* THE TICKER. Only what `_headlines` kept, only what has already happened at
   the current hour, newest at the bottom. Clicking a line travels to it. */
const tickerRows = document.getElementById("ticker-rows");
let lastTickHour = -1;
function drawTicker(){
  if (!REPLAY) return;
  const hl = (DATA.headlines || []).filter(x => x.h <= HOUR).slice(-6);
  const stamp = hl.length ? hl[hl.length - 1].h : -1;
  if (stamp === lastTickHour && tickerRows.childElementCount === hl.length) return;
  lastTickHour = stamp;
  tickerRows.innerHTML = hl.map(x =>
    `<div class="tick ${esc(x.kind)}" data-hour="${x.h}" data-who="${esc(x.who || "")}">`
    + `<b>h${x.h.toFixed(1)}</b>${esc(x.text)}</div>`).join("");
  tickerRows.querySelectorAll(".tick").forEach(el =>
    el.addEventListener("click", () =>
      goToMoment(parseFloat(el.dataset.hour), el.dataset.who || null, 0.06)));
}

zoom = 1;
resize();

/* A REDRAW LOOP. The page drew only on demand -- a drag, a click, a slider
   move -- which is right for a static map and wrong the moment anything on it
   animates. Without this the workers' hop only ran while the clock was
   playing, so a paused valley looked asleep even though half of it was at work.
   Clock advance still belongs to `tick`; this only repaints. */
(function animate(){
  if (REPLAY && !playing) draw();
  drawTicker();
  requestAnimationFrame(animate);
})();

/* ---------------------------------------------------------------------------
   THE BOARDS
   Rendered from DATA.boards, which `convoy/inspect.py` assembled -- the same
   shapes `serve.py` returns, so a live page and a baked one cannot disagree.
   Nothing here is computed from the map: if a number needs working out, it is
   worked out by the code that runs the world.
--------------------------------------------------------------------------- */
const BOARDS = DATA.boards || {};
const ASSET_COLOURS = {cash:"#9dd17a", goods:"#d9c46a", businesses:"#7aa9d1",
                       vehicles:"#c58fd1", property:"#d1937a"};
/* Whole denari, no suffix. The popup's `money` is 2dp with a "D" on the end,
   which is right for a card reading "cash: 1,204.50 D" and far too wide for a
   column of twenty of them. Same number, different job. */
const coin = n => (n === null || n === undefined) ? "&mdash;"
  : Number(n).toLocaleString(undefined, {maximumFractionDigits: 0});
const pct = n => (n >= 0 ? "+" : "") + Math.round(n * 100) + "%";

function assetBar(a){
  const total = Object.values(a).reduce((s, v) => s + Math.max(0, v), 0);
  if (total <= 0) return '<div class="bar"></div>';
  return '<div class="bar">' + Object.entries(a).map(([k, v]) =>
    v > 0 ? `<i style="width:${(v / total * 100).toFixed(1)}%;`
          + `background:${ASSET_COLOURS[k]}" title="${k} ${coin(v)}"></i>` : ""
  ).join("") + '</div>';
}

function boardLeaderboard(){
  const rows = BOARDS.leaderboard || [];
  if (!rows.length) return '<div class="empty">Nobody in the valley yet.</div>';
  let h = '<div class="key">' + Object.entries(ASSET_COLOURS).map(([k, c]) =>
        `<span><i style="background:${c}"></i>${k}</span>`).join("") + "</div>";
  h += '<table><tr><th>#</th><th>Who</th><th class="n">Net worth</th>'
    +  '<th>Job</th><th>Where the money is</th><th>Holdings</th></tr>';
  rows.forEach((r, i) => {
    const a = r.assets;
    h += `<tr><td class="dim">${i + 1}</td>`
      +  `<td class="who">${esc(r.name)}`
      +  (r.alive ? "" : ' <span class="bad">dead</span>')
      +  `<br><span class="dim">${esc(r.doing)}</span></td>`
      +  `<td class="n who">${coin(r.net_worth)}</td>`
      +  `<td>${r.job ? esc(r.job) + `<br><span class="dim">`
                        + coin(r.wage) + `/h</span>` : '<span class="dim">no job</span>'}</td>`
      +  `<td>${assetBar(a)}<span class="dim">`
      +  `cash ${coin(a.cash)} &middot; goods ${coin(a.goods)}`
      +  (a.businesses ? ` &middot; biz ${coin(a.businesses)}` : "")
      +  (a.vehicles ? ` &middot; carts ${coin(a.vehicles)}` : "")
      +  (a.property ? ` &middot; home ${coin(a.property)}` : "")
      +  `</span></td>`
      // VEHICLES BELONG HERE, not just in the asset bar. A cart is a liquid
      // asset -- it can be sold, lent with a consignment, or driven for hire --
      // and "what could this agent actually put on the road tomorrow" is not
      // answerable from a coloured bar.
      +  `<td class="dim">${holdings(r) || "&mdash;"}</td></tr>`;
  });
  return h + "</table>";
}

/* What an agent owns, in the order it matters: the businesses that earn, the
   carts that move goods, then the roof over their head. */
function holdings(r){
  const bits = [];
  for (const b of r.businesses) bits.push(esc(b.name));
  const carts = {};
  for (const v of (r.vehicles || [])) carts[v] = (carts[v] || 0) + 1;
  for (const [type, n] of Object.entries(carts))
    bits.push(`<span class="cart">${esc(type)}${n > 1 ? ` x${n}` : ""}</span>`);
  if (r.has_home) bits.push(`<span class="home">a home</span>`);
  return bits.join("<br>");
}

function boardCommodities(){
  const rows = BOARDS.commodities || [];
  if (!rows.length) {
    return '<div class="empty">Nothing has been sold yet, so nothing has a '
         + 'price. The ticker fills in as the valley trades.</div>';
  }
  let h = '<table><tr><th>Good</th><th class="n">Avg</th><th class="n">Last</th>'
        + '<th class="n">Low</th><th class="n">High</th><th class="n">Sold</th>'
        + '<th class="n">Trades</th><th class="n">Book</th>'
        + '<th class="n">vs book</th></tr>';
  rows.forEach(r => {
    const cls = r.premium >= 0 ? "up" : "down";
    h += `<tr><td class="who">${esc(r.item)}</td>`
      +  `<td class="n who">${r.vwap}</td><td class="n">${r.last}</td>`
      +  `<td class="n dim">${r.low}</td><td class="n dim">${r.high}</td>`
      +  `<td class="n">${coin(r.volume)}</td><td class="n dim">${r.trades}</td>`
      +  `<td class="n dim">${r.book}</td>`
      +  `<td class="n ${cls}">${pct(r.premium)}</td></tr>`;
  });
  return h + "</table>";
}

/* THE REPORT CARD. What was said, whether it was HEARD, and what happened to
   the agent against what happened to everybody else. The last column is the
   one that matters: an agent that gained 200 in a valley that all gained 200
   was not helped, and only the whole-leaderboard snapshot makes that
   subtractable. */
function boardAdvice(){
  const rows = BOARDS.advice || [];
  if (!rows.length){
    return '<div class="empty">No advice was given in this run. Start one with '
         + '<code>--advise</code>, or talk to an agent through serve.py.</div>';
  }
  let h = '<table><tr><th class="n">Hour</th><th>Who</th><th>Advice</th>'
        + '<th>Heard?</th><th>Did</th><th class="n">Rank</th>'
        + '<th class="n">Gained</th><th class="n">The field</th>'
        + '<th class="n">Vs field</th></tr>';
  rows.forEach(r => {
    const beat = r.beat_field;
    const cls = beat === null ? "dim" : beat >= 0 ? "up" : "down";
    h += `<tr class="jump" data-hour="${r.hour}" data-who="${esc(r.agent_id)}" `
      +  `title="watch this moment">`
      +  `<td class="n dim">h${r.hour}</td>`
      +  `<td class="who">${esc(r.agent)}<br><span class="dim">${esc(r.from_who)}</span></td>`
      +  `<td style="max-width:280px">${esc(r.text)}</td>`
      +  `<td>${r.heard
             ? `<span class="good">yes</span><br><span class="dim">${r.times_seen}x, `
               + `first h${r.first_seen_hour}</span>`
             : `<span class="bad">never reached it</span>`}</td>`
      +  `<td class="dim">${esc((r.did_after || []).join(", ")) || "&mdash;"}</td>`
      +  `<td class="n dim">${r.rank_then || "?"} &rarr; ${r.rank_now || "?"}</td>`
      +  `<td class="n">${r.gained === null ? "&mdash;" : coin(r.gained)}</td>`
      +  `<td class="n dim">${r.field_gained === null ? "&mdash;" : coin(r.field_gained)}</td>`
      +  `<td class="n ${cls}">${beat === null ? "&mdash;"
             : (beat >= 0 ? "+" : "") + coin(beat)}</td></tr>`;
  });
  return h + "</table>";
}

function boardConvoys(){
  const b = BOARDS.convoys || {};
  const live = b.live || [], hist = b.history || [], t = b.totals || {};
  let h = "";
  if (t.delivered || t.robbed) {
    h += `<div class="sub">${t.delivered} delivered, `
      +  `<span class="bad">${t.robbed} robbed</span> &mdash; `
      +  `${Math.round((t.success_rate || 0) * 100)}% got through, `
      +  `${coin(t.value_lost)} lost on the road.</div>`;
  }
  h += "<h2>On the road now</h2>";
  if (!live.length) {
    h += '<div class="empty">No loads posted.</div>';
  } else {
    h += '<table><tr><th>Load</th><th class="n">Units</th><th class="n">Worth</th>'
      +  '<th>Route</th><th class="n">Fee</th><th>Courier</th>'
      +  '<th>Risk on</th><th class="n">Posted</th></tr>';
    live.forEach(r => {
      h += `<tr><td class="who">${esc(r.item)}</td><td class="n">${r.qty}</td>`
        +  `<td class="n">${coin(r.value)}</td>`
        +  `<td class="dim">${esc(r.from)} &rarr; ${esc(r.to)}</td>`
        +  `<td class="n">${coin(r.fee)}</td>`
        +  `<td>${r.courier ? esc(r.courier)
                 : '<span class="dim">unclaimed</span>'}</td>`
        +  `<td class="dim">${esc(r.risk_borne_by)}</td>`
        +  `<td class="n dim">h${r.posted_hour}</td></tr>`;
    });
    h += "</table>";
  }
  h += "<h2 style=\"margin-top:16px\">What happened before</h2>";
  if (!hist.length) {
    h += '<div class="empty">No completed journeys in this run.</div>';
  } else {
    h += '<table><tr><th class="n">Hour</th><th>Outcome</th><th>Who</th>'
      +  '<th>Where</th><th class="n">Value</th><th>Cart</th>'
      +  '<th class="n">Guards</th><th>Detail</th></tr>';
    hist.forEach(r => {
      const robbed = r.outcome === "robbed";
      h += `<tr class="jump" data-hour="${r.hour}" data-who="${esc(r.actor || "")}" `
        +  `title="watch this happen">`
        +  `<td class="n dim">h${r.hour}</td>`
        +  `<td class="${robbed ? 'bad' : 'good'}">${robbed ? "robbed" : "delivered"}</td>`
        +  `<td class="dim">${esc(r.actor || "")}</td>`
        +  `<td class="dim">${esc(r.route || r.where || "")}</td>`
        +  `<td class="n">${coin(r.value)}</td>`
        +  `<td class="dim">${esc(r.vehicle || "")}</td>`
        +  `<td class="n dim">${r.escorts === undefined ? "" : r.escorts}</td>`
        +  `<td class="dim">${robbed
              ? Math.round((r.share_lost || 0) * 100) + "% of " + esc(r.cargo || "the load")
                + " &middot; " + Math.round((r.risk || 0) * 100) + "% risk"
              : (r.units ? r.units + "x " + esc(r.item) : "")}</td></tr>`;
    });
    h += "</table>";
  }
  return h;
}

const BOARD_TITLES = {
  leaderboard: ["Leaderboard", "Every agent, richest first. The bar shows where "
              + "the money actually is."],
  convoys: ["Convoy schedule", "Loads on the road, and how the ones already run "
          + "turned out."],
  commodities: ["Commodity prices", "What goods have actually changed hands for. "
              + "Anonymous: what sold and for how much, never who sold it."],
  advice: ["Advice report", "What was said, whether the agent HEARD it, and how "
         + "it did against everyone else. A rising tide is not good advice."],
};

const boardEl = document.getElementById("board");
let openBoard = null;

function showBoard(which){
  const nav = document.querySelectorAll("#boards-nav button");
  if (openBoard === which) { which = null; }
  openBoard = which;
  nav.forEach(b => b.classList.toggle("on", b.dataset.board === which));
  if (!which) { boardEl.classList.remove("open"); return; }
  const [title, sub] = BOARD_TITLES[which];
  const body = which === "leaderboard" ? boardLeaderboard()
             : which === "commodities" ? boardCommodities()
             : which === "advice" ? boardAdvice() : boardConvoys();
  boardEl.innerHTML = `<h2>${title}</h2><div class="sub">${sub}</div>` + body;
  // (boards) -- the agent-card follow link is wired in openPanel.
  boardEl.querySelectorAll("tr.jump").forEach(tr =>
    tr.addEventListener("click", () =>
      goToMoment(parseFloat(tr.dataset.hour), tr.dataset.who || null)));
  boardEl.classList.add("open");
  boardEl.scrollTop = 0;
}

document.querySelectorAll("#boards-nav button").forEach(b =>
  b.addEventListener("click", () => showBoard(b.dataset.board)));
/* Escape closes whatever is open -- the board first, since it is on top. */
document.addEventListener("keydown", e => {
  if (e.key === "Escape" && openBoard) showBoard(null);
});
</script></body></html>
"""


if __name__ == "__main__":
    raise SystemExit(main())
