/* MOVEMENT (designer request, 2026-10-31): "make the character movement as
   close to Fortnite as possible ... give the animals, like the donkey,
   movement, and make it so that I ride the donkey ... similar to Red Dead
   Redemption 2."

   Four layers, kept apart so the same rules can one day run on a server and
   be predicted on the client (input -> intent -> state machine -> physics):

     readIntent(input, camYaw)      what the player is asking for this frame
     createWalker().step(dt, intent)  states and physics on foot
     createRider().step(dt, intent)   gaits and physics on a donkey

   Nothing here touches the scene or the server. main.js reads the keys and
   mouse, calls these, applies collisions, draws, and listens to the events
   (OnJump, OnLand, OnSlideStart, ...) to animate.

   The numbers are starting values, all in TUNE, to be tuned by feel; the
   debug readout (the ` key) shows the state and the live values. One scene
   unit is a metre at character scale (a person is 1.8 tall). */

export const TUNE = {
  // On foot (Fortnite).
  // Walk 1.5x and sprint 2x the first values (designer, 2026-11-01: "a
  // little too slow"); accel, decel and the slide scaled to keep the feel.
  walk: 6.0,                 // m/s
  sprint: 14.0,
  accel: 60,                 // m/s^2 toward the wanted speed
  decel: 65,                 // ... and to a stop: ~0.1 s from a walk
  airControl: 0.35,          // share of accel while airborne
  jumpHeight: 1.2,
  gravityUp: 22,             // m/s^2 rising ...
  gravityDown: 44,           // ... and falling (2x): snappy, not floaty
  coyote: 0.1,               // s after leaving the ground a jump still counts
  jumpBuffer: 0.1,           // s before landing a jump press still counts
  landing: 0.12,             // s of landing recovery
  staminaMax: 100,
  staminaDrain: 12,          // per s sprinting (~8 s)
  staminaRegen: 20,          // per s
  staminaDelay: 1.0,         // s after sprinting before it comes back
  staminaToSprint: 10,       // needed to start sprinting again
  slideMinSpeed: 10.0,        // must be sprinting this fast to slide
  slideSpeed: 17.0,
  slideTau: 0.32,            // s: speed decays toward walk with this time constant
  slideTime: 0.75,
  slideCooldown: 0.5,
  slideSteer: 0.15,          // share of normal steering while sliding
  slideWeaponDelay: 0.25,    // s after a slide before you can swing
  aimSpeed: 0.55,            // move speed while aiming
  aimFov: 12,                // degrees narrower
  sprintFov: 6,              // degrees wider
  fovEase: 0.15,             // s
  spreadBase: 1.0,           // hip-fire spread, in reticle units
  spreadMove: 1.6,           // ... added at full speed
  spreadPerSwing: 0.6,       // ... bloom per attack, recovering
  spreadRecover: 3.0,        // per s
  aimSpread: 0.25,           // share of spread left when aiming
  swingWindup: 0.15,         // s before the hit lands
  swingCooldown: 0.5,
  // Riding (Red Dead Redemption 2), for a donkey.
  // Raised with the faster walk and sprint (designer, 2026-11-01): a gallop
  // has to beat running on foot, or the donkey is not worth calling.
  gaits: [0, 3.3, 7.0, 11.5, 18.0],  // stand, walk, trot, canter, gallop (m/s)
  gaitNames: ["stand", "walk", "trot", "canter", "gallop"],
  rideAccel: 5.5,
  rideDecel: 7.5,
  rideBrake: 15.0,
  backUp: 1.6,               // reversing, slowly ...
  backUpDelay: 0.6,          // ... after holding S this long at a stand
  turnSlow: 2.4,             // rad/s at a walk ...
  turnFast: 0.9,             // ... and at a gallop: wide arcs
  spurWindow: 2.5,           // s a spur keeps a gait before it eases off
  mountStaminaMax: 100,
  mountDrainGallop: 9,       // per s
  mountDrainCanter: 1.5,
  mountRegen: 12,
};

/* ------------------------------------------------------------ input -> intent */

/* `input` is what main.js saw: held keys (a Set of lower-case names) and the
   keys and buttons pressed since the last frame (another Set). */
