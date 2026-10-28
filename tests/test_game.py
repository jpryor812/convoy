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
from convoy import world_map as M
from convoy import data as D
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
        ok("an NPC hire at someone else's business is refused", not r["ok"])
        calls = [e for e in game.log.events if e.type == "action_call" and e.actor == game.human_id]
        ok("and logged like an agent's call", len(calls) == 3)
        st = game.state()
        ok("the player sees what an agent sees", "YOU" in st["text"] and st["obs"]["you"]["id"] == game.human_id)
        names = {t["name"] for t in game.tools()}
        ok("every action is offered", {"travel_to", "pay", "start_business", "hire_npc_employee"} <= names)
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
        ok("the first day starts with a farm or a mine", a["goals"][0]["goal"] == "Found a farm or a mine"
           and not a["goals"][0]["done"])
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
        farm.add_item("Wheat", 20)            # a donkey carries 10: two trips (2026-10-18)
        farm.retail_prices["Wheat"] = 2.0
        you.location = "Cinder Row"
        r = game.act("start_business", {"type": "Refinery"})
        ok("a refinery is affordable from the start", r["ok"], r["message"])
        ref = w.businesses[you.owned_businesses[0]]
        game.act("deposit", {"business_id": ref.id, "amount": 40})
        r = game.fetch({"my_business_id": ref.id, "seller_business_id": farm.id, "item": "Wheat", "qty": 20})
        ok("ordered with no courier fee, and sent to the farm", r["ok"] and r.get("go") == "Windmill Fields", str(r))
        ok("you carry what you can on foot; the rest waits",
           "10" in r["message"] and "other 10" in r["message"], r["message"])
        h = game.status()["haul"]
        ok("the compass points to the farm to load", h and not h["loaded"] and h["from"] == farm.id, str(h))
        r = game.arrive("Windmill Fields")
        ok("walking in loads it, and sends you home", you.hauling and r.get("go") == "Cinder Row", str(r))
        h = game.status()["haul"]
        ok("then home to your refinery", h and h["loaded"] and h["to"] == ref.id, str(h))
        r = game.arrive("Cinder Row")
        ok("walking home hands it over", ref.inventory.get("Wheat", 0) == 10 and not you.hauling, str(r))
        ok("and sends you back for the rest, already claimed", r.get("go") == "Windmill Fields"
           and any(c.courier == you.id and c.status == "claimed" for c in w.consignments.values()), str(r))
        moves = [m["button"] for m in game.advisor()["advice"]]
        ok("Next move says to pick it up", any(b.get("place") == "Windmill Fields" for b in moves), str(moves))
        game.arrive("Windmill Fields"); game.arrive("Cinder Row")
        ok("second trip: all twenty are in", ref.inventory.get("Wheat", 0) == 20, str(dict(ref.inventory)))
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
        before = rival.denari
        okf, msg = A.fill_buy_order(w, game.log, rival, order.id, farm.id)
        ok("an agent fills it from stock, paid at the asking price", okf and rival.denari - before > 14.9, msg)
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


def test_towns_open_with_the_state_four_and_characters() -> None:
    """Designer decision, 2026-10-18: each town starts with the state's
    Tavern, Farm, Mine and Refinery; everyone has a calling for life."""
    with tempfile.TemporaryDirectory() as tmp:
        game, _ = _game(Path(tmp), calling="Hauler")
        w, you = game.world, game.you
        for city in w.cities:
            state = sorted(b.type for b in w.businesses.values()
                           if b.is_government and M.city_of(b.location) == city)
            ok(f"{city}: the state's four", state == sorted(["Tavern / Inn", "Farm", "Mining Operation", "Refinery"]), str(state))
        ok("no tax", w.no_state and w.starter_sites)
        ok("you are what you picked", you.calling == "Hauler")
        ok("everyone has a calling", all(a.calling in D.CALLINGS for a in w.agents.values()))
        ok("a Hauler carries more: 11 on the donkey everyone starts with", you.carry_capacity(w) == 11, str(you.carry_capacity(w)))
        brief = O.briefing_for(w, you)
        ok("the briefing names the state's four", "FOUR STATE SITES" in brief, brief[:400])
        listings = game.market()["listings"]
        ok("the state's Meals are on the market", any(l["state"] and l["item"] == "Meal" for l in listings))
        game.engine.close()


def test_a_calling_speeds_your_own_businesses() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        game, _ = _game(Path(tmp))
        w, you = game.world, game.you
        you.location = "Cinder Row"
        game.act("start_business", {"type": "Refinery"})
        ref = w.businesses[you.owned_businesses[0]]
        game.act("set_production", {"business_id": ref.id, "output": "Grain"})
        game.act("apply_for_job", {"business_id": ref.id})
        you.calling = "Miner"
        plain = game.engine.production_rate(ref)
        you.calling = "Refiner"
        ok("a Refiner's refinery is 10% faster", abs(game.engine.production_rate(ref) - plain * 1.1) < 1e-6,
           f"{plain} -> {game.engine.production_rate(ref)}")
        game.engine.close()


