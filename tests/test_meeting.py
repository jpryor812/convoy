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
    world, log = _world()
    a, b, _ = _pair(world, log)
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
    A.ask_info(world, log, b, a.id, "trade")
    text = O.render(O.observe(world, log, a, "x", record_delivery=False))
    ok("who they found, without unshared detail", b.name in text and "no contact" in text)
    ok("requests to answer", "requests_to_you" in text and "asks for your trade" in text)


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
