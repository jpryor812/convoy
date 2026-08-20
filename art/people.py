"""Cut the character sheets into map sprites, and put them in medieval clothes.

    .venv-art/bin/python art/people.py   ->  art/generated/people/*.png

WHY THESE AND NOT THE PACK WE WERE USING
-----------------------------------------------------------------------------
Kenney's units have no eyes, and it is not that they are badly drawn -- they are
drawn TOP-DOWN, so what you are looking at is the crown of a head and a pair of
shoulders. There is no face to bring out because the camera is above it. Nothing
could be manipulated into a face; it would have to be a different drawing.

isaiah658's pack is that different drawing: front-on figures at near eye level
with head, body, arms and legs, two-pixel eyes, and a three-frame walk cycle in
four directions. Front-facing characters on top-down ground is exactly what the
reference art does -- Pokemon has done it for thirty years -- so the mismatch
reads as convention rather than as error.

THE SHEETS ARE MODERN, WHICH IS THE ONE THING WRONG WITH THEM. Jeans, t-shirts,
a tuxedo, swimming trunks. So the clothes are re-hued here.

RECOLOURING BY EXCLUSION, NOT BY LISTING THE CLOTHES
-----------------------------------------------------------------------------
The obvious way is to list every clothing colour per character and map each one.
That is a lot of data to get slightly wrong -- kaylee's sheet alone carries sixty
colours, most of them one-pixel anti-aliasing on her hair.

So the small list is the one that is easy to be right about: SKIN AND HAIR, which
are three or four colours a piece and read straight off a palette dump. Anything
else on the figure is cloth or leather, and gets rolled to an earthy hue with its
LUMINANCE UNTOUCHED. Keeping luminance is what preserves the shading the artist
drew -- the highlight stays a highlight and the fold stays a fold -- so the
result reads as the same sprite in different clothes rather than as a flat
silhouette in a new colour.

Black outline is preserved everywhere, because it is the outline.
"""

from __future__ import annotations

import colorsys
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
PACK = ROOT / "art" / "source" / "isaiah658" / "Characters"
OUT = ROOT / "art" / "generated" / "people"

# Rows on an RPG-Maker-style sheet, established by measurement rather than by
# assuming the usual order: row 0 carries the most skin (a face), row 1 the least
# (the back of a head), and rows 2 and 3 are near mirrors of each other.
DIRECTIONS = ("S", "N", "W", "E")

# 16px figures are small beside a 48px building. Doubling is the only honest
# scale for pixel art -- any other factor resamples and softens the very edges
# that make it read -- and it lands a person at about two thirds a cottage,
# which is the proportion the reference art uses.
SCALE = 2

# Anything darker than this is outline or deep shadow and is left alone.
OUTLINE_MAX_L = 0.12


# name -> (skin and hair colours to keep, target hue for the clothes)
#
# Hue is 0-1 round the circle: 0.08 is tan leather, 0.28 a moss green, 0.55 a
# faded blue-grey, 0.02 an oxblood red. Chosen to be tellable apart at 32px,
# which is the only test that matters -- these are the five faces standing for
# five different models.
PEOPLE: dict[str, tuple[tuple[str, ...], float]] = {
    "luke": (("#f2d6c1", "#f2b871", "#e0ab67", "#c19259"), 0.28),
    "salley": (("#eaceb9", "#c8a971", "#9b8156", "#d9b982", "#ed356c"), 0.02),
    "child-1": (("#f2d6c1", "#68422e", "#7f5039"), 0.08),
    "zack": (("#ffe8d6", "#f7e0cf", "#d88054", "#b56b46", "#8e5437"), 0.11),
    # Tan, not blue: noah's HAIR is blue and preserved, so blue clothes made him
    # one colour from head to boot and unreadable at map size.
    "noah": (("#f2d6c1", "#8ed5ff", "#bae5ff", "#4995c1", "#53ace0",
              "#68422e"), 0.08),
    "green-cap-character": (("#f2d6c1", "#5cc376", "#2d9f4a", "#33b253",
                             "#42c463", "#61cc7c"), 0.09),
    # Already a hooded figure in a black cloak. Nothing to re-clothe, and the one
    # sprite in the pack that was medieval to begin with.
    "cloaked-figure": ((), None),
}


