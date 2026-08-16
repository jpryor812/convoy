"""The executable action layer.

This is the surface an agent's turn resolves onto. In Phase 1 the callers are
deterministic rule-based policies; in Phase 2+ a parsed LLM action maps onto the
exact same functions, so the simulation cannot tell the two apart. Every action
validates against the spreadsheet's rules and returns (ok, message).

Phase 1 implements the economic subset of the ~94-action list: movement, labor,
refining/crafting, trading, and business management. Convoy, combat, theft,
government, and social actions arrive in Phase 3.
"""

from __future__ import annotations

from typing import Any

from . import data as D
from . import economy as E
from . import world_map
from .events import EventLog, Significance
from .state import (
    Activity,
    Agent,
    Business,
    Consignment,
    ChatMessage,
    Employment,
    Guild,
    JobPosting,
    Property,
    StolenStack,
    Transaction,
    TradeOffer,
    VehicleInstance,
    World,
)

Result = tuple[bool, str]


# ---------------------------------------------------------------------------
# MOVEMENT
# ---------------------------------------------------------------------------

def travel_to(world: World, log: EventLog, agent: Agent, destination: str) -> Result:
    if destination not in D.ALL_PLACES:
        return False, f"unknown location {destination!r}"
    if agent.location == destination and not agent.in_transit:
        return False, "already there"

    vehicle_type = None
    if agent.mounted_vehicle:
        vehicle_type = world.vehicles[agent.mounted_vehicle].type
    seconds = E.travel_seconds(agent.location, destination, vehicle_type)
    seconds /= world.government.convoy_speed_modifier

    origin = agent.location
    agent.in_transit = (origin, destination, 0.0)
    agent.activity = Activity(
        "travel", world.sim_time + seconds, {"origin": origin, "destination": destination}
    )
    log.emit(
        world.sim_time, "travel", actor=agent.id, location=origin,
        destination=destination, seconds=round(seconds, 1),
    )
    return True, f"travelling to {destination}"


def mount(world: World, log: EventLog, agent: Agent, vehicle_id: str) -> Result:
    veh = world.vehicles.get(vehicle_id)
    if not veh or veh.owner != agent.id:
        return False, "not your vehicle"
    if veh.location != agent.location:
        return False, "vehicle is elsewhere"
    if veh.condition == "destroyed":
        return False, "vehicle destroyed"
    agent.mounted_vehicle = vehicle_id
    veh.mounted_by = agent.id
    return True, f"mounted {veh.type}"


def dismount(world: World, log: EventLog, agent: Agent) -> Result:
    if not agent.mounted_vehicle:
        return False, "not mounted"
    veh = world.vehicles[agent.mounted_vehicle]
    veh.mounted_by = None
    veh.location = agent.location
    agent.mounted_vehicle = None
    return True, "dismounted"


def wait(world: World, log: EventLog, agent: Agent, seconds: float) -> Result:
    """Do nothing until `seconds` have passed.

    Terminal by convention: `LLMPolicy` ends the decision here rather than
    asking again. Measured, 36% of all actions in the first live run came AFTER
    a wait in the same turn, and every one of them cost a round trip to say
    "and I am still waiting".

    WAITING MUST NEVER CANCEL WHAT IS ALREADY UNDERWAY. `agent.activity` is a
    single slot, so an unconditional write here silently destroyed whatever the
    agent had just committed to:

      * a 'work' activity -- wages accrue ONLY while kind == 'work', so an
        agent that started a shift and then waited clocked itself straight back
        out and earned nothing;
      * a 'travel' activity -- the engine moves the agent and clears
        `in_transit` only from its travel branch, so a cancelled journey could
        neither arrive nor reset. The agent stood at its origin, permanently
        "in transit", forever.

    Both were live in the 2026-08-14 72-hour run: 9 of 12 agents were stranded
    mid-journey and the whole population was earning a fraction of its wage.
    """
    live = agent.activity
    if live.kind in ("work", "travel") and live.ends_at > world.sim_time:
        left = (live.ends_at - world.sim_time) / 3600.0
        doing = "on shift" if live.kind == "work" else "travelling"
        return True, f"still {doing}, {left:.1f}h left -- it continues while you wait"

    # A wait shorter than the re-evaluation interval is worse than useless. The
    # engine wakes an idle agent at its next scheduled re-evaluation regardless,
    # so a shorter wait cannot buy less time -- but an `ends_at` in the near
    # future ALSO trips the activity_complete branch, manufacturing an extra
    # decision that nobody asked for. 596 of the 1,245 waits in the aborted
    # 2026-08-14 run were under the interval, and 45% of every decision in that
    # run was self-inflicted churn. Clamping is honest: it makes the parameter
    # mean what the engine will actually do.
    floor = D.REEVALUATION_INTERVAL_MIN * 60.0
    seconds = max(float(seconds), floor)
    agent.activity = Activity("idle", world.sim_time + seconds)
    return True, f"waiting {seconds:.0f}s"


# Actions that mean "I am done deciding". Continuing past one buys nothing and
# costs an API call, which at Phase 3 volume is the difference between $87 and
# $171 against a $94 budget.
TERMINAL_ACTIONS = frozenset({"wait"})


# ---------------------------------------------------------------------------
# LABOR
# ---------------------------------------------------------------------------

def _usable_items(biz: Business) -> list[str]:
    """Everything this business can either consume as an input or sell."""
    items: set[str] = set(biz.spec.outputs)
    for out in biz.spec.outputs:
        recipe = D.REFINING_RECIPES.get(out) or D.CRAFTING_RECIPES.get(out)
        if recipe:
            items |= set(recipe.inputs)
    return sorted(items)


def _business_can_use(biz: Business, item: str) -> bool:
    return item in _usable_items(biz)


def _may_buy_from(buyer: Business, seller: Business) -> tuple[bool, str]:
    """The chain only runs one way: farm/mine -> refinery -> store.

    Every store type in the game needs REFINED inputs and no raw ones, so a shop
    has no business at a farm gate. Without this rule four taverns spent 156
    denari on Dirty Water they could never use (2026-08-16), because buying it
    was legal and nothing said otherwise. A refinery buys raw from extraction,
    and also buys Charcoal from another refinery -- Bronze and Iron need it.
    """
    if buyer.type in D.EXTRACTION_BUSINESS_TYPES:
        return False, (
            f"a {buyer.type} grows or digs its own goods and buys no inputs"
        )
    if buyer.type == "Refinery":
        if seller.type in D.EXTRACTION_BUSINESS_TYPES or seller.type == "Refinery":
            return True, ""
        return False, (
            f"a Refinery buys raw materials from a Farm or Mining Operation "
            f"(and Charcoal from another Refinery), not from a {seller.type}"
        )
    if seller.type != "Refinery":
        return False, (
            f"a {buyer.type} buys REFINED goods from a Refinery. {seller.type} "
            f"sells raw materials, which only a Refinery can use. Order the "
            f"refined version from a Refinery instead."
        )
    return True, ""


def employee_cap(biz: Business) -> int | None:
    """How many production staff a business may hold. None == uncapped.

    Ownership, not type: the government is a backstop employer and is held to
    a small cap, while anything a player builds may hire freely.
    """
    if biz.is_government:
        return D.GOVERNMENT_MAX_EMPLOYEES
    return None


def apply_for_job(
    world: World, log: EventLog, agent: Agent, business_id: str, role: str = "",
    as_researcher: bool = False,
) -> Result:
    biz = world.businesses.get(business_id)
    if not biz or biz.closed:
        return False, "no such business"
    if agent.current_job:
        return False, "already employed -- quit first"
    if biz.location != agent.location:
        return False, "not at this business"

    spec = biz.spec
    # Omitting the role means "whatever this place hires". Requiring an exact
    # string turned 9 of 13 applications in the 2026-08-14 runs into rejections
    # for naming a real role that this particular business does not employ.
    if not role and not as_researcher:
        if not spec.production_roles:
            return False, f"{biz.type} does not hire production staff"
        role = spec.production_roles[0]
    # Research is a PLAYER-ONLY capability (designer decision, 2026-08-12) --
    # government businesses never unlock tiers, so the state can never out-research
    # the market it exists to backstop.
    if as_researcher and biz.is_government:
        return False, "government businesses have no Research track"
    if as_researcher and not spec.can_research:
        return False, f"{biz.type} has no Research track"
    if not as_researcher and role not in spec.production_roles:
        return False, f"{role} is not a role at {biz.type}"

    # Researchers are a SEPARATE, UNCAPPED headcount pool (Research tab: "No cap
    # on Researcher count"). The Businesses tab's Max Employees column governs
    # PRODUCTION staff only -- applying it to researchers would block the
    # high-research store strategy entirely.
    if not as_researcher:
        cap = employee_cap(biz)
        if cap is not None and len(biz.production_staff()) >= cap:
            return False, f"no vacancy ({len(biz.production_staff())}/{cap} filled)"

    # Wage rules (designer decisions, 2026-08-11):
    #   * An OWNER staffing their own business draws no wage -- they are paid by
    #     owning the output and the profit, not by payroll.
    #   * GOVERNMENT businesses pay the Smart Player Wage, not the inflated NPC
    #     wage. The NPC wage is what it costs to HIRE an NPC, not what the state
    #     pays a person. This leaves headroom above the government rate so a
    #     player-owned business can actually outbid it for labour.
    if agent.id == biz.owner:
        wage = 0.0
    elif biz.is_government:
        wage = E.government_wage(role)
    else:
        wage = max(biz.wages.get(role, E.smart_wage(role)), E.wage_floor(role))

    biz.roster.append(Employment(agent.id, role, wage, as_researcher))
    agent.current_job = (business_id, role, wage)
    log.emit(
        world.sim_time, "hired", actor=agent.id, subject=business_id,
        location=biz.location, role=role, wage=round(wage, 2),
        researcher=as_researcher, employer=biz.name,
    )
    return True, f"hired at {biz.name} as {role} for {wage:.2f}/hr"


