#!/usr/bin/env python3
"""A business must never pay wages it cannot afford, and must say when it can't.

The 2026-08-16 96-hour run ranked an agent FIRST at 1,375 net worth while the
two businesses they owned sat 2,852 denari in the red. Three things combined to
produce that, and none of them was visible to a unit test -- each call was
correct in isolation and only the SEQUENCE was wrong:

  1. `_pay_wages` did a bare `biz.cash -= gross`, so payroll drove cash
     arbitrarily negative with nothing to stop it.
  2. NPC hires billed around the clock whether or not the business could
     produce. Three NPC refinery workers standing in a refinery with no ore
     cost 2,124 denari in 11 simulated hours.
  3. `Business.valuation` never read `cash`, so that debt was invisible to the
     net worth the agents were told to maximise.

These tests exercise the sequence: hire -> run the engine -> check the books.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from convoy import actions as A
from convoy import data as D
from convoy import economy as E
from convoy.engine import Engine, EngineConfig
from convoy.events import EventLog
from convoy.state import Employment
from convoy.world_setup import new_world

FAILURES: list[str] = []


class NullPolicy:
    def decide(self, world, agent, reason) -> None:
        return None


def ok(label: str, cond: bool, detail: str = "") -> None:
    print(f"  {label}" + (f": {detail}" if detail else ""))
    if not cond:
        FAILURES.append(f"{label}{': ' + detail if detail else ''}")


def setup():
    log = EventLog(None, echo_min=99)
    world = new_world(log, [("owner", "rule-based")])
    return world, log, next(iter(world.agents.values()))


def _run(world, log, hours: float):
    Engine(
        world, log, policy=NullPolicy(), config=EngineConfig(
            duration_hours=hours, speed=1e9, checkpoint_every_hours=1e9,
        ),
    ).run()


def test_payroll_cannot_drive_cash_negative():
    """The original bug: hire beyond your means, run time, watch cash go under."""
    world, log, a = setup()
    biz = next(b for b in world.businesses.values()
               if b.type == "Refinery" and b.is_government)
    # Re-own it as a player business with a tiny float and an expensive roster.
    biz.owner = a.id          # is_government is derived from owner
    a.owned_businesses.append(biz.id)
    biz.cash = 10.0
    biz.active_production = "Bronze"
    biz.inventory.update({"Copper Ore": 500, "Tin Ore": 500, "Charcoal": 500})
    for _ in range(3):
        biz.roster.append(Employment(agent_id="NPC", role="Refinery Worker",
                                     wage=D.NPC_WAGES["Refinery Worker"], is_npc=True))

    _run(world, log, 12.0)

    ok("business cash never went negative", biz.cash >= 0.0, f"cash={biz.cash:.2f}")
    ok("unpaid staff were released", len(biz.roster) < 3, f"roster={len(biz.roster)}")


def test_idle_npcs_are_not_paid():
    """An NPC in a business with no feedstock must cost nothing."""
    world, log, a = setup()
    biz = next(b for b in world.businesses.values()
               if b.type == "Refinery" and b.is_government)
    biz.owner = a.id          # is_government is derived from owner
    a.owned_businesses.append(biz.id)
    biz.cash = 5000.0
    biz.active_production = "Bronze"
    biz.inventory.clear()                      # nothing to refine
    for _ in range(3):
        biz.roster.append(Employment(agent_id="NPC", role="Refinery Worker",
                                     wage=D.NPC_WAGES["Refinery Worker"], is_npc=True))

    before = biz.cash
    _run(world, log, 11.0)

    ok("an idle NPC roster costs nothing", abs(biz.cash - before) < 1e-6,
       f"spent {before - biz.cash:.2f} on 3 idle NPCs over 11h")
    ok("production is flagged blocked", biz.production_blocked, "")
    ok("roster survives (nothing was owed)", len(biz.roster) == 3, f"{len(biz.roster)}")


def test_producing_npcs_are_paid():
    """The other half: a working NPC must still cost its wage."""
    world, log, a = setup()
    biz = next(b for b in world.businesses.values()
               if b.type == "Refinery" and b.is_government)
    biz.owner = a.id          # is_government is derived from owner
    a.owned_businesses.append(biz.id)
    biz.cash = 5000.0
    biz.active_production = "Bronze"
    biz.inventory.update({"Copper Ore": 500, "Tin Ore": 500, "Charcoal": 500})
    biz.roster.append(Employment(agent_id="NPC", role="Refinery Worker",
                                 wage=D.NPC_WAGES["Refinery Worker"], is_npc=True))

    before = biz.cash
    _run(world, log, 5.0)

    ok("a producing NPC is paid", biz.cash < before - 1.0,
       f"spent {before - biz.cash:.2f} over 5h")
    ok("and made something", sum(biz.inventory.get(i, 0) for i in ("Bronze",)) > 0,
       f"bronze={biz.inventory.get('Bronze', 0)}")


def test_valuation_counts_cash_and_stock():
    """Debt must reduce net worth, and stock must not vanish from the books."""
    world, log, a = setup()
    biz = next(b for b in world.businesses.values()
               if b.type == "Refinery" and b.is_government)
    biz.owner = a.id          # is_government is derived from owner
    a.owned_businesses.append(biz.id)
    biz.inventory.clear()
    biz.cash = 0.0

    base = biz.valuation(world)
    biz.cash = 300.0
    ok("cash raises valuation", abs(biz.valuation(world) - (base + 300.0)) < 1e-6,
       f"{biz.valuation(world):.2f} vs {base + 300.0:.2f}")

    biz.cash = 0.0
    biz.inventory["Copper Ore"] = 10
    want = base + E.inventory_value({"Copper Ore": 10})
    ok("stock raises valuation", abs(biz.valuation(world) - want) < 1e-6,
       f"{biz.valuation(world):.2f} vs {want:.2f}")


def test_spending_cash_on_stock_is_value_neutral():
    """Ordering feedstock must not LOOK like destroying value.

    This is the trap in adding cash alone: a business that converts 100 denari
    into goods would show a 100-denari loss, which would punish exactly the
    B2B ordering these runs exist to observe -- the same shape as the old bug
    where founding a business read as a loss.
    """
    world, log, a = setup()
    biz = next(b for b in world.businesses.values()
               if b.type == "Refinery" and b.is_government)
    biz.owner = a.id          # is_government is derived from owner
    a.owned_businesses.append(biz.id)
    biz.inventory.clear()

    unit = D.base_price("Copper Ore")
    biz.cash = unit * 10
    before = biz.valuation(world)
    biz.cash = 0.0                        # spent it all at base price
    biz.inventory["Copper Ore"] = 10
    ok("cash -> stock is value neutral", abs(biz.valuation(world) - before) < 1e-6,
       f"{biz.valuation(world):.2f} vs {before:.2f}")


def test_owner_sees_the_insolvency_clock():
    """The observation must SAY the business is dying. It never used to.

    30 bankruptcy warnings were logged in the 2026-08-16 run and not one
    reached an agent.
    """
    from convoy import observe as O

    world, log, a = setup()
    biz = next(b for b in world.businesses.values()
               if b.type == "Refinery" and b.is_government)
    biz.owner = a.id          # is_government is derived from owner
    a.owned_businesses.append(biz.id)
    biz.cash = 10.0
    biz.active_production = "Bronze"
    biz.inventory.update({"Copper Ore": 500, "Tin Ore": 500, "Charcoal": 500})
    for _ in range(3):
        biz.roster.append(Employment(agent_id="NPC", role="Refinery Worker",
                                     wage=D.NPC_WAGES["Refinery Worker"], is_npc=True))

    _run(world, log, 6.0)
    text = O.render(O.observe(world, log, a, "activity_complete"))

    ok("insolvency reaches the observation", "INSOLVENT" in text.upper(),
       text[-400:] if "INSOLVENT" not in text.upper() else "")
    ok("payroll is visible to the owner", "payroll" in text.lower(), "")


def test_a_stranger_cannot_create_a_wage_bill():
    """Nobody joins a player business without its owner agreeing.

    apply_for_job used to append straight to the roster at a wage the owner
    never set. On 2026-08-17 that bankrupted six of seven businesses inside the
    first simulated hour: agents with no state job walked into zero-cash
    businesses, became a recurring 28.89/hr liability, went unpaid, walked, and
    walked back in. One pair repeated it more than a dozen times.
    """
    world, log, owner = setup()
    stranger = list(world.agents.values())[0]
    if stranger is owner:                       # setup() spawns one agent
        from convoy.state import Agent
        stranger = Agent(id=world.new_id("A"), name="stranger", model="rule-based",
                         location=owner.location)
        world.agents[stranger.id] = stranger
    owner.denari = 3000
    owner.location = "Copper Gulch"
    stranger.location = "Copper Gulch"
    A.start_business(world, log, owner, "Mining Operation", seed_cash=0)
    mine = world.businesses[owner.owned_businesses[-1]]

    okr, msg = A.apply_for_job(world, log, stranger, mine.id)
    ok("a stranger cannot join a player business", not okr, msg[:90])
    ok("and creates no wage liability", len(mine.roster) == 0, f"roster={len(mine.roster)}")
    ok("the refusal points at the job board",
       "post_job" in msg and "apply_to_job" in msg, msg[:90])

    okr, _ = A.apply_for_job(world, log, owner, mine.id)
    ok("but the OWNER may still staff it", okr, "")

    gov = next(b for b in world.businesses.values()
               if b.is_government and b.spec.needs_worker)
    stranger.location = gov.location
    okr, msg = A.apply_for_job(world, log, stranger, gov.id)
    ok("and state jobs stay open to anyone", okr, msg[:70])


def test_jobseekers_are_warned_about_an_insolvent_employer():
    """An insolvent business must not look identical to a healthy one."""
    from convoy import observe as O

    world, log, owner = setup()
    owner.denari = 3000
    owner.location = "Copper Gulch"
    A.start_business(world, log, owner, "Mining Operation", seed_cash=0)
    mine = world.businesses[owner.owned_businesses[-1]]

    view = O._shop_view(world, mine)
    ok("a solvent business carries no warning", "warning" not in view, str(view)[:80])

    mine.insolvent_since = 0.0
    mine.insolvent_debt = 28.89
    view = O._shop_view(world, mine)
    ok("an insolvent one does", "CANNOT MAKE PAYROLL" in view.get("warning", ""),
       str(view.get("warning"))[:90])
    ok("and it names what is owed", "28.89" in view.get("warning", ""), "")


def main() -> int:
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in tests:
        print(f"\n--- {fn.__name__} ---")
        fn()
    print()
    if FAILURES:
        print(f"{len(FAILURES)} FAILURES:")
        for f in FAILURES:
            print(f"  ! {f}")
        return 1
    print("OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
