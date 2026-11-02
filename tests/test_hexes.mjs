// The page's hex grid (game3d/hexes.js) against the server's (convoy/hexes.py),
// through the fixture tests/test_hexes.py checks too. Run: node tests/test_hexes.mjs
import { readFileSync } from "node:fs";
import { toHex, centre, distance, ring, path, neighbours, key } from "../game3d/hexes.js";

const fx = JSON.parse(readFileSync(new URL("./hex_fixture.json", import.meta.url)));
const fails = [];
const ok = (label, cond, detail = "") => { if (!cond) fails.push(`${label}${detail ? ": " + detail : ""}`); };

for (const [x, y, want] of fx.points){ const got = toHex(x, y); ok("same hex as the server", got[0] === want[0] && got[1] === want[1], `${x},${y} -> ${got} vs ${want}`); }
for (const [q, r, want] of fx.centres){ const got = centre([q, r]); ok("same centre", Math.abs(got[0] - want[0]) < 1e-6 && Math.abs(got[1] - want[1]) < 1e-6, `${q},${r}`); }
for (const [a, b, want] of fx.distance) ok("same distance", distance(a, b) === want);
ok("same ring", ring([5, 5], 2).length === fx.ring2);
const [a, b, want] = fx.path;
const got = path(a, b, h => (h[0] === 1 && h[1] === 0) ? null : 1);
ok("a path as long as the server's, round the same block", got && got.length === want.length && key(got[got.length - 1]) === key(b)
   && !got.some(h => h[0] === 1 && h[1] === 0), JSON.stringify(got));
let prev = a;
for (const h of got || []){ ok("each step a neighbour", neighbours(prev).some(n => key(n) === key(h))); prev = h; }

console.log(`test_hexes.mjs: ${fails.length} failures`);
for (const f of fails) console.log(`  FAIL ${f}`);
process.exit(fails.length ? 1 : 0);
