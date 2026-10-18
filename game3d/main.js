/* Convoy in 3D: the valley from over your shoulder.

   The simulation is unchanged. This is a new front end on the same server
   (`play.py`): the world's layout, its buildings and every agent's movements
   come from `/replay`, exactly what the 2D map draws; the player's state from
   `/api/state` and `/api/status`; every action goes through `/api/act`, the
   same dispatcher the agents use. The one new thing the server learns from
   this page is where the player's feet are (`/api/arrive`), because here the
   player walks rather than taking `travel_to`'s timed road.

   THE WORLD IS SHRUNK. The simulation's valley is about 2.4 km end to end;
   at SCALE a walk across a town takes about two minutes. Far places, and the
   other cities, are a fast travel away -- the timed `travel_to`.

   Axes match the 2D map: scene X is world y (along the valley road), scene Z
   is world x (across it, and from one city to the next). */

import * as THREE from "three";
import { GLTFLoader } from "three/addons/loaders/GLTFLoader.js";
import * as SkeletonUtils from "three/addons/utils/SkeletonUtils.js";
import { CSS2DRenderer, CSS2DObject } from "three/addons/renderers/CSS2DRenderer.js";
import { mergeGeometries } from "three/addons/utils/BufferGeometryUtils.js";
import { createUI } from "./ui.js";
import { createLife } from "./life.js";

const G = window.GAME;
const $ = id => document.getElementById(id);

/* ------------------------------------------------------------ constants */
const SCALE = 0.15;               // world metres -> scene units (tighter, 2026-10-17)
const CELL = 6.5;                 // one grid square: one plot. A business is 2x2.
const WALK = 4.6, RUN = 9.5;      // units per second
const HUMAN_H = 1.8;
let IDLE_AT = 0.25;               // where in the walk cycle a standing figure is held
const BUILDING_W = 13;            // a business's footprint, in scene units
const CHARACTERS = ["african-man", "african-woman", "asian-girl", "asian-man", "indian-man",
  "indian-woman", "persian-girl", "persian-man", "viking-girl"];
const PLAYER_CHARACTER = "persian-man";
const MODEL_FOR_TYPE = {
  "Tavern / Inn": "tavern", "Farm": "farm", "Refinery": "refinery",
  "Vehicle Dealer / Stable": "stable", "Weaponsmith / Armory": "blacksmith",
  "Mining Operation": "mine",
};
const PLAIN_COLOUR = {
  "Home Improvement Store": "#9b7651", "Mining/Farming Equipment Store": "#6f8191",
  "Private Security Contractor": "#5d5a72",
};
const SHORT_TYPE = {"Tavern / Inn": "Tavern", "Vehicle Dealer / Stable": "Stable",
  "Weaponsmith / Armory": "Armory", "Mining/Farming Equipment Store": "Equipment",
  "Home Improvement Store": "Builder's Yard", "Private Security Contractor": "Guards",
  "Mining Operation": "Mine"};

/* ------------------------------------------------------------ the server */
const api = {
  get: url => fetch(url, {cache: "no-store"}).then(r => r.json()),
  post: (url, body) => fetch(url, {method: "POST",
    headers: {"Content-Type": "application/json", "X-Game-Token": G.token},
    body: JSON.stringify(body || {})}).then(r => r.json()),
};

/* Everything the page knows, shared with the menus (ui.js). */
export const S = {
  DATA: null, ST: null, OBS: null, BOARD: null, HOUR: 0, base: {hour: 0, at: 0},
  places: {}, buildings: new Map(), agents: new Map(),
  player: null, here: null, arriving: false, travelling: null,
};

const hash = (s, k = 0) => {
  let h = 2166136261 ^ k;
  for (let i = 0; i < s.length; i++) { h ^= s.charCodeAt(i); h = Math.imul(h, 16777619); }
  return ((h >>> 0) % 100000) / 100000;
};
// "Aldermarch-gpt-6-luna-07" reads as "Aldermarch #07": the city, and the seat.
// Anywhere in a string, so "Aldermarch-gpt-6-luna-01's Farm" works too.
const short = n => String(n || "").replace(/\b([A-Z][a-z]+)-[A-Za-z0-9.]+(?:-[A-Za-z0-9.]+)*?-(\d{2,})\b/g, "$1 #$2");

/* MESHY EXPORTS ARRIVE SEE-THROUGH: every material is flagged transparent with
   depth writes off, so the ground showed through the body. Nothing here needs
   real transparency; make them solid, with alpha cut-outs kept as cut-outs. */
function solidify(root){
  root.traverse(o => {
    if (!o.isMesh) return;
    for (const m of [].concat(o.material)){
      m.transparent = false; m.depthWrite = true; m.opacity = 1;
      if (m.map) m.alphaTest = 0.5;
      if ("transmission" in m) m.transmission = 0;
      m.side = THREE.FrontSide;
      m.needsUpdate = true;
    }
  });
}

/* ------------------------------------------------------------ renderer */
const renderer = new THREE.WebGLRenderer({antialias: true});
renderer.setPixelRatio(Math.min(devicePixelRatio, 2));
renderer.setSize(innerWidth, innerHeight);
renderer.outputColorSpace = THREE.SRGBColorSpace;
renderer.toneMapping = THREE.ACESFilmicToneMapping;
renderer.toneMappingExposure = 1.28;
$("scene").appendChild(renderer.domElement);
const labels = new CSS2DRenderer();
labels.setSize(innerWidth, innerHeight);
$("labels").appendChild(labels.domElement);

const scene = new THREE.Scene();
scene.fog = new THREE.Fog("#c9dbe6", 260, 1100);
const camera = new THREE.PerspectiveCamera(55, innerWidth / innerHeight, 0.1, 3000);
addEventListener("resize", () => {
  renderer.setSize(innerWidth, innerHeight); labels.setSize(innerWidth, innerHeight);
  camera.aspect = innerWidth / innerHeight; camera.updateProjectionMatrix();
});

/* Sky: a gradient dome, horizon pale, zenith blue. */
{
  const geo = new THREE.SphereGeometry(2200, 32, 16);
  const mat = new THREE.ShaderMaterial({
    side: THREE.BackSide, depthWrite: false, fog: false,
    uniforms: {top: {value: new THREE.Color("#4f8fd0")}, bottom: {value: new THREE.Color("#d9e9f2")}},
    vertexShader: "varying vec3 p; void main(){ p = normalize(position); gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0); }",
    fragmentShader: "uniform vec3 top; uniform vec3 bottom; varying vec3 p; void main(){ float k = smoothstep(-0.05, 0.45, p.y); gl_FragColor = vec4(mix(bottom, top, k), 1.0); }",
  });
  scene.add(new THREE.Mesh(geo, mat));
}
// ART DIRECTION (2026-10-17): brighter and warmer than realism -- between
// Civilization and FarmVille. A strong sky light, a golden sun.
scene.add(new THREE.HemisphereLight("#e8f3ff", "#7a8a48", 1.5));
const sun = new THREE.DirectionalLight("#ffe7bd", 2.5);
sun.position.set(300, 420, 160);
scene.add(sun);

/* ------------------------------------------------------------ textures */
function noiseTexture(base, spread, size = 256, repeat = 1){
  const c = document.createElement("canvas"); c.width = c.height = size;
  const g = c.getContext("2d");
  g.fillStyle = base; g.fillRect(0, 0, size, size);
  const rgb = new THREE.Color(base);
  for (let i = 0; i < size * size / 3; i++){
    const x = Math.random() * size, y = Math.random() * size, d = (Math.random() - 0.5) * spread;
    const w = 2 + Math.random() * 2, h = 2 + Math.random() * 2;
    g.fillStyle = `rgb(${(rgb.r * 255 + d) | 0},${(rgb.g * 255 + d * 1.1) | 0},${(rgb.b * 255 + d * 0.6) | 0})`;
    // Drawn again across each edge, so the tile wraps without a seam: a seam
    // repeated every few metres reads as a grid laid over the grass.
    for (const ox of [0, -size]) for (const oy of [0, -size]) g.fillRect(x + ox, y + oy, w, h);
  }
  const t = new THREE.CanvasTexture(c);
  t.wrapS = t.wrapT = THREE.RepeatWrapping; t.repeat.set(repeat, repeat);
  t.colorSpace = THREE.SRGBColorSpace; t.anisotropy = 8;
  return t;
}
function softDisc(colour){
  const c = document.createElement("canvas"); c.width = c.height = 128;
  const g = c.getContext("2d"), grd = g.createRadialGradient(64, 64, 10, 64, 64, 64);
  const col = new THREE.Color(colour), rgba = a => `rgba(${col.r * 255 | 0},${col.g * 255 | 0},${col.b * 255 | 0},${a})`;
  grd.addColorStop(0, rgba(0.95)); grd.addColorStop(0.7, rgba(0.8)); grd.addColorStop(1, rgba(0));
  g.fillStyle = grd; g.fillRect(0, 0, 128, 128);
  const t = new THREE.CanvasTexture(c); t.colorSpace = THREE.SRGBColorSpace; return t;
}

/* ------------------------------------------------------------ the world */
let CX = 0, CY = 0;
const toScene = (x, y) => new THREE.Vector3((y - CY) * SCALE, 0, (x - CX) * SCALE);
const toWorld = v => ({x: v.z / SCALE + CX, y: v.x / SCALE + CY});
const roadSegs = [];              // [ax, az, bx, bz, halfWidth] for keeping trees off roads
const colliders = [];             // {x, z, r} -- buildings, which the player cannot walk through

