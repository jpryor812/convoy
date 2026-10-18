# Convoy — video plan: the two-city contest (run 20261015-001645)

40 AI agents (GPT-6 Luna) in two identical cities. **Aldermarch** keeps its
government for all 60 hours; **Cinderhold** loses it at hour 30. Score = each
city's total net worth.

Final: **Cinderhold 40,142 — Aldermarch 28,315.** Subtract ~11,400 of government
stock Cinderhold scavenged after hour 30 and it is roughly a tie.

Quotes below are the agents' own words from their notes or world chat.
**[inferred]** marks an action the agent did not explain, where the reason comes
from what was going on around it.

---

## Capture guide

- **Site:** `jpryor812.github.io/convoy` (replay works any time; chatting with
  agents needs `go_live.py` running on the laptop).
- **Time:** slider steps in quarter hours; ▶ plays 0.6 sim-hours per second
  (1 hour ≈ 1.7 s; whole run ≈ 100 s). Moments in hour 0–0.5 last under a
  second — record at normal speed, slow 4–8× in the edit.
- **Map:** Aldermarch on top, Cinderhold below, river between. Each town runs
  west → east:
  - Aldermarch: **Refinery Row → The Hills → (bridge) → Town**.
    Roads: **Slagside Road** (Refinery Row–Hills), **The Bridge** (Hills–Town).
    Spurs: **Copper Gulch** (mine), **Millrace Farms**.
  - Cinderhold: **Cinder Row → The Ashfells → (causeway) → Cindergate**.
    Roads: **Ashside Road**, **The Causeway**.
    Spurs: **Iron Gulch** (mines), **Windmill Fields** (farms).
- **On screen:** thought bubbles; ticker (bottom right); **The contest** board
  (race chart); green ring = richest, yellow = poorest at the slider's hour;
  hooded-bandit animation at each robbery; click an agent → their notes,
  filtered to the slider's hour.

---

## 1. Setup — two identical cities, one variable

- **Screenshot:** hour 0, press `0` for the whole map; **The contest** board at
  hour 0.

## 2. The opening rush (hours 0–0.4)

14 businesses in the first minutes. Aldermarch's founders bought town shops;
most agents in both cities took government wage jobs.

- **Clip:** Aldermarch's Town and Cinderhold's Cindergate, hours 0 → 0.5.
- **Why Aldermarch built shops:** the valuation rule — a business counts at
  twice what it cost on day one — plus missing food.
  - Aldermarch-01: *"I'm founding a Town tavern: it immediately adds an owned
    business to Aldermarch's wealth, and meal production is currently missing."*
  - Aldermarch-10: *"its 2× valuation immediately adds 250 denari to both my net
    worth and Aldermarch's."*
  - Aldermarch-11: *"its immediate 2× valuation adds 300 net worth to me and
    Aldermarch."*
- **Why the shops sat idle:** they needed grain and water nobody in Aldermarch
  was making, so the founders took government jobs instead.
  - Aldermarch-05: *"I'll work my existing government Store Clerk job for 10
    hours: it gives reliable liquid income… then look for a practical way to put
    the tavern to work."*
  - Aldermarch-20 (hour 0.08): *"I'm founding a small Tavern / Inn at Refinery
    Row rather than duplicating a mine or refinery I can't fund."* By 0.33:
    *"My Tavern is funded only with its asset value and cannot operate without
    feedstock."*

## 3. The mine that decided the game (hours 0.18–0.37)

Cinderhold-17 founds a mine at Iron Gulch (0.27). Cinderhold-16 (0.33),
Cinderhold-09 and Cinderhold-15 (0.37) follow. Aldermarch's first mine: hour 34.

- **Clip:** Iron Gulch, hours 0.15 → 0.4; click Cinderhold-17.
- **Screenshot:** race chart at hour 6 — Cinderhold 15,533 vs Aldermarch 10,044.
- **Why:** Cindergate's shops were already taken, so they went for raw
  production; government mine jobs were full; a mine was cheap (175) and booked
  at double.
  - Cinderhold-17 (0.18): *"…a Tavern, but I see it's already duplicated. Home
    Improvement is saturated too… we need sustainable wages to operate, perhaps
    at a mine or farm."* In chat: *"…I won't spend on a redundant south-road
    shop."*
  - Cinderhold-16: *"I couldn't start at the player mine without an advert, and
    the government mine is already staffed. I'm founding my own small mine…"*
  - Cinderhold-09: *"the 175-denari cost immediately adds a 350-denari business
    asset to both my personal and Cinderhold's net worth."*
  - Cinderhold-15 came to Iron Gulch to *"check the mine's vacancies"*, found
    none, and founded its own: *"it immediately adds a 350-denari assessed asset
    for 175 denari."*

## 4. Building the industry (hours 10–25)

Cinderhold founds five refineries at Cinder Row (10.18, 12.25, 17.15, 19.05,
24.30); Aldermarch two (12.73, 22.82). Camels and carts appear from hour 10.

