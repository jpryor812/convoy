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
    import importlib.util

    spec = importlib.util.spec_from_file_location("render_world", ROOT / "render_world.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)          # type: ignore[union-attr]
    return mod


def test_layout_places_every_location_and_spur() -> None:
    places = _renderer().build_places()
    check("23 places", len(places), len(M.LOCATIONS_SPEC) + len(M.SPURS))
    for loc in M.LOCATIONS_SPEC:
        ok(f"{loc.name} placed", loc.name in places)
    for spur in M.SPURS:
        ok(f"{spur.name} placed", spur.name in places)
        check(f"{spur.name} hangs off its junction",
              places[spur.name]["junction"], spur.junction)


def test_nothing_is_laid_out_off_canvas() -> None:
    """A place drawn at a negative x is invisible and nobody notices."""
    r = _renderer()
    half = 226 / 2
    for name, p in r.build_places().items():
        ok(f"{name} within canvas",
           half <= p["x"] <= r.CANVAS_W - half, f"x={p['x']}")


def test_dedupe_collapses_a_stationary_agent() -> None:
    r = _renderer()
    track = [[float(h), "Town", None] for h in range(21)]
    check("21 identical hourly samples collapse to 1", len(r.dedupe(track)), 1)
    track.append([21.0, "Kiln Row", None])
    check("a real move survives", len(r.dedupe(track)), 2)


def test_checkpoint_decoding_unwraps_the_custom_encoding() -> None:
    r = _renderer()
    encoded = {"__dict__": [["Iron", 4], ["Grain", 2]]}
    check("dict round-trip", r.decode(encoded), {"Iron": 4, "Grain": 2})
    check("seq round-trip", r.decode({"__seq__": [1, 2, 3]}), [1, 2, 3])


def test_a_real_run_reconstructs() -> None:
    r = _renderer()
    runs = [d for d in Path("runs/phase2").iterdir() if (d / "events.jsonl").exists()
            and (d / "events.jsonl").stat().st_size > 10_000]
    if not runs:
        return                                   # nothing to check against
    run = max(runs, key=lambda d: (d / "events.jsonl").stat().st_size)
    payload = r.load_run(run, r.build_places())

    ok("agents found", payload["agents"], run.name)
    ok("end hour positive", payload["end_hour"] > 0)
    ok("every agent has a track",
       all(a["id"] in payload["tracks"] for a in payload["agents"]))

    # A RUN BELONGS TO THE MAP IT WAS RECORDED ON, and that is worth saying out
    # loud rather than discovering as a wall of "place is not real" failures.
    #
    # The demo map dropped both protected zones and six spurs, so a run from the
    # seven-place valley names ground that no longer exists -- Drovers End,
    # Orchard Walk, and the rest. Nothing is wrong with either the run or the
    # renderer; they are simply describing different worlds.
    #
    # Any unknown place means a foreign map, because the simulation only ever
    # writes places it has. So the whole run is reported as foreign and skipped,
    # instead of one assertion firing per business standing on a deleted spur.
    known = {p["name"] for p in payload["places"]}
    seen = {row[1] for t in payload["tracks"].values() for row in t}
    seen |= {row[2] for t in payload["tracks"].values() for row in t
             if row[2] is not None}
    seen |= {b["place"] for b in payload["businesses"]}
    foreign = sorted(x for x in seen if x not in known)
    if foreign:
        print(f"  SKIP {run.name}: recorded on a different map "
              f"({len(foreign)} places this world does not have, "
              f"e.g. {', '.join(foreign[:3])})")
        return

    for aid, track in payload["tracks"].items():
        for row in track:
            ok(f"{aid} track place is real", row[1] in known, str(row))
            if row[2] is not None:
                ok(f"{aid} destination is real", row[2] in known, str(row))
    for b in payload["businesses"]:
        ok(f"business {b['id']} sits somewhere real", b["place"] in known, str(b))
    ok("payload is JSON-serialisable", json.dumps(payload) is not None)


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