def test_people_reports_and_threads() -> None:
    """Designer request, 2026-10-18: see everyone in town, what they own and
    what they are good at; buy a report on another town; talk in private."""
    with tempfile.TemporaryDirectory() as tmp:
        game, _ = _game(Path(tmp))
        w, you = game.world, game.you
        other = next(a for a in w.agents_in("cinderhold") if a.id != you.id)
        other.skill_hours["Miner"] = 40.0
        P = game.citizens()
        row = next(p for p in P["people"] if p["id"] == other.id)
        ok("my town: everyone, with calling and experience", row["calling"] and row["skills"][0]["level"] == "Expert", str(row))
        ok("wages are not shown", "wage" not in str(row))
        far = P["cities"][0]["key"]
        ok("another town is closed until you buy a report", game.citizens(far).get("locked"))
        cash = you.denari
        r = game.buy_report(far)
        ok("a report costs 100", r["ok"] and abs(cash - you.denari - 100) < 1e-6, str(r))
        rep = game.citizens(far)
        ok("and shows that town's people", not rep.get("locked") and rep["population"] > 0, str(rep)[:200])
        game.act("send_direct_message", {"target_id": other.id, "text": "Want to run my mine?"})
        A.send_direct_message(w, game.log, other, you.id, "For 12 an hour.")
        T = game.thread(other.id)
        ok("the thread has both sides, in order", [m["from_me"] for m in T["messages"]] == [True, False], str(T))
        game.engine.close()


def test_a_head_start_then_you_arrive() -> None:
    """Designer request, 2026-10-18: "load me in assuming the agents have been
    operating the town for 12 in-game hours already"."""
    from convoy import town as TOWN
    with tempfile.TemporaryDirectory() as tmp:
        towns, games = Path(tmp) / "towns", Path(tmp) / "games"
        s = Settings(cities={"aldermarch": 3, "cinderhold": 2}, your_city="cinderhold",
                     pace=1e6, workers=1, head_start=2, calling="Miner")
        ok("no town yet", TOWN.find_template(s, towns) is None)
        hs = TOWN.HeadStart(s, towns_dir=towns, models=StandIn())
        path = hs.run()
        ok("the towns ran two hours without you", path is not None and abs(hs.hour - 2.0) < 0.05, str(hs.progress()))
        ok("and were kept as a template", TOWN.find_template(s, towns) == path)
        game = Game.from_town(s, path, games, models=StandIn())
        w, you = game.world, game.you
        ok("you arrive at hour two", abs(w.sim_hour - 2.0) < 0.05, str(w.sim_hour))
        ok("as one more citizen of your town", len(w.agents_in("cinderhold")) == 3 and w.city_of(you) == "cinderhold")
        ok("named like the rest, the next in line", you.name.endswith("-03"), you.name)
        ok("with your calling, fed, and 300", you.calling == "Miner" and you.hours_since_last_meal == 0
           and you.denari == D.STARTING_DENARI)
        ok("told what you walked into", any("You arrive in" in f["text"] for f in game.feed), str(list(game.feed))[:300])
        ok("the template is untouched", "A00" in (path / "checkpoint.json").read_text()
           and you.id not in (path / "checkpoint.json").read_text())
        game.save()
        again = Game.load(game.run_dir, models=StandIn())
        ok("and the game saves and loads like any other", again.human_id == you.id)
        game.engine.close(); again.engine.close()


def _hours(game, h):
    game.engine.step_until(game.world.sim_time + h * 3600.0)


def test_projects_finish_sooner_with_crew_and_material() -> None:
    """Designer request, 2026-10-18: Civ's pyramids, 50 turns or 20."""
    from convoy import progress as PG
    with tempfile.TemporaryDirectory() as tmp:
        game, _ = _game(Path(tmp))
        w, you = game.world, game.you
        you.location = "Cinder Row"
        game.act("start_business", {"type": "Refinery"})
        ref = w.businesses[you.owned_businesses[0]]
        r = game.act("start_project", {"business_id": ref.id, "project": "Storehouse"})
        ok("a project starts, with an ETA", r["ok"] and "ready in" in r["message"], r["message"])
        slow = PG.eta_hours(w, ref, you)
        ref.add_item("Lumber", 20)
        fam = next(m for m in you.family if m.adult)
        game.act("assign_family", {"member_id": fam.id, "business_id": ref.id})
        fast = PG.eta_hours(w, ref, you)
        ok("crew and material bring it closer", fast < slow / 2, f"{slow:.1f}h -> {fast:.1f}h")
        tier = ref.storage_tier
        _hours(game, fast + 0.5)
        ok("and it finishes", ref.project is None and ref.storage_tier == tier + 1, str(ref.project))
        game.engine.close()


