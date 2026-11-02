#!/usr/bin/env python3
"""Moving on the map, hex by hex (designer, 2026-11-01; convoy/journey.py).

A step is a neighbouring hex, 1 energy (2 on a mountain), 10 game minutes;
nobody walks into the river except at a ford; at 0 energy you stop. What
your mount allows is your most energy; home upgrades add to it. Rest at home
fills you, a camp gives 8 for one Camp Supplies, sleeping rough 5, a meal 2.
Explorers -- family or hired -- walk for you and fill in your map. Only home
is a fast trip, and convoys go only to places you have found.
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
from convoy import data as D
from convoy import hexes as H
from convoy import journey as JY
from convoy import layout as L
from convoy import town as TOWN
from convoy.events import EventLog
from convoy.state import VehicleInstance
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
    you = next(iter(world.agents.values()))
    world.human = you.id
    JY.ensure(world, you)
    return world, log, you


def _walk(world, log, you, n=1):
    """Let `n` steps run their ten minutes each."""
    out = []
    for _ in range(n):
        world.sim_time += JY.STEP_S + 1
        ev = JY.advance(world, log, you)
        if ev:
            out.append(ev)
    return out


def _open_neighbour(world, h):
    return next(nb for nb in H.neighbours(h) if H.terrain(world, nb) in ("open", "road"))


def test_a_step() -> None:
    world, log, you = _world()
    start = JY.here(you)
    ok("you start at home, full", you.hex is not None and you.energy == JY.max_energy(world, you))
    ok("and you know your home's ring", all(H.key(h) in you.explored for h in H.ring(start, 1)))
    nb = _open_neighbour(world, start)
    e0 = you.energy
    okm, msg = JY.set_route(world, log, you, [list(nb)])
    ok("a step to a neighbour", okm and you.activity.kind == "move", msg)
    ok("it costs 1", you.energy == e0 - 1)
    ok("and is not done at once", JY.here(you) == start)
    _walk(world, log, you)
    ok("ten minutes later you are there", JY.here(you) == nb)
    ok("and see round it", all(H.key(h) in you.explored for h in H.ring(nb, 1)))
    far = (start[0] + 3, start[1])
    okm, msg = JY.set_route(world, log, you, [list(far)])
    ok("not a hex that is not next to you", not okm, msg)


def test_water_mountains_and_the_edge() -> None:
    world, log, you = _world()
    cities = list(world.cities)
    y = L.river_axis()
    xs = [x for x in range(-3000, 3000, 50)]
    wet = next((H.to_hex(x, y) for x in xs if H.terrain(world, H.to_hex(x, y)) == "water"), None)
    ok("the river is water", wet is not None)
    ford = next((H.to_hex(x, y) for x in xs if H.terrain(world, H.to_hex(x, y)) == "road"), None)
    ok("where a road crosses it, a ford", ford is not None)
    ok("water is not a step", H.step_cost(world, wet) is None)
    m = L.mountains(cities)[0]
    ok("a mountain costs 2", H.step_cost(world, H.to_hex(m["x"], m["y"])) == 2)
    ok("off the map, no", H.terrain(world, H.to_hex(99999, 99999)) == "edge")


def test_spent_you_stop() -> None:
    world, log, you = _world()
    you.energy = 2
    h = JY.here(you)
    line = [h]
    for _ in range(4):
        nb = next(n for n in H.neighbours(line[-1]) if H.step_cost(world, n) == 1 and n not in line)
        line.append(nb)
    JY.set_route(world, log, you, [list(x) for x in line[1:]])
    evs = _walk(world, log, you, 4)
    ok("two steps on 2 energy, then you stop", JY.here(you) == line[2] and you.energy == 0, str(you.energy))
    ok("and are told why", any("spent" in (e.get("stopped") or "") for e in evs))


def test_energy_by_mount_and_home() -> None:
    world, log, you = _world()
    def ride(kind):
        vid = world.new_id("V")
        world.vehicles[vid] = VehicleInstance(id=vid, type=kind, owner=you.id, location=you.location)
        you.mounted_vehicle = vid
        return JY.max_energy(world, you)
    ok("a donkey goes 10", ride("Donkey") == 10)
    ok("a horse 12", ride("Horse") == 12)
    ok("a carriage 15", ride("2-Horse Chariot") == 15)
    you.mounted_vehicle = None
    ok("on foot 8", JY.max_energy(world, you) == 8)
    ride("Donkey")
    you.denari = 1000
    okh, msg = JY.upgrade_home(world, log, you, "Feather Bed")
    ok("a feather bed adds 2", okh and JY.max_energy(world, you) == 12, msg)
    okh, _ = JY.upgrade_home(world, log, you, "Feather Bed")
    ok("once", not okh)


def test_rest_camp_rough_and_a_meal() -> None:
    world, log, you = _world()
    top = JY.max_energy(world, you)
    you.energy = 1
    okr, msg = JY.rest(world, log, you)
    ok("rest at home", okr, msg)
    world.sim_time += JY.REST_H * 3600 + 1
    JY.advance(world, log, you)
    ok("to full in two hours", you.energy == top, str(you.energy))
    # Out in the field.
    nb = _open_neighbour(world, JY.here(you))
    JY.set_route(world, log, you, [list(nb)])
    _walk(world, log, you)
    ok("no resting at home away from it", not JY.rest(world, log, you)[0])
    you.energy = 0
    okc, msg = JY.make_camp(world, log, you)
    ok("no camp without supplies", not okc, msg)
    you.add_item("Camp Supplies", 1)
    okc, msg = JY.make_camp(world, log, you)
    world.sim_time += JY.CAMP_H * 3600 + 1
    JY.advance(world, log, you)
    ok("a camp gives 8 and uses the supplies", okc and you.energy == 8 and not you.inventory.get("Camp Supplies"), str(you.energy))
    you.energy = 0
    JY.sleep_rough(world, log, you)
    world.sim_time += JY.ROUGH_H * 3600 + 1
    JY.advance(world, log, you)
    ok("rough, 5 in four hours", you.energy == 5)
    you.energy = 0
    JY.sleep_rough(world, log, you)
    world.sim_time += JY.ROUGH_H * 3600 / 2
    JY.set_route(world, log, you, [list(_open_neighbour(world, JY.here(you)))])
    ok("woken halfway, half of it", 1.4 < you.energy + 1 < 3.6, str(you.energy))
    you.energy = 0
    from convoy import actions as A
    A._apply_meal(world, log, you, "Meal", 12.0, 0.0, "test")
    ok("a meal gives 2", you.energy == 2, str(you.energy))
    ok("Camp Supplies are sold to people", not D.is_intermediate("Camp Supplies"))


def test_explorers() -> None:
    world, log, you = _world()
    m = next(m for m in you.family if m.adult)
    okx, msg = JY.send(world, log, you, member_id=m.id, direction="north", days=1)
    ok("send family roaming", okx, msg)
    before = len(you.explored)
    rng = random.Random(1)
    for _ in range(int(86400 / 600) + 60):
        world.sim_time += 600
        JY.tick_explorers(world, log, rng)
    ok("they fill in your map", len(you.explored) > before + 10, f"{before} -> {len(you.explored)}")
    ok("and come home after their days", not world.explorers, str(list(world.explorers.values())[:1]))
    ok("with news", any(e.type == "explorer_back" for e in log.events))
    # To a spot, and a hired scout.
    goal = JY.here(you)
    goal = (goal[0] + 8, goal[1] - 2)
    while H.step_cost(world, goal) is None:
        goal = (goal[0] - 1, goal[1])
    you.denari = 100
    oks, msg = JY.send(world, log, you, target=list(goal), hired=True)
    ok("hire a scout to a spot", oks and you.denari < 100, msg)
    e = next(iter(world.explorers.values()))
    reached = False
    for _ in range(400):
        world.sim_time += 600
        JY.tick_explorers(world, log, rng)
        if e.target is None:
            reached = True
        if e.id not in world.explorers:
            break
    ok("they reach it", reached and H.key(goal) in you.explored)
    ok("and come back", e.id not in world.explorers)


def test_a_family_explorer_leaves_work() -> None:
    from convoy import actions as A
    world, log, you = _world()
    m = next(m for m in you.family if m.adult)
    you.denari = 2000
    x, y = CL.sample_sites(world, *CL.place_xy(world, you.home), random.Random(2), n=1, near=90, far=400)[0]
    CL.claim(world, log, you, x, y, "Farm")
    you.location = list(c.name for c in world.claims.values() if c.owner == you.id and c.name != you.home)[-1]
    A.start_business(world, log, you, "Farm")
    b = world.businesses[you.owned_businesses[-1]]
    A.assign_family(world, log, you, m.id, b.id)
    ok("at work", m.works_at == b.id)
    JY.send(world, log, you, member_id=m.id, direction="east")
    ok("sent exploring, off the roster", m.works_at == "" and not any("family" in e.agent_id for e in b.roster))


def test_checkpoint_keeps_the_map() -> None:
    world, log, you = _world()
    JY.send(world, log, you, member_id=next(m for m in you.family if m.adult).id, direction="west")
    you.home_rest.append("Hearth")
    with tempfile.TemporaryDirectory() as tmp:
        p = Path(tmp) / "w.json"
        CK.save(world, p)
        back = CK.load(p)
    b = back.agents[you.id]
    ok("hex, energy, map and upgrades survive", b.hex == you.hex and b.explored == you.explored and b.home_rest == ["Hearth"])
    ok("explorers too", len(back.explorers) == 1)


def test_the_game_only_fast_travels_home() -> None:
    from convoy.game import Game, Settings

    class StandIn:
        def __init__(self):
            self.world_lock = contextlib.nullcontext()
            self.usage = {}

        def decide(self, world, agent, reason) -> None:
            return None

    with tempfile.TemporaryDirectory() as tmp:
        game = Game.new(Settings(model="x/rule-based", outposts=True, pace=1e6, workers=1,
                                 cities={"aldermarch": 3, "cinderhold": 2}), Path(tmp), models=StandIn())
        w, you = game.world, game.you
        game._journeys()
        ok("the game gives you a hex", you.hex is not None)
        away = next(n for n in w.claims if n != you.home)
        r = game.act("travel_to", {"destination": away})
        ok("no fast travel but home", not r["ok"] and "hex by hex" in r["message"], r["message"])
        # Walk one hex out, with goods, then home is allowed.
        nb = _open_neighbour(w, JY.here(you))
        game.journey_op({"op": "move", "path": [list(nb)]})
        w.sim_time += JY.STEP_S + 1
        game._journeys()
        you.add_item("Wheat", 40)
        game._journeys()
        ok("a step out of home stays out", JY.here(you) == nb, f"{JY.here(you)} vs {nb}")
        r = game.journey_op({"op": "home"})
        ok("home is a fast trip, goods and all", r["ok"], r["message"])
        w.sim_time = you.activity.ends_at + 1
        game._journeys()
        ok("and you are home", JY.here(you) == JY.hex_of_place(w, you.home) and you.location == you.home)
        st = game.status()
        ok("the status carries the map", st.get("map") and st["map"]["energy"] is not None and st["map"]["explored"])
        # A convoy only to places you have found.
        unfound = next((p for p in L.places_cached(list(w.cities))
                        if not JY.found(you, JY.hex_of_place(w, p))), None)
        if unfound:
            you.in_transit = None
            you.location = you.home
            t = game.trek_op({"op": "start", "to": unfound, "metres": 3000})
            ok("no convoy to a place you have not found", not t["ok"] and "not found" in t["message"], t["message"])
        game.engine.close()


def main() -> int:
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for t in tests:
        t()
    print(f"test_journey.py: {len(tests)} tests, {len(FAILURES)} failures")
    for f in FAILURES:
        print(f"  FAIL {f}")
    return 1 if FAILURES else 0


if __name__ == "__main__":
    raise SystemExit(main())
