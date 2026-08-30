# PHASE 8 — the state withdraws, and the observation catches up

2026-08-21 to 2026-08-22. Two 20-agent runs of the same experiment, the second
of which worked. Then the viewer that makes any of it watchable.

Read `PHASE7.md` for the convoy system itself. This is what happened when it met
a real economy, and the four observation bugs that decided the outcome.

---

## 1. The experiment, and the result

At a set hour the government closes every business it owns. Nine businesses, the
only refinery, the only tavern, the only stable, and the employer of sixteen of
the twenty agents. The question is whether a synthetic economy can stand up
without a buyer of last resort.

**Run one (h36 withdrawal, done by hand): seven agents starved.**
**Run two (h36 withdrawal, scheduled): zero starved, four refineries founded.**

The difference was not the model, the map, the prices, or the agents. It was
four things the code knew and never said.

---

## 2. What the agents did wrong, and why it was our fault

In run one, after the state closed, agents kept executing the habits of a world
that no longer existed:

| in 251 decisions after the collapse | |
|---|---|
| `buy_meal` (from taverns with no stock) | **224** |
| `wait` | 126 |
| `send_direct_message` | 113 |
| **`loot_ground`** | **0** |
| **`start_business`** | **0** |
| **`set_production`** | **0** |

They tried to BUY food 224 times and never once tried to MAKE any. Seven died.

Standing in the wreckage the whole time:

- **150 Wheat lying in a field at Millrace Farms**, never touched.
- **A refinery, owned, open, empty and idle** -- its owner ended the run with
  39 denari standing in Town, having never gone back to it.
- **Eight agents who could afford to found a refinery outright**, and sixteen
  free plots at Refinery Row to build one on.

The richest survivor was **starving in Town with 1,380 denari**, reading this:

    Main road: you can afford to found here but there are only 0 unsold plots
    and a business needs 4.

True, locally, and useless. **The affordance system answers "what can I do
HERE" and never "what does the valley NEED".** PHASE4 §2 at the scale of a whole
economy.

---

## 3. The four things the observation never said

### `nobody_makes` -- the structural gap

For each good in the food chain, whether anyone is actually PRODUCING it, and
if not, whether the plant exists and is merely idle or does not exist at all.
Those are different problems with different answers -- go and switch that one
on, versus found one -- so the line says which:

    NOBODY IS MAKING Purified Water, though a Refinery stands idle at Refinery
    Row (yours). Switching it on needs feedstock, a worker and set_production.

**CAPABLE IS NOT PRODUCING.** The first version counted businesses that COULD
make a thing, via `banditry.market_power` -- and by that measure the valley had
a refinery while seven agents starved. It counts actual production and stock
now.

Note the "(yours)". The refinery's owner is pointed at the exact thing it owned
for 36 hours and never used.

### `SAY WHY` -- asking them to explain themselves

Reasoning has been captured since PHASE4 §9, but what is captured is the model's
THINKING -- a stream of thought that wanders, and often lands somewhere other
than the actions emitted on the same turn. Measured: an agent bought a
600-denari cart at h23.27 while its recorded prose was about which courier job
id to take, so asked later why it bought the cart it could only answer,
correctly, that it had not said.

Nothing in the briefing had ever asked an agent to justify an action. Now:

    SAY WHY. Everything you think before you act is recorded, and people will
    ask you about it later by name and hour. State briefly why you take EACH
    action [...] A decision you did not explain is one you can only answer for
    with "I did not note why".

It worked immediately and visibly. Run two's reasoning opens with literal
`**Why:**` headers and reads like justification rather than musing.

### Ground loot -- a tool nobody could see

`loot_ground` has been in every agent's hands since Phase 1 and **nothing has
ever told them there was anything on the ground to pick up.** The pile lived in
`world.ground_loot` and appeared in no observation. Goods dropped by a death, or
by the state withdrawing, sat there for the rest of the run.

Found while asking where a closed business's stock should go: the answer is
"the ground", and the answer was useless until the observation said so.

### The briefing was lying about the map