def test_know_how_lands_and_pays() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        game, _ = _game(Path(tmp))
        w, you = game.world, game.you
        r = game.act("research", {"tech": "masonry"})
        ok("tier two needs tier one first", not r["ok"], r["message"])
        r = game.act("research", {"tech": "saddles"})
        ok("a first tech starts", r["ok"] and "6.0h" in r["message"], r["message"])
        cap = you.carry_capacity(w)
        _hours(game, 6.2)
        ok("and lands on its own", "saddles" in you.tech and you.researching is None, str(you.tech))
        ok("and does what it said", you.carry_capacity(w) > cap, f"{cap} -> {you.carry_capacity(w)}")
        game.engine.close()


def test_a_household_grows_by_marriage() -> None:
    """Designer request, 2026-10-18: a family grows through diplomacy."""
    with tempfile.TemporaryDirectory() as tmp:
        game, _ = _game(Path(tmp))
        w, you = game.world, game.you
        ok("every citizen heads a house: a partner, a son and a daughter",
           all(a.house and [m.role for m in a.family] == ["partner", "son", "daughter"] for a in w.agents.values()))
        partner = you.family[0]
        ok("the partner is married to the head", partner.spouse == "__head__")
        for a in w.agents.values():               # nobody starves while we wait a month
            a.last_meal_window = 10_000.0
        other = next(a for a in w.agents_in("cinderhold") if a.id != you.id)
        _hours(game, 49)
        mine = next(m for m in you.family if m.role == "son")
        theirs = next(m for m in other.family if m.role == "daughter")
        ok("the children came of age", mine.adult and theirs.adult)
        r = game.act("propose_marriage", {"agent_id": other.id, "member_id": mine.id,
                                          "their_member_id": theirs.id, "dowry": 20})
        ok("a proposal goes out", r["ok"], r["message"])
        offer = next(iter(w.marriage_offers.values()))
        okm, msg = A.accept_marriage(w, game.log, other, offer.id)
        ok("accepted: theirs joins your household", okm and any(m.id == theirs.id for m in you.family), msg)
        ok("the houses are allies", other.id in you.allies and you.id in other.allies)
        ok("the dowry moved", other.denari == D.STARTING_DENARI + 20)
        r = game.act("create_guild", {"name": "The Salt Road"})
        ok("a clan needs an ally -- and now there is one", r["ok"] and other.id in w.guilds[you.guild].invited, r["message"])
        _hours(game, 30 * 24 + 2)
        ok("a month in, the couples have children", len(you.family) >= 6, str([(m.name, m.role) for m in you.family]))
        baby = next(m for m in you.family if not m.adult)
        you.inventory["Meal"] = 3
        left = baby.grown_at - w.sim_time
        r = game.act("feed_family", {"member_id": baby.id})
        ok("a Meal brings a child a day closer", r["ok"] and abs((left - (baby.grown_at - w.sim_time)) - 86400) < 1, r["message"])
        game.engine.close()


def test_a_partner_at_work_stays_at_work() -> None:
    """Designer report, 2026-10-18 (twice): "I put my partner to work and
    nothing is getting produced." Payroll sacked a 0-wage family hand as unpaid
    when the farm and its owner had no cash."""
    with tempfile.TemporaryDirectory() as tmp:
        game, _ = _game(Path(tmp))
        w, you = game.world, game.you
        you.location = M.spurs_in(w.city_of(you))[0].name
        r = game.act("start_business", {"type": "Farm"})
        ok("a farm", r["ok"], r["message"])
        biz = w.businesses[you.owned_businesses[-1]]
        partner = you.family[0]
        r = game.act("assign_family", {"member_id": partner.id, "business_id": biz.id})
        ok("the partner goes to work", r["ok"], r["message"])
        game.act("set_production", {"business_id": biz.id, "output": "Wheat"})
        you.denari, biz.cash = 0.0, 0.0
        you.last_meal_window = 10_000.0
        _hours(game, 6)
        ok("still on the roster after payroll", any(e.agent_id.startswith("family:") for e in biz.roster),
           str([vars(e) for e in biz.roster]))
        ok("and the farm made something", sum(biz.inventory.values()) > 0, str(dict(biz.inventory)))
        biz.roster.clear()                        # whatever drops them, they come back
        _hours(game, 0.2)
        ok("a dropped family hand is put back", any(e.agent_id.startswith("family:") for e in biz.roster))
        game.engine.close()


