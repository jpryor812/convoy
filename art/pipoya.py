"""Cut the Pipoya tileset into the pieces the map uses. Runs OUTSIDE Blender.

    .venv-art/bin/python art/pipoya.py   ->  art/generated/terrain/  and
                                             art/generated/pipoya/

WHY PIPOYA AND NOT KENNEY, FOR EVERYTHING ON THE GROUND
-----------------------------------------------------------------------------
Kenney's medieval pack was the whole map for a day and lost the job on two
points, neither of them about which pack is "better".

FIRST, THE THINGS THAT MATTER MOST HERE ARE THE THINGS IT IS WEAKEST AT. The two
buildings this economy is actually about are the farm and the mine. Kenney offers
a windmill and a small grey ramp; Pipoya offers a farmhouse with a ploughed field
beside it and a rock face with a timbered adit cut into it. One pair says "farm"
and "mine" without a caption and the other does not. Its trees are better too,
and there are three sizes of them.

SECOND, MIXING THEM IS WORSE THAN EITHER. Pipoya is painterly -- soft shading, no
keyline; Kenney is flat fills with a hard dark outline. Ground against buildings
that clash is tolerable, because ground is background. Buildings against
buildings is not: a Kenney barn beside a Pipoya farmhouse reads as two games in
one window, and the Kenney one also looks oversized, being drawn on a 64px canvas
against Pipoya's 48px.

WHAT PIPOYA CANNOT DO, AND WHAT IS DONE ABOUT IT
-----------------------------------------------------------------------------
It is an OVERWORLD set. Most of the sheet is castles, fortresses and whole towns
drawn as single landmarks, and there are NO CHARACTERS in it at all. Roughly
fourteen of its tiles are ordinary standalone buildings, which is enough for ten
business types, though a few of the assignments below are generic rather than
literal -- there is no forge and no market stall in it.

People are still Kenney's unit grid, and that is the one clash left standing.
The fix is Pipoya's own free character sprites, a separate pack by the same
artist: same style, 32x32, and four-directional WALK CYCLES, which would also
give back the facings that were lost when the Meshy characters were dropped.
Until those are downloaded the Kenney units stand in.

THE SHEETS ARE AUTOTILES, WHICH IS WHY THE TERRAIN HALF EXISTS
-----------------------------------------------------------------------------
An RPG Maker autotile is a kit of edges, corners and interiors meant to be
assembled by an engine that knows which neighbours match. This map draws smooth
polyline roads and an even parcel grid, neither of which lands on autotile
boundaries, so the kit is not usable as shipped. What IS usable is each terrain's
interior fill, found here without hand-picking coordinates from six different
sheet layouts: it is the most UNIFORM fully-opaque tile on the sheet. An edge
piece has grass on one side and water on the other and scores badly; the interior
is flat and scores best.
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageEnhance, ImageStat

ROOT = Path(__file__).resolve().parent.parent
PIPOYA = ROOT / "Pipoya RPG World Tileset 48x48 40x40 32x32" / "48x48"
AUTOTILES = PIPOYA / "[A]_type3"
SHEET = PIPOYA / "pipo-map001.png"

TERRAIN_OUT = ROOT / "art" / "generated" / "terrain"
OBJECT_OUT = ROOT / "art" / "generated" / "pipoya"

TILE = 48

# ---------------------------------------------------------------------------
# BRIGHTNESS
# ---------------------------------------------------------------------------
#
# Pipoya draws for a muted, naturalistic overworld: its grass reads #5c8141, a
# dark olive. Beside the reference art this map is aiming at -- flat lime lawns,
# bright sand paths, a clear blue river -- it looks like dusk.
#
# LIFTED AT EXTRACTION, NOT IN THE RENDERER. Every consumer then gets the same
# colours: the 2D map, anything drawn on a canvas later, and the eventual 3D
# scene. Doing it in a canvas filter would have brightened only whatever happened
# to be drawn through that filter, and the sprites would drift apart from the
# ground the first time somebody added a layer.
#
# Everything gets the same lift so nothing separates from anything else. Grass
# additionally rolls a little toward yellow, because "brighter green" in this
# style means more lime rather than more emerald, and saturation alone takes it
# toward emerald.
SATURATION = 1.30
BRIGHTNESS = 1.34

# Per-terrain overrides, because "brighter" means different things to grass and
# to water and a single global lift gets neither right. Hue is in Pillow's HSV
# units (0-255 for the full circle), NOT degrees; negative runs green toward
# yellow and blue toward cyan.
#
# Grass needs the hue roll as much as the lift: saturating a green pushes it
# toward emerald, and the look being copied is LIME. Water needs the most
# saturation of anything here -- Pipoya's river is a naturalistic grey-blue and
# reads as mud once the grass around it gets bright.
TUNE = {                     # label: (saturation, brightness, hue shift)
    "grass":  (1.34, 1.52, -5),
    "water":  (1.85, 1.42, -4),
    "forest": (1.30, 1.40, -4),
    "earth":  (1.20, 1.30,  0),
    "sand":   (1.15, 1.20,  0),
    "rock":   (1.25, 1.35,  0),
}


def brighten(im: Image.Image, label: str = "") -> Image.Image:
    """Lift an extracted tile toward the reference palette."""
    saturation, brightness, hue_shift = TUNE.get(
        label, (SATURATION, BRIGHTNESS, 0)
    )
    rgb = Image.merge("RGB", im.split()[:3])
    if hue_shift:
        h, s, v = rgb.convert("HSV").split()
        h = h.point(lambda x: (x + hue_shift) % 256)
        rgb = Image.merge("HSV", (h, s, v)).convert("RGB")
    rgb = ImageEnhance.Color(rgb).enhance(saturation)
    rgb = ImageEnhance.Brightness(rgb).enhance(brightness)
    return Image.merge("RGBA", (*rgb.split(), im.split()[3]))

# ---------------------------------------------------------------------------
# TERRAIN
# ---------------------------------------------------------------------------

TERRAINS = {
    "kusa":   "grass",       # the valley floor
    "tuti":   "earth",       # bare worked ground; the road surface
    "miti":   "road",        # a made road; often has no solid interior
    "umi":    "water",       # the river at The Crossing
    "mori":   "forest",      # tree cover in the wilderness
    "yama1":  "rock",        # The Hills and The Climb
    "sabaku": "sand",        # dry ground
}
BASE = "kusa"


# ---------------------------------------------------------------------------
# OBJECTS -- (column, row) on pipo-map001.png
# ---------------------------------------------------------------------------
#
# Every one of these is a SINGLE tile. The sheet's multi-tile pieces -- the
# castles, the mountains, the town clusters -- are deliberately left out: a
# business stands on a 2x2 block of parcels, which is 64 map pixels, and a 96px
# landmark laid on one would cover its neighbours' land. The town and castle
# icons are the right art for a zoomed-out view, and can be cut later when there
# is one.
OBJECTS = {
    # -- buildings, one per business type ---------------------------------
    # Chosen for silhouette and colour as much as for subject: at 48px a player
    # tells these apart by shape and roof colour long before recognising what
    # they are, so no two share both.
    "farm":            (0, 7),    # farmhouse with a ploughed field beside it
    "mine":            (7, 3),    # rock face with a timbered adit
    "refinery":        (6, 8),    # squat brown stone tower -- a furnace
    "tavern":          (0, 6),    # small timber building on the road
    "weaponsmith":     (2, 9),    # flagged keep; an armoury
    "stable":          (6, 9),    # long brown building
    "home-store":      (1, 9),    # gold-fronted hall with wide doors
    "equipment-store": (0, 9),    # a market tent
    "security":        (5, 8),    # round watchtower
    "brokerage":       (0, 8),    # blue-roofed civic hall

    # -- ground clutter ---------------------------------------------------
    "tree-small":      (0, 1),
    "tree-mid":        (1, 1),
    "tree-big":        (2, 1),
    "rock-small":      (3, 1),
    "rock-big":        (4, 1),
    "scrub":           (5, 1),
    "pond":            (6, 1),

    # -- the crossing -----------------------------------------------------
    # A bridge deck drawn for LEFT-RIGHT travel: the planking runs across the
    # direction you walk and the rails cap the top and bottom edges. The sheet
    # also carries a vertical-travel bridge at c1, which is the wrong one here --
    # the valley road runs left to right across the river, not along it.
    "bridge-deck":     (2, 2),    # stone roadway
    "bridge-pier":     (2, 3),    # the piers it stands on, drawn below the deck

    # -- landmarks --------------------------------------------------------
    "signpost":        (4, 3),
    "grave":           (5, 3),    # where the dead reappear
    "cave":            (6, 3),    # a second adit, for variety on a mining spur
}


def _tiles(sheet: Image.Image):
    for j in range(sheet.height // TILE):
        for i in range(sheet.width // TILE):
            yield sheet.crop((i * TILE, j * TILE,
                              i * TILE + TILE, j * TILE + TILE))


def interior(name: str, base: Image.Image | None = None) -> Image.Image | None:
    """The flattest opaque tile on a terrain's sheet -- see the module header."""
    path = AUTOTILES / f"pipo-map001_at-{name}.png"
    if not path.exists():
        return None
    sheet = Image.open(path).convert("RGBA")

    best: tuple[float, Image.Image] | None = None
    for tile in _tiles(sheet):
        if tile.split()[3].getextrema()[0] < 250:
            continue                       # has transparency: an edge piece
        score = sum(ImageStat.Stat(tile.convert("RGB")).stddev)
        if best is None or score < best[0]:
            best = (score, tile)
    if best is not None:
        return best[1]

    if base is None:
        return None
    # An overlay terrain, drawn to sit on grass. 0.72 rather than a stricter
    # bar because the road pieces carry small transparent nicks at their edges.
    fallback: tuple[float, Image.Image] | None = None
    for tile in _tiles(sheet):
        covered = ImageStat.Stat(tile.split()[3]).mean[0] / 255.0
        if covered < 0.72:
            continue
        merged = base.copy()
        merged.alpha_composite(tile)
        score = sum(ImageStat.Stat(merged.convert("RGB")).stddev)
        if fallback is None or score < fallback[0]:
            fallback = (score, merged)
    return fallback[1] if fallback else None


