"""A head start: the towns run without you first, and you arrive as a newcomer.

Designer request, 2026-10-18: "load me in assuming the agents have been
operating the town for 12 in-game hours already -- that way it's a little more
authentic." At hour zero fifty people with identical purses look at an empty
valley at the same moment, so nothing anyone does is a reaction to anything.
Twelve hours in there are prices, owners, jobs, people with experience and
links nobody has filled, and the player's first decision can be an informed
one -- which is also how the shared world will feel, where a player joins a
town that already exists.

A head start costs real time and money (the clock waits on the model), so
each one is kept as a TOWN TEMPLATE in `runs/towns/` and a later game with the
same towns starts from a copy, instantly and for nothing. The player is never
in the template: they are added on arrival, an extra citizen named like the
rest, so a template does not depend on which town the player picks.
"""

from __future__ import annotations

import json
import random
import shutil
import threading
import time
from pathlib import Path
from typing import Any, Callable

from . import checkpoint
from . import data as D
from . import llm
from . import world_map as M
from .engine import Engine, EngineConfig
from .events import EventLog
from .state import Agent
from .world_setup import new_world
from . import family as FAM

TOWNS_DIR = Path(__file__).resolve().parent.parent / "runs" / "towns"
STEP_SECONDS = 600.0          # progress is reported every ten game minutes
HEAD_START_RPM = 240.0
HEAD_START_WORKERS = 32


def town_key(settings) -> str:
    """What makes two head starts interchangeable."""
    cities = "-".join(f"{c}{int(n)}" for c, n in sorted(settings.cities.items()))
    model = settings.model.split("/")[-1]
    kind = "outposts" if getattr(settings, "outposts", False) else ("starter" if settings.starter_sites else "bare")
    return f"{cities}_{kind}_{model}_{int(settings.head_start)}h"


def find_template(settings, towns_dir: Path = TOWNS_DIR) -> Path | None:
    """The newest finished template for these settings, if any."""
    key = town_key(settings)
    found = sorted((p for p in towns_dir.glob(f"{key}__*") if (p / "town.json").exists()),
                   reverse=True)
    return found[0] if found else None


def _rosters(settings) -> dict[str, list[tuple[str, str]]]:
    tail = settings.model.split("/")[-1]
    if getattr(settings, "outposts", False):
        # No towns, so nobody is named for one: settlers, numbered across the
        # whole frontier. The city is only which trading post they start near.
        out, k = {}, 0
        for city, n in settings.cities.items():
            out[city] = [(f"Settler-{tail}-{k + i + 1:02d}", settings.model) for i in range(int(n))]
            k += int(n)
        return out
    return {city: [(f"{M.CITIES[city].name}-{tail}-{i + 1:02d}", settings.model)
                   for i in range(int(n))]
            for city, n in settings.cities.items()}


class HeadStart:
    """Runs the towns with nobody watching, in a thread, and reports progress.

    `progress` is read by the start page while it waits."""

    def __init__(self, settings, towns_dir: Path = TOWNS_DIR, models: Any = None):
        self.settings = settings
        self.towns_dir = towns_dir
        self.models = models
        self.hour = 0.0
        self.target = float(settings.head_start)
        self.spent = 0.0
        self.error: str | None = None
        self.done: Path | None = None
        self.cancelled = False
        self.started = time.time()
        self._thread: threading.Thread | None = None

    def progress(self) -> dict[str, Any]:
        return {"hour": round(self.hour, 2), "target": self.target, "spent": round(self.spent, 3),
                "seconds": round(time.time() - self.started), "error": self.error,
                "done": self.done is not None}

    def start(self, on_done: Callable[[Path], None]) -> None:
        def run() -> None:
            try:
                path = self.run()
                if path is not None:
                    on_done(path)
            except Exception as exc:                  # noqa: BLE001
                self.error = f"{type(exc).__name__}: {exc}"
        self._thread = threading.Thread(target=run, name="head-start", daemon=True)
        self._thread.start()

    def run(self) -> Path | None:
        """Build and run the towns; save them as a template. Returns its folder."""
        s = self.settings
        key = town_key(s)
        work = self.towns_dir / f"{key}__{time.strftime('%Y%m%d-%H%M%S')}"
        work.mkdir(parents=True, exist_ok=True)
        log = EventLog(work / "events.jsonl", echo_min=99)
        world = new_world(log, [], _rosters(s), government=s.government,
                          starter_sites=s.starter_sites)
        world.npc_bandits = False
        deal = random.Random(world.land_seed)
        if getattr(s, "outposts", False):
            populate_outposts(world, log, deal)
        else:
            for a in world.agents.values():
                a.calling = deal.choice(list(D.CALLINGS))
                FAM.found_household(world, a, deal)
                FAM.give_donkey(world, a)
        # Nobody is watching, so it runs as fast as the model allows: a higher
        # request rate and more agents thinking at once than live play uses.
        models = self.models if self.models is not None else llm.LLMPolicy(
            log=log, requests_per_minute=max(s.rpm, HEAD_START_RPM))
        engine = Engine(world, log, models, EngineConfig(
            duration_hours=float("inf"), speed=1e9, checkpoint_every_hours=1.0,
            decision_workers=max(s.workers, HEAD_START_WORKERS), reflexes=True, restock=True,
        ))
        log.emit(0.0, "sim_start", agents=len(world.agents), businesses=len(world.businesses),
                 duration_hours=None, cities=list(world.cities), no_state=world.no_state,
                 head_start=self.target)
        engine._stagger_opening()
        try:
            while world.sim_time < self.target * 3600.0 - 1e-6:
                if self.cancelled:
                    return None
                if self.spent >= s.budget:
                    self.error = (f"stopped at hour {world.sim_hour:.1f}: the head start reached "
                                  f"the ${s.budget:.2f} spending cap")
                    return None
                engine.step_until(min(self.target * 3600.0, world.sim_time + STEP_SECONDS))
                self.hour = world.sim_hour
                self.spent = sum(u.cost for u in getattr(models, "usage", {}).values())
            engine.drain()
        finally:
            engine.close()
        with engine.world_lock:
            checkpoint.save(world, work / "checkpoint.json")
            log.flush()
        (work / "town.json").write_text(json.dumps({
            "key": key, "hour": round(world.sim_hour, 2), "spent": round(self.spent, 4),
            "agents": len(world.agents), "made": time.strftime("%Y-%m-%d %H:%M"),
            "businesses": sum(1 for b in world.businesses.values()
                              if not b.closed and not b.is_government),
        }, indent=2))
        self.done = work
        return work


