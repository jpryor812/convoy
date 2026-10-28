# Game modes

Notes on how a game starts and what kind of game it is. Written 2026-10-18.

## Open world (what `play.py` runs now)

You join a town that is already a town. Each city starts with the state's
four sites: a **Tavern** in the market square, a **Farm**, a **Mine** and a
**Refinery**. They are a backstop, not a rival:

- they **sell** at a fixed high price (about 1.5x book),
- they **buy** what they use at a fixed low price (0.4x book),
- they **hire** anyone at a fixed wage.

So nobody starves on the first day, anyone can earn a wage from hour zero, and
the open question for every citizen is how to do better than the state: make
what it sells and undercut it, pay more than it does, or buy from it and add
value. There is no other government and no tax. (Turn it off on the start
screen for the old "nothing exists until someone makes it" opening.)

**You arrive in a running town.** By default the agents run both towns for
8 game hours before you arrive (`convoy/town.py`), so your first look is at a
town with owners, prices, people with experience and links nobody has filled,
not 50 people at the starting line. Each head start is kept as a template and
reused, so it costs time and money once. The agents just see one more
citizen turn up.

**Characters.** Everyone has a calling for life. You pick yours on the start
screen; each agent is dealt one at random.

| Calling | Bonus |
|---|---|
| Farmer | your farms grow 10% faster |
| Miner | your mines dig 10% faster |
| Refiner | your refineries refine 10% faster |
| Maker | your taverns, smithies, stables and stores make 10% faster |
| Hauler | you carry 10% more, on foot and in any vehicle |

The production bonuses apply to businesses you **own**, so a Miner who founds
a mine is the natural owner of one. Callings show on the People page, so you
can look for a Miner to run your mine.

**Long term:** a player joins the town they want, which puts them on that
town's server. Raiding or trading with another town means going there, and
can't mean ten towns of 50 people on one server. Hiring from other towns
(`offer_job` works across cities) and the 100-coin **town report** are the
first cross-town tools.

## Later: a timed single-player "discovery" start

Not built. Kept here so it isn't lost.

You do not start in a town. You start by choosing **land**:

1. **Pick a character** (the callings above).
2. **Scout plots.** Arrows at the top of the screen (previous / next) take
   you to random 2x2 plots in various towns. Fog of war: you see the plot
   itself and little of what is around it.
3. **Read the town, not the map.** For each plot you see facts about its town:
   population, and how many buildings of each type it has. A town with eight
   farms and no refinery is an opening; one with four taverns is not.
4. **Settle.** Choosing a plot founds you there, alone on your own land, and
   the game is about growing from that plot within a time limit.

This suits a timed single-player mode better than the shared open world,
where players should be joining a town that already exists rather than
scouting for one. It also fits the hidden land luck: you could scout a plot's
look but never its yield.

## Later: exploration missions (designer note, 2026-10-18)

Something to do when you do not want to work or run deliveries: go looking.
Needs a better map first -- places worth going that are not on the roads.

- **Cave dwellings** in the mountains: walk in, fight what lives there with
  the bat-and-block combat, and come out with rare weapons, armour or ore.
- **River diving**: dive the rivers for lost goods, rare finds and the odd
  weapon.
- Finds should be things you cannot buy -- a better sword, armour, a rich
  resource -- so exploring is a real alternative route to getting ahead, not
  just a coin bonus.

