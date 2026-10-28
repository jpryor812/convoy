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
from . import land as LAND
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
# Kept as a name for the one-city world every earlier run and test was recorded
# in; `job_centre_of` is what the code reads, because each city has its own.
JOB_CENTRE_LOCATION = M.market_of(M.HOME_CITY)


def job_centre_of(city: str) -> str:
    """Where a city's job board hangs: its market, because everyone spawns there.

    So the whole population reads it at hour zero without spending a step to
    reach it -- which is the only reason the board works at all (PHASE4 §2's
    second entry: 543 refusals from agents walking the valley looking for work).
    """
    return M.market_of(city)
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
    # The hourly score. Agents get it as a standing block in every observation
    # (`_contest_view`); letting the log rows through as well would spend the
    # 15-line memory budget restating a number already on the page, and evict
    # the news that a neighbour opened a refinery to do it. Same argument as the
    # advice events above.
    "city_standings",
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


def _static_map(city: str = M.HOME_CITY, rival: str | None = None,
                npc_bandits: bool = True, outposts: bool = False) -> str:
    """The valley THIS agent lives in, and nothing about anyone else's.

    A citizen of Aldermarch cannot walk to Cinderhold, cannot trade there and
    cannot see it. Describing the rival's ground would be describing places
    every travel_to would refuse -- fourteen destinations offered where seven
    are reachable, which is PHASE4 §2 with the sign flipped: the briefing
    asserting something the code will not honour. What an agent is told about
    the rival is exactly one thing, and it is a score.
    """
    home = M.CITIES[city]
    lines = [f"THE WORLD -- {home.name.upper()}", ""]
    lines.append(
        f"One road runs north to south through {home.name}. Production sits at "
        f"the north end, the only market at the south end, so goods must cross "
        f"the dangerous middle to reach a buyer. Protected ground means no "
        f"combat and no theft."
    )
    rivals = [rival] if isinstance(rival, str) else list(rival or [])
    if rivals:
        # ROADS JOIN THE CITIES (2026-10-16). Name every other city's places,
        # because an agent cannot travel to a name it has never been told, and
        # name the roads, because those are where the money -- and the
        # robbers -- will be.
        lines.append("")
        lines.append(
            "OTHER CITIES. Roads join every city's market. You may travel, trade, "
            "work, buy land and build in any of them, and people from them may "
            "do all of that in yours. The roads between cities are the longest "
            "and least guarded on the map."
        )
        for r in rivals:
            c = M.CITIES[r]
            lines.append(
                f"  {c.name}: {c.locations[0]} (refineries), {c.locations[1]} "
                f"(hub; spurs {', '.join(c.spurs)}), {c.locations[2]} (market)."
            )
        for seg in M.INTERCITY_SEGMENTS:
            ends = {M.city_of(seg.a), M.city_of(seg.b)}
            if city in ends and ends <= set([city] + rivals):
                lines.append(
                    f"  {seg.name} ({seg.a} <-> {seg.b}): {seg.seconds:.0f}s, "
                    f"danger {seg.danger:.2f}."
                )
    lines.append("")
    for name in home.places[:3]:
        loc = M.LOCATION_BY_NAME[name]
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
    for seg in M.segments_in(city):
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
        f"{len(M.spurs_in(city))} spur roads dead-end off the main road, "
        f"{M.SPUR_SECONDS:.0f}s deep each: surveyed land near the trading post. "
        f"Everyone else lives and works on claims of open land, each joined to "
        f"the roads by its own dirt road; travel_to any outpost or claim by its "
        f"name."
        if outposts else
        f"{len(M.spurs_in(city))} spur roads dead-end off the main road, "
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
        "SAY WHY. Every action has a `why` field: one sentence on why you are "
        "doing it. It goes into your own notes, which people will read and ask "
        "you about later; nobody in the world sees it. WORLD CHAT IS FOR TALKING "
        "TO OTHER CITIZENS -- offering or asking for work, posting a convoy, "
        "recruiting, bargaining, asking for help. Do not narrate your actions "
        "there; that is what `why` is for."
    )
    lines.append("")
    lines.append(
        f"MARKET PRICES. Your observation carries what goods have ACTUALLY sold "
        f"for over the last {E.TICKER_WINDOW_HOURS:.0f} hours -- a "
        f"volume-weighted average against the book price, anonymous. Use it to "
        f"price your own goods and judge an offer in front of you."
    )
    lines.append("")
    if not npc_bandits:
        # THE ROBBERS ARE PEOPLE (2026-10-16). Said in full, because an agent
        # that does not know it may raid will never raid, and one that does not
        # know raiders can die will raid with a slingshot against a cart.
        lines.append(
            "RAIDS. There are no faceless bandits: the robbers are people. Anyone "
            "may lie in wait on a road to rob whoever crosses it with cargo -- "
            "plan_raid, standing at one end of that road -- and others standing "
            "at either end may join_raid. When a load crosses, the raiders' "
            "strength (their weapons and armour, summed) meets the convoy's (the "
            "traveller, any escorts, the cart's own plating). Scouts may spot the "
            "ambush and slip it; a fast cart may outrun it. Raiders who win take "
            "half to all of the load as stolen goods. Raiders who LOSE may be "
            "KILLED, losing what was on them -- cargo, the cart they rode, their "
            "weapons and armour -- though never their cash or what they own. "
            "Weapons and armour are forged at a Weaponsmith; equip what you buy. "
            "Market squares are protected: nobody fights there. The roads "
            "between cities carry the richest loads and the fewest guards. "
            "Robbing your own city's convoys only moves money between its own "
            "pockets; robbing a rival city's moves it into yours. To defend a "
            "load, hire_escort (or post_escort_job: an agent costs less than an "
            "NPC) and carry weapons yourself. WHO PAYS FOR A CONVOY between two "
            "businesses is negotiable -- a seller/buyer split of 100/0, 75/25, "
            "60/40, 50/50 and so on, covering both the courier's fee and "
            "anything raiders take."
        )
        lines.append("")
    if npc_bandits: lines.append(
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
    lines.append((
        f"LAND. A business needs four plots of its own. claim_land takes four "
        f"plots of open land (a site from OPEN LAND NEAR YOU) with a dirt road to "
        f"them; then travel_to the claim and start_business there. The price is "
        f"set by how near it is to a trading post and to land people have built "
        f"on: dear close in, cheap far out. A claim is its claimant's -- nobody "
        f"else builds there -- and land counts in your net worth at what you "
        f"paid. Founding on a named spur charges the same nearness price. Sell "
        f"plots with list_land; buy others' with buy_listed_land.\n"
        if outposts else
        f"LAND. Plots are finite everywhere and can sell out; "
        f"{M.market_of(city)} is scarcest. "
        f"Unsold land is {D.LAND_BASE_PRICE:.0f}/plot (buy_land), else buy from a "
        f"holder (buy_listed_land) or sell your own (list_land).\n")
        +
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
    for junction in M.locations_in(city):
        spurs = M.SPURS_BY_JUNCTION.get(junction, [])
        if spurs:
            lines.append(f"  off {junction}: " + ", ".join(s.name for s in spurs))
    return "\n".join(lines)


def _static_economy(state_gone: bool = False, city: str = M.HOME_CITY,
                    no_state: bool = False, starter: bool = False) -> str:
    lines = ["", "PRICES", ""]
    if no_state:
        # NO FIXED PRICES TO LIST, so list what things are WORTH. Book value is
        # the yardstick goodwill is measured against and a fair guide to a
        # price, but it is not an offer: nothing here buys or sells at it.
        lines.append(
            "There are no fixed prices. BOOK is what a thing is worth -- a guide "
            "to pricing and the yardstick profit is measured against -- not an "
            "offer: a thing sells for whatever a citizen will pay."
        )
        lines.append("")
        lines.append(f"  {'item':<24}{'book':>8}")
        for item in D.ALL_ITEMS:
            if item == "On Foot":
                continue
            lines.append(f"  {item:<24}{_money(round(D.base_price(item), 2)):>8}")
    else:
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
        "Claim one, collect at the pickup, deliver at the destination. Too big "
        "for you? Claim the part you can carry (qty) and others take the rest -- "
        f"on foot you carry {D.ON_FOOT_CAPACITY} units. Honest money with no "
        "capital, and the only way goods cross the valley."
    )
    lines.append("")
    lines.append(
        "SHOPS NEED SOMEBODY IN THEM. A player business only sells while its "
        "owner or an employee stands at it. Government shops are always staffed."
    )

    lines.append("")
    if state_gone:
        # THE PRICES ABOVE ARE NOW HISTORY, AND SAYING SO IS THE POINT. The old
        # version of this paragraph promised that government businesses "always
        # buy what you bring and sell at the prices above" -- and went on saying
        # it for the whole run after they were demolished.
        lines.append((
            # STARTER SITES ARE NOT A GOVERNMENT, BUT THEY EXIST (2026-10-28).
            # A no-state world reports the state as gone, and this used to tell
            # agents beside a state tavern that there was none.
            "BUSINESSES. No experience is needed for anything: any role, and "
            "founding any business, is open at any hour. Apart from the state's "
            "four sites at each market (above), every business in the valley is "
            "owned by one of you, or does not exist yet. Businesses are not "
            "listed here -- find them by going and looking, or by asking in chat."
        ) if starter else (
            "BUSINESSES. No experience is needed for anything: any role, and "
            "founding any business, is open at any hour. THERE ARE NO "
            "GOVERNMENT BUSINESSES. Nothing will buy what you bring at a fixed "
            "price and nothing will sell to you at one"
            + ("; book value is a guide, not an offer. " if no_state else
               "; the prices above are only what things used to fetch. ")
            + "Every business in the valley is "
            "owned by one of you, or does not exist yet. Businesses are not "
            "listed here -- find them by going and looking, or by asking in chat."
        ))
        lines.append(f"  {'type':<32}{'hires'}")
        for name, spec in sorted(D.BUSINESS_TYPES.items()):
            roles = ", ".join(spec.production_roles) if spec.production_roles else "nobody"
            tail = " + Researcher" if spec.can_research else ""
            lines.append(f"  {name:<32}{roles}{tail}")
    else:
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
            place = M.government_sites_for(city).get(name, "-")
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
        "WAGES per hour. The state's four sites pay the 'typical' rate; a "
        "citizen may pay anything at or above the floor, and a worker leaves "
        "for whoever pays more."
        if no_state and starter else
        "WAGES per hour. Only citizens employ. 'typical' is what the role is "
        "usually worth; an employer may pay anything at or above the floor, and "
        "a worker leaves for whoever pays more."
        if no_state else
        "WAGES per hour. There is no state employer any more, so the state "
        "column below is only what work used to pay. A player employer may set "
        "any wage at or above the floor; nobody has to match the old rate."
        if state_gone else
        "WAGES per hour. The state pays a narrow band. A player employer may set "
        "any wage at or above the floor, so outbidding the state for staff is "
        "open to you:"
    )
    lines.append(f"  {'role':<18}{'typical' if no_state else 'state':>8}{'floor':>8}")
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


