#!/usr/bin/env python3
"""Play Convoy: a start screen, then a world you live in.

    python3 play.py              # then open http://localhost:8800

The start screen sets up a game -- how many cities, how many agents in each,
which city you live in, how fast time runs, what it may spend -- or picks up a
saved one. Then you are one citizen among the agents, and they do not know.

LOCAL ONLY. The server binds to 127.0.0.1 and every request that changes
anything must carry the per-launch token baked into the page, so another site
open in the same browser cannot drive your character. Putting a game on the
internet is a different job (accounts, one world per player, a host) -- see
PLAYING.md.
"""

from __future__ import annotations

import argparse
import json
import secrets
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

sys.path.insert(0, str(Path(__file__).resolve().parent))

from convoy import data as D
from convoy import inspect as INSPECT
from convoy import world_map as M
from convoy.config import load_env
from convoy.game import GAMES_DIR, Game, Settings
from convoy import town as TOWN

TOKEN = secrets.token_urlsafe(24)
HERE = Path(__file__).resolve().parent
GAME3D = HERE / "game3d"                     # the 3D client: page, script, style
ASSETS3D = HERE / "art" / "generated" / "3d"  # Meshy models, shrunk for the web


class Host:
    """At most one game at a time, and the map built from it."""

    def __init__(self, games_dir: Path):
        self.games_dir = games_dir
        self.game: Game | None = None
        self._lock = threading.RLock()
        self._map: tuple[float, bytes] | None = None
        self._page: tuple[str, bytes] | None = None
        # A head start in progress: the towns running before you arrive.
        self.warming: TOWN.HeadStart | None = None

    # -- games -------------------------------------------------------------

    def new(self, body: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            if self.game is not None:
                return {"ok": False, "error": "a game is already running -- end it first"}
            if self.warming is not None and not self.warming.error:
                return {"ok": False, "error": "the towns are already getting a head start"}
            raw = body.get("settings") or {}
            try:
                settings = Settings(
                    cities={k: int(v) for k, v in (raw.get("cities") or {}).items()},
                    your_city=str(raw.get("your_city", "")),
                    model=str(raw.get("model") or Settings.model),
                    pace=float(raw.get("pace", 12)),
                    budget=float(raw.get("budget", 10)),
                    workers=int(raw.get("workers", 16)),
                    # 60 was the old default and held the clock back: lift it.
                    rpm=(240.0 if float(raw.get("rpm", 240)) == 60 else float(raw.get("rpm", 240))),
                    raids=bool(raw.get("raids", True)),
                    starter_sites=bool(raw.get("starter_sites", True)),
                    calling=str(raw.get("calling") or "Farmer"),
                    head_start=float(raw.get("head_start", 8)),
                    solo=bool(raw.get("solo", False)),
                    sex=str(raw.get("sex") or "m"),
                    partner_sex=str(raw.get("partner_sex") or "f"),
                )
                settings.validate()
                if settings.head_start > 0:
                    template = TOWN.find_template(settings) if raw.get("reuse_town", True) else None
                    if template is None:
                        # Run the towns first, in the background; the start
                        # page shows the clock and opens the game when you arrive.
                        self.warming = TOWN.HeadStart(settings)
                        self.warming.start(lambda path: self._arrive(settings, path))
                        return {"ok": True, "warming": True}
                    game = Game.from_town(settings, template, self.games_dir)
                else:
                    game = Game.new(settings, self.games_dir)
            except (ValueError, TypeError) as exc:
                return {"ok": False, "error": str(exc)}
            game.save()            # names on the map from the first frame
            game.start()
            self.game = game
            self._map = self._page = None
            return {"ok": True, "game": game.run_dir.name}

    def _arrive(self, settings: Settings, template: Path) -> None:
        """The head start is done: you arrive in the towns it made."""
        with self._lock:
            game = Game.from_town(settings, template, self.games_dir)
            game.save()
            game.start()
            self.game = game
            self.warming = None
            self._map = self._page = None

    def load(self, body: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            if self.game is not None:
                return {"ok": False, "error": "a game is already running -- end it first"}
            name = str(body.get("id", ""))
            run_dir = self.games_dir / name
            if not name or "/" in name or not (run_dir / "checkpoint.json").exists():
                return {"ok": False, "error": "no saved game by that name"}
            game = Game.load(run_dir)
            game.paused = True      # a loaded game waits for you to press play
            game.note = "Loaded. Press play when you are ready."
            game.start()
            self.game = game
            self._map = self._page = None
            return {"ok": True, "game": name}

    def end(self) -> dict[str, Any]:
        with self._lock:
            if self.warming is not None:              # stop a head start
                self.warming.cancelled = True
                self.warming = None
            if self.game is None:
                return {"ok": True}
            game, self.game = self.game, None
        game.stop()
        return {"ok": True, "saved": game.run_dir.name}

    def control(self, body: dict[str, Any]) -> dict[str, Any]:
        g = self.game
        if g is None:
            return {"ok": False, "error": "no game"}
        if "paused" in body:
            g.paused = bool(body["paused"])
            if not g.paused:
                g.note = ""
        if "pace" in body:
            g.settings.pace = max(1.0, min(240.0, float(body["pace"])))
        if "budget" in body:
            g.settings.budget = max(0.5, float(body["budget"]))
        return {"ok": True, **g.status()}

    def menu(self) -> dict[str, Any]:
        return {
            "running": self.game is not None,
            "saved": Game.saved(self.games_dir),
            "cities": [{"key": k, "name": M.CITIES[k].name} for k in M.CITY_KEYS],
            "defaults": Settings().__dict__,
            "warming": self.warming.progress() if self.warming is not None else None,
            "towns": [json.loads((p / "town.json").read_text()) for p in
                      sorted(TOWN.TOWNS_DIR.glob("*__*")) if (p / "town.json").exists()],
        }

    # -- the map -----------------------------------------------------------

    def map_bytes(self) -> bytes:
        """The replay payload, rebuilt at most every few seconds."""
        import preview_world as PW
        g = self.game
        if g is None:
            return b"{}"
        with self._lock:
            if self._map and time.time() - self._map[0] < 3.0:
                return self._map[1]
            with g.engine.world_lock:
                g.log.flush()
                claims = list(g.world.claims.values())
            data = json.dumps(PW.build_payload(g.run_dir, claims=claims)).encode()
            self._map = (time.time(), data)
            return data

    def page(self) -> bytes:
        import preview_world as PW
        g = self.game
        with self._lock:
            if self._page and self._page[0] == g.run_dir.name:
                return self._page[1]
            with g.engine.world_lock:
                g.log.flush()
            html = PW.render_html(PW.build_payload(g.run_dir), served=True,
                                  game={"token": TOKEN, "you": g.human_id}).encode()
            self._page = (g.run_dir.name, html)
            return html


def make_handler(host: Host):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args) -> None:       # quiet
            return

        def _send(self, obj: Any, code: int = 200) -> None:
            body = json.dumps(obj, default=str).encode()
            self._raw(body, "application/json", code)

        def _raw(self, body: bytes, ctype: str, code: int = 200, cache: bool = False) -> None:
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            # Models never change under a name; everything else is live.
            self.send_header("Cache-Control", "max-age=3600" if cache else "no-store")
            self.end_headers()
            self.wfile.write(body)

        def _body(self) -> dict[str, Any]:
            try:
                n = int(self.headers.get("Content-Length") or 0)
                data = json.loads(self.rfile.read(min(n, 65_536)) or b"{}")
                return data if isinstance(data, dict) else {}
            except (ValueError, json.JSONDecodeError):
                return {}

        def do_GET(self) -> None:                   # noqa: N802
            url = urlparse(self.path)
            path, q = url.path, parse_qs(url.query)
            g = host.game
            if path == "/":
                if g is None:
                    return self._raw(START_PAGE.replace("__TOKEN__", TOKEN)
                                     .replace("__CALLINGS__", json.dumps(D.CALLINGS)).encode(),
                                     "text/html; charset=utf-8")
                # The 3D game is the game. The 2D map is still there, at /map.
                page = (GAME3D / "index.html").read_text()
                page = (page.replace("__TOKEN__", TOKEN).replace("__YOU__", g.human_id))
                return self._raw(page.encode(), "text/html; charset=utf-8")
            if path.startswith("/game3d/") or path.startswith("/assets3d/"):
                root = GAME3D if path.startswith("/game3d/") else ASSETS3D
                name = path.split("/", 2)[2]
                target = (root / name).resolve()
                if root.resolve() not in target.parents or not target.is_file():
                    return self._send({"error": "not found"}, 404)
                ctype = {".js": "text/javascript", ".css": "text/css", ".glb": "model/gltf-binary",
                         ".html": "text/html", ".png": "image/png", ".jpg": "image/jpeg"}.get(target.suffix,
                                                                       "application/octet-stream")
                return self._raw(target.read_bytes(), ctype + ("; charset=utf-8" if ctype.startswith("text") else ""),
                                 cache=target.suffix in (".glb", ".jpg", ".hdr"))
            if path == "/map" and g is not None:
                return self._raw(host.page(), "text/html; charset=utf-8")
            if path == "/api/menu":
                return self._send(host.menu())
            if g is None:
                return self._send({"error": "no game running"}, 409)
            if path == "/replay":
                return self._raw(host.map_bytes(), "application/json")
            if path == "/cards":
                with g.engine.world_lock:
                    return self._send({"hour": round(g.world.sim_hour, 2),
                                       "cards": INSPECT.cards(g.world)})
            if path == "/api/status":
                return self._send(g.status())
            if path == "/api/state":
                return self._send(g.state())
            if path == "/api/feed":
                since = int((q.get("since") or ["0"])[0] or 0)
                return self._send({"feed": g.feed_since(since)})
            if path == "/api/tools":
                return self._send({"tools": g.tools()})
            if path == "/api/briefing":
                return self._send({"text": g.briefing()})
            if path == "/api/advisor":
                return self._send(g.advisor())
            if path == "/api/market":
                return self._send(g.market())
            if path == "/api/missions":
                return self._send(g.missions())
            if path == "/api/deliveries":
                return self._send(g.deliveries())
            if path == "/api/knowhow":
                return self._send(g.knowhow())
            if path == "/api/household":
                return self._send(g.household())
            if path == "/api/citizens":
                return self._send(g.citizens(str((q.get("city") or [""])[0])))
            if path == "/api/thread":
                return self._send(g.thread(str((q.get("with") or [""])[0])))
            if path == "/api/business":
                return self._send(g.business(str((q.get("id") or [""])[0])))
            if path == "/api/assets":
                return self._send(g.assets(str((q.get("id") or [""])[0])))
            if path == "/api/me":
                return self._send(g.me())
            if path == "/api/plots":
                return self._send(g.plots())
            if path == "/api/production":
                return self._send(g.production())
            if path == "/api/ledger":
                return self._send(g.ledger())
            if path == "/api/chains":
                return self._send(g.chains())
            if path in ("/api/board", "/api/lookup"):
                return self._send(g.board())
            return self._send({"error": f"no route {path}"}, 404)

        def do_POST(self) -> None:                  # noqa: N802
            if self.headers.get("X-Game-Token") != TOKEN:
                return self._send({"error": "bad token -- reload the page"}, 403)
            path = urlparse(self.path).path
            body = self._body()
            if path == "/api/new":
                return self._send(host.new(body))
            if path == "/api/load":
                return self._send(host.load(body))
            if path == "/api/end":
                return self._send(host.end())
            if path == "/api/control":
                return self._send(host.control(body))
            if path == "/api/claim":
                g = host.game
                if g is None:
                    return self._send({"error": "no game running"}, 409)
                return self._send(g.claim(str(body.get("place", "")), [str(c) for c in body.get("cells") or []][:8],
                                          str(body.get("business_id", ""))))
            if path == "/api/arrive":
                g = host.game
                if g is None:
                    return self._send({"error": "no game running"}, 409)
                return self._send(g.arrive(str(body.get("place", ""))))
            if path == "/api/wildclaim":
                g = host.game
                if g is None:
                    return self._send({"error": "no game running"}, 409)
                out = g.wild_claim(body if isinstance(body, dict) else {})
                host._map = None                      # the map must show it at once
                return self._send(out)
            if path == "/api/fight":
                g = host.game
                if g is None:
                    return self._send({"error": "no game running"}, 409)
                return self._send(g.fight_op(body if isinstance(body, dict) else {}))
            if path == "/api/eat":
                g = host.game
                if g is None:
                    return self._send({"error": "no game running"}, 409)
                return self._send(g.eat(body if isinstance(body, dict) else {}))
            if path == "/api/depart":
                g = host.game
                if g is None:
                    return self._send({"error": "no game running"}, 409)
                return self._send(g.depart())
            if path == "/api/mission":
                g = host.game
                if g is None:
                    return self._send({"error": "no game running"}, 409)
                return self._send(g.mission(body if isinstance(body, dict) else {}))
            if path == "/api/delivery":
                g = host.game
                if g is None:
                    return self._send({"error": "no game running"}, 409)
                return self._send(g.delivery(body if isinstance(body, dict) else {}))
            if path == "/api/report":
                g = host.game
                if g is None:
                    return self._send({"error": "no game running"}, 409)
                return self._send(g.buy_report(str(body.get("city", ""))))
            if path == "/api/fetch":
                g = host.game
                if g is None:
                    return self._send({"error": "no game running"}, 409)
                return self._send(g.fetch(body if isinstance(body, dict) else {}))
            if path == "/api/act":
                g = host.game
                if g is None:
                    return self._send({"error": "no game running"}, 409)
                return self._send(g.act(str(body.get("action", "")), body.get("args") or {}))
            return self._send({"error": f"no route {path}"}, 404)

    return Handler


START_PAGE = r"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Convoy</title>
<style>
:root{--bg:#141a12;--panel:#1d2619;--line:#33422c;--ink:#e8eadf;--dim:#9aa58f;--accent:#d9a06a;--good:#9dd17a;--bad:#e07a6a}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.5 ui-sans-serif,system-ui,-apple-system,sans-serif}
main{max-width:760px;margin:0 auto;padding:32px 16px 64px}
h1{font-size:30px;margin:0 0 4px;letter-spacing:.02em}
h2{font-size:17px;margin:28px 0 10px;color:var(--accent);text-transform:uppercase;letter-spacing:.08em}
.sub{color:var(--dim);margin:0 0 18px}
.card{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:16px;margin-bottom:12px}
.row{display:flex;gap:12px;align-items:center;flex-wrap:wrap;margin:8px 0}
label{color:var(--dim);font-size:13px}
input,select{background:#10150e;color:var(--ink);border:1px solid var(--line);border-radius:6px;padding:7px 9px;font:inherit}
input[type=number]{width:88px}
button{background:var(--accent);color:#1a120a;border:0;border-radius:7px;padding:9px 16px;font:inherit;font-weight:600;cursor:pointer}
button.ghost{background:transparent;color:var(--ink);border:1px solid var(--line)}
button:disabled{opacity:.5;cursor:default}
.city{display:grid;grid-template-columns:22px 1fr 100px 90px;gap:10px;align-items:center;padding:6px 0;border-bottom:1px solid var(--line)}
.city:last-child{border-bottom:0}
.callings{display:grid;grid-template-columns:repeat(auto-fill,minmax(130px,1fr));gap:8px;margin:6px 0 14px}
.calling{border:1px solid var(--line);border-radius:8px;padding:9px;cursor:pointer;background:#10150e}
.calling b{display:block;color:var(--ink)} .calling span{font-size:12.5px;color:var(--dim)}
.calling.on{border-color:var(--accent);box-shadow:0 0 0 1px var(--accent) inset}
.meter{height:10px;background:#10150e;border:1px solid var(--line);border-radius:6px;overflow:hidden;margin:8px 0}
.meter i{display:block;height:100%;width:0;background:var(--accent);transition:width .6s}
.msg{min-height:22px;color:var(--dim)} .msg.err{color:var(--bad)}
table{width:100%;border-collapse:collapse;font-size:14px} td,th{padding:6px 4px;border-bottom:1px solid var(--line);text-align:left}
th{color:var(--dim);font-weight:500}
.est{color:var(--dim);font-size:13px}
@media (max-width:560px){.city{grid-template-columns:22px 1fr 80px}.city .you{grid-column:2/4}}
</style></head><body><main>
<h1>Convoy</h1>
<p class="sub">You are one citizen of a Bronze Age valley. Everyone else is an AI agent, and none of them know you are not. Build the most wealth you can.</p>

<div id="warming" class="card" style="display:none">
  <div class="row" style="margin-top:0"><strong>The towns are running without you</strong></div>
  <div class="meter"><i id="w-bar"></i></div>
  <div class="row"><span id="w-text" class="est"></span><button class="ghost" id="w-stop">Stop</button></div>
  <div class="est">The agents found, hire, trade and argue for <span id="w-target"></span> game hours; then you arrive as a newcomer. The finished towns are kept, so the next game with the same towns starts instantly.</div>
</div>
<div id="running" class="card" style="display:none">
  <div class="row"><strong>A game is running.</strong> <button onclick="location.reload()">Go to it</button></div>
</div>

<h2>New game</h2>
<div class="card">
  <div class="row" style="margin-top:0"><strong>Your character</strong> <span class="est">a bonus for life; everyone else is dealt one at random</span></div>
  <div id="callings" class="callings"></div>
  <div class="row">
    <label>You are <select id="sex"><option value="m">a man</option><option value="f">a woman</option></select></label>
    <label>Your partner is <select id="partner"><option value="f">a woman</option><option value="m">a man</option></select></label>
    <span class="est">You start with your partner, a son and a daughter.</span>
  </div>
  <div class="row"><label><input type="checkbox" id="solo" checked> <b>A town of my own</b>: start alone in a new town beside the agents' towns (tick the agents' towns below)</label></div>
  <div id="cities"></div>
  <div class="row"><span class="est" id="est"></span></div>
  <div class="row">
    <label>Game speed <select id="pace">
      <option value="6">slow: 1 game hour = 10 min</option>
      <option value="12" selected>normal: 1 game hour = 5 min</option>
      <option value="30">fast: 1 game hour = 2 min</option>
      <option value="60">very fast: 1 game hour = 1 min</option>
    </select></label>
    <label>Spending cap $ <input id="budget" type="number" min="1" step="1" value="10"></label>
  </div>
  <div class="row">
    <label>Model <input id="model" size="24"></label>
    <label>Agents thinking at once <input id="workers" type="number" min="1" max="32" value="16"></label>
    <label>Requests / min <input id="rpm" type="number" min="5" max="600" value="240"></label>
  </div>
  <div class="row">
    <label>Head start <select id="head">
      <option value="0">none: everyone starts together at hour 0</option>
      <option value="6">6 game hours</option>
      <option value="8" selected>8 game hours</option>
      <option value="12">12 game hours</option>
      <option value="24">24 game hours</option>
    </select></label>
    <label><input type="checkbox" id="reuse" checked> reuse towns that already ran</label>
  </div>
  <div class="row"><span class="est" id="head-note"></span></div>
  <div class="row"><label><input type="checkbox" id="starter" checked> Start each town with the state's Tavern, Farm, Mine and Refinery (they sell high, buy low and hire at a fixed wage)</label></div>
  <div class="row"><button id="go">Start game</button><span class="msg" id="msg"></span></div>
</div>

<h2>Saved games</h2>
<div class="card"><table id="saved"><tr><td class="est">none yet</td></tr></table></div>
</main>
<script>
const TOKEN = "__TOKEN__";
const post = (url, body) => fetch(url, {method: "POST", headers: {"Content-Type": "application/json", "X-Game-Token": TOKEN}, body: JSON.stringify(body || {})}).then(r => r.json());
const $ = id => document.getElementById(id);
let MENU = null;
const CALLINGS = __CALLINGS__;
let CALLING = "Farmer";
function callingCards(){
  const prev = remembered();
  if (prev && prev.calling in CALLINGS) CALLING = prev.calling;
  if (prev && "starter_sites" in prev) $("starter").checked = !!prev.starter_sites;
  $("callings").innerHTML = Object.entries(CALLINGS).map(([k, d]) =>
    `<div class="calling${k === CALLING ? " on" : ""}" data-k="${k}"><b>${k}</b><span>${d}</span></div>`).join("");
  $("callings").querySelectorAll(".calling").forEach(el => el.onclick = () => { CALLING = el.dataset.k; callingCards(); });
}
const SAVED_KEY = "convoy.newgame";
function remembered(){ try { return JSON.parse(localStorage.getItem(SAVED_KEY)) || null; } catch (e) { return null; } }
function remember(s){ try { localStorage.setItem(SAVED_KEY, JSON.stringify(s)); } catch (e) {} }

function cityRows(){
  const prev = remembered();
  const counts = prev ? prev.cities : MENU.defaults.cities;
  const mine = prev ? prev.your_city : MENU.defaults.your_city;
  $("cities").innerHTML = `<div class="city" style="color:var(--dim);font-size:13px"><span></span><span>City</span><span>Agents</span><span class="you">You live here</span></div>`
    + MENU.cities.map(c => `<div class="city">
      <input type="checkbox" data-c="${c.key}" ${counts[c.key] ? "checked" : ""}>
      <span>${c.name}</span>
      <input type="number" min="1" max="60" data-n="${c.key}" value="${counts[c.key] || 20}">
      <label class="you"><input type="radio" name="you" value="${c.key}" ${c.key === mine ? "checked" : ""}> here</label>
    </div>`).join("");
  $("cities").querySelectorAll("input").forEach(el => el.addEventListener("input", estimate));
  if (prev){ $("pace").value = prev.pace; $("budget").value = prev.budget; $("workers").value = prev.workers; $("rpm").value = prev.rpm;
    if ("head_start" in prev) $("head").value = prev.head_start; if ("reuse_town" in prev) $("reuse").checked = !!prev.reuse_town;
    if ("solo" in prev) $("solo").checked = !!prev.solo; if (prev.sex) $("sex").value = prev.sex; if (prev.partner_sex) $("partner").value = prev.partner_sex; }
  $("model").value = (prev && prev.model) || MENU.defaults.model;
  callingCards();
  estimate();
}
function settings(){
  const cities = {};
  document.querySelectorAll("[data-c]").forEach(cb => {
    if (cb.checked) cities[cb.dataset.c] = +document.querySelector(`[data-n="${cb.dataset.c}"]`).value;
  });
  let you = (document.querySelector("input[name=you]:checked") || {}).value;
  // A town of your own: the first town the agents are NOT in.
  if ($("solo") && $("solo").checked){
    const ticked = new Set([...document.querySelectorAll("[data-c]")].filter(c => c.checked).map(c => c.dataset.c));
    you = (MENU.cities.find(c => !ticked.has(c.key)) || {}).key;
  }
  return {cities, your_city: you, pace: +$("pace").value, budget: +$("budget").value,
          model: $("model").value.trim(), workers: +$("workers").value, rpm: +$("rpm").value,
          calling: CALLING, starter_sites: $("starter").checked,
          head_start: +$("head").value, reuse_town: $("reuse").checked,
          solo: $("solo").checked, sex: $("sex").value, partner_sex: $("partner").value};
}
// Matches convoy/town.py town_key.
function townKey(s){
  const cities = Object.keys(s.cities).sort().map(c => c + s.cities[c]).join("-");
  return `${cities}_${s.starter_sites ? "starter" : "bare"}_${(s.model || "").split("/").pop()}_${s.head_start}h`;
}
function estimate(){
  const s = settings();
  const n = Object.values(s.cities).reduce((a, b) => a + b, 0);
  const town = (MENU.towns || []).filter(t => t.key === townKey(s)).pop();
  const ahead = s.head_start * n * 1.18 / (30 * 24);
  $("head-note").textContent = !s.head_start ? "Everyone, you included, starts at once in an empty town."
    : town && s.reuse_town ? `A town like this already ran (${town.made}, ${town.businesses} businesses by hour ${town.hour}): you start there at once, free.`
    : `The ${n} agents run ${s.head_start} game hours first, as fast as the AI answers -- usually several minutes -- for about $${ahead.toFixed(2)}. You then arrive as one more citizen.`;
  // Measured 2026-10-17: 30 agents for 24 game hours cost $1.18.
  const perAgentHour = 1.18 / (30 * 24);
  $("est").textContent = n ? `${n} citizens, ${Math.max(0, n - 1)} of them AI. Roughly $${(perAgentHour * (n - 1)).toFixed(3)} per game hour, about $${(perAgentHour * (n - 1) * 24).toFixed(2)} per game day.` : "Pick at least one city.";
}
$("go").onclick = async () => {
  const s = settings();
  $("msg").className = "msg";
  if (!Object.keys(s.cities).length){ $("msg").textContent = "Pick at least one city."; return; }
  if (s.solo && !s.your_city){ $("msg").textContent = "Leave one town unticked: it becomes yours."; $("msg").className = "msg err"; return; }
  if (!s.solo && (!s.your_city || !(s.your_city in s.cities))){ $("msg").textContent = "Choose a city you live in (one that is ticked)."; $("msg").className = "msg err"; return; }
  remember(s);
  $("go").disabled = true; $("msg").textContent = "Building the world…";
  const r = await post("/api/new", {settings: s});
  if (r.ok && r.warming){ $("go").disabled = false; $("msg").textContent = ""; watchWarming(); return; }
  if (r.ok) location.reload();
  else { $("go").disabled = false; $("msg").textContent = r.error; $("msg").className = "msg err"; }
};
async function watchWarming(){
  const m = await (await fetch("/api/menu")).json();
  if (m.running){ location.reload(); return; }
  const w = m.warming;
  if (!w){ $("warming").style.display = "none"; return; }
  $("warming").style.display = "";
  $("w-target").textContent = w.target;
  $("w-bar").style.width = `${Math.min(100, w.hour / w.target * 100)}%`;
  $("w-text").textContent = w.error ? w.error
    : `Hour ${w.hour.toFixed(1)} of ${w.target} \u00b7 $${w.spent.toFixed(2)} \u00b7 ${Math.floor(w.seconds / 60)}m ${w.seconds % 60}s`;
  if (!w.error) setTimeout(watchWarming, 2000);
}
async function load(id){
  const r = await post("/api/load", {id});
  if (r.ok) location.reload(); else alert(r.error);
}
(async () => {
  MENU = await (await fetch("/api/menu")).json();
  if (MENU.running) $("running").style.display = "";
  if (MENU.warming) watchWarming();
  $("w-stop").onclick = async () => { await post("/api/end", {}); location.reload(); };
  ["head", "reuse", "starter", "solo"].forEach(id => $(id).addEventListener("input", estimate));
  cityRows();
  if (MENU.saved.length){
    $("saved").innerHTML = `<tr><th>Started</th><th>Cities</th><th>Hour</th><th>Spent</th><th></th></tr>`
      + MENU.saved.map(g => `<tr><td>${g.id}</td><td>${Object.entries(g.settings.cities || {}).map(([k, n]) => k[0].toUpperCase() + k.slice(1) + " " + n).join(", ")}</td><td>${(+g.hour).toFixed(1)}</td><td>$${(+g.spent).toFixed(2)}</td><td>${g.can_resume ? `<button class="ghost" onclick="load('${g.id}')">Resume</button>` : ""}</td></tr>`).join("");
  }
})();
</script></body></html>
"""


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--port", type=int, default=8800)
    ap.add_argument("--games-dir", type=Path, default=GAMES_DIR)
    args = ap.parse_args()
    load_env()
    host = Host(args.games_dir)
    server = ThreadingHTTPServer(("127.0.0.1", args.port), make_handler(host))
    print(f"Convoy is ready: http://localhost:{args.port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        print("saving...")
        host.end()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
