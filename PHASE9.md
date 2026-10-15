# PHASE 9 — two cities, and a prompt that was throwing three blocks away

2026-09-03. The simulation becomes a CONTEST: two mirrored valleys, twenty
agents each, no road between them, scored on which city's total net worth is
higher. Plus the bug found on the way, which is the more important half of this
document.

Read `PHASE8.md` for the world this rests on. `PHASE4.md` §2 remains the first
thing to read before debugging any agent behaviour; this session added two
entries to it, and one of them had been silently eating PHASE8's own fixes.

---

## 1. The shape of it

**Two valleys, generated from one template, with no road between them.**

    ALDERMARCH                          CINDERHOLD
    Refinery Row                        Cinder Row
        |                                   |
    The Hills  -- 4 spurs               The Ashfells -- 4 spurs
        |                                   |
    Town (market)                       Cindergate (market)

              no road, ever

Each city is the demo map, exactly: three stops, two segments, four spurs, 160
plots, one government branch of every type, twenty citizens. **Aldermarch keeps
the demo map's names, place for place** -- every checkpoint, event log and
rendered page on disk refers to `Town`, `The Hills`, `Refinery Row` and the four
spurs by those names, and renaming them to make the mirror prettier would have
made every saved world unreadable and every geography test a rewrite, for
nothing.

**Nothing structural is written twice.** Elevations, segment timings, terrain
modifiers, the concealment/vantage/exposure triples, plot supplies and which
role the state seats each branch on are defined once per ROLE and each city is
that template under its own names. `assert_cities_are_mirrors()` runs on every
import and compares the two by structure, ignoring names, because "identical by
construction" is a claim that rots the first time somebody special-cases one
side to see what happens.

### Why isolated rather than joined

The alternative was one long road with a contested middle, which is more
dramatic. It was rejected because the question being asked is *how do two
populations under identical conditions diverge*, and a trade route between them
makes each city's result partly a function of the other's play. The cities meet
in exactly one place: **the scoreboard**.

Isolation is enforced, not merely conventional. `road_path` raises
`NoRoadThere`; `travel_to` refuses with a message that distinguishes "no such
place" from "that place exists and you cannot walk to it"; world chat is scoped
to the speaker's city; the price ticker is per-city; the job board, the courier
board, the escort board, the land market and the remote-ordering list are all
filtered to the agent's own valley. `test_cities.py` asserts that the rival
city's names appear **nowhere** in an agent's observation.

### The objective

    FIRST:  your city wins if its citizens' TOTAL net worth beats the rival's.
            A citizen of the losing city has lost, however rich it personally is.
    SECOND: within your own city you are ranked against your own neighbours.

Not pure collectivism. With only the city total to play for, no citizen has a
private reason to be the one who takes the founding risk rather than the one who
watches somebody else take it, and the predictable result is a valley of
free-riders that reads as the model being passive. Not pure self-interest
either, or the two cities are two unrelated runs sharing a page. Both terms, in
a stated order, so an agent facing a trade between them knows which way to break
the tie.

**The score is a SUM, and that is the interesting part.** Death already wipes an
agent's businesses, vehicles and home, so a corpse contributes its pocket change
-- and the survivors averaging higher never makes it back. The briefing says so
outright: *"a citizen who starves is a hole in your city's score. Feeding
somebody who is Starving is worth more than the meal costs."* Whether that
produces any actual mutual aid is the thing to watch in the first real run.

---

## 2. THE BUG: three PHASE8 blocks were built and never said

`observe()` returns a dict. `render()` turns it into the prompt text **from a
whitelist of keys**. Nobody extended the whitelist when PHASE8 added its blocks.

Measured on a world constructed to fire all of them, at commit `9fafd47`, before
any of this session's changes:

| block | built into the observation | reached the prompt |
|---|---|---|
| `nobody_makes` | yes | **no** |
| `on_the_ground_here` | yes | **no** |
| `market_prices` | yes | **no** |
| `escort_jobs` (PHASE7) | yes | **no** |

PHASE8 §3 credits four fixes for run two's outcome -- zero starvations against
seven, four refineries founded. **Three of those four never reached a single
prompt.** The two that were real were `SAY WHY` and the spur count, both of
which live in `static_briefing`, which is rendered directly and not through the
whitelist.

So PHASE8's headline conclusion needs restating: *"the fix wasn't hints or
scripts, it was telling agents four things the code already knew"* is right about
the method and wrong about three of the four things. What actually changed
between run one and run two was the briefing (`SAY WHY`, the corrected map) and
the withdrawal being scheduled rather than done by hand. **The economy recovered
without ever being told that nobody was making food.** That is a more
interesting result than the one on the record, and it is now untestable against
the old runs, because the blocks are wired up from here on.

This is PHASE4 §2 happening to PHASE8's own entries in PHASE4 §2. The general
shape -- *the code knows, the prompt does not say* -- has now been the
explanation for nineteen behaviour bugs and for the fix to three of them.

`test_cities.py::test_phase8_blocks_reach_the_prompt_too` pins all three by
name, and the contest block is pinned the same way, so a block added to
`observe` and forgotten in `render` fails a test rather than a $12 run.

