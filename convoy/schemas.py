"""The 45 agent actions, as tool definitions a model can call.

WHY TOOL-CALLING AND NOT JSON

Ling 3.0 Flash does not support structured outputs. Prompting for JSON and
parsing the reply would work for four of the five models and fail for 15 of the
75 agents -- and it would fail as malformed text, which looks like a bad model
rather than a bad harness. Tool-calling is the only path all five share, so it
is the only path used.

WHY THE SCHEMAS ARE GENERATED, NOT WRITTEN OUT

Every action in `actions.py` has the same shape: (world, log, agent, **params).
So names, types, and which parameters are required all come from introspection
and cannot drift from the functions they describe. Only the descriptions are
written by hand, because those are the part the model actually reads.

ENUMS ARE THE GUARDRAIL

Where the valid values are known and static -- item names, places, business
types, roles -- they go in the schema as enums. That converts a whole class of
hallucination ("sell 5 Silver") into a request the API rejects before it ever
reaches the engine. Runtime identifiers (business_id, offer_id, target_id) are
deliberately NOT enums: they change constantly, and the observation is what
tells an agent which ones exist right now.
"""

from __future__ import annotations

import inspect
from typing import Any, Callable

from . import actions as A
from . import data as D
from . import world_map as M
from .events import EventLog
from .state import Agent, World

# Read helpers, not actions -- their output is already in the observation.
# `eat_self_prep` is deliberately NOT offered (designer decision, 2026-08-14).
# Cooking Grain + Water cost 4.80 for the same 12h window a tavern charges 16.00
# for, so no tavern could ever win a customer and the whole Tavern business line
# was dead on arrival. Food is a tavern trade now.
_NOT_ACTIONS = frozenset({
    "visible_chat", "accessible_goods", "eat_self_prep",
    # Helpers, not actions -- and their signatures would have been handed
    # (world, log, agent) by the dispatcher. Introspection exposes every public
    # function in the module, so anything that is not a real action must say so.
    "employee_cap", "is_staffed", "open_courier_jobs",
})

# Engine-internal: loot transfer is driven by the combat/death path, not chosen.
_ENGINE_ONLY = frozenset({"receive_stolen"})


