/* THE CONVOY (designer, 2026-11-01): "when the convoy happens, it goes back
   to 3rd person POV and maybe music starts and there is like the widescreen
   view with some black on the top and bottom of the screen. I want to give a
   dramatic cinematic feel. And then, it should be a pretty long trek and
   every time, bandits come at you ... And when we have goods, and are
   riding/driving the vehicle, can the goods be on the vehicle? Like in a
   sack or something."

   The server keeps the score (convoy/trek.py, POST /api/trek); this plays it:

     * SET OUT: a panel of where you could take the load, the road's length
       and the danger, guards to hire. Leaving a place with goods offers it.
     * THE ROAD: found here over the map's roads and your claims' tracks, and
       drawn as a faint ribbon; the compass follows it. You steer the whole
       way. Off the road nothing gallops; a cart never passes a trot; a heavy
       load slows every gait (`limits`).
     * THE CINEMA: black bars top and bottom, a title card, the HUD down to
       what matters, and music (WebAudio, drawn here; a track at
       /audio/convoy.mp3 is played instead if there is one).
     * ENCOUNTERS: the page reports how far along the road you are; when
       bandits are reached the server answers with a fight, and fight.js
       plays it -- on foot ahead of you, riders from behind, settlers by name.
     * YOUR LOAD: sacks slung on the donkey, a cart behind it, a sack on your
       back on foot, as many as the load fills (`dress`). */

