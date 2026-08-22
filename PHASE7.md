# PHASE 7 — bandits on the road

2026-08-20. The convoy system: cargo can be robbed, guards can be hired, and
the two sides of a trade have to settle who carries the risk.

Read `PHASE6.md` for the map and the click-through UI. This supersedes nothing
in it; it adds the first randomness the simulation has ever had.

---

## 1. What exists now

- `convoy/banditry.py` — the model. Pure functions, no world mutation.
- `hire_escort` — NPC guards for one journey, priced off the Convoy tab.
- A roll on arrival in `Engine`, which takes part of a load and logs it.
- `responsibility` on `Consignment` — who eats the loss, negotiated.
- A `road_risk` block in the observation, and a `BANDITS` paragraph in the
  briefing.

20 test files pass; `run_phase1.py` reports invariants clean. Two new files:
`tests/test_banditry.py` (30 assertions) and `tests/test_convoy_system.py` (49).

---

## 2. Most of it was already specified and never built

This is the third time a spreadsheet tab turned out to be sitting in `data.py`
wired to nothing. What was already there:

| already in the code | doing what, before this |
|---|---|
| `CONVOY_PAY` — Driver-provided, Driver-own, Scout, Bodyguard, flat + commission | nothing |
| `CONVOY_MAX_VEHICLES`, recruit window, max extensions, post cooldown | nothing |
| `Convoy` / `ConvoyMember` state classes, with an `Ambushed` status | nothing |
| `RoadSegment.concealment` / `.vantage` / `.exposure` | averaged into `danger`, which priced courier fees |
| `can_flee_offroad()` | read by nobody |
| `Vehicle.armor`, `ArmorPiece.damage_reduction`, `Weapon.damage` | net worth, and a conformance test |

**The three segment numbers are the whole design.** Their own docstrings say so:
concealment is "how well an ambusher hides FROM SCOUTS", vantage is "the
attacker's first-strike advantage", exposure is "how trapped the convoy is
(blocks Flee Off-Road)". Those are three different questions, and averaging them
into one `danger` scalar threw away the structure that makes scouts, guards and
horses three different purchases instead of three ways to buy one stat.

---

## 3. The equation

Per road segment crossed, not per journey:

    p_loss = p_intercept x p_press x (1 - p_escape)

| stage | question | driven by | countered by |
|---|---|---|---|
| intercept | are you found? | `concealment`, time on the stretch, cargo value | Scouts, vehicle speed |
| press | do they come on? | `vantage` | weapons, armour, numbers, vehicle armour |
| escape | can you run with the load? | `exposure` | vehicle speed |

Route risk is `1 - Π(1 - p_segment)`.

**Distance enters as segment count**, which is the honest version — Copper Gulch
to Refinery Row crosses one segment, Refinery Row to Town crosses two. Within a
segment, a faster vehicle is exposed for less time. No invented distance
multiplier anywhere.

**Risk lives on the trunk road only.** Not because spurs are special-cased, but
because `world_map.travel_path` already stated the rule this had to obey:
*"convoys never use spurs, only solo trips do."* A dead-end track where a robber
can be seen coming and cannot get away is a bad place to work.

The press stage is a contest ratio, `bandit / (bandit + strength)`, so neither
side is ever certain. Strength is `(weapon damage / 34) x (1 + armour reduction)`
per body, summed, scaled by the vehicle's armour — the Bronze Sword as the
anchor for "one armed adult of no special quality".

### Calibration

Two anchors were stated: an armed four-horse chariot around 5%, a lone donkey
with a sling around 75%. Same 800-denari load on every loadout:

| loadout | mine→refinery | the long haul |
|---|---|---|
| on foot, slingshot | — | — |
| **solo donkey + sling** | 31% | **75%** |
| donkey + 1 guard, spears + leather | 17% | 47% |
| 2-horse chariot, 2 guards + scout | 2% | 10% |
| **4-horse chariot, 3 iron guards + scout** | 3% (floor) | **6% (floor)** |

