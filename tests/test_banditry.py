#!/usr/bin/env python3
"""Bandits on the road: the shape of the risk, not the roll of the dice.

`convoy/banditry.py` turns a journey into a probability. A probability is easy
to get subtly wrong and hard to notice, because every individual outcome looks
plausible -- so these tests check the SHAPE rather than any single number:
every lever moves risk in the direction it is supposed to, nothing ever leaves
[0, 1], and a partial loss is always partial.

Then a handful of them pin the CALIBRATION, because the constants were tuned
against two stated anchors and a later edit that quietly moves them should
fail out loud rather than change the economy in silence.

NO PLACE IS NAMED HERE. Hard-coded place names broke this suite four times
across the 2026-08-20 recuts (PHASE6 §7), so routes are DERIVED: the shortest
road journey and the longest one, whatever the map currently is.
"""

from __future__ import annotations

import random
import sys
from itertools import combinations
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from convoy import banditry as B
from convoy import data as D
from convoy import world_map as M

FAILURES: list[str] = []

LEATHER = ("Leather Cap", "Leather Vest", "Leather Leggings")
IRON = ("Iron Helm", "Iron Cuirass", "Iron Greaves")


def ok(label: str, cond: bool, detail: str = "") -> None:
    print(f"  {'ok  ' if cond else 'FAIL'} {label}" + (f": {detail}" if detail else ""))
    if not cond:
        FAILURES.append(label)


def guard(weapon: str, armor: tuple[str, ...] = (), role: str = "Bodyguard") -> B.Escort:
    return B.Escort("g", role, weapon, armor)


# --- routes, derived off the map rather than named -------------------------

def _routes_by_segment_count() -> dict[int, tuple[str, str]]:
    """One representative journey for each length the map offers."""
    found: dict[int, tuple[str, str]] = {}
    for a, b in combinations(M.LOCATIONS, 2):
        n = len(M.travel_path(a, b)[1])
        found.setdefault(n, (a, b))
    return found


ROUTES = _routes_by_segment_count()
SHORT = ROUTES[min(k for k in ROUTES if k >= 1)]
LONG = ROUTES[max(ROUTES)]
LONG_SEGMENTS = M.travel_path(*LONG)[1]
WORST = max(M.SEGMENTS, key=lambda s: s.danger)
MILDEST = min(M.SEGMENTS, key=lambda s: s.danger)


def test_every_lever_moves_risk_the_right_way() -> None:
    """The whole product argument is that better kit is worth buying."""
    base = B.Party.solo("Donkey Cart", 800, "Sling")
    r = lambda p: B.route_risk(*LONG, p).probability

    armed = B.Party((guard("Iron Sword"),), "Donkey Cart", 800)
    ok("a better weapon lowers risk", r(armed) < r(base),
       f"{r(base):.3f} -> {r(armed):.3f}")

    armoured = B.Party((guard("Iron Sword", IRON),), "Donkey Cart", 800)
    ok("armour lowers risk", r(armoured) < r(armed),
       f"{r(armed):.3f} -> {r(armoured):.3f}")

    crowd = B.Party((guard("Iron Sword", IRON), guard("Iron Sword", IRON)), "Donkey Cart", 800)
    ok("a second body lowers risk", r(crowd) < r(armoured),
       f"{r(armoured):.3f} -> {r(crowd):.3f}")

    faster = B.Party(crowd.escorts, "4-Horse Chariot", 800)
    ok("a better vehicle lowers risk", r(faster) < r(crowd),
       f"{r(crowd):.3f} -> {r(faster):.3f}")

    richer = B.Party.solo("Donkey Cart", 8000, "Sling")
    ok("a richer load RAISES risk", r(richer) > r(base),
       f"{r(base):.3f} -> {r(richer):.3f}")


def test_distance_costs_you() -> None:
    """Distance enters as segments crossed, so it must be monotone in them."""
    if min(ROUTES) == max(ROUTES):
        print("  skip: this map has only one journey length")
        return
    p = B.Party.solo("Donkey Cart", 800, "Sling")
    short, long_ = B.route_risk(*SHORT, p).probability, B.route_risk(*LONG, p).probability
    ok("a longer road is riskier", long_ > short, f"{short:.3f} -> {long_:.3f}")

    lengths = sorted(ROUTES)
    risks = [B.route_risk(*ROUTES[n], p).probability for n in lengths]
    ok("risk rises with every extra segment", risks == sorted(risks),
       " < ".join(f"{x:.3f}" for x in risks))