def arrive(template: Path, run_dir: Path, settings) -> tuple[Any, EventLog, str, float]:
    """Copy a template into a new game folder and add the player to it.

    Returns (world, log, the player's id, what the head start cost)."""
    run_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy(template / "checkpoint.json", run_dir / "checkpoint.json")
    shutil.copy(template / "events.jsonl", run_dir / "events.jsonl")
    meta = json.loads((template / "town.json").read_text())
    world = checkpoint.load(run_dir / "checkpoint.json")
    log = EventLog(run_dir / "events.jsonl", echo_min=99)
    log.replay()
    # A town made before households existed (2026-10-18) gets them now, so a
    # head start already paid for is still good.
    for a in world.agents.values():
        if a.alive and not a.house:
            FAM.found_household(world, a)
    you = settle(world, log, settings)
    return world, log, you, float(meta.get("spent", 0.0))


HOME_PLOTS = 4


def populate_outposts(world, log: EventLog, rng: random.Random) -> None:
    """OUTPOSTS (2026-10-27): no towns at hour zero. Every agent gets a
    calling, a house and a donkey, and settles on open land near its roster
    city's anchor -- the state's trading post. See `claims.auto_settle`."""
    from . import claims as CL
    world.outposts = True
    for a in list(world.agents.values()):
        a.calling = rng.choice(list(D.CALLINGS))
        FAM.found_household(world, a, rng)
        FAM.give_donkey(world, a)
        a.settled = False
        CL.auto_settle(world, log, a, a.city or world.cities[0], rng)


def settle(world, log: EventLog, settings) -> str:
    """Add the player to a world: in their town (a new one of their own, in a
    solo start), with a house, a home on four plots of the square, and a
    newcomer's protection. Returns their id."""
    from .world_setup import STARTER_SITE_TYPES, build_government
    from .state import Plot
    city = settings.your_city
    if city not in world.cities:
        # A NEW TOWN of the player's own, beside the agents'. It opens the way
        # every town does: the state's four sites, if this world has them.
        world.cities.append(city)
        if world.starter_sites:
            build_government(world, log, city, only=STARTER_SITE_TYPES)
    tail = settings.model.split("/")[-1]
    # Named as the next of the town, so you read as someone who came later --
    # or, with no towns, as the next settler.
    if world.outposts:
        name = f"Settler-{tail}-{len(world.agents) + 1:02d}"
    else:
        name = f"{M.CITIES[city].name}-{tail}-{len(world.agents_in(city)) + 1:02d}"
    you = Agent(id=world.new_id("A"), name=name,
                model=settings.model, city=city, location=M.market_of(city))
    you.calling = settings.calling
    world.agents[you.id] = you
    FAM.found_household(world, you, sex=settings.sex, partner_sex=settings.partner_sex)
    # Everyone has a donkey -- agents in an older town too.
    for a in world.agents.values():
        if a.alive:
            FAM.give_donkey(world, a)
    you.protected_until = world.sim_time + 24 * 3600.0     # a newcomer's first day
    if world.no_state:
        you.last_meal_window = D.START_FED_HOURS_NO_STATE
    if world.outposts:
        # You choose your land on the map before the clock runs: no home in
        # the square. You wait at the anchor until then. See `claims.settle`.
        you.settled = False
        log.emit(world.sim_time, "arrived_in_town", actor=you.id, location=you.location,
                 city=city, text=f"{you.name} came to the frontier near {M.CITIES[city].name}.")
        return you.id
    # YOUR HOME (2026-10-18): four plots of your town's square, yours and not
    # for sale. The page draws it with your border around it.
    home = M.market_of(city)
    if M.plots_free(world, home) >= HOME_PLOTS:
        for _ in range(HOME_PLOTS):
            q = Plot(id=world.new_id("L"), location=home, owner=you.id, developed=True, home=True)
            world.plots[q.id] = q
    log.emit(world.sim_time, "arrived_in_town", actor=you.id, location=you.location,
             city=city, text=f"{you.name} arrived in {M.CITIES[city].name}.")
    return you.id
