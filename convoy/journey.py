"""MOVING ON THE MAP, HEX BY HEX (designer, 2026-11-01).

"Let's go back to map view, but still foggy and you have to move your
character to find stuff ... move one space at a time, and each movement
drains energy, which can be replenished by food (though it is separate than
hunger) or by going home and resting. If you go out to explore and run out of
energy, you can fast travel home to rest ... players can buy camp supplies ...
So maybe the energy bar is 10 moves and then you need two hours of rest ...
horses can go 12 instead of the 10 a donkey goes, carriages can go 15 ... I
think you should also be able to send off family workers to go explore for
you, or hire people to go explore for you."

  * A STEP is one hex (convoy/hexes.py, 250 m): a neighbour you can stand on,
    1 energy (2 up a mountain), 10 game minutes. A route is a line of steps,
    walked one at a time (`set_route`, then `advance` every tick).
  * Each hex you reach shows you it and the six round it (`reveal`): the map
    is found by moving. A hex with a place in it is arriving there.
  * ENERGY is the most your mount allows (data.ENERGY) plus what your home
    upgrades give (`HOME_UPGRADES`). Rest at home: two hours, to full. Camp
    anywhere with Camp Supplies: two hours, +8. Sleep rough: four hours, +5,
    so nobody is ever stranded. A meal gives +2 (actions._apply_meal).
  * EXPLORERS: a grown member of the family, or a scout hired for the trip,
    walk the hexes for you -- to a spot, or roaming one way for some days --
    camping when spent, and everything they see goes on your map.

Only the player moves this way for now; settlers keep the timed roads.
"""

from __future__ import annotations

import math
import random
from typing import TYPE_CHECKING, Any

from . import claims as CL
from . import data as D
from . import discovery as DS
from . import hexes as H
from .events import Significance
from .state import Activity, Explorer

if TYPE_CHECKING:
    from .events import EventLog
    from .state import Agent, World

STEP_S = 600.0                 # a hex: ten game minutes
SIGHT = 1                      # you see the hex you are on and the ring round it
REST_H = 2.0                   # at home, to full
CAMP_H, CAMP_GAIN = 2.0, 8.0   # with Camp Supplies
ROUGH_H, ROUGH_GAIN = 4.0, 5.0 # with nothing
MEAL_GAIN = 2.0
CAMP_ITEM = "Camp Supplies"
HOME_UPGRADES: dict[str, tuple[float, float, str]] = {
    # name: (max energy added, price, what it is)
    "Feather Bed": (2.0, 150.0, "sleep better: +2 energy at most"),
    "Hearth": (3.0, 300.0, "a warm house to come home to: +3 energy at most"),
}
SCOUT_WAGE = 20.0              # a hired scout, a day, paid up front
SCOUT_NAMES = ["Abner", "Tamsin", "Ezra", "Wren", "Silas", "Maud", "Jory", "Ottilie"]
EXPLORER_ENERGY = 10.0
_COMPASS = {"east": 0, "north-east": 45, "north": 90, "north-west": 135,
            "west": 180, "south-west": 225, "south": 270, "south-east": 315}


# -- where you are --------------------------------------------------------------

def max_energy(world: "World", agent: "Agent") -> float:
    v = world.vehicles.get(agent.mounted_vehicle or "")
    base = D.ENERGY.get(v.type if v else "On Foot", D.ENERGY["On Foot"])
    return float(base + sum(HOME_UPGRADES[u][0] for u in agent.home_rest if u in HOME_UPGRADES))


def here(agent: "Agent") -> H.Hex:
    return (agent.hex[0], agent.hex[1])


_PLACES: dict[tuple, dict[str, list[str]]] = {}


def places_by_hex(world: "World") -> dict[str, list[str]]:
    from . import layout as L
    tag = (id(world), tuple(world.cities), len(world.claims))
    t = _PLACES.get(tag)
    if t is None:
        t = {}
        names = list(L.places_cached(list(world.cities))) + list(world.claims)
        for n in names:
            xy = CL.place_xy(world, n)
            if xy:
                t.setdefault(H.key(H.to_hex(*xy)), []).append(n)
        _PLACES.clear()
        _PLACES[tag] = t
    return t


def places_in(world: "World", h: H.Hex) -> list[str]:
    """The places in a hex, the nearest its centre first."""
    names = places_by_hex(world).get(H.key(h), [])
    c = H.centre(h)
    return sorted((n for n in names if CL.place_xy(world, n)), key=lambda n: math.dist(c, CL.place_xy(world, n)))