def quit_job(world: World, log: EventLog, agent: Agent) -> Result:
    if not agent.current_job:
        return False, "not employed"
    business_id, role, _wage = agent.current_job
    biz = world.businesses.get(business_id)
    if biz:
        biz.roster = [e for e in biz.roster if e.agent_id != agent.id]
    agent.current_job = None
    if agent.activity.kind == "work":
        agent.activity = Activity("idle", world.sim_time)
    log.emit(world.sim_time, "quit_job", actor=agent.id, subject=business_id, role=role)
    return True, "quit"


def start_shift(world: World, log: EventLog, agent: Agent, hours: float = 4.0) -> Result:
    """Begin working. One decision, then silence until the session resolves."""
    if not agent.current_job:
        return False, "not employed"
    business_id, role, _wage = agent.current_job
    biz = world.businesses.get(business_id)
    if not biz or biz.closed:
        agent.current_job = None
        return False, "employer closed"
    if biz.location != agent.location:
        return False, "not at workplace"
    # Already on this shift. Without this the call silently overwrites the
    # activity and pushes ends_at forward, so a model that re-asserts its plan
    # restarts the clock -- 15% of all actions in the first live run.
    # Only refuse while the shift is STILL RUNNING. An expired shift keeps
    # kind == "work" until something replaces it, so checking the kind alone
    # locked an agent out of ever working again: 24 of 50 start_shift calls in
    # the 2026-08-15 smoke were refused, 9 of them "already working this shift,
    # 0.0h left" -- the agent had just been woken BECAUSE the shift ended.
    if (agent.activity.kind == "work"
            and agent.activity.detail.get("business") == business_id
            and agent.activity.ends_at > world.sim_time):
        remaining = (agent.activity.ends_at - world.sim_time) / 3600.0
        return False, f"already working this shift, {remaining:.1f}h left"

    agent.activity = Activity(
        "work", world.sim_time + hours * 3600.0,
        {"business": business_id, "role": role},
    )
    log.emit(
        world.sim_time, "job_started", actor=agent.id, subject=business_id,
        location=biz.location, role=role, hours=hours,
    )
    return True, f"working {hours}h at {biz.name}"


def end_shift(world: World, log: EventLog, agent: Agent) -> Result:
    if agent.activity.kind != "work":
        return False, "not working"
    agent.activity = Activity("idle", world.sim_time)
    return True, "shift ended"


# ---------------------------------------------------------------------------
# TRADING & MARKET
# ---------------------------------------------------------------------------

def is_staffed(world: World, biz: Business) -> bool:
    """Is there anybody here to serve you?

    A shop cannot trade with nobody behind the counter (designer decision,
    2026-08-15). Government businesses are staffed by exemption -- they are the
    market backstop and must never close. For a player's shop it takes the owner
    or an employee standing at the business, or an NPC hire, who is always on.
    """
    if biz.is_government:
        return True
    owner = world.agents.get(biz.owner)
    if owner and owner.alive and owner.location == biz.location:
        return True
    for emp in biz.roster:
        if emp.is_npc:
            return True
        staff = world.agents.get(emp.agent_id)
        if staff and staff.alive and staff.location == biz.location:
            return True
    return False


def buy_from_business(
    world: World, log: EventLog, agent: Agent, business_id: str, item: str, qty: int = 1
) -> Result:
    biz = world.businesses.get(business_id)
    if not biz or biz.closed:
        return False, "no such business"
    if biz.location != agent.location:
        return False, "not at this business"
    if qty <= 0:
        return False, "bad quantity"
    if not is_staffed(world, biz):
        return False, f"{biz.name} is unattended -- nobody is there to sell to you"
    # Feedstock moves between businesses, never over a counter. A business that
    # needs it uses order_from_business, which is what the courier system is for.
    if D.is_intermediate(item):
        return False, (
            f"{item} is feedstock and is not sold to people. A business that "
            f"refines or crafts with it buys it with order_from_business, and a "
            f"courier hauls it."
        )
    if not biz.is_government and biz.inventory.get(item, 0) < qty:
        return False, f"{biz.name} has no {item}"

    unit = biz.price_for(item)
    subtotal = unit * qty
    tax = E.sales_tax_on(subtotal, world.government.sales_tax)
    if agent.denari < subtotal:
        return False, f"cannot afford {qty}x{item} ({subtotal:.2f})"

    capacity = agent.carry_capacity(world)
    if agent.carried_units() + qty > capacity:
        return False, f"carry capacity {capacity} exceeded"

    agent.denari -= subtotal                  # the marked price, nothing on top
    agent.add_item(item, qty)
    if not biz.is_government:
        biz.remove_item(item, qty)
        biz.cash += subtotal - tax            # the seller remits the revenue tax
    world.government.collect(tax)
    world.market.record(Transaction(world.sim_time, item, qty, unit, biz.id, agent.id))
    log.emit(
        world.sim_time, "trade", actor=agent.id, subject=business_id, location=biz.location,
        direction="buy", item=item, qty=qty, unit=round(unit, 2), tax=round(tax, 2),
    )
    if tax:
        log.emit(world.sim_time, "tax_collected", actor=agent.id, kind="sales", amount=round(tax, 2))
    return True, f"bought {qty}x{item} for {subtotal:.2f}"


def sell_to_business(
    world: World, log: EventLog, agent: Agent, business_id: str, item: str, qty: int = 1
) -> Result:
    biz = world.businesses.get(business_id)
    if not biz or biz.closed:
        return False, "no such business"
    if biz.location != agent.location:
        return False, "not at this business"
    if agent.inventory.get(item, 0) < qty:
        return False, f"no {item} to sell"
    # The chain rule has to hold on BOTH doors. Blocking order_from_business
    # alone left this one open: an agent could carry Dirty Water to a Tavern and
    # sell it in over the counter, and the tavern ended up with the same dead
    # stock by another route. The state still buys anything -- it is the
    # universal buyer of last resort, which is what stops goods being unsellable.
    if not biz.is_government and not _business_can_use(biz, item):
        return False, (
            f"{biz.name} has no use for {item}. A {biz.type} takes only "
            f"{', '.join(_usable_items(biz)) or 'nothing'}. The state buys "
            f"anything if you just want rid of it."
        )

    unit = biz.buy_price_for(item)
    proceeds = unit * qty
    if not biz.is_government:
        if biz.cash < proceeds:
            return False, f"{biz.name} cannot afford it"
        biz.cash -= proceeds
        biz.add_item(item, qty)

    agent.remove_item(item, qty)
    agent.denari += proceeds
    world.market.record(Transaction(world.sim_time, item, qty, unit, agent.id, biz.id))
    log.emit(
        world.sim_time, "trade", actor=agent.id, subject=business_id, location=biz.location,
        direction="sell", item=item, qty=qty, unit=round(unit, 2),
    )
    return True, f"sold {qty}x{item} for {proceeds:.2f}"


def set_retail_price(
    world: World, log: EventLog, agent: Agent, business_id: str, item: str, price: float
) -> Result:
    biz = world.businesses.get(business_id)
    if not biz or biz.owner != agent.id:
        return False, "not your business"
    floor = E.player_price_floor(item)
    if price < floor:
        return False, f"below the {D.PLAYER_STORE_FLOOR_PCT:.0%} price floor ({floor:.2f})"
    biz.retail_prices[item] = price
    log.emit(
        world.sim_time, "price_set", actor=agent.id, subject=business_id,
        item=item, price=round(price, 2),
    )
    return True, f"{item} priced at {price:.2f}"


# ---------------------------------------------------------------------------
# BUSINESS MANAGEMENT
# ---------------------------------------------------------------------------