The chariot lands at 4% carrying a genuinely rich cargo, which is where the 5%
instinct was pointing. The escort economics come out right too — a
24,000-denari load across the valley costs 344 to guard and saves ~3,400 in
expected loss, which is a sum an agent can actually do.

---

## 4. Three things that changed the design

### Cargo value drives interception

Without it the model said an hour-zero labourer carrying five units of ore is
robbed on 93% of long hauls. Every agent starts on foot with a free Slingshot,
so nobody would ever earn the cart that fixes it. **The economy could not
start.**

It also makes the ladder cohere for a better reason than balance: a bigger
vehicle carries more value and therefore ATTRACTS more attention, so the cart
and the guards get bought together instead of the cart alone being "safer".

### Nobody is robbed on foot

Designer decision, and it replaced the attractiveness curve as the bottom rung.
Walking is free, slow and SAFE — `ON_FOOT_CAPACITY` is 5 against a donkey cart's
100, at half the speed. Moving a cart's load on foot is **160x the travel time**
(`test_walking_is_safe_because_it_is_slow` computes that off the data rather
than asserting a number someone typed).

**It is deliberately exploitable and the exploit is the point.** Choosing
between a slow certainty and a fast risk is the decision the system exists to
create.

### No amount of money buys safety

`MIN_SEGMENT_RISK = 0.03`, floored **per segment rather than per route**, so
risk still composes: the best convoy in the valley floors at 3% on one stretch
and 5.9% on two. A per-route floor would have made "a longer road is more
dangerous" stop being true at the top of the ladder.

---

## 5. Who pays for the convoy

The rule is scarcity, stated by Justin: one refinery buying from three mines does
not pay for haulage, because a mine with no other customer will offer to. Three
refineries chasing one mine will pay, because the mine can wait and they cannot.

**The abundant side pays; the scarce side names the terms.**

`banditry.market_power(world, item)` counts open businesses producing the item
against open businesses whose recipes consume it. Government sites COUNT — they
are the market floor and they really will trade, and pretending otherwise would
tell a miner it has no customer while the state refinery stands there.

What the engine does NOT do is decide. `_settle_responsibility` computes the
customary terms, hands them back with the numbers behind them, and refuses only
a demand the structure plainly will not bear:

> you are not in a position to insist the buyer covers the convoy. Copper Ore:
> 1 selling, 1 buying — evenly matched. Offer to cover it yourself, or agree the
> customary terms (buyer pays).

**Offering to carry the risk yourself is always allowed.** That is the move a
seller with no other customer makes to win a sale, and it is the whole mechanic
in one action.

### What this cost

`Consignment` deliberately hard-coded the other answer. Its docstring said the
goods are the buyer's the moment they are paid for and *"the seller is finished
and carries no delivery risk"*, with money moving once at order time. That
simplification had to be unpicked: `responsibility` defaults to `"buyer"`, which
is exactly the old behaviour, and `"seller"` now moves money — the seller
refunds what did not arrive. **If agreeing terms moves no money it is not a
bargain**, which is what `test_a_responsible_seller_actually_pays_up` pins.

---

## 6. The observation, because this is where it would have failed

PHASE4 §2 is at fourteen. This system was a prime candidate for the fifteenth:
the entire product argument is that agents buy better carts and hire guards, and
**nobody buys either on the strength of a probability they were never shown.**

So the number is computed for the journeys actually available and put in the
observation before the decision:

    road_risk:
      carrying: 100 units of your own goods
      worth: 600
      guards_hired: 0
      chance_of_being_robbed: {Refinery Row: 75%, The Hills: 64%, ...}

Only when there is something to lose — an empty-handed agent gets nothing there,
because a risk line about no cargo is per-call tokens spent on a decision that
cannot be made. `hire_escort` also quotes the delta at the moment of purchase
(*"Risk to Town: 75% -> 35%"*), because an escort is bought to move a number and
an agent that cannot see it move has no way to know whether it bought enough.

### A briefing that had been lying for two recuts

`observe.py` told every agent, on every call, that **"Sixteen spur roads dead-end
off the main road."** There have been four since the second recut. It is now
counted off `world_map` rather than written down.