export function readIntent(input, camYaw){
  const held = input.held, hit = input.pressed;
  const ax = (held.has("d") ? 1 : 0) - (held.has("a") ? 1 : 0);
  const ay = (held.has("w") ? 1 : 0) - (held.has("s") ? 1 : 0);
  // Camera-relative: forward is where the camera looks along the ground.
  const fx = -Math.sin(camYaw), fz = -Math.cos(camYaw), rx = Math.cos(camYaw), rz = -Math.sin(camYaw);
  let mx = rx * ax + fx * ay, mz = rz * ax + fz * ay;
  const m = Math.hypot(mx, mz);
  if (m > 0){ mx /= m; mz /= m; }
  return {
    ax, ay, moveX: mx, moveZ: mz, moving: m > 0,
    sprint: held.has("shift"),
    sprintTap: hit.has("shift"),
    jump: hit.has(" "),
    crouch: hit.has("c"),
    aim: held.has("mouse2"),
    attack: hit.has("mouse0") || hit.has("r"),
    brake: held.has("s"),
  };
}

/* ------------------------------------------------------------ events */

function emitter(){
  const fns = {};
  return {
    on(name, fn){ (fns[name] = fns[name] || []).push(fn); },
    emit(name, data){ (fns[name] || []).forEach(f => f(data)); (fns["*"] || []).forEach(f => f(name, data)); },
  };
}

const approach = (v, to, rate, dt) => v < to ? Math.min(to, v + rate * dt) : Math.max(to, v - rate * dt);
const ease = (v, to, secs, dt) => v + (to - v) * (1 - Math.exp(-dt / Math.max(0.001, secs / 3)));

/* ------------------------------------------------------------ on foot */

/* States: idle, walk, sprint, slide, air, land. Aiming is an overlay that
   rides on walk, idle or air -- never on a slide or a sprint. */