def hex_of_place(world: "World", place: str) -> H.Hex | None:
    xy = CL.place_xy(world, place)
    return H.to_hex(*xy) if xy else None


def ensure(world: "World", agent: "Agent") -> None:
    """Give someone a hex, full energy, and the map they start with: home and
    the ring round it, their land, and the state's trading posts."""
    if agent.hex is not None:
        return
    xy = DS.position(world, agent) or CL.place_xy(world, agent.home or agent.location)
    h = H.to_hex(*xy) if xy else (0, 0)
    agent.hex = [h[0], h[1]]
    agent.energy = max_energy(world, agent)
    reveal(world, agent, h)
    for p in [agent.home, *(c.name for c in world.claims.values() if c.owner == agent.id)]:
        ph = hex_of_place(world, p) if p else None
        if ph:
            reveal(world, agent, ph)
    for xy in CL.anchors(world).values():
        reveal(world, agent, H.to_hex(*xy))


def reveal(world: "World", agent: "Agent", h: H.Hex, radius: int = SIGHT) -> int:
    """Add `h` and the hexes round it to `agent`'s map; returns how many were new."""
    have = set(agent.explored)
    new = [H.key(x) for x in H.ring(h, radius) if H.key(x) not in have]
    agent.explored.extend(new)
    return len(new)


def found(agent: "Agent", place_hex: H.Hex | None) -> bool:
    return place_hex is not None and H.key(place_hex) in set(agent.explored)


# -- moving ----------------------------------------------------------------------

def set_route(world: "World", log: "EventLog", agent: "Agent", steps: list[list[int]]) -> tuple[bool, str]:
    """Walk these hexes, one after another, from where you stand (or from the
    hex you are stepping onto now). A new route replaces the old."""
    ensure(world, agent)
    if agent.in_transit:
        return False, "you are on the road; wait until you arrive"
    if agent.activity.kind in ("rest", "camp"):
        _wake(world, agent)
    start = here(agent)
    if agent.activity.kind == "move":
        to = agent.activity.detail.get("to")
        start = (to[0], to[1])
    clean, prev = [], start
    for s in steps[:60]:
        h = (int(s[0]), int(s[1]))
        if H.distance(prev, h) != 1:
            break
        clean.append([h[0], h[1]])
        prev = h
    if not clean and steps:
        return False, "that is not next to where you stand"
    agent.route = clean
    if agent.activity.kind != "move" and agent.route:
        why = _start_step(world, agent)
        if why:
            return False, why
    return True, f"{len(clean)} hex{'es' if len(clean) != 1 else ''} to walk"


def _start_step(world: "World", agent: "Agent") -> str:
    """Set off onto the next hex of the route, or say why not."""
    if not agent.route:
        return ""
    nxt = (agent.route[0][0], agent.route[0][1])
    cost = H.step_cost(world, nxt)
    if cost is None:
        agent.route.clear()
        return "you cannot cross there" if H.terrain(world, nxt) == "water" else "that is the edge of the world"
    if agent.energy < cost:
        agent.route.clear()
        return "you are spent: rest, camp, or go home"
    agent.energy -= cost
    agent.activity = Activity("move", world.sim_time + STEP_S, {"to": [nxt[0], nxt[1]], "from": list(agent.hex)})
    return ""


def advance(world: "World", log: "EventLog", agent: "Agent") -> dict[str, Any] | None:
    """Every tick: finish a step that is done (and start the next), or a rest.
    Returns what happened, for the caller to arrive or leave places."""
    act = agent.activity
    if act.kind == "move" and world.sim_time >= act.ends_at:
        to = act.detail["to"]
        before = places_in(world, here(agent))
        agent.hex = [to[0], to[1]]
        world.positions[agent.id] = H.centre(here(agent))
        new = reveal(world, agent, here(agent))
        if agent.route and agent.route[0] == to:
            agent.route.pop(0)
        agent.activity = Activity("idle", world.sim_time)
        why = _start_step(world, agent) if agent.route else ""
        return {"stepped": to, "new": new, "places": places_in(world, here(agent)), "left": before, "stopped": why}
    if act.kind in ("rest", "camp") and world.sim_time >= act.ends_at:
        gain = _wake(world, agent)
        return {"rested": round(gain, 1), "where": act.detail.get("where", "")}
    if act.kind == "homeward" and world.sim_time >= act.ends_at:
        h = hex_of_place(world, agent.home)
        agent.hex = [h[0], h[1]]
        world.positions[agent.id] = H.centre(h)
        agent.activity = Activity("idle", world.sim_time)
        return {"home": agent.home}
    return None


