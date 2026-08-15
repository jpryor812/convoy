#!/usr/bin/env python3
"""Action schemas and the dispatcher.

The rule that must never silently break: the tool schemas are part of the CACHED
prefix. If they vary between calls or between agents, caching stops hitting and
the run goes from ~$66 to ~$293 against a $94 budget -- with no visible failure,
only an invoice.

The second rule: a malformed tool call must never take the simulation down. At
hour 63 of 120, one model emitting a bad argument has to cost that agent a tick,
not the run.

No network is touched here.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from convoy import actions as A
from convoy import data as D
from convoy import schemas as S
from convoy.events import EventLog
from convoy.state import Agent, Business, VehicleInstance, World

FAILURES: list[str] = []
HOUR = 3600.0


def check(label, actual, expected) -> None:
    if actual != expected:
        FAILURES.append(f"{label}: got {actual!r}, expected {expected!r}")


def ok(label, condition, detail="") -> None:
    if not condition:
        FAILURES.append(f"{label}{': ' + detail if detail else ''}")


def setup():
    w, log = World(), EventLog(None, echo_min=99)
    w.sim_time = 10 * HOUR
    a = Agent(id="A0001", name="Tester", model="rb", location="Town")
    a.denari = 2000.0
    a.inventory = {"Grain": 10}
    w.agents[a.id] = a
    v = VehicleInstance(id="V1", type="Donkey Cart", owner=a.id, location="Town")
    w.vehicles["V1"] = v
    a.owned_vehicles.append("V1")
    biz = Business(
        id="B0001", type="Tavern / Inn", name="Store", owner="Government",
        location="Town",
    )
    biz.inventory = {"Grain": 50}
    w.businesses[biz.id] = biz
    return w, log, a


# ---------------------------------------------------------------------------

def test_schemas_are_stable():
    """The cached prefix must be byte-identical every time it is built."""
    first = json.dumps(S.tool_schemas())
    second = json.dumps(S.tool_schemas())
    check("tool schemas are deterministic", first, second)


def test_every_action_is_exposed_and_described():
    tools = S.tool_schemas()
    names = {t["function"]["name"] for t in tools}

    check("one tool per action", len(tools), len(S.ACTIONS))
    ok("names match the action table", names == set(S.ACTIONS))

    for tool in tools:
        fn = tool["function"]
        ok(
            f"{fn['name']} has a real description",
            len(fn["description"]) > 20,
            fn["description"],
        )


def test_read_helpers_and_engine_internals_are_excluded():
    names = set(S.ACTIONS)
    for helper in ("visible_chat", "accessible_goods"):
        ok(f"{helper} is not a tool", helper not in names)
    ok("receive_stolen is engine-only", "receive_stolen" not in names)
    # ...but they must still exist, or something was renamed out from under us.
    for helper in ("visible_chat", "accessible_goods", "receive_stolen"):
        ok(f"{helper} still exists in actions", hasattr(A, helper))


def test_static_domains_are_enums():
    """Enums turn a hallucinated item name into an API-level rejection."""
    tools = {t["function"]["name"]: t["function"]["parameters"] for t in S.tool_schemas()}

    sell = tools["sell_to_business"]["properties"]
    ok("item is constrained", "enum" in sell["item"])
    ok("enum covers real goods", "Iron" in sell["item"]["enum"])
    ok("enum excludes invented goods", "Silver" not in sell["item"]["enum"])

    travel = tools["travel_to"]["properties"]["destination"]
    ok("destination is constrained", "enum" in travel)
    ok("spurs are reachable", "Kiln Row" in travel["enum"])
    ok("road places are reachable", "The Climb" in travel["enum"])

    found = tools["start_business"]["properties"]["type"]
    ok("business type is constrained", "enum" in found)
    ok("business enum is real", "Refinery" in found["enum"])


def test_runtime_ids_are_not_enums():
    """IDs change constantly; the observation is what supplies them."""
    tools = {t["function"]["name"]: t["function"]["parameters"] for t in S.tool_schemas()}
    for action, param in [
        ("sell_to_business", "business_id"),
        ("accept_trade", "offer_id"),
        ("invite_to_guild", "target_id"),
        ("mount", "vehicle_id"),
    ]:
        prop = tools[action]["properties"][param]
        ok(f"{action}.{param} is not an enum", "enum" not in prop)
        ok(f"{action}.{param} warns against invention", "invent" in prop.get("description", ""))


def test_required_matches_the_function_signature():
    """Defaults are optional, everything else is required -- derived, not typed out."""
    tools = {t["function"]["name"]: t["function"]["parameters"] for t in S.tool_schemas()}

    check("qty defaults, so is optional", "qty" in tools["buy_from_business"]["required"], False)
    ok("item has no default, so is required", "item" in tools["buy_from_business"]["required"])
    check("no-arg action requires nothing", tools["quit_job"]["required"], [])
    ok("hours defaults", "hours" not in tools["start_shift"]["required"])


def test_dispatch_runs_a_real_action():
    w, log, a = setup()
    ok_flag, detail = S.dispatch(w, log, a, "mount", {"vehicle_id": "V1"})
    ok("mount succeeded", ok_flag, detail)
    check("agent is mounted", a.mounted_vehicle, "V1")


def test_dispatch_rejects_unknown_action():
    w, log, a = setup()
    ok_flag, detail = S.dispatch(w, log, a, "steal_everything", {})
    check("unknown action refused", ok_flag, False)
    ok("says which action", "steal_everything" in detail)


def test_dispatch_rejects_bad_parameters():
    """A model inventing or omitting a parameter must get a readable rejection."""
    w, log, a = setup()

    ok_flag, detail = S.dispatch(w, log, a, "mount", {"vehicle": "V1"})
    check("unknown parameter refused", ok_flag, False)
    ok("names the bad parameter", "vehicle" in detail)

    ok_flag, detail = S.dispatch(w, log, a, "mount", {})
    check("missing parameter refused", ok_flag, False)
    ok("names the missing parameter", "vehicle_id" in detail)


def test_dispatch_survives_an_exception():
    """One bad call at hour 63 must cost a tick, not the run."""
    w, log, a = setup()
    ok_flag, detail = S.dispatch(
        w, log, a, "buy_from_business",
        {"business_id": "B0001", "item": "Grain", "qty": "lots"},   # wrong type
    )
    check("bad call refused, not raised", ok_flag, False)
    ok("error is reported", "failed" in detail or "unknown" in detail, detail)
    ok("error is logged", any(e.type == "action_error" for e in log.events))


def test_dispatch_returns_engine_refusals_verbatim():
    """The agent must learn WHY, or it will retry the same thing forever."""
    w, log, a = setup()
    a.inventory = {}
    ok_flag, detail = S.dispatch(
        w, log, a, "sell_to_business",
        {"business_id": "B0001", "item": "Iron", "qty": 5},
    )
    check("selling what you lack is refused", ok_flag, False)
    ok("refusal explains itself", len(detail) > 5, detail)


def test_llm_policy_builds_prompts_without_network():
    """dry_run must construct a full prompt and never touch the API."""
    from convoy import llm

    w, log, a = setup()
    policy = llm.LLMPolicy(log=log, dry_run=True)
    policy.decide(w, a, "reevaluation")

    events = [e for e in log.events if e.type == "llm_dry_run"]
    check("one dry-run event", len(events), 1)
    ok("prompt is substantial", events[0].detail["prompt_chars"] > 1000)


def test_llm_policy_demands_a_key():
    from convoy import llm
    import os

    saved = os.environ.pop("OPENROUTER_API_KEY", None)
    # Emptying the environment is not enough: __post_init__ calls load_env(),
    # which reads the repo's own .env straight back in. Without stubbing that,
    # this test passes only on a machine that has never been configured to run
    # the thing it is testing.
    real_load_env = llm.load_env
    llm.load_env = lambda *a, **k: {}
    try:
        raised = False
        try:
            llm.LLMPolicy(log=EventLog(None, echo_min=99))
        except RuntimeError as exc:
            raised = "OPENROUTER_API_KEY" in str(exc)
        ok("missing key fails loudly at startup", raised)
    finally:
        llm.load_env = real_load_env
        if saved is not None:
            os.environ["OPENROUTER_API_KEY"] = saved


def test_env_loader():
    """A .env must load, and a real environment variable must still win."""
    import os
    import tempfile
    from convoy.config import load_env

    with tempfile.TemporaryDirectory() as d:
        path = Path(d) / ".env"
        path.write_text(
            '# a comment\nOPENROUTER_API_KEY="sk-or-fromfile"\n'
            'export CONVOY_TEST_PLAIN=plain\nnot_a_pair\n',
            encoding="utf-8",
        )
        saved = os.environ.pop("OPENROUTER_API_KEY", None)
        try:
            loaded = load_env(path)
            check("quoted value is unquoted", loaded["OPENROUTER_API_KEY"], "sk-or-fromfile")
            check("export prefix tolerated", loaded["CONVOY_TEST_PLAIN"], "plain")
            ok("junk line skipped", "not_a_pair" not in loaded)

            # A real environment variable must override the file, so
            # OPENROUTER_API_KEY=... python3 run_phase2.py works without editing it.
            os.environ["OPENROUTER_API_KEY"] = "sk-or-from-shell"
            load_env(path)
            check("real env wins", os.environ["OPENROUTER_API_KEY"], "sk-or-from-shell")
        finally:
            os.environ.pop("CONVOY_TEST_PLAIN", None)
            os.environ.pop("OPENROUTER_API_KEY", None)
            if saved is not None:
                os.environ["OPENROUTER_API_KEY"] = saved

    check("absent .env is not an error", load_env(Path(d) / "gone.env"), {})


def test_env_file_is_gitignored():
    """The one failure here that cannot be undone: a key pushed to GitHub."""
    import subprocess

    root = Path(__file__).resolve().parent.parent
    result = subprocess.run(
        ["git", "check-ignore", ".env"], cwd=root, capture_output=True, text=True
    )
    ok(".env is gitignored", result.returncode == 0, "add '.env' to .gitignore")
    ok(".env.example is checked in", (root / ".env.example").is_file())


def test_tool_call_parsing_is_defensive():
    from convoy.llm import _parse_tool_call

    name, args = _parse_tool_call(
        {"function": {"name": "travel_to", "arguments": '{"destination": "Town"}'}}
    )
    check("well-formed call parses", (name, args), ("travel_to", {"destination": "Town"}))

    name, _ = _parse_tool_call({"function": {"name": "travel_to", "arguments": "{oops"}})
    check("malformed JSON is rejected, not raised", name, None)

    name, _ = _parse_tool_call({"function": {}})
    check("nameless call is rejected", name, None)

    name, args = _parse_tool_call(
        {"function": {"name": "quit_job", "arguments": {"already": "a dict"}}}
    )
    check("dict arguments are accepted", name, "quit_job")


def test_prefix_cost_is_within_budget():
    """Guards the number the caching decision rests on."""
    from convoy import observe as O

    tools_tok = len(json.dumps(S.tool_schemas())) // 4
    prefix_tok = len(O.static_briefing()) // 4 + tools_tok
    ok("cached prefix under 12k tokens", prefix_tok < 12000, f"~{prefix_tok} tokens")
    ok("prefix is large enough to cache", prefix_tok > 1024, f"~{prefix_tok} tokens")


def main() -> int:
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in tests:
        fn()
        print(f"  {fn.__name__}")
    if FAILURES:
        print(f"\nFAIL ({len(FAILURES)})")
        for f in FAILURES:
            print(f"  - {f}")
        return 1
    print(f"\nOK -- {len(tests)} schema/dispatch tests passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