PHASE4 §2 is usually the observation withholding something the code knows. This
is the same failure with the sign flipped — the observation asserting something
the code knew to be false — and it survived two map recuts because nothing reads
prose.

The raw concealment/vantage/exposure triple is still not quoted. The reason
changed: agents now get a computed percentage for the journey they are actually
considering, and three raw floats would invite them to do that arithmetic
themselves and get it wrong. One headline `danger` per segment is enough to rank
roads before a load exists to price.

**Prefix cost: 13,283 → 13,504 tokens**, against the 14,000 guard. 496 left.

---

## 7. The first randomness in the simulation

Everything before this was deterministic, which was worth not giving up by
accident.

- The RNG lives on the **Engine, not the World** — `checkpoint.save` walks
  dataclass fields to JSON and a `random.Random` is not one, so putting it on
  the World would have made every checkpoint unwritable.
- `EngineConfig.banditry_seed` is explicit, and `banditry=False` switches the
  whole thing off, which is what keeps every pre-banditry test deterministic.
- A resumed run re-seeds. Replay reproduces a run from its event log, not by
  re-rolling.

**A determinism test on a quiet seed proves nothing.** The first version of
`test_the_same_seed_gives_the_same_road` passed with `[100, 100, 100]` — three
identical untouched loads, which look exactly like a working generator and
exactly like a dead code path. It is pinned to seed 1, which robs.

---

## 8. Two holes found by auditing the finished system

Both were multi-step flows, which is where this codebase's worst bugs live --
each action correct alone, the sequence wrong.

**A courier could smuggle its own goods behind a job.** `cargo_at_risk` returned
the consignment OR the inventory, never both, so taking a courier job and
loading your own stock alongside moved your valuables at somebody else's risk
and none of your own. A bandit cannot tell whose crate is whose. Both are
counted now, and a robbery takes from both.

**A one-unit stack was a total loss on the gentlest possible roll.** Rounding
the share per ITEM meant `max(1, round(1 x 0.30))` took the whole thing, so a
lone Iron Sword worth 650 vanished while the observation promised "you lose part
of the load, not all of it". The share is now computed across the WHOLE load by
`engine._share_of`, which never takes the last unit when there is more than one
to divide -- the promise is structural rather than hoped for. A single
indivisible unit is the one honest exception, and the wording no longer
over-promises.

The second one is the more instructive: the mechanic was defensible, and what
made it a bug was the observation asserting something the code contradicted.
PHASE4 §2 with the sign flipped, twice in one feature.

---

## 9. The loss got harsher, and then insurance was cut

**Being caught now costs between half the load and ALL of it**, rolled flat
(designer decision, 2026-08-20). No second probability on the size of the loss:
the odds of being caught are where all the structure lives, and grading the
severity too would make a load's fate turn on two rolls nobody can see apart.

The earlier guarantee that something always survived is gone. `_share_of` no
longer holds a unit back, because `LOOT_FRACTION_MAX` is 1.0 and clamping would
have made the worst case unreachable — and the worst case is the entire reason
to insure anything.

### Insurance is gone, and the reason is arithmetic

Cargo insurance was built, worked, and was then **cut entirely** along with the
Insurance Brokerage building (designer decision, 2026-08-20). `buy_insurance` is
gone from the action surface, the brokerage is gone from `GOVERNMENT_SITES`, and
the **Tavern takes its plot in Town** -- where an inn belongs, beside the market
everybody already walks to. The tavern has now outlived four homes.

The argument that cut it is one table. On a 600-denari load:

| risk | premium | expected loss | paid for nothing |
|---|---|---|---|
| 5.9% (the floor) | 33.19 | 26.55 | +6.64 |
| 17% | 95.62 | 76.50 | +19.12 |
| 75% | 421.88 | 337.50 | +84.38 |

The gap is positive at every point and **must** be: an underwriter charging
below expected loss goes broke, and an agent maximising net worth declines
anything above it. There is no price at which both sides want to trade. That is
not a mis-tuned load factor -- every load factor either bankrupts the insurer or
is refused.

