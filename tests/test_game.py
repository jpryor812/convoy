#!/usr/bin/env python3
"""Playing: a human in one seat of a world of agents, who do not know it.

Designer request, 2026-10-17. The player is named and placed like any other
citizen, acts through the same dispatcher with the same refusals, is woken the
same way (a feed line instead of a model call), and the world never waits for
them. A game can be paused, saved, and resumed.
"""

from __future__ import annotations

import contextlib
import re
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from convoy import actions as A
from convoy import observe as O
from convoy.game import Game, Settings
from convoy.llm import Usage

FAILURES: list[str] = []


def ok(label, condition, detail="") -> None:
    if not condition:
        FAILURES.append(f"{label}{': ' + detail if detail else ''}")


class StandIn:
    """Plays every model seat by doing nothing, and can pretend to spend."""

    def __init__(self):
        self.world_lock = contextlib.nullcontext()
        self.usage: dict[str, Usage] = {}
        self.asked: list[str] = []

    def decide(self, world, agent, reason) -> None:
        self.asked.append(agent.id)


def _game(tmp: Path, **kw) -> tuple[Game, StandIn]:
    models = StandIn()
    settings = Settings(cities={"aldermarch": 3, "cinderhold": 2}, your_city="cinderhold",
                        pace=1e6, workers=1, **kw)
    return Game.new(settings, tmp, models=models), models


def test_the_player_is_a_citizen_like_any_other() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        game, _ = _game(Path(tmp))
        w = game.world
        ok("five citizens", len(w.agents) == 5)
        you = game.you
        ok("living where they chose", w.city_of(you) == "cinderhold")
        pattern = re.compile(r"^Cinderhold-gpt-6-luna-\d\d$")
        ok("named like the neighbours",
           all(pattern.match(a.name) for a in w.agents_in("cinderhold")), you.name)
        other = next(a for a in w.agents.values() if a.id != you.id)
        seen = O.render(O.observe(w, game.log, other, "reevaluation", record_delivery=False))
        brief = O.briefing_for(w, other)
        # "player business" is the world's own word for any citizen's shop, so
        # only what could single someone out is checked for.
        ok("nothing tells the others",
           not re.search(r"\bhuman\b|\bplayed by\b|\breal person\b", seen + brief, re.I))
        game.engine.close()


def test_the_player_acts_through_the_same_rules() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        game, _ = _game(Path(tmp))
        r = game.act("travel_to", {"destination": game.you.location})
        ok("an action runs and answers like a tool call", "ok" in r and "message" in r, str(r))
        r = game.act("start_business", {"type": "Castle"})
        ok("and is refused for the same reasons", not r["ok"], r["message"])
        r = game.act("hire_npc_employee", {"business_id": "B0001", "role": "x"})
        ok("hidden tools are refused too", not r["ok"])
        calls = [e for e in game.log.events if e.type == "action_call" and e.actor == game.human_id]
        ok("and logged like an agent's call", len(calls) == 3)
        st = game.state()
        ok("the player sees what an agent sees", "YOU" in st["text"] and st["obs"]["you"]["id"] == game.human_id)
        names = {t["name"] for t in game.tools()}
        ok("every action is offered", {"travel_to", "pay", "start_business"} <= names
           and "hire_npc_employee" not in names)
        game.engine.close()


def test_the_world_runs_without_waiting_and_saves() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        game, models = _game(Path(tmp))
        game.start()
        deadline = time.time() + 20
        while game.world.sim_hour < 1.2 and time.time() < deadline:
            time.sleep(0.05)
        ok("the clock ran on its own", game.world.sim_hour >= 1.2, f"{game.world.sim_hour:.2f}")
        ok("the models were asked", game.human_id not in models.asked and len(models.asked) > 0)
        game.paused = True
        time.sleep(0.3)
        held = game.world.sim_time
        time.sleep(0.3)
        ok("pause holds the clock", game.world.sim_time == held)
        game.stop()
        ok("saved", (game.run_dir / "checkpoint.json").exists() and (game.run_dir / "game.json").exists())
        listed = Game.saved(Path(tmp))
        ok("listed as a saved game", listed and listed[0]["id"] == game.run_dir.name)
        again = Game.load(game.run_dir, models=StandIn())
        ok("resumes in the same seat at the same hour",
           again.human_id == game.human_id and abs(again.world.sim_time - held) < 3600 + 1)
        again.engine.close()


