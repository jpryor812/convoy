"""Robbery by people: raids planned and joined by agents, resolved on the road.

Designer decision, 2026-10-16. The faceless dice-roll bandits of PHASE7 are
replaced by raiders who are agents: someone plans a raid on a road segment,
others join, and they lie in wait there with the weapons they actually own.
The odds come from the same three-stage model PHASE7 built -- concealment,
fighting strength, escape -- with real raiders where the dice used to be:

  1. SPOTTED. The convoy's scouts may see the ambush on bad cover and slip it.
  2. THE FIGHT. Raiders' strength (weapons and armour, summed, emboldened by
     the road's vantage) against the convoy's (traveller, escorts, the cart's
     own plating). A ratio, so neither side is ever certain.
  3. ESCAPE. Beaten, a fast vehicle on open ground may still outrun them.

Win, and the raiders take half to all of the load, split between them as
stolen goods. Lose the fight, and each raider may die -- likelier the more the
convoy outclassed them. A raider who dies loses what was on them: cargo, the
cart they rode, their weapons and armour. Cash and everything else they own
is kept (insurance against even that comes later).

Pure functions here; the engine applies the outcome.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from . import banditry as B
from . import world_map as M

if TYPE_CHECKING:
    from .state import Agent, Raid, World

RAID_MAX_HOURS = 12.0
# Chance a beaten raider dies, at the extreme where the convoy utterly
# outclasses them; scaled down by how close the fight was.
RAIDER_DEATH_BASE = 0.60


def segment_named(name: str) -> M.RoadSegment | None:
    return next((s for s in M.EVERY_SEGMENT if s.name == name), None)


def live_members(world: "World", raid: "Raid") -> list[str]:
    """Raiders still alive and still waiting on this raid's road."""
    out = []
    for aid in raid.members:
        a = world.agents.get(aid)
        if (a is not None and a.alive and a.activity.kind == "raid"
                and a.activity.detail.get("raid") == raid.id
                and a.activity.ends_at > world.sim_time):
            out.append(aid)
    return out


def waiting_on(world: "World", segment: str) -> list["Raid"]:
    """Raids lying in wait on this road right now, oldest first."""
    return sorted(
        (r for r in world.raids.values()
         if r.status == "waiting" and r.segment == segment
         and r.until > world.sim_time and live_members(world, r)),
        key=lambda r: r.created_at,
    )


def body_strength(agent: "Agent") -> float:
    """One person's fighting worth: their weapon, times their armour. The same
    measure as a hired guard's, so a raider and an escort compare fairly."""
    armor = tuple(v for v in agent.equipped_armor.values() if v)
    return B.Escort(agent.name, "Bodyguard", agent.equipped_weapon, armor).strength


def raid_strength(world: "World", members: list[str], segment: M.RoadSegment) -> float:
    bodies = sum(body_strength(world.agents[m]) for m in members) or B.UNARMED_STRENGTH
    return bodies * (1.0 + B.VANTAGE_WEIGHT * segment.vantage)


def p_spotted(segment: M.RoadSegment, party: B.Party) -> float:
    """Scouts strip cover. On open ground they see an ambush coming."""
    s = party.scouts
    return B.SCOUT_MAX_REDUCTION * s / (s + B.SCOUT_HALF) * (1.0 - segment.concealment)


def p_raiders_win(strength: float, party: B.Party) -> float:
    return strength / (strength + party.strength)


def p_death(strength: float, party: B.Party) -> float:
    """For each raider, when the convoy wins: the more outclassed, the deadlier."""
    return RAIDER_DEATH_BASE * party.strength / (strength + party.strength)