def test_a_bat_against_bandits() -> None:
    """Designer request, 2026-10-18: everyone starts with a bat; R swings, F
    blocks. The page plays the fight, the server keeps score."""
    from convoy import combat as CB
    from convoy import missions as MI
    with tempfile.TemporaryDirectory() as tmp:
        game, _ = _game(Path(tmp))
        w, you = game.world, game.you
        ok("everyone starts with a bat", all(a.equipped_weapon == "Bat" for a in w.agents.values()))
        r = game.fight_op({"op": "camp"})
        ok("no camp, no fight", not r["ok"])
        you.missions_done = ["harvest"]
        r = game.mission({"action": "start", "id": "bounty"})
        ok("the bounty starts", r["ok"], r["message"])
        you.location = you.mission["place"]
        r = game.fight_op({"op": "camp"})
        ok("walking up to the camp starts a fight", r["ok"] and len(r["fight"]["foes"]) == 2, str(r))
        hp = you.health
        r = game.fight_op({"op": "struck", "foe": "bandit0", "blocked": True})
        blocked = hp - you.health
        r = game.fight_op({"op": "struck", "foe": "bandit0", "blocked": False})
        ok("a block stops four fifths", abs((hp - blocked - you.health) - CB.BANDIT_HIT) < 0.01 and abs(blocked - CB.BANDIT_HIT * 0.2) < 0.01,
           f"blocked {blocked:.1f}")
        r = game.fight_op({"op": "swing", "foe": "bandit0"})
        r2 = game.fight_op({"op": "swing", "foe": "bandit0"})
        ok("no faster than the bat swings", not r2["ok"] and r2["message"] == "too soon", str(r2))
        reward = MI.by_id("bounty")["reward"]
        coins, n = you.denari, 1
        while game.fight is not None and n < 20:
            game.fight.last_swing = -1e9
            foe = next(f.id for f in game.fight.foes if f.hp > 0)
            r = game.fight_op({"op": "swing", "foe": foe}); n += 1
        ok("eight-odd swings of a bat win it", r["fight"]["over"] == "won" and 6 <= n <= 9, f"{n} swings: {r['message']}")
        ok("and finish the mission", "bounty" in you.missions_done and you.denari == coins + reward, r["message"])

        # The road: carrying goods, out between places.
        you.protected_until = 0.0
        you.inventory["Iron"] = 20
        got = CB.road_check(w, game.log, you, -1e12, rng=type("R", (), {"random": lambda self: 0.0})())
        ok("bandits on the road go for a laden rider", got is not None and got.kind == "ambush")
        you.protected_until = w.sim_time + 3600
        ok("never a newcomer", CB.road_check(w, game.log, you, -1e12, rng=type("R", (), {"random": lambda self: 0.0})()) is None)
        you.protected_until = 0.0
        game.fight, game.last_ambush = got, w.sim_time
        you.health = CB.KNOCKED_DOWN + 1
        r = game.fight_op({"op": "struck", "foe": got.foes[0].id, "blocked": False})
        ok("knocked down on the road, they take half", r["fight"]["over"] == "lost" and you.inventory.get("Iron") == 10, r["message"])
        r = game.fight_op({"op": "camp"})
        ok("too hurt to go at a camp", not r["ok"])
        hp = you.health
        you.hours_since_last_meal, you.sustenance_stage = 0.0, "Normal"
        _hours(game, 2)
        ok("health comes back while fed", you.health > hp, f"{hp} -> {you.health}")
        game.engine.close()


def test_eating_walking_off_and_what_people_own() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        game, _ = _game(Path(tmp))
        w, you = game.world, game.you
        you.inventory["Meal"] = 1
        you.hours_since_last_meal = 20.0
        r = game.eat({"carried": True})
        ok("eat a meal you carry", r["ok"] and you.hours_since_last_meal == 0 and "Meal" not in you.inventory, r["message"])
        ok("the card says what you can eat", "carried" in game.me() and "health" in game.me())
        you.location = M.spurs_in(w.city_of(you))[0].name
        game.act("start_business", {"type": "Farm"})
        biz = w.businesses[you.owned_businesses[-1]]
        game.act("set_production", {"business_id": biz.id, "output": "Wheat"})
        r = game.act("apply_for_job", {"business_id": biz.id})       # the page's "Work here myself"
        if you.activity.kind != "work":
            r = game.act("start_shift", {"hours": 4})
        ok("at work", you.activity.kind == "work", str(r))
        r = game.depart()
        ok("walking out of the place ends the shift", you.activity.kind != "work" and "shift" in r["message"], r["message"])
        a = game.assets(you.id)
        ok("what someone owns adds up to their worth",
           abs(sum(v for _, v in a["lines"]) - a["worth"]) < 1.0 and a["businesses"][0]["type"] == "Farm", str(a["lines"]))
        other = next(x for x in w.agents.values() if x.id != you.id)
        ok("anyone's, from the leaderboard", game.assets(other.id)["name"] == other.name)
        game.engine.close()


