"""Households: a citizen's first workers, and how a family grows.

Designer decision, 2026-10-18. Starting as one person with 300 coins in a
crowded square was overwhelming: everything was open at once and nothing was
yours. Now every citizen heads a HOUSE (a dynasty name) with a small household:

  * one grown relative, who works any business of the house's, unpaid and
    always on shift -- your first worker before you ever hire;
  * one child, who comes of age on a timer (the egg that hatches).

A family does not grow by itself. New children are born only to a MARRIED
couple, and a marriage joins two houses: you propose one of your grown
members to one of another house's, offering a dowry; if they accept, their
member joins your household and the two houses are ALLIES. So population and
strength are made by diplomacy -- and a town's houses marrying into each
other is how a town knits together.

If a citizen dies with a grown member in the house, that heir takes over: the
businesses, land and vehicles stay in the family (what was carried is still
lost). See `engine._kill`.

Family members are scripted, never a model call, so a household costs nothing
to run.
"""

from __future__ import annotations

import random
from typing import TYPE_CHECKING

from . import data as D
from .events import Significance
from .state import Employment, FamilyMember

if TYPE_CHECKING:
    from .events import EventLog
    from .state import Agent, World

# A GAME MONTH (designer decision, 2026-10-18): a couple has a child a month,
# and a newborn takes a month to be old enough to work -- a day sooner for every
# Meal you feed it. Children are how a house gets workers without hiring.
MONTH_HOURS = 30 * 24.0
GROW_UP_HOURS = MONTH_HOURS
CHILD_EVERY_HOURS = MONTH_HOURS
FEED_HOURS = 24.0             # one Meal brings a child a day closer
HOUSEHOLD_CAP = 6             # people in a household, the head not counted
KINSHIP_EXTRA = 2
# The household a citizen starts with: a partner, and a son and a daughter
# nearly grown, so a new house can marry its children off within days.
START_SON_HOURS = 36.0
START_DAUGHTER_HOURS = 48.0
HEAD = "__head__"             # a partner's `spouse`: married to the head of the house

FIRST_NAMES = [
    "Ada", "Bram", "Cora", "Dagny", "Edwin", "Fenna", "Gideon", "Hester", "Ivo", "Jessa",
    "Kael", "Lise", "Mattias", "Nell", "Osric", "Pella", "Quill", "Rhea", "Silas", "Tamsin",
    "Ulric", "Vera", "Wynn", "Ysolde", "Zeb", "Alma", "Brin", "Calla", "Dorian", "Elke",
    "Faro", "Greta", "Hollis", "Ilse", "Jory", "Kit", "Lark", "Mira", "Nils", "Orla",
]
HOUSE_NAMES = [
    "Ashcombe", "Blackwood", "Carrow", "Dunmore", "Elsworth", "Fairbairn", "Greyhallow",
    "Hartwell", "Ironside", "Jessop", "Kestrel", "Larkspur", "Merriweather", "Northgate",
    "Oakhurst", "Pennwick", "Quarrington", "Redmayne", "Stonebridge", "Thistlewood",
    "Underhill", "Vance", "Whitlock", "Yardley", "Ambrose", "Brightwater", "Coldharbour",
    "Draycott", "Easterly", "Fennimore", "Goodall", "Holloway", "Kingsley", "Lockwood",
    "Marlowe", "Nettleton", "Pemberton", "Ravenscroft", "Sallow", "Tremaine",
]


def cap(agent: "Agent") -> int:
    return HOUSEHOLD_CAP + (KINSHIP_EXTRA if "kinship" in agent.tech else 0)


def child_every(agent: "Agent") -> float:
    return CHILD_EVERY_HOURS * (0.75 if "kinship" in agent.tech else 1.0)


def _name(world: "World", rng: random.Random) -> str:
    return rng.choice(FIRST_NAMES)


MALE_NAMES = ["Bram", "Edwin", "Gideon", "Ivo", "Kael", "Mattias", "Osric", "Quill", "Silas", "Ulric",
              "Wynn", "Zeb", "Dorian", "Faro", "Hollis", "Jory", "Nils", "Tobin", "Rowan", "Aldric"]
FEMALE_NAMES = ["Ada", "Cora", "Dagny", "Fenna", "Hester", "Jessa", "Lise", "Nell", "Pella", "Rhea",
                "Tamsin", "Vera", "Ysolde", "Alma", "Calla", "Elke", "Greta", "Ilse", "Mira", "Orla"]


def _named(rng: random.Random, sex: str) -> str:
    return rng.choice(MALE_NAMES if sex == "m" else FEMALE_NAMES)