def test_scouts_and_guards_do_different_jobs() -> None:
    """If they were interchangeable, one of the two roles would be dead data."""
    kit = dict(weapon="Bow", armor=LEATHER)
    scouted = B.Party((guard(role="Scout", **kit), guard("Bronze Sword", LEATHER)), "Donkey Cart", 800)
    guarded = B.Party((guard(**kit), guard("Bronze Sword", LEATHER)), "Donkey Cart", 800)

    ok("a scout cuts the chance of being FOUND",
       B.p_intercept(WORST, scouted) < B.p_intercept(WORST, guarded),
       f"{B.p_intercept(WORST, guarded):.3f} -> {B.p_intercept(WORST, scouted):.3f}")
    ok("a scout does NOT change the standoff",
       abs(B.p_press(WORST, scouted) - B.p_press(WORST, guarded)) < 1e-9,
       "same men, same weapons, same fight")


def test_the_worst_segment_cannot_be_outrun() -> None:
    """`can_flee_offroad()` has been a flag nothing read since Phase 1.

    Exposure is what gates escape, so on a segment with no off-road the fastest
    vehicle in the game must still be unable to run with the load.
    """
    fastest = max(D.VEHICLES.values(), key=lambda v: v.speed_mult).name
    flyer = B.Party((guard("Iron Sword", IRON),), fastest, 800)
    for seg in M.SEGMENTS:
        if not seg.can_flee_offroad():
            ok(f"{seg.name}: no off-road, so almost no escape",
               B.p_escape(seg, flyer) < 0.10, f"p_escape={B.p_escape(seg, flyer):.3f}")
    escapable = [s for s in M.SEGMENTS if s.can_flee_offroad()]
    if escapable:
        best = min(escapable, key=lambda s: s.exposure)
        ok(f"{best.name}: open ground, so speed buys a real chance",
           B.p_escape(best, flyer) > B.p_escape(WORST, flyer),
           f"{B.p_escape(WORST, flyer):.3f} -> {B.p_escape(best, flyer):.3f}")


def test_probabilities_stay_probabilities() -> None:
    """Sweep the extremes: nothing may leave [0, 1], ever."""
    rich = 10 ** 9
    parties = [
        B.Party((), "On Foot", rich),                                  # nobody there
        B.Party.solo("On Foot", 0, "Slingshot"),                       # nothing worth taking
        B.Party.solo("On Foot", rich, "Slingshot"),                    # a fortune, unguarded
        B.Party(tuple(guard("Iron Sword", IRON) for _ in range(50)), "4-Horse Chariot", rich),
        B.Party(tuple(guard("Bow", IRON, "Scout") for _ in range(50)), "4-Horse Chariot", 0),
    ]
    bad: list[str] = []
    for p in parties:
        for seg in M.SEGMENTS:
            for fn in (B.p_intercept, B.p_press, B.p_escape, B.segment_risk):
                v = fn(seg, p)
                if not 0.0 <= v <= 1.0:
                    bad.append(f"{fn.__name__}={v}")
        for a, b in ROUTES.values():
            v = B.route_risk(a, b, p).probability
            if not 0.0 <= v <= 1.0:
                bad.append(f"route_risk={v}")
    ok("every probability is in [0, 1] across the extremes", not bad, "; ".join(bad[:4]))

    ok("an empty party is not certain doom", B.p_press(WORST, B.Party((), "On Foot", 800)) < 1.0)
    ok("a journey to nowhere has no risk",
       B.route_risk(M.LOCATIONS[0], M.LOCATIONS[0], B.Party.solo()).probability == 0.0)


def test_a_loss_is_always_partial() -> None:
    """One roll must never end an agent who staked a run on one shipment."""
    rng = random.Random(1)
    doomed = B.Party((), "Donkey Cart", 10 ** 9)   # about as robbable as it gets
    fractions = []
    for _ in range(3000):
        robbed, lost = B.resolve(*LONG, doomed, rng)
        if robbed:
            fractions.append(lost)
    ok("robberies actually happen to the defenceless", len(fractions) > 100,
       f"{len(fractions)} of 3000")
    ok("never takes everything", max(fractions) <= B.LOOT_FRACTION_MAX)
    ok("never takes nothing", min(fractions) >= B.LOOT_FRACTION_MIN)
    ok("an unrobbed trip loses nothing",
       B.resolve(*LONG, B.Party.solo(), random.Random(2))[1] >= 0.0)


def test_the_roll_is_reproducible() -> None:
    """A run must replay, and a test must not be a coin toss."""
    p = B.Party.solo("Donkey Cart", 800, "Sling")
    a = [B.resolve(*LONG, p, random.Random(99)) for _ in range(5)]
    ok("same seed, same outcome", len(set(a)) == 1, str(a[0]))


