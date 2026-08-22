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

from . import banditry as B
from . import data as D
from . import economy as E
from . import world_map as M
from .events import EventLog, Significance
from .state import Agent, World

# Public knowledge decays: a death two hours ago is still news, a sale is not.
WORLD_NEWS_WINDOW_HOURS = 1.0
DEFAULT_MEMORY_LIMIT = 15

# Your last few decisions in your own words. Small on purpose: this is for
# continuity of plan ("I was three steps into stocking the refinery"), not a
# full history -- that lives in the event log.
DEFAULT_THINKING_LIMIT = 5
THINKING_CHARS_IN_PROMPT = 220
# Where the job board hangs. Town, because every agent spawns there -- so the
# whole population reads it at hour zero without spending a step to reach it.
JOB_CENTRE_LOCATION = "Town"
DEFAULT_CHAT_LIMIT = 8

# Diaries are self-narration, not events. They fill leftover space only.
_MAX_DIARY_LINES = 4

# Engine bookkeeping an inhabitant would never experience.
#
# The three advice events are here for a reason worth keeping. Advice reaches an
# agent through the ADVICE block, which expires it on schedule; the log entries
# recording that delivery do not expire, so leaving them in scope put hour-10
# advice back in the prompt at hour 17 as a raw event dump, reading as current
# long after it had lapsed -- expiry defeated by the mechanism that records it.
# They also spend the memory budget, which is 15 lines and is the reason
# reasoning was kept out of `memory_for` in the first place (PHASE4 §9): an
# advisor could otherwise evict the news that a rival opened a refinery next
# door simply by talking. The events are for the TRANSCRIPT, not the agent.
_ENGINE_BOOKKEEPING = frozenset({
    "sim_start", "sim_end", "decision",
    "advice_given", "advice_delivered", "advice_outcome",
})

