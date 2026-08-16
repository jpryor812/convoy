"""Turning the world into what an agent sees.

THE SPLIT THAT MATTERS

Everything an agent could be told falls into one of two buckets, and the
distinction is not "important vs unimportant" -- it is "does this ever change?"

  STATIC   the map, every NPC price, every recipe, how hunger works, what each
           business does. Identical for all 75 agents for all 120 hours.
           -> `static_briefing()`, sent once as a cached system prompt.

  DYNAMIC  where you are, what you're carrying, who is standing next to you,
           what just happened to you.
           -> `observe()`, rebuilt per decision.

Measured on a live 30-hour world: the whole road map is ~439 tokens and every
NPC price is ~631 tokens. Both are constants. Rationing them would have saved
nothing and left agents unable to know Iron outsells Grain without walking to a
refinery -- so early play would have been noise, and the five-model comparison
would have partly measured who got lucky exploring. Static economic facts are
common knowledge here; only world STATE is local.

Tax rates are deliberately dynamic: policy can move them mid-run, so the
briefing explains the mechanism and the observation carries the current number.
"""

from __future__ import annotations

from typing import Any

from . import data as D
from . import economy as E
from . import world_map as M
from .events import EventLog, Significance
from .state import Agent, World

# Public knowledge decays: a death two hours ago is still news, a sale is not.
WORLD_NEWS_WINDOW_HOURS = 1.0
DEFAULT_MEMORY_LIMIT = 15
DEFAULT_CHAT_LIMIT = 8

# Diaries are self-narration, not events. They fill leftover space only.
_MAX_DIARY_LINES = 4

# Engine bookkeeping an inhabitant would never experience.
_ENGINE_BOOKKEEPING = frozenset({"sim_start", "sim_end", "decision"})

# A crowded junction can hold every agent in the world. Past a point the list
# stops being information and starts being filler, so it is capped and counted.
HERE_LIMIT = 12


# ---------------------------------------------------------------------------
# STATIC -- written once, cached, identical for every agent
# ---------------------------------------------------------------------------

def _money(x: float) -> str:
    return f"{x:g}"


def _static_map() -> str:
    lines = ["THE WORLD", ""]
    lines.append(
        "One road runs north to south. Production sits at the north end, the "
        "only market at the south end, so goods must cross the dangerous middle "
        "to reach a buyer. Protected ground means no combat and no theft."
    )
    lines.append("")
    for loc in M.LOCATIONS_SPEC:
        guard = "PROTECTED" if loc.protected else "unprotected"
        lines.append(f"  {loc.name} ({loc.kind}, {loc.elevation}m, {guard}) - {loc.blurb}")
    lines.append("")
    lines.append("Road segments, north to south (times at Medium speed):")
    # The concealment/vantage/exposure figures are DELIBERATELY omitted. They
    # are precise inputs to an ambush model that does not exist yet -- there is
    # no combat or theft code in the engine -- so quoting them to agents spent
    # ~120 cached tokens inviting them to plan around a risk that cannot occur.
    # The blurbs keep the character of each stretch. Restore the numbers in the
    # same change that lands combat.
    for seg in M.SEGMENTS:
        flee = "" if seg.can_flee_offroad() else " No escape off-road."
        lines.append(
            f"  {seg.name} ({seg.a} <-> {seg.b}): {seg.seconds:.0f}s, "
            f"{seg.terrain}.{flee} {seg.blurb}"
        )
    lines.append("")
    lines.append(
        f"Sixteen spur roads dead-end off the main road, {M.SPUR_SECONDS:.0f}s deep each. "
        f"Mines, farms and homes live on spurs and nowhere else. A spur holds "
        f"{M.PLOTS_PER_SPUR} plots: a home takes {M.HOME_BASE_PLOTS}, a mine or farm "
        f"takes {M.SITE_BASE_PLOTS}. Travelling spur-to-spur means climbing back to "
        f"the main road and down again."
    )
    for junction in M.LOCATIONS:
        spurs = M.SPURS_BY_JUNCTION.get(junction, [])
        if spurs:
            lines.append(f"  off {junction}: " + ", ".join(s.name for s in spurs))
    return "\n".join(lines)