Also later, from the same request: another citizen attacking you in person
(the agents' raids still happen on the timed roads), and state convoy jobs,
escorting a convoy and defending a state refinery as repeatable missions.

## Later: the cost of spreading out (designer note, 2026-10-19)

Expansion should cost you reach. As a house spreads -- a farm here, a mine a
long way off -- two things get worse at once:

- **Longer shipping lanes are more exposed.** The farther goods travel between
  your own sites, the more road they cross and the more chances for bandits or
  raiders to take them. Distance is risk, not just time.
- **Buildings can be robbed.** A raid on a site (its yard stock, its cash) is
  possible, and it is hardest to answer when you are far away.

When one of your buildings is being robbed:

- **You are told at once**, wherever you are (a red alert, the building on the
  compass and minimap).
- **The robbery takes time**, so there is a window to answer it.
- **You can ride there and fight** with the bat-and-block combat,
- **or send mercenaries** -- hired guards who ride out and fight for you,
  arriving after a travel time that depends on distance.
- Guard posts and catapults at the site defend it on their own while you
  answer; a site near your others is easier to cover.

That makes the choice real: compact and safe, or sprawling and rich but
stretched thin. It pairs with the planned map rings (safe valley, contested
frontier, lawless wilderness) and needs offline protection rules for online
play.

## The game: five pillars (design, 2026-10-28)

What the game is about, and what everything else serves. Five pillars, each
of which costs you something in another -- that cost is where the strategy
is:

> **Explore** -> find land and people -> **trade** -> money -> **develop** ->
> wealth draws trouble -> **combat** -> safety in numbers -> **towns and
> dynasties** -> towns compete for land, routes and the river -> push out and
> explore again.

Combat is on hold for now. The others are below, with what exists, what
makes each worth playing, and what to build.

### The map: rings, levels and eras

- **Rings.** The world is a set of rings around a centre, like a diagram of
  the solar system. Everyone starts in the innermost ring. Each ring out has
  richer ground (more and better deposits) and a level cap: the inner ring
  is for houses up to **level 10**, the next up to **level 20**, and so on.
  New players are never next to houses far beyond them.
- **What the cap governs.** Recommended: where you can **claim new land and
  build** (and, later, fight) -- **not what you own or where you trade.** A
  house that outgrows the inner ring keeps its outpost there, run by family
  and hired hands, and can still visit and trade there. Nothing is
  abandoned, and towns in the inner ring keep their members as they level.
  A house may also choose to **hold its level** and stay.
- **Levels.** A house levels up from all the pillars: land found, people
  found, trade with others, buildings and their upgrades, know-how.
- **Eras.** Each ring is an era: ancient, antiquity, medieval, renaissance,
  industrial, modern. Levelling up and know-how unlock the next era's
  vehicles, weapons, armour and clothing. To keep a high-era house from
  being overpowered in a low ring (once combat returns), gear above a ring's
  era could be scaled down to its ceiling there. TBD.
- **Region servers** (see "Scale") map onto the rings: a ring, or a sector
  of one, per server.

### Towns across the eras (designer note, 2026-10-28)

A town keeps its identity as its people level up, without higher houses
living among lower ones.

- **One town, a branch in each era.** Pittsburgh is founded in the ancient
  ring. When enough of its houses (say three) pass the ring's cap, they found
  **Medieval Pittsburgh** in the next ring: the same name and flag, a new
  place. Ancient Pittsburgh, Antiquity Pittsburgh, Medieval Pittsburgh ...
- **Allegiance is to the whole town.** You live and build in your era's
  branch, but keep the flag, the town chat and your membership everywhere.
- **Old buildings stay yours**, as estates run by family or hired hands.
- **Between eras, only peaceful contact**: trade, chat, groups, marriages,
  visits. Claiming land and (later) fighting happen only inside your own
  ring, so everyone you can contest is within ten levels of you.
- **Guard the early game.** Veterans must not be able to pour wealth into a
  lower branch: limit what goes down an era (only that era's goods, or a cap
  on gifts).
- **Room for everyone.** Rings grow outward, or gain sectors, as players
  arrive, so land always fits every player even as veterans keep theirs.

### Taking land: no conquest for now (designer note, 2026-10-28)

Land changes hands only by **sale**, or when abandoned land returns to the
wild. Rivalry between towns is over unclaimed rich land, trade routes, tolls
and the river -- not over each other's ground. Big towns must not be able to
force small ones out. If conquest comes later, the known guards are: wars
only between towns of similar size, protection under a certain size, truce
periods after a war, and conquest only in the lawless outer rings.

### Exploration

- **In the game:** the haze, finding people, hidden land luck, ground hints,
  claims anywhere, the minimap cloud.
- **The view.** The over-the-shoulder view (Red Dead) is the default, with
  the minimap; the minimap opens into a **full map** of the land you have
  discovered, which keeps everything you have found pinned on it: outposts,
  towns, taverns, trading posts, people's land.
- **Deposits.** Some land carries a deposit bonus, unknown at first.
  Know-how (the **survey** line) makes it more predictable where mineral- or
  farm-rich land lies: first a hint by area, later a reading of the spot.
- **No maps or reports for sale.** What is out there is found by playing;
  town reports go.
- **The trade-off** is time: while you explore you are not producing or
  hauling. That is enough -- exploring is how you meet people and build a
  trading network.

### Trading

- **In the game:** listings, buy orders, bids, delivery runs, couriers, the
  state's convoy as a floor, only trading with people you have found.
- **Markets are discovered.** You see prices and listings only at markets you
  have found (trading posts beyond your own ring, and towns). Each new market
  widens where you can sell.
- **Prices differ by place.** Regions lean toward farming or mining (land
  luck already does), so markets have different prices, and a market's
  state floor follows its own local prices. Carrying goods to where they are
  scarce is the trade.

### Development

- **Foundations you build onto**: floors, roofs, extensions, each raising
  output or storage (see "Building").
- **Flags, banners and colours** (see "Making it yours").
- **The town ladder** (see "Why people gather").
- **Specialising**, so a mining house and a farming house play differently:
  deeper bonuses and buildings for the line a house invests in, so focus
  pays more than spreading thin.

### Meeting people (one of the first things to build)

Finding someone (being within sight) only shows you they exist. Then:

- **Say hi.** Click a settler you have found to open a panel of set actions,
  like Civilization's diplomacy screen.
- **Share, by request.** Each is asked for and accepted or declined, and can
  be offered in return: **your level**, **what you own**, **where your land
  and buildings are** (pinned on their map), **what you are buying or
  selling now**, and **your children** (for a match).
- **Share contact.** Unlocks private messages and invitations to group
  chats.
- Agents answer and make these requests too, so the early game is meeting
  and building relationships before trading, like early Civilization.

### Towns and dynasties

- **A town is geographic, a dynasty (clan) is political.** You belong to the
  town where your land is; your clan and marriages span towns.
- **Tolls.** From 100 members a town may charge non-members to enter its
  land, at a rate it sets -- a tariff. (Add to the ladder.)
- The rest as in "Why people gather" and "Why towns do not grow forever".

### Open questions

- What exactly earns a level, and how fast.
- Whether a higher-era item works, is weakened or is barred in a lower ring.
- How the inner ring keeps room for newcomers as veterans' land fills it
  (rings that grow, or gain sectors, as players arrive).
- Whether towns can ever conquer land, and on what terms (see "Taking land").
- The look across eras: the current models are a western frontier.

### Order to build

1. **Meeting people** (say hi, share, contact) and the **full map** with pins;
   over-the-shoulder view as default.
2. **Discovered markets and local prices.**
3. **Towns** (founding, square, ladder, tolls) and **specialising**.
4. **Foundations and flags** (needs the Meshy rework).
5. **Rings, levels, survey know-how**, then **eras**.
6. **Combat** returns: robbing buildings, danger by ring.

## Next: outposts and towns (design, 2026-10-27)

The game we are building towards. It replaces the open world above: there
are no starting towns. Everyone starts at an outpost of their own on open
land, and towns form where people choose to gather.

### Starting out

- **An outpost on open land.** You start with your house -- you, your partner,
  a son and a daughter -- a donkey, a bat and 300, on a claim of your own
  joined to the roads by a dirt road.
- **Choosing where.** You pick your plot on the map yourself (no random
  placement for now). **The first home is free** (2026-10-28), and the map is
  **hazy**: you see the trading posts but not who has settled where, so where
  you land among people is partly chance. **You can only trade with people
  you have found**, by coming within sight (about 400 m) of them or their
  land -- so the early game is exploring for neighbours and buyers. Agents
  play by the same rule. **First homes stand at least 650 m apart** on a
  bigger map (the mountains pushed out to about 1.3 km beyond the trading
  posts' land): far enough that you see others only as smoke on the
  horizon, not clear as day beside you. Later land is priced
  by how much is built near it: cheap far out, dear beside other people. To
  start somewhere dear you can take on **debt** from the state.
- **Settling near friends.** Players who know each other can settle side by
  side: pick a friend and the map shows the open land around their outpost.
  Two friends starting together should be able to arrange it.
- **Agents settle outposts too**, by the same rules, for now. The end game has
  no agents; they fill a world until people do.

### Anchors: the state's trading posts

The map is seeded with the state's trading posts, at a ford or a crossroads.
Each has the **starter tavern**, and is where the government's convoys run
from. Nobody owns them. The state also **hires** there, at a low fixed wage,
so anyone short of coin can earn while their outpost gets going. Eventually
there is about one per region (around ten);
we start with **three, fairly close together**, to see whether three towns
form.

- **Food comes from taverns only.** You walk to a tavern and buy a meal, or
  order one brought to your outpost. There is no cooking at home unless you
  build a tavern of your own. This is what draws the first settlers to the
  anchors, and what a later town needs a player's tavern for.
- **Selling to the state.** From any building of yours you can order a
  **government convoy** to come and collect goods. It pays **50% of the
  average price that good sold for between players** over the last game day
  (50% of book when it has not traded), and charges no fee: they come to you.
  It is a floor, never the best price.
- **First sales work as now**: delivery runs to buyers who pay more at their
  door.

### Building

Structures sit on the grid as **foundations you add to**, not freeform
building and not finished products. Components stack on a foundation -- a
new floor, a roof, an extension -- and each raises its storage or its output.
The Meshy buildings need redoing for this: a base that reads as unfinished,
and parts that fit on top of it.

### Making it yours

- A **flag and banner** you design, and a **colour scheme** for your
  buildings.
- You fly your **family flag**, and your **town's flag** once you join one.
- Your **border** is your family's colour; once you are in a town it is a
  gradient from your family's colour to the town's.

### Why people gather

Being near people pays, and joining a town pays more. Both are needed, or
nobody joins.

| Anyone nearby gets | Only members get |
|---|---|
| A tavern in reach, short meal deliveries | The market square and its shared yard |
| Shared roads, cheaper road links | Members' road upgrades, police, the bank |
| Workers who can reach your shifts | Town chat, flag, vote, gradient border, rankings |
| Easier trade with neighbours (and dearer land) | The know-how boost |

**Founding a town.** Three or more households with outposts within about
500 m of a tavern can found one by charter. The founder names it. Population
counts **everyone living in member households**, partners and children
included, so a starting house is 4 people and families grow towns. (No limit
on children for now.)

**The ladder.**

| Population | Unlocks |
|---|---|
| 12+ (3 houses) near a tavern | Found the town: name, flag, chat |
| **50** | **Market square**: trades between members in the shared yard are quicker, safer and cheaper -- no haul |
| **75** | **Road upgrades**, paid for by members: faster travel |
| **100** | **Police**: warns the town when bandits come and does some simple defence -- weaker than people fighting, better with higher town taxes |
| **200** | **Bank**: a player can open one; loans backed by the town fund, whose earnings pay for police and roads |

**Know-how boost.** Every member's own know-how is studied faster: +1% at 20
people, and each further 1% takes 1.5 times as many more people as the last.

| People | 20 | 50 | 95 | 162 | 264 | 416 | 643 | 985 |
|---|---|---|---|---|---|---|---|---|
| Faster study | +1% | +2% | +3% | +4% | +5% | +6% | +7% | +8% |

**Town taxes.** A town sets its own taxes and only its members pay them; they
fund the police, the roads and the bank's fund. The *state* still taxes
nobody.

**Organising around pollution.** A town can pay for chimneys, tailings dams
and the like together, and make pacts with the towns downstream (see "the
river rises").

### Why towns do not grow forever

No hard cap. The rewards stop at 200 people; the costs keep climbing:

- **Smoke.** A dense town fouls its own air and slows its own work.
- **Land.** Prices rise as a town grows, so a newcomer gets a better deal in a
  small one.
- **Reach.** The market square serves a radius. Members on the far edge of a
  sprawling town lose its no-haul trades; past that, a second square is in
  effect a second town.
- **Crowded markets.** Twelve farms in one town push Wheat down; a small town
  with no refinery pays well for one. The map shows what each town lacks.
- **Upkeep.** Police and roads cost more per head as a town grows, so taxes
  rise.
- **Bandits follow money.** Raids on a town grow with its wealth.
- **Being a big fish.** Titles and leadership are easier to win in a small
  town, and towns rank per head, not by total wealth.
- **Alliances, not mergers.** Towns can ally -- cheaper trade between them,
  roads paid for together, river pacts -- so cooperating does not mean
  becoming one town.

An entry fee is up to each town, but towns want members, so it is not the
brake.

### Scale (when there are players)

- A **world** is one map, one clock and one market: who you can trade with,
  fight and ally with. About 10,000 members, 1,000-2,000 online.
- It is split into **regions**, one server each, up to about 1,000 online.
  Borders follow rivers and ridges; crossing a bridge, a ford or a pass hands
  you to the next server during the crossing. The market, messages, clans and
  rankings stay world-wide, and your outposts keep working while you are away.
- A town sits inside one region (anchors mid-region); a bridge belongs to one
  side; nobody builds on a border. Towns and alliances live inside a world;
  only social things (profiles, clan chat) span worlds.
- Not built: one server holds the first world. The code should stop keying
  everything by city and keep the market separate from where people stand.

### Later

- **Robbing buildings**, once combat is settled (see "the cost of spreading
  out").

## Later: the river rises (designer note, 2026-10-27)

Farms on the riverbed grow more, but the river can flood them, and the
people upstream are why.

Mines and refineries put silt and tailings into the river. It builds up over
time and flows **downstream**: the riverbed rises, and floods get worse for
farms below. (This happened in 1850s-80s California: hydraulic mining raised
the rivers and flooded the valley farms until the courts stopped it.) It is
the slow, shared counterpart to smoke, which is local and clears in hours.

- **Downstream, not global.** The damage traces back to who is upstream, so
  there is someone to blame and something to do: a deal, compensation, a raid
  on the polluter, or buying the land upstream yourself.
- **Seen coming.** A river gauge and a flood season; risk rises in steps you
  can watch, never a sudden wipe-out with no warning.
- **Fixes in the setting.** Tailings dams and settling ponds on mines, levees
  and terracing on farms, replanting upstream -- as know-how and Projects.
- **Still worth the risk.** Riverbed farms keep their bonus. Flood insurance
  and levee building are openings for other players to sell.
- **For the agents:** do they cut their silt together, or all free-ride? A
  showcase question.

Build the outposts first: flooding matters once players choose where to
settle -- riverbed or high ground, above or below the miners.
