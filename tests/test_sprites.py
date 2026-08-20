#!/usr/bin/env python3
"""Art binding: everything that exists in the world can be drawn.

The failure this guards against is quiet. Nothing crashes when a good has no
icon -- it renders as a blank square, months later, in a classroom, in front of
people. So the binding is checked the same way the economy is: assert against
`data.py` rather than against a list someone remembered to update.

Also covers the unit grid. The pack's 24 people are 4 faction colours x 6 poses,
and the colours do NOT start where the filenames do -- blue begins at 23 and
wraps past 24 to 1. That offset was measured by counting pixels; if anyone
"tidies" it to a naive 0-23 the map silently repaints every agent the wrong
colour, which is the sort of thing nobody notices until a screenshot is already
in a slide deck.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from convoy import data as D
from convoy import sprites as SP
from convoy import world_map as M

FAILURES: list[str] = []


def check(label, actual, expected) -> None:
    if actual != expected:
        FAILURES.append(f"{label}: got {actual!r}, expected {expected!r}")


def ok(label, condition, detail="") -> None:
    if not condition:
        FAILURES.append(f"{label}{': ' + detail if detail else ''}")


# ---------------------------------------------------------------------------
# completeness
# ---------------------------------------------------------------------------

def test_everything_in_the_world_has_art() -> None:
    problems = SP.check()
    ok("binding complete", not problems, "; ".join(problems[:6]))


def test_the_check_actually_bites() -> None:
    """A completeness check that cannot fail is decoration."""
    saved = SP.GLYPH_FOR_ACTION.pop("travel_to")
    try:
        problems = SP.check()
        ok("removing a glyph is caught",
           any("travel_to" in p for p in problems), str(problems[:3]))
    finally:
        SP.GLYPH_FOR_ACTION["travel_to"] = saved
    ok("restored", not SP.check())


def test_every_item_and_action_is_covered_by_name() -> None:
    from convoy import schemas as S

    for item in D.ALL_ITEMS:
        ok(f"icon for {item}", SP.item_icon(item).exists(), str(SP.item_icon(item)))
    for tool in S.tool_schemas():
        name = tool["function"]["name"]
        ok(f"glyph for {name}", name in SP.GLYPH_FOR_ACTION)
    for btype in D.BUSINESS_TYPES:
        ok(f"structure for {btype}", btype in SP.STRUCTURE_FOR_BUSINESS)
    for loc in M.LOCATIONS_SPEC:
        ok(f"decor for {loc.name}", loc.name in SP.DECOR_FOR_LOCATION)


# ---------------------------------------------------------------------------
# the unit grid
# ---------------------------------------------------------------------------

def test_unit_grid_covers_24_sprites_exactly_once() -> None:
    seen = {SP.unit(f, p) for f in SP.FACTION_BASE for p in SP.POSES}
    check("4 factions x 6 poses are 24 distinct sprites", len(seen), 24)
    for path in seen:
        ok(f"{path.name} exists", path.exists())


def test_blue_wraps_past_24() -> None:
    """Blue starts at 23, so its last two poses are files 1 and 2."""
    got = [SP.unit("blue", pose).stem[-2:] for pose in SP.POSES]
    check("blue cycle", got, ["23", "24", "01", "02", "03", "04"])


def test_each_faction_is_one_colour_block() -> None:
    """A faction's six sprites must be contiguous, or two models share a look."""
    for faction, base in SP.FACTION_BASE.items():
        nums = [int(SP.unit(faction, p).stem[-2:]) for p in SP.POSES]
        rebased = [((n - base) % 24) for n in nums]
        check(f"{faction} is contiguous from its base", rebased, [0, 1, 2, 3, 4, 5])


def test_agent_sprite_reflects_what_the_agent_is() -> None:
    model = "openai/gpt-5.6-luna"
    owner = SP.agent_sprite(model, owns_business=True)
    plain = SP.agent_sprite(model)
    ok("owner differs from plain", owner != plain)
    check("dead is the death glyph", SP.agent_sprite(model, dead=True).name, "death.svg")
    # Owning outranks hauling: an owner reads as an owner even mid-delivery.
    check("owner outranks hauler",
          SP.agent_sprite(model, owns_business=True, hauling=True), owner)


def test_no_two_models_share_a_look() -> None:
    """The invariant, whichever art set is switched on.

    This is the property that keeps a mixed-model run readable without a legend,
    and it has now been broken twice from opposite directions, which is why it is
    asserted about the ACTIVE binding rather than about one art set.

    The pack gives four faction colours for five models, so `terra` and `ling`
    came out as the same blue villager -- the same PNG, twice. The rendered
    characters fixed that with five distinct people and broke it back the moment
    `sprites.PREFER_RENDERED` was turned off again. It is settled now by giving
    ling a different POSE inside its colour; see `BASE_POSE_FOR_MODEL`.
    """
    plain = {SP.agent_sprite(s.openrouter_id) for s in D.MODEL_ROSTER}
    check("every model gets its own sprite", len(plain), len(D.MODEL_ROSTER))

    model = D.MODEL_ROSTER[0].openrouter_id
    if SP.CHARACTER_FOR_MODEL.get(model) and \
            SP.agent_sprite(model).parent.name == "characters":
        check("hauling folds into plain in the rendered set",
              SP.agent_sprite(model, hauling=True), SP.agent_sprite(model))
    else:
        ok("kenney fallback still distinguishes a hauler",
           SP.agent_sprite(model, hauling=True) != SP.agent_sprite(model))