def _static_economy() -> str:
    lines = ["", "PRICES", ""]
    lines.append(
        "NPC stores buy and sell at fixed rates that never move. Other players "
        "may price differently -- their prices appear in your observation when "
        "you are standing where they trade."
    )
    lines.append("")
    lines.append(f"  {'item':<24}{'NPC sells to you':>18}{'NPC buys from you':>19}")
    for item in D.ALL_ITEMS:
        lines.append(
            f"  {item:<24}{_money(round(E.npc_sell_price(item), 2)):>18}"
            f"{_money(round(E.npc_buy_price(item), 2)):>19}"
        )
    lines.append("")
    lines.append(
        f"Players cannot retail below {D.PLAYER_STORE_FLOOR_PCT:.0%} of base price."
    )

    lines.append("")
    lines.append("PRODUCTION CHAINS")
    lines.append("")
    lines.append("Extraction (per Novice worker per hour, before skill and crowding):")
    for name in D.RAW_RESOURCES:
        r = D.RESOURCES[name]
        lines.append(f"  {name:<16} {r.base_rate_hr:>4.0f}/hr at a {r.source} ({r.rarity})")
    lines.append("")
    # Time per unit now scales with value, so it is no longer one number an
    # agent can assume -- a Meal is 15 minutes and an Iron Sword is 12 hours.
    lines.append(
        "Refining and crafting (inputs -> output, and worker-hours per unit -- "
        "the more valuable the good, the longer it takes):"
    )
    for recipe in list(D.REFINING_RECIPES.values()) + list(D.CRAFTING_RECIPES.values()):
        ins = " + ".join(f"{q}x {i}" for i, q in recipe.inputs.items())
        hrs = D.production_hours(recipe.output)
        lines.append(
            f"  {ins} -> {recipe.output} ({hrs:.2f}h, at a {recipe.produced_at})"
        )

    # Which roles a business type hires is static, and NOT telling agents was a
    # measured failure: 9 of 13 job applications in the 2026-08-14 harness runs
    # were rejected for inventing a role ("Laborer is not a role at General
    # Store"). apply_for_job takes an exact role string, so a guess is a wasted
    # decision -- and a wasted API call.
    # Where the state's businesses stand never changes, so withholding it only
    # made agents rediscover the map by walking. That contradicts this module's
    # own rule -- static economic facts are common knowledge -- and it is why
    # agents kept trying to eat in Town, where there is no tavern.
    # Location and roles in ONE table: both key on business type, and listing
    # the eleven type names twice cost ~120 tokens of the cached prefix for no
    # extra information.
    # Rules the agent cannot deduce and will otherwise discover only by being
    # refused. Every previous run wasted decisions this way -- eating in a Town
    # with no tavern, applying for roles a business does not hire.
    lines.append("")
    lines.append(
        "WHAT PEOPLE BUY. Shops sell FINISHED goods: meals, weapons, armour, "
        "tools, vehicles, upgrades. Feedstock -- ore, wheat, hide, metal -- is "
        "never sold to a person. It moves business to business, one way:"
    )
    lines.append("  farm or mine  ->  refinery  ->  shop  ->  you")
    lines.append("")
    lines.append(
        "ORDERING STOCK. order_from_business buys for a business you own, without "
        "travelling. It pays from its OWN cash, so deposit first. The goods leave "
        "the seller at once and wait at their gate for someone to HAUL them. The "
        "carriage fee you set is held aside, so whoever delivers is always paid. "
        "If nobody takes the job the goods never arrive -- your loss, not the "
        "seller's."
    )
    lines.append("")
    lines.append(
        "HAULING. Open carriage jobs and their pay appear in your observation. "
        "Claim one, collect at the pickup, deliver at the destination. A load "
        "moves whole, so your vehicle decides which jobs you can take -- on foot "
        f"it is {D.ON_FOOT_CAPACITY} units. Honest money with no capital, and the "
        "only way goods cross the valley."
    )
    lines.append("")
    lines.append(
        "SHOPS NEED SOMEBODY IN THEM. A player business only sells while its "
        "owner or an employee stands at it. Government shops are always staffed."
    )

    lines.append("")
    lines.append(
        f"BUSINESSES. No experience is needed for anything: any role, and "
        f"founding any business, is open from hour one. Omit the role when you "
        f"apply to get whatever that place hires. Government businesses sit at "
        f"the sites below, always buy what you bring and sell at the prices "
        f"above -- but hire at most {D.GOVERNMENT_MAX_EMPLOYEES} each: a "
        f"backstop, not a career. One YOU found may hire as many as you can pay. "
        f"Other players' businesses are not listed; find those by trading there."
    )
    lines.append(f"  {'type':<32}{'government site':<22}hires")
    for name, spec in sorted(D.BUSINESS_TYPES.items()):
        place = M.GOVERNMENT_SITES.get(name, "-")
        roles = ", ".join(spec.production_roles) if spec.production_roles else "nobody"
        tail = " + Researcher" if spec.can_research else ""
        lines.append(f"  {name:<32}{place:<22}{roles}{tail}")

    # Roles pay very differently -- Refinery Worker is 2.1x Store Clerk -- and
    # agents were choosing blind. In the 2026-08-14 runs everyone took the
    # lowest-paid role in the world (Store Clerk, 17.78) because it happened to
    # be where they spawned; the one agent who took Miner finished with more
    # than double everyone else's net worth. That is a wage table doing the work
    # of a strategy, so the table belongs in front of them.
    lines.append("")
    lines.append(
        "WAGES per hour. The state pays a narrow band. A player employer may set "
        "any wage at or above the floor, so outbidding the state for staff is "
        "open to you:"
    )
    lines.append(f"  {'role':<18}{'state':>8}{'floor':>8}")
    for role in D.WAGE_ROLES:
        lines.append(
            f"  {role:<18}{D.GOVERNMENT_WAGES[role]:>8.2f}{D.WAGE_FLOORS[role]:>8.2f}"
        )
    lines.append("")
    lines.append(
        "SKILL is tracked SEPARATELY FOR EACH ROLE and only ever speeds you up: "
        + ", ".join(
            f"{label} at {hours:.0f}h (+{bonus:.0%})"
            for hours, bonus, label in D.SKILL_TIERS
        )
        + ". Changing role starts the new role at Novice -- the hours you built "
        "up elsewhere keep their own tier and are waiting if you go back."
    )
    return "\n".join(lines)


