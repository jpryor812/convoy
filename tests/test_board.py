#!/usr/bin/env python3
"""The market board at the trading posts (designer request, 2026-10-31; see
convoy/board.py).

Open to everyone: a for-sale post holds the goods, a wanted post holds the
money; anyone may take either, part or all; the post keeps 2%; porters carry
the goods to the buyer's business; posts come down after a day with what is
left returned. Settlers other than the player trade there by rule.
"""

from __future__ import annotations

import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from convoy import actions as A
from convoy import board as BD
from convoy import claims as CL
from convoy import town as TOWN
from convoy.engine import Engine, EngineConfig
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


class Idle:
    def decide(self, world, agent, reason) -> None:
        return None


def _world(seed: int = 7):
    log = EventLog(None, echo_min=99)
    world = new_world(log, [], TOWN._rosters(_S), government=False, starter_sites=True)
    world.land_seed = seed
    TOWN.populate_outposts(world, log, random.Random(seed))
    return world, log


def _found(world, log, a, kind, output, seed=1):
    a.denari = max(a.denari, 1500.0)
    if kind == "Refinery":
        # Refineries stand only in a refinery district (convoy/territory.py).
        from convoy import territory as TR
        a.location = TR.district_places(world)[seed % len(TR.district_places(world))]
    else:
        x, y = CL.sample_sites(world, *CL.place_xy(world, a.home), random.Random(seed), n=1, near=90, far=400, who=a.id)[0]
        _, _, c = CL.claim(world, log, a, x, y, kind)
        a.location = c.name
    A.start_business(world, log, a, kind)
    b = world.businesses[a.owned_businesses[-1]]
    A.set_production(world, log, a, b.id, output)
    return b


def test_sell_and_buy_with_strangers() -> None:
    world, log = _world()
    a, b = list(world.agents.values())[:2]
    world.human = b.id
    farm = _found(world, log, a, "Farm", "Wheat")
    ref = _found(world, log, b, "Refinery", "Grain", seed=2)
    farm.add_item("Wheat", 50)
    okp, msg = A.board_post(world, log, a, "sell", "Wheat", 40, 2.5)
    ok("posted", okp, msg)
    ok("the goods are held at the post", farm.inventory.get("Wheat", 0) == 10)
    pid = next(iter(world.board))
    ok("anyone can see it", BD.view(world, b)["posts"][0]["id"] == pid)
    cash_a, cash_b = a.denari, b.denari
    okt, msg = A.board_take(world, log, b, pid, 30)
    ok("a stranger can buy", okt, msg)
    ok("paid, less the post's 2%", abs(b.denari - (cash_b - 75.0)) < 0.01 and abs(a.denari - (cash_a + 73.5)) < 0.01,
       f"{a.denari - cash_a} {b.denari - cash_b}")
    ok("ten are still up", world.board[pid].qty == 10)
    d = next(d for d in world.dispatches.values() if d.kind == "goods")
    ok("porters carry it to the business that uses it", d.business == ref.id and d.qty == 30)
    eng = Engine(world, log, Idle(), EngineConfig(speed=1e9))
    world.sim_time = d.arrives_at + 1
    eng._dispatches()
    ok("and it arrives", ref.inventory.get("Wheat", 0) == 30)
    eng.close()
    ok("the deal sets the going price", BD.going_price(world, "Wheat") == 2.5)
    ok("and is in the deals", BD.deals(world)[0]["qty"] == 30)
    okt, msg = A.board_take(world, log, a, pid)
    ok("not your own post", not okt, msg)


def test_wanted_holds_the_money() -> None:
    world, log = _world()
    a, b = list(world.agents.values())[:2]
    world.human = a.id
    _found(world, log, a, "Refinery", "Grain")
    cash = a.denari
    okp, msg = A.board_post(world, log, a, "buy", "Wheat", 20, 3.0)
    ok("a wanted post", okp and abs(a.denari - (cash - 60.0)) < 0.01, msg)
    pid = next(iter(world.board))
    okt, msg = A.board_take(world, log, b, pid, 5)
    ok("nobody sells what they have not got", not okt, msg)
    b.add_item("Wheat", 8)
    okt, msg = A.board_take(world, log, b, pid)
    ok("sell into it", okt and b.inventory.get("Wheat", 0) == 0 and world.board[pid].qty == 12, msg)
    okc, msg = A.board_cancel(world, log, a, pid)
    ok("take it down, the rest back", okc and abs(a.denari - (cash - 24.0)) < 0.01, f"{msg} {a.denari - cash}")


def test_posts_come_down_after_a_day() -> None:
    world, log = _world()
    a = next(iter(world.agents.values()))
    world.human = a.id
    farm = _found(world, log, a, "Farm", "Wheat")
    farm.add_item("Wheat", 30)
    A.board_post(world, log, a, "sell", "Wheat", 30, 9.0)
    world.sim_time += 25 * 3600.0
    BD.tick(world, log)
    ok("expired, the goods back", farm.inventory.get("Wheat", 0) == 30 and not BD.open_posts(world))


def test_settlers_trade_by_rule() -> None:
    world, log = _world()
    people = list(world.agents.values())
    world.human = people[-1].id
    farms = [_found(world, log, a, "Farm", "Wheat", seed=i) for i, a in enumerate(people[:3])]
    refs = [_found(world, log, a, "Refinery", "Grain", seed=10 + i) for i, a in enumerate(people[3:5])]
    for f in farms:
        f.add_item("Wheat", 60)
    n = BD.ai_tick(world, log, random.Random(1))
    n += BD.ai_tick(world, log, random.Random(2))
    ok("they post and deal on their own", n > 0, str(n))
    sold = [t for t in world.market.transactions if t.item == "Wheat"]
    ok("farms sell Wheat to refineries", sold, "no Wheat deals")
    ok("never for the player", not any(p.owner == world.human for p in world.board.values()))


def main() -> int:
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for t in tests:
        t()
    print(f"test_board.py: {len(tests)} tests, {len(FAILURES)} failures")
    for f in FAILURES:
        print(f"  FAIL {f}")
    return 1 if FAILURES else 0


if __name__ == "__main__":
    raise SystemExit(main())