def start_business(
    world: World, log: EventLog, agent: Agent, type: str, seed_cash: float = 0.0
) -> Result:
    spec = D.BUSINESS_TYPES.get(type)
    if not spec:
        return False, f"unknown business type {type!r}"

    # Mines and farms are worked land -- they only exist down a spur, and they
    # take eight plots of it. Everything else sits on the main road.
    plots = 0
    if type in world_map.PLOT_CONSUMING_BUSINESSES:
        if not D.is_spur(agent.location):
            return False, f"a {type} can only be founded down a spur road"
        free = world_map.plots_free(world, agent.location)
        if free < world_map.SITE_BASE_PLOTS:
            return False, (
                f"{agent.location} has only {free} plots left; a {type} needs "
                f"{world_map.SITE_BASE_PLOTS}"
            )
        plots = world_map.SITE_BASE_PLOTS
    elif D.is_spur(agent.location):
        return False, f"a {type} belongs on the main road, not down a spur"

    total = spec.startup_cost + seed_cash
    if agent.denari < total:
        return False, f"need {total:.0f} to found a {type}"

    agent.denari -= total
    biz = Business(
        id=world.new_id("B"),
        type=type,
        name=f"{agent.name}'s {type}",
        owner=agent.id,
        location=agent.location,
        cash=seed_cash,
        plots=plots,
    )
    world.businesses[biz.id] = biz
    agent.owned_businesses.append(biz.id)
    log.emit(
        world.sim_time, "business_founded", actor=agent.id, subject=biz.id,
        location=agent.location, business_type=type, cost=spec.startup_cost, seed=seed_cash,
    )
    return True, f"founded {biz.name}"


def expand_site(
    world: World, log: EventLog, agent: Agent, business_id: str
) -> Result:
    """Buy more land for a mine or farm: +4 plots, and more room to stockpile.

    Storage is the point. A worked site holds only so much before production
    stalls for want of anywhere to put the output, so expanding buys time
    between hauling runs -- which is what makes a distant, high-yield claim
    workable at all.
    """
    biz = world.businesses.get(business_id)
    if not biz or biz.closed or biz.owner != agent.id:
        return False, "not your business"
    if biz.type not in world_map.PLOT_CONSUMING_BUSINESSES:
        return False, f"a {biz.type} sits on the main road and cannot expand"

    add = world_map.SITE_EXPANSION_PLOTS
    free = world_map.plots_free(world, biz.location)
    if free < add:
        return False, f"{biz.location} has only {free} plots left"

    cost = D.SITE_EXPANSION_COST
    if agent.denari < cost:
        return False, f"expanding costs {cost:.0f} Denari"

    agent.denari -= cost
    biz.plots += add
    log.emit(
        world.sim_time, "site_expanded", actor=agent.id, subject=biz.id,
        location=biz.location, plots=biz.plots,
        capacity=E.site_storage_capacity(biz.plots), cost=cost,
    )
    return True, f"{biz.name} expanded to {biz.plots} plots"


def set_production(
    world: World, log: EventLog, agent: Agent, business_id: str, output: str
) -> Result:
    biz = world.businesses.get(business_id)
    if not biz or biz.owner != agent.id:
        return False, "not your business"
    if output not in biz.spec.outputs:
        return False, f"{biz.type} cannot produce {output}"
    biz.active_production = output
    biz.production_buffer = 0.0
    return True, f"{biz.name} now producing {output}"


def set_wage(
    world: World, log: EventLog, agent: Agent, business_id: str, role: str, wage: float
) -> Result:
    biz = world.businesses.get(business_id)
    if not biz or biz.owner != agent.id:
        return False, "not your business"
    floor = E.wage_floor(role)
    if wage < floor:
        return False, f"below the wage floor for {role} ({floor:.2f})"
    biz.wages[role] = wage
    return True, f"{role} wage set to {wage:.2f}"


def post_job(
    world: World, log: EventLog, agent: Agent, business_id: str, role: str,
    wage: float, as_researcher: bool = False,
) -> Result:
    """Advertise a role at a wage on the world job board, seen by every agent.

    This is the only way an agent employee can learn that a player business is
    hiring, and at what rate. It writes a world-chat line carrying the posting
    id, so anyone can answer it with apply_to_job.
    """
    biz = world.businesses.get(business_id)
    if not biz or biz.closed or biz.owner != agent.id:
        return False, "not your business"
    spec = biz.spec
    if as_researcher and not spec.can_research:
        return False, f"{biz.type} has no Research track"
    if not as_researcher and role not in spec.production_roles:
        return False, (
            f"{role} is not a role at {biz.type}. It hires: "
            f"{', '.join(spec.production_roles) or 'nobody'}"
        )
    floor = E.wage_floor(role)
    if wage < floor:
        return False, f"below the wage floor for {role} ({floor:.2f})"
    if not as_researcher:
        cap = employee_cap(biz)
        if cap is not None and len(biz.production_staff()) >= cap:
            return False, f"no vacancy ({len(biz.production_staff())}/{cap} filled)"
    for p in world.job_postings.values():
        if (p.business_id == business_id and p.role == role
                and p.is_live(world.sim_time)):
            return False, (
                f"{p.id} is already advertising {role} at {p.wage:.2f}. "
                f"close_job first if you want to change the wage."
            )

    pid = world.new_id("J")
    posting = JobPosting(
        id=pid, business_id=business_id, owner=agent.id, role=role,
        wage=round(wage, 2), posted_at=world.sim_time,
        expires_at=world.sim_time + D.JOB_POSTING_HOURS * 3600.0,
        as_researcher=as_researcher,
    )
    world.job_postings[pid] = posting
    text = (
        f"HIRING: {role} at {biz.name} ({biz.location}) for {wage:.2f}/hr. "
        f"apply_to_job(\"{pid}\") to apply."
    )
    world.chat.append(ChatMessage(
        sim_time=world.sim_time, channel="world", sender=agent.id,
        sender_name=agent.name, text=text,
    ))
    log.emit(
        world.sim_time, "job_posted", actor=agent.id, subject=business_id,
        posting=pid, role=role, wage=round(wage, 2), location=biz.location,
    )
    return True, (
        f"posted {pid}: {role} at {wage:.2f}/hr, on the board for "
        f"{D.JOB_POSTING_HOURS:.0f}h. Applicants appear in your observation; "
        f"hire_applicant to take one, or close_job and repost at a new wage."
    )


def apply_to_job(world: World, log: EventLog, agent: Agent, posting_id: str) -> Result:
    """Answer a job advert. The owner still chooses -- this is not a hire."""
    p = world.job_postings.get(posting_id)
    if not p:
        return False, "no such job posting"
    if not p.is_live(world.sim_time):
        return False, f"{posting_id} is {p.status if p.status != 'open' else 'expired'}"
    if agent.id == p.owner:
        return False, "you cannot apply to your own posting"
    if agent.id in p.applicants:
        return False, f"you have already applied to {posting_id}"
    p.applicants.append(agent.id)
    biz = world.businesses.get(p.business_id)
    log.emit(
        world.sim_time, "job_applied", actor=agent.id, subject=p.business_id,
        posting=posting_id, role=p.role, wage=p.wage,
    )
    where = biz.location if biz else "?"
    return True, (
        f"applied to {posting_id} ({p.role} at {p.wage:.2f}/hr, {where}). "
        f"The owner decides; you are not hired yet and may apply elsewhere."
    )


def hire_applicant(
    world: World, log: EventLog, agent: Agent, posting_id: str, applicant_id: str,
) -> Result:
    """Take one of the people who answered your advert, at the posted wage."""
    p = world.job_postings.get(posting_id)
    if not p:
        return False, "no such job posting"
    if p.owner != agent.id:
        return False, "not your posting"
    if p.status != "open":
        return False, f"{posting_id} is {p.status}"
    if applicant_id not in p.applicants:
        return False, (
            f"{applicant_id} has not applied to {posting_id}. Applicants: "
            f"{', '.join(p.applicants) or 'none yet'}"
        )
    biz = world.businesses.get(p.business_id)
    if not biz or biz.closed:
        return False, "that business is gone"
    hire = world.agents.get(applicant_id)
    if not hire or not hire.alive:
        return False, "that agent is not available"
    if hire.current_job:
        return False, f"{applicant_id} has taken another job since applying"
    if not p.as_researcher:
        cap = employee_cap(biz)
        if cap is not None and len(biz.production_staff()) >= cap:
            return False, f"no vacancy ({len(biz.production_staff())}/{cap} filled)"

    biz.roster.append(Employment(hire.id, p.role, p.wage, p.as_researcher))
    hire.current_job = (biz.id, p.role, p.wage)
    biz.wages[p.role] = p.wage
    p.status = "filled"
    log.emit(
        world.sim_time, "hired", actor=hire.id, subject=biz.id,
        role=p.role, wage=p.wage, employer=biz.name, via=posting_id,
    )
    return True, (
        f"hired {hire.name} as {p.role} at {p.wage:.2f}/hr. They must be AT "
        f"{biz.location} and on shift to work and to be paid."
    )


def close_job(world: World, log: EventLog, agent: Agent, posting_id: str) -> Result:
    """Pull an advert, usually to repost at a different wage."""
    p = world.job_postings.get(posting_id)
    if not p:
        return False, "no such job posting"
    if p.owner != agent.id:
        return False, "not your posting"
    if p.status != "open":
        return False, f"{posting_id} is already {p.status}"
    p.status = "closed"
    log.emit(
        world.sim_time, "job_closed", actor=agent.id, subject=p.business_id,
        posting=posting_id, role=p.role, wage=p.wage,
        applicants=len(p.applicants),
    )
    return True, f"closed {posting_id}. You can post_job again at a new wage."