function buildWorld(D, totals){
  const B = D.bounds;
  CX = (B.minx + B.maxx) / 2; CY = (B.miny + B.maxy) / 2;
  const w = (B.maxy - B.miny) * SCALE + 700, d = (B.maxx - B.minx) * SCALE + 700;

  // Grass.
  const grass = new THREE.Mesh(new THREE.PlaneGeometry(w, d),
    new THREE.MeshLambertMaterial({map: noiseTexture("#94c95c", 20, 256, Math.max(w, d) / 14)}));
  grass.rotation.x = -Math.PI / 2; grass.receiveShadow = true; grass.name = "ground";
  scene.add(grass);
  S.ground = grass;

  // Rivers: one across each valley, one between each pair of cities.
  const water = new THREE.MeshPhongMaterial({color: "#ffffff", shininess: 60, specular: "#9cc7e8",
    map: noiseTexture("#5fb3e6", 30, 128, 30)});
  S.water = water;
  const ax = (D.river.axis - CY) * SCALE, half = D.river.half * SCALE;
  const valleyRiver = new THREE.Mesh(new THREE.PlaneGeometry(half * 2, d), water);
  valleyRiver.rotation.x = -Math.PI / 2; valleyRiver.position.set(ax, 0.04, 0);
  scene.add(valleyRiver);
  for (const r of D.river.borders || []){
    const m = new THREE.Mesh(new THREE.PlaneGeometry(w, r.half * 2 * SCALE), water);
    m.rotation.x = -Math.PI / 2; m.position.set(0, 0.05, (r.axis - CX) * SCALE);
    scene.add(m);
  }

  // Roads: main roads wide, the roads between cities a little less, spur tracks narrow.
  const nCities = (D.cities || []).length || 1;
  // Double-sided: a ribbon's winding depends on which way the road runs.
  const roadMat = new THREE.MeshLambertMaterial({map: noiseTexture("#cdb07a", 28, 128, 1),
    side: THREE.DoubleSide, polygonOffset: true, polygonOffsetFactor: -2});
  D.roads.forEach((line, i) => {
    const width = i < nCities ? 6.5 : i < nCities + 3 ? 5 : 3.6;
    addRoad(line.map(([x, y]) => toScene(x, y)), width, roadMat);
  });

  // Places: a worn patch of ground, a name, and a radius that counts as "here".
  const dirt = new THREE.MeshLambertMaterial({map: softDisc("#d2bd8a"), transparent: true, opacity: 0.6, depthWrite: false,
    polygonOffset: true, polygonOffsetFactor: -1});
  // THE GRID. Every place is a block of grid squares around its centre, one
  // per plot the simulation gives it, kept off the roads and the rivers; the
  // biggest places choose first. A plot bought there sits on one square, and
  // a business takes a 2x2 block of four.
  const riverX = (D.river.axis - CY) * SCALE, riverHalf = D.river.half * SCALE;
  const borderZ = (D.river.borders || []).map(r => [(r.axis - CX) * SCALE, r.half * SCALE]);
  const wet = (x, z) => Math.abs(x - riverX) < riverHalf + CELL * 0.6 || borderZ.some(([bz, bh]) => Math.abs(z - bz) < bh + CELL * 0.6);
  S.cells = new Map();
  const order = [...D.places].sort((a, b) => (totals[b.name] || 0) - (totals[a.name] || 0));
  for (const p of order){
    const c = toScene(p.x, p.y), want = totals[p.name] || 16;
    const keys = [];
    for (let R = Math.sqrt(want) * CELL * 0.9; keys.length < want && R < 160; R += CELL){
      keys.length = 0;
      const cand = [];
      const g0x = Math.floor((c.x - R) / CELL), g1x = Math.floor((c.x + R) / CELL);
      const g0z = Math.floor((c.z - R) / CELL), g1z = Math.floor((c.z + R) / CELL);
      for (let gx = g0x; gx <= g1x; gx++) for (let gz = g0z; gz <= g1z; gz++){
        const x = (gx + 0.5) * CELL, z = (gz + 0.5) * CELL, k = `${gx},${gz}`;
        const d = Math.hypot(x - c.x, z - c.z);
        if (d > R || S.cells.has(k) || wet(x, z) || distToRoads(x, z) < CELL * 0.62) continue;
        cand.push([d, k, gx, gz, x, z]);
      }
      cand.sort((a, b) => a[0] - b[0]);
      for (const row of cand.slice(0, want)) keys.push(row);
    }
    for (const [, k, gx, gz, x, z] of keys) S.cells.set(k, {key: k, gx, gz, x, z, place: p.name});
    const r = Math.max(14, ...keys.map(([d]) => d)) + CELL * 0.8;
    const city = (D.cities || []).find(k => k.places.includes(p.name));
    S.places[p.name] = {name: p.name, kind: p.kind, c, r, city: city ? city.key : "", cityName: city ? city.name : "",
                        cells: keys.map(row => row[1])};
  }
  for (const p of D.places){
    const c = S.places[p.name].c;
    const el = document.createElement("div"); el.className = "lbl-place"; el.textContent = p.name;
    const lbl = new CSS2DObject(el); lbl.position.set(c.x, 16, c.z);
    scene.add(lbl);
    S.places[p.name].label = lbl;
  }
  for (const k of D.cities || []){
    const m = S.places[k.market]; if (!m) continue;
    const el = document.createElement("div"); el.className = "lbl-place city"; el.textContent = k.name.toUpperCase();
    const lbl = new CSS2DObject(el); lbl.position.set(m.c.x, 46, m.c.z);
    scene.add(lbl); k.label = lbl;
  }

  makeClouds(w, d);
  // A faint grid over all of it: the map reads as squares everywhere.
  {
    const pts = [], x0 = -w / 2, x1 = w / 2, z0 = -d / 2, z1 = d / 2;
    for (let x = Math.ceil(x0 / CELL) * CELL; x <= x1; x += CELL) pts.push(x, 0.07, z0, x, 0.07, z1);
    for (let z = Math.ceil(z0 / CELL) * CELL; z <= z1; z += CELL) pts.push(x0, 0.07, z, x1, 0.07, z);
    const g = new THREE.BufferGeometry(); g.setAttribute("position", new THREE.Float32BufferAttribute(pts, 3));
    scene.add(new THREE.LineSegments(g, new THREE.LineBasicMaterial({color: "#ffffff", transparent: true, opacity: 0.09, depthWrite: false})));
  }
  // Trees and rocks: the map's own, plus woodland everywhere nobody has built.
  scatterNature(D, w, d);
}

function addRoad(pts, width, mat){
  if (pts.length < 2) return;
  const pos = [], idx = [], uv = [];
  let along = 0;
  for (let i = 0; i < pts.length; i++){
    const a = pts[Math.max(0, i - 1)], b = pts[Math.min(pts.length - 1, i + 1)];
    const dx = b.x - a.x, dz = b.z - a.z, len = Math.hypot(dx, dz) || 1;
    const nx = -dz / len * width / 2, nz = dx / len * width / 2;
    if (i > 0) along += pts[i].distanceTo(pts[i - 1]);
    pos.push(pts[i].x + nx, 0.08, pts[i].z + nz, pts[i].x - nx, 0.08, pts[i].z - nz);
    uv.push(0, along / 8, 1, along / 8);
    if (i > 0){ const o = (i - 1) * 2; idx.push(o, o + 1, o + 2, o + 1, o + 3, o + 2); }
    if (i > 0) roadSegs.push([pts[i - 1].x, pts[i - 1].z, pts[i].x, pts[i].z, width / 2]);
  }
  const g = new THREE.BufferGeometry();
  g.setAttribute("position", new THREE.Float32BufferAttribute(pos, 3));
  g.setAttribute("uv", new THREE.Float32BufferAttribute(uv, 2));
  g.setIndex(idx); g.computeVertexNormals();
  const m = new THREE.Mesh(g, mat);
  scene.add(m);
}

function distToRoads(x, z){
  let best = 1e9;
  for (const [ax, az, bx, bz, hw] of roadSegs){
    const vx = bx - ax, vz = bz - az, l2 = vx * vx + vz * vz || 1;
    const t = Math.max(0, Math.min(1, ((x - ax) * vx + (z - az) * vz) / l2));
    best = Math.min(best, Math.hypot(x - ax - vx * t, z - az - vz * t) - hw);
  }
  return best;
}

/* WIND. Tree crowns lean and sway, more at the top, each a little out of step
   with its neighbours -- the cheapest thing that makes a landscape feel alive. */
const WIND = {value: 0};
function windy(mat){
  mat.onBeforeCompile = sh => {
    sh.uniforms.uWind = WIND;
    sh.vertexShader = "uniform float uWind;\n" + sh.vertexShader.replace("#include <begin_vertex>",
      `#include <begin_vertex>
       float ph = instanceMatrix[3].x * 0.21 + instanceMatrix[3].z * 0.17;
       float k = max(0.0, position.y - 2.0) * 0.03;
       transformed.x += sin(uWind * 1.6 + ph) * k;
       transformed.z += cos(uWind * 1.1 + ph * 1.3) * k * 0.6;`);
  };
  return mat;
}

function scatterNature(D, w, d){
  const trees = [], rocks = [];
  for (const p of D.places) for (const q of p.props){
    const v = toScene(q.x, q.y);
    if (S.cells.has(`${Math.floor(v.x / CELL)},${Math.floor(v.z / CELL)}`)) continue;   // nothing grows on a plot
    (q.kind === "rock" ? rocks : trees).push([v.x, v.z, (q.scale || 1)]);
  }
  // Woodland: deterministic, kept off roads, places and water.
  const placeList = Object.values(S.places);
  const riverX = (D.river.axis - CY) * SCALE, riverH = D.river.half * SCALE;
  const borders = (D.river.borders || []).map(r => [(r.axis - CX) * SCALE, r.half * SCALE]);
  let seed = 7; const rnd = () => (seed = (seed * 16807) % 2147483647) / 2147483647;
  for (let i = 0; i < 5200; i++){
    const x = (rnd() - 0.5) * (w - 100), z = (rnd() - 0.5) * (d - 100);
    if (Math.abs(x - riverX) < riverH + 4) continue;
    if (borders.some(([bz, bh]) => Math.abs(z - bz) < bh + 4)) continue;
    if (placeList.some(p => Math.hypot(x - p.c.x, z - p.c.z) < p.r + 4)) continue;
    if (distToRoads(x, z) < 7) continue;
    (rnd() < 0.12 ? rocks : trees).push([x, z, 0.7 + rnd() * 0.9]);
  }
  const trunkGeo = new THREE.CylinderGeometry(0.25, 0.35, 2.4, 6); trunkGeo.translate(0, 1.2, 0);
  const crownGeo = new THREE.IcosahedronGeometry(2.1, 0); crownGeo.translate(0, 3.9, 0);
  const pineGeo = new THREE.ConeGeometry(1.9, 5.2, 7); pineGeo.translate(0, 4.4, 0);
  const rockGeo = new THREE.DodecahedronGeometry(1.2, 0); rockGeo.translate(0, 0.5, 0);
  const trunks = new THREE.InstancedMesh(trunkGeo, new THREE.MeshLambertMaterial({color: "#6b4a2b"}), trees.length);
  const crowns = new THREE.InstancedMesh(crownGeo, windy(new THREE.MeshLambertMaterial({color: "#5fa13e", flatShading: true})), trees.length);
  const pines = new THREE.InstancedMesh(pineGeo, windy(new THREE.MeshLambertMaterial({color: "#4a8a3c", flatShading: true})), trees.length);
  const stones = new THREE.InstancedMesh(rockGeo, new THREE.MeshLambertMaterial({color: "#8c8a80", flatShading: true}), rocks.length);
  const m = new THREE.Matrix4(), q = new THREE.Quaternion(), s = new THREE.Vector3(), p = new THREE.Vector3(), e = new THREE.Euler();
  const hidden = new THREE.Matrix4().makeScale(0, 0, 0);
  const tint = new THREE.Color();
  trees.forEach(([x, z, k], i) => {
    e.set(0, (x * 13.7 + z) % 6.28, 0); q.setFromEuler(e); s.set(k, k, k); p.set(x, 0, z);
    m.compose(p, q, s);
    trunks.setMatrixAt(i, m);
    const pine = hash(`${x | 0},${z | 0}`) < 0.45;
    crowns.setMatrixAt(i, pine ? hidden : m);
    pines.setMatrixAt(i, pine ? m : hidden);
    tint.setHSL(0.24 + hash(`${z | 0}`, 3) * 0.08, 0.45, 0.32 + hash(`${x | 0}`, 5) * 0.1);
    crowns.setColorAt(i, tint); pines.setColorAt(i, tint);
  });
  rocks.forEach(([x, z, k], i) => {
    e.set(0, x % 6.28, 0); q.setFromEuler(e); s.set(k, k * 0.7, k); p.set(x, 0, z);
    m.compose(p, q, s); stones.setMatrixAt(i, m);
  });
  scene.add(trunks, crowns, pines, stones);
}

