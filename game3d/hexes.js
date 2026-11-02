/* THE HEX GRID (2026-11-01), the page's copy of convoy/hexes.py: pointy-top
   axial hexes in map metres, 250 m flat to flat. tests/test_hexes.mjs checks
   it gives the same answers as the server's. The server says what a hex is
   (convoy/hexes.terrain); here only the arithmetic, and the path preview. */

export const ACROSS_M = 250;
export const R = ACROSS_M / Math.sqrt(3);
const SQRT3 = Math.sqrt(3);
const DIRS = [[1, 0], [1, -1], [0, -1], [-1, 0], [-1, 1], [0, 1]];

export const key = h => `${h[0]},${h[1]}`;
export const parse = k => k.split(",").map(Number);

export function centre([q, r]){ return [R * SQRT3 * (q + r / 2), R * 1.5 * r]; }

function round(qf, rf){
  const sf = -qf - rf;
  let q = Math.round(qf), r = Math.round(rf);
  const s = Math.round(sf);
  const dq = Math.abs(q - qf), dr = Math.abs(r - rf), ds = Math.abs(s - sf);
  if (dq > dr && dq > ds) q = -r - s;
  else if (dr > ds) r = -q - s;
  return [q + 0, r + 0];
}
/* Python rounds halves to even; JS rounds them up. A centre exactly on a
   hex boundary is all that differs, and no map point lands there. */
export function toHex(x, y){
  return round((SQRT3 / 3 * x - y / 3) / R, (2 / 3 * y) / R);
}
export function neighbours([q, r]){ return DIRS.map(([dq, dr]) => [q + dq, r + dr]); }
export function distance(a, b){
  const dq = a[0] - b[0], dr = a[1] - b[1];
  return (Math.abs(dq) + Math.abs(dr) + Math.abs(dq + dr)) / 2;
}
export function ring(h, radius){
  const out = [];
  for (let dq = -radius; dq <= radius; dq++)
    for (let dr = Math.max(-radius, -dq - radius); dr <= Math.min(radius, -dq + radius); dr++) out.push([h[0] + dq, h[1] + dr]);
  return out;
}
/* The six corners of a hex, in map metres. */
export function corners(h){
  const [cx, cy] = centre(h), out = [];
  for (let i = 0; i < 6; i++){ const a = Math.PI / 180 * (60 * i - 30); out.push([cx + R * Math.cos(a), cy + R * Math.sin(a)]); }
  return out;
}
/* The cheapest way from a to b, a left out; cost(h) is the energy to step
   onto h, or null where you cannot go. */
export function path(a, b, cost, limit = 4000){
  if (a[0] === b[0] && a[1] === b[1]) return [];
  const seen = new Map([[key(a), 0]]), came = new Map();
  const todo = [[distance(a, b), 0, a]];
  let n = 0;
  while (todo.length && n < limit){
    let bi = 0;
    for (let i = 1; i < todo.length; i++) if (todo[i][0] < todo[bi][0] || (todo[i][0] === todo[bi][0] && todo[i][1] < todo[bi][1])) bi = i;
    const [, , h] = todo.splice(bi, 1)[0];
    if (h[0] === b[0] && h[1] === b[1]){
      const out = [b];
      while (came.has(key(out[out.length - 1])) && key(came.get(key(out[out.length - 1]))) !== key(a)) out.push(came.get(key(out[out.length - 1])));
      return out.reverse();
    }
    n++;
    for (const nb of neighbours(h)){
      const c = cost(nb);
      if (c == null) continue;
      const g = seen.get(key(h)) + c;
      if (g < (seen.has(key(nb)) ? seen.get(key(nb)) : Infinity)){
        seen.set(key(nb), g); came.set(key(nb), h);
        todo.push([g + distance(nb, b), n, nb]);
      }
    }
  }
  return null;
}