def test_the_ground_wears_and_the_air_fouls() -> None:
    """Designer request, 2026-10-18: mines and farms deplete, refineries (and
    anything run fast) pollute, and upgrades push back."""
    from convoy import ground as GR
    from convoy import progress as PG
    with tempfile.TemporaryDirectory() as tmp:
        game, _ = _game(Path(tmp))
        w, you = game.world, game.you
        you.denari = 5000
        spur = M.spurs_in(w.city_of(you))[0].name
        you.location = spur
        game.act("start_business", {"type": "Mining Operation"})
        mine = w.businesses[you.owned_businesses[-1]]
        game.act("set_production", {"business_id": mine.id, "output": "Iron Ore"})
        game.act("assign_family", {"member_id": you.family[0].id, "business_id": mine.id})
        fresh = game.engine.production_rate(mine)
        for _ in range(40):                       # dig, carting the ore away each hour
            _hours(game, 1); mine.inventory.clear()
        ok("a seam runs down as it is dug", 0.3 < mine.richness < 0.6, f"{mine.richness:.2f}")
        GR.worked(w, game.log, mine, "Iron Ore", int(D.production_rate_hr("Iron Ore") * 60))
        ok("and is worked out in a few days", GR.spent(mine) and game.engine.production_rate(mine) == 0.0,
           f"{mine.richness:.2f}")
        ok("which the owner is told", any(e.type == "seam_spent" for e in game.log.events))
        head, why = game.engine.production_headroom(mine)
        ok("nothing more comes out", head == 0 and "worked out" in why, why)
        GR.improved(mine, "Deeper shaft")
        ok("a deeper shaft reaches fresh ore", game.engine.production_rate(mine) > 0 and mine.richness == 0.5)
        ok("mines get mine upgrades, not farm ones",
           "Deeper shaft" in PG.available(mine) and "Crop rotation" not in PG.available(mine))
        r = game.act("start_project", {"business_id": mine.id, "project": "Crop rotation"})
        ok("and cannot build them", not r["ok"], r["message"])

        # A farm tires, and rests back.
        you.location = M.spurs_in(w.city_of(you))[1].name
        r = game.act("start_business", {"type": "Farm"})
        farm = w.businesses[you.owned_businesses[-1]]
        ok("a farm", r["ok"] and farm.type == "Farm", r["message"])
        game.act("set_production", {"business_id": farm.id, "output": "Wheat"})
        GR.worked(w, game.log, farm, "Wheat", int(D.production_rate_hr("Wheat") * 40))
        tired = farm.richness
        ok("forty hours of wheat tire a field", tired < 0.2 and GR.depletion_multiplier(farm) < 0.6,
           f"{tired:.2f} -> pace {GR.depletion_multiplier(farm):.2f}")
        farm.active_production = None
        _hours(game, 12)
        ok("and a resting field recovers", farm.richness > tired + 0.4, f"{tired:.2f} -> {farm.richness:.2f}")

        # A refinery next door fouls the air.
        before = GR.air_multiplier(w, farm)
        spur = farm.location
        you.location = spur
        # A refinery belongs on the main road; stand one beside the farm anyway.
        you.location, you.denari = "Cinder Row", 5000.0
        r = game.act("start_business", {"type": "Refinery"})
        ref = w.businesses[you.owned_businesses[-1]]
        ok("a refinery", r["ok"] and ref.type == "Refinery", r["message"])
        ref.location = spur
        GR.worked(w, game.log, ref, "Grain", int(D.production_rate_hr("Grain") * 30))
        w.sim_time += 1                           # a new moment: the air is recomputed
        hit = GR.air_multiplier(w, farm)
        ok("refinery smoke slows the farm beside it", hit < before - 0.1, f"{before:.2f} -> {hit:.2f}")
        ok("crops suffer more than refinery hands", 1 - hit > 1 - GR.air_multiplier(w, ref))
        smoke = ref.smoke
        ref.improvements["Tall chimney"] = 1
        GR.worked(w, game.log, ref, "Grain", int(D.production_rate_hr("Grain") * 30))
        ok("a tall chimney cuts the smoke", ref.smoke - smoke < smoke * 0.7, f"{smoke:.1f} then +{ref.smoke - smoke:.1f}")
        _hours(game, 24)
        ok("and smoke thins with time: halved every 8 hours", ref.smoke < 8, f"{ref.smoke:.1f}")
        game.engine.close()


def test_an_heir_takes_over() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        game, _ = _game(Path(tmp))
        w, you = game.world, game.you
        you.location = "Cinder Row"
        game.act("start_business", {"type": "Refinery"})
        game.engine._kill(you, "violence")
        ok("the house goes on", you.alive and you.owned_businesses, f"alive={you.alive}")
        ok("the heir left the household", sum(m.adult for m in you.family) == 0)
        game.engine.close()