DESCRIPTIONS: dict[str, str] = {
    # -- movement -----------------------------------------------------------
    "travel_to": (
        "Travel to another place. Takes real time -- you cannot act until you "
        "arrive. Spurs dead-end, so spur-to-spur means climbing back to the main "
        "road and down again."
    ),
    "mount": "Mount a vehicle you own, to carry far more and travel faster.",
    "hire_escort": (
        "Hire NPC guards for your next journey, paid now, gone on arrival. "
        "Bodyguards deter; Scouts hide you; Drivers handle the cart. Better kit "
        "deters more. An NPC costs HALF AGAIN what an agent does -- "
        "post_escort_job is cheaper if you can wait."
    ),
    "post_escort_job": (
        "Offer an AGENT a place on your next convoy, announced in world chat. "
        "Cheaper than an NPC, but you wait for a taker. Paid on arrival. "
        "lend_weapon arms them from your inventory and comes back."
    ),
    "accept_escort_job": (
        "Take escort work. You travel with them, are paid on arrival, and end up "
        "where they were going. Driver-own pays most: bring your own vehicle."
    ),
    "dismount": "Get off your vehicle and continue on foot.",
    "wait": (
        "Do nothing for a while, and end this turn. Use when waiting on "
        "production or a trade. You are re-checked every 15 minutes regardless, "
        "so anything shorter than 900s is rounded up to it. Waiting does NOT "
        "interrupt a shift or a journey already under way -- those continue."
    ),
    # -- employment ---------------------------------------------------------
    "apply_for_job": (
        "Apply for a job at a business here. Government businesses always hire. "
        "Set as_researcher=true to generate Research Points instead of goods "
        "(player-owned businesses only)."
    ),
    "quit_job": "Leave your current job. You keep the skill you built up.",
    "start_shift": (
        "Start working your job for a number of hours. You only earn wages and "
        "produce goods while actually on shift."
    ),
    "end_shift": "Stop working before your shift was due to end.",
    # -- trade --------------------------------------------------------------
    "buy_from_business": "Buy goods from a business at this location. Sales tax is added on top.",
    "sell_to_business": "Sell goods from what you are carrying to a business here.",
    "set_retail_price": (
        "Set what your own business charges for an item. You cannot price below "
        f"{D.PLAYER_STORE_FLOOR_PCT:.0%} of base price."
    ),
    # -- your businesses ----------------------------------------------------
    "start_business": (
        "Found a business. Mines and farms must be founded on spur land with free "
        "plots; everything else sits on the main road. You pay the startup cost "
        "and take no wage -- owners earn the profit instead."
    ),
    # Terse on purpose. The cached prefix is the single largest cost in the run
    # and it has a hard ceiling -- the 84-hour run died at hour 47 to a prompt
    # limit. The LAND RULES are explained once in the static briefing; these say
    # only what the call does.
    "buy_land": (
        f"Buy unsold land here, {D.LAND_BASE_PRICE:.0f} each. Raw until develop_plot."
    ),
    "develop_plot": (
        "Build on one raw plot: +1 employee place. Cheap and slow, or "
        f"{D.DEVELOPMENT_INSTANT_MULTIPLIER:g}x to finish now."
    ),
    "post_delivery_job": (
        "Pay a courier to move YOUR stock to a government business or one you "
        "own. Goods leave the yard at once, so a full site produces again. "
        "Announced in chat as a price and a route -- couriers are not told what "
        "is in the load. A courier usually wants about a tenth of what it is "
        "worth, more through dangerous country; you may offer what you like "
        "above the floor. Lend a vehicle so a courier without one can take it."
    ),
    "list_land": "Offer a plot you own for sale at your price.",
    "buy_listed_land": "Buy a plot another agent listed, at their price.",
    "upgrade_site_storage": (
        "Raise a production site's storehouse: more stock, no more land."
    ),
    "set_production": "Choose which item your business produces.",
    "set_wage": "Set the hourly wage your business offers for a role. Higher wages attract workers.",
    "post_job": (
        "Advertise a role and wage from your business to every agent. The only "
        "way anyone learns you are hiring. Applicants appear in your observation; "
        "you choose."
    ),
    "apply_to_job": (
        "Answer a job advert by its id. The owner still picks, so you are not "
        "hired yet and may apply to several."
    ),
    "hire_applicant": (
        "Take one of the agents who answered your advert, at the wage you posted."
    ),
    "close_job": "Pull one of your job adverts, usually to repost at a new wage.",
    "hire_npc_employee": (
        "Hire an NPC worker, who is always on shift but costs more than a player. "
        "Remember every extra worker cuts every worker's individual rate by "
        f"{1 - D.WORKER_DECAY_PER_HEAD:.0%}."
    ),
    "allocate_research": (
        "Spend your business's accumulated Research Points to advance a track by "
        "one tier. 'efficiency' raises output; 'quality' unlocks better goods."
    ),
    "deposit": "Move denari from your pocket into one of your businesses.",
    "withdraw": "Take denari out of one of your businesses into your pocket.",
    "collect_business_inventory": "Take goods out of your business and carry them.",
    "stock_business_inventory": "Put goods you are carrying into your business.",
    # -- property and kit ---------------------------------------------------
    "buy_vehicle": (
        "Buy a vehicle. Carrying capacity is usually what limits earnings, not "
        "how fast you can produce -- on foot you carry only "
        f"{D.ON_FOOT_CAPACITY} units."
    ),
    "equip_tools": (
        f"Equip Upgraded Tools for +{D.TOOL_EXTRACTION_BONUS:.0%} extraction speed."
    ),
    "buy_property": (
        f"Buy a home on the spur you are standing on ({M.HOME_BASE_PLOTS} plots). "
        "Gives storage, a safehouse for stolen goods, and upgrade options. "
        "Property tax is billed on it weekly."
    ),
    "upgrade_storage": "Raise your home's storage capacity a tier. Costs denari and materials.",
    "upgrade_garage": "Raise your home's garage a tier, for vehicle slots.",
    "store_at_home": "Put goods into your home's storage. You must be at your home.",
    # -- staying alive ------------------------------------------------------
    "eat_self_prep": (
        "Cook and eat from what you carry ("
        + " + ".join(f"{q}x {i}" for i, q in D.SELF_PREP_INPUTS.items())
        + f"). Cheapest way to stay fed; lasts {D.SELF_PREP_WINDOW_HOURS:.0f}h."
    ),
    "buy_meal": (
        "Buy and eat a meal from a tavern. Better meals last longer, heal, or "
        "boost production. 'prefer' picks the line when you do not name a meal."
    ),
    "eat_best_available": (
        "Buy and eat the best meal the Tavern where you stand can serve. Food is "
        "sold at Taverns and nowhere else -- you cannot cook. Being dead ends "
        "all earning, so travel to a Tavern before hunger becomes urgent."
    ),
    # -- business-to-business trade and haulage ------------------------------
    "order_from_business": (
        "Buy stock for a business you own from another business, and post the "
        "haulage job in one go. You do NOT have to travel to the seller. Your "
        "business pays for the goods and escrows the courier's fee out of its "
        "OWN cash, so deposit into it first. The goods leave the seller at once "
        "and wait at their site until a courier hauls them; if nobody does, that "
        "is your loss, not the seller's. Set courier_fee high enough that "
        "somebody wants the job -- a share of what the load is worth is the "
        "usual way to think about it."
    ),
    "accept_courier_job": (
        "Take on a haulage job somebody has posted. The fee is already escrowed, "
        "so finishing it always pays. You can only haul one at a time."
    ),
    "collect_consignment": (
        "Load a job you have claimed. You must be at the pickup location and "
        "have room for the WHOLE load -- it does not split, so the size of your "
        "vehicle decides which jobs you can take."
    ),
    "deliver_consignment": (
        "Hand the load over at its destination and collect your fee. The goods "
        "go into the buying business's stock."
    ),
    "cancel_consignment": (
        "Call off a consignment of yours that nobody has loaded yet. The "
        "carriage fee comes back; the goods stay with the seller, already paid for."
    ),
    # -- social -------------------------------------------------------------
    "post_world_chat": "Say something every living agent can read.",
    "send_direct_message": "Send a private message to one agent, wherever they are.",
    "post_guild_chat": "Say something only your guild can read.",
    "create_guild": "Found a guild. You become its leader and can invite others.",
    "invite_to_guild": "Invite an agent to your guild. Guilds are invite-only.",
    "accept_guild_invite": "Accept a guild invitation you have received.",
    "leave_guild": "Leave your guild. You lose access to its chat history.",
    "remove_guild_member": "Remove a member from the guild you lead.",
    # -- player-to-player ---------------------------------------------------
    "offer_trade": (
        "Offer goods to another agent for a price. You can only trade what is "
        "reachable: carried, in a vehicle here, or in a home at this location. "
        "Offers expire."
    ),
    "accept_trade": "Accept a trade offer made to you.",
    "decline_trade": "Decline a trade offer.",
    # -- crime --------------------------------------------------------------
    "stash_in_safehouse": (
        "Put stolen goods into your home's safehouse. They cannot be sold or "
        f"traded until they have sat there {D.SAFEHOUSE_CURE_HOURS:.0f} hours."
    ),
    "collect_from_safehouse": (
        "Take cured stolen goods out of your safehouse. They are now ordinary "
        "inventory and can be sold."
    ),
    "loot_ground": "Pick up whatever a dead agent dropped here.",
    # -- risk ---------------------------------------------------------------
}