def main() -> int:
    if not SHEET.exists():
        print(f"no Pipoya sheet at {SHEET}")
        return 1
    TERRAIN_OUT.mkdir(parents=True, exist_ok=True)
    OBJECT_OUT.mkdir(parents=True, exist_ok=True)

    grass = interior(BASE)
    if grass is None:
        print("could not find a grass interior -- sheet layout has changed")
        return 1

    print("terrain")
    for name, label in TERRAINS.items():
        tile = interior(name, base=grass)
        if tile is None:
            print(f"  {label:<8} -- no usable interior on {name}")
            continue
        tile = brighten(tile, label)
        tile.save(TERRAIN_OUT / f"{label}.png")
        rgb = ImageStat.Stat(tile.convert("RGB")).mean
        print(f"  {label:<8} <- {name:<7} "
              f"#{int(rgb[0]):02x}{int(rgb[1]):02x}{int(rgb[2]):02x}")

    print("objects")
    sheet = Image.open(SHEET).convert("RGBA")
    for label, (col, row) in OBJECTS.items():
        tile = sheet.crop((col * TILE, row * TILE,
                           col * TILE + TILE, row * TILE + TILE))
        box = tile.getbbox()
        if box is None:
            print(f"  {label:<16} -- EMPTY at c{col} r{row}")
            continue
        tile = brighten(tile)
        tile.save(OBJECT_OUT / f"{label}.png")
        w, h = box[2] - box[0], box[3] - box[1]
        print(f"  {label:<16} c{col} r{row}  content {w}x{h}")

    print(f"\nwritten to {OBJECT_OUT.relative_to(ROOT)} "
          f"and {TERRAIN_OUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