Real insurance escapes this through RISK AVERSION. These agents are LLMs told to
maximise net worth, and they have none. The one honest source of it in Convoy is
that **ruin is absorbing** -- a business that misses payroll closes -- but acting
on that requires the observation to put ruin in front of the agent at the moment
it decides, which is a bigger and riskier change than the feature itself.

Two further reasons it did not survive: the premium only becomes affordable as
risk approaches the floor, so insurance could never substitute for the guards the
product actually wants bought; and every policy is decisions spent on both sides
of every shipment, which is the run's real budget.

**What was left behind is deliberately inert**: `Agent.insurance` still exists
and is always empty, `economy.insurance_premium` still computes, and `_kill`
still reads Life and Asset cover it will never find. That is the switch to flip
if a run ever shows agents reasoning about ruin rather than expected value.

### For the record: what it did before it was cut

`buy_insurance` has offered three products since Phase 1. `Life` pays out on
death; `Asset` gates the post-death wipe; **`Cargo` did nothing whatsoever.** An
agent could pay the 20% premium, be robbed, and receive zero. Not a missing
feature — a product that took money and returned nothing.

It now pays **the denari value of what was taken**, capped by the cover, and the
cover is consumed as it pays. Half a 600-denari load stolen is 300 arriving and
300 paid. A flat fraction of the policy would have made a claim and a loss two
different sizes, which is not something an owner can reason about.

**Priced off the road, not off a flat rate.** A flat 20% would charge the same
to cross the mildest stretch behind four guards as to take the Bridge alone —
that is a toll, not insurance. `economy.cargo_premium` is `chance of being
robbed x average loss x value`, times a load factor:

| journey | risk | premium on 600d cover |
|---|---|---|
| unguarded donkey cart, the long haul | 75% | **422** (70% of cover) |
| same load, three iron-armed guards | 17% | **96** (16% of cover) |

**Which teaches the right lesson in the right order: fix the road, then insure
what is left.** At 75% the premium is most of the cargo's value, and it should
be — that journey is not an insurable risk, it is a bad plan.

`CARGO_PREMIUM_LOAD` is 1.25, deliberately above fair odds. At fair odds the
state brokerage breaks even and no agent could ever profit by opening one, so
there would be no insurance market — only a state utility. The markup is the
room an agent-run broker has to undercut the government and still make money.

**A claim is paid to whoever actually lost something.** A hired courier carrying
a buyer-risk consignment loses nothing of its own, so its policy does not pay;
the loss is borne by the business, and it is that business's OWNER whose cover
is checked. `_rob_consignment` returns the bearer alongside the value.

---

---

## 10. The commodity ticker, and three boards for people watching

### The prices were already recorded

`Market.transactions` has held every sale in the valley since Phase 1 -- five
call sites writing item, quantity, unit price, both parties and the hour. Exactly
one function ever read it, `revenue_since`, and only to answer "what did THIS
seller take in". **Nobody had ever asked it what anything was worth.**

So every price an agent had was either a book price out of `data.py` or the one
counter in front of it. "Is 5.2 a good price for ore?" had no answer anywhere in
the world, and an agent could undersell its whole output for eighty hours with
nothing to tell it.

`economy.ticker` aggregates it: volume-weighted average, volume, trade count,
high, low, and how far the market sits from the book price, over a rolling
window. **Volume-weighted matters** -- a 100-unit sale at 4.9 and two small ones
at 5.2 and 6.1 give a VWAP of 5.13 against a naive mean of 5.4, and the naive
number would say ore is dearer than anyone is actually paying.

**Anonymous by construction.** A `Quote` carries no counterparty. A public feed
that names who bought and who sold is not a price feed, it is a surveillance
tool: it would let an agent see exactly who is short of what and price against
them personally. What sold, for how much, how often -- never whom.

It reaches agents narrowed to what they trade (their stock, their businesses'
inputs and outputs) plus the busiest few, because a full 62-item board is
per-call tokens forever on goods most agents will never touch.

### Three boards, for the person at the keyboard

Three stacked buttons top-left of the map: **Leaderboard**, **Convoy schedule**,
**Commodity prices**.