# Static value sets. Runtime IDs are excluded on purpose -- see the module note.
def _enum_for(action: str, param: str) -> list[str] | None:
    # Escorts are hired into the Convoy tab's roles, not the wage roles a
    # business hires into. Checked BEFORE the generic `role` branch below,
    # which would otherwise offer a courier the choice of hiring a Blacksmith
    # to guard its cart.
    if action in ("hire_escort", "post_escort_job"):
        if param == "role":
            return list(D.CONVOY_PAY)
        if param in ("weapon", "lend_weapon"):
            return list(D.WEAPONS)
        if param == "armor":
            return list(A.ARMOR_SETS)

    if param in ("item", "output"):
        # "On Foot" is in ALL_ITEMS as the null vehicle, and is not a thing
        # anyone can hold, stock, haul or sell. Offering it as a valid `item`
        # invites a call that can only ever be refused, and costs the enum's
        # tokens on every tool that takes one, on every call, forever. The other
        # five vehicles stay: a Vehicle Dealer really does stock them.
        return [i for i in D.ALL_ITEMS if i != "On Foot"]
    if param == "destination":
        return list(D.ALL_PLACES)
    if param == "vehicle_type":
        return [v for v in D.VEHICLES if v != "On Foot"]
    if param == "type" and action == "start_business":
        return list(D.BUSINESS_TYPES)
    if param == "role":
        return list(D.WAGE_ROLES)
    if param == "track":
        return ["efficiency", "quality"]
    if param == "prefer":
        return ["duration", "hearty", "laborer"]
    if param == "meal":
        return list(D.MEALS)
    if param == "product":
        return ["Life", "Asset", "Cargo"]
    return None


_TYPE_MAP = {
    str: "string",
    int: "integer",
    float: "number",
    bool: "boolean",
}


