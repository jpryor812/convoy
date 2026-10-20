/* FIGHTS (designer request, 2026-10-18): your bat against bandits.

   R swings, holding F raises your guard. Bandits close in, wind up (a red "!"
   over the head) and swing; a guard up and facing them stops most of the
   blow. Run far enough and you get away. The server keeps the score
   (/api/fight, convoy/combat.py): every swing and every blow goes there, and
   it says who is down and how the fight ended.

   Two kinds: the bounty mission's camp (walk up to it and they come at you)
   and an ambush on the open road while you carry goods (the server rolls for
   it every few seconds you spend between places). */

export function createFight({THREE, scene, S, api, makePerson, setAnim, CSS2DObject, UI, placeAt, campInfo, groundAt, banditModel}){
  const REACH = 2.9, BANDIT_SPEED = 5.2, WINDUP = 0.7, RECOVER = 1.6, ESCAPE = 30;
  let F = null;              // the server's view of the fight
  let foes = new Map();      // foe id -> {p, state, t, el, dead}
  let blocking = false, swingUntil = 0, nextSwing = 0, roadAt = 0, busy = false, restUntil = 0;
  let shield = null, bat = null, hud = null;

  function el(id){ return document.getElementById(id); }
  function ensureHud(){
    if (hud) return hud;
    hud = document.createElement("div"); hud.id = "fighthud"; hud.className = "frame gold";
    document.body.appendChild(hud);
    return hud;
  }
  function float(text, pos, cls){
    const d = document.createElement("div"); d.className = "fx-float " + (cls || ""); d.textContent = text;
    const o = new CSS2DObject(d); o.position.copy(pos).add(new THREE.Vector3(0, 2.3, 0)); scene.add(o);
    setTimeout(() => { scene.remove(o); d.remove(); }, 900);
  }

  /* The bat in your hand: a club on the right hand bone, or at your side. */
  function arm(){
    const P = S.player; if (!P || bat) return;
    const g = new THREE.Group();
    const wood = new THREE.MeshLambertMaterial({color: "#9b6a3a"});
    const club = new THREE.Mesh(new THREE.CylinderGeometry(0.07, 0.035, 0.85, 8), wood); club.position.y = 0.42; g.add(club);
    const grip = new THREE.Mesh(new THREE.CylinderGeometry(0.04, 0.04, 0.18, 8), new THREE.MeshLambertMaterial({color: "#3c2a1c"})); grip.position.y = 0.02; g.add(grip);
    let hand = null;
    P.body.traverse(o => { if (!hand && o.isBone && /right.?hand|hand.?r(ight)?$|r.?hand/i.test(o.name) && !/thumb|index|middle|ring|pinky/i.test(o.name)) hand = o; });
    if (hand){
      const s = 1 / (P.body.scale.x || 1);
      g.scale.setScalar(s); g.rotation.x = Math.PI / 2; hand.add(g);
    } else { g.position.set(0.32, 0.75, 0.1); g.rotation.x = 0.35; P.root.add(g); }
    bat = g;
    shield = new THREE.Mesh(new THREE.CircleGeometry(0.55, 20), new THREE.MeshBasicMaterial({color: "#cfe6ff", transparent: true, opacity: 0.35, side: THREE.DoubleSide, depthWrite: false}));
    shield.position.set(0, 1.15, 0.65); shield.visible = false; P.root.add(shield);
  }

  function spawn(view, at){
    clearFoes();
    const P = S.player.root.position;
    view.foes.forEach((f, i) => {
      const p = makePerson(banditModel ? banditModel() : "persian-man");
      p.body.traverse(o => { if (o.isMesh && o.material){ o.material = o.material.clone(); o.material.color && o.material.color.multiplyScalar(0.45); } });
      const ang = (at ? 0 : Math.random() * Math.PI * 2) + i * 1.3;
      const from = at ? at.clone().add(new THREE.Vector3(i * 2 - 1, 0, 1.5)) : P.clone().add(new THREE.Vector3(Math.cos(ang) * 14, 0, Math.sin(ang) * 14));
      p.root.position.copy(from);
      const tag = document.createElement("div"); tag.className = "foe-tag";
      tag.innerHTML = `<b>${f.name}</b><i><u style="width:100%"></u></i><em>!</em>`;
      const lbl = new CSS2DObject(tag); lbl.position.set(0, 2.25, 0); p.root.add(lbl);
      scene.add(p.root);
      foes.set(f.id, {p, state: "approach", t: 0.4 + i * 0.5, el: tag, dead: false, hp: f.hp, max: f.max});
    });
  }
  function clearFoes(){
    for (const f of foes.values()){ scene.remove(f.p.root); f.el.remove(); }
    foes.clear();
  }
  function sync(view){
    F = view;
    if (!view){ return; }
    for (const v of view.foes){
      const f = foes.get(v.id); if (!f) continue;
      f.hp = v.hp; f.el.querySelector("u").style.width = `${Math.max(0, v.hp / v.max * 100)}%`;
      if (v.hp <= 0 && !f.dead){ f.dead = true; f.state = "down"; f.t = 0; }
    }
    renderHud();
  }
  function renderHud(){
    const h = ensureHud();
    if (!F){ h.classList.remove("on"); return; }
    const you = F.you;
    const pct = Math.max(0, (you.hp - you.down_at) / (100 - you.down_at) * 100);
    h.innerHTML = `<div class="fh-title">${F.kind === "camp" ? "☠️ Bandit camp" : "⚔️ Ambush!"}</div>`
      + `<div class="fh-row"><span>You</span><i class="fh-bar you"><u style="width:${pct}%"></u></i><b>${Math.round(you.hp)}</b></div>`
      + F.foes.map(f => `<div class="fh-row"><span>${f.name}</span><i class="fh-bar"><u style="width:${Math.max(0, f.hp / f.max * 100)}%"></u></i><b>${Math.round(f.hp)}</b></div>`).join("")
      + `<div class="fh-keys"><b>R</b> swing your ${you.weapon} &middot; hold <b>F</b> to block &middot; ${F.kind === "ambush" ? "or run" : "walk away to give up"}</div>`;
    h.classList.add("on");
  }

  async function send(body){
    let r;
    try { r = await api.post("/api/fight", body); } catch (e) { return null; }
    return r;
  }
  function finish(r){
    // The server settled it: say how, let the fallen lie a moment, tidy up.
    if (r && r.message) UI.toast(r.message, r.fight && r.fight.over === "lost" ? "bad" : "");
    const left = [...foes.values()];
    for (const f of left) if (!f.dead){ f.state = "leave"; f.t = 0; }
    F = null; renderHud(); restUntil = performance.now() + 10000;
    setTimeout(() => { for (const f of left){ scene.remove(f.p.root); f.el.remove(); } foes = new Map([...foes].filter(([, f]) => !left.includes(f))); }, 2200);
    UI.refreshSoon();
  }
  function handle(r){
    if (!r) return;
    if (r.fight) sync(r.fight);
    if (r.fight && r.fight.over) finish(r);
    else if (r.message && r.ok && !/^-\d+$|^Blocked$/.test(r.message) && !r.message.startsWith("Crushing")) UI.toast(r.message);
  }

  /* R: swing. Lands on the nearest bandit in front of you within reach. */
  async function swing(){
    const P = S.player; if (!P) return;
    arm();
    const now = performance.now();
    if (now < nextSwing) return;
    const speed = (F && F.you.swing) || 0.8;
    nextSwing = now + speed * 1000 * 0.85; swingUntil = now + 520;
    if (!F) return;
    const fwd = new THREE.Vector3(Math.sin(P.heading), 0, Math.cos(P.heading));
    let best = null, bd = 1e9;
    // The nearest bandit in reach, those in front of you first; you turn to
    // face whom you hit, so a swing is never wasted on facing the wrong way.
    for (const [id, f] of foes){
      if (f.dead) continue;
      const to = f.p.root.position.clone().sub(P.root.position).setY(0), d = to.length();
      const ahead = d > 0.01 ? fwd.dot(to.normalize()) : 1;
      const score = d - ahead * 0.8;
      if (d < REACH + 0.3 && score < bd){ best = id; bd = score; }
    }
    if (!best) return;
    // Turn to face whom you hit.
    const tgt = foes.get(best).p.root.position;
    P.heading = Math.atan2(tgt.x - P.root.position.x, tgt.z - P.root.position.z); P.root.rotation.y = P.heading;
    const r = await send({op: "swing", foe: best});
    if (r && r.ok && r.message) float(r.message.replace(" -- down!", ""), tgt, r.message.startsWith("Crushing") ? "crit" : "hit");
    handle(r);
  }
  function block(on){
    blocking = !!on;
    arm();
    if (shield) shield.visible = blocking;
  }

  async function strike(id, f){
    const P = S.player;
    const to = f.p.root.position.clone().sub(P.root.position).setY(0);
    if (to.length() > REACH + 0.4) return;           // you stepped back in time
    const fwd = new THREE.Vector3(Math.sin(P.heading), 0, Math.cos(P.heading));
    const facing = fwd.dot(to.clone().normalize()) > 0.1;     // your guard toward them
    const r = await send({op: "struck", foe: id, blocked: blocking && facing});
    if (r && r.ok) float(r.message || "", P.root.position, r.message === "Blocked" ? "block" : "hurt");
    if (r && r.ok && r.message !== "Blocked"){ document.body.classList.add("ouch"); setTimeout(() => document.body.classList.remove("ouch"), 180); }
    handle(r);
  }

  function update(dt, now){
    const P = S.player; if (!P) return;
    // Start: the camp, when you walk up to it.
    const camp = campInfo();
    if (!F && !busy && camp && now > restUntil && P.root.position.distanceTo(camp.pos) < 9){
      busy = true;
      send({op: "camp"}).then(r => {
        busy = false;
        if (r && r.ok && r.fight){ arm(); camp.hide(true); spawn(r.fight, camp.pos); sync(r.fight); if (r.message) UI.toast(r.message); }
        else { restUntil = performance.now() + 10000; if (r && r.message) UI.toast(r.message, "bad"); }
      });
    }
    // Start: an ambush, out between places carrying goods.
    if (!F && !busy && now - roadAt > 4000 && !placeAt(P.root.position) && !(S.ST && /^Travelling/.test(S.ST.activity || ""))){
      roadAt = now;
      const carrying = S.OBS && Object.values(S.OBS.you.carrying || {}).reduce((a, b) => a + b, 0) > 0;
      if (carrying){
        busy = true;
        send({op: "road"}).then(r => {
          busy = false;
          if (r && r.ok && r.fight){ arm(); spawn(r.fight, null); sync(r.fight); }
        });
      }
    }
    if (camp && !F) camp.hide(false);
    // The bandits.
    let nearest = 1e9;
    for (const [id, f] of foes){
      f.p.mixer.update(dt);
      if (groundAt) f.p.root.position.y = groundAt(f.p.root.position.x, f.p.root.position.z);
      const to = P.root.position.clone().sub(f.p.root.position).setY(0), d = to.length();
      if (f.state === "down"){
        f.t += dt; f.p.root.rotation.x = Math.max(-Math.PI / 2, -f.t * 4); f.el.style.opacity = "0.4";
        setAnim(f.p, "idle"); continue;
      }
      if (f.state === "leave"){
        f.p.root.position.addScaledVector(to.normalize(), -BANDIT_SPEED * dt);
        setAnim(f.p, "run", 1.2); continue;
      }
      nearest = Math.min(nearest, d);
      if (d > 0.01) f.p.heading = Math.atan2(to.x, to.z);
      f.p.root.rotation.y = f.p.heading;
      f.t -= dt;
      f.el.classList.toggle("wind", f.state === "windup");
      if (f.state === "approach"){
        if (d > REACH * 0.7){
          f.p.root.position.addScaledVector(to.normalize(), BANDIT_SPEED * dt);
          setAnim(f.p, "run", 1.1);
        } else { setAnim(f.p, "idle"); if (f.t <= 0){ f.state = "windup"; f.t = WINDUP; } }
      } else if (f.state === "windup"){
        setAnim(f.p, f.p.acts.attack ? "attack" : f.p.acts.work ? "work" : "idle", f.p.acts.attack ? 1.0 : 0.6);
        if (f.t <= 0){ f.state = "recover"; f.t = RECOVER + Math.random() * 0.6; strike(id, f); }
      } else if (f.state === "recover"){
        setAnim(f.p, "idle");
        if (d > REACH * 0.9) f.p.root.position.addScaledVector(to.normalize(), BANDIT_SPEED * 0.8 * dt);
        if (f.t <= 0) f.state = "approach";
      }
      // Bandits do not stand inside you.
      if (d < 1.1 && d > 0.01) f.p.root.position.addScaledVector(to.normalize(), -(1.1 - d));
    }
    // Run far enough and you are away.
    if (F && F.kind === "ambush" && !busy && nearest > ESCAPE && nearest < 1e8){
      busy = true;
      send({op: "flee"}).then(r => { busy = false; handle(r); });
    }
    if (F && F.kind === "camp" && camp && P.root.position.distanceTo(camp.pos) > ESCAPE && !busy){
      busy = true;
      send({op: "flee"}).then(r => { busy = false; handle(r); });
    }
    if (bat) bat.visible = true;
    if (shield) shield.visible = blocking;
  }

  return {
    update, swing, block,
    get blocking(){ return blocking; },
    swinging: () => performance.now() < swingUntil,
    get active(){ return !!F; },
  };
}
