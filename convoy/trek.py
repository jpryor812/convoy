"""THE CONVOY: a long, dangerous trek with your goods (designer, 2026-11-01).

"Right now it just kind of feels like delivering goods is tedious, whereas I
wanted it to be the core action/event of the game ... it should be a pretty
long trek and every time, bandits come at you, and depending on how much
you're carrying, either more bandits or other players will come after you.
Make sure it's in the agent's logic that if they see a convoy with a lot of
goods, they should go try to rob it."

The player rides it in the 3D world (game3d/convoy.js), steering the whole
way; this module keeps the score, as combat.py does for a fight:

  * Leaving a place carrying MIN_VALUE or more is a convoy, set out with a
    destination (`start`). Fast travel with goods is refused (game.py).
  * Every convoy meets at least one ENCOUNTER on the way; the more it carries,
    the more of them and the bigger (`encounters`). Riders come for the rich
    loads. They wait at points along the route; the page reports how far
    along it you are (`progress`) and the next one reached becomes a fight
    (`fight_for`, then combat.py as any other fight).
  * Settlers who can see the road may come for it (`consider`, run hourly by
    the engine for every settler; LLM settlers can also choose to with the
    `rob_convoy` tool). They take one encounter's place, under their own
    names. Win and they run, dropping coin; lose and what they take is theirs.
  * Arriving at the destination ends it (`finish`); turning back too (`abort`).

Hired guards (actions.hire_escort) ride along and each takes on one foe.
"""

from __future__ import annotations

import math
import random
from typing import TYPE_CHECKING, Any

from . import claims as CL
from . import combat as CB
from . import data as D
from . import discovery as DS
from .events import Significance
from .state import Activity, Trek

if TYPE_CHECKING:
    from .events import EventLog
    from .state import Agent, World

# Any load at all is a convoy (the designer: "every time, bandits come at
# you"); how much it is worth, at book price, sets how hard.
MIN_VALUE = 1.0
ENCOUNTER_PER = 150.0          # one more encounter for each this much carried ...
MAX_ENCOUNTERS = 4
BANDITS_BASE = 2               # ... and bandits in each: 2, one more per BANDITS_PER
BANDITS_PER = 100.0
MAX_BANDITS = 6
RIDERS_FROM = 300.0            # riders (mounted, fast) come for loads worth this
RIDER_HP = 50.0
QUIET_BELOW = CB.AMBUSH_MIN_VALUE   # robbed down below this, the rest leave you be
# Settlers who come for it.
REACH_M = 2 * DS.SIGHT_M       # how far from the road they hear of a convoy
MAX_RAIDERS = 3
TEMPT_FROM = 80.0              # loads worth less tempt nobody
TEMPT_FULL = 480.0             # ... worth this tempt the most
TEMPT_MAX = 0.55               # chance an hour, at the most
FIT_TO_RAID = 40.0             # health a raider needs
RAIDER_SHARE_OF_PURSE = 0.1    # what a beaten raider drops


def cargo(world: "World", agent: "Agent") -> dict[str, int]:
    """The goods a convoy carries: everything in hand but weapons, armour,
    meals and camp kit, and any consignment being hauled for someone."""
    out = {i: q for i, q in agent.inventory.items()
           if q > 0 and i not in D.WEAPONS and i not in D.ARMOR and i not in D.MEALS
           and i not in D.PLAYER_ONLY_ITEMS}
    c = world.consignments.get(agent.hauling or "")
    if c is not None and agent.hauling_units > 0:
        out[c.item] = out.get(c.item, 0) + agent.hauling_units
    return out


def _book(item: str) -> float:
    try:
        return D.base_price(item)
    except KeyError:
        return 1.0


def value(world: "World", agent: "Agent") -> float:
    """What the load is worth at book price -- what bandits reckon it at."""
    return sum(_book(i) * q for i, q in cargo(world, agent).items())


def active(world: "World", agent: "Agent") -> Trek | None:
    t = world.treks.get(agent.id)
    return t if t is not None and t.status == "on" else None