export function createWalker(){
  const ev = emitter();
  const s = {
    state: "idle", aiming: false,
    vx: 0, vz: 0, vy: 0, y: 0, grounded: true,
    stamina: TUNE.staminaMax, staminaWait: 0,
    sinceGround: 0, jumpAt: -1e9, t: 0, jumped: false,
    slideT: 0, slideCool: 0, slideDirX: 0, slideDirZ: 0, weaponReady: 0,
    landT: 0, fovOffset: 0, spread: TUNE.spreadBase, swingT: -1, swingCool: 0,
    facing: 0,
  };
  function set(next){
    if (next === s.state) return;
    const prev = s.state;
    s.state = next;
    if (prev === "sprint") ev.emit("OnSprintEnd");
    if (next === "sprint") ev.emit("OnSprintStart");
    if (prev === "slide") ev.emit("OnSlideEnd");
    ev.emit("OnStateChange", {from: prev, to: next});
  }
  function setAim(on){
    if (on === s.aiming) return;
    s.aiming = on;
    ev.emit(on ? "OnAimStart" : "OnAimEnd");
  }
  /* `ground` is the height of the ground under you now; `opts.speedMul` slows
     you (a raised guard), `opts.locked` stops input (fast travel). */
  function step(dt, it, ground, opts = {}){
    s.t += dt;
    const T = TUNE, speedNow = Math.hypot(s.vx, s.vz);
    if (opts.locked) it = {...it, moving: false, sprint: false, jump: false, crouch: false, attack: false, aim: false};
    // Timers.
    s.slideCool = Math.max(0, s.slideCool - dt);
    s.swingCool = Math.max(0, s.swingCool - dt);
    if (it.jump) s.jumpAt = s.t;
    // Ground contact.
    if (s.grounded) s.sinceGround = 0; else s.sinceGround += dt;

    // AIMING: held, but not while sprinting or sliding -- whichever came last wins.
    if (it.aim && s.state !== "slide"){
      setAim(true);
      if (s.state === "sprint") set("walk");
    } else setAim(false);

    // SLIDE: crouch while sprinting fast enough, on the ground, off cooldown.
    if (it.crouch && s.state === "sprint" && s.grounded && speedNow >= T.slideMinSpeed && s.slideCool <= 0){
      const k = 1 / (speedNow || 1);
      s.slideDirX = s.vx * k; s.slideDirZ = s.vz * k;
      s.vx = s.slideDirX * T.slideSpeed; s.vz = s.slideDirZ * T.slideSpeed;
      s.slideT = 0;
      set("slide");
      ev.emit("OnSlideStart");
    }

    // JUMP: on the ground, or just off it (coyote), or pressed just before landing (buffer).
    // Once per leaving the ground: from it, or within coyote time of walking off.
    const canJump = !s.jumped && (s.grounded || s.sinceGround <= T.coyote);
    if (canJump && s.t - s.jumpAt <= T.jumpBuffer){
      s.vy = Math.sqrt(2 * T.gravityUp * T.jumpHeight);
      s.grounded = false; s.sinceGround = T.coyote + 1; s.jumpAt = -1e9; s.jumped = true;
      if (s.state === "slide"){ s.slideCool = T.slideCooldown; s.weaponReady = s.t + T.slideWeaponDelay; }
      set("air");
      ev.emit("OnJump");
    }

    // SPRINT and STAMINA.
    const forwardish = it.moving && it.ay >= 0;
    let sprinting = it.sprint && forwardish && !s.aiming && s.state !== "slide" && s.grounded
      && (s.state === "sprint" ? s.stamina > 0 : s.stamina >= T.staminaToSprint);
    if (sprinting){
      s.stamina = Math.max(0, s.stamina - T.staminaDrain * dt);
      s.staminaWait = T.staminaDelay;
      if (s.stamina <= 0) sprinting = false;
    } else if (s.state !== "sprint"){
      s.staminaWait = Math.max(0, s.staminaWait - dt);
      if (s.staminaWait <= 0) s.stamina = Math.min(T.staminaMax, s.stamina + T.staminaRegen * dt);
    }

    // HORIZONTAL.
    if (s.state === "slide"){
      s.slideT += dt;
      const v = T.walk + (T.slideSpeed - T.walk) * Math.exp(-s.slideT / T.slideTau);
      // A little steering, no more.
      if (it.moving){
        s.slideDirX += (it.moveX - s.slideDirX) * T.slideSteer * dt * 6;
        s.slideDirZ += (it.moveZ - s.slideDirZ) * T.slideSteer * dt * 6;
        const n = Math.hypot(s.slideDirX, s.slideDirZ) || 1; s.slideDirX /= n; s.slideDirZ /= n;
      }
      s.vx = s.slideDirX * v; s.vz = s.slideDirZ * v;
      if (s.slideT >= T.slideTime || v <= T.walk + 0.3){
        s.slideCool = T.slideCooldown;
        s.weaponReady = s.t + T.slideWeaponDelay;
        set(it.moving ? (sprinting ? "sprint" : "walk") : "idle");
      }
    } else {
      let want = it.moving ? (sprinting ? T.sprint : T.walk) : 0;
      if (s.aiming) want *= T.aimSpeed;
      want *= opts.speedMul == null ? 1 : opts.speedMul;
      // In the air you keep the speed you took off with (a sprint jump goes
      // far); you can steer, and slow down, but not stop dead.
      if (!s.grounded && it.moving) want = Math.max(want, Math.hypot(s.vx, s.vz));
      const tx = it.moveX * want, tz = it.moveZ * want;
      const rate = (want > 0.01 ? T.accel : T.decel) * (s.grounded ? 1 : T.airControl);
      // Move the velocity toward the target, with each axis's share of the rate.
      const dx = tx - s.vx, dz = tz - s.vz, d = Math.hypot(dx, dz);
      if (d > 0){ const k = Math.min(1, rate * dt / d); s.vx += dx * k; s.vz += dz * k; }
      if (s.grounded && s.state !== "land"){
        const sp = Math.hypot(s.vx, s.vz);
        set(sprinting && sp > T.walk * 0.9 ? "sprint" : sp > 0.3 || it.moving ? "walk" : "idle");
      }
    }

    // VERTICAL: asymmetric gravity, and landing.
    if (!s.grounded){
      s.vy -= (s.vy > 0 ? T.gravityUp : T.gravityDown) * dt;
      s.y += s.vy * dt;
      if (s.y <= ground){
        s.y = ground; s.vy = 0; s.grounded = true; s.jumped = false;
        s.landT = T.landing;
        set("land");
        ev.emit("OnLand", {speed: Math.hypot(s.vx, s.vz)});
      }
    } else {
      // Walking off a drop: fall instead of snapping down.
      if (s.y - ground > 0.45){ s.grounded = false; s.vy = 0; set("air"); }
      else s.y = ground;
    }
    if (s.state === "land"){
      s.landT -= dt;
      if (s.landT <= 0) set(Math.hypot(s.vx, s.vz) > 0.3 ? "walk" : "idle");
    }

    // MELEE: a short windup, then the blow; not sliding, not airborne, not
    // the moment a slide ends. It cancels a sprint.
    if (s.swingT >= 0){
      s.swingT += dt;
      if (s.swingT >= T.swingWindup){ s.swingT = -1; ev.emit("OnSwingHit"); }
    } else if (it.attack && s.swingCool <= 0 && s.grounded && s.state !== "slide" && s.t >= s.weaponReady){
      s.swingT = 0; s.swingCool = T.swingCooldown;
      s.spread += T.spreadPerSwing;
      if (s.state === "sprint") set("walk");
      ev.emit("OnSwingStart");
    }

    // FOV and spread.
    const fovWant = s.aiming ? -T.aimFov : s.state === "sprint" || s.state === "slide" ? T.sprintFov : 0;
    s.fovOffset = ease(s.fovOffset, fovWant, T.fovEase, dt);
    const moveSpread = T.spreadBase + T.spreadMove * Math.min(1, Math.hypot(s.vx, s.vz) / T.sprint) + (s.grounded ? 0 : 1);
    s.spread = Math.max(moveSpread, s.spread - T.spreadRecover * dt);
    s.spreadNow = s.spread * (s.aiming ? T.aimSpread : 1);
    return s;
  }
  return {s, step, on: ev.on, emit: ev.emit};
}