def hire_npc_employee(
    world: World, log: EventLog, agent: Agent, business_id: str, role: str,
    as_researcher: bool = False,
) -> Result:
    """Hire an NPC at the NPC wage -- always on shift, no agent needed.

    NPC employees cost NPC_WAGE_MULTIPLIER times the smart player wage, which is
    the whole point: convenience at a premium, paid out of business cash.
    """
    biz = world.businesses.get(business_id)
    if not biz or biz.closed or biz.owner != agent.id:
        return False, "not your business"
    spec = biz.spec
    # Research is a PLAYER-ONLY capability (designer decision, 2026-08-12) --
    # government businesses never unlock tiers, so the state can never out-research
    # the market it exists to backstop.
    if as_researcher and biz.is_government:
        return False, "government businesses have no Research track"
    if as_researcher and not spec.can_research:
        return False, f"{biz.type} has no Research track"
    if not as_researcher and role not in spec.production_roles:
        return False, f"{role} is not a role at {biz.type}"
    # Researchers are a SEPARATE, UNCAPPED headcount pool (Research tab: "No cap
    # on Researcher count"). The Businesses tab's Max Employees column governs
    # PRODUCTION staff only -- applying it to researchers would block the
    # high-research store strategy entirely.
    if not as_researcher:
        cap = employee_cap(biz)
        if cap is not None and len(biz.production_staff()) >= cap:
            return False, f"no vacancy ({len(biz.production_staff())}/{cap} filled)"

    wage = E.npc_wage(role)
    biz.roster.append(Employment("NPC", role, wage, as_researcher, is_npc=True))
    log.emit(
        world.sim_time, "hired", actor=agent.id, subject=business_id,
        location=biz.location, role=role, wage=round(wage, 2),
        researcher=as_researcher, employer=biz.name, npc=True,
    )
    return True, f"hired an NPC {role} at {wage:.2f}/hr"


def allocate_research(
    world: World, log: EventLog, agent: Agent, business_id: str, track: str
) -> Result:
    """Spend accumulated RP to advance one Research track by a tier.

    The Research tab says the owner "spends accumulated RP on either track", and
    gives cumulative RP thresholds per tier. Stated assumption, flagged: RP is a
    CURRENCY -- advancing Efficiency to Tier 1 costs 150 RP, and advancing
    Quality to Tier 1 costs a further 150. The two tracks therefore progress
    independently and compete for the same pool, which is what makes the choice
    between "produce faster" and "produce better" a real decision.
    """
    if track not in ("efficiency", "quality"):
        return False, "track must be 'efficiency' or 'quality'"
    biz = world.businesses.get(business_id)
    if not biz or biz.closed or biz.owner != agent.id:
        return False, "not your business"
    if not biz.spec.can_research:
        return False, f"{biz.type} has no Research track"

    current = getattr(biz.research, f"{track}_tier")
    if current >= len(D.RESEARCH_TIERS):
        return False, f"{track} already at max tier"
    next_tier = D.RESEARCH_TIERS[current]
    prev_cost = D.RESEARCH_TIERS[current - 1].cumulative_rp if current > 0 else 0.0
    cost = next_tier.cumulative_rp - prev_cost

    if biz.research.unspent_rp < cost:
        return False, (
            f"need {cost:.0f} RP for {track} tier {next_tier.tier}, "
            f"have {biz.research.unspent_rp:.0f}"
        )

    biz.research.unspent_rp -= cost
    setattr(biz.research, f"{track}_tier", next_tier.tier)
    log.emit(
        world.sim_time, "research_allocated", actor=agent.id, subject=business_id,
        business=biz.name, track=track, tier=next_tier.tier,
        tag=next_tier.tag, spent=cost,
    )
    return True, f"{biz.name} reached {track} tier {next_tier.tier}"


def loot_ground(world: World, log: EventLog, agent: Agent) -> Result:
    """Pick up whatever a dead agent dropped at this location."""
    pile = world.ground_loot.get(agent.location)
    if not pile or (not pile["items"] and pile["denari"] <= 0):
        return False, "nothing here"

    denari = pile["denari"]
    agent.denari += denari
    pile["denari"] = 0.0

    taken: dict[str, int] = {}
    space = agent.carry_capacity(world) - agent.carried_units()
    for item in list(pile["items"]):
        if space <= 0:
            break
        qty = min(pile["items"][item], space)
        agent.add_item(item, qty)
        pile["items"][item] -= qty
        if pile["items"][item] <= 0:
            del pile["items"][item]
        taken[item] = qty
        space -= qty

    # Nothing actually moved -- no space, or nothing worth taking. Report failure
    # so a caller does not sit in a loop "looting" a pile it cannot carry.
    if not taken and denari <= 0:
        return False, "no room to carry any of it"

    log.emit(
        world.sim_time, "looted", actor=agent.id, location=agent.location,
        denari=round(denari, 2), items=taken,
    )
    return True, f"looted {sum(taken.values())} units and {denari:.2f} Denari"


def deposit(world: World, log: EventLog, agent: Agent, business_id: str, amount: float) -> Result:
    biz = world.businesses.get(business_id)
    if not biz or biz.owner != agent.id:
        return False, "not your business"
    if amount <= 0 or agent.denari < amount:
        return False, "insufficient funds"
    agent.denari -= amount
    biz.cash += amount
    if biz.cash >= 0:
        biz.insolvent_since = None
    return True, f"deposited {amount:.2f}"


def withdraw(world: World, log: EventLog, agent: Agent, business_id: str, amount: float) -> Result:
    biz = world.businesses.get(business_id)
    if not biz or biz.owner != agent.id:
        return False, "not your business"
    if amount <= 0 or biz.cash < amount:
        return False, "insufficient business cash"
    biz.cash -= amount
    agent.denari += amount
    return True, f"withdrew {amount:.2f}"


def collect_business_inventory(
    world: World, log: EventLog, agent: Agent, business_id: str, item: str, qty: int
) -> Result:
    """Owner moves goods from the business into personal inventory, to haul and sell."""
    biz = world.businesses.get(business_id)
    if not biz or biz.owner != agent.id:
        return False, "not your business"
    if biz.location != agent.location:
        return False, "not at the business"
    have = biz.inventory.get(item, 0)
    qty = min(qty, have, agent.carry_capacity(world) - agent.carried_units())
    if qty <= 0:
        return False, "nothing to collect or no capacity"
    biz.remove_item(item, qty)
    agent.add_item(item, qty)
    return True, f"collected {qty}x{item}"


def stock_business_inventory(
    world: World, log: EventLog, agent: Agent, business_id: str, item: str, qty: int
) -> Result:
    """Owner moves personal inventory into the business (e.g. refinery feedstock)."""
    biz = world.businesses.get(business_id)
    if not biz or biz.owner != agent.id:
        return False, "not your business"
    if biz.location != agent.location:
        return False, "not at the business"
    qty = min(qty, agent.inventory.get(item, 0))
    if qty <= 0:
        return False, "nothing to stock"
    agent.remove_item(item, qty)
    biz.add_item(item, qty)
    return True, f"stocked {qty}x{item}"


# ---------------------------------------------------------------------------
# VEHICLES & PROPERTY
# ---------------------------------------------------------------------------

def buy_vehicle(world: World, log: EventLog, agent: Agent, vehicle_type: str) -> Result:
    spec = D.VEHICLES.get(vehicle_type)
    if not spec or vehicle_type == "On Foot":
        return False, "not purchasable"
    dealer = None
    for b in world.businesses_at(agent.location, "Vehicle Dealer / Stable"):
        if b.is_government or b.inventory.get(vehicle_type, 0) > 0:
            dealer = b
            break
    if not dealer:
        return False, "no stable here"

    unit = dealer.price_for(vehicle_type)
    tax = E.sales_tax_on(unit, world.government.sales_tax)
    if agent.denari < unit:
        return False, f"cannot afford {vehicle_type} ({unit:.2f})"

    agent.denari -= unit
    if not dealer.is_government:
        dealer.remove_item(vehicle_type, 1)
        dealer.cash += unit - tax
    world.government.collect(tax)

    veh = VehicleInstance(
        id=world.new_id("V"), type=vehicle_type, owner=agent.id, location=agent.location
    )
    world.vehicles[veh.id] = veh
    agent.owned_vehicles.append(veh.id)
    log.emit(
        world.sim_time, "vehicle_purchased", actor=agent.id, subject=veh.id,
        location=agent.location, vehicle_type=vehicle_type, price=round(unit, 2),
    )
    return True, f"bought a {vehicle_type}"


