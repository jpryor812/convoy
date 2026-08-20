"""Reduce the Blender renders to pixel sprites. Runs OUTSIDE Blender.

    .venv-art/bin/python art/pixelate.py

STAGE TWO OF TWO -- `art/build_sprites.py` writes `art/generated/raw/`, this
turns it into what the map loads. Cheap and re-runnable: retuning the look costs
a second, where re-rendering costs minutes.

WHAT "REDUCED DEFINITION" ACTUALLY TAKES
-----------------------------------------------------------------------------
A Meshy render is a photograph: thousands of colours, soft anti-aliased edges,
lighting tuned for realism. Pixel art is the opposite of all three. Four things
have to happen, and the order matters.

1. SATURATE AND CONTRAST FIRST, while there are still enough pixels to carry it.
   Meshy's output is muted, and boosting after the downsample just amplifies
   whichever handful of wrong colours survived.

2. FLATTEN, then downsample. A median filter kills texture speckle -- individual
   roof shingles, stone pointing -- while leaving real edges alone. Downsampling
   without it turns detail into noise, which is what a photograph reduced to
   64px always looks like.

3. QUANTISE TO THE MODEL'S OWN COLOURS, not to `art/palette.py`. This was the
   surprise. Snapping the renders into the Kenney ramp -- the obvious move, and
   what the palette module exists for -- produced uniform brown mud, because the
   ramp was sampled from flat vector art and has nothing to say about a
   photographed stone wall. An adaptive palette of ~18 colours keeps each
   building looking like itself. `palette.py` is still right for the hand-drawn
   item icons and the UI; it is just the wrong tool here.

4. HARD ALPHA AND ONE OUTLINE. Pixel art has no soft edges, and Kenney's dark
   keyline is the single strongest marker of the style. The outline is taken
   from the alpha channel here rather than from Freestyle in Blender -- see the
   header of `build_sprites.py` for why that had to move.

SIZE: 8 PIXELS TO THE METRE
-----------------------------------------------------------------------------
One Kenney ground tile is 64px and covers 8 metres, so the whole valley is about
43,000px wide and a 1920px viewport shows 240m -- a junction and the ground
around it, which is the default zoom. Buildings inherit that scale honestly, so
a 13m refinery lands at ~104px against a 8m farm at ~64px. People do not; see
CHARACTER_M in `build_sprites.py`.
"""

from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image, ImageEnhance, ImageFilter

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

GENERATED = ROOT / "art" / "generated"
RAW = GENERATED / "raw"

PIXELS_PER_METRE = 8.0
BUILDING_FRAME_M = 22.0          # must match build_sprites.BUILDING_FRAME_M
BUILDING_RENDER_PX = 512
# 24px against a ~76px building -- roughly the 3.5:1 the reference screenshot
# uses. Still hugely out of scale (that is 19 world metres tall at map scale) and
# still correct: at true scale a person here is two pixels.
CHARACTER_TARGET_PX = 24

# The reduction factor that turns the shared building frame into map pixels.
# Derived rather than typed, so the two files cannot drift apart silently.
BUILDING_SCALE = (BUILDING_FRAME_M * PIXELS_PER_METRE) / BUILDING_RENDER_PX

OUTLINE_COLOUR = "#3b2a1c"
ADAPTIVE_COLOURS = 18

# A signature hue per business type, so a map can be scanned for who built what.
# Six Meshy buildings all render in the same beige-and-brown, which is faithful
# to the models and useless at a glance -- the mine and the tavern were genuinely
# hard to tell apart at map size. The tint is applied as a gentle pull toward the
# hue rather than a repaint, so the model keeps its own shading and detail.
TINTS: dict[str, tuple[int, int, int]] = {
    "farm":                  (126, 176, 74),    # green, growing things
    "mining-operation":      (122, 134, 150),   # slate, cut rock
    "refinery":              (198, 106, 62),    # furnace orange
    "tavern-inn":            (196, 150, 74),    # lamplit amber
    "weaponsmith-armory":    (172, 84, 72),     # forge red
    "vehicle-dealer-stable": (150, 112, 72),    # timber and tack
}
TINT_STRENGTH = 0.38


def trim(im: Image.Image) -> Image.Image:
    box = im.getbbox()
    return im.crop(box) if box else im


def tint(im: Image.Image, colour: tuple[int, int, int], strength: float) -> Image.Image:
    """Pull every pixel a fraction of the way toward `colour`.

    A pull, not a repaint. Replacing the colour outright flattens the model's own
    shading into a silhouette; moving it a third of the way keeps the roof, the
    walls and the shadows distinguishable while making the whole building read as
    "the green one" from across the map.
    """
    r, g, b, a = im.split()
    lut = [
        [round(v + (colour[c] - v) * strength) for v in range(256)]
        for c in range(3)
    ]
    return Image.merge("RGBA", (r.point(lut[0]), g.point(lut[1]),
                                b.point(lut[2]), a))