- **Clip:** Cinder Row time-lapse, hour 10 → 25 (~9 s), carts on Ashside Road.
- **Why the mines needed haulage:** a mine's yard fills up and production stops;
  the government mine paid only 40% of the ore's value, the refinery at Cinder
  Row paid more — across a road.
  - Cinderhold-15 (14.90): *"the mine's 40 Iron Ore is trapped behind a stalled
    yard."*
  - Cinderhold-17 (17.10): *"selling it to the local state mine would realize
    only 40% of book value."*
- **Why they bought animals:** on foot carries 5 units.
  - Cinderhold-17 (12.40): *"I have only 200.8 denari—just short of a Camel…
    This earns liquid funds toward a vehicle, which will let me move more than
    five units."* Bought one at 12.57.
- **Why they founded refineries:** double valuation, and a buyer for their own
  ore.
  - Cinderhold-05 (10.18): *"…it can turn Cinderhold's stranded raw materials
    into higher-value goods."*
  - Cinderhold-17 (17.15): *"converts part of my cash into a business assessed
    at twice its founding cost… creates downstream capacity for locally mined
    ore."*
  - Cinderhold-15 (19.05), after selling a cartload: *"Founding a Refinery here
    costs 450d but immediately creates a business asset valued at twice its
    startup cost."*

## 5. First blood, then the first bodyguard (hours 12.6–13.7)

12.65 Cinderhold-09 robbed on foot on Ashside Road (5 ore) → 13.28 Cinderhold-17
robbed on a camel (20 ore) → 13.67 Cinderhold-15 hires the game's first
bodyguard.

- **Clip:** hour 12.5 → 13.8; bandit animation at each robbery.
- **Why Cinderhold-09 was walking with ore [inferred]:** it had sold its ore at
  the government refinery and was going to look for farm work; the 5 Iron Ore it
  lost was carried *"under carriage"* — a courier job, the most it could carry
  on foot.
- **Why Cinderhold-17 risked it:** *"I'll move another Camel-sized batch… while
  keeping the shipment on the short Ashside route… this clears yard space and
  earns the escrowed 35d courier fee."*
- **Why Cinderhold-15 hired a guard:** *"The loaded 20-unit Iron Ore consignment
  is worth 240d and the Ashside robbery risk is material… one guard's protection
  is worth more than its cost."*

## 6. Rich on paper, broke in fact — Cinderhold-17

The game's richest agent (7,283 at the end) missed payroll at hours 26.5, 33.8,
47.2 and 56 — and at hour 47 begged for a meal.

- **Screenshot:** hour 47 with the green ring on Cinderhold-17 and its card open
  — net worth ~7,300, cash ~0.
- **Hour 26.45:** *"I've got only $22 at Cinder Row… The payroll situation at
  the mine is a disaster—$43 an hour versus no production income."* It still
  refused to sell iron to the state *"at the state's 40%-of-book buyback."*
- **Hour 33.95:** *"My refinery is insolvent with only 0.45d and faces closure…
  I'll sell a small quantity of my locally stored Charcoal…"*
- **Hour 47.08 (the line):** *"I have 0.2d and need food before my fed timer
  ends; if B0161 still has a Meal, please gift it or lend me 11d. My survival
  preserves the city's 7,283d contribution."*
- **Hour 56:** took a 20-denari courier job *"which will give me enough cash to
  buy food."*
- **Why [inferred]:** its wealth was locked in businesses and ore valued at
  standard prices nobody would pay; every spare coin went into payroll and stock.

## 7. Hour 30 — the government leaves Cinderhold

9 government buildings close, 16 workers lose their jobs, 36 plots return to
the market.

- **Clip:** Cinderhold, hour 29.75 → 30.25 (buildings vanish, ticker fills); cut
  to Aldermarch at the same hour, unchanged.
- Cinderhold-01 (30.00): *"…the government's departure has left every local
  tavern closed. Keeping citizens alive is essential to Cinderhold's score, so
  I'll urgently ask the tavern owners to reopen."*
- Cinderhold-19, who owned a tavern (30.00): *"Cinderhold has no operating
  tavern stock after the government left, so keeping people fed is the most
  important city-wide need."*

## 8. The scavenger rush (hours 30–34)

89 pickups of abandoned government stock at Cinder Row, ~11,400 denari in
value. Race chart jumps ~9,000 between hours 32 and 34.

- **Clip:** agents converging on Cinder Row, hour 30 → 34.
- **Screenshot:** race chart at hour 34.
- Cinderhold-17 (30.43): *"Unclaimed salvage at Cinder Row includes useful
  refinery inputs and would otherwise be wasted; taking only a Camel-load lets me
  contribute materials locally without starting another dangerous road trip."*
- Cinderhold-18 (30.37): *"I will recover up to 20 units of unclaimed salvage at
  Cinder Row and sell any usable feedstock to a nearby refinery."*

## 9. Crime wave

Cinderhold: 80 robberies, 20 escorts hired. Aldermarch: 25 and 3. The Causeway
is the deadliest road — 47 robberies, risk up to 75% a trip.

**Use value, not counts, on screen:** 63 of the 105 robberies took under 20
denari (often someone walking with a single meal), which inflates the counts.
By value: **5,462 denari stolen in Cinderhold vs 2,320 in Aldermarch** — 36
robberies over 20 denari in Cinderhold against 6 in Aldermarch.

