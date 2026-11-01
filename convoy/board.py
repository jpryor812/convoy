"""The market board at each trading post (designer request, 2026-10-31).

"The players aren't really buying or selling goods very much. I think the
market system should be a little more robust ... showing previous deals and
posts about what people are buying and selling." In the 2026-10-30 run 297 of
310 sales were to the state; 13 were between settlers, because you can only
trade with people you have found and homes stand far apart.

So each trading post (a city's market) keeps a BOARD, open to everyone -- the
trading posts are known to all, and so is what is pinned up there:

  * A FOR SALE post holds the goods: they are taken from what you carry or
    from your businesses' yards when you post (the post's porters fetch them).
  * A WANTED post holds the money, so whoever fills it is sure to be paid.
  * Anyone may take either, all or part, without having found the poster.
  * The post keeps FEE of every deal; the goods go by its porters to the
    buyer's business that uses them (or one with room, or the buyer's pack),
    taking time by distance -- twice as long to land with no road.
  * Posts expire after a game day; what is left goes back to its owner.

Settlers other than the player also trade here BY RULE, once a game hour
(`ai_tick`): spare goods are posted a little above the going price, a
business short of inputs buys the cheapest fair offer or posts a wanted, and
anyone holding something wanted at a fair price sells into it. The models can
trade here too, with the board_* tools.

Deals are recorded like any other sale, so they set the going price -- and
with it what the state pays (half the average between players).
"""

from __future__ import annotations

import math
import random
from typing import TYPE_CHECKING, Any

from . import data as D
from . import economy as E
from . import world_map as M
from .events import Significance

if TYPE_CHECKING:
    from .events import EventLog
    from .state import Agent, Business, World

FEE = 0.02                     # the post keeps this share of every deal
POST_HOURS = 24.0              # a post stays up this long
MAX_POSTS = 12                 # open posts per settler
MAX_QTY = 500
PORTER_MPS = 2.0               # the post's porters, on the road
MIN_DELIVERY_H = 0.25
PRICE_WINDOW_H = 24.0
# The rules settlers trade by (`ai_tick`).
SURPLUS_MIN = 10               # spare units before a settler bothers to post
POST_SHARE = 0.7               # of the spare, posted at once
ASK_OVER_GOING = 1.05          # asks a little over the going price ...
ASK_OVER_STATE = 1.5           # ... and well over what the state pays
BUY_UNDER_GOING = 1.25         # pays up to this over the going price
WANT_AT_GOING = 0.95           # posts a wanted a little under it
SELL_INTO_AT = 0.85            # fills a wanted at no less than this of going
STOCK_UNITS = 8                # a business wants inputs for this many units
RULE_ACTIONS = 3               # deals a settler makes by rule in an hour
CASH_RESERVE = 30.0


# ---------------------------------------------------------------------------
# Where, and what things are going for
# ---------------------------------------------------------------------------

def trading_posts(world: "World") -> list[str]:
    return [M.market_of(c) for c in world.cities]


def _xy(world: "World", place: str) -> tuple[float, float] | None:
    from . import claims as CL
    return CL.place_xy(world, place)


def nearest_post(world: "World", agent: "Agent") -> str:
    at = _xy(world, agent.home or agent.location) or _xy(world, agent.location)
    posts = trading_posts(world)
    if at is None:
        return posts[0]
    return min(posts, key=lambda p: math.hypot(*(a - b for a, b in zip(_xy(world, p) or at, at))))


def _is_state(world: "World", party: str) -> bool:
    return E._is_state(world, party)


def going_price(world: "World", item: str) -> float:
    """What a good has gone for between people over the last game day, or
    book when nobody has traded it."""
    since = world.sim_time - PRICE_WINDOW_H * 3600.0
    units = paid = 0.0
    for t in reversed(world.market.transactions):
        if t.sim_time < since:
            break
        if t.item != item or t.unit_price <= 0 or _is_state(world, t.seller) or _is_state(world, t.buyer):
            continue
        units += t.qty
        paid += t.unit_price * t.qty
    return round(paid / units, 2) if units else round(D.base_price(item), 2)


