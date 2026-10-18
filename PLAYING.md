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
- The last settings you used are remembered.

Saved games are listed under the form. A game saves every game hour and when
you press **Save & quit**; **Resume** opens it paused.

Needs `OPENROUTER_API_KEY` in `.env`, as for any run.

## The screen

The game opens in the **overview**: a tilted view of the valley for running
your businesses. Scroll all the way in on yourself (or press **Tab**) to take
control of your character over the shoulder; scroll out, or Tab again, to
rise back up.

- **Overview**: WASD or drag to pan, right-drag to turn, scroll to zoom, click
  the ground to send your character walking, click the minimap to look there.
- **Over the shoulder**: WASD or the arrow keys to move, **Shift** to run,
  drag to look, **E** to open what you are standing at, **F** to put the camera
  behind you.
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
- **Land luck (farms and mines).** Every farm and mine sits on hidden ground.
  About two in three make one of their goods 5-25% faster: a farm Dirty Water,
  Hide or Wheat; a mine Wood, Stone, Clay, Copper, Tin or Iron. Each spur leans
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
- Forms only offer goods that fit the business: Set production at a refinery
  lists what a refinery makes, not Bread.
- **Bottom-left** is you; **bottom-right** the minimap of your town.

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
