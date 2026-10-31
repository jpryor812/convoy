"""A game: one world, held open, with a human in one seat.

Designer request, 2026-10-17: "make it so that I can play and try to build up
the most wealth in a world of 50 agents in two cities, with me being an
'agent' in one of them" -- and the agents must not know. So the human is a
citizen like any other: named like its neighbours, briefed with the same rules,
acting through the same `schemas.dispatch` with the same refusals. The only
difference is who decides. Every other seat is a model; this one is whoever is
holding the mouse.

THE WORLD NEVER WAITS FOR THE HUMAN. A model agent is woken ("you arrived",
"your shift is over") and answers; the human is woken the same way, and the
wake becomes a line in their feed. The clock carries on regardless, paced to
`pace` game minutes per real minute so a person can keep up -- and slowed
further, automatically, whenever the models are behind, because the engine
already holds the clock for a decision still being thought about. Pausing is
allowed: it is a private world.

Reflexes (`convoy/reflexes.py`) run for the human too: load a claimed cart and
set off, eat when hungry in a stocked tavern, start the same shift again. That
is the autopilot a strategy game gives its player.

Nothing here knows about HTTP. `play.py` is the server; this is the game.
"""

from __future__ import annotations

import json
import math
import random
import threading
import time
from collections import Counter, deque
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from . import checkpoint
from . import data as D
from . import economy as E
from . import llm
from . import observe as O
from . import schemas as S
from . import world_map as M
from .engine import TICK_SECONDS, Engine, EngineConfig
from .world_setup import state_offers
from . import family as FAM
from . import delivery as DL
from . import missions as MI
from . import combat as CB
from . import ground as GR

# Raiders leave a newcomer alone for their first game day.
NEWCOMER_PROTECTION_HOURS = 24.0
from .events import EventLog, Significance
from . import actions as A
from . import advisor as ADV
from . import land as LAND
from . import claims as CL
from . import discovery as DS
from . import robbery as RB
from . import social as SO
from .state import Activity, Agent, World
from .world_setup import new_world

GAMES_DIR = Path("runs/games")
DEFAULT_MODEL = "openai/gpt-6-luna"
# Events about the player worth a line in their feed even when someone else
# was the actor. Bookkeeping (production ticks, standings) is left out.
# Events the player's own actions emit, already reported by `act`.
_OWN_ACTION_ECHOES = frozenset({
    "travel", "business_founded", "job_started", "hired", "price_set", "payment",
    "job_posted", "job_offered", "job_applied", "courier_claimed", "consignment_posted",
    "delivery_posted", "raid_planned", "raid_joined", "equipped", "ate", "land_bought",
    "vehicle_purchased", "quit_job", "development_started", "deposit", "withdraw",
    "buy_order_posted", "buy_order_cancelled",
})
_FEED_SKIP = frozenset({
    "production", "city_standings", "diary", "llm_reasoning", "action_call",
    "digest", "sim_start", "site_full", "llm_error", "decision_error",
})


@dataclass
class Settings:
    """What a new game is made of. Every field has a form control on the start
    page, and every one is saved with the game so a reload says what it was."""

    # Agents per city, in map order; 1 to 3 cities. Counts may differ.
    cities: dict[str, int] = field(default_factory=lambda: {"aldermarch": 20, "cinderhold": 20})
    # The city the player lives in. Their seat is one of that city's count.
    your_city: str = "aldermarch"
    model: str = DEFAULT_MODEL
    # Game minutes per real minute. 12 is an hour every five minutes.
    pace: float = 12.0
    # Hard stop on API spend, in dollars. The game pauses itself at it.
    budget: float = 10.0
    workers: int = 16
    # Requests a minute to the model. 60 held the clock back with 40 agents
    # (the "freezes" of 2026-10-18); 240 is what the head start uses.
    rpm: float = 240.0
    raids: bool = True            # agents may plan raids on the roads
    government: bool = False
    # The state's Tavern, Farm, Mine and Refinery in each city, and no other
    # government (see World.starter_sites).
    starter_sites: bool = True
    # Your character: one of data.CALLINGS. Agents are dealt one at random.
    calling: str = "Farmer"
    # Game hours the towns run without you before you arrive (0: you start
    # with everyone at hour zero). With a head start the city counts are the
    # agents, and you arrive as one more. See convoy/town.py.
    head_start: float = 8.0
    # SOLO (designer request, 2026-10-18): you start in a new town of your own,
    # next to the towns the agents run -- your own patch, nobody else in it yet.
    # `cities` are then the agents' towns and `your_city` is not among them.
    solo: bool = False
    # OUTPOSTS (2026-10-27): no towns at the start. Everyone settles on open
    # land; each city's market is the state's trading post. You choose your
    # land on the map when the game opens. See GAME_MODES.md.
    outposts: bool = False
    # You and your partner: "m" or "f".
    sex: str = "m"
    partner_sex: str = "f"

    def validate(self) -> None:
        if not 1 <= len(self.cities) <= 3:
            raise ValueError("a game has one, two or three cities")
        for key, n in self.cities.items():
            if key not in M.CITIES:
                raise ValueError(f"unknown city {key!r}")
            if not 1 <= int(n) <= 60:
                raise ValueError(f"{M.CITIES[key].name} needs 1 to 60 agents")
        if self.solo:
            if self.your_city in self.cities or self.your_city not in M.CITIES:
                raise ValueError("in a solo start your town is a new one, not one of the agents'")
        elif self.your_city not in self.cities:
            raise ValueError("you must live in one of the game's cities")
        if self.sex not in ("m", "f") or self.partner_sex not in ("m", "f"):
            raise ValueError("choose a man or a woman, for you and for your partner")
        if self.calling and self.calling not in D.CALLINGS:
            raise ValueError(f"unknown character {self.calling!r}")
        if not 0 <= self.head_start <= 48:
            raise ValueError("a head start is 0 to 48 game hours")
        if self.pace <= 0 or self.budget <= 0:
            raise ValueError("pace and budget must be positive")


class _Seats:
    """The policy for a world with one human seat: the model for everyone
    else, a feed line for the human. The engine hands its lock to whichever
    policy it holds; this passes it on to the model's."""

    def __init__(self, model: llm.LLMPolicy, human_id: str, on_wake):
        self.model = model
        self.human_id = human_id
        self.on_wake = on_wake

    @property
    def world_lock(self):
        return self.model.world_lock

    @world_lock.setter
    def world_lock(self, lock) -> None:
        self.model.world_lock = lock

    def decide(self, world: World, agent: Agent, reason: str) -> None:
        if agent.id == self.human_id:
            self.on_wake(world, agent, reason)
            return
        self.model.decide(world, agent, reason)


def _rosters(settings: Settings) -> tuple[dict[str, list[tuple[str, str]]], int]:
    """Names for every seat, and which of the player's city's seats is theirs.

    The player is named exactly like the others -- `Aldermarch-gpt-6-luna-07` --
    and sits at a random place in the roster, not always first or last, so
    nothing about the name or the id gives them away."""
    tail = settings.model.split("/")[-1]
    rosters = {
        city: [(f"{M.CITIES[city].name}-{tail}-{i + 1:02d}", settings.model)
               for i in range(int(n))]
        for city, n in settings.cities.items()
    }
    seat = (random.randrange(int(settings.cities[settings.your_city]))
            if settings.your_city in settings.cities else 0)
    return rosters, seat