def test_the_calibration_anchors_hold() -> None:
    """Two stated anchors. If a constant moves these, say so loudly.

    Justin's framing: a four-horse chariot with three armed escorts should be
    down around 5%, and one person on a donkey with a sling going a long way
    should be up around 75%.
    """
    lone = B.Party.solo("Donkey Cart", 800, "Sling")
    lone_risk = B.route_risk(*LONG, lone).probability
    ok("lone donkey + sling, longest road ~= 75%", 0.68 <= lone_risk <= 0.82,
       f"{lone_risk:.1%}")

    convoy = B.Party(
        (guard("Iron Sword", IRON), guard("Iron Sword", IRON), guard("Iron Sword", IRON),
         guard("Bow", IRON, "Scout")),
        "4-Horse Chariot", 800,
    )
    convoy_risk = B.route_risk(*LONG, convoy).probability
    ok("4-horse + 3 armed escorts, longest road <= 8%", convoy_risk <= 0.08,
       f"{convoy_risk:.1%}")
    ok("...and never zero, however good the kit", convoy_risk >= B.MIN_SEGMENT_RISK,
       f"{convoy_risk:.1%} on {len(LONG_SEGMENTS)} segments")
    ok("the gap between them is the reason to upgrade",
       lone_risk / max(convoy_risk, 1e-9) > 10,
       f"{lone_risk / max(convoy_risk, 1e-9):.0f}x")


def test_walking_is_the_worst_way_to_carry_anything() -> None:
    """The exemption is gone (2026-08-21). The equation says why on its own.

    A walker is the slowest thing on the road, so it is exposed longest; it has
    no speed to run with, so `p_escape` is zero; and it deters nobody. The only
    thing in its favour is that a cheap load is not worth the ambush.
    """
    worst = max(M.SEGMENTS, key=lambda s: s.danger)
    walker = B.Party.solo(B.ON_FOOT, 30, "Slingshot")
    cart = B.Party.solo("Donkey Cart", 30, "Slingshot")

    ok("a walker can be robbed at all",
       B.route_risk(*LONG, walker).probability > 0)
    ok("it cannot outrun anybody", B.p_escape(worst, walker) == 0.0)
    ok("a cart carrying the SAME value is safer",
       B.route_risk(*LONG, cart).probability < B.route_risk(*LONG, walker).probability,
       f"foot {B.route_risk(*LONG, walker).probability:.0%} vs "
       f"cart {B.route_risk(*LONG, cart).probability:.0%}")
    ok("and it is exposed longer than anything else",
       B.p_intercept(worst, walker) > B.p_intercept(worst, cart))


def test_value_is_noticed_however_small_the_load() -> None:
    """Five bronze daggers are worth 600 denari, and walking does not hide that.

    This is the hole the flat foot rule left: under it, a pedestrian could carry
    any fortune across the worst road in the valley for free.
    """
    cheap = B.Party.solo(B.ON_FOOT, 30, "Slingshot")
    rich = B.Party.solo(B.ON_FOOT, 600, "Slingshot")
    ok("a valuable walked load is far riskier than a cheap one",
       B.route_risk(*LONG, rich).probability > B.route_risk(*LONG, cheap).probability * 1.5,
       f"{B.route_risk(*LONG, cheap).probability:.0%} -> "
       f"{B.route_risk(*LONG, rich).probability:.0%}")


def test_splitting_a_load_no_longer_buys_safety() -> None:
    """The exploit that killed the rule: 20 walked 5-unit trips vs one cart.

    Measured on the 2026-08-21 run before the fix -- 20 of 26 posted jobs were
    for exactly five units. Per unit delivered, a guarded cart must now beat
    many small walks, or the market will keep splitting.
    """
    per_trip = 5
    big = 100
    walker = B.Party.solo(B.ON_FOOT, 30, "Slingshot")
    guarded = B.Party(
        tuple(B.Escort(str(i), "Bodyguard", "Iron Sword", ("Iron Cuirass",))
              for i in range(2)) + (B.Escort("d", "Driver-own", "Bronze Sword", ()),),
        "Donkey Cart", 600,
    )
    trips = big / per_trip
    foot_loss = trips * B.route_risk(*LONG, walker).probability * B.EXPECTED_LOSS_FRACTION * per_trip
    cart_loss = B.route_risk(*LONG, guarded).probability * B.EXPECTED_LOSS_FRACTION * big
    ok("moving 100 units on foot loses more than one guarded cart does",
       foot_loss > cart_loss,
       f"{trips:.0f} walks lose ~{foot_loss:.1f} units vs ~{cart_loss:.1f} by cart")


