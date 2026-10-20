"""Missions: a short chain of state jobs that teach the game and pay a bonus.

Designer decision, 2026-10-18. After a first farm the early game went quiet,
and a new player did not know the roads, the compass or a fight existed.
Three missions, one unlocking the next, each a system the game runs on:

  1. DELIVER YOUR FIRST HARVEST (an achievement): found a farm or a mine, then
     carry your own goods to a refinery on a delivery job. Done by itself the
     moment you hand them over. Teaches loading, the compass and the roads --
     with your own goods, which is the game, not borrowed state Wheat.
  2. CLEAR A BANDIT CAMP on a road near you. Teaches fighting -- your weapon,
     your armour -- with no other player at risk.
  3. DELIVER TO A CITIZEN (an achievement): complete a delivery to a citizen's
     business. Teaches the market between people, which is the real game.

Later, as repeatable work for the quiet hours (designer, 2026-10-18): the
state's own convoy jobs, escorting a convoy against bandits, and defending a
state refinery from a bandit raid. And exploration (designer, 2026-10-18):
cave dwellings and river diving, for rare weapons, armour and resources --
see GAME_MODES.md. Not built yet.

They are the player's, as the delivery runs are: the agents learn the same
things from their own briefing and need no tutorial.
"""

from __future__ import annotations

import random
from typing import TYPE_CHECKING, Any

from . import raids as R
from . import world_map as M
from .events import Significance

if TYPE_CHECKING:
    from .events import EventLog
    from .state import Agent, World

MISSIONS: list[dict[str, Any]] = [
    {"id": "harvest", "title": "Deliver your first harvest", "reward": 60.0, "auto": True,
     "does": "Found a farm or a mine, then take a delivery job (Market, Sell, Deliver it "
             "yourself) to carry your own goods to a refinery -- the state's or a citizen's. "
             "Done the moment you hand them over."},
    {"id": "bounty", "title": "Clear the bandit camp", "reward": 80.0,
     "does": "Bandits are camped beside a road near your town. Ride out and fight them: R swings "
             "your bat, hold F to block their blows. A better weapon and armour help; if you lose, "
             "you are hurt, not killed."},
    {"id": "citizen", "title": "Deliver to a citizen", "reward": 50.0, "auto": True,
     "does": "Take a delivery job to a citizen's business (Market, Sell, Deliver it yourself) "
             "and complete it. Citizens pay more than the state and need you more."},
]
BANDIT_STRENGTH = 0.12         # each bandit; a slingshot is about 0.29
ONBOARDING_EDGE = 0.15         # a first fight should usually be won


def by_id(mid: str) -> dict[str, Any] | None:
    return next((m for m in MISSIONS if m["id"] == mid), None)


def board(world: "World", agent: "Agent") -> list[dict[str, Any]]:
    """Each mission with its status: done, active, open, or locked."""
    out, unlocked = [], True
    extraction = any(world.businesses[b].type in ("Farm", "Mining Operation")
                     for b in agent.owned_businesses
                     if b in world.businesses and not world.businesses[b].closed)
    for m in MISSIONS:
        done = m["id"] in agent.missions_done
        active = bool(agent.mission and agent.mission.get("id") == m["id"])
        if done:
            status = "done"
        elif not unlocked:
            status = "locked"
        elif m.get("auto"):
            # An achievement: under way by itself once it can be done.
            status = "active" if (m["id"] != "harvest" or extraction) else "needs"
        else:
            status = "active" if active else "open"
        out.append({**m, "status": status})
        unlocked = unlocked and done
    return out


def is_active(world: "World", agent: "Agent", mid: str) -> bool:
    return any(r["id"] == mid and r["status"] == "active" for r in board(world, agent))


def _bounty_spot(world: "World", agent: "Agent") -> tuple[str, str] | None:
    """A road of the agent's town whose ends are not a market square."""
    city = world.city_of(agent)
    markets = {M.market_of(c) for c in world.cities}
    for seg in M.EVERY_SEGMENT:
        if M.city_of(seg.a) == city and M.city_of(seg.b) == city and not ({seg.a, seg.b} & markets):
            return seg.name, seg.a
    return None


def start(world: "World", log: "EventLog", agent: "Agent", mid: str) -> tuple[bool, str]:
    row = next((r for r in board(world, agent) if r["id"] == mid), None)
    if row is None:
        return False, "no such mission"
    if row["status"] == "done":
        return False, "you have done that one"
    if row["status"] == "locked":
        return False, "finish the one before it first"
    if row.get("auto"):
        return False, "this one needs no starting: it completes by itself when you do it"
    if agent.mission:
        return False, "you are on a mission already"
    city = world.city_of(agent)
    if mid == "bounty":
        spot = _bounty_spot(world, agent)
        if spot is None:
            return False, "no road near you for bandits to camp on"
        seg, place = spot
        agent.mission = {"id": "bounty", "segment": seg, "place": place, "bandits": 2}
        msg = f"Mission: bandits are camped at {place}, on {seg}. Ride there and drive them off."
    else:
        return False, "no such mission"
    log.emit(world.sim_time, "mission_started", actor=agent.id, mission=mid)
    return True, msg


def odds(world: "World", agent: "Agent") -> float:
    m = agent.mission or {}
    mine = R.body_strength(agent)
    theirs = BANDIT_STRENGTH * m.get("bandits", 2)
    return min(0.95, mine / (mine + theirs) + ONBOARDING_EDGE)


def attack(world: "World", log: "EventLog", agent: "Agent", rng: random.Random | None = None) -> tuple[bool, str]:
    m = agent.mission
    if not m or m.get("id") != "bounty":
        return False, "you are not hunting bandits"
    if agent.location != m["place"] or agent.in_transit:
        return False, f"the camp is at {m['place']}"
    p = odds(world, agent)
    roll = (rng or random.Random()).random()
    if roll < p:
        log.emit(world.sim_time, "bandits_cleared", actor=agent.id, location=agent.location,
                 significance=Significance.MEDIUM, chance=round(p, 2))
        return True, finish(world, log, agent, "bounty", f"You drove the bandits off ({p:.0%} odds).")
    agent.health = max(10.0, agent.health - 25.0)
    log.emit(world.sim_time, "bandits_won", actor=agent.id, location=agent.location, chance=round(p, 2))
    return False, (f"The bandits beat you back ({p:.0%} odds). You are hurt but alive: "
                   f"catch your breath, find a better weapon, and try again.")


def finish(world: "World", log: "EventLog", agent: "Agent", mid: str, lead: str = "") -> str:
    row = by_id(mid)
    reward = row["reward"] if row else 0.0
    agent.denari += reward
    if mid not in agent.missions_done:
        agent.missions_done.append(mid)
    agent.mission = None
    log.emit(world.sim_time, "mission_done", actor=agent.id, significance=Significance.MEDIUM,
             mission=mid, reward=reward)
    nxt = next((r for r in board(world, agent) if r["status"] == "open"), None)
    return (f"{lead} Mission done: {row['title'] if row else mid}, +{reward:.0f}."
            + (f" Next: {nxt['title']}." if nxt else " That was the last one -- the valley is yours.")).strip()


def abandon(world: "World", log: "EventLog", agent: "Agent") -> str:
    m = agent.mission
    if not m:
        return "No mission to give up."
    d = agent.delivery
    if d and d.get("mission"):
        if d.get("loaded"):                     # the state's goods go back to the state
            agent.remove_item(d["item"], min(d["qty"], agent.inventory.get(d["item"], 0)))
        agent.delivery = None
    agent.mission = None
    return "Mission given up; you can start it again from the Missions page."
