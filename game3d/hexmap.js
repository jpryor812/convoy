/* THE MAP, HEX BY HEX (designer, 2026-11-01): "let's go back to map view,
   but still foggy and you have to move your character to find stuff ... move
   one space at a time, and each movement drains energy ... Also the
   characters on the 3D map should be big, like in civilization."

   The server keeps where you are, your energy and what you have found
   (convoy/journey.py; the status's `map`). This draws it and takes your
   orders:

     * the hexes you have found, outlined on the ground, and the fog over the
       rest (the ground veil, the minimap and the full map all read `known`);
     * the hex under the mouse, the way there and what it costs ("5 hexes ·
       6 energy · 50 min"), green while you can afford it, red past that;
     * a click to walk it (POST /api/journey move), hex by hex, ten game
       minutes a hex -- your unit walks it in time with the clock;
     * your explorers, out on the map with their names.

   Map metres <-> scene: toScene / toWorld (main.js). Hex arithmetic:
   hexes.js, the same as the server's. */

import * as HX from "./hexes.js";

export function createHexMap(ctx){
  const {THREE, scene, S, api, UI, toScene, toWorld, groundAt, makePerson, setAnim, CSS2DObject} = ctx;
  const M = {known: new Set(), sig: "", grid: null, gridSig: "", preview: null, hoverKey: "", picking: null, scouts: new Map()};

  const map = () => S.ST && S.ST.map;
  const hexScene = h => { const [x, y] = HX.centre(h); return toScene(x, y); };
  const hexOf = v => { const w = toWorld(v); return HX.toHex(w.x, w.y); };
  const cornersScene = (() => {
    const cache = new Map();
    return k => {
      if (!cache.has(k)) cache.set(k, HX.corners(HX.parse(k)).map(([x, y]) => toScene(x, y)));
      return cache.get(k);
    };
  })();

  /* What you have found, from the status. Returns true when it changed. */
  function sync(){
    const m = map(); if (!m) return false;
    const sig = `${m.explored.length}`;
    if (sig === M.sig) return false;
    M.sig = sig; M.known = new Set(m.explored);
    return true;
  }
  const knownAt = (x, z) => M.known.has(HX.key(hexOf(new THREE.Vector3(x, 0, z))));
  const knownPlace = c => M.known.has(HX.key(hexOf(c)));

  /* The fog, painted: `px(x, z)` maps scene to the canvas. Found hexes are
     cut out of whatever is on `c` (destination-out), softly. */
  function cutHexes(c, px, blur = 0){
    c.save();
    c.globalCompositeOperation = "destination-out";
    if (blur) c.filter = `blur(${blur}px)`;
    c.fillStyle = "#000";
    c.beginPath();
    for (const k of M.known){
      const pts = cornersScene(k);
      pts.forEach((v, i) => { const [x, y] = px(v.x, v.z); i ? c.lineTo(x, y) : c.moveTo(x, y); });
      c.closePath();
    }
    c.fill();
    c.restore();
  }

  /* The found hexes, outlined on the ground: in the map view only. */
  function drawGrid(){
    const sig = M.sig;
    if (sig === M.gridSig) return;
    M.gridSig = sig;
    if (M.grid){ scene.remove(M.grid); M.grid.geometry.dispose(); }
    const pos = [], seen = new Set();
    for (const k of M.known){
      const pts = cornersScene(k);
      for (let i = 0; i < 6; i++){
        const a = pts[i], b = pts[(i + 1) % 6];
        const ek = [Math.round(a.x * 2 + b.x * 2), Math.round(a.z * 2 + b.z * 2)].join(",");
        if (seen.has(ek)) continue; seen.add(ek);
        const n = 4;
        for (let j = 0; j < n; j++){
          const p = a.clone().lerp(b, j / n), q = a.clone().lerp(b, (j + 1) / n);
          pos.push(p.x, groundAt(p.x, p.z) + 0.35, p.z, q.x, groundAt(q.x, q.z) + 0.35, q.z);
        }
      }
    }
    const g = new THREE.BufferGeometry(); g.setAttribute("position", new THREE.Float32BufferAttribute(pos, 3));
    M.grid = new THREE.LineSegments(g, new THREE.LineBasicMaterial({color: "#fff6dc", transparent: true, opacity: 0.22, depthWrite: false}));
    M.grid.raycast = () => {}; M.grid.renderOrder = 3;
    scene.add(M.grid);
  }

  /* ------------------------------------------------------------ the way */
  function costOf(h){
    const m = map(); const t = m && m.terrain[HX.key(h)];
    return t === "w" || t === "e" ? null : t === "m" ? 2 : 1;
  }
  function from(){
    const m = map(); if (!m || !m.hex) return null;
    return m.moving ? m.moving.to : m.hex;
  }
  function plan(to){
    const a = from(); if (!a) return null;
    const p = HX.path(a, to, costOf, 3000);
    if (!p) return null;
    let spent = 0;
    const steps = p.map(h => { spent += costOf(h) || 1; return {h, spent}; });
    return {path: p, steps, cost: spent};
  }
  function ensurePreview(){
    if (M.preview) return M.preview;
    const g = new THREE.Group(); g.renderOrder = 4;
    const disc = new THREE.CircleGeometry(3.2, 20); disc.rotateX(-Math.PI / 2);
    const hexGeo = new THREE.CircleGeometry(HX.R * ctx.SCALE * 0.96, 6); hexGeo.rotateX(-Math.PI / 2); hexGeo.rotateY(Math.PI / 6);
    g.userData.disc = disc;
    g.userData.ok = new THREE.MeshBasicMaterial({color: "#8ee06a", transparent: true, opacity: 0.85, depthWrite: false, fog: false});
    g.userData.bad = new THREE.MeshBasicMaterial({color: "#ff6a4a", transparent: true, opacity: 0.85, depthWrite: false, fog: false});
    g.userData.pool = [];
    const cursor = new THREE.Mesh(hexGeo, new THREE.MeshBasicMaterial({color: "#ffd23f", transparent: true, opacity: 0.18, depthWrite: false, fog: false}));
    cursor.raycast = () => {}; g.add(cursor); g.userData.cursor = cursor;
    scene.add(g); M.preview = g;
    return g;
  }
  function showPath(pl, energy){
    const g = ensurePreview(), pool = g.userData.pool;
    let i = 0;
    for (const s of (pl ? pl.steps : [])){
      let d = pool[i];
      if (!d){ d = new THREE.Mesh(g.userData.disc, g.userData.ok); d.raycast = () => {}; g.add(d); pool.push(d); }
      const v = hexScene(s.h);
      d.position.set(v.x, groundAt(v.x, v.z) + 0.6, v.z);
      d.material = s.spent <= energy ? g.userData.ok : g.userData.bad;
      d.visible = true; i++;
    }
    for (; i < pool.length; i++) pool[i].visible = false;
  }
  /* The mouse over the ground in the map view: `point` in the scene, or null. */
  function hover(point, tip, ev){
    const g = ensurePreview(), m = map();
    if (!point || !m || !m.hex){ g.visible = false; return false; }
    g.visible = true;
    const h = hexOf(point), k = HX.key(h);
    const c = hexScene(h);
    g.userData.cursor.position.set(c.x, groundAt(c.x, c.z) + 0.4, c.z);
    if (k === M.hoverKey && M.lastPlan !== undefined){ placeTip(tip, ev); return true; }
    M.hoverKey = k;
    if (M.picking){
      showPath(null, 0);
      tip.innerHTML = `Send ${M.picking.label} here`;
      placeTip(tip, ev); M.lastPlan = null;
      return true;
    }
    const pl = HX.key(h) === HX.key(from()) ? null : plan(h);
    M.lastPlan = pl;
    showPath(pl, m.energy);
    if (!pl){ tip.innerHTML = HX.key(h) === HX.key(from()) ? "You are here" : "No way there"; placeTip(tip, ev); return true; }
    const mins = pl.path.length * 10;
    const over = pl.cost > m.energy;
    tip.innerHTML = `<b>${pl.path.length} hex${pl.path.length > 1 ? "es" : ""}</b> · ${pl.cost} energy · ${mins >= 60 ? (mins / 60).toFixed(1) + " h" : mins + " min"}`
      + (over ? `<br><span style="color:#c93322">You have ${m.energy.toFixed(0)}: you will stop when spent</span>` : "")
      + (!M.known.has(k) ? `<br><small>Unexplored</small>` : "");
    placeTip(tip, ev);
    return true;
  }
  function placeTip(tip, ev){
    if (!ev) return;
    tip.style.display = "block"; tip.style.left = `${ev.clientX + 14}px`; tip.style.top = `${ev.clientY + 12}px`;
  }
  function hideHover(){ if (M.preview) M.preview.visible = false; M.hoverKey = ""; M.lastPlan = undefined; }

  /* A click on open ground in the map view: walk there, or (choosing for an
     explorer) send them there. */
  async function click(point){
    const m = map(); if (!m || !point) return false;
    const h = hexOf(point);
    if (M.picking){
      const p = M.picking; M.picking = null;
      document.body.classList.remove("picking");
      const r = await api.post("/api/journey", {...p.body, target: h});
      UI.toast(r.message || "", r.ok ? "milestone" : "bad");
      UI.refreshSoon();
      return true;
    }
    const pl = plan(h);
    if (!pl || !pl.path.length) return false;
    const r = await api.post("/api/journey", {op: "move", path: pl.path});
    if (!r.ok) UI.toast(r.message, "bad");
    if (r.map) S.ST.map = r.map;
    M.hoverKey = "";
    UI.refreshSoon();
    return true;
  }
  /* Choosing a spot for an explorer: the next click on the map is it. */
  function pick(label, body){
    M.picking = {label, body};
    document.body.classList.add("picking");
    UI.toast(`Click a spot on the map to send ${label}.`);
  }

  /* ------------------------------------------------------------ your unit */
  /* Where your unit stands now: on its hex, or partway across the step under
     way, in time with the clock (`simNow` in game seconds). */
  function unitAt(simNow){
    const m = map(); if (!m || !m.hex) return null;
    if (m.moving){
      const t = Math.max(0, Math.min(1, (simNow - m.moving.starts) / Math.max(1, m.moving.ends - m.moving.starts)));
      const a = hexScene(m.moving.from || m.hex), b = hexScene(m.moving.to);
      return {pos: a.lerp(b, t), moving: true, heading: Math.atan2(b.x - a.x, b.z - a.z)};
    }
    return {pos: hexScene(m.hex), moving: false};
  }

  /* A camp while you rest out there: a canvas tent and a small fire beside
     your unit, gone when you wake. */
  let tent = null;
  function camp(pos, scale){
    const m = map(), on = !!(m && m.resting && m.resting.where === "camp" && pos);
    if (on && !tent){
      tent = new THREE.Group();
      const cloth = new THREE.Mesh(new THREE.ConeGeometry(1.5, 1.9, 4, 1, true), new THREE.MeshLambertMaterial({color: "#cbb48a", side: THREE.DoubleSide}));
      cloth.position.y = 0.95; cloth.rotation.y = Math.PI / 4; cloth.castShadow = true; tent.add(cloth);
      const fire = new THREE.Mesh(new THREE.SphereGeometry(0.28, 8, 6), new THREE.MeshBasicMaterial({color: "#ff9a3c"}));
      fire.position.set(2.1, 0.25, 0.4); tent.add(fire);
      const glow = new THREE.PointLight("#ff9a3c", 2.5, 9); glow.position.set(2.1, 0.8, 0.4); tent.add(glow);
      tent.userData.fire = fire;
      scene.add(tent);
    }
    if (!tent) return;
    tent.visible = on;
    if (on){
      tent.position.set(pos.x - 3 * scale, groundAt(pos.x - 3 * scale, pos.z), pos.z);
      tent.scale.setScalar(scale);
      tent.userData.fire.scale.setScalar(0.85 + 0.3 * Math.random());
    }
  }

  /* Explorers: family out on the map (main.js draws them, at `familyAt`),
     and hired scouts drawn here. */
  function familyAt(memberId){
    const m = map(); const e = m && m.explorers.find(x => x.member === memberId);
    return e ? hexScene(e.hex) : null;
  }
  function updateScouts(dt, scale){
    const m = map(); const list = (m && m.explorers || []).filter(e => e.kind === "hired");
    const live = new Set(list.map(e => e.id));
    for (const [id, v] of M.scouts) if (!live.has(id)){ scene.remove(v.root); v.el.remove(); M.scouts.delete(id); }
    for (const e of list){
      let v = M.scouts.get(e.id);
      if (!v){
        v = makePerson("drover");
        const el = document.createElement("div"); el.className = "lbl-fam"; v.el = el;
        const lbl = new CSS2DObject(el); lbl.position.set(0, 2.7, 0); v.root.add(lbl);
        v.root.position.copy(hexScene(e.hex)); scene.add(v.root); M.scouts.set(e.id, v);
      }
      v.el.innerHTML = `<span class="fam-ic">\u{1F9ED}</span><span><b>${e.name}</b><small>${e.status === "camp" ? "camping" : "scouting"} · ${e.found} found</small></span>`;
      const want = hexScene(e.hex), d = want.distanceTo(v.root.position);
      if (d > 0.3){ v.root.position.lerp(want, Math.min(1, dt * 1.5)); v.root.rotation.y = Math.atan2(want.x - v.root.position.x, want.z - v.root.position.z); }
      v.root.position.y = groundAt(v.root.position.x, v.root.position.z);
      v.root.scale.setScalar(scale);
      setAnim(v, d > 0.5 ? "walk" : "idle"); v.mixer.update(dt);
    }
  }

  return {sync, knownAt, knownPlace, cutHexes, drawGrid, hover, hideHover, click, pick, unitAt, familyAt, updateScouts, camp,
          hexOf, hexScene, get grid(){ return M.grid; }, get picking(){ return !!M.picking; }, get known(){ return M.known; }};
}