class Game:
    """One world, running, with a player in it."""

    def __init__(self, run_dir: Path, world: World, log: EventLog, settings: Settings,
                 human_id: str, spent_before: float = 0.0, models: Any = None):
        self.run_dir = run_dir
        self.world = world
        # Claims on open land are places of this world (convoy/claims.py).
        M.register_claims(world.claims.values())
        self.log = log
        self.settings = settings
        self.human_id = human_id
        world.human = human_id
        self.spent_before = spent_before
        self.feed: deque[dict[str, Any]] = deque(maxlen=400)
        self._feed_seq = 0
        self._seen_events = len(log.events)
        self.paused = False
        self.stopped = False
        self.note = ""                       # why the game paused itself, if it did
        self._hunger_told = "Normal"
        # Hourly snapshots of everyone's worth, for the ledger. See `advisor`.
        hist = run_dir / "history.json"
        self.history = ADV.History.from_json(json.loads(hist.read_text()) if hist.exists() else None)
        self.reports: list[dict[str, Any]] = []
        self._day = int(world.sim_hour // 24)
        self._titles: set[str] = set()
        # Which grid square each plot of the player's sits on, when they chose
        # it. Everyone else's plots are placed by the page, deterministically.
        meta_path = run_dir / "game.json"
        meta = json.loads(meta_path.read_text()) if meta_path.exists() else {}
        self.claims: dict[str, str] = dict(meta.get("claims") or {})
        # Town reports bought on other cities: city key -> the snapshot.
        self.intel: dict[str, dict[str, Any]] = dict(meta.get("intel") or {})
        # A fight in progress (convoy/combat.py): the page plays it, this keeps score.
        self.fight: CB.Fight | None = None
        self.last_ambush = -1e12
        # `models` is for tests: anything with `decide`, `usage` and `world_lock`.
        self.models = models if models is not None else llm.LLMPolicy(
            log=log, requests_per_minute=settings.rpm,
        )
        self.policy = _Seats(self.models, human_id, self._wake)
        self.engine = Engine(world, log, self.policy, EngineConfig(
            duration_hours=float("inf"),
            speed=settings.pace,     # game minutes per real minute = game s per real s
            checkpoint_every_hours=1.0,
            decision_workers=settings.workers,
            reflexes=True,
            restock=True,
            manual_agents=frozenset({human_id}),
            # The clock may run this far ahead of a decision still being
            # thought about: wider than the default, so a slow answer does not
            # freeze the world under the player's feet.
            max_decision_lag_minutes=20.0,
        ), on_checkpoint=lambda w: self.save())
        self._thread: threading.Thread | None = None

    # -- making and finding games -----------------------------------------

    @classmethod
    def new(cls, settings: Settings, games_dir: Path = GAMES_DIR,
            models: Any = None) -> "Game":
        settings.validate()
        run_dir = games_dir / time.strftime("%Y%m%d-%H%M%S")
        n = 2
        while run_dir.exists():                 # two games in one second
            run_dir = games_dir / f"{time.strftime('%Y%m%d-%H%M%S')}-{n}"
            n += 1
        run_dir.mkdir(parents=True, exist_ok=True)
        log = EventLog(run_dir / "events.jsonl", echo_min=99)
        if settings.outposts:
            # Every count is agents; you arrive as one more, as with a head start.
            from . import town as TOWN
            world = new_world(log, [], TOWN._rosters(settings), government=settings.government,
                              starter_sites=settings.starter_sites)
            world.npc_bandits = False
            TOWN.populate_outposts(world, log, random.Random(world.land_seed))
            you = TOWN.settle(world, log, settings)
            game = cls(run_dir, world, log, settings, you, models=models)
            game._welcome()
            game._write_meta()
            return game
        rosters, seat = _rosters(settings)
        world = new_world(log, [], rosters, government=settings.government,
                          starter_sites=settings.starter_sites)
        world.npc_bandits = False
        if settings.solo:
            from . import town as TOWN
            deal = random.Random(world.land_seed)
            for a in world.agents.values():
                a.calling = deal.choice(list(D.CALLINGS))
                FAM.found_household(world, a, deal)
                FAM.give_donkey(world, a)
            you = TOWN.settle(world, log, settings)
            game = cls(run_dir, world, log, settings, you, models=models)
            game._welcome()
            game._write_meta()
            return game
        human = world.agents_in(settings.your_city)[seat]
        # Characters: yours as chosen, everyone else's dealt evenly at random.
        deal = random.Random(world.land_seed)
        kinds = list(D.CALLINGS)
        for a in world.agents.values():
            a.calling = deal.choice(kinds)
            if a.id != human.id:
                FAM.found_household(world, a, deal)
        FAM.found_household(world, human, deal, sex=settings.sex, partner_sex=settings.partner_sex)
        for a in world.agents.values():
            FAM.give_donkey(world, a)
        human.calling = settings.calling
        human.protected_until = world.sim_time + NEWCOMER_PROTECTION_HOURS * 3600.0
        game = cls(run_dir, world, log, settings, human.id, models=models)
        game._write_meta()
        return game

    @classmethod
    def from_town(cls, settings: Settings, template: Path, games_dir: Path = GAMES_DIR,
                  models: Any = None) -> "Game":
        """A new game in towns that have already been running: you arrive."""
        from . import town as TOWN
        settings.validate()
        run_dir = games_dir / time.strftime("%Y%m%d-%H%M%S")
        n = 2
        while run_dir.exists():
            run_dir = games_dir / f"{time.strftime('%Y%m%d-%H%M%S')}-{n}"
            n += 1
        world, log, you, spent = TOWN.arrive(template, run_dir, settings)
        game = cls(run_dir, world, log, settings, you, spent_before=spent, models=models)
        game._welcome()
        game._write_meta()
        return game

    def _welcome(self) -> None:
        """What you walk into: the town as it stands when you arrive."""
        w, you = self.world, self.you
        city = w.city_of(you)
        if w.outposts:
            n = sum(1 for a in w.agents.values() if a.id != you.id and a.home)
            xy = CL.place_xy(w, you.home) if you.home else None
            city, d = CL.nearest_anchor(w, *xy) if xy else (you.city, 0.0)
            far = f", {d / 1000:.1f} km from the nearest trading post" if xy else ""
            self._push("milestone", (
                f"You have settled on the frontier{far}. Your first home is free. There are no towns "
                f"yet: {n} other people have outposts of their own around the state's "
                f"{len(w.cities)} trading posts, which feed, hire and buy. The frontier is hazy: you "
                f"cannot see who is out there until you find them, and you can only trade with "
                f"people you have found. You have {you.denari:.0f}."))
            return
        mine = [b for b in w.businesses.values()
                if not b.closed and not b.is_government and M.city_of(b.location) == city]
        kinds = Counter(b.type.split(" /")[0] for b in mine)
        top = sorted((a for a in w.agents_in(city) if a.id != you.id),
                     key=lambda a: -a.net_worth(w))[:1]
        plural = lambda k, n: k if n == 1 else (k[:-1] + "ies" if k.endswith("y") else k + "s")
        made = ", ".join(f"{n} {plural(k, n)}" for k, n in kinds.most_common())
        if not [a for a in w.agents_in(city) if a.id != you.id]:
            others = [c for c in w.cities if c != city]
            n = sum(len(w.agents_in(c)) for c in others)
            biz = sum(1 for b in w.businesses.values()
                      if not b.closed and not b.is_government and M.city_of(b.location) in others)
            self._push("milestone", (
                f"You settle {M.CITIES[city].name}, a town of your own, at hour {w.sim_hour:.0f}. "
                f"Your home stands in the square and its border is marked around it. "
                f"Next door, {n} people in {' and '.join(M.CITIES[c].name for c in others)} "
                f"run {biz} businesses -- your first buyers. Open the guide (?) to begin."))
            return
        self._push("milestone", (
            f"You arrive in {M.CITIES[city].name} at hour {w.sim_hour:.0f}. "
            f"{len(w.agents_in(city)) - 1} people have been at it since dawn"
            + (f" and own {made}" if made else ", and nobody has founded anything yet")
            + (f"; the richest, {top[0].name}, is worth {top[0].net_worth(w):.0f}" if top else "")
            + f". You have {you.denari:.0f} and a calling ({you.calling}). The Market and People pages show what is going on."))

    @classmethod
    def load(cls, run_dir: Path, models: Any = None) -> "Game":
        meta = json.loads((run_dir / "game.json").read_text())
        settings = Settings(**meta["settings"])
        log = EventLog(run_dir / "events.jsonl", echo_min=99)
        log.replay()
        world = checkpoint.load(run_dir / "checkpoint.json")
        return cls(run_dir, world, log, settings, meta["human_id"],
                   spent_before=float(meta.get("spent", 0.0)), models=models)

    @staticmethod
    def saved(games_dir: Path = GAMES_DIR) -> list[dict[str, Any]]:
        out = []
        for meta_path in sorted(games_dir.glob("*/game.json"), reverse=True):
            try:
                meta = json.loads(meta_path.read_text())
            except (OSError, ValueError):
                continue
            out.append({
                "id": meta_path.parent.name,
                "settings": meta.get("settings", {}),
                "hour": meta.get("hour", 0.0),
                "spent": meta.get("spent", 0.0),
                "you": meta.get("you_name", ""),
                "saved_at": meta.get("saved_at", ""),
                "can_resume": (meta_path.parent / "checkpoint.json").exists(),
            })
        return out

    def _write_meta(self) -> None:
        you = self.world.agents[self.human_id]
        (self.run_dir / "game.json").write_text(json.dumps({
            "settings": asdict(self.settings),
            "human_id": self.human_id,
            "you_name": you.name,
            "hour": round(self.world.sim_hour, 2),
            "spent": round(self.spent(), 4),
            "saved_at": time.strftime("%Y-%m-%d %H:%M"),
            "claims": getattr(self, "claims", {}),
            "intel": getattr(self, "intel", {}),
        }, indent=2))

    def save(self) -> None:
        """Checkpoint and metadata. Called by the engine on the hour, and on stop."""
        with self.engine.world_lock:
            checkpoint.save(self.world, self.run_dir / "checkpoint.json")
            self.log.flush()
            self._write_meta()
            (self.run_dir / "history.json").write_text(json.dumps(self.history.to_json()))

    # -- running -----------------------------------------------------------

    def start(self) -> None:
        if self._thread is not None:
            return
        self._thread = threading.Thread(target=self._run, name="game", daemon=True)
        self._thread.start()

    def _run(self) -> None:
        w = self.world
        if w.sim_time == 0.0:
            self.log.emit(w.sim_time, "sim_start", agents=len(w.agents),
                          businesses=len(w.businesses), duration_hours=None,
                          cities=list(w.cities), no_state=w.no_state)
            self.engine._stagger_opening()
        while not self.stopped:
            if self.paused:
                time.sleep(0.2)
                continue
            if self.spent() >= self.settings.budget:
                self.paused = True
                self.note = (f"Paused: the game has spent ${self.spent():.2f} of its "
                             f"${self.settings.budget:.2f} budget. Raise it to go on.")
                continue
            self.engine.config.speed = self.settings.pace
            # A game minute at a time, so pause and pace take effect at once.
            #
            # A BAD TICK MUST NOT STOP THE WORLD (2026-10-18). An exception here
            # used to kill this thread silently: the page went on animating its
            # timers against a clock that had stopped, and the player's farm
            # "made" nothing. Now it is logged, the player is told once, and
            # the clock goes on.
            try:
                self.engine.step_until(w.sim_time + TICK_SECONDS)
                # A delivery waiting at your business loads the moment there is
                # something to load and you are standing there (2026-10-18).
                you = self.you
                if you.delivery and not you.delivery["loaded"]:
                    with self.engine.world_lock:
                        line = DL.load(w, self.log, you)
                    if line.startswith("Loaded"):
                        self._push("wake", line)
                self._collect_feed()
                self._on_the_hour()
            except Exception as exc:                  # noqa: BLE001
                import traceback
                traceback.print_exc()
                with self.engine.world_lock:
                    self.log.emit(w.sim_time, "game_error", error=f"{type(exc).__name__}: {exc}")
                if not getattr(self, "_told_error", False):
                    self._told_error = True
                    self._push("alert", f"Something went wrong in the simulation ({type(exc).__name__}); "
                                        f"it has carried on. The details are in the terminal.")
                if w.sim_time < getattr(self, "_last_error_at", -1) + 1:
                    time.sleep(0.5)            # a fault on every tick must not spin the CPU
                self._last_error_at = w.sim_time
        self.engine.drain()
        self.save()

    def _on_the_hour(self) -> None:
        """The ledger's hourly snapshot, and at each new game day, the report."""
        w = self.world
        with self.engine.world_lock:
            titles = ADV.titles(w, self.log)
            mine = set(titles.get(self.human_id, []))
            for t in sorted(mine - self._titles):
                self._push("milestone", f"You are now the {t}!")
            for t in sorted(self._titles - mine):
                holder = next((self._name(a) for a, ts in titles.items() if t in ts), "someone")
                self._push("rival", f"You lost the title {t} to {holder}.")
            self._titles = mine
            before = len(self.history.rows)
            self.history.record(w)
            if len(self.history.rows) > before >= 1:
                for line in ADV.overtakes(self.history, self.human_id, w):
                    self._push("rival", line)
            day = int(w.sim_hour // 24)
            if day > self._day:
                self._day = day
                rep = ADV.daily_report(w, self.log, self.you, self.history, day)
                self.reports.append(rep)
                change = rep["worth_change"]
                self._push("report", f"Day {day} is over. Your worth: {rep['worth']:.0f}"
                           + (f" ({change:+.0f} today)" if change is not None else "") + ".")

    # -- the advisors (see convoy/advisor.py) --------------------------------

    def advisor(self) -> dict[str, Any]:
        """What the HUD polls: next moves, goals, building markers, the deltas."""
        with self.engine.world_lock:
            w, me = self.world, self.you
            self.history.record(w)
            led = ADV.ledger(w, self.log, me, self.history)
            return {
                "leaders": ADV.leaderboard(w, me, self.history),
                "titles": ADV.titles(w, self.log),
                "advice": ADV.advice(w, self.log, me, self.history),
                "goals": ADV.goals(w, self.log, me),
                "markers": ADV.markers(w, self.log, me),
                "kpi": {k: led[k] for k in ("rank", "population", "worth", "cash", "worth_per_hour",
                                            "worth_change_1h", "cash_change_1h", "rank_change_1h")},
                "report": self.reports[-1] if self.reports else None,
            }

    def production(self) -> dict[str, Any]:
        """Every business being worked right now: what it is making, how far
        into the next unit it is, how fast, and who is at the bench -- for the
        timers over workers' heads. Read with the engine's own rate and
        headroom functions, so the countdown ends when the unit appears."""
        out = {}
        with self.engine.world_lock:
            w = self.world
            for b in w.businesses.values():
                if b.closed or b.is_government or not b.active_production:
                    continue
                workers = [a.id for a in w.agents.values()
                           if a.alive and a.activity.kind == "work"
                           and a.activity.detail.get("business") == b.id
                           and a.activity.ends_at > w.sim_time]
                # Family and hired hands are always on shift (2026-10-18).
                workers += [e.agent_id for e in b.roster if e.is_npc]
                if not workers:
                    continue
                rate = self.engine.production_rate(b)
                headroom, why = self.engine.production_headroom(b)
                blocked = headroom < 1 or rate <= 0
                out[b.id] = {
                    "item": b.active_production, "progress": round(min(1.0, b.production_buffer), 4),
                    "per_hour": round(rate, 4),
                    "minutes_per_unit": round(60.0 / rate, 2) if rate > 0 else None,
                    "blocked": blocked, "why": why if blocked else "", "workers": workers,
                    "owner": b.owner,
                }
            # FLOORS (2026-10-30): how tall each building stands.
            floors = {b.id: b.storage_tier for b in w.businesses.values()
                      if not b.closed and b.storage_tier}
        return {"hour": round(self.world.sim_hour, 4), "businesses": out, "floors": floors}

    # -- one business, everything the owner needs on one screen ---------------

    def business(self, bid: str) -> dict[str, Any]:
        """A business's economics at a glance: what each output would make with
        the crew it has, what one more worker would add, what that is worth,
        what to offer to hire one, its storage, stock, staff and books.
        Computed with the engine's own production formulas."""
        with self.engine.world_lock:
            w = self.world
            b = w.businesses.get(bid)
            if b is None or b.closed:
                return {"error": "no such business"}
            city = M.city_of(b.location)
            staff = b.production_staff()
            n = len(staff)
            eff = E.efficiency_bonus(b.research.efficiency_tier)
            price = lambda item: E.realizable_price(w, item, city)

            def crew_rate(item: str, crew: int) -> float:
                """Units an hour with `crew` workers all on shift (the extras
                new, unskilled)."""
                base = D.production_rate_hr(item)
                skills = [w.agents[e.agent_id].skill_hours.get(e.role, 0.0)
                          if e.agent_id in w.agents else 0.0 for e in staff][:crew]
                skills += [0.0] * max(0, crew - len(skills))
                total = sum(E.worker_output_rate(base, crew, sk, eff) for sk in skills)
                # Rich ground counts only once revealed: the table must not
                # give away what the first harvest is meant to show.
                return total * (LAND.multiplier(b, item) if b.land_revealed else 1.0)

            outputs = []
            for item in b.spec.outputs:
                recipe = D.REFINING_RECIPES.get(item) or D.CRAFTING_RECIPES.get(item)
                inputs = dict(recipe.inputs) if recipe else {}
                unit_cost = sum(price(i) * q for i, q in inputs.items())
                now_rate = crew_rate(item, max(n, 1))
                more = crew_rate(item, n + 1) - crew_rate(item, n)
                outputs.append({
                    "item": item, "price": round(price(item), 2), "inputs": inputs,
                    "input_cost": round(unit_cost, 2),
                    "rate": round(now_rate, 2), "crew": max(n, 1),
                    "value_per_hour": round(now_rate * (price(item) - unit_cost), 2),
                    "extra_worker_rate": round(more, 2),
                    "extra_worker_value": round(more * (price(item) - unit_cost), 2),
                    "land_bonus": round(b.land_bonus_pct, 3) if b.land_revealed and b.land_bonus_item == item else 0.0,
                    "making": b.active_production == item,
                })
            # What to offer: the floor, what this role has actually gone for
            # lately, and what it takes to beat the best open advert.
            roles = []
            since = w.sim_time - 48 * 3600
            for role in b.spec.production_roles:
                paid = sorted(e.detail.get("wage") or 0.0 for e in self.log.events
                              if e.type == "hired" and e.sim_time >= since and e.detail.get("role") == role
                              and (e.detail.get("wage") or 0) > 0)
                typical = paid[len(paid) // 2] if paid else None
                best_ad = max((p.wage for p in w.job_postings.values()
                               if p.is_live(w.sim_time) and p.role == role and p.business_id != b.id), default=None)
                floor = E.wage_floor(role)
                suggest = max(floor, typical if typical else E.smart_wage(role) * 0.8)
                if best_ad:
                    suggest = max(suggest, best_ad + 1)
                roles.append({"role": role, "floor": round(floor, 2),
                              "typical": None if typical is None else round(typical, 2),
                              "best_advert": None if best_ad is None else round(best_ad, 2),
                              "suggested": round(suggest, 2)})
            producing = b.active_production
            rate_now = self.engine.production_rate(b) if producing else 0.0
            headroom, why = self.engine.production_headroom(b) if producing else (0, "")
            places = E.employee_slots(w, b)
            status = (("watching" if b.production_staff() else "unstaffed")
                      if not b.spec.outputs else
                      "idle" if not producing else
                      "stalled" if b.production_blocked or headroom < 1 else
                      "working" if rate_now > 0 else "unstaffed")
            books = ADV.business_books(w, self.log, b)
            # CAN IT PAY? Wages come out of the business's own cash; a worker
            # who is not paid leaves, and an unpaid business closes. On
            # 2026-10-17 two of the player's hires walked off a mine holding 0
            # while nothing on screen said why.
            payroll = sum(e.wage for e in staff if e.agent_id != b.owner)
            grace_left = None
            if b.insolvent_since is not None:
                grace_left = max(0.0, D.BANKRUPTCY_GRACE_HOURS - (w.sim_time - b.insolvent_since) / 3600.0)
            stock = [{"item": i, "qty": q, "value": round(price(i) * q, 2),
                      "retail": b.retail_prices.get(i), "market": round(price(i), 2)}
                     for i, q in sorted(b.inventory.items()) if q > 0]
            postings = [{"id": p.id, "role": p.role, "wage": round(p.wage, 2),
                         "applicants": [{"id": a, "name": w.agents[a].name if a in w.agents else a} for a in p.applicants]}
                        for p in w.job_postings.values() if p.business_id == b.id and p.is_live(w.sim_time)]
            fam_names = {f"family:{m.id}": f"{m.name} (family)" for m in self.you.family}
            # PROJECTS: the one under way, and the ones you could start.
            from . import progress as PG
            proj = None
            if b.project:
                rate, extra = PG.project_rate(w, b, self.you)
                proj = {"kind": b.project["kind"], "pct": round(b.project["done"] / b.project["total"], 3),
                        "eta": round(PG.eta_hours(w, b, self.you), 2), "rate": round(rate, 2),
                        "material": PG.PROJECTS[b.project["kind"]]["material"],
                        "material_have": b.inventory.get(PG.PROJECTS[b.project["kind"]]["material"], 0),
                        "with_one_more": round(max(0.0, b.project["total"] - b.project["done"])
                                               / max(0.1, rate + 1 + extra), 2)}
            projects = [{"kind": k, "cost": PG.project_cost(b, k), "work": round(PG.project_work(b, k), 1),
                         "does": v["does"], "material": v["material"], "level": b.improvements.get(k, 0),
                         "max": v["max"]}
                        for k, v in PG.PROJECTS.items() if k in PG.available(b)]
            # YOUR FAMILY, from the business itself (2026-10-18): who is grown
            # and free to put to work here, and who already is.
            family = [{"id": m.id, "name": m.name, "role": m.role, "sex": m.sex,
                       "works_here": m.works_at == b.id, "works_at": m.works_at}
                      for m in self.you.family if m.adult] if b.owner == self.human_id else []
            return {
                "family": family, "places_total": places,
                "project": proj, "projects": projects,
                "id": b.id, "type": b.type, "location": b.location, "cash": round(b.cash, 2),
                "producing": producing, "status": status,
                "stall_reason": why if status == "stalled" else "",
                "rate_now": round(rate_now, 2),
                "storage": {"used": sum(b.inventory.values()), "cap": E.business_storage_capacity(w, b)},
                "staff": [{"id": e.agent_id,
                           "name": (w.agents[e.agent_id].name if e.agent_id in w.agents
                                    else fam_names.get(e.agent_id, e.agent_id)),
                           "family": e.agent_id.startswith("family:"),
                           "role": e.role, "wage": round(e.wage, 2),
                           "on_shift": e.is_npc or (e.agent_id in w.agents and w.agents[e.agent_id].activity.kind == "work"
                                                    and w.agents[e.agent_id].activity.detail.get("business") == b.id)}
                          for e in staff],
                "places": places, "places_free": max(0, places - n),
                "you_work_here": any(e.agent_id == self.human_id for e in staff),
                "outputs": outputs, "roles": roles, "stock": stock, "postings": postings,
                "books": {k: books[k] for k in ("revenue", "supplies", "wages", "profit", "profit_per_hour")},
                "land": ({"item": b.land_bonus_item, "pct": b.land_bonus_pct} if b.land_revealed else None)
                        if b.type in LAND.GOODS else None,
                "land_pending": b.type in LAND.GOODS and not b.land_revealed,
                # The ground wearing and the air fouling (convoy/ground.py).
                **GR.view(w, b),
                "payroll_per_hour": round(payroll, 2),
                "insolvent": b.insolvent_since is not None,
                "owed": round(b.insolvent_debt, 2),
                "closes_in_hours": None if grace_left is None else round(grace_left, 1),
            }

    # -- the market ------------------------------------------------------------

    def market(self) -> dict[str, Any]:
        """Everything for sale, your goods to list, and what things fetch.

        A good is FOR SALE when a business holds it and has priced it
        (`set_retail_price`) -- the same price every buyer pays, an agent's
        order or the player's purchase. Finished goods are bought over the
        counter by someone standing there while the shop is staffed; feedstock
        is never sold to people and moves by `order_from_business`, delivered,
        to a business that uses it."""
        with self.engine.world_lock:
            w, me = self.world, self.you
            city = w.city_of(me)
            mine = [b for b in w.businesses.values() if b.owner == me.id and not b.closed]
            # What things have actually sold for, today.
            sold: dict[str, list[float]] = {}
            since = w.sim_time - 24 * 3600
            for e in reversed(self.log.events):
                if e.sim_time < since:
                    break
                if e.type == "sale" and e.detail.get("qty"):
                    row = sold.setdefault(e.detail["item"], [0.0, 0.0, 0.0, 0.0])
                    row[0] += e.detail.get("total") or 0.0
                    row[1] += e.detail["qty"]
                    if e.detail.get("city") == city:
                        row[2] += e.detail.get("total") or 0.0
                        row[3] += e.detail["qty"]
            listings, cheapest = [], {}
            for b in w.businesses.values():
                if b.closed or (b.is_government and M.city_of(b.location) != city):
                    continue
                if not DS.business_known(w, me, b):      # outposts: only people you have found
                    continue
                # The state's sites (your own town's) sell what they make,
                # without limit, at the state's fixed price.
                stock = ({i: 999 for i in state_offers(b)} if b.is_government
                         else b.inventory)
                for item, qty in stock.items():
                    if qty <= 0 or (item not in b.retail_prices and not b.is_government):
                        continue
                    price = b.price_for(item)
                    kind = "order" if D.is_intermediate(item) else "counter"
                    if b.owner != me.id:
                        cheapest[item] = min(cheapest.get(item, 1e18), price)
                    listings.append({
                        "business": b.id, "type": b.type, "item": item, "qty": qty, "price": round(price, 2),
                        "seller": (w.agents[b.owner].name if b.owner in w.agents
                                   else "The state" if b.is_government else b.owner),
                        "state": b.is_government,
                        "mine": b.owner == me.id, "place": b.location, "city": M.city_of(b.location),
                        "open": b.is_staffed(w), "here": b.location == me.location, "kind": kind,
                        "receivers": [{"id": m.id, "type": m.type} for m in mine
                                      if m.id != b.id and A._business_can_use(m, item)] if kind == "order" else [],
                    })
            listings.sort(key=lambda r: (r["item"], r["price"]))
            def stat(item):
                r = sold.get(item)
                avg = (r[2] / r[3]) if r and r[3] else (r[0] / r[1]) if r and r[1] else None
                return {"avg": None if avg is None else round(avg, 2), "sold": int(r[1]) if r else 0,
                        "cheapest": None if item not in cheapest else round(cheapest[item], 2),
                        "book": round(D.base_price(item), 2), "floor": round(E.player_price_floor(item), 2)}
            goods = []
            for b in mine:
                for item, qty in sorted(b.inventory.items()):
                    if qty > 0:
                        goods.append({"business": b.id, "type": b.type, "place": b.location, "item": item, "qty": qty,
                                      "price": b.retail_prices.get(item), "kind": "order" if D.is_intermediate(item) else "counter",
                                      **stat(item)})
            here_mine = [b for b in mine if b.location == me.location]
            carried = [{"item": i, "qty": q, **stat(i),
                        "list_at": [{"id": b.id, "type": b.type} for b in here_mine]}
                       for i, q in sorted(me.inventory.items()) if q > 0]
            # BUY ORDERS: everyone's open bids, and which of your businesses
            # could fill each; yours, with how far filled; and what each of your
            # businesses could ask for (its inputs).
            name = lambda aid: w.agents[aid].name if aid in w.agents else aid
            wanted, my_orders = [], []
            for o in w.buy_orders.values():
                buyer = w.businesses.get(o.business)
                row = {"id": o.id, "item": o.item, "qty": o.qty, "posted": o.qty_posted, "price": o.price,
                       "fee": o.courier_fee, "status": o.status, "buyer": name(o.buyer),
                       "business": o.business, "type": buyer.type if buyer else "",
                       "place": buyer.location if buyer else "", "city": M.city_of(buyer.location) if buyer else "",
                       "escrow": round(o.escrow, 2)}
                if o.buyer == me.id:
                    if o.status == "open" or w.sim_time - o.created_at < 24 * 3600:
                        my_orders.append(row)
                elif o.status == "open" and buyer and DS.business_known(w, me, buyer):
                    row["fill_from"] = [{"id": b.id, "type": b.type, "have": b.inventory.get(o.item, 0)}
                                        for b in mine if b.inventory.get(o.item, 0) > 0]
                    wanted.append(row)
            wanted.sort(key=lambda r: (r["item"], -r["price"]))
            my_orders.sort(key=lambda r: (r["status"] != "open", r["item"]))
            can_ask = []
            for b in mine:
                ins = sorted({i for out in b.spec.outputs
                              for r in [D.REFINING_RECIPES.get(out) or D.CRAFTING_RECIPES.get(out)] if r
                              for i in r.inputs})
                if ins:
                    can_ask.append({"id": b.id, "type": b.type, "place": b.location,
                                    "items": [{"item": i, **stat(i)} for i in ins]})
            # WHO WOULD BUY (2026-10-18): for every good you hold or make, the
            # businesses bidding for it now, best price first, in any town.
            wants = {g["item"] for g in goods} | {o for b in mine for o in (b.spec.outputs or ())}
            bids: dict[str, list[dict[str, Any]]] = {}
            for item in sorted(wants):
                rows = []
                for b in w.businesses.values():
                    if b.owner == me.id or b.closed or not DS.business_known(w, me, b):
                        continue
                    # The state pays the same everywhere: show only your town's site.
                    if b.is_government and M.city_of(b.location) != city:
                        continue
                    bid = A.standing_bid(w, b, item)
                    if bid is None:
                        continue
                    if b.is_government:                       # 100 a day (2026-10-30)
                        bid = (bid[0], A.state_room(w, me))
                    rows.append({"business": b.id, "type": b.type, "place": b.location,
                                 "city": M.CITIES[M.city_of(b.location)].name, "state": b.is_government,
                                 "owner": "the state" if b.is_government else name(b.owner),
                                 "price": bid[0], "qty": bid[1],
                                 "fetch": 0.0 if b.is_government else round(bid[0] * 0.1, 2)})
                rows.sort(key=lambda r: -r["price"])
                # One state row: it pays the same at all four of its sites.
                state_row = next((r for r in rows if r["state"]), None)
                rows = [r for r in rows if not r["state"]] + ([state_row] if state_row else [])
                rows.sort(key=lambda r: -r["price"])
                if rows:
                    bids[item] = rows[:8]
            items = sorted(set(sold) | {r["item"] for r in listings})
            return {"listings": listings, "goods": goods, "carried": carried, "bids": bids,
                    "deliveries": DL.offers(w, me)[:10],
                    "delivery_room": max(0, me.carry_capacity(w) - me.carried_units()),
                    "wanted": wanted, "my_orders": my_orders, "can_ask": can_ask,
                    "cash": round(me.denari, 2),
                    "prices": [{"item": i, **stat(i)} for i in items],
                    "city": city, "my_businesses": [{"id": b.id, "type": b.type, "place": b.location} for b in mine]}

    # -- the land grid (see game3d/main.js) ------------------------------------

    def fetch(self, args: dict[str, Any]) -> dict[str, Any]:
        """FETCH IT YOURSELF (designer request, 2026-10-17): "I bought 10 wheat
        from a farm and wanted to go pick it up myself, not pay a courier fee."

        The rules always allowed it -- order with no carriage fee, claim the
        haul as its courier, load it at the seller, hand it over at your
        business -- but that is four actions an agent strings together and a
        player had no buttons for. This is one: order (if `seller_business_id`
        is given) and claim. Loading and handing over then happen when you walk
        in (see `_haul_on_arrival`). You claim what you can carry; on foot that
        is five units, and the rest stays posted for a second trip.
        """
        w, you = self.world, self.you
        with self.engine.world_lock:
            cid = str(args.get("consignment_id", ""))
            if not cid:
                before = set(w.consignments)
                order = {k: args[k] for k in ("my_business_id", "seller_business_id", "item", "qty") if k in args}
                order["courier_fee"] = 0.0
                ok, msg = self._do("order_from_business", order)
                if not ok:
                    return {"ok": False, "message": msg}
                new = [c for c in w.consignments if c not in before]
                if not new:                       # same place: it was handed over on the spot
                    return {"ok": True, "message": msg}
                cid = new[0]
            con = w.consignments.get(cid)
            if con is None:
                return {"ok": False, "message": "no such delivery"}
            room = max(0, you.carry_capacity(w) - you.carried_units())
            if room <= 0:
                return {"ok": False, "message": (
                    f"your hands are full ({you.carried_units()}/{you.carry_capacity(w)}). "
                    f"The order is placed and waits at {con.origin}; put something down or get a cart.")}
            total = con.qty
            ok, msg = self._do("accept_courier_job", {"consignment_id": cid, "qty": min(room, con.qty)})
            if not ok:
                return {"ok": False, "message": msg}
            mine = next((c for c in w.consignments.values()
                         if c.courier == you.id and c.status == "claimed"), con)
            rest = total - mine.qty
            note = (f" You can carry {mine.qty}; the other {rest} wait at {mine.origin} for another trip."
                    if rest > 0 else "")
            if you.location == mine.origin and not you.in_transit:
                ok, m2 = self._do("collect_consignment", {"consignment_id": mine.id})
                return {"ok": ok, "message": (f"Loaded {mine.qty} {mine.item}. Carry it to {mine.destination}." if ok else m2) + note,
                        "go": mine.destination if ok else None}
            return {"ok": True, "message": f"Go to {mine.origin} to load {mine.qty} {mine.item}, then carry it to {mine.destination}.{note}",
                    "go": mine.origin}

    def _do(self, action: str, args: dict[str, Any]) -> tuple[bool, str]:
        """Dispatch one action for the player and record it as `act` does.
        Call with the world lock held."""
        ok, message = S.dispatch(self.world, self.log, self.you, action, dict(args))
        if ok and action == "travel_to":
            # Riding the road: where you last walked no longer says where you are.
            self.world.positions.pop(self.human_id, None)
        self.log.emit(self.world.sim_time, "action_call", actor=self.human_id,
                      action=action, ok=ok, detail_text=str(message)[:200], why="")
        self._push("did", f"{action}: {message}" if ok else f"{action} refused: {message}")
        return ok, message

    # -- delivery runs (2026-10-18) -------------------------------------------

    def deliveries(self) -> dict[str, Any]:
        """Buyers who want your goods brought to them, and the run you are on."""
        with self.engine.world_lock:
            w, you = self.world, self.you
            d = you.delivery
            cur = None
            if d:
                b = w.businesses.get(d["buyer"])
                cur = {**d, "type": b.type if b else "", "buyer_name": b.name if b else "",
                       "city_name": M.CITIES[d["city"]].name, "total": round(d["unit"] * d["qty"], 2),
                       "from_place": w.businesses[d["from"]].location if d["from"] in w.businesses else ""}
            return {"offers": DL.offers(w, you)[:24], "current": cur,
                    "room": max(0, you.carry_capacity(w) - you.carried_units()),
                    "capacity": you.carry_capacity(w)}

    def delivery(self, body: dict[str, Any]) -> dict[str, Any]:
        with self.engine.world_lock:
            w, you = self.world, self.you
            if body.get("action") == "drop":
                you.delivery = None
                msg = "Delivery dropped; anything you loaded is still with you."
                self._push("did", msg)
                return {"ok": True, "message": msg}
            if body.get("action") == "load":
                d = you.delivery
                if not d:
                    return {"ok": False, "message": "no delivery to load"}
                if d["loaded"]:
                    return {"ok": False, "message": "already loaded: follow the compass"}
                src = w.businesses.get(d["from"])
                if src and you.location != src.location:
                    return {"ok": False, "message": f"go to your {src.type.split(' /')[0]} at {src.location} to load"}
                msg = DL.load(w, self.log, you) or "nothing to load yet"
                self._push("did", msg)
                return {"ok": bool(you.delivery and you.delivery["loaded"]), "message": msg}
            ok, msg = DL.take(w, self.log, you, str(body.get("business_id", "")),
                              str(body.get("buyer_business_id", "")), str(body.get("item", "")),
                              int(body.get("qty", 0) or 0))
        self._push("did" if ok else "alert", msg)
        return {"ok": ok, "message": msg}

    # -- missions (2026-10-18) ------------------------------------------------

    def missions(self) -> dict[str, Any]:
        with self.engine.world_lock:
            w, you = self.world, self.you
            m = you.mission
            return {"board": MI.board(w, you), "active": m,
                    "odds": round(MI.odds(w, you), 2) if m and m.get("id") == "bounty" else None,
                    "at_camp": bool(m and m.get("id") == "bounty" and you.location == m.get("place"))}

    def mission(self, body: dict[str, Any]) -> dict[str, Any]:
        with self.engine.world_lock:
            w, you = self.world, self.you
            act = body.get("action")
            if act == "start":
                ok, msg = MI.start(w, self.log, you, str(body.get("id", "")))
                if ok and you.delivery and you.delivery.get("mission"):
                    extra = DL.load(w, self.log, you)
                    if extra:
                        msg += " " + extra
            elif act == "attack":
                if not (you.mission and you.mission.get("id") == "bounty" and you.location == you.mission.get("place")):
                    ok, msg = MI.attack(w, self.log, you)            # says why not
                    self._push("did", msg)
                    return {"ok": False, "message": msg}
                won, msg = MI.attack(w, self.log, you)
                # A lost fight is an outcome, not a refusal: told once, plainly.
                self._push("did", msg)
                return {"ok": True, "won": won, "message": msg}
            elif act == "abandon":
                ok, msg = True, MI.abandon(w, self.log, you)
            else:
                ok, msg = False, "start, attack or abandon"
        self._push("did", msg)
        return {"ok": ok, "message": msg}

    # -- fights (2026-10-18): your bat against bandits ---------------------------

    def fight_op(self, body: dict[str, Any]) -> dict[str, Any]:
        """One step of a fight, played by the page and scored here. Ops:
        camp (start the bounty camp's fight), road (out between places: are
        you set upon?), swing (at a foe), struck (a foe's blow, blocked or
        not), flee, and state."""
        op = str(body.get("op", "state"))
        with self.engine.world_lock:
            w, you = self.world, self.you
            f, line = self.fight, ""
            if op == "camp":
                mi = you.mission or {}
                if mi.get("id") != "bounty" or you.location != mi.get("place"):
                    return {"ok": False, "message": "no bandit camp here"}
                if you.health < CB.FIT_TO_FIGHT:
                    return {"ok": False, "message": (f"You are too hurt to take them on ({you.health:.0f} health; "
                                                     f"{CB.FIT_TO_FIGHT:.0f} to fight). Eat and rest: health comes back while you are fed.")}
                if f is None or f.over:
                    self.fight = f = CB.start_camp(w, you, int(mi.get("bandits", 2)))
                    line = "The bandits come at you! R to swing, hold F to block."
            elif op == "road":
                if f is None:
                    nf = CB.road_check(w, self.log, you, self.last_ambush)
                    if nf is not None:
                        self.fight, self.last_ambush, f = nf, w.sim_time, nf
                        line = "Bandits! They want what you carry. R to swing, hold F to block -- or run."
                        self._push("alert", line)
            elif f is None:
                return {"ok": False, "message": "no fight", "fight": None}
            elif op == "swing":
                landed, line = CB.swing(w, self.log, you, f, str(body.get("foe", "")))
                if not landed and line == "too soon":
                    return {"ok": False, "message": line, "fight": CB.view(f, you)}
            elif op == "struck":
                _dmg, line = CB.struck(w, self.log, you, f, str(body.get("foe", "")), bool(body.get("blocked")))
            elif op == "flee":
                f.over = f.over or "fled"
            if f is not None and f.over:
                line = (line + " " + self._settle_fight(f)).strip()
            out = {"ok": True, "message": line, "fight": CB.view(f, you)}
            if f is not None and f.over:
                self.fight = None
        return out

    def _settle_fight(self, f: CB.Fight) -> str:
        """The end of a fight. Call with the world lock held."""
        w, you = self.world, self.you
        if f.over == "won":
            if f.kind == "camp":
                msg = MI.finish(w, self.log, you, "bounty", "You drove the bandits off.")
            else:
                coins = CB.spoils(w, you, f)
                msg = f"You beat them off. They dropped {coins:.0f} coins as they ran."
        elif f.over == "lost":
            msg = (CB.rob(w, self.log, you) if f.kind == "ambush" else
                   "The bandits beat you back. Catch your breath -- health returns while you are fed -- and try again.")
        else:
            msg = "You got away." if f.kind == "ambush" else "You fall back from the camp."
        self._push("did", msg)
        return msg

    def depart(self) -> dict[str, Any]:
        """The player walked out of the place they stood in. A shift there ends:
        you cannot work a bench you have walked away from (designer report,
        2026-10-18: "I'm still producing grain when I'm running to get my stuff")."""
        with self.engine.world_lock:
            you, w = self.you, self.world
            if you.activity.kind == "work" and you.activity.ends_at > w.sim_time:
                A.end_shift(w, self.log, you)
                self._push("wake", "You left your shift.")
                return {"ok": True, "message": "You left your shift."}
        return {"ok": True, "message": ""}

    # -- what someone owns (designer request, 2026-10-18) ------------------------

    def cards(self) -> dict[str, Any]:
        """Every clickable thing, as the page sees it. With outposts (2026-10-28)
        only people you have found, showing what they shared with you, and only
        the businesses of people you have found (and the state's)."""
        from . import inspect as INSPECT
        from . import social as SO
        with self.engine.world_lock:
            w, me = self.world, self.you
            cards = INSPECT.cards(w)
            if not w.outposts:
                return {"hour": round(w.sim_hour, 2), "cards": cards}
            out = {}
            for cid, c in cards.items():
                if c.get("kind") == "agent":
                    a = w.agents.get(cid)
                    if a is None or not (a.id == me.id or DS.knows(w, me, a.id)):
                        continue
                    if a.id != me.id:
                        v = SO.view_of(w, me, a)
                        c = {"kind": "agent", "id": a.id, "name": a.name, "alive": a.alive,
                             "at": c.get("at"), "doing": c.get("doing"), "meet": v,
                             **({"net_worth": v["standing"]["worth"], "rank": v["standing"]["rank"],
                                 "of": v["standing"]["of"]} if "standing" in v else {}),
                             "businesses": c["businesses"] if "holdings" in v else []}
                    out[cid] = c
                else:
                    b = w.businesses.get(cid)
                    if b is not None and not DS.business_known(w, me, b):
                        continue
                    out[cid] = c
            return {"hour": round(w.sim_hour, 2), "cards": out}

    def assets(self, agent_id: str) -> dict[str, Any]:
        """Why someone is rich or poor: their net worth, line by line. What is
        counted is what the map shows anyway -- buildings, land, carts -- plus
        coin and goods; what they trade and with whom is a town report."""
        from . import social as SO
        with self.engine.world_lock:
            w = self.world
            a = w.agents.get(agent_id)
            if a is None:
                return {"error": "no such citizen"}
            if w.outposts and not (SO.sees(w, self.you, a, "holdings") and SO.sees(w, self.you, a, "standing")):
                return {"error": f"{a.name} has not shared their standing and holdings with you"}
            city = w.city_of(a)
            biz = []
            for bid in a.owned_businesses:
                b = w.businesses.get(bid)
                if b is None or b.closed:
                    continue
                stock = E.realizable_value(w, b.inventory, M.city_of(b.location))
                biz.append({"id": b.id, "type": b.type, "place": b.location, "worth": round(b.valuation(w), 1),
                            "cash": round(b.cash, 1), "stock": round(stock, 1),
                            "staff": len(b.production_staff()), "making": b.active_production,
                            "profit_day": round(b.daily_profit(w), 1),
                            "state": b.is_government})
            biz.sort(key=lambda x: -x["worth"])
            goods = E.realizable_value(w, a.inventory, city)
            carts = [w.vehicles[v].type for v in a.owned_vehicles if v in w.vehicles]
            plots = sum(1 for p in w.plots.values() if p.owner == a.id)
            prop = w.properties[a.owned_property].assessed_value() if a.owned_property else 0.0
            total = a.net_worth(w)
            lines = [["Coins", round(a.denari, 1)],
                     ["Businesses", round(sum(x["worth"] for x in biz), 1)],
                     ["Goods carried", round(goods, 1)],
                     ["Vehicles", round(sum(D.VEHICLES[t].base_price for t in carts), 1)]]
            if prop:
                lines.append(["Property", round(prop, 1)])
            land = a.land_value(w)
            if land:
                lines.append(["Land (at cost)", round(land, 1)])
            if a.debt:
                lines.append(["Owed to the state", -round(a.debt, 1)])
            return {"id": a.id, "name": a.name, "you": a.id == self.human_id, "house": a.house,
                    "city": city, "city_name": M.CITIES[city].name if city in M.CITIES else city,
                    "calling": a.calling, "worth": round(total, 1), "lines": lines,
                    "businesses": biz, "vehicles": carts, "plots": plots,
                    "goods": {i: q for i, q in sorted(a.inventory.items()) if q > 0},
                    "weapon": a.equipped_weapon, "family": len(a.family),
                    "job": (w.businesses[a.current_job[0]].type
                            if a.current_job and a.current_job[0] in w.businesses else None)}

    # -- you: health, food and what you can eat (designer request, 2026-10-18) ---

    def me(self) -> dict[str, Any]:
        with self.engine.world_lock:
            w, you = self.world, self.you
            here = [b for b in w.businesses_at(you.location, "Tavern / Inn") if not b.closed]
            menu = []
            for t in here:
                tier = 0 if t.is_government else t.research.quality_tier
                meal = E.best_meal_for_tier(tier, "duration")
                if t.is_government or t.inventory.get(meal, 0) > 0:
                    menu.append({"tavern": t.id, "name": t.name, "meal": meal,
                                 "price": round(t.price_for(meal), 2), "hours": E.meal_window(meal),
                                 "staffed": A.is_staffed(w, t)})
            taverns = [b for b in w.businesses.values() if b.type == "Tavern / Inn" and not b.closed
                       and M.city_of(b.location) == w.city_of(you)]
            near = min(taverns, key=lambda b: (b.location != you.location, b.price_for("Meal")), default=None)
            # Taverns, so the card can say where food is: yours first, then the
            # other towns' (a solo town starts with none of its own).
            home = w.city_of(you)
            everywhere = [b for b in w.businesses.values() if b.type == "Tavern / Inn" and not b.closed
                          and M.city_of(b.location) in w.cities]
            town = []
            for t in sorted(everywhere, key=lambda b: (b.location != you.location, M.city_of(b.location) != home,
                                                       b.price_for("Meal")))[:8]:
                tier = 0 if t.is_government else t.research.quality_tier
                meal = E.best_meal_for_tier(tier, "duration")
                town.append({"id": t.id, "name": t.name, "place": t.location, "here": t.location == you.location,
                             "city_name": M.CITIES[M.city_of(t.location)].name, "home": M.city_of(t.location) == home,
                             "meal": meal, "price": round(t.price_for(meal), 2), "hours": E.meal_window(meal),
                             "open": A.is_staffed(w, t) and (t.is_government or t.inventory.get(meal, 0) > 0),
                             "owner": "the state" if t.is_government else
                                      (w.agents[t.owner].name if t.owner in w.agents else "")})
                if w.outposts and t.location != you.location:
                    town[-1]["brought"] = round(town[-1]["price"] + A._meal_fee(w, t, you.location), 2)
                    town[-1]["minutes"] = round(A._dispatch_hours(w, t.location, you.location, A.MEAL_PREP_H) * 60)
            on_way = [{"meal": d.item, "minutes": max(1, round((d.arrives_at - w.sim_time) / 60))}
                      for d in w.dispatches.values()
                      if d.kind == "meal" and d.agent == you.id and d.status == "on_way"]
            fed_left = you.last_meal_window - you.hours_since_last_meal
            return {"name": you.name, "house": you.house, "health": round(you.health, 1),
                    "stage": you.sustenance_stage, "fed_hours": round(max(0.0, fed_left), 1),
                    "weapon": you.equipped_weapon, "armour": {k: v for k, v in you.equipped_armor.items() if v},
                    # YOUR KIT (2026-10-30): weapons and armour you carry, to put on.
                    "kit": [{"item": i, "qty": q, "weapon": i in D.WEAPONS,
                             "stat": (f"{D.WEAPONS[i].damage:.0f} damage" if i in D.WEAPONS
                                      else f"{D.ARMOR[i].slot}, -{D.ARMOR[i].damage_reduction:.0%} damage")}
                            for i, q in sorted(you.inventory.items())
                            if q > 0 and (i in D.WEAPONS or i in D.ARMOR)],
                    "weapon_damage": D.WEAPONS[you.equipped_weapon].damage if you.equipped_weapon in D.WEAPONS else 0,
                    "full_stomach": A.FULL_STOMACH_H,
                    "carried": [{"meal": m, "qty": q, "hours": E.meal_window(m)}
                                for m, q in sorted(you.inventory.items()) if m in D.MEALS and q > 0],
                    "menu": menu, "coins": round(you.denari, 2), "on_way": on_way,
                    "outposts": w.outposts,
                    "nearest_tavern": ({"id": near.id, "place": near.location, "name": near.name}
                                       if near else None),
                    "taverns": town}

    def eat(self, body: dict[str, Any]) -> dict[str, Any]:
        """Eat from the character card: a meal you carry, or one bought at a
        tavern where you stand."""
        with self.engine.world_lock:
            if body.get("carried"):
                ok, msg = A.eat_meal(self.world, self.log, self.you, str(body.get("meal", "")))
                self._push("did" if ok else "alert", msg)
            elif body.get("order"):
                ok, msg = self._do("order_meal", {"business_id": str(body["order"])})
            else:
                args = {"business_id": body["tavern"]} if body.get("tavern") else {}
                ok, msg = self._do("buy_meal", args)
        return {"ok": ok, "message": msg}

    # -- claims on open land (2026-10-18) -------------------------------------

    def pins(self, body: dict[str, Any]) -> dict[str, Any]:
        """Add or remove one of your own pins on the full map (map metres)."""
        with self.engine.world_lock:
            you = self.you
            if body.get("remove") is not None:
                i = int(body["remove"])
                if 0 <= i < len(you.pins):
                    you.pins.pop(i)
                return {"ok": True, "pins": you.pins}
            try:
                x, y = float(body.get("x")), float(body.get("y"))
            except (TypeError, ValueError):
                return {"ok": False, "message": "where?"}
            label = str(body.get("label") or "").strip()[:40] or "Pin"
            if len(you.pins) >= 60:
                return {"ok": False, "message": "you have 60 pins already: remove one first"}
            you.pins.append({"x": round(x, 1), "y": round(y, 1), "label": label})
            return {"ok": True, "pins": you.pins}

    def seen_at(self, body: dict[str, Any]) -> dict[str, Any]:
        """Where the player is standing in the 3D world, in map metres, so
        the people they walk past find them (outposts; see discovery.py)."""
        try:
            x, y = float(body.get("x")), float(body.get("y"))
        except (TypeError, ValueError):
            return {"ok": False}
        with self.engine.world_lock:
            self.world.positions[self.human_id] = [round(x, 1), round(y, 1)]
        return {"ok": True}

    def settle(self, body: dict[str, Any]) -> dict[str, Any]:
        """Found your outpost at (x, y), borrowing `borrow` from the state."""
        with self.engine.world_lock:
            try:
                x, y = float(body.get("x")), float(body.get("y"))
                borrow = float(body.get("borrow") or 0.0)
            except (TypeError, ValueError):
                return {"ok": False, "message": "where?"}
            if body.get("quote"):
                q = CL.quote(self.world, x, y, home=not self.you.home)
                if not self.you.home:
                    # The first home and its road are free (2026-10-28).
                    q.update(total=0.0, land_cost=0.0, road_cost=0.0, free=True)
                return {"ok": True, **q, "ground": CL.ground_hint(self.world, x, y),
                        "cash": round(self.you.denari, 2), "max_loan": CL.MAX_SETTLE_LOAN}
            ok, msg, c = CL.settle(self.world, self.log, self.you, x, y, borrow)
        self._push("milestone" if ok else "alert", msg)
        self._map_dirty = True
        return {"ok": ok, "message": msg, "place": c.name if c else None,
                "claim": ({"name": c.name, "x": c.x, "y": c.y, "road": c.road, "city": c.city,
                           "owner": c.owner} if c else None)}

    def wild_claim(self, body: dict[str, Any]) -> dict[str, Any]:
        from . import claims as CL
        with self.engine.world_lock:
            try:
                x, y = float(body.get("x")), float(body.get("y"))
            except (TypeError, ValueError):
                return {"ok": False, "message": "where?"}
            if body.get("quote"):
                return {"ok": True, **CL.quote(self.world, x, y)}
            ok, msg, c = CL.claim(self.world, self.log, self.you, x, y, str(body.get("purpose", "")))
        self._push("did" if ok else "alert", msg)
        self._map_dirty = True
        return {"ok": ok, "message": msg, "place": c.name if c else None,
                "claim": ({"name": c.name, "x": c.x, "y": c.y, "road": c.road, "city": c.city,
                           "owner": c.owner} if c else None)}

    def road(self, body: dict[str, Any]) -> dict[str, Any]:
        """BUILT ROADS (2026-10-30): price or build a dirt road from your claim
        `place` to the road or claim nearest (x, y), or to claim `to`."""
        with self.engine.world_lock:
            place = str(body.get("place", ""))
            try:
                x = float(body["x"]) if body.get("x") is not None else None
                y = float(body["y"]) if body.get("y") is not None else None
            except (TypeError, ValueError):
                return {"ok": False, "message": "where?"}
            to = str(body.get("to") or "")
            c = self.world.claims.get(place)
            if c is None or c.owner != self.you.id:
                return {"ok": False, "message": f"{place} is not your land"}
            if body.get("quote"):
                return {"ok": True, **CL.road_plan(self.world, place, x, y, to),
                        "cash": round(self.you.denari, 2)}
            ok, msg = CL.build_road(self.world, self.log, self.you, place, x, y, to)
        self._push("milestone" if ok else "alert", msg)
        self._map_dirty = True
        return {"ok": ok, "message": msg, "road": c.road if ok else None}

    def _haul_on_arrival(self) -> tuple[str, str | None]:
        """Walking in with a haul to do does it: load at the origin, hand over
        at the destination. Returns what happened and where to go next."""
        w, you = self.world, self.you
        if you.hauling:
            con = w.consignments.get(you.hauling)
            if con and you.location == con.destination:
                ok, msg = self._do("deliver_consignment", {"consignment_id": con.id})
                if ok:
                    # The rest of a no-fee order is yours to fetch: claim the
                    # next load now, so walking back loads it.
                    left = [c for c in w.consignments.values()
                            if c.status == "awaiting_courier" and c.buyer_business == con.buyer_business
                            and c.seller_business == con.seller_business and c.item == con.item
                            and c.courier_fee <= 0]
                    if not left:
                        return f" Handed over {con.qty} {con.item}.", None
                    total = sum(c.qty for c in left)
                    room = max(0, you.carry_capacity(w) - you.carried_units())
                    ok2, _ = self._do("accept_courier_job", {"consignment_id": left[0].id,
                                                             "qty": min(room, left[0].qty)})
                    if not ok2:
                        return f" Handed over {con.qty} {con.item}. {total} more wait at {con.origin}.", None
                    return (f" Handed over {con.qty} {con.item}. Back to {con.origin} for the "
                            f"other {total}."), con.origin
            return "", None
        con = next((c for c in w.consignments.values()
                    if c.courier == you.id and c.status == "claimed"), None)
        if con and you.location == con.origin:
            ok, msg = self._do("collect_consignment", {"consignment_id": con.id})
            if ok:
                return f" Loaded {con.qty} {con.item}; carry it to {con.destination}.", con.destination
            return f" Could not load {con.item}: {msg}", None
        return "", None

    # -- people (designer request, 2026-10-18) ---------------------------------

    REPORT_COST = 100.0

    def _town(self, city: str | None) -> dict[str, Any]:
        """Everyone in a city -- or, with no towns (outposts, None), everyone
        -- what they own, where they work (not the wage -- that is theirs to
        tell), their calling and their experience. Call with the world lock held."""
        w, me = self.world, self.you
        here = (lambda place: True) if city is None else (lambda place: M.city_of(place) == city)
        people = []
        from . import social as SO
        for a in (list(w.agents.values()) if city is None else w.agents_in(city)):
            if not a.alive:
                continue
            # Outposts: only people you have found, and only what they shared.
            if w.outposts and a.id != me.id and not DS.knows(w, me, a.id):
                continue
            hide = w.outposts and a.id != me.id
            job = None
            if a.current_job:
                biz = w.businesses.get(a.current_job[0])
                if biz is not None:
                    job = {"business": biz.id, "type": biz.type, "role": a.current_job[1],
                           "employer": ("the state" if biz.is_government
                                        else "themself" if biz.owner == a.id
                                        else w.agents[biz.owner].name if biz.owner in w.agents else biz.owner)}
            skills = sorted(({"role": r, "hours": round(h, 1), "level": E.skill_label(h)}
                             for r, h in a.skill_hours.items() if h >= 0.5),
                            key=lambda x: -x["hours"])
            people.append({
                "id": a.id, "name": a.name, "you": a.id == me.id, "calling": a.calling,
                "house": a.house, "household": len(a.family), "ally": a.id in me.allies,
                "worth": (None if hide and not SO.sees(w, me, a, "standing") else round(a.net_worth(w), 0)),
                "location": a.location,
                "owns": ([] if hide and not SO.sees(w, me, a, "holdings") else
                         [{"id": b, "type": w.businesses[b].type, "place": w.businesses[b].location}
                          for b in a.owned_businesses if b in w.businesses and not w.businesses[b].closed]),
                "job": job, "skills": skills,
                "shared": SO.view_of(w, me, a)["shared"] if hide else list(SO.KINDS),
                "contact": (not hide) or SO.sees(w, me, a, "contact"),
            })
        people.sort(key=lambda p: -(p["worth"] or 0))
        counts = Counter(b.type for b in w.businesses.values()
                         if not b.closed and here(b.location) and not b.is_government)
        state = sorted(b.type for b in w.businesses.values()
                       if not b.closed and b.is_government and here(b.location))
        return {"city": city or "", "name": M.CITIES[city].name if city else "the frontier",
                "hour": round(w.sim_hour, 1),
                "population": len(people), "people": people,
                "buildings": [{"type": t, "count": n} for t, n in counts.most_common()],
                "state_sites": state}

    def citizens(self, city: str = "") -> dict[str, Any]:
        """Your own city, live; another city, from the report you last bought."""
        with self.engine.world_lock:
            w = self.world
            mine = w.city_of(self.you)
            city = city if city in w.cities else mine
            others = [{"key": c, "name": M.CITIES[c].name,
                       "report_hour": (self.intel.get(c) or {}).get("hour")}
                      for c in w.cities if c != mine]
            # CLANS: across towns. A secret one is seen only by its members.
            clans = []
            for g in w.guilds.values():
                members = [w.agents[m] for m in g.members if m in w.agents]
                inside = self.you.id in g.members
                if g.secret and not inside:
                    continue
                clans.append({"id": g.id, "name": g.name, "secret": g.secret, "mine": inside,
                              "members": len(members), "worth": round(sum(a.net_worth(w) for a in members)),
                              "towns": sorted({M.CITIES[w.city_of(a)].name for a in members}),
                              "names": [a.name for a in members] if inside or not g.secret else []})
            clans.sort(key=lambda c: (not c["mine"], -c["worth"]))
            base = {"cities": others, "your_city": mine, "report_cost": self.REPORT_COST,
                    "cash": round(self.you.denari, 2), "clans": clans,
                    "my_clan": self.you.guild or ""}
            if w.outposts:
                # No towns: everyone, live, and no reports to buy.
                return {**base, "cities": [], **self._town(None), "live": True, "outposts": True}
            if city == mine:
                return {**base, **self._town(city), "live": True}
            snap = self.intel.get(city)
            if snap is None:
                return {**base, "city": city, "name": M.CITIES[city].name, "locked": True,
                        "population": len(w.agents_in(city))}
            return {**base, **snap, "live": False}

    def buy_report(self, city: str) -> dict[str, Any]:
        """A report on another town: who lives there, what they own and what they
        are good at, as of now. The money goes to nobody -- it is the cost of
        sending someone to look."""
        with self.engine.world_lock:
            w, you = self.world, self.you
            if city not in w.cities or city == w.city_of(you):
                return {"ok": False, "message": "pick another town"}
            if you.denari < self.REPORT_COST:
                return {"ok": False, "message": f"a report costs {self.REPORT_COST:.0f}; you have {you.denari:.0f}"}
            you.denari -= self.REPORT_COST
            self.intel[city] = self._town(city)
            self.log.emit(w.sim_time, "report_bought", actor=you.id, city=city,
                          cost=self.REPORT_COST)
        self._push("did", f"Bought a report on {M.CITIES[city].name} for {self.REPORT_COST:.0f}.")
        return {"ok": True, "message": f"Report on {M.CITIES[city].name} bought."}

    def thread(self, other: str) -> dict[str, Any]:
        """Your private messages with one person, oldest first."""
        with self.engine.world_lock:
            w, me = self.world, self.human_id
            a = w.agents.get(other)
            if a is None:
                return {"ok": False, "message": "no such person"}
            msgs = [{"from_me": m.sender == me, "text": m.text, "hour": round(m.sim_time / 3600.0, 2)}
                    for m in w.chat
                    if m.channel == "direct" and {m.sender, m.recipient} == {me, other}]
            return {"ok": True, "with": {"id": a.id, "name": a.name, "calling": a.calling,
                                         "city": M.CITIES[w.city_of(a)].name},
                    "messages": msgs[-80:]}

    def plots(self) -> dict[str, Any]:
        """Every owned plot in the world, and the squares the player chose for
        theirs. The 3D page lays each place out as a block of grid squares and
        puts every plot on one; a business's four plots make a 2x2 block."""
        with self.engine.world_lock:
            w = self.world
            rows = [{"id": q.id, "place": q.location, "owner": q.owner, "business": q.business,
                     "developed": q.developed, "for_sale": q.for_sale_at, "home": q.home,
                     "structure": q.structure}
                    for q in w.plots.values() if q.owner]
            return {"plots": rows, "claims": dict(self.claims),
                    "totals": {p: M.plots_at(p) for c in w.cities for p in M.places_in(c)}}

    def claim(self, place: str, cells: list[str], business_id: str = "") -> dict[str, Any]:
        """Put the player's plots at `place` on the squares they picked:
        those attached to `business_id` if given (a business just founded),
        otherwise their most recently bought unattached plots."""
        with self.engine.world_lock:
            w, me = self.world, self.human_id
            mine = [q for q in w.plots.values() if q.owner == me and q.location == place]
            if business_id == "structure":
                # A defense on your own land (2026-10-30) takes a plot you
                # already had there: move it onto the square you picked,
                # trading places with whatever free plot of yours was there.
                built = next((e.detail.get("plot") for e in reversed(self.log.events)
                              if e.type == "defense_built" and e.actor == me and e.location == place), None)
                q = w.plots.get(built or "")
                if q is None or not cells:
                    return {"ok": False, "claimed": 0}
                cell, old = cells[0], self.claims.get(q.id)
                other = next((pid for pid, c in self.claims.items() if c == cell and pid != q.id), None)
                if other is not None:
                    o = w.plots.get(other)
                    if o is None or o.owner != me or o.business or o.home or o.structure:
                        return {"ok": False, "claimed": 0}
                    if old:
                        self.claims[other] = old
                    else:
                        del self.claims[other]
                self.claims[q.id] = cell
                return {"ok": True, "claimed": 1}
            if business_id:
                mine = [q for q in mine if q.business == business_id]
            else:
                mine = [q for q in mine if not q.business and not q.home and q.id not in self.claims]
            mine.sort(key=lambda q: q.id, reverse=not business_id)
            taken = set(self.claims.values())
            done = 0
            for q, cell in zip(mine, cells):
                if cell in taken:
                    continue
                self.claims[q.id] = cell
                taken.add(cell)
                done += 1
            return {"ok": done > 0, "claimed": done}

    def ledger(self) -> dict[str, Any]:
        with self.engine.world_lock:
            self.history.record(self.world)
            return ADV.ledger(self.world, self.log, self.you, self.history)

    def chains(self) -> dict[str, Any]:
        with self.engine.world_lock:
            return ADV.chains(self.world, self.world.city_of(self.you))

    def stop(self) -> None:
        self.stopped = True
        if self._thread is not None:
            self._thread.join(timeout=120)
        self.engine.close()

    def spent(self) -> float:
        return self.spent_before + sum(u.cost for u in self.models.usage.values())

    def thinking(self) -> int:
        return len(self.engine._pending)

    # -- the player's view ---------------------------------------------------

    @property
    def you(self) -> Agent:
        return self.world.agents[self.human_id]

    def _push(self, kind: str, text: str, hour: float | None = None, ref: str | None = None) -> None:
        """A feed line. `ref` names the building it is about, so the map can
        point at it."""
        self._feed_seq += 1
        self.feed.append({"seq": self._feed_seq, "kind": kind, "text": text, "ref": ref,
                          "hour": round(self.world.sim_hour if hour is None else hour, 2)})

    def _wake(self, world: World, agent: Agent, reason: str) -> None:
        # The routine check-in every quarter hour is not news to a person
        # looking at the screen; arriving, finishing and being called are.
        if agent.sustenance_stage != self._hunger_told:
            self._hunger_told = agent.sustenance_stage
            if agent.sustenance_stage != "Normal":
                self._push("alert", f"You are {agent.sustenance_stage.upper()}. Eat a Meal "
                                    f"at a tavern that has one, or you will weaken and die.")
        if reason == "reevaluation":
            return
        # A wait running out, or the idle timer the engine parks an idle agent
        # on, is not news to someone looking at the screen. A shift, a
        # journey or a raid ending is.
        if reason == "activity_complete" and agent.activity.kind == "idle":
            return
        haul = ""
        if reason == "arrived":            # fast travel ends here: load or hand over, as on foot
            with self.engine.world_lock:
                haul, _ = self._haul_on_arrival()
        nice = {"arrived": f"You arrived at {agent.location}.{haul}",
                "activity_complete": "You are free: what you were doing has finished."}
        self._push("wake", nice.get(reason, f"You were woken: {reason}"))

    def _name(self, ref: str | None) -> str:
        if not ref:
            return "someone"
        if ref == self.human_id:
            return "you"
        a = self.world.agents.get(ref)
        if a is not None:
            return f"{a.name} ({ref})"
        b = self.world.businesses.get(ref)
        return b.name if b is not None else ref

    def _describe(self, e) -> tuple[str, str] | None:
        """One feed line for an event, or None if it is not worth one.

        The player's own actions are already reported by `act` as they happen,
        so the events those actions emit are skipped rather than said twice."""
        me, d, n = self.human_id, e.detail, self._name
        mine = set(self.you.owned_businesses)
        if e.type == "chat":
            if d.get("recipient") == me and e.actor != me:
                return "message", f"{n(e.actor)} to you: {d.get('text', '')}"
            return None
        if e.type == "land_revealed" and e.actor == me:
            biz = self.world.businesses.get(e.subject)
            kind = biz.type if biz else "business"
            if d.get("item"):
                return "milestone", (f"Rich ground! Your {kind} at {e.location} makes "
                                     f"{d['item']} {d.get('pct', 0):.0%} faster.")
            return "you", f"Your {kind} at {e.location} is on ordinary ground: no bonus."
        if e.type == "reflex" and e.actor == me:
            if d.get("reflex") == "keep waiting":
                return None
            return "you", f"Autopilot: {d.get('did', d.get('reflex'))}"
        if e.actor == me and e.type in _OWN_ACTION_ECHOES:
            return None
        # MEETING PEOPLE (2026-10-28): greetings, shares and requests to you.
        if e.subject == me and e.actor != me:
            who = n(e.actor)
            if e.type == "greeted":
                return "message", f"{who} says hi" + (f": {d.get('text')}" if d.get("text") else ".")
            if e.type == "share_asked":
                from . import social as SO
                return "milestone", (f"{who} asks you to share {SO.KINDS.get(d.get('kind'), d.get('kind'))}. "
                                     f"Answer it on the People page.")
            if e.type == "shared":
                return "milestone", (f"{who} shared their {d.get('kind')} with you"
                                     + (": pinned on your map." if d.get("kind") == "locations" else
                                        ": you can message them now." if d.get("kind") == "contact" else "."))
            if e.type == "share_answered":
                if d.get("priced"):
                    return "you", (f"{who} will share their {d.get('kind')} for a price: "
                                   f"see it on their card (People).")
                return "you", (f"{who} {'shared' if d.get('accepted') else 'declined to share'} "
                               f"their {d.get('kind')}.")
            if e.type == "group_joined":
                return "you", f"{who} added you to the group {d.get('name')}."
        if e.actor == me and e.type in ("greeted", "shared", "share_asked", "share_answered",
                                        "group_made", "group_joined", "info_bought"):
            return None
        # Outposts: someone found (2026-10-28) -- the only way to trade with them.
        if e.type == "met" and me in (e.actor, e.subject):
            other = self.world.agents.get(e.subject if e.actor == me else e.actor)
            if other is not None:
                owns = sorted({self.world.businesses[b].type.split(" /")[0] for b in other.owned_businesses
                               if b in self.world.businesses})
                return "milestone", (f"You found {other.name} of {other.house}"
                                     + (f", who owns a {', a '.join(owns)}" if owns else "")
                                     + ". You can trade with them now.")
        # BANDIT GANGS (2026-10-30, convoy/robbery.py): coming, robbing, done.
        if e.actor == me and e.type in ("robbery_sighted", "robbery_started", "building_robbed", "robbery_beaten"):
            biz = self.world.businesses.get(e.subject)
            what = f"your {biz.type.split(' /')[0]} at {e.location}" if biz else e.location
            n = d.get("bandits", 0)
            if e.type == "robbery_sighted":
                return "alert", (f"Your lookouts see {n} bandits heading for {what}, about "
                                 f"{d.get('minutes', 0)} min away.")
            if e.type == "robbery_started":
                return "alert", (f"{n} bandits are robbing {what}! They will be gone with a share of its "
                                 f"goods and purse in an hour unless someone stops them.")
            if e.type == "building_robbed":
                goods = ", ".join(f"{q} {i}" for i, q in (d.get("goods") or {}).items())
                return "alert", (f"Bandits robbed {what}: they took "
                                 + (goods or "no goods") + f" and {d.get('cash', 0):.0f} from its purse.")
            return "milestone", f"Your {d.get('lookouts')} lookouts drove the bandits off from {what}."
        if e.actor == me and e.type == "gang_set_out":
            return None
        # Outposts: things brought to you, and what you settled (2026-10-27).
        if e.actor == me and e.type == "meal_delivered":
            return "wake", f"Your {d.get('item', 'meal')} has arrived; eat it from your card when you are hungry."
        if e.actor == me and e.type == "state_collected":
            return "milestone", f"The state's convoy collected {d.get('qty')} {d.get('item')}: +{d.get('paid', 0):.0f}."
        if e.actor == me and e.type in ("settled", "meal_ordered", "state_convoy_called", "debt_repaid",
                                        "road_built"):
            return None
        if e.actor == me and e.type == "delivered":
            return "milestone", f"Delivered {d.get('qty')} {d.get('item')}: +{d.get('paid', 0):.0f}."
        # The countdowns landing, and the household (2026-10-18).
        if e.actor == me and e.type == "tech_learned":
            return "milestone", f"You learned {d.get('name')}."
        if e.actor == me and e.type == "project_done":
            biz = self.world.businesses.get(e.subject)
            return "milestone", f"{d.get('project')} finished at your {biz.type.split(' /')[0] if biz else 'business'}."
        if e.actor == me and e.type == "came_of_age":
            return "family", f"{d.get('name')} has come of age: put them to work, or marry them into another house."
        if e.actor == me and e.type == "child_born":
            return "family", f"A child is born to {' and '.join(p for p in d.get('parents', []) if p)}: {d.get('name')}."
        if e.type == "marriage_proposed" and e.subject == me:
            return "family", (f"{d.get('house')} proposes their {d.get('member')} for your "
                              f"{d.get('their_member')}, with a dowry of {d.get('dowry', 0):.0f}.")
        if e.type == "married" and me in (e.actor, e.subject):
            return "milestone", (f"{' and '.join(d.get('couple', []))} are married: "
                                 f"{' and '.join(d.get('houses', []))} are allies.")
        if e.type == "marriage_declined" and e.subject == me:
            return "family", f"{self._name(e.actor)} turned down your proposal."
        if e.type == "succession" and e.actor == me:
            return "alert", (f"You died ({d.get('cause')}). {d.get('heir')} takes over {d.get('house')}: "
                             f"what you carried is lost, everything you own stays in the family.")
        if e.type == "buy_order_filled" and d.get("buyer") == me and e.actor != me:
            where = (f"It waits at {e.location}: fetch it from Market, Deliveries."
                     if d.get("consignment") else "It is in your stock.")
            return "you", (f"{n(d.get('seller_business'))} filled your buy order: {d.get('qty')} "
                           f"{d.get('item')} at {d.get('price')}. {where}")
        if e.type == "buy_order_posted" and e.actor != me:
            hold = [b for b in (self.world.businesses.get(x) for x in mine)
                    if b and (b.inventory.get(d.get("item"), 0) > 0 or d.get("item") in (b.spec.outputs or ()))]
            if hold:
                return "wanted", (f"{n(e.actor)} wants {d.get('qty')} {d.get('item')} at "
                                  f"{d.get('price')} each -- your {hold[0].type.split(' /')[0]} could fill it.")
            return None
        if e.type == "sale":
            if d.get("seller") in mine or d.get("seller") == me:
                return "you", (f"{n(d.get('seller'))} sold {d.get('qty')} {d.get('item')} to "
                               f"{n(d.get('buyer'))} for {d.get('total')}")
            if e.actor != me and (d.get("buyer") in mine or d.get("buyer") == me):
                return "you", (f"{n(d.get('buyer'))} bought {d.get('qty')} {d.get('item')} from "
                               f"{n(d.get('seller'))} for {d.get('total')}")
            return None
        if e.type == "payment" and e.subject == me:
            note = f": {d['note']}" if d.get("note") else ""
            return "you", f"{n(e.actor)} paid you {d.get('amount')}{note}"
        if e.type == "job_offered" and d.get("target") == me:
            return "message", (f"{n(e.actor)} offered you {d.get('role')} at {n(e.subject)} "
                               f"for {d.get('wage')}/hr ({d.get('posting')}). "
                               f"accept_job_offer to take it.")
        if e.type == "hired" and e.subject in mine and e.actor != me:
            return "you", f"{n(e.actor)} now works at {n(e.subject)} as {d.get('role')}"
        if e.type == "quit_job" and e.subject in mine and e.actor != me:
            return "you", f"{n(e.actor)} left {n(e.subject)}"
        if e.type == "job_applied" and e.subject in mine:
            return "you", f"{n(e.actor)} applied for a job at {n(e.subject)}"
        if e.type == "wages_unpaid" and (e.subject in mine or d.get("worker") == me):
            return "alert", f"{d.get('business')} could not pay {n(d.get('worker'))}'s wages"
        if e.type in ("bankruptcy_warning", "business_bankrupt", "business_closed") and e.subject in mine:
            return "alert", f"{n(e.subject)}: {e.type.replace('_', ' ')}"
        if e.type == "robbed" and e.actor == me:
            return "alert", (f"You were robbed on {d.get('segment')}: about {d.get('value_lost')} "
                             f"taken by {', '.join(d.get('raiders') or []) or 'raiders'}")
        if e.type in ("robbed", "raid_repelled") and self.you.name in (d.get("raiders") or []):
            return "you", f"Your raid: {e.type.replace('_', ' ')} on {d.get('segment')}"
        if e.type in ("agent_died", "starved_to_death"):
            return ("alert" if e.actor == me else "news",
                    f"{n(e.actor)} died ({d.get('cause', e.type)})")
        if e.type == "business_founded" and e.actor != me:
            return "news", f"{n(e.actor)} opened a {d.get('business_type')} at {e.location}"
        involved = (e.actor == me or e.subject == me or e.subject in mine
                    or e.actor in mine or me in (d.get("target"), d.get("worker"), d.get("recipient")))
        if involved:
            return "you", self._plain(e)
        if e.significance >= Significance.HIGH:
            return "news", self._plain(e)
        return None

    def _rivalry(self, e) -> tuple[str, str] | None:
        """Competition aimed at you: someone opening the same kind of business
        in your city, or pricing below you. Returned with the rival building's
        id, so the map can show where."""
        w, me = self.world, self.you
        if e.actor == me.id:
            return None
        mine = [w.businesses[b] for b in me.owned_businesses if b in w.businesses and not w.businesses[b].closed]
        if not mine:
            return None
        city = w.city_of(me)
        if e.type == "business_founded":
            biz = w.businesses.get(e.subject)
            if biz and M.city_of(biz.location) == city and any(b.type == biz.type for b in mine):
                near = next((b for b in mine if b.type == biz.type and b.location == biz.location), None)
                where = f"right next to yours at {biz.location}" if near else f"at {biz.location}"
                return (f"{self._name(e.actor)} opened a rival {biz.type} {where}.", biz.id)
        if e.type == "price_set":
            biz = w.businesses.get(e.subject)
            item, price = e.detail.get("item"), e.detail.get("price") or 0.0
            if biz and M.city_of(biz.location) == city:
                for b in mine:
                    if item in b.retail_prices and price < b.retail_prices[item] - 1e-6:
                        return (f"{self._name(e.actor)} now sells {item} at {price:.2f}, "
                                f"under your {b.retail_prices[item]:.2f}.", biz.id)
        return None

    def _plain(self, e) -> str:
        """Any other event, with names instead of ids."""
        bits = ", ".join(f"{k.replace('_', ' ')} {self._name(v) if isinstance(v, str) and v[:1] in 'AB' and v[1:].isdigit() else v}"
                         for k, v in e.detail.items() if v not in (None, "", [], {}))
        return f"{self._name(e.actor) if e.actor else ''} {e.type.replace('_', ' ')}: {bits}".strip()

    def _collect_feed(self) -> None:
        """Turn new events that concern the player into feed lines."""
        with self.engine.world_lock:
            events = self.log.events[self._seen_events:]
            self._seen_events = len(self.log.events)
            for e in events:
                rival = self._rivalry(e)
                if rival:
                    self._push("rival", rival[0], e.sim_hour, ref=rival[1])
                    continue
                if e.type in _FEED_SKIP:
                    continue
                line = self._describe(e)
                if line is not None:
                    # A message carries who sent it, so the page can open the thread.
                    self._push(line[0], line[1], e.sim_hour,
                               ref=e.actor if line[0] == "message" else None)
            self._scan_listings()

    def _scan_listings(self) -> None:
        """NEW ON THE MARKET (designer request, 2026-10-17): "I should be
        notified when someone offers things to sell on the market that I can
        decide to buy." A listing is a business holding a good at a price; an
        alert goes out when one appears (or comes back into stock) or its price
        drops by a twentieth, for a good one of your businesses uses or one you
        have a buy order out for. Everything else would bury the feed.
        Call with the world lock held."""
        w, me = self.world, self.you
        mine = [w.businesses[b] for b in me.owned_businesses
                if b in w.businesses and not w.businesses[b].closed]
        care = {i for b in mine for out in b.spec.outputs
                for r in [D.REFINING_RECIPES.get(out) or D.CRAFTING_RECIPES.get(out)] if r
                for i in r.inputs}
        care |= {o.item for o in w.buy_orders.values() if o.buyer == me.id and o.status == "open"}
        now = {}
        for b in w.businesses.values():
            if b.closed or b.is_government or b.owner == me.id:
                continue
            for item, qty in b.inventory.items():
                if qty > 0 and item in b.retail_prices:
                    now[(b.id, item)] = (b.price_for(item), qty)
        seen = getattr(self, "_listings_seen", None)
        self._listings_seen = now
        if seen is None:                      # first look: what is already there is not news
            return
        for (bid, item), (price, qty) in now.items():
            if item not in care:
                continue
            was = seen.get((bid, item))
            if was is not None and price > was[0] * 0.95:
                continue
            b = w.businesses[bid]
            what = "now sells" if was is None else "cut its price on"
            self._push("offer", f"{self._name(b.owner)}'s {b.type.split(' /')[0]} at {b.location} "
                                f"{what} {item}: {qty} at {price:.2f}.", w.sim_hour, ref=item)

    # -- know-how, the household, and what is coming (2026-10-18) -------------

    def knowhow(self) -> dict[str, Any]:
        """The tech tree as you stand: known, studying, open, locked -- and what
        each would be worth to you now."""
        from . import progress as PG
        with self.engine.world_lock:
            w, you = self.world, self.you
            mine = [w.businesses[b] for b in you.owned_businesses
                    if b in w.businesses and not w.businesses[b].closed]
            def day_value(types) -> float:
                total = 0.0
                for b in mine:
                    if b.type in types and b.active_production:
                        total += self.engine.production_rate(b) * D.base_price(b.active_production) * 24
                return total
            def worth(tid: str) -> str:
                kinds = {"irrigation": ("Farm",), "picks": ("Mining Operation",),
                         "bellows": ("Refinery",), "hearth": D.STORE_BUSINESS_TYPES}
                if tid in kinds:
                    v = day_value(kinds[tid]) * 0.10
                    return f"about +{v:.0f} a day at your businesses now" if v >= 1 else "nothing yet: you own none that it speeds"
                if tid == "steam":
                    return f"about +{day_value(tuple(D.BUSINESS_TYPES)) * 0.15:.0f} a day now"
                if tid == "charter":
                    return f"+{min(25, 5 * len(you.allies))}% with your {len(you.allies)} allies"
                return ""
            r = you.researching
            nodes = []
            for tid, t in PG.TECHS.items():
                ok_, why = PG.can_study(you, tid)
                status = ("known" if tid in you.tech else "studying" if r and r["tech"] == tid
                          else "open" if ok_ else "locked")
                nodes.append({"id": tid, "name": t["name"], "tier": t["tier"], "hours": t["hours"],
                              "does": t["does"], "status": status, "why": "" if ok_ else why,
                              "worth": worth(tid),
                              "eta": round(t["hours"] / PG.research_rate(you), 1)})
            return {"nodes": nodes, "rate": PG.research_rate(you),
                    "studying": ({"id": r["tech"], "name": PG.TECHS[r["tech"]]["name"],
                                  "pct": round(r["done"] / PG.TECHS[r["tech"]]["hours"], 3),
                                  "eta": round(PG.research_eta(you), 2)} if r else None)}

    def household(self) -> dict[str, Any]:
        """Your house: who is in it, where they work, who you could marry into."""
        from . import family as FAM
        with self.engine.world_lock:
            w, you = self.world, self.you
            now = w.sim_time
            def mrow(m, owner):
                sp = FAM.member(owner, m.spouse) if m.spouse and m.spouse != FAM.HEAD else None
                return {"id": m.id, "name": m.name, "adult": m.adult, "calling": m.calling,
                        "sex": m.sex, "role": m.role, "partner": m.spouse == FAM.HEAD,
                        "pct_grown": (None if m.adult or not m.grown_at else
                                      round(min(1.0, max(0.0, (now - m.born_at) / max(1.0, m.grown_at - m.born_at))), 3)),
                        "grows_in": None if m.adult else round(max(0.0, (m.grown_at - now) / 3600), 2),
                        "works_at": m.works_at,
                        "works_type": w.businesses[m.works_at].type if m.works_at in w.businesses else "",
                        "spouse": "you" if m.spouse == FAM.HEAD else (sp.name if sp else ""),
                        "from_house": m.from_house,
                        "next_child_in": (round(max(0.0, (m.next_child_at - now) / 3600), 2)
                                          if m.spouse and m.next_child_at else None)}
            city = w.city_of(you)
            houses = []
            for a in w.agents.values():
                if a.id == you.id or not a.alive or not a.house:
                    continue
                free = [mrow(m, a) for m in a.family if m.adult and not m.spouse]
                houses.append({"agent": a.id, "name": a.name, "house": a.house,
                               "city": M.CITIES[w.city_of(a)].name, "here": w.city_of(a) == city,
                               "ally": a.id in you.allies, "free": free,
                               "size": len(a.family)})
            houses.sort(key=lambda h: (not h["here"], not h["free"], h["house"]))
            offers_in = [{"id": o.id, "house": w.agents[o.proposer].house, "agent": o.proposer,
                          "their": (FAM.member(w.agents[o.proposer], o.member) or type("x", (), {"name": "?"})).name,
                          "mine": (FAM.member(you, o.their_member) or type("x", (), {"name": "?"})).name,
                          "dowry": o.dowry}
                         for o in w.marriage_offers.values()
                         if o.target == you.id and o.status == "open" and o.proposer in w.agents]
            offers_out = [{"id": o.id, "house": w.agents[o.target].house, "status": o.status, "dowry": o.dowry}
                          for o in w.marriage_offers.values() if o.proposer == you.id and o.target in w.agents]
            return {"house": you.house, "members": [mrow(m, you) for m in you.family],
                    "you": {"name": you.name, "sex": you.sex, "calling": you.calling},
                    "meals": you.inventory.get("Meal", 0),
                    "home": next((q.location for q in w.plots.values() if q.home and q.owner == you.id), ""),
                    "cap": FAM.cap(you), "allies": [{"agent": a, "house": w.agents[a].house}
                                                    for a in you.allies if a in w.agents],
                    "businesses": [{"id": b, "type": w.businesses[b].type} for b in you.owned_businesses
                                   if b in w.businesses and not w.businesses[b].closed],
                    "houses": houses, "offers_in": offers_in, "offers_out": offers_out,
                    "cash": round(you.denari, 2)}

    def upcoming(self) -> list[dict[str, Any]]:
        """Every countdown you have running, soonest first: the 'next turn'."""
        from . import progress as PG
        w, you = self.world, self.you
        out = []
        if you.researching:
            out.append({"what": f"Learn {PG.TECHS[you.researching['tech']]['name']}",
                        "hours": PG.research_eta(you), "kind": "tech"})
        for bid in you.owned_businesses:
            b = w.businesses.get(bid)
            if b and b.project and not b.closed:
                out.append({"what": f"{b.project['kind']} at your {b.type.split(' /')[0]}",
                            "hours": PG.eta_hours(w, b, you), "kind": "project", "ref": b.id})
        for m in you.family:
            if not m.adult and m.grown_at:
                out.append({"what": f"{m.name} comes of age", "hours": max(0.0, (m.grown_at - w.sim_time) / 3600),
                            "kind": "family"})
            if m.spouse and m.next_child_at:
                out.append({"what": f"{m.name}'s next child", "hours": max(0.0, (m.next_child_at - w.sim_time) / 3600),
                            "kind": "family"})
        for d in w.dispatches.values():
            if d.agent != you.id or d.status != "on_way":
                continue
            what = (f"{d.item} brought to you" if d.kind == "meal" else
                    f"The state's convoy collects {d.qty} {d.item} ({d.unit_price * d.qty:.0f})")
            out.append({"what": what, "hours": max(0.0, (d.arrives_at - w.sim_time) / 3600),
                        "kind": "dispatch", "ref": d.business if d.kind == "state_pickup" else None})
        out.sort(key=lambda x: x["hours"])
        return [{**x, "hours": round(x["hours"], 2)} for x in out[:6]]

    def state(self) -> dict[str, Any]:
        """Everything the player's agent would be shown, as data and as text."""
        with self.engine.world_lock:
            obs = O.observe(self.world, self.log, self.you, "you looked",
                            record_delivery=True)
            return {"obs": obs, "text": O.render(obs)}

    def briefing(self) -> str:
        with self.engine.world_lock:
            return O.briefing_for(self.world, self.you)

    def tools(self) -> list[dict[str, Any]]:
        city = self.world.city_of(self.you)
        gone = self.world.state_gone_at(city) is not None
        return [t["function"] for t in S.tool_schemas(state_gone=gone,
                                                      no_state=self.world.no_state,
                                                      outposts=self.world.outposts, player=True)]

    def arrive(self, place: str) -> dict[str, Any]:
        """The player WALKED here, in the 3D world.

        In the 3D game the player's body moves under the arrow keys, not by
        `travel_to`'s timer, and the server learns where they are only when
        they step into a named place. That is when their location changes, so
        buying in a tavern needs them physically at the tavern, as it needs an
        agent to have travelled there. Walking out of a place mid-shift ends
        the shift -- you cannot work a bench you have walked away from -- and
        an unfinished `travel_to` is abandoned, because the feet won.

        Fair against the agents at the default pace: a two-minute walk across
        town is about 24 game minutes, a little slower than the timed road.
        """
        w, you = self.world, self.you
        if place not in M.EVERY_PLACE or M.city_of(place) not in w.cities:
            return {"ok": False, "message": f"{place} is not a place in this world"}
        with self.engine.world_lock:
            if not you.alive:
                return {"ok": False, "message": "you are dead"}
            if you.location == place and not you.in_transit:
                return {"ok": True, "message": f"at {place}"}
            note = ""
            if you.activity.kind == "work" and you.activity.ends_at > w.sim_time:
                ok, _ = A.end_shift(w, self.log, you)
                note = " You left your shift."
            if you.activity.kind == "raid":
                return {"ok": False, "message": "you are lying in wait; abandon the raid first"}
            origin = you.location
            you.in_transit = None
            you.activity = Activity("idle", w.sim_time)
            you.location = place
            if you.mounted_vehicle and you.mounted_vehicle in w.vehicles:
                w.vehicles[you.mounted_vehicle].location = place
            # Logged as a journey that has already ended, so the map's tracks,
            # the escorts and every other reader see the player where they are.
            self.log.emit(w.sim_time, "travel", actor=you.id, location=origin,
                          destination=place, seconds=0.0, walked=True)
            haul, go = self._haul_on_arrival()
            # A delivery run: load at your business, hand over at the buyer's.
            if you.delivery:
                for line in (DL.load(w, self.log, you), DL.complete(w, self.log, you)):
                    if line:
                        haul += " " + line
        self._push("wake", f"You arrived at {place}.{note}{haul}")
        return {"ok": True, "message": f"arrived at {place}.{note}{haul}", "haul": haul.strip(), "go": go}

    def act(self, action: str, args: dict[str, Any]) -> dict[str, Any]:
        """One action, exactly as an agent's tool call would run it."""
        if not isinstance(args, dict):
            return {"ok": False, "message": "arguments must be an object"}
        with self.engine.world_lock:
            # "WORK HERE MYSELF" MEANS WORK. For an agent, joining its own
            # business's roster and starting a shift are two decisions; for the
            # player they are one click, from whichever button. Already on the
            # roster there, it just starts the shift.
            you, biz = self.you, self.world.businesses.get(str(args.get("business_id", "")))
            # A job at the state's site is taken the same way: one click, and to work.
            own_work = (action == "apply_for_job" and biz is not None
                        and (biz.owner == you.id or biz.is_government))
            # MOVING TO ANOTHER OF YOUR BENCHES (2026-10-18): working your mine
            # after your farm used to be refused with "quit first" -- ending a
            # shift does not leave the job. Going to work somewhere of your own
            # (or the state's) leaves the old job for you.
            if own_work and you.current_job and you.current_job[0] != biz.id:
                if you.activity.kind == "work":
                    S.dispatch(self.world, self.log, you, "end_shift", {})
                okq, msgq = S.dispatch(self.world, self.log, you, "quit_job", {})
                self.log.emit(self.world.sim_time, "action_call", actor=self.human_id,
                              action="quit_job", ok=okq, detail_text=str(msgq)[:200], why="")
            if own_work and you.current_job and you.current_job[0] == biz.id:
                ok, message = S.dispatch(self.world, self.log, you, "start_shift", {"hours": 4})
                self.log.emit(self.world.sim_time, "action_call", actor=self.human_id,
                              action="start_shift", ok=ok, detail_text=str(message)[:200], why="")
                self._push("did", message if ok else f"start_shift refused: {message}")
                return {"ok": ok, "message": message}
            ok, message = S.dispatch(self.world, self.log, self.you, action, dict(args))
            if own_work and ok:
                ok2, msg2 = S.dispatch(self.world, self.log, you, "start_shift", {"hours": 4})
                self.log.emit(self.world.sim_time, "action_call", actor=self.human_id,
                              action="start_shift", ok=ok2, detail_text=str(msg2)[:200], why="")
                message = f"{message}; {msg2}" if ok2 else f"{message} (but could not start work: {msg2})"
            # Logged like a model's call, so the map, the trade board and every
            # other reader treat the player exactly like anyone else.
            self.log.emit(self.world.sim_time, "action_call", actor=self.human_id,
                          action=action, ok=ok, detail_text=str(message)[:200], why="")
        self._push("did", f"{action}: {message}" if ok else f"{action} refused: {message}")
        return {"ok": ok, "message": message}

    def activity(self) -> str:
        """What the player is doing right now, in one line, for the top of the
        screen."""
        w, you = self.world, self.you
        act = you.activity
        left = max(0.0, (act.ends_at - w.sim_time) / 3600.0) if act.ends_at != float("inf") else 0.0
        if not you.alive:
            return "Dead -- you will be back soon"
        if act.kind == "travel" and you.in_transit:
            return f"Travelling to {you.in_transit[1]} \u00b7 {left * 60:.0f} min left"
        if act.kind == "work":
            biz = w.businesses.get(act.detail.get("business", ""))
            where = biz.name if biz else "work"
            if biz and biz.owner == you.id:
                where = f"your {biz.type}"
            return f"Working at {where} \u00b7 {left:.1f}h left"
        if act.kind == "raid":
            return f"Lying in wait on {act.detail.get('segment', 'the road')} \u00b7 {left:.1f}h left"
        return f"Idle at {you.location}"

    def status(self) -> dict[str, Any]:
        w = self.world
        you = self.you
        fed_left = you.last_meal_window - you.hours_since_last_meal
        city = w.city_of(you)
        standings = w.city_standings() if w.is_contest() else []
        mounted = w.vehicles.get(you.mounted_vehicle) if you.mounted_vehicle else None
        # What is up on the market now, for the page's "something new" badge.
        market_keys = sorted(
            [f"{b.id}:{i}" for b in w.businesses.values()
             if not b.closed and not b.is_government and b.owner != you.id
             for i, q in b.inventory.items() if q > 0 and i in b.retail_prices]
            + [o.id for o in w.buy_orders.values() if o.status == "open" and o.buyer != you.id])
        upcoming = self.upcoming()
        # A fetch of your own (2026-10-18): the page points the way, you ride.
        con = (w.consignments.get(you.hauling) if you.hauling else
               next((c for c in w.consignments.values() if c.courier == you.id and c.status == "claimed"), None))
        haul = None if con is None else {
            "id": con.id, "item": con.item, "qty": con.qty, "loaded": you.hauling == con.id,
            "origin": con.origin, "destination": con.destination,
            "from": con.seller_business, "to": con.buyer_business}
        return {"upcoming": upcoming, "market_keys": market_keys, "delivery": you.delivery, "mission": you.mission,
            "haul": haul, "health": round(you.health, 1), "fight": CB.view(self.fight, you),
            "activity": self.activity(),
            "location": you.location,
            # What the player rides, and how much faster than walking it is:
            # the 3D page moves them at this multiple. See `D.VEHICLES`.
            "vehicle": mounted.type if mounted else None,
            "speed": round(D.VEHICLES[mounted.type].speed_mult / D.VEHICLES["On Foot"].speed_mult, 2)
                     if mounted else 1.0,
            "vehicles": [{"id": v.id, "type": v.type, "location": v.location,
                          "mounted": v.id == you.mounted_vehicle}
                         for v in w.vehicles.values() if v.owner == you.id],
            "hunger": you.sustenance_stage,
            "fed_hours_left": round(fed_left, 2),
            "city": city,
            "city_name": M.CITIES[city].name if city in M.CITIES else city,
            "cities": [] if w.outposts else [{"key": r["city"], "name": r["name"],
                        "total": round(r["total_net_worth"], 1)} for r in standings],
            "game": self.run_dir.name,
            "hour": round(w.sim_hour, 3),
            "paused": self.paused,
            "note": self.note,
            "pace": self.settings.pace,
            "spent": round(self.spent(), 4),
            "budget": self.settings.budget,
            "thinking": self.thinking(),
            "you": {"id": you.id, "name": you.name, "city": w.city_of(you),
                    "settled": you.settled, "home": you.home, "debt": round(you.debt, 2),
                    "outposts": w.outposts, "known": list(you.known) + list(you.allies),
                    # BANDIT GANGS (2026-10-30): coming for, robbing or having robbed yours.
                    "robberies": RB.for_owner(w, you) if w.outposts else [],
                    # BUILT ROADS (2026-10-30): your land, and whether a road joins it up.
                    "land": [{"name": c.name, "road": bool(c.road), "connected": CL.connected(w, c.name)}
                             for c in w.claims.values() if c.owner == you.id] if w.outposts else [],
                    # MEETING PEOPLE (2026-10-28): whose contact you hold, who shared
                    # where their land is, requests waiting on you, your groups, pins.
                    "contacts": SO.contacts(w, you),
                    "locations_from": [a.id for a in w.agents.values()
                                       if a.id != you.id and "locations" in a.shared.get(you.id, [])],
                    "requests": [{"id": r.id, "from": r.sender, "name": w.agents[r.sender].name,
                                  "kind": r.kind, "what": SO.KINDS[r.kind]}
                                 for r in w.share_requests.values()
                                 if r.target == you.id and r.status == "open" and r.sender in w.agents],
                    "groups": [{"id": g.id, "name": g.name, "members": g.members}
                               for g in w.groups.values() if you.id in g.members],
                    "pins": list(you.pins),
                    "denari": round(you.denari, 2),
                    "net_worth": round(you.net_worth(w), 2), "alive": you.alive},
            "leaders": [
                {"name": a.name, "id": a.id, "worth": round(a.net_worth(w), 1),
                 "you": a.id == you.id}
                for a in sorted(w.agents.values(), key=lambda a: -a.net_worth(w))
                if not w.outposts or a.id == you.id or SO.sees(w, you, a, "standing")
            ][:10],
            # The same ranking the ledger uses: equals share a rank.
            "your_rank": 1 + sum(1 for a in w.agents.values()
                                 if a.net_worth(w) > you.net_worth(w) + 1e-6),
            "population": len(w.agents),
            "settings": asdict(self.settings),
        }

    def board(self) -> dict[str, Any]:
        """The world's public notice boards, shaped for the player's menus:
        jobs, haulage, raids, places with travel times, what can be founded.
        Everything here is on the map or in an agent's observation already."""
        w, me = self.world, self.human_id
        you = self.you
        n = lambda ref: (w.agents[ref].name if ref in w.agents
                         else w.businesses[ref].name if ref in w.businesses else ref)
        vehicle = w.vehicles[you.mounted_vehicle].type if you.mounted_vehicle else None
        with self.engine.world_lock:
            places = []
            for c in w.cities:
                for name in M.places_in(c):
                    try:
                        mins = (0.0 if name == you.location else
                                E.travel_seconds(you.location, name, vehicle) / 60.0)
                    except Exception:            # noqa: BLE001 -- no road: leave it blank
                        mins = None
                    places.append({"name": name, "city": c,
                                   "city_name": M.CITIES[c].name,
                                   "minutes": None if mins is None else round(mins)})
            jobs = []
            for p in w.job_postings.values():
                if not p.is_live(w.sim_time):
                    continue
                invitee = getattr(p, "invitee", "")
                if invitee and invitee != me and p.owner != me:
                    continue                      # somebody else's private offer
                biz = w.businesses.get(p.business_id)
                jobs.append({
                    "id": p.id, "role": p.role, "wage": round(p.wage, 2),
                    "business": n(p.business_id), "business_id": p.business_id,
                    "at": biz.location if biz else "", "owner": p.owner,
                    "mine": p.owner == me, "to_me": invitee == me,
                    "applied": me in p.applicants,
                    "applicants": [{"id": a, "name": n(a)} for a in p.applicants]
                    if p.owner == me else len(p.applicants),
                })
            hauls = []
            for c in w.consignments.values():
                if c.status not in ("awaiting_courier", "claimed"):
                    continue
                poster = w.businesses.get(c.buyer_business)
                hauls.append({
                    "id": c.id, "item": c.item, "qty": c.qty, "fee": round(c.courier_fee, 2),
                    "from": c.origin, "to": c.destination, "status": c.status,
                    "mine_to_carry": c.courier == me,
                    "mine_to_receive": bool(poster and poster.owner == me),
                    "carrying": you.hauling == c.id,
                    "to_business": poster.type.split(" /")[0] if poster else "",
                    "seller": (w.businesses[c.seller_business].name
                               if c.seller_business in w.businesses else ""),
                })
            raids = [{"id": r.id, "segment": r.segment, "members": len(r.members),
                      "hours_left": round(max(0.0, r.until - w.sim_time) / 3600.0, 1),
                      "mine": me in r.members}
                     for r in w.raids.values() if r.status == "waiting"]
            types = [{"name": t, "cost": spec.startup_cost,
                      "spur": t in ("Farm", "Mining Operation"),
                      "makes": list(spec.outputs),
                      **({"does": (f"Makes nothing: hire Lookouts or put your grown family there. Each "
                                   f"on watch guards your loads on journeys within "
                                   f"{D.LOOKOUT_RANGE_M / 1000:.1f} km of it against raiders.")}
                         if not spec.outputs else {})}
                     for t, spec in D.BUSINESS_TYPES.items()]
            # Land anywhere: four squares of open land, with a road (2026-10-18).
            if w.outposts:
                # Priced where you put it (convoy/claims.py): the cheapest it can be.
                floor = CL.LAND_FLOOR * M.CLAIM_PLOTS
                types += [{"name": "Land claim", "cost": floor, "spur": None, "claim": True, "from": True,
                           "makes": [], "does": (f"Four squares of open land, with no road (build one after): "
                                                 f"from {floor:.0f} far out, dearer near people. The map shows the price.")}]
            else:
                types += [{"name": "Land claim", "cost": D.LAND_BASE_PRICE * 4, "spur": None, "claim": True,
                           "makes": [], "does": "Buy four squares anywhere on open land; a dirt road is laid to them."}]
            # Defenses take one square, anywhere (2026-10-18).
            types += [{"name": k, "cost": v["cost"], "spur": None, "defense": True, "size": 1,
                       "makes": [], "does": v["does"]} for k, v in D.DEFENSES.items()]
            # Real estate: unsold ground at every place, at the world's price,
            # and plots other people have put up for sale.
            owned_at: Counter[str] = Counter(q.location for q in w.plots.values() if q.owner)
            for row in places:
                total = M.plots_at(row["name"])
                row["plots_free"] = max(0, total - owned_at[row["name"]])
                row["plots_total"] = total
            listed = [{"id": q.id, "at": q.location, "price": round(q.for_sale_at, 2),
                       "owner": n(q.owner), "mine": q.owner == me, "developed": q.developed}
                      for q in w.plots.values() if q.for_sale_at is not None and q.owner]
            my_land = [{"id": q.id, "at": q.location, "developed": q.developed,
                        "business": q.business, "for_sale_at": q.for_sale_at}
                       for q in w.plots.values() if q.owner == me]
        return {"places": places, "jobs": jobs, "hauls": hauls, "raids": raids,
                "carry_room": max(0, you.carry_capacity(w) - you.carried_units()),
                # What each business makes, takes in and holds, so a form about
                # one offers only its goods -- not Bread at a refinery.
                "biz_items": {b.id: {"makes": list(b.spec.outputs or ()),
                                     "uses": sorted(set(A._usable_items(b)) - set(b.spec.outputs or ())),
                                     "holds": sorted(i for i, q in b.inventory.items() if q > 0),
                                     "priced": sorted(i for i, q in b.inventory.items()
                                                      if q > 0 and i in b.retail_prices)}
                              for b in w.businesses.values() if not b.closed and b.spec},
                "land_price": D.LAND_BASE_PRICE, "listed_land": listed, "my_land": my_land,
                "business_types": types,
                "agents": [{"id": a.id, "name": a.name, "city": w.city_of(a)}
                           for a in w.agents.values() if a.alive and a.id != me],
                "items": [i for i in D.ALL_ITEMS if i != "On Foot"],
                "segments": [s.name for s in M.EVERY_SEGMENT
                             if any(x in w.cities for x in (M.city_of(s.a), M.city_of(s.b)))]}

    def feed_since(self, seq: int) -> list[dict[str, Any]]:
        return [f for f in self.feed if f["seq"] > seq]