def test_the_budget_stops_the_spending() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        game, models = _game(Path(tmp), budget=1.0)
        models.usage["m"] = Usage(cost=1.5)
        game.start()
        time.sleep(0.5)
        ok("over budget, it pauses itself", game.paused and "budget" in game.note, game.note)
        game.stop()


def test_wakes_and_hunger_reach_the_player() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        game, _ = _game(Path(tmp))
        you = game.you
        game._wake(game.world, you, "arrived")
        you.sustenance_stage = "Hungry"
        game._wake(game.world, you, "reevaluation")
        kinds = [f["kind"] for f in game.feed_since(0)]
        ok("an arrival is a feed line", "wake" in kinds, str(kinds))
        ok("hunger is an alert", "alert" in kinds, str(kinds))
        game._wake(game.world, you, "reevaluation")
        ok("said once, not every quarter hour",
           [f["kind"] for f in game.feed_since(0)].count("alert") == 1)
        game.engine.close()


def test_walking_into_a_place_puts_the_player_there() -> None:
    """The 3D page moves the player's body; the server learns where they are
    when they step into a named place."""
    with tempfile.TemporaryDirectory() as tmp:
        game, _ = _game(Path(tmp))
        you = game.you
        here = you.location
        other = next(p for p in __import__("convoy.world_map", fromlist=["x"]).places_in("cinderhold")
                     if p != here)
        r = game.arrive(other)
        ok("arriving moves them", r["ok"] and you.location == other, str(r))
        ok("and is logged as a finished journey, for the map",
           any(e.type == "travel" and e.actor == you.id and e.detail.get("walked")
               for e in game.log.events))
        ok("a place outside this world is refused", not game.arrive("Kiln Row")["ok"])
        game.act("start_business", {"type": "Farm"})
        biz = you.owned_businesses[0] if you.owned_businesses else None
        if biz:
            game.act("apply_for_job", {"business_id": biz})
            game.act("start_shift", {"hours": 4})
            back = next(p for p in __import__("convoy.world_map", fromlist=["x"]).places_in("cinderhold")
                        if p != other)
            r = game.arrive(back)
            ok("walking off a shift ends it", you.activity.kind != "work" and "left your shift" in r["message"], str(r))
        game.engine.close()


def test_the_advisors_say_what_to_do_and_how_you_are_doing() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        game, _ = _game(Path(tmp))
        a = game.advisor()
        ok("there is always a next move", 1 <= len(a["advice"]) <= 3, str(a["advice"]))
        ok("each with a button", all("button" in m and m["button"]["kind"] for m in a["advice"]))
        ok("the first day's goals, none done yet", len(a["goals"]) == 7 and not any(g["done"] for g in a["goals"]))
        you = game.you
        you.sustenance_stage = "Hungry"
        first = game.advisor()["advice"][0]["text"]
        ok("hunger comes first", "eat" in first.lower() or "tavern" in first.lower() or "meal" in first.lower(), first)
        you.sustenance_stage = "Normal"
        game.act("start_business", {"type": "Tavern / Inn"})
        a = game.advisor()
        ok("founding ticks a goal", any(g["done"] for g in a["goals"] if g["goal"] == "Found a business"))
        ok("and the new business's first problem is the next move",
           any("making nothing" in m["text"] for m in a["advice"]), str([m["text"] for m in a["advice"]]))
        biz = you.owned_businesses[0]
        ok("your building carries a health flag", game.advisor()["markers"][biz]["health"] in ("good", "idle", "bad"))
        led = game.ledger()
        ok("the ledger has the measures", {m["name"] for m in led["metrics"]} >= {"Net worth", "Cash", "Businesses"})
        ok("and your business's books", led["businesses"] and led["businesses"][0]["id"] == biz)
        ok("the guide covers every business type", len(game.chains()["types"]) == len(__import__("convoy.data", fromlist=["x"]).BUSINESS_TYPES))
        # A day ends: a report.
        game.world.sim_time = 24 * 3600 + 60
        game._on_the_hour()
        ok("a report at the end of the day", game.reports and game.reports[-1]["day"] == 1)
        ok("and a line in the feed", any(f["kind"] == "report" for f in game.feed_since(0)))
        game.save()
        again = Game.load(game.run_dir, models=StandIn())
        ok("the history is saved with the game", again.history.rows)
        again.engine.close()
        game.engine.close()


