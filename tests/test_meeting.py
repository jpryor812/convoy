#!/usr/bin/env python3
"""Meeting people (designer request, 2026-10-28; see convoy/social.py).

With outposts, finding someone only shows they exist. What else you know,
they share -- one kind at a time, given or asked for. Messages and group
chats need their contact; public chat is heard only nearby; a marriage needs
their family shared. Worlds without outposts are unchanged.
"""

from __future__ import annotations

import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from convoy import actions as A
from convoy import advisor as ADV
from convoy import claims as CL
from convoy import discovery as DS
from convoy import observe as O
from convoy import social as SO
from convoy import town as TOWN
from convoy.events import EventLog
from convoy.world_setup import new_world

FAILURES: list[str] = []


def ok(label, condition, detail="") -> None:
    if not condition:
        FAILURES.append(f"{label}{': ' + detail if detail else ''}")


class _S:
    model = "x/rule-based"
    outposts = True
    cities = {"aldermarch": 6, "cinderhold": 6, "thornwick": 6}


def _world(seed: int = 7):
    log = EventLog(None, echo_min=99)
    world = new_world(log, [], TOWN._rosters(_S), government=False, starter_sites=True)
    world.land_seed = seed
    TOWN.populate_outposts(world, log, random.Random(seed))
    return world, log


def _pair(world, log):
    """Two settlers who have found each other, and a third neither knows."""
    people = list(world.agents.values())
    a, b, c = people[0], people[1], people[2]
    for x in (a, b, c):
        x.known = []
    DS.meet(world, log, a, b, "Town")
    return a, b, c


def test_you_know_only_what_is_shared() -> None:
    world, log = _world()
    a, b, _ = _pair(world, log)
    v = SO.view_of(world, a, b)
    ok("found, nothing shared", v["found"] and v["shared"] == [], str(v["shared"]))
    ok("no standing, holdings or locations", not any(k in v for k in ("standing", "holdings", "locations")))
    okb, msg = A.share_info(world, log, b, a.id, "holdings")
    ok("sharing works", okb, msg)
    v = SO.view_of(world, a, b)
    ok("exactly that kind", v["shared"] == ["holdings"] and "holdings" in v and "standing" not in v, str(v))
    okb, _ = A.share_info(world, log, b, a.id, "holdings")
    ok("not twice", not okb)
    okb, msg = A.share_info(world, log, b, a.id, "secrets")
    ok("only the six kinds", not okb, msg)


def test_asking_and_answering() -> None:
    """The player answers by hand (2026-10-30): here `b` is the player."""
    world, log = _world()
    a, b, _ = _pair(world, log)
    world.human = b.id
    okb, msg = A.ask_info(world, log, a, b.id, "standing")
    ok("asked", okb, msg)
    rid = next(iter(world.share_requests))
    okb, _ = A.ask_info(world, log, a, b.id, "standing")
    ok("not asked twice while open", not okb)
    okb, _ = A.answer_request(world, log, a, rid, True)
    ok("only its target answers", not okb)
    okb, msg = A.answer_request(world, log, b, rid, True)
    ok("accepted", okb and SO.sees(world, a, b, "standing"), msg)
    A.ask_info(world, log, a, b.id, "family")
    rid2 = [r for r in world.share_requests if r != rid][0]
    A.answer_request(world, log, b, rid2, False)
    ok("declined shares nothing", not SO.sees(world, a, b, "family"))


def test_you_must_have_found_them() -> None:
    world, log = _world()
    a, _, c = _pair(world, log)
    for fn, args in ((A.say_hi, (c.id, "hello")), (A.share_info, (c.id, "standing")),
                     (A.ask_info, (c.id, "standing"))):
        okb, msg = fn(world, log, a, *args)
        ok(f"{fn.__name__} needs them found", not okb and "not found" in msg, msg)