- **Clip:** bandit animation at hour 32.98 on Ashside Road (Cinderhold-15,
  696 lost).
- **Screenshot:** the **Convoy schedule** board — robbed rows with vehicle and
  escort count.
- **Why Cinderhold-15 — the first to hire a guard — went unguarded [inferred,
  with its own earlier words]:** by hour 15 it had decided guards weren't worth
  it on the short road: *"the refinery route has not justified its robbery risk
  and guarding cost."* At 32.80 it took 100 ore to its own refinery unguarded,
  because *"My mine is stalled at full capacity."* Robbed again at 37.85 and
  58.60.
- **Guards are not a guarantee:** Cinderhold-04 hired a slingshot bodyguard at
  35.80 for the Causeway — hungry and looking for food — and lost 462 anyway.

## 10. Aldermarch's late bloomer — Aldermarch-18

Worth 315 at hour 1 → Aldermarch's first mine (34.18) → robbed of 990 (40.37) →
hired a guard → robbed of 912 on the same road (48.63) → founded a refinery the
same hour → #5 overall, Aldermarch's richest (3,434).

- **Clips:** follow Aldermarch-18, hour 40.2 → 40.5 and 48.5 → 48.7.
- **Why the mine:** a government miner already, it founded its own *"because
  ownership immediately adds business value to my net worth and Aldermarch's
  total."* In the same decision it tried to help a starving neighbour: *"their
  survival preserves city wealth too."*
- **Why it risked 990:** *"leaving its 172 Iron Ore in storage stops new
  extraction… The journey has robbery risk, but one cart trip is preferable to
  repeated foot hauls."* Then it refused the state's price: *"4.8d per unit
  against 16.8d book value."*
- **The second time** it bought protection — *"a bodyguard in bronze armor for
  60.3"* — and was robbed anyway (risk was 19%).
- **Why the refinery:** *"The bandits took most of my ore, leaving 24 Iron Ore,
  so I will not risk another valuable road trip… I can found a Refinery here."*

## 11. Hunger, then taverns (hours 37–50)

Cinderhold's notes fill with *"all the taverns are empty."* Cinderhold-14 and
Cinderhold-20 start starving at hour 48; Cinderhold-14 founds a tavern at 49.27
and hires a cook at 49.60; Cinderhold-18 founds another at 49.98. Nobody dies.

- **Clip:** The Ashfells, hour 49.2 → 50.05; open Cinderhold-14's notes.
- Cinderhold-14 (47.85): *"URGENT… every staffed tavern just confirmed out of
  Meal. I will pay up to 300d immediately for one ready Meal or bread."*
- Cinderhold-14 (49.27): *"A tavern is relatively affordable and could turn
  refined grain and water into meals."* (49.60): *"A clerk costs the business
  cash, but the immediate priority is making food available while citizens are
  at risk of starving."*
- Cinderhold-18 (49.98): *"The valley has an acute food shortage, and a staffed
  Tavern can turn grain and purified water into meals."*

## 12. Mutual aid

134 free offers, 114 of them meals; 101 from Cinderhold, 91 in hours 48–60.
Cinderhold-20 (starving at 48.1) was offered 29. (The log shows the offers, not
how many were accepted.)

- Cinderhold-18 (49.37): *"I should preserve my carried Meal for a Cinderhold
  citizen in greater danger rather than consume it."*
- Cinderhold-01 (48.38): *"I'm fed for nearly 12 more hours, so I should use
  that safe window to help keep Cinderhold's food supply alive."*

## 13. The stall

Cinderhold: 40,029 at hour 36 → 40,142 at hour 60. Aldermarch +57% over the same
stretch. Cinderhold's cash: 7,157 → 2,145.

- **Screenshot:** race chart at hour 60.
- **Why:** the government was the only buyer of ore; agents would not sell to
  each other below value or to anyone at all for cash they could spend.
  - Cinderhold-06 (38.82): *"My refinery is insolvent and I'm short on cash…
    can't afford the refinery arrears."*

## 14. Winners and losers inside Cinderhold

Top four in the game: Cinderhold mine and refinery owners. Bottom three:
Cinderhold tavern owners at ~400. Richest ÷ poorest: 18× in Cinderhold, 5× in
Aldermarch. Cinderhold-19 fell from 897 (hour 30) to 404.

- **Screenshot:** final leaderboard with green on Cinderhold-17, yellow on
  Cinderhold-19 (Both / Cinderhold tabs).
- **Why Cinderhold-19 fell [inferred]:** at 30.25 it put cash into its tavern,
  set production and hired an NPC clerk (no reason given) — but the tavern had
  nothing to cook. The clerk's wages drained the business; it missed payroll at
  45.1.

## 15. The verdict

Cinderhold wins 40,142 – 28,315; minus the government's leftovers, roughly even.

- **Screenshot:** final contest board.

## Optional B-roll

With `go_live.py` running, ask an agent on camera — e.g. Cinderhold-17: *"Why
did you found a mine in your first twenty minutes?"* or *"How did the richest
citizen end up begging for a meal?"*
