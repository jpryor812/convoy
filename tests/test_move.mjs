// Movement rules (game3d/move.js), checked against the designer's spec,
// 2026-10-31: Fortnite on foot, Red Dead on a donkey. Run: node tests/test_move.mjs
import { TUNE, readIntent, createWalker, createRider } from "../game3d/move.js";

const fails = [];
const ok = (label, cond, detail = "") => { if (!cond) fails.push(`${label}${detail ? ": " + detail : ""}`); };
const DT = 1 / 120;
const intent = (held = [], pressed = [], yaw = Math.PI) => readIntent({held: new Set(held), pressed: new Set(pressed)}, yaw);
function run(w, secs, held = [], pressedFirst = [], ground = 0){
  let first = true;
  for (let t = 0; t < secs; t += DT){
    w.step(DT, intent(held, first ? pressedFirst : []), ground);
    first = false;
  }
  return w.s;
}
const speed = s => Math.hypot(s.vx, s.vz);

// Walk (6 m/s), and stopping is quick but not instant.
{
  const w = createWalker();
  run(w, 0.15, ["w"]);
  ok("walk reaches full speed fast", Math.abs(speed(w.s) - TUNE.walk) < 0.05, speed(w.s).toFixed(2));
  run(w, 0.05, []);
  ok("not an instant stop", speed(w.s) > 0.5, speed(w.s).toFixed(2));
  run(w, 0.15, []);
  ok("stopped within ~0.15-0.2 s", speed(w.s) < 0.01, speed(w.s).toFixed(2));
}
// Sprint and stamina: about 8 s, then a second's pause before it comes back.
{
  const w = createWalker();
  let t = 0;
  for (; t < 12 && (t < 0.5 || w.s.state === "sprint"); t += DT) w.step(DT, intent(["w", "shift"]), 0);
  ok("sprint runs about 8 s", t > 7.5 && t < 9, t.toFixed(2));
  ok("at sprint speed", true);
  const at = w.s.stamina;
  run(w, 0.8, ["w"]);
  ok("no regen in the first second", w.s.stamina - at < 1, (w.s.stamina - at).toFixed(1));
  run(w, 1.0, ["w"]);
  ok("then ~20/s", w.s.stamina > at + 10, w.s.stamina.toFixed(1));
}
// Jump: ~1.2 m, snappier down than up; air control; coyote and buffer.
{
  const w = createWalker();
  w.step(DT, intent([], [" "]), 0);
  let apex = 0, up = 0, down = 0, t = 0;
  while (t < 2){ w.step(DT, intent(), 0); t += DT; apex = Math.max(apex, w.s.y); if (w.s.vy > 0) up += DT; else if (!w.s.grounded) down += DT; if (w.s.grounded) break; }
  ok("jump height ~1.2 m", Math.abs(apex - TUNE.jumpHeight) < 0.05, apex.toFixed(2));
  ok("falls faster than it rises", down < up, `${up.toFixed(2)} up, ${down.toFixed(2)} down`);
  // Coyote: walk off a ledge, jump 0.08 s later -- it still counts.
  const c = createWalker();
  c.s.y = 2; c.step(DT, intent(), 2);          // standing on a ledge at 2 m
  c.step(DT, intent(["w"]), 0);                 // the ground drops away: falling
  for (let k = 0; k < 9; k++) c.step(DT, intent(["w"]), 0);
  c.step(DT, intent(["w"], [" "]), 0);
  ok("coyote time: a late jump still jumps", c.s.vy > 1, c.s.vy.toFixed(2));
  // Buffer: press 0.06 s before landing -- it jumps on landing.
  const b = createWalker();
  b.step(DT, intent([], [" "]), 0);
  let pressedAt = null;
  for (let k = 0; k < 400; k++){
    const willLand = b.s.vy < 0 && b.s.y + b.s.vy * 0.06 <= 0 && pressedAt == null;
    b.step(DT, intent([], willLand ? [" "] : []), 0);
    if (willLand) pressedAt = k;
    if (pressedAt != null && k > pressedAt + 12) break;
  }
  ok("jump buffer: pressed just before landing, it jumps again", b.s.vy > 0 || b.s.y > 0.05, `vy ${b.s.vy.toFixed(2)} y ${b.s.y.toFixed(2)}`);
}
// Slide: from a sprint, faster than it, easing toward a walk in ~0.75 s; not from a walk; the weapon waits.
{
  const w = createWalker();
  run(w, 0.5, ["w", "shift"]);
  w.step(DT, intent(["w", "shift"], ["c"]), 0);
  ok("slide starts above a sprint", w.s.state === "slide" && speed(w.s) > TUNE.slideSpeed - 0.5, `${w.s.state} ${speed(w.s).toFixed(2)}`);
  run(w, 0.4, ["w", "shift"]);
  const mid = speed(w.s);
  ok("eases off, not a linear drop", mid < TUNE.sprint && mid > TUNE.walk, mid.toFixed(2));
  run(w, 0.5, ["w"]);
  ok("over by ~0.8 s", w.s.state !== "slide", w.s.state);
  w.step(DT, intent(["w"], ["r"]), 0);
  ok("no swing the moment a slide ends", w.s.swingT < 0);
  const v = createWalker();
  run(v, 0.5, ["w"]);
  v.step(DT, intent(["w"], ["c"]), 0);
  ok("no slide from a walk", v.s.state !== "slide", v.s.state);
}
// Aim: slower, narrower, no sprint, tighter spread.
{
  const w = createWalker();
  run(w, 0.5, ["w", "shift"]);
  run(w, 0.4, ["w", "shift", "mouse2"]);
  ok("aiming stops the sprint", w.s.state !== "sprint" && w.s.aiming, w.s.state);
  ok("and slows you ~45%", Math.abs(speed(w.s) - TUNE.walk * TUNE.aimSpeed) < 0.1, speed(w.s).toFixed(2));
  ok("FOV narrows ~12 degrees", w.s.fovOffset < -11, w.s.fovOffset.toFixed(1));
  ok("spread tighter than hip-fire", w.s.spreadNow < TUNE.spreadBase, w.s.spreadNow.toFixed(2));
}
// Melee: a windup, then the blow; a cooldown; not in the air.
{
  const w = createWalker();
  let hits = 0;
  w.on("OnSwingHit", () => hits++);
  w.step(DT, intent([], ["r"]), 0);
  run(w, 0.1, []);
  ok("windup before the hit", hits === 0);
  run(w, 0.1, []);
  ok("the hit lands after ~0.15 s", hits === 1);
  w.step(DT, intent([], ["r"]), 0);
  ok("cooldown between swings", w.s.swingT < 0);
  const a = createWalker();
  a.step(DT, intent([], [" "]), 0);
  run(a, 0.1, []);
  a.step(DT, intent([], ["r"]), 0);
  ok("no swing in the air", a.s.swingT < 0);
}
// Riding: gaits by spurs, momentum, a gallop eases to a canter, stamina, wide turns, rein in.
{
  const r = createRider();
  const ride = (secs, held = [], tap = false) => { let first = true; for (let t = 0; t < secs; t += DT){ r.step(DT, readIntent({held: new Set(held), pressed: new Set(first && tap ? ["shift"] : [])}, 0)); first = false; } };
  ride(1.5, ["w"]);
  ok("W walks on", r.s.gait === 1 && Math.abs(r.s.speed - TUNE.gaits[1]) < 0.05, `${r.s.gait} ${r.s.speed.toFixed(2)}`);
  ride(0.6, ["w"], true); ride(0.6, ["w"], true); ride(0.6, ["w"], true);
  ok("three spurs, a gallop", r.s.gait === 4, String(r.s.gait));
  ride(2, ["w"]);
  ok("momentum: it builds", r.s.speed > TUNE.gaits[3], r.s.speed.toFixed(2));
  ride(3, ["w"]);
  ok("unspurred, a gallop eases to a canter", r.s.gait === 3, String(r.s.gait));
  ride(1, ["w", "shift"]); ride(0.3, ["w", "shift"], true);
  const st = r.s.stamina;
  ride(1, ["w", "shift"]);
  ok("a gallop tires the animal", r.s.stamina < st, `${st.toFixed(1)} -> ${r.s.stamina.toFixed(1)}`);
  const h0 = r.s.heading; ride(1, ["w", "shift", "a"]);
  const fastTurn = Math.abs(r.s.heading - h0);
  const slow = createRider();
  for (let t = 0; t < 1.5; t += DT) slow.step(DT, readIntent({held: new Set(["w"]), pressed: new Set()}, 0));
  const h1 = slow.s.heading; for (let t = 0; t < 1; t += DT) slow.step(DT, readIntent({held: new Set(["w", "a"]), pressed: new Set()}, 0));
  ok("wider arcs at speed", fastTurn < Math.abs(slow.s.heading - h1), `${fastTurn.toFixed(2)} vs ${Math.abs(slow.s.heading - h1).toFixed(2)}`);
  ride(2.5, ["s"]);
  ok("S reins in to a stop", Math.abs(r.s.speed) < 0.3 || r.s.speed < 0, r.s.speed.toFixed(2));
  ride(1.0, ["s"]);
  ok("keep holding and it backs up", r.s.speed < 0, r.s.speed.toFixed(2));
}

console.log(`test_move.mjs: ${fails.length} failures`);
for (const f of fails) console.log(`  FAIL ${f}`);
process.exit(fails.length ? 1 : 0);