def test_messages_and_groups_need_contact() -> None:
    world, log = _world()
    a, b, _ = _pair(world, log)
    okb, msg = A.send_direct_message(world, log, a, b.id, "hello")
    ok("no message without their contact", not okb and "contact" in msg, msg)
    okb, msg = A.say_hi(world, log, a, b.id, "hello neighbour")
    ok("but you can say hi", okb, msg)
    A.share_info(world, log, b, a.id, "contact")
    okb, msg = A.send_direct_message(world, log, a, b.id, "hello")
    ok("with it you can", okb, msg)
    okb, msg = A.make_group(world, log, a, "Riverside", b.id)
    gid = next(iter(world.groups))
    ok("a group with your contacts", okb and b.id in world.groups[gid].members, msg)
    okb, _ = A.post_group_chat(world, log, b, gid, "hi all")
    ok("members can post", okb)
    m = world.chat[-1]
    ok("members hear it", m.visible_to(a) and m.visible_to(b))
    ok("others do not", not any(m.visible_to(x) for x in world.agents.values() if x.id not in (a.id, b.id)))
    okb, msg = A.make_group(world, log, b, "B's", a.id)
    ok("you cannot add someone whose contact you lack", okb and a.id not in world.groups[list(world.groups)[-1]].members, msg)


def test_public_chat_is_heard_nearby() -> None:
    world, log = _world()
    a = next(iter(world.agents.values()))
    near = set(SO.hearers(world, a))
    A.post_world_chat(world, log, a, "anyone buying wheat?")
    m = world.chat[-1]
    for x in world.agents.values():
        if x.id == a.id:
            continue
        ok("heard by those near, and only them", m.visible_to(x) == (x.id in near), x.id)
    a.location = "Town"
    b = list(world.agents.values())[5]
    b.location = "Town"
    ok("at the same place you hear each other", b.id in SO.hearers(world, a))


def test_marriage_needs_family_shared() -> None:
    world, log = _world()
    a, b, _ = _pair(world, log)
    a.family[0].adult = True
    okb, msg = A.propose_marriage(world, log, a, b.id, a.family[1].id, b.family[1].id)
    ok("no proposal without their family", not okb and "family" in msg, msg)


def test_the_board_shows_only_who_shared_standing() -> None:
    world, log = _world()
    a, b, _ = _pair(world, log)

    class H:
        def back(self, n):
            return None
    board = ADV.leaderboard(world, a, H())
    ok("just you at first", [r["id"] for r in board["top"]] == [a.id])
    ok("ranked against everyone", board["population"] == len(world.agents))
    A.share_info(world, log, b, a.id, "standing")
    board = ADV.leaderboard(world, a, H())
    ok("then them too", {r["id"] for r in board["top"]} == {a.id, b.id})


def test_agents_are_told() -> None:
    world, log = _world()
    a, b, _ = _pair(world, log)
    world.human = a.id                      # requests wait only for the player
    A.ask_info(world, log, b, a.id, "trade")
    text = O.render(O.observe(world, log, a, "x", record_delivery=False))
    ok("who they found, without unshared detail", b.name in text and "no contact" in text)
    ok("requests to answer", "requests_to_you" in text and "asks for your trade" in text)


def _open_and_guarded(world):
    people = list(world.agents.values())[1:]            # the first is "me" 
    return (next(p for p in people if SO.temper(p) == "open"),
            next(p for p in people if SO.temper(p) == "guarded"))


def test_settlers_answer_at_once_by_rule() -> None:
    """Designer request, 2026-10-30: deterministic, and sometimes a price."""
    world, log = _world()
    me = list(world.agents.values())[0]
    world.human = me.id
    op, gu = _open_and_guarded(world)
    for o in (op, gu):
        DS.meet(world, log, me, o, "Town")
    okb, msg = A.ask_info(world, log, me, op.id, "standing")
    ok("standing is free, at once", okb and SO.sees(world, me, op, "standing"), msg)
    okb, msg = A.ask_info(world, log, me, op.id, "locations")
    ok("locations have a price", okb and "40 coins" in msg and not SO.sees(world, me, op, "locations"), msg)
    okb, msg = A.ask_info(world, log, me, gu.id, "holdings")
    ok("a guarded house wants paying even for its holdings", "coins" in msg and not SO.sees(world, me, gu, "holdings"), msg)
    t = SO.terms(world, gu, me, "locations")
    ok("and asks more", t["price"] == 60, str(t))
    ok("the same answer every time", SO.terms(world, gu, me, "locations") == t)
    A.share_info(world, log, me, op.id, "locations")
    ok("share yours, get theirs free", "free" in SO.terms(world, op, me, "locations"))
    ok("their card shows their price", "holdings" in SO.view_of(world, me, gu)["terms"])