def _static_rules() -> str:
    lines = ["", "HOW THINGS WORK", ""]
    lines.append(
        f"SUSTENANCE. Food is sold at TAVERNS only -- you cannot cook. The "
        f"state's Tavern ({M.GOVERNMENT_SITES['Tavern / Inn']}) charges "
        f"{E.npc_sell_price('Meal'):.2f} for a Meal: Normal for "
        f"{D.MEALS['Meal'].window_hours:.0f}h. A player Tavern may charge as "
        f"little as {E.player_price_floor('Meal'):.2f} and can research Quality "
        f"for meals that last longer, heal, or speed your work. "
        f"After the window you go Hungry ({D.HUNGRY_SPEED_PENALTY:.0%} slower) for "
        f"{D.HUNGRY_STAGE_HOURS:.0f}h, then Starving ({D.STARVING_SPEED_PENALTY:.0%} slower, "
        f"-{D.STARVING_HP_HIT:.0f} HP) for {D.STARVING_STAGE_HOURS:.0f}h, then you die. "
        f"You cannot accumulate wealth while dead. Eat before it is urgent -- being "
        f"cash-poor while holding unsold stock has killed agents who were, on paper, rich."
    )
    lines.append("")
    lines.append(
        f"WORK. Each extra worker at a business cuts EVERY worker's individual rate "
        f"by {1 - D.WORKER_DECAY_PER_HEAD:.0%}, compounding. Total output still rises to "
        f"about {E.per_worker_multiplier(19) * 19:.2f}x at 19-20 workers and then falls. "
        f"The headcount that maximises PROFIT is well below the one that maximises "
        f"output, because every worker draws a wage. Skill grows with hours worked."
    )
    lines.append("")
    lines.append(
        "OWNERSHIP. A business owner takes no wage -- owners earn the business's "
        "profit. Government businesses are always staffed, never research, and set a "
        "price floor you must beat on price or on distance."
    )
    lines.append("")
    lines.append(
        f"RESEARCH. Only player-owned businesses can research. Researchers generate "
        f"{D.RP_PER_RESEARCHER_HOUR:.0f} RP/hour and burn materials. Tiers cost "
        + ", ".join(f"{t.cumulative_rp:.0f} RP (+{t.efficiency:.0%})" for t in D.RESEARCH_TIERS)
        + " cumulative."
    )
    lines.append("")
    lines.append(
        f"HAULING. On foot you carry {D.ON_FOOT_CAPACITY} units. Vehicles carry far more "
        f"and move faster, and capacity is usually what limits earnings rather than "
        f"production: "
        + "; ".join(
            f"{v.name} {_money(v.base_price)}d, {v.cargo_capacity} units, {v.speed_label}"
            for v in D.VEHICLES.values()
            if v.name != "On Foot"
        )
        + "."
    )
    lines.append("")
    lines.append(
        f"CRIME. Stolen goods are held separately from your inventory and cannot be "
        f"sold or traded until they have sat in a safehouse for "
        f"{D.SAFEHOUSE_CURE_HOURS:.0f} hours. Killing and theft raise a bounty on you. "
        f"Neither is possible on protected ground."
    )
    lines.append("")
    lines.append(
        f"TAXES. Four of them. Sales tax is paid by the buyer on top of the price. "
        f"Income tax is withheld from every wage payment. Property tax is billed every "
        f"{D.PROPERTY_TAX_PERIOD_HOURS:.0f}h on assessed property value. Road tax is "
        f"billed every {D.ROAD_TAX_PERIOD_HOURS:.0f}h on your whole Net Worth and funds "
        f"roads and police. Current rates are in your observation -- policy can move them."
    )
    lines.append("")
    lines.append(
        "DEATH. Whatever you were carrying drops where you fell and anyone may take "
        "it. Without insurance, everything you were not carrying is wiped."
    )
    return "\n".join(lines)