`observe.py` told every agent, on every call, that **"Sixteen spur roads
dead-end off the main road."** There have been four since the second map recut.
Counted off `world_map` now rather than written down.

PHASE4 §2 is usually the observation WITHHOLDING something. This is the same
failure with the sign flipped -- asserting something the code knew to be false --
and it survived two recuts because nothing reads prose.

---

## 4. The withdrawal is a mechanism now

`--state-exits-at HOUR` (`EngineConfig.state_exits_at`). At that simulated hour
the engine closes every government business, releases its staff, spills its
stores onto the ground as loot, **releases its plots back to the market**, and
announces it at HIGH significance.

Scheduled inside the engine rather than done by stopping and editing a
checkpoint, because the hand-done version let a changed prompt in halfway and
made it two experiments instead of one.

**The plots matter more than they sound.** Closing a business does not release
its land, so the state's holdings stayed locked under an owner that no longer
existed -- twenty of Town's forty plots. That is why a starving agent with 1,380
denari was told there was nowhere to build. Released as RAW land, not developed:
the buildings go with the state, the ground returns at the ordinary price.

`test_the_state_can_withdraw_on_schedule` pins all of it, including that it
fires exactly once and never when unscheduled.

---

## 5. Run two, hour by hour

The state closed at h36. **Sixty-two minutes later:**

> *"I will found a Refinery here with 450 denari: ownership converts capital
> into an appreciating business, and Refinery Row is the only place where
> refining can be done."* -- A0047, h37.08

| after the withdrawal (h36 -> h58.55) | |
|---|---|
| businesses founded | **8** -- 4 refineries, 3 farms, 1 mine |
| jobs posted / hires | 5 / 17 |
| escorts hired | 4 |
| **starvations** | **0** |

**The escort market turned on for the first time ever.** Zero hires in every
prior run; two agents developed a standing habit of hiring a Scout before every
haul, one of them at zero cargo value.

**Robberies more than tripled** -- 9 in the state-backed first half, 30 in the
22 hours after. Nobody engineered that. With the fixed government buyer gone,
agents had to move goods between each other, and more cargo on the road means
more of it taken. A market appearing shows up in the crime rate first.

**Two of the final top five founded a mine in their first hour**, before any
pressure to. The collapse rewarded agents who had already taken the ownership
risk; all five ended up owning a refinery or something feeding one.

---

## 6. The viewer

The map was a static board. It is now something you can watch.

- **Thought bubbles.** The models title their own reasoning -- every entry opens
  `**Planning transport logistics**` -- so the bubble text is written by the
  only party that knew what it was thinking. `_gist` takes the bold header, or
  falls back to the first action.
- **A ticker**, bottom right: robberies, deliveries over 100 denari, purchases,
  foundings, deaths. Nothing smaller -- a feed that reports everything reports
  nothing. Each line jumps to its moment.
- **Rank rings** -- green on the leader, yellow on the poorest, blue on whoever
  you follow.
- **Follow an agent**: click, then "follow" on the card. Grabbing the map hands
  the camera back.
- **A courier's pack** instead of the old hooded cloak, drawn only between
  collecting a consignment and delivering it -- a real timeline, not "anyone in
  transit". The cloak became the bandits.
- **Ambush staging.** Three hooded figures converge on the convoy over the
  seconds before a recorded robbery, with a ring tightening as they close.
  **This is a dramatisation and the code says so**: the sim records one event at
  arrival, not an approach. What is real is that it happened, when, on which
  road, to whom, with what cart and how many guards. The figures walking in are
  invented.
- **Click-to-rewind.** Every convoy history row jumps to its hour with the
  camera locked on the agent.
- **An advice report card**, the fourth board. What was said, whether the agent
  HEARD it (`times_seen`, written when text enters a prompt and by nothing
  else), what it did after, and **how it did against the field** -- because an
  agent that gained 200 in a valley that all gained 200 was not helped. Only the
  whole-leaderboard `Snapshot` makes that subtractable.

---

## 7. Five bugs that only showed up by looking