def test_work_here_myself_starts_the_shift() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        game, _ = _game(Path(tmp))
        game.act("start_business", {"type": "Tavern / Inn"})
        biz = game.you.owned_businesses[0]
        r = game.act("apply_for_job", {"business_id": biz})
        ok("one click: on the roster and at work", r["ok"] and game.you.activity.kind == "work", str(r))
        game.act("end_shift", {})
        r = game.act("apply_for_job", {"business_id": biz})
        ok("already on the roster: it just starts work", r["ok"] and game.you.activity.kind == "work", str(r))
        game.engine.close()


def test_the_market_lists_what_is_priced() -> None:
    """Designer request, 2026-10-17: post your goods at a price you set, and see
    what everyone else has posted that you could buy."""
    with tempfile.TemporaryDirectory() as tmp:
        game, _ = _game(Path(tmp))
        game.act("start_business", {"type": "Tavern / Inn"})
        biz = game.world.businesses[game.you.owned_businesses[0]]
        biz.add_item("Meal", 5)
        m = game.market()
        mine = [g for g in m["goods"] if g["business"] == biz.id and g["item"] == "Meal"]
        ok("your stock is offered for pricing, unpriced", mine and mine[0]["price"] is None, str(mine))
        ok("unpriced stock is not on sale", not any(l["mine"] for l in m["listings"]))
        price = mine[0]["floor"] + 1
        r = game.act("set_retail_price", {"business_id": biz.id, "item": "Meal", "price": price})
        m = game.market()
        posted = [l for l in m["listings"] if l["mine"] and l["item"] == "Meal"]
        ok("a price puts it on the market", r["ok"] and posted and posted[0]["price"] >= price - 1e-9, str(r))
        ok("Meals are bought over the counter", posted and posted[0]["kind"] == "counter")
        game.you.add_item("Wheat", 3)
        carried = [g for g in game.market()["carried"] if g["item"] == "Wheat"]
        ok("what you carry can be listed where you stand", carried and carried[0]["list_at"] and carried[0]["list_at"][0]["id"] == biz.id, str(carried))
        game.engine.close()


def test_you_can_fetch_your_own_order() -> None:
    """Designer request, 2026-10-17: "I bought 10 wheat from a farm and wanted to
    go pick it up myself (not pay a courier fee)"."""
    with tempfile.TemporaryDirectory() as tmp:
        game, _ = _game(Path(tmp))
        w, you = game.world, game.you
        rival = next(a for a in w.agents.values() if a.id != you.id and w.city_of(a) == "cinderhold")
        rival.location = "Windmill Fields"
        A.start_business(w, game.log, rival, "Farm")
        farm = w.businesses[rival.owned_businesses[0]]
        farm.add_item("Wheat", 10)
        farm.retail_prices["Wheat"] = 3.0
        you.location = "Cinder Row"
        r = game.act("start_business", {"type": "Refinery"})
        ok("a refinery is affordable from the start", r["ok"], r["message"])
        ref = w.businesses[you.owned_businesses[0]]
        game.act("deposit", {"business_id": ref.id, "amount": 40})
        r = game.fetch({"my_business_id": ref.id, "seller_business_id": farm.id, "item": "Wheat", "qty": 10})
        ok("ordered with no courier fee, and sent to the farm", r["ok"] and r.get("go") == "Windmill Fields", str(r))
        ok("you carry what you can on foot; the rest waits",
           "5" in r["message"] and "other 5" in r["message"], r["message"])
        r = game.arrive("Windmill Fields")
        ok("walking in loads it, and sends you home", you.hauling and r.get("go") == "Cinder Row", str(r))
        r = game.arrive("Cinder Row")
        ok("walking home hands it over", ref.inventory.get("Wheat", 0) == 5 and not you.hauling, str(r))
        ok("and sends you back for the rest, already claimed", r.get("go") == "Windmill Fields"
           and any(c.courier == you.id and c.status == "claimed" for c in w.consignments.values()), str(r))
        moves = [m["button"] for m in game.advisor()["advice"]]
        ok("Next move says to pick it up", any(b.get("place") == "Windmill Fields" for b in moves), str(moves))
        game.arrive("Windmill Fields"); game.arrive("Cinder Row")
        ok("second trip: all ten are in", ref.inventory.get("Wheat", 0) == 10, str(dict(ref.inventory)))
        ok("and nobody was paid to carry it", not any(e.type == "consignment_delivered" and e.detail.get("fee")
                                                      for e in game.log.events))
        game.engine.close()