def static_briefing() -> str:
    """Everything that never changes, for the cached system prompt.

    Pure function: no world, no agent, no clock. Byte-identical across all 75
    agents and all 120 hours, which is what makes it cacheable.
    """
    header = (
        "You are a person living in Convoy, a Bronze Age valley economy. Your one "
        "goal is to maximise your own Net Worth (denari + businesses + vehicles + "
        "property + inventory) by the end. You compete and cooperate with other "
        "real agents. Nothing below ever changes; your current situation arrives "
        "separately with each decision.\n\n"
        # Four smoke runs produced no business at all, by agents who could afford
        # one and were told so. Spending 200 denari on a tavern LOOKS like losing
        # 200 of net worth unless you know how a business is valued -- so say it.
        "FOUNDING A BUSINESS DOES NOT COST YOU NET WORTH. A business you own "
        f"counts as what you paid for it PLUS {D.BUSINESS_REVENUE_MULTIPLE:.0f}x "
        "its last 24 hours of sales. So founding one is worth the same to you as "
        "the denari you spent, and every sale after that adds to it. A wage is "
        "safe and small; the money is in owning the thing that pays the wage."
    )
    return "\n".join([header, "", _static_map(), _static_economy(), _static_rules()])


# ---------------------------------------------------------------------------
# MEMORY -- what this agent should remember happening
# ---------------------------------------------------------------------------

def memory_for(
    log: EventLog, agent: Agent, now: float, limit: int = DEFAULT_MEMORY_LIMIT
) -> list[str]:
    """This agent's recent past, most recent last.

    Without this an agent wakes with total amnesia every 15 simulated minutes and
    re-derives its plan from scratch several hundred times -- which reads as
    erratic reasoning but is really a missing observation.

    Two things qualify: anything notable that happened TO you, and any HIGH
    event anywhere in the last hour (a death, a heist, a passed policy -- public
    news everyone would hear about).

    Walks the log backwards and stops early, so cost is proportional to `limit`
    rather than to the ~160k events a full 120-hour run produces.
    """
    news_cutoff = now - WORLD_NEWS_WINDOW_HOURS * 3600.0
    events: list = []
    diaries: list = []

    for ev in reversed(log.events):
        if len(events) >= limit:
            break
        if ev.type in _ENGINE_BOOKKEEPING:
            continue
        mine = ev.actor == agent.id or ev.subject == agent.id
        if mine and ev.type == "diary":
            # An idle agent writes the same diary line every hour. Keeping all of
            # them would evict the real events -- so diaries are a fallback that
            # only fills space the actual history leaves over.
            if len(diaries) < _MAX_DIARY_LINES:
                diaries.append(ev)
        elif mine and ev.significance >= Significance.MEDIUM:
            events.append(ev)
        elif ev.significance >= Significance.HIGH and ev.sim_time >= news_cutoff:
            events.append(ev)

    room = max(limit - len(events), 0)
    picked = sorted(events + diaries[:room], key=lambda e: e.sim_time)
    return _collapse_repeats([e.format() for e in picked])