**Agents had never moved in any replay.** A travel decision emits several events
at one timestamp, so a plain "standing at X" row could land AFTER the departure
row carrying the destination -- and the lookup takes the last row at or before
the hour. Measured: **0 of 3,160 sampled frames had anyone moving**, while
PHASE6 recorded that they interpolate along the road. Fixed by sorting
departures last at equal times. Now 74.8%.

**`data_uri` hard-coded `image/png`.** An SVG served as PNG does not error --
it loads as a **zero-by-zero image and draws nothing**, which looks exactly like
art that was never wired up. That is why the vehicles appeared missing.

**The vehicle sprites were six times too big.** `sprites.vehicle_sprite` prefers
the Blender renders in `vehicles-3d/`, which are 192x96 against a 32-pixel
person -- PHASE6 §4's "brown mass at map scale" exactly. The map uses the 64x64
hand-drawn SVGs.

**The rank rings ranked the wrong thing at the wrong time.** They read the
FINAL leaderboard, so scrubbing back to hour 10 still ringed whoever finished
first. And they ranked the dead -- run two's poorest agent starved at h70.8, and
a corpse is not drawn, so the yellow ring never appeared at all. Now ranked at
the slider's hour off each agent's own last reported net worth, among the living.

**A successful delivery never recorded what carried it.** `robbed` always logged
the vehicle, because `banditry` needs it to price the risk; `consignment_delivered`
never asked the same question of itself. So every robbed row named a Donkey Cart
and every delivered row named nothing, which READS as "carts get robbed" and is
really "deliveries are vehicle-blind". Now logs `vehicle` and `escorts`, with
`"On Foot"` rather than a blank -- walking is an answer, not a missing value.

---

## 8. Operational lessons, all learned the hard way

**Sleep kills a run.** The first 20-agent run took **8.27 wall hours to reach
simulated hour 3** because the laptop slept: `pmset` showed it entering sleep
repeatedly all night and waking at 08:18, which is exactly when the run resumed.
Awake it manages **9.3x realtime**.

    caffeinate -ims -w $(pgrep -f "MacOS/Python run_phase2.py" | head -1)

`-s` is ignored on battery and neither flag prevents lid-close sleep. **On AC,
lid open.** PHASE5 already said this and it was dropped when the command was
retyped.

**A key limit ends a run silently.** Run two hit `HTTP 403: Key limit exceeded`
at h58.55 and ran on to h72 with **1,500 failed calls and zero decisions** --
production, wages and hunger all tick without a model, so the world kept moving
while nobody steered it. One agent starved in that window; it is an artifact of
the outage, not a finding. **Treat that run as 58.5 hours, not 72.**

The key had its own `limit: 20`, separate from the account balance. Check
`https://openrouter.ai/api/v1/auth/key` before a long run.

**Cost: ~$5.90 for 20 agents x 72 hours.** More than double the $2.50 estimate,
because a population that founds, hires and hauls generates far more decisions
than one grinding wages. Budget $6 for a full run.

**There is only one checkpoint file and it is overwritten hourly.** There is no
rolling back to an earlier hour. A run that coasts through an outage saves that
state over the last good one.

**A schema change can destroy every saved world.** Renaming
`Consignment.responsibility` made `checkpoint.load` die on every existing file.
`_decode` now drops fields the dataclass no longer has and REPORTS them, because
losing a checkpoint is far worse than losing a field from it.

---

## 9. What is not done

- **Nothing tells agents the state is going to leave**, deliberately. Forewarning
  tests obedience rather than adaptation, and the real game will not warn anyone.
- **The `nobody_makes` line covers the food chain only** -- Purified Water,
  Grain, Meal. It does not notice a valley with no weaponsmith.
- **The advice report card has never been used in anger**, because both runs
  were launched without `--advise`.
- **`serve.py` cannot advise a RUNNING world.** It writes into the checkpoint,
  which the engine overwrites on the hour. Advice is picked up by `--resume`.
  Asking is safe and works live.
- **The delivery-vehicle fix postdates both runs.** Their logs will never show a
  cart on a delivered row; the next run will.