/* ------------------------------------------------------------ models */
const loader = new GLTFLoader();
const MODELS = {};          // name -> {scene, animations, scale, lift}
async function loadModels(progress){
  const names = [...CHARACTERS, ...new Set(Object.values(MODEL_FOR_TYPE))];
  let done = 0;
  await Promise.all(names.map(n => loader.loadAsync(`/assets3d/${n}.glb`).then(gltf => {
    solidify(gltf.scene);
    gltf.scene.updateMatrixWorld(true);
    const box = new THREE.Box3().setFromObject(gltf.scene), size = box.getSize(new THREE.Vector3());
    const isChar = CHARACTERS.includes(n);
    // The Meshy buildings were textured dark and muted; lift them toward the
    // brighter look by letting the texture light itself a little, and warm it.
    if (!isChar) gltf.scene.traverse(o => {
      if (!o.isMesh) return;
      for (const m of [].concat(o.material)){
        if (m.color) m.color.multiplyScalar(1.18);
        if (m.map && "emissive" in m){ m.emissiveMap = m.map; m.emissive = new THREE.Color("#ffe2b8"); m.emissiveIntensity = 0.32; }
        if ("roughness" in m) m.roughness = Math.min(m.roughness, 0.85);
        m.needsUpdate = true;
      }
    });
    const scale = isChar ? HUMAN_H / size.y : BUILDING_W / Math.max(size.x, size.z);
    MODELS[n] = {scene: gltf.scene, animations: gltf.animations, scale,
      lift: -box.min.y * scale, cx: (box.min.x + box.max.x) / 2 * scale, cz: (box.min.z + box.max.z) / 2 * scale,
      height: size.y * scale};
    progress(++done / names.length);
  }).catch(err => { console.warn("model", n, err); progress(++done / names.length); })));
}

const BLOB = new THREE.Mesh(new THREE.CircleGeometry(0.62, 20),
  new THREE.MeshBasicMaterial({color: "#000000", transparent: true, opacity: 0.28, depthWrite: false}));
BLOB.rotation.x = -Math.PI / 2; BLOB.position.y = 0.1; BLOB.renderOrder = 1;

/* A person: the rigged model, its animations, a wrapper we move. */
function makePerson(name){
  const M = MODELS[name] || MODELS[CHARACTERS[0]];
  const body = SkeletonUtils.clone(M.scene);
  body.scale.setScalar(M.scale);
  body.position.set(-M.cx, M.lift, -M.cz);
  body.traverse(o => { if (o.isMesh){ o.frustumCulled = false; } });
  const root = new THREE.Group(); root.add(body, BLOB.clone());
  const mixer = new THREE.AnimationMixer(body);
  const clip = re => M.animations.find(a => re.test(a.name));
  const acts = {};
  for (const [k, re] of [["walk", /walk/i], ["run", /run/i], ["work", /swing|attack|combo/i]]){
    const c = clip(re); if (c) acts[k] = mixer.clipAction(c);
  }
  // No idle in these exports: stand in the walk's PASSING frame, a quarter of
  // the way through the cycle, where the feet are together under the body.
  // Frame 0 is a stride, and held still it looks like a statue mid-step.
  if (acts.walk){
    acts.idle = mixer.clipAction(acts.walk.getClip().clone());
    acts.idle.play(); acts.idle.paused = true; acts.idle.time = IDLE_AT * acts.walk.getClip().duration;
  }
  const person = {root, body, mixer, acts, state: "idle", heading: 0};
  return person;
}
function setAnim(p, state, speed = 1){
  if (p.state === state){ if (p.acts[state]) p.acts[state].timeScale = speed; return; }
  const from = p.acts[p.state], to = p.acts[state];
  if (!to) return;
  to.reset(); to.timeScale = speed; to.enabled = true; to.setEffectiveWeight(1);
  if (state === "idle"){ to.paused = true; to.time = IDLE_AT * to.getClip().duration; }
  to.play();
  if (from) from.crossFadeTo(to, 0.2, false);
  p.state = state;
}

/* A business: the Meshy building for its type, or a plain one with a sign. */
function makeBuilding(b){
  const key = MODEL_FOR_TYPE[b.type];
  const root = new THREE.Group();
  if (key && MODELS[key]){
    const M = MODELS[key], m = M.scene.clone(true);
    m.scale.setScalar(M.scale); m.position.set(-M.cx, M.lift, -M.cz);
    root.add(m); root.userData.height = M.height;
  } else {
    const colour = PLAIN_COLOUR[b.type] || "#957d5b";
    const walls = new THREE.Mesh(new THREE.BoxGeometry(10, 6, 9), new THREE.MeshLambertMaterial({color: colour}));
    walls.position.y = 3;
    const roof = new THREE.Mesh(new THREE.ConeGeometry(8.2, 4, 4), new THREE.MeshLambertMaterial({color: "#7a3b26", flatShading: true}));
    roof.rotation.y = Math.PI / 4; roof.scale.set(1, 1, 0.9); roof.position.y = 8;
    const door = new THREE.Mesh(new THREE.BoxGeometry(2, 3.4, 0.3), new THREE.MeshLambertMaterial({color: "#3b2414"}));
    door.position.set(0, 1.7, 4.55);
    const board = new THREE.Mesh(new THREE.BoxGeometry(6, 1.3, 0.3), new THREE.MeshLambertMaterial({color: "#d9c08a"}));
    board.position.set(0, 4.6, 4.6);
    root.add(walls, roof, door, board); root.userData.height = 10;
  }
  root.traverse(o => { o.userData.pick = {kind: "building", id: b.id}; });
  const el = document.createElement("div");
  el.className = "lbl-biz" + (b.owner === G.you ? " mine" : "");
  el.innerHTML = signHTML(b, null);
  // On the facade, not floating above the roof: close up, a sign over the
  // roof is off the top of the screen.
  const lbl = new CSS2DObject(el); lbl.position.set(0, 6.5, 0);
  root.add(lbl); root.userData.label = lbl;
  return root;
}
/* A building's sign: what you could do there now (icons), what it is, whose
   it is -- and for yours, how it is doing. See `advisor.markers`. */