def outline(im: Image.Image, colour: str) -> Image.Image:
    """One dark keyline around the silhouette, drawn from the alpha channel."""
    w, h = im.size
    col = tuple(int(colour[i:i + 2], 16) for i in (1, 3, 5))
    alpha = im.split()[3]
    ring = Image.new("RGBA", (w + 2, h + 2), (0, 0, 0, 0))
    # Dilate by one pixel in all eight directions, then lay the sprite on top.
    mask = alpha.point(lambda v: 255 if v > 96 else 0)
    solid = Image.new("RGBA", (w, h), (*col, 255))
    for dx in (0, 1, 2):
        for dy in (0, 1, 2):
            ring.paste(solid, (dx, dy), mask)
    ring.paste(im, (1, 1), im)
    return ring


def reduce(
    src: Path,
    dst: Path,
    *,
    target_h: int | None = None,
    scale: float | None = None,
    tint_colour: tuple[int, int, int] | None = None,
    saturation: float = 1.75,
    contrast: float = 1.22,
    median: int = 5,
) -> tuple[int, int]:
    """One render -> one sprite. Either `target_h` or `scale`, not both."""
    im = trim(Image.open(src).convert("RGBA"))

    rgb = Image.merge("RGB", im.split()[:3])
    rgb = ImageEnhance.Color(rgb).enhance(saturation)
    rgb = ImageEnhance.Contrast(rgb).enhance(contrast)
    if median:
        rgb = rgb.filter(ImageFilter.MedianFilter(median))
    im = Image.merge("RGBA", (*rgb.split(), im.split()[3]))

    w, h = im.size
    if target_h is not None:
        size = (max(1, round(w * target_h / h)), target_h)
    else:
        size = (max(1, round(w * scale)), max(1, round(h * scale)))
    im = im.resize(size, Image.LANCZOS)

    if tint_colour:
        im = tint(im, tint_colour, TINT_STRENGTH)

    r, g, b, a = im.split()
    a = a.point(lambda v: 255 if v > 110 else 0)          # no soft edges
    im = Image.merge("RGBA", (r, g, b, a))

    flat = Image.merge("RGB", im.split()[:3]).quantize(
        colors=ADAPTIVE_COLOURS, method=Image.MEDIANCUT
    ).convert("RGB")
    im = Image.merge("RGBA", (*flat.split(), im.split()[3]))

    im = outline(im, OUTLINE_COLOUR)
    dst.parent.mkdir(parents=True, exist_ok=True)
    im.save(dst)
    return im.size


def main() -> int:
    if not RAW.exists():
        print(f"no renders at {RAW} -- run art/build_sprites.py in Blender first")
        return 1

    made = 0
    print(f"buildings  ({PIXELS_PER_METRE:.0f}px/m, x{BUILDING_SCALE:.3f})")
    for src in sorted((RAW / "buildings").glob("*.png")):
        size = reduce(
            src, GENERATED / "buildings" / src.name,
            scale=BUILDING_SCALE, tint_colour=TINTS.get(src.stem),
        )
        print(f"  {src.stem:<24} {size[0]:>3}x{size[1]:<3}"
              f"{'  tinted' if src.stem in TINTS else ''}")
        made += 1

    # THE THREE BUILDINGS MESHY NEVER MADE. Two stores and the player's home are
    # still the procedural Kenney-style sprites from `blender_assets.py`, because
    # nobody has modelled them -- and they arrived on a padded 128x128 canvas at a
    # scale set months before any of this. On the map they towered over a
    # refinery, which is the one size relationship the shared frame exists to get
    # right.
    #
    # They are trimmed and rescaled to a stated height here, in the same metres
    # the Meshy buildings are sized in, so the whole set is comparable. Nothing
    # else is done to them: they are already flat, already outlined, already the
    # right palette. Running them through the median filter and the quantiser
    # would only degrade art that was drawn correctly in the first place.
    LEGACY_HEIGHT_M = {
        "home-improvement-store": 7.0,
        "mining-farming-equipment-store": 7.0,
        "player-home": 5.0,
    }
    legacy = RAW / "legacy"
    if legacy.exists():
        print("legacy     (procedural, rescaled to match)")
        for src in sorted(legacy.glob("*.png")):
            metres = LEGACY_HEIGHT_M.get(src.stem, 6.0)
            im = trim(Image.open(src).convert("RGBA"))
            target = max(1, round(metres * PIXELS_PER_METRE))
            im = im.resize(
                (max(1, round(im.width * target / im.height)), target),
                Image.NEAREST,          # flat art: keep the edges hard
            )
            dst = GENERATED / "buildings" / src.name
            im.save(dst)
            print(f"  {src.stem:<32} {im.width:>3}x{im.height:<3} ({metres:.0f}m)")
            made += 1

    print(f"characters ({CHARACTER_TARGET_PX}px tall, out of scale by design)")
    for src in sorted((RAW / "characters").glob("*.png")):
        size = reduce(
            src, GENERATED / "characters" / src.name,
            target_h=CHARACTER_TARGET_PX,
            # People are small on the map, so texture detail is noise at any
            # setting; a lighter median keeps what little shape survives.
            median=3, saturation=1.85,
        )
        print(f"  {src.stem:<24} {size[0]:>3}x{size[1]}")
        made += 1

    print(f"\n{made} sprites written to art/generated/")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
