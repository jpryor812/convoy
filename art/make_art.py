#!/usr/bin/env python3
"""Draw the sprites the Kenney pack does not ship, in the Kenney pack's style.

The CC0 Medieval RTS pack covers terrain, structures and people. Convoy also has
six vehicles and 63 tradeable goods, and none of those exist in it. This file
draws them as SVG, using `palette.py` -- whose colours were sampled out of the
pack's own PNGs -- so the new art sits beside the old without looking bolted on.

Why generated rather than 69 hand-written files: the goods are a *taxonomy*, not
69 unrelated objects. Ore is ore whether it is copper, tin or iron; a cuirass is
a cuirass in bronze, iron or leather. Drawing one shape per category and tinting
it per material is how the Kenney pack itself gets 58 tiles out of about eight
ideas, and it means a new good added to `data.py` inherits sane art for free
instead of shipping with a blank square.

    python3 art/make_art.py            # writes art/generated/**

Every shape follows the three rules read off the pack: flat fill, outline in a
darker shade of the fill (never black), one lighter highlight plane.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import palette as P

OUT = Path(__file__).resolve().parent / "generated"
SIZE = 64
STROKE = 2.4


def svg(body: str, size: int = SIZE) -> str:
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {size} {size}" '
        f'width="{size}" height="{size}">'
        f'<g stroke-linejoin="round" stroke-linecap="round">{body}</g></svg>'
    )


def shape(d: str, fill: str, line: str, w: float = STROKE) -> str:
    return f'<path d="{d}" fill="{fill}" stroke="{line}" stroke-width="{w}"/>'


def ell(cx, cy, rx, ry, fill, line, w: float = STROKE) -> str:
    return (
        f'<ellipse cx="{cx}" cy="{cy}" rx="{rx}" ry="{ry}" fill="{fill}" '
        f'stroke="{line}" stroke-width="{w}"/>'
    )


def rect(x, y, w_, h, fill, line, r=3, w: float = STROKE) -> str:
    return (
        f'<rect x="{x}" y="{y}" width="{w_}" height="{h}" rx="{r}" fill="{fill}" '
        f'stroke="{line}" stroke-width="{w}"/>'
    )


def plain(d: str, fill: str, opacity: float = 1.0) -> str:
    """A highlight plane -- fill only, no outline, drawn over its parent."""
    return f'<path d="{d}" fill="{fill}" opacity="{opacity}"/>'


# ---------------------------------------------------------------------------
# VEHICLES -- top-down, nose north, matching the pack's unit orientation
# ---------------------------------------------------------------------------

def quadruped(body: str, body_dark: str, humps: int = 0, mane: str | None = None) -> str:
    """A four-legged animal from above, facing north.

    Proportions matter more than detail at 64px. The first attempt used a fat
    ellipse barrel with four rectangular legs poking straight out sideways and
    read unmistakably as a beetle. What fixes it is the silhouette, not more
    parts: a LONG narrow barrel, legs tucked close and angled along the body
    rather than out from it, and a distinct neck so the head reads as a head
    instead of a second body segment.
    """
    out = []
    # Legs first, so the barrel overlaps and hides where they join. Angled with
    # the body, tucked in tight -- splayed legs are what made it an insect.
    for lx, ly, rot in ((21, 25, -12), (43, 25, 12), (21, 43, -8), (43, 43, 8)):
        out.append(
            f'<g transform="rotate({rot} {lx} {ly})">'
            + rect(lx - 2.6, ly - 4, 5.2, 15, body_dark, body_dark, 2.6)
            + "</g>"
        )
    out.append(shape("M31 52 q-1 8 -4 10 q6 1 8 -9 z", body_dark, body_dark, 1.6))  # tail
    out.append(rect(23, 22, 18, 32, body, body_dark, 9))                  # barrel
    if humps:
        for i in range(humps):
            out.append(ell(32, 30 + i * 11, 7.5, 6, body, body_dark, 2.0))
    else:
        out.append(plain("M26 26 q6 -3 12 0 q0 22 -12 22 z", "#ffffff", 0.13))
    out.append(shape("M27 26 q5 -10 10 0 q-5 4 -10 0 z", body, body_dark, 2.0))  # neck
    if mane:
        out.append(plain("M28.5 22 q3.5 -8 7 0 q-3.5 3 -7 0 z", mane))
    out.append(shape("M25 7 l3 -6 l3.5 6 z", body, body_dark, 1.8))       # ears
    out.append(shape("M39 7 l-3 -6 l-3.5 6 z", body, body_dark, 1.8))
    out.append(rect(25.5, 6, 13, 18, body, body_dark, 6.5))               # head
    out.append(ell(32, 20, 5, 4.5, P.SAND_DARK, body_dark, 1.8))          # muzzle
    for ex in (28.5, 35.5):
        out.append(f'<circle cx="{ex}" cy="12" r="1.7" fill="{body_dark}"/>')
    return "".join(out)


def cart(wheels: int, body_w: int) -> str:
    """A cart bed with wheels and shafts, drawn behind whatever pulls it.

    The bed needs visible planking and the wheels need to be round and to sit
    proud of the bed, or from above the whole thing is an anonymous brown box.
    """
    x = 32 - body_w / 2
    out = []
    for sx in (x + 4, x + body_w - 6):          # shafts reaching to the harness
        out.append(rect(sx, 16, 2.6, 22, P.WOOD_DARK, P.WOOD_DARK, 1.2))
    ys = (40, 52) if wheels == 4 else (46,)
    for wy in ys:                               # wheels, behind the bed
        for wx in (x - 3, x + body_w + 3):
            out.append(ell(wx, wy, 4.5, 8, P.DIRT_DARK, "#4a3018", 2.0))
            out.append(plain(f"M{wx - 2} {wy - 5} h4 v10 h-4 z", P.WOOD_LIGHT, 0.35))
    out.append(rect(x, 34, body_w, 24, P.WOOD, P.WOOD_DARK, 3))
    for i in range(1, 4):                       # planks
        py = 34 + i * 6
        out.append(f'<path d="M{x + 2} {py} h{body_w - 4}" stroke="{P.WOOD_DARK}" '
                   f'stroke-width="1.4" opacity="0.55" fill="none"/>')
    out.append(plain(f"M{x + 3} 36 h{body_w - 6} v4 h{-(body_w - 6)} z",
                     P.WOOD_LIGHT, 0.5))
    return "".join(out)


def horse_at(dx: float, scale: float, body: str, dark: str, mane: str) -> str:
    """One draught animal, scaled and shifted, anchored at the top of the frame."""
    return (
        f'<g transform="translate({dx},-2) scale({scale}) '
        f'translate({(1 - scale) * 32 / scale},0)">'
        f"{quadruped(body, dark, mane=mane)}</g>"
    )


VEHICLES: dict[str, str] = {
    # A person, not a vehicle -- but an agent's `mounted_vehicle` may be None and
    # the map still has to draw something. Two boot prints read as "walking"
    # instantly at 24px, where a single boot just reads as a brown blob.
    "On Foot": svg(
        "".join(
            shape(f"M{x} {y} q-5 -12 0 -18 q6 -4 10 2 q3 6 0 16 q-5 3 -10 0 z",
                  P.LEATHER, P.LEATHER_DARK)
            + ell(x + 5, y + 3, 6, 4.5, P.LEATHER, P.LEATHER_DARK, 2.0)
            for x, y in ((16, 40), (34, 28))
        )
    ),
    "Horse": svg(quadruped(P.WOOD, P.WOOD_DARK, mane=P.DIRT_DARK)),
    "Camel": svg(quadruped(P.SAND, P.WOOD_DARK, humps=2)),
    "Donkey Cart": svg(
        cart(2, 24)
        + horse_at(0, 0.66, P.STONE, P.STONE_DARK, P.STONE_DARK)
    ),
    "2-Horse Chariot": svg(
        cart(2, 28)
        + horse_at(-8, 0.60, P.WOOD, P.WOOD_DARK, P.DIRT_DARK)
        + horse_at(8, 0.60, P.WOOD, P.WOOD_DARK, P.DIRT_DARK)
    ),
    "4-Horse Chariot": svg(
        cart(4, 32)
        + horse_at(-13.5, 0.48, P.WOOD, P.WOOD_DARK, P.DIRT_DARK)
        + horse_at(-4.5, 0.48, P.SAND, P.WOOD_DARK, P.DIRT_DARK)
        + horse_at(4.5, 0.48, P.WOOD, P.WOOD_DARK, P.DIRT_DARK)
        + horse_at(13.5, 0.48, P.SAND, P.WOOD_DARK, P.DIRT_DARK)
    ),
}


# ---------------------------------------------------------------------------
# GOODS -- one shape per category, tinted per material
# ---------------------------------------------------------------------------

def ore(fill: str, dark: str) -> str:
    """A rough rock with visible flecks -- matches Environment_11/18 in the pack."""
    body = shape(
        "M14 40 q-4 -12 6 -19 q10 -8 21 -3 q13 6 9 19 q-3 11 -18 12 q-15 1 -18 -9 z",
        P.STONE, P.STONE_DARK,
    )
    flecks = "".join(
        f'<circle cx="{cx}" cy="{cy}" r="{r}" fill="{fill}" stroke="{dark}" stroke-width="1.4"/>'
        for cx, cy, r in ((25, 26, 4.2), (38, 33, 3.4), (30, 40, 2.8), (40, 22, 2.4))
    )
    return svg(body + plain("M20 24 q10 -6 19 -1 q-10 4 -19 1 z", P.STONE_LIGHT, 0.6) + flecks)


def ingot(fill: str, dark: str) -> str:
    """A cast bar, seen at three-quarters."""
    return svg(
        shape("M12 40 l7 -12 h26 l7 12 z", fill, dark)
        + shape("M12 40 h40 v7 h-40 z", fill, dark)
        + plain("M20 30 h24 l4 8 h-32 z", "#ffffff", 0.22)
    )


def loaf(fill: str, dark: str, score: bool = True) -> str:
    body = shape("M11 40 q0 -16 21 -16 q21 0 21 16 q0 8 -21 8 q-21 0 -21 -8 z", fill, dark)
    marks = "".join(
        f'<path d="M{x} 30 l5 7" stroke="{dark}" stroke-width="2.2" fill="none"/>'
        for x in (22, 30, 38)
    ) if score else ""
    return svg(body + plain("M16 32 q16 -8 32 0 q-16 -4 -32 0 z", "#ffffff", 0.3) + marks)


def droplet(fill: str, dark: str) -> str:
    return svg(
        shape("M32 10 q16 20 16 28 a16 16 0 0 1 -32 0 q0 -8 16 -28 z", fill, dark)
        + plain("M25 34 q3 -8 8 -11 q-8 3 -8 11 z", "#ffffff", 0.55)
    )


def sheaf(fill: str, dark: str) -> str:
    """Standing stalks with fat seed heads -- a sheaf, tied at the waist.

    The first version drew bare curved lines and read as a firework. Cereal is
    recognisable by the HEADS, so they carry the drawing and the stalks are
    just what holds them up.
    """
    out = []
    for bend, lean in ((-9, -15), (-4.5, -7), (0, 0), (4.5, 7), (9, 15)):
        out.append(f'<path d="M32 54 q{bend} -16 {lean} -30" stroke="{dark}" '
                   f'stroke-width="2.6" fill="none"/>')
        head_x, head_y = 32 + lean, 24
        out.append(f'<g transform="rotate({lean * 1.6} {head_x} {head_y})">'
                   + ell(head_x, head_y - 6, 3.6, 8, fill, dark, 2.0)
                   + f'<path d="M{head_x} {head_y - 13} v13" stroke="{dark}" '
                     f'stroke-width="1.2" opacity="0.6" fill="none"/></g>')
    out.append(rect(23, 40, 18, 7, P.WOOD, P.WOOD_DARK, 3))       # the tie
    return svg("".join(out))


def sack(fill: str, dark: str) -> str:
    """A tied sack. Milled grain is a SACK, not stalks -- otherwise `Grain` and
    `Wheat` are the same picture, and the refining step is invisible on the map.
    """
    return svg(
        shape("M18 52 q-4 -22 6 -30 q8 -6 16 0 q10 8 6 30 q-14 4 -28 0 z", fill, dark)
        + rect(25, 14, 14, 9, P.WOOD, P.WOOD_DARK, 3)             # the neck tie
        + plain("M24 30 q8 -5 16 0 q-8 4 -16 0 z", "#ffffff", 0.28)
        + f'<path d="M28 40 h8" stroke="{dark}" stroke-width="2" opacity="0.5" fill="none"/>'
    )


def log_(fill: str, dark: str, cut: bool = False) -> str:
    out = [rect(10, 22, 44, 20, fill, dark, 8)]
    out.append(ell(50, 32, 5, 10, P.SAND_DARK if cut else fill, dark))
    if cut:
        out.append(ell(50, 32, 2.2, 5, dark, dark, 1.2))
    out.append(plain("M16 26 h30 v4 h-30 z", "#ffffff", 0.2))
    return svg("".join(out))


def block(fill: str, dark: str, bricks: bool = False) -> str:
    out = [shape("M12 26 l20 -10 l20 10 l-20 10 z", fill, dark)]         # top face
    out.append(shape("M12 26 v14 l20 10 v-14 z", fill, dark))            # left face
    out.append(shape("M52 26 v14 l-20 10 v-14 z", fill, dark))           # right face
    out.append(plain("M12 26 l20 -10 l20 10 l-20 10 z", "#ffffff", 0.25))
    out.append(plain("M52 26 v14 l-20 10 v-14 z", "#000000", 0.12))
    if bricks:
        out.append(f'<path d="M22 31 l20 10 M32 36 v14" stroke="{dark}" '
                   f'stroke-width="1.6" fill="none" opacity="0.7"/>')
    return svg("".join(out))


def hide(fill: str, dark: str) -> str:
    return svg(
        shape("M18 12 q6 6 14 6 q8 0 14 -6 q6 10 2 20 q4 10 -2 20 q-6 -6 -14 -6 "
              "q-8 0 -14 6 q-6 -10 -2 -20 q-4 -10 2 -20 z", fill, dark)
        + plain("M26 22 q6 -3 12 0 q-6 4 -12 0 z", "#ffffff", 0.25)
    )


def blade(fill: str, dark: str, length: int, guard: bool = True) -> str:
    top = 46 - length
    out = [shape(f"M32 {top} l6 8 v{length - 16} l-6 6 l-6 -6 v-{length - 16} z", fill, dark)]
    out.append(plain(f"M32 {top + 3} l3 6 v{length - 20} l-3 3 z", "#ffffff", 0.3))
    if guard:
        out.append(rect(20, 44, 24, 5, P.BRONZE_DARK, P.BRONZE_DARK, 2))
    out.append(rect(29, 48, 6, 10, P.WOOD, P.WOOD_DARK, 2))
    return svg("".join(out))


def spear(tip: str, tip_dark: str) -> str:
    return svg(
        rect(30, 12, 4, 46, P.WOOD, P.WOOD_DARK, 2)
        + shape("M32 4 l7 12 l-7 8 l-7 -8 z", tip, tip_dark)
        + plain("M32 8 l3 7 l-3 4 z", "#ffffff", 0.3)
    )


def sling(fill: str, dark: str) -> str:
    """A leather pouch on two long draped cords. The cords must SAG -- drawn
    straight and short they read as a pair of rabbit ears."""
    return svg(
        f'<path d="M14 8 q2 22 15 30 M50 8 q-2 22 -15 30" stroke="{P.LEATHER_DARK}" '
        f'stroke-width="2.8" fill="none"/>'
        + shape("M20 34 q12 -7 24 0 q-2 16 -12 18 q-10 -2 -12 -18 z", fill, dark)
        + plain("M25 37 q7 -3 14 0 q-7 4 -14 0 z", "#ffffff", 0.25)
    )


def slingshot(fill: str, dark: str) -> str:
    """A forked stick with an elastic band -- a different weapon from a sling,
    and it should not be a different colour of the same picture."""
    return svg(
        rect(29, 32, 6, 26, fill, dark, 3)                     # handle
        + shape("M29 34 q-9 -10 -13 -22 q6 -3 9 0 q4 10 10 16 z", fill, dark)
        + shape("M35 34 q9 -10 13 -22 q-6 -3 -9 0 q-4 10 -10 16 z", fill, dark)
        + f'<path d="M17 12 q15 10 30 0" stroke="{P.LEATHER_DARK}" '
          f'stroke-width="2.6" fill="none"/>'
        + ell(32, 17, 5, 3.5, P.LEATHER, P.LEATHER_DARK, 1.8)  # the pouch
    )


def bow(fill: str, dark: str) -> str:
    return svg(
        f'<path d="M22 10 q22 22 0 44" stroke="{dark}" stroke-width="6" fill="none"/>'
        f'<path d="M22 10 q22 22 0 44" stroke="{fill}" stroke-width="3" fill="none"/>'
        f'<path d="M22 10 L22 54" stroke="{P.SAND_DARK}" stroke-width="2" fill="none"/>'
    )


def helm(fill: str, dark: str) -> str:
    return svg(
        shape("M16 38 q0 -24 16 -24 q16 0 16 24 q-8 5 -16 5 q-8 0 -16 -5 z", fill, dark)
        + rect(28, 30, 8, 14, P.STONE_DARK, dark, 2)
        + plain("M22 24 q10 -8 20 0 q-10 -3 -20 0 z", "#ffffff", 0.3)
    )


def cuirass(fill: str, dark: str) -> str:
    """A breastplate: SHOULDERS, a neck notch, and a waist.

    Drawn as a plain rounded blob with a centre seam it read as a coffee bean.
    Body armour is recognised by its shoulder line, so that is what has to be
    in the silhouette.
    """
    return svg(
        shape("M14 24 q2 -10 10 -12 q4 6 8 6 q4 0 8 -6 q8 2 10 12 "
              "q1 8 -2 12 q-2 14 -16 16 q-14 -2 -16 -16 q-3 -4 -2 -12 z", fill, dark)
        + plain("M22 16 q10 8 20 0 q-2 6 -10 7 q-8 -1 -10 -7 z", "#000000", 0.14)
        + plain("M20 26 q6 -4 10 -2 q-4 8 -8 12 q-3 -5 -2 -10 z", "#ffffff", 0.28)
        + f'<path d="M32 30 v18" stroke="{dark}" stroke-width="1.8" '
          f'opacity="0.55" fill="none"/>'
    )


def greaves(fill: str, dark: str) -> str:
    return svg(
        shape("M18 12 q8 -3 10 0 q3 20 -1 40 q-6 3 -10 0 q3 -20 1 -40 z", fill, dark)
        + shape("M46 12 q-8 -3 -10 0 q-3 20 1 40 q6 3 10 0 q-3 -20 -1 -40 z", fill, dark)
        + plain("M20 18 q4 -2 6 0 q-2 8 -3 14 q-3 1 -5 0 z", "#ffffff", 0.25)
    )


def tools(fill: str, dark: str) -> str:
    return svg(
        f'<path d="M14 50 L40 20" stroke="{P.WOOD_DARK}" stroke-width="5" fill="none"/>'
        + shape("M36 12 q12 -4 16 8 q-12 8 -20 2 z", fill, dark)
        + f'<path d="M50 50 L28 24" stroke="{P.WOOD_DARK}" stroke-width="5" fill="none"/>'
        + shape("M22 14 q-10 2 -8 12 q10 6 16 0 z", fill, dark)
    )


def house(fill: str, dark: str) -> str:
    return svg(
        shape("M10 30 L32 12 L54 30 z", P.GRASS, P.GRASS_DARK)
        + rect(16, 29, 32, 22, fill, dark, 2)
        + rect(28, 38, 9, 13, P.WOOD, P.WOOD_DARK, 1)
        + plain("M14 32 h14 v6 h-14 z", "#ffffff", 0.3)
    )


def coin_stack(fill: str, dark: str) -> str:
    return svg("".join(
        ell(32, y, 14, 6, fill, dark) for y in (44, 36, 28)
    ) + plain("M22 26 q10 -4 20 0 q-10 3 -20 0 z", "#ffffff", 0.4))


def meal(fill: str, dark: str) -> str:
    return svg(
        ell(32, 36, 20, 14, P.SAND, P.SAND_DARK)
        + ell(32, 34, 12, 8, fill, dark)
        + plain("M24 32 q8 -4 16 0 q-8 3 -16 0 z", "#ffffff", 0.3)
    )


# item name -> (drawing function, fill, outline)
ITEMS: dict[str, tuple] = {
    # raw extraction
    "Copper Ore": (ore, P.COPPER, P.COPPER_DARK),
    "Tin Ore": (ore, P.TIN, P.TIN_DARK),
    "Iron Ore": (ore, P.IRON, P.IRON_DARK),
    "Stone": (block, P.STONE, P.STONE_DARK),
    "Clay": (block, P.TERRACOTTA, P.FIRE_DARK),
    "Wood": (log_, P.WOOD, P.WOOD_DARK),
    "Wheat": (sheaf, P.WHEAT, P.WHEAT_DARK),
    "Hide": (hide, P.LEATHER, P.LEATHER_DARK),
    "Dirty Water": (droplet, P.MUD, P.MUD_DARK),
    # refined
    "Bronze": (ingot, P.BRONZE, P.BRONZE_DARK),
    "Iron": (ingot, P.IRON, P.IRON_DARK),
    "Charcoal": (block, "#4a4a4a", "#2b2b2b"),
    "Lumber": (log_, P.WOOD_LIGHT, P.WOOD_DARK),
    "Hardwood": (log_, P.DIRT_DARK, "#4a3018"),
    "Seasoned Hardwood": (log_, "#8a5a2b", "#4a3018"),
    "Cut Stone": (block, P.STONE_LIGHT, P.STONE_DARK),
    "Fired Brick": (block, P.TERRACOTTA, P.FIRE_DARK),
    "Purified Water": (droplet, P.WATER, "#5aa8c4"),
    "Grain": (sack, P.SAND, P.WHEAT_DARK),
    "Tanned Leather": (hide, "#8a5a2b", P.LEATHER_DARK),
    # food
    "Meal": (meal, P.TERRACOTTA, P.FIRE_DARK),
    # weapons
    "Slingshot": (slingshot, P.WOOD, P.WOOD_DARK),
    "Sling": (sling, P.LEATHER, P.LEATHER_DARK),
    "Bow": (bow, P.WOOD, P.WOOD_DARK),
    "Wooden Spear": (spear, P.WOOD_LIGHT, P.WOOD_DARK),
    "Bronze-Tipped Spear": (spear, P.BRONZE, P.BRONZE_DARK),
    "Iron-Tipped Spear": (spear, P.IRON, P.IRON_DARK),
    # armour
    "Leather Cap": (helm, P.LEATHER, P.LEATHER_DARK),
    "Leather Vest": (cuirass, P.LEATHER, P.LEATHER_DARK),
    "Leather Leggings": (greaves, P.LEATHER, P.LEATHER_DARK),
    "Bronze Helm": (helm, P.BRONZE, P.BRONZE_DARK),
    "Bronze Cuirass": (cuirass, P.BRONZE, P.BRONZE_DARK),
    "Bronze Greaves": (greaves, P.BRONZE, P.BRONZE_DARK),
    "Iron Helm": (helm, P.IRON, P.IRON_DARK),
    "Iron Cuirass": (cuirass, P.IRON, P.IRON_DARK),
    "Iron Greaves": (greaves, P.IRON, P.IRON_DARK),
    # equipment
    "Upgraded Tools": (tools, P.IRON, P.IRON_DARK),
    "Property Upgrade": (house, P.SAND, P.SAND_DARK),
}

# Daggers and swords differ only in blade length, so they are generated.
for _name, _fill, _dark, _len in (
    ("Bronze Dagger", P.BRONZE, P.BRONZE_DARK, 26),
    ("Iron Dagger", P.IRON, P.IRON_DARK, 26),
    ("Bronze Sword", P.BRONZE, P.BRONZE_DARK, 40),
    ("Iron Sword", P.IRON, P.IRON_DARK, 40),
):
    ITEMS[_name] = (lambda f, d, L=_len: blade(f, d, L), _fill, _dark)

# The bread ladder: five Laborer's tiers, five Hearty tiers, then the named
# loaves. Colour climbs from plain crust to gold so a student can read quality
# off the map without a legend.
_BREAD_TINTS = [
    (P.BREAD_DARK, "#7a4f24"), (P.BREAD, P.BREAD_DARK), ("#e0b45c", P.BREAD_DARK),
    ("#e8c877", P.WHEAT_DARK), (P.GOLD, P.GOLD_DARK),
]
for _i in range(1, 6):
    _f, _d = _BREAD_TINTS[_i - 1]
    ITEMS[f"Laborer's Bread T{_i}"] = (loaf, _f, _d)
    ITEMS[f"Hearty Bread T{_i}"] = (loaf, _f, _d)
ITEMS["Tier 1 Bread"] = (loaf, P.BREAD_DARK, "#7a4f24")
ITEMS["Tier 2 Bread"] = (loaf, P.BREAD, P.BREAD_DARK)
ITEMS["Fine Bread"] = (loaf, P.BREAD_FINE, P.WHEAT_DARK)
ITEMS["Masterwork Bread"] = (loaf, P.GOLD, P.GOLD_DARK)
ITEMS["Legendary Bread"] = (loaf, "#f5e07a", P.GOLD_DARK)

# Vehicles are tradeable goods too, so they need an inventory icon as well as a
# map sprite. The map sprite doubles as the icon -- same object, same drawing.
_VEHICLE_GOODS = ("Camel", "Horse", "Donkey Cart", "2-Horse Chariot",
                  "4-Horse Chariot", "On Foot")


# ---------------------------------------------------------------------------
# UI GLYPHS -- one per KIND of action, not one per action
# ---------------------------------------------------------------------------
# There are 53 actions and they fall into about ten families. A student reading
# a timeline needs to see "this was a trade, that was a hire" at a glance;
# 53 bespoke glyphs would be noise, and most would never be distinguishable at
# 16px anyway.

UI: dict[str, str] = {
    "coin": coin_stack(P.GOLD, P.GOLD_DARK),
    "chat": svg(
        shape("M8 14 q0 -6 6 -6 h36 q6 0 6 6 v20 q0 6 -6 6 h-22 l-10 9 v-9 h-4 "
              "q-6 0 -6 -6 z", P.CLOTH, P.STONE_DARK)
        + "".join(f'<circle cx="{cx}" cy="24" r="2.8" fill="{P.STONE_DARK}"/>'
                  for cx in (22, 32, 42))
    ),
    "work": svg(
        f'<path d="M18 50 L42 20" stroke="{P.WOOD_DARK}" stroke-width="6" fill="none"/>'
        + shape("M36 10 q14 0 16 12 q-14 6 -22 -2 z", P.IRON, P.IRON_DARK)
    ),
    "hire": svg(
        ell(22, 22, 8, 8, P.FACTIONS["green"], P.GRASS_DARK)
        + shape("M10 50 q0 -14 12 -14 q12 0 12 14 z", P.FACTIONS["green"], P.GRASS_DARK)
        + ell(44, 26, 7, 7, P.FACTIONS["blue"], "#20618c")
        + shape("M33 52 q0 -12 11 -12 q11 0 11 12 z", P.FACTIONS["blue"], "#20618c")
    ),
    "travel": svg(
        shape("M32 6 q14 0 14 15 q0 12 -14 27 q-14 -15 -14 -27 q0 -15 14 -15 z",
              P.TERRACOTTA, P.FIRE_DARK)
        + ell(32, 21, 6, 6, P.CLOTH, P.FIRE_DARK, 2.0)
    ),
    "build": svg(
        shape("M8 30 L32 10 L56 30 z", P.GRASS, P.GRASS_DARK)
        + rect(14, 29, 36, 24, P.SAND, P.SAND_DARK, 2)
        + rect(27, 39, 10, 14, P.WOOD, P.WOOD_DARK, 1)
    ),
    "combat": svg(
        f'<g transform="rotate(-30 32 32)">{blade(P.IRON, P.IRON_DARK, 36)}</g>'
        f'<g transform="rotate(30 32 32)">{blade(P.BRONZE, P.BRONZE_DARK, 36)}</g>'
    ),
    "food": meal(P.TERRACOTTA, P.FIRE_DARK),
    "warning": svg(
        shape("M32 8 L58 52 H6 z", P.GOLD, P.GOLD_DARK)
        + rect(29, 22, 6, 16, P.DIRT_DARK, P.DIRT_DARK, 2)
        + f'<circle cx="32" cy="44" r="3.4" fill="{P.DIRT_DARK}"/>'
    ),
    "death": svg(
        shape("M32 8 q16 0 16 18 q0 8 -4 12 v8 q0 6 -12 6 q-12 0 -12 -6 v-8 "
              "q-4 -4 -4 -12 q0 -18 16 -18 z", P.CLOTH, P.STONE_DARK)
        + f'<circle cx="25" cy="26" r="4.4" fill="{P.STONE_DARK}"/>'
        + f'<circle cx="39" cy="26" r="4.4" fill="{P.STONE_DARK}"/>'
    ),
}


def main() -> int:
    (OUT / "vehicles").mkdir(parents=True, exist_ok=True)
    (OUT / "items").mkdir(parents=True, exist_ok=True)
    (OUT / "ui").mkdir(parents=True, exist_ok=True)

    for name, markup in UI.items():
        (OUT / "ui" / f"{name}.svg").write_text(markup, encoding="utf-8")

    for name, markup in VEHICLES.items():
        (OUT / "vehicles" / f"{slug(name)}.svg").write_text(markup, encoding="utf-8")

    for name, (fn, fill, dark) in ITEMS.items():
        (OUT / "items" / f"{slug(name)}.svg").write_text(fn(fill, dark), encoding="utf-8")

    for name in _VEHICLE_GOODS:
        (OUT / "items" / f"{slug(name)}.svg").write_text(VEHICLES[name], encoding="utf-8")

    n_items = len(ITEMS) + len(_VEHICLE_GOODS)
    print(f"wrote {len(VEHICLES)} vehicles, {n_items} items, {len(UI)} ui glyphs to {OUT}")
    return 0


def slug(name: str) -> str:
    keep = [c.lower() if c.isalnum() else "-" for c in name]
    out = "".join(keep)
    while "--" in out:
        out = out.replace("--", "-")
    return out.strip("-")


if __name__ == "__main__":
    raise SystemExit(main())