def _collapse_repeats(lines: list[str]) -> list[str]:
    """Fold runs of an identical line into one, tagged with the count.

    "working as Farmhand" ten hours running is one fact, not ten.
    """
    runs: list[list] = []   # [body, count, most-recent-formatted-line]
    for line in lines:
        body = line.split("] ", 1)[-1]
        if runs and runs[-1][0] == body:
            runs[-1][1] += 1
            runs[-1][2] = line          # lines arrive oldest first; keep the latest
        else:
            runs.append([body, 1, line])
    return [text if n == 1 else f"{text}  (x{n}, latest shown)" for _b, n, text in runs]


# ---------------------------------------------------------------------------
# AFFORDANCES -- what is actually possible from where you stand
# ---------------------------------------------------------------------------

def affordances(world: World, agent: Agent) -> list[str]:
    """Concrete openings available right now.

    The full action catalogue is static and lives in the system prompt. This is
    the short dynamic list of what would actually succeed from here, so agents
    stop spending decisions on calls the rules reject.
    """
    out: list[str] = []

    if agent.in_transit:
        origin, dest, progress = agent.in_transit
        remaining = max(agent.activity.ends_at - world.sim_time, 0.0)
        out.append(
            f"You are on the road {origin} -> {dest}, {progress:.0%} of the way, "
            f"~{remaining:.0f}s out. You cannot trade or work until you arrive."
        )
        return out

    # Businesses are already named with IDs under `here` -- summarise the
    # openings rather than reprinting the list, which at a crowded junction
    # doubled the payload for nothing.
    here = [
        b for b in world.businesses.values()
        if b.location == agent.location and not b.closed
    ]
    if here:
        hiring = sum(1 for b in here if b.spec.needs_worker and not b.is_government)
        out.append(
            f"{len(here)} business(es) here to buy from or sell to (listed above)"
            + (f"; {hiring} player-owned and may hire." if hiring else ".")
        )

    if M.is_spur(agent.location):
        free = M.plots_free(world, agent.location)
        out.append(
            f"This is spur land: {free} of {M.PLOTS_PER_SPUR} plots free. You can "
            f"found a mine or farm ({M.SITE_BASE_PLOTS} plots) or buy a home "
            f"({M.HOME_BASE_PLOTS} plots) here."
        )
    else:
        # Saying only what CANNOT be built here reads as "you cannot build here",
        # and agents behaved accordingly: in the 2026-08-15 smoke, three agents
        # sat on 225-285 denari -- enough to found four of the five types that
        # belong on this ground -- and never tried. Name what IS possible, and
        # what it costs, since affording it is the whole question.
        affordable = sorted(
            (spec.startup_cost, name)
            for name, spec in D.BUSINESS_TYPES.items()
            if name not in M.PLOT_CONSUMING_BUSINESSES
            and spec.startup_cost <= agent.denari
        )
        if affordable:
            out.append(
                "Main road: mines and farms need spur land, but you could found "
                + ", ".join(f"a {n} ({c:.0f})" for c, n in affordable[:5])
                + " right here."
            )
        else:
            cheapest = min(
                (spec.startup_cost, name)
                for name, spec in D.BUSINESS_TYPES.items()
                if name not in M.PLOT_CONSUMING_BUSINESSES
            )
            out.append(
                f"Main road: mines and farms need spur land. The cheapest business "
                f"you could found here is a {cheapest[1]} at {cheapest[0]:.0f} "
                f"and you have {agent.denari:.0f}."
            )

    if not M.is_protected(agent.location):
        out.append("Unprotected ground: you can be attacked and robbed here.")

    if agent.stolen:
        ready = [
            f"{s.qty}x {s.item}"
            for prop in world.properties.values()
            if prop.owner == agent.id
            for s in prop.safehouse
            if s.is_clean(world.sim_time)
        ]
        out.append(
            "Carrying stolen goods ("
            + ", ".join(f"{q}x {i}" for i, q in agent.stolen.items())
            + "); unsellable until stashed in a safehouse for "
            f"{D.SAFEHOUSE_CURE_HOURS:.0f}h."
        )
        if ready:
            out.append("Cured and sellable in your safehouse: " + ", ".join(ready))

    prop = world.properties.get(agent.owned_property) if agent.owned_property else None
    if prop and prop.location == agent.location:
        out.append(
            f"Your home is here: {sum(prop.stored.values())}/{prop.storage_capacity()} "
            f"units stored, {prop.garage_slots()} garage slots."
        )

    offers = [
        o for o in getattr(world, "trade_offers", {}).values()
        if getattr(o, "location", agent.location) == agent.location
        and getattr(o, "seller", None) != agent.id
    ]
    if offers:
        out.append(f"{len(offers)} open player trade offer(s) here.")

    if agent.sustenance_stage != "Normal":
        out.append(
            f"You are {agent.sustenance_stage} "
            f"({agent.hours_since_last_meal:.1f}h since eating). Eat."
        )

    free_capacity = agent.carry_capacity(world) - agent.carried_units()
    out.append(f"Carrying {agent.carried_units()}/{agent.carry_capacity(world)} units.")
    if free_capacity <= 0:
        out.append("You are full: you cannot pick up anything else until you sell or unload.")

    return out


