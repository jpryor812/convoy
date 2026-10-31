"""Bandit gangs robbing buildings (designer request, 2026-10-30).

"Right now there is basically no conflict. I'm just sort of building and
selling. They should attack my buildings periodically." See GAME_MODES.md,
"Robbing buildings", step 1 of its build order:

  * A GANG of two to four bandits sets out from a hideout in the hills -- the
    foot of the nearest mountain -- and walks to a building.
  * Who is targeted follows MONEY AND DISTANCE: what is in the building's yard
    and purse, how far it is from any other building, and how many lookouts
    watch over it (`hourly_chance`).
  * The owner hears when the gang is SIGHTED -- half an hour out if lookouts
    are watching within range, otherwise when it reaches the door -- and the
    gang LOOTS for an hour.
  * Then it is RESOLVED: the gang's strength (cut by guard posts and catapults
    on the site) against the owner's lookouts on watch within range. With no
    one there, the building is robbed. Robbed, it loses 30-60% of its yard
    goods and of its purse; the coins you carry and your home are never taken.

Protections: nothing in a house's first six game hours (designer request,
2026-10-30, so a play session meets them), one robbery at a time per house and none within 12 game hours of
the last. Riding over to fight (step 2), hired guards (step 3) and AI settlers
robbing (step 4) come next.

Only worlds with outposts have gangs.
"""

from __future__ import annotations

import math
import random
from typing import TYPE_CHECKING, Any

from . import banditry as B
from . import data as D
from .events import Significance

if TYPE_CHECKING:
    from .events import EventLog
    from .state import Agent, Business, World

BASE_CHANCE = 0.008            # per building per game hour, before the factors below
VALUE_REF = 200.0              # yard + purse worth this is "1x" ...
VALUE_RANGE = (0.75, 4.0)      # ... between these bounds
REMOTE_RANGE = (0.8, 2.0)      # 0.8 + km to the nearest other building, clamped
LOOKOUT_DETERRENCE = 2.0       # each lookout in range divides the chance by 1 + this
GRACE_H = 6.0                  # nobody is robbed in their first six game hours
NEWCOMER_H = 24.0              # Agent.protected_until is set this long after arriving
COOLDOWN_H = 12.0              # between robberies of one house
GANG_SPEED_MPS = 1.6           # bandits walk
MAX_APPROACH_H = 2.0
SPOT_AHEAD_H = 0.5             # lookouts see a gang this long before it arrives
LOOT_H = 1.0                   # the hour you have to answer
LOSS_RANGE = (0.3, 0.6)        # share of yard goods and purse taken
KEEP_DONE_H = 6.0              # a finished robbery stays on the owner's alert this long
GANG_WEAPONS = ["Bat", "Bat", "Wooden Spear", "Bronze Dagger", "Bronze-Tipped Spear", "Bronze Sword"]
SECURITY = "Private Security Contractor"


def _xy(world: "World", place: str) -> tuple[float, float] | None:
    from . import claims as CL
    return CL.place_xy(world, place)


def yard_value(world: "World", biz: "Business") -> float:
    goods = sum(D.base_price(i) * q for i, q in biz.inventory.items() if q > 0 and i in D.ALL_ITEMS)
    return goods + max(0.0, biz.cash)


def lookouts_near(world: "World", owner: "Agent", place: str) -> list[str]:
    """The owner's lookouts on watch at a security firm within range of `place`."""
    at = _xy(world, place)
    if at is None:
        return []
    out = []
    for bid in owner.owned_businesses:
        b = world.businesses.get(bid)
        if b is None or b.closed or b.type != SECURITY:
            continue
        f = _xy(world, b.location)
        if f and math.hypot(f[0] - at[0], f[1] - at[1]) <= D.LOOKOUT_RANGE_M:
            out += [e.agent_id for e in b.production_staff()]
    return out


def _remote_km(world: "World", biz: "Business") -> float:
    """How far it is to the nearest other building or home, anyone's."""
    at = _xy(world, biz.location)
    if at is None:
        return 0.0
    places = {b.location for b in world.businesses.values() if not b.closed and b.id != biz.id}
    places |= {a.home for a in world.agents.values() if a.home}
    places.discard(biz.location)
    best = min((math.hypot(p[0] - at[0], p[1] - at[1])
                for p in (_xy(world, q) for q in places) if p), default=2000.0)
    return best / 1000.0


