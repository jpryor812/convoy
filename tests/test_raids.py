#!/usr/bin/env python3
"""Robbery by people: raids planned, joined, won, lost and died in.

Designer decisions of 2026-10-16. The dice-roll bandits are replaced by agents
lying in wait on a road. A raid that wins takes the load as stolen goods,
shared between the raiders; one that loses may get raiders killed, and a dead
raider loses what was on them -- cargo, the cart they rode, their weapons and
armour -- but keeps their cash and everything else. The dice are scripted here,
so every branch is exercised exactly.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from convoy import actions as A
from convoy import data as D
from convoy import raids as R
from convoy import world_map as M
from convoy.engine import Engine, EngineConfig
from convoy.events import EventLog
from convoy.state import VehicleInstance
from convoy.world_setup import new_world

FAILURES: list[str] = []


def ok(label, condition, detail="") -> None:
    if not condition:
        FAILURES.append(f"{label}{': ' + detail if detail else ''}")


def check(label, actual, expected) -> None:
    if actual != expected:
        FAILURES.append(f"{label}: got {actual!r}, expected {expected!r}")


class Dice:
    """Plays back the rolls it is given, in order."""

    def __init__(self, rolls: list[float], fraction: float = 1.0):
        self.rolls = list(rolls)
        self.fraction = fraction

    def random(self) -> float:
        return self.rolls.pop(0) if self.rolls else 0.5

    def uniform(self, a: float, b: float) -> float:
        return a + (b - a) * self.fraction


class Idle:
    def decide(self, world, agent, reason) -> None:
        return None


ROAD = "The Long Road"


def _setup(n_raiders: int = 2):
    log = EventLog(None, echo_min=99)
    cities = M.CITY_KEYS[:2]
    world = new_world(log, [], {
        c: [(f"{c}-{i}", "m") for i in range(n_raiders + 1)] for c in cities
    }, government=False)
    world.npc_bandits = False
    seg = R.segment_named(ROAD)
    raiders = world.agents_in(cities[0])[:n_raiders]
    victim = world.agents_in(cities[1])[0]
    for r in raiders:
        r.location = seg.a
    eng = Engine(world, log, Idle(), EngineConfig(banditry=False, speed=1e9))
    return world, log, eng, seg, raiders, victim


def test_a_raid_is_planned_from_the_end_of_a_road() -> None:
    world, log, eng, seg, raiders, victim = _setup()
    away = raiders[0]
    away.location = M.spurs_in(world.cities[0])[0].name
    okp, msg = A.plan_raid(world, log, away, ROAD)
    ok("not from the middle of nowhere", not okp, msg)
    away.location = seg.a
    okp, msg = A.plan_raid(world, log, away, ROAD, hours=3)
    ok("from one end, it is planned", okp, msg)
    raid = next(iter(world.raids.values()))
    check("they lie in wait", away.activity.kind, "raid")
    okj, msg = A.join_raid(world, log, raiders[1], raid.id)
    ok("a second raider joins from the same end", okj, msg)
    check("two waiting", len(R.live_members(world, raid)), 2)
    ok("the roads between cities can be raided", ROAD in [s.name for s in M.INTERCITY_SEGMENTS])


def test_a_winning_raid_takes_the_load_as_stolen_goods() -> None:
    world, log, eng, seg, raiders, victim = _setup()
    A.plan_raid(world, log, raiders[0], ROAD)
    raid = next(iter(world.raids.values()))
    A.join_raid(world, log, raiders[1], raid.id)
    victim.inventory = {"Bronze": 4}
    before = sum(victim.inventory.values())
    eng._rng = Dice([0.99, 0.0, 0.99])           # not spotted, raiders win, no escape
    eng._resolve_raids(victim, seg.b, seg.a)
    robbed = [e for e in log.events if e.type == "robbed"]
    check("one robbery", len(robbed), 1)
    if robbed:
        ok("naming the raiders", set(robbed[0].detail["raiders"]) == {r.name for r in raiders})
    took = before - sum(victim.inventory.values())
    stolen = sum(sum(r.stolen.values()) for r in raiders)
    ok("something was taken", took > 0, str(victim.inventory))
    check("and it went to the raiders, as stolen goods", stolen, took)
    ok("shared between them", all(sum(r.stolen.values()) > 0 for r in raiders) or took < 2)


def test_a_beaten_raid_can_kill_and_a_dead_raider_keeps_their_money() -> None:
    world, log, eng, seg, raiders, victim = _setup(n_raiders=1)
    raider = raiders[0]
    cart = VehicleInstance(id=world.new_id("V"), type="Donkey Cart", owner=raider.id,
                           location=raider.location)
    world.vehicles[cart.id] = cart
    raider.owned_vehicles.append(cart.id)
    raider.mounted_vehicle = cart.id
    raider.equipped_weapon = "Bronze Sword"
    raider.inventory = {"Grain": 3}
    raider.denari = 777.0
    A.plan_raid(world, log, raider, ROAD)
    victim.inventory = {"Bronze": 4}
    victim.equipped_weapon = "Iron Sword"
    eng._rng = Dice([0.99, 0.99, 0.0])           # not spotted, convoy wins, raider dies
    eng._resolve_raids(victim, seg.b, seg.a)
    check("the raid was beaten off", len([e for e in log.events if e.type == "raid_repelled"]), 1)
    ok("the raider died", not raider.alive)
    check("cash is kept", raider.denari, 777.0)
    ok("the cart they rode is gone", cart.id not in world.vehicles and cart.id not in raider.owned_vehicles)
    check("so is their weapon", raider.equipped_weapon, "")
    ok("and what they carried", not raider.inventory)
    pile = world.ground_loot.get(seg.a, {}).get("items", {})
    ok("dropped where they fell, for anyone to take",
       pile.get("Grain") == 3 and pile.get("Bronze Sword") == 1, str(pile))
    check("the convoy kept its load", victim.inventory, {"Bronze": 4})
    world.sim_time += D.RESPAWN_SECONDS + 1
    eng._respawn()
    ok("and they come back", raider.alive)


def test_a_named_target_lets_everyone_else_pass() -> None:
    world, log, eng, seg, raiders, victim = _setup()
    someone_else = raiders[1]
    A.plan_raid(world, log, raiders[0], ROAD, target_id=someone_else.id)
    victim.inventory = {"Bronze": 4}
    eng._rng = Dice([0.0, 0.0, 0.0])
    eng._resolve_raids(victim, seg.b, seg.a)
    check("not the target, not touched", victim.inventory, {"Bronze": 4})
    check("no robbery", len([e for e in log.events if e.type == "robbed"]), 0)


def test_raiders_do_not_rob_their_own_crew() -> None:
    world, log, eng, seg, raiders, victim = _setup()
    A.plan_raid(world, log, raiders[0], ROAD)
    raid = next(iter(world.raids.values()))
    A.join_raid(world, log, raiders[1], raid.id)
    raiders[1].inventory = {"Bronze": 4}
    eng._rng = Dice([0.0, 0.0, 0.0])
    # The second raider walking the road it is waiting on: the only other
    # member is the first, and a crew does not rob itself.
    eng._resolve_raids(raiders[1], seg.a, seg.b)
    check("its own crew is never robbed", raiders[1].inventory, {"Bronze": 4})


def test_nothing_happens_to_an_empty_traveller() -> None:
    world, log, eng, seg, raiders, victim = _setup()
    A.plan_raid(world, log, raiders[0], ROAD)
    victim.inventory = {}
    eng._rng = Dice([0.0, 0.0, 0.0])
    eng._resolve_raids(victim, seg.b, seg.a)
    check("nothing to take, no ambush", len([e for e in log.events
                                            if e.type in ("robbed", "raid_repelled")]), 0)


def test_weapons_and_armour_are_equipped_from_the_pack() -> None:
    world, log, eng, seg, raiders, victim = _setup()
    a = raiders[0]
    a.inventory = {"Iron Sword": 1, "Bronze Helm": 1}
    weak = R.body_strength(a)
    oke, msg = A.equip(world, log, a, "Iron Sword")
    ok("a weapon can be wielded", oke, msg)
    check("the old one goes in the pack", a.inventory.get("Slingshot"), 1)
    oke, msg = A.equip(world, log, a, "Bronze Helm")
    ok("armour can be worn", oke, msg)
    ok("and they fight better for it", R.body_strength(a) > weak,
       f"{weak:.2f} -> {R.body_strength(a):.2f}")
    oke, msg = A.equip(world, log, a, "Grain")
    ok("grain is not a weapon", not oke, msg)


def main() -> int:
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for t in tests:
        t()
    print(f"test_raids.py: {len(tests)} tests, {len(FAILURES)} failures")
    for f in FAILURES:
        print(f"  FAIL {f}")
    return 1 if FAILURES else 0


if __name__ == "__main__":
    raise SystemExit(main())