def encounters(v: float, rng: random.Random) -> list[dict[str, Any]]:
    """Where along the road, and who: at least one, more and bigger with
    more carried, spread out so the trek is never quiet for long."""
    n = max(1, min(MAX_ENCOUNTERS, 1 + int(v // ENCOUNTER_PER)))
    size = max(BANDITS_BASE, min(MAX_BANDITS, BANDITS_BASE + int(v // BANDITS_PER)))
    out = []
    for i in range(n):
        at = (i + 1) / (n + 1) + rng.uniform(-0.06, 0.06)
        riders = v >= RIDERS_FROM and i % 2 == 1
        out.append({"at": round(max(0.15, min(0.92, at)), 3), "kind": "riders" if riders else "bandits",
                    "n": max(2, size - 1) if riders else size, "raiders": [], "done": ""})
    if v >= RIDERS_FROM and n == 1:
        out[0]["kind"] = "riders"
    return out


def straight_m(world: "World", origin: str, destination: str) -> float:
    a, b = CL.place_xy(world, origin), CL.place_xy(world, destination)
    return math.hypot(b[0] - a[0], b[1] - a[1]) if a and b else 0.0


def plan(world: "World", agent: "Agent", destination: str, route_m: float = 0.0) -> dict[str, Any]:
    """What setting out would mean, before you do: the length, the load and
    the danger. Changes nothing."""
    v = value(world, agent)
    line = straight_m(world, agent.location, destination)
    length = max(line, min(route_m or line * 1.3, line * 3)) if line else route_m
    n = max(1, min(MAX_ENCOUNTERS, 1 + int(v // ENCOUNTER_PER)))
    size = max(BANDITS_BASE, min(MAX_BANDITS, BANDITS_BASE + int(v // BANDITS_PER)))
    return {"destination": destination, "metres": round(length), "cargo": cargo(world, agent),
            "value": round(v, 2), "convoy": v >= MIN_VALUE, "attacks": n, "bandits": size,
            "riders": v >= RIDERS_FROM, "guards": len(agent.escorts),
            "danger": danger_line(n, size, v)}


def danger_line(n: int, size: int, v: float) -> str:
    who = "riders likely" if v >= RIDERS_FROM else "bandits on foot"
    if v >= TEMPT_FULL:
        who += "; settlers will hear of a load like this"
    return f"Expect {n} attack{'s' if n > 1 else ''} of about {size}; {who}."


def start(world: "World", log: "EventLog", agent: "Agent", destination: str,
          route_m: float, rng: random.Random) -> tuple[Trek | None, str]:
    if destination == agent.location:
        return None, "you are already there"
    if CL.place_xy(world, destination) is None:
        return None, f"{destination} is not a place you can ride to"
    # Only to places you have found on the map (convoy/journey.py).
    if agent.hex is not None and agent.explored:
        from . import journey as JY
        if not JY.found(agent, JY.hex_of_place(world, destination)):
            return None, f"you have not found {destination} yet: explore the map first"
    v = value(world, agent)
    if v < MIN_VALUE:
        return None, f"you carry {v:.0f} worth; a convoy is for {MIN_VALUE:.0f} or more"
    p = plan(world, agent, destination, route_m)
    t = Trek(id=world.new_id("T"), owner=agent.id, origin=agent.location, destination=destination,
             cargo=p["cargo"], value=p["value"], metres=float(p["metres"]), started=world.sim_time,
             encounters=encounters(v, rng), guards=len(agent.escorts))
    world.treks[agent.id] = t
    log.emit(world.sim_time, "convoy_set_out", actor=agent.id, location=agent.location,
             destination=destination, value=round(v, 1), attacks=len(t.encounters),
             significance=Significance.MEDIUM)
    return t, f"You set out for {destination} with {_goods(t.cargo)}, worth {v:.0f}."


def progress(world: "World", agent: "Agent", metres: float) -> dict[str, Any] | None:
    """How far along the road (reported by the page). Returns the encounter
    reached, if one is; it is then fought (`fight_for`)."""
    t = active(world, agent)
    if t is None:
        return None
    t.share = max(t.share, min(1.0, max(0.0, metres) / max(1.0, t.metres)))
    for enc in t.encounters:
        if not enc["done"] and enc["at"] <= t.share:
            enc["done"] = "on"
            return enc
    return None


def fight_for(world: "World", log: "EventLog", agent: "Agent", enc: dict[str, Any]) -> CB.Fight:
    """The encounter as a fight: bandits, riders, or settlers by name. Each
    hired guard takes one of them on, but someone always comes for you."""
    foes: list[CB.Foe] = []
    for rid in enc["raiders"]:
        r = world.agents.get(rid)
        if r is None or not r.alive:
            continue
        w = CB.weapon(r)
        foes.append(CB.Foe(rid, r.name, hp=60.0, max_hp=60.0, hit=CB.BANDIT_HIT * max(0.8, w.damage / 12.0), agent=rid))
    riders = enc["kind"] == "riders"
    for i in range(enc["n"] if not foes else max(0, enc["n"] - 2 - len(foes))):
        foes.append(CB.Foe(f"b{i}", "Rider" if riders else "Bandit", hp=RIDER_HP if riders else CB.BANDIT_HP,
                           max_hp=RIDER_HP if riders else CB.BANDIT_HP, mounted=riders))
    t = world.treks.get(agent.id)
    guards = t.guards if t else 0
    keep = max(1, len(foes) - guards)
    taken = len(foes) - keep
    foes = sorted(foes, key=lambda f: not f.agent)[:keep] if taken else foes
    enc["guarded"] = taken
    names = ", ".join(f.name for f in foes if f.agent)
    log.emit(world.sim_time, "convoy_ambushed", actor=agent.id, location=agent.location,
             foes=len(foes), riders=riders, raiders=list(enc["raiders"]), by=names,
             significance=Significance.MEDIUM)
    return CB.Fight("convoy", agent.location, foes, started=world.sim_time)


def settle(world: "World", log: "EventLog", agent: "Agent", f: CB.Fight, rng: random.Random) -> str:
    """The end of an encounter's fight: won, lost or got away."""
    t = world.treks.get(agent.id)
    enc = next((e for e in (t.encounters if t else []) if e["done"] == "on"), None)
    raiders = [world.agents[r] for r in (enc["raiders"] if enc else []) if r in world.agents]
    if enc is not None:
        enc["done"] = f.over or "fled"
    if f.over == "won":
        coins = CB.spoils(world, agent, f, rng)
        for r in raiders:
            drop = round(max(0.0, r.denari) * RAIDER_SHARE_OF_PURSE, 2)
            r.denari -= drop
            agent.denari += drop
            coins += drop
            r.stolen.clear()            # what they had taken before, they drop as they run
        if t:
            t.beaten += len(f.foes)
            t.coins += coins
        log.emit(world.sim_time, "convoy_beat_off", actor=agent.id, location=agent.location,
                 foes=len(f.foes), raiders=[r.id for r in raiders], coins=round(coins, 1),
                 significance=Significance.MEDIUM)
        who = _names(raiders)
        msg = (f"You beat off {who}. They dropped {coins:.0f} coins as they ran." if who else
               f"You beat them off. They dropped {coins:.0f} coins as they ran.")
    elif f.over == "lost":
        taken, coins = CB.take(world, agent)
        left = share_loot(world, [r.id for r in raiders], taken) if raiders else taken
        if t:
            t.lost = {i: t.lost.get(i, 0) + q for i, q in taken.items()}
            for i, q in taken.items():
                t.cargo[i] = max(0, t.cargo.get(i, 0) - q)
        log.emit(world.sim_time, "convoy_robbed", actor=agent.id, location=agent.location,
                 by=[r.id for r in raiders] or "bandits", items=taken, denari=coins,
                 significance=Significance.HIGH if raiders else Significance.MEDIUM)
        goods = _goods(taken) or "nothing you carried"
        who = _names(raiders) or "The bandits"
        msg = f"{who} knock you down and take {goods} and {coins:.0f} coins."
        del left
        # Robbed down to little, the road leaves you alone the rest of the way.
        if value(world, agent) < QUIET_BELOW and t:
            for e in t.encounters:
                if not e["done"]:
                    e["done"] = "quiet"
    else:
        msg = "You got away with the load."
    for r in raiders:
        _release(world, r)
    return msg


def finish(world: "World", log: "EventLog", agent: "Agent", place: str) -> str:
    """Arrived at the destination: the convoy is over. Returns the result line."""
    t = active(world, agent)
    if t is None or place != t.destination:
        return ""
    t.status = "arrived"
    t.ended = world.sim_time
    _end(world, t)
    agent.escorts.clear()
    now = cargo(world, agent)
    log.emit(world.sim_time, "convoy_arrived", actor=agent.id, location=place, origin=t.origin,
             items=now, beaten=t.beaten, lost=t.lost, significance=Significance.MEDIUM)
    parts = [f"Reached {place} with {_goods(now)}." if now else f"Reached {place}, the load gone."]
    if t.beaten:
        parts.append(f"Beat off {t.beaten}.")
    if t.coins:
        parts.append(f"Took {t.coins:.0f} coins.")
    if t.lost:
        parts.append(f"Lost {_goods(t.lost)} on the way.")
    return " ".join(parts)


def abort(world: "World", log: "EventLog", agent: "Agent") -> str:
    t = active(world, agent)
    if t is None:
        return "no convoy under way"
    t.status = "turned back"
    t.ended = world.sim_time
    _end(world, t)
    return "You turn the convoy back."


def _end(world: "World", t: Trek) -> None:
    for e in t.encounters:
        for rid in e["raiders"]:
            r = world.agents.get(rid)
            if r is not None:
                _release(world, r)


def _release(world: "World", r: "Agent") -> None:
    if r.activity.kind == "raid" and r.activity.detail.get("trek"):
        r.activity = Activity("idle", world.sim_time)


# -- settlers who come for it ---------------------------------------------------

def _near_road(world: "World", t: Trek, xy: tuple[float, float]) -> float:
    """Metres from `xy` to the convoy's way, as the line from origin to destination."""
    a, b = CL.place_xy(world, t.origin), CL.place_xy(world, t.destination)
    if not a or not b:
        return float("inf")
    vx, vy = b[0] - a[0], b[1] - a[1]
    l2 = vx * vx + vy * vy or 1.0
    k = max(0.0, min(1.0, ((xy[0] - a[0]) * vx + (xy[1] - a[1]) * vy) / l2))
    return math.hypot(xy[0] - a[0] - vx * k, xy[1] - a[1] - vy * k)


def friendly(world: "World", a: "Agent", b: "Agent") -> bool:
    """Kin, married-in houses, friends who swapped contacts, or group-mates:
    they do not rob each other's convoys."""
    if b.id in a.allies or a.id in b.allies:
        return True
    if "contact" in a.shared.get(b.id, []) and "contact" in b.shared.get(a.id, []):
        return True
    return any(a.id in g.members and b.id in g.members for g in world.groups.values())


def can_rob(world: "World", raider: "Agent", t: Trek) -> str:
    """Why `raider` cannot go for convoy `t`, or "" if they can."""
    owner = world.agents.get(t.owner)
    if t.status != "on" or owner is None:
        return "that convoy is not on the road"
    if raider.id == t.owner:
        return "that is your own convoy"
    if not raider.alive or raider.health < FIT_TO_RAID:
        return f"too hurt to go after anyone ({raider.health:.0f} health)"
    if raider.in_transit or raider.activity.kind in ("raid", "travel", "convoy"):
        return "you are busy on the road"
    if friendly(world, raider, owner):
        return f"{owner.name} is kin or a friend"
    if sum(len(e["raiders"]) for e in t.encounters) >= MAX_RAIDERS:
        return "enough are already after it"
    if not any(not e["done"] and e["at"] > t.share for e in t.encounters):
        return "it is nearly there; you would never catch it"
    at = DS.position(world, raider)
    if at is None or _near_road(world, t, at) > REACH_M:
        return "too far from its road"
    return ""


def join(world: "World", log: "EventLog", raider: "Agent", t: Trek) -> tuple[bool, str]:
    why = can_rob(world, raider, t)
    if why:
        return False, why
    enc = next(e for e in t.encounters if not e["done"] and e["at"] > t.share)
    enc["raiders"].append(raider.id)
    raider.activity = Activity("raid", world.sim_time + 6 * 3600.0, {"trek": t.id, "owner": t.owner})
    log.emit(world.sim_time, "convoy_raiders", actor=raider.id, location=raider.location,
             target=t.owner, value=round(t.value, 1), significance=Significance.MEDIUM)
    owner = world.agents[t.owner]
    return True, f"You ride out to wait for {owner.name}'s convoy on the road to {t.destination}."


def temptation(world: "World", raider: "Agent", t: Trek) -> float:
    """The chance an hour a settler who could go for it does: more for a
    richer load, for the poor, and for those who have robbed before."""
    v = value(world, world.agents[t.owner]) if t.owner in world.agents else t.value
    if v < TEMPT_FROM:
        return 0.0
    p = TEMPT_MAX * min(1.0, (v - TEMPT_FROM) / (TEMPT_FULL - TEMPT_FROM))
    p *= 1.4 if raider.denari < 100 else 1.0 if raider.denari < 600 else 0.5
    if raider.stolen:
        p *= 1.5
    return min(0.85, p)


def consider(world: "World", log: "EventLog", raider: "Agent", rng: random.Random) -> str | None:
    """A settler's own rule: a convoy with a lot on it, on a road they can
    reach, may be worth going for. Returns the trek joined, if any."""
    best, best_v = None, 0.0
    for t in world.treks.values():
        if t.status != "on" or can_rob(world, raider, t):
            continue
        if t.value > best_v:
            best, best_v = t, t.value
    if best is None or rng.random() >= temptation(world, raider, best):
        return None
    ok, _ = join(world, log, raider, best)
    return best.id if ok else None


def tick(world: "World", log: "EventLog", rng: random.Random) -> int:
    """Hourly: every settler but the player weighs the convoys on the road."""
    if not any(t.status == "on" for t in world.treks.values()):
        return 0
    n = 0
    for a in sorted(world.agents.values(), key=lambda a: a.id):
        if a.id == world.human or not a.alive:
            continue
        if consider(world, log, a, rng):
            n += 1
    return n


def on_the_road(world: "World", viewer: "Agent") -> list[dict[str, Any]]:
    """The convoys a settler could go for, for their observation."""
    out = []
    for t in world.treks.values():
        if t.status != "on" or t.owner == viewer.id:
            continue
        at = DS.position(world, viewer)
        if at is None or _near_road(world, t, at) > REACH_M:
            continue
        owner = world.agents.get(t.owner)
        out.append({"trek_id": t.id, "owner": owner.name if owner else t.owner, "to": t.destination,
                    "value": round(t.value), "guards": t.guards, "along": round(t.share, 2),
                    "friend": bool(owner and friendly(world, viewer, owner)),
                    "why_not": can_rob(world, viewer, t)})
    return out


def share_loot(world: "World", members: list[str], taken: dict[str, int]) -> dict[str, int]:
    """Deal a take round the raiders as stolen goods, one unit at a time, to
    whoever still has room. Returns what nobody could carry."""
    room = {m: max(0, world.agents[m].carry_capacity(world) - world.agents[m].carried_units())
            for m in members}
    left: dict[str, int] = {}
    i = 0
    for item, qty in taken.items():
        for _ in range(qty):
            placed = False
            for k in range(len(members)):
                m = members[(i + k) % len(members)]
                if room[m] > 0:
                    world.agents[m].add_stolen(item, 1)
                    room[m] -= 1
                    i = (i + k + 1) % len(members)
                    placed = True
                    break
            if not placed:
                left[item] = left.get(item, 0) + 1
    return left


def _goods(items: dict[str, int]) -> str:
    return ", ".join(f"{q} {i}" for i, q in items.items() if q > 0)


def _names(people: list["Agent"]) -> str:
    if not people:
        return ""
    if len(people) == 1:
        return people[0].name
    return f"{people[0].name} and {len(people) - 1} other{'s' if len(people) > 2 else ''}"