They are drawn as a DARK panel rather than the white card the map uses, and the
distinction is real: a card shows what one person in the valley could tell you
if you walked up and asked, and these show what nobody in the world can see.
Different source of knowledge, different surface.

- **Leaderboard** -- every agent, richest first, with job, what they are doing,
  and a bar showing WHERE the money is. Net worth alone says who is winning and
  nothing about how, and 3,000 in cash and 3,000 sunk in a mine that cannot make
  payroll rank identically and are not alike. The breakdown reconciles exactly
  with the ranked total, which `test_the_three_boards_assemble` pins.
- **Convoy schedule** -- loads on the road now, and how the finished ones went:
  value, cart, guards, and for a robbery the share lost and the risk it ran.
- **Commodity prices** -- the ticker.

The convoy history is read off the **event log, not the world**, because a
delivered consignment is deleted and a robbed one never existed in world state
at all. `robbed`, `consignment_posted` and `consignment_delivered` carry it.

`inspect.boards()` assembles all three -- same rule as the cards, one assembler
and two consumers, so a baked page and a served one cannot disagree.

### Two bugs the browser caught that the build did not

- **`money` was declared twice.** The popup already had one (2dp, with a "D"
  suffix, right for a card and far too wide for a column of twenty). The page
  died on a syntax error while `preview_world.py` reported success, because the
  renderer only writes the file -- it never loads it.
- **The buttons wrapped and the panel landed on top of them.** At 132px
  "Convoy schedule" took two lines, which grew the stack past the panel's fixed
  top. Only visible by looking.

---

---

## 11. The cart is never taken (designer decision, 2026-08-20)

Bandits take goods and leave the vehicle. No theft, no damage,
`VehicleInstance.condition` never changes -- that is the full game's business,
not this mode's. A vehicle lent with a consignment always comes home too, which
`_return_lent_vehicle` already guaranteed.

Worth writing down because it was true **by omission**: nothing in `banditry.py`
mentions vehicles, so nothing took one. An invariant nobody stated is one a
later edit removes without noticing, so it is now a paragraph in the module and
two tests -- one that robs across fifteen seeds and checks the cart survives
every time, one that takes a lent load down to zero units and checks the loan
comes back.

**A consequence for any future convoy bidding:** a driver on a convoy is NOT
risking its cart, so "commands a higher price because its own vehicle is at
risk" is not a justification that holds in this mode. If the cart is ever to be
at stake, that is a deliberate change in `banditry`, not a side effect elsewhere.

### The one path that still destroys a vehicle

`Engine._wipe_assets` destroys an agent's businesses, vehicles and property on
death, gated on `Asset` insurance -- and `Asset` insurance became unbuyable when
the whole line was cut. **So death now destroys carts unconditionally**, where
it used to be preventable.

Agents can still die: `_kill(agent, cause="starvation")` fires at
`engine.py:403` and PHASE4 §10 records A0029 dying exactly that way. This is
therefore a live path and a real change, produced by the insurance cut rather
than chosen. Flagged, not fixed -- it is death semantics rather than banditry,
and narrowing it is a decision about what death means in this mode.

---

---

## 12. The escort labour market (2026-08-20)

Agents can now be hired for convoys, in **every** role -- Driver-provided,
Driver-own, Scout, Bodyguard -- exactly as NPCs can.

**An NPC costs half again what a person does** (`ESCORT_NPC_MULTIPLIER = 1.50`),
mirroring `NPC_WAGE_MULTIPLIER` for employees. That number is the reason the
market can exist at all: if an NPC were the cheap option, no agent would ever be
worth hiring and `post_escort_job` would be a tool nobody used. It is the same
trap the wage multiplier was cut from 2.25 to 1.50 to escape, where the
convenient option was also the only viable one.

| role | an agent | an NPC |
|---|---|---|
| Scout | 10.70 | 16.05 |
| Bodyguard | 11.30 | 16.95 |
| Driver-provided | 14.20 | 21.30 |
| **Driver-own** | **20.70** | **31.05** |