HOME_SPEEDUP = 3.0             # going home is three times quicker than walking it


def go_home(world: "World", log: "EventLog", agent: "Agent") -> tuple[bool, str]:
    """The one fast trip: home, from wherever you stand, goods and all, at a
    third of the time walking it would take (at least ten minutes)."""
    ensure(world, agent)
    home = hex_of_place(world, agent.home) if agent.home else None
    if home is None:
        return False, "you have no home yet"
    if agent.in_transit:
        return False, "you are on the road"
    if home == here(agent) and agent.location == agent.home:
        return False, "you are home"
    agent.route.clear()
    if agent.activity.kind in ("rest", "camp"):
        _wake(world, agent)
    secs = max(STEP_S, H.distance(here(agent), home) * STEP_S / HOME_SPEEDUP)
    agent.activity = Activity("homeward", world.sim_time + secs, {"from": list(agent.hex)})
    return True, f"You head home: {secs / 60:.0f} minutes."


def _wake(world: "World", agent: "Agent") -> float:
    """End a rest, whole or cut short: energy for the share of it slept."""
    act = agent.activity
    if act.kind not in ("rest", "camp"):
        return 0.0
    total = act.detail.get("hours", REST_H) * 3600.0
    share = 1.0 if world.sim_time >= act.ends_at else max(0.0, 1.0 - (act.ends_at - world.sim_time) / total)
    gain = act.detail.get("gain", 0.0) * share
    agent.energy = min(max_energy(world, agent), agent.energy + gain)
    agent.activity = Activity("idle", world.sim_time)
    return gain


def snap(world: "World", agent: "Agent") -> None:
    """After any other way of getting somewhere (a convoy, a timed trip):
    stand on the hex of where you are. Only when `location` has just changed
    by one of those -- a step out of a place leaves `location` as it was."""
    if agent.hex is None or agent.activity.kind == "move" or agent.in_transit:
        return
    h = hex_of_place(world, agent.location)
    if h is not None and h != here(agent) and agent.location not in places_in(world, here(agent)):
        agent.hex = [h[0], h[1]]
        agent.route.clear()
        reveal(world, agent, h)


# -- resting -----------------------------------------------------------------

def _resting(world: "World", agent: "Agent", where: str, hours: float, gain: float) -> None:
    agent.route.clear()
    agent.activity = Activity("rest" if where == "home" else "camp", world.sim_time + hours * 3600.0,
                              {"where": where, "hours": hours, "gain": gain})


def _check_still(agent: "Agent") -> str:
    if agent.in_transit:
        return "you are on the road"
    if agent.activity.kind in ("move", "homeward"):
        return "you are on your way; stop first"
    if agent.activity.kind in ("rest", "camp"):
        return "you are resting already"
    if agent.activity.kind == "work" and agent.activity.ends_at > 0:
        return "you are at work; stop first"
    return ""


def rest(world: "World", log: "EventLog", agent: "Agent") -> tuple[bool, str]:
    ensure(world, agent)
    why = _check_still(agent)
    if why:
        return False, why
    home = hex_of_place(world, agent.home) if agent.home else None
    if home is None or home != here(agent):
        return False, "you rest at home; out here, make_camp or sleep_rough"
    top = max_energy(world, agent)
    _resting(world, agent, "home", REST_H, top - agent.energy)
    return True, f"You rest at home for {REST_H:.0f} hours: back to {top:.0f} energy."


def make_camp(world: "World", log: "EventLog", agent: "Agent") -> tuple[bool, str]:
    ensure(world, agent)
    why = _check_still(agent)
    if why:
        return False, why
    if agent.inventory.get(CAMP_ITEM, 0) <= 0:
        return False, f"you have no {CAMP_ITEM} (a store sells them); you can sleep_rough"
    agent.remove_item(CAMP_ITEM, 1)
    _resting(world, agent, "camp", CAMP_H, CAMP_GAIN)
    return True, f"You pitch camp for {CAMP_H:.0f} hours: +{CAMP_GAIN:.0f} energy."


def sleep_rough(world: "World", log: "EventLog", agent: "Agent") -> tuple[bool, str]:
    ensure(world, agent)
    why = _check_still(agent)
    if why:
        return False, why
    _resting(world, agent, "rough", ROUGH_H, ROUGH_GAIN)
    return True, f"You sleep rough for {ROUGH_H:.0f} hours: +{ROUGH_GAIN:.0f} energy."


def meal(agent: "Agent", world: "World") -> None:
    """A meal puts a little back in your legs (separate from hunger)."""
    if agent.hex is not None:
        agent.energy = min(max_energy(world, agent), agent.energy + MEAL_GAIN)


