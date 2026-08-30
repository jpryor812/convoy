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


def test_the_boards_assemble() -> None:
    """The spectator boards. One assembler, two consumers -- see `inspect`."""
    from convoy.state import Transaction

    world = setup()[0]
    for hour, item, qty, price in (
        (1, "Copper Ore", 50, 5.2), (2, "Copper Ore", 100, 4.9),
        (2, "Bronze", 10, 44.0),
    ):
        world.market.record(Transaction(hour * HOUR, item, qty, price, "B1", "B2"))
    world.sim_time = 3 * HOUR

    boards = I.boards(world, [])
    ok("every board is there",
       set(boards) == {"leaderboard", "commodities", "convoys", "advice"},
       str(sorted(boards)))

    lb = boards["leaderboard"]
    ok("every agent is on the leaderboard", len(lb) == len(world.agents))
    ok("richest first",
       [r["net_worth"] for r in lb] == sorted((r["net_worth"] for r in lb), reverse=True))
    for row in lb:
        parts = sum(row["assets"].values())
        ok(f"{row['name']}'s breakdown adds up to its rank",
           abs(parts - row["net_worth"]) < 0.02,
           f"{parts:.2f} vs {row['net_worth']:.2f}")

    prices = boards["commodities"]
    ok("the ticker reports what sold", {r["item"] for r in prices} == {"Copper Ore", "Bronze"},
       str([r["item"] for r in prices]))
    ore = next(r for r in prices if r["item"] == "Copper Ore")
    ok("volume-weighted, not a plain mean", ore["vwap"] < 5.05, f"vwap {ore['vwap']}")
    ok("busiest first", prices[0]["volume"] >= prices[-1]["volume"])
    ok("NOBODY is named in a public price feed",
       not ({"seller", "buyer"} & set(ore)), str(sorted(ore)))

    convoys = boards["convoys"]
    ok("the convoy board has both halves",
       set(convoys) == {"live", "history", "totals"}, str(sorted(convoys)))


def test_the_advice_report_separates_ignored_from_unheard() -> None:
    """The teaching artefact. Two failures that look identical from outside.

    "It ignored me" and "it never heard me" are different facts about the world,
    and only `times_seen` -- written by `observe` when text enters a prompt --
    tells them apart. Six recommendations once expired unseen (PHASE4 §2).
    """
    from convoy.state import Recommendation, Snapshot

    world = setup()[0]
    heard, deaf = list(world.agents.values())[:2]

    before = Snapshot(hour=1.0, net_worth={a.id: 100.0 for a in world.agents.values()})
    heard.inbox.append(Recommendation(
        id="R1", from_who="a student", text="buy a cart", given_at_hour=1.0,
        times_seen=3, first_seen_hour=1.2, before=before))
    deaf.inbox.append(Recommendation(
        id="R2", from_who="a student", text="found a mine", given_at_hour=1.0,
        times_seen=0, before=before))

    rows = {r["id"]: r for r in I.advice_report(world, [])}
    ok("both pieces of advice are reported", len(rows) == 2)
    ok("one was heard", rows["R1"]["heard"] is True)
    ok("and the other never reached a prompt", rows["R2"]["heard"] is False)
    ok("the unheard one says so rather than showing zero effect",
       rows["R2"]["times_seen"] == 0)

    r = rows["R1"]
    ok("it scores against the FIELD, not just itself",
       r["field_gained"] is not None and r["beat_field"] is not None,
       f"gained {r['gained']} field {r['field_gained']}")
    ok("beating the field is gain minus what everyone else managed",
       abs(r["beat_field"] - (r["gained"] - r["field_gained"])) < 0.01)
    ok("rank then and now are both reported",
       r["rank_then"] is not None and r["rank_now"] is not None)

    ok("a world nobody advised reports nothing",
       I.advice_report(setup()[0], []) == [])


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
