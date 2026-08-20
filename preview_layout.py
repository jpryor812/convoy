#!/usr/bin/env python3
"""Draw the valley's LAYOUT, with no run and no art. A plan, not a picture.

    python3 preview_layout.py                  # -> layout.html
    python3 preview_layout.py --out plan.html --scale 3.4

`render_world.py` draws a finished run: agents, businesses, sprites, a time
scrubber. This draws the ground they stand on, and deliberately nothing else --
coloured blocks where buildings go, dots where trees go.

That is the point. The layout has to be judged BEFORE the art arrives, because
every Meshy asset is modelled to sit in one of these footprints, and a spur whose
buildings overlap is far easier to see as ten bare squares than under ten
thatched roofs. It is also the only way to look at the world while the asset
library is still empty.

Blocks are colour-coded by what a slot is FOR -- market frontage, garrison,
working site -- so it is possible to tell at a glance whether Town reads as a
market and The Hills reads as somewhere nobody sensible builds.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from convoy import layout as L
from convoy import world_map as M

GRASS = "#93a96d"
ROAD = "#ad8f63"
SPUR = "#c2ab84"
PROP_COLOUR = {"tree": "#3d6b30", "bush": "#5f8845", "rock": "#8d8b83", "stump": "#7d5f3e"}
SLOT_COLOUR = {"store": "#c25b3a", "civic": "#4a6fa5", "home": "#c9a227", "site": "#6b4f2a"}

# Protected ground is tinted rather than outlined. A wall drawn round a
# waystation would imply a boundary the engine does not have -- protection is a
# property of the PLACE, and travelling agents pass through it, not into it.
PROTECTED_TINT = "#b9c98a"


def draw(places: dict[str, L.Place], scale: float) -> str:
    x0, y0, x1, y1 = L.bounds(places)
    w, h = x1 - x0, y1 - y0

    def pt(p) -> str:
        return f"{p.x - x0:.1f},{p.y - y0:.1f}"

    def poly(pts) -> str:
        return " ".join(pt(p) for p in pts)

    out = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w:.0f} {h:.0f}" '
        f'width="{w / scale:.0f}" style="display:block">',
        f'<rect width="{w:.0f}" height="{h:.0f}" fill="{GRASS}"/>',
    ]

    # ONE tint per junction, not one per place. Spurs inherit their junction's
    # protection, so drawing it per-place stacked three translucent discs on the
    # same ground and banded it into something that looked like a rendering bug
    # rather than a safe zone. The radius reaches past the spur loops because
    # the protection genuinely does.
    for name in M.LOCATIONS:
        if not M.LOCATION_BY_NAME[name].protected:
            continue
        c = places[name].center
        out.append(
            f'<circle cx="{c.x - x0:.1f}" cy="{c.y - y0:.1f}" '
            f'r="{L.SPUR_DEPTH + L.SPUR_LOOP_RADIUS + 60:.0f}" '
            f'fill="{PROTECTED_TINT}" opacity="0.5"/>'
        )

    for p in places.values():
        if p.path:
            out.append(
                f'<polyline points="{poly(p.path)}" fill="none" stroke="{SPUR}" '
                f'stroke-width="{L.SPUR_WIDTH}" stroke-linecap="round"/>'
            )
            out.append(
                f'<circle cx="{p.center.x - x0:.1f}" cy="{p.center.y - y0:.1f}" '
                f'r="{L.SPUR_LOOP_RADIUS}" fill="none" stroke="{SPUR}" '
                f'stroke-width="{L.SPUR_WIDTH}"/>'
            )
    out.append(
        f'<polyline points="{poly(L.main_road())}" fill="none" stroke="{ROAD}" '
        f'stroke-width="{L.ROAD_WIDTH}" stroke-linecap="round"/>'
    )

    for p in places.values():
        for q in p.props:
            r = (8.0 if q.kind == "tree" else 5.0) * q.scale
            out.append(
                f'<circle cx="{q.x - x0:.1f}" cy="{q.y - y0:.1f}" r="{r:.1f}" '
                f'fill="{PROP_COLOUR[q.kind]}"/>'
            )

    for p in places.values():
        for s in p.slots:
            # Rotated to the slot's facing, so the plan shows which way a
            # building will front -- the thing that decides whether a settlement
            # reads as a street or a storage yard.
            out.append(
                f'<rect x="{s.x - x0 - 10:.1f}" y="{s.y - y0 - 10:.1f}" width="20" '
                f'height="20" fill="{SLOT_COLOUR[s.kind]}" stroke="#2b2118" '
                f'stroke-width="1.5" transform="rotate({s.facing:.0f} '
                f'{s.x - x0:.1f} {s.y - y0:.1f})"/>'
            )

    for p in places.values():
        weight = "bold" if p.kind != "spur" else "normal"
        size = 30 if p.kind != "spur" else 25
        out.append(
            f'<text x="{p.center.x - x0:.1f}" y="{p.center.y - y0:.1f}" '
            f'font-size="{size}" text-anchor="middle" fill="#1c1409" '
            f'font-family="sans-serif" font-weight="{weight}" paint-order="stroke" '
            f'stroke="#f2eddc" stroke-width="6">{p.name}</text>'
        )
    out.append("</svg>")
    return "\n".join(out)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="layout.html")
    ap.add_argument("--scale", type=float, default=3.4,
                    help="world metres per rendered pixel")
    args = ap.parse_args()

    problems = L.check()
    places = L.build()
    x0, y0, x1, y1 = L.bounds(places)
    slots = sum(len(p.slots) for p in places.values())
    props = sum(len(p.props) for p in places.values())

    legend = "".join(
        f'<span style="background:{c};color:#fff;padding:2px 8px;'
        f'border-radius:3px;margin-right:6px">{k}</span>'
        for k, c in SLOT_COLOUR.items()
    )
    banner = (
        f'<p style="color:#c25b3a"><b>{len(problems)} layout problems</b><br>'
        + "<br>".join(problems[:12]) + "</p>"
        if problems else
        '<p style="color:#3d6b30"><b>layout check: all clean</b></p>'
    )

    Path(args.out).write_text(
        '<body style="margin:0;background:#1c1c1c;color:#ddd;'
        'font-family:system-ui,sans-serif">'
        f'<div style="padding:14px 18px">'
        f'<h2 style="margin:0 0 6px">The valley — layout plan</h2>'
        f'<p style="margin:0 0 6px;opacity:.8">{len(places)} places · '
        f'{slots} building slots · {props} props · '
        f'{x1 - x0:.0f}m x {y1 - y0:.0f}m · '
        f'{len(M.LOCATIONS)} junctions, {len(M.SPURS)} spurs</p>'
        f'<p style="margin:0 0 4px">{legend}</p>{banner}</div>'
        + draw(places, args.scale) + "</body>",
        encoding="utf-8",
    )
    print(f"wrote {args.out} — {len(places)} places, {slots} slots, {props} props")
    for x in problems:
        print(f"  ! {x}")
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