export function createConvoy(ctx){
  const {THREE, scene, S, api, UI, SCALE, roadSegs, distToRoads, groundAt, placeAt, you, short} = ctx;
  const C = {trek: null, route: null, ribbon: null, sentAt: 0, sending: false, prompted: "", panel: null,
             guards: [], fightOn: false};
  const $ = id => document.getElementById(id);

  /* ------------------------------------------------------------ the road */
  let G = null, gN = -1;
  function graph(){
    if (G && gN === roadSegs.length) return G;
    gN = roadSegs.length;
    const nodes = [], key = new Map(), adj = [];
    const grid = new Map(), CELLG = 3;
    const near = (x, z) => {
      const gx = Math.floor(x / CELLG), gz = Math.floor(z / CELLG);
      for (let i = -1; i <= 1; i++) for (let j = -1; j <= 1; j++){
        for (const n of grid.get(`${gx + i},${gz + j}`) || []) if (Math.hypot(nodes[n].x - x, nodes[n].z - z) < 1.6) return n;
      }
      return -1;
    };
    const node = (x, z) => {
      let n = near(x, z);
      if (n >= 0) return n;
      n = nodes.length; nodes.push({x, z}); adj.push([]);
      const k = `${Math.floor(x / CELLG)},${Math.floor(z / CELLG)}`;
      if (!grid.has(k)) grid.set(k, []); grid.get(k).push(n);
      return n;
    };
    for (const [ax, az, bx, bz] of roadSegs){
      const a = node(ax, az), b = node(bx, bz);
      if (a === b) continue;
      const d = Math.hypot(bx - ax, bz - az);
      adj[a].push([b, d]); adj[b].push([a, d]);
    }
    G = {nodes, adj, nearest(x, z){
      let best = -1, bd = 1e18;
      nodes.forEach((n, i) => { const d = (n.x - x) ** 2 + (n.z - z) ** 2; if (d < bd){ bd = d; best = i; } });
      return [best, Math.sqrt(bd)];
    }};
    return G;
  }
  /* The way from `a` to `b` (scene points): straight to the nearest road,
     along the roads (A*), straight off at the end -- or straight across if
     that is shorter. Returns {pts, cum, len} in scene units. */
  function findRoute(a, b){
    const g = graph();
    const straight = [a.clone(), b.clone()];
    let pts = straight;
    if (g.nodes.length){
      const [s, ds] = g.nearest(a.x, a.z), [t, dt] = g.nearest(b.x, b.z);
      const path = astar(g, s, t);
      if (path){
        const via = [a.clone(), ...path.map(i => new THREE.Vector3(g.nodes[i].x, 0, g.nodes[i].z)), b.clone()];
        const len = poly(via).len;
        if (len < a.distanceTo(b) * 2.6 || ds + dt < a.distanceTo(b)) pts = via;
      }
    }
    return poly(pts);
  }
  function poly(pts){
    const cum = [0];
    for (let i = 1; i < pts.length; i++) cum.push(cum[i - 1] + Math.hypot(pts[i].x - pts[i - 1].x, pts[i].z - pts[i - 1].z));
    return {pts, cum, len: cum[cum.length - 1]};
  }
  function astar(g, s, t){
    if (s < 0 || t < 0) return null;
    const gs = new Map([[s, 0]]), from = new Map(), open = [[0, s]], done = new Set();
    const h = i => Math.hypot(g.nodes[i].x - g.nodes[t].x, g.nodes[i].z - g.nodes[t].z);
    while (open.length){
      open.sort((p, q) => p[0] - q[0]);
      const [, u] = open.shift();
      if (u === t){ const out = [t]; let c = t; while (from.has(c)){ c = from.get(c); out.unshift(c); } return out; }
      if (done.has(u)) continue;
      done.add(u);
      for (const [v, d] of g.adj[u]){
        const ng = gs.get(u) + d;
        if (ng < (gs.has(v) ? gs.get(v) : 1e18)){ gs.set(v, ng); from.set(v, u); open.push([ng + h(v), v]); }
      }
      if (done.size > 20000) break;
    }
    return null;
  }
  /* How far along the route a point is (scene units), and how far off it. */
  function along(r, p){
    let best = 0, bd = 1e18;
    for (let i = 1; i < r.pts.length; i++){
      const a = r.pts[i - 1], b = r.pts[i], vx = b.x - a.x, vz = b.z - a.z, l2 = vx * vx + vz * vz || 1;
      const k = Math.max(0, Math.min(1, ((p.x - a.x) * vx + (p.z - a.z) * vz) / l2));
      const d = Math.hypot(p.x - a.x - vx * k, p.z - a.z - vz * k);
      if (d < bd){ bd = d; best = r.cum[i - 1] + k * Math.sqrt(l2); }
    }
    return [best, bd];
  }
  function pointAt(r, s){
    s = Math.max(0, Math.min(r.len, s));
    for (let i = 1; i < r.pts.length; i++){
      if (r.cum[i] >= s){
        const a = r.pts[i - 1], b = r.pts[i], k = (s - r.cum[i - 1]) / Math.max(1e-6, r.cum[i] - r.cum[i - 1]);
        return new THREE.Vector3(a.x + (b.x - a.x) * k, 0, a.z + (b.z - a.z) * k);
      }
    }
    return r.pts[r.pts.length - 1].clone();
  }
  function drawRibbon(r){
    dropRibbon();
    const pos = [], idx = [];
    const step = 3;
    for (let s = 0, i = 0; s <= r.len; s += step, i++){
      const p = pointAt(r, s), q = pointAt(r, Math.min(r.len, s + 1));
      const dx = q.x - p.x, dz = q.z - p.z, l = Math.hypot(dx, dz) || 1, nx = -dz / l * 0.5, nz = dx / l * 0.5;
      const y = groundAt(p.x, p.z) + 0.25;
      pos.push(p.x + nx, y, p.z + nz, p.x - nx, y, p.z - nz);
      if (i > 0){ const o = (i - 1) * 2; idx.push(o, o + 1, o + 2, o + 1, o + 3, o + 2); }
    }
    const geo = new THREE.BufferGeometry();
    geo.setAttribute("position", new THREE.Float32BufferAttribute(pos, 3)); geo.setIndex(idx);
    C.ribbon = new THREE.Mesh(geo, new THREE.MeshBasicMaterial({color: "#f3d27a", transparent: true, opacity: 0.38,
      depthWrite: false, side: THREE.DoubleSide, fog: false}));
    C.ribbon.raycast = () => {}; C.ribbon.renderOrder = 2;
    scene.add(C.ribbon);
  }
  function dropRibbon(){ if (C.ribbon){ scene.remove(C.ribbon); C.ribbon.geometry.dispose(); C.ribbon = null; } }

  /* ------------------------------------------------------------ where to */
  function destinations(){
    const P = S.player; if (!P) return [];
    const here = placeAt(P.root.position), seen = new Map();
    const add = (place, label, kind) => {
      const pl = S.places[place]; if (!pl || (here && here.name === place) || seen.has(place)) return;
      seen.set(place, {place, label, kind, km: P.root.position.distanceTo(pl.c) / SCALE / 1000});
    };
    const go = S.ST && (S.ST.go || (S.ST.delivery && S.ST.delivery.destination));
    if (go) add(go, `Your delivery: ${short(go)}`, "job");
    for (const k of (S.DATA && S.DATA.cities) || []) add(k.market, `Trading post · ${short(k.market)}`, "post");
    for (const v of S.buildings.values()){
      const mine = v.b.owner === you(), state = !v.b.owner;
      if (!mine && !state) continue;
      if (state && !/Refinery|Tavern/.test(v.b.type)) continue;
      add(v.b.place, `${mine ? "Your" : "The state's"} ${v.b.type.split(" /")[0]} · ${short(v.b.place)}`, mine ? "yours" : "state");
    }
    return [...seen.values()].sort((a, b) => (a.kind === "job" ? -1 : 0) - (b.kind === "job" ? -1 : 0) || a.km - b.km).slice(0, 9);
  }
  function carrying(){
    const c = S.OBS && S.OBS.you && S.OBS.you.carrying || {};
    return Object.entries(c).filter(([i, q]) => q > 0 && !/Bat|Dagger|Sword|Spear|Axe|Club|Armou?r|Helm|Shield/.test(i));
  }
  function units(){ return carrying().reduce((a, [, q]) => a + q, 0); }
  function capacity(){ return (S.OBS && S.OBS.you && S.OBS.you.capacity) || 10; }

  function panel(html){
    if (!C.panel){ C.panel = document.createElement("div"); C.panel.id = "convoy-panel"; C.panel.className = "frame gold"; document.body.appendChild(C.panel); }
    C.panel.innerHTML = html; C.panel.style.display = "block";
    C.panel.querySelectorAll("[data-cv-x]").forEach(b => b.onclick = () => closePanel());
    return C.panel;
  }
  function closePanel(){ if (C.panel) C.panel.style.display = "none"; }
  function esc(s){ return String(s).replace(/[&<>"]/g, c => ({"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;"}[c])); }

  function open(reason){
    if (C.trek) return;
    const goods = carrying();
    if (!goods.length){ UI.toast("You carry nothing to take by convoy.", "bad"); return; }
    const list = destinations();
    panel(`<h3>Set out with your load <button class="mini" data-cv-x>&times;</button></h3>
      ${reason ? `<div class="dim">${esc(reason)}</div>` : ""}
      <div class="cv-load">${goods.map(([i, q]) => `<span>${q} ${esc(i)}</span>`).join("")}</div>
      <div class="cv-h">Where to?</div>
      <div class="cv-list">${list.map((d, i) => `<button data-cv-to="${i}"><b>${esc(d.label)}</b><small>${d.km.toFixed(1)} km</small></button>`).join("") || `<div class="dim">Nowhere you know to take it yet.</div>`}</div>
      <div class="cv-foot"><button class="mini" data-cv-x>Not now</button></div>`)
      .querySelectorAll("[data-cv-to]").forEach(b => b.onclick = () => choose(list[+b.dataset.cvTo]));
  }
  async function choose(d){
    const P = S.player, pl = S.places[d.place];
    const r = findRoute(P.root.position.clone(), pl.c.clone());
    const res = await api.post("/api/trek", {op: "plan", to: d.place, metres: r.len / SCALE});
    if (!res.ok){ UI.toast(res.message || "Can't plan that.", "bad"); return; }
    const p = res.plan;
    if (!p.convoy){
      panel(`<h3>${esc(d.label)} <button class="mini" data-cv-x>&times;</button></h3>
        <div>What you carry is worth ${p.value.toFixed(0)} -- too little for anyone to come after. Just ride there.</div>
        <div class="cv-foot"><button class="mini" data-cv-x>OK</button></div>`);
      S.waypoint = Object.assign(pl.c.clone(), {label: short(d.place)});
      return;
    }
    const el = panel(`<h3>The road to ${esc(short(d.place))} <button class="mini" data-cv-x>&times;</button></h3>
      <div class="cv-facts"><div><small>Road</small><b>${(p.metres / 1000).toFixed(1)} km</b></div>
        <div><small>Load</small><b>${p.value.toFixed(0)}</b></div>
        <div><small>Guards</small><b>${p.guards}</b></div></div>
      <div class="cv-danger">${esc(p.danger)}</div>
      <div class="cv-foot"><button class="mini" data-cv-guard>Hire a guard</button><button class="mini" data-cv-back>Back</button>
        <button class="go" data-cv-go>Set out</button></div>`);
    el.querySelector("[data-cv-back]").onclick = () => open();
    el.querySelector("[data-cv-guard]").onclick = async () => {
      const h = await api.post("/api/act", {action: "hire_escort", args: {role: "Bodyguard", weapon: "Wooden Spear", count: 1}});
      UI.toast(h.ok ? h.message : `Can't: ${h.message}`, h.ok ? "milestone" : "bad");
      if (h.ok){ UI.refreshSoon(); setTimeout(() => choose(d), 400); }
    };
    el.querySelector("[data-cv-go]").onclick = () => setOut(d, r);
  }
  async function setOut(d, r){
    const res = await api.post("/api/trek", {op: "start", to: d.place, metres: r.len / SCALE});
    if (!res.ok){ UI.toast(res.message, "bad"); return; }
    closePanel();
    begin(res.trek, r, true);
  }

  /* ------------------------------------------------------------ the cinema */
  function bars(on){
    for (const id of ["lb-top", "lb-bot"]){
      let b = $(id);
      if (!b){ b = document.createElement("div"); b.id = id; b.className = "letterbox"; document.body.appendChild(b); }
      requestAnimationFrame(() => b.classList.toggle("on", on));
    }
    document.body.classList.toggle("cinema", on);
  }
  function card(title, sub, ms = 4200){
    let c = $("cv-card");
    if (!c){ c = document.createElement("div"); c.id = "cv-card"; document.body.appendChild(c); }
    c.innerHTML = `<h1>${esc(title)}</h1><p>${esc(sub)}</p>`;
    c.classList.remove("on"); void c.offsetWidth; c.classList.add("on");
    clearTimeout(card.t); card.t = setTimeout(() => c.classList.remove("on"), ms);
  }
  function hud(){
    let h = $("cv-hud");
    if (!h){
      h = document.createElement("div"); h.id = "cv-hud";
      h.innerHTML = `<span id="cv-where"></span><span id="cv-left"></span><button id="cv-mute" title="Music on or off">&#9835;</button><button id="cv-back">Turn back</button>`;
      document.body.appendChild(h);
      $("cv-mute").onclick = () => { MUSIC.mute(!MUSIC.muted); $("cv-mute").classList.toggle("off", MUSIC.muted); };
      $("cv-back").onclick = abort;
    }
    return h;
  }
  function begin(trek, r, fresh){
    C.trek = trek; C.route = r || C.route; C.sentAt = 0; C.begun = performance.now();
    if (ctx.enterThird) ctx.enterThird();
    bars(true); hud().style.display = "flex";
    drawRibbon(C.route);
    MUSIC.start();
    if (fresh){
      const goods = Object.entries(trek.cargo).filter(([, q]) => q > 0).map(([i, q]) => `${q} ${i}`).join(", ");
      card(`The road to ${short(trek.destination)}`, `${goods} · worth ${trek.value.toFixed(0)}`);
    }
    guards(trek.guards);
  }
  function end(text, good){
    if (!C.trek) return;
    C.trek = null; C.fightOn = false;
    dropRibbon(); guards(0);
    MUSIC.sting(good); MUSIC.stop();
    setTimeout(() => bars(false), 600);
    const h = $("cv-hud"); if (h) h.style.display = "none";
    if (text){
      const el = panel(`<h3>${good ? "Through" : "Back"} <button class="mini" data-cv-x>&times;</button></h3><div class="cv-result">${esc(text)}</div>
        <div class="cv-foot">${units() ? `<button class="mini" data-cv-sell>Sell here</button>` : ""}<button class="go" data-cv-x>Carry on</button></div>`);
      const sell = el.querySelector("[data-cv-sell]");
      if (sell) sell.onclick = () => { closePanel(); if (UI.openTab) UI.openTab("here"); };
    }
  }
  async function abort(){
    const r = await api.post("/api/trek", {op: "abort"});
    UI.toast(r.message || "You turn back.");
    end("", false);
  }

  /* Hired guards: riders a little behind you, one each side. */
  function guards(n){
    for (const g of C.guards) scene.remove(g.root);
    C.guards = [];
    if (!ctx.makePerson) return;
    for (let i = 0; i < Math.min(4, n); i++){
      const p = ctx.makePerson(i % 2 ? "drover" : "cowboy");
      const m = ctx.makeMount ? ctx.makeMount() : null;
      if (m){ scene.add(m); }
      scene.add(p.root);
      C.guards.push({root: p.root, p, m, side: i % 2 ? 1 : -1, back: 4 + Math.floor(i / 2) * 3});
    }
  }
  function moveGuards(dt){
    const P = S.player; if (!P || !C.guards.length) return;
    const h = P.heading || 0, fx = Math.sin(h), fz = Math.cos(h);
    for (const g of C.guards){
      const want = new THREE.Vector3(P.root.position.x - fx * g.back + fz * g.side * 2.2, 0, P.root.position.z - fz * g.back - fx * g.side * 2.2);
      const at = g.root.position, d = Math.hypot(want.x - at.x, want.z - at.z);
      const k = Math.min(1, dt * (d > 12 ? 6 : 2.5));
      at.x += (want.x - at.x) * k; at.z += (want.z - at.z) * k;
      const gy = groundAt(at.x, at.z);
      if (g.m){ g.m.position.set(at.x, gy, at.z); g.m.rotation.y = h; at.y = gy + 0.12; } else at.y = gy;
      g.root.rotation.y = h;
      if (ctx.setAnim){ ctx.setAnim(g.p, g.m ? "idle" : d > 0.4 ? "run" : "idle", 1); g.p.mixer.update(dt); }
    }
  }

  /* ------------------------------------------------------------ on the road */
  function limits(){
    const P = S.player;
    const out = {};
    const veh = S.ST && S.ST.vehicle || "";
    if (/Cart/.test(veh)) out.maxGait = 2;
    if (C.trek && P && distToRoads(P.root.position.x, P.root.position.z) > 7) out.maxGait = Math.min(out.maxGait ?? 4, 3);
    const f = Math.min(1, units() / Math.max(1, capacity()));
    out.speedMul = 1 - 0.3 * f;
    return out;
  }
  async function report(now){
    if (!C.trek || C.sending || now - C.sentAt < 1500) return;
    const P = S.player; if (!P || !C.route) return;
    C.sentAt = now; C.sending = true;
    const [s] = along(C.route, P.root.position);
    const left = Math.max(0, C.route.len - s) / SCALE;
    const l = $("cv-left"); if (l) l.textContent = `${left >= 1000 ? (left / 1000).toFixed(1) + " km" : Math.round(left) + " m"} to go`;
    const w = $("cv-where"); if (w) w.textContent = `The road to ${short(C.trek.destination)}`;
    try {
      const r = await api.post("/api/trek", {op: "progress", metres: s / SCALE});
      if (r.trek) C.trek = r.trek;
      if (r.trek && r.trek.status !== "on"){ end("", true); return; }
      if (r.fight && ctx.FIGHT()){
        const ahead = pointAt(C.route, s + 26), behind = pointAt(C.route, s - 40);
        ahead.y = groundAt(ahead.x, ahead.z); behind.y = groundAt(behind.x, behind.z);
        ctx.FIGHT().begin(r.fight, {ahead, behind});
        if (r.kind !== "riders" && ctx.stopMount) ctx.stopMount();
        C.fightOn = true;
        MUSIC.danger(1);
        card(r.kind === "riders" ? "Riders!" : r.fight.foes.some(f => f.settler) ? "Ambush!" : "Bandits!", r.message || "", 2600);
      }
    } finally { C.sending = false; }
  }
  function update(dt, now){
    if (!C.trek) return;
    report(now);
    moveGuards(dt);
    if (C.fightOn && !(ctx.FIGHT() && ctx.FIGHT().active)){ C.fightOn = false; MUSIC.danger(0); }
    const P = S.player;
    if (P && C.route){
      // The compass follows the road a little ahead of you.
      const [s] = along(C.route, P.root.position);
      S.waypoint = Object.assign(pointAt(C.route, s + 40), {label: short(C.trek.destination)});
    }
  }
  /* Arrived somewhere: the server's news (game.arrive's `convoy`). */
  function arrived(r){
    if (r && r.convoy){ S.waypoint = null; end(r.convoy, true); }
  }
  /* After a reload, or the status disagrees: pick the trek back up, or end it. */
  function sync(ST){
    const t = ST && ST.trek;
    if (t && t.status === "on" && !C.trek && S.player && S.places[t.destination]){
      begin(t, findRoute(S.player.root.position.clone(), S.places[t.destination].c.clone()), false);
    } else if (C.trek && (!t || t.status !== "on") && performance.now() - C.begun > 6000) end("", true);   // not a status sent before it began
  }
  /* Leaving a place carrying goods: offer the convoy once a visit. */
  function left(fromPlace){
    if (C.trek || !units() || C.prompted === fromPlace) return;
    C.prompted = fromPlace;
    open(`You're leaving ${short(fromPlace)} with goods. Goods go by convoy.`);
  }

  /* ------------------------------------------------------------ your load */
  let burlap = null;
  function burlapTex(){
    if (burlap) return burlap;
    const c = document.createElement("canvas"); c.width = c.height = 64;
    const g = c.getContext("2d"); g.fillStyle = "#b39466"; g.fillRect(0, 0, 64, 64);
    for (let i = 0; i < 64; i += 2){ g.fillStyle = `rgba(80,60,35,${0.12 + (i % 4) * 0.03})`; g.fillRect(i, 0, 1, 64); g.fillRect(0, i, 64, 1); }
    for (let i = 0; i < 300; i++){ g.fillStyle = `rgba(${150 + Math.random() * 60 | 0},${120 + Math.random() * 50 | 0},80,0.4)`; g.fillRect(Math.random() * 64, Math.random() * 64, 2, 1); }
    burlap = new THREE.CanvasTexture(c); burlap.wrapS = burlap.wrapT = THREE.RepeatWrapping; burlap.colorSpace = THREE.SRGBColorSpace;
    return burlap;
  }
  let sackGeo = null, sackMat = null, tieMat = null;
  function sack(size = 1){
    if (!sackGeo){
      const prof = [];
      for (let i = 0; i <= 10; i++){ const t = i / 10; prof.push(new THREE.Vector2(Math.sin(Math.PI * Math.min(1, t * 1.15)) * 0.32 * (t < 0.85 ? 1 : 0.4) + 0.02, t * 0.7)); }
      sackGeo = new THREE.LatheGeometry(prof, 10);
      sackMat = new THREE.MeshLambertMaterial({map: burlapTex()});
      tieMat = new THREE.MeshLambertMaterial({color: "#5b4127"});
    }
    const g = new THREE.Group();
    const body = new THREE.Mesh(sackGeo, sackMat); body.scale.set(1, 1, 0.8); g.add(body);
    const tie = new THREE.Mesh(new THREE.CylinderGeometry(0.06, 0.07, 0.1, 6), tieMat); tie.position.y = 0.62; g.add(tie);
    g.scale.setScalar(size);
    g.traverse(o => { if (o.isMesh) o.castShadow = true; });
    return g;
  }
  /* A two-wheeled cart behind the animal, with its load in the bed. */
  function cart(){
    const g = new THREE.Group(), wood = new THREE.MeshLambertMaterial({color: "#7a5c3c"}), dark = new THREE.MeshLambertMaterial({color: "#4b3624"});
    const bed = new THREE.Mesh(new THREE.BoxGeometry(1.5, 0.12, 2.0), wood); bed.position.y = 0.95; g.add(bed);
    for (const x of [-0.75, 0.75]){ const side = new THREE.Mesh(new THREE.BoxGeometry(0.08, 0.35, 2.0), wood); side.position.set(x, 1.15, 0); g.add(side); }
    const back = new THREE.Mesh(new THREE.BoxGeometry(1.5, 0.35, 0.08), wood); back.position.set(0, 1.15, -1.0); g.add(back);
    g.userData.wheels = [];
    for (const x of [-0.88, 0.88]){
      const w = new THREE.Group();
      const rim = new THREE.Mesh(new THREE.TorusGeometry(0.62, 0.06, 6, 16), dark); w.add(rim);
      for (let i = 0; i < 6; i++){ const sp = new THREE.Mesh(new THREE.BoxGeometry(0.05, 1.2, 0.05), dark); sp.rotation.z = i * Math.PI / 6; w.add(sp); }
      w.rotation.y = Math.PI / 2; w.position.set(x, 0.65, 0); g.add(w); g.userData.wheels.push(w);
    }
    for (const x of [-0.5, 0.5]){ const shaft = new THREE.Mesh(new THREE.BoxGeometry(0.07, 0.07, 2.2), wood); shaft.position.set(x, 1.0, 1.9); shaft.rotation.x = 0.12; g.add(shaft); }
    g.userData.load = new THREE.Group(); g.userData.load.position.y = 1.02; g.add(g.userData.load);
    g.traverse(o => { if (o.isMesh){ o.castShadow = true; o.receiveShadow = true; } });
    return g;
  }
  /* Sacks on the animal (or in its cart) for how full the load is. */
  function dress(animal, vehicle, frac, speed, dt){
    if (!animal) return;
    const U = animal.userData;
    const isCart = /Cart/.test(vehicle || "");
    if (isCart && !U.cart){ U.cart = cart(); U.cart.position.set(0, 0, -2.6); animal.add(U.cart); }
    if (!isCart && U.cart){ animal.remove(U.cart); U.cart = null; }
    if (U.cart && speed) for (const w of U.cart.userData.wheels) w.rotation.x += speed * dt / 0.62;
    const n = frac <= 0 ? 0 : isCart ? Math.max(1, Math.round(frac * 9)) : Math.max(1, Math.round(frac * 5));
    if (U.sackN === n && U.sackCart === isCart) return;
    U.sackN = n; U.sackCart = isCart;
    if (!U.sacks){ U.sacks = new THREE.Group(); }
    U.sacks.clear();
    if (isCart){
      U.cart.userData.load.add(U.sacks);
      for (let i = 0; i < n; i++){
        const s = sack(1.15); s.position.set(-0.4 + (i % 3) * 0.4, Math.floor(i / 6) * 0.45, -0.6 + Math.floor(i / 3) % 2 * 0.65 + (i >= 6 ? 0.3 : 0));
        s.rotation.set(0.3 * ((i % 2) - 0.5), i * 1.3, 0.25 * ((i % 3) - 1)); U.sacks.add(s);
      }
    } else {
      // Slung over the back, a pair at a time: left, right, then on top.
      if (!U.saddle){
        const box = new THREE.Box3().setFromObject(animal);
        const size = box.getSize(new THREE.Vector3()), s = animal.scale.x || 1;
        U.saddle = {y: (box.max.y - animal.position.y) / s * 0.66, w: Math.min(size.x, size.z) / s * 0.38};
      }
      (U.body || animal).add(U.sacks);
      const spots = [[-1, 0, 0], [1, 0, 0], [-1, -0.45, 0.1], [1, -0.45, 0.1], [0, 0.35, -0.2]];
      for (let i = 0; i < n; i++){
        const [side, z, up] = spots[i];
        const sk = sack(0.85); sk.position.set(side * U.saddle.w, U.saddle.y - 0.35 + up, z);
        sk.rotation.z = side * 0.35; if (!side){ sk.rotation.x = Math.PI / 2; } U.sacks.add(sk);
      }
    }
    if (U.packs) U.packs.visible = false;
  }
  /* On foot, a sack on your back. */
  function dressWalker(P, frac, ridingNow){
    if (!P) return;
    const on = frac > 0 && !ridingNow;
    if (on && !P.root.userData.backSack){ const s = sack(0.8); s.position.set(0, 0.95, -0.32); s.rotation.x = 0.25; P.root.add(s); P.root.userData.backSack = s; }
    if (P.root.userData.backSack) P.root.userData.backSack.visible = on;
  }

  /* ------------------------------------------------------------ the music */
  const MUSIC = createMusic();

  return {
    open, update, arrived, sync, left, limits, dress, dressWalker,
    get active(){ return !!C.trek; }, get trek(){ return C.trek; }, get route(){ return C.route; },
    load(){ return Math.min(1, units() / Math.max(1, capacity())); },
    skip(share){ if (C.route && S.player){ const p = pointAt(C.route, C.route.len * share); ctx.teleport(p.x, p.z); } },
    music: MUSIC,
  };
}

/* THE SCORE: a drum and a drone, and a lonely whistle over them, drawn with
   WebAudio so nothing has to be downloaded. `danger` speeds the drum and
   opens the drone when bandits come. A track at /audio/convoy.mp3 (and
   /audio/fight.mp3) is played instead if the server has one. */
function createMusic(){
  let ac = null, out = null, timer = null, beat = 0, next = 0, tempo = 72, level = 0, drone = null, filt = null;
  let track = null, fightTrack = null, files = null;
  const M = {muted: false};
  try { M.muted = localStorage.getItem("convoy.music") === "off"; } catch (e) {}
  const PENTA = [146.83, 174.61, 196.0, 220.0, 261.63, 293.66, 349.23, 392.0];   // D minor pentatonic
  async function probe(){
    if (files !== null) return files;
    files = {};
    try {
      const have = await (await fetch("/audio/list")).json();
      for (const n of ["convoy", "fight"]) if (have[n]) files[n] = `/audio/${n}.mp3`;
    } catch (e) {}
    return files;
  }
  function ctx(){
    if (!ac){
      ac = new (window.AudioContext || window.webkitAudioContext)();
      out = ac.createGain(); out.gain.value = 0;
      const comp = ac.createDynamicsCompressor(); out.connect(comp); comp.connect(ac.destination);
    }
    if (ac.state === "suspended") ac.resume();
    return ac;
  }
  function kick(t, loud){
    const o = ac.createOscillator(), g = ac.createGain();
    o.frequency.setValueAtTime(110, t); o.frequency.exponentialRampToValueAtTime(42, t + 0.18);
    g.gain.setValueAtTime(0.0001, t); g.gain.exponentialRampToValueAtTime(0.9 * loud, t + 0.01); g.gain.exponentialRampToValueAtTime(0.0001, t + 0.35);
    o.connect(g); g.connect(out); o.start(t); o.stop(t + 0.4);
  }
  function tak(t, loud){
    const n = ac.createBuffer(1, ac.sampleRate * 0.08, ac.sampleRate), d = n.getChannelData(0);
    for (let i = 0; i < d.length; i++) d[i] = (Math.random() * 2 - 1) * (1 - i / d.length) ** 3;
    const s = ac.createBufferSource(), bp = ac.createBiquadFilter(), g = ac.createGain();
    s.buffer = n; bp.type = "bandpass"; bp.frequency.value = 1800; bp.Q.value = 1.2; g.gain.value = 0.35 * loud;
    s.connect(bp); bp.connect(g); g.connect(out); s.start(t);
  }
  function whistle(t, f, len){
    const o = ac.createOscillator(), g = ac.createGain(), v = ac.createOscillator(), vg = ac.createGain();
    o.type = "triangle"; o.frequency.value = f * 2;
    v.frequency.value = 5.5; vg.gain.value = f * 0.012; v.connect(vg); vg.connect(o.frequency);
    g.gain.setValueAtTime(0.0001, t); g.gain.exponentialRampToValueAtTime(0.16, t + 0.12); g.gain.exponentialRampToValueAtTime(0.0001, t + len);
    const dl = ac.createDelay(), fb = ac.createGain(); dl.delayTime.value = 0.42; fb.gain.value = 0.32;
    o.connect(g); g.connect(out); g.connect(dl); dl.connect(fb); fb.connect(dl); dl.connect(out);
    o.start(t); v.start(t); o.stop(t + len + 0.1); v.stop(t + len + 0.1);
  }
  function startDrone(){
    filt = ac.createBiquadFilter(); filt.type = "lowpass"; filt.frequency.value = 380; filt.Q.value = 2;
    const g = ac.createGain(); g.gain.value = 0.12;
    drone = [73.42, 110.0, 73.42 * 1.004].map(f => { const o = ac.createOscillator(); o.type = "sawtooth"; o.frequency.value = f; o.connect(filt); o.start(); return o; });
    const lfo = ac.createOscillator(), lg = ac.createGain(); lfo.frequency.value = 0.07; lg.gain.value = 140; lfo.connect(lg); lg.connect(filt.frequency); lfo.start();
    drone.push(lfo);
    filt.connect(g); g.connect(out);
  }
  function schedule(){
    const t0 = ac.currentTime;
    while (next < t0 + 0.25){
      const spb = 60 / tempo, b = beat % 8;
      if (b === 0 || b === 3 || b === 4 || (level > 0.5 && b === 6)) kick(next, b === 0 ? 1 : 0.7);
      if (level > 0.3 && b % 2 === 1) tak(next, level);
      if (b === 0 && beat % 16 === 0 && Math.random() < 0.8){
        const notes = [PENTA[(Math.random() * 5) | 0], PENTA[(Math.random() * 8) | 0]];
        whistle(next + spb * 0.5, notes[0], spb * 2.2); whistle(next + spb * 3, notes[1], spb * 3.5);
      }
      next += spb / 2; beat++;
    }
  }
  M.start = async function(){
    if (M.muted) return;
    ctx();
    const f = await probe();
    if (f.convoy){
      if (!track){ track = new Audio(f.convoy); track.loop = true; track.volume = 0.6; }
      track.play().catch(() => {});
      return;
    }
    if (timer) return;
    out.gain.cancelScheduledValues(ac.currentTime); out.gain.setTargetAtTime(0.55, ac.currentTime, 1.2);
    startDrone(); next = ac.currentTime + 0.1; beat = 0;
    timer = setInterval(schedule, 90);
  };
  M.stop = function(){
    if (track) track.pause();
    if (fightTrack) fightTrack.pause();
    if (!ac || !timer) return;
    out.gain.setTargetAtTime(0, ac.currentTime, 0.8);
    const d = drone; clearInterval(timer); timer = null;
    setTimeout(() => { (d || []).forEach(o => { try { o.stop(); } catch (e) {} }); }, 3000);
    drone = null; M.danger(0);
  };
  M.danger = function(v){
    level = v; tempo = v > 0.5 ? 128 : 72;
    if (filt && ac) filt.frequency.setTargetAtTime(v > 0.5 ? 1400 : 380, ac.currentTime, 0.6);
    if (files && files.fight){
      if (!fightTrack){ fightTrack = new Audio(files.fight); fightTrack.loop = true; }
      if (v > 0.5 && !M.muted){ fightTrack.play().catch(() => {}); if (track) track.volume = 0.15; }
      else { fightTrack.pause(); if (track) track.volume = 0.6; }
    }
  };
  M.sting = function(good){
    if (M.muted || !ac) return;
    const t = ac.currentTime + 0.05, seq = good ? [0, 2, 4, 7] : [4, 3, 1, 0];
    seq.forEach((n, i) => whistle(t + i * 0.18, PENTA[n % 8] * (n >= 8 ? 2 : 1), good ? 0.9 : 1.2));
  };
  M.mute = function(on){
    M.muted = on;
    try { localStorage.setItem("convoy.music", on ? "off" : "on"); } catch (e) {}
    if (on) M.stop(); else M.start();
  };
  return M;
}