def _hex(value: str) -> tuple[int, int, int]:
    return tuple(int(value[i:i + 2], 16) for i in (1, 3, 5))


def reclothe(im: Image.Image, keep: set[tuple[int, int, int]],
             hue: float | None) -> Image.Image:
    """Roll every colour that is not skin, hair or outline to `hue`."""
    if hue is None:
        return im
    out = Image.new("RGBA", im.size, (0, 0, 0, 0))
    src, dst = im.load(), out.load()
    cache: dict[tuple[int, int, int], tuple[int, int, int]] = {}
    for y in range(im.height):
        for x in range(im.width):
            r, g, b, a = src[x, y]
            if a == 0:
                continue
            rgb = (r, g, b)
            if rgb in keep:
                dst[x, y] = (r, g, b, a)
                continue
            if rgb not in cache:
                h, lum, sat = colorsys.rgb_to_hls(r / 255, g / 255, b / 255)
                if lum <= OUTLINE_MAX_L:
                    cache[rgb] = rgb                       # outline, untouched
                else:
                    # Luminance kept exactly; saturation floored so a grey
                    # t-shirt becomes cloth rather than staying grey.
                    nr, ng, nb = colorsys.hls_to_rgb(hue, lum, max(sat, 0.42))
                    cache[rgb] = (round(nr * 255), round(ng * 255),
                                  round(nb * 255))
            nr, ng, nb = cache[rgb]
            dst[x, y] = (nr, ng, nb, a)
    return out


def direction_rows(sheet: Image.Image) -> int:
    """How many direction rows this sheet actually has.

    THE PACK IS NOT A UNIFORM GRID, which cost an hour. Most sheets are three
    columns by four rows -- south, north, west, east -- but `character-1` and
    `tuxedo-man` are three by THREE, at 24px a frame rather than 18. Cutting
    those on a four-row grid does not fail; it produces twelve frames of a
    person sliced through the waist, with a floating head in one and a pair of
    legs in the next, and the only way to notice is to look at them.

    So the rows are counted off the art: fully transparent scanlines separate
    the bands. Sheets whose figures touch top to bottom report one merged band
    and fall through to four, which is right for every one of them.
    """
    alpha = sheet.split()[3]
    bands, start = 0, None
    for y in range(sheet.height):
        filled = max(alpha.crop((0, y, sheet.width, y + 1)).getextrema()) > 0
        if filled and start is None:
            start = y
        elif not filled and start is not None:
            bands, start = bands + 1, None
    if start is not None:
        bands += 1
    return 3 if bands == 3 else 4


def cut(name: str) -> int:
    sheet_path = PACK / f"{name}.png"
    if not sheet_path.exists():
        print(f"  {name:<22} MISSING")
        return 0
    sheet = Image.open(sheet_path).convert("RGBA")
    rows = direction_rows(sheet)
    if rows != 4:
        print(f"  {name:<22} SKIPPED -- {rows} direction rows, not 4")
        return 0
    fw, fh = sheet.width // 3, sheet.height // 4
    keep_hex, hue = PEOPLE[name]
    keep = {_hex(h) for h in keep_hex}

    made = 0
    for row, facing in enumerate(DIRECTIONS):
        for col in range(3):
            frame = sheet.crop((col * fw, row * fh, col * fw + fw, row * fh + fh))
            frame = reclothe(frame, keep, hue)
            frame = frame.resize((fw * SCALE, fh * SCALE), Image.NEAREST)
            dest = OUT / f"{name}-{facing}-{col}.png"
            frame.save(dest)
            made += 1
    print(f"  {name:<22} {fw}x{fh} -> {fw * SCALE}x{fh * SCALE}, {made} frames"
          f"{'' if hue is None else f', hue {hue}'}")
    return made


def main() -> int:
    if not PACK.exists():
        print(f"no character sheets at {PACK}")
        return 1
    OUT.mkdir(parents=True, exist_ok=True)
    total = sum(cut(name) for name in PEOPLE)
    print(f"\n{total} frames written to {OUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