/* ------------------------------------------------------------ on a donkey */

/* RDR2's horse: hold W to walk on; TAP Shift to spur up a gait (trot, canter,
   gallop) -- a spur holds that gait for a while, holding Shift keeps it,
   and it eases back a gait when you stop spurring. S reins in, and backs up
   from a stand. A/D steer, through wider arcs the faster you go. Galloping
   tires the animal; spent, it will not gallop. */
export function createRider(){
  const ev = emitter();
  const T = TUNE;
  const s = {gait: 0, speed: 0, heading: 0, stamina: T.mountStaminaMax, spurAt: -1e9, t: 0, turn: 0, stoppedT: 0};
  function setGait(g){
    g = Math.max(0, Math.min(T.gaits.length - 1, g));
    if (g === s.gait) return;
    const from = s.gait; s.gait = g;
    ev.emit("OnGait", {from: T.gaitNames[from], to: T.gaitNames[g]});
  }
  function step(dt, it, opts = {}){
    s.t += dt;
    if (opts.locked) it = {...it, ay: 0, ax: 0, sprintTap: false, sprint: false, brake: false};
    const fwd = it.ay > 0, back = it.ay < 0;
    // Spurs.
    if (it.sprintTap && fwd){
      s.spurAt = s.t;
      setGait(Math.max(2, s.gait + 1));
      ev.emit("OnSpur");
    }
    if (fwd && s.gait === 0) setGait(1);
    if (!fwd && !back) setGait(s.speed > 0.5 ? Math.min(s.gait, 1) : 0);
    if (back && s.speed > 0.3) setGait(0);
    // A spur wears off: a gallop eases to a canter and holds it there,
    // unless Shift is held (as Red Dead's horse does).
    if (fwd && !it.sprint && s.gait > 3 && s.t - s.spurAt > T.spurWindow){ setGait(3); s.spurAt = s.t; }
    // Stamina: a gallop spends it; spent, the gallop drops to a canter.
    if (s.gait === 4) s.stamina = Math.max(0, s.stamina - T.mountDrainGallop * dt);
    else if (s.gait === 3) s.stamina = Math.max(0, s.stamina - T.mountDrainCanter * dt);
    else s.stamina = Math.min(T.mountStaminaMax, s.stamina + T.mountRegen * dt);
    if (s.gait === 4 && s.stamina <= 0){ setGait(3); ev.emit("OnWinded"); }
    // THE CONVOY (2026-11-01): a cart goes no faster than a trot, nothing
    // gallops off the road, and a heavy load slows every gait (opts from
    // convoy.js).
    if (opts.maxGait != null && s.gait > opts.maxGait) setGait(opts.maxGait);
    // Speed: momentum both ways; reining in is quicker than coasting.
    let want = T.gaits[s.gait] * (opts.speedMul ?? 1);
    // Reining in stops you; keep holding at a stand and you back up.
    s.stoppedT = back && Math.abs(s.speed) <= 0.3 ? s.stoppedT + dt : 0;
    if (back && (s.stoppedT > T.backUpDelay || s.speed < -0.05)) want = -T.backUp;
    const rate = want > s.speed ? T.rideAccel : back ? T.rideBrake : T.rideDecel;
    s.speed = approach(s.speed, want, rate, dt);
    // Steering: wide arcs at speed, a pivot at a stand.
    const k = Math.min(1, Math.abs(s.speed) / T.gaits[4]);
    const rate2 = T.turnSlow + (T.turnFast - T.turnSlow) * k;
    s.turn = ease(s.turn, -it.ax * rate2, 0.25, dt);
    s.heading += s.turn * dt * (s.speed < 0 ? -1 : 1);
    return s;
  }
  return {s, step, on: ev.on, setGait};
}