def test_the_core_is_patrolled_and_rivers_are_safe() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        game, _ = _game(Path(tmp))
        w, you = game.world, game.you
        market = M.market_of("cinderhold")
        seg = next(s for s in M.EVERY_SEGMENT if market in (s.a, s.b))
        you.location = market
        r = game.act("plan_raid", {"segment": seg.name})
        ok("no ambush on a road into the market", not r["ok"] and "patrolled" in r["message"], r["message"])
        from convoy.state import VehicleInstance
        v = VehicleInstance(id=w.new_id("V"), type="River Barge", owner=you.id, location=market)
        w.vehicles[v.id] = v; you.owned_vehicles.append(v.id); you.mounted_vehicle = v.id
        far = M.market_of("aldermarch")
        r = game.act("travel_to", {"destination": far})
        ok("a barge needs the know-how", not r["ok"] and "River barges" in r["message"], r["message"])
        you.tech += ["saddles", "barges"]
        r = game.act("travel_to", {"destination": "Cinder Row"})
        ok("and sails only quay to quay", not r["ok"] and "quays" in r["message"], r["message"])
        road = __import__("convoy.economy", fromlist=["x"]).travel_seconds(market, far, None)
        r = game.act("travel_to", {"destination": far})
        ok("between the towns it goes, faster than walking", r["ok"]
           and you.activity.ends_at - w.sim_time < road and you.activity.detail.get("by_water"), r["message"])
        game.engine.close()


def test_a_town_of_your_own_and_selling_to_the_best_bidder() -> None:
    """Designer request, 2026-10-18: start alone in a new town beside the
    agents' towns, found a farm, and sell to whichever refinery pays best."""
    with tempfile.TemporaryDirectory() as tmp:
        s = Settings(cities={"aldermarch": 3, "cinderhold": 2}, your_city="thornwick", solo=True,
                     pace=1e6, workers=1, head_start=0, sex="f", partner_sex="f")
        game = Game.new(s, Path(tmp), models=StandIn())
        w, you = game.world, game.you
        ok("your own town, nobody else in it", "thornwick" in w.cities and w.agents_in("thornwick") == [you])
        ok("with the state's four", sum(1 for b in w.businesses.values() if b.is_government
                                        and M.city_of(b.location) == "thornwick") == 4)
        ok("a home of four plots in the square", sum(1 for q in w.plots.values() if q.home and q.owner == you.id) == 4)
        ok("you and your partner as chosen", you.sex == "f" and you.family[0].sex == "f" and you.family[0].role == "partner")
        you.location = "Hollow Draw"
        game.act("start_business", {"type": "Farm"})
        farm = w.businesses[you.owned_businesses[0]]
        farm.add_item("Wheat", 20)
        # A citizen's refinery next door, making Grain, short of Wheat.
        rival = next(a for a in w.agents_in("aldermarch"))
        rival.location = "Refinery Row"
        A.start_business(w, game.log, rival, "Refinery")
        ref = w.businesses[rival.owned_businesses[0]]
        A.set_production(w, game.log, rival, ref.id, "Grain")
        bids = game.market()["bids"]["Wheat"]
        ok("the best bid is a citizen's, above the state's", bids[0]["business"] == ref.id
           and bids[0]["price"] > bids[-1]["price"], str(bids))
        cash = you.denari
        r = game.act("sell_to_bidder", {"business_id": farm.id, "buyer_business_id": ref.id, "item": "Wheat"})
        ok("sold, paid at once -- into your own pocket", r["ok"] and you.denari > cash and farm.cash == 0, r["message"])
        ok("and their courier is sent for it", any(c.buyer_business == ref.id and c.courier_fee > 0
                                                  for c in w.consignments.values()))
        r = game.act("sell_to_bidder", {"business_id": farm.id, "item": "Wheat",
                                        "buyer_business_id": next(b.id for b in w.businesses.values()
                                                                  if b.is_government and b.type == "Refinery"
                                                                  and M.city_of(b.location) == "thornwick")})
        ok("the rest to the state, at its low fixed price", r["ok"] and farm.inventory.get("Wheat", 0) == 0, r["message"])
        game.engine.close()


def test_overtaking_is_reported_without_crashing() -> None:
    """The 2026-10-18 crash: two citizens swapping places in an hour."""
    from convoy import advisor as ADV
    with tempfile.TemporaryDirectory() as tmp:
        game, _ = _game(Path(tmp))
        w, me = game.world, game.human_id
        other = next(a for a in w.agents if a != me)
        h = ADV.History()
        h.rows = [{"agents": {me: [300, 0, 2], other: [310, 0, 1]}},
                  {"agents": {me: [320, 0, 1], other: [305, 0, 2]}}]
        lines = ADV.overtakes(h, me, w)
        ok("you passing someone is news, not a crash", lines and "You passed" in lines[0], str(lines))
        game.engine.close()


