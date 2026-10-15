#!/usr/bin/env python3
"""Two cities, one contest.

WHAT THIS FILE IS FOR. The whole two-city arrangement rests on two claims, and
neither is self-evidently true from reading the code:

  1. THE GROUND IS THE SAME. If one valley is easier than the other, the result
     measures the map instead of the play, and every conclusion is worthless.
  2. THE VALLEYS DO NOT TOUCH. Not "agents do not usually cross" -- there must
     be no road, no trade, no chat, no job, no price and no consignment that
     crosses, or the two economies are quietly one economy and the comparison
     is contaminated.

Everything here checks one of those two, plus the third thing that decides
whether any of it changes behaviour: THE AGENTS HAVE TO BE TOLD. PHASE8's whole
finding was that agents do exactly what the briefing says and nothing it does
not say, so a scoreboard the prompt never renders is a scoreboard nobody plays
for -- which is what `test_the_score_reaches_the_prompt` exists to stop
happening again.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from convoy import actions as A
from convoy import economy as E
from convoy import inspect as I
from convoy import observe as O
from convoy import world_map as M
from convoy.engine import Engine, EngineConfig
from convoy.events import EventLog
from convoy.state import Agent, Transaction, World
from convoy.world_setup import new_world

FAILURES: list[str] = []
HOUR = 3600.0
OTHER = M.CITY_KEYS[1]
HOME = M.CITY_KEYS[0]


def ok(label: str, cond: bool, detail: str = "") -> None:
    if not cond:
        FAILURES.append(f"{label}{': ' + detail if detail else ''}")


def check(label: str, actual, expected) -> None:
    if actual != expected:
        FAILURES.append(f"{label}: got {actual!r}, expected {expected!r}")


def contest(n: int = 3) -> tuple[World, EventLog]:
    log = EventLog(None, echo_min=99)
    world = new_world(log, [], {
        c: [(f"{M.CITIES[c].name}-{i:02d}", "test/model") for i in range(1, n + 1)]
        for c in (HOME, OTHER)
    })
    return world, log


def citizen(world: World, city: str) -> Agent:
    return world.agents_in(city)[0]


# ---------------------------------------------------------------------------
# 1. THE GROUND IS THE SAME
# ---------------------------------------------------------------------------

def test_the_valleys_are_mirrors() -> None:
    """The fairness guarantee, checked rather than asserted in prose.

    `world_map` runs this on import too. It is repeated here because an import
    assertion that stops firing is invisible, and because this is the single
    claim the entire experiment rests on.
    """
    M.assert_cities_are_mirrors()          # raises if they diverge

    for city in M.CITY_KEYS:
        check(f"{city}: three stops", len(M.locations_in(city)), 3)
        check(f"{city}: two segments", len(M.segments_in(city)), 2)
        check(f"{city}: four spurs", len(M.spurs_in(city)), 4)
        check(f"{city}: 160 plots",
              sum(M.plots_at(p) for p in M.places_in(city)), 160)
        # Every business type exists exactly once per city at hour zero.
        check(f"{city}: one government branch of each type",
              sorted(M.government_sites_for(city)),
              sorted(M.government_sites_for(HOME)))

    # Distances match, or one city is closer to its own market than the other.
    home_road = M.travel_seconds(*[M.locations_in(HOME)[i] for i in (0, 2)])
    away_road = M.travel_seconds(*[M.locations_in(OTHER)[i] for i in (0, 2)])
    check("both roads are the same length", round(home_road, 6), round(away_road, 6))

    # And the danger is the same danger, segment for segment.
    check("both roads are equally dangerous",
          [s.danger for s in M.segments_in(HOME)],
          [s.danger for s in M.segments_in(OTHER)])


def test_every_place_belongs_to_exactly_one_city() -> None:
    seen: dict[str, str] = {}
    for city in M.CITY_KEYS:
        for place in M.places_in(city):
            ok(f"{place} is in one city only", place not in seen,
               f"also in {seen.get(place)}")
            seen[place] = city
    check("every place is attributed", len(seen), len(M.EVERY_PLACE))
    for place in M.EVERY_PLACE:
        ok(f"{place} has a role", place in M.ROLE_OF)


def test_the_home_valley_is_untouched() -> None:
    """Aldermarch must still be, name for name, the map every earlier run used.

    Not cosmetic: every checkpoint, event log and rendered page on disk refers
    to these names, and a rename would make all of them unreadable.
    """
    check("the home road", M.LOCATIONS, ["Refinery Row", "The Hills", "Town"])
    check("the home spurs", [s.name for s in M.SPURS],
          ["Blindfold Draw", "Rockfall Cut", "Copper Gulch", "Millrace Farms"])
    check("the market", M.market_of(HOME), "Town")
    check("ALL_PLACES is still one valley", len(M.ALL_PLACES), 7)


# ---------------------------------------------------------------------------
# 2. THE VALLEYS DO NOT TOUCH
# ---------------------------------------------------------------------------

def test_there_is_no_road_between_them() -> None:
    world, log = contest()
    here, there = citizen(world, HOME), citizen(world, OTHER)

    ok("travel across the border is refused",
       not A.travel_to(world, log, here, there.location)[0])
    reason = A.travel_to(world, log, here, there.location)[1]
    # TWO DIFFERENT REFUSALS. "No such place" would teach an agent the rival
    # city is imaginary, and it would go on naming it.
    ok("and says why, not 'unknown location'",
       "no road" in reason.lower() and "unknown" not in reason.lower(), reason)
    ok("a place that really does not exist reads differently",
       "unknown" in A.travel_to(world, log, here, "Atlantis")[1].lower())

    try:
        M.travel_path(here.location, there.location)
        FAILURES.append("travel_path allowed a cross-city journey")
    except M.NoRoadThere:
        pass

    # ...and travel INSIDE a city still works, or the guard is too wide.
    ok("travel at home still works",
       A.travel_to(world, log, here, M.spurs_in(HOME)[0].name)[0])


def test_nothing_the_observation_offers_is_unreachable() -> None:
    """Every id, place and job an agent is shown must be one it can act on.

    This is PHASE4 §2 in its most expensive form: an observation that offers
    forty destinations where twenty are reachable does not merely waste tokens,
    it spends decisions on calls that can only be refused.
    """
    world, log = contest()
    here = citizen(world, HOME)
    here.denari = 5_000.0
    obs = O.observe(world, log, here, "reevaluation")

    foreign = set(M.places_in(OTHER))
    blob = repr(obs)
    for place in sorted(foreign):
        ok(f"the observation never names {place}", place not in blob)

    # The job centre is the agent's own market, and lists its own city's work.
    jobs = [ln for ln in obs["you_can"] if "JOB CENTRE" in ln]
    ok("the job board is the home market", jobs and M.market_of(HOME) in jobs[0],
       jobs[0] if jobs else "no job centre line")


def test_the_markets_are_separate() -> None:
    """Two isolated economies must have two price feeds.

    A shared ticker is not merely wrong, it is the channel through which two
    populations that are supposed to be running the same experiment separately
    would learn each other's prices.
    """
    world, _log = contest()
    world.sim_time = 4 * HOUR
    world.market.record(
        Transaction(1 * HOUR, "Copper Ore", 50, 5.0, "B1", "B2", city=HOME))
    world.market.record(
        Transaction(2 * HOUR, "Bronze", 10, 44.0, "B3", "B4", city=OTHER))

    mine = E.ticker(world, city=HOME)
    theirs = E.ticker(world, city=OTHER)
    ok("the home feed has the home trade", "Copper Ore" in mine)
    ok("and not the rival's", "Bronze" not in mine, str(sorted(mine)))
    ok("the rival feed has the rival trade", "Bronze" in theirs)
    ok("and not the home city's", "Copper Ore" not in theirs, str(sorted(theirs)))
    # No city at all is every trade -- what a spectator board wants.
    check("unscoped is the whole world", len(E.ticker(world)), 2)


def test_chat_does_not_carry_across_the_hills() -> None:
    world, log = contest()
    here, there = citizen(world, HOME), citizen(world, OTHER)
    A.post_world_chat(world, log, here, "grain is 9 at the bridge")

    ok("a neighbour hears it",
       any("grain is 9" in m.text for m in A.visible_chat(world, world.agents_in(HOME)[1])))
    ok("the rival city does not",
       not any("grain is 9" in m.text for m in A.visible_chat(world, there)))


def test_no_consignment_may_cross() -> None:
    """The one path that could create a load with no road to travel.

    Ordering is remote; carriage is not. A cross-city order would be refused by
    nothing until `suggested_courier_fee` raised on it, which kills the tick
    rather than the action.
    """
    from convoy.state import Business

    world, log = contest()
    here = citizen(world, HOME)
    mine = Business(id="B1", type="Refinery", name="Mine", owner=here.id,
                    location=M.CITIES[HOME].refinery_row, cash=5_000.0)
    world.businesses[mine.id] = mine
    here.owned_businesses.append(mine.id)
    rival_farm = next(
        b for b in world.businesses.values()
        if b.type == "Farm" and M.city_of(b.location) == OTHER
    )
    okay, why = A.order_from_business(
        world, log, here, mine.id, rival_farm.id, "Wheat", 5, 10.0)
    ok("a cross-city order is refused", not okay)
    ok("and says there is no road", "no road" in why.lower(), why)


# ---------------------------------------------------------------------------
# 3. THE AGENTS HAVE TO BE TOLD
# ---------------------------------------------------------------------------

def test_each_city_gets_its_own_briefing() -> None:
    world, _log = contest()
    here, there = citizen(world, HOME), citizen(world, OTHER)
    mine, theirs = O.briefing_for(world, here), O.briefing_for(world, there)

    ok("the two briefings differ", mine != theirs)
    ok("each names its own market", M.market_of(HOME) in mine
       and M.market_of(OTHER) in theirs)
    ok("and neither describes the other's ground",
       M.market_of(OTHER) not in mine and M.market_of(HOME) not in theirs)
    for text, city, rival in ((mine, HOME, OTHER), (theirs, OTHER, HOME)):
        ok(f"{city}: the objective names the rival city",
           M.CITIES[rival].name in text)
        ok(f"{city}: the city total comes first",
           "TOTAL Net Worth" in text and "FIRST:" in text)
        ok(f"{city}: personal rank comes second",
           "SECOND:" in text and "ranked against your own" in text)
        ok(f"{city}: dying is priced as a hole in the city's score",
           "DYING COSTS YOUR CITY" in text)
        ok(f"{city}: says there is no road",
           "THERE IS NO ROAD TO IT" in text)

    # A ONE-CITY WORLD READS EXACTLY AS IT ALWAYS DID, or every earlier run
    # stops being comparable to the next one.
    solo, solo_log = World(), EventLog(None, echo_min=99)
    lone = Agent(id="A1", name="Solo", model="m")
    solo.agents["A1"] = lone
    ok("a solo world gets the original briefing",
       O.briefing_for(solo, lone) == O.static_briefing())
    ok("and is told to maximise its OWN net worth",
       "maximise your own Net Worth" in O.briefing_for(solo, lone))


def test_the_score_reaches_the_prompt() -> None:
    """Built is not the same as SAID.

    Three PHASE8 blocks were built into the observation and never added to
    `render`'s list, so they were paid for on every call and reached no prompt
    at all. This asserts the contest block is not the fourth.
    """
    world, log = contest()
    here = citizen(world, HOME)
    here.denari = 1_200.0
    obs = O.observe(world, log, here, "reevaluation")

    view = obs.get("the_contest")
    ok("the contest block is built", view is not None)
    check("it names your city", view["your_city"], M.CITIES[HOME].name)
    check("and the rival", view["rival_city"], M.CITIES[OTHER].name)
    ok("it carries both totals",
       "your_city_total" in view and "rival_city_total" in view)
    ok("your own share of it", view["your_share_of_it"] == round(here.net_worth(world), 2))
    ok("and your rank among your own neighbours",
       "in " + M.CITIES[HOME].name in (view["your_rank_at_home"] or ""))
    ok("the standing is stated in words",
       any(w in view["standing"] for w in ("AHEAD", "BEHIND", "level")), view["standing"])

    text = O.render(obs)
    ok("THE CONTEST is rendered into the prompt", "THE CONTEST" in text)
    ok("with the numbers in it", M.CITIES[OTHER].name in text)
    # And it is near the top: the observation runs past 20,000 characters and a
    # score buried under the price tables is a score nobody plays for.
    ok("and it leads the payload",
       text.index("THE CONTEST") < text.index("WHERE YOU ARE"))

    # A one-city world must not grow a contest block out of nowhere.
    solo, solo_log = World(), EventLog(None, echo_min=99)
    lone = Agent(id="A1", name="Solo", model="m")
    solo.agents["A1"] = lone
    ok("no contest in a one-city world",
       O.observe(solo, solo_log, lone, "reevaluation").get("the_contest") is None)


def test_phase8_blocks_reach_the_prompt_too() -> None:
    """The three that did not, until 2026-09-03. See PHASE9 §2.

    Pinned by name so that adding a block to `observe` and forgetting to add it
    to `render` fails here rather than in a $6 run.
    """
    from convoy.world_setup import rule_based_roster

    log = EventLog(None, echo_min=99)
    world = new_world(log, rule_based_roster(2))
    world.sim_time = 1 * HOUR
    agent = list(world.agents.values())[0]
    world.drop_loot(agent.location, {"Wheat": 150}, 40.0)
    for biz in world.businesses.values():
        if biz.type in ("Refinery", "Farm", "Tavern / Inn"):
            biz.active_production = None
            biz.inventory.clear()
    world.market.record(Transaction(0.0, "Copper Ore", 50, 5.2, "B1", "B2"))

    obs = O.observe(world, log, agent, "reevaluation")
    text = O.render(obs)
    for key, marker in (
        ("nobody_makes", "NOBODY"),
        ("on_the_ground_here", "loot_ground"),
        ("market_prices", "Copper Ore"),
    ):
        ok(f"{key} is built", key in obs)
        ok(f"{key} reaches the prompt", marker in text)


# ---------------------------------------------------------------------------
# 4. THE SCORE ITSELF
# ---------------------------------------------------------------------------

def test_the_score_is_a_sum_and_a_death_is_a_hole_in_it() -> None:
    world, _log = contest(n=3)
    for i, agent in enumerate(world.agents_in(HOME)):
        agent.denari = 100.0 * (i + 1)          # 100 + 200 + 300
    check("the city total is the sum of its citizens",
          world.city_wealth(HOME), 600.0)

    standings = {r["city"]: r for r in world.city_standings()}
    check("mean is reported too", standings[HOME]["mean_net_worth"], 200.0)
    check("richest is named", standings[HOME]["richest"],
          world.agents_in(HOME)[2].name)

    # A citizen dying takes its whole contribution with it -- the survivors
    # averaging higher does not make it back.
    dead = world.agents_in(HOME)[2]
    dead.alive = False
    dead.denari = 0.0
    check("the total falls by the dead citizen's whole worth",
          world.city_wealth(HOME), 300.0)
    after = {r["city"]: r for r in world.city_standings()}
    check("the dead are counted, not dropped", after[HOME]["citizens"], 3)
    check("and reported as lost", after[HOME]["dead"], 1)
    ok("the mean does NOT rise by ignoring them",
       after[HOME]["mean_net_worth"] == 100.0, str(after[HOME]["mean_net_worth"]))


def test_the_race_is_recoverable_from_the_log() -> None:
    """There is one checkpoint and it is overwritten hourly (PHASE8 §8).

    So "when did they pull ahead?" is answerable only if the engine wrote the
    score down as it went.
    """
    world, log = contest()
    Engine(world, log, _Idle(),
           EngineConfig(duration_hours=4, speed=1e9,
                        checkpoint_every_hours=1.0)).run()

    rows = [e for e in log.events if e.type == "city_standings"]
    ok("the score was written hourly", len(rows) >= 6, f"{len(rows)} rows")
    check("both cities each hour", {e.detail["city"] for e in rows}, {HOME, OTHER})

    board = I.city_standings(world, log.events)
    ok("the board has a history", len(board["history"][HOME]) >= 3)
    ok("and a leader", board["leader"] in
       (M.CITIES[HOME].name, M.CITIES[OTHER].name))

    # ...and none of it reaches an agent's MEMORY, where it would evict real
    # news to restate a number already standing in the observation.
    agent = citizen(world, HOME)
    ok("the log rows stay out of memory",
       not any("city_standings" in line
               for line in O.memory_for(log, agent, world.sim_time)))


def test_the_leaderboard_can_be_split_by_city() -> None:
    """The page filters forty rows into twenty by these fields."""
    world, _log = contest()
    rows = I.leaderboard(world)
    ok("every row carries its city", all(r.get("city") for r in rows))
    ok("and a readable name", all(r.get("city_name") for r in rows))
    ok("and a rank among its own neighbours",
       all(r.get("rank_at_home") for r in rows))

    home_rows = [r for r in rows if r["city"] == HOME]
    check("ranks at home run 1..n",
          sorted(r["rank_at_home"] for r in home_rows),
          list(range(1, len(home_rows) + 1)))


class _Idle:
    """A policy that does nothing, so the engine's own bookkeeping is what runs."""

    def decide(self, world: World, agent: Agent, reason: str) -> None:
        return None