### The order is the point

The whitelist is also the ORDER. The observation runs past 20,000 characters and
a model reads the top of it best, so the things an agent is scored on go first:
advice, **the contest**, what you have, where you are, what is lying at your
feet.

---

## 3. What else this changed

**`_nearest` killed the tick, not the action.** `rule_agents._nearest` searched
every business in the world for the closest one of a type; with two valleys, the
first thing it did was ask `travel_seconds` for a route that does not exist, and
`NoRoadThere` came out through the engine's tick rather than through a refusal.
Found by running a real 16-hour two-city simulation, not by any unit test --
which is the argument for running one before believing any of this.

**`order_from_business` is the only path that could create a cross-city
consignment.** Ordering is remote; carriage is not. The observation never offers
a rival seller's id, so the guard there is defensive -- but the failure mode
without it is a load with no road to travel, discovered by
`suggested_courier_fee` raising mid-tick.

**Respawn sent the dead to Aldermarch.** `agent.location = "Town"` was fine while
there was one market. It would now teleport a dead Cinderholder across a border
with no road back.

**The chat normalisation was asymmetric and I wrote it that way.**
`ChatMessage.visible_to` compares the message's city against the agent's RAW
`city` field; stamping the message with the NORMALISED value made a legacy agent
(city `""`) unable to read its own messages. Caught by `test_social`.

**The race chart's colours contradicted the table beside it.** `history` is keyed
in standings order, which is sorted by wealth and changes hands during a run, so
indexing the palette by row position drew Aldermarch's line in Cinderhold's
colour. One city is one colour everywhere on the page now.

---

## 4. The viewer

`preview_world.py` draws both valleys side by side with open country between
them and **no road across it** -- one polyline per city, never joined, because a
single road drawn through both would be the page asserting a journey the engine
refuses to allow.

* **City tabs** on the boards: `Both | Aldermarch | Cinderhold`. Filtering, not
  highlighting -- the question a tab answers is "how is Cinderhold doing", and
  twenty of its citizens interleaved with twenty of somebody else's does not
  answer it. `Both` stays the default, because the comparison is the point.
* Switching city **takes the camera with it**, framing that valley. On a map
  twice as wide as it used to be, "show me Cinderhold" should not be two
  separate actions.
* The **Leaderboard** grows a colour-coded city column when both are shown, and
  ranks agents **at home** when one is -- because that is the number a citizen
  is actually scored on.
* A new **contest board**: both totals, the gap, who has led and since when, and
  the race as a line per city.
* The race chart is **not zero-based**, and says so under itself. Two cities that
  both grew from 300 to 2,500 are two indistinguishable lines on a zero-based
  axis, and the only thing anybody wants from a race chart is where the lines
  separate. Both lines share one scale, so the comparison between them is exact.

The panels now sit below the button stack by measurement rather than at a
hard-coded 166px, which was already a tight fit under four buttons and became an
overlap the moment a fifth was added.

---

## 5. Running it

```
python3 run_phase2.py --cities 2 --agents 20 --decisions 800 --hours 72
```

`--agents` is **per city**, so that is forty agents. `--cities 1` is the default
and is the single valley every earlier run used, unchanged.

Then:

```
python3 preview_world.py --run runs/phase2/<stamp>
```

### What it costs

Measured against a one-city run:

| | one city | two cities |
|---|---|---|
| cached briefing | 20,988 chars | 22,440 (+1,452) |
| per-call observation | 3,243 chars | 3,514 (+271) |
| distinct cached prefixes per run | 2 | 4 |
| agents | 20 | 40 |

The per-call growth is ~8%. **The cost is driven by the population, not by the
feature**: twice the agents is twice the decisions. PHASE8 measured $5.90 for 20
agents over 72 hours, so **budget $14** for 40, and re-read PHASE8 §8 before
launching -- the key limit, `caffeinate`, and the single overwritten checkpoint
all still apply, and they now apply to a run that costs twice as much to lose.

---

## 6. What is deliberately not done

* **The cities cannot see each other's play, only each other's score.** No
  intelligence, no espionage, no ability to learn what the rival did. That is
  the price of a clean comparison and it is paid on purpose.
* **Nothing rebalances a city that falls behind.** No catch-up mechanic, no
  handicap. If one city loses three citizens at hour 20 the run is effectively
  over as a contest, and it will still run to 72 hours.
* **`assign_archetypes` deals across the combined roster**, so a rule-based
  two-city smoke run does not give both cities an identical archetype mix. It
  does not matter -- archetypes are unused from Phase 2 on -- but it means the
  16-hour smoke run's near-tie (2,518 vs 2,491) is a weaker fairness signal than
  it looks.
* ~~The state still withdraws from both cities at once~~ -- **done 2026-10-14**:
  `--state-exits-city cinderhold` (with `--state-exits-at`) withdraws the state
  from that city only. Per-city record in `World.state_withdrawn_in`; every
  reader asks `world.state_gone_at(city)`. See §10.
* **A third city would work**, structurally -- `CITIES` is a dict and everything
  reads it -- but nothing has drawn three valleys and `rival_of` assumes exactly
  one rival.