def test_paying_for_information() -> None:
    world, log = _world()
    me = list(world.agents.values())[0]
    world.human = me.id
    _, gu = _open_and_guarded(world)
    DS.meet(world, log, me, gu, "Town")
    me.denari, gu.denari = 500.0, 500.0
    A.ask_info(world, log, me, gu.id, "locations")
    ok("their terms are on their card", "locations" in SO.view_of(world, me, gu)["terms"])
    okb, msg = A.offer_for_info(world, log, me, gu.id, "locations", coins=10)
    ok("too little is refused", not okb and not SO.sees(world, me, gu, "locations") and me.denari == 500.0, msg)
    okb, msg = A.offer_for_info(world, log, me, gu.id, "locations", coins=60)
    ok("their price buys it", okb and SO.sees(world, me, gu, "locations"), msg)
    ok("and the coins change hands", me.denari == 440.0 and gu.denari == 560.0, f"{me.denari} {gu.denari}")
    # Or in goods sold cheap: meals, which anyone will take.
    me.add_item("Meal", 10)
    t = SO.terms(world, gu, me, "holdings")
    g = t["goods"]
    ok("they name goods they would take cheap", g and g["item"] == "Meal" and g["you_have"] == 10, str(t))
    okb, msg = A.offer_for_info(world, log, me, gu.id, "holdings", item=g["item"], qty=g["qty"],
                                unit_price=g["unit"])
    ok("a cheap sale buys it", okb and SO.sees(world, me, gu, "holdings"), msg)
    ok("the goods go and are paid for", me.inventory.get("Meal", 0) == 10 - g["qty"]
       and abs(me.denari - (440.0 + g["qty"] * g["unit"])) < 0.01, f"{me.denari}")


def test_greeted_back_once_and_no_one_to_marry() -> None:
    world, log = _world()
    a, b, _ = _pair(world, log)
    okb, msg = A.say_hi(world, log, a, b.id, "hello")
    ok("they answer", okb and "answers" in msg, msg)
    okb, msg = A.say_hi(world, log, a, b.id, "hello again")
    ok("once", okb and "answers" not in msg, msg)
    for m in b.family:
        m.spouse, m.grown_at, m.adult = ("x" if m.role != "partner" else m.spouse), 0.0, m.adult
    ok("nobody to marry, no family shared", "no" in SO.terms(world, b, a, "family"))


def test_only_the_player_answers_by_hand() -> None:
    from convoy import schemas as S
    llm = {t["function"]["name"] for t in S.tool_schemas(outposts=True)}
    me = {t["function"]["name"] for t in S.tool_schemas(outposts=True, player=True)}
    ok("settlers are not given answer_request", "answer_request" not in llm and "offer_for_info" in llm)
    ok("the player is", "answer_request" in me)


def test_without_outposts_everyone_sees_everything() -> None:
    world, log = _world()
    world.outposts = False
    a, b, c = list(world.agents.values())[:3]
    ok("sees", SO.sees(world, a, c, "family") and SO.sees(world, a, c, "contact"))
    okb, msg = A.send_direct_message(world, log, a, c.id, "hello")
    ok("messages anyone", okb, msg)


def main() -> int:
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for t in tests:
        t()
    print(f"test_meeting.py: {len(tests)} tests, {len(FAILURES)} failures")
    for f in FAILURES:
        print(f"  FAIL {f}")
    return 1 if FAILURES else 0


if __name__ == "__main__":
    raise SystemExit(main())