def test_defenses_switching_benches_and_wheat() -> None:
    """Designer requests, 2026-10-18: guard posts and catapults on one square;
    moving from your farm to your mine without "quit first"; slower Wheat."""
    from convoy import raids as R
    with tempfile.TemporaryDirectory() as tmp:
        game, _ = _game(Path(tmp))
        w, you = game.world, game.you
        ok("Wheat at half speed", D.production_rate_hr("Wheat") == 36)
        market = M.market_of("cinderhold")
        seg = next(s for s in M.EVERY_SEGMENT if market not in (s.a, s.b) and M.city_of(s.a) == "cinderhold")
        you.location = seg.a
        base = R.defense_factor(w, seg)
        r = game.act("build_defense", {"kind": "Catapult"})
        ok("a catapult costs 250", r["ok"] and you.denari == D.STARTING_DENARI - 250, r["message"])
        ok("and blunts raiders on its roads", abs(R.defense_factor(w, seg) - base * 0.75) < 1e-9)
        ok("on one square of its own", sum(1 for q in w.plots.values() if q.structure == "Catapult") == 1)
        you.denari = 2000
        you.location = "Windmill Fields"
        game.act("start_business", {"type": "Farm"})
        farm = you.owned_businesses[0]
        you.location = "Iron Gulch"
        game.act("start_business", {"type": "Mining Operation"})
        mine = you.owned_businesses[1]
        you.location = "Windmill Fields"
        game.act("apply_for_job", {"business_id": farm})
        game.act("end_shift", {})
        you.location = "Iron Gulch"
        r = game.act("apply_for_job", {"business_id": mine})
        ok("from the farm to the mine in one click", r["ok"] and you.current_job[0] == mine
           and you.activity.kind == "work", r["message"])
        game.engine.close()


def test_a_delivery_run() -> None:
    """Designer request, 2026-10-18: something to do while goods are made --
    load the donkey, ride to a buyer, get paid more than at the gate."""
    with tempfile.TemporaryDirectory() as tmp:
        s = Settings(cities={"aldermarch": 3, "cinderhold": 2}, your_city="thornwick", solo=True,
                     pace=1e6, workers=1, head_start=0)
        game = Game.new(s, Path(tmp), models=StandIn())
        w, you = game.world, game.you
        ok("everyone starts on a donkey that carries ten",
           all(a.mounted_vehicle and w.vehicles[a.mounted_vehicle].type == "Donkey" for a in w.agents.values())
           and you.carry_capacity(w) == 10)
        you.location = "Hollow Draw"
        game.act("start_business", {"type": "Farm"})
        farm = w.businesses[you.owned_businesses[0]]
        farm.add_item("Wheat", 30)
        offers = game.deliveries()["offers"]
        away = next(o for o in offers if o["item"] == "Wheat" and o["state"] and o["city"] != "thornwick")
        ok("a buyer in another town pays more than the gate", away["unit"] > away["gate"], str(away))
        r = game.delivery({"business_id": farm.id, "buyer_business_id": away["buyer"], "item": "Wheat"})
        ok("taken, and loaded at once (you are at the farm)", r["ok"] and you.inventory.get("Wheat") == 10, r["message"])
        cash = you.denari
        game.arrive(away["place"])
        ok("riding in hands it over and pays", you.delivery is None and you.denari > cash
           and you.inventory.get("Wheat", 0) == 0, f"{you.denari} {you.delivery}")
        ok("paid the delivered price, and the first-harvest bonus", abs(you.denari - cash - away["unit"] * 10 - 60) < 0.01,
           f"{you.denari - cash}")
        game.engine.close()


def test_the_state_market_and_the_mission_chain() -> None:
    """Designer request, 2026-10-18: the state buys anything low and sells
    finished goods high; three missions teach the roads, a fight and trade."""
    import random as _r
    from convoy import missions as MI
    with tempfile.TemporaryDirectory() as tmp:
        s = Settings(cities={"aldermarch": 3, "cinderhold": 2}, your_city="thornwick", solo=True,
                     pace=1e6, workers=1, head_start=0)
        game = Game.new(s, Path(tmp), models=StandIn())
        w, you = game.world, game.you
        state = next(b for b in w.businesses.values() if b.is_government and b.type == "Mining Operation")
        ok("the state buys a good it has no use for, at the floor",
           A.standing_bid(w, state, "Tanned Leather") == (round(D.base_price("Tanned Leather") * 0.4, 2), 999))
        store = next(b for b in w.businesses.values() if b.is_government and b.type == "Tavern / Inn")
        ok("and sells weapons from its store, at the ceiling",
           any(i in D.WEAPONS for i in __import__("convoy.world_setup", fromlist=["x"]).state_offers(store)))
        board = game.missions()["board"]
        ok("the first is an achievement, waiting for a farm", [r["status"] for r in board] == ["needs", "locked", "locked"], str(board))
        you.location = "Hollow Draw"
        game.act("start_business", {"type": "Farm"})
        farm = w.businesses[you.owned_businesses[0]]
        farm.add_item("Wheat", 10)
        ok("with a farm it is under way by itself", game.missions()["board"][0]["status"] == "active")
        ref = next(o for o in game.deliveries()["offers"] if o["item"] == "Wheat" and o["type"] == "Refinery")
        game.delivery({"business_id": farm.id, "buyer_business_id": ref["buyer"], "item": "Wheat"})
        cash = you.denari
        game.arrive(ref["place"])
        ok("delivering your own harvest to a refinery earns it",
           "harvest" in you.missions_done and you.denari == cash + ref["unit"] * 10 + 60, f"{you.denari} vs {cash}")
        r = game.mission({"action": "start", "id": "bounty"})
        ok("the bounty opens next", r["ok"] and you.mission["id"] == "bounty", r["message"])
        camp = you.mission["place"]
        ok("the odds favour a first fight", MI.odds(w, you) > 0.6, str(MI.odds(w, you)))
        game.arrive(camp)
        okl, msg = MI.attack(w, game.log, you, rng=_r.Random(0) if False else type("R", (), {"random": lambda self: 0.99})())
        ok("a loss hurts but does not end the mission", not okl and you.mission and you.health < 100, msg)
        okw, msg = MI.attack(w, game.log, you, rng=type("R", (), {"random": lambda self: 0.0})())
        ok("a win clears the camp and pays", okw and "bounty" in you.missions_done, msg)
        ok("then a delivery to a citizen, under way by itself",
           game.missions()["board"][2]["status"] == "active")
        game.engine.close()


