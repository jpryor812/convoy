#!/usr/bin/env python3
"""Bandit gangs robbing buildings (designer request, 2026-10-30; see
convoy/robbery.py and GAME_MODES.md, "Robbing buildings").

Who is targeted follows money and distance, and lookouts make it rarer;
nobody is robbed in their first six game hours, more than once in twelve hours, or
twice at once; a gang is sighted early only by lookouts, loots for an hour,
and then takes 30-60% of the yard and purse -- unless the watch drives it off.
"""

from __future__ import annotations

import random
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from convoy import actions as A
from convoy import checkpoint as CP
from convoy import claims as CL
from convoy import robbery as RB
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
    world.sim_time = 30 * 3600.0                     # past the first day
    for a in world.agents.values():
        a.protected_until = 0.0
    return world, log


def _farm(world, log, a, near, far, seed=3):
    rng = random.Random(seed)
    x, y = CL.sample_sites(world, *CL.place_xy(world, a.home), rng, n=1, near=near, far=far)[0]
    _, _, c = CL.claim(world, log, a, x, y, "Farm")
    a.location = c.name
    A.start_business(world, log, a, "Farm")
    return world.businesses[a.owned_businesses[-1]]


def _firm(world, log, a, at):
    rng = random.Random(9)
    x, y = CL.sample_sites(world, *CL.place_xy(world, at), rng, n=1, near=90, far=300)[0]
    _, _, c = CL.claim(world, log, a, x, y, "")
    a.location = c.name
    A.start_business(world, log, a, "Private Security Contractor")
    firm = world.businesses[a.owned_businesses[-1]]
    for m in [m for m in a.family if m.adult][:2]:
        A.assign_family(world, log, a, m.id, firm.id)
    return firm


def _run(world, log, rng, hours):
    for _ in range(int(hours * 60)):
        world.sim_time += 60.0
        RB.tick(world, log, rng, hour_passed=world.sim_time % 3600.0 == 0)


def test_money_and_distance() -> None:
    world, log = _world()
    a = next(iter(world.agents.values()))
    a.denari = 5000.0
    remote = _farm(world, log, a, 900, 1300)
    near = _farm(world, log, a, 90, 200, seed=4)
    remote.add_item("Wheat", 300)
    near.add_item("Wheat", 40)
    pr, pn = RB.hourly_chance(world, remote), RB.hourly_chance(world, near)
    ok("a rich, remote farm about every day or two", 1 / 48 <= pr <= 1 / 20, f"{pr:.4f}/h")
    ok("a modest farm near others about once a week", 1 / 250 <= pn <= 1 / 100, f"{pn:.4f}/h")
    _firm(world, log, a, remote.location)
    ok("lookouts in range make it much rarer", RB.hourly_chance(world, remote) < pr / 3,
       f"{RB.hourly_chance(world, remote):.4f} vs {pr:.4f}")


def test_protections() -> None:
    world, log = _world()
    a = next(iter(world.agents.values()))
    a.denari = 5000.0
    farm = _farm(world, log, a, 900, 1300)
    farm.add_item("Wheat", 5000)
    world.sim_time = 5 * 3600.0
    ok("nobody in the first six hours", not RB._eligible(world, a))
    world.sim_time = 7 * 3600.0
    ok("then yes", RB._eligible(world, a))
    a.protected_until = world.sim_time + 20 * 3600.0          # arrived three hours ago
    ok("a late arrival gets their own six hours", not RB._eligible(world, a))
    world.sim_time += 4 * 3600.0
    ok("and then is fair game, protected or not", RB._eligible(world, a))
    a.protected_until = 0.0
    world.sim_time = 30 * 3600.0
    RB.start(world, log, farm, random.Random(1))
    ok("one at a time, and twelve hours apart", not RB._eligible(world, a))
    world.robberies.clear()
    world.sim_time += 11 * 3600.0
    ok("still not at eleven hours", not RB._eligible(world, a))
    world.sim_time += 2 * 3600.0
    ok("again after twelve", RB._eligible(world, a))


