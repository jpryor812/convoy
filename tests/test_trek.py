#!/usr/bin/env python3
"""The convoy (designer, 2026-11-01; see convoy/trek.py).

Leaving with goods is a convoy; every convoy is attacked at least once, more
and harder the more it carries; riders come for rich loads; settlers who can
see the road may come for it under their own names -- but not for a friend's
or a poor load; a lost fight hands goods to them, a won one makes them pay;
arriving ends it; fast travel with goods is refused.
"""

from __future__ import annotations

import contextlib
import random
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from convoy import checkpoint as CK
from convoy import claims as CL
from convoy import combat as CB
from convoy import discovery as DS
from convoy import town as TOWN
from convoy import trek as TK
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


def _dest(world, who):
    """Somewhere a few kilometres off: another settler's home."""
    import math
    me = CL.place_xy(world, who.home)
    others = [a for a in world.agents.values() if a.id != who.id and a.home]
    return min(others, key=lambda a: abs(2500 - math.dist(me, CL.place_xy(world, a.home)))).home


def test_every_convoy_is_attacked_more_with_more() -> None:
    rng = random.Random(1)
    small, big = TK.encounters(30, rng), TK.encounters(600, rng)
    ok("at least one, even for a little", len(small) >= 1)
    ok("more for more", len(big) > len(small), f"{len(small)} vs {len(big)}")
    ok("and bigger", max(e["n"] for e in big) > max(e["n"] for e in small))
    ok("no riders for a little", all(e["kind"] == "bandits" for e in small))
    ok("riders for a rich load", any(e["kind"] == "riders" for e in big))
    ok("spread along the road", all(0.1 < e["at"] < 0.95 for e in big)
       and sorted(e["at"] for e in big) == [e["at"] for e in big])


def test_set_out_ride_and_arrive() -> None:
    world, log = _world()
    you = next(iter(world.agents.values()))
    world.human = you.id
    you.inventory.clear()
    you.location = you.home
    dest = _dest(world, you)
    ok("nothing carried is no convoy", TK.start(world, log, you, dest, 0, random.Random(1))[0] is None)
    you.add_item("Wheat", 75)
    t, msg = TK.start(world, log, you, dest, 0, random.Random(1))
    ok("set out", t is not None and t.status == "on", msg)
    ok("as long as the road at least", t.metres >= TK.straight_m(world, you.location, dest) - 1)
    enc = TK.progress(world, you, t.metres * (t.encounters[0]["at"] + 0.01))
    ok("bandits reached on the way", enc is not None and enc["done"] == "on")
    f = TK.fight_for(world, log, you, enc)
    ok("a convoy fight", f.kind == "convoy" and len(f.foes) >= 1)
    for foe in f.foes:
        foe.hp = 0
    f.over = "won"
    cash = you.denari
    msg = TK.settle(world, log, you, f, random.Random(2))
    ok("beat them off, coins dropped", you.denari > cash and "beat" in msg.lower(), msg)
    TK.progress(world, you, t.metres)
    line = TK.finish(world, log, you, dest)
    ok("arriving ends it", t.status == "arrived" and "Reached" in line, line)
    ok("not at somewhere else on the way", TK.finish(world, log, you, dest) == "")


def test_guards_take_one_each_but_someone_comes() -> None:
    world, log = _world()
    you = next(iter(world.agents.values()))
    you.inventory.clear(); you.add_item("Wheat", 200); you.location = you.home
    t, _ = TK.start(world, log, you, _dest(world, you), 0, random.Random(1))
    t.guards = 20
    enc = TK.progress(world, you, t.metres)
    f = TK.fight_for(world, log, you, enc)
    ok("someone always comes", len(f.foes) == 1, str(len(f.foes)))


def _neighbours(world, you, n=3):
    """Settlers stood right on `you`'s road, armed and fit."""
    me = CL.place_xy(world, you.home)
    for a in world.agents.values():
        world.positions[a.id] = (-1e6, -1e6)       # everyone else well away
    out = []
    for a in world.agents.values():
        if a.id == you.id:
            continue
        world.positions[a.id] = (me[0] + 50 * (len(out) + 1), me[1])
        a.health = 100.0
        a.denari = 40.0
        out.append(a)
        if len(out) == n:
            break
    return out


def test_settlers_come_for_a_rich_load() -> None:
    world, log = _world()
    you = next(iter(world.agents.values()))
    world.human = you.id
    you.inventory.clear(); you.add_item("Wheat", 400); you.location = you.home
    raiders = _neighbours(world, you)
    t, _ = TK.start(world, log, you, _dest(world, you), 0, random.Random(1))
    n = sum(TK.tick(world, log, random.Random(s)) for s in range(6))
    came = [r for e in t.encounters for r in e["raiders"]]
    ok("a rich load draws settlers who can see the road", n > 0 and came, str(n))
    ok("at most three", len(came) <= TK.MAX_RAIDERS)
    ok("they are out on the road", all(world.agents[r].activity.kind == "raid" for r in came))
    # The fight has them in it, by name.
    enc = next(e for e in t.encounters if e["raiders"])
    t.share = enc["at"] - 0.001
    for e in t.encounters:
        if e is not enc and e["at"] <= enc["at"]:
            e["done"] = "won"
    got = TK.progress(world, you, t.metres * enc["at"])
    f = TK.fight_for(world, log, you, got)
    named = [x for x in f.foes if x.agent]
    ok("named settlers in the fight", named and all(x.name == world.agents[x.agent].name for x in named))
    # Lose: the goods go to them.
    f.over = "lost"
    before = sum(you.inventory.values())
    msg = TK.settle(world, log, you, f, random.Random(3))
    stolen = sum(sum(world.agents[x.agent].stolen.values()) for x in named)
    ok("lost: they have what you lost", stolen > 0 and sum(you.inventory.values()) < before, msg)
    ok("and go home", all(world.agents[x.agent].activity.kind != "raid" for x in named))