def equip_tools(world: World, log: EventLog, agent: Agent) -> Result:
    """Equip an Upgraded Tools set for a permanent extraction speed bonus.

    The Resources tab lists Wood as feeding "tools" and the Production Chain
    sells Upgraded Tools, but nothing ever consumed them -- this wires the
    Equipment Store's only product to the effect it always claimed.
    """
    if agent.equipped_tools:
        return False, "already using upgraded tools"
    if not agent.remove_item("Upgraded Tools", 1):
        return False, "no Upgraded Tools to equip"
    agent.equipped_tools = True
    log.emit(
        world.sim_time, "tools_equipped", actor=agent.id, location=agent.location,
        bonus=D.TOOL_EXTRACTION_BONUS,
    )
    return True, f"equipped tools (+{D.TOOL_EXTRACTION_BONUS:.0%} extraction)"


def _pay_upgrade(world: World, log: EventLog, agent: Agent, prop: Property,
                 kind: str, tier: int, cost: float, inputs: dict[str, int]) -> Result:
    """Charge the Denari delta plus the tier's materials, or one packaged kit.

    Every tier also takes another plot of land -- a bigger house occupies more
    ground, so a home can outgrow a crowded spur.
    """
    if agent.denari < cost:
        return False, f"need {cost:.0f} Denari for {kind} tier {tier}"
    if world_map.plots_free(world, prop.location) < 1:
        return False, f"no land left on {prop.location} to expand into"

    pool = accessible_goods(world, agent)
    used_kit = False
    if all(pool.get(i, 0) >= q for i, q in inputs.items()):
        pass
    elif pool.get(D.PROPERTY_UPGRADE_KIT, 0) >= 1:
        used_kit = True
    else:
        missing = ", ".join(
            f"{q}x {i}" for i, q in inputs.items() if pool.get(i, 0) < q
        )
        return False, f"missing materials ({missing}) and no {D.PROPERTY_UPGRADE_KIT}"

    agent.denari -= cost
    if used_kit:
        _take_from_accessible(world, agent, D.PROPERTY_UPGRADE_KIT, 1)
    else:
        for item, qty in inputs.items():
            _take_from_accessible(world, agent, item, qty)

    prop.plots += 1
    log.emit(
        world.sim_time, "property_upgraded", actor=agent.id, subject=prop.id,
        location=prop.location, kind=kind, tier=tier, cost=round(cost, 2),
        used_kit=used_kit, plots=prop.plots,
    )
    return True, f"{kind} upgraded to tier {tier}"


def upgrade_storage(world: World, log: EventLog, agent: Agent) -> Result:
    """Raise home storage a tier: 20 -> 70 -> 170 -> 370 units."""
    prop = world.properties.get(agent.owned_property) if agent.owned_property else None
    if prop is None:
        return False, "you do not own a property"
    if prop.location != agent.location:
        return False, "not at your property"
    tier = prop.storage_tier + 1
    if tier > 3:
        return False, "storage already at tier 3"

    total, _cap = D.STORAGE_TIERS[tier]
    already = D.STORAGE_TIERS[tier - 1][0] if tier > 1 else 0.0
    ok, msg = _pay_upgrade(
        world, log, agent, prop, "storage", tier, total - already,
        D.STORAGE_TIER_INPUTS[tier],
    )
    if ok:
        prop.storage_tier = tier
        prop.upgrades.append(f"Storage Tier {tier}")
    return ok, msg


def upgrade_garage(world: World, log: EventLog, agent: Agent) -> Result:
    """Raise garage a tier: 0 -> 1 -> 2 -> 3 vehicle slots."""
    prop = world.properties.get(agent.owned_property) if agent.owned_property else None
    if prop is None:
        return False, "you do not own a property"
    if prop.location != agent.location:
        return False, "not at your property"
    tier = prop.garage_tier + 1
    if tier > 3:
        return False, "garage already at tier 3"

    total, _slots = D.GARAGE_TIERS[tier]
    already = D.GARAGE_TIERS[tier - 1][0] if tier > 1 else 0.0
    ok, msg = _pay_upgrade(
        world, log, agent, prop, "garage", tier, total - already,
        D.GARAGE_TIER_INPUTS[tier],
    )
    if ok:
        prop.garage_tier = tier
        prop.upgrades.append(f"Garage Tier {tier}")
    return ok, msg


def buy_property(world: World, log: EventLog, agent: Agent) -> Result:
    """Buy a plot. Homes only exist down the spur roads, never on the main road.

    Where you settle is a real trade-off: Kiln Row puts you on Town's doorstep,
    Copper Gulch puts you next to the ore but five minutes from a buyer, and
    Eagle's Rest is cheap ground overlooking the worst stretch of the road.
    """
    if agent.owned_property:
        return False, "already own a property (max 1)"
    if not D.is_spur(agent.location):
        return False, "homes are only built down the spur roads"

    spur = world_map.SPUR_BY_NAME[agent.location]
    free = world_map.plots_free(world, agent.location)
    if free < world_map.HOME_BASE_PLOTS:
        return False, (
            f"{spur.name} has only {free} plots left; a home needs "
            f"{world_map.HOME_BASE_PLOTS}"
        )
    if agent.denari < D.PROPERTY_BASE_COST:
        return False, "cannot afford a property"
    agent.denari -= D.PROPERTY_BASE_COST
    prop = Property(
        id=world.new_id("P"), owner=agent.id, location=agent.location,
        plots=world_map.HOME_BASE_PLOTS,
    )
    world.properties[prop.id] = prop
    agent.owned_property = prop.id
    log.emit(
        world.sim_time, "property_purchased", actor=agent.id, subject=prop.id,
        location=agent.location, price=D.PROPERTY_BASE_COST,
    )
    return True, "bought a property"


# ---------------------------------------------------------------------------
# SURVIVAL / SUSTENANCE
# ---------------------------------------------------------------------------

def _apply_meal(world: World, log: EventLog, agent: Agent, meal: str, window: float,
                cost: float, source: str) -> Result:
    agent.hours_since_last_meal = 0.0
    agent.last_meal_window = window
    agent.sustenance_stage = "Normal"

    # Researched variants carry an effect beyond the window.
    spec = D.MEALS.get(meal)
    healed = 0.0
    agent.meal_work_bonus = 0.0
    if spec:
        if spec.heal:
            before = agent.health
            agent.health = min(100.0, agent.health + spec.heal)
            healed = agent.health - before
        agent.meal_work_bonus = spec.work_bonus

    log.emit(
        world.sim_time, "ate", actor=agent.id, location=agent.location,
        meal=meal, window_hours=window, cost=round(cost, 2), source=source,
        healed=round(healed, 1), work_bonus=agent.meal_work_bonus,
    )
    detail = f"{window:.0f}h window"
    if healed:
        detail += f", +{healed:.0f} HP"
    if agent.meal_work_bonus:
        detail += f", +{agent.meal_work_bonus:.0%} work"
    return True, f"ate {meal} ({detail})"


def eat_self_prep(world: World, log: EventLog, agent: Agent) -> Result:
    """Free DIY meal: consumes Grain + Water from own inventory, 12-hour window."""
    for item, qty in D.SELF_PREP_INPUTS.items():
        if agent.inventory.get(item, 0) < qty:
            return False, f"need {item} to self-prep"
    for item, qty in D.SELF_PREP_INPUTS.items():
        agent.remove_item(item, qty)
    return _apply_meal(
        world, log, agent, "Self-Prep", D.SELF_PREP_WINDOW_HOURS, 0.0, "self-prep"
    )


def buy_meal(world: World, log: EventLog, agent: Agent, business_id: str | None = None,
             prefer: str = "duration", meal: str | None = None) -> Result:
    """Buy and eat a meal at a Tavern.

    `prefer` chooses which researched line to ask for -- 'duration' for the
    longest window, 'hearty' to heal, 'laborer' for a production bonus -- or pass
    `meal` to name one exactly. A Tavern can only serve up to its Quality tier.
    """
    if business_id:
        tavern = world.businesses.get(business_id)
    else:
        taverns = world.businesses_at(agent.location, "Tavern / Inn")
        tavern = taverns[0] if taverns else None
    if not tavern or tavern.closed:
        return False, "no tavern here"
    if not is_staffed(world, tavern):
        return False, f"{tavern.name} is unattended -- nobody is serving"

    quality_tier = 0 if tavern.is_government else tavern.research.quality_tier
    if meal is not None:
        spec = D.MEALS.get(meal)
        if spec is None:
            return False, f"unknown meal {meal!r}"
        if spec.required_tier > quality_tier:
            return False, f"{tavern.name} cannot serve {meal} (needs Quality tier {spec.required_tier})"
    else:
        meal = E.best_meal_for_tier(quality_tier, prefer)
    # The tavern's OWN price, not the base rate. Using E.meal_price here meant
    # every tavern in the world charged identically, so a player tavern could
    # not undercut the state and there was no reason to found one. The state
    # charges the marked-up NPC rate; a player charges whatever they set, down
    # to the 60% floor.
    price = tavern.price_for(meal)
    tax = E.sales_tax_on(price, world.government.sales_tax)
    if agent.denari < price:
        return False, f"cannot afford {meal} ({price:.2f})"

    # A player-owned tavern must actually have the food in stock.
    if not tavern.is_government:
        if tavern.inventory.get(meal, 0) < 1:
            return False, f"{tavern.name} is out of {meal}"
        tavern.remove_item(meal, 1)
        tavern.cash += price - tax

    agent.denari -= price
    world.government.collect(tax)
    world.market.record(Transaction(world.sim_time, meal, 1, price, tavern.id, agent.id))
    return _apply_meal(world, log, agent, meal, E.meal_window(meal), price, tavern.name)


