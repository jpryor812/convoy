# Playing Convoy

You are one citizen of the valley. Every other citizen is an AI agent, and
none of them know you are not one of them.

## Start

```bash
python3 play.py
```

Then open http://localhost:8800. The start screen sets up a game:

- **Cities and agents**: tick one to three cities and set how many citizens
  each starts with (1 to 60). Pick the city you live in; your seat is one of
  that city's count, placed at random and named like everyone else.
- **Game speed**: how many game minutes pass per real minute. "Normal" is a
  game hour every five real minutes, so a game day takes two hours. You can
  change it, or pause, at any time during play.
- **Spending cap**: the game pauses itself when the agents' API calls reach it.
  Raise it from the start screen settings for the next game.
- **Head start** (default 8 game hours): the agents run both towns without
  you first, then you arrive as one more citizen -- named like the rest, the
  next in line -- with 300, into a town that already has owners, prices, jobs
  and gaps. A welcome note says what you walked into. The first time, the
  start screen shows the towns' clock while they run (it goes as fast as the
  AI answers: about 1.5 real minutes a game hour measured with 6 agents; more
  agents take longer) and roughly what it costs. The finished towns are kept
  in `runs/towns/`, and a later game with the same towns, model and head
  start begins from a copy instantly and free ("reuse towns that already
  ran"). With a head start the city counts are the agents; you are extra.
- **Your character**: a bonus for life -- Farmer, Miner, Refiner or Maker
  (your own businesses of that kind work 10% faster) or Hauler (you carry 10%
  more). Every agent is dealt one at random.
- **The state's four**: on by default, each town opens with the state's
  Tavern, Farm, Mine and Refinery. They are always open, sell what they make
  without limit at a high fixed price, buy at a low one, and hire anyone at a
  fixed wage -- somewhere to eat and earn from hour zero. No other
  government, no tax. See `GAME_MODES.md`.
- **Outposts** (on by default, 2026-10-27): no towns at the start. Every
  agent settles an outpost on open land around the ticked cities' markets,
  which are now the state's **trading posts** (its Tavern, Farm, Mine and
  Refinery: they feed, hire at a fixed wage and buy). The game opens on
  **Choose your land**: move your home over open grass and click. **Your
  first home is free.** The frontier is **hazy**: you see the state's
  trading posts, but not who has settled out there. The banner lets you
  **borrow** up to 400 from the state as you settle, to start a business
  with (2% a game day; a fifth of what your businesses earn pays it down).
  The clock waits until you settle. See "Outposts" below and GAME_MODES.md.
- The last settings you used are remembered.

Saved games are listed under the form. A game saves every game hour and when
you press **Save & quit**; **Resume** opens it paused.

Needs `OPENROUTER_API_KEY` in `.env`, as for any run.

## The screen

The game opens in the **overview**: a tilted view of the valley for running
your businesses. Scroll all the way in on yourself (or press **Tab**) to take
control of your character over the shoulder; scroll out, or Tab again, to
rise back up.