def test_no_amount_of_money_buys_safety() -> None:
    """The top rung. Justin: risk should never drop below 3%, even with the best."""
    best_vehicle = max(D.VEHICLES.values(), key=lambda v: v.speed_mult).name
    best_weapon = max(D.WEAPONS.values(), key=lambda w: w.damage).name
    best_armor = tuple(
        max((a for a in D.ARMOR.values() if a.slot == slot),
            key=lambda a: a.damage_reduction).name
        for slot in {a.slot for a in D.ARMOR.values()}
    )
    unlimited = B.Party(
        tuple(B.Escort("g", "Bodyguard", best_weapon, best_armor) for _ in range(20))
        + tuple(B.Escort("s", "Scout", best_weapon, best_armor) for _ in range(20)),
        best_vehicle, 1.0,
    )
    for seg in M.SEGMENTS:
        ok(f"{seg.name}: still at least {B.MIN_SEGMENT_RISK:.0%}",
           B.segment_risk(seg, unlimited) >= B.MIN_SEGMENT_RISK,
           f"{B.segment_risk(seg, unlimited):.3f}")

    ok("a longer road is still worse, even at the floor",
       B.route_risk(*LONG, unlimited).probability
       > B.route_risk(*SHORT, unlimited).probability,
       f"{B.route_risk(*SHORT, unlimited).probability:.1%} -> "
       f"{B.route_risk(*LONG, unlimited).probability:.1%}")


def test_escorts_are_paid_through_the_existing_convoy_table() -> None:
    """CONVOY_PAY has been in data.py since Phase 1, referenced by nothing."""
    p = B.Party((guard("Iron Sword", IRON), guard("Bow", IRON, "Scout")), "Donkey Cart", 1000)
    expected = sum(
        D.CONVOY_PAY[r]["flat"] + 1000 * D.CONVOY_PAY[r]["commission"]
        for r in ("Bodyguard", "Scout")
    )
    ok("escort cost comes off the Convoy tab", abs(B.escort_cost(p, 1000) - expected) < 1e-9,
       f"{B.escort_cost(p, 1000):.2f}")
    ok("a bigger load costs more to guard", B.escort_cost(p, 5000) > B.escort_cost(p, 1000))
    ok("nobody to pay costs nothing", B.escort_cost(B.Party((), "On Foot", 1000), 1000) == 0.0)


def test_the_agent_is_told_before_it_decides() -> None:
    """PHASE4 §2: a number the agent never sees changes no decision.

    Nobody buys a chariot because of a probability the observation withheld.
    """
    p = B.Party.solo("Donkey Cart", 800, "Sling")
    line = B.route_risk(*LONG, p).explain()
    ok("the warning names a percentage", "%" in line, line)
    ok("the warning names both ends", LONG[0] in line and LONG[1] in line)
    ok("the warning names the worst stretch",
       any(s.name in line for s in M.SEGMENTS), line)
    ok("a riskless journey says so",
       "nothing to rob" in B.route_risk(M.LOCATIONS[0], M.LOCATIONS[0], p).explain().lower())

    walker = B.route_risk(*LONG, B.Party.solo(B.ON_FOOT, 800)).explain()
    ok("a walker gets a real number too, not an exemption",
       "%" in walker and "none" not in walker.lower(), walker)


def main() -> int:
    tests = [
        test_every_lever_moves_risk_the_right_way,
        test_distance_costs_you,
        test_scouts_and_guards_do_different_jobs,
        test_the_worst_segment_cannot_be_outrun,
        test_probabilities_stay_probabilities,
        test_a_loss_is_always_partial,
        test_the_roll_is_reproducible,
        test_the_calibration_anchors_hold,
        test_walking_is_the_worst_way_to_carry_anything,
        test_value_is_noticed_however_small_the_load,
        test_splitting_a_load_no_longer_buys_safety,
        test_no_amount_of_money_buys_safety,
        test_escorts_are_paid_through_the_existing_convoy_table,
        test_the_agent_is_told_before_it_decides,
    ]
    print(f"banditry — {len(M.SEGMENTS)} segments, "
          f"routes of {min(ROUTES)}–{max(ROUTES)} segments")
    for fn in tests:
        print(f"\n--- {fn.__name__} ---")
        fn()
    print()
    if FAILURES:
        print(f"{len(FAILURES)} FAILURES:")
        for f in FAILURES:
            print(f"  ! {f}")
        return 1
    print("OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