def eat_best_available(world: World, log: EventLog, agent: Agent) -> Result:
    """Self-prep if we're holding the ingredients, otherwise buy at a local tavern."""
    ok, msg = buy_meal(world, log, agent)
    if ok:
        return ok, msg
    return False, (
        f"{msg}. Food is served at Taverns only -- travel to one to eat. "
        f"The state's Tavern is at {world_map.GOVERNMENT_SITES['Tavern / Inn']}."
    )


# ---------------------------------------------------------------------------
# CHAT -- three channels
# ---------------------------------------------------------------------------
#
# Per the Actions tab, READING chat is available context every turn, not a
# callable action -- see `visible_chat` below, which the observation layer feeds
# to every agent. Only POSTING is an action.

MAX_CHAT_CHARS = 400


def _post(world: World, log: EventLog, agent: Agent, channel: str, text: str,
          guild_id: str | None = None, recipient: str | None = None) -> Result:
    text = text.strip()
    if not text:
        return False, "empty message"
    if len(text) > MAX_CHAT_CHARS:
        text = text[:MAX_CHAT_CHARS]
    msg = ChatMessage(
        sim_time=world.sim_time, channel=channel, sender=agent.id,
        sender_name=agent.name, text=text, guild_id=guild_id, recipient=recipient,
    )
    world.chat.append(msg)
    log.emit(
        world.sim_time, "chat", actor=agent.id, location=agent.location,
        channel=channel, text=text, recipient=recipient, guild=guild_id,
    )
    return True, "posted"


def post_world_chat(world: World, log: EventLog, agent: Agent, text: str) -> Result:
    """Open-world chat -- every living agent can read this."""
    return _post(world, log, agent, "world", text)


def send_direct_message(
    world: World, log: EventLog, agent: Agent, target_id: str, text: str
) -> Result:
    """Private one-to-one message. No co-location required -- it's a message."""
    target = world.agents.get(target_id)
    if target is None:
        return False, "no such agent"
    if target_id == agent.id:
        return False, "cannot message yourself"
    return _post(world, log, agent, "direct", text, recipient=target_id)


def post_guild_chat(world: World, log: EventLog, agent: Agent, text: str) -> Result:
    """Guild-only channel. Readable solely by current members."""
    if not agent.guild:
        return False, "not in a guild"
    return _post(world, log, agent, "guild", text, guild_id=agent.guild)


def visible_chat(world: World, agent: Agent, since: float = 0.0, limit: int = 40):
    """Every message this agent is allowed to see, oldest first.

    World chat is public; direct messages only to the two parties; guild chat
    only to current members -- so leaving a guild cuts off its history.
    """
    msgs = [m for m in world.chat if m.sim_time >= since and m.visible_to(agent)]
    return msgs[-limit:]


# ---------------------------------------------------------------------------
# GUILDS -- invite only
# ---------------------------------------------------------------------------

def create_guild(world: World, log: EventLog, agent: Agent, name: str) -> Result:
    if agent.guild:
        return False, "already in a guild"
    guild = Guild(id=world.new_id("GU"), name=name, leader=agent.id, members=[agent.id])
    world.guilds[guild.id] = guild
    agent.guild = guild.id
    agent.is_guild_leader = True
    log.emit(
        world.sim_time, "guild_created", actor=agent.id, subject=guild.id, name=name
    )
    return True, f"founded guild {name}"


def invite_to_guild(
    world: World, log: EventLog, agent: Agent, target_id: str
) -> Result:
    """Only the leader may invite. Membership is invite-only -- there is no
    way to join a guild without being asked first."""
    if not agent.guild or not agent.is_guild_leader:
        return False, "only the guild leader can invite"
    guild = world.guilds.get(agent.guild)
    target = world.agents.get(target_id)
    if guild is None or target is None:
        return False, "no such guild or agent"
    if target_id in guild.members:
        return False, "already a member"
    if target_id not in guild.invited:
        guild.invited.append(target_id)
    log.emit(
        world.sim_time, "guild_invited", actor=agent.id, subject=guild.id,
        target=target_id, guild_name=guild.name,
    )
    return True, f"invited {target.name}"


def accept_guild_invite(
    world: World, log: EventLog, agent: Agent, guild_id: str
) -> Result:
    guild = world.guilds.get(guild_id)
    if guild is None:
        return False, "no such guild"
    if agent.guild:
        return False, "already in a guild"
    if agent.id not in guild.invited:
        return False, "not invited -- guilds are invite-only"
    guild.invited.remove(agent.id)
    guild.members.append(agent.id)
    agent.guild = guild.id
    log.emit(
        world.sim_time, "guild_joined", actor=agent.id, subject=guild.id,
        guild_name=guild.name, members=len(guild.members),
    )
    return True, f"joined {guild.name}"


def leave_guild(world: World, log: EventLog, agent: Agent) -> Result:
    guild = world.guilds.get(agent.guild) if agent.guild else None
    if guild is None:
        return False, "not in a guild"
    guild.members = [m for m in guild.members if m != agent.id]
    agent.guild = None
    was_leader, agent.is_guild_leader = agent.is_guild_leader, False
    if was_leader and guild.members:
        guild.leader = guild.members[0]
        new_leader = world.agents.get(guild.leader)
        if new_leader:
            new_leader.is_guild_leader = True
    log.emit(world.sim_time, "guild_left", actor=agent.id, subject=guild.id)
    return True, "left the guild"


def remove_guild_member(
    world: World, log: EventLog, agent: Agent, target_id: str
) -> Result:
    if not agent.guild or not agent.is_guild_leader:
        return False, "only the guild leader can remove members"
    guild = world.guilds[agent.guild]
    if target_id not in guild.members or target_id == agent.id:
        return False, "not a removable member"
    guild.members.remove(target_id)
    target = world.agents.get(target_id)
    if target:
        target.guild = None
    log.emit(
        world.sim_time, "guild_removed", actor=agent.id, subject=guild.id,
        target=target_id,
    )
    return True, "removed"


# ---------------------------------------------------------------------------
# PLAYER-TO-PLAYER TRADE
# ---------------------------------------------------------------------------

def accessible_goods(world: World, agent: Agent) -> dict[str, int]:
    """Everything an agent can put into a trade right now.

    Designer rule (2026-08-12): you can only trade what you have ON you -- which
    is not much -- unless your vehicle or your home happens to be at the same
    location, in which case its storage counts too. That makes WHERE a deal
    happens matter, and gives carts and homes a second purpose beyond hauling.
    """
    pool = dict(agent.inventory)

    for vid in agent.owned_vehicles:
        veh = world.vehicles.get(vid)
        if veh and veh.location == agent.location and veh.condition != "destroyed":
            for item, qty in veh.cargo.items():
                pool[item] = pool.get(item, 0) + qty

    if agent.owned_property:
        prop = world.properties.get(agent.owned_property)
        if prop and prop.location == agent.location:
            for item, qty in prop.stored.items():
                pool[item] = pool.get(item, 0) + qty

    return {k: v for k, v in pool.items() if v > 0}


def _take_from_accessible(world: World, agent: Agent, item: str, qty: int) -> bool:
    """Remove `qty` of `item`, drawing from person, then vehicle, then home."""
    remaining = qty
    have = agent.inventory.get(item, 0)
    take = min(have, remaining)
    if take:
        agent.remove_item(item, take)
        remaining -= take

    for vid in agent.owned_vehicles:
        if remaining <= 0:
            break
        veh = world.vehicles.get(vid)
        if not veh or veh.location != agent.location or veh.condition == "destroyed":
            continue
        take = min(veh.cargo.get(item, 0), remaining)
        if take:
            veh.cargo[item] -= take
            if veh.cargo[item] <= 0:
                del veh.cargo[item]
            remaining -= take

    if remaining > 0 and agent.owned_property:
        prop = world.properties.get(agent.owned_property)
        if prop and prop.location == agent.location:
            take = min(prop.stored.get(item, 0), remaining)
            if take:
                prop.stored[item] -= take
                if prop.stored[item] <= 0:
                    del prop.stored[item]
                remaining -= take

    return remaining == 0