const ICON = {meal: "\u{1F372}", buys: "\u{1F4B0}", shop: "\u{1F6D2}", hiring: "\u2757", work: "\u2692"};
function signHTML(b, mk){
  const icons = mk && mk.icons && mk.icons.length
    ? `<div class="icons">${mk.icons.map(i => `<span class="ic ${i.icon}" title="${esc(i.tip)}">${ICON[i.icon] || "?"}</span>`).join("")}</div>` : "";
  const mine = b.owner === G.you;
  const hp = mine && mk && mk.health ? `<span class="hp ${mk.health}"></span>` : "";
  const sub = mine ? (mk && mk.profit_per_hour ? `yours \u00b7 ${mk.profit_per_hour > 0 ? "+" : ""}${mk.profit_per_hour.toFixed(1)}/h` : "yours")
                   : esc(short(ownerName(b.owner)));
  // The shop's price, on its sign: an undercut is visible from the street.
  const card = typeof LIFE !== "undefined" && LIFE ? LIFE.cards()[b.id] : null;
  const priced = card && (card.stock || []).find(s => s.price != null && s.qty > 0);
  const price = priced ? `<span class="price">${esc(priced.item)} ${(+priced.price).toFixed(priced.price < 10 ? 1 : 0)}</span>` : "";
  const dot = `<span class="own" style="background:${LIFE ? LIFE.cssColour(b.owner) : "#999"}"></span>`;
  const rich = card && card.land && card.land.item ? `<span class="rich">+${Math.round(card.land.pct * 100)}% ${esc(card.land.item)}</span>` : "";
  return `${icons}${hp}${dot}${esc(SHORT_TYPE[b.type] || b.type)}${rich}${price}<small>${sub}</small>`;
}
const esc = s => String(s == null ? "" : s).replace(/[&<>"']/g, ch => ({"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"}[ch]));
function ownerName(id){
  const a = S.DATA && S.DATA.agents.find(x => x.id === id);
  return a ? a.name : id || "";
}

/* ------------------------------------------------------------ clouds */
const clouds = [];
function makeClouds(w, d){
  const mat = new THREE.MeshLambertMaterial({color: "#ffffff", flatShading: true, emissive: "#ffffff", emissiveIntensity: 0.35});
  let seed = 11; const rnd = () => (seed = (seed * 16807) % 2147483647) / 2147483647;
  for (let i = 0; i < 14; i++){
    const g = new THREE.Group();
    for (let j = 0; j < 5; j++){
      const b = new THREE.Mesh(new THREE.IcosahedronGeometry(5 + rnd() * 5, 0), mat);
      b.position.set((j - 2) * 6 + rnd() * 3, rnd() * 3, rnd() * 5); b.scale.y = 0.6;
      g.add(b);
    }
    g.position.set((rnd() - 0.5) * w, 70 + rnd() * 40, (rnd() - 0.5) * d);
    g.userData.speed = 1.5 + rnd() * 2; g.userData.span = w;
    scene.add(g); clouds.push(g);
  }
}

/* ------------------------------------------------------------ the land */
/* EVERY PLOT ON A SQUARE. The server lists every owned plot (place, owner,
   business) and the squares the player chose for theirs; the rest are laid out
   here, the same way on every load: each business on the first free 2x2 block
   of its place, loose plots on the first free squares. Free squares are
   outlined, owned ones tinted in their owner's colour, chosen ones glow. */
const PARCEL = CELL;
let landKey = "", outlines = null, tints = null, picks = null;
const saleSigns = new Map();
S.cellOwner = new Map();          // cell key -> {plot, owner, business}
S.bizCells = new Map();           // business id -> [cell keys]
S.selected = new Set();
let PLOTS = null;
async function pollPlots(){
  try { PLOTS = await api.get("/api/plots"); } catch (e) { return; }
  syncLand(); syncBuildings();
}
function assignPlots(){
  S.cellOwner.clear(); S.bizCells.clear();
  if (!PLOTS) return;
  const taken = new Set();
  const put = (q, k) => {
    S.cellOwner.set(k, {plot: q.id, owner: q.owner, business: q.business});
    taken.add(k);
    if (q.business){ if (!S.bizCells.has(q.business)) S.bizCells.set(q.business, []); S.bizCells.get(q.business).push(k); }
  };
  const byId = new Map(PLOTS.plots.map(q => [q.id, q]));
  // The player's choices first.
  for (const [pid, k] of Object.entries(PLOTS.claims || {})){
    const q = byId.get(pid), c = S.cells.get(k);
    if (q && c && c.place === q.place && !taken.has(k)) put(q, k);
  }
  const placed = new Set([...S.cellOwner.values()].map(o => o.plot));
  const free = place => (S.places[place] ? S.places[place].cells : []).filter(k => !taken.has(k));
  // Businesses, oldest first, each on a 2x2 block.
  const groups = new Map();
  for (const q of PLOTS.plots) if (q.business && !placed.has(q.id)){
    if (!groups.has(q.business)) groups.set(q.business, []); groups.get(q.business).push(q);
  }
  for (const [bid, qs] of [...groups].sort((a, b) => a[0].localeCompare(b[0]))){
    const place = qs[0].place, cells = free(place);
    let block = null;
    for (const k of cells){
      const c = S.cells.get(k), ks = [k, `${c.gx + 1},${c.gz}`, `${c.gx},${c.gz + 1}`, `${c.gx + 1},${c.gz + 1}`];
      if (ks.every(x => S.cells.has(x) && S.cells.get(x).place === place && !taken.has(x))){ block = ks; break; }
    }
    const spots = block || cells.slice(0, qs.length);
    qs.sort((a, b) => a.id.localeCompare(b.id)).forEach((q, i) => { if (spots[i]) put(q, spots[i]); });
  }
  // Loose plots.
  for (const q of PLOTS.plots) if (!q.business && !placed.has(q.id)){
    const k = free(q.place)[0]; if (k) put(q, k);
  }
}
function syncLand(){
  assignPlots();
  const key = [...S.cellOwner].map(([k, o]) => `${k}:${o.owner}`).join("|") + "#" + [...S.selected].join(",");
  if (key === landKey) return;
  landKey = key;
  if (outlines){ scene.remove(outlines, tints, picks); }
  const all = [...S.cells.values()];
  const freeCells = all.filter(c => !S.cellOwner.has(c.key));
  // Outline of a free square: a rounded frame on the grass.
  const e = CELL / 2 - 0.3, t = 0.22;
  const frame = mergeGeometries([[0, -e, CELL - 0.6, t], [0, e, CELL - 0.6, t], [-e, 0, t, CELL - 0.6], [e, 0, t, CELL - 0.6]]
    .map(([x, z, w, d]) => { const g = new THREE.PlaneGeometry(w, d); g.rotateX(-Math.PI / 2); g.translate(x, 0, z); return g; }));
  outlines = new THREE.InstancedMesh(frame, new THREE.MeshBasicMaterial({color: "#fff6d8", transparent: true, opacity: 0.6,
    depthWrite: false, polygonOffset: true, polygonOffsetFactor: -2}), Math.max(1, freeCells.length));
  const m = new THREE.Matrix4();
  freeCells.forEach((c, i) => { m.makeTranslation(c.x, 0.09, c.z); outlines.setMatrixAt(i, m); });
  outlines.count = freeCells.length;
  // Owned squares in the owner's colour.
  const owned = all.filter(c => S.cellOwner.has(c.key));
  const sq = new THREE.PlaneGeometry(CELL - 0.35, CELL - 0.35); sq.rotateX(-Math.PI / 2);
  tints = new THREE.InstancedMesh(sq, new THREE.MeshBasicMaterial({transparent: true, opacity: 0.42, depthWrite: false,
    polygonOffset: true, polygonOffsetFactor: -1}), Math.max(1, owned.length));
  owned.forEach((c, i) => {
    m.makeTranslation(c.x, 0.08, c.z); tints.setMatrixAt(i, m);
    tints.setColorAt(i, LIFE ? LIFE.ownerColour(S.cellOwner.get(c.key).owner) : new THREE.Color("#c8a060"));
  });
  tints.count = owned.length;
  // Squares you have picked.
  const chosen = [...S.selected].map(k => S.cells.get(k)).filter(Boolean);
  picks = new THREE.InstancedMesh(sq, new THREE.MeshBasicMaterial({color: "#ffd84a", transparent: true, opacity: 0.75, depthWrite: false,
    polygonOffset: true, polygonOffsetFactor: -3}), Math.max(1, chosen.length));
  chosen.forEach((c, i) => { m.makeTranslation(c.x, 0.1, c.z); picks.setMatrixAt(i, m); });
  picks.count = chosen.length;
  scene.add(outlines, tints, picks);
  // How many squares each place has left, under its name.
  for (const p of Object.values(S.places)){
    if (!p.label) continue;
    const n = p.cells.filter(k => !S.cellOwner.has(k)).length;
    const html = `${esc(p.name)}<small>${n ? `${n} plot${n > 1 ? "s" : ""} for sale` : "sold out"}</small>`;
    if (p.label.element.innerHTML !== html) p.label.element.innerHTML = html;
  }
}
function cellAt(v){ return S.cells.get(`${Math.floor(v.x / CELL)},${Math.floor(v.z / CELL)}`); }
/* Picking squares: click free squares of one place, up to four. Four in a 2x2
   block can take a business; any number can be bought as land. */
function toggleCell(c){
  const first = S.selected.size ? S.cells.get([...S.selected][0]) : null;
  if (first && first.place !== c.place) S.selected.clear();
  if (S.selected.has(c.key)) S.selected.delete(c.key);
  else if (S.selected.size < 4) S.selected.add(c.key);
  else { S.selected.clear(); S.selected.add(c.key); }
  landKey = ""; syncLand();
  const cells = [...S.selected].map(k => S.cells.get(k));
  let block = false;
  if (cells.length === 4){
    const gx = Math.min(...cells.map(c => c.gx)), gz = Math.min(...cells.map(c => c.gz));
    block = cells.every(c => c.gx - gx <= 1 && c.gz - gz <= 1);
  }
  UI.selectionChanged(cells.length ? {place: c.place, cells: cells.map(c => c.key), block} : null);
}
function clearSelection(){ S.selected.clear(); landKey = ""; syncLand(); UI.selectionChanged(null); }
/* Founding on the squares you picked: walk there if need be, found, and pin
   the new business's plots to those squares. */
async function foundOn(place, cells, type){
  const go = async () => {
    const r = await UI.act("start_business", {type});
    if (!r.ok) return;
    const m = /\(id (B\d+)\)/.exec(r.message || "");
    await api.post("/api/claim", {place, cells, business_id: m ? m[1] : ""});
    clearSelection(); popNext = m ? m[1] : null;
    pollPlots();
  };
  if (S.here === place && S.OBS && S.OBS.you.location === place) go();
  else { UI.toast(`Walking to ${place} to build`); walkToPlace(place, () => setTimeout(go, 1200)); }
}
async function buyOn(place, cells){
  const go = async () => {
    const r = await UI.act("buy_land", {plots: cells.length});
    if (!r.ok) return;
    await api.post("/api/claim", {place, cells});
    clearSelection(); pollPlots();
  };
  if (S.here === place && S.OBS && S.OBS.you.location === place) go();
  else { UI.toast(`Walking to ${place} to buy`); walkToPlace(place, () => setTimeout(go, 1200)); }
}
let popNext = null;               // the next building to appear does so with a bounce

/* ------------------------------------------------------------ syncing the world */
function syncBuildings(){
  const D = S.DATA, h = S.HOUR, live = new Set();
  for (const b of D.buildings || []){
    if (b.from != null && b.from > h + 0.01) continue;
    if (b.to != null && b.to <= h) continue;
    if (b.government) continue;
    live.add(b.id);
    const cells = (S.bizCells.get(b.id) || []).map(k => S.cells.get(k)).filter(Boolean);
    const pos = cells.length ? new THREE.Vector3(cells.reduce((a, c) => a + c.x, 0) / cells.length, 0,
                                                 cells.reduce((a, c) => a + c.z, 0) / cells.length) : toScene(b.x, b.y);
    const have = S.buildings.get(b.id);
    if (have){
      if (have.pos.distanceTo(pos) > 0.5){     // its squares changed: move it
        have.pos.copy(pos); have.root.position.copy(pos);
        const col = colliders.find(c => c.id === b.id); if (col){ col.x = pos.x; col.z = pos.z; }
      }
      continue;
    }
    const root = makeBuilding(b);
    const place = S.places[b.place];
    // Face the middle of its place: the doors open onto the square.
    const ang = place ? Math.atan2(place.c.x - pos.x, place.c.z - pos.z) : 0;
    root.position.copy(pos); root.rotation.y = ang;
    scene.add(root);
    S.buildings.set(b.id, {root, b, pos, ang, born: performance.now(), pop: popNext === b.id || S.ready});
    if (popNext === b.id) popNext = null;
    colliders.push({id: b.id, x: pos.x, z: pos.z, r: BUILDING_W * 0.42});
  }
  for (const [id, v] of S.buildings){
    if (live.has(id)) continue;
    scene.remove(v.root); v.root.traverse(o => { if (o.isCSS2DObject) o.element.remove(); });
    S.buildings.delete(id);
    const i = colliders.findIndex(c => c.id === id); if (i >= 0) colliders.splice(i, 1);
  }
}

/* Where an agent is, from its track: standing about its place, at its bench
   during a shift, or partway down the road between two places. */
function agentTarget(a, h){
  const tr = S.DATA.tracks[a.id];
  if (!tr || !tr.length){
    const card = (S.DATA.cards || {})[a.id], at = S.places[(card && card.at) || a.at];
    if (!at) return null;
    const ang = hash(a.id) * Math.PI * 2, rad = 5 + hash(a.id, 1) * (at.r * 0.55);
    return {p: new THREE.Vector3(at.c.x + Math.cos(ang) * rad, 0, at.c.z + Math.sin(ang) * rad), place: at.name};
  }
  let lo = 0, hi = tr.length - 1, at = -1;
  while (lo <= hi){ const mid = (lo + hi) >> 1; if (tr[mid][0] <= h){ at = mid; lo = mid + 1; } else hi = mid - 1; }
  if (at < 0) at = 0;
  const [t0, from, dest] = tr[at];
  const here = S.places[from]; if (!here) return null;
  if (dest && tr[at + 1]){
    const [t1, to] = tr[at + 1], there = S.places[to];
    if (there && t1 > t0 && h < t1){
      const k = Math.max(0, Math.min(1, (h - t0) / (t1 - t0)));
      return {p: here.c.clone().lerp(there.c, k), moving: true, place: from};
    }
  }
  const shift = (a.shifts || []).find(([s, e]) => s <= h && h < e);
  const bench = shift && S.buildings.get(shift[2]);
  if (bench){
    const toward = here.c.clone().sub(bench.pos).setY(0).normalize();
    const side = new THREE.Vector3(toward.z, 0, -toward.x);
    return {p: bench.pos.clone().addScaledVector(toward, 8.5).addScaledVector(side, (hash(a.id, 2) - 0.5) * 6), working: true, place: from};
  }
  const ang = hash(a.id) * Math.PI * 2, rad = 5 + hash(a.id, 1) * (here.r * 0.55);
  return {p: new THREE.Vector3(here.c.x + Math.cos(ang) * rad, 0, here.c.z + Math.sin(ang) * rad), place: from};
}

function syncAgents(){
  const D = S.DATA;
  // Everyone alive, not only those who have already moved: the cards come
  // from the checkpoint and list the whole population.
  const roster = new Map((D.agents || []).map(a => [a.id, a]));
  for (const c of Object.values(D.cards || {})){
    if (c.kind === "agent" && !roster.has(c.id)) roster.set(c.id, {id: c.id, name: c.name, died: c.alive === false ? 0 : null, at: c.at});
  }
  for (const a of roster.values()){
    if (a.id === G.you) continue;
    const dead = a.died != null && a.died <= S.HOUR;
    let v = S.agents.get(a.id);
    if (dead){ if (v){ scene.remove(v.root); S.agents.delete(a.id); } continue; }
    if (!v){
      const ch = CHARACTERS[Math.floor(hash(a.id, 9) * CHARACTERS.length)];
      v = makePerson(ch);
      v.id = a.id; v.a = a;
      v.root.traverse(o => { o.userData.pick = {kind: "agent", id: a.id}; });
      const t = agentTarget(a, S.HOUR);
      if (t) v.root.position.copy(t.p);
      scene.add(v.root);
      S.agents.set(a.id, v);
    }
    v.a = a;
  }
}

/* ------------------------------------------------------------ the player */
const keys = new Set();
let yaw = Math.PI, pitch = 0.2, dist = 7;
/* TWO CAMERAS, ONE WORLD. "strategy" is the default: a tilted overview you
   pan and zoom, for running your businesses (Civ, Anno, Manor Lords). "third"
   is over your shoulder, for walking the streets and for the moments that
   matter. Zoom all the way in on yourself and you drop into it; zoom out and
   you rise back; Tab switches either way. They share `yaw`, so the world does
   not spin when you change. */
let camMode = "strategy";
const focus = new THREE.Vector3(), focusGoal = new THREE.Vector3();
let sPitch = 0.95, sDist = 55;
const S_MIN = 14, S_MAX = 520, THIRD_OUT = 24;
function focusPoint(){ return camMode === "strategy" ? focus : (S.player ? S.player.root.position : focus); }
function enterThird(){
  if (!S.player) return;
  camMode = "third"; dist = 8; pitch = 0.22;
  yaw = Math.atan2(camera.position.x - S.player.root.position.x, camera.position.z - S.player.root.position.z);
  modeChanged();
}
function enterStrategy(at){
  camMode = "strategy";
  focusGoal.copy(at || (S.player ? S.player.root.position : focus)); focus.copy(focusGoal);
  sDist = Math.max(sDist, 40);
  modeChanged();
}
function toggleCamera(){ camMode === "strategy" ? enterThird() : enterStrategy(); }
function flyTo(v, d){
  if (camMode !== "strategy") enterStrategy(S.player.root.position);
  focusGoal.set(v.x, 0, v.z); if (d) sDist = d;
}
function modeChanged(){
  $("keys").innerHTML = camMode === "strategy"
    ? "<b>WASD</b>/<b>drag</b> pan &middot; <b>right-drag</b> turn &middot; <b>scroll</b> zoom &middot; <b>click</b> to walk or open &middot; <b>Tab</b> take control &middot; <b>F</b> find me"
    : "<b>WASD</b> move &middot; <b>Shift</b> run &middot; <b>drag</b> look &middot; <b>E</b> open &middot; <b>Tab</b> overview &middot; <b>F</b> behind me";
  if (window.convoyUI) window.convoyUI.cameraChanged(camMode);
}
let autoTarget = null, autoOnArrive = null;
const marker = new THREE.Mesh(new THREE.RingGeometry(0.8, 1.2, 28), new THREE.MeshBasicMaterial({color: "#ffd966", transparent: true, opacity: 0.85, depthWrite: false}));
marker.rotation.x = -Math.PI / 2; marker.visible = false; scene.add(marker);
const youRing = new THREE.Mesh(new THREE.RingGeometry(0.55, 0.72, 32), new THREE.MeshBasicMaterial({color: "#ffcf4a", transparent: true, opacity: 0.55, depthWrite: false}));
youRing.rotation.x = -Math.PI / 2; scene.add(youRing);

function spawnPlayer(place){
  const P = makePerson(PLAYER_CHARACTER);
  P.root.traverse(o => { o.userData.pick = {kind: "you"}; });
  const c = (S.places[place] || Object.values(S.places)[0]).c;
  P.root.position.set(c.x + 3, 0, c.z + 3);
  scene.add(P.root);
  S.player = P;
  S.here = place;
}

function placeAt(v){
  let best = null, bd = 1e9;
  for (const p of Object.values(S.places)){
    const d = Math.hypot(v.x - p.c.x, v.z - p.c.z);
    if (d < p.r && d < bd){ best = p; bd = d; }
  }
  return best;
}
function nearestPlace(v){
  let best = null, bd = 1e9;
  for (const p of Object.values(S.places)){
    const d = Math.hypot(v.x - p.c.x, v.z - p.c.z);
    if (d < bd){ best = p; bd = d; }
  }
  return best;
}

function updatePlayer(dt){
  const P = S.player; if (!P) return;
  const busyTravel = S.ST && /^Travelling/.test(S.ST.activity || "");
  const fwd = new THREE.Vector3(-Math.sin(yaw), 0, -Math.cos(yaw));
  const right = new THREE.Vector3(Math.cos(yaw), 0, -Math.sin(yaw));
  const mv = new THREE.Vector3();
  if (!busyTravel && !S.travelling && camMode === "third"){
    if (keys.has("w") || keys.has("arrowup")) mv.add(fwd);
    if (keys.has("s") || keys.has("arrowdown")) mv.sub(fwd);
    if (keys.has("a") || keys.has("arrowleft")) mv.sub(right);
    if (keys.has("d") || keys.has("arrowright")) mv.add(right);
  }
  const run = keys.has("shift");
  if (mv.lengthSq() > 0){ autoTarget = null; autoOnArrive = null; marker.visible = false; }
  else if (autoTarget && !busyTravel){
    const to = autoTarget.clone().sub(P.root.position).setY(0);
    if (to.length() < 1.2){
      autoTarget = null; marker.visible = false;
      const cb = autoOnArrive; autoOnArrive = null; if (cb) cb();
    } else mv.copy(to);
  }
  let speed = 0;
  if (mv.lengthSq() > 0){
    mv.normalize();
    speed = run || (autoTarget && autoTarget.distanceTo(P.root.position) > 40) ? RUN : WALK;
    // Mounted, you go at your vehicle's pace (a 4-horse chariot is 4x a walk).
    if (S.ST && S.ST.vehicle) speed *= S.ST.speed || 1;
    P.root.position.addScaledVector(mv, speed * dt);
    const want = Math.atan2(mv.x, mv.z);
    let dh = want - P.heading; dh = Math.atan2(Math.sin(dh), Math.cos(dh));
    P.heading += dh * Math.min(1, dt * 12);
    P.root.rotation.y = P.heading;
  }
  // Buildings are solid.
  for (const c of colliders){
    const dx = P.root.position.x - c.x, dz = P.root.position.z - c.z, d = Math.hypot(dx, dz);
    if (d < c.r && d > 0.001){ P.root.position.x = c.x + dx / d * c.r; P.root.position.z = c.z + dz / d * c.r; }
  }
  const working = S.ST && /^Working/.test(S.ST.activity || "");
  const legs = S.ST && S.ST.vehicle ? speed / (S.ST.speed || 1) : speed;   // a rider's legs do not race
  setAnim(P, speed > 0 ? (legs > WALK + 0.1 ? "run" : "walk") : working && P.acts.work ? "work" : "idle",
          speed > 0 ? legs / (legs > WALK + 0.1 ? 7.5 : 3.6) : 1);
  P.mixer.update(dt);
  youRing.position.set(P.root.position.x, 0.12, P.root.position.z);
  const pulse = 1 + 0.08 * Math.sin(performance.now() / 260);
  youRing.scale.setScalar(pulse);

  // Arriving somewhere is news to the server.
  const at = placeAt(P.root.position);
  if (at && at.name !== S.here && !S.arriving && !busyTravel && !S.travelling){
    S.arriving = true;
    api.post("/api/arrive", {place: at.name}).then(r => {
      S.arriving = false;
      if (r.ok){
        S.here = at.name; UI.refreshSoon();
        // A haul loaded or handed over on the way in: say so, and head on.
        if (r.haul) UI.toast(r.haul);
        if (r.go && r.go !== at.name) walkToPlace(r.go);
      }
    }).catch(() => { S.arriving = false; });
  }
}

function updateStrategyCamera(dt){
  // Pan with the keys, relative to which way the camera faces; faster when high.
  const fwd = new THREE.Vector3(-Math.sin(yaw), 0, -Math.cos(yaw));
  const right = new THREE.Vector3(Math.cos(yaw), 0, -Math.sin(yaw));
  const pan = new THREE.Vector3();
  if (keys.has("w") || keys.has("arrowup")) pan.add(fwd);
  if (keys.has("s") || keys.has("arrowdown")) pan.sub(fwd);
  if (keys.has("a") || keys.has("arrowleft")) pan.sub(right);
  if (keys.has("d") || keys.has("arrowright")) pan.add(right);
  if (pan.lengthSq()) focusGoal.addScaledVector(pan.normalize(), sDist * 1.1 * dt * (keys.has("shift") ? 2.2 : 1));
  focus.lerp(focusGoal, 0.18);
  const cam = focus.clone()
    .add(new THREE.Vector3(Math.sin(yaw), 0, Math.cos(yaw)).multiplyScalar(sDist * Math.cos(sPitch)))
    .add(new THREE.Vector3(0, sDist * Math.sin(sPitch), 0));
  camera.position.lerp(cam, 0.25);
  camera.lookAt(focus);
  scene.fog.near = Math.max(260, sDist * 1.6); scene.fog.far = Math.max(1100, sDist * 5);
}

function updateCamera(dt){
  if (camMode === "strategy") return updateStrategyCamera(dt);
  scene.fog.near = 260; scene.fog.far = 1100;
  const P = S.player; if (!P) return;
  const fwd = new THREE.Vector3(-Math.sin(yaw), 0, -Math.cos(yaw));
  const right = new THREE.Vector3(Math.cos(yaw), 0, -Math.sin(yaw));
  // Over the right shoulder, Fortnite-style: the character sits a little left
  // of centre and low in the frame, the world ahead of them.
  const target = P.root.position.clone().add(new THREE.Vector3(0, 1.9, 0)).addScaledVector(right, Math.min(1.1, dist * 0.12));
  // THE CAMERA DOES NOT GO THROUGH WALLS. If a building stands between you
  // and where the camera wants to be, the camera comes in to this side of it.
  // Buildings are circles on the ground for this, the same as for walking.
  let d = dist;
  const back = fwd.clone().negate();
  for (const c of colliders){
    if (c.r < 3) continue;                       // wells and stalls are short
    const ox = target.x - c.x, oz = target.z - c.z;
    const b = ox * back.x + oz * back.z, cc = ox * ox + oz * oz - (c.r + 0.8) ** 2;
    const disc = b * b - cc;
    if (disc < 0) continue;
    const t = -b - Math.sqrt(disc);               // first entry along the ray
    if (t > 0.3 && t < d * Math.cos(pitch)) d = Math.max(1.6, t / Math.cos(pitch) - 0.4);
  }
  const cam = target.clone().addScaledVector(fwd, -d * Math.cos(pitch)).add(new THREE.Vector3(0, d * Math.sin(pitch), 0));
  cam.y = Math.max(0.6, cam.y);
  camera.position.lerp(cam, 0.35);
  // Look a little past the character, not down at its feet: the horizon
  // stays in the upper third, the way a third-person game frames the road.
  camera.lookAt(target.clone().addScaledVector(fwd, 4).add(new THREE.Vector3(0, -0.3, 0)));
}

function updateAgents(dt){
  for (const v of S.agents.values()){
    const t = agentTarget(v.a, S.HOUR);
    if (!t) continue;
    const to = t.p.clone().sub(v.root.position).setY(0);
    const d = to.length();
    if (d > 90){ v.root.position.copy(t.p); continue; }
    let speed = 0;
    if (d > 0.4){
      speed = Math.min(d / Math.max(dt, 0.001), t.moving ? 14 : 3.2);
      v.root.position.addScaledVector(to.normalize(), speed * dt);
      const want = Math.atan2(to.x, to.z);
      let dh = want - v.heading; dh = Math.atan2(Math.sin(dh), Math.cos(dh));
      v.heading += dh * Math.min(1, dt * 8); v.root.rotation.y = v.heading;
    } else if (t.working){
      // Face the bench.
      const bench = [...S.buildings.values()].find(b => b.b.place === t.place && b.pos.distanceTo(v.root.position) < 14);
      if (bench){ v.heading = Math.atan2(bench.pos.x - v.root.position.x, bench.pos.z - v.root.position.z); v.root.rotation.y = v.heading; }
    }
    const reach = camMode === "strategy" ? Math.max(260, sDist * 2.2) : 260;
    const near = v.root.position.distanceToSquared(focusPoint()) < reach * reach;
    v.root.visible = near;
    if (!near) continue;
    setAnim(v, speed > 0.3 ? (speed > 6 ? "run" : "walk") : t.working && v.acts.work ? "work" : "idle",
            speed > 0.3 ? Math.max(0.6, speed / (speed > 6 ? 7.5 : 3.6)) : 1);
    v.mixer.update(dt);
  }
}

function updateLabels(){
  // Measured from what you are looking at: in the overview the camera is high
  // above, and distance from it says nothing about what is on screen.
  const cp = focusPoint();
  const zoomK = camMode === "strategy" ? Math.max(1, sDist / 70) : 1;
  for (const p of Object.values(S.places)){
    const d = Math.hypot(cp.x - p.c.x, cp.z - p.c.z);
    // Near names only: a dozen far-off names stacked on the horizon sat on
    // top of whatever building was in front of you.
    p.label.visible = d < 170 * zoomK && (camMode === "strategy" || d > 8);
    p.label.element.style.opacity = d < 40 ? 0.6 : 1;
  }
  const marks = (S.ADV && S.ADV.markers) || {};
  for (const v of S.buildings.values()){
    const d = cp.distanceTo(v.pos), mk = marks[v.b.id];
    const lbl = v.root.userData.label;
    // A building with something for you shows from further off.
    lbl.visible = d < 120 * zoomK || (mk && ((mk.icons && mk.icons.length) || mk.health) && d < 280 * zoomK);
    const html = signHTML(v.b, mk);
    if (lbl.element.innerHTML !== html) lbl.element.innerHTML = html;
  }
  for (const k of S.DATA.cities || []) if (k.label){
    const m = S.places[k.market]; k.label.visible = m && (camMode === "strategy" ? sDist > 200 : Math.hypot(cp.x - m.c.x, cp.z - m.c.z) > 120);
  }
}

/* ------------------------------------------------------------ hover and placement */
/* THE SQUARE UNDER YOUR CURSOR GLOWS, the way Offworld Trading Company lights
   the hex you are about to click: bright on free land, dim on someone's.
   PLACEMENT: pick a building from the build menu and a hologram of it rides
   under the cursor on the 2x2 block of squares it would take -- green where it
   can go, red where it cannot, with the reason. Click to build there. */
function glowSquare(colour){
  const g = new THREE.Group();
  const fill = new THREE.Mesh(new THREE.PlaneGeometry(CELL - 0.3, CELL - 0.3),
    new THREE.MeshBasicMaterial({color: colour, transparent: true, opacity: 0.32, depthWrite: false, blending: THREE.AdditiveBlending}));
  fill.rotation.x = -Math.PI / 2;
  const e = CELL / 2 - 0.15;
  const ring = new THREE.LineLoop(new THREE.BufferGeometry().setFromPoints(
    [[-e, -e], [e, -e], [e, e], [-e, e]].map(([x, z]) => new THREE.Vector3(x, 0, z))),
    new THREE.LineBasicMaterial({color: colour, transparent: true, opacity: 1}));
  const edge = new THREE.Mesh(new THREE.RingGeometry(0, 0.01, 4), new THREE.MeshBasicMaterial({visible: false}));
  g.add(fill, ring, edge); g.userData = {fill, ring};
  g.position.y = 0.16; g.visible = false; g.renderOrder = 5;
  scene.add(g);
  return g;
}
const hoverSq = glowSquare("#7ff3ff");
const blockSq = [0, 1, 2, 3].map(() => glowSquare("#7dff8a"));
let placing = null;                // {type, ghost, cells, place, valid, why}
let lastGround = null;

function holo(type){
  const key = MODEL_FOR_TYPE[type];
  let body;
  if (key && MODELS[key]){
    const M = MODELS[key];
    body = M.scene.clone(true);
    body.scale.setScalar(M.scale); body.position.set(-M.cx, M.lift, -M.cz);
  } else {
    body = new THREE.Group();
    const walls = new THREE.Mesh(new THREE.BoxGeometry(10, 6, 9)); walls.position.y = 3;
    const roof = new THREE.Mesh(new THREE.ConeGeometry(8.2, 4, 4)); roof.rotation.y = Math.PI / 4; roof.position.y = 8;
    body.add(walls, roof);
  }
  // A hologram: see-through cyan, with its edges drawn bright so the shape
  // reads on any ground.
  const mat = new THREE.MeshBasicMaterial({color: "#4fe0ff", transparent: true, opacity: 0.6, depthWrite: false});
  const lines = new THREE.LineBasicMaterial({color: "#c8f7ff", transparent: true, opacity: 0.85});
  const edges = [];
  body.traverse(o => {
    if (!o.isMesh) return;
    o.material = mat; o.raycast = () => {};
    if (!key) edges.push(o);
  });
  for (const o of edges) o.add(new THREE.LineSegments(new THREE.EdgesGeometry(o.geometry), lines));
  if (key){
    // Meshy models are dense; a bounding outline reads cleaner than every edge.
    const box = new THREE.Box3().setFromObject(body), size = box.getSize(new THREE.Vector3());
    const frame = new THREE.LineSegments(new THREE.EdgesGeometry(new THREE.BoxGeometry(size.x, size.y, size.z)), lines);
    frame.position.copy(box.getCenter(new THREE.Vector3()));
    body.parent ? null : null;
    lines.userData.frame = frame;
  }
  const root = new THREE.Group(); root.add(body); root.userData.mat = mat; root.userData.lines = lines;
  if (lines.userData.frame) root.add(lines.userData.frame);
  const el = document.createElement("div"); el.className = "holo-tag";
  const tag = new CSS2DObject(el); tag.position.set(0, 13, 0); root.add(tag); root.userData.tag = tag;
  scene.add(root);
  return root;
}
function startPlacing(type){
  stopPlacing();
  clearSelection();
  placing = {type, ghost: holo(type)};
  renderer.domElement.style.cursor = "crosshair";
  UI.toast(`Choose where to build the ${type.split(" /")[0]}: click to place, Esc to cancel`);
  if (lastGround) updatePlacement(lastGround);
}
function stopPlacing(){
  if (!placing) return;
  scene.remove(placing.ghost);
  placing.ghost.traverse(o => { if (o.isCSS2DObject) o.element.remove(); });
  placing = null;
  for (const b of blockSq) b.visible = false;
  renderer.domElement.style.cursor = "default";
  UI.placingChanged(null);
}
function updatePlacement(point){
  if (!placing) return;
  // The block whose shared corner is nearest the cursor: the cursor sits in its middle.
  const gx = Math.round(point.x / CELL) - 1, gz = Math.round(point.z / CELL) - 1;
  const keys = [`${gx},${gz}`, `${gx + 1},${gz}`, `${gx},${gz + 1}`, `${gx + 1},${gz + 1}`];
  const cells = keys.map(k => S.cells.get(k));
  const cx = (gx + 1) * CELL, cz = (gz + 1) * CELL;
  const spec = (S.BOARD ? S.BOARD.business_types : []).find(t => t.name === placing.type) || {cost: 0, spur: false};
  const cash = S.ST ? S.ST.you.denari : 0;
  let why = "";
  const place = cells[0] && cells[0].place;
  if (!cells.every(Boolean)) why = "Build on a place's squares";
  else if (!cells.every(c => c.place === place)) why = "All four squares must be in one place";
  else if (cells.some(c => S.cellOwner.has(c.key))) why = "Those squares are not free";
  else if ((S.places[place].kind === "spur") !== !!spec.spur) why = spec.spur ? "Farms and mines need spur land" : "This belongs on the main road, not a spur";
  else if (cash < spec.cost) why = `Need ${Math.ceil(spec.cost - cash)} more`;
  placing.valid = !why; placing.why = why; placing.cells = keys; placing.place = place;
  const g = placing.ghost;
  g.position.set(cx, 0, cz);
  if (place){ const pc = S.places[place].c; g.rotation.y = Math.atan2(pc.x - cx, pc.z - cz); }
  g.userData.mat.color.set(why ? "#ff6a5a" : "#3fd8ff");
  g.userData.lines.color.set(why ? "#ffd0c8" : "#c8f7ff");
  g.userData.tag.element.innerHTML = why ? `<b>${esc(placing.type.split(" /")[0])}</b><small class="no">${esc(why)}</small>`
    : `<b>${esc(placing.type.split(" /")[0])} \u00b7 ${Math.round(spec.cost)}</b><small>${esc(place)} \u00b7 click to build</small>`;
  keys.forEach((k, i) => {
    const sq = blockSq[i];
    sq.position.set((gx + (i % 2) + 0.5) * CELL, 0.17, (gz + Math.floor(i / 2) + 0.5) * CELL);
    const col = why ? "#ff6a5a" : "#7dff8a";
    sq.userData.fill.material.color.set(col); sq.userData.ring.material.color.set(col);
    sq.visible = true;
  });
  UI.placingChanged(placing.type);
}
function confirmPlacement(){
  if (!placing) return;
  if (!placing.valid){ UI.toast(placing.why, "bad"); return; }
  const {type, place, cells} = placing;
  stopPlacing();
  foundOn(place, cells, type);
}
function groundPoint(e){
  ndc.set(e.clientX / innerWidth * 2 - 1, -(e.clientY / innerHeight) * 2 + 1);
  ray.setFromCamera(ndc, camera);
  const g = ray.intersectObject(S.ground)[0];
  return g ? g.point : null;
}
function updateHover(e){
  const p = groundPoint(e);
  lastGround = p;
  if (placing){ hoverSq.visible = false; if (p) updatePlacement(p); return; }
  const c = p && cellAt(p);
  if (!p){ hoverSq.visible = false; return; }
  const gx = Math.floor(p.x / CELL), gz = Math.floor(p.z / CELL);
  hoverSq.position.set((gx + 0.5) * CELL, 0.16, (gz + 0.5) * CELL);
  const owned = c && S.cellOwner.has(c.key);
  const colour = !c ? "#ffffff" : owned ? "#ffb35a" : "#7ff3ff";
  hoverSq.userData.fill.material.color.set(colour); hoverSq.userData.ring.material.color.set(colour);
  hoverSq.userData.fill.material.opacity = !c ? 0.12 : owned ? 0.2 : 0.38;
  hoverSq.visible = true;
}

/* ------------------------------------------------------------ input */
const pointer = {down: false, x: 0, y: 0, moved: 0, button: 0};
const ray = new THREE.Raycaster(), ndc = new THREE.Vector2();
function pick(e, includeGround){
  ndc.set(e.clientX / innerWidth * 2 - 1, -(e.clientY / innerHeight) * 2 + 1);
  ray.setFromCamera(ndc, camera);
  const targets = [];
  for (const v of S.buildings.values()) targets.push(v.root);
  for (const v of S.agents.values()) if (v.root.visible) targets.push(v.root);
  if (S.player) targets.push(S.player.root);
  const hit = ray.intersectObjects(targets, true).find(h => h.object.userData.pick);
  if (hit) return hit.object.userData.pick;
  if (includeGround){
    const g = ray.intersectObject(S.ground)[0];
    if (g) return {kind: "ground", point: g.point};
  }
  return null;
}
renderer.domElement.addEventListener("pointerdown", e => {
  pointer.down = true; pointer.x = e.clientX; pointer.y = e.clientY; pointer.moved = 0; pointer.button = e.button;
  renderer.domElement.setPointerCapture(e.pointerId);
});
renderer.domElement.addEventListener("pointermove", e => {
  if (pointer.down){
    const dx = e.clientX - pointer.x, dy = e.clientY - pointer.y;
    pointer.moved += Math.abs(dx) + Math.abs(dy);
    pointer.x = e.clientX; pointer.y = e.clientY;
    if (pointer.moved > 4){
      if (camMode === "strategy" && pointer.button === 0){
        // Drag the map: the ground under the cursor follows it.
        const k = sDist * 0.0016;
        const fwd = new THREE.Vector3(-Math.sin(yaw), 0, -Math.cos(yaw));
        const right = new THREE.Vector3(Math.cos(yaw), 0, -Math.sin(yaw));
        focusGoal.addScaledVector(right, -dx * k).addScaledVector(fwd, dy * k / Math.sin(sPitch));
        focus.copy(focusGoal);
      } else if (camMode === "strategy"){
        yaw -= dx * 0.005;
        sPitch = Math.max(0.35, Math.min(1.35, sPitch + dy * 0.004));
      } else {
        yaw -= dx * 0.0055;
        pitch = Math.max(0.04, Math.min(1.45, pitch + dy * 0.004));
      }
    }
    return;
  }
  hover(e);
  updateHover(e);
});
renderer.domElement.addEventListener("pointerup", e => {
  pointer.down = false;
  if (pointer.moved > 4) return;
  if (placing){
    if (e.button === 2) stopPlacing(); else confirmPlacement();
    return;
  }
  const p = pick(e, true);
  if (!p) return;
  if (p.kind === "building") UI.openBuilding(p.id);
  else if (p.kind === "agent") UI.openPerson(p.id);
  else if (p.kind === "you") UI.openTab("here");
  else if (p.kind === "ground"){
    // A free square: pick it. An owned one: open what stands there. Elsewhere: walk.
    const c = cellAt(p.point);
    const own = c && S.cellOwner.get(c.key);
    if (c && !own) toggleCell(c);
    else if (own && own.business && S.buildings.has(own.business)) UI.openBuilding(own.business);
    else { if (S.selected.size) clearSelection(); walkToPoint(p.point); }
  }
});
renderer.domElement.addEventListener("wheel", e => {
  e.preventDefault();
  const out = e.deltaY > 0, f = out ? 1.12 : 1 / 1.12;
  if (camMode === "strategy"){
    // All the way in, close to yourself: take control.
    if (!out && sDist <= S_MIN + 0.5 && S.player && focus.distanceTo(S.player.root.position) < 40){ enterThird(); return; }
    sDist = Math.max(S_MIN, Math.min(S_MAX, sDist * f));
  } else {
    if (out && dist >= THIRD_OUT){ sDist = 45; enterStrategy(S.player.root.position); return; }
    dist = Math.max(3, Math.min(THIRD_OUT, dist * f));
  }
}, {passive: false});
renderer.domElement.addEventListener("contextmenu", e => e.preventDefault());
let lastHover = 0;
function hover(e){
  if (placing){ $("tooltip").style.display = "none"; return; }
  const now = performance.now(); if (now - lastHover < 90) return; lastHover = now;
  const p = pick(e, false), tip = $("tooltip");
  renderer.domElement.style.cursor = p ? "pointer" : "default";
  if (!p || p.kind === "you"){ tip.style.display = "none"; return; }
  let text = "";
  if (p.kind === "building"){ const v = S.buildings.get(p.id); text = v ? `${v.b.type} — ${v.b.owner === G.you ? "yours" : short(ownerName(v.b.owner))}` : ""; }
  if (p.kind === "agent") text = short(ownerName(p.id));
  tip.textContent = text; tip.style.display = text ? "block" : "none";
  tip.style.left = `${e.clientX + 14}px`; tip.style.top = `${e.clientY + 12}px`;
}
const typing = () => /INPUT|SELECT|TEXTAREA/.test((document.activeElement || {}).tagName || "");
addEventListener("keydown", e => {
  if (typing()) return;
  const k = e.key.toLowerCase();
  if (k === "escape"){ if (placing){ stopPlacing(); return; } UI.close(); return; }
  if (k === "tab"){ e.preventDefault(); toggleCamera(); return; }
  if (k === "f"){ camMode === "strategy" ? flyTo(S.player.root.position) : findMe(); return; }
  if (k === "e"){ usePrompt(); return; }
  if (["w", "a", "s", "d", "arrowup", "arrowdown", "arrowleft", "arrowright", "shift"].includes(k)){
    keys.add(k); if (k.startsWith("arrow")) e.preventDefault();
  }
});
addEventListener("keyup", e => keys.delete(e.key.toLowerCase()));
addEventListener("blur", () => keys.clear());

function walkToPoint(point, then){
  autoTarget = new THREE.Vector3(point.x, 0, point.z);
  autoOnArrive = then || null;
  marker.position.set(point.x, 0.15, point.z); marker.visible = true;
}
function walkToPlace(name, then){
  const p = S.places[name]; if (!p) return;
  walkToPoint(p.c, then);
}
function walkToBuilding(id, then){
  const v = S.buildings.get(id); if (!v) return;
  const place = S.places[v.b.place];
  const toward = place ? place.c.clone().sub(v.pos).setY(0).normalize() : new THREE.Vector3(0, 0, 1);
  walkToPoint(v.pos.clone().addScaledVector(toward, BUILDING_W * 0.62), then);
}
function findMe(){
  if (!S.player) return;
  yaw = S.player.heading + Math.PI; dist = 7; pitch = 0.2;
}

/* Fast travel: the simulation's own timed road. The screen goes dark while
   the clock runs, and the player appears at the other end. */
async function fastTravel(place){
  const r = await UI.act("travel_to", {destination: place});
  if (!r.ok) return;
  S.travelling = place;
  $("tr-title").textContent = `Travelling to ${place}`;
  $("travel").classList.add("on");
}
function checkTravel(){
  const st = S.ST; if (!st) return;
  const on = /^Travelling/.test(st.activity || "");
  if (on){ $("travel").classList.add("on"); $("tr-sub").textContent = st.activity; if (!S.travelling) S.travelling = st.location; return; }
  if (S.travelling){
    const dest = S.places[st.location];
    if (dest && S.player){
      S.player.root.position.set(dest.c.x + 2, 0, dest.c.z + 3); S.here = st.location;
      if (camMode === "strategy"){ focusGoal.copy(S.player.root.position); focus.copy(focusGoal); }
    }
    S.travelling = null;
    $("travel").classList.remove("on");
  }
}

/* ------------------------------------------------------------ production timers */
/* WHAT EACH WORKER IS MAKING, AND HOW LONG UNTIL THE NEXT ONE. A ring that
   fills as the unit is made, the item, and the real seconds left. The server
   sends each worked business's progress and rate every two seconds (read with
   the engine's own production functions); between answers it runs forward on
   the game clock, so the ring moves smoothly and empties when the unit lands. */
let PROD = null;
async function pollProduction(){
  try { PROD = await api.get("/api/production"); } catch (e) { return; }
  if (LIFE) LIFE.setProduction(PROD);
}
setInterval(pollProduction, 2000);
const RING = 2 * Math.PI * 8;
function timerFor(person){
  if (person.timer) return person.timer;
  const el = document.createElement("div"); el.className = "ptimer";
  el.innerHTML = `<svg viewBox="0 0 20 20"><circle class="bg" cx="10" cy="10" r="8" fill="none" stroke-width="3"/>`
    + `<circle class="fg" cx="10" cy="10" r="8" fill="none" stroke-width="3" stroke-dasharray="${RING}" stroke-dashoffset="${RING}"/></svg><span></span>`;
  const lbl = new CSS2DObject(el); lbl.position.set(0, HUMAN_H + 0.45, 0);
  person.root.add(lbl);
  person.timer = lbl;
  return lbl;
}
function updateTimers(){
  const byWorker = {};
  if (PROD) for (const [bid, b] of Object.entries(PROD.businesses)) for (const w of b.workers) byWorker[w] = b;
  const pace = (S.ST && !S.ST.paused) ? S.ST.pace : 0;
  const people = [...S.agents.values()];
  if (S.player) people.push(S.player);
  for (const p of people){
    const id = p === S.player ? G.you : p.id;
    const b = byWorker[id];
    const near = p.root.visible !== false && (camMode === "third" ? p.root.position.distanceTo(camera.position) < 70 : sDist < 45 && p.root.position.distanceTo(focus) < 60);
    if (!b || !near){ if (p.timer) p.timer.visible = false; continue; }
    const t = timerFor(p); t.visible = true;
    const el = t.element;
    el.classList.toggle("you", p === S.player);
    el.classList.toggle("blocked", b.blocked);
    let frac = b.progress, label;
    if (b.blocked){
      label = `${esc(b.item)} <small>stalled${b.why ? ": " + esc(String(b.why).split(/[.;(]/)[0].slice(0, 40)) : ""}</small>`;
    } else {
      // Run forward on the game clock since the server's answer.
      const hours = Math.max(0, S.HOUR - PROD.hour);
      frac = (b.progress + b.per_hour * hours) % 1;
      const realSecs = pace ? (1 - frac) / b.per_hour * 3600 / pace : null;
      label = `${esc(b.item)} <small>${realSecs == null ? "paused" : realSecs < 60 ? `${Math.ceil(realSecs)}s` : `${Math.ceil(realSecs / 60)}m`} \u00b7 ${b.per_hour >= 1 ? Math.round(b.per_hour) + "/h" : (60 / b.per_hour).toFixed(0) + " min each"}</small>`;
    }
    el.querySelector(".fg").setAttribute("stroke-dashoffset", String(RING * (1 - frac)));
    const span = el.querySelector("span");
    if (span.innerHTML !== label) span.innerHTML = label;
  }
}

/* ------------------------------------------------------------ walk-up prompt */
/* Walk up to a building or a person and a prompt says what E will do, the
   way a third-person game offers "enter" or "talk" at a door. */
let promptFor = null;
function updatePrompt(){
  const P = S.player; if (!P) return;
  const me = P.root.position;
  let best = null, bd = 1e9;
  for (const v of S.buildings.values()){
    const d = Math.hypot(me.x - v.pos.x, me.z - v.pos.z) - BUILDING_W * 0.42;
    if (d < 6 && d < bd){ best = {kind: "building", id: v.b.id, label: `Open the ${SHORT_TYPE[v.b.type] || v.b.type}${v.b.owner === G.you ? " (yours)" : ` \u2014 ${short(ownerName(v.b.owner))}`}`}; bd = d; }
  }
  for (const v of S.agents.values()){
    const d = v.root.position.distanceTo(me);
    if (d < 3.2 && d < bd){ best = {kind: "agent", id: v.id, label: `Talk to ${short(ownerName(v.id))}`}; bd = d; }
  }
  promptFor = best;
  const el = $("eprompt");
  el.style.display = best && !S.travelling ? "flex" : "none";
  if (best) $("ep-text").textContent = best.label;
}
function usePrompt(){
  if (!promptFor) return;
  if (promptFor.kind === "building") UI.openBuilding(promptFor.id); else UI.openPerson(promptFor.id);
}
$("eprompt").addEventListener("click", usePrompt);

/* ------------------------------------------------------------ waypoint */
/* Where you are walking to: a column of light over it, and a line on the
   ground from you to it. */
const beam = new THREE.Mesh(new THREE.CylinderGeometry(0.9, 0.9, 60, 16, 1, true),
  new THREE.MeshBasicMaterial({color: "#ffd966", transparent: true, opacity: 0.28, depthWrite: false, side: THREE.DoubleSide, fog: false}));
beam.position.y = 30; beam.visible = false; scene.add(beam);
const wayGeo = new THREE.BufferGeometry().setFromPoints([new THREE.Vector3(), new THREE.Vector3()]);
const wayLine = new THREE.Line(wayGeo, new THREE.LineDashedMaterial({color: "#ffe9a8", dashSize: 1.2, gapSize: 0.8, transparent: true, opacity: 0.9}));
wayLine.visible = false; wayLine.frustumCulled = false; scene.add(wayLine);
function updateWaypoint(){
  const on = !!autoTarget && !!S.player;
  beam.visible = wayLine.visible = on;
  if (!on) return;
  beam.position.x = autoTarget.x; beam.position.z = autoTarget.z;
  const a = S.player.root.position;
  const pos = wayGeo.attributes.position;
  pos.setXYZ(0, a.x, 0.25, a.z); pos.setXYZ(1, autoTarget.x, 0.25, autoTarget.z);
  pos.needsUpdate = true; wayLine.computeLineDistances();
}

/* ------------------------------------------------------------ minimap */
const mm = $("minimap"), mg = mm.getContext("2d");
let mmBox = null;
function minimapBox(){
  const P = S.player; if (!P) return null;
  const city = nearestPlace(P.root.position);
  const pts = Object.values(S.places).filter(p => !city || p.city === city.city);
  const xs = pts.map(p => p.c.x), zs = pts.map(p => p.c.z);
  const pad = 40;
  return {x0: Math.min(...xs) - pad, x1: Math.max(...xs) + pad, z0: Math.min(...zs) - pad, z1: Math.max(...zs) + pad, city};
}
function drawMinimap(){
  mmBox = minimapBox(); if (!mmBox) return;
  const W = mm.width, H = mm.height;
  const k = Math.min(W / (mmBox.x1 - mmBox.x0), H / (mmBox.z1 - mmBox.z0));
  const ox = (W - (mmBox.x1 - mmBox.x0) * k) / 2, oz = (H - (mmBox.z1 - mmBox.z0) * k) / 2;
  const sx = x => ox + (x - mmBox.x0) * k, sz = z => oz + (z - mmBox.z0) * k;
  mmBox.k = k; mmBox.ox = ox; mmBox.oz = oz;
  mg.fillStyle = "#3d6a33"; mg.fillRect(0, 0, W, H);
  const D = S.DATA;
  mg.fillStyle = "#3d7fb5";
  const rx = (D.river.axis - CY) * SCALE, rh = D.river.half * SCALE;
  mg.fillRect(sx(rx - rh), 0, rh * 2 * k, H);
  for (const r of D.river.borders || []){ const z = (r.axis - CX) * SCALE, h2 = r.half * SCALE; mg.fillRect(0, sz(z - h2), W, h2 * 2 * k); }
  mg.strokeStyle = "#d7bd85"; mg.lineCap = "round";
  for (const [ax, az, bx, bz, hw] of roadSegs){
    mg.lineWidth = Math.max(1.5, hw * 2 * k); mg.beginPath(); mg.moveTo(sx(ax), sz(az)); mg.lineTo(sx(bx), sz(bz)); mg.stroke();
  }
  for (const p of Object.values(S.places)){
    mg.fillStyle = "#b59a63aa"; mg.beginPath(); mg.arc(sx(p.c.x), sz(p.c.z), Math.max(3, p.r * k * 0.8), 0, 7); mg.fill();
  }
  for (const v of S.buildings.values()){
    mg.fillStyle = v.b.owner === G.you ? "#8fe36a" : "#e9d18c";
    mg.fillRect(sx(v.pos.x) - 3, sz(v.pos.z) - 3, 6, 6);
  }
  mg.fillStyle = "#ffffff";
  for (const v of S.agents.values()){ mg.beginPath(); mg.arc(sx(v.root.position.x), sz(v.root.position.z), 2.2, 0, 7); mg.fill(); }
  if (autoTarget){
    mg.strokeStyle = "#ffd966"; mg.lineWidth = 3;
    const tx = sx(autoTarget.x), tz = sz(autoTarget.z);
    mg.beginPath(); mg.moveTo(tx - 6, tz - 6); mg.lineTo(tx + 6, tz + 6); mg.moveTo(tx + 6, tz - 6); mg.lineTo(tx - 6, tz + 6); mg.stroke();
  }
  // The camera's view, and you.
  const P = S.player.root.position, px = sx(P.x), pz = sz(P.z);
  const fx = -Math.sin(yaw), fz = -Math.cos(yaw);
  if (camMode === "strategy"){
    const r = Math.max(4, sDist * 0.9 * k);
    mg.strokeStyle = "rgba(255,255,255,0.75)"; mg.lineWidth = 1.5;
    mg.strokeRect(sx(focus.x) - r, sz(focus.z) - r * 0.65, r * 2, r * 1.3);
  }
  mg.fillStyle = "rgba(255,255,255,0.18)";
  mg.beginPath(); mg.moveTo(px, pz);
  const a0 = Math.atan2(fz, fx);
  mg.arc(px, pz, 46, a0 - 0.5, a0 + 0.5); mg.closePath(); mg.fill();
  mg.save(); mg.translate(px, pz); mg.rotate(-S.player.heading + Math.PI);
  mg.fillStyle = "#e8463a"; mg.strokeStyle = "#fff"; mg.lineWidth = 2;
  mg.beginPath(); mg.moveTo(0, -9); mg.lineTo(6, 7); mg.lineTo(0, 3); mg.lineTo(-6, 7); mg.closePath(); mg.fill(); mg.stroke();
  mg.restore();
  const here = placeAt(S.player.root.position);
  $("mm-cap").textContent = here ? `${here.name} · ${here.cityName}` : `Near ${nearestPlace(S.player.root.position).name}`;
}
mm.addEventListener("click", e => {
  if (!mmBox) return;
  const r = mm.getBoundingClientRect();
  const x = (e.clientX - r.left) * (mm.width / r.width), z = (e.clientY - r.top) * (mm.height / r.height);
  const at = new THREE.Vector3(mmBox.x0 + (x - mmBox.ox) / mmBox.k, 0, mmBox.z0 + (z - mmBox.oz) / mmBox.k);
  if (camMode === "strategy" && !e.shiftKey) flyTo(at); else walkToPoint(at);
});

/* ------------------------------------------------------------ portrait */
function drawPortrait(){
  const c = $("portrait-c");
  const r = new THREE.WebGLRenderer({canvas: c, alpha: true, antialias: true});
  r.setSize(c.width, c.height, false); r.outputColorSpace = THREE.SRGBColorSpace;
  const sc = new THREE.Scene();
  sc.add(new THREE.HemisphereLight("#ffffff", "#445566", 2.2));
  const l = new THREE.DirectionalLight("#fff0dd", 2); l.position.set(1, 2, 3); sc.add(l);
  const p = makePerson(PLAYER_CHARACTER);
  p.mixer.update(0);
  sc.add(p.root);
  const cam = new THREE.PerspectiveCamera(30, 1, 0.01, 50);
  cam.position.set(0, HUMAN_H * 0.86, 1.25); cam.lookAt(0, HUMAN_H * 0.84, 0);
  r.render(sc, cam);
  r.dispose();
}

/* ------------------------------------------------------------ the loop */
let last = performance.now(), mmAt = 0, lblAt = 0;
function liveHour(){
  const st = S.ST; if (!st) return S.HOUR;
  if (st.paused) return st.hour;
  const ahead = (performance.now() - S.base.at) / 1000 * st.pace / 3600;
  return S.base.hour + Math.min(ahead, 5 * st.pace / 3600);
}
function animate(now){
  frame(now);
  requestAnimationFrame(animate);
}
/* A hidden tab gets no animation frames at all. The world still moves on the
   server, so a fallback timer keeps the page up to date -- and it is what lets
   the page be checked from a browser that is not on screen. */
setInterval(() => { const now = performance.now(); if (now - last > 250) frame(now); }, 100);
function frame(now){
  if (!S.player) return;
  const dt = Math.min(0.1, (now - last) / 1000); last = now;
  S.HOUR = liveHour();
  updatePlayer(dt);
  updateCamera(dt);
  updateAgents(dt);
  if (S.water && S.water.map) S.water.map.offset.y += dt * 0.01;
  WIND.value += dt;
  const glow = 0.5 + 0.5 * Math.sin(now / 220);
  hoverSq.userData.ring.material.opacity = 0.6 + 0.4 * glow;
  if (placing){
    placing.ghost.userData.mat.opacity = 0.5 + 0.15 * glow;
    placing.ghost.position.y = 0.15;
    for (const b of blockSq) b.userData.fill.material.opacity = 0.3 + 0.2 * glow;
  }
  for (const c of clouds){
    c.position.x += c.userData.speed * dt;
    if (c.position.x > c.userData.span / 2) c.position.x = -c.userData.span / 2;
  }
  // A new building springs up: grows past full size and settles.
  for (const v of S.buildings.values()){
    if (!v.pop) continue;
    const k = (now - v.born) / 700;
    if (k >= 1){ v.root.scale.setScalar(1); v.pop = false; continue; }
    // Rises out of the ground and settles, with a small overshoot.
    const s = k < 0.6 ? (k / 0.6) * 1.04 : 1 + 0.04 * (1 - (k - 0.6) / 0.4);
    v.root.scale.set(1, Math.max(0.01, s), 1);
  }
  if (now - lblAt > 200){ lblAt = now; updateLabels(); updatePrompt(); }
  updateWaypoint();
  updateTimers();
  if (LIFE) LIFE.update(dt);
  if (now - mmAt > 150){ mmAt = now; drawMinimap(); }
  renderer.render(scene, camera);
  labels.render(scene, camera);
}

/* For poking at from the console: window.convoy.camera, .S, .scene. */
window.convoy = {camera, scene, S, renderer, set idleAt(v){ IDLE_AT = v; for (const p of [S.player, ...S.agents.values()]) if (p && p.acts.idle){ p.acts.idle.time = v * p.acts.idle.getClip().duration; } }, get yaw(){ return yaw; }, get pitch(){ return pitch; }, get dist(){ return dist; },
  view(y, p, d){ yaw = y ?? yaw; pitch = p ?? pitch; dist = d ?? dist; },
  get mode(){ return camMode; }, third: () => enterThird(), overview: (d) => { if (d) sDist = d; enterStrategy(); },
  look(x, z, d){ focusGoal.set(x, 0, z); focus.copy(focusGoal); if (d) sDist = d; },
  hold(k, ms){ keys.add(k); setTimeout(() => keys.delete(k), ms); },
  teleport(x, z){ S.player.root.position.set(x, 0, z); }};

/* ------------------------------------------------------------ start */
const UI = createUI({api, S, walkToPlace, walkToBuilding, fastTravel, findMe, short,
  onStatus: () => checkTravel(), toggleCamera: () => toggleCamera(), mode: () => camMode,
  foundOn: (p, c, t) => foundOn(p, c, t), buyOn: (p, c) => buyOn(p, c), clearSelection: () => clearSelection(),
  startPlacing: t => startPlacing(t), stopPlacing: () => stopPlacing()});
let LIFE = null;
function startLife(){
  LIFE = createLife({THREE, scene, S, camera, CSS2DObject, G, api, BUILDING_W, short,
    openBuilding: id => UI.openBuilding(id), flyTo: (v, d) => flyTo(v, d),
    focusPoint, isStrategy: () => camMode === "strategy", viewDist: () => sDist});
  window.convoyLife = LIFE;
  landKey = "";                                        // repaint the plots in owners' colours
}

(async function start(){
  const bar = $("cover-bar"), msg = $("cover-msg");
  try {
    msg.textContent = "Reading the valley…";
    S.DATA = await api.get("/replay");
    if (!S.DATA || !S.DATA.places){ msg.textContent = "No game is running. Start one from the start screen."; return; }
    PLOTS = await api.get("/api/plots");
    buildWorld(S.DATA, PLOTS.totals || {});
    bar.style.width = "10%";
    msg.textContent = "Calling the townsfolk…";
    await loadModels(k => { bar.style.width = `${10 + k * 80}%`; });
    await UI.boot();
    const st = S.ST, place = (S.OBS && S.OBS.you.location) || (st && st.location);
    S.HOUR = st ? st.hour : S.DATA.end_hour;
    startLife(); syncLand(); syncBuildings(); syncAgents(); pollProduction();
    S.ready = true;
    setInterval(pollPlots, 4000);
    spawnPlayer(place);
    drawPortrait();
    findMe();
    // Open in the overview, over your own patch of the valley.
    enterStrategy(S.player.root.position); sDist = 48;
    camera.position.copy(S.player.root.position).add(new THREE.Vector3(0, 80, 60));
    bar.style.width = "100%";
    setTimeout(() => $("cover").remove(), 250);
    requestAnimationFrame(animate);
    setInterval(async () => {
      try {
        const d = await api.get("/replay");
        if (d && d.places){ S.DATA = d; syncLand(); syncBuildings(); syncAgents(); }
      } catch (e) { /* the next one will do */ }
    }, 4000);
  } catch (err) {
    console.error(err);
    msg.textContent = `Something went wrong: ${err.message || err}`;
  }
})();
