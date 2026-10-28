/* The town, alive: everything that makes a business something you can SEE
   working rather than a row in a menu.

   Designer direction, 2026-10-17: "it needs to be more like FarmVille in terms
   of visibility into your businesses and the time you have left to produce" --
   and to feel the competition around your resources. So every building shows
   its state without being clicked:

     timers      a ring over every worked building filling toward the next unit
     pops        "+1 Wheat" when a unit lands (yours always; others close by)
     stockpiles  sacks, barrels, logs, ore and crates piling up in the yard as
                 stock grows -- a full yard is visible from across the valley
     crops       fields that grow and are harvested; a pond, a few cows; an ore
                 cart rolling at the mine; smoke from chimneys while working
     bubbles     a "!" over any business of yours that needs you
     banners     every owner's colour on a flag by their buildings
     callouts    a rival moving against you is pointed out on the map
     holdings    one card per business of yours along the bottom: timer, stock,
                 state; click to fly there

   Data: `/api/production` (progress and rate, read with the engine's own
   functions), `/cards` (stock and prices), and the advisor's markers. */

export function createLife(ctx){
  const {THREE, scene, S, camera, CSS2DObject, G, api, BUILDING_W, openBuilding, flyTo, focusPoint, isStrategy, viewDist, short} = ctx;
  const $ = id => document.getElementById(id);
  const esc = s => String(s == null ? "" : s).replace(/[&<>"']/g, ch => ({"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"}[ch]));
  let CARDS = {}, PROD = null;
  const state = new Map();                  // building id -> what is drawn around it
  const puffs = [];

  /* ---------------------------------------------------------- data */
  async function pollCards(){
    try { CARDS = (await api.get("/cards")).cards || {}; } catch (e) { /* next time */ }
  }
  setInterval(pollCards, 4000);
  pollCards();
  function setProduction(p){ PROD = p; }

  /* ---------------------------------------------------------- owners' colours */
  const hue = id => { let h = 0; for (const c of String(id)) h = (h * 31 + c.charCodeAt(0)) % 360; return h; };
  function ownerColour(id){
    // Muted, like dyed cloth (2026-10-19): yours brass, others earthy.
    if (id === G.you) return new THREE.Color("#b8913f");
    return new THREE.Color().setHSL(hue(id) / 360, 0.34, 0.42);
  }
  const cssColour = id => `#${ownerColour(id).getHexString()}`;

  /* ---------------------------------------------------------- shared materials */
  const mat = c => new THREE.MeshLambertMaterial({color: c});
  const M = {
    wood: mat("#8a5a32"), sack: mat("#e3c463"), sack2: mat("#d4a94a"), water: mat("#5d9fd6"), water2: mat("#8fd0f0"),
    rim: mat("#5a3a1e"), log: mat("#9b6a3b"), stone: mat("#a9a59a"), brick: mat("#c4704a"), copper: mat("#c07b3e"),
    tin: mat("#b9bcc2"), iron: mat("#76665c"), char: mat("#2e2b29"), hide: mat("#c9a47a"), crate: mat("#b98a55"),
    red: mat("#c0443a"), ingot: new THREE.MeshPhongMaterial({color: "#d9a441", shininess: 90}),
    ingotI: new THREE.MeshPhongMaterial({color: "#9aa3ad", shininess: 90}), cow: mat("#f2efe8"), cowSpot: mat("#3a2e2a"),
    pond: new THREE.MeshPhongMaterial({color: "#4f9ed8", shininess: 100, specular: "#e0f2ff"}),
  };
  const G3 = {
    sack: new THREE.SphereGeometry(0.42, 10, 8), barrel: new THREE.CylinderGeometry(0.38, 0.38, 0.85, 12),
    log: new THREE.CylinderGeometry(0.2, 0.2, 1.4, 8), block: new THREE.BoxGeometry(0.6, 0.45, 0.6),
    ore: new THREE.DodecahedronGeometry(0.36, 0), ingot: new THREE.BoxGeometry(0.7, 0.18, 0.32),
    crate: new THREE.BoxGeometry(0.7, 0.6, 0.7), hide: new THREE.BoxGeometry(0.8, 0.12, 0.6),
    sprout: new THREE.ConeGeometry(0.34, 1, 6),
  };
  G3.sprout.translate(0, 0.5, 0);
  function stockLook(item){
    const i = item.toLowerCase();
    if (i === "wheat") return ["sack", M.sack];
    if (i === "grain") return ["sack", M.sack2];
    if (i.includes("water")) return ["barrel", i.startsWith("pur") ? M.water2 : M.water];
    if (i.includes("wood") || i === "lumber") return ["log", M.log];
    if (i === "charcoal") return ["ore", M.char];
    if (i.includes("copper")) return ["ore", M.copper];
    if (i.includes("tin")) return ["ore", M.tin];
    if (i === "iron ore") return ["ore", M.iron];
    if (i === "bronze") return ["ingot", M.ingot];
    if (i === "iron") return ["ingot", M.ingotI];
    if (i.includes("stone")) return ["block", M.stone];
    if (i.includes("clay") || i.includes("brick")) return ["block", M.brick];
    if (i.includes("hide") || i.includes("leather")) return ["hide", M.hide];
    if (i.includes("meal") || i.includes("bread")) return ["crate", M.red];
    return ["crate", M.crate];
  }

  /* ---------------------------------------------------------- per building */
  function stateFor(v){
    let st = state.get(v.b.id);
    if (st) return st;
    st = {id: v.b.id, yard: new THREE.Group(), stockKey: "", extras: new THREE.Group(), smokeAt: 0,
          lastFrac: null, popAcc: 0, popAt: 0, kind: v.b.type};
    const pick = {kind: "building", id: v.b.id};
    st.yard.position.set(BUILDING_W * 0.78, 0, BUILDING_W * 0.62);
    v.root.add(st.yard, st.extras);
    // A banner in the owner's colour, at the corner.
    const pole = new THREE.Mesh(new THREE.CylinderGeometry(0.12, 0.12, 8, 6), M.wood);
    pole.position.set(-BUILDING_W * 0.48, 4, BUILDING_W * 0.42);
    const flag = new THREE.Mesh(new THREE.PlaneGeometry(3, 1.8), new THREE.MeshLambertMaterial({color: ownerColour(v.b.owner), side: THREE.DoubleSide}));
    flag.geometry.translate(1.5, 0, 0);
    flag.position.set(-BUILDING_W * 0.48, 7, BUILDING_W * 0.42);
    st.flag = flag;
    st.extras.add(pole, flag);
    // Per kind: fields, a pond, cows, an ore cart.
    if (v.b.type === "Farm"){
      const field = new THREE.InstancedMesh(G3.sprout, new THREE.MeshLambertMaterial({color: "#7fb347", flatShading: true}), 48);
      const m4 = new THREE.Matrix4();
      let n = 0;
      for (let r = 0; r < 6; r++) for (let c = 0; c < 8; c++){
        m4.makeTranslation(-BUILDING_W * 0.95 + c * 1.05, 0, -3 + r * 1.2); field.setMatrixAt(n++, m4);
      }
      const soil = new THREE.Mesh(new THREE.PlaneGeometry(9, 7.6), mat("#7a5a36"));
      soil.rotation.x = -Math.PI / 2; soil.position.set(-BUILDING_W * 0.95 + 3.7, 0.06, 0);
      st.field = field; st.fieldBase = [];
      for (let i = 0; i < 48; i++){ const t = new THREE.Matrix4(); field.getMatrixAt(i, t); st.fieldBase.push(t); }
      const pond = new THREE.Mesh(new THREE.CircleGeometry(2.2, 24), M.pond);
      pond.rotation.x = -Math.PI / 2; pond.position.set(-BUILDING_W * 0.6, 0.08, BUILDING_W * 0.75);
      st.pond = pond;
      const cows = new THREE.Group();
      for (let i = 0; i < 2; i++){
        const cow = new THREE.Group();
        const body = new THREE.Mesh(new THREE.BoxGeometry(1.3, 0.7, 0.6), M.cow); body.position.y = 0.75;
        const head = new THREE.Mesh(new THREE.BoxGeometry(0.4, 0.4, 0.4), M.cow); head.position.set(0.8, 0.95, 0);
        const spot = new THREE.Mesh(new THREE.BoxGeometry(0.5, 0.5, 0.62), M.cowSpot); spot.position.set(-0.1, 0.85, 0);
        for (const [lx, lz] of [[-0.45, -0.2], [0.45, -0.2], [-0.45, 0.2], [0.45, 0.2]]){
          const leg = new THREE.Mesh(new THREE.BoxGeometry(0.14, 0.5, 0.14), M.cow); leg.position.set(lx, 0.25, lz); cow.add(leg);
        }
        cow.add(body, head, spot);
        cow.position.set(BUILDING_W * 0.1 + i * 2.2, 0, -BUILDING_W * 0.75 - i);
        cows.add(cow);
      }
      st.cows = cows;
      st.extras.add(field, soil, pond, cows);
    }
    if (v.b.type === "Mining Operation"){
      const cart = new THREE.Group();
      const tub = new THREE.Mesh(new THREE.BoxGeometry(1.4, 0.7, 0.9), M.wood); tub.position.y = 0.7;
      const ore = new THREE.Mesh(new THREE.DodecahedronGeometry(0.45, 0), M.iron); ore.position.y = 1.15;
      cart.add(tub, ore);
      for (const [wx, wz] of [[-0.5, -0.5], [0.5, -0.5], [-0.5, 0.5], [0.5, 0.5]]){
        const w = new THREE.Mesh(new THREE.CylinderGeometry(0.25, 0.25, 0.12, 10), M.rim);
        w.rotation.x = Math.PI / 2; w.position.set(wx, 0.25, wz); cart.add(w);
      }
      const rail = new THREE.Mesh(new THREE.BoxGeometry(10, 0.08, 1.1), M.rim); rail.position.set(-BUILDING_W * 0.1, 0.05, BUILDING_W * 0.62);
      cart.position.set(-BUILDING_W * 0.1, 0, BUILDING_W * 0.62);
      st.cart = cart; st.cartOre = ore;
      st.extras.add(rail, cart);
    }
    st.extras.traverse(o => { o.userData.pick = pick; });
    // The timer over the building, and the "!" bubble.
    const tEl = document.createElement("div"); tEl.className = "btimer";
    tEl.innerHTML = `<svg viewBox="0 0 24 24"><circle class="bg" cx="12" cy="12" r="9.5" fill="none" stroke-width="3.5"/><circle class="fg" cx="12" cy="12" r="9.5" fill="none" stroke-width="3.5" stroke-dasharray="${RING}" stroke-dashoffset="${RING}"/></svg><span></span>`;
    st.timer = new CSS2DObject(tEl); st.timer.position.set(0, 12.5, 0); st.timer.visible = false;
    const bEl = document.createElement("div"); bEl.className = "bubble"; bEl.textContent = "!";
    bEl.addEventListener("pointerdown", e => e.stopPropagation());
    bEl.addEventListener("click", e => { e.stopPropagation(); openBuilding(v.b.id); });
    st.bubble = new CSS2DObject(bEl); st.bubble.position.set(0, 16.5, 0); st.bubble.visible = false;
    v.root.add(st.timer, st.bubble);
    state.set(v.b.id, st);
    return st;
  }
  const RING = 2 * Math.PI * 9.5;

  /* RICH GROUND, SHOWN. Once a farm's or mine's first harvest has revealed
     its land (see convoy/land.py), the land fills in around it: more wells,
     more cows, a second field of wheat, heaps of ore in the metal's colour --
     more of them the richer it is. Nothing shows before. */
  const ORE = {"Copper Ore": "#c8743a", "Tin Ore": "#c3c7cf", "Iron Ore": "#7a5246", "Stone": "#a9a59a", "Clay": "#b5653a"};
  function buildGround(st, v, land){
    const key = land ? `${land.item}:${land.pct}` : "";
    if (key === st.groundKey) return;
    st.groundKey = key;
    if (st.ground){ v.root.remove(st.ground); }
    st.ground = new THREE.Group();
    v.root.add(st.ground);
    if (!land || !land.item) return;
    const n = 1 + Math.round(land.pct * 100 / 5);           // 5% -> 2 ... 25% -> 6
    const spot = i => {                                       // around the back and sides
      const a = Math.PI * (0.55 + 0.9 * i / Math.max(1, n - 1)) + (st.id.charCodeAt(3) % 7) * 0.05;
      const r = BUILDING_W * (0.95 + 0.25 * (i % 2));
      return [Math.cos(a) * r, -Math.abs(Math.sin(a)) * r * 0.9 - 2];
    };
    for (let i = 0; i < n; i++){
      const [x, z] = spot(i);
      let thing;
      if (land.item === "Dirty Water"){
        thing = new THREE.Group();
        const ring = new THREE.Mesh(new THREE.CylinderGeometry(1.1, 1.2, 0.9, 12), M.stone); ring.position.y = 0.45;
        const water = new THREE.Mesh(new THREE.CircleGeometry(0.95, 12), M.water); water.rotation.x = -Math.PI / 2; water.position.y = 0.91;
        const roof = new THREE.Mesh(new THREE.ConeGeometry(1.5, 0.9, 4), mat("#b5482f")); roof.position.y = 2.5; roof.rotation.y = Math.PI / 4;
        const post = new THREE.Mesh(new THREE.BoxGeometry(0.14, 2.1, 0.14), M.wood); post.position.set(1, 1.05, 0);
        const post2 = post.clone(); post2.position.x = -1;
        thing.add(ring, water, roof, post, post2);
      } else if (land.item === "Hide"){
        thing = new THREE.Group();
        const body = new THREE.Mesh(new THREE.BoxGeometry(1.3, 0.7, 0.6), i % 2 ? M.cowSpot : M.cow); body.position.y = 0.75;
        const head = new THREE.Mesh(new THREE.BoxGeometry(0.4, 0.4, 0.4), M.cow); head.position.set(0.8, 0.95, 0);
        thing.add(body, head);
        for (const [lx, lz] of [[-0.45, -0.2], [0.45, -0.2], [-0.45, 0.2], [0.45, 0.2]]){
          const leg = new THREE.Mesh(new THREE.BoxGeometry(0.14, 0.5, 0.14), M.cow); leg.position.set(lx, 0.25, lz); thing.add(leg);
        }
        thing.userData.grazes = true;
      } else if (land.item === "Wheat"){
        thing = new THREE.Group();
        for (let r = 0; r < 3; r++) for (let c = 0; c < 3; c++){
          const s = new THREE.Mesh(G3.sprout, mat("#e3c463")); s.scale.y = 1.6; s.position.set(c * 0.9 - 0.9, 0, r * 0.9 - 0.9); thing.add(s);
        }
      } else if (land.item === "Wood"){
        thing = new THREE.Group();
        for (let k = 0; k < 3; k++){
          const log = new THREE.Mesh(G3.log, M.log); log.rotation.z = Math.PI / 2; log.position.set(0, 0.2 + k * 0.38, (k % 2) * 0.2); thing.add(log);
        }
        const stump = new THREE.Mesh(new THREE.CylinderGeometry(0.45, 0.55, 0.6, 9), M.log); stump.position.set(1.3, 0.3, 0.4); thing.add(stump);
      } else {
        thing = new THREE.Group();
        const colour = ORE[land.item] || "#888";
        const m = new THREE.MeshPhongMaterial({color: colour, shininess: land.item.includes("Ore") ? 70 : 10, flatShading: true});
        for (let k = 0; k < 4; k++){
          const rock = new THREE.Mesh(new THREE.DodecahedronGeometry(0.5 + (k % 2) * 0.25, 0), m);
          rock.position.set((k % 2) * 0.8 - 0.4, 0.35 + Math.floor(k / 2) * 0.45, (k > 1 ? 0.3 : -0.3));
          rock.rotation.set(k, k * 1.7, 0); thing.add(rock);
        }
      }
      thing.position.set(x, 0, z);
      thing.traverse(o => { o.userData.pick = {kind: "building", id: st.id}; });
      st.ground.add(thing);
    }
  }

  function rebuildYard(st, card){
    const stock = (card && card.stock || []).filter(s => s.qty > 0).sort((a, b) => b.qty - a.qty).slice(0, 4);
    const key = stock.map(s => `${s.item}:${Math.ceil(s.qty / 6)}`).join("|");
    if (key === st.stockKey) return;
    st.stockKey = key;
    st.yard.clear();
    stock.forEach((s, row) => {
      const [shape, m] = stockLook(s.item);
      const n = Math.min(12, Math.ceil(s.qty / 6));
      for (let i = 0; i < n; i++){
        const mesh = new THREE.Mesh(G3[shape], m);
        const col = i % 4, layer = Math.floor(i / 4);
        mesh.position.set(col * 0.85, 0.3 + layer * 0.55, row * 1.0);
        if (shape === "log"){ mesh.rotation.z = Math.PI / 2; mesh.position.y = 0.2 + layer * 0.4; }
        if (shape === "barrel") mesh.position.y = 0.43 + layer * 0.86;
        if (shape === "ore"){ mesh.rotation.set(i, i * 2, 0); }
        mesh.userData.pick = {kind: "building", id: st.id};
        st.yard.add(mesh);
      }
    });
  }

  /* ---------------------------------------------------------- smoke */
  const puffTex = (() => {
    const c = document.createElement("canvas"); c.width = c.height = 64;
    const g = c.getContext("2d"), grd = g.createRadialGradient(32, 32, 4, 32, 32, 32);
    grd.addColorStop(0, "rgba(255,255,255,0.9)"); grd.addColorStop(1, "rgba(255,255,255,0)");
    g.fillStyle = grd; g.fillRect(0, 0, 64, 64);
    const t = new THREE.CanvasTexture(c); t.colorSpace = THREE.SRGBColorSpace; return t;
  })();
  function puff(at, dark){
    const s = new THREE.Sprite(new THREE.SpriteMaterial({map: puffTex, color: dark ? "#8a8580" : "#f4f1ea", transparent: true, depthWrite: false, opacity: 0.8}));
    s.position.copy(at); s.scale.setScalar(1.2);
    s.userData = {age: 0, life: 3 + Math.random(), drift: new THREE.Vector3((Math.random() - 0.5) * 0.4, 1.3, (Math.random() - 0.5) * 0.4)};
    scene.add(s); puffs.push(s);
  }
  const SMOKES = {"Tavern / Inn": false, "Refinery": true, "Weaponsmith / Armory": true, "Mining Operation": true};

  /* ---------------------------------------------------------- pops */
  function pop(v, text, mine){
    const el = document.createElement("div"); el.className = "pop" + (mine ? " mine" : "");
    el.textContent = text;
    const o = new CSS2DObject(el); o.position.set(0, 10, 0);
    v.root.add(o);
    setTimeout(() => { v.root.remove(o); el.remove(); }, 1700);
  }

  /* ---------------------------------------------------------- callouts */
  function callout(id, text){
    const v = S.buildings.get(id); if (!v) return;
    const el = document.createElement("div"); el.className = "callout"; el.textContent = text;
    const o = new CSS2DObject(el); o.position.set(0, 15, 0);
    v.root.add(o);
    setTimeout(() => { v.root.remove(o); el.remove(); }, 25000);
  }

  /* ---------------------------------------------------------- every frame */
  let t0 = performance.now(), holdAt = 0;
  function update(dt){
    const now = performance.now(), t = (now - t0) / 1000;
    const pace = S.ST && !S.ST.paused ? S.ST.pace : 0;
    const fp = focusPoint(), strat = isStrategy(), vd = viewDist();
    const marks = (S.ADV && S.ADV.markers) || {};
    for (const [id, st] of state) if (!S.buildings.has(id)) state.delete(id);
    for (const v of S.buildings.values()){
      const st = stateFor(v);
      // Someone you have not found (outposts): nothing of theirs shows.
      if (!v.root.visible){ st.timer.visible = st.bubble.visible = false; continue; }
      const mine = v.b.owner === G.you;
      const d = Math.hypot(fp.x - v.pos.x, fp.z - v.pos.z);
      const inView = d < (strat ? Math.max(160, vd * 2.2) : 140);
      st.flag.rotation.y = Math.sin(t * 1.4 + v.pos.x) * 0.18;
      rebuildYard(st, CARDS[v.b.id]);
      buildGround(st, v, (CARDS[v.b.id] || {}).land);
      if (st.ground) st.ground.children.forEach((c, i) => {
        if (c.userData.grazes){ c.rotation.y = Math.sin(t * 0.25 + i * 1.7) * 1.4; }
      });
      const p = PROD && PROD.businesses[v.b.id];
      let frac = 0, working = false;
      if (p && !p.blocked){
        working = true;
        frac = (p.progress + p.per_hour * Math.max(0, S.HOUR - PROD.hour)) % 1;
      }
      // Fields grow over ten units and are harvested; the pond ripples; cows graze.
      if (st.field){
        const item = p ? p.item : (CARDS[v.b.id] || {}).producing;
        const grow = item === "Wheat" && p ? ((p.progress + p.per_hour * Math.max(0, S.HOUR - PROD.hour)) / 10) % 1 : 0.15;
        const m4 = new THREE.Matrix4(), sc = new THREE.Matrix4();
        for (let i = 0; i < 48; i++){
          sc.makeScale(1, 0.5 + 2.2 * grow, 1);
          m4.multiplyMatrices(st.fieldBase[i], sc); st.field.setMatrixAt(i, m4);
        }
        st.field.instanceMatrix.needsUpdate = true;
        st.field.material.color.setHSL(0.27 - 0.13 * grow, 0.55, 0.42 + 0.12 * grow);
        st.pond.scale.setScalar(1 + 0.04 * Math.sin(t * 2 + v.pos.z));
        st.cows.children.forEach((c, i) => { c.rotation.y = Math.sin(t * 0.3 + i * 2) * 1.2; c.position.x = BUILDING_W * 0.1 + i * 2.2 + Math.sin(t * 0.2 + i) * 0.8; });
      }
      if (st.cart){
        const k = working ? (Math.sin(t * 0.9) + 1) / 2 : 0;
        st.cart.position.x = -BUILDING_W * 0.1 - 4 + k * 8;
        st.cartOre.visible = working && Math.cos(t * 0.9) > 0;
      }
      // Smoke while the fires are lit.
      if (working && inView && v.b.type in SMOKES && now - st.smokeAt > 550){
        st.smokeAt = now;
        const h = v.root.userData.height || 10;
        const at = new THREE.Vector3(BUILDING_W * 0.18, h * 0.92, -BUILDING_W * 0.1).applyAxisAngle(new THREE.Vector3(0, 1, 0), v.root.rotation.y).add(v.pos);
        puff(at, SMOKES[v.b.type]);
      }
      // The timer, and the pops when a unit lands.
      const showTimer = p && inView && (mine || d < (strat ? vd * 1.2 : 70));
      st.timer.visible = !!showTimer;
      if (showTimer){
        const el = st.timer.element;
        el.classList.toggle("mine", mine); el.classList.toggle("blocked", !!p.blocked);
        const realSecs = pace && p.per_hour ? (1 - frac) / p.per_hour * 3600 / pace : null;
        const label = p.blocked ? `${esc(p.item)} <small>stalled</small>`
          : `${esc(p.item)} <small>${realSecs == null ? "paused" : realSecs < 60 ? Math.ceil(realSecs) + "s" : Math.ceil(realSecs / 60) + "m"}</small>`;
        el.querySelector(".fg").setAttribute("stroke-dashoffset", String(RING * (1 - (p.blocked ? 1 : frac))));
        const span = el.querySelector("span"); if (span.innerHTML !== label) span.innerHTML = label;
      }
      if (working && st.lastFrac != null && frac < st.lastFrac - 0.0001) st.popAcc += 1;
      st.lastFrac = working ? frac : null;
      if (st.popAcc && now - st.popAt > 1400 && (mine || d < 90)){
        pop(v, `+${st.popAcc} ${p ? p.item : ""}`, mine);
        st.popAcc = 0; st.popAt = now;
      }
      // "!" over yours when it needs you.
      const mk = marks[v.b.id];
      const needs = mine && ((p && p.blocked) || (mk && (mk.health === "bad" || (mk.health === "idle" && !p))));
      st.bubble.visible = !!needs;
      if (needs) st.bubble.element.title = p && p.blocked ? `Stalled: ${p.why || "check it"}` : "Not producing: click to see why";
    }
    for (let i = puffs.length - 1; i >= 0; i--){
      const s = puffs[i], u = s.userData;
      u.age += dt;
      s.position.addScaledVector(u.drift, dt);
      s.scale.setScalar(1.2 + u.age * 1.4);
      s.material.opacity = Math.max(0, 0.8 * (1 - u.age / u.life));
      if (u.age >= u.life){ scene.remove(s); s.material.dispose(); puffs.splice(i, 1); }
    }
    if (now - holdAt > 400){ holdAt = now; renderHoldings(); }
  }

  /* ---------------------------------------------------------- holdings bar */
  const TYPE_ICON = {"Farm": "\u{1F33E}", "Mining Operation": "⛏", "Refinery": "\u{1F3ED}", "Tavern / Inn": "\u{1F372}",
    "Vehicle Dealer / Stable": "\u{1F40E}", "Weaponsmith / Armory": "⚔", "Home Improvement Store": "\u{1F528}",
    "Mining/Farming Equipment Store": "\u{1F527}", "Private Security Contractor": "\u{1F6E1}"};
  function renderHoldings(){
    const box = $("holdings"); if (!box) return;
    const mine = [...S.buildings.values()].filter(v => v.b.owner === G.you);
    box.style.display = mine.length ? "flex" : "none";
    if (!mine.length) return;
    const pace = S.ST && !S.ST.paused ? S.ST.pace : 0;
    const marks = (S.ADV && S.ADV.markers) || {};
    const html = mine.map(v => {
      const p = PROD && PROD.businesses[v.b.id], card = CARDS[v.b.id] || {}, mk = marks[v.b.id] || {};
      const stock = (card.stock || []).filter(s => s.qty > 0).sort((a, b) => b.qty - a.qty).slice(0, 2).map(s => `${s.qty} ${s.item}`).join(", ") || "empty";
      let frac = 0, line = "idle";
      if (p && !p.blocked){
        frac = (p.progress + p.per_hour * Math.max(0, S.HOUR - PROD.hour)) % 1;
        const secs = pace ? (1 - frac) / p.per_hour * 3600 / pace : null;
        line = `${p.item} ${secs == null ? "" : secs < 60 ? Math.ceil(secs) + "s" : Math.ceil(secs / 60) + "m"}`;
      } else if (p && p.blocked) line = `${p.item}: stalled`;
      else if (card.producing) line = `${card.producing}: nobody working`;
      const health = mk.health || "idle";
      return `<button class="hold ${health}" data-hold="${esc(v.b.id)}" title="${esc(v.b.type)} at ${esc(v.b.place)}">
        <span class="ico">${TYPE_ICON[v.b.type] || "\u{1F3E0}"}</span>
        <span class="txt"><b>${esc(v.b.type.split(" /")[0])}${card.land && card.land.item ? ` <span class="rich">+${Math.round(card.land.pct * 100)}% ${esc(card.land.item.replace(" Ore", ""))}</span>` : ""}</b><small>${esc(v.b.place)}</small><i class="bar"><i style="width:${(frac * 100).toFixed(1)}%"></i></i><small>${esc(line)} · ${esc(stock)}</small></span>
        ${mk.profit_per_hour ? `<span class="pph ${mk.profit_per_hour > 0 ? "up" : "down"}">${mk.profit_per_hour > 0 ? "+" : ""}${mk.profit_per_hour.toFixed(0)}/h</span>` : ""}
      </button>`;
    }).join("");
    if (box.dataset.html !== html){
      box.dataset.html = html; box.innerHTML = html;
      box.querySelectorAll("[data-hold]").forEach(b => b.onclick = () => {
        const v = S.buildings.get(b.dataset.hold); if (!v) return;
        flyTo(v.pos, 55); openBuilding(v.b.id);
      });
    }
  }

  return {update, setProduction, callout, ownerColour, cssColour, cards: () => CARDS};
}
