"""Fighting with your own hands: the player's bat against bandits.

Designer request, 2026-10-18: "every character should start with a bat and use
that to attack bandits and defend itself from attackers ... R should be the
attack button and F should be the block button when someone attacks you."

The page plays the fight -- the bandits close in, wind up and swing; you swing
back (R) or raise your guard (F) -- and this module keeps the score, so a page
cannot simply declare a win:

  * your swing lands for your WEAPON's damage, no faster than its attack speed;
  * a bandit's blow costs you HEALTH, cut by your armour, and by four fifths if
    you were blocking;
  * drop to KNOCKED_DOWN and the fight is lost: at a camp you are beaten back
    (try again), on the road the bandits take a share of what you carry;
  * run far enough and you get away with everything.

Two kinds of fight, both against NPC bandits so no other player is at risk:

  CAMP    the bounty mission's camp (convoy/missions.py). Win and the mission
          is done.
  AMBUSH  on the open road, carrying goods. The page asks now and then while
          you are out between places; the chance grows with what you carry,
          and never while you are new or in your first hours after one.

Health comes back slowly while you are fed (`regen`), for everyone.

Not built yet (noted): another CITIZEN attacking you in person. The agents'
raids still happen on the timed roads (convoy/raids.py), as before.
"""

from __future__ import annotations

import random
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from . import data as D
from . import economy as E
from .events import Significance

if TYPE_CHECKING:
    from .events import EventLog
    from .state import Agent, World

BANDIT_HP = 40.0               # a Bat (12) takes four swings
BANDIT_HIT = 7.0               # one bandit's blow, before armour
BLOCKED_SHARE = 0.2            # what gets through a block
KNOCKED_DOWN = 15.0            # health at which the fight is lost
FIT_TO_FIGHT = 40.0            # health needed to go at a camp
CRIT_CHANCE = 0.12
AMBUSH_COOLDOWN_H = 2.0        # game hours between road ambushes
AMBUSH_MAX_P = 0.08            # per check (the page asks every few seconds)
AMBUSH_VALUE_SCALE = 4000.0    # chance per check = value carried / this
# Designer request, 2026-10-30: "when I'm trading more than $50 worth of
# goods ... I should be targeted" -- not every time. And from the third game
# hour, not after the newcomer's whole first day, which no play-test reached.
AMBUSH_MIN_VALUE = 50.0
AMBUSH_GRACE_H = 3.0
ROAD_LOSS_SHARE = 0.5          # of each good carried, on a lost road fight
COIN_LOSS_SHARE = 0.1
REGEN_PER_HOUR = 4.0           # health a fed citizen gets back an hour


@dataclass
class Foe:
    id: str
    name: str
    hp: float = BANDIT_HP
    max_hp: float = BANDIT_HP
    hit: float = BANDIT_HIT


@dataclass
class Fight:
    kind: str                  # "camp" or "ambush"
    place: str
    foes: list[Foe] = field(default_factory=list)
    started: float = 0.0       # sim time
    last_swing: float = 0.0    # wall clock, for the weapon's attack speed
    over: str = ""             # "", "won", "lost", "fled"

    def live(self) -> list[Foe]:
        return [f for f in self.foes if f.hp > 0]


def weapon(agent: "Agent") -> D.Weapon:
    return D.WEAPONS.get(agent.equipped_weapon) or D.WEAPONS["Bat"]


def armour(agent: "Agent") -> float:
    """The share of a blow your armour stops, capped short of all of it."""
    return min(0.75, sum(D.ARMOR[a].damage_reduction for a in agent.equipped_armor.values()
                         if a and a in D.ARMOR))


def carried_value(world: "World", agent: "Agent") -> float:
    return E.realizable_value(world, agent.inventory, world.city_of(agent))


def view(f: Fight | None, agent: "Agent") -> dict[str, Any] | None:
    if f is None:
        return None
    w = weapon(agent)
    return {"kind": f.kind, "place": f.place, "over": f.over,
            "foes": [{"id": x.id, "name": x.name, "hp": round(x.hp, 1), "max": x.max_hp} for x in f.foes],
            "you": {"hp": round(agent.health, 1), "down_at": KNOCKED_DOWN, "weapon": w.name,
                    "damage": w.damage, "swing": w.attack_speed, "armour": round(armour(agent), 2)}}


def start_camp(world: "World", agent: "Agent", n: int) -> Fight:
    return Fight("camp", agent.location, [Foe(f"bandit{i}", "Bandit") for i in range(n)],
                 started=world.sim_time)


