"""Projects and know-how: things that finish in a while, sooner if you push.

Designer request, 2026-10-18: Civ's pyramids take 50 turns, add production
and they take 20 -- and several things are always about to land: a tech next
turn, a building in two, a milestone in five. Waiting is the fun when it is
waiting FOR something you chose and can hurry.

PROJECTS are built at a business, one at a time. Work goes in every hour: one
unit for the contractor, one for each person on shift there (family
included), and more for every unit of the project's material in the yard,
which is used up. So "Storehouse: ready in 9h" becomes 4h with a crew and a
stack of Lumber.

KNOW-HOW is a citizen's own tech tree. One tech is studied at a time; it
advances a research-hour every game hour (faster with Ledgers), so a first
tech lands in six hours and a third-tier one in a day. Each says what it is
worth before you choose it.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from . import data as D
from .events import Significance

if TYPE_CHECKING:
    from .events import EventLog
    from .state import Agent, Business, World


# ---------------------------------------------------------------------------
# PROJECTS
# ---------------------------------------------------------------------------

PROJECTS: dict[str, dict[str, Any]] = {
    "Storehouse": {
        "work": 12.0, "cost": 40.0, "material": "Lumber", "per_unit": 1.0, "max": 3,
        "does": "Holds half as much again: a full yard stops production, a taller one does not.",
    },
    "Better tools": {
        "work": 20.0, "cost": 60.0, "material": "Lumber", "per_unit": 1.0, "max": 3,
        "does": "Makes everything here 10% faster, for good -- and smokier and harder on the ground.",
    },
    # Depletion and pollution (2026-10-18). See convoy/ground.py.
    "Crop rotation": {
        "for": ("Farm",), "work": 16.0, "cost": 50.0, "material": "Lumber", "per_unit": 1.0, "max": 2,
        "does": "The soil tires a third slower.",
    },
    "Manure pits": {
        "for": ("Farm",), "work": 12.0, "cost": 40.0, "material": "Hide", "per_unit": 1.0, "max": 1,
        "does": "Gives back a quarter of the soil now, and a resting field recovers twice as fast.",
    },
    "Hedgerows": {
        "for": ("Farm",), "work": 10.0, "cost": 35.0, "material": "Lumber", "per_unit": 1.0, "max": 2,
        "does": "Shelters the crop: foul air does half the harm here.",
    },
    "Timbered shafts": {
        "for": ("Mining Operation",), "work": 18.0, "cost": 60.0, "material": "Lumber", "per_unit": 1.0, "max": 2,
        "does": "The seam lasts longer: it is worked out 30% slower.",
    },
    "Deeper shaft": {
        "for": ("Mining Operation",), "work": 30.0, "cost": 120.0, "material": "Cut Stone", "per_unit": 1.0, "max": 2,
        "does": "Reaches fresh ore: gives back half a seam, even to a worked-out mine.",
    },
    "Tall chimney": {
        "for": ("Refinery", "Mining Operation"), "work": 16.0, "cost": 70.0, "material": "Fired Brick",
        "per_unit": 1.0, "max": 2,
        "does": "Carries the smoke off: this place fouls the air 40% less.",
    },
}


def available(biz: "Business") -> list[str]:
    """The projects this kind of business can build."""
    return [k for k, v in PROJECTS.items() if biz.type in v.get("for", (biz.type,))]
MATERIAL_PER_HOUR = 4          # most material a project can use in an hour


def project_cost(biz: "Business", kind: str) -> float:
    """Each level costs half again the last."""
    done = biz.improvements.get(kind, 0)
    return round(PROJECTS[kind]["cost"] * (1.5 ** done), 2)


def project_work(biz: "Business", kind: str) -> float:
    done = biz.improvements.get(kind, 0)
    return PROJECTS[kind]["work"] * (1.25 ** done)


def project_rate(world: "World", biz: "Business", owner: "Agent | None") -> tuple[float, float]:
    """(work per hour without material, extra per hour from material on hand)."""
    crew = 0
    for emp in biz.roster:
        if emp.is_npc:
            crew += 1
            continue
        a = world.agents.get(emp.agent_id)
        if a and a.alive and a.activity.kind == "work" and a.activity.detail.get("business") == biz.id:
            crew += 1
    rate = 1.0 + crew
    if owner is not None and "masonry" in owner.tech:
        rate *= 1.25
    spec = PROJECTS.get((biz.project or {}).get("kind", ""), {})
    mat = spec.get("material")
    extra = 0.0
    if mat:
        extra = min(MATERIAL_PER_HOUR, biz.inventory.get(mat, 0)) * spec.get("per_unit", 1.0)
    return rate, extra


def eta_hours(world: "World", biz: "Business", owner: "Agent | None") -> float | None:
    p = biz.project
    if not p:
        return None
    rate, extra = project_rate(world, biz, owner)
    left = max(0.0, p["total"] - p["done"])
    return left / max(0.1, rate + extra)


def tick_projects(world: "World", log: "EventLog", hours: float) -> None:
    for biz in world.businesses.values():
        p = biz.project
        if not p or biz.closed:
            continue
        owner = world.agents.get(biz.owner)
        rate, _extra = project_rate(world, biz, owner)
        spec = PROJECTS[p["kind"]]
        work = rate * hours
        mat = spec.get("material")
        if mat and biz.inventory.get(mat, 0) > 0:
            # Whole units only: a unit is used when an hour's share of it is.
            p["material_credit"] = p.get("material_credit", 0.0) + MATERIAL_PER_HOUR * hours
            use = min(int(p["material_credit"]), biz.inventory.get(mat, 0))
            if use > 0:
                biz.remove_item(mat, use)
                p["material_credit"] -= use
                work += use * spec.get("per_unit", 1.0)
        p["done"] = min(p["total"], p["done"] + work)
        if p["done"] >= p["total"] - 1e-9:
            _finish(world, log, biz, p["kind"])


def _finish(world: "World", log: "EventLog", biz: "Business", kind: str) -> None:
    biz.project = None
    biz.improvements[kind] = biz.improvements.get(kind, 0) + 1
    if kind == "Storehouse":
        biz.storage_tier += 1
    from . import ground as GR
    GR.improved(biz, kind)
    log.emit(world.sim_time, "project_done", actor=biz.owner, subject=biz.id,
             location=biz.location, significance=Significance.MEDIUM,
             project=kind, level=biz.improvements[kind])


def tools_bonus(biz: "Business") -> float:
    return 1.0 + 0.10 * biz.improvements.get("Better tools", 0)


# ---------------------------------------------------------------------------
# KNOW-HOW: the tech tree
# ---------------------------------------------------------------------------
#
# The era is the eve of the railroad (designer direction, 2026-10-18): the
# tree climbs from pack saddles to barges and canal locks, and ends at steam.

TECHS: dict[str, dict[str, Any]] = {
    # Tier 1: six hours each, nothing needed.
    "irrigation": {"name": "Irrigation", "tier": 1, "hours": 6, "needs": [],
                   "does": "Your farms grow 10% faster."},
    "picks": {"name": "Iron picks", "tier": 1, "hours": 6, "needs": [],
              "does": "Your mines dig 10% faster."},
    "bellows": {"name": "Bellows", "tier": 1, "hours": 6, "needs": [],
                "does": "Your refineries refine 10% faster."},
    "hearth": {"name": "Brick hearths", "tier": 1, "hours": 6, "needs": [],
               "does": "Your taverns, smithies, stables and stores make 10% faster."},
    "saddles": {"name": "Pack saddles", "tier": 1, "hours": 6, "needs": [],
                "does": "You carry 10% more."},
    # Tier 2: twelve hours, one tier-1 tech first.
    "masonry": {"name": "Masonry", "tier": 2, "hours": 12, "needs_any": ["irrigation", "picks", "bellows", "hearth"],
                "does": "Your projects build 25% faster."},
    "ledgers": {"name": "Ledgers", "tier": 2, "hours": 12, "needs_any": ["irrigation", "picks", "bellows", "hearth", "saddles"],
                "does": "You learn 25% faster."},
    "kinship": {"name": "Kinship", "tier": 2, "hours": 12, "needs_any": ["hearth", "irrigation"],
                "does": "Room for two more in your household, and children come sooner."},
    "barges": {"name": "River barges", "tier": 2, "hours": 12, "needs": ["saddles"],
               "does": "You may sail a River Barge between the towns' quays: 150 units, no road, no raiders."},
    # Tier 3: a day.
    "locks": {"name": "Canal locks", "tier": 3, "hours": 24, "needs": ["barges", "masonry"],
              "does": "Your barge sails twice as fast."},
    "charter": {"name": "Guild charter", "tier": 3, "hours": 24, "needs": ["ledgers"],
                "does": "Your businesses make 5% more for every ally your house has, up to 25%."},
    # The milestone.
    "steam": {"name": "Steam", "tier": 4, "hours": 48, "needs": ["locks", "charter"],
              "does": "Everything you own makes 15% more. The railroad is coming."},
}


def can_study(agent: "Agent", tech: str) -> tuple[bool, str]:
    t = TECHS.get(tech)
    if t is None:
        return False, f"no such know-how {tech!r}"
    if tech in agent.tech:
        return False, "you know it already"
    missing = [n for n in t.get("needs", []) if n not in agent.tech]
    if missing:
        return False, "first learn " + " and ".join(TECHS[m]["name"] for m in missing)
    if t.get("needs_any") and not any(n in agent.tech for n in t["needs_any"]):
        return False, "first learn one of " + ", ".join(TECHS[m]["name"] for m in t["needs_any"])
    return True, ""


def research_rate(agent: "Agent") -> float:
    return 1.25 if "ledgers" in agent.tech else 1.0


def research_eta(agent: "Agent") -> float | None:
    r = agent.researching
    if not r:
        return None
    return max(0.0, TECHS[r["tech"]]["hours"] - r["done"]) / research_rate(agent)


def tick_research(world: "World", log: "EventLog", hours: float) -> None:
    for a in world.agents.values():
        r = a.researching
        if not r or not a.alive:
            continue
        r["done"] += hours * research_rate(a)
        if r["done"] >= TECHS[r["tech"]]["hours"] - 1e-9:
            a.tech.append(r["tech"])
            a.researching = None
            log.emit(world.sim_time, "tech_learned", actor=a.id, significance=Significance.MEDIUM,
                     tech=r["tech"], name=TECHS[r["tech"]]["name"])


_TYPE_TECH = {"Farm": "irrigation", "Mining Operation": "picks", "Refinery": "bellows"}


def production_bonus(world: "World", biz: "Business", owner: "Agent | None") -> float:
    """Everything know-how and projects add to one business's rate."""
    mult = tools_bonus(biz)
    if owner is None:
        return mult
    tech = _TYPE_TECH.get(biz.type) or ("hearth" if biz.type in D.STORE_BUSINESS_TYPES else None)
    if tech and tech in owner.tech:
        mult *= 1.10
    if "charter" in owner.tech:
        mult *= 1.0 + min(0.25, 0.05 * len(owner.allies))
    if "steam" in owner.tech:
        mult *= 1.15
    return mult


def carry_bonus(agent: "Agent") -> float:
    return 1.10 if "saddles" in agent.tech else 1.0