def _param_schema(action: str, param: inspect.Parameter) -> dict[str, Any]:
    # The convoy split is a LADDER, not a free number -- see data.CONVOY_SPLITS.
    # Given as the seller's share, with -1 meaning "whatever is customary", which
    # is what an agent should send unless it is deliberately bargaining.
    if param.name == "seller_share":
        return {
            "type": "number",
            "description": (
                "Seller's share of convoy cost AND loss: 1, .75, .6, .5, .4, "
                ".25, 0. Omit for customary. The state never shares."
            ),
        }
    annotation = param.annotation
    # "str | None" and similar arrive as strings under `from __future__ import
    # annotations`, so match on text rather than on the type object.
    text = annotation if isinstance(annotation, str) else getattr(annotation, "__name__", "str")
    if "dict" in text:
        schema: dict[str, Any] = {
            "type": "object",
            "additionalProperties": {"type": "integer"},
            "description": "Item name -> quantity.",
        }
    elif "int" in text:
        schema = {"type": "integer"}
    elif "float" in text:
        schema = {"type": "number"}
    elif "bool" in text:
        schema = {"type": "boolean"}
    else:
        schema = {"type": "string"}

    enum = _enum_for(action, param.name)
    if enum and schema["type"] == "string":
        schema["enum"] = enum

    if param.name.endswith("_id"):
        schema["description"] = (
            "An id from your current observation. Do not invent one."
        )
    # The enum lists every role in the world, but a given business hires only a
    # few of them, and a wrong guess is a wasted decision. Omitting it is the
    # safe move, so say so where the model is actually looking.
    if action == "apply_for_job" and param.name == "role":
        schema["description"] = (
            "Optional. Omit this to be given whatever role that business hires."
        )
    return schema


def _actions() -> dict[str, Callable]:
    out: dict[str, Callable] = {}
    for name in sorted(dir(A)):
        if name.startswith("_") or name in _NOT_ACTIONS or name in _ENGINE_ONLY:
            continue
        fn = getattr(A, name)
        if not inspect.isfunction(fn) or fn.__module__ != "convoy.actions":
            continue
        out[name] = fn
    return out


ACTIONS: dict[str, Callable] = _actions()


def tool_schemas() -> list[dict[str, Any]]:
    """OpenAI-style tool definitions for every callable action.

    Part of the cached prefix, so this must not vary between calls or between
    agents -- hence sorted names and no world state anywhere in here.
    """
    tools: list[dict[str, Any]] = []
    for name, fn in ACTIONS.items():
        sig = inspect.signature(fn)
        properties: dict[str, Any] = {}
        required: list[str] = []
        for param in sig.parameters.values():
            if param.name in ("world", "log", "agent"):
                continue
            properties[param.name] = _param_schema(name, param)
            if param.default is inspect.Parameter.empty:
                required.append(param.name)
        tools.append({
            "type": "function",
            "function": {
                "name": name,
                "description": DESCRIPTIONS.get(name, f"Perform {name.replace('_', ' ')}."),
                "parameters": {
                    "type": "object",
                    "properties": properties,
                    "required": required,
                    "additionalProperties": False,
                },
            },
        })
    return tools


def dispatch(
    world: World, log: EventLog, agent: Agent, name: str, arguments: dict[str, Any]
) -> tuple[bool, str]:
    """Route a model's tool call into the engine.

    Returns the action's own (ok, message) so the result can be fed back to the
    model as a tool response -- an agent that tries to sell what it is not
    carrying should be told why, not silently no-op'd.

    Validates before calling, because a model will occasionally invent a
    parameter or omit a required one, and an unexpected TypeError deep in an
    action is far harder to read than a rejection here.
    """
    fn = ACTIONS.get(name)
    if fn is None:
        return False, f"no such action {name!r}"

    sig = inspect.signature(fn)
    allowed = {
        p.name for p in sig.parameters.values()
        if p.name not in ("world", "log", "agent")
    }
    required = {
        p.name for p in sig.parameters.values()
        if p.name not in ("world", "log", "agent")
        and p.default is inspect.Parameter.empty
    }

    unknown = set(arguments) - allowed
    if unknown:
        return False, f"{name}: unknown parameter(s) {sorted(unknown)}"
    missing = required - set(arguments)
    if missing:
        return False, f"{name}: missing required parameter(s) {sorted(missing)}"

    try:
        return fn(world, log, agent, **arguments)
    except Exception as exc:                      # noqa: BLE001
        # A malformed call must never take the simulation down mid-run; the
        # agent is told, and the run continues.
        log.emit(
            world.sim_time, "action_error", actor=agent.id,
            action=name, error=f"{type(exc).__name__}: {exc}",
        )
        return False, f"{name} failed: {type(exc).__name__}: {exc}"