def found_household(world: "World", agent: "Agent", rng: random.Random | None = None,
                    sex: str = "", partner_sex: str = "") -> None:
    """A house name, a partner, a son and a daughter. Idempotent.

    `sex` and `partner_sex` are the player's choice ("m"/"f"); an agent's are
    dealt at random."""
    if agent.house:
        return
    rng = rng or random.Random(hash((world.land_seed, agent.id)) & 0xFFFFFFFF)
    taken = {a.house for a in world.agents.values() if a.house}
    free = [h for h in HOUSE_NAMES if f"House {h}" not in taken] or HOUSE_NAMES
    agent.house = f"House {rng.choice(free)}"
    agent.sex = sex or agent.sex or rng.choice("mf")
    kinds = list(D.CALLINGS)
    now = world.sim_time
    partner = FamilyMember(
        id=world.new_id("F"), name="", adult=True, born_at=now - 1.0,
        calling=rng.choice(kinds), sex=partner_sex or rng.choice("mf"), role="partner",
        spouse=HEAD, next_child_at=now + CHILD_EVERY_HOURS * 3600.0)
    partner.name = _named(rng, partner.sex)
    son = FamilyMember(id=world.new_id("F"), name=_named(rng, "m"), adult=False, born_at=now,
                       grown_at=now + START_SON_HOURS * 3600.0, calling=rng.choice(kinds),
                       sex="m", role="son")
    daughter = FamilyMember(id=world.new_id("F"), name=_named(rng, "f"), adult=False, born_at=now,
                            grown_at=now + START_DAUGHTER_HOURS * 3600.0, calling=rng.choice(kinds),
                            sex="f", role="daughter")
    agent.family += [partner, son, daughter]


def feed(agent: "Agent", m: "FamilyMember", now: float) -> float:
    """Feed a child a Meal: a day closer to grown. Returns hours left."""
    m.grown_at = max(now, m.grown_at - FEED_HOURS * 3600.0)
    return max(0.0, (m.grown_at - now) / 3600.0)


def member(agent: "Agent", member_id: str) -> FamilyMember | None:
    return next((m for m in agent.family if m.id == member_id), None)


def worker_id(m: FamilyMember) -> str:
    """How a family member appears on a business's roster."""
    return f"family:{m.id}"


def leave_work(world: "World", m: FamilyMember) -> None:
    if m.works_at:
        biz = world.businesses.get(m.works_at)
        if biz:
            biz.roster = [e for e in biz.roster if e.agent_id != worker_id(m)]
        m.works_at = ""


def keep_at_work(world: "World", m: FamilyMember) -> None:
    """A member at work stays on that business's roster. Anything that drops
    them from it (it happened: payroll sacked a 0-wage hand as unpaid) is
    undone here, and a closed business sends them home."""
    if not m.works_at:
        return
    biz = world.businesses.get(m.works_at)
    if biz is None or biz.closed or not biz.spec.production_roles:
        m.works_at = ""
        return
    if not any(e.agent_id == worker_id(m) for e in biz.roster):
        biz.roster.append(Employment(worker_id(m), biz.spec.production_roles[0], 0.0, is_npc=True))


def tick(world: "World", log: "EventLog") -> None:
    """Children come of age; married couples have children."""
    now = world.sim_time
    for agent in world.agents.values():
        if not agent.alive or not agent.family:
            continue
        for m in agent.family:
            keep_at_work(world, m)
        for m in list(agent.family):
            if not m.adult and m.grown_at and now >= m.grown_at:
                m.adult = True
                log.emit(now, "came_of_age", actor=agent.id, significance=Significance.MEDIUM,
                         member=m.id, name=m.name, house=agent.house)
        for m in list(agent.family):
            if not (m.adult and m.spouse and m.next_child_at and now >= m.next_child_at):
                continue
            if len(agent.family) >= cap(agent):
                m.next_child_at = now + child_every(agent) * 3600.0
                continue
            spouse = member(agent, m.spouse) if m.spouse != HEAD else None
            rng = random.Random(hash((m.id, now)) & 0xFFFFFFFF)
            other_calling = agent.calling if m.spouse == HEAD else (spouse.calling if spouse else "")
            calling = rng.choice([c for c in (m.calling, other_calling) if c] or list(D.CALLINGS))
            sex = rng.choice("mf")
            child = FamilyMember(id=world.new_id("F"), name=_named(rng, sex), adult=False,
                                 born_at=now, grown_at=now + GROW_UP_HOURS * 3600.0,
                                 calling=calling, sex=sex, role="son" if sex == "m" else "daughter")
            agent.family.append(child)
            m.next_child_at = now + child_every(agent) * 3600.0
            log.emit(now, "child_born", actor=agent.id, significance=Significance.MEDIUM,
                     member=child.id, name=child.name, house=agent.house,
                     parents=[m.name, agent.name if m.spouse == HEAD else (spouse.name if spouse else "")])


def succession(world: "World", agent: "Agent") -> FamilyMember | None:
    """On a death: the eldest grown member takes over the house, or None."""
    heirs = [m for m in agent.family if m.adult]
    if not heirs:
        return None
    heir = min(heirs, key=lambda m: m.born_at)
    leave_work(world, heir)
    if heir.spouse and heir.spouse != HEAD:
        sp = member(agent, heir.spouse)
        if sp:
            sp.spouse = ""
            sp.next_child_at = 0.0
    agent.family.remove(heir)
    return heir


def give_donkey(world: "World", agent: "Agent") -> None:
    """Everyone starts with a donkey, mounted (2026-10-18). Idempotent."""
    from .state import VehicleInstance
    if agent.owned_vehicles:
        return
    v = VehicleInstance(id=world.new_id("V"), type="Donkey", owner=agent.id, location=agent.location)
    world.vehicles[v.id] = v
    agent.owned_vehicles.append(v.id)
    agent.mounted_vehicle = v.id