def _static_rules(state_gone: bool = False, city: str = M.HOME_CITY,
                  no_state: bool = False, starter: bool = False,
                  outposts: bool = False) -> str:
    lines = ["", "HOW THINGS WORK", ""]
    lines.append(
        f"SUSTENANCE. Food is sold at TAVERNS only -- you cannot cook. "
        + (
            "THERE IS NO STATE TAVERN. The only food in the valley is in a "
            "tavern somebody here owns and has stocked; if none of you keeps "
            "one supplied, everybody starves. "
            if state_gone and not starter else
            f"The state's Tavern "
            f"({M.government_sites_for(city)['Tavern / Inn']}) charges "
            f"{E.npc_sell_price('Meal'):.2f} for a Meal: Normal for "
            f"{D.MEALS['Meal'].window_hours:.0f}h. "
        )
        + ("You live away from the taverns: order_meal has one brought to you "
           "for its price and a fee by distance -- order before you are hungry. "
           if outposts else "")
        + f"A player Tavern may charge as "
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
        "profit."
        + ("" if no_state else
           " Government businesses are always staffed, never research, and set a "
           "price floor you must beat on price or on distance.")
    )
    lines.append("")
    lines.append(
        f"HIRING. post_job advertises a role and wage to everyone -- the only way "
        f"an agent learns you are hiring. Applicants appear in your observation; "
        f"take one with hire_applicant, or close_job and repost higher if nobody "
        f"bites. Adverts lapse after {D.JOB_POSTING_HOURS:.0f}h. "
        + (
            # No state, no NPC workers: see `schemas.NO_STATE_HIDDEN`.
            f"Every worker is a citizen. offer_job puts a wage to one named "
            f"person -- even someone employed elsewhere, who may leave for it; "
            f"so may yours, if a rival pays more. A worker GETS BETTER, reaching "
            f"+{E.skill_bonus(1e9):.0%} output with experience. To work your OWN "
            f"business, apply_for_job there (no wage) and start_shift. "
            if no_state else
            f"An agent is cheaper than an NPC but must be present and on shift -- "
            f"and an agent GETS BETTER, reaching +{E.skill_bonus(1e9):.0%} output "
            f"with experience, while an NPC is stuck at Novice forever. "
        )
        + "Answer others' adverts with apply_to_job; you may apply to several."
    )
    lines.append("")
    lines.append(
        f"PAYROLL. Wages come out of the business's own cash, not your pocket, so "
        f"keep it funded with deposit. A business never goes into debt: if it "
        f"cannot pay someone THAT WORKER LEAVES, and it CLOSES in "
        f"{D.BANKRUPTCY_GRACE_HOURS:.0f}h unless you deposit the hour of payroll "
        f"it missed. "
        + ("" if no_state else
           "NPC hires are paid only while the business is actually producing, so "
           "an idle NPC is free -- but ")
        + ("An" if no_state else "an")
        + " agent you employ is paid for every hour they work whether or not you "
        "have feedstock. Your observation shows each business's cash and payroll."
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
        + ". A big load can be shared: each courier claims what it can carry."
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
        "TAXES. None: there is no government to collect them."
        if no_state else
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


def static_briefing(
    state_gone: bool = False,
    city: str = M.HOME_CITY,
    rival: str | None = None,
    no_state: bool = False,
    npc_bandits: bool = True,
    starter: bool = False,
    outposts: bool = False,
) -> str:
    """Everything that never changes, for the cached system prompt.

    Pure function: no world, no agent, no clock. Byte-identical across every
    agent OF ONE CITY on ONE side of the withdrawal, which is what makes it
    cacheable -- a two-city run has four of these in it, not one per call.

    `state_gone` is the single exception to "never changes", and it is here
    rather than in the per-decision observation on purpose. The old briefing
    described the government in five places; a correction bolted onto the hourly
    observation would have to out-argue all five, and the model would be left
    picking between two things the prompt asserted. Cheaper and honest to stop
    saying the false one.

    `rival` turns the whole thing from a solo game into a contest. Passing None
    -- a one-city world -- produces the briefing exactly as it read before there
    were cities, which is what keeps every earlier run comparable.
    """
    if rival is None:
        header = (
            "You are a person living in Convoy, a Bronze Age valley economy. Your goal "
            "is to maximise your own Net Worth (denari + businesses + vehicles + "
            "property + inventory) by the end, WITHOUT DYING. Starving kills you and "
            "wipes everything you own, so a dead agent scores nothing however rich it "
            "was an hour earlier -- staying alive is not a side condition, it is the "
            "first term. You compete and cooperate with other real agents. Nothing "
            "below ever changes; your current situation arrives separately with each "
            "decision.\n\n"
        )
    else:
        # THE OBJECTIVE IS THE ONE THING THIS SIMULATION IS ASKING ABOUT, so it
        # is stated in full and stated first. PHASE8's finding was that agents
        # do what the briefing says and nothing it does not say -- the valley
        # starved next to 150 units of wheat because nothing had told anyone
        # nobody was making food. An objective that has to be inferred from a
        # scoreboard would be inferred wrong.
        #
        # CITY FIRST, THEN RANK WITHIN IT (designer decision, 2026-09-03). Not
        # pure collectivism: with only the city total to play for, no citizen
        # has a private reason to be the one who takes the founding risk rather
        # than the one who watches somebody else take it, and the predictable
        # result is a valley of free-riders that reads as the model being
        # passive. Not pure self-interest either, or the cities are two
        # unrelated runs sharing a page. Both terms, in a stated order, so an
        # agent facing a trade between them knows which way to break the tie.
        home_name = M.CITIES[city].name
        rivals = [rival] if isinstance(rival, str) else list(rival)
        rival_name = (
            M.CITIES[rivals[0]].name if len(rivals) == 1 else
            ", ".join(M.CITIES[r].name for r in rivals[:-1])
            + " and " + M.CITIES[rivals[-1]].name
        )
        header = (
            f"You are a citizen of {home_name}, a Bronze Age valley economy, and "
            f"{home_name} is in a contest with the city of {rival_name}.\n\n"
            f"HOW YOU ARE SCORED, IN ORDER.\n"
            f"FIRST: {home_name} wins if its TOTAL beats "
            + ("every rival's" if len(rivals) > 1 else f"{rival_name}'s")
            + f" at the end. This is the term that matters most. A citizen of a "
            f"losing city has lost, however rich that citizen personally is.\n"
            f"WHAT A CITY'S TOTAL IS: the cash, goods, vehicles and homes of its "
            f"citizens, PLUS every business standing in the city, whoever owns "
            f"it. A business counts for the city it stands in -- build in "
            f"{home_name} and it is {home_name}'s; build in a rival city and you "
            f"are adding to theirs.\n"
            f"SECOND: within {home_name} you are ranked against your own "
            f"neighbours by your personal Net Worth (denari + businesses + "
            f"vehicles + property + inventory). Being the citizen who built the "
            f"refinery beats being the one who watched.\n\n"
            f"So: grow your own wealth, because your wealth IS part of your "
            f"city's total and the two mostly pull the same way. But when they "
            f"pull apart, the city comes first. Taking 50 more denari off a "
            f"neighbour mostly moves 50 from one of {home_name}'s pockets to "
            f"another. What actually grows {home_name} is somebody MAKING "
            f"something that was not there an hour ago -- ore dug, grain grown, "
            f"bronze smelted. Selling a neighbour the tool that lets them "
            f"produce is worth more to {home_name} than the margin you made on "
            f"it. Trade with {rival_name} is open to you by road; what you sell "
            f"them for more than it cost you is {home_name}'s gain.\n\n"
            f"DYING COSTS YOUR CITY EVERYTHING YOU HAD. Starving kills you and "
            f"wipes what you own, and the city total is a SUM -- your whole "
            f"contribution goes to nearly zero and the survivors averaging "
            f"higher does not make it back. Staying alive is not a side "
            f"condition, it is the first term, and it applies to your neighbours "
            f"too: a citizen of {home_name} who starves is a hole in "
            f"{home_name}'s score. Feeding somebody who is Starving is worth "
            f"more than the meal costs.\n\n"
            f"Nothing below ever changes; your current situation, and the "
            f"current score, arrive separately with each decision.\n\n"
        )
    header += (
        # Four smoke runs produced no business at all, by agents who could afford
        # one and were told so. Spending 200 denari on a tavern LOOKS like losing
        # 200 of net worth unless you know how a business is valued -- so say it.
        # It now GAINS net worth, which is a stronger thing to say and has to be
        # said just as plainly, or the change buys nothing.
        "OWNING IS HOW YOU GET RICH. A business you own is worth what it cost, "
        "plus its cash, plus its stock at what that stock would actually SELL "
        f"for, plus {D.BUSINESS_PROFIT_MULTIPLE:.0f}x the PROFIT it made in the "
        "last 24 hours. One that makes things and sells them at a profit grows "
        "your worth far faster than any wage; one that sits idle is worth only "
        "what is in it, and goods nobody will buy are worth scrap. More workers "
        "make more to sell.\n\n"
        # THE MARGIN RULE, stated because an agent that does not know it will
        # price at book and wonder why nothing accrues. It is also the sentence
        # that forecloses the wash trade, and it is cheaper to say than to
        # detect: an agent told that selling at book earns nothing has no reason
        # to try passing goods back and forth to inflate a valuation.
        "PROFIT MEANS ABOVE BOOK PRICE. Goodwill counts only what you sell ABOVE "
        "a good's listed base price. Selling AT book moves value from shelf to "
        "purse and earns nothing; selling BELOW it -- "
        + ("the state's convoy pays half what a good sells for between people"
           if outposts else "the state's 0.4x offer is below it")
        + " -- loses you the difference, and passing goods back and forth "
        "with a neighbour at book earns neither of you a denari. What pays is "
        "buying low, ADDING something, and selling high."
    )
    if no_state:
        # NEVER A GOVERNMENT, rather than one that left: and with nothing to
        # buy at hour zero, the briefing has to say what the valley must make
        # first, or nobody makes it. The food chain is spelled out because the
        # 2026-10-15 run starved for want of a tavern even with a state.
        header += ((
            # OUTPOSTS (2026-10-27): the state's four as trading posts, the
            # convoy's price, and how a citizen gets started from an outpost.
            "\n\nOUTPOSTS: THERE ARE NO TOWNS YET, NO GOVERNMENT AND NO TAX. "
            "Everyone lives at an outpost of their own on open land -- YOUR "
            "OUTPOST says where yours is. Each city's market is a STATE TRADING "
            "POST with four sites, a Tavern, Farm, Mine and Refinery. They SELL at "
            "a fixed HIGH price (about 1.5x book; its Tavern also sells weapons, "
            "armour and tools), HIRE anyone at a fixed wage, and BUY ANY good at "
            "HALF what it sold for between people over the last day "
            "(sell_to_bidder: the state's convoy collects from your yard, free, "
            "and pays when it collects). A citizen who makes what the state "
            "sells and prices it under the state takes its customers.\n"
            "HOW TO START. Your grown family works any business you own for "
            "nothing (assign_family). A business needs four plots of its own: "
            "claim_land a site from OPEN LAND NEAR YOU, travel_to it, then "
            "start_business there -- farms do best near water, mines near the "
            "mountains, and each site says which. Land near people and the "
            "trading posts costs more; far out it is cheap. Short of money, "
            "take the state's wage at a trading post first. If you borrowed to "
            "settle, YOUR OUTPOST says what you owe: it grows 2% a day and a "
            "fifth of what your businesses earn pays it down (repay_debt pays "
            "more). Settling near others is how towns will form.\n"
        ) if outposts else (
            "\n\nTHERE IS NO GOVERNMENT, AND NO TAX -- only FOUR STATE SITES "
            "the town was started with: the state's Tavern (in the market "
            "square), Farm, Mine and Refinery. They are a backstop: they SELL "
            "at a fixed HIGH price (about 1.5x book; its Tavern also sells "
            "weapons, armour and tools), BUY ANY good at a fixed LOW price "
            "(0.4x book; sell_to_bidder), and HIRE anyone at a fixed wage -- so nobody "
            "starves on day one and anyone can earn a wage. Everything else -- "
            "every other shop, job, cart and weapon -- exists only because one "
            "of you made it, and a citizen who makes what the state sells and "
            "prices it under the state takes its customers.\n"
        ) if starter else (
            "\n\nTHERE IS NO GOVERNMENT. Nothing buys or sells at a fixed "
            "price, nobody pays a wage but another citizen, and there is no tax. "
            "Every shop, job, meal, cart and weapon in the world exists only "
            "because one of you made it.\n"
        )) + (
            f"YOU START FED FOR {D.START_FED_HOURS_NO_STATE:.0f} HOURS. After "
            "that you can eat only a Meal cooked at a Tavern. A Tavern cooks "
            "Meals from Grain and Purified Water; a Refinery makes those from "
            "Wheat and Dirty Water; a Farm grows those. "
        ) + ((
            "The state's Tavern feeds anyone who can pay its high price, so "
            "the opportunity is to feed the town CHEAPER: a citizen chain of "
            "farm, refinery and tavern that undercuts it takes every customer.\n"
            + ("You live away from the taverns: order_meal has a meal brought "
               "for its price and a fee by distance -- order before you are "
               "hungry.\n" if outposts else "")
        ) if starter else (
            "NOBODY MAKES ANY OF IT "
            "YET: unless citizens found farms, a refinery and a tavern -- and "
            "staff them -- within the first day, people starve, and a citizen "
            "who starves is a hole in the city's score.\n"
        )) + (
            "The same goes for everything else. A Stable breeds Camels from "
            "Purified Water, Grain and Tanned Leather (a Refinery tans Hide from "
            "a Farm). A Weaponsmith forges Slings and Spears from Lumber and "
            "Leather, and blades and armour from Bronze and Iron (Refinery, "
            "from Mine ores and Charcoal). Until somebody builds the chain, "
            "everyone walks and fights with a slingshot.\n"
            # The first no-state smoke (2026-10-16): all twelve agents founded a
            # Tavern in the same six minutes, each "the city's first", and then
            # nobody could afford the Refinery between the Farm and the Tavern.
            # So say what each link costs against what one person has, and that
            # the others are choosing at the same moment.
            f"YOU START WITH {D.STARTING_DENARI:.0f} DENARI. Founding costs: "
            + ", ".join(
                f"{n.split(' /')[0]} {D.BUSINESS_TYPES[n].startup_cost:.0f}"
                for n in ("Farm", "Refinery", "Tavern / Inn", "Mining Operation",
                          "Vehicle Dealer / Stable", "Weaponsmith / Armory")
                if n in D.BUSINESS_TYPES
            )
            + (", plus the land it stands on" if outposts else "")
            + ". A link that costs more than one person has needs two or more "
            "to POOL their cash with `pay`. Your neighbours are deciding at the "
            "same time as you: one Tavern feeds a city, and a city with four "
            "taverns and no Refinery starves. Read world chat, say what you are "
            "founding before you found it, and build the link nobody has claimed."
        )
    elif state_gone:
        header += (
            "\n\nTHE GOVERNMENT IS GONE. It closed every business it owned, "
            "released every worker, abandoned its land and left the valley. "
            "IT IS NOT COMING BACK. It will not reopen, it will not buy your "
            "goods at a fixed price, it will not sell you food, and it will not "
            "hire you. There is no point waiting for it or planning around it. "
            "Everything from here is between you and the other people here: if a "
            "thing is going to be made, sold, carried or eaten, one of you has "
            "to do it."
        )
    return "\n".join([
        header, "",
        _static_map(city, rival, npc_bandits, outposts),
        _static_economy(state_gone, city, no_state, starter),
        _static_rules(state_gone, city, no_state, starter, outposts),
    ])


def briefing_for(world: World, agent: Agent) -> str:
    """The cached prefix for one agent, given the world it is in.

    The one place that works out an agent's city and rival, so no caller has to
    remember that "" means home and that a one-city world has no rival at all.
    Two cities and two sides of the withdrawal make four distinct strings across
    a whole run, which is what the prompt cache wants.
    """
    city = world.city_of(agent)
    return static_briefing(
        state_gone=world.state_gone_at(city) is not None,
        city=city,
        rival=([c for c in world.cities if c != city] or None) if world.is_contest() else None,
        no_state=world.no_state,
        npc_bandits=world.npc_bandits,
        starter=world.starter_sites,
        outposts=world.outposts,
    )


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
    home = world.city_of(agent)
    job_centre = job_centre_of(home)
    if agent.location == job_centre and not agent.current_job:
        openings: list[tuple[float, str]] = []
        for b in world.businesses.values():
            if b.closed or not b.spec.needs_worker:
                continue
            # Your own city's vacancies. A wage in the other valley is a wage
            # nobody can walk to collect.
            if M.city_of(b.location) != home:
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
                f"JOB CENTRE ({job_centre}) -- every position open in "
                f"{M.CITIES[home].name} right now, best paid first: {shown}. "
                f"Travel to one and "
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
    def _advert_is_local(posting) -> bool:
        """Any advert in a city this world contains: roads join them now, and
        a better wage in the next city is a reason to move (2026-10-16)."""
        biz = world.businesses.get(posting.business_id)
        return biz is not None and M.city_of(biz.location) in world.cities

    # Offers made to THIS agent by name come first: they can be taken outright.
    offers = [
        p for p in world.job_postings.values()
        if p.invitee == agent.id and p.is_live(world.sim_time)
    ]
    if offers:
        offers.sort(key=lambda p: -p.wage)
        lines = []
        for p in offers[:6]:
            b = world.businesses.get(p.business_id)
            delta = (f", {p.wage - current_wage:+.2f}/hr on what you earn now"
                     if agent.current_job else "")
            lines.append(f"{p.id}: {p.role} at {b.name if b else '?'} "
                         f"({b.location if b else '?'}) for {p.wage:.2f}/hr{delta}")
        out.append("JOB OFFERS TO YOU -- accept_job_offer(id) takes one outright, "
                   "leaving any job you hold:\n  " + "\n  ".join(lines))

    open_jobs = [
        p for p in world.job_postings.values()
        if p.is_live(world.sim_time) and p.owner != agent.id
        and p.invitee is None
        and p.wage > current_wage and _advert_is_local(p)
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
    if world.outposts and M.is_claim(agent.location):
        # A claim is somebody's land, bought with it: there is no unsold land
        # here to buy, and its four plots are one building's worth.
        held = world.claims.get(agent.location)
        free_mine = [p for p in world.plots.values()
                     if p.owner == agent.id and p.location == agent.location
                     and not p.business and not p.home]
        if held is not None and held.owner != agent.id:
            who = world.agents.get(held.owner)
            out.append(f"LAND HERE: {agent.location} is {who.name if who else 'somebody'}'s claim.")
        elif agent.home == agent.location:
            out.append("LAND HERE: your home fills this claim. To found a business, "
                       "claim_land a site from OPEN LAND NEAR YOU and found it there.")
        elif len(free_mine) >= M.SITE_BASE_PLOTS:
            out.append(f"LAND HERE: your claim, {len(free_mine)} plots free -- found any "
                       f"business here with start_business (the land is already yours).")
    else:
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
            # And WHERE TO GET IT, at what price (2026-10-17). "MISSING: Grain"
            # told a tavern owner what it lacked but not that a refinery in the
            # same square had it on sale -- and the Grain went unbought.
            def _source(item: str) -> str:
                from . import actions as A   # circular at import time, as in `observe`
                best = None
                for s in world.businesses.values():
                    if s.closed or s.owner == b.owner or M.city_of(s.location) not in world.cities:
                        continue
                    if s.is_government:
                        if item not in (s.spec.outputs or ()):
                            continue
                    elif s.inventory.get(item, 0) <= 0 or item not in s.retail_prices:
                        continue
                    if not A._may_buy_from(b, s)[0]:
                        continue
                    if best is None or s.price_for(item) < best.price_for(item):
                        best = s
                if best is None:
                    return f" -- nobody has it on sale; post_buy_order to ask for it"
                where = ("same place, handed over at once" if best.location == b.location
                         else best.location)
                if best.is_government:
                    return (f" -- the state's {best.type} sells it at {best.price_for(item):.2f} "
                            f"({best.id}, {where}); order_from_business")
                return (f" -- ON SALE: {best.inventory.get(item, 0)} at "
                        f"{best.price_for(item):.2f} from {best.name} ({best.id}, {where}); "
                        f"order_from_business")
            short = [
                f"{i} (have {b.inventory.get(i, 0)}, need {q}){_source(i)}"
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
    ground = LAND.describe(b)
    if ground:
        view["land"] = ground
    from . import ground as GR
    wear = GR.describe(world, b)
    if wear:
        view["ground_and_air"] = wear
    # PROJECTS (2026-10-18): what is being built here, or what could be.
    from . import progress as PG
    owner = world.agents.get(b.owner)
    if b.project:
        eta = PG.eta_hours(world, b, owner)
        mat = PG.PROJECTS[b.project["kind"]]["material"]
        view["project"] = (f"building {b.project['kind']}: {b.project['done'] / b.project['total']:.0%}, "
                           f"ready in about {eta:.1f}h -- sooner with more people on shift here "
                           f"and {mat} in the yard")
    elif not b.is_government:
        opts = [f"{k} ({PG.project_cost(b, k):.0f}, ~{PG.project_work(b, k):.0f} work-hours): {v['does']}"
                for k, v in PG.PROJECTS.items() if k in PG.available(b) and b.improvements.get(k, 0) < v["max"]]
        if opts:
            view["projects_you_can_start"] = opts
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
                    f"close_job('{p.id}') and post_job again at a higher wage"
                    + (", or offer_job to someone by name." if world.no_state
                       else ", or hire_npc_employee instead.")
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


def _contest_view(world: World, agent: Agent) -> dict[str, Any] | None:
    """THE SCORE, in front of the agent, on every single decision.

    None in a one-city world, so nothing about a solo run changes and every
    earlier run stays comparable.

    WHY IT IS ON EVERY DECISION rather than announced on the hour. PHASE8 §3:
    the government left at h36 and the news lived for one hour, so every agent
    whose next decision fell after h37.01 was never told at all. A score that
    scrolls away is a score nobody plays for. It is four numbers; it can afford
    to be standing.

    WHAT IT SAYS IS DELIBERATELY NOT ADVICE. It reports the two totals, the gap,
    this agent's own share of its city's number, and its rank among its own
    neighbours -- the two terms of the objective, measured. What to do about
    being 2,000 behind is the agent's problem; PHASE7 and PHASE8 are both full
    of cases where the fix was to state a fact the code already held, and none
    where the fix was a hint.

    THE RIVAL'S TOTAL AND NOTHING ELSE. No breakdown of who over there is rich,
    what they have founded, or where their ground is free -- an agent cannot act
    on any of it, since there is no road, and a page of unusable detail about
    the enemy is per-call tokens spent on a decision that cannot be made.
    """
    if not world.is_contest():
        return None

    city = world.city_of(agent)
    standings = {row["city"]: row for row in world.city_standings()}
    mine = standings[city]
    rival_key = world.rival_of(city)
    theirs = standings.get(rival_key) if rival_key else None

    # Rank among your OWN neighbours -- the second term of the objective. The
    # global leaderboard is the wrong comparison here: it mixes in a city you
    # are not ranked against and cannot reach.
    neighbours = sorted(
        world.agents_in(city), key=lambda a: -a.net_worth(world)
    )
    place = next(
        (i + 1 for i, a in enumerate(neighbours) if a.id == agent.id), None
    )
    yours = agent.net_worth(world)

    view: dict[str, Any] = {
        "your_city": mine["name"],
        "your_city_total": mine["total_net_worth"],
        "your_share_of_it": round(yours, 2),
        "your_rank_at_home": (
            f"{place} of {len(neighbours)} in {mine['name']}" if place else None
        ),
        "citizens_lost": mine["dead"],
    }
    # EVERY CITY, RANKED (three since 2026-10-16). The standing is against
    # whoever is nearest: the leader is told its lead over second, everyone
    # else how far behind the city above them they are.
    order = sorted(standings.values(), key=lambda r: -r["total_net_worth"])
    view["standings"] = [
        f"{i + 1}. {r['name']} {r['total_net_worth']:,.0f}"
        + (f" ({r['dead']} dead)" if r["dead"] else "")
        for i, r in enumerate(order)
    ]
    pos = next(i for i, r in enumerate(order) if r["city"] == city)
    if len(order) > 1:
        if pos == 0:
            gap = mine["total_net_worth"] - order[1]["total_net_worth"]
            view["standing"] = f"{mine['name']} LEADS {order[1]['name']} by {gap:,.0f}"
        else:
            gap = order[pos - 1]["total_net_worth"] - mine["total_net_worth"]
            view["standing"] = (f"{mine['name']} is BEHIND {order[pos - 1]['name']} "
                                f"by {gap:,.0f}")
    if theirs is not None and len(order) == 2:
        view["rival_city"] = theirs["name"]
        view["rival_city_total"] = theirs["total_net_worth"]
    return view



def _value_bucket(v: float) -> str:
    """Roughly how much a load is worth, as a raider would judge it from the
    road: the size of the cart and the look of it, not an invoice."""
    if v < 50:
        return "a little"
    if v < 200:
        return "~100-200"
    if v < 600:
        return "~200-600"
    if v < 1500:
        return "~600-1,500"
    return "over 1,500"


def _raid_blocks(world: World, log: EventLog, agent: Agent, obs: dict) -> None:
    """What a person needs to raid, or to not be raided (2026-10-16).

    YOUR KIT -- what you fight with, and what is in your pack you could wield.
    YOUR RAID -- if you are lying in wait: where, with whom, for how long.
    RAIDS TO JOIN -- your own city's people lying in wait, and where to stand.
    ON THE ROADS -- loads moving now, roughly how rich and how guarded: the
      intelligence a raider picks targets from, and a defender reads as a list
      of who else is out there.
    RAIDS ON THE ROADS -- the last day's ambushes, by road, with names: who
      robbed whom is known, because the victims saw them.
    """
    from . import raids as R

    armor = [v for v in agent.equipped_armor.values() if v]
    pack = [i for i in agent.inventory if i in D.WEAPONS or i in D.ARMOR]
    obs["you"]["kit"] = {
        "weapon": agent.equipped_weapon or "nothing",
        "armour": armor or "none",
        "fighting_strength": round(R.body_strength(agent), 2),
        **({"in_your_pack_to_equip": pack} if pack else {}),
    }

    if agent.activity.kind == "raid":
        raid = world.raids.get(agent.activity.detail.get("raid"))
        if raid is not None:
            members = R.live_members(world, raid)
            obs["your_raid"] = {
                "raid": raid.id, "road": raid.segment,
                "with": [world.agents[m].name for m in members if m != agent.id] or "nobody yet",
                "hours_left": round((raid.until - world.sim_time) / 3600.0, 1),
                "stolen_so_far": round(raid.takings, 0),
                "note": "abandon_raid to leave; anyone you tell can join_raid from either end",
            }

    home = world.city_of(agent)
    joinable = []
    for r in world.raids.values():
        if r.status != "waiting" or r.until <= world.sim_time or agent.id in r.members:
            continue
        org = world.agents.get(r.organizer)
        if org is None or world.city_of(org) != home:
            continue
        members = R.live_members(world, r)
        if not members:
            continue
        seg = R.segment_named(r.segment)
        joinable.append(
            f"{r.id}: {len(members)} lying in wait on {r.segment} "
            f"(stand at {seg.a} or {seg.b}), {(r.until - world.sim_time) / 3600:.1f}h left, "
            f"strength {sum(R.body_strength(world.agents[m]) for m in members):.1f}"
        )
    if joinable:
        obs["raids_to_join"] = joinable[:4]

    moving = []
    for other in world.agents.values():
        if other.id == agent.id or not other.alive or not other.in_transit:
            continue
        value, _what = B.cargo_at_risk(world, other)
        if value <= 0:
            continue
        o, d, _p = other.in_transit
        try:
            _s, path = M.travel_path(o, d, world.cities)
        except M.NoRoadThere:
            continue
        party = B.party_for(world, other, value)
        eta = (other.activity.ends_at - world.sim_time) / 3600.0
        moving.append((value, (
            f"{other.name} {o} -> {d} via {', '.join(seg.name for seg in path) or 'no road'}: "
            f"{party.vehicle}, {len(other.escorts)} guard(s), load {_value_bucket(value)}, "
            f"arrives in {max(eta, 0):.1f}h"
        )))
    if moving:
        moving.sort(key=lambda kv: -kv[0])
        obs["on_the_roads"] = [line for _v, line in moving[:6]]

    since = world.sim_time - 24 * 3600.0
    names = {a.id: a.name for a in world.agents.values()}
    recent = []
    for ev in reversed(log.events):
        if ev.sim_time < since:
            break
        if ev.type == "robbed" and ev.detail.get("raiders"):
            recent.append(
                f"h{ev.sim_time / 3600:.1f} {names.get(ev.actor, ev.actor)} robbed on "
                f"{ev.detail.get('segment')} by {', '.join(ev.detail['raiders'])} "
                f"({ev.detail.get('value_lost', 0):.0f} taken)"
            )
        elif ev.type == "raid_repelled":
            killed = ev.detail.get("killed") or []
            recent.append(
                f"h{ev.sim_time / 3600:.1f} {names.get(ev.actor, ev.actor)} beat off "
                f"{', '.join(ev.detail.get('raiders') or [])} on {ev.detail.get('segment')}"
                + (f" -- killed {', '.join(killed)}" if killed else "")
            )
        if len(recent) >= 6:
            break
    if recent:
        obs["raids_lately"] = recent


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

    # A STANDING LINE, NOT A NEWS ITEM. World news lives for
    # WORLD_NEWS_WINDOW_HOURS (one hour), so in the 2026-08-21 run every agent
    # whose next decision fell after h37.01 was never told the government had
    # gone at all -- one cryptic key=value row, then silence, against a briefing
    # that went on describing the state for another thirty-five hours. This says
    # it at the top of every observation for the rest of the run.
    gone_at = world.state_gone_at(world.city_of(agent))
    if world.outposts:
        obs_state_gone = (
            "NO TOWNS YET AND NO GOVERNMENT: each market is a state trading "
            "post whose Tavern, Farm, Mine and Refinery sell high, hire at a "
            "fixed wage and buy at half the price between people. Everything "
            "else is another citizen's -- if a thing is going to exist, one of "
            "you makes it."
        )
    elif world.no_state and world.starter_sites:
        obs_state_gone = (
            "NO GOVERNMENT BUT FOUR STATE SITES: its Tavern, Farm, Mine and "
            "Refinery sell high, buy low and hire at a fixed wage. Everything "
            "else is another citizen's -- if a thing is going to exist, one of "
            "you makes it."
        )
    elif world.no_state:
        obs_state_gone = (
            "THERE IS NO GOVERNMENT. Every shop, job, meal and buyer is another "
            "citizen's -- if a thing is going to exist, one of you makes it."
        )
    elif gone_at is not None:
        obs_state_gone = (
            f"THE GOVERNMENT IS GONE. It left the valley at hour "
            f"{gone_at:.0f} and IS NOT COMING BACK. Its "
            f"businesses are demolished, its land is back on the market, and "
            f"nothing buys or sells at a fixed price any more. Nobody is going "
            f"to reopen anything for you."
        )
    else:
        obs_state_gone = None

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
    if agent.calling:
        you["calling"] = f"{agent.calling}: {D.CALLINGS.get(agent.calling, '')} For life."
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

    # THE AGENT'S OWN CITY, worked out once. Everything below that offers an
    # agent a place, a supplier, a plot, a convoy or a price has to be narrowed
    # to the valley it can actually walk in -- there is no road to the other one,
    # so anything from over there is an option that every action would refuse.
    my_city = world.city_of(agent)

    here: dict[str, Any] = {"agents": here_agents, "businesses": here_businesses}
    if len(all_here_agents) > HERE_LIMIT:
        here["more_agents"] = len(all_here_agents) - HERE_LIMIT
    if len(all_here_businesses) > HERE_LIMIT:
        here["more_businesses"] = len(all_here_businesses) - HERE_LIMIT

    obs: dict[str, Any] = {
        "woken_because": reason,
        "hour": round(world.sim_hour, 2),
        "state_gone": obs_state_gone,
        "the_contest": _contest_view(world, agent),
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

    # WHAT'S WORKING, for everyone. See `convoy/digest.py`.
    if world.digest:
        obs["whats_working"] = world.digest.splitlines()
        obs["whats_working_new"] = agent.digest_seen_at < world.digest_at
        if record_delivery:
            agent.digest_seen_at = world.sim_time

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
                    "your home" if p.home
                    else "building" if p.is_building(world.sim_time)
                    else "developed" if p.developed else "raw"
                ),
                "attached_to": p.business,
                "listed_at": p.for_sale_at,
            }
            for p in sorted(my_land, key=lambda x: x.id)[:12]
        ]

    # OUTPOSTS (2026-10-27): where you live, what you owe, how you eat, and the
    # land you could claim next. Per agent, so here and not in the briefing.
    if world.outposts:
        from . import claims as CL
        outpost: dict[str, Any] = {"home": agent.home or "not settled"}
        if agent.debt > 0:
            outpost["you_owe_the_state"] = (
                f"{agent.debt:.2f} -- grows {CL.LOAN_RATE_PER_DAY:.0%} a day; a fifth of what your "
                f"businesses earn pays it down; repay_debt pays more")
        coming = [d for d in world.dispatches.values()
                  if d.agent == agent.id and d.status == "on_way"]
        for d in coming:
            mins = max(1, round((d.arrives_at - world.sim_time) / 60))
            what = (f"{d.item} on its way to you" if d.kind == "meal"
                    else f"the state's convoy coming for {d.qty} {d.item} ({d.unit_price * d.qty:.2f})")
            outpost.setdefault("on_the_way", []).append(f"{what}, in {mins} min")
        meals = sum(q for i, q in agent.inventory.items() if i in D.MEALS)
        if meals:
            outpost["meals_you_carry"] = meals
        food = []
        for t in world.businesses.values():
            if t.closed or t.type != "Tavern / Inn" or M.city_of(t.location) not in world.cities:
                continue
            if t.location == agent.location:
                food.append({"tavern": t.id, "at": t.location, "note": "here: buy_meal"})
                continue
            meal = E.best_meal_for_tier(0 if t.is_government else t.research.quality_tier, "duration")
            price = t.price_for(meal)
            fee = A._meal_fee(world, t, agent.location)
            mins = round(A._dispatch_hours(world, t.location, agent.location, A.MEAL_PREP_H) * 60)
            food.append({"tavern": t.id, "at": t.location, "meal": meal,
                         "brought_to_you": round(price + fee, 2), "minutes": mins})
        food.sort(key=lambda r: r.get("brought_to_you", 0))
        if food:
            outpost["food (order_meal(tavern) to have it brought)"] = food[:4]
        obs["your_outpost"] = outpost
        sites = CL.sites_near(world, agent)
        if sites:
            obs["open_land_near_you"] = sites

    # Land other agents have put up for sale. Without this, `buy_listed_land`
    # is an action whose only argument is unobtainable.
    # Land in any city of this world (roads join them), your own city's first.
    listed = [
        p for p in world.plots.values()
        if p.for_sale_at is not None and p.owner != agent.id
        and M.city_of(p.location) in world.cities
    ]
    listed.sort(key=lambda p: (M.city_of(p.location) != my_city, p.for_sale_at))
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
                    (f"{i} {b.price_for(i):.2f}" + ("" if i in b.retail_prices or b.is_government else " (not on sale)"))
                    for i in (b.spec.outputs or ())
                    if b.is_government or b.inventory.get(i, 0) > 0
                )[:5],
            }
            for b in world.businesses.values()
            if not b.closed and b.spec.outputs and b.id not in agent.owned_businesses
            and any(D.is_intermediate(i) for i in b.spec.outputs)
            # Any city of this world: roads join them now, and a supplier in
            # the next city is real trade -- a longer, more exposed haul.
            and M.city_of(b.location) in world.cities
        ]

    # THE HOUSEHOLD AND KNOW-HOW (2026-10-18). See family.py, progress.py.
    from . import family as FAM
    from . import progress as PG
    if agent.house:
        now = world.sim_time
        def _line(m):
            if not m.adult:
                return (f"{m.id} {m.name}: {m.role or 'child'}, of age in "
                        f"{max(0.0, (m.grown_at - now) / 86400):.1f} days ({m.calling}); "
                        f"feed_family with a Meal to bring it a day sooner")
            bits = [f"{m.id} {m.name}: grown, {m.calling}"]
            bits.append(f"works at {m.works_at}" if m.works_at else "idle at home (assign_family to put them to work)")
            if m.spouse == FAM.HEAD:
                bits.append("your partner")
            elif m.spouse:
                sp = FAM.member(agent, m.spouse)
                bits.append(f"married to {sp.name if sp else '?'}")
            elif m.adult:
                bits.append("unmarried")
            return ", ".join(bits)
        obs["your_house"] = {
            "house": f"{agent.house}, {len(agent.family)} of {FAM.cap(agent)} in the household",
            "members": [_line(m) for m in agent.family] or ["nobody: the house is just you"],
            "allies": [f"{world.agents[a].house} ({a})" for a in agent.allies if a in world.agents] or "none yet",
            "how it grows": ("children are born only to a married couple; marry a grown member to "
                             "another house's with propose_marriage -- theirs joins you, the houses "
                             "become allies. A grown member is also your heir if you die."),
        }
        offers = [o for o in world.marriage_offers.values() if o.target == agent.id and o.status == "open"]
        if offers:
            obs["marriage_proposals_to_you"] = [
                f"{o.id}: {world.agents[o.proposer].house} ({o.proposer}) asks for your "
                f"{(FAM.member(agent, o.their_member) or type('x', (), {'name': '?'})).name} "
                f"to marry their {(FAM.member(world.agents[o.proposer], o.member) or type('x', (), {'name': '?'})).name}, "
                f"dowry {o.dowry:.0f} -- accept_marriage or decline_marriage"
                for o in offers if o.proposer in world.agents]
        if any(m.adult and not m.spouse for m in agent.family):
            city = world.city_of(agent)
            matches = []
            for other in world.agents_in(city):
                if other.id == agent.id or not other.alive or not other.house:
                    continue
                free = [m for m in other.family if m.adult and not m.spouse]
                if free:
                    matches.append(f"{other.house} ({other.id}): " + ", ".join(
                        f"{m.id} {m.name} ({m.calling})" for m in free[:2]))
            if matches:
                obs["houses_you_could_marry_into"] = matches[:6]
    study = agent.researching
    can = [f"{k}: {t['name']} ({t['hours']}h) -- {t['does']}" for k, t in PG.TECHS.items()
           if PG.can_study(agent, k)[0]]
    obs["know_how"] = {
        "studying": (f"{PG.TECHS[study['tech']]['name']}, learned in {PG.research_eta(agent):.1f}h"
                     if study else "nothing -- research(tech) to start; it lands on its own"),
        "known": [PG.TECHS[t]["name"] for t in agent.tech] or "none yet",
        "could_study_next": can[:6],
    }

    # BUY ORDERS (2026-10-17): somebody has named a price for a thing. Shown to
    # the owners who could fill one -- a business of theirs holds it or makes
    # it -- because a bid nobody who can sell sees is a bid that is never filled.
    if agent.owned_businesses:
        mine = [world.businesses[b] for b in agent.owned_businesses
                if b in world.businesses and not world.businesses[b].closed]
        fillable = []
        for o in world.buy_orders.values():
            if o.status != "open" or o.buyer == agent.id:
                continue
            holders = [b for b in mine if b.inventory.get(o.item, 0) > 0 or o.item in (b.spec.outputs or ())]
            if not holders:
                continue
            buyer = world.businesses.get(o.business)
            fillable.append({
                "order": o.id, "wants": f"{o.qty} {o.item} at {o.price:.2f} each",
                "for": f"{buyer.name if buyer else o.business} at {buyer.location if buyer else '?'}",
                "carriage": (f"they pay {o.courier_fee:.2f} to carry it" if o.courier_fee > 0
                             else "they fetch it themselves"),
                "you_hold": ", ".join(f"{b.id} {b.inventory.get(o.item, 0)}" for b in holders),
            })
        if fillable:
            obs["buy_orders_you_can_fill"] = fillable[:8]
        own = [o for o in world.buy_orders.values() if o.buyer == agent.id and o.status == "open"]
        if own:
            obs["your_buy_orders"] = [
                f"{o.id}: {o.qty} of {o.qty_posted} {o.item} still wanted at {o.price:.2f}"
                for o in own
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
    # THE GAP IS YOUR CITY'S GAP. A refinery standing idle in the rival valley
    # is not an answer to "nobody here is making water" -- it is unreachable,
    # unbuyable and irrelevant, and naming it would send an agent to found
    # nothing while it waited for a plant it can never switch on.
    gaps: list[str] = []
    for item in ("Purified Water", "Grain", "Meal"):
        makers = [
            b for b in world.businesses.values()
            if not b.closed and item in b.spec.outputs
            and M.city_of(b.location) == my_city
        ]
        producing = [b for b in makers if b.active_production == item]
        in_stock = [b for b in makers if b.inventory.get(item, 0) > 0]
        if producing or in_stock:
            continue
        maker_type = next(
            (t for t, spec in D.BUSINESS_TYPES.items() if item in spec.outputs), None)
        if maker_type is None:
            continue
        state_only = world.starter_sites and makers and all(b.is_government for b in makers)
        makers = [b for b in makers if not b.is_government] or (
            [] if world.starter_sites else makers)
        if state_only:
            # The state's sites sell at their fixed price whether or not they
            # make anything, and nobody can switch them on: say who supplies it.
            cost = D.BUSINESS_TYPES[maker_type].startup_cost
            where = ("on land you claim_land" if world.outposts
                     else "on free ground")
            gaps.append(
                f"ONLY THE STATE SELLS {item}, at its high fixed price. A "
                f"citizen's {maker_type} ({cost:.0f}, {where}) that undercuts it "
                f"takes its customers."
                + (" You can afford it." if agent.denari >= cost else "")
            )
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
            room = [pl for pl in M.places_in(my_city)
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

    # THE OTHER HALF OF THE GAP: goods you hold that NOBODY USES. In the
    # 2026-10-15 run mines piled up ore for thirty hours after its only buyer
    # left, valued at full price while it could not be sold. Stock is now worth
    # scrap when no business is set up to use it (`economy.realizable_price`),
    # so say so -- an agent watching its net worth fall should know why, and
    # what would fix it: somebody refining it, or stopping making it.
    held: dict[str, int] = dict(agent.inventory)
    for bid in agent.owned_businesses:
        b = world.businesses.get(bid)
        if b is not None and not b.closed:
            for k, q in b.inventory.items():
                held[k] = held.get(k, 0) + q
    used = E.items_in_use(world)
    idle = [
        f"{item} ({qty} held) -- worth scrap until a business uses it or it sells"
        for item, qty in sorted(held.items(), key=lambda kv: -kv[1])
        if qty > 0 and D.is_intermediate(item) and item not in used
        and E.realizable_price(world, item, my_city) < D.base_price(item)
    ]
    if idle:
        obs["nobody_uses"] = idle[:5]

    if not world.npc_bandits:
        _raid_blocks(world, log, agent, obs)

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
    quotes = E.ticker(world, city=my_city)
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
        and M.city_of(p.origin) in world.cities
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
    if cargo_value > 0 and not agent.in_transit and world.npc_bandits:
        party = B.party_for(world, agent, cargo_value)
        # ONLY DESTINATIONS THERE IS A ROAD TO. The rival city's places are in
        # the world but not in this agent's valley, and pricing the risk of a
        # journey nobody can make would put seven impossible routes in front of
        # every agent on every decision.
        #
        # KEYED OFF WHERE THE AGENT IS STANDING, not off its citizenship. The
        # two agree for every agent this simulation creates, and when they do
        # not -- a hand-built world, an older checkpoint, a test fixture that
        # drops somebody on foreign ground -- `route_risk` would be handed a
        # pair with no road between them and raise, killing the whole
        # observation. A route is priced from where you are.
        risks = {
            dest: B.route_risk(agent.location, dest, party).probability
            for dest in M.places_in(M.city_of(agent.location))
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
            # WHAT THE FIX COSTS, beside what it saves. The percentages above
            # have been shown since PHASE7 and bought almost nothing: eight
            # escorts against forty robberies in the 2026-08-21 run. A guard on
            # the Grain corridor costs ~10 denari and saves an expected ~35, and
            # no agent was ever in a position to notice, because the price lived
            # in `banditry.suggested_fee` and the risk lived here.
            worst = max(risks.items(), key=lambda kv: kv[1])[0]
            if not agent.escorts:
                quote = B.guard_quote(agent.location, worst, party)
                block["hiring_a_guard"] = {
                    "for_the_trip_to": worst,
                    "risk_now": f"{quote.unguarded:.0%}",
                    "risk_with_one_guard": f"{quote.guarded:.0%}",
                    "guard_costs": round(quote.price, 2),
                    "expected_cargo_saved": round(quote.expected_saving, 2),
                    "verdict": (
                        "a guard pays for itself on this load"
                        if quote.worth_it else
                        "this load is too cheap to be worth guarding"
                    ),
                    "how": "post_escort_job, or ask in chat who will ride with you",
                }
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
    # Above ADVICE, above YOU, above everything. The withdrawal changes what
    # every other line in the observation means.
    if obs.get("state_gone"):
        lines.insert(1, obs["state_gone"])
    # Advice is named on line one and rendered before anything else. The
    # observation runs past 20,000 characters; a block placed after the price
    # tables is present in the prompt and absent from the decision, which is the
    # exact distinction PHASE4 §2 is a list of.
    if obs.get("whats_working_new"):
        lines[0] += (" A NEW report on WHAT'S WORKING across the world is below: "
                     "check your plan against it.")
    if obs.get("advice"):
        n = len(obs["advice"])
        lines[0] += (
            f" You have {n} piece{'s' if n != 1 else ''} of ADVICE waiting, "
            f"below. Read it before you decide."
        )
    # THIS LIST IS THE PROMPT. A key that is not in it is a block `observe`
    # built, paid for, and threw away -- present in the observation, absent from
    # the decision, which is the exact distinction PHASE4 §2 is a list of.
    #
    # FOUR BLOCKS WERE IN THAT STATE (found 2026-09-03). `nobody_makes`,
    # `on_the_ground_here` and `market_prices` were all added in PHASE8 and none
    # of them was ever added HERE, so three of the four fixes PHASE8 credits for
    # run two's outcome never reached a single prompt. `escort_jobs` had been in
    # the same state since PHASE7. Whatever changed run two's behaviour, it was
    # not those three -- see PHASE9. This is PHASE4 §2 happening to PHASE8's own
    # entries in PHASE4 §2, which is worth stating plainly rather than quietly
    # correcting.
    #
    # THE ORDER IS THE POINT, not the membership. The observation runs past
    # 20,000 characters and a model reads the top of it best, so the things an
    # agent is scored on go first: what it was told, what the score is, what it
    # has, and what is lying at its feet.
    for key, heading in [
        ("advice", "ADVICE FOR YOU (from someone watching -- weigh it, then decide)"),
        ("the_contest", "THE CONTEST (your city against theirs -- this is the score)"),
        ("whats_working", "WHAT'S WORKING ACROSS THE WORLD (a summary everyone gets)"),
        ("you", "YOU"),
        ("your_outpost", "YOUR OUTPOST (where you live, what you owe, how you eat)"),
        ("here", "WHERE YOU ARE"),
        ("on_the_ground_here", "ON THE GROUND HERE, UNCLAIMED (loot_ground takes it)"),
        ("player_prices_here", "PLAYER PRICES HERE"),
        ("market_prices", "WHAT GOODS HAVE ACTUALLY BEEN SELLING FOR"),
        ("your_land", "LAND YOU OWN"),
        ("land_for_sale", "LAND FOR SALE (other agents' asking prices)"),
        ("open_land_near_you", "OPEN LAND NEAR YOU (claim_land(site_id); near people costs more)"),
        ("you_can", "WHAT YOU CAN DO FROM HERE"),
        ("nobody_makes", "WHAT NOBODY IN YOUR CITY IS MAKING"),
        ("nobody_uses", "WHAT YOU HOLD THAT NOBODY USES"),
        ("your_house", "YOUR HOUSE (your family: your first workers, and your heirs)"),
        ("marriage_proposals_to_you", "MARRIAGE PROPOSALS TO YOUR HOUSE"),
        ("houses_you_could_marry_into", "HOUSES WITH SOMEONE TO MARRY (propose_marriage)"),
        ("know_how", "KNOW-HOW (one study at a time; each makes you better at something for good)"),
        ("your_raid", "YOUR RAID (you are lying in wait)"),
        ("raids_to_join", "RAIDS YOUR NEIGHBOURS ARE LYING IN WAIT ON (join_raid)"),
        ("on_the_roads", "LOADS ON THE ROADS RIGHT NOW"),
        ("raids_lately", "RAIDS IN THE LAST DAY"),
        ("taxes_now", "CURRENT TAX RATES"),
        ("where_to_buy_stock", "WHERE TO ORDER FEEDSTOCK (you need not travel)"),
        ("buy_orders_you_can_fill", "BUY ORDERS YOU COULD FILL (fill_buy_order -- paid at their price, at once)"),
        ("your_buy_orders", "YOUR BUY ORDERS STILL OPEN"),
        ("courier_jobs", "HAULAGE JOBS GOING BEGGING"),
        ("escort_jobs", "ESCORT WORK GOING BEGGING (paid passage, if you want it)"),
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