def hourly_chance(world: "World", biz: "Business") -> float:
    """The chance a gang sets out for this building in a game hour."""
    owner = world.agents.get(biz.owner)
    if owner is None:
        return 0.0
    v = min(VALUE_RANGE[1], max(VALUE_RANGE[0], yard_value(world, biz) / VALUE_REF))
    r = min(REMOTE_RANGE[1], max(REMOTE_RANGE[0], 0.8 + _remote_km(world, biz)))
    watch = 1.0 / (1.0 + LOOKOUT_DETERRENCE * len(lookouts_near(world, owner, biz.location)))
    return BASE_CHANCE * v * r * watch


def _eligible(world: "World", owner: "Agent") -> bool:
    now = world.sim_time
    # From the start of the game, or from a later arrival: protected_until is
    # a newcomer's whole first day, of which only the first GRACE_H count here.
    arrived = max(0.0, owner.protected_until - NEWCOMER_H * 3600.0)
    if not owner.alive or now < max(GRACE_H * 3600.0, arrived + GRACE_H * 3600.0):
        return False
    if now - owner.robbed_at < COOLDOWN_H * 3600.0:
        return False
    return not any(r.owner == owner.id and r.status in ("coming", "looting")
                   for r in world.robberies.values())


def _hideout(world: "World", at: tuple[float, float], rng: random.Random) -> tuple[float, float]:
    """The foot of the nearest mountain, on the side facing the building."""
    from . import layout as L
    best = None
    for m in L.mountains(list(world.cities)):
        dx, dy = at[0] - m["x"], at[1] - m["y"]
        d = math.hypot(dx, dy) or 1.0
        foot = (m["x"] + dx / d * m["r"], m["y"] + dy / d * m["r"])
        gap = math.hypot(foot[0] - at[0], foot[1] - at[1])
        if best is None or gap < best[0]:
            best = (gap, foot)
    if best is None:
        a = rng.uniform(0, 2 * math.pi)
        return at[0] + 1500 * math.cos(a), at[1] + 1500 * math.sin(a)
    return best[1]


def start(world: "World", log: "EventLog", biz: "Business", rng: random.Random) -> "Any":
    """Send a gang for `biz`."""
    from .state import Robbery
    owner = world.agents[biz.owner]
    at = _xy(world, biz.location) or (0.0, 0.0)
    home = _hideout(world, at, rng)
    value = yard_value(world, biz)
    n = 2 + (value > 400) + (value > 1000 and rng.random() < 0.5)
    gang = [rng.choice(GANG_WEAPONS) for _ in range(n)]
    now = world.sim_time
    walk = min(MAX_APPROACH_H * 3600.0, math.hypot(home[0] - at[0], home[1] - at[1]) / GANG_SPEED_MPS)
    arrives = now + max(600.0, walk)
    watched = bool(lookouts_near(world, owner, biz.location))
    r = Robbery(id=world.new_id("X"), business=biz.id, owner=owner.id, place=biz.location, gang=gang,
                hideout=[round(home[0], 1), round(home[1], 1)], set_out=now,
                sighted_at=max(now, arrives - SPOT_AHEAD_H * 3600.0) if watched else arrives,
                arrives_at=arrives, ends_at=arrives + LOOT_H * 3600.0)
    world.robberies[r.id] = r
    owner.robbed_at = now
    log.emit(now, "gang_set_out", actor=owner.id, subject=biz.id, location=biz.location,
             robbery=r.id, bandits=n)
    return r


def gang_strength(world: "World", r: "Any") -> float:
    bodies = sum(B.Escort("bandit", "Bodyguard", w, ()).strength for w in r.gang) or B.UNARMED_STRENGTH
    f = 1.0
    for q in world.plots.values():
        if q.structure and q.location == r.place and q.owner == r.owner:
            f *= D.DEFENSES.get(q.structure, {}).get("strength", 1.0)
    return bodies * max(D.DEFENSE_FLOOR, f)