# Advice from outside the sim. No limit worth having is smaller than this: an
# agent is meant to be able to hold every live recommendation at once, and
# `Agent.live_advice` has already dropped the expired ones.
DEFAULT_ADVICE_LIMIT = 6

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
    # The raw concealment/vantage/exposure triple is still NOT quoted, even now
    # that banditry exists. The reason changed: agents get a computed CONVOY
    # RISK percentage for the actual journey they are considering, which is the
    # number to act on. Three raw floats invite an agent to do that arithmetic
    # itself and get it wrong. One headline `danger` per segment is enough to
    # rank the roads before a load exists to price.
    for seg in M.SEGMENTS:
        flee = "" if seg.can_flee_offroad() else " No escape off-road."
        lines.append(
            f"  {seg.name} ({seg.a} <-> {seg.b}): {seg.seconds:.0f}s, "
            f"{seg.terrain}, danger {seg.danger:.2f}.{flee} {seg.blurb}"
        )
    lines.append("")
    # COUNTED, NOT WRITTEN DOWN. This said "Sixteen spur roads" long after the
    # map was cut to four -- the briefing telling every agent, on every call, a
    # fact about the world that had not been true for two recuts. PHASE4 §2 is
    # usually the observation withholding something; this is the same failure
    # with the sign flipped.
    lines.append(
        f"{len(M.SPURS)} spur roads dead-end off the main road, "
        f"{M.SPUR_SECONDS:.0f}s deep each. Mines, farms and homes live on spurs "
        f"and nowhere else. Travelling spur-to-spur means climbing back to the "
        f"main road and down again."
    )
    lines.append("")
    # ASKING THEM TO EXPLAIN, which nothing ever did. Reasoning has been captured
    # since PHASE4 §9, but what is captured is the model's THINKING -- a stream
    # of thought that wanders, and often lands somewhere other than the actions
    # it emitted on the same turn. Measured on the 2026-08-21 run: A0056 bought a
    # 600-denari cart at h23.27 while its recorded prose was about which courier
    # job id to take, so asked later why it bought the cart it could only answer,
    # correctly, that it had not said. A record of thinking is not a record of
    # reasons, and the interrogator can only quote what is there.
    lines.append(
        "SAY WHY. Everything you think before you act is recorded, and people "
        "will ask you about it later by name and hour. State briefly why you "
        "take EACH action -- above all a purchase, a business, a job, or a "
        "journey you could have refused. A decision you did not explain is one "
        "you can only answer for with 'I did not note why'."
    )
    lines.append("")
    lines.append(
        f"MARKET PRICES. Your observation carries what goods have ACTUALLY sold "
        f"for over the last {E.TICKER_WINDOW_HOURS:.0f} hours -- a "
        f"volume-weighted average against the book price, anonymous. Use it to "
        f"price your own goods and judge an offer in front of you."
    )
    lines.append("")
    lines.append(
        f"BANDITS. Cargo on the open road can be robbed. Nobody is hurt, but if "
        f"they catch you they take between HALF the load and ALL of it. "
        f"ON FOOT IS THE MOST DANGEROUS WAY TO CARRY ANYTHING: slowest, so "
        f"exposed longest, and too slow to escape. Splitting a load into many "
        f"small walks is many rolls, not safety. "
        f"Everything you carry counts, a hauled consignment included. Three things "
        f"drive the odds: "
        f"how much the load is worth, how well guarded it is, and how far it "
        f"goes -- a cheap load draws little attention, but value is noticed "
        f"however small. hire_escort buys Bodyguards (who make bandits "
        f"reconsider) and Scouts (who make you harder to find); better kit "
        f"deters more. AN NPC COSTS HALF AGAIN WHAT AN AGENT DOES: "
        f"post_escort_job is cheaper if you can wait, and taking escort work is "
        f"paid passage to wherever the convoy goes. No convoy is ever "
        f"completely safe. WHO PAYS FOR A CONVOY IS NEGOTIABLE between two "
        f"agents: a deal names a seller/buyer split of "
        + "/".join(f"{r*100:.0f}" for r in D.CONVOY_SPLITS[:1])
        + f"/0, 75/25, 60/40, 50/50 and so on, covering BOTH the courier fee "
        f"and anything bandits take. Whoever has somewhere else to trade can "
        f"push more of it onto the other. A GOVERNMENT business never carries "
        f"any share at all -- sell to the state and the whole convoy is yours "
        f"to pay for, which is the reason to found a refinery or a store of "
        f"your own and offer somebody a better split. When you buy from or "
        f"sell to another business, the split is part of the deal."
    )
    lines.append("")
    # LAND, stated once, in the cached prefix. The rules below decide who can
    # hire and how big anything gets, and repeating them per-tool would cost the
    # same tokens on every call for every agent forever.
    lines.append(
        f"LAND. Plots are finite everywhere and can sell out; Town is scarcest. "
        f"Unsold land is {D.LAND_BASE_PRICE:.0f}/plot (buy_land), else buy from a "
        f"holder (buy_listed_land) or sell your own (list_land).\n"
        f"A BUSINESS SEATS ONE EMPLOYEE PER DEVELOPED PLOT beyond its "
        f"{D.STRUCTURE_PLOTS}-plot building, which you work unpaid. Founding gives "
        f"{D.SITE_BASE_PLOTS} plots = 2 hires; for a third, buy_land then "
        f"develop_plot.\n"
        f"Stock: a store holds {D.STORE_STORAGE_PER_PLOT}/plot -- its land is shelf "
        f"space. A mine/farm/refinery holds as much as it cost to found (a Farm "
        f"{D.BUSINESS_TYPES['Farm'].startup_cost:.0f}, a Refinery "
        f"{D.BUSINESS_TYPES['Refinery'].startup_cost:.0f}) and grows upward "
        f"(upgrade_site_storage), keeping its land for people. A FULL YARD STOPS "
        f"PRODUCTION DEAD -- move stock out before it fills."
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
    lines.append(
        "  and ONLY that way: a shop buys refined goods from a Refinery and "
        "cannot buy raw from a farm or mine. A Refinery buys raw from farms and "
        "mines, plus Charcoal from another Refinery. State businesses always hold "
        "every good at their listed price, so supply never stops."
    )
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
        f"HIRING. post_job advertises a role and wage to everyone -- the only way "
        f"an agent learns you are hiring. Applicants appear in your observation; "
        f"take one with hire_applicant, or close_job and repost higher if nobody "
        f"bites. Adverts lapse after {D.JOB_POSTING_HOURS:.0f}h. An agent is "
        f"cheaper than an NPC but must be present and on shift -- and an agent "
        f"GETS BETTER, reaching +{E.skill_bonus(1e9):.0%} output with experience, "
        f"while an NPC is stuck at Novice forever. Answer others' adverts with "
        f"apply_to_job; you may apply to several."
    )
    lines.append("")
    lines.append(
        f"PAYROLL. Wages come out of the business's own cash, not your pocket, so "
        f"keep it funded with deposit. A business never goes into debt: if it "
        f"cannot pay someone THAT WORKER LEAVES, and it CLOSES in "
        f"{D.BANKRUPTCY_GRACE_HOURS:.0f}h unless you deposit the hour of payroll "
        f"it missed. NPC hires are paid only while the business is actually "
        f"producing, so an idle NPC is free -- but an agent you employ is paid for "
        f"every hour they work whether or not you have feedstock. Your observation "
        f"shows each business's cash and payroll."
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
        # WHAT YOU PAY, not the book value. This quoted `base_price` while the
        # PRICES table above quoted `npc_sell_price`, so the briefing carried two
        # vehicle tables that disagreed by the 1.5x Stables markup -- a Donkey
        # Cart at 400 here and 600 there. Agents anchored on THIS line, because
        # it is the one with the capacities they were shopping for, and budgeted
        # against a price that does not exist.
        #
        # Caught by an agent, not by a test: at h11.25 of the 2026-08-20 smoke
        # A0050 said "there's a discrepancy between my hauling options: one table
        # mentions 400, but I'm looking at a buy NPC for 600." PHASE4 §2 -- and
        # this one the observation really was guilty of.
        f"HAULING. On foot you carry {D.ON_FOOT_CAPACITY} units. Vehicles carry far more "
        f"and move faster, and capacity is usually what limits earnings rather than "
        f"production. Prices are what a Stable CHARGES you: "
        + "; ".join(
            f"{v.name} {_money(E.npc_sell_price(v.name))}d, {v.cargo_capacity} units, "
            f"{v.speed_label}"
            for v in D.VEHICLES.values()
            if v.name != "On Foot"
        )
        + ". A consignment moves WHOLE, so a load bigger than your capacity "
        "cannot be collected at all."
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
    # No "without insurance" caveat any more -- the whole line was cut on
    # 2026-08-20 and there is no cover to buy. A briefing that offers an escape
    # route the world does not have is PHASE4 §2 in its purest form: the agent
    # is told something false at the moment it decides.
    lines.append(
        "DEATH. Starvation is the only way to die. Whatever you were carrying "
        "drops where you fell and anyone may take it, and everything you were "
        "NOT carrying -- businesses, carts, your home -- is wiped. There is no "
        "insurance against it. Sell what you cannot defend before it gets that "
        "far; a business sold is worth something and a business wiped is not."
    )
    return "\n".join(lines)


def static_briefing() -> str:
    """Everything that never changes, for the cached system prompt.

    Pure function: no world, no agent, no clock. Byte-identical across all 75
    agents and all 120 hours, which is what makes it cacheable.
    """
    header = (
        "You are a person living in Convoy, a Bronze Age valley economy. Your goal "
        "is to maximise your own Net Worth (denari + businesses + vehicles + "
        "property + inventory) by the end, WITHOUT DYING. Starving kills you and "
        "wipes everything you own, so a dead agent scores nothing however rich it "
        "was an hour earlier -- staying alive is not a side condition, it is the "
        "first term. You compete and cooperate with other real agents. Nothing "
        "below ever changes; your current situation arrives separately with each "
        "decision.\n\n"
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


def thinking_for(agent: Agent, limit: int = DEFAULT_THINKING_LIMIT) -> list[str]:
    """This agent's own recent reasoning, most recent last.

    Deliberately NOT folded into `memory_for`. Memory has a fixed budget of
    lines, and reasoning is emitted on nearly every decision while the events
    worth remembering are rare -- mixing them would let an agent's own chatter
    evict the news that a rival opened a refinery next door. Twelve entries in
    the §2 table are an observation crowding out or omitting something the code
    knew; this keeps the two budgets separate so neither can starve the other.

    Trimmed harder here than in storage: the log keeps the full text for the
    transcript, the prompt gets the gist.
    """
    out = []
    for entry in agent.reasoning[-limit:]:
        said = entry.text[:THINKING_CHARS_IN_PROMPT]
        if len(entry.text) > THINKING_CHARS_IN_PROMPT:
            said += "..."
        did = ", ".join(entry.actions) if entry.actions else "nothing"
        out.append(f"[h{entry.hour:.1f}] you thought: {said or '(nothing)'} -- you did: {did}")
    return out


def advice_for(
    world: World,
    log: EventLog,
    agent: Agent,
    *,
    record_delivery: bool = True,
    limit: int = DEFAULT_ADVICE_LIMIT,
) -> list[str]:
    """Live recommendations for this agent, and the record that it saw them.

    THIS FUNCTION IS THE WHOLE FEATURE. Storing advice on the agent is
    bookkeeping; a channel exists only if the text reaches the model at the
    moment it decides. PHASE4 §2 is thirteen entries long and every one is a
    fact the code held and the prompt did not carry, so the failure to expect
    here is not "the agent disobeyed" but "the agent was never told".

    Delivery is therefore RECORDED HERE and nowhere else, at the one point in
    the codebase where the words go into a prompt. `times_seen` is evidence, not
    an estimate: if a student says their advice was ignored and `times_seen` is
    0, the advice never arrived and the agent is not the thing that is broken.

    `record_delivery=False` is for callers that build an observation without
    sending it -- a dry run, a test, a preview. Counting those as delivery would
    corrupt the only number that can settle the argument above.
    """
    live = agent.live_advice(world.sim_hour)[-limit:]
    if not live:
        return []

    lines = []
    for rec in live:
        lines.append(rec.format(world.sim_hour))
        if not record_delivery:
            continue
        first = rec.times_seen == 0
        rec.times_seen += 1
        if first:
            rec.first_seen_hour = round(world.sim_hour, 2)
            # MEDIUM: a student needs to find this without grepping past ten
            # thousand mining ticks.
            log.emit(
                world.sim_time, "advice_delivered", actor=agent.id,
                location=agent.location, significance=Significance.MEDIUM,
                advice_id=rec.id, from_who=rec.from_who, text=rec.text,
                given_at_hour=rec.given_at_hour,
            )
    return lines


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
        # WHICH government posts are actually open, not just the rule that they
        # cap at two. Agents knew the cap and still had to discover a full site
        # by walking to it and being refused: 543 "no vacancy (2/2 filled)"
        # rejections in the 2026-08-16 72-hour run, 36.8% of every action taken,
        # all of it in the first 16 simulated hours. The engine can answer this
        # before they travel.
        vacancies = []
        for b in here:
            if not (b.is_government and b.spec.needs_worker):
                continue
            cap = D.GOVERNMENT_MAX_EMPLOYEES
            taken = len(b.production_staff())
            if taken < cap:
                roles = "/".join(b.spec.production_roles) or "?"
                vacancies.append(f"{b.name} ({cap - taken} open: {roles})")
        gov_here = [b for b in here if b.is_government and b.spec.needs_worker]
        if gov_here:
            out.append(
                "State vacancies here: " + ("; ".join(vacancies) if vacancies
                else "NONE -- every state job at this location is filled, so "
                     "applying here will be refused. Try another location, or "
                     "a player business, or found your own.")
            )

    # THE JOB CENTRE. Every agent spawns in Town, so a board here is read by the
    # whole population at hour zero before anyone takes a step. State vacancies
    # used to be visible only at the site itself, which meant the only way to
    # find work was to walk the valley and be refused -- 543 refusals, 36.8% of
    # every action, in the 2026-08-16 72-hour run. One board, every opening,
    # best paid first, so the first journey an agent makes is TO a job rather
    # than in search of one.
    if agent.location == JOB_CENTRE_LOCATION and not agent.current_job:
        openings: list[tuple[float, str]] = []
        for b in world.businesses.values():
            if b.closed or not b.spec.needs_worker:
                continue
            if b.is_government:
                free = D.GOVERNMENT_MAX_EMPLOYEES - len(b.production_staff())
                if free <= 0:
                    continue
                for role in b.spec.production_roles:
                    wage = E.government_wage(role)
                    openings.append((wage, f"{role} at {b.name} ({b.location}) {wage:.2f}/hr"))
        for p in world.job_postings.values():
            if not p.is_live(world.sim_time) or p.owner == agent.id:
                continue
            b = world.businesses.get(p.business_id)
            risk = (" [WARNING: this employer has already missed payroll]"
                    if b is not None and b.insolvent_since is not None else "")
            openings.append((p.wage, (
                f"{p.role} at {b.name if b else '?'} ({b.location if b else '?'}) "
                f"{p.wage:.2f}/hr -- apply_to_job('{p.id}'){risk}"
            )))
        if openings:
            openings.sort(key=lambda x: -x[0])
            shown = "; ".join(text for _, text in openings[:10])
            out.append(
                f"JOB CENTRE ({JOB_CENTRE_LOCATION}) -- every position open in the "
                f"valley right now, best paid first: {shown}. Travel to one and "
                f"apply_for_job there, or apply_to_job for a player advert."
            )

    # Player job adverts, world-wide, and EVERYONE sees them -- not only the
    # unemployed. Gating this on `not agent.current_job` was a token
    # optimisation that quietly destroyed the labour market: by hour 44 of the
    # 2026-08-17 run all 20 agents held a job, so nobody could see a single
    # advert, nobody could ever move, and labour supply was permanently zero.
    # Refinery owners paid 56.67 for NPCs rather than advertise at 25 to an
    # audience of no one. An employed agent is shown only offers that BEAT what
    # they currently earn, so the list stays short and every line is a reason
    # to act.
    current_wage = agent.current_job[2] if agent.current_job else 0.0
    open_jobs = [
        p for p in world.job_postings.values()
        if p.is_live(world.sim_time) and p.owner != agent.id
        and p.wage > current_wage
    ]
    if open_jobs:
        open_jobs.sort(key=lambda p: -p.wage)
        lines = []
        for p in open_jobs[:6]:
            b = world.businesses.get(p.business_id)
            mark = " (already applied)" if agent.id in p.applicants else ""
            risk = (" [has missed payroll]"
                    if b is not None and b.insolvent_since is not None else "")
            raise_ = (f", a rise of {p.wage - current_wage:.2f}/hr"
                      if agent.current_job else "")
            lines.append(
                f"{p.id}: {p.role} at {b.name if b else '?'} "
                f"({b.location if b else '?'}) for {p.wage:.2f}/hr{raise_}{mark}{risk}"
            )
        headline = (
            f"JOBS PAYING MORE THAN YOUR {current_wage:.2f}/hr"
            if agent.current_job else "JOBS ON THE BOARD, best paid first"
        )
        out.append(
            f"{headline} -- apply_to_job(id) even while employed; you keep your "
            f"current job unless an owner takes you on: " + "; ".join(lines)
        )

    # LAND, wherever you are standing. Every location has a finite supply now,
    # and headcount is a property of land -- so an owner who cannot see the
    # ground market cannot grow, and would read a hiring refusal as the world
    # being arbitrary. PHASE4 §2, in advance, for a system built today.
    free = M.plots_free(world, agent.location)
    mine_here = [
        p for p in world.plots.values()
        if p.owner == agent.id and p.location == agent.location
    ]
    spare = [p for p in mine_here if not p.developed and p.business is None
             and not p.is_building(world.sim_time)]
    if free:
        out.append(
            f"LAND HERE: {free} of {M.plots_at(agent.location)} plots unsold at "
            f"{D.LAND_BASE_PRICE:.0f} each -- buy_land(plots=N). Raw land seats "
            f"nobody until develop_plot builds on it."
        )
    else:
        out.append(
            f"LAND HERE: every one of {M.plots_at(agent.location)} plots is owned. "
            f"To build here you must buy from a holder -- check land for sale."
        )
    if spare:
        out.append(
            f"You hold {len(spare)} undeveloped plot(s) here. develop_plot(business) "
            f"turns one into a place for one more employee."
        )

    if M.is_spur(agent.location):
        out.append(
            f"This is spur land: found a mine or farm ({M.SITE_BASE_PLOTS} plots, "
            f"included in the startup cost) or buy a home ({M.HOME_BASE_PLOTS} "
            f"plots) here."
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
        if affordable and free >= D.STORE_BASE_PLOTS:
            out.append(
                "Main road: mines and farms need spur land, but you could found "
                + ", ".join(f"a {n} ({c:.0f})" for c, n in affordable[:5])
                + " right here."
            )
        elif affordable:
            out.append(
                f"Main road: you can afford to found here but there are only "
                f"{free} unsold plots and a business needs "
                f"{D.STORE_BASE_PLOTS}. Buy land from a holder, or found elsewhere."
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
    else:
        # Say when you are ALREADY FED, not just when you are hungry. The state
        # block reports "Normal, 0.2h since eating" and eating stays affordable,
        # so nothing ever told an agent a second meal was money for nothing.
        # A0029 bought TEN meals in 90 simulated minutes on 2026-08-17 -- ~200
        # denari, and ~10 of the 400 decisions it was allowed all run. Those
        # wasted decisions are what exhausted its budget at hour 45, which is
        # what left it unable to act when it went Hungry at 57 and starved at
        # 81. The most expensive line in that chain was this missing sentence.
        left = agent.last_meal_window - agent.hours_since_last_meal
        if left > 0:
            out.append(
                f"You are FED for another {left:.1f}h (until hour "
                f"{(world.sim_hour + left):.1f}). Eating again before then is "
                f"wasted denari and a wasted decision -- you gain nothing."
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


def _shop_view(world: World, b: Business) -> dict[str, Any]:
    """A shop as a customer sees it: is it open, and does it have anything?

    Listing a name and type and nothing else made every player shop look like a
    counter you could buy from. In the 2026-08-16 48-hour run agents walked into
    empty, unattended taverns and were refused 240 times -- 46% of every failed
    action in the run -- because the observation never said "closed" or "out of
    Meal" and the engine knew both. A state shop is always open and always
    stocked, so it needs no such warning.
    """
    view: dict[str, Any] = {
        "id": b.id,
        "name": b.name,
        "type": b.type,
        "owner": "Government" if b.is_government else b.owner,
    }
    if b.is_government:
        return view
    # A business that has already missed payroll should say so to anyone who
    # might work there or trade with it. Without this, an insolvent business
    # looks exactly like a healthy one: on 2026-08-17 the same agent rejoined a
    # mine holding 0.44 denari more than a dozen times, losing an hour's wages
    # each time, because nothing marked it as unable to pay.
    if b.insolvent_since is not None:
        view["warning"] = (
            f"CANNOT MAKE PAYROLL -- this business missed wages and owes "
            f"{b.insolvent_debt:.2f}. It will not pay you until its owner funds "
            f"it, and it closes if they do not."
        )
    # Only shops a PERSON can buy from. A farm or refinery sells nothing over a
    # counter -- its goods move by order_from_business, which is remote and does
    # not care whether anyone is standing in it. Calling those "CLOSED" would
    # tell a refinery owner its supplier was unavailable when it is not.
    if not any(o in D.FINAL_GOODS for o in b.spec.outputs):
        return view
    if not b.is_staffed(world):
        view["status"] = (
            "CLOSED -- nobody is working here, so it will not sell to you. "
            "A player shop only trades while its owner or an employee is on shift."
        )
        return view
    for_sale = {i: q for i, q in b.inventory.items() if q > 0 and i in b.retail_prices}
    if for_sale:
        view["status"] = "open"
        view["sells"] = {
            i: {"price": round(b.price_for(i), 2), "stock": q}
            for i, q in sorted(for_sale.items())
        }
    else:
        view["status"] = "open but EMPTY -- staffed, with nothing in stock to sell"
    return view


def _owned_business_view(world: World, bid: str) -> dict[str, Any]:
    """One of the agent's own businesses, including whether it is dying.

    The engine tracked insolvency from the start and never told the owner: the
    2026-08-16 run logged 30 bankruptcy warnings and 7 liquidations, and not one
    of them reached an agent's observation. Owners could see a `cash` figure go
    negative but were never told a grace clock was running or what would end it.
    That is the mistake this project has now made nine times -- the code knowing
    something and the observation not saying it -- and it matters more now that
    missing payroll costs you your staff.
    """
    b = world.businesses[bid]
    view: dict[str, Any] = {
        "id": bid,
        "name": b.name,
        "type": b.type,
        "location": b.location,
        "cash": round(b.cash, 2),
        "stock": dict(b.inventory),
        "workers": len(b.production_staff()),
        # Land, and what it buys. An owner refused a hire needs to be able to
        # see WHY without guessing -- "no vacancy" is arbitrary unless the same
        # observation says how many places the site has and how to add one.
        "developed_plots": E.developed_plots(world, b),
        "employee_places": E.employee_slots(world, b),
        "employee_places_free": max(
            E.employee_slots(world, b) - len(b.production_staff()), 0
        ),
        "storage_capacity": E.business_storage_capacity(world, b),
        "storage_used": sum(b.inventory.values()),
        "researchers": len(b.researchers()),
        "research_tier": b.research.efficiency_tier,
        "unspent_rp": round(b.research.unspent_rp, 1),
    }
    payroll = sum(e.wage for e in b.roster if e.wage > 0)
    if payroll:
        view["payroll_per_hour"] = round(payroll, 2)
        view["hours_of_payroll_left"] = round(b.cash / payroll, 1)
    if not b.active_production:
        # An idle business used to report nothing but a row of zeros, and an
        # owner reading it had no way to tell "new and doing nothing" from
        # "running fine". In the 2026-08-16 smoke an agent founded a Weaponsmith
        # at hour 8, was shown exactly that, and went back to a wage job for the
        # remaining 16 hours while the business sat empty. Say the next step.
        makes = ", ".join(b.spec.outputs[:6]) if b.spec.outputs else "nothing"
        # Extraction has no inputs, so telling a farmer to go and buy feedstock
        # would be a plain falsehood -- the exact class of wrong-observation bug
        # that has cost this project eight runs.
        needs = (
            "somebody working in it, and a price"
            if b.type in D.EXTRACTION_BUSINESS_TYPES
            else "feedstock (order_from_business), somebody working in it, and a price"
        )
        view["production"] = (
            f"IDLE -- making nothing and earning nothing. Call set_production to "
            f"start. This type can make: {makes}. It also needs {needs}."
        )
    else:
        recipe = (D.REFINING_RECIPES.get(b.active_production)
                  or D.CRAFTING_RECIPES.get(b.active_production))
        needs = ""
        if recipe and recipe.inputs:
            needs = " Needs per unit: " + ", ".join(
                f"{q}x {i}" for i, q in recipe.inputs.items()
            ) + "."
        if not b.production_blocked:
            view["production"] = f"making {b.active_production}.{needs}"
        else:
            # Name the MISSING input. Saying only "no feedstock" while the stock
            # list plainly shows goods reads as "not enough of what you have",
            # and on 2026-08-16 a tavern owner answered it by ordering a third
            # load of Dirty Water -- an input no tavern can use -- while the one
            # it actually lacked was Purified Water. The engine knows exactly
            # which line of the recipe is short; it must say so.
            short = [
                f"{i} (have {b.inventory.get(i, 0)}, need {q})"
                for i, q in (recipe.inputs.items() if recipe else [])
                if b.inventory.get(i, 0) < q
            ]
            if short:
                why = "MISSING: " + "; ".join(short)
            else:
                why = (
                    "the yard is FULL -- nothing can be stored until a courier "
                    "hauls stock away"
                )
            view["production"] = (
                f"STALLED making {b.active_production} -- {why}.{needs} NPC hires "
                f"are not paid while stalled; agent employees are."
            )
    mine = [
        p for p in world.job_postings.values()
        if p.business_id == bid and p.is_live(world.sim_time)
    ]
    if mine:
        # Age and applicant count together, because the useful signal is "three
        # hours up and nobody has answered" -- that is the moment to raise the
        # wage, and an owner cannot infer it from a list of names alone.
        view["job_postings"] = [
            {
                "id": p.id,
                "role": p.role,
                "wage": p.wage,
                "hours_on_board": round(p.hours_open(world.sim_time), 1),
                "applicants": list(p.applicants),
                "next": (
                    # Name a REAL applicant, not a placeholder. This line used to
                    # read "hire_applicant('J0090', '<agent id>')" and on
                    # 2026-08-17 an owner sat on FOUR applicants for twelve
                    # simulated hours and let the advert lapse without hiring
                    # anyone. The candidates were listed in a neighbouring field;
                    # the instruction that mattered named none of them.
                    f"{len(p.applicants)} applicant(s) waiting. "
                    f"hire_applicant('{p.id}', '{p.applicants[0]}') takes the "
                    f"first; any id from the applicants list works. The advert "
                    f"lapses in {max(0.0, D.JOB_POSTING_HOURS - p.hours_open(world.sim_time)):.1f}h."
                    if p.applicants else
                    f"NOBODY has applied in {p.hours_open(world.sim_time):.1f}h. "
                    f"close_job('{p.id}') and post_job again at a higher wage, "
                    f"or hire_npc_employee instead."
                ),
            }
            for p in mine
        ]
    if b.insolvent_since is not None:
        left = D.BANKRUPTCY_GRACE_HOURS - (world.sim_time - b.insolvent_since) / 3600.0
        view["INSOLVENT"] = (
            f"could not pay wages; unpaid staff have left. This business CLOSES "
            f"in {max(0.0, left):.1f}h unless it holds {b.insolvent_debt:.2f} "
            f"(one hour of the payroll it missed). deposit that much to save it."
        )
    return view


def observe(
    world: World,
    log: EventLog,
    agent: Agent,
    reason: str,
    *,
    memory_limit: int = DEFAULT_MEMORY_LIMIT,
    chat_limit: int = DEFAULT_CHAT_LIMIT,
    thinking_limit: int = DEFAULT_THINKING_LIMIT,
    record_delivery: bool = True,
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
            _owned_business_view(world, bid) for bid in agent.owned_businesses
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
    here_businesses = [_shop_view(world, b) for b in all_here_businesses[:HERE_LIMIT]]

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
        "your_thinking": thinking_for(agent, thinking_limit),
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

    # Advice goes in BEFORE anything is trimmed or capped, and `render` puts it
    # at the top of the prompt. See `advice_for`.
    advice = advice_for(world, log, agent, record_delivery=record_delivery)
    if advice:
        obs["advice"] = advice

    # LAND YOU OWN, with ids. `develop_plot` and `list_land` both take one, and
    # an id that exists only inside the engine is an action nobody can call --
    # the same failure that made 15 bought vehicles unusable in the 2026-08-15
    # run, and B2B unusable on arrival before that.
    my_land = [p for p in world.plots.values() if p.owner == agent.id]
    if my_land:
        obs["your_land"] = [
            {
                "id": p.id, "at": p.location,
                "state": (
                    "building" if p.is_building(world.sim_time)
                    else "developed" if p.developed else "raw"
                ),
                "attached_to": p.business,
                "listed_at": p.for_sale_at,
            }
            for p in sorted(my_land, key=lambda x: x.id)[:12]
        ]

    # Land other agents have put up for sale. Without this, `buy_listed_land`
    # is an action whose only argument is unobtainable.
    listed = [
        p for p in world.plots.values()
        if p.for_sale_at is not None and p.owner != agent.id
    ]
    if listed:
        obs["land_for_sale"] = [
            {
                "id": p.id, "at": p.location, "price": round(p.for_sale_at, 2),
                "developed": p.developed,
                "seller": (world.agents[p.owner].name
                           if p.owner in world.agents else p.owner),
            }
            for p in sorted(listed, key=lambda x: x.for_sale_at or 0)[:10]
        ]

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
    # WHAT IS LYING ON THE GROUND HERE.
    #
    # `loot_ground` has been an action every agent holds since Phase 1 and
    # NOTHING has ever told them there was anything to pick up -- the pile
    # existed in `world.ground_loot` and appeared in no observation, so the tool
    # could only ever be called by an agent guessing. Goods dropped by a death,
    # or by the state withdrawing, simply sat there for the rest of the run.
    # PHASE4 §2: the observation withholding something the code already knew.
    pile = world.ground_loot.get(agent.location)
    if pile and (pile.get("items") or pile.get("denari", 0) > 0):
        lying = {i: q for i, q in (pile.get("items") or {}).items() if q > 0}
        obs["on_the_ground_here"] = {
            "items": lying,
            "denari": round(pile.get("denari", 0.0), 2),
            "worth": round(E.inventory_value(lying), 2),
            "note": "Unclaimed. loot_ground() takes what you can carry.",
        }

    # WHAT NOBODY IS MAKING, AND WHERE THERE IS ROOM TO MAKE IT.
    #
    # THE AFFORDANCE LINES ARE LOCATION-LOCAL. They answer "what can I do
    # HERE", and never "what does the valley need". On 2026-08-21 the state
    # withdrew and seven agents starved: the richest was standing in Town with
    # 1,380 denari, STARVING, reading "you can afford to found here but there
    # are only 0 unsold plots" -- while Refinery Row had sixteen free plots and
    # the world contained no refinery at all. It tried to BUY food 224 times and
    # never once tried to make any.
    #
    # Nothing here is a hint about what to do. It is two facts the code already
    # held and never said: nobody produces this, and there is ground free over
    # there. PHASE4 §2 at the scale of a whole economy.
    # CAPABLE IS NOT THE SAME AS PRODUCING. `market_power` counts businesses
    # that COULD make a thing, and by that measure the valley had a refinery
    # while seven agents starved -- it was open, empty, unstaffed and set to
    # produce nothing. What an agent needs to know is whether anyone is actually
    # making the thing, and if not, whether the plant exists and is merely idle.
    # Those are different problems with different answers: found one, or go and
    # switch that one on.
    gaps: list[str] = []
    for item in ("Purified Water", "Grain", "Meal"):
        makers = [
            b for b in world.businesses.values()
            if not b.closed and item in b.spec.outputs
        ]
        producing = [b for b in makers if b.active_production == item]
        in_stock = [b for b in makers if b.inventory.get(item, 0) > 0]
        if producing or in_stock:
            continue
        maker_type = next(
            (t for t, spec in D.BUSINESS_TYPES.items() if item in spec.outputs), None)
        if maker_type is None:
            continue
        if makers:
            idle = makers[0]
            who = "yours" if idle.owner == agent.id else f"{idle.name}"
            gaps.append(
                f"NOBODY IS MAKING {item}, though a {maker_type} stands idle at "
                f"{idle.location} ({who}). Switching it on needs feedstock, a "
                f"worker and set_production."
            )
        else:
            cost = D.BUSINESS_TYPES[maker_type].startup_cost
            room = [pl for pl in D.ALL_PLACES
                    if M.plots_at(pl) - sum(
                        1 for q in world.plots.values()
                        if q.location == pl and q.owner) >= D.SITE_BASE_PLOTS]
            gaps.append(
                f"NOBODY MAKES {item} AND NO {maker_type.upper()} EXISTS. "
                f"Founding one costs {cost:.0f}"
                + (f"; free ground at {', '.join(room[:3])}." if room
                   else "; no free ground -- buy from a holder.")
                + (" You can afford it." if agent.denari >= cost else "")
            )
    if gaps:
        obs["nobody_makes"] = gaps

    # WHAT THINGS ACTUALLY SELL FOR. Every price an agent has had until now was
    # either a book price from `data.py` or one counter's asking price in front
    # of it, so "is 5.2 a good price for ore?" had no answer anywhere in the
    # world -- an agent could be underselling its whole output for eighty hours
    # and nothing would tell it.
    #
    # NARROWED TO WHAT THIS AGENT TRADES, plus the busiest few. A full 62-item
    # board is per-call tokens on every decision forever, and most of it is
    # goods this agent will never touch.
    stake = set(agent.inventory)
    for bid in agent.owned_businesses:
        biz = world.businesses.get(bid)
        if biz is None:
            continue
        stake.update(biz.spec.outputs)
        stake.update(biz.inventory)
    quotes = E.ticker(world)
    mine = {i: q for i, q in quotes.items() if i in stake}
    busiest = sorted(quotes.values(), key=lambda q: -q.volume)[:4]
    for q in busiest:
        mine.setdefault(q.item, q)
    if mine:
        obs["market_prices"] = E.ticker_lines(mine, limit=8)

    # ESCORT WORK GOING BEGGING, and the convoy you are already on.
    #
    # A job board nobody can see is not a market -- PHASE4 §2's second entry was
    # nine of thirteen job applications rejected because agents were never told
    # which roles a business hires. An escort posting announced only in world
    # chat would scroll away in an hour and be gone.
    open_escort = [
        {
            "id": p.id, "role": p.role, "pays": round(p.fee, 2),
            "from": p.origin, "to": p.destination,
            "hired_by": world.agents[p.owner].name if p.owner in world.agents else p.owner,
            "weapon_provided": p.lent_weapon,
            # Driver-own means putting your OWN cart on the road, so an agent
            # without one here cannot take it and should not spend a decision
            # finding that out. Derived per-agent, like `you_can_carry_it`.
            "you_can_take_it": (
                agent.location == p.origin and not agent.escorting
                and (p.role != "Driver-own" or any(
                    v in world.vehicles and world.vehicles[v].location == agent.location
                    for v in agent.owned_vehicles))
            ),
        }
        for p in world.escort_postings.values()
        if p.status == "open" and p.owner != agent.id
    ]
    if open_escort:
        open_escort.sort(key=lambda j: (not j["you_can_take_it"], -j["pays"]))
        obs["escort_jobs"] = open_escort[:6]

    if agent.escorting:
        boss = world.agents.get(agent.escorting)
        obs["you"]["escorting"] = (
            f"guarding {boss.name if boss else agent.escorting} -- you travel when "
            f"they do and are paid on arrival"
        )
    if agent.escorts:
        obs["you"]["your_convoy"] = [
            {"who": (world.agents[m.agent_id].name
                     if m.agent_id in world.agents else "an NPC"),
             "role": m.role, "carrying": m.weapon, "costs": round(m.wage_paid, 2)}
            for m in agent.escorts
        ]

    # WHAT THE ROAD WILL COST YOU, at the decision rather than after it.
    #
    # This whole system exists so that agents buy better carts and hire guards.
    # Nobody buys either on the strength of a probability they were never shown,
    # and "the agents ignore the bandits" would be PHASE4 §2 for the fifteenth
    # time. So the number is computed for the journeys actually available and
    # put in front of them BEFORE they set off.
    #
    # Only when there is something to lose: an empty-handed agent gets nothing
    # here, because a risk line about no cargo is per-call tokens spent on a
    # decision that cannot be made.
    cargo_value, what = B.cargo_at_risk(world, agent)
    if cargo_value > 0 and not agent.in_transit:
        party = B.party_for(world, agent, cargo_value)
        risks = {
            dest: B.route_risk(agent.location, dest, party).probability
            for dest in D.ALL_PLACES
            if dest != agent.location
        }
        risky = {d: f"{r:.0%}" for d, r in sorted(risks.items()) if r > 0}
        block: dict[str, Any] = {
            "carrying": what,
            "worth": round(cargo_value, 2),
            "guards_hired": len(agent.escorts),
        }
        if risky:
            block["chance_of_being_robbed"] = risky
            block["note"] = (
                "If they catch you they take between half the load and ALL of "
                "it, and there is no insurance. A faster vehicle and hired "
                "guards both cut this; walking is the worst of both. Per unit "
                "delivered, one guarded cart beats many small trips."
            )
        obs["you"]["road_risk"] = block

    if job is not None:
        loaded = agent.hauling == job.id
        obs["you"]["your_haulage_job"] = {
            "id": job.id, "item": job.item, "qty": job.qty,
            "pays": round(job.courier_fee, 2),
            # How the two businesses split the convoy. The courier carries
            # someone else's property either way, but the split is what they
            # agreed, and it is what a courier needs to judge who will care if
            # the load goes missing.
            "convoy_split": job.split_label(),
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
    # Advice is named on line one and rendered before anything else. The
    # observation runs past 20,000 characters; a block placed after the price
    # tables is present in the prompt and absent from the decision, which is the
    # exact distinction PHASE4 §2 is a list of.
    if obs.get("advice"):
        n = len(obs["advice"])
        lines[0] += (
            f" You have {n} piece{'s' if n != 1 else ''} of ADVICE waiting, "
            f"below. Read it before you decide."
        )
    for key, heading in [
        ("advice", "ADVICE FOR YOU (from someone watching -- weigh it, then decide)"),
        ("you", "YOU"),
        ("here", "WHERE YOU ARE"),
        ("player_prices_here", "PLAYER PRICES HERE"),
        ("your_land", "LAND YOU OWN"),
        ("land_for_sale", "LAND FOR SALE (other agents' asking prices)"),
        ("you_can", "WHAT YOU CAN DO FROM HERE"),
        ("taxes_now", "CURRENT TAX RATES"),
        ("where_to_buy_stock", "WHERE TO ORDER FEEDSTOCK (you need not travel)"),
        ("courier_jobs", "HAULAGE JOBS GOING BEGGING"),
        ("your_orders_in_transit", "YOUR ORDERS NOT YET DELIVERED"),
        ("memory", "RECENTLY"),
        ("your_thinking", "YOUR LAST FEW DECISIONS, AND WHY YOU MADE THEM"),
        ("chat", "CHAT"),
    ]:
        value = obs.get(key)
        if not value:
            continue
        lines.append(heading)
        lines.extend(_render_value(value, 1))
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"
