#!/usr/bin/env python3
"""The hex grid (convoy/hexes.py, 2026-11-01): the arithmetic, and the shared
fixture tests/hex_fixture.json that tests/test_hexes.mjs checks the page's
copy (game3d/hexes.js) against -- so the page and the server agree on which
hex any spot is in. Regenerate the fixture only when the grid itself changes.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from convoy import hexes as H

FAILURES: list[str] = []
FIXTURE = Path(__file__).with_name("hex_fixture.json")


def ok(label, condition, detail="") -> None:
    if not condition:
        FAILURES.append(f"{label}{': ' + detail if detail else ''}")


def test_geometry() -> None:
    ok("250 m flat to flat", abs(H.distance((0, 0), (1, 0)) - 1) < 1e-9
       and abs(H.centre((1, 0))[0] - H.ACROSS_M) < 1e-6)
    for h in [(0, 0), (4, -9), (-13, 2)]:
        ok("a centre is in its own hex", H.to_hex(*H.centre(h)) == h, str(h))
        ok("six neighbours, each one away", len(set(H.neighbours(h))) == 6
           and all(H.distance(h, n) == 1 for n in H.neighbours(h)))
    ok("a ring of radius 2 is 19 hexes", len(H.ring((0, 0), 2)) == 19)
    ok("keys round-trip", H.parse(H.key((-3, 7))) == (-3, 7))


def test_paths() -> None:
    p = H.path((0, 0), (5, 0), lambda h: 1)
    ok("a straight path", p is not None and len(p) == 5 and p[-1] == (5, 0), str(p))
    p = H.path((0, 0), (3, 0), lambda h: None if h in ((1, 0), (2, -1), (1, 1)) else 1)
    ok("round what you cannot cross", p is not None and (1, 0) not in p and p[-1] == (3, 0), str(p))
    ok("no way at all", H.path((0, 0), (3, 0), lambda h: None) is None)
    p = H.path((0, 0), (2, 0), lambda h: 5 if h == (1, 0) else 1)
    ok("dear ground is avoided", p is not None and (1, 0) not in p, str(p))


def test_the_fixture_still_holds() -> None:
    fx = json.loads(FIXTURE.read_text())
    for x, y, want in fx["points"]:
        ok("fixture point", list(H.to_hex(x, y)) == want, f"{x},{y}")


def main() -> int:
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for t in tests:
        t()
    print(f"test_hexes.py: {len(tests)} tests, {len(FAILURES)} failures")
    for f in FAILURES:
        print(f"  FAIL {f}")
    return 1 if FAILURES else 0


if __name__ == "__main__":
    raise SystemExit(main())