`post_escort_job` advertises in world chat; `accept_escort_job` takes it. The
escort is paid **on arrival, not at hiring** -- which is the whole difference
between a person and an NPC: the NPC takes its premium up front, and the person
carries the risk of the journey with you.

**`Activity("convoy")` finally does something.** The kind has been in the state
model's docstring since Phase 1 and nothing had ever set it. A bound escort
travels when its employer does, because a guard that stayed behind while the
convoy walked off would still be counted in the risk calculation -- paid for,
priced in, and not there.

Three things that fell out of building it:

- **Driver-own must actually bring a cart**, and if it is faster than the
  employer's, the convoy moves at ITS speed. Otherwise the top rate buys nothing
  and the role is a worse-paid Driver-provided.
- **A lent weapon works like a lent vehicle** -- bound to the job, returned on
  arrival, impossible to keep, so it needs no trust system. It exists because an
  agent's own kit is usually the free Slingshot it started with, and a guard is
  worth what it is carrying. Measured: an unarmed agent guard moved the odds
  75% -> 66%, against 75% -> 24% for an NPC with a spear.
- **`you_can_take_it` is derived per agent**, like `you_can_carry_it` on a
  carriage advert. A Driver-own job is unclaimable without a cart, and finding
  that out should not cost a decision.

### The budget is now the binding constraint

The two new tools cost 376 tokens and pushed the cached prefix to **14,030
against a 14,000 guard**. Rather than raise the ceiling -- which a previous run
died on at hour 47 -- the tokens came back out of my own prose in the three tool
descriptions and the BANDITS paragraph.

Prefix now **13,954**. Forty-six tokens of headroom, and the largest prompt ever
observed to work on this key is 14,081. There is no room left for another tool
without spending the `item` enum, which the schema test warns costs refusals.

---

---

## 13. What the 20-agent run found, and the two rules it changed

Stopped at hour 15.9 with 6,859 events: 8 businesses founded, 38 consignments
delivered, 62 trades -- and **zero robberies, zero escort hires**.

### Agents routed around the whole system, and were right to

Twenty of 26 haulage jobs were posted for **exactly five units** -- foot
capacity. Every one of the 38 loads delivered was ten units or fewer, while four
hundred-unit loads sat unclaimed for hours. One agent said it at h0.08:
*"Traveling by foot feels safer."*

None of that was a bug. Walking was immune, walking caps you at five units, so
the market sized every job to five units and walked it.

**The trade-off we relied on does not survive a labour market.** Foot immunity
was accepted on the grounds that walking is slow, so splitting a load costs more
in time than it saves in risk. True for ONE agent. Twenty couriers each walking
five units move a cart's tonnage, and the time is paid in parallel by spare
labour rather than serially by the shipper.

Worse, the numbers said to do it: a median 8.00 fee over a 0.08h delivery is
**96 denari/hour against a median wage of 17.22** -- couriering paid 5.6x a job,
at no risk. Nobody bought a cart because nobody needed one.

**Foot immunity is gone (2026-08-21), and nothing replaced it.** The equation
already described a pedestrian correctly: slowest on the road so exposed
longest, `p_escape` of exactly zero, and no deterrence -- only a cheap load
protects it, and only while the load is cheap.

| load | mine->refinery | long haul |
|---|---|---|
| on foot, 5 ore (~30d) | 17% | 42% |
| on foot, 5 daggers (~600d) | 53% | **92%** |
| Donkey Cart + 2 iron guards | 8% | 24% |
| 4-Horse + 3 guards | 3% | **6%** |

Per unit delivered the ladder now runs 0.32 -> 0.18 -> 0.045, so a guarded
chariot is seven times more efficient than walking. `test_splitting_a_load_no_longer_buys_safety` pins that.

### Nothing was ever negotiated

26 seller-posted loads all went to the **state** refinery; 14 buyer-pulled
orders defaulted to buyer-pays because market power was "evenly matched" at one
producer per good. `_settle_responsibility` never fired once.

---

## 14. Convoy splits (2026-08-21)