def offer_trade(
    world: World, log: EventLog, agent: Agent, target_id: str,
    items: dict[str, int], price: float,
) -> Result:
    """Propose selling `items` to `target_id` for `price` Denari.

    Both parties must be in the same place -- goods change hands physically.
    """
    target = world.agents.get(target_id)
    if target is None or not target.alive:
        return False, "no such agent"
    if target_id == agent.id:
        return False, "cannot trade with yourself"
    if target.location != agent.location:
        return False, f"{target.name} is not at {agent.location}"
    if not items or any(q <= 0 for q in items.values()):
        return False, "nothing offered"
    if price < 0:
        return False, "price cannot be negative"

    pool = accessible_goods(world, agent)
    for item, qty in items.items():
        if pool.get(item, 0) < qty:
            return False, f"you cannot reach {qty}x {item} here"

    open_offers = [
        o for o in world.trade_offers.values()
        if o.seller == agent.id and o.status == "open"
    ]
    if len(open_offers) >= D.MAX_OPEN_OFFERS_PER_SELLER:
        return False, f"already have {len(open_offers)} offers open"
    if any(o.buyer == target_id for o in open_offers):
        return False, f"already have an open offer to {target.name}"

    offer = TradeOffer(
        id=world.new_id("T"), seller=agent.id, buyer=target_id, items=dict(items),
        price=price, location=agent.location, offered_at=world.sim_time,
    )
    world.trade_offers[offer.id] = offer
    log.emit(
        world.sim_time, "trade_offered", actor=agent.id, subject=offer.id,
        location=agent.location, target=target_id, items=items, price=round(price, 2),
    )
    return True, f"offered {items} to {target.name} for {price:.2f}"


def accept_trade(world: World, log: EventLog, agent: Agent, offer_id: str) -> Result:
    offer = world.trade_offers.get(offer_id)
    if offer is None or offer.status != "open":
        return False, "no such open offer"
    if offer.buyer != agent.id:
        return False, "not your offer to accept"
    seller = world.agents.get(offer.seller)
    if seller is None or not seller.alive:
        offer.status = "invalid"
        return False, "the other party is gone"
    if seller.location != agent.location:
        offer.status = "invalid"
        return False, "you are no longer in the same place"
    if agent.denari < offer.price:
        return False, "cannot afford it"

    units = sum(offer.items.values())
    if agent.carried_units() + units > agent.carry_capacity(world):
        return False, "not enough carrying capacity"

    pool = accessible_goods(world, seller)
    for item, qty in offer.items.items():
        if pool.get(item, 0) < qty:
            offer.status = "invalid"
            return False, f"seller no longer has {qty}x {item}"

    for item, qty in offer.items.items():
        _take_from_accessible(world, seller, item, qty)
        agent.add_item(item, qty)

    # Sales tax on a player-to-player deal, same incidence as any other sale.
    tax = E.sales_tax_on(offer.price, world.government.sales_tax)
    agent.denari -= offer.price
    seller.denari += offer.price - tax
    world.government.collect(tax)

    offer.status = "accepted"
    for item, qty in offer.items.items():
        world.market.record(
            Transaction(world.sim_time, item, qty, offer.price / max(units, 1),
                        seller.id, agent.id)
        )
    log.emit(
        world.sim_time, "trade_accepted", actor=agent.id, subject=offer.id,
        location=agent.location, seller=seller.id, items=offer.items,
        price=round(offer.price, 2), tax=round(tax, 2),
    )
    return True, f"bought {offer.items} from {seller.name}"


def decline_trade(world: World, log: EventLog, agent: Agent, offer_id: str) -> Result:
    offer = world.trade_offers.get(offer_id)
    if offer is None or offer.status != "open" or offer.buyer != agent.id:
        return False, "no such open offer"
    offer.status = "declined"
    log.emit(world.sim_time, "trade_declined", actor=agent.id, subject=offer_id)
    return True, "declined"


# ---------------------------------------------------------------------------
# SAFEHOUSE -- laundering stolen goods
# ---------------------------------------------------------------------------

def receive_stolen(world: World, log: EventLog, agent: Agent, item: str, qty: int) -> Result:
    """Take possession of hot goods. Phase 3 theft and looting call this.

    Stolen goods land OUTSIDE normal inventory, so every sell and trade path
    refuses them automatically until they have been laundered.
    """
    if agent.carried_units() + qty > agent.carry_capacity(world):
        return False, "not enough room to carry it"
    agent.add_stolen(item, qty)
    log.emit(
        world.sim_time, "stolen_goods_taken", actor=agent.id, location=agent.location,
        item=item, qty=qty,
    )
    return True, f"took {qty}x {item} (hot -- must be laundered)"


def stash_in_safehouse(
    world: World, log: EventLog, agent: Agent, item: str, qty: int
) -> Result:
    """Put hot goods in your own property to start the 24-hour cure.

    A thief with no home has nowhere to launder -- they either hold goods they
    cannot spend, or find someone with a safehouse willing to fence for them.
    """
    prop = world.properties.get(agent.owned_property) if agent.owned_property else None
    if prop is None:
        return False, "you have no property to use as a safehouse"
    if prop.location != agent.location:
        return False, "not at your safehouse"
    qty = min(qty, agent.stolen.get(item, 0))
    if qty <= 0:
        return False, f"no stolen {item} on you"

    used = sum(prop.stored.values()) + sum(s.qty for s in prop.safehouse)
    space = prop.storage_capacity() - used
    qty = min(qty, space)
    if qty <= 0:
        return False, "safehouse is full"

    agent.remove_stolen(item, qty)
    prop.safehouse.append(StolenStack(item=item, qty=qty, stashed_at=world.sim_time))
    ready = (world.sim_time + D.SAFEHOUSE_CURE_HOURS * 3600.0) / 3600.0
    log.emit(
        world.sim_time, "stolen_goods_stashed", actor=agent.id, subject=prop.id,
        location=agent.location, item=item, qty=qty, clean_at_hour=round(ready, 1),
    )
    return True, f"stashed {qty}x {item}; clean in {D.SAFEHOUSE_CURE_HOURS:.0f}h"


def collect_from_safehouse(world: World, log: EventLog, agent: Agent) -> Result:
    """Retrieve everything that has finished its 24 hours. Now ordinary goods."""
    prop = world.properties.get(agent.owned_property) if agent.owned_property else None
    if prop is None:
        return False, "you have no property"
    if prop.location != agent.location:
        return False, "not at your safehouse"

    ready = [s for s in prop.safehouse if s.is_clean(world.sim_time)]
    if not ready:
        pending = len(prop.safehouse)
        return False, (
            f"nothing has cured yet ({pending} stack(s) still hot)" if pending
            else "safehouse is empty"
        )

    space = agent.carry_capacity(world) - agent.carried_units()
    taken: dict[str, int] = {}
    for stack in list(ready):
        if space <= 0:
            break
        move = min(stack.qty, space)
        agent.add_item(stack.item, move)      # laundered: ordinary inventory now
        stack.qty -= move
        space -= move
        taken[stack.item] = taken.get(stack.item, 0) + move
        if stack.qty <= 0:
            prop.safehouse.remove(stack)

    if not taken:
        return False, "no room to carry any of it"
    log.emit(
        world.sim_time, "stolen_goods_laundered", actor=agent.id, subject=prop.id,
        location=agent.location, items=taken,
    )
    return True, f"collected laundered goods: {taken}"


def store_at_home(
    world: World, log: EventLog, agent: Agent, item: str, qty: int
) -> Result:
    """Move goods from your person into home storage (must be at the property)."""
    prop = world.properties.get(agent.owned_property) if agent.owned_property else None
    if prop is None or prop.location != agent.location:
        return False, "not at your property"
    qty = min(qty, agent.inventory.get(item, 0))
    if qty <= 0:
        return False, "nothing to store"
    used = sum(prop.stored.values())
    space = prop.storage_capacity() - used
    qty = min(qty, space)
    if qty <= 0:
        return False, "home storage is full"
    agent.remove_item(item, qty)
    prop.stored[item] = prop.stored.get(item, 0) + qty
    return True, f"stored {qty}x {item}"


# ---------------------------------------------------------------------------
# INSURANCE
# ---------------------------------------------------------------------------

def buy_insurance(
    world: World, log: EventLog, agent: Agent, product: str, coverage: float
) -> Result:
    if product not in ("Life", "Asset", "Cargo"):
        return False, "unknown product"
    broker = world.government_business("Insurance Brokerage")
    if broker is None:
        return False, "no brokerage available"
    if not broker.is_government:
        reserve_needed = E.required_reserve(broker.outstanding_insured_value + coverage)
        if broker.cash < reserve_needed:
            return False, "brokerage reserve too low to issue"

    premium = E.insurance_premium(coverage)
    if agent.denari < premium:
        return False, "cannot afford the premium"
    agent.denari -= premium
    if not broker.is_government:
        broker.cash += premium
    broker.outstanding_insured_value += coverage
    agent.insurance[product] = agent.insurance.get(product, 0.0) + coverage
    log.emit(
        world.sim_time, "insurance_issued", actor=agent.id, subject=broker.id,
        product=product, coverage=coverage, premium=round(premium, 2),
    )
    return True, f"insured {product} for {coverage:.0f}"


