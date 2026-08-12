#!/usr/bin/env python3
"""Property upgrades and Upgraded Tools — the two goods that had no consumer.

Garage/storage tiers were fully specified on the World State Schema tab but had
no transaction implemented. Upgraded Tools were sold but did nothing.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from convoy import actions as A
from convoy import data as D
from convoy import economy as E
from convoy.engine import Engine, EngineConfig
from convoy.events import EventLog
from convoy.state import Activity, Agent, Business, Employment, Property, World

FAILURES: list[str] = []


def check(label, actual, expected) -> None:
    if actual != expected:
        FAILURES.append(f"{label}: got {actual!r}, expected {expected!r}")


def setup(denari=5000.0):
    w, log = World(), EventLog(None, echo_min=99)
    a = Agent(id="A0001", name="Owner", model="rb", location="Kiln Row")
    a.denari = denari
    w.agents[a.id] = a
    prop = Property(id="P0001", owner=a.id, location="Kiln Row", plots=4)
    w.properties[prop.id] = prop
    a.owned_property = prop.id
    return w, log, a, prop


def test_storage_tiers():
    w, log, a, prop = setup()
    check("base storage", prop.storage_capacity(), 20)

    ok, msg = A.upgrade_storage(w, log, a)
    check("no materials -> refused", ok, False)

    for tier, cap, cost in [(1, 70, 150.0), (2, 170, 200.0), (3, 370, 350.0)]:
        for item, qty in D.STORAGE_TIER_INPUTS[tier].items():
            a.add_item(item, qty)
        before = a.denari
        ok, msg = A.upgrade_storage(w, log, a)
        check(f"storage tier {tier} applied", ok, True)
        check(f"storage tier {tier} capacity", prop.storage_capacity(), cap)
        check(f"storage tier {tier} charges the delta", round(before - a.denari, 2), cost)

    ok, _ = A.upgrade_storage(w, log, a)
    check("cannot exceed tier 3", ok, False)


def test_garage_tiers():
    w, log, a, prop = setup()
    check("base garage slots", prop.garage_slots(), 0)
    for tier, slots, cost in [(1, 1, 200.0), (2, 2, 250.0), (3, 3, 350.0)]:
        for item, qty in D.GARAGE_TIER_INPUTS[tier].items():
            a.add_item(item, qty)
        before = a.denari
        ok, _ = A.upgrade_garage(w, log, a)
        check(f"garage tier {tier} applied", ok, True)
        check(f"garage tier {tier} slots", prop.garage_slots(), slots)
        check(f"garage tier {tier} charges the delta", round(before - a.denari, 2), cost)


def test_upgrade_kit_substitutes_for_materials():
    """One Property Upgrade kit stands in for a tier's whole material bill --
    which is what finally gives the Home Improvement Store a customer."""
    w, log, a, prop = setup()
    a.add_item(D.PROPERTY_UPGRADE_KIT, 1)
    ok, _ = A.upgrade_storage(w, log, a)
    check("kit satisfies the materials", ok, True)
    check("kit consumed", a.inventory.get(D.PROPERTY_UPGRADE_KIT, 0), 0)
    check("storage raised", prop.storage_capacity(), 70)


def test_upgrades_need_you_to_be_there():
    w, log, a, prop = setup()
    a.add_item("Stone", 1); a.add_item("Clay", 1)
    a.location = "The Hills"
    ok, msg = A.upgrade_storage(w, log, a)
    check("must be at the property", ok, False)


def test_tools_speed_up_extraction_only():
    def output(business_type, product, tooled):
        w, log = World(), EventLog(None, echo_min=99)
        biz = Business(id="B1", type=business_type, name="B", owner="A0001",
                       location="Town", cash=1e9, active_production=product)
        w.businesses[biz.id] = biz
        a = Agent(id="A0002", name="W", model="rb", location="Town")
        a.activity = Activity("work", 1e9, {"business": "B1", "role": "Farmhand"})
        a.next_reeval_at = a.next_diary_at = 1e9
        a.equipped_tools = tooled
        w.agents[a.id] = a
        biz.roster.append(Employment(a.id, "Farmhand", 0.0))
        eng = Engine(w, log, type("N", (), {"decide": lambda *a: None})(),
                     EngineConfig(speed=1e9))
        for _ in range(60):
            eng.tick(60.0)
        return biz.inventory.get(product, 0) + biz.production_buffer

    farm_base = output("Farm", "Grain", False)
    farm_tools = output("Farm", "Grain", True)
    check("farm base rate", round(farm_base, 2), 72.0)
    check("tools give +25% on a farm", round(farm_tools, 2), round(72.0 * 1.25, 2))

    # A Refinery is not an extraction business -- tools must do nothing there.
    ref_base = output("Refinery", "Charcoal", False)
    ref_tools = output("Refinery", "Charcoal", True)
    check("tools do NOT help refining", round(ref_tools, 2), round(ref_base, 2))
    print(f"  farm {farm_base:.1f} -> {farm_tools:.1f}/hr with tools; "
          f"refinery unchanged at {ref_base:.1f}/hr")


def test_equipping_consumes_the_item():
    w, log, a, _p = setup()
    ok, _ = A.equip_tools(w, log, a)
    check("cannot equip what you do not have", ok, False)
    a.add_item("Upgraded Tools", 1)
    ok, _ = A.equip_tools(w, log, a)
    check("equipped", ok, True)
    check("item consumed", a.inventory.get("Upgraded Tools", 0), 0)
    ok, _ = A.equip_tools(w, log, a)
    check("cannot double-equip", ok, False)


def test_wool_is_gone():
    check("Wool removed from resources", "Wool" in D.RESOURCES, False)
    check("Wool not a Farm output", "Wool" in D.BUSINESS_TYPES["Farm"].outputs, False)
    check("Wool consumed by nothing", any(
        "Wool" in r.inputs for r in
        list(D.REFINING_RECIPES.values()) + list(D.CRAFTING_RECIPES.values())
    ), False)


def main() -> int:
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for t in tests:
        t()
    print(f"Ran {len(tests)} property/tools tests.")
    if FAILURES:
        print(f"\n{len(FAILURES)} FAILURES:")
        for f in FAILURES:
            print(f"  ! {f}")
        return 1
    print("Property upgrades and Upgraded Tools both behave.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