def resolve(world: "World", log: "EventLog", r: "Any", rng: random.Random) -> None:
    """The hour is up: did the watch drive them off, or were they robbed?"""
    from . import raids as R
    biz = world.businesses.get(r.business)
    owner = world.agents.get(r.owner)
    if biz is None or biz.closed or owner is None:
        r.status = "beaten"
        r.outcome = {"why": "gone"}
        return
    watch = lookouts_near(world, owner, r.place)
    party = B.Party(tuple(B.Escort(w, "Scout", D.LOOKOUT_WEAPON, ()) for w in watch))
    strength = gang_strength(world, r)
    if watch and rng.random() >= R.p_raiders_win(strength, party):
        r.status = "beaten"
        r.outcome = {"lookouts": len(watch)}
        log.emit(world.sim_time, "robbery_beaten", actor=owner.id, subject=biz.id, location=r.place,
                 significance=Significance.HIGH, robbery=r.id, lookouts=len(watch), bandits=len(r.gang))
        return
    share = rng.uniform(*LOSS_RANGE)
    taken: dict[str, int] = {}
    for item, q in list(biz.inventory.items()):
        n = int(round(q * share))
        if n > 0:
            biz.remove_item(item, n)
            taken[item] = n
    cash = round(max(0.0, biz.cash) * share, 2)
    biz.cash -= cash
    r.status = "robbed"
    r.outcome = {"share": round(share, 2), "goods": taken, "cash": cash, "lookouts": len(watch)}
    log.emit(world.sim_time, "building_robbed", actor=owner.id, subject=biz.id, location=r.place,
             significance=Significance.HIGH, robbery=r.id, goods=taken, cash=cash,
             share=round(share, 2), lookouts=len(watch), bandits=len(r.gang))


def tick(world: "World", log: "EventLog", rng: random.Random, hour_passed: bool) -> None:
    """Move every robbery on, and once a game hour, see who is targeted."""
    if not world.outposts:
        return
    now = world.sim_time
    for r in list(world.robberies.values()):
        if r.status == "coming":
            # Seen early only by lookouts; otherwise you hear when they are at the door.
            if r.sighted_at <= now and r.sighted_at < r.arrives_at and not r.outcome.get("sighted"):
                r.outcome["sighted"] = True
                log.emit(now, "robbery_sighted", actor=r.owner, subject=r.business, location=r.place,
                         significance=Significance.HIGH, robbery=r.id, bandits=len(r.gang),
                         minutes=round(max(0.0, r.arrives_at - now) / 60))
            if r.arrives_at <= now:
                r.status = "looting"
                r.outcome["sighted"] = True
                log.emit(now, "robbery_started", actor=r.owner, subject=r.business, location=r.place,
                         significance=Significance.HIGH, robbery=r.id, bandits=len(r.gang),
                         minutes=round(LOOT_H * 60))
        if r.status == "looting" and r.ends_at <= now:
            resolve(world, log, r, rng)
        if r.status in ("robbed", "beaten") and now - r.ends_at > KEEP_DONE_H * 3600.0:
            del world.robberies[r.id]
    if not hour_passed:
        return
    for owner in list(world.agents.values()):
        if not _eligible(world, owner):
            continue
        mine = [world.businesses[b] for b in owner.owned_businesses
                if b in world.businesses and not world.businesses[b].closed]
        chances = [(b, hourly_chance(world, b)) for b in mine]
        for b, p in chances:
            if rng.random() < p:
                start(world, log, b, rng)
                break


def for_owner(world: "World", agent: "Agent") -> list[dict[str, Any]]:
    """What the owner knows of gangs coming for, robbing or having robbed
    their buildings: for the page and the agents' view."""
    from . import claims as CL
    now = world.sim_time
    out = []
    for r in world.robberies.values():
        if r.owner != agent.id or (r.status == "coming" and r.sighted_at > now):
            continue
        biz = world.businesses.get(r.business)
        at = CL.place_xy(world, r.place)
        out.append({"id": r.id, "business": r.business, "type": biz.type if biz else "", "place": r.place,
                    "status": r.status, "bandits": len(r.gang), "gang": list(r.gang),
                    "x": at[0] if at else None, "y": at[1] if at else None, "hideout": list(r.hideout),
                    "set_out": r.set_out, "arrives_at": r.arrives_at, "ends_at": r.ends_at,
                    "arrives_in_min": round(max(0.0, r.arrives_at - now) / 60),
                    "ends_in_min": round(max(0.0, r.ends_at - now) / 60),
                    "lookouts": len(lookouts_near(world, agent, r.place)),
                    "strength": round(gang_strength(world, r), 2),
                    "outcome": {k: v for k, v in r.outcome.items() if k != "sighted"}})
    return out