def road_check(world: "World", log: "EventLog", agent: "Agent", last_ambush: float,
               rng: random.Random | None = None) -> Fight | None:
    """Out on the open road: are you set upon? Called by the page every few
    seconds while you are between places."""
    if not agent.alive or world.sim_time < AMBUSH_GRACE_H * 3600.0:
        return None
    if world.sim_time - last_ambush < AMBUSH_COOLDOWN_H * 3600.0:
        return None
    value = carried_value(world, agent)
    if value < AMBUSH_MIN_VALUE:
        return None
    p = min(AMBUSH_MAX_P, value / AMBUSH_VALUE_SCALE)
    if (rng or random.Random()).random() >= p:
        return None
    n = 2 if value > 250 else 1
    log.emit(world.sim_time, "ambushed", actor=agent.id, location=agent.location,
             significance=Significance.MEDIUM, bandits=n, carried=round(value, 1))
    return Fight("ambush", agent.location, [Foe(f"bandit{i}", "Bandit") for i in range(n)],
                 started=world.sim_time)


def swing(world: "World", log: "EventLog", agent: "Agent", f: Fight, foe_id: str,
          rng: random.Random | None = None, now: float | None = None) -> tuple[bool, str]:
    """Your swing at one foe. Returns (landed, what happened)."""
    if f.over:
        return False, "the fight is over"
    foe = next((x for x in f.foes if x.id == foe_id and x.hp > 0), None)
    if foe is None:
        return False, "nobody there"
    w = weapon(agent)
    now = time.monotonic() if now is None else now
    if now - f.last_swing < w.attack_speed * 0.8:
        return False, "too soon"
    f.last_swing = now
    crit = (rng or random.Random()).random() < CRIT_CHANCE
    dmg = w.damage * (w.crit_mult if crit else 1.0)
    foe.hp = max(0.0, foe.hp - dmg)
    line = f"{'Crushing blow! ' if crit else ''}-{dmg:.0f}" + (" -- down!" if foe.hp <= 0 else "")
    if not f.live():
        f.over = "won"
        log.emit(world.sim_time, "fight_won", actor=agent.id, location=agent.location,
                 significance=Significance.MEDIUM, kind=f.kind, bandits=len(f.foes))
    return True, line


def struck(world: "World", log: "EventLog", agent: "Agent", f: Fight, foe_id: str,
           blocked: bool) -> tuple[float, str]:
    """A foe's blow lands on you (or on your guard). Returns (damage, line)."""
    if f.over:
        return 0.0, ""
    foe = next((x for x in f.foes if x.id == foe_id and x.hp > 0), None)
    if foe is None:
        return 0.0, ""
    dmg = foe.hit * (1.0 - armour(agent)) * (BLOCKED_SHARE if blocked else 1.0)
    agent.health = max(KNOCKED_DOWN, agent.health - dmg)
    if agent.health <= KNOCKED_DOWN:
        f.over = "lost"
        log.emit(world.sim_time, "fight_lost", actor=agent.id, location=agent.location,
                 significance=Significance.MEDIUM, kind=f.kind)
    return dmg, ("Blocked" if blocked else f"-{dmg:.0f}")


def rob(world: "World", log: "EventLog", agent: "Agent", rng: random.Random | None = None) -> str:
    """A lost road fight: the bandits take a share of each good and some coin."""
    rng = rng or random.Random()
    taken: dict[str, int] = {}
    for item, qty in list(agent.inventory.items()):
        if item in D.WEAPONS or item in D.ARMOR:
            continue
        n = int(round(qty * ROAD_LOSS_SHARE))
        if n > 0 and agent.remove_item(item, n):
            taken[item] = n
    coins = round(agent.denari * COIN_LOSS_SHARE, 2)
    agent.denari -= coins
    log.emit(world.sim_time, "robbed", actor=agent.id, location=agent.location,
             significance=Significance.MEDIUM, by="bandits", items=taken, denari=coins)
    goods = ", ".join(f"{q} {i}" for i, q in taken.items()) or "nothing you carried"
    return f"The bandits knock you down and take {goods} and {coins:.0f} coins."


def spoils(world: "World", agent: "Agent", f: Fight, rng: random.Random | None = None) -> float:
    """What beaten road bandits leave behind."""
    coins = float((rng or random.Random()).randint(5, 15) * len(f.foes))
    agent.denari += coins
    return coins


def regen(world: "World", hours: float) -> None:
    """Health comes back slowly to anyone fed."""
    for a in world.agents.values():
        if a.alive and a.health < 100.0 and a.sustenance_stage == "Normal":
            a.health = min(100.0, a.health + REGEN_PER_HOUR * hours)