def upgrade_home(world: "World", log: "EventLog", agent: "Agent", kind: str) -> tuple[bool, str]:
    if kind not in HOME_UPGRADES:
        return False, f"choose one of {', '.join(HOME_UPGRADES)}"
    if kind in agent.home_rest:
        return False, f"your home has a {kind} already"
    if not agent.home:
        return False, "you have no home to improve"
    add, price, what = HOME_UPGRADES[kind]
    if agent.denari < price:
        return False, f"a {kind} costs {price:.0f}; you have {agent.denari:.0f}"
    agent.denari -= price
    agent.home_rest.append(kind)
    log.emit(world.sim_time, "home_upgraded", actor=agent.id, location=agent.home, kind=kind, price=price)
    return True, f"Your home has a {kind} now ({what}). You can go {max_energy(world, agent):.0f} hexes between rests."


# -- explorers -----------------------------------------------------------------

def _home_hex(world: "World", owner: "Agent") -> H.Hex:
    return hex_of_place(world, owner.home) or (here(owner) if owner.hex else (0, 0))


def send(world: "World", log: "EventLog", owner: "Agent", member_id: str = "", target: list[int] | None = None,
         direction: str = "", days: float = 1.0, hired: bool = False) -> tuple[bool, str]:
    """Send a grown family member (or, `hired`, a scout for the trip) to a
    hex, or roaming one way for some days."""
    ensure(world, owner)
    if target is None and direction not in _COMPASS:
        return False, f"give a target hex, or a direction: {', '.join(_COMPASS)}"
    days = max(0.5, min(5.0, float(days or 1.0)))
    if hired:
        trip_days = days if target is None else max(1.0, math.ceil(2 * H.distance(_home_hex(world, owner), (target[0], target[1])) * STEP_S / 86400.0))
        cost = SCOUT_WAGE * trip_days
        if owner.denari < cost:
            return False, f"a scout for {trip_days:.0f} day{'s' if trip_days > 1 else ''} costs {cost:.0f}; you have {owner.denari:.0f}"
        owner.denari -= cost
        taken = {e.name for e in world.explorers.values()}
        name = next((n for n in SCOUT_NAMES if n not in taken), f"Scout {len(world.explorers) + 1}")
        member = ""
    else:
        m = next((m for m in owner.family if m.id == member_id), None)
        if m is None:
            return False, f"no one called {member_id!r} in your house"
        if not m.adult:
            return False, f"{m.name} is still a child"
        if any(e.member == m.id for e in world.explorers.values()):
            return False, f"{m.name} is out exploring already"
        _unrostered(world, owner, m)
        name, member = m.name, m.id
    start = _home_hex(world, owner)
    e = Explorer(id=world.new_id("X"), owner=owner.id, name=name, kind="hired" if hired else "family", member=member,
                 hex=[start[0], start[1]], energy=EXPLORER_ENERGY, max_energy=EXPLORER_ENERGY,
                 mode="target" if target is not None else "roam",
                 target=[int(target[0]), int(target[1])] if target is not None else None,
                 direction=direction, until=world.sim_time + days * 86400.0, started=world.sim_time,
                 busy_until=world.sim_time + STEP_S)
    world.explorers[e.id] = e
    log.emit(world.sim_time, "explorer_out", actor=owner.id, name=name, kind=e.kind, mode=e.mode,
             direction=direction, significance=Significance.LOW)
    where = f"to the spot you chose" if target is not None else f"roaming {direction} for {days:g} day{'s' if days != 1 else ''}"
    return True, f"{name} sets out {where}. What they see goes on your map."


def _unrostered(world: "World", owner: "Agent", m) -> None:
    """A member sent exploring is off whatever roster they were on."""
    from . import family as FAM
    if m.works_at and m.works_at in world.businesses:
        b = world.businesses[m.works_at]
        b.roster = [e for e in b.roster if e.agent_id != FAM.worker_id(m)]
    m.works_at = ""


def recall(world: "World", log: "EventLog", owner: "Agent", explorer_id: str) -> tuple[bool, str]:
    e = world.explorers.get(explorer_id)
    if e is None or e.owner != owner.id:
        return False, "no such explorer of yours"
    e.mode, e.target = "target", None
    e.until = world.sim_time
    return True, f"{e.name} turns for home."