def test_models_get_distinct_enough_colours() -> None:
    factions = {SP.FACTION_FOR_MODEL[s.openrouter_id] for s in D.MODEL_ROSTER}
    ok("a mixed run is not monochrome", len(factions) >= 3, str(factions))
    variants = {SP.CHARACTER_FOR_MODEL[s.openrouter_id] for s in D.MODEL_ROSTER}
    check("five models, five characters", len(variants), len(D.MODEL_ROSTER))


def test_every_vehicle_has_a_sprite() -> None:
    for name in D.VEHICLES:
        path = SP.vehicle_sprite(name)
        ok(f"sprite for {name}", path.exists(), str(path))


# ---------------------------------------------------------------------------
# the renderer's data reconstruction
# ---------------------------------------------------------------------------

def _renderer():
    """The map builder, loaded by path because it is a script, not a package.

    Was `render_world.py` until 2026-08-20, when the two renderers were merged.
    One could read a run and the other could draw the world, and neither could
    do both -- so the run you wanted to watch was only ever available in the old
    card layout. `preview_world.py` absorbed the reading.
    """
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "preview_world", ROOT / "preview_world.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)          # type: ignore[union-attr]
    return mod


def test_dedupe_collapses_a_stationary_agent() -> None:
    r = _renderer()
    track = [[float(h), "Town", None] for h in range(21)]
    check("21 identical hourly samples collapse to 1", len(r.dedupe(track)), 1)
    track.append([21.0, M.SPURS[0].name, None])
    check("a real move survives", len(r.dedupe(track)), 2)


def test_checkpoint_decoding_unwraps_the_custom_encoding() -> None:
    r = _renderer()
    encoded = {"__dict__": [["Iron", 4], ["Grain", 2]]}
    check("dict round-trip", r.decode(encoded), {"Iron": 4, "Grain": 2})
    check("seq round-trip", r.decode({"__seq__": [1, 2, 3]}), [1, 2, 3])


def test_the_snapshot_payload_is_drawable() -> None:
    """Hour zero, with no run: what the page shows before anybody has played."""
    r = _renderer()
    payload = r.build_payload()
    check("snapshot mode", payload["mode"], "snapshot")
    ok("every place is positioned",
       {p["name"] for p in payload["places"]} == set(M.ALL_PLACES))
    ok("one government branch per business type",
       len(payload["buildings"]) == len(M.GOVERNMENT_SITES),
       f"{len(payload['buildings'])} buildings")
    ok("every building has a card",
       all(b["id"] in payload["cards"] for b in payload["buildings"]))
    ok("every person has a card",
       all(p["id"] in payload["cards"] for p in payload["people"]))


def test_a_real_run_replays() -> None:
    r = _renderer()
    runs = [d for d in Path("runs/phase2").iterdir()
            if (d / "events.jsonl").exists()
            and (d / "events.jsonl").stat().st_size > 10_000
            and (d / "checkpoint.json").exists()]
    if not runs:
        return                                   # nothing to check against
    run = max(runs, key=lambda d: (d / "events.jsonl").stat().st_size)
    payload = r.build_payload(run)

    check("replay mode", payload["mode"], "replay")
    ok("agents found", payload["agents"], run.name)
    ok("end hour positive", payload["end_hour"] > 0)
    ok("every agent has a track",
       all(a["id"] in payload["tracks"] for a in payload["agents"]))

    # A BUILDING MUST STAND SOMEWHERE THE LAYOUT KNOWS. A run recorded on a
    # bigger valley names ground this world does not have; `replay` drops those
    # with a printed warning rather than drawing them at nowhere, so whatever
    # survives has to be placeable.
    known = {p["name"] for p in payload["places"]}
    for b in payload["buildings"]:
        ok(f"{b['id']} stands somewhere real", b["place"] in known, str(b))
        ok(f"{b['id']} has a position", b["x"] is not None and b["y"] is not None)

    # Tracks may name foreign places -- that is data, not a bug -- but every
    # POSITION the page can compute must resolve, so a track row either names a
    # known place or is not there at all.
    for aid, track in payload["tracks"].items():
        for row in track:
            ok(f"{aid} track place is real", row[1] in known, str(row))

def main() -> int:
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in tests:
        fn()
        print(f"  {fn.__name__}")
    if FAILURES:
        print(f"\nFAIL ({len(FAILURES)})")
        for f in FAILURES[:20]:
            print(f"  - {f}")
        return 1
    print(f"\nOK -- {len(tests)} sprite/render tests passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