# ---------------------------------------------------------------------------
# BUSINESS-TO-BUSINESS TRADE AND HAULAGE
# ---------------------------------------------------------------------------
#
# The supply chain is farm/mine -> refinery -> store -> person, and only the
# last leg happens over a counter. Everything upstream moves between BUSINESSES,
# which is why this exists: a refinery has no way to sell metal to a weaponsmith
# otherwise, and a tavern cannot buy grain to bake with.
#
# One object carries both halves of the deal. Ordering IS the purchase: the
# buyer pays, the goods leave the seller immediately, and what remains is a
# haulage job sitting at the seller's gate. The seller is done and bears no
# delivery risk (designer decision, 2026-08-15) -- if nobody hauls it, the loss
# is the buyer's.
#
# Money moves once, at order time. The buyer's business pays for the goods and
# escrows the courier's fee, so anyone who finishes the job is certain to be
# paid and nobody has to trust a stranger at the far end of a dangerous road.

def order_from_business(
    world: World, log: EventLog, agent: Agent, my_business_id: str,
    seller_business_id: str, item: str, qty: int, courier_fee: float,
) -> Result:
    """Buy goods from another business for one of yours, and post the haulage.

    Placed remotely: a shop owner must not have to abandon their counter to
    order stock.
    """
    buyer = world.businesses.get(my_business_id)
    if not buyer or buyer.closed or buyer.owner != agent.id:
        return False, "not your business"
    seller = world.businesses.get(seller_business_id)
    if not seller or seller.closed:
        return False, "no such seller"
    if seller.id == buyer.id:
        return False, "a business cannot buy from itself"
    allowed, why = _may_buy_from(buyer, seller)
    if not allowed:
        return False, why
    if qty <= 0:
        return False, "bad quantity"
    if courier_fee < 0:
        return False, "courier fee cannot be negative"
    if seller.location == buyer.location:
        courier_fee = 0.0          # nothing to haul; it is already there

    if not seller.is_government and seller.inventory.get(item, 0) < qty:
        return False, f"{seller.name} has only {seller.inventory.get(item, 0)}x {item}"

    unit = seller.price_for(item)
    goods = unit * qty
    tax = E.sales_tax_on(goods, world.government.sales_tax)
    total = goods + courier_fee
    if buyer.cash < total:
        return False, (
            f"{buyer.name} has {buyer.cash:.2f} and needs {total:.2f} "
            f"({goods:.2f} goods + {courier_fee:.2f} carriage). "
            f"Deposit into the business first."
        )

    buyer.cash -= total
    if not seller.is_government:
        seller.remove_item(item, qty)
        seller.cash += goods - tax
    world.government.collect(tax)
    world.market.record(Transaction(world.sim_time, item, qty, unit, seller.id, buyer.id))

    if seller.location == buyer.location:
        buyer.add_item(item, qty)
        log.emit(
            world.sim_time, "b2b_purchase", actor=agent.id, subject=seller.id,
            item=item, qty=qty, unit=round(unit, 2), delivered=True,
        )
        return True, f"bought {qty}x {item} for {total:.2f}, delivered on the spot"

    con = Consignment(
        id=world.new_id("C"), seller_business=seller.id, buyer_business=buyer.id,
        item=item, qty=qty, goods_price=goods, courier_fee=courier_fee,
        origin=seller.location, destination=buyer.location, created_at=world.sim_time,
    )
    world.consignments[con.id] = con
    log.emit(
        world.sim_time, "consignment_posted", actor=agent.id, subject=con.id,
        item=item, qty=qty, paid=round(total, 2), fee=round(courier_fee, 2),
        origin=con.origin, destination=con.destination,
    )
    return True, (
        f"bought {qty}x {item} for {total:.2f}. Consignment {con.id} waits at "
        f"{con.origin}; {courier_fee:.2f} offered to whoever hauls it to {con.destination}"
    )


def accept_courier_job(world: World, log: EventLog, agent: Agent, consignment_id: str) -> Result:
    """Claim a haulage job. You are not committed until you collect."""
    con = world.consignments.get(consignment_id)
    if not con:
        return False, "no such consignment"
    if con.status != "awaiting_courier":
        return False, f"already {con.status}"
    if agent.hauling:
        return False, "you are already hauling a consignment -- deliver it first"
    # Claiming has to be exclusive too, not just loading. A consignment moves
    # whole and one at a time, so a second claim can never be acted on -- but it
    # DOES hide the job from every other courier. In the 2026-08-15 smoke one
    # agent claimed both outstanding jobs, wandered to the wrong end of the
    # valley, and delivered neither while nobody else could take them.
    held = next(
        (c for c in world.consignments.values()
         if c.courier == agent.id and c.status == "claimed"),
        None,
    )
    if held is not None:
        return False, (
            f"you already claimed {held.id} ({held.qty}x {held.item}, "
            f"{held.origin} to {held.destination}) -- finish or drop it first"
        )
    con.status = "claimed"
    con.courier = agent.id
    log.emit(
        world.sim_time, "courier_claimed", actor=agent.id, subject=con.id,
        fee=round(con.courier_fee, 2), origin=con.origin, destination=con.destination,
    )
    return True, (
        f"claimed {con.id}: collect {con.qty}x {con.item} at {con.origin}, "
        f"deliver to {con.destination} for {con.courier_fee:.2f}"
    )


def collect_consignment(world: World, log: EventLog, agent: Agent, consignment_id: str) -> Result:
    """Load a claimed consignment at its origin. All of it, or not at all."""
    con = world.consignments.get(consignment_id)
    if not con:
        return False, "no such consignment"
    if con.courier != agent.id:
        return False, "not your job"
    if con.status != "claimed":
        return False, f"consignment is {con.status}"
    if agent.location != con.origin:
        return False, f"the goods are at {con.origin}, you are at {agent.location}"

    free = agent.carry_capacity(world) - agent.carried_units()
    if free < con.qty:
        return False, (
            f"you can carry {free} more units and this load is {con.qty}. "
            f"A consignment moves whole -- get a bigger vehicle or drop what you carry."
        )

    agent.hauling = con.id
    agent.hauling_units = con.qty
    log.emit(
        world.sim_time, "consignment_collected", actor=agent.id, subject=con.id,
        item=con.item, qty=con.qty, location=con.origin,
    )
    return True, f"loaded {con.qty}x {con.item}; deliver to {con.destination}"


def deliver_consignment(world: World, log: EventLog, agent: Agent, consignment_id: str) -> Result:
    """Hand over at the destination and take the fee."""
    con = world.consignments.get(consignment_id)
    if not con:
        return False, "no such consignment"
    if con.courier != agent.id or agent.hauling != con.id:
        return False, "you are not carrying that"
    if agent.location != con.destination:
        return False, f"deliver at {con.destination}, you are at {agent.location}"

    buyer = world.businesses.get(con.buyer_business)
    if buyer and not buyer.closed:
        buyer.add_item(con.item, con.qty)
    con.status = "delivered"
    agent.hauling = None
    agent.hauling_units = 0
    agent.denari += con.courier_fee        # escrowed at order time; always paid
    log.emit(
        world.sim_time, "consignment_delivered", actor=agent.id, subject=con.id,
        item=con.item, qty=con.qty, fee=round(con.courier_fee, 2),
        location=con.destination,
    )
    return True, f"delivered {con.qty}x {con.item}, earned {con.courier_fee:.2f}"


def cancel_consignment(world: World, log: EventLog, agent: Agent, consignment_id: str) -> Result:
    """Call off a consignment nobody has loaded, and get the goods back on site."""
    con = world.consignments.get(consignment_id)
    if not con:
        return False, "no such consignment"
    buyer = world.businesses.get(con.buyer_business)
    if not buyer or buyer.owner != agent.id:
        return False, "not your consignment"
    if con.status not in ("awaiting_courier", "claimed"):
        return False, f"consignment is {con.status}"
    courier = world.agents.get(con.courier or "")
    if courier and courier.hauling == con.id:
        return False, "already loaded -- it is on the road"

    con.status = "cancelled"
    buyer.cash += con.courier_fee          # the carriage escrow comes back
    seller = world.businesses.get(con.seller_business)
    if seller and not seller.closed:
        seller.add_item(con.item, con.qty)  # goods sit with the seller again
    log.emit(
        world.sim_time, "consignment_cancelled", actor=agent.id, subject=con.id,
        item=con.item, qty=con.qty,
    )
    return True, (
        f"cancelled {con.id}; carriage fee refunded. The {con.qty}x {con.item} "
        f"is back with {seller.name if seller else 'the seller'} -- the goods are not refunded"
    )


def open_courier_jobs(world: World, agent: Agent, limit: int = 8) -> list[dict[str, Any]]:
    """Haulage nobody has claimed. Read-only context, not an action."""
    out: list[dict[str, Any]] = []
    for con in world.consignments.values():
        if con.status != "awaiting_courier" or con.courier_fee <= 0:
            continue
        out.append({
            "id": con.id, "item": con.item, "qty": con.qty,
            "from": con.origin, "to": con.destination,
            "pays": round(con.courier_fee, 2),
        })
    out.sort(key=lambda j: -j["pays"])
    return out[:limit]
