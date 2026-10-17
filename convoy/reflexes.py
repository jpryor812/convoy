"""Reflexes: the moves with one sensible answer, made without asking the model.

Designer decision, 2026-10-16 (option A of the hybrid design). Measured on the
second no-state smoke: of 235 decisions, 92 were an agent waking because it had
ARRIVED somewhere and 79 because a shift or wait had ENDED; 36 did nothing but
wait again. Most of those wakes had exactly one sensible answer -- a courier
standing at the pickup loads the goods and sets off; a hungry agent standing in
a stocked tavern eats -- and each cost a round trip to a language model to say
so. The model is worth its price on strategy, negotiation and talk, not on
turning a key.

So before the engine asks the model anything, `handle` tries these, in order:

  EAT        Hungry or worse, standing where a staffed tavern has a meal you
             can afford: eat. Never on its own the whole answer for an idle
             agent -- it eats and is then asked as usual -- but a WORKING agent
             pulled off its bench by hunger just eats and carries on.
  COURIER    Arrived at the pickup of a load you claimed: load it and set off
             for the destination. Arrived at the destination carrying it:
             deliver, and head for the next pickup if you hold another claim.
  KEEP AT IT A shift ended, nothing has changed for you since you last thought,
             and the job can still run (employer can pay / owner has inputs):
             start the same shift again.
  KEEP WAITING
             A routine re-evaluation, your last decision was to wait, and
             nothing has changed for you since: keep waiting.

"Nothing has changed" is `fingerprint`: everything that is NEWS to one agent --
a message to it or naming it, a job offer, an applicant, money arriving, its
stock or its businesses moving, hunger, a new world digest, robbery. The model
is always asked if any of it moved, and always asked at least every
`MAX_SILENCE_HOURS` whatever happened, so no agent goes on autopilot for long.

Every reflex is logged as a `reflex` event naming what it did, which the agent
sees in its own memory next time it thinks -- the model is told what its hands
did while it was not looking.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from . import actions as A
from . import world_map
from .events import Significance

if TYPE_CHECKING:
    from .events import EventLog
    from .state import Agent, World

# The longest an agent goes without the model being asked, whatever the
# reflexes could have handled. Longer than one ordinary shift, so a four-hour
# shift can run once more on its own and no more than that; the digest, every
# four hours, is news by itself, so nobody idles past it unasked.
MAX_SILENCE_HOURS = 6.0


def fingerprint(world: "World", agent: "Agent") -> list:
    """Everything that, if it moved, the agent would want to think about.

    A list, not a tuple, so it round-trips through a checkpoint unchanged.
    """
    city = world.city_of(agent)
    neighbours = sum(1 for b in world.businesses.values()
                     if not b.closed and world_map.city_of(b.location) == city)
    offers = sorted(p.id for p in world.job_postings.values()
                    if getattr(p, "invitee", "") == agent.id and p.is_live(world.sim_time))
    applicants = sum(len(p.applicants) for p in world.job_postings.values()
                     if p.owner == agent.id and p.is_live(world.sim_time))
    trades = sorted(o.id for o in world.trade_offers.values()
                    if agent.id in (o.seller, o.buyer) and o.status == "open")
    mine = []
    for bid in agent.owned_businesses:
        b = world.businesses.get(bid)
        if b is None:
            continue
        mine.append([bid, b.closed, b.insolvent_since is not None,
                     len(b.roster), int(b.cash // 25), sum(b.inventory.values()) // 5])
    # SUPPLIES APPEARING. A tavern owner waiting on Grain is waiting for a
    # refinery to have some, which is nothing in its own books -- so in the
    # second reflex smoke it kept waiting straight through the moment it
    # should have ordered. Stock of what its businesses use, at the other
    # businesses in its city, in steps of five.
    needs: set[str] = set()
    for bid in agent.owned_businesses:
        b = world.businesses.get(bid)
        if b is None or b.closed:
            continue
        for out in b.spec.outputs:
            recipe = A.D.REFINING_RECIPES.get(out) or A.D.CRAFTING_RECIPES.get(out)
            if recipe:
                needs |= set(recipe.inputs)
    supplies = []
    if needs:
        for item in sorted(needs):
            stock = sum(b.inventory.get(item, 0) for b in world.businesses.values()
                        if not b.closed and b.owner != agent.id
                        and world_map.city_of(b.location) == city)
            supplies.append([item, stock // 5])
    jobless_board = 0
    if not agent.current_job:
        jobless_board = sum(1 for p in world.job_postings.values()
                            if p.is_live(world.sim_time) and not getattr(p, "invitee", ""))
    return [
        neighbours, offers, applicants, trades, mine, supplies, jobless_board,
        int(agent.denari // 10), sum(agent.inventory.values()),
        sum(agent.stolen.values()), agent.sustenance_stage, agent.alive,
        bool(agent.current_job), world.digest_at,
    ]


def news_since(world: "World", agent: "Agent", t: float) -> bool:
    """A message to this agent, or naming it in world chat, after `t`.

    By time rather than by count, because the snapshot is taken after the
    agent acts and a message that arrived while it was thinking was never in
    front of it."""
    name, aid = agent.name.lower(), agent.id.lower()
    for m in reversed(world.chat):
        if m.sim_time <= t:
            break
        if m.sender == agent.id:
            continue
        if m.recipient == agent.id:
            return True
        if m.channel == "world" and (aid in m.text.lower() or name in m.text.lower()):
            return True
    return False


def _quiet(world: "World", agent: "Agent") -> bool:
    """Nothing new for this agent, and the model was asked recently enough."""
    if agent.last_thought_at < 0 or not agent.thought_fingerprint:
        return False
    if world.sim_time - agent.last_thought_at >= MAX_SILENCE_HOURS * 3600.0:
        return False
    if news_since(world, agent, agent.last_thought_at):
        return False
    return fingerprint(world, agent) == agent.thought_fingerprint


def _note(world: "World", log: "EventLog", agent: "Agent", kind: str, did: str) -> None:
    # MEDIUM puts it in the agent's memory: it should know its hands loaded a
    # cart. A wait that went on is not news, and every quarter hour of one
    # would push real events out of that memory -- so LOW.
    sig = Significance.LOW if kind == "keep waiting" else Significance.MEDIUM
    log.emit(world.sim_time, "reflex", actor=agent.id, location=agent.location,
             reflex=kind, did=did, significance=sig)


def _eat(world: "World", log: "EventLog", agent: "Agent") -> bool:
    if agent.sustenance_stage == "Normal":
        return False
    for tavern in world.businesses_at(agent.location, "Tavern / Inn"):
        if tavern.closed or not A.is_staffed(world, tavern):
            continue
        if not any(q > 0 for i, q in tavern.inventory.items() if i in A.D.MEALS):
            continue
        ok, msg = A.buy_meal(world, log, agent, tavern.id)
        if ok:
            _note(world, log, agent, "eat", msg)
            return True
    return False


def _courier(world: "World", log: "EventLog", agent: "Agent") -> bool:
    claims = [c for c in world.consignments.values()
              if c.courier == agent.id and c.status == "claimed"]
    if not claims:
        return False
    carrying = next((c for c in claims if agent.hauling == c.id), None)
    if carrying is not None:
        if agent.location != carrying.destination:
            return False   # somewhere unexpected: the model decides
        ok, msg = A.deliver_consignment(world, log, agent, carrying.id)
        if not ok:
            return False
        _note(world, log, agent, "deliver", msg)
        nxt = next((c for c in claims if c.id != carrying.id and c.status == "claimed"), None)
        if nxt is None:
            return False   # job done; what next is a real decision
        ok, msg = A.travel_to(world, log, agent, nxt.origin)
        if ok:
            _note(world, log, agent, "next pickup", f"set off for {nxt.origin}: {msg}")
        return ok
    here = next((c for c in claims if c.origin == agent.location), None)
    if here is None or agent.hauling:
        return False
    ok, msg = A.collect_consignment(world, log, agent, here.id)
    if not ok:
        return False   # will not fit, or similar: the model decides
    _note(world, log, agent, "collect", msg)
    ok, msg = A.travel_to(world, log, agent, here.destination)
    if ok:
        _note(world, log, agent, "set off", f"for {here.destination}: {msg}")
    return ok


def _keep_at_it(world: "World", log: "EventLog", agent: "Agent") -> bool:
    last = agent.activity
    if last.kind != "work" or not agent.current_job:
        return False
    if agent.sustenance_stage != "Normal" or not _quiet(world, agent):
        return False
    biz = world.businesses.get(agent.current_job[0])
    if biz is None or biz.closed or biz.insolvent_since is not None:
        return False
    if biz.owner != agent.id:
        if biz.cash < agent.current_job[2]:        # cannot pay the next hour
            return False
    else:
        item = biz.active_production
        if not item:
            return False
        recipe = A.D.REFINING_RECIPES.get(item) or A.D.CRAFTING_RECIPES.get(item)
        if recipe and any(biz.inventory.get(i, 0) < q for i, q in recipe.inputs.items()):
            return False
    hours = last.detail.get("hours") or 4.0
    ok, msg = A.start_shift(world, log, agent, hours)
    if ok:
        _note(world, log, agent, "keep working", msg)
    return ok


def handle(world: "World", log: "EventLog", agent: "Agent", reason: str) -> bool:
    """True if a reflex dealt with this wake and the model need not be asked."""
    if not agent.alive:
        return False
    busy = agent.activity.kind in ("work", "travel", "raid") and \
        agent.activity.ends_at > world.sim_time
    ate = _eat(world, log, agent)
    if busy:
        # Woken mid-shift by hunger. Eaten, it carries on; not eaten, it must
        # go and find food, which is the model's call.
        return ate and agent.sustenance_stage == "Normal"
    if reason == "arrived" and _courier(world, log, agent):
        return True
    if reason == "activity_complete" and _keep_at_it(world, log, agent):
        return True
    # KEEP WAITING. Its last decision ended in a wait -- usually after a
    # message or two, whose replies are news and wake it -- and nothing has
    # moved since. The end of its own wait timer counts the same: 82 of 84
    # "activity complete" wakes in the first reflex smoke were exactly that.
    if reason in ("reevaluation", "activity_complete") and agent.activity.kind == "idle":
        last = agent.reasoning[-1] if agent.reasoning else None
        if (last is not None and last.actions
                and last.actions[-1].split(" ")[0] == "wait" and _quiet(world, agent)):
            _note(world, log, agent, "keep waiting", "nothing new since it last thought")
            return True
    return False