class _Idle:
    def decide(self, world, agent, reason):
        return None


def test_the_state_can_leave_one_city_and_stay_in_the_other() -> None:
    """The one-city withdrawal is the controlled experiment: Cinderhold loses
    its government at the hour, Aldermarch keeps its government for the whole
    run -- and nobody in Aldermarch is told anything happened, because the
    cities do not see each other's play."""
    world, log = contest()
    gov_here = [b for b in world.businesses.values()
                if b.is_government and M.city_of(b.location) == HOME]
    gov_there = [b.id for b in world.businesses.values()
                 if b.is_government and M.city_of(b.location) == OTHER]
    ok("both cities start with a government", gov_here and gov_there)
    plots_there = [p for p in world.plots.values()
                   if M.city_of(p.location) == OTHER and p.owner == "Government"]
    plots_here = [p.id for p in world.plots.values()
                  if M.city_of(p.location) == HOME and p.owner == "Government"]

    eng = Engine(world, log, _Idle(), EngineConfig(
        duration_hours=0.2, speed=1e9, checkpoint_every_hours=1e9,
        banditry=False, state_exits_at=0.05, state_exits_city=OTHER,
    ))
    eng.step_until(world.sim_time + 1800.0)

    ok("its government is gone from the city named",
       not any(bid in world.businesses for bid in gov_there))
    ok("and untouched in the other",
       all(b.id in world.businesses and not b.closed for b in gov_here))
    ok("only the named city's state land went back on the market",
       all(p.owner is None for p in plots_there)
       and all(world.plots[pid].owner == "Government" for pid in plots_here))
    check("the record is per city", world.state_gone_at(HOME), None)
    ok("...and says when, for the city it left", world.state_gone_at(OTHER) is not None)
    check("and is not a withdrawal from everywhere", world.state_withdrawn_at, None)

    here, there = citizen(world, HOME), citizen(world, OTHER)
    gone_text = "IS NOT COMING BACK"
    ok("the city it left is told, in the observation",
       gone_text in O.render(O.observe(world, log, there, "reevaluation")))
    ok("the city it stayed in is not",
       gone_text not in O.render(O.observe(world, log, here, "reevaluation")))
    ok("and the two briefings disagree about the state, as they must",
       O.briefing_for(world, here) != O.static_briefing(
           state_gone=True, city=HOME, rival=OTHER))
    withdrew = [e for e in log.events if e.type == "state_withdrew"]
    check("announced once", len(withdrew), 1)
    check("naming the city", withdrew[0].detail.get("city") if withdrew else None, OTHER)


def main() -> int:
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in tests:
        print(f"  {fn.__name__}")
        fn()
    print(f"\nRan {len(tests)} two-city tests.")
    if FAILURES:
        print(f"\nFAIL ({len(FAILURES)})")
        for f in FAILURES:
            print(f"  - {f}")
        return 1
    print("Mirrored ground, sealed borders, and a score the agents are told.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