def history(world: "World", item: str, hours: float = 24.0, buckets: int = 12) -> list[float | None]:
    """Average price between people in each of `buckets` slices of the last
    `hours`, oldest first; None where nothing traded."""
    start = world.sim_time - hours * 3600.0
    step = hours * 3600.0 / buckets
    acc = [[0.0, 0] for _ in range(buckets)]
    for t in reversed(world.market.transactions):
        if t.sim_time < start:
            break
        if t.item != item or t.qty <= 0 or _is_state(world, t.seller) or _is_state(world, t.buyer):
            continue
        k = min(buckets - 1, int((t.sim_time - start) // step))
        acc[k][0] += t.unit_price * t.qty
        acc[k][1] += t.qty
    return [round(v / n, 2) if n else None for v, n in acc]


def party_name(world: "World", party: str) -> str:
    if _is_state(world, party):
        return "the state"
    a = world.agents.get(party)
    if a is not None:
        return a.name
    b = world.businesses.get(party)
    if b is not None:
        o = world.agents.get(b.owner)
        return o.name if o else b.name
    return party


def owner_of(world: "World", party: str) -> str:
    """The agent behind a party in a transaction: itself, or a business's owner."""
    if party in world.agents:
        return party
    b = world.businesses.get(party)
    return b.owner if b is not None else ""


def deals(world: "World", limit: int = 30) -> list[dict[str, Any]]:
    """The latest sales anywhere, newest first: who, what, how many, at what."""
    out = []
    for t in reversed(world.market.transactions):
        if len(out) >= limit:
            break
        if t.qty <= 0:
            continue
        # Meals bought at the state's taverns are not trade, and would bury it.
        if t.item in D.MEALS and _is_state(world, t.seller):
            continue
        out.append({"hour": round(t.sim_time / 3600.0, 2), "item": t.item, "qty": t.qty,
                    "price": round(t.unit_price, 2), "seller": party_name(world, t.seller),
                    "buyer": party_name(world, t.buyer), "seller_id": owner_of(world, t.seller),
                    "buyer_id": owner_of(world, t.buyer),
                    "state": _is_state(world, t.seller) or _is_state(world, t.buyer)})
    return out


# ---------------------------------------------------------------------------
# Goods in and out of your hands
# ---------------------------------------------------------------------------

def holding(world: "World", agent: "Agent", item: str) -> int:
    n = agent.inventory.get(item, 0)
    for b in agent.owned_businesses:
        biz = world.businesses.get(b)
        if biz is not None and not biz.closed:
            n += biz.inventory.get(item, 0)
    return n


def _take_goods(world: "World", agent: "Agent", item: str, qty: int) -> int:
    """Take up to `qty` of `item` from what `agent` carries, then from their
    businesses, fullest first. Returns how many."""
    left = qty
    n = min(left, agent.inventory.get(item, 0))
    if n:
        agent.remove_item(item, n)
        left -= n
    yards = sorted((world.businesses[b] for b in agent.owned_businesses
                    if b in world.businesses and not world.businesses[b].closed),
                   key=lambda b: -b.inventory.get(item, 0))
    for biz in yards:
        if left <= 0:
            break
        n = min(left, biz.inventory.get(item, 0))
        if n:
            biz.remove_item(item, n)
            left -= n
    return qty - left


def receiver(world: "World", agent: "Agent", item: str, qty: int) -> "Business | None":
    """Where goods bought for `agent` are carried: a business of theirs that
    uses them, else one with room, else None (their pack)."""
    from . import actions as A
    mine = [world.businesses[b] for b in agent.owned_businesses
            if b in world.businesses and not world.businesses[b].closed]
    for b in mine:
        if A._business_can_use(b, item):
            return b
    for b in mine:
        if E.business_storage_capacity(world, b) - sum(b.inventory.values()) >= qty:
            return b
    return None


def _hours(world: "World", post: str, dest: str) -> float:
    from . import claims as CL
    a, b = _xy(world, post), _xy(world, dest)
    if not a or not b:
        return MIN_DELIVERY_H
    h = math.hypot(a[0] - b[0], a[1] - b[1]) / PORTER_MPS / 3600.0
    if dest in world.claims and not CL.connected(world, dest):
        h *= 2.0
    return max(MIN_DELIVERY_H, h)


def _send(world: "World", log: "EventLog", to: "Agent", item: str, qty: int, price: float, post: str) -> str:
    """The post's porters carry goods to their buyer. Returns where to."""
    from .state import Dispatch
    dest = receiver(world, to, item, qty)
    place = dest.location if dest else (to.home or to.location)
    hours = _hours(world, post, place)
    d = Dispatch(id=world.new_id("D"), kind="goods", agent=to.id, business=dest.id if dest else "",
                 item=item, qty=qty, unit_price=price, fee=0.0, destination=place,
                 created_at=world.sim_time, arrives_at=world.sim_time + hours * 3600.0)
    world.dispatches[d.id] = d
    where = f"your {dest.type.split(' /')[0]} at {dest.location}" if dest else "you"
    return f"porters bring it to {where} in about {max(1, round(hours * 60))} min"


def _record(world: "World", log: "EventLog", item: str, qty: int, price: float,
            seller: str, buyer: str, post: str) -> None:
    from . import actions as A
    from .state import Transaction
    A._record_trade(world, log, Transaction(world.sim_time, item, qty, price, seller, buyer,
                                            city=M.city_of(post)), "board", post)


# ---------------------------------------------------------------------------
# Posting, taking, cancelling
# ---------------------------------------------------------------------------

def open_posts(world: "World", *, item: str | None = None, side: str | None = None,
               post: str | None = None) -> list[Any]:
    return [p for p in world.board.values()
            if p.status == "open" and p.qty > 0 and (item is None or p.item == item)
            and (side is None or p.side == side) and (post is None or p.post == post)]


def post(world: "World", log: "EventLog", agent: "Agent", side: str, item: str, qty: int,
         price: float, at: str = "") -> tuple[bool, str]:
    from .state import BoardPost
    if side not in ("sell", "buy"):
        return False, "side is sell (for sale) or buy (wanted)"
    if item not in D.ALL_ITEMS or item == "On Foot":
        return False, f"there is no such good as {item!r}"
    qty, price = int(qty or 0), round(float(price or 0.0), 2)
    if not 1 <= qty <= MAX_QTY:
        return False, f"post between 1 and {MAX_QTY}"
    if price <= 0 or price > D.base_price(item) * 10:
        return False, f"name a price above 0 and at most {D.base_price(item) * 10:.0f}"
    at = at or nearest_post(world, agent)
    if at not in trading_posts(world):
        return False, f"post at a trading post: {', '.join(trading_posts(world))}"
    if sum(1 for p in world.board.values() if p.owner == agent.id and p.status == "open") >= MAX_POSTS:
        return False, f"you have {MAX_POSTS} posts up already: take one down first"
    escrow = 0.0
    if side == "sell":
        qty = _take_goods(world, agent, item, qty)
        if qty <= 0:
            return False, f"you have no {item} to put up"
    else:
        escrow = round(price * qty, 2)
        if agent.denari < escrow:
            return False, f"{qty} at {price:.2f} is {escrow:.0f}, held until filled; you have {agent.denari:.0f}"
        agent.denari -= escrow
    p = BoardPost(id=world.new_id("P"), post=at, side=side, owner=agent.id, item=item, qty=qty,
                  price=price, created_at=world.sim_time,
                  expires_at=world.sim_time + POST_HOURS * 3600.0, qty_posted=qty, escrow=escrow)
    world.board[p.id] = p
    log.emit(world.sim_time, "board_posted", actor=agent.id, subject=p.id, location=at,
             side=side, item=item, qty=qty, price=price)
    what = "for sale" if side == "sell" else "wanted"
    held = "the goods are held at the post" if side == "sell" else f"{escrow:.0f} is held until it is filled"
    return True, f"posted {qty} {item} {what} at {price:.2f} each on the board at {at} ({p.id}); {held}"


def take(world: "World", log: "EventLog", agent: "Agent", post_id: str, qty: int = 0) -> tuple[bool, str]:
    """Take a post: buy from a for-sale post, or sell into a wanted one."""
    p = world.board.get(post_id)
    if p is None or p.status != "open" or p.qty <= 0:
        return False, "no such post on the board"
    if p.owner == agent.id:
        return False, "that is your own post: board_cancel it instead"
    other = world.agents.get(p.owner)
    if other is None:
        return False, "its owner is gone"
    want = int(qty) if qty and int(qty) > 0 else p.qty
    if p.side == "sell":
        n = min(want, p.qty)
        if agent.denari < p.price:
            return False, f"one costs {p.price:.2f}; you have {agent.denari:.0f}"
        n = min(n, int(agent.denari // p.price))
        cost = round(n * p.price, 2)
        agent.denari -= cost
        fee = round(cost * FEE, 2)
        other.denari += cost - fee
        world.government.collect(fee)
        p.qty -= n
        how = _send(world, log, agent, p.item, n, p.price, p.post)
        seller, buyer = other, agent
    else:
        n = min(want, p.qty, holding(world, agent, p.item))
        if n <= 0:
            return False, f"you have no {p.item}"
        n = _take_goods(world, agent, p.item, n)
        pay = round(n * p.price, 2)
        fee = round(pay * FEE, 2)
        agent.denari += pay - fee
        world.government.collect(fee)
        p.escrow = round(max(0.0, p.escrow - pay), 2)
        p.qty -= n
        how = _send(world, log, other, p.item, n, p.price, p.post)
        seller, buyer = agent, other
    p.filled += n
    if p.qty <= 0:
        p.status = "done"
        if p.side == "buy" and p.escrow > 0:          # rounding dust goes home
            other.denari += p.escrow
            p.escrow = 0.0
    _record(world, log, p.item, n, p.price, seller.id, buyer.id, p.post)
    log.emit(world.sim_time, "board_traded", actor=agent.id, subject=p.owner, location=p.post,
             significance=Significance.MEDIUM, post=p.id, side=p.side, item=p.item, qty=n,
             price=p.price, seller=seller.id, buyer=buyer.id)
    if p.side == "sell":
        return True, f"bought {n} {p.item} from {other.name} at {p.price:.2f} ({cost:.2f}); {how}"
    return True, f"sold {n} {p.item} to {other.name} at {p.price:.2f} ({pay - fee:.2f} after the post's cut)"


def _close(world: "World", log: "EventLog", p: Any, status: str) -> None:
    owner = world.agents.get(p.owner)
    if owner is not None and p.qty > 0 and p.side == "sell":
        dest = receiver(world, owner, p.item, p.qty)
        (dest or owner).add_item(p.item, p.qty)
    if owner is not None and p.side == "buy" and p.escrow > 0:
        owner.denari += p.escrow
    p.escrow, p.status = 0.0, status
    log.emit(world.sim_time, "board_closed", actor=p.owner, subject=p.id, location=p.post,
             side=p.side, item=p.item, left=p.qty, status=status)


def cancel(world: "World", log: "EventLog", agent: "Agent", post_id: str) -> tuple[bool, str]:
    p = world.board.get(post_id)
    if p is None or p.owner != agent.id or p.status != "open":
        return False, "no such post of yours on the board"
    left = p.qty
    _close(world, log, p, "cancelled")
    back = f"{left} {p.item} back to you" if p.side == "sell" else "the money held back to you"
    return True, f"took down {p.id}: {back}"


def tick(world: "World", log: "EventLog") -> None:
    """Posts past their day come down; long-closed ones are forgotten."""
    now = world.sim_time
    for p in list(world.board.values()):
        if p.status == "open" and (p.expires_at <= now or p.qty <= 0):
            _close(world, log, p, "expired" if p.qty > 0 else "done")
        elif p.status != "open" and now - p.expires_at > 24 * 3600.0:
            del world.board[p.id]


# ---------------------------------------------------------------------------
# Trading by rule (everyone but the player)
# ---------------------------------------------------------------------------

def _inputs_wanted(world: "World", agent: "Agent") -> dict[str, int]:
    """What the agent's businesses are short of, for STOCK_UNITS of output."""
    out: dict[str, int] = {}
    for b in agent.owned_businesses:
        biz = world.businesses.get(b)
        if biz is None or biz.closed or not biz.active_production:
            continue
        r = D.REFINING_RECIPES.get(biz.active_production) or D.CRAFTING_RECIPES.get(biz.active_production)
        if not r:
            continue
        for item, q in r.inputs.items():
            need = q * STOCK_UNITS - biz.inventory.get(item, 0)
            if need > 0:
                out[item] = out.get(item, 0) + need
    coming = {}
    for d in world.dispatches.values():
        if d.kind == "goods" and d.agent == agent.id and d.status == "on_way":
            coming[d.item] = coming.get(d.item, 0) + d.qty
    for p in world.board.values():
        if p.owner == agent.id and p.status == "open" and p.side == "buy":
            coming[p.item] = coming.get(p.item, 0) + p.qty
    return {i: n - coming.get(i, 0) for i, n in out.items() if n - coming.get(i, 0) > 0}


def _spare(world: "World", agent: "Agent") -> dict[str, int]:
    """Goods the agent makes and does not use itself."""
    uses = set()
    for b in agent.owned_businesses:
        biz = world.businesses.get(b)
        if biz is not None and not biz.closed and biz.active_production:
            r = D.REFINING_RECIPES.get(biz.active_production) or D.CRAFTING_RECIPES.get(biz.active_production)
            if r:
                uses |= set(r.inputs)
    out: dict[str, int] = {}
    for b in agent.owned_businesses:
        biz = world.businesses.get(b)
        if biz is None or biz.closed:
            continue
        for item, q in biz.inventory.items():
            if q > 0 and item not in uses and item in (biz.spec.outputs or ()) and item not in D.MEALS:
                out[item] = out.get(item, 0) + q
    return out


def ai_tick(world: "World", log: "EventLog", rng: random.Random) -> int:
    """Once a game hour: every settler but the player trades by rule.
    Returns how many deals and posts were made."""
    if not world.outposts:
        return 0
    people = [a for a in world.agents.values() if a.alive and a.id != world.human and a.owned_businesses]
    rng.shuffle(people)
    done = 0
    for a in people:
        acts = 0
        # 1. Short of inputs: buy the cheapest fair offer, or post a wanted.
        for item, need in sorted(_inputs_wanted(world, a).items()):
            if acts >= RULE_ACTIONS:
                break
            going = going_price(world, item)
            offers = sorted((p for p in open_posts(world, item=item, side="sell") if p.owner != a.id),
                            key=lambda p: p.price)
            bought = False
            for p in offers:
                if p.price > going * BUY_UNDER_GOING or a.denari - CASH_RESERVE < p.price:
                    break
                n = min(need, p.qty, int((a.denari - CASH_RESERVE) // p.price))
                if n > 0 and take(world, log, a, p.id, n)[0]:
                    need -= n
                    acts += 1
                    done += 1
                    bought = True
                if need <= 0 or acts >= RULE_ACTIONS:
                    break
            if need > 0 and not bought and acts < RULE_ACTIONS:
                price = round(going * WANT_AT_GOING, 2)
                n = min(need, int((a.denari - CASH_RESERVE) // max(price, 0.01)))
                if n >= 1 and post(world, log, a, "buy", item, n, price)[0]:
                    acts += 1
                    done += 1
        # 2. Spare goods: fill wanteds at a fair price, then post the rest.
        for item, spare in sorted(_spare(world, a).items(), key=lambda x: -x[1]):
            if acts >= RULE_ACTIONS:
                break
            going = going_price(world, item)
            for p in sorted(open_posts(world, item=item, side="buy"), key=lambda p: -p.price):
                if p.owner == a.id or p.price < going * SELL_INTO_AT or spare <= 0:
                    continue
                ok, _ = take(world, log, a, p.id, min(spare, p.qty))
                if ok:
                    spare = _spare(world, a).get(item, 0)
                    acts += 1
                    done += 1
                if acts >= RULE_ACTIONS:
                    break
            already = sum(p.qty for p in open_posts(world, item=item, side="sell") if p.owner == a.id)
            if spare >= SURPLUS_MIN and not already and acts < RULE_ACTIONS:
                price = round(max(going * ASK_OVER_GOING, E.state_price(world, item) * ASK_OVER_STATE), 2)
                n = min(MAX_QTY, int(spare * POST_SHARE))
                if n >= 1 and post(world, log, a, "sell", item, n, price)[0]:
                    acts += 1
                    done += 1
    return done


# ---------------------------------------------------------------------------
# What the page and the agents see
# ---------------------------------------------------------------------------

def view(world: "World", viewer: "Agent") -> dict[str, Any]:
    posts = sorted(open_posts(world), key=lambda p: (p.item, p.side, p.price))
    items = sorted({p.item for p in posts} | {d["item"] for d in deals(world, 40)})
    return {
        "trading_posts": trading_posts(world),
        "home_post": nearest_post(world, viewer),
        "fee": FEE,
        "posts": [{"id": p.id, "post": p.post, "side": p.side, "item": p.item, "qty": p.qty,
                   "price": p.price, "owner": party_name(world, p.owner), "owner_id": p.owner,
                   "mine": p.owner == viewer.id, "hours_left": round(max(0.0, p.expires_at - world.sim_time) / 3600, 1),
                   "you_have": holding(world, viewer, p.item)}
                  for p in posts],
        "deals": deals(world, 30),
        "prices": {i: {"going": going_price(world, i), "state": E.state_price(world, i),
                       "book": round(D.base_price(i), 2), "history": history(world, i)} for i in items},
    }


def lines_for(world: "World", agent: "Agent", limit: int = 6) -> list[str]:
    """For an agent's observation: posts that matter to it -- wanted goods it
    holds, offers of what its businesses use -- and its own."""
    from . import actions as A
    uses = set()
    for b in agent.owned_businesses:
        biz = world.businesses.get(b)
        if biz is not None and not biz.closed:
            uses |= set(A._usable_items(biz))
    out = []
    for p in sorted(open_posts(world), key=lambda p: p.price):
        if p.owner == agent.id:
            out.append(f"{p.id} YOURS: {p.side} {p.qty} {p.item} at {p.price:g} ({p.post})")
        elif p.side == "buy" and holding(world, agent, p.item) > 0:
            out.append(f"{p.id} WANTED {p.qty} {p.item} at {p.price:g} by {party_name(world, p.owner)} ({p.post})")
        elif p.side == "sell" and p.item in uses:
            out.append(f"{p.id} FOR SALE {p.qty} {p.item} at {p.price:g} by {party_name(world, p.owner)} ({p.post})")
        if len(out) >= limit:
            break
    return out