def test_a_won_fight_makes_them_pay() -> None:
    world, log = _world()
    you = next(iter(world.agents.values()))
    world.human = you.id
    you.inventory.clear(); you.add_item("Wheat", 400); you.location = you.home
    r = _neighbours(world, you, 1)[0]
    r.denari = 200.0
    r.add_stolen("Ore", 3)
    t, _ = TK.start(world, log, you, _dest(world, you), 0, random.Random(1))
    okj, msg = TK.join(world, log, r, t)
    ok("joined", okj, msg)
    enc = next(e for e in t.encounters if e["raiders"])
    for e in t.encounters:
        if e is not enc:
            e["done"] = "won"
    f = TK.fight_for(world, log, you, TK.progress(world, you, t.metres))
    f.over = "won"
    cash = you.denari
    TK.settle(world, log, you, f, random.Random(4))
    ok("they drop coin", you.denari - cash >= 20.0 and r.denari <= 180.0, f"{you.denari - cash:.1f}")
    ok("and what they had stolen", not r.stolen)


def test_not_a_poor_load_nor_a_friends() -> None:
    world, log = _world()
    you = next(iter(world.agents.values()))
    world.human = you.id
    you.inventory.clear(); you.add_item("Wheat", 25); you.location = you.home
    raiders = _neighbours(world, you)
    t, msg = TK.start(world, log, you, _dest(world, you), 0, random.Random(1))
    ok("a small convoy", t is not None, msg)
    n = sum(TK.tick(world, log, random.Random(s)) for s in range(20))
    ok("a poor load tempts nobody", n == 0, str(n))
    TK.abort(world, log, you)
    you.add_item("Wheat", 500)
    for r in raiders:
        you.allies.append(r.id)
    t, _ = TK.start(world, log, you, _dest(world, you), 0, random.Random(1))
    n = sum(TK.tick(world, log, random.Random(s)) for s in range(20))
    ok("kin do not rob kin", n == 0, str(n))
    ok("and are told why", TK.can_rob(world, raiders[0], t).endswith("kin or a friend"))
    you.allies.clear()
    world.positions.update({r.id: (-1e6, -1e6) for r in raiders})
    ok("too far off, no", "too far" in TK.can_rob(world, raiders[0], t))


def test_the_tool_and_the_observation() -> None:
    from convoy import actions as A
    from convoy import observe as O
    world, log = _world()
    you = next(iter(world.agents.values()))
    world.human = you.id
    you.inventory.clear(); you.add_item("Wheat", 300); you.location = you.home
    r = _neighbours(world, you, 1)[0]
    t, _ = TK.start(world, log, you, _dest(world, you), 0, random.Random(1))
    seen = O.render(O.observe(world, log, r, "reevaluation", record_delivery=False))
    ok("settlers see it", "CONVOYS ON THE ROAD NEAR YOU" in seen and t.id in seen)
    okr, msg = A.rob_convoy(world, log, r, t.id)
    ok("and can go for it", okr, msg)


def test_checkpoint_keeps_a_convoy() -> None:
    world, log = _world()
    you = next(iter(world.agents.values()))
    you.inventory.clear(); you.add_item("Wheat", 300); you.location = you.home
    TK.start(world, log, you, _dest(world, you), 0, random.Random(1))
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "w.json"
        CK.save(world, path)
        back = CK.load(path)
    t = back.treks.get(you.id)
    ok("a convoy survives a restart", t is not None and t.status == "on" and t.encounters, str(t))


def test_goods_go_by_convoy_not_fast_travel() -> None:
    from convoy.game import Game, Settings

    class StandIn:
        def __init__(self):
            self.world_lock = contextlib.nullcontext()
            self.usage = {}

        def decide(self, world, agent, reason) -> None:
            return None

    with tempfile.TemporaryDirectory() as tmp:
        game = Game.new(Settings(model="x/rule-based", outposts=True, pace=1e6, workers=1,
                                 cities={"aldermarch": 3, "cinderhold": 2}),
                        Path(tmp), models=StandIn())
        you, w = game.you, game.world
        you.location = you.home
        you.add_item("Wheat", 100)
        dest = _dest(w, you)
        r = game.act("travel_to", {"destination": dest})
        ok("no fast travel with a load", not r["ok"] and "convoy" in r["message"].lower(), r["message"])
        p = game.trek_op({"op": "plan", "to": dest, "metres": 3000})
        ok("a plan says the danger", p["ok"] and p["plan"]["attacks"] >= 1 and p["plan"]["danger"], str(p))
        s = game.trek_op({"op": "start", "to": dest, "metres": 3000})
        ok("set out", s["ok"] and s["trek"]["status"] == "on", s.get("message", ""))
        g = game.trek_op({"op": "progress", "metres": 3000})
        ok("bandits on the road", g["fight"] is not None and g["fight"]["kind"] == "convoy", str(g)[:200])
        game.fight.over = "fled"
        game.fight_op({"op": "flee"})
        ok("got away", game.fight is None)
        a = game.arrive(dest)
        ok("arriving ends the convoy", "Reached" in (a.get("convoy") or ""), str(a)[:200])
        game.engine.close()


def main() -> int:
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for t in tests:
        t()
    print(f"test_trek.py: {len(tests)} tests, {len(FAILURES)} failures")
    for f in FAILURES:
        print(f"  FAIL {f}")
    return 1 if FAILURES else 0


if __name__ == "__main__":
    raise SystemExit(main())
