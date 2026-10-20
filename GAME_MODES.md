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