def test_land_pockets_geography_and_loading() -> None:
    """Designer requests, 2026-10-18: rich ground comes in pockets, near water
    for farms and mountains for mines; a delivery loads while you wait."""
    from convoy import land as LAND
    from convoy.state import Business
    with tempfile.TemporaryDirectory() as tmp:
        game, _ = _game(Path(tmp))
        w, you = game.world, game.you
        spurs = [p for p in M.EVERY_PLACE if D.is_spur(p) and M.city_of(p) in w.cities]
        place = next(p for p in spurs if LAND.pocket(w, p, "Farm"))
        a, b = (Business(id=f"BX{i}", type="Farm", name="x", owner=you.id, location=place) for i in (1, 2))
        LAND.roll(w, a); LAND.roll(w, b)
        ok("two farms at one place share its pocket", a.land_bonus_item == b.land_bonus_item
           and abs(a.land_bonus_pct - b.land_bonus_pct) <= 0.04, f"{a.land_bonus_item} {b.land_bonus_item}")
        wet = sorted(spurs, key=lambda p: -LAND.affinity(w, p, "Farm"))
        ok("water matters for farms", LAND.affinity(w, wet[0], "Farm") > LAND.affinity(w, wet[-1], "Farm"))
        you.location = "Windmill Fields"
        game.act("start_business", {"type": "Farm"})
        farm = w.businesses[you.owned_businesses[0]]
        buyer = next(bz for bz in w.businesses.values() if bz.is_government and bz.type == "Refinery")
        r = game.delivery({"business_id": farm.id, "buyer_business_id": buyer.id, "item": "Wheat"})
        ok("no goods, no job", not r["ok"] and "make some first" in r["message"], r["message"])
        farm.add_item("Wheat", 3)
        r = game.delivery({"business_id": farm.id, "buyer_business_id": buyer.id, "item": "Wheat"})
        ok("a job for what you have", r["ok"] and you.delivery["qty"] == 3 and you.delivery["loaded"], r["message"])
        game.engine.close()


def test_claiming_open_land_anywhere() -> None:
    """Designer request, 2026-10-18: any open land is fair game; a building there
    is joined to the roads by a dirt road its claimant pays for."""
    from convoy import claims as CL, layout as L
    with tempfile.TemporaryDirectory() as tmp:
        game, _ = _game(Path(tmp))
        w, you = game.world, game.you
        you.denari = 2000
        home = L.places_cached(list(w.cities))[M.market_of("cinderhold")].center
        spot = next((home.x + dx, home.y + dy) for dx in range(-600, 601, 40) for dy in range(-600, 601, 40)
                    if not CL.check(w, home.x + dx, home.y + dy))
        q = game.wild_claim({"x": spot[0], "y": spot[1], "quote": True})
        ok("a quote: road length and cost", q["ok"] and q["road_m"] > 0 and not q["why_not"], str(q))
        cash = you.denari
        r = game.wild_claim({"x": spot[0], "y": spot[1], "purpose": "Farm"})
        name = r["place"]
        ok("claimed, paying for the road", r["ok"] and abs(cash - you.denari - q["road_cost"]) < 0.01, r["message"])
        ok("the claim is a place of its own", name in M.EVERY_PLACE and M.is_claim(name) and M.plots_at(name) == 4)
        ok("not twice in one spot", game.wild_claim({"x": spot[0], "y": spot[1]})["ok"] is False)
        ok("you can travel there", M.travel_seconds(M.market_of("cinderhold"), name) > 0)
        you.location = name
        r = game.act("start_business", {"type": "Farm"})
        ok("and found a farm on it", r["ok"], r["message"])
        game.save()
        again = Game.load(game.run_dir, models=StandIn())
        ok("a reloaded game knows its claims", M.is_claim(name) and name in again.world.claims)
        again.engine.close()
        ok("the river is no place for a claim", "river" in CL.check(w, spot[0], L.river_axis()))
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