def _step_dir(e: Explorer, h: H.Hex, owner: "Agent", world: "World", rng: random.Random) -> H.Hex | None:
    """Roaming: the next hex, keeping roughly to the direction, favouring
    ground nobody in the house has seen."""
    ang = math.radians(_COMPASS.get(e.direction, 0))
    want = (math.cos(ang), math.sin(ang))
    have = set(owner.explored)
    c0 = H.centre(h)
    best, bs = None, -1e9
    for nb in H.neighbours(h):
        if H.step_cost(world, nb) is None:
            continue
        c = H.centre(nb)
        d = ((c[0] - c0[0]) / H.ACROSS_M, (c[1] - c0[1]) / H.ACROSS_M)
        score = d[0] * want[0] + d[1] * want[1] + (0.8 if H.key(nb) not in have else 0.0) + rng.uniform(-0.35, 0.35)
        if score > bs:
            best, bs = nb, score
    return best


def tick_explorers(world: "World", log: "EventLog", rng: random.Random) -> None:
    for e in list(world.explorers.values()):
        owner = world.agents.get(e.owner)
        if owner is None or not owner.alive:
            world.explorers.pop(e.id, None)
            continue
        if world.sim_time < e.busy_until:
            continue
        if e.status == "camp":
            e.energy, e.status = e.max_energy, "out"
        h = (e.hex[0], e.hex[1])
        home = _home_hex(world, owner)
        going_home = (e.mode == "roam" and world.sim_time >= e.until) or (e.mode == "target" and e.target is None)
        if going_home and h == home:
            world.explorers.pop(e.id)
            log.emit(world.sim_time, "explorer_back", actor=owner.id, name=e.name, found=e.found,
                     significance=Significance.MEDIUM)
            continue
        if going_home:
            goal = home
        elif e.mode == "target":
            goal = (e.target[0], e.target[1])
            if h == goal:
                e.target = None
                e.busy_until = world.sim_time + STEP_S
                continue
        else:
            goal = None
        if goal is not None:
            p = H.path(h, goal, lambda x: H.step_cost(world, x), limit=1500)
            nxt = p[0] if p else None
        else:
            nxt = _step_dir(e, h, owner, world, rng)
        if nxt is None:
            e.target, e.mode = None, "target"          # nowhere to go: home
            e.busy_until = world.sim_time + STEP_S
            continue
        cost = H.step_cost(world, nxt) or 1
        if e.energy < cost:
            e.status, e.busy_until = "camp", world.sim_time + CAMP_H * 3600.0
            continue
        e.energy -= cost
        e.hex = [nxt[0], nxt[1]]
        e.found += reveal(world, owner, nxt)
        e.busy_until = world.sim_time + STEP_S


def view(world: "World", agent: "Agent") -> dict[str, Any]:
    """The player's map state, for the page."""
    ensure(world, agent)
    act = agent.activity
    out: dict[str, Any] = {
        "hex": agent.hex, "energy": round(agent.energy, 1), "max": max_energy(world, agent),
        "route": agent.route, "explored": agent.explored,
        "moving": ({"to": act.detail["to"], "from": act.detail.get("from"), "ends": act.ends_at,
                    "starts": act.ends_at - STEP_S} if act.kind == "move" else None),
        "resting": ({"where": act.detail.get("where"), "ends": act.ends_at, "gain": act.detail.get("gain")}
                    if act.kind in ("rest", "camp") else None),
        "homeward": ({"ends": act.ends_at} if act.kind == "homeward" else None),
        "home": list(hex_of_place(world, agent.home)) if agent.home and hex_of_place(world, agent.home) else None,
        "camp_supplies": agent.inventory.get(CAMP_ITEM, 0),
        "upgrades": agent.home_rest,
        "upgrades_for_sale": [{"kind": k, "adds": a, "price": p, "what": w} for k, (a, p, w) in HOME_UPGRADES.items()
                              if k not in agent.home_rest],
        "explorers": [{"id": e.id, "name": e.name, "kind": e.kind, "member": e.member, "hex": e.hex, "mode": e.mode, "status": e.status,
                       "direction": e.direction, "found": e.found, "target": e.target}
                      for e in world.explorers.values() if e.owner == agent.id],
        "terrain": _terrain_near(world, agent),
    }
    return out


def _terrain_near(world: "World", agent: "Agent") -> dict[str, str]:
    """What the found hexes and their edges are, where it is not open ground:
    the page's path preview needs to know water from mountain."""
    keys = set(agent.explored)
    for k in list(keys):
        for nb in H.neighbours(H.parse(k)):
            keys.add(H.key(nb))
    out = {}
    for k in keys:
        t = H.terrain(world, H.parse(k))
        if t != "open":
            out[k] = t[0]          # r(oad), m(ountain), w(ater), e(dge)
    return out