`responsibility` was binary and is now a **ladder**: `CONVOY_SPLITS` of
100/0, 75/25, 60/40, 50/50, 40/60, 25/75, 0/100, held as
`Consignment.seller_share`. A rung rather than any number, because a
negotiation with a continuum has no focal points -- nobody shakes hands on
62.5/37.5, and every extra choice is another decision to price.

**The split covers the courier fee AND the robbery loss**, by the same
fraction. Paying for a convoy while not carrying its risk is not a deal anybody
would offer. The poster still escrows the whole fee -- a courier must be certain
of payment and cannot be made to chase two businesses -- and the counterparty
reimburses its share on delivery (`_settle_convoy_cost`), with a shortfall
recorded rather than the delivery refused.

**Scarcity sets the customary rung**, exactly Justin's rule on the ladder
instead of as a coin flip:

| market | customary (seller/buyer) |
|---|---|
| 3 mines, 1 refinery | **75/25** -- the mines carry most |
| 1 mine, 3 refineries | **25/75** -- the refineries carry most |
| evenly matched | 50/50 |

An agent may always offer to carry MORE than customary; it is refused only when
demanding the other side carry more than its market power supports.

### The state never carries a share, and that is the point

`GOVERNMENT_BEARS_NOTHING`. Sell to a state business and the whole convoy is
yours; buy from one, likewise. Not the treasury being greedy -- it is the first
reason in this economy to compete with the government rather than merely
alongside it. Measured:

    ship 100 ore to the state refinery   -> Mara pays 60, the state pays 0
    ship to an agent's refinery at 0/100 -> Bel pays 60, Mara pays 0

**One limit worth knowing.** `post_delivery_job` refuses third-party
destinations -- a rule that predates this ("a delivery to someone else is a
sale, and a sale needs the other side to agree a price"). So a seller cannot
push a load to a rival refinery with an attractive split; the rival must PULL
with `order_from_business`. The incentive survives, reversed: an agent buyer
attracts sellers by offering to carry more of the convoy than the state ever
will.

### The budget

Both guards were raised deliberately -- prefix 14,000 -> 14,500 and briefing
5,100 -> 5,300 -- for the escort market, the split parameter and the three new
briefing blocks. What makes it safe is evidence rather than hope: a live call at
this size returned in 2.2s, and the 20-agent run made ~280 calls at ~14k with
one read timeout and no rejection, at $9.77 remaining. **That headroom shrinks
as credit is spent.**

---

## 15. Run it plugged in

The 20-agent run took **8.27 wall hours to reach sim hour 3** because the laptop
slept: `pmset` showed it entering sleep repeatedly all night and waking at
08:18, which is exactly when the run resumed. Awake it manages **9.3x
realtime**.

PHASE5's own recipe already ended with `caffeinate -is -w $(pgrep -f "MacOS/Python run_phase2.py" | head -1)` and it was dropped when the command was
retyped. Use it. Note that `-s` is ignored on battery and neither flag prevents
lid-close sleep, so: **on AC, lid open.**

---

## 16. What is not done

- **No run has ever exercised this with a real model.** Everything above is
  verified against unit tests and a `--dry-run` that builds prompts and calls
  nothing.
- **The map does not draw a robbery.** The convoy board lists them, but nothing
  appears on the map or the replay timeline at the hour it happened -- though
  `robbed` is logged at HIGH significance with a `warning` glyph, so the
  surfaces have what they need.
- **No convoy composition screen.** Deferred by decision on 2026-08-20: this
  mode observes agents rather than driving them, so there is nobody to compose a
  convoy for. The bidding, lent weapons and driver-provided vehicles that screen
  implied are unbuilt with it.
- **The full convoy posting is still unbuilt** — `CONVOY_MAX_VEHICLES`, the
  recruit window, extensions and the cooldown remain wired to nothing. Escorts
  are NPCs hired at dispatch, deliberately: agent-to-agent recruiting turns
  every shipment into several decisions for several agents, and decisions are
  the budget.
- **Insurance exists and is not connected.** `insurance_premium` /
  `insurance_payout` have been in `economy.py` since Phase 1, and a road that
  can now actually take your goods is the first time they would mean anything.