# ---------------------------------------------------------------------------
# DYNAMIC -- rebuilt per decision
# ---------------------------------------------------------------------------

def _local_prices(world: World, agent: Agent) -> dict[str, dict[str, float]]:
    """Only prices that DIFFER from the static NPC table.

    NPC rates are already common knowledge from the briefing, so repeating them
    every call would be ~631 wasted tokens. Player storefronts are the news.
    """
    out: dict[str, dict[str, float]] = {}
    for b in world.businesses.values():
        if b.location != agent.location or b.closed or b.is_government:
            continue
        deviating = {
            item: round(b.price_for(item), 2)
            for item in b.retail_prices
            if abs(b.price_for(item) - E.npc_sell_price(item)) > 0.01
        }
        if deviating:
            out[f"{b.name} ({b.id})"] = deviating
    return out


def observe(
    world: World,
    log: EventLog,
    agent: Agent,
    reason: str,
    *,
    memory_limit: int = DEFAULT_MEMORY_LIMIT,
    chat_limit: int = DEFAULT_CHAT_LIMIT,
) -> dict[str, Any]:
    """What this agent knows, right now.

    `reason` is why the engine woke this agent, and it leads the payload -- an
    ambush and a routine checkpoint should not produce the same prompt.
    """
    from . import actions as A   # circular: actions imports state, we import both

    gov = world.government

    you: dict[str, Any] = {
        "id": agent.id,
        "name": agent.name,
        "denari": round(agent.denari, 2),
        "net_worth": round(agent.net_worth(world), 2),
        "location": agent.location,
        "health": round(agent.health, 1),
        "hunger": f"{agent.sustenance_stage}, {agent.hours_since_last_meal:.1f}h since eating",
        "doing": agent.activity.kind,
        "carrying": dict(agent.inventory),
        "capacity": agent.carry_capacity(world),
        "vehicle": (
            world.vehicles[agent.mounted_vehicle].type if agent.mounted_vehicle else "On Foot"
        ),
        "weapon": agent.equipped_weapon,
    }
    # Vehicles an agent OWNS, with their ids. Without this the id exists only
    # inside the engine: `mount` needs one, the schema tells the model never to
    # invent an id, and nothing in the observation ever supplied one. Every
    # mount attempt in the 2026-08-15 run failed with "not your vehicle" -- 15
    # vehicles and 4,174 denari, 58% of the economy's capital, unusable.
    if agent.owned_vehicles:
        you["your_vehicles"] = [
            {
                "id": vid,
                "type": v.type,
                "location": v.location,
                "cargo_capacity": D.VEHICLES[v.type].cargo_capacity,
                "carrying": dict(v.cargo),
                "mounted": vid == agent.mounted_vehicle,
                "condition": v.condition,
            }
            for vid in agent.owned_vehicles
            if (v := world.vehicles.get(vid)) is not None
        ]

    if agent.stolen:
        you["stolen_uncured"] = dict(agent.stolen)
    if agent.current_job:
        biz_id, role, wage = agent.current_job
        biz = world.businesses.get(biz_id)
        you["job"] = {
            "business": f"{biz.name} ({biz_id})" if biz else biz_id,
            "role": role,
            "wage_per_hour": round(wage, 2),
        }
    if agent.owned_businesses:
        you["businesses"] = [
            {
                "id": bid,
                "name": world.businesses[bid].name,
                "type": world.businesses[bid].type,
                "location": world.businesses[bid].location,
                "cash": round(world.businesses[bid].cash, 2),
                "stock": dict(world.businesses[bid].inventory),
                "workers": len(world.businesses[bid].production_staff()),
                "researchers": len(world.businesses[bid].researchers()),
                "research_tier": world.businesses[bid].research.efficiency_tier,
                "unspent_rp": round(world.businesses[bid].research.unspent_rp, 1),
            }
            for bid in agent.owned_businesses
        ]
    if agent.owned_property:
        prop = world.properties[agent.owned_property]
        you["home"] = {
            "id": prop.id,
            "location": prop.location,
            "stored": dict(prop.stored),
            "storage_capacity": prop.storage_capacity(),
        }
    if agent.guild:
        guild = world.guilds.get(agent.guild)
        if guild:
            you["guild"] = {
                "name": guild.name,
                "members": len(guild.members),
                "leader": agent.is_guild_leader,
            }
    if agent.bounty_total:
        you["bounty_on_you"] = round(agent.bounty_total, 2)

    all_here_agents = [
        x for x in world.agents.values()
        if x.location == agent.location and x.id != agent.id and x.alive
    ]
    all_here_businesses = [
        b for b in world.businesses.values()
        if b.location == agent.location and not b.closed
    ]
    here_agents = [{"id": x.id, "name": x.name} for x in all_here_agents[:HERE_LIMIT]]
    here_businesses = [
        {
            "id": b.id,
            "name": b.name,
            "type": b.type,
            "owner": "Government" if b.is_government else b.owner,
        }
        for b in all_here_businesses[:HERE_LIMIT]
    ]

    here: dict[str, Any] = {"agents": here_agents, "businesses": here_businesses}
    if len(all_here_agents) > HERE_LIMIT:
        here["more_agents"] = len(all_here_agents) - HERE_LIMIT
    if len(all_here_businesses) > HERE_LIMIT:
        here["more_businesses"] = len(all_here_businesses) - HERE_LIMIT

    obs: dict[str, Any] = {
        "woken_because": reason,
        "hour": round(world.sim_hour, 2),
        "you": you,
        "here": here,
        "you_can": affordances(world, agent),
        "taxes_now": {
            "sales": gov.sales_tax,
            "income": gov.wage_tax,
            "property_weekly": gov.property_tax,
            "road_daily": gov.road_tax,
            "police_tier": gov.police_tier,
            "active_policies": list(gov.active_policies),
        },
        "memory": memory_for(log, agent, world.sim_time, memory_limit),
        # An empty CHAT section is rendered as a standing invitation rather than
        # omitted. Rendering nothing until somebody speaks is a deadlock: no
        # agent talked in 1,331 decisions across two runs, and nothing in the
        # observation ever suggested talking was possible. Now that shops set
        # their own prices and wages, having somewhere to advertise them is the
        # difference between a market and a set of strangers.
        "chat": (
            [m.format() for m in A.visible_chat(world, agent, limit=chat_limit)]
            or ["(nobody has said anything yet -- world chat reaches every living "
                "agent, and is how prices, wages and carriage jobs get known)"]
        ),
    }

    local = _local_prices(world, agent)
    if local:
        obs["player_prices_here"] = local

    # Ordering is REMOTE, so an owner needs the id of a seller they are nowhere
    # near. Without this the whole B2B system is unusable: an agent can only see
    # ids for businesses at their own location, and order_from_business takes an
    # id it refuses to let them invent. Only shown to people who own something,
    # since only they can order.
    if agent.owned_businesses:
        obs["where_to_buy_stock"] = [
            {
                "id": b.id, "name": b.name, "type": b.type, "at": b.location,
                "sells": sorted(
                    i for i in (b.spec.outputs or ())
                    if b.is_government or b.inventory.get(i, 0) > 0
                )[:5],
            }
            for b in world.businesses.values()
            if not b.closed and b.spec.outputs and b.id not in agent.owned_businesses
            and any(D.is_intermediate(i) for i in b.spec.outputs)
        ]

    # Haulage nobody has taken. Without this an agent could never FIND work --
    # the same cold start that has kept every chat channel silent so far.
    jobs = A.open_courier_jobs(world, agent)
    if jobs:
        obs["courier_jobs"] = jobs

    # What the agent is carrying for someone else, and what their own
    # businesses are still waiting on.
    # A job the agent has TAKEN ON, claimed or loaded. Claiming used to make a
    # job invisible: it leaves the public board the moment it is spoken for, and
    # this block only filled once the goods were loaded -- so a courier held a
    # job it could not see, with no id, no pickup point and no fee. In the
    # 2026-08-15 smoke an agent claimed two jobs and walked to the far end of
    # the valley.
    job = world.consignments.get(agent.hauling) if agent.hauling else next(
        (c for c in world.consignments.values()
         if c.courier == agent.id and c.status == "claimed"),
        None,
    )
    if job is not None:
        loaded = agent.hauling == job.id
        obs["you"]["your_haulage_job"] = {
            "id": job.id, "item": job.item, "qty": job.qty,
            "pays": round(job.courier_fee, 2),
            "next": (
                f"deliver at {job.destination}" if loaded
                else f"collect at {job.origin}, then deliver at {job.destination}"
            ),
            "loaded": loaded,
        }
    mine = [
        {
            "id": c.id, "item": c.item, "qty": c.qty, "status": c.status,
            "waiting_at": c.origin, "for": c.destination,
            "fee_offered": round(c.courier_fee, 2),
        }
        for c in world.consignments.values()
        if c.status in ("awaiting_courier", "claimed")
        and c.buyer_business in agent.owned_businesses
    ]
    if mine:
        obs["your_orders_in_transit"] = mine

    return obs