def test_an_unwatched_building_is_robbed() -> None:
    world, log = _world()
    a = next(iter(world.agents.values()))
    a.denari = 5000.0
    farm = _farm(world, log, a, 900, 1300)
    farm.add_item("Wheat", 200)
    farm.cash = 100.0
    coins = a.denari
    r = RB.start(world, log, farm, random.Random(2))
    ok("nobody hears of it before it arrives", r.sighted_at == r.arrives_at)
    ok("a gang of two to four", 2 <= len(r.gang) <= 4, str(r.gang))
    ok("not yet in the owner's list", not RB.for_owner(world, a))
    _run(world, log, random.Random(2), (r.arrives_at - world.sim_time) / 3600 + 0.1)
    ok("then they loot, and the owner knows", r.status == "looting" and RB.for_owner(world, a))
    _run(world, log, random.Random(2), 1.1)
    ok("robbed after the hour", r.status == "robbed", r.status)
    took = 1 - farm.inventory.get("Wheat", 0) / 200
    ok("30-60% of the yard", 0.29 <= took <= 0.61, f"{took:.2f}")
    ok("and of the purse", 0.39 * 100 <= 100 - farm.cash <= 0.61 * 100, f"{farm.cash}")
    ok("never your pocket", a.denari == coins)
    types = [e.type for e in log.events]
    ok("the owner is told each step", all(t in types for t in ("robbery_started", "building_robbed")))


def test_lookouts_see_them_coming_and_fight() -> None:
    won = lost = 0
    for seed in range(12):
        world, log = _world()
        a = next(iter(world.agents.values()))
        a.denari = 5000.0
        farm = _farm(world, log, a, 900, 1300)
        farm.add_item("Wheat", 200)
        _firm(world, log, a, farm.location)
        r = RB.start(world, log, farm, random.Random(seed))
        if seed == 0:
            ok("lookouts see the gang half an hour out", abs(r.arrives_at - r.sighted_at - 1800) < 1
               or r.sighted_at == r.set_out)
        _run(world, log, random.Random(seed), (r.ends_at - world.sim_time) / 3600 + 0.1)
        won += r.status == "beaten"
        lost += r.status == "robbed"
    ok("two lookouts with bats sometimes drive them off", won > 0, f"{won} won, {lost} lost")
    ok("and sometimes do not", lost > 0, f"{won} won, {lost} lost")


def test_a_guard_post_weakens_the_gang() -> None:
    world, log = _world()
    a = next(iter(world.agents.values()))
    a.denari = 5000.0
    farm = _farm(world, log, a, 900, 1300)
    r = RB.start(world, log, farm, random.Random(4))
    before = RB.gang_strength(world, r)
    from convoy.state import Plot
    world.plots["Lg"] = Plot(id="Lg", location=farm.location, owner=a.id, developed=True, structure="Guard post")
    ok("a guard post halves it", abs(RB.gang_strength(world, r) - before * 0.5) < 1e-6)


def test_gangs_come_on_their_own_and_survive_a_save() -> None:
    world, log = _world()
    a = next(iter(world.agents.values()))
    a.denari = 5000.0
    farm = _farm(world, log, a, 900, 1300)
    farm.add_item("Wheat", 2000)
    farm.cash = 400.0
    _run(world, log, random.Random(5), 72)
    hit = [e for e in log.events if e.type == "gang_set_out" and e.actor == a.id]
    ok("a rich, remote farm is visited within three days", hit, "none")
    r = RB.start(world, log, world.businesses[a.owned_businesses[-1]], random.Random(1)) \
        if not world.robberies else next(iter(world.robberies.values()))
    with tempfile.TemporaryDirectory() as d:
        path = Path(d) / "checkpoint.json"
        CP.save(world, path)
        back = CP.load(path)
    ok("a robbery is saved and loaded", r.id in back.robberies and back.robberies[r.id].gang == r.gang)


def main() -> int:
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for t in tests:
        t()
    print(f"test_robbery.py: {len(tests)} tests, {len(FAILURES)} failures")
    for f in FAILURES:
        print(f"  FAIL {f}")
    return 1 if FAILURES else 0


if __name__ == "__main__":
    raise SystemExit(main())