def _farm_and_refinery(game):
    w, you = game.world, game.you
    rival = next(a for a in w.agents.values() if a.id != you.id and w.city_of(a) == "cinderhold")
    rival.location = "Windmill Fields"
    A.start_business(w, game.log, rival, "Farm")
    farm = w.businesses[rival.owned_businesses[0]]
    you.location = "Cinder Row"
    game.act("start_business", {"type": "Refinery"})
    return rival, farm, w.businesses[you.owned_businesses[0]]


def test_buying_for_a_business_with_cash_in_your_pocket() -> None:
    """Designer request, 2026-10-17: "I shouldn't have to deposit money in my
    business to buy wheat from another farm"."""
    with tempfile.TemporaryDirectory() as tmp:
        game, _ = _game(Path(tmp))
        _, farm, ref = _farm_and_refinery(game)
        farm.add_item("Wheat", 10); farm.retail_prices["Wheat"] = 3.0
        ok("the refinery has no cash of its own", ref.cash < 1, str(ref.cash))
        pocket = game.you.denari
        r = game.fetch({"my_business_id": ref.id, "seller_business_id": farm.id, "item": "Wheat", "qty": 5})
        ok("ordered anyway, paid from your pocket", r["ok"] and game.you.denari < pocket, str(r))
        game.engine.close()


def test_buy_orders_are_posted_filled_and_cancelled() -> None:
    """Designer request, 2026-10-17: post prices and how many you want, so that
    people can fill those orders -- and hear when goods come up for sale."""
    with tempfile.TemporaryDirectory() as tmp:
        game, _ = _game(Path(tmp))
        w, you = game.world, game.you
        rival, farm, ref = _farm_and_refinery(game)
        game._collect_feed()                      # the market as it stands is not news
        pocket = you.denari
        r = game.act("post_buy_order", {"business_id": ref.id, "item": "Wheat", "qty": 10, "price": 2.5})
        ok("a buy order is posted and its money held", r["ok"] and abs(pocket - you.denari - 25) < 0.01, r["message"])
        r = game.act("post_buy_order", {"business_id": ref.id, "item": "Bread", "qty": 1, "price": 9})
        ok("only for something the business uses", not r["ok"], r["message"])
        order = next(iter(w.buy_orders.values()))
        farm.add_item("Wheat", 6)
        from convoy import observe as O2
        obs = O2.observe(w, game.log, rival, "reevaluation")
        ok("a seller who holds it is shown the order", any(o["order"] == order.id for o in obs.get("buy_orders_you_can_fill", [])),
           str(obs.get("buy_orders_you_can_fill")))
        before = farm.cash
        okf, msg = A.fill_buy_order(w, game.log, rival, order.id, farm.id)
        ok("an agent fills it from stock, paid at the asking price", okf and farm.cash - before > 14.9, msg)
        ok("partly: four are still wanted", order.qty == 4 and order.status == "open", str(order))
        con = next(c for c in w.consignments.values() if c.buyer_business == ref.id)
        ok("the goods wait at the farm for you, no carriage", con.qty == 6 and con.courier_fee == 0 and con.origin == "Windmill Fields")
        game._collect_feed()
        ok("you are told it was filled", any("filled your buy order" in f["text"] for f in game.feed), [f["text"] for f in game.feed][-3:])
        m = game.market()
        ok("the market shows your order and how far filled", m["my_orders"] and m["my_orders"][0]["qty"] == 4, str(m["my_orders"]))
        pocket = you.denari
        r = game.act("cancel_buy_order", {"order_id": order.id})
        ok("cancelling returns the rest to your pocket", r["ok"] and abs(you.denari - pocket - 10) < 0.01, f"{r} {you.denari}")
        farm.add_item("Wheat", 5); farm.retail_prices["Wheat"] = 3.0
        game._collect_feed()
        ok("a good you use coming up for sale is an alert", any(f["kind"] == "offer" and "Wheat" in f["text"] for f in game.feed),
           [f["text"] for f in game.feed][-3:])
        game.engine.close()


def main() -> int:
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for t in tests:
        t()
    print(f"test_game.py: {len(tests)} tests, {len(FAILURES)} failures")
    for f in FAILURES:
        print(f"  FAIL {f}")
    return 1 if FAILURES else 0


if __name__ == "__main__":
    raise SystemExit(main())