- **Keys**: **WASD** moves, the **arrow keys** turn and tilt the camera
  (or hold **Ctrl**/**Cmd** and move the mouse), **Shift** runs, **E** opens
  what you are standing at, **C** puts the camera behind you. **R** swings your
  weapon and holding **F** blocks.
- **Overview**: WASD or drag to pan, arrows or right-drag to turn, scroll to
  zoom, click the ground to send your character walking, click the minimap to
  look there.
- **Fighting.** Everyone starts with a **Bat**. Bandits come at you at the
  bounty mission's camp (walk up to the tents) and, now and then, on the open
  road when you are carrying goods -- never in your first day. They close in,
  wind up (a red **!** over the head) and swing: hold **F** facing them to
  stop most of the blow, and press **R** to hit back. On the road you can also
  run for it. Knocked down, you lose a share of what you carry (at a camp, you
  are just beaten back). Health comes back slowly while you are fed; a better
  weapon and armour from an armory make fights easier.
- **Eating.** Food is sold at **taverns** only. Tap the **Fed** pill at the top, your **portrait** (bottom left) or the card's **Eat**
  button: it shows your health and food and lets you eat a meal you carry, or
  buy one at a tavern where you stand. With nothing to eat it points you to the
  nearest tavern. A meal never shortens how long you are fed.
- **Errands point, you ride.** Fetching an order yourself, or buying goods in
  person at a shop, no longer walks you there: the compass across the top
  points the way and the purchase or pickup happens as you walk in. Walking out
  of the place you work in ends your shift.
- **Why is someone rich?** Tap any name on the leaderboard (or Rankings) to see
  what their net worth is made of: coin, each business with its profit and
  stock, goods, carts and land.
- **Building**: the **Build** menu down the left edge lists every business
  with its cost (greyed if you cannot afford it, with a count of how many you
  own). Pick one and a hologram of it follows your cursor on the 2x2 block of
  squares it would take: cyan where it can go, red where it cannot, with the
  reason. Click to build there; Esc or right-click cancels. The square under
  your cursor always glows, so you can see what a click will hit.
- **The land is a grid.** Every place is a block of squares, one per plot.
  Click free squares to pick them (up to four, in one place): four in a 2x2
  block can take a business, any number can be bought as land. The bar that
  appears offers what fits there; if you are elsewhere, your character walks
  over and builds. Owned squares are tinted in their owner's colour; each
  place's name shows how many plots it has left.
- **Open land anywhere.** Point the building hologram at open grass -- any
  2x2 that is not river, mountainside, road or part of a place -- and it turns
  into a claim: the tag shows the dirt road it needs to the nearest road (up to
  1,200 m) and what that costs (0.12 a metre). Click and the road is laid, the
  four squares become a place of their own ("Kestrel Fields"), and your
  character rides out and builds. Any business can go on a claim; the "Land
  claim" stake buys the four plots bare. Travel there takes as long as the
  road is long.
- **Your territory.** Your home, businesses and land each carry a one-square
  ring around them, outlined in gold. Rings that touch merge into one border;
  a patch that does not reach your home's is marked **Outpost** -- far land,
  harder to watch.
- **Geography (2026-10-18).** Mountains ring the settled land. Rich ground
  comes in pockets -- areas of the map about 260 m across, so neighbouring
  farms or mines in one area share its luck (each varies a little) --
  and it follows the land: farms near water strike rich soil more often,
  mines near the mountains rich seams. The building hologram says what the
  ground promises before you build. Refineries have no land luck: put them near
  your farms, mines or town.
- **The ground wears out; the air fouls.** A mine's seam runs down as it is
  dug -- a lone hand works one out in about three game days -- and never comes
  back: output holds until half is gone, then fades, then stops. A farm's soil
  tires as it is farmed (down to about a third of full pace) and recovers while
  the field rests. Everything that makes things gives off smoke, refineries most
  and anything run fast more; within about 600 m it slows crops most, then
  miners and refinery hands, and it thins over hours. Your business card shows
  "Soil 64% left" and "Air 20% foul". Upgrades push back: Crop rotation, Manure
  pits and Hedgerows on a farm; Timbered shafts and a Deeper shaft (fresh ore,
  even for a worked-out mine) on a mine; a Tall chimney on a refinery or mine.
  Worn-out ground is why you claim more land.
- **The minimap is cloud until you have been near.** The world in front of
  you is always drawn; the map remembers where you have ridden.
- **Land luck (farms and mines).** Every farm and mine sits on hidden ground.
  About two in three make one of their goods 5-25% faster: a farm Dirty Water,
  Hide or Wheat; a mine Wood, Stone, Clay, Copper, Tin or Iron. Each area leans
  toward certain goods, so where you found matters, but nothing shows until the
  first harvest. Then you are told, the sign and the holdings card say "+18%
  Copper Ore", and the land shows it: extra wells, more cows, a second wheat
  field, heaps of ore in the metal's colour -- more for a richer find. The
  agents roll the same way and see their own once revealed.
- **Your businesses show their state**: a timer over each working building,
  "+1 Wheat" as units land, stock piling up in the yard, crops growing and
  being harvested, smoke while fires are lit, and a "!" over any of yours that
  needs you. The **holdings bar** along the bottom has a card per business;
  click one to fly there.
- **Owners' colours**: every owner flies a banner in their colour and their
  plots are tinted with it. Shops show their price on their sign. When a rival
  opens against you or undercuts you, the map points at them.
- **Titles**: whoever made the most of a key good in their city over the last
  half day holds its title ("Grain Baron of Aldermarch"), shown with a crown on
  the leaderboard. You are told when you win or lose one.
- **Click a building** to open it: what it sells and for how much (buy food,
  weapons, vehicles), sell to it, order deliveries, apply for its jobs -- or,
  if it is yours, manage it. You trade in person, so you have to be standing
  at its place; the menu offers to walk you there or fast travel.
- **Click a person** to message them, pay them or offer them a job.
- **Click an unsold plot** (the pale outlines on the grass) to buy land or
  found a business there.
- **Top bar**: cash, net worth, rank, food, how your city stands, the clock,
  game speed, pause, the 2D **MAP**, and **MENU** (every action by name, the
  rules, saving).
- **Right-hand buttons**: where you stand, travel, your businesses and land,
  jobs, market, chat, news, rankings.
- **Market** (scales button) is where all buying and selling happens; you
  never need to open a business to trade.
  - **Buy** lists everything for sale, grouped by good, cheapest first, with
    each seller, where they are, and a button that says what happens and what
    it costs ("Buy & fetch · 15"). **Feedstock** (Wheat, ore, hides) is paid
    for now and waits at the seller's: your character walks there, it loads,
    and you carry it home (on foot you carry 5, so a bigger order is more
    trips, each claimed for you) -- or **pay a courier**. **Shop goods**
    (Meals, tools, weapons) are bought at the counter: the button walks you
    there and buys on arrival. Your business's cash pays first and your pocket
    covers the rest, so you never have to deposit before buying.
  - **Buy orders**: "Post a buy order" names a good one of your businesses
    uses, how many, the price each and an optional courier fee. The money is
    held so sellers know they will be paid; anyone holding it -- agents
    included -- can fill it, all or part. Filled goods wait at the seller's
    for you to fetch (or the courier). Cancel any time; what is left comes
    back to your pocket.
  - **Sell**: *Buyers waiting* lists everyone's buy orders with a **Sell**
    button where you hold the good -- paid at once. *What you have to sell*
    lists your businesses' stock with a price box: **Put on sale** and anyone
    can buy it (you cannot go below 60% of book). Goods you carry can be put
    on sale at a business of yours you are standing at.
  - **Deliveries**: what you ordered and what you are carrying, with the next
    step as a button.
  - **Prices**: what each good sold for today, how many, and the cheapest
    rival.
  - **Alerts**: when a good one of your businesses uses (or one you have a
    buy order out for) comes up for sale or drops in price, when someone wants
    something you hold, and when your buy order is filled. Click the alert to
    go straight to it in the Market.
- **People** (two-person button): everyone in your town -- their character,
  what they own, where they work and their experience in each kind of work
  (Novice to Master, with hours). Wages are private: **Message** opens a
  private thread, like a phone's messages, to talk terms, and **Offer a job**
  pitches a wage at one of your businesses. Other towns are closed until you
  buy a **report** (100): their people as of that hour, which you can then
  recruit from -- a job offer works across towns.
- Forms only offer goods that fit the business: Set production at a refinery
  lists what a refinery makes, not Bread.
- **Bottom-left** is you; **bottom-right** the minimap of your town.

### Your house, know-how and projects

- **A town of your own** (start screen, on by default): you start alone in a
  new town, with the state's four sites and your home in the square, beside the
  agents' towns. Your home's border is marked in gold around it. The agents'
  towns are your first customers: in Market, Sell, "Who would buy" lists every
  business bidding for what you hold or make, best price first -- the state's
  refinery at its fixed low price, citizens' refineries at what their output can
  pay -- and Sell takes the bid.
- **Your house** (house button): you choose to be a man or a woman, and your
  partner's. You start with your partner, a son and a daughter. Grown members
  work any business of yours, unpaid and always on shift. The son and daughter
  come of age in 1.5 and 2 game days; every married couple (you and your
  partner too) has a child each game month, and a newborn takes a month to be
  old enough to work -- a day sooner for every Meal you feed it. Marry your
  children into other houses for allies (theirs joins you, your houses ally);
  founding a clan needs at least one ally. Hired NPC hands are back, at 60%
  of a person's pace. Your family walk the map with their name and what they
  are doing over their heads. A grown member is your heir if you die.
- **Delivery runs**: everyone starts with a donkey (carries 10, three times a
  walk). Market, Sell, "Deliver it yourself" lists buyers who pay more at their
  door than the gate does -- citizens' refineries at their bid plus a fifth,
  the state's sites at full book price in another town. Take a job and the
  camera drops behind you; the goods load at your business. The buyer is only
  hinted at: a yellow circle on the minimap and a compass across the top. Ride
  into the circle and the building lights up; walk in to hand over and be
  paid. What you carry can be raided on the road.
- **The state as price floor and ceiling**: any state site buys ANY good at
  0.4x book (Market, Sell, "Who would buy" always lists it), and the state's
  Tavern in each market square sells Meals, weapons, armour and tools at its
  high fixed price. Citizens, buy orders and delivery runs always pay better.
- **Missions** (scroll button): three goals, one unlocking the next.
  *Deliver your first harvest* is an achievement: once you own a farm or mine,
  carry your own goods to a refinery on a delivery job and it pays +60 by
  itself. *Clear the bandit camp* you start when ready (+80; your odds show,
  and better weapons and armour raise them; lose and you are hurt, not
  killed); the compass points to the camp. *Deliver to a citizen* is another
  achievement (+50). Coming later: the state's own convoy jobs, escorting
  convoys and defending a state refinery against bandits.
- **The Market button** shows a red count when something new is posted.
- **Defenses**: a Guard post (500) or a Catapult (250) takes one square and
  weakens raiders on the roads at its place -- to half, or three quarters.
- **The guide** ("?" in the top bar) walks you through the first steps; it
  opens by itself the first time you play a game.
- **Know-how** (light-bulb button): your own tech tree, studied one at a time.
  Tier one takes 6 game hours (Irrigation, Iron picks, Bellows, Brick hearths,
  Pack saddles), tier two 12 (Masonry, Ledgers, Kinship, River barges), tier
  three a day (Canal locks, Guild charter), and Steam two days. Each says what
  it would be worth to you now.
- **Projects** (Build, in your business's panel): a Storehouse or Better tools,
  paid for up front, then built hour by hour. One more person on shift or a
  stack of Lumber in the yard brings the finish closer -- the panel shows how
  much.
- **Coming up** (left, under Next move): every countdown you have running,
  soonest first.
- **Clans** (People page): found one, public or secret, and invite anyone, in
  any town. Outsiders never see who is in a secret clan.
- **The town is patrolled**: nobody can lie in wait on a road into a market
  square, and a newcomer cannot be raided for their first game day.
- **River barges**: with the River barges know-how, a River Barge (built at a
  citizen's Vehicle Dealer) carries 150 units between the towns' market quays
  in half the road's time, and raiders cannot reach it on the water.

### Outposts (2026-10-27)

- **Finding people** (2026-10-28): you can only trade with settlers you
  have found -- no selling to their bids, buying their stock, filling their
  orders or taking their deliveries. You find someone by coming within about
  400 m of them or of their land (they find you too), or by meeting face to
  face. Until then they, their homes and their businesses are hidden, and
  ground you have not explored stays hazy. The state's trading posts are
  always known. Agents play by the same rule.
- **Meeting people** (2026-10-28): finding someone only shows you they
  exist. Open them (People, or click them) to **say hi**, then **share** or
  **ask for** each of: standing (net worth and rank), holdings, locations
  (pinned on your map), trade (what they sell and buy), family, and
  **contact** -- which lets you message them and add them to group chats.
  Requests to you wait on the People page. Public chat is heard only by
  people near you; the leaderboard shows only those who shared standing.
- **The view and the map**: the game opens over your character's shoulder
  once you have settled (Tab for the overview). **M**, the minimap or MAP
  opens the full map of what you have discovered: drag, zoom, and click a
  spot to set a waypoint the compass points to, or to drop a pin (saved
  with the game).
- **Your outpost** is the claim your home stands on. Later claims cost land
  (priced by what is built near it) and road. A business needs four
  plots of its own: place one on open land and you claim the land as you
  build (land price + road + the business). Nobody else can build on your
  claim.
- **Food** comes from taverns only. Walk in and eat, or tap Food and **Have
  it brought**: the meal's price plus about 2 a kilometre, arriving in what
  you carry. Agents order theirs when they get hungry.
- **Selling to the state**: Market, Sell, the state's row calls **the state's
  convoy**. It pays half what the good sold for between players over the last
  game day (half of book if nobody traded it), comes to your yard for free,
  and pays when it collects. Citizens and delivery runs pay better.
- **Agents** see the open land near them with its price and what the ground
  is good for, and can claim it (`claim_land`), order meals (`order_meal`)
  and repay what they owe (`repay_debt`).
- `python3 play.py --offline` runs a game whose agents never think: no model
  calls and nothing spent, for trying the start out.

### Knowing what to do

- **Next move** (top left) suggests one to three things to do now, worked out
  from your situation -- hungry, a stalled business, an offer waiting, a link
  your city is missing -- each with the button that does it.
- **First day** (under it) is a seven-step checklist that teaches the game:
  eat, grow your worth, found a business, put it to work, make a sale, hire,
  turn a profit.
- **Icons over buildings** say what you could do there now: a pot for Meals,
  a coin where they would buy what you carry, a cart where goods are on sale,
  "!" where they are hiring, a hammer at your job. Your own buildings carry a
  green, yellow or red flag (profitable, idle, losing money) and their profit
  per hour.
- Walk up to a building or a person and press **E**.
- Where you are walking to is marked with a column of light and a line on the
  ground, and an X on the minimap.
- **Guide** (book button): the three production chains and every business,
  what it makes from what, what that sells for, and how many your city has.

### Knowing how you are doing

- The top bar shows what moved in the last game hour: cash, worth per hour,
  and your rank going up or down.
- **Ledger** (chart button): your net worth over time against the average and
  the richest, your rank over time, every measure against the average, best
  and worst citizen, each business's takings, supplies, wages, profit and
  return on what it cost, and your share of your city.
- At the end of each game day a **report** opens: your worth and rank and how
  they moved, your best and weakest business, and one good your city traded
  but nobody in it makes.

A town is about a two-minute walk end to end. **Fast travel** (Travel menu)
takes the simulation's timed road -- the screen waits while the clock runs --
and is how you get to another city quickly. Riding a vehicle you own moves
you at its speed.

Routine moves happen on their own, as they do for the agents: you eat when
hungry if a stocked tavern is where you stand, and a shift with nothing new
happening starts again.

**Agents restock on their own.** Every game hour, an agent's business that is
short of an input buys it from whoever has it on sale -- cheapest first,
enough for about four hours -- as long as the inputs cost no more than 85% of
what the output sells for. So pricing a good a business needs is how you sell
it to them: a tavern buys Grain and Purified Water (never Dirty Water: a Meal
is 2 Grain and 1 Purified Water, made from refined goods only). Your own
businesses do not restock automatically; you do your own buying.

The 2D map, with the boards and the trade ledger, is still at `/map`.

The 3D page loads three.js and its fonts from public CDNs, so it needs an
internet connection. The models are in `art/generated/3d/`, shrunk from the
Meshy exports in `art/Meshy/` (about 1 MB each instead of 20).

## What it costs

Measured on 2026-10-17: 30 agents for 24 game hours cost $1.18. That is about
$0.0016 per agent per game hour, so 49 agents is roughly $0.08 a game hour,
$1.90 a game day. The start screen shows the estimate for your settings.

## Do I need a server or a database?

**Not to play yourself.** Everything runs on this machine and a game is three
files in `runs/games/<id>/`: the event log, the latest checkpoint and
`game.json`. Nothing needs Firebase or Supabase.

**You need a server when someone else plays, or when you want to play from
another device.** At that point:

- **One rented machine** (a small VM is plenty: the work is waiting on the
  model API, not computing) runs the game server around the clock, with HTTPS
  in front. `play.py` binds to localhost on purpose; putting it on the internet
  needs the next item first.
- **Accounts** -- who is which player. This is where Supabase fits: its auth
  gives sign-in for free, and a small table maps each player to their game and
  seat. The world itself stays in files (or object storage); a database row per
  tick would be slow and pointless.
- **Several humans in one world** needs each request tied to a signed-in
  player rather than to the single page token used now.