# ---------------------------------------------------------------------------
# RENDERING
# ---------------------------------------------------------------------------

def _render_value(value: Any, indent: int = 0) -> list[str]:
    pad = "  " * indent
    if isinstance(value, dict):
        lines = []
        for k, v in value.items():
            if isinstance(v, (dict, list)) and v:
                lines.append(f"{pad}{k}:")
                lines.extend(_render_value(v, indent + 1))
            elif isinstance(v, (dict, list)):
                continue
            else:
                lines.append(f"{pad}{k}: {v}")
        return lines
    if isinstance(value, list):
        lines = []
        for item in value:
            if isinstance(item, dict):
                flat = ", ".join(
                    f"{k}={v}" for k, v in item.items() if not isinstance(v, (dict, list))
                )
                nested = {k: v for k, v in item.items() if isinstance(v, (dict, list)) and v}
                lines.append(f"{pad}- {flat}")
                for k, v in nested.items():
                    # Flatten rather than falling back to a Python repr -- this
                    # text goes straight into the prompt.
                    inner = (
                        ", ".join(f"{ik}={iv}" for ik, iv in v.items())
                        if isinstance(v, dict)
                        else ", ".join(str(x) for x in v)
                    )
                    lines.append(f"{pad}  {k}: {inner}")
            else:
                lines.append(f"{pad}- {item}")
        return lines
    return [f"{pad}{value}"]


def render(obs: dict[str, Any]) -> str:
    """Flatten an observation into the user-turn text for a model call."""
    lines = [
        f"HOUR {obs['hour']}. You were woken because: {obs['woken_because']}.",
        "",
    ]
    for key, heading in [
        ("you", "YOU"),
        ("here", "WHERE YOU ARE"),
        ("player_prices_here", "PLAYER PRICES HERE"),
        ("you_can", "WHAT YOU CAN DO FROM HERE"),
        ("taxes_now", "CURRENT TAX RATES"),
        ("where_to_buy_stock", "WHERE TO ORDER FEEDSTOCK (you need not travel)"),
        ("courier_jobs", "HAULAGE JOBS GOING BEGGING"),
        ("your_orders_in_transit", "YOUR ORDERS NOT YET DELIVERED"),
        ("memory", "RECENTLY"),
        ("chat", "CHAT"),
    ]:
        value = obs.get(key)
        if not value:
            continue
        lines.append(heading)
        lines.extend(_render_value(value, 1))
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"