## 7. The valuation, changed twice over

`Business.valuation` was `startup_cost + 3x gross revenue + cash + stock`. It is
now:

    2 x startup_cost  +  3 x max(0, profit above book)  +  cash  +  stock

**Founding now pays.** A 450-denari refinery is worth 900 the instant it stands,
so founding CREATES 450 rather than moving net worth sideways. Four smoke runs
once produced no business at all from agents who could afford one and were told
so; a neutral trade is a weak invitation to take a risk. Bounded by land, which
is finite.

**Goodwill is on PROFIT ABOVE BOOK, not on gross revenue**, and this one is a
fix rather than a tuning. On gross revenue every sale minted 3x its price in net
worth whether or not the seller earned anything, so two agents passing the same
goods back and forth at book price generated unbounded value from a trade that
moved nothing. Individual scoring limited that -- handing a counterparty 3x was
arming a rival. **City scoring counts both sides for you, so the wash trade
became the dominant strategy the moment the contest existed.** Measured after
the change: five round trips at book price move a business's valuation by
exactly zero.

Losses are floored at zero *in the goodwill term only*. Selling below book
already costs you -- the stock leaves at base price and less cash comes back --
and multiplying that by three as well would charge it twice, making a sale to
the state at 0.4x a catastrophe rather than a bad price.

| 20 Bronze, book 32 | margin | goodwill | business worth |
|---|---|---|---|
| to the state @0.4x | -384 | 0 | 1,156 |
| at book | 0 | 0 | 1,540 |
| at 1.4x book | +256 | +768 | 2,564 |

**The residual, stated plainly:** margin kills the FREE wash trade but not a
determined one. Two citizens trading above book still mint 3x the margin for the
city each pass, at the buyer's expense -- the seller gains more than the buyer
loses, so under city scoring it remains rational. The cheap cap if it shows up
in a run is to bound 24h goodwill at some multiple of startup cost.

The briefing carries all of it, because an agent that has not been told profit
is measured above book will price at book, watch its valuation never move, and
have no way to find out why. `test_observe`'s token budget went 5,300 -> 5,400
to pay for it, documented in the same style as every earlier raise.

**One briefing line had to be corrected rather than added.** It said squeezing a
neighbour for 50 denari "changes the score by NOTHING". Under any
revenue-or-margin multiple that is false -- the extra 50 books 150 of goodwill --
so it now says such a trade *mostly* moves money between pockets, and points at
production as the thing that actually grows a city.

---

## 8. The dark grey bars

Place-name labels drew their background plate and not their name. The plate was
positioned with `wx(p)/wy(p)` and the text with `p.sx/p.sy`, which a place
record does not have -- it carries `x`/`y` and nothing else -- so `fillText` ran
with two undefined coordinates and drew nothing. What you saw was a row of dark
bars floating over buildings and road: a label with no label on it.

Both use the same coordinates now. The labels earn their place more than they
did: with two valleys on one page, the name over a settlement is what tells you
which city you are looking at.

---

## 9. The open question, restated

PHASE8 ended on conflict: agents optimise in parallel, guild machinery is built
and unused, almost no direct trade. This does not solve that inside a city, and
it deliberately makes it impossible between them.

What it does is give twenty agents a shared reason to care what the other
nineteen are doing. Whether "your neighbour starving costs you" produces
anything that looks like a society -- or twenty individualists with a shared
scoreboard they ignore -- is the thing the first real run is for.

---

## 10. The next run, set up 2026-10-14

    caffeinate -ims python3 run_phase2.py --cities 2 --agents 20 --hours 72 \
        --decisions 800 --state-exits-at 36 --state-exits-city cinderhold

**The government leaves Cinderhold at hour 36 and stays in Aldermarch.** A
controlled experiment: identical valleys, identical rules, one variable.
Aldermarchers are never told; the cities see only each other's score.

**GPT-6 Luna** replaced GPT-5.6 Luna everywhere, at the same "medium" effort:
$0.10 / $0.50 per Mtok against $0.20 / $1.20. It writes about twice the output
tokens per decision, so the real saving is about half, not more: the smoke test
measured $0.00057 a call against $0.00099. Budget about $9 for the run.

**The decision cap is 800**, up from 400. The smoke test measured 5.4 decisions
per agent-hour, which is ~390 over 72 hours -- right at the old cap, and an agent
at its cap stops deciding for the rest of the run.

**The map stacks the cities north and south with a river between them** (world
x is screen y, so `VALLEY_PITCH` was already a vertical separation; what was
missing was anything saying so). `layout.border_rivers` centres the water in
the measured gap, and `check()` proves nothing of either city stands in it.

**Smoke tests go to `--runs-dir runs/smoke`.** The public server follows the
newest run under `runs/phase2`; a smoke test there is shown to the world as the
live simulation.

Smoke test (2 cities x 4 agents, 3 hours, state out of Cinderhold at 1.5): 129
calls, 0 errors, $0.07; all 9 of Cinderhold's government buildings gone at
h1.50, all 9 of Aldermarch's still standing at h3; one of 33 post-withdrawal
thoughts mentioned the government, none expected it back.
