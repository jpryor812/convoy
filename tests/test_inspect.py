#!/usr/bin/env python3
"""What a viewer sees when they click something.

These panels are the only part of the simulation most people will ever read, so
the failure that matters is not an exception -- it is a panel that renders
perfectly and says nothing. Every assertion here is that a field which HAS a
value in the world actually reaches the card.

The hour-zero map is all empty shelves and idle agents, which is honest and
proves nothing, so this builds a world with stock on the shelf, a wage being
paid, a job going begging and two agents of unequal wealth.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from convoy import inspect as I
from convoy import world_map as M
from convoy.events import EventLog
from convoy.state import Agent, Business, Employment, JobPosting, World

FAILURES: list[str] = []
HOUR = 3600.0


def ok(label: str, cond: bool, detail: str = "") -> None:
    if not cond:
        FAILURES.append(f"{label}{': ' + detail if detail else ''}")


def check(label: str, actual, expected) -> None:
    if actual != expected:
        FAILURES.append(f"{label}: got {actual!r}, expected {expected!r}")


def setup():
    w = World()
    w.sim_time = 30 * HOUR

    owner = Agent(id="A0001", name="Mara", model="m1", location="Town")
    owner.denari = 900.0
    hand = Agent(id="A0002", name="Bel", model="m2", location=M.SPURS[0].name)
    hand.denari = 40.0
    idler = Agent(id="A0003", name="Cass", model="m3", location="Town")
    idler.denari = 5.0
    for a in (owner, hand, idler):
        w.agents[a.id] = a

    biz = Business(id="B0001", type="Farm", name="Mara's Farm", owner=owner.id,
                   location=M.SPURS[0].name, cash=310.0, plots=8)
    biz.inventory = {"Grain": 42, "Hardwood": 7}
    # Grain is priced and Hardwood is not -- stock nobody can buy is a real
    # state and the card has to distinguish it.
    biz.retail_prices = {"Grain": 6.5}
    biz.active_production = "Grain"
    biz.roster.append(Employment(agent_id=hand.id, role="Farmhand", wage=14.0))
    w.businesses[biz.id] = biz
    owner.owned_businesses.append(biz.id)

    # The employee is out on the road, not at their post.
    hand.activity.kind = "travel"
    hand.in_transit = ("Town", "Refinery Row", 0.4)
    owner.activity.kind = "work"
    owner.activity.detail = {"role": "Farmhand"}

    w.job_postings["J1"] = JobPosting(
        id="J1", business_id=biz.id, owner=owner.id, role="Farmhand",
        wage=17.5, posted_at=28 * HOUR, expires_at=40 * HOUR,
        applicants=["A0003"],
    )
    # An expired posting must NOT show: a card advertising a job nobody can
    # take sends an agent walking across the valley for nothing.
    w.job_postings["J2"] = JobPosting(
        id="J2", business_id=biz.id, owner=owner.id, role="Miner",
        wage=99.0, posted_at=1 * HOUR, expires_at=2 * HOUR,
    )
    return w, biz, owner, hand, idler


def test_business_card_carries_the_shelf():
    w, biz, _o, _h, _i = setup()
    card = I.business_card(w, biz)

    check("owner named", card["owner"], "Mara")
    check("not the state", card["government"], False)
    check("what it is making", card["producing"], "Grain")
    check("land reported", card["plots"], 8)

    stock = {s["item"]: s for s in card["stock"]}
    check("priced stock carries its price", stock["Grain"]["price"], 6.5)
    check("quantity carried", stock["Grain"]["qty"], 42)
    check("unpriced stock says so", stock["Hardwood"]["price"], None)


def test_business_card_says_where_the_staff_actually_are():
    """A roster is not a register of who is at their post."""
    w, biz, _o, _h, _i = setup()
    card = I.business_card(w, biz)

    check("one on the payroll", len(card["staff"]), 1)
    hand = card["staff"][0]
    check("named", hand["who"], "Bel")
    check("wage", hand["wage"], 14.0)
    ok("reports the employee is on the road, not at work",
       "travelling" in hand["doing"], hand["doing"])
    ok("the owner's own activity is reported",
       card["owner_doing"] == "working as Farmhand", str(card["owner_doing"]))


def test_only_live_jobs_are_advertised():
    w, biz, _o, _h, _i = setup()
    card = I.business_card(w, biz)

    check("one live posting", len(card["jobs"]), 1)
    job = card["jobs"][0]
    check("the live one", job["role"], "Farmhand")
    check("wage advertised", job["wage"], 17.5)
    check("applicants counted", job["applicants"], 1)
    ok("hours open computed", job["hours_open"] > 0, str(job["hours_open"]))


def test_agent_card_ranks_by_net_worth():
    """The number alone says nothing: 900 denari is winning or losing."""
    w, _b, owner, hand, idler = setup()
    ranks = I.rankings(w)

    rich = I.agent_card(w, owner, ranks)
    poor = I.agent_card(w, idler, ranks)
    check("richest is first", rich["rank"], 1)
    check("out of everyone alive", rich["of"], 3)
    ok("poorest ranks last", poor["rank"] == 3, str(poor["rank"]))
    ok("owning a business counts toward net worth",
       rich["net_worth"] > rich["denari"],
       f"{rich['net_worth']} vs cash {rich['denari']}")

    check("business listed", len(rich["businesses"]), 1)
    check("business named", rich["businesses"][0]["name"], "Mara's Farm")

    employed = I.agent_card(w, hand, ranks)
    check("employment shown from the worker's side",
          len(employed["employed_by"]), 1)
    check("the wage they are on", employed["employed_by"][0]["wage"], 14.0)
    ok("travel progress reported", employed["travel_progress"] == 0.4,
       str(employed["travel_progress"]))


def test_the_dead_do_not_rank():
    w, _b, _o, _h, idler = setup()
    idler.alive = False
    ranks = I.rankings(w)
    check("only the living are ranked", len(ranks), 2)
    ok("the dead are absent", idler.id not in ranks)


def test_cards_covers_everything_clickable():
    """The page embeds this whole dict and looks things up by id."""
    w, biz, owner, _h, _i = setup()
    cards = I.cards(w)
    ok("the business has a card", biz.id in cards)
    ok("the agent has a card", owner.id in cards)
    check("every card declares what it is",
          {c["kind"] for c in cards.values()}, {"business", "agent"})


def test_it_matches_the_live_feed():
    """`live.status` and these panels must not phrase the same activity twice."""
    from convoy import live as LV
    w, _b, owner, hand, _i = setup()
    check("the phrasing is shared", LV.inspect_mod.doing_phrase, I.doing_phrase)
    ok("a working agent reads as working",
       I.doing_phrase(owner).startswith("working as"))
    ok("a travelling agent names its destination",
       "Refinery Row" in I.doing_phrase(hand))


def main() -> int:
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in tests:
        fn()
    print(f"Ran {len(tests)} inspection tests.")
    if FAILURES:
        print(f"\nFAIL ({len(FAILURES)})")
        for f in FAILURES:
            print(f"  - {f}")
        return 1
    print("Panels carry what the world knows.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
