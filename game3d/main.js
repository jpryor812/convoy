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
import { createFight } from "./fight.js";
import { createConvoy } from "./convoy.js";
import { createHexMap } from "./hexmap.js";
import { createTerrain, HAZE_GLSL } from "./terrain.js";
import { createFlora } from "./flora.js";
import { TUNE, readIntent, createWalker, createRider } from "./move.js";
import { EffectComposer } from "three/addons/postprocessing/EffectComposer.js";
import { RenderPass } from "three/addons/postprocessing/RenderPass.js";
import { ShaderPass } from "three/addons/postprocessing/ShaderPass.js";
import { OutputPass } from "three/addons/postprocessing/OutputPass.js";
import { RGBELoader } from "three/addons/loaders/RGBELoader.js";

const G = window.GAME;
const $ = id => document.getElementById(id);

/* ------------------------------------------------------------ constants */
const SCALE = 0.15;               // world metres -> scene units (tighter, 2026-10-17)
const CELL = 6.5;                 // one grid square: one plot. A business is 2x2.
const WALK = 4.6, RUN = 9.5;      // units per second
const HUMAN_H = 1.8;
let IDLE_AT = 0.25;               // where in the walk cycle a standing figure is held
const BUILDING_W = 13;            // a business's footprint, in scene units
/* THE CAST (2026-10-19): rugged frontier people, made with Meshy and rigged
   with idle, walk, run, hammer swing, block and attack (scripts/meshy.py).
   The older cast is the fallback if the new one does not load. */
// Three types (designer, 2026-10-19), a man and a woman of each:
// cowboy / rancher, miner / drover, farmer / homesteader.
const NEW_CAST = {m: ["cowboy", "miner", "farmer"], f: ["rancher", "drover", "homesteader"]};
const OLD_CAST = {m: ["persian-man", "asian-man", "indian-man", "african-man"],
                  f: ["indian-woman", "african-woman", "persian-girl", "viking-girl", "asian-girl"]};
let CAST = NEW_CAST;
let CHARACTERS = [...NEW_CAST.m, ...NEW_CAST.f];
let PLAYER_CHARACTER = "cowboy";       // a woman's model if you chose to be one
const MODEL_FOR_TYPE = {
  "Tavern / Inn": "tavern", "Farm": "farm", "Refinery": "refinery",
  "Vehicle Dealer / Stable": "stable", "Weaponsmith / Armory": "blacksmith",
  "Mining Operation": "mine", "Your home": "home",
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
// No canvas MSAA: the frame goes through the composer's render targets, so
// it would only smooth the final full-screen quad -- cost for nothing.
const renderer = new THREE.WebGLRenderer({antialias: false, powerPreference: "low-power"});
renderer.setPixelRatio(Math.min(devicePixelRatio, 2));
renderer.setSize(innerWidth, innerHeight);
renderer.outputColorSpace = THREE.SRGBColorSpace;
renderer.toneMapping = THREE.ACESFilmicToneMapping;
renderer.toneMappingExposure = 1.0;
renderer.shadowMap.enabled = true;
renderer.shadowMap.type = THREE.PCFSoftShadowMap;
$("scene").appendChild(renderer.domElement);
const labels = new CSS2DRenderer();
labels.setSize(innerWidth, innerHeight);
$("labels").appendChild(labels.domElement);

const scene = new THREE.Scene();
// THE LOOK (2026-10-19): Red Dead's palette -- late afternoon, dust in the
// air, muted earth and sage -- not the bright Hay Day of 2026-10-17.
const HAZE = "#c9b996";
scene.fog = new THREE.Fog(HAZE, 180, 900);
/* HAZE LIES LOW (2026-11-01): dust and haze sit in the valleys and thin with
   height, so peaks stand clear above it, and what is far off cools toward
   blue -- distance read the way a painter reads it. Every material's fog,
   patched once before anything compiles. */
THREE.ShaderChunk.fog_pars_vertex = "#ifdef USE_FOG\n varying float vFogDepth; varying float vFogY;\n#endif";
THREE.ShaderChunk.fog_vertex = `#ifdef USE_FOG
  vFogDepth = - mvPosition.z;
  vFogY = (transpose(mat3(viewMatrix)) * (mvPosition.xyz - viewMatrix[3].xyz)).y;
#endif`;
THREE.ShaderChunk.fog_pars_fragment = `#ifdef USE_FOG
  uniform vec3 fogColor; varying float vFogDepth; varying float vFogY;
  #ifdef FOG_EXP2
    uniform float fogDensity;
  #else
    uniform float fogNear; uniform float fogFar;
  #endif
#endif`;
THREE.ShaderChunk.fog_fragment = `#ifdef USE_FOG
  #ifdef FOG_EXP2
    float fogFactor = 1.0 - exp(- fogDensity * fogDensity * vFogDepth * vFogDepth);
  #else
    float fogFactor = smoothstep(fogNear, fogFar, vFogDepth);
  #endif
  fogFactor *= mix(1.0, exp(- max(0.0, vFogY - 6.0) / 26.0), 0.85);
  vec3 fogTint = mix(fogColor, fogColor * vec3(0.8, 0.9, 1.1), smoothstep(fogNear, fogFar * 1.6, vFogDepth));
  gl_FragColor.rgb = mix(gl_FragColor.rgb, fogTint, fogFactor);
#endif`;
const camera = new THREE.PerspectiveCamera(55, innerWidth / innerHeight, 0.1, 3000);
addEventListener("resize", () => {
  renderer.setSize(innerWidth, innerHeight); labels.setSize(innerWidth, innerHeight);
  composer.setSize(innerWidth, innerHeight);
  camera.aspect = innerWidth / innerHeight; camera.updateProjectionMatrix();
});

/* Sky: a gradient dome, horizon pale, zenith blue -- the fallback when the
   photographed sky (loadLand) does not load. */
let skyDome = null;
{
  const geo = new THREE.SphereGeometry(2200, 32, 16);
  const mat = new THREE.ShaderMaterial({
    side: THREE.BackSide, depthWrite: false, fog: false,
    uniforms: {top: {value: new THREE.Color("#6f8ea3")}, bottom: {value: new THREE.Color("#e6d2a8")}},
    vertexShader: "varying vec3 p; void main(){ p = normalize(position); gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0); }",
    fragmentShader: "uniform vec3 top; uniform vec3 bottom; varying vec3 p; void main(){ float k = smoothstep(-0.05, 0.45, p.y); gl_FragColor = vec4(mix(bottom, top, k), 1.0); }",
  });
  skyDome = new THREE.Mesh(geo, mat);
  scene.add(skyDome);
}
// ART DIRECTION (2026-10-19): a low, warm sun with long soft shadows and a
// dusty sky fill; the colour grade (below) mutes and warms the rest.
scene.add(new THREE.HemisphereLight("#e2dccb", "#6f6648", 1.4));
const sun = new THREE.DirectionalLight("#ffd29a", 2.6);
const SUN_OFFSET = new THREE.Vector3(120, 165, 60);
sun.position.copy(SUN_OFFSET);
sun.castShadow = true;
sun.shadow.mapSize.set(2048, 2048);
sun.shadow.camera.left = -90; sun.shadow.camera.right = 90; sun.shadow.camera.top = 90; sun.shadow.camera.bottom = -90;
sun.shadow.camera.near = 10; sun.shadow.camera.far = 500;
sun.shadow.bias = -0.0006; sun.shadow.normalBias = 0.6; sun.shadow.radius = 3;
scene.add(sun, sun.target);
// Shadows are drawn round whatever you are looking at, and follow it.
function followSun(at){
  sun.target.position.set(Math.round(at.x / 4) * 4, 0, Math.round(at.z / 4) * 4);
  sun.position.copy(sun.target.position).add(SUN_OFFSET);
}

/* THE GRADE: the frame is finished like film -- colours pulled toward earth,
   warm highlights and cooler shadows, a soft vignette and a little grain. */
const composer = new EffectComposer(renderer);
composer.addPass(new RenderPass(scene, camera));
composer.addPass(new OutputPass());
const grade = new ShaderPass({
  uniforms: {tDiffuse: {value: null}, uTime: {value: 0}, uSat: {value: 0.92}, uWarm: {value: 0.07}, uVig: {value: 0.3}},
  vertexShader: "varying vec2 vUv; void main(){ vUv = uv; gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0); }",
  fragmentShader: `uniform sampler2D tDiffuse; uniform float uTime, uSat, uWarm, uVig; varying vec2 vUv;
    float rand(vec2 c){ return fract(sin(dot(c, vec2(12.9898, 78.233))) * 43758.5453); }
    void main(){
      vec3 c = texture2D(tDiffuse, vUv).rgb;
      float l = dot(c, vec3(0.299, 0.587, 0.114));
      c = mix(vec3(l), c, uSat);                                     // muted
      c += uWarm * vec3(0.9, 0.45, -0.35) * smoothstep(0.35, 0.95, l);   // warm highlights
      c += uWarm * vec3(-0.25, 0.0, 0.25) * (1.0 - smoothstep(0.0, 0.4, l)); // cool shadows
      c = (c - 0.5) * 1.06 + 0.5;                                    // a touch of contrast
      vec2 q = vUv - 0.5; c *= 1.0 - uVig * smoothstep(0.25, 0.85, length(q * vec2(1.15, 1.0)));
      c += (rand(vUv * 731.0 + uTime) - 0.5) * 0.025;                // grain
      gl_FragColor = vec4(clamp(c, 0.0, 1.0), 1.0);
    }`,
});
composer.addPass(grade);

/* GRAPHICS (2026-10-30): "the game makes my laptop very hot." Most of the
   heat is pixels and frames: a Retina screen at 2x is four times the pixels,
   and an uncapped loop draws 60-120 frames a second. Balanced (the default)
   draws 30 frames at 1.25x with smaller shadows; Battery saver drops shadows
   and the colour grade too; Sharp is how it was. Kept per browser. */
const QUALITY = {
  saver:    {fps: 30, dpr: 1,    shadow: 0,    grade: false},
  balanced: {fps: 30, dpr: 1.25, shadow: 1024, grade: true},
  sharp:    {fps: 60, dpr: 2,    shadow: 2048, grade: true},
};
let GFX = QUALITY.balanced;
function applyQuality(name){
  if (!QUALITY[name]) name = "balanced";
  GFX = QUALITY[name];
  const dpr = Math.min(devicePixelRatio, GFX.dpr);
  renderer.setPixelRatio(dpr); composer.setPixelRatio(dpr);
  renderer.setSize(innerWidth, innerHeight); composer.setSize(innerWidth, innerHeight);
  const shadows = GFX.shadow > 0;
  if (shadows && sun.shadow.mapSize.x !== GFX.shadow){
    sun.shadow.mapSize.set(GFX.shadow, GFX.shadow);
    if (sun.shadow.map){ sun.shadow.map.dispose(); sun.shadow.map = null; }
  }
  if (renderer.shadowMap.enabled !== shadows){
    renderer.shadowMap.enabled = shadows;
    scene.traverse(o => { if (o.material) [].concat(o.material).forEach(m => { m.needsUpdate = true; }); });
  }
  grade.enabled = GFX.grade;
  const sel = $("t-gfx"); if (sel) sel.value = name;
  try { localStorage.setItem("convoy.gfx", name); } catch (e) {}
}
{
  let saved = "balanced";
  try { saved = localStorage.getItem("convoy.gfx") || saved; } catch (e) {}
  applyQuality(saved);
  const sel = $("t-gfx"); if (sel) sel.onchange = () => applyQuality(sel.value);
}

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

/* ------------------------------------------------------------ the land's look */
/* POLY HAVEN (CC0, 2026-10-19; see art/generated/3d/polyhaven/CREDITS.md):
   photographed ground for the terrain, roads and rock, and a real late-day
   sky that lights the scene. Loaded before the world is built; if any of it
   fails the game still runs on the painted look. */
const PH = "/assets3d/polyhaven/";
let LAND = null, FLORA = null, GRASS = null;
async function loadLand(){
  const tl = new THREE.TextureLoader();
  const load = (n, srgb = true) => tl.loadAsync(PH + n).then(t => {
    t.wrapS = t.wrapT = THREE.RepeatWrapping; t.anisotropy = renderer.capabilities.getMaxAnisotropy();
    if (srgb) t.colorSpace = THREE.SRGBColorSpace;
    return t;
  });
  try {
    const [grass, moss, dry, trail, rock, sky, twig, twigA, bark, leaves, leavesA, blades, bladesA] = await Promise.all([
      load("grass_ground_diff_1k.jpg"), load("aerial_grass_rock_diff_1k.jpg"), load("dry_ground_01_diff_1k.jpg"),
      load("rocky_trail_diff_1k.jpg"), load("rock_face_diff_1k.jpg"),
      new RGBELoader().loadAsync(PH + "kloppenheim_06_puresky_2k.hdr"),
      load("fir_tree_01_twig_diff_1k.jpg"), load("fir_tree_01_twig_alpha_1k.png", false), load("fir_tree_01_bark_diff_1k.jpg"),
      load("tree_small_02_leaves_diff_1k.jpg"), load("tree_small_02_leaves_alpha_1k.png", false),
      load("grass_medium_02_diff_1k.jpg"), load("grass_medium_02_alpha_1k.png", false)]);
    const [grassN, sand, ripples] = await Promise.all([load("grass_ground_nor_gl_1k.jpg", false),
      load("gravelly_sand_diff_1k.jpg"), load("waternormals.jpg", false)]);
    LAND = {grass, moss, dry, trail, rock, grassN, sand, ripples};
    for (const t of [twig, twigA, leaves, leavesA, blades, bladesA]){ t.wrapS = t.wrapT = THREE.ClampToEdgeWrapping; }
    FLORA = createFlora({THREE, wind: WIND, tex: {twig, twigA, bark, leaves, leavesA, grass: blades, grassA: bladesA}});
    sky.mapping = THREE.EquirectangularReflectionMapping;
    scene.background = sky;
    scene.backgroundIntensity = 0.85;
    const pm = new THREE.PMREMGenerator(renderer);
    scene.environment = pm.fromEquirectangular(sky).texture;
    scene.environmentIntensity = 0.7;
    if (skyDome) skyDome.visible = false;
    aimSunAt(sky);
  } catch (e){ console.warn("land textures", e); LAND = null; }
}
/* Put the sun where the sky's sun is: the brightest point of the image. */
function aimSunAt(sky){
  const img = sky.image, data = img.data, W = img.width, H = img.height;
  if (!data) return;
  const half = data instanceof Uint16Array, f = half ? THREE.DataUtils.fromHalfFloat : (v => v);
  let best = -1, bi = 0;
  for (let i = 0; i < W * H; i += 3){
    const l = f(data[i * 4]) + f(data[i * 4 + 1]) + f(data[i * 4 + 2]);
    if (l > best){ best = l; bi = i; }
  }
  // three's equirect lookup: u = atan2(z, x) / 2pi + 0.5, and the top row of
  // the image is straight up.
  const u = (bi % W) / W, row = Math.floor(bi / W) / H;
  const az = (u - 0.5) * Math.PI * 2;
  let elev = (0.5 - row) * Math.PI;
  elev = Math.max(0.33, Math.min(0.9, elev));                 // keep shadows readable
  const dir = new THREE.Vector3(Math.cos(az) * Math.cos(elev), Math.sin(elev), Math.sin(az) * Math.cos(elev));
  SUN_OFFSET.copy(dir.multiplyScalar(220));
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

  // The ground is laid once the roads and places are known: it lies flat
  // under them and rolls everywhere else. See terrain.js and below.

  // Rivers: one across each valley, one between each pair of cities.
  // Water that takes the sky: low roughness, so the photographed sky shows in
  // it; a ripple texture moving slowly (see the loop) breaks it up.
  // In its channel (see terrain.js), a little below the plain; ripples move
  // across it (see the loop) and it takes the sky.
  if (LAND){ LAND.ripples.repeat.set(w / 30, d / 30); }
  const water = LAND
    ? new THREE.MeshStandardMaterial({color: "#26332c", roughness: 0.1, metalness: 0.0, transparent: true, opacity: 0.94,
        normalMap: LAND.ripples, normalScale: new THREE.Vector2(0.3, 0.3), envMapIntensity: 0.5})
    : new THREE.MeshPhongMaterial({color: "#ffffff", shininess: 30, specular: "#6e6a58",
        map: noiseTexture("#93b2a8", 14, 128, 30)});
  S.water = water;
  const ax = (D.river.axis - CY) * SCALE, half = D.river.half * SCALE;
  const WY = LAND ? -0.4 : 0.04, wide = LAND ? 9 : 0;
  const valleyRiver = new THREE.Mesh(new THREE.PlaneGeometry(half * 2 + wide * 2, d), water);
  valleyRiver.rotation.x = -Math.PI / 2; valleyRiver.position.set(ax, WY, 0);
  scene.add(valleyRiver);
  for (const r of D.river.borders || []){
    const m = new THREE.Mesh(new THREE.PlaneGeometry(w, r.half * 2 * SCALE + wide * 2), water);
    m.rotation.x = -Math.PI / 2; m.position.set(0, WY + 0.01, (r.axis - CX) * SCALE);
    scene.add(m);
  }

  // MOUNTAINS (2026-10-18): ranges round the settled land. Mines near them
  // strike rich seams more often; farms near water, rich soil.
  S.mountains = [];
  const rockTex = LAND ? LAND.rock.clone() : null;
  if (rockTex){ rockTex.needsUpdate = true; rockTex.repeat.set(6, 3); }
  const rockA = new THREE.MeshStandardMaterial({color: LAND ? "#b8ab98" : "#7d7262", map: rockTex, roughness: 0.95, flatShading: true});
  const rockB = new THREE.MeshStandardMaterial({color: LAND ? "#9c907e" : "#655b4c", map: rockTex, roughness: 0.95, flatShading: true});
  const snowM = new THREE.MeshLambertMaterial({color: "#e4e0d4", flatShading: true});
  (D.mountains || []).forEach((m, i) => {
    const c = toScene(m.x, m.y), r = m.r * SCALE * 1.7, h = m.h * SCALE * 1.6;
    if (LAND){ S.mountains.push({x: c.x, z: c.z, r, h: h * 0.75}); return; }   // part of the ground: see terrain.js
    const cone = new THREE.Mesh(new THREE.ConeGeometry(r, h, 7, 1), i % 2 ? rockA : rockB);
    cone.position.set(c.x, h / 2 - 0.5, c.z); cone.rotation.y = i * 1.3;
    const cap = new THREE.Mesh(new THREE.ConeGeometry(r * 0.33, h * 0.31, 7, 1), snowM);
    cap.position.set(c.x, h * 0.85 - 0.5, c.z); cap.rotation.y = i * 1.3;
    cone.castShadow = cone.receiveShadow = true;
    scene.add(cone, cap);
    S.mountains.push({x: c.x, z: c.z, r});
  });
  S.riverLines = {x: [(D.river.axis - CY) * SCALE], z: (D.river.borders || []).map(r => (r.axis - CX) * SCALE)};

  // Roads: main roads wide, the roads between cities a little less, spur tracks narrow.
  const nCities = (D.cities || []).length || 1;
  // Double-sided: a ribbon's winding depends on which way the road runs.
  const roadTex = LAND ? LAND.trail.clone() : null;
  if (roadTex){ roadTex.needsUpdate = true; roadTex.repeat.set(1, 0.6); }
  const roadMat = new (LAND ? THREE.MeshStandardMaterial : THREE.MeshLambertMaterial)({map: roadTex || noiseTexture("#b39c74", 26, 128, 1),
    color: LAND ? "#efe4cf" : "#ffffff", ...(LAND ? {roughness: 1, transparent: true, depthWrite: false} : {}),
    side: THREE.DoubleSide, polygonOffset: true, polygonOffsetFactor: -2});
  if (LAND) rutted(roadMat);
  veiled(roadMat);
  D.roads.forEach((line, i) => {
    const width = (i < nCities ? 6.5 : i < nCities + 3 ? 5 : 3.6) * (LAND ? 1.35 : 1);
    addRoad(line.map(([x, y]) => toScene(x, y)), width, roadMat);
  });

  // Places: a worn patch of ground, a name, and a radius that counts as "here".
  const dirt = new THREE.MeshLambertMaterial({map: softDisc("#a8936a"), transparent: true, opacity: LAND ? 0.25 : 0.6, depthWrite: false,
    polygonOffset: true, polygonOffsetFactor: -1});
  // THE GRID. Every place is a block of grid squares around its centre, one
  // per plot the simulation gives it, kept off the roads and the rivers; the
  // biggest places choose first. A plot bought there sits on one square, and
  // a business takes a 2x2 block of four.
  const riverX = (D.river.axis - CY) * SCALE, riverHalf = D.river.half * SCALE;
  const borderZ = (D.river.borders || []).map(r => [(r.axis - CX) * SCALE, r.half * SCALE]);
  const wet = (x, z) => Math.abs(x - riverX) < riverHalf + CELL * 0.6 || borderZ.some(([bz, bh]) => Math.abs(z - bz) < bh + CELL * 0.6);
  S.cells = new Map();
  const order = [...D.places].filter(p => p.kind !== "claim").sort((a, b) => (totals[b.name] || 0) - (totals[a.name] || 0));
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
  for (const p of D.places) if (p.kind === "claim") addClaimPlace(p, false);
  for (const p of D.places){
    if (p.kind === "claim") continue;
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

  // THE GROUND (2026-10-19): rolling land, flat where people are. The old
  // faint grid over everything is gone: squares show at places, and in the
  // overview, not across open country.
  TERRAIN = createTerrain({THREE, w, d, roadSegs, places: S.places,
    rivers: {x: [{at: riverX, half: riverHalf}], z: borderZ.map(([at, half]) => ({at, half}))},
    mountains: S.mountains, windUniform: WIND, tex: LAND, haze: hazeSetup(w, d)});
  scene.add(TERRAIN.mesh);
  S.ground = TERRAIN.mesh;
  if (!FLORA) scene.add(TERRAIN.tufts(26000));
  if (!LAND) makeClouds(w, d);              // the photographed sky has its own
  // Trees and rocks: the map's own, plus woodland everywhere nobody has built.
  scatterNature(D, w, d);
}

let TERRAIN = null, TREE_MESHES = [];
/* Trees by grid cell, for bumping into them and keeping the camera out of them. */
const TREES = new Map(), TREE_CELL = 8;
function treesNear(x, z){
  const out = [], cx = Math.floor(x / TREE_CELL), cz = Math.floor(z / TREE_CELL);
  for (let i = -1; i <= 1; i++) for (let j = -1; j <= 1; j++){ const a = TREES.get(`${cx + i},${cz + j}`); if (a) out.push(...a); }
  return out;
}
const groundAt = (x, z) => TERRAIN ? TERRAIN.heightAt(x, z) : 0;

/* A CLAIM on open land (2026-10-18): a place of exactly four squares, the 2x2
   block round its centre, joined to the roads by a dirt track. */
let trackMat = null;
function addClaimPlace(p, withRoad){
  if (S.places[p.name]) return;
  const c = toScene(p.x, p.y);
  const gx = Math.round(c.x / CELL) - 1, gz = Math.round(c.z / CELL) - 1;
  const keys = [];
  for (const [i, j] of [[0, 0], [1, 0], [0, 1], [1, 1]]){
    const k = `${gx + i},${gz + j}`;
    keys.push(k);
    S.cells.set(k, {key: k, gx: gx + i, gz: gz + j, x: (gx + i + 0.5) * CELL, z: (gz + j + 0.5) * CELL, place: p.name});
  }
  const city = ((S.DATA && S.DATA.cities) || []).find(k => k.places.includes(p.name));
  S.places[p.name] = {name: p.name, kind: "claim", c, r: CELL * 1.7, city: city ? city.key : "", cityName: city ? city.name : "", cells: keys, owner: p.owner || "", path: p.path || []};
  const el = document.createElement("div"); el.className = "lbl-place claim"; el.textContent = p.name;
  const lbl = new CSS2DObject(el); lbl.position.set(c.x, 12, c.z); scene.add(lbl);
  S.places[p.name].label = lbl;
  if (p.path && p.path.length) CLAIM_ROADS.add(p.name);   // drawn with the map's roads
  if (withRoad && p.path && p.path.length) drawClaimRoad(p.name, p.path, true);
  landKey = "";
}
/* A claim's dirt road, drawn as it is built (2026-10-30: built by hand, and
   paid for, with outposts -- see claims.build_road). */
const CLAIM_ROADS = new Set();
function drawClaimRoad(name, path, force){
  if (!force && CLAIM_ROADS.has(name)) return;
  CLAIM_ROADS.add(name);
  if (S.places[name]) S.places[name].path = path;
  if (!trackMat){
    const tt = LAND ? LAND.trail.clone() : null; if (tt){ tt.needsUpdate = true; tt.repeat.set(1, 0.6); }
    trackMat = new (LAND ? THREE.MeshStandardMaterial : THREE.MeshLambertMaterial)({map: tt || noiseTexture("#ad9670", 26, 128, 1),
      color: LAND ? "#e6dac4" : "#ffffff", side: THREE.DoubleSide, polygonOffset: true, polygonOffsetFactor: -2,
      ...(LAND ? {roughness: 1, transparent: true, depthWrite: false} : {})});
    if (LAND) rutted(trackMat);
    veiled(trackMat);
  }
  const pts = path.map(([x, y]) => toScene(x, y));
  addRoad(pts, 3.2, trackMat);
  // Level the new claim and its track into the hills.
  const c = S.places[name] && S.places[name].c;
  if (TERRAIN && c){
    const xs = pts.map(v => v.x).concat(c.x), zs = pts.map(v => v.z).concat(c.z);
    TERRAIN.reground(Math.min(...xs), Math.min(...zs), Math.max(...xs), Math.max(...zs));
  }
}

/* A DIRT ROAD, not a strip of carpet (2026-10-19): its edges fray into the
   grass, and two wheel ruts run along it, darker and smoother. Across the
   ribbon uv.x runs 0..1; along it, uv.y. */
function rutted(mat){
  mat.onBeforeCompile = sh => {
    sh.fragmentShader = sh.fragmentShader.replace("#include <map_fragment>", `#include <map_fragment>
      float ax = vMapUv.x;
      float fray = texture2D(map, vMapUv * vec2(1.0, 2.7) + 0.37).g;
      float edge = smoothstep(0.0, 0.22 + fray * 0.12, ax) * smoothstep(1.0, 0.78 - fray * 0.12, ax);
      float rut = exp(-pow((ax - 0.32) / 0.05, 2.0)) + exp(-pow((ax - 0.68) / 0.05, 2.0));
      diffuseColor.rgb *= 1.0 - rut * 0.22;
      diffuseColor.a *= edge;`);
  };
}
/* ROADS UNDER THE HAZE (2026-10-30): "somewhat near a road, but not a
   visible road". With outposts a road shows only where you have explored,
   fading out at the haze's edge like the ground under it (GROUND_HAZE). */
function veiled(mat){
  mat.transparent = true; mat.depthWrite = false;
  const before = mat.onBeforeCompile;
  mat.onBeforeCompile = (sh, r) => {
    if (before) before.call(mat, sh, r);
    if (!GROUND_HAZE.uniforms) return;
    Object.assign(sh.uniforms, GROUND_HAZE.uniforms);
    sh.vertexShader = sh.vertexShader
      .replace("#include <common>", "#include <common>\nvarying vec2 vHazeXZ;")
      .replace("#include <begin_vertex>", "#include <begin_vertex>\nvHazeXZ = (modelMatrix * vec4(transformed, 1.0)).xz;");
    sh.fragmentShader = sh.fragmentShader
      .replace("#include <common>", "#include <common>\nuniform sampler2D tHaze; uniform vec4 uHazeBox; uniform float uHazeOn; varying vec2 vHazeXZ;")
      .replace("#include <dithering_fragment>", `#include <dithering_fragment>
        gl_FragColor.a *= 1.0 - uHazeOn * texture2D(tHaze, (vHazeXZ - uHazeBox.xy) / uHazeBox.zw).a;`);
  };
}
/* Trees and rocks take the same veil as the ground (HAZE_GLSL), so where
   the land is unexplored they are dust-veiled with it, not standing out. */
function hazeMat(mat){
  const before = mat.onBeforeCompile, key = mat.customProgramCacheKey ? mat.customProgramCacheKey() : "";
  mat.customProgramCacheKey = () => key + "|haze";
  mat.onBeforeCompile = (sh, r) => {
    if (before) before.call(mat, sh, r);
    if (!GROUND_HAZE.uniforms) return;
    Object.assign(sh.uniforms, GROUND_HAZE.uniforms);
    sh.vertexShader = sh.vertexShader
      .replace("#include <common>", "#include <common>\nvarying vec3 vHazeP;")
      .replace("#include <project_vertex>", `#include <project_vertex>
        #ifdef USE_INSTANCING
          vHazeP = (modelMatrix * instanceMatrix * vec4(transformed, 1.0)).xyz;
        #else
          vHazeP = (modelMatrix * vec4(transformed, 1.0)).xyz;
        #endif`);
    sh.fragmentShader = sh.fragmentShader
      .replace("#include <common>", "#include <common>\nuniform sampler2D tHaze; uniform vec4 uHazeBox; uniform float uHazeOn; varying vec3 vHazeP;")
      .replace("#include <dithering_fragment>", `#include <dithering_fragment>\n${HAZE_GLSL}`);
  };
  return mat;
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
  // WOODS AND MEADOWS (2026-11-01): trees gather where a slow noise is high
  // -- stands of wood with open grass between and the odd lone tree -- instead
  // of an even sprinkle over everything. Bushes fringe the woods.
  const vh = (i, j) => { const v = Math.sin(i * 127.1 + j * 311.7) * 43758.5453; return v - Math.floor(v); };
  const vn = (x, z) => {
    const i = Math.floor(x), j = Math.floor(z), fx = x - i, fz = z - j, sx = fx * fx * (3 - 2 * fx), sz = fz * fz * (3 - 2 * fz);
    const a = vh(i, j), b = vh(i + 1, j), c = vh(i, j + 1), e = vh(i + 1, j + 1);
    return a + (b - a) * sx + (c - a) * sz + (a - b - c + e) * sx * sz;
  };
  const woods = (x, z) => vn(x / 170 + 9.3, z / 170 - 4.1) * 0.7 + vn(x / 55, z / 55) * 0.3;
  for (let i = 0; i < 16000 && trees.length < 6200; i++){
    const x = (rnd() - 0.5) * (w - 100), z = (rnd() - 0.5) * (d - 100);
    if (Math.abs(x - riverX) < riverH + 4) continue;
    if (borders.some(([bz, bh]) => Math.abs(z - bz) < bh + 4)) continue;
    if (placeList.some(p => Math.hypot(x - p.c.x, z - p.c.z) < p.r + 4)) continue;
    if (distToRoads(x, z) < 7) continue;
    const n = woods(x, z), r = rnd();
    if (r < 0.035){ rocks.push([x, z, 0.7 + rnd() * 0.9]); continue; }
    const pTree = 0.04 + 0.9 * Math.pow(Math.max(0, Math.min(1, (n - 0.42) / 0.25)), 1.4);
    if (r < pTree) trees.push([x, z, 0.75 + rnd() * 0.8]);
    else if (n > 0.34 && n < 0.52 && r < pTree + 0.08) trees.push([x, z, 0.7 + rnd() * 0.6, "bush"]);
  }
  if (FLORA){
    // Firs on high ground and in the cold; oaks lower down and by the water.
    // Above the tree line, nothing; just below it, small firs only.
    const kindOf = (x, y, z, kind) => {
      if (kind) return kind;
      const h = hash(`${x | 0},${z | 0}`), fir = y > 9 || h < 0.55 + Math.min(0.3, y / 30);
      return fir ? (hash(`${z | 0}`, 2) < 0.3 ? "fir2" : "fir") : (hash(`${x | 0}`, 3) < 0.35 ? "oak2" : "oak");
    };
    const list = trees.map(([x, z, k, kind]) => { const y = groundAt(x, z); return [x, y - 0.15, z, k * 0.85 * (y > 30 ? 0.7 : 1), kindOf(x, y, z, kind)]; })
      .filter(t => t[1] < 48 && !(t[1] > 30 && t[4] !== "fir"));
    for (const [x, , z, k, kind] of list){
      if (kind === "bush") continue;
      const key = `${Math.floor(x / TREE_CELL)},${Math.floor(z / TREE_CELL)}`;
      if (!TREES.has(key)) TREES.set(key, []);
      TREES.get(key).push([x, z, k]);
    }
    for (const m of FLORA.materials) hazeMat(m);
    TREE_MESHES = FLORA.plant(list, []);
    for (const im of TREE_MESHES) scene.add(im);
    GRASS = FLORA.grassField(groundAt, (x, z) => TERRAIN.grassy(x, z) && !inField(x, z));
    scene.add(GRASS.mesh);
    // BOULDERS (2026-11-01): grey granite, broken into facets and half sunk
    // in the ground, with moss and lichen on their tops -- not smooth brown
    // pebbles set on the grass. Two shapes, each tumbled its own way.
    const rockTex = LAND.rock.clone(); rockTex.needsUpdate = true;
    const stoneMat = new THREE.MeshStandardMaterial({map: rockTex, color: "#c4c0b6", roughness: 0.95, flatShading: true});
    stoneMat.customProgramCacheKey = () => "boulder";
    stoneMat.onBeforeCompile = sh => {
      sh.vertexShader = sh.vertexShader.replace("#include <common>", "#include <common>\nvarying vec3 vUpN;")
        .replace("#include <begin_vertex>", "#include <begin_vertex>\nvUpN = normalize(mat3(modelMatrix) * mat3(instanceMatrix) * objectNormal);");
      sh.fragmentShader = sh.fragmentShader.replace("#include <common>", "#include <common>\nvarying vec3 vUpN;")
        .replace("#include <map_fragment>", `#include <map_fragment>
          vec3 mono = vec3(dot(diffuseColor.rgb, vec3(0.3, 0.55, 0.15)));
          diffuseColor.rgb = mix(mono, diffuseColor.rgb, 0.45);
          float moss = smoothstep(0.75, 0.97, normalize(vUpN).y);
          diffuseColor.rgb = mix(diffuseColor.rgb, vec3(0.42, 0.44, 0.28) * (0.8 + mono * 0.6), moss * 0.35);`);
    };
    hazeMat(stoneMat);
    const boulder = (seed, detail) => {
      const g = new THREE.IcosahedronGeometry(1.2, detail), v = g.attributes.position;
      for (let i = 0; i < v.count; i++){
        const x = v.getX(i), y = v.getY(i), z = v.getZ(i);
        const n = Math.sin(x * 3.1 + seed) * Math.cos(z * 2.7 - seed) * 0.5 + Math.sin(y * 4.3 + seed * 2) * 0.25;
        const k = 1 + n * 0.3, flat = y > 0.7 ? 0.7 + (y - 0.7) * 0.2 : y;    // weathered flat on top
        v.setXYZ(i, x * k, flat * k * 0.85, z * k);
      }
      g.computeVertexNormals(); g.translate(0, 0.35, 0);
      return g;
    };
    const geos = [boulder(1.7, 1), boulder(4.2, 1)];
    const m = new THREE.Matrix4(), q = new THREE.Quaternion(), s = new THREE.Vector3(), p = new THREE.Vector3(), e = new THREE.Euler();
    geos.forEach((geo, gi) => {
      const mine = rocks.filter((r, i) => i % 2 === gi);
      const stones = new THREE.InstancedMesh(geo, stoneMat, Math.max(1, mine.length));
      mine.forEach(([x, z, k], i) => {
        const fr = v => ((v % 1) + 1) % 1;
        e.set((fr(x * 1.3) - 0.5) * 0.7, fr(x * 0.37) * 6.28, (fr(z * 1.7) - 0.5) * 0.7); q.setFromEuler(e);
        s.set(k * (0.8 + fr(z * 3.1) * 0.6), k * (0.55 + fr(x * 2.3) * 0.4), k * (0.8 + fr(x * 5.7) * 0.5));
        p.set(x, groundAt(x, z) - 0.35 * k, z); m.compose(p, q, s); stones.setMatrixAt(i, m);
      });
      stones.count = mine.length;
      stones.castShadow = stones.receiveShadow = true;
      scene.add(stones);
    });
    return;
  }
  const trunkGeo = new THREE.CylinderGeometry(0.25, 0.35, 2.4, 6); trunkGeo.translate(0, 1.2, 0);
  const crownGeo = new THREE.IcosahedronGeometry(2.1, 0); crownGeo.translate(0, 3.9, 0);
  const pineGeo = new THREE.ConeGeometry(1.9, 5.2, 7); pineGeo.translate(0, 4.4, 0);
  const rockGeo = new THREE.DodecahedronGeometry(1.2, 0); rockGeo.translate(0, 0.5, 0);
  const trunks = new THREE.InstancedMesh(trunkGeo, new THREE.MeshLambertMaterial({color: "#4f3a27"}), trees.length);
  const crowns = new THREE.InstancedMesh(crownGeo, windy(new THREE.MeshLambertMaterial({color: "#ffffff", flatShading: true})), trees.length);
  const pines = new THREE.InstancedMesh(pineGeo, windy(new THREE.MeshLambertMaterial({color: "#ffffff", flatShading: true})), trees.length);
  const stones = new THREE.InstancedMesh(rockGeo, new THREE.MeshLambertMaterial({color: "#7a7365", flatShading: true}), rocks.length);
  const m = new THREE.Matrix4(), q = new THREE.Quaternion(), s = new THREE.Vector3(), p = new THREE.Vector3(), e = new THREE.Euler();
  const hidden = new THREE.Matrix4().makeScale(0, 0, 0);
  const tint = new THREE.Color();
  trees.forEach(([x, z, k], i) => {
    e.set(0, (x * 13.7 + z) % 6.28, 0); q.setFromEuler(e); s.set(k, k, k); p.set(x, groundAt(x, z) - 0.2, z);
    m.compose(p, q, s);
    trunks.setMatrixAt(i, m);
    const pine = hash(`${x | 0},${z | 0}`) < 0.45;
    crowns.setMatrixAt(i, pine ? hidden : m);
    pines.setMatrixAt(i, pine ? m : hidden);
    // Muted: olive to dark pine, some autumn-dry.
    tint.setHSL(0.2 + hash(`${z | 0}`, 3) * 0.1, 0.32 + hash(`${x | 0}`, 4) * 0.12, 0.2 + hash(`${x | 0}`, 5) * 0.08);
    crowns.setColorAt(i, tint); pines.setColorAt(i, tint);
  });
  rocks.forEach(([x, z, k], i) => {
    e.set(0, x % 6.28, 0); q.setFromEuler(e); s.set(k, k * 0.7, k); p.set(x, groundAt(x, z) - 0.15, z);
    m.compose(p, q, s); stones.setMatrixAt(i, m);
  });
  for (const im of [trunks, crowns, pines, stones]) im.castShadow = true;
  scene.add(trunks, crowns, pines, stones);
}

/* ------------------------------------------------------------ models */
const loader = new GLTFLoader();
const MODELS = {};          // name -> {scene, animations, scale, lift}
// Models that may not be there (2026-10-19, Meshy): the home, the donkey,
// and a general store for the shops that had only a painted box.
const EXTRA_MODELS = ["home", "donkey", "store"];
const MODELS_V = "20261019e";       // bump when a model file changes: browsers cache them
async function loadModels(progress){
  await loadSet([...CHARACTERS, ...new Set(Object.values(MODEL_FOR_TYPE)), ...EXTRA_MODELS], progress);
  // Fall back to the older cast for whichever sex has no new model loaded.
  for (const sex of ["m", "f"]){
    const have = NEW_CAST[sex].filter(n => MODELS[n]);
    if (have.length) { CAST = {...CAST, [sex]: have}; continue; }
    await loadSet(OLD_CAST[sex], () => {});
    CAST = {...CAST, [sex]: OLD_CAST[sex].filter(n => MODELS[n])};
  }
  CHARACTERS = [...CAST.m, ...CAST.f];
  if (!MODELS[PLAYER_CHARACTER]) PLAYER_CHARACTER = CAST.m[0];
}
async function loadSet(names, progress){
  let done = 0;
  await Promise.all(names.map(n => loader.loadAsync(`/assets3d/${n}.glb?v=${MODELS_V}`).then(gltf => {
    solidify(gltf.scene);
    gltf.scene.updateMatrixWorld(true);
    const box = new THREE.Box3().setFromObject(gltf.scene), size = box.getSize(new THREE.Vector3());
    const isChar = [...NEW_CAST.m, ...NEW_CAST.f, ...OLD_CAST.m, ...OLD_CAST.f].includes(n);
    // The Meshy buildings were textured dark and muted; lift them toward the
    // brighter look by letting the texture light itself a little, and warm it.
    if (!isChar) gltf.scene.traverse(o => {
      if (!o.isMesh) return;
      for (const m of [].concat(o.material)){
        // 2026-10-19: no more self-lit glow; the textures sit in the light.
        if (m.map && "emissive" in m){ m.emissiveMap = m.map; m.emissive = new THREE.Color("#ffe2b8"); m.emissiveIntensity = 0.06; }
        if ("roughness" in m) m.roughness = Math.max(m.roughness, 0.8);
        m.needsUpdate = true;
      }
    });
    // Buildings fill their 2x2 block, but a tall narrow one (the mine's
    // headframe) is held to a sane height rather than scaled to a tower.
    const scale = isChar ? HUMAN_H / size.y : n === "donkey" ? 1.45 / size.y
      : Math.min(BUILDING_W / Math.max(size.x, size.z), 16 / size.y);
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
  body.traverse(o => { if (o.isMesh){ o.frustumCulled = false; o.castShadow = true; } });
  const root = new THREE.Group(); root.add(body, BLOB.clone());
  const mixer = new THREE.AnimationMixer(body);
  const clip = re => M.animations.find(a => re.test(a.name));
  const acts = {};
  for (const [k, re] of [["walk", /walk/i], ["run", /run/i], ["work", /swing|attack|combo/i],
                         ["block", /block/i], ["attack", /^attack/i], ["breathe", /^idle/i]]){
    const c = clip(re); if (c) acts[k] = mixer.clipAction(c);
  }
  // The new cast has a real idle (breathing, shifting weight). The older one
  // had none: stand in the walk's PASSING frame, a quarter of the way through
  // the cycle, where the feet are together under the body.
  if (acts.breathe){
    acts.idle = acts.breathe; acts.idle.userData = {live: true};
    acts.idle.play(); acts.idle.time = Math.random() * acts.idle.getClip().duration;   // not all in step
  }
  else if (acts.walk){
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
  if (state === "idle" && !(to.userData && to.userData.live)){ to.paused = true; to.time = IDLE_AT * to.getClip().duration; }
  to.play();
  if (from) from.crossFadeTo(to, 0.2, false);
  p.state = state;
}

/* A business: the Meshy building for its type, or a plain one with a sign. */
function makeBuilding(b){
  const key = MODEL_FOR_TYPE[b.type] || (MODELS.store ? "store" : null);
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
  root.traverse(o => { o.userData.pick = {kind: "building", id: b.id}; if (o.isMesh){ o.castShadow = true; o.receiveShadow = true; } });
  const el = document.createElement("div");
  el.className = "lbl-biz" + (b.owner === G.you ? " mine" : "");
  el.innerHTML = signHTML(b, null);
  // On the facade, not floating above the roof: close up, a sign over the
  // roof is off the top of the screen.
  const lbl = new CSS2DObject(el); lbl.position.set(0, 6.5, 0);
  root.add(lbl); root.userData.label = lbl;
  root.userData.bizId = b.id;
  setFloors(root, b.floors || 0);
  return root;
}
/* FARMLAND (2026-11-01: "make the graphics of the world better ... the
   farmland"). A farm is its barn and its fields: up to three ploughed plots
   round the back and sides of the barn, fenced with split rails, showing what
   it grows -- golden wheat in rows, pasture for the hides, young shoots in
   the furrows otherwise. A plot is left out where it would cross a road, the
   water, someone else's square or another building. Trees on a plot are
   felled; the grass round you does not grow on one. */
const FIELDS = [];             // {id, cx, cz, ax, az, hw, hd}: rectangles, for the grass and trees
function inField(x, z){
  for (const f of FIELDS){
    const dx = x - f.cx, dz = z - f.cz;
    if (Math.abs(dx * f.ax + dz * f.az) < f.hw && Math.abs(-dx * f.az + dz * f.ax) < f.hd) return true;
  }
  return false;
}
let soilTex = null, fenceMat = null;
function soil(){
  if (soilTex) return soilTex;
  // Eight furrows a tile: dark troughs, lighter ridges, clods.
  const c = document.createElement("canvas"); c.width = c.height = 256;
  const g = c.getContext("2d");
  for (let x = 0; x < 256; x++){
    const t = (x % 32) / 32, ridge = Math.sin(t * Math.PI);
    const v = 70 + ridge * 48;
    g.fillStyle = `rgb(${v + 22 | 0},${v + 6 | 0},${v - 18 | 0})`; g.fillRect(x, 0, 1, 256);
  }
  for (let i = 0; i < 3500; i++){
    const v = Math.random() * 40 - 20, x = Math.random() * 256, y = Math.random() * 256;
    g.fillStyle = `rgba(${110 + v | 0},${88 + v | 0},${60 + v | 0},0.55)`; g.fillRect(x, y, 1 + Math.random() * 3, 1 + Math.random() * 2);
  }
  soilTex = new THREE.CanvasTexture(c);
  soilTex.wrapS = soilTex.wrapT = THREE.RepeatWrapping; soilTex.colorSpace = THREE.SRGBColorSpace;
  soilTex.anisotropy = renderer.capabilities.getMaxAnisotropy();
  return soilTex;
}
const CROP = {
  Wheat:         {soil: "#e2cf9c", plant: "#f2cf6e", k: 1.1, ky: 1.45, row: 0.85, gap: 0.42},
  Hide:          {soil: null,      plant: "#b9c482", k: 1.0, ky: 0.8,  row: 0,    gap: 1.0},
  "Dirty Water": {soil: "#ffffff", plant: "#9fbf62", k: 0.55, ky: 0.55, row: 0.85, gap: 0.6},
};
function dropFields(v){
  if (v.fields) v.root.remove(v.fields);
  for (let i = FIELDS.length - 1; i >= 0; i--) if (FIELDS[i].id === v.b.id) FIELDS.splice(i, 1);
  v.fields = null; v.crop = null;
}
function farmFields(v){
  const card = (S.DATA.cards || {})[v.b.id] || {};
  const crop = CROP[card.producing] ? card.producing : "Dirty Water";
  // Re-laid when the crop changes, or squares round it are bought or built on.
  const key = `${crop}|${S.cellOwner.size}|${S.buildings.size}`;
  if (v.fieldKey === key) return;
  dropFields(v);
  v.crop = crop; v.fieldKey = key;
  const C = CROP[crop], root = v.root, ang = v.ang, P = v.pos;
  const fx = Math.sin(ang), fz = Math.cos(ang), rx = Math.cos(ang), rz = -Math.sin(ang);
  const toW = (lx, lz) => [P.x + rx * lx + fx * lz, P.z + rz * lx + fz * lz];
  const mine = new Set(S.bizCells.get(v.b.id) || []);
  const group = new THREE.Group();
  const H = BUILDING_W / 2;
  // [centre across, centre along (front is +), half width, half depth]
  const slots = [[0, -(H + 1.5 + 9), 7, 9], [-(H + 1.5 + 7), -2, 7, 8.5], [H + 1.5 + 7, -2, 7, 8.5]];
  const ok = (lx, lz) => {
    const [x, z] = toW(lx, lz);
    if (distToRoads(x, z) < 3.5) return false;
    if (S.riverLines && (S.riverLines.x.some(a => Math.abs(x - a) < 12) || S.riverLines.z.some(a => Math.abs(z - a) < 12))) return false;
    // Its own squares, and the empty, unowned squares of its own place, are
    // farmland; anyone else's are not.
    const cell = `${Math.floor(x / CELL)},${Math.floor(z / CELL)}`, sq = S.cells.get(cell);
    if (sq && !mine.has(cell) && (sq.place !== v.b.place || S.cellOwner.has(cell))) return false;
    if (colliders.some(c => c.id !== v.b.id && Math.hypot(c.x - x, c.z - z) < (c.r || 3) + 2)) return false;
    if (inField(x, z)) return false;
    return Math.abs(groundAt(x, z)) < 6;
  };
  const crops = [], posts = [], rails = [];
  for (const [cx, cz, hw, hd] of slots){
    let fine = true;
    for (const [a, b] of [[0, 0], [-1, -1], [1, -1], [-1, 1], [1, 1], [0, -1], [0, 1], [-1, 0], [1, 0]]) if (!ok(cx + a * hw, cz + b * hd)){ fine = false; break; }
    if (!fine) continue;
    const [wx, wz] = toW(cx, cz);
    FIELDS.push({id: v.b.id, cx: wx, cz: wz, ax: rx, az: rz, hw: hw + 0.5, hd: hd + 0.5});
    // The ground of the plot, draped over the land.
    if (C.soil){
      const geo = new THREE.PlaneGeometry(hw * 2, hd * 2, Math.ceil(hw), Math.ceil(hd)); geo.rotateX(-Math.PI / 2);
      const pa = geo.attributes.position;
      for (let i = 0; i < pa.count; i++){
        const lx = pa.getX(i) + cx, lz = pa.getZ(i) + cz, [x, z] = toW(lx, lz);
        pa.setXYZ(i, lx, groundAt(x, z) - P.y + 0.06, lz);
      }
      const uv = geo.attributes.uv;
      for (let i = 0; i < uv.count; i++) uv.setXY(i, uv.getX(i) * hw * 2 / 7.2, uv.getY(i) * hd * 2 / 7.2);
      geo.computeVertexNormals();
      const mesh = new THREE.Mesh(geo, new THREE.MeshStandardMaterial({map: soil(), color: C.soil, roughness: 1,
        polygonOffset: true, polygonOffsetFactor: -1}));
      mesh.receiveShadow = true; mesh.raycast = () => {};
      group.add(mesh);
    }
    // What grows: rows along the plot, or pasture scattered over it.
    for (let a = -hw + 0.6; a <= hw - 0.6; a += C.row || C.gap * 1.6){
      for (let b = -hd + 0.5; b <= hd - 0.5; b += C.gap){
        const j = hash(`${v.b.id}${a.toFixed(1)}${b.toFixed(1)}`);
        const lx = cx + a + (C.row ? (j - 0.5) * 0.12 : (j - 0.5) * 1.4), lz = cz + b + (hash(`${b}${a}`, 3) - 0.5) * (C.row ? 0.2 : 1.2);
        if (!C.row && j < 0.35) continue;
        const [x, z] = toW(lx, lz);
        crops.push([lx, groundAt(x, z) - P.y, lz, C.k * (0.85 + j * 0.3), C.ky * (0.85 + hash(`${a}${b}`, 5) * 0.3)]);
      }
    }
    // A split-rail fence round it: a post every 2.4 m, two rails between.
    const corners = [[-hw - 0.4, -hd - 0.4], [hw + 0.4, -hd - 0.4], [hw + 0.4, hd + 0.4], [-hw - 0.4, hd + 0.4]];
    for (let s = 0; s < 4; s++){
      const [ax, az] = corners[s], [bx, bz] = corners[(s + 1) % 4];
      const len = Math.hypot(bx - ax, bz - az), n = Math.max(1, Math.round(len / 2.4));
      let prev = null;
      for (let i = 0; i <= n; i++){
        const lx = cx + ax + (bx - ax) * i / n, lz = cz + az + (bz - az) * i / n, [x, z] = toW(lx, lz);
        const pt = new THREE.Vector3(lx, groundAt(x, z) - P.y, lz);
        if (i < n) posts.push(pt);
        if (prev) for (const h of [0.5, 0.95]) rails.push([prev.clone().setY(prev.y + h), pt.clone().setY(pt.y + h)]);
        prev = pt;
      }
    }
  }
  if (!FIELDS.some(f => f.id === v.b.id)) return;
  if (FLORA && crops.length) group.add(FLORA.crops(crops, C.plant, crop === "Wheat" ? 0.16 : 0.1));
  if (!fenceMat) fenceMat = new THREE.MeshStandardMaterial({color: "#ffffff", map: noiseTexture("#7f6b52", 30, 64, 1), roughness: 1});
  const m4 = new THREE.Matrix4(), q = new THREE.Quaternion(), sc = new THREE.Vector3(), X = new THREE.Vector3(1, 0, 0);
  const postIM = new THREE.InstancedMesh(new THREE.BoxGeometry(0.16, 1.25, 0.16).translate(0, 0.5, 0), fenceMat, posts.length);
  posts.forEach((pt, i) => { q.setFromAxisAngle(new THREE.Vector3(0, 1, 0), hash(`${pt.x}${pt.z}`) * 0.4 - 0.2); sc.set(1, 0.9 + hash(`${pt.z}`) * 0.25, 1); m4.compose(pt, q, sc); postIM.setMatrixAt(i, m4); });
  const railIM = new THREE.InstancedMesh(new THREE.BoxGeometry(1, 0.09, 0.11), fenceMat, rails.length);
  rails.forEach(([a, b], i) => {
    const d = b.clone().sub(a), len = d.length();
    q.setFromUnitVectors(X, d.normalize()); sc.set(len + 0.2, 1, 1); m4.compose(a.clone().add(b).multiplyScalar(0.5), q, sc); railIM.setMatrixAt(i, m4);
  });
  for (const im of [postIM, railIM]){ im.castShadow = im.receiveShadow = true; im.raycast = () => {}; im.computeBoundingSphere(); group.add(im); }
  root.add(group); v.fields = group;
  // Fell the trees on the plots, and let the grass round you re-grow around them.
  const gone = (x, z) => inField(x, z);
  if (FLORA) FLORA.clear(TREE_MESHES, gone);
  for (const [k, list] of TREES) TREES.set(k, list.filter(([x, z]) => !gone(x, z)));
  if (GRASS && S.player) GRASS.update(S.player.root.position, true);
}

/* FLOORS (2026-10-30): "an upgrade to buildings to add a floor which would
   increase storage". Each floor is a timber storey under the building, which
   is lifted onto it -- the building as it was, now standing taller. */
const FLOOR_H = 3.2;
let floorMats = null;
function setFloors(root, n){
  if ((root.userData.floors || 0) === n) return;
  root.userData.floors = n;
  if (!root.userData.body){
    // Everything the building was, in one group we can lift.
    const body = new THREE.Group();
    for (const c of [...root.children]) body.add(c);
    root.add(body); root.userData.body = body;
    const box = new THREE.Box3().setFromObject(body);
    root.userData.foot = {w: Math.min(BUILDING_W * 0.8, box.max.x - box.min.x), d: Math.min(BUILDING_W * 0.8, box.max.z - box.min.z),
                          x: (box.max.x + box.min.x) / 2 - root.position.x, z: (box.max.z + box.min.z) / 2 - root.position.z};
  }
  if (root.userData.storeys) root.remove(root.userData.storeys);
  if (!floorMats){
    floorMats = {wall: new THREE.MeshLambertMaterial({map: noiseTexture("#94714c", 30, 128, 1)}), beam: new THREE.MeshLambertMaterial({color: "#4a3626"}),
                 window: new THREE.MeshLambertMaterial({color: "#211c18"})};
  }
  const f = root.userData.foot, g = new THREE.Group();
  for (let i = 0; i < n; i++){
    const wall = new THREE.Mesh(new THREE.BoxGeometry(f.w, FLOOR_H, f.d), floorMats.wall);
    wall.position.set(f.x, i * FLOOR_H + FLOOR_H / 2, f.z);
    const beam = new THREE.Mesh(new THREE.BoxGeometry(f.w + 0.6, 0.35, f.d + 0.6), floorMats.beam);
    beam.position.set(f.x, (i + 1) * FLOOR_H, f.z);
    g.add(wall, beam);
    for (const [cx, cz] of [[-1, -1], [1, -1], [-1, 1], [1, 1]]){     // corner posts
      const post = new THREE.Mesh(new THREE.BoxGeometry(0.5, FLOOR_H, 0.5), floorMats.beam);
      post.position.set(f.x + cx * f.w / 2, i * FLOOR_H + FLOOR_H / 2, f.z + cz * f.d / 2);
      g.add(post);
    }
    for (const s of [-1, 1]){                       // a pair of shuttered windows, front and back
      for (const k of [-0.25, 0.25]){
        const w = new THREE.Mesh(new THREE.BoxGeometry(f.w * 0.14, FLOOR_H * 0.4, 0.12), floorMats.window);
        w.position.set(f.x + k * f.w, i * FLOOR_H + FLOOR_H * 0.55, f.z + s * (f.d / 2 + 0.05));
        g.add(w);
      }
    }
  }
  g.traverse(o => { if (o.isMesh){ o.castShadow = o.receiveShadow = true; o.userData.pick = {kind: "building", id: root.userData.bizId}; } });
  root.add(g); root.userData.storeys = g;
  root.userData.body.position.y = n * FLOOR_H;
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
  const mat = new THREE.MeshLambertMaterial({color: "#ece4d4", flatShading: true, emissive: "#d8c8a8", emissiveIntensity: 0.25, transparent: true, opacity: 0.85});
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
S.homes = new Map();              // owner id -> [cell keys] of their home
let border = null;                // your home's border: the ring of squares around it
S.selected = new Set();
let PLOTS = null;
async function pollPlots(){
  let got; try { got = await api.get("/api/plots"); } catch (e) { return; }
  if (!got || !got.plots) return;                 // no game loaded, or a server error: keep the last
  PLOTS = got;
  syncLand(); syncBuildings();
}
function assignPlots(){
  S.cellOwner.clear(); S.bizCells.clear();
  if (!PLOTS) return;
  const taken = new Set();
  const put = (q, k) => {
    S.cellOwner.set(k, {plot: q.id, owner: q.owner, business: q.business, home: !!q.home, structure: q.structure || ""});
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
  // HOMES (2026-10-18): a citizen's four home plots, the 2x2 block nearest the
  // middle of the square -- placed before any business, so home is central.
  S.homes.clear();
  const homeGroups = new Map();
  for (const q of PLOTS.plots) if (q.home){
    if (!homeGroups.has(q.owner)) homeGroups.set(q.owner, []); homeGroups.get(q.owner).push(q);
  }
  for (const [owner, qs] of homeGroups){
    const place = qs[0].place, P = S.places[place];
    const already = qs.map(q => [...S.cellOwner].find(([, o]) => o.plot === q.id)).filter(Boolean).map(([k]) => k);
    if (already.length === qs.length){ S.homes.set(owner, already); continue; }
    let best = null, bd = Infinity;
    for (const k of free(place)){
      const c = S.cells.get(k), ks = [k, `${c.gx + 1},${c.gz}`, `${c.gx},${c.gz + 1}`, `${c.gx + 1},${c.gz + 1}`];
      if (!ks.every(x => S.cells.has(x) && S.cells.get(x).place === place && !taken.has(x))) continue;
      const d = P ? (c.x - P.c.x) ** 2 + (c.z - P.c.z) ** 2 : 0;
      if (d < bd){ bd = d; best = ks; }
    }
    const spots = best || free(place).slice(0, qs.length);
    qs.sort((a, b) => a.id.localeCompare(b.id)).forEach((q, i) => { if (spots[i]) put(q, spots[i]); });
    S.homes.set(owner, spots.slice(0, qs.length));
  }
  for (const q of PLOTS.plots) if (q.home) placed.add(q.id);
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
  const key = [...S.cellOwner].map(([k, o]) => `${k}:${o.owner}`).join("|") + "#" + [...S.selected].join(",") + "#" + KNOWN.size;
  if (key === landKey) return;
  landKey = key;
  if (outlines){ scene.remove(outlines, tints, picks); }
  const all = [...S.cells.values()];
  const freeCells = all.filter(c => !S.cellOwner.has(c.key));
  // Outline of a free square: a rounded frame on the grass.
  const e = CELL / 2 - 0.3, t = 0.22;
  const frame = mergeGeometries([[0, -e, CELL - 0.6, t], [0, e, CELL - 0.6, t], [-e, 0, t, CELL - 0.6], [e, 0, t, CELL - 0.6]]
    .map(([x, z, w, d]) => { const g = new THREE.PlaneGeometry(w, d); g.rotateX(-Math.PI / 2); g.translate(x, 0, z); return g; }));
  outlines = new THREE.InstancedMesh(frame, new THREE.MeshBasicMaterial({color: "#e6d8b0", transparent: true, opacity: 0.38,
    depthWrite: false, polygonOffset: true, polygonOffsetFactor: -2}), Math.max(1, freeCells.length));
  const m = new THREE.Matrix4();
  freeCells.forEach((c, i) => { m.makeTranslation(c.x, 0.09, c.z); outlines.setMatrixAt(i, m); });
  outlines.count = freeCells.length;
  // Owned squares in the owner's colour.
  const owned = all.filter(c => S.cellOwner.has(c.key) && landShown(S.cellOwner.get(c.key).owner, c));
  const sq = new THREE.PlaneGeometry(CELL - 0.35, CELL - 0.35); sq.rotateX(-Math.PI / 2);
  tints = new THREE.InstancedMesh(sq, new THREE.MeshBasicMaterial({transparent: true, opacity: 0.2, depthWrite: false,
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
  // YOUR TERRITORY (2026-10-18): every square you own -- home, businesses,
  // land, defenses -- and the ring of squares round each. Rings that touch
  // join: two buildings two squares apart share one border. A patch not joined
  // to your home's is an OUTPOST. Drawn on the grid itself, over road and
  // grass alike, so it reads wherever your land is.
  if (border){ scene.remove(border); border.traverse(o => { if (o.isCSS2DObject) o.element.remove(); }); border = null; }
  const ownKeys = [...S.cellOwner].filter(([, o]) => o.owner === G.you).map(([k]) => k);
  if (ownKeys.length){
    const terr = new Set();
    for (const k of ownKeys){
      const [gx, gz] = k.split(",").map(Number);
      for (let i = -1; i <= 1; i++) for (let j = -1; j <= 1; j++) terr.add(`${gx + i},${gz + j}`);
    }
    const ring = [...terr].filter(k => !ownKeys.includes(k) && S.cells.has(k) && !S.cellOwner.has(k)).map(k => S.cells.get(k));
    border = new THREE.Group();
    const fill = new THREE.PlaneGeometry(CELL - 0.6, CELL - 0.6); fill.rotateX(-Math.PI / 2);
    const fillM = new THREE.InstancedMesh(fill, new THREE.MeshBasicMaterial({color: "#d8b860", transparent: true, opacity: 0.14,
      depthWrite: false, polygonOffset: true, polygonOffsetFactor: -3}), Math.max(1, ring.length));
    ring.forEach((c, i) => { m.makeTranslation(c.x, 0.14, c.z); fillM.setMatrixAt(i, m); });
    fillM.count = ring.length;
    border.add(fillM);
    // The boundary: an edge wherever a territory square meets one outside it.
    const lineMat = new THREE.MeshBasicMaterial({color: "#c9a24a", transparent: true, opacity: 0.9, depthWrite: false,
      polygonOffset: true, polygonOffsetFactor: -5});
    const hz = new THREE.PlaneGeometry(CELL, 0.7); hz.rotateX(-Math.PI / 2);
    const vt = new THREE.PlaneGeometry(0.7, CELL); vt.rotateX(-Math.PI / 2);
    const edges = [];
    for (const k of terr){
      const [gx, gz] = k.split(",").map(Number);
      if (!terr.has(`${gx},${gz - 1}`)) edges.push([hz, (gx + 0.5) * CELL, gz * CELL]);
      if (!terr.has(`${gx},${gz + 1}`)) edges.push([hz, (gx + 0.5) * CELL, (gz + 1) * CELL]);
      if (!terr.has(`${gx - 1},${gz}`)) edges.push([vt, gx * CELL, (gz + 0.5) * CELL]);
      if (!terr.has(`${gx + 1},${gz}`)) edges.push([vt, (gx + 1) * CELL, (gz + 0.5) * CELL]);
    }
    for (const geo of [hz, vt]){
      const mine = edges.filter(e => e[0] === geo);
      const im = new THREE.InstancedMesh(geo, lineMat, Math.max(1, mine.length));
      mine.forEach(([, x, z], i) => { m.makeTranslation(x, 0.18, z); im.setMatrixAt(i, m); });
      im.count = mine.length; border.add(im);
    }
    // Patches: the one with your home is your land; any other is an outpost.
    const homeKeys = new Set(S.homes.get(G.you) || []), seen = new Set();
    for (const start of terr){
      if (seen.has(start)) continue;
      const comp = [], stack = [start]; seen.add(start);
      while (stack.length){
        const k = stack.pop(); comp.push(k);
        const [gx, gz] = k.split(",").map(Number);
        for (const n of [`${gx + 1},${gz}`, `${gx - 1},${gz}`, `${gx},${gz + 1}`, `${gx},${gz - 1}`])
          if (terr.has(n) && !seen.has(n)){ seen.add(n); stack.push(n); }
      }
      if (comp.some(k => homeKeys.has(k)) || !homeKeys.size) continue;
      const xs = comp.map(k => (Number(k.split(",")[0]) + 0.5) * CELL), zs = comp.map(k => (Number(k.split(",")[1]) + 0.5) * CELL);
      const el = document.createElement("div"); el.className = "lbl-biz outpost"; el.innerHTML = "<b>Outpost</b>";
      const lbl = new CSS2DObject(el); lbl.position.set(xs.reduce((a, b) => a + b, 0) / xs.length, 2.5, Math.max(...zs) + CELL * 0.7);
      border.add(lbl);
    }
    border.userData.line = lineMat;
    border.userData.edge = {material: lineMat};
    scene.add(border);
  }
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
/* OPEN LAND: claim it (the server lays and charges the road), draw the new
   place, then walk there and build -- or buy the four plots for a land claim. */
async function wildFound(type, cx, cz, landOnly){
  const w = toWorld(new THREE.Vector3(cx, 0, cz));
  const r = await api.post("/api/wildclaim", {x: w.x, y: w.y, purpose: landOnly ? "" : type});
  UI.toast(r.message, r.ok ? "" : "bad");
  if (!r.ok) return;
  addClaimPlace({name: r.claim.name, x: r.claim.x, y: r.claim.y, path: r.claim.road, owner: r.claim.owner}, true);
  const cells = S.places[r.place].cells;
  if (landOnly) buyOn(r.place, cells); else foundOn(r.place, cells, type);
}
/* A defense on the square you picked: walk there, build, pin it there. */
async function defendOn(place, cells, kind){
  const go = async () => {
    const r = await UI.act("build_defense", {kind});
    if (!r.ok) return;
    await api.post("/api/claim", {place, cells, business_id: "structure"});
    pollPlots();
  };
  if (S.here === place && S.OBS && S.OBS.you.location === place) go();
  else { UI.toast(`Walking to ${place} to build`); walkToPlace(place, () => setTimeout(go, 1200)); }
}
let popNext = null;               // the next building to appear does so with a bounce

/* ------------------------------------------------------------ syncing the world */
/* A HOME: a cottage on its four squares. Yours opens your house. */
S.homeObjs = new Map();
function makeHome(owner){
  const root = new THREE.Group();
  if (MODELS.home){
    const M = MODELS.home, m = M.scene.clone(true);
    m.scale.setScalar(M.scale * 0.92); m.position.set(-M.cx * 0.92, M.lift * 0.92, -M.cz * 0.92);
    m.traverse(o => { if (o.isMesh){ o.castShadow = o.receiveShadow = true; } });
    root.add(m);
    root.traverse(o => { o.userData.pick = {kind: "home", id: owner}; });
    const el = document.createElement("div");
    el.className = "lbl-biz home" + (owner === G.you ? " mine" : "");
    el.innerHTML = `<b>\u{1F3E0} ${owner === G.you ? "Your home" : esc(short(ownerName(owner))) + "'s home"}</b>`;
    const lbl = new CSS2DObject(el); lbl.position.set(0, 7, 0); root.add(lbl);
    return root;
  }
  const walls = new THREE.Mesh(new THREE.BoxGeometry(9, 5.5, 8), new THREE.MeshLambertMaterial({color: owner === G.you ? "#f1dfb8" : "#d9c9a6"}));
  walls.position.y = 2.75;
  const roof = new THREE.Mesh(new THREE.ConeGeometry(7.6, 4.2, 4), new THREE.MeshLambertMaterial({color: "#a8432a", flatShading: true}));
  roof.rotation.y = Math.PI / 4; roof.scale.set(1, 1, 0.92); roof.position.y = 7.6;
  const door = new THREE.Mesh(new THREE.BoxGeometry(1.8, 3, 0.3), new THREE.MeshLambertMaterial({color: "#4a2c16"}));
  door.position.set(0, 1.5, 4.05);
  const chimney = new THREE.Mesh(new THREE.BoxGeometry(1.1, 3, 1.1), new THREE.MeshLambertMaterial({color: "#7d6a58"}));
  chimney.position.set(2.4, 8.6, -1.2);
  const win = new THREE.Mesh(new THREE.BoxGeometry(1.6, 1.4, 0.3), new THREE.MeshLambertMaterial({color: "#ffe9a3", emissive: "#8a6a20"}));
  win.position.set(-2.6, 3.2, 4.05);
  root.add(walls, roof, door, chimney, win);
  root.traverse(o => { o.userData.pick = {kind: "home", id: owner}; });
  const el = document.createElement("div");
  el.className = "lbl-biz home" + (owner === G.you ? " mine" : "");
  el.innerHTML = `<b>\u{1F3E0} ${owner === G.you ? "Your home" : esc(short(ownerName(owner))) + "'s home"}</b>`;
  const lbl = new CSS2DObject(el); lbl.position.set(0, 7, 0); root.add(lbl);
  return root;
}
function syncHomes(){
  for (const [owner, keys] of S.homes){
    const cells = keys.map(k => S.cells.get(k)).filter(Boolean);
    if (!cells.length) continue;
    const pos = new THREE.Vector3(cells.reduce((a, c) => a + c.x, 0) / cells.length, 0, cells.reduce((a, c) => a + c.z, 0) / cells.length);
    let v = S.homeObjs.get(owner);
    if (!v){
      const root = makeHome(owner);
      const place = S.places[S.cells.get(keys[0]).place];
      root.rotation.y = place ? Math.atan2(place.c.x - pos.x, place.c.z - pos.z) : 0;
      scene.add(root);
      shown(root, landShown(owner, pos));
      v = {root, pos}; S.homeObjs.set(owner, v);
      colliders.push({id: "home:" + owner, x: pos.x, z: pos.z, r: 5.5});
    }
    v.pos.copy(pos); v.root.position.copy(pos);
  }
}
/* DEFENSES (2026-10-18): a guard post is a timber watchtower with a guard on
   it; a catapult is a wheeled frame with its arm cocked. One square each. */
function makeDefense(kind){
  const root = new THREE.Group();
  const wood = new THREE.MeshLambertMaterial({color: "#8a5a32"}), dark = new THREE.MeshLambertMaterial({color: "#5b3a1e"});
  if (kind === "Guard post"){
    for (const [x, z] of [[-1.3, -1.3], [1.3, -1.3], [-1.3, 1.3], [1.3, 1.3]]){
      const leg = new THREE.Mesh(new THREE.BoxGeometry(0.35, 6, 0.35), wood); leg.position.set(x, 3, z); root.add(leg);
    }
    const deck = new THREE.Mesh(new THREE.BoxGeometry(3.6, 0.4, 3.6), dark); deck.position.y = 6; root.add(deck);
    const rail = new THREE.Mesh(new THREE.BoxGeometry(3.6, 1, 3.6), new THREE.MeshLambertMaterial({color: "#a06a3c", transparent: true, opacity: 0.9}));
    rail.position.y = 6.7; root.add(rail);
    const roof = new THREE.Mesh(new THREE.ConeGeometry(3, 2.2, 4), new THREE.MeshLambertMaterial({color: "#a8432a", flatShading: true}));
    roof.rotation.y = Math.PI / 4; roof.position.y = 8.6; root.add(roof);
    const flag = new THREE.Mesh(new THREE.PlaneGeometry(1.6, 1), new THREE.MeshLambertMaterial({color: "#c0392b", side: THREE.DoubleSide}));
    flag.position.set(0.8, 10.4, 0); root.add(flag);
    const pole = new THREE.Mesh(new THREE.CylinderGeometry(0.06, 0.06, 2.4, 6), dark); pole.position.set(0, 10.2, 0); root.add(pole);
  } else {
    const base = new THREE.Mesh(new THREE.BoxGeometry(3.4, 0.6, 2.2), wood); base.position.y = 0.9; root.add(base);
    for (const [x, z] of [[-1.3, -1.2], [1.3, -1.2], [-1.3, 1.2], [1.3, 1.2]]){
      const w = new THREE.Mesh(new THREE.CylinderGeometry(0.6, 0.6, 0.3, 12), dark); w.rotation.x = Math.PI / 2; w.position.set(x, 0.6, z); root.add(w);
    }
    const post = new THREE.Mesh(new THREE.BoxGeometry(0.4, 2.2, 1.6), wood); post.position.set(0.4, 2.1, 0); root.add(post);
    const arm = new THREE.Mesh(new THREE.BoxGeometry(4.2, 0.3, 0.3), dark); arm.position.set(-0.6, 3, 0); arm.rotation.z = 0.55; root.add(arm);
    const cup = new THREE.Mesh(new THREE.SphereGeometry(0.45, 10, 8), new THREE.MeshLambertMaterial({color: "#8c8c8c"}));
    cup.position.set(-2.3, 4.2, 0); root.add(cup);
  }
  return root;
}
S.defenses = new Map();
function syncDefenses(){
  const live = new Set();
  for (const [k, o] of S.cellOwner){
    if (!o.structure) continue;
    live.add(o.plot);
    if (S.defenses.has(o.plot)) continue;
    const c = S.cells.get(k); if (!c) continue;
    const root = makeDefense(o.structure);
    root.position.set(c.x, 0, c.z);
    root.userData.owner = o.owner;
    const el = document.createElement("div");
    el.className = "lbl-biz def" + (o.owner === G.you ? " mine" : "");
    el.innerHTML = `<b>${o.structure === "Guard post" ? "\u{1F6E1}\uFE0F" : "\u{1FAA8}"} ${o.structure}</b>`;
    const lbl = new CSS2DObject(el); lbl.position.set(0, 11, 0); root.add(lbl);
    shown(root, landShown(o.owner, root.position));
    scene.add(root);
    S.defenses.set(o.plot, root);
  }
  for (const [pid, root] of S.defenses) if (!live.has(pid)){ scene.remove(root); S.defenses.delete(pid); }
}
function syncBuildings(){
  syncHomes();
  syncDefenses();
  const D = S.DATA, h = S.HOUR, live = new Set();
  for (const b of D.buildings || []){
    if (b.from != null && b.from > h + 0.01) continue;
    if (b.to != null && b.to <= h) continue;
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
    root.visible = landShown(b.owner, pos);
    scene.add(root);
    S.buildings.set(b.id, {root, b, pos, ang, born: performance.now(), pop: popNext === b.id || S.ready});
    if (b.type === "Farm") farmFields(S.buildings.get(b.id));
    if (popNext === b.id) popNext = null;
    colliders.push({id: b.id, x: pos.x, z: pos.z, r: BUILDING_W * 0.42});
  }
  for (const v of S.buildings.values()) if (v.b.type === "Farm") farmFields(v);
  for (const [id, v] of S.buildings){
    if (live.has(id)) continue;
    if (v.fields) dropFields(v);
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

/* ------------------------------------------------------------ your family */
/* YOUR HOUSEHOLD ON THE MAP (2026-10-18): each member is a figure -- at home
   around your cottage, or at the business they work -- with their name and
   what they are doing over their head, and a ring for a child growing up. */
S.family = new Map();
let HOUSE = null;
const FAM_MODELS = {get m(){ return CAST.m; }, get f(){ return CAST.f; }};
async function pollFamily(){
  try { HOUSE = await api.get("/api/household"); } catch (e) { return; }
  syncFamily();
}
function homeCentre(){
  const v = S.homeObjs.get(G.you);
  return v ? v.pos : (S.player ? S.player.root.position : new THREE.Vector3());
}
function famSpot(m, i){
  const out = HEXMAP.familyAt(m.id);         // out exploring (convoy/journey.py)
  if (out) return out.clone();
  if (m.works_at && S.buildings.has(m.works_at)){
    const b = S.buildings.get(m.works_at), place = S.places[b.b.place];
    const toward = place ? place.c.clone().sub(b.pos).setY(0).normalize() : new THREE.Vector3(0, 0, 1);
    const side = new THREE.Vector3(toward.z, 0, -toward.x);
    return b.pos.clone().addScaledVector(toward, 9).addScaledVector(side, (hash(m.id, 4) - 0.5) * 7);
  }
  const ang = (i / Math.max(1, HOUSE.members.length)) * Math.PI * 2 + 0.6;
  return homeCentre().clone().add(new THREE.Vector3(Math.cos(ang) * 8.5, 0, Math.sin(ang) * 8.5));
}
const famIcon = m => m.adult ? (m.sex === "f" ? "\u{1F469}" : "\u{1F468}") : (m.sex === "f" ? "\u{1F467}" : "\u{1F466}");
function famStatus(m){
  if (!m.adult) return `grown in ${m.grows_in < 24 ? Math.ceil(m.grows_in) + "h" : (m.grows_in / 24).toFixed(1) + " days"}`;
  if (m.works_at) return `\u2692 ${(m.works_type || "work").split(" /")[0]}`;
  if (typeof HEXMAP !== "undefined" && HEXMAP.familyAt(m.id)) return "\u{1F9ED} out exploring";
  if (m.partner && m.next_child_in != null) return `at home \u00b7 child in ${(m.next_child_in / 24).toFixed(0)}d`;
  return "at home";
}
function syncFamily(){
  if (!HOUSE || !HOUSE.members || !S.ready) return;   // no game loaded, or a server error
  const live = new Set();
  HOUSE.members.forEach((m, i) => {
    live.add(m.id);
    let v = S.family.get(m.id);
    if (!v){
      const list = FAM_MODELS[m.sex === "f" ? "f" : "m"];
      v = makePerson(list[Math.floor(hash(m.id, 3) * list.length)]);
      v.root.traverse(o => { o.userData.pick = {kind: "home", id: G.you}; });
      const el = document.createElement("div"); el.className = "lbl-fam";
      const lbl = new CSS2DObject(el); lbl.position.set(0, HUMAN_H + 0.9, 0); v.root.add(lbl);
      v.el = el;
      v.root.position.copy(famSpot(m, i));
      scene.add(v.root); S.family.set(m.id, v);
    }
    v.m = m; v.i = i;
    v.root.scale.setScalar(m.adult ? 1 : 0.68);
    const pct = m.pct_grown;
    const ring = pct == null ? "" : `<i class="fam-ring" style="--p:${Math.round(pct * 100)}"></i>`;
    const html = `<span class="fam-ic">${famIcon(m)}</span><span><b>${esc(m.name)}</b><small>${esc(famStatus(m))}</small></span>${ring}`;
    if (v.el.innerHTML !== html) v.el.innerHTML = html;
  });
  for (const [id, v] of S.family) if (!live.has(id)){ scene.remove(v.root); S.family.delete(id); }
}
function updateFamily(dt){
  for (const v of S.family.values()){
    const to = famSpot(v.m, v.i).sub(v.root.position).setY(0), d = to.length();
    if (d > 120){ v.root.position.copy(famSpot(v.m, v.i)); continue; }
    let speed = 0;
    if (d > 0.5){
      speed = Math.min(d / Math.max(dt, 0.001), 4);
      v.root.position.addScaledVector(to.normalize(), speed * dt);
      v.heading = Math.atan2(to.x, to.z); v.root.rotation.y = v.heading;
    }
    setAnim(v, speed > 0.3 ? "walk" : v.m.works_at && v.acts.work ? "work" : "idle");
    v.root.position.y = groundAt(v.root.position.x, v.root.position.z); v.mixer.update(dt);
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
  camMode = "third"; dist = 3.6; pitch = 0.12;
  yaw = Math.atan2(camera.position.x - S.player.root.position.x, camera.position.z - S.player.root.position.z);
  modeChanged();
}
function enterStrategy(at){
  freeMouse();
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
  // THE MAP (2026-11-01): outside a convoy you move by clicking hexes, and
  // close up you only look.
  const onMap = typeof HEXMAP !== "undefined" && mapDriven();
  $("keys").innerHTML = camMode === "strategy"
    ? (onMap ? "<b>click</b> a hex to walk there &middot; <b>WASD</b>/<b>drag</b> pan &middot; <b>scroll</b> zoom &middot; <b>Tab</b> look round &middot; <b>C</b> find me"
             : "<b>WASD</b>/<b>drag</b> pan &middot; <b>arrows</b> turn &middot; <b>scroll</b> zoom &middot; <b>click</b> to walk or open &middot; <b>Tab</b> take control &middot; <b>C</b> find me")
    : onMap ? "<b>drag</b> or <b>arrows</b> to look round &middot; <b>scroll</b> zoom &middot; <b>Tab</b> back to the map"
    : riding()
      ? "<b>W</b> walk on &middot; tap <b>Shift</b> to spur (hold to keep the pace) &middot; <b>S</b> rein in &middot; <b>A/D</b> steer &middot; <b>E</b> get down &middot; " + (mouseLook ? "<b>Esc</b> free the mouse" : LOCK_OK ? "<b>click</b> to look" : "<b>drag</b> to look") + " &middot; <b>Tab</b> overview"
      : "<b>WASD</b> move &middot; " + (mouseLook ? "<b>mouse</b> look &middot; <b>LMB</b> swing &middot; <b>RMB</b> aim &middot; <b>Esc</b> free the mouse" : LOCK_OK ? "<b>click</b> to look" : "<b>drag</b> to look &middot; <b>RMB</b> aim") + " &middot; <b>Shift</b> sprint &middot; <b>Space</b> jump &middot; <b>C</b> slide &middot; <b>R</b> swing &middot; hold <b>F</b> block &middot; <b>E</b> use / ride &middot; <b>H</b> whistle &middot; <b>Tab</b> overview";
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

/* MOVEMENT (2026-10-31): Fortnite on foot, Red Dead on a donkey -- the rules
   are in move.js (input -> intent -> state machine -> physics); this applies
   them to the scene: collisions, facing, animation and the arrival news. */
const WALKER = createWalker(), RIDER = createRider();
const pressed = new Set();                  // pressed since the last frame
let lastLook = 0;                           // when the mouse last turned the camera
function riding(){ return !!(S.ST && RIDEABLE.has(S.ST.vehicle) && DONKEY.root); }
/* What is solid: steep ground, mountain cones, tree trunks, buildings. Moves
   `pos` out of them; true if anything was hit. */
function collide(pos, last, maxGrade = 0.9){
  let hit = false;
  // Too steep to climb: people scramble up to ~42 degrees, animals ~30.
  if (last){
    const dh = groundAt(pos.x, pos.z) - groundAt(last.x, last.z);
    const run = Math.hypot(pos.x - last.x, pos.z - last.z);
    if (run > 0.001 && dh / run > maxGrade){ pos.x = last.x; pos.z = last.z; hit = true; }
  }
  for (const m of (LAND ? [] : S.mountains || [])){
    const dx = pos.x - m.x, dz = pos.z - m.z, d = Math.hypot(dx, dz), r = m.r * 0.72;
    if (d < r && d > 0.001){ pos.x = m.x + dx / d * r; pos.z = m.z + dz / d * r; hit = true; }
  }
  for (const [x, z, k] of treesNear(pos.x, pos.z)){
    const dx = pos.x - x, dz = pos.z - z, d = Math.hypot(dx, dz), r = 0.55 * k + 0.35;
    if (d < r && d > 0.001){ pos.x = x + dx / d * r; pos.z = z + dz / d * r; hit = true; }
  }
  for (const c of colliders){
    const dx = pos.x - c.x, dz = pos.z - c.z, d = Math.hypot(dx, dz);
    if (d < c.r && d > 0.001){ pos.x = c.x + dx / d * c.r; pos.z = c.z + dz / d * c.r; hit = true; }
  }
  return hit;
}
WALKER.on("OnLand", () => { if (S.player) S.player.pose && (S.player.pose.squash = 0.84); });
WALKER.on("OnSwingHit", () => FIGHT.swing());

function updatePlayer(dt){
  const P = S.player; if (!P) return;
  const busyTravel = S.ST && /^Travelling/.test(S.ST.activity || "");
  if (camMode === "third" && orbiting()) orbitKeys(dt);
  else if (camMode === "third") arrowCamera(dt);
  // THE MAP MOVES YOU (2026-11-01): outside a convoy your feet are the
  // server's; third person is for looking round.
  if (mapDriven()){
    pressed.clear();
    updateMapUnit(dt);
    youRing.position.set(P.root.position.x, P.root.position.y + 0.12, P.root.position.z);
    youRing.visible = !riding();
    followSun(focusPoint());
    return;
  }
  // INPUT -> INTENT. In the overview WASD pans the map, not you.
  const control = camMode === "third" && !orbiting();
  let it = readIntent({held: control ? keys : new Set(), pressed: control ? pressed : new Set()}, yaw);
  pressed.clear();
  if (it.moving){ autoTarget = null; autoOnArrive = null; marker.visible = false; }
  else if (autoTarget && !busyTravel){
    const to = autoTarget.clone().sub(P.root.position).setY(0), d = to.length();
    if (d < 1.2){
      autoTarget = null; marker.visible = false;
      const cb = autoOnArrive; autoOnArrive = null; if (cb) cb();
    } else {
      to.normalize();
      // Walking somewhere for you: forward along the way, the camera's frame aside.
      it = {...it, moving: true, moveX: to.x, moveZ: to.z, ax: 0, ay: 1, sprint: d > 40, auto: true};
    }
  }
  const locked = busyTravel || !!S.travelling;
  if (riding()) updateRiding(dt, it, locked);
  else updateWalking(dt, it, locked);
  youRing.position.set(P.root.position.x, P.root.position.y + 0.12, P.root.position.z);
  youRing.visible = !riding();
  followSun(focusPoint());
  youRing.scale.setScalar(1 + 0.08 * Math.sin(performance.now() / 260));
  arrivals(busyTravel);
}

function updateWalking(dt, it, locked){
  const P = S.player;
  const g0 = groundAt(P.root.position.x, P.root.position.z);
  if (!WALKER.ready){ WALKER.s.y = g0; WALKER.ready = true; }
  // A cart is still a faster walk; animals are ridden (updateRiding).
  const cart = S.ST && S.ST.vehicle && !RIDEABLE.has(S.ST.vehicle) ? (S.ST.speed || 1) : 1;
  const s = WALKER.step(dt, it, g0, {locked, speedMul: (FIGHT.blocking ? 0.4 : 1) * cart});
  const last = P.root.position.clone();
  P.root.position.x += s.vx * dt; P.root.position.z += s.vz * dt;
  if (collide(P.root.position, last)){
    // Bumping something takes the speed out of you, the way it does.
    const dx = (P.root.position.x - last.x) / Math.max(dt, 1e-4), dz = (P.root.position.z - last.z) / Math.max(dt, 1e-4);
    s.vx = dx; s.vz = dz;
  }
  P.root.position.y = s.y;
  P.vel = (P.vel || new THREE.Vector3()).set(s.vx, 0, s.vz);
  const speed = Math.hypot(s.vx, s.vz);
  // FACING, as Fortnite: you face where the camera looks while you move or
  // aim, leaning into a strafe; a slide goes where it is going; walking
  // somewhere for you, you face the way.
  let want = null;
  if (s.state === "slide" || it.auto) want = speed > 0.2 ? Math.atan2(s.vx, s.vz) : null;
  else if (camMode === "third" && (it.moving || s.aiming || s.swingT >= 0)){
    const lean = it.moving ? Math.atan2(it.ax, Math.max(0.001, Math.abs(it.ay))) * 0.6 * (it.ay < 0 ? -1 : 1) : 0;
    want = yaw + Math.PI + lean;
  } else if (speed > 0.3) want = Math.atan2(s.vx, s.vz);
  if (want != null){
    let dh = want - P.heading; dh = Math.atan2(Math.sin(dh), Math.cos(dh));
    P.heading += dh * Math.min(1, dt * 14);
  }
  P.root.rotation.y = P.heading;
  // ANIMATION from the state.
  const working = S.ST && /^Working/.test(S.ST.activity || "");
  const back = it.moving && it.ay < 0 && !it.auto && camMode === "third";
  let clip = "idle", rate = 1;
  if ((FIGHT.swinging() || s.swingT >= 0) && (P.acts.attack || P.acts.work)) clip = P.acts.attack ? "attack" : "work";
  else if (FIGHT.blocking && P.acts.block && speed < 0.3) clip = "block";
  else if (s.state === "air" || s.state === "slide"){ clip = "run"; rate = 0.05; }
  else if (s.state === "sprint"){ clip = "run"; rate = speed / 9.0; }
  else if (speed > 0.3){ clip = "walk"; rate = (back ? -1 : 1) * Math.max(0.5, speed / 4.5); }
  else if (working && P.acts.work) clip = "work";
  setAnim(P, clip, rate);
  P.mixer.update(dt);
  // POSE: lean back into a slide, tuck in the air, squash on landing.
  const body = P.root.children[0];
  P.pose = P.pose || {tilt: 0, drop: 0, squash: 1, y: body.position.y};
  const tilt = s.state === "slide" ? -1.1 : s.state === "air" ? 0.15 : 0;
  P.pose.tilt += (tilt - P.pose.tilt) * Math.min(1, dt * 16);
  P.pose.drop += ((s.state === "slide" ? -0.2 : 0) - P.pose.drop) * Math.min(1, dt * 16);
  P.pose.squash += (1 - P.pose.squash) * Math.min(1, dt * 12);
  body.rotation.x = P.pose.tilt; body.position.y = P.pose.y + P.pose.drop;
  body.scale.y = body.scale.x * P.pose.squash;
}

/* THE HUD for movement: stamina (yours, or your animal's and its gait), the
   crosshair that widens with spread, and the debug readout (` key) with the
   state and the live numbers, for tuning by feel. */
let DEBUG = false, hudAt = 0, LAST_RIDING = null;
const HUD = {};
function hudEl(id, cls){
  if (!HUD[id]){ HUD[id] = document.createElement("div"); HUD[id].id = id; if (cls) HUD[id].className = cls; document.body.appendChild(HUD[id]); }
  return HUD[id];
}
function updateHUD(now){
  if (now - hudAt < 50) return;
  hudAt = now;
  const third = camMode === "third" && S.player, ride = riding();
  // Stamina: shown while it is not full, or while you sprint or gallop.
  const st = hudEl("stam"), w = WALKER.s, r = RIDER.s;
  const val = ride ? r.stamina / TUNE.mountStaminaMax : w.stamina / TUNE.staminaMax;
  const show = third && (val < 0.999 || (ride ? r.gait >= 3 : w.state === "sprint"));
  st.style.display = show ? "block" : "none";
  if (show) st.innerHTML = `<i style="width:${Math.round(val * 100)}%" class="${val < 0.2 ? "low" : ""}"></i>`
    + (ride ? `<b>${TUNE.gaitNames[r.gait]}</b>` : "");
  // Crosshair: on foot, mouse taken.
  const rt = hudEl("reticle");
  rt.style.display = third && !ride && (mouseLook || w.aiming) ? "block" : "none";
  if (rt.style.display === "block"){
    const gap = 6 + (w.spreadNow || 1) * 7;
    rt.style.setProperty("--gap", `${gap}px`);
    rt.classList.toggle("aim", w.aiming);
  }
  const dbg = hudEl("dbg");
  dbg.style.display = DEBUG ? "block" : "none";
  if (DEBUG){
    const sp = Math.hypot(w.vx, w.vz);
    dbg.textContent = ride
      ? `RIDING  gait ${TUNE.gaitNames[r.gait]}  speed ${r.speed.toFixed(2)}  turn ${r.turn.toFixed(2)}\nmount stamina ${r.stamina.toFixed(0)}  heading ${(r.heading * 57.3 % 360).toFixed(0)}  fov ${camera.fov.toFixed(1)}`
      : `state ${w.state}${w.aiming ? " +aim" : ""}  speed ${sp.toFixed(2)}  vy ${w.vy.toFixed(2)}  ${w.grounded ? "grounded" : "airborne"}\n`
        + `stamina ${w.stamina.toFixed(0)}  slide cd ${w.slideCool.toFixed(2)}  swing cd ${w.swingCool.toFixed(2)}  spread ${(w.spreadNow || 0).toFixed(2)}  fov ${camera.fov.toFixed(1)}\n`
        + `walk ${TUNE.walk} sprint ${TUNE.sprint} jump ${TUNE.jumpHeight} g ${TUNE.gravityUp}/${TUNE.gravityDown}  (window.convoy.tune)`;
  }
}

/* RIDING (Red Dead): the donkey carries you; move.js's rider has the gaits. */
const SADDLE = 0.12;                        // hips at the animal's back, legs astride
function updateRiding(dt, it, locked){
  const P = S.player, D = DONKEY;
  const r = RIDER.step(dt, it, {locked, ...CONVOY.limits()});
  const last = D.root.position.clone();
  D.root.position.x += Math.sin(r.heading) * r.speed * dt;
  D.root.position.z += Math.cos(r.heading) * r.speed * dt;
  if (collide(D.root.position, last, 0.58)) r.speed *= 0.4;
  D.root.position.y = groundAt(D.root.position.x, D.root.position.z);
  D.root.rotation.y = r.heading; D.heading = r.heading;
  P.root.position.set(D.root.position.x, D.root.position.y + SADDLE, D.root.position.z);
  P.heading = r.heading; P.root.rotation.y = r.heading;
  P.vel = (P.vel || new THREE.Vector3()).set(Math.sin(r.heading) * r.speed, 0, Math.cos(r.heading) * r.speed);
  setAnim(P, "idle", 1); P.mixer.update(dt);
  const body = P.root.children[0];
  if (P.pose){ body.rotation.x = 0; body.position.y = P.pose.y; body.scale.y = body.scale.x; }
  WALKER.s.y = D.root.position.y; WALKER.s.vx = WALKER.s.vz = 0;
}

/* Arriving somewhere is news to the server; so is leaving where you work. */
function arrivals(busyTravel){
  const P = S.player;
  const working = S.ST && /^Working/.test(S.ST.activity || "");
  const at = placeAt(P.root.position);
  if (working && (!at || at.name !== S.here) && !S.departing && !busyTravel){
    S.departing = true;
    api.post("/api/depart", {}).then(r => { if (r && r.message) UI.toast(r.message); UI.refreshSoon(); })
      .finally(() => setTimeout(() => { S.departing = false; }, 3000));
  }
  // Out of a place with goods on you: the convoy is offered.
  if (at) S.inside = at.name;
  else if (S.inside){ const from = S.inside; S.inside = null; if (!busyTravel && !S.travelling) CONVOY.left(from); }
  if (at && at.name !== S.here && !S.arriving && !busyTravel && !S.travelling){
    S.arriving = true;
    api.post("/api/arrive", {place: at.name}).then(r => {
      S.arriving = false;
      if (r.ok){
        S.here = at.name; UI.refreshSoon();
        CONVOY.arrived(r);
        if (r.haul) UI.toast(r.haul);
        if (S.errand && S.errand.place === at.name){ const e = S.errand; S.errand = null; if (e.buy) setTimeout(e.buy, 600); }
      }
    }).catch(() => { S.arriving = false; });
  }
}

/* HOLD CTRL OR CMD TO TURN THE CAMERA (designer request, 2026-10-18): the
   arrows (or WASD) turn and tilt it instead of moving, and so does moving the
   mouse, no button needed. */
const orbiting = () => keys.has("control") || keys.has("meta");
function orbitKeys(dt){
  const turn = (keys.has("a") || keys.has("arrowleft") ? 1 : 0) - (keys.has("d") || keys.has("arrowright") ? 1 : 0);
  const tilt = (keys.has("w") || keys.has("arrowup") ? 1 : 0) - (keys.has("s") || keys.has("arrowdown") ? 1 : 0);
  yaw += turn * 1.8 * dt;
  if (camMode === "strategy") sPitch = Math.max(0.35, Math.min(1.35, sPitch + tilt * 0.9 * dt));
  else pitch = Math.max(0.04, Math.min(1.45, pitch + tilt * 0.9 * dt));
}

function arrowCamera(dt){
  const turn = (keys.has("arrowleft") ? 1 : 0) - (keys.has("arrowright") ? 1 : 0);
  const tilt = (keys.has("arrowup") ? 1 : 0) - (keys.has("arrowdown") ? 1 : 0);
  yaw += turn * 1.8 * dt;
  if (camMode === "strategy") sPitch = Math.max(0.35, Math.min(1.35, sPitch + tilt * 0.9 * dt));
  else pitch = Math.max(0.04, Math.min(1.45, pitch + tilt * 0.9 * dt));
}
function updateStrategyCamera(dt){
  if (camera.fov !== 55){ camera.fov = 55; camera.updateProjectionMatrix(); }
  // Pan with the keys, relative to which way the camera faces; faster when high.
  const fwd = new THREE.Vector3(-Math.sin(yaw), 0, -Math.cos(yaw));
  const right = new THREE.Vector3(Math.cos(yaw), 0, -Math.sin(yaw));
  const pan = new THREE.Vector3();
  if (orbiting()) orbitKeys(dt);
  else {
  arrowCamera(dt);
  if (keys.has("w")) pan.add(fwd);
  if (keys.has("s")) pan.sub(fwd);
  if (keys.has("a")) pan.sub(right);
  if (keys.has("d")) pan.add(right);
  }
  if (pan.lengthSq()) focusGoal.addScaledVector(pan.normalize(), sDist * 1.1 * dt * (keys.has("shift") ? 2.2 : 1));
  focus.lerp(focusGoal, 0.18);
  const cam = focus.clone()
    .add(new THREE.Vector3(Math.sin(yaw), 0, Math.cos(yaw)).multiplyScalar(sDist * Math.cos(sPitch)))
    .add(new THREE.Vector3(0, sDist * Math.sin(sPitch), 0));
  camera.position.lerp(cam, 0.25);
  camera.lookAt(focus);
  scene.fog.near = Math.max(220, sDist * 1.6); scene.fog.far = Math.max(1000, sDist * 5);
  followSun(focus);
}

function updateCamera(dt){
  if (camMode === "strategy") return updateStrategyCamera(dt);
  // THE FRONTIER IS HAZY (2026-10-30): with outposts the air closes in, so
  // you find what is out there by riding to it; smoke still shows above it.
  if (outposts()){ scene.fog.near = 60; scene.fog.far = 340; } else { scene.fog.near = 180; scene.fog.far = 900; }
  const P = S.player; if (!P) return;
  const ride = riding();
  // RIDING (Red Dead): the camera drifts back behind the animal when you
  // leave the mouse alone.
  if (ride && performance.now() - lastLook > 1200 && Math.abs(RIDER.s.speed) > 0.5){
    let dy = (RIDER.s.heading + Math.PI) - yaw; dy = Math.atan2(Math.sin(dy), Math.cos(dy));
    yaw += dy * Math.min(1, dt * 1.6);
  }
  const fwd = new THREE.Vector3(-Math.sin(yaw), 0, -Math.cos(yaw));
  const right = new THREE.Vector3(Math.cos(yaw), 0, -Math.sin(yaw));
  // Over the right shoulder, Fortnite-style: close, the character a little
  // left of centre and low in the frame; lower in a slide. Riding, higher and
  // further back, centred on the animal.
  const high = ride ? 2.1 : WALKER.s.state === "slide" ? 1.0 : 1.6;
  const target = P.root.position.clone().add(new THREE.Vector3(0, high, 0)).addScaledVector(right, ride ? 0 : 0.75);
  const fov = 70 + (ride ? (RIDER.s.gait >= 4 ? 7 : RIDER.s.gait >= 3 ? 3 : 0) : WALKER.s.fovOffset);
  if (Math.abs(camera.fov - fov) > 0.05){ camera.fov += (fov - camera.fov) * Math.min(1, dt * 12); camera.updateProjectionMatrix(); }
  // THE CAMERA DOES NOT GO THROUGH WALLS. If a building stands between you
  // and where the camera wants to be, the camera comes in to this side of it.
  // Buildings are circles on the ground for this, the same as for walking.
  let d = ride ? Math.max(dist, 6) : dist;
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
  // Nor through tree crowns: a crown behind you pulls the camera in front of it.
  for (const [x, z, k] of treesNear(target.x, target.z)){
    const ox = target.x - x, oz = target.z - z, rr = 2.4 * k;
    const b = ox * back.x + oz * back.z, cc = ox * ox + oz * oz - rr * rr, disc = b * b - cc;
    if (disc < 0) continue;
    const t = -b - Math.sqrt(disc);
    if (t > 0.8 && t < d * Math.cos(pitch)) d = Math.max(2.2, t / Math.cos(pitch) - 0.3);
  }
  const cam = target.clone().addScaledVector(fwd, -d * Math.cos(pitch)).add(new THREE.Vector3(0, d * Math.sin(pitch), 0));
  // THE CAMERA STAYS ABOVE THE HILLS between it and you, not just under itself.
  for (let k = 0.25; k <= 1.0001; k += 0.25){
    const x = target.x + (cam.x - target.x) * k, z = target.z + (cam.z - target.z) * k;
    cam.y = Math.max(cam.y, groundAt(x, z) + 0.9);
  }
  camera.position.lerp(cam, 1 - Math.exp(-dt * (ride ? 7 : 16)));   // close behind, a touch of lag
  // Look where the crosshair points: along the camera's yaw, down by its pitch.
  const look = new THREE.Vector3(fwd.x * Math.cos(pitch), -Math.sin(pitch) * 0.85, fwd.z * Math.cos(pitch));
  camera.lookAt(camera.position.clone().addScaledVector(look, 10));
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
    v.root.position.y = groundAt(v.root.position.x, v.root.position.z);
    const reach = camMode === "strategy" ? Math.max(260, sDist * 2.2) : 260;
    const near = v.root.position.distanceToSquared(focusPoint()) < reach * reach && found(v.id);
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
    p.label.visible = d < 170 * zoomK && (camMode === "strategy" || d > 8) && (p.kind !== "claim" || landShown(p.owner, p.c));
    p.label.element.style.opacity = d < 40 ? 0.6 : 1;
  }
  const marks = (S.ADV && S.ADV.markers) || {};
  for (const v of S.buildings.values()){
    const d = cp.distanceTo(v.pos), mk = marks[v.b.id];
    const lbl = v.root.userData.label;
    // A building with something for you shows from further off.
    lbl.visible = v.root.visible && (d < 120 * zoomK || (mk && ((mk.icons && mk.icons.length) || mk.health) && d < 280 * zoomK));
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
  if (type === "Land claim"){
    body = new THREE.Group();
    const stake = new THREE.Mesh(new THREE.CylinderGeometry(0.25, 0.3, 5, 8)); stake.position.y = 2.5;
    const flag = new THREE.Mesh(new THREE.BoxGeometry(2.6, 1.6, 0.1)); flag.position.set(1.3, 4.1, 0);
    body.add(stake, flag);
  } else if (type === "Guard post" || type === "Catapult"){
    body = makeDefense(type);
  } else if (key && MODELS[key]){
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
/* ------------------------------------------------------------ settling (outposts) */
/* OUTPOSTS (2026-10-27): nobody starts in a town. Everyone, you included,
   is settled on open land at the start (2026-10-30); the server prices any
   land claimed after that (by what is built nearby, plus its road). */
const QUOTES = new Map();
function outposts(){ return !!(S.ST && S.ST.you && S.ST.you.outposts); }
/* FINDING PEOPLE (2026-10-28): with outposts you see a settler -- their
   figure, home, claims and businesses -- only once you have found them. The
   state's trading posts and your own are always there. */
let KNOWN = new Set();
function found(owner){
  return !outposts() || !owner || owner === G.you || owner === "Government" || KNOWN.has(owner);
}
function shown(root, on){
  root.visible = on;
  root.traverse(o => { if (o.isCSS2DObject) o.visible = on; });
}
let SEEN_SIG = "";
function checkKnown(){
  const k = (S.ST && S.ST.you && S.ST.you.known) || [];
  KNOWN = new Set(k);
  // Re-checked on every status: what you have explored grows as you ride.
  const sig = `${k.length}|${((S.ST && S.ST.you.locations_from) || []).length}|${HEXMAP.known.size}`;
  if (sig === SEEN_SIG) return;
  SEEN_SIG = sig;
  landKey = "";                                    // repaint the plots
  for (const [owner, v] of S.homeObjs) shown(v.root, landShown(owner, v.pos));
  for (const v of S.buildings.values()) v.root.visible = landShown(v.b.owner, v.pos);
  for (const root of S.defenses.values()) shown(root, landShown(root.userData.owner, root.position));
}
/* SMOKE ON THE HORIZON (2026-10-28): a settler you have not found shows as
   a thread of chimney smoke from up to 1.5 km off (discovery.GLIMPSE_M) --
   someone lives over there -- but who, and what they have, you learn by going. */
const GLIMPSE = 1500 * SCALE, SIGHT = 400 * SCALE;
const SMOKE = new Map();                         // owner -> {group, pos}
let smokeTex = null;
function smokeTexture(){
  if (smokeTex) return smokeTex;
  const c = document.createElement("canvas"); c.width = c.height = 64;
  const g = c.getContext("2d"), r = g.createRadialGradient(32, 32, 2, 32, 32, 30);
  r.addColorStop(0, "rgba(112,104,98,0.95)"); r.addColorStop(0.5, "rgba(128,120,112,0.55)"); r.addColorStop(1, "rgba(140,132,124,0)");
  g.fillStyle = r; g.fillRect(0, 0, 64, 64);
  smokeTex = new THREE.CanvasTexture(c);
  smokeTex.colorSpace = THREE.SRGBColorSpace;
  return smokeTex;
}
function plume(pos){
  const group = new THREE.Group();
  for (let i = 0; i < 8; i++){
    const m = new THREE.SpriteMaterial({map: smokeTexture(), color: "#4f4741", transparent: true, depthWrite: false,
                                        opacity: 0.5, toneMapped: false, fog: false});
    const sp = new THREE.Sprite(m); sp.userData.phase = i / 8; group.add(sp);
  }
  group.position.set(pos.x, groundAt(pos.x, pos.z) + 6, pos.z);
  scene.add(group);
  return group;
}
function updateSmoke(now){
  if (!outposts() || !S.player || !S.ST || !S.ST.you.settled){
    for (const v of SMOKE.values()) v.group.visible = false;
    return;
  }
  const me = S.player.root.position, t = now / 1000;
  for (const [owner, home] of S.homeObjs){
    if (owner === G.you) continue;
    const d = Math.hypot(home.pos.x - me.x, home.pos.z - me.z);
    const want = !landShown(owner, home.pos) && d < GLIMPSE && d > SIGHT * 0.5;
    let v = SMOKE.get(owner);
    if (!want){ if (v) v.group.visible = false; continue; }
    if (!v){ v = {group: plume(home.pos)}; SMOKE.set(owner, v); }
    v.group.visible = true;
    v.group.children.forEach(sp => {
      const k = (t * 0.08 + sp.userData.phase) % 1;         // rises, spreads, fades
      // Tall enough to show over the hills and trees in between.
      sp.position.set(Math.sin(k * 3 + sp.userData.phase * 9) * 4 * k, 6 + k * 84, 0);
      sp.scale.setScalar(8 + k * 26);
      sp.material.opacity = 0.75 * (1 - k * 0.85);
    });
  }
}

/* OVER THE SHOULDER BY DEFAULT (2026-10-28): the game opens behind your
   character, and Tab or scrolling out still gives the overview. */
let POV_SET = false;
function defaultView(){
  if (POV_SET || !S.ST || !S.player) return;
  POV_SET = true;
  if (camMode !== "third" && !outposts()) enterThird();
}
function landQuote(cx, cz){
  const key = `${Math.round(cx / CELL)},${Math.round(cz / CELL)}`;
  if (QUOTES.has(key)) return QUOTES.get(key);
  QUOTES.set(key, null);
  const w = toWorld(new THREE.Vector3(cx, 0, cz));
  api.post("/api/settle", {x: w.x, y: w.y, quote: true}).then(r => {
    QUOTES.set(key, r && r.ok ? r : {why_not: (r && r.message) || "cannot price this land"});
    if (placing && lastGround) updatePlacement(lastGround);
  }).catch(() => QUOTES.delete(key));
  return null;
}
function startPlacing(type){
  stopPlacing();
  clearSelection();
  if (type === "Road"){ startRoad(); return; }
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
  if (placing.road){ updateRoad(point); return; }
  const spec = (S.BOARD ? S.BOARD.business_types : []).find(t => t.name === placing.type) || {cost: 0, spur: false};
  // A business takes the 2x2 block whose shared corner is nearest the cursor;
  // a defense takes the one square under it (2026-10-18).
  const one = spec.size === 1;
  const gx = one ? Math.floor(point.x / CELL) : Math.round(point.x / CELL) - 1;
  const gz = one ? Math.floor(point.z / CELL) : Math.round(point.z / CELL) - 1;
  const keys = one ? [`${gx},${gz}`] : [`${gx},${gz}`, `${gx + 1},${gz}`, `${gx},${gz + 1}`, `${gx + 1},${gz + 1}`];
  const cells = keys.map(k => S.cells.get(k));
  const cx = one ? (gx + 0.5) * CELL : (gx + 1) * CELL, cz = one ? (gz + 0.5) * CELL : (gz + 1) * CELL;
  const cash = S.ST ? S.ST.you.denari : 0;
  let why = "";
  let place = cells[0] && cells[0].place;
  // OPEN LAND (2026-10-18): four squares nobody has laid out are a claim to make.
  const wild = !one && cells.every(c => !c);
  let roadM = 0;
  if (wild){
    roadM = Math.max(0, distToRoads(cx, cz)) / SCALE;
    const centres = keys.map(k => k.split(",").map(Number)).map(([gx2, gz2]) => [(gx2 + 0.5) * CELL, (gz2 + 0.5) * CELL]);
    const wetHere = ([x, z]) => S.riverLines && (S.riverLines.x.some(rx => Math.abs(x - rx) < 12) || S.riverLines.z.some(rz => Math.abs(z - rz) < 15));
    if (centres.some(wetHere)) why = "That is in the river";
    else if (centres.some(([x, z]) => distToRoads(x, z) < CELL * 0.62)) why = "That is on a road";
    // With outposts you may build anywhere the ground is not river or road
    // (designer request, 2026-10-30); claims.check says the same.
    else if (!outposts() && (S.mountains || []).some(mt => Math.hypot(cx - mt.x, cz - mt.z) < mt.r + CELL)) why = "That is on the mountainside";
    else if (!outposts() && roadM > 1200) why = "Too far from any road";   // claims.MAX_ROAD_M
    else if (!outposts() && cash < spec.cost + roadM * 0.12) why = `Need ${Math.ceil(spec.cost + roadM * 0.12 - cash)} more`;
    place = null;
  } else if (!cells.every(Boolean)) why = "Build on a place's squares, or on open land";
  else if (!cells.every(c => c.place === place)) why = "All four squares must be in one place";
  // YOUR OWN LAND takes anything (2026-10-30): a land claim's squares are
  // free to build on for you -- a business, a guard post -- until something
  // stands there.
  else if (cells.some(c => { const o = S.cellOwner.get(c.key); return o && (o.owner !== G.you || o.business || o.home || o.structure); })) why = "Those squares are not free";
  else if (spec.claim && cells.some(c => S.cellOwner.has(c.key))) why = "That land is yours already: build on it";
  else if (!outposts() && !spec.defense && !spec.claim && S.places[place].kind !== "claim" && (S.places[place].kind === "spur") !== !!spec.spur) why = spec.spur ? "Farms and mines need spur land" : "This belongs on the main road, not a spur";
  else if (cash < spec.cost) why = `Need ${Math.ceil(spec.cost - cash)} more`;
  // OUTPOSTS (2026-10-27): open land has a price, set by the server from how
  // much is built nearby. Ask for it; until it answers, say so.
  let q = null;
  if (wild && !why && outposts()){
    q = landQuote(cx, cz);
    if (!q) why = "Pricing this land…";
    else if (q.why_not) why = q.why_not[0].toUpperCase() + q.why_not.slice(1);
    else {
      const short = spec.cost + q.total - cash;
      if (short > 0) why = `Need ${Math.ceil(short)} more`;
    }
  }
  placing.valid = !why; placing.why = why; placing.cells = keys; placing.place = place; placing.wild = wild;
  placing.cx = cx; placing.cz = cz;
  const g = placing.ghost;
  g.position.set(cx, groundAt(cx, cz), cz);
  if (place){ const pc = S.places[place].c; g.rotation.y = Math.atan2(pc.x - cx, pc.z - cz); }
  g.userData.mat.color.set(why ? "#ff6a5a" : "#3fd8ff");
  g.userData.lines.color.set(why ? "#ffd0c8" : "#c8f7ff");
  const hint = groundHint(placing.type, cx, cz);
  let where = wild ? `open land \u00b7 road ${Math.round(roadM)} m (${Math.round(roadM * 0.12)})` : esc(place);
  let total = Math.round(spec.cost + (wild ? roadM * 0.12 : 0));
  if (q && !q.why_not){
    total = Math.round(spec.cost + q.total);
    where = q.free ? `free \u00b7 a dirt road of ${Math.round(q.road_m)} m`
      : !q.road_included ? `land ${Math.round(q.land_cost)} \u00b7 no road: the nearest is ${Math.round(q.road_m)} m off`
      : `land ${Math.round(q.land_cost)} \u00b7 road ${Math.round(q.road_m)} m (${Math.round(q.road_cost)})`;
  }
  const verb = wild ? "claim and build" : "build";
  g.userData.tag.element.innerHTML = why ? `<b>${esc(placing.type.split(" /")[0])}</b><small class="no">${esc(why)}</small>`
    : `<b>${esc(placing.type.split(" /")[0])}${q && q.free ? "" : ` \u00b7 ${total}`}</b><small>${where} \u00b7 click to ${verb}</small>${hint ? `<small class="hint">${esc(hint)}</small>` : ""}`;
  blockSq.forEach((b, i) => { if (i >= keys.length) b.visible = false; });
  keys.forEach((k, i) => {
    const sq = blockSq[i];
    sq.position.set((gx + (i % 2) + 0.5) * CELL, 0.17, (gz + Math.floor(i / 2) + 0.5) * CELL);
    const col = why ? "#ff6a5a" : "#7dff8a";
    sq.userData.fill.material.color.set(col); sq.userData.ring.material.color.set(col);
    sq.visible = true;
  });
  UI.placingChanged(placing.type);
}
/* BUILDING A ROAD (outposts, 2026-10-30): "you have to pay and manually
   build roads to connect farms and homes". Pick Road in the build menu,
   click your land (or it starts from your only land without one), then
   click a road or another claim: the server prices it and lays it. */
function roadGhost(){
  const root = new THREE.Group();
  const mat = new THREE.MeshBasicMaterial({color: "#4fe0ff", transparent: true, opacity: 0.55, depthWrite: false});
  const strip = new THREE.Mesh(new THREE.PlaneGeometry(1, 1), mat);
  strip.rotation.x = -Math.PI / 2; strip.raycast = () => {};
  root.add(strip); root.userData.strip = strip; root.userData.mat = mat;
  const el = document.createElement("div"); el.className = "holo-tag";
  const tag = new CSS2DObject(el); root.add(tag); root.userData.tag = tag;
  scene.add(root);
  return root;
}
function myLand(){ return Object.values(S.places).filter(p => p.kind === "claim" && p.owner === G.you); }
function startRoad(){
  const bare = ((S.ST && S.ST.you.land) || []).filter(l => !l.road);
  if (!bare.length){ UI.toast("All your land has a road already", "bad"); return; }
  placing = {type: "Road", road: true, ghost: roadGhost(), from: bare.length === 1 ? S.places[bare[0].name] : null};
  renderer.domElement.style.cursor = "crosshair";
  UI.toast(placing.from ? `A road from ${placing.from.name}: click a road or another claim, Esc to cancel`
                        : "Click your land to build a road from it, Esc to cancel");
  UI.placingChanged("Road");
  if (lastGround) updateRoad(lastGround);
}
const ROAD_QUOTES = new Map();
function roadQuote(from, x, z){
  const key = `${from}|${Math.round(x / 4)},${Math.round(z / 4)}`;
  if (ROAD_QUOTES.has(key)) return ROAD_QUOTES.get(key);
  ROAD_QUOTES.set(key, null);
  const w = toWorld(new THREE.Vector3(x, 0, z));
  api.post("/api/road", {place: from, x: w.x, y: w.y, quote: true}).then(r => {
    ROAD_QUOTES.set(key, r && r.ok ? r : {why_not: (r && r.message) || "cannot build a road there"});
    if (placing && placing.road && lastGround) updateRoad(lastGround);
  }).catch(() => ROAD_QUOTES.delete(key));
  return null;
}
function updateRoad(point){
  const g = placing.ghost, strip = g.userData.strip, tag = g.userData.tag.element;
  if (!placing.from){
    // Which of your land the click would start from.
    const near = myLand().filter(p => Math.hypot(p.c.x - point.x, p.c.z - point.z) < CELL * 3);
    placing.pick = near[0] || null;
    const at = placing.pick ? placing.pick.c : point;
    strip.scale.set(CELL * 2, CELL * 2, 1);
    strip.position.set(at.x, groundAt(at.x, at.z) + 0.25, at.z); strip.rotation.z = 0;
    g.userData.tag.position.set(at.x, groundAt(at.x, at.z) + 6, at.z);
    g.userData.mat.color.set(placing.pick ? "#3fd8ff" : "#ff6a5a");
    tag.innerHTML = placing.pick ? `<b>Road from ${esc(placing.pick.name)}</b><small>click to start here</small>`
                                 : `<b>Road</b><small class="no">Click your own land to start</small>`;
    placing.valid = !!placing.pick;
    return;
  }
  const a = placing.from.c, q = roadQuote(placing.from.name, point.x, point.z);
  // Drawn to where it would really end: the point on the road it snaps to.
  const end = q && !q.why_not ? toScene(q.to[0], q.to[1]) : point;
  const dx = end.x - a.x, dz = end.z - a.z, len = Math.hypot(dx, dz) || 0.01;
  strip.scale.set(3.2, len, 1);
  strip.position.set((a.x + end.x) / 2, groundAt((a.x + end.x) / 2, (a.z + end.z) / 2) + 0.3, (a.z + end.z) / 2);
  strip.rotation.z = Math.atan2(dx, dz);
  g.userData.tag.position.set(end.x, groundAt(end.x, end.z) + 6, end.z);
  const cash = S.ST ? S.ST.you.denari : 0;
  let why = !q ? "Pricing this road…" : q.why_not ? q.why_not[0].toUpperCase() + q.why_not.slice(1)
    : q.cost > cash ? `Need ${Math.ceil(q.cost - cash)} more` : "";
  placing.valid = !why; placing.quote = q;
  g.userData.mat.color.set(why ? "#ff6a5a" : "#3fd8ff");
  tag.innerHTML = why ? `<b>Road from ${esc(placing.from.name)}</b><small class="no">${esc(why)}</small>`
    : `<b>Road · ${Math.round(q.cost)}</b><small>${q.metres} m to ${esc(q.joins)} · click to build</small>`
      + (q.connects ? `<small class="hint">The state's convoy can then collect from here</small>`
                    : `<small class="hint">${esc(q.joins)} has no road to the main roads yet</small>`);
}
async function confirmRoad(){
  if (!placing.from){
    if (!placing.pick){ UI.toast("Click your own land to start", "bad"); return; }
    const l = ((S.ST && S.ST.you.land) || []).find(x => x.name === placing.pick.name);
    if (l && l.road){ UI.toast(`${l.name} has a road already`, "bad"); return; }
    placing.from = placing.pick;
    ROAD_QUOTES.clear();
    if (lastGround) updateRoad(lastGround);
    return;
  }
  if (!placing.valid){ UI.toast(placing.why || (placing.quote && placing.quote.why_not) || "Not there", "bad"); return; }
  const from = placing.from.name, q = placing.quote;
  stopPlacing();
  const r = await api.post("/api/road", {place: from, x: q.to[0], y: q.to[1]});
  ROAD_QUOTES.clear();
  if (!r.ok){ UI.toast(r.message, "bad"); return; }
  drawClaimRoad(from, r.road, true);
  const l = ((S.ST && S.ST.you.land) || []).find(x => x.name === from); if (l) l.road = true;
}

/* What the ground here promises, before you build: near water for farms,
   near mountains for mines. The luck itself stays hidden till the harvest. */
function groundHint(type, x, z){
  if (type === "Farm" && S.riverLines){
    const d = Math.min(...S.riverLines.x.map(rx => Math.abs(x - rx)), ...S.riverLines.z.map(rz => Math.abs(z - rz)));
    const m = d / SCALE;
    return m < 250 ? "Near water: farms here strike rich soil more often" : m < 600 ? "Some way from water: an ordinary chance of rich soil" : "Far from water: rich soil is rare here";
  }
  if (type === "Mining Operation" && S.mountains && S.mountains.length){
    const d = Math.min(...S.mountains.map(p => Math.hypot(x - p.x, z - p.z) - p.r)) / SCALE;
    return d < 350 ? "Near the mountains: rich seams are likely" : d < 800 ? "Some way from the mountains: an ordinary chance of a rich seam" : "Far from the mountains: rich seams are rare";
  }
  return "";
}
function confirmPlacement(){
  if (!placing) return;
  if (placing.road){ confirmRoad(); return; }
  if (!placing.valid){ UI.toast(placing.why, "bad"); return; }
  const {type, place, cells, wild, cx, cz} = placing;
  const spec = (S.BOARD ? S.BOARD.business_types : []).find(t => t.name === type) || {};
  stopPlacing();
  if (wild){ wildFound(type, cx, cz, !!spec.claim); return; }
  if (spec.claim) buyOn(place, cells);
  else if (spec.defense) defendOn(place, cells, type); else foundOn(place, cells, type);
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
  hoverSq.position.set((gx + 0.5) * CELL, groundAt((gx + 0.5) * CELL, (gz + 0.5) * CELL) + 0.16, (gz + 0.5) * CELL);
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
/* MOUSE LOOK (2026-10-31): over the shoulder, a click takes the mouse --
   it turns the camera, left button swings, right button aims; Esc gives it
   back for the panels. */
let mouseLook = false, LOCK_OK = true;
// Some embedded browsers refuse pointer lock; then the mouse looks by dragging,
// as before.
function lockMouse(){
  if (camMode !== "third" || mouseLook || !LOCK_OK || !renderer.domElement.requestPointerLock) return;
  try {
    const r = renderer.domElement.requestPointerLock();
    if (r && r.catch) r.catch(() => { LOCK_OK = false; modeChanged(); });
  } catch (e){ LOCK_OK = false; }
}
document.addEventListener("pointerlockerror", () => { LOCK_OK = false; modeChanged(); });
function freeMouse(){ if (mouseLook && document.exitPointerLock) document.exitPointerLock(); }
document.addEventListener("pointerlockchange", () => {
  mouseLook = document.pointerLockElement === renderer.domElement;
  if (!mouseLook) keys.delete("mouse2");
  modeChanged();
});
document.addEventListener("mousemove", e => {
  if (!mouseLook) return;
  const k = WALKER.s.aiming ? 0.55 : 1;                    // finer while aiming
  yaw -= (e.movementX || 0) * 0.0022 * k;
  pitch = Math.max(-0.45, Math.min(1.25, pitch + (e.movementY || 0) * 0.0018 * k));
  lastLook = performance.now();
});
renderer.domElement.addEventListener("contextmenu", e => { if (camMode === "third") e.preventDefault(); });
renderer.domElement.addEventListener("mousedown", e => {
  if (!mouseLook) return;
  if (e.button === 0) pressed.add("mouse0");
  if (e.button === 2) keys.add("mouse2");
});
addEventListener("mouseup", e => { if (e.button === 2) keys.delete("mouse2"); });
renderer.domElement.addEventListener("pointerdown", e => {
  if (camMode === "third" && !placing && LOCK_OK){
    if (!mouseLook && e.button === 0){ lockMouse(); pointer.swallow = true; return; }
    if (mouseLook){ pointer.swallow = true; return; }
  }
  if (camMode === "third" && !mouseLook && e.button === 2) keys.add("mouse2");   // aim without the lock
  pointer.down = true; pointer.x = e.clientX; pointer.y = e.clientY; pointer.moved = 0; pointer.button = e.button;
  renderer.domElement.setPointerCapture(e.pointerId);
});
renderer.domElement.addEventListener("pointermove", e => {
  if (mouseLook) return;
  if (pointer.down){
    const dx = e.clientX - pointer.x, dy = e.clientY - pointer.y;
    pointer.moved += Math.abs(dx) + Math.abs(dy);
    pointer.x = e.clientX; pointer.y = e.clientY;
    if (pointer.moved > 4){
      if (camMode === "strategy" && pointer.button === 0 && !(e.ctrlKey || e.metaKey)){
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
  if (e.ctrlKey || e.metaKey){
    const mx = e.movementX || 0, my = e.movementY || 0;
    yaw -= mx * 0.005;
    if (camMode === "strategy") sPitch = Math.max(0.35, Math.min(1.35, sPitch + my * 0.004));
    else pitch = Math.max(0.04, Math.min(1.45, pitch + my * 0.004));
    return;
  }
  hover(e);
  updateHover(e);
});
renderer.domElement.addEventListener("pointerup", e => {
  if (pointer.swallow){ pointer.swallow = false; return; }
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
  else if (p.kind === "home"){ if (p.id === G.you) UI.openTab("house"); }
  else if (p.kind === "you") UI.openTab("here");
  else if (p.kind === "ground"){
    // A free square: pick it. An owned one: open what stands there. Elsewhere: walk.
    const c = cellAt(p.point);
    const own = c && S.cellOwner.get(c.key);
    // On the map (2026-11-01): a click walks you there, hex by hex; shift
    // picks a free square instead.
    if (mapMode() || HEXMAP.picking){
      if (e.shiftKey && c && !own) toggleCell(c);
      else if (own && own.business && S.buildings.has(own.business) && !HEXMAP.picking) UI.openBuilding(own.business);
      else { if (S.selected.size) clearSelection(); HEXMAP.click(p.point); }
      return;
    }
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
  // On the map: the hex under the mouse, the way there and what it costs.
  if (!p && mapMode() && HEXMAP.hover(groundPoint(e), tip, e)){ renderer.domElement.style.cursor = "pointer"; return; }
  HEXMAP.hideHover();
  if (!p || p.kind === "you"){ tip.style.display = "none"; return; }
  let text = "";
  if (p.kind === "building"){ const v = S.buildings.get(p.id); text = v ? `${v.b.type} — ${v.b.owner === G.you ? "yours" : short(ownerName(v.b.owner))}` : ""; }
  if (p.kind === "agent") text = short(ownerName(p.id));
  if (p.kind === "home") text = p.id === G.you ? "Your home -- click for your house" : "A home";
  tip.textContent = text; tip.style.display = text ? "block" : "none";
  tip.style.left = `${e.clientX + 14}px`; tip.style.top = `${e.clientY + 12}px`;
}
const typing = () => /INPUT|SELECT|TEXTAREA/.test((document.activeElement || {}).tagName || "");
addEventListener("keydown", e => {
  if (typing()) return;
  const k = e.key.toLowerCase();
  if (k === "escape"){ if (BIGMAP.open){ closeBigMap(); return; } if (placing){ stopPlacing(); return; } UI.close(); return; }
  if (k === "tab"){ e.preventDefault(); if (!CONVOY.active) toggleCamera(); return; }
  if (k === "c"){ if (camMode === "strategy") flyTo(S.player.root.position); else if (!e.repeat) pressed.add("c"); return; }
  if (k === "r"){ if (!e.repeat) pressed.add("r"); return; }
  if (k === "f"){ FIGHT.block(true); return; }
  if (k === "e"){ interact(); return; }
  if (k === "h"){ whistle(); return; }
  if (k === "`"){ DEBUG = !DEBUG; return; }
  if (k === " "){ e.preventDefault(); if (!e.repeat) pressed.add(" "); return; }
  if (k === "shift" && !e.repeat) pressed.add("shift");
  if (k === "m"){ BIGMAP.open ? closeBigMap() : openBigMap(); return; }
  if (["w", "a", "s", "d", "arrowup", "arrowdown", "arrowleft", "arrowright", "shift", "control", "meta"].includes(k)){
    keys.add(k); if (k.startsWith("arrow")) e.preventDefault();
  }
});
addEventListener("keyup", e => {
  const k = e.key.toLowerCase();
  keys.delete(k);
  if (k === "f") FIGHT.block(false);
  // While Cmd is down a Mac sends no keyup for other keys, so letting go of it
  // must let go of the arrows too, or the camera keeps turning.
  if (k === "meta" || k === "control") ["w", "a", "s", "d", "arrowup", "arrowdown", "arrowleft", "arrowright"].forEach(x => keys.delete(x));
});
addEventListener("blur", () => { keys.clear(); FIGHT.block(false); });

function walkToPoint(point, then){
  autoTarget = new THREE.Vector3(point.x, 0, point.z);
  autoOnArrive = then || null;
  marker.position.set(point.x, groundAt(point.x, point.z) + 0.15, point.z); marker.visible = true;
}
function walkToPlace(name, then){
  const p = S.places[name]; if (!p) return;
  if (mapDriven()){ HEXMAP.click(p.c); return; }      // hex by hex, on the map
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
  yaw = S.player.heading + Math.PI; dist = riding() ? 6 : 3.6; pitch = 0.12;
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
  for (const [id, v] of S.buildings) setFloors(v.root, (PROD.floors || {})[id] || 0);
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
  if (PROD && PROD.businesses) for (const [bid, b] of Object.entries(PROD.businesses)) for (const w of b.workers || []) byWorker[w] = b;
  const pace = (S.ST && !S.ST.paused) ? S.ST.pace : 0;
  const people = [...S.agents.values()];
  if (S.player) people.push(S.player);
  for (const p of people){
    const id = p === S.player ? G.you : p.id;
    const b = p.root.visible ? byWorker[id] : null;
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
    if (d < 6 && d < bd && v.root.visible){ best = {kind: "building", id: v.b.id, label: `Open the ${SHORT_TYPE[v.b.type] || v.b.type}${v.b.owner === G.you ? " (yours)" : ` \u2014 ${short(ownerName(v.b.owner))}`}`}; bd = d; }
  }
  for (const v of S.agents.values()){
    const d = v.root.position.distanceTo(me);
    if (d < 3.2 && d < bd){ best = {kind: "agent", id: v.id, label: `Talk to ${short(ownerName(v.id))}`}; bd = d; }
  }
  // Your animal: ride it, or get down (2026-10-31).
  const an = myAnimal();
  if (riding()) best = {kind: "dismount", label: `Get down off your ${an ? an.type.toLowerCase() : "animal"}`};
  else if (an && DONKEY.root && DONKEY.root.visible){
    const d = Math.hypot(me.x - DONKEY.root.position.x, me.z - DONKEY.root.position.z);
    if (d < 2.8 && d < bd + 1){ best = {kind: "ride", label: `Ride your ${an.type.toLowerCase()}`}; bd = d; }
  }
  promptFor = best;
  const el = $("eprompt");
  el.style.display = best && !S.travelling ? "flex" : "none";
  if (best) $("ep-text").textContent = best.label;
}
function usePrompt(){
  if (!promptFor) return;
  if (promptFor.kind === "ride"){ mountAnimal(); return; }
  if (promptFor.kind === "dismount"){ dismountAnimal(); return; }
  freeMouse();                               // a panel wants the mouse back
  if (promptFor.kind === "building") UI.openBuilding(promptFor.id); else UI.openPerson(promptFor.id);
}
function interact(){ updatePrompt(); usePrompt(); }
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
  wayLine.visible = on;
  beam.visible = on || !!beam.userData.delivery;
  if (!on) return;
  beam.position.x = autoTarget.x; beam.position.z = autoTarget.z;
  const a = S.player.root.position;
  const pos = wayGeo.attributes.position;
  pos.setXYZ(0, a.x, 0.25, a.z); pos.setXYZ(1, autoTarget.x, 0.25, autoTarget.z);
  pos.needsUpdate = true; wayLine.computeLineDistances();
}

/* ------------------------------------------------------------ delivery runs */
/* THE RUN (2026-10-18): where to go, without saying exactly. While a delivery
   is on, a compass across the top points the way; the minimap shows a yellow
   circle the buyer is somewhere inside; ride into it and the building itself
   lights up. Before the goods are loaded it points you to your own business. */
const SEARCH_R = 60;
function deliveryTarget(){
  const d = S.ST && S.ST.delivery;
  // A bounty: the camp is shown exactly -- you are hunting, not searching.
  const mi = S.ST && S.ST.mission;
  if (!d && mi && mi.id === "bounty"){
    const place = S.places[mi.place]; if (!place) return null;
    return {pos: campSpot(place), exact: true, label: `Bandit camp at ${mi.place}`, bandits: true};
  }
  const h = S.ST && S.ST.haul;
  if (!d && !h && S.errand){
    const b = S.buildings.get(S.errand.business), place = S.places[S.errand.place];
    const label = S.errand.label || `Buy ${S.errand.qty} ${S.errand.item} at ${S.errand.place}`;
    if (b) return {pos: b.pos, exact: true, label, building: S.errand.business};
    return place ? {pos: place.c, exact: true, label} : null;
  }
  if (!d && h){
    // FETCH IT YOURSELF: to the seller to load, then home to hand it over.
    const id = h.loaded ? h.to : h.from, b = S.buildings.get(id), place = S.places[h.loaded ? h.destination : h.origin];
    const label = h.loaded ? `Carry ${h.qty} ${h.item} to ${b ? "your " + b.b.type.split(" /")[0] : h.destination}`
                           : `Pick up ${h.qty} ${h.item} at ${b ? b.b.type.split(" /")[0] + ", " : ""}${h.origin}`;
    if (b) return {pos: b.pos, exact: true, label, building: id};
    return place ? {pos: place.c, exact: true, label} : null;
  }
  if (!d && S.waypoint) return {pos: S.waypoint, exact: true, label: S.waypoint.label || "Your waypoint"};
  if (!d) return null;
  if (!d.loaded){
    const b = S.buildings.get(d.from);
    return b ? {pos: b.pos, exact: true, label: "Load up at your " + b.b.type.split(" /")[0], building: d.from} : null;
  }
  const place = S.places[d.place]; if (!place) return null;
  // The circle sits off the buyer's square by a fixed, buyer-specific amount.
  const ang = hash(d.buyer, 7) * Math.PI * 2, off = SEARCH_R * 0.45 * hash(d.buyer, 8);
  const centre = place.c.clone().add(new THREE.Vector3(Math.cos(ang) * off, 0, Math.sin(ang) * off));
  const b = S.buildings.get(d.buyer);
  const near = S.player && S.player.root.position.distanceTo(centre) < SEARCH_R;
  if (near && b) return {pos: b.pos, exact: true, label: `Deliver ${d.qty} ${d.item} here`, building: d.buyer, centre};
  const town = place.cityName || "";
  return {pos: centre, exact: false, label: `Deliver ${d.qty} ${d.item} \u2014 the buyer is somewhere in the yellow circle${town ? ", " + town : ""}`, centre};
}
const CARD = [["N", 0], ["NE", 45], ["E", 90], ["SE", 135], ["S", 180], ["SW", 225], ["W", 270], ["NW", 315]];
function updateCompass(){
  const box = $("compass"), t = deliveryTarget();
  if (!t || !S.player){ box.classList.remove("on"); beam.userData.delivery = false; return; }
  box.classList.add("on");
  // Bearings: 0 = north (-z), clockwise. The camera faces -sin(yaw), -cos(yaw).
  const bearing = (x, z) => ((Math.atan2(x, -z) * 180 / Math.PI) + 360) % 360;
  const facing = bearing(-Math.sin(yaw), -Math.cos(yaw));
  const P = S.player.root.position, to = t.pos.clone().sub(P);
  const tb = bearing(to.x, to.z), dist = Math.round(to.setY(0).length() * 10);
  const W = 360, px = rel => W / 2 + rel / 90 * (W / 2);
  const rel = a => { let r = a - facing; r = ((r + 540) % 360) - 180; return r; };
  let html = "";
  for (const [n, a] of CARD){ const r = rel(a); if (Math.abs(r) <= 90) html += `<span class="cp-${n.length === 1 ? "main" : "sub"}" style="left:${px(r)}px">${n}</span>`; }
  for (let a = 0; a < 360; a += 15){ const r = rel(a); if (Math.abs(r) <= 90 && a % 45) html += `<i style="left:${px(r)}px"></i>`; }
  const tr = rel(tb), clamped = Math.max(-90, Math.min(90, tr));
  html += `<b class="cp-mark${Math.abs(tr) > 90 ? " edge" : ""}" style="left:${px(clamped)}px">\u25BC</b>`;
  $("cp-strip").innerHTML = html;
  $("cp-text").textContent = `${t.label} \u00b7 ${dist} m`;
  // The exact building, once found, gets the column of light.
  if (t.exact && !autoTarget){ beam.visible = true; beam.position.x = t.pos.x; beam.position.z = t.pos.z; beam.userData.delivery = true; }
  else beam.userData.delivery = false;
}

/* THE BANDIT CAMP of the bounty mission: two tents and their owners. */
let camp = null;
function campSpot(place){ return place.c.clone().add(new THREE.Vector3(place.r * 0.55, 0, -place.r * 0.35)); }
function updateCamp(){
  const mi = S.ST && S.ST.mission, place = mi && mi.id === "bounty" ? S.places[mi.place] : null;
  if (!place){ if (camp){ scene.remove(camp); camp = null; } return; }
  if (camp && camp.userData.place === mi.place) return;
  if (camp) scene.remove(camp);
  camp = new THREE.Group(); camp.userData.place = mi.place;
  const at = campSpot(place); camp.position.copy(at);
  for (const [x, z, col] of [[-3, 0, "#7a2e22"], [3, 1.5, "#5b4a2a"]]){
    const tent = new THREE.Mesh(new THREE.ConeGeometry(2.2, 3, 4), new THREE.MeshLambertMaterial({color: col, flatShading: true}));
    tent.position.set(x, 1.5, z); tent.rotation.y = Math.PI / 4; camp.add(tent);
  }
  const fire = new THREE.Mesh(new THREE.ConeGeometry(0.5, 1, 6), new THREE.MeshBasicMaterial({color: "#ff8a2a"}));
  fire.position.set(0, 0.5, 2.5); camp.add(fire);
  camp.userData.bandits = [];
  for (const [x, z] of [[-1, 3.6], [1.4, 3.2]]){
    const b = makePerson(CAST.m[CAST.m.length > 1 ? 1 : 0]); b.root.position.set(x, 0, z); b.root.rotation.y = Math.PI;
    camp.userData.bandits.push(b.root);
    b.body.traverse(o => { if (o.isMesh && o.material){ o.material = o.material.clone(); o.material.color && o.material.color.multiplyScalar(0.45); } });
    b.mixer.update(0);
    camp.add(b.root);
  }
  const el = document.createElement("div"); el.className = "lbl-biz camp"; el.innerHTML = "<b>\u2620\uFE0F Bandit camp</b>";
  const lbl = new CSS2DObject(el); lbl.position.set(0, 6, 0); camp.add(lbl);
  scene.add(camp);
}

/* The camp, for a fight: where it is, and its bandits to stand down while
   the fighting ones are up. */
function campInfo(){
  const mi = S.ST && S.ST.mission;
  if (!camp || !mi || mi.id !== "bounty") return null;
  return {pos: camp.position.clone().add(new THREE.Vector3(0, 0, 3)),
    hide: on => camp.userData.bandits.forEach(b => { b.visible = !on; })};
}

/* YOUR DONKEY: packs on its back when you carry something. */
function makeDonkey(){
  if (MODELS.donkey){
    // The Meshy donkey is one solid piece: it walks with a gentle bob and
    // sway rather than moving legs (see updateDonkey).
    const M = MODELS.donkey, g = new THREE.Group(), m = M.scene.clone(true);
    m.scale.setScalar(M.scale); m.position.set(-M.cx, M.lift, -M.cz);
    m.traverse(o => { if (o.isMesh){ o.castShadow = true; } });
    const body = new THREE.Group(); body.add(m); g.add(body);
    g.userData.legs = []; g.userData.packs = new THREE.Group(); g.userData.body = body; g.userData.model = true;
    return g;
  }
  const g = new THREE.Group();
  const coat = new THREE.MeshLambertMaterial({color: "#8d7b6a"}), darkM = new THREE.MeshLambertMaterial({color: "#4a3f36"});
  const body = new THREE.Mesh(new THREE.BoxGeometry(0.8, 0.75, 1.7), coat); body.position.y = 1.1; g.add(body);
  const neck = new THREE.Mesh(new THREE.BoxGeometry(0.35, 0.7, 0.4), coat); neck.position.set(0, 1.55, 0.85); neck.rotation.x = -0.5; g.add(neck);
  const head = new THREE.Mesh(new THREE.BoxGeometry(0.38, 0.4, 0.7), coat); head.position.set(0, 1.85, 1.15); g.add(head);
  for (const x of [-0.12, 0.12]){ const ear = new THREE.Mesh(new THREE.BoxGeometry(0.08, 0.45, 0.1), darkM); ear.position.set(x, 2.2, 1.0); g.add(ear); }
  g.userData.legs = [];
  for (const [x, z] of [[-0.28, 0.6], [0.28, 0.6], [-0.28, -0.6], [0.28, -0.6]]){
    const leg = new THREE.Mesh(new THREE.BoxGeometry(0.16, 0.8, 0.16), darkM); leg.position.set(x, 0.4, z); g.add(leg); g.userData.legs.push(leg);
  }
  const packs = new THREE.Group();
  for (const x of [-0.55, 0.55]){ const bag = new THREE.Mesh(new THREE.BoxGeometry(0.35, 0.5, 0.8), new THREE.MeshLambertMaterial({color: "#c9a25e"})); bag.position.set(x, 1.15, 0); packs.add(bag); }
  g.add(packs); g.userData.packs = packs;
  g.scale.setScalar(0.85);
  return g;
}
/* YOUR DONKEY (2026-10-31): an animal in the world, not a follower. Left
   alone it grazes where you left it, wandering a few steps; whistle (H) and it
   trots to you; E beside it to ride, E again to get down. Ridden, it moves by
   RIDER's gaits (updateRiding). */
const RIDEABLE = new Set(["Donkey", "Horse", "Camel", "Donkey Cart"]);
const DONKEY = {root: null, mode: "graze", anchor: null, target: null, wait: 0, heading: 0, vid: "", gaitT: 0, called: false};
function myAnimal(){ return ((S.ST && S.ST.vehicles) || []).find(v => RIDEABLE.has(v.type)); }
function updateDonkey(dt, now){
  const v = myAnimal();
  if (!v || !S.player){ if (DONKEY.root) DONKEY.root.visible = false; return; }
  if (!DONKEY.root){
    DONKEY.root = makeDonkey(); scene.add(DONKEY.root); DONKEY.vid = v.id;
    const home = v.mounted ? S.player.root.position : (S.places[v.location] ? S.places[v.location].c : S.player.root.position);
    DONKEY.root.position.set(home.x + 2.5, 0, home.z + 1.5);
    DONKEY.anchor = DONKEY.root.position.clone();
  }
  const D = DONKEY, pos = D.root.position;
  D.root.visible = true;
  let speed = 0;
  if (riding()){
    speed = Math.abs(RIDER.s.speed); D.mode = "ridden"; D.anchor = pos.clone();
  } else {
    if (D.mode === "ridden"){ D.mode = "graze"; D.anchor = pos.clone(); D.target = null; D.wait = 2; }
    let goal = null, pace = 0;
    if (D.mode === "come"){
      const me = S.player.root.position, d = Math.hypot(me.x - pos.x, me.z - pos.z);
      if (d < 2.4){
        D.mode = "graze"; D.anchor = pos.clone(); D.target = null; D.wait = 3;
        // Where you are, the server agrees it is -- so you can mount it here.
        api.post("/api/callvehicle", {vehicle_id: v.id}).then(() => UI.refreshSoon()).catch(() => {});
      } else if (d > 400){ pos.set(me.x - 3, 0, me.z - 3); }
      else { goal = me; pace = TUNE.gaits[2]; }
    } else {
      D.wait -= dt;
      if (!D.target && D.wait <= 0){
        const a = Math.random() * Math.PI * 2, r = 1 + Math.random() * 4;
        D.target = new THREE.Vector3(D.anchor.x + Math.cos(a) * r, 0, D.anchor.z + Math.sin(a) * r);
      }
      if (D.target){
        if (Math.hypot(D.target.x - pos.x, D.target.z - pos.z) < 0.3){ D.target = null; D.wait = 3 + Math.random() * 6; }
        else { goal = D.target; pace = 1.0; }
      }
    }
    if (goal){
      const want = Math.atan2(goal.x - pos.x, goal.z - pos.z);
      let dh = want - D.heading; dh = Math.atan2(Math.sin(dh), Math.cos(dh));
      D.heading += dh * Math.min(1, dt * 3.5);
      speed = pace * Math.max(0.2, Math.cos(dh));
      const last = pos.clone();
      pos.x += Math.sin(D.heading) * speed * dt; pos.z += Math.cos(D.heading) * speed * dt;
      if (collide(pos, last, 0.58) && D.target){ D.target = null; D.wait = 1; }
    }
    D.root.rotation.y = D.heading;
  }
  pos.y = groundAt(pos.x, pos.z);
  // Gait, as bob and sway: quicker and higher the faster it goes; at rest it
  // drops its head to graze.
  // The stride lengthens at speed rather than the legs blurring.
  D.gaitT += dt * (2 + Math.min(speed, 9) * 1.3 + Math.max(0, speed - 9) * 0.35);
  const moving = speed > 0.15, bob = Math.min(0.16, 0.025 + speed * 0.012);
  D.root.userData.legs.forEach((l, i) => { l.rotation.x = moving ? Math.sin(D.gaitT * 3 + (i % 2) * Math.PI) * Math.min(0.9, 0.3 + speed * 0.06) : 0; });
  if (D.root.userData.body){
    const b = D.root.userData.body;
    b.position.y = moving ? Math.abs(Math.sin(D.gaitT * 3)) * bob : 0;
    b.rotation.z = moving ? Math.sin(D.gaitT * 3) * 0.03 : 0;
    const graze = !moving && !riding() ? 0.12 + Math.sin(now / 900) * 0.04 : 0;
    b.rotation.x += ((moving ? -speed * 0.006 : graze) - b.rotation.x) * Math.min(1, dt * 4);
  }
  // Your load rides on it: sacks slung over it, or in its cart (convoy.js).
  CONVOY.dress(D.root, v.type, CONVOY.load(), speed, dt);
}
function whistle(){
  if (!myAnimal() || !DONKEY.root || riding()) return;
  DONKEY.mode = "come"; DONKEY.target = null;
  UI.toast(`You whistle. Your ${myAnimal().type.toLowerCase()} is coming.`);
}
async function mountAnimal(){
  const v = myAnimal(); if (!v || !DONKEY.root) return;
  // The server must have it where you are: a whistle tells it so.
  await api.post("/api/callvehicle", {vehicle_id: v.id}).catch(() => {});
  const r = await UI.act("mount", {vehicle_id: v.id});
  if (!r.ok) return;
  RIDER.s.heading = DONKEY.heading; RIDER.s.speed = 0; RIDER.setGait(0);
  if (S.ST) S.ST.vehicle = v.type;
  yaw = DONKEY.heading + Math.PI;
  modeChanged();
}
async function dismountAnimal(){
  if (RIDER.s.speed > 1.5){ UI.toast("Rein in first (S)"); return; }
  const r = await UI.act("dismount", {});
  if (!r.ok) return;
  if (S.ST) S.ST.vehicle = null;
  const P = S.player, side = new THREE.Vector3(Math.cos(DONKEY.heading), 0, -Math.sin(DONKEY.heading));
  P.root.position.addScaledVector(side, -1.2);
  P.root.position.y = groundAt(P.root.position.x, P.root.position.z);
  WALKER.s.y = P.root.position.y;
  DONKEY.mode = "graze"; DONKEY.anchor = DONKEY.root.position.clone(); DONKEY.wait = 2;
  modeChanged();
}

/* ------------------------------------------------------------ fog */
/* THE MINIMAP IS CLOUD UNTIL YOU HAVE BEEN NEAR (2026-10-18). The world in
   front of you is always drawn; the map only remembers where you have been.
   Kept per game in this browser. */
// THE FOG IS THE SERVER'S (2026-11-01): the hexes you have found
// (convoy/journey.py, the status's map), drawn by hexmap.js. FOG_CELL is
// only the ground veil's texture resolution now.
const FOG_CELL = 8;
const fogC = document.createElement("canvas"), fg = fogC.getContext("2d");
function updateFog(){
  if (outposts() && HEXMAP.sync()){ GROUND_HAZE.n = -1; drawHaze(); }
  else if (GROUND_HAZE.on < 0) drawHaze();
}
/* THE GROUND_HAZE ON THE GROUND (outposts, 2026-10-28): the same explored squares,
   painted into a texture the ground shader veils with. Clear where you have
   been (and the trading posts), hazy everywhere else. */
const GROUND_HAZE = {cv: document.createElement("canvas"), box: null, tex: null, uniforms: null, n: -1, on: -1};
function hazeSetup(w, d){
  GROUND_HAZE.box = {x0: -w / 2, z0: -d / 2, w, d};
  GROUND_HAZE.cv.width = Math.ceil(w / FOG_CELL) * 2; GROUND_HAZE.cv.height = Math.ceil(d / FOG_CELL) * 2;
  GROUND_HAZE.tex = new THREE.CanvasTexture(GROUND_HAZE.cv);
  GROUND_HAZE.tex.minFilter = GROUND_HAZE.tex.magFilter = THREE.LinearFilter;
  GROUND_HAZE.tex.flipY = false;                       // canvas rows run with the map's z
  GROUND_HAZE.uniforms = {tHaze: {value: GROUND_HAZE.tex}, uHazeBox: {value: new THREE.Vector4(-w / 2, -d / 2, w, d)}, uHazeOn: {value: 0}};
  return GROUND_HAZE.uniforms;
}
function drawHaze(){
  if (!GROUND_HAZE.uniforms) return;
  const on = outposts() && !GROUND_HAZE.off ? 1 : 0;
  if (on !== GROUND_HAZE.on){ GROUND_HAZE.on = on; GROUND_HAZE.uniforms.uHazeOn.value = on; }
  if (!on || GROUND_HAZE.n === HEXMAP.known.size) return;
  GROUND_HAZE.n = HEXMAP.known.size;
  const c = GROUND_HAZE.cv.getContext("2d"), W = GROUND_HAZE.cv.width, H = GROUND_HAZE.cv.height, px = 2 / FOG_CELL;
  c.globalCompositeOperation = "source-over"; c.clearRect(0, 0, W, H);
  c.fillStyle = "#000"; c.fillRect(0, 0, W, H);
  HEXMAP.cutHexes(c, (x, z) => [(x - GROUND_HAZE.box.x0) * px, (z - GROUND_HAZE.box.z0) * px], 1.2);
  GROUND_HAZE.tex.needsUpdate = true;
}

/* WHERE YOU ARE, for finding people (outposts): told to the server every
   couple of seconds while you move, in map metres. */
let posSent = null;
setInterval(() => {
  if (!S.player || !outposts() || !S.ST.you.settled || !CONVOY.active) return;
  const p = S.player.root.position;
  if (posSent && Math.hypot(p.x - posSent.x, p.z - posSent.z) < 4) return;
  posSent = p.clone();
  const w = toWorld(p);
  api.post("/api/pos", {x: w.x, y: w.y}).catch(() => {});
}, 2000);

function drawFog(sx, sz, k, W, H, ctx = mg){
  if (fogC.width !== W){ fogC.width = W; fogC.height = H; }
  fg.globalCompositeOperation = "source-over";
  fg.fillStyle = "rgba(214,201,172,0.95)"; fg.fillRect(0, 0, W, H);
  // A little texture, so it reads as cloud and not a blank.
  fg.fillStyle = "rgba(240,230,206,0.35)";
  for (let i = 0; i < 18; i++){ fg.beginPath(); fg.arc((i * 97) % W, (i * 53) % H, 18 + (i % 5) * 7, 0, 7); fg.fill(); }
  HEXMAP.cutHexes(fg, (x, z) => [sx(x), sz(z)]);
  ctx.drawImage(fogC, 0, 0);
}

/* ------------------------------------------------------------ minimap */
const mm = $("minimap"), mg = mm.getContext("2d");
let mmBox = null;
function minimapBox(){
  const P = S.player; if (!P) return null;
  const city = nearestPlace(P.root.position);
  const pts = Object.values(S.places).filter(p => !city || p.city === city.city);
  const xs = pts.map(p => p.c.x), zs = pts.map(p => p.c.z);
  // A delivery elsewhere: zoom out to take in its circle too.
  const t = deliveryTarget();
  if (t){ const c = t.centre || t.pos; xs.push(c.x - SEARCH_R, c.x + SEARCH_R); zs.push(c.z - SEARCH_R, c.z + SEARCH_R); }
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
  mg.fillStyle = "#7c7a48"; mg.fillRect(0, 0, W, H);
  const D = S.DATA;
  mg.fillStyle = "#5d7b78";
  const rx = (D.river.axis - CY) * SCALE, rh = D.river.half * SCALE;
  mg.fillRect(sx(rx - rh), 0, rh * 2 * k, H);
  for (const r of D.river.borders || []){ const z = (r.axis - CX) * SCALE, h2 = r.half * SCALE; mg.fillRect(0, sz(z - h2), W, h2 * 2 * k); }
  mg.strokeStyle = "#c7ac78"; mg.lineCap = "round";
  for (const [ax, az, bx, bz, hw] of roadSegs){
    mg.lineWidth = Math.max(1.5, hw * 2 * k); mg.beginPath(); mg.moveTo(sx(ax), sz(az)); mg.lineTo(sx(bx), sz(bz)); mg.stroke();
  }
  for (const p of Object.values(S.places)){
    if (p.kind === "claim" && !landShown(p.owner, p.c)) continue;
    mg.fillStyle = "#b59a63aa"; mg.beginPath(); mg.arc(sx(p.c.x), sz(p.c.z), Math.max(3, p.r * k * 0.8), 0, 7); mg.fill();
  }
  mg.fillStyle = "#7d7466";
  for (const m of S.mountains || []){
    const x = sx(m.x), z = sz(m.z), r = Math.max(3, m.r * k);
    mg.beginPath(); mg.moveTo(x, z - r); mg.lineTo(x + r, z + r * 0.7); mg.lineTo(x - r, z + r * 0.7); mg.closePath(); mg.fill();
  }
  for (const v of S.buildings.values()){
    if (!v.root.visible) continue;
    mg.fillStyle = v.b.owner === G.you ? "#d8b65a" : "#3a2c1e";
    mg.fillRect(sx(v.pos.x) - 3, sz(v.pos.z) - 3, 6, 6);
  }
  mg.fillStyle = "#ffffff";
  for (const v of S.agents.values()){ if (!found(v.id)) continue; mg.beginPath(); mg.arc(sx(v.root.position.x), sz(v.root.position.z), 2.2, 0, 7); mg.fill(); }
  drawFog(sx, sz, k, W, H);          // under the hint circle and the waypoint, over the land
  const dt_ = deliveryTarget();
  if (dt_){
    const c = dt_.centre || dt_.pos;
    mg.fillStyle = "rgba(255,210,60,0.22)"; mg.strokeStyle = "#ffcc33"; mg.lineWidth = 2.5;
    mg.beginPath(); mg.arc(sx(c.x), sz(c.z), Math.max(8, SEARCH_R * k), 0, 7); mg.fill(); mg.stroke();
    if (dt_.exact){ mg.fillStyle = "#ffcc33"; mg.beginPath(); mg.arc(sx(dt_.pos.x), sz(dt_.pos.z), 5, 0, 7); mg.fill(); }
  }
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
  $("mm-cap").textContent = here ? (outposts() ? here.name : `${here.name} · ${here.cityName}`) : `Near ${nearestPlace(S.player.root.position).name}`;
}
mm.addEventListener("click", e => {
  if (!mmBox) return;
  if (!e.shiftKey && outposts()){ openBigMap(); return; }
  const r = mm.getBoundingClientRect();
  const x = (e.clientX - r.left) * (mm.width / r.width), z = (e.clientY - r.top) * (mm.height / r.height);
  const at = new THREE.Vector3(mmBox.x0 + (x - mmBox.ox) / mmBox.k, 0, mmBox.z0 + (z - mmBox.oz) / mmBox.k);
  if (camMode === "strategy" && !e.shiftKey) flyTo(at); else walkToPoint(at);
});

/* ------------------------------------------------------------ the full map */
/* THE FULL MAP (2026-10-28): M, the minimap or the MAP button. Only what you
   have discovered: explored ground, trading posts, your own land, the land of
   people you have found where you have seen it (or anywhere, once they share
   their locations), taverns you know, and your own pins -- kept on the server
   so they follow you to another browser. Drag to pan, wheel to zoom, click
   for a waypoint or a pin. */
const BIGMAP = {open: false, cx: 0, cz: 0, k: 1, drag: null, el: null, cv: null};
function exploredAt(x, z){ return HEXMAP.knownAt(x, z); }
function sharedLocations(owner){ return !!(S.ST && S.ST.you && (S.ST.you.locations_from || []).includes(owner)); }
/* A found person's land shows where you have seen it, or anywhere once they
   share where it is. Yours, the state's, and everything without outposts: always. */
function landShown(owner, pos){
  if (!found(owner)) return false;
  if (!outposts() || !owner || owner === G.you || owner === "Government") return true;
  return sharedLocations(owner) || (pos && exploredAt(pos.x, pos.z));
}
function openBigMap(){
  if (!BIGMAP.el){
    const el = document.createElement("div"); el.id = "bigmap";
    el.innerHTML = `<div class="bm-top"><b>Map</b><span>Drag to pan \u00b7 wheel to zoom \u00b7 click a spot for a waypoint or a pin \u00b7 M or Esc to close</span><button id="bm-x">\u00d7</button></div><canvas id="bm-cv"></canvas><div id="bm-pop"></div>`;
    document.body.appendChild(el);
    BIGMAP.el = el; BIGMAP.cv = el.querySelector("#bm-cv");
    el.querySelector("#bm-x").onclick = closeBigMap;
    const cv = BIGMAP.cv;
    cv.addEventListener("wheel", e => { e.preventDefault(); BIGMAP.k = Math.max(0.15, Math.min(6, BIGMAP.k * (e.deltaY > 0 ? 0.87 : 1.15))); drawBigMap(); }, {passive: false});
    cv.addEventListener("pointerdown", e => { BIGMAP.drag = {x: e.clientX, y: e.clientY, cx: BIGMAP.cx, cz: BIGMAP.cz, moved: 0}; });
    addEventListener("pointermove", e => {
      const d = BIGMAP.drag; if (!d) return;
      d.moved = Math.max(d.moved, Math.hypot(e.clientX - d.x, e.clientY - d.y));
      BIGMAP.cx = d.cx - (e.clientX - d.x) / BIGMAP.k; BIGMAP.cz = d.cz - (e.clientY - d.y) / BIGMAP.k; drawBigMap();
    });
    addEventListener("pointerup", e => {
      const d = BIGMAP.drag; BIGMAP.drag = null;
      if (d && d.moved < 5 && e.target === cv) bigMapClick(e);
    });
  }
  BIGMAP.open = true; BIGMAP.el.style.display = "flex";
  const P = S.player ? S.player.root.position : {x: 0, z: 0};
  BIGMAP.cx = P.x; BIGMAP.cz = P.z;
  $("bm-pop").style.display = "none";
  drawBigMap();
}
function closeBigMap(){ BIGMAP.open = false; if (BIGMAP.el) BIGMAP.el.style.display = "none"; }
function bigMapXY(e){
  const r = BIGMAP.cv.getBoundingClientRect(), W = BIGMAP.cv.width, H = BIGMAP.cv.height;
  const px = (e.clientX - r.left) * (W / r.width), pz = (e.clientY - r.top) * (H / r.height);
  return {x: BIGMAP.cx + (px - W / 2) / BIGMAP.k, z: BIGMAP.cz + (pz - H / 2) / BIGMAP.k, px: e.clientX - r.left, pz: e.clientY - r.top};
}
function bigMapClick(e){
  const at = bigMapXY(e), pop = $("bm-pop");
  const pins = (S.ST && S.ST.you.pins) || [];
  const near = pins.findIndex(p => { const c = toScene(p.x, p.y); return Math.hypot(c.x - at.x, c.z - at.z) * BIGMAP.k < 12; });
  pop.innerHTML = `<button data-bm="way">Set waypoint</button>`
    + (near >= 0 ? `<button data-bm="unpin">Remove pin \u201c${esc(pins[near].label)}\u201d</button>` : `<input id="bm-label" placeholder="Pin label" maxlength="40"><button data-bm="pin">Add a pin</button>`);
  pop.style.left = `${at.px + 12}px`; pop.style.top = `${at.pz + 40}px`; pop.style.display = "flex";
  pop.querySelectorAll("[data-bm]").forEach(b => b.onclick = async () => {
    const w = toWorld(new THREE.Vector3(at.x, 0, at.z));
    if (b.dataset.bm === "way"){ S.waypoint = new THREE.Vector3(at.x, 0, at.z); UI.toast("Waypoint set: the compass points to it"); }
    else if (b.dataset.bm === "pin"){
      const r = await api.post("/api/pins", {x: w.x, y: w.y, label: ($("bm-label") || {}).value || "Pin"});
      if (r.ok && S.ST) S.ST.you.pins = r.pins; else if (!r.ok) UI.toast(r.message, "bad");
    } else {
      const r = await api.post("/api/pins", {remove: near});
      if (r.ok && S.ST) S.ST.you.pins = r.pins;
    }
    pop.style.display = "none"; drawBigMap();
  });
  setTimeout(() => { const i = $("bm-label"); if (i) i.focus(); }, 0);
}
function drawBigMap(){
  if (!BIGMAP.open || !S.DATA) return;
  const cv = BIGMAP.cv, W = cv.clientWidth, H = cv.clientHeight;
  if (cv.width !== W || cv.height !== H){ cv.width = W; cv.height = H; }
  const c = cv.getContext("2d"), k = BIGMAP.k;
  const sx = x => W / 2 + (x - BIGMAP.cx) * k, sz = z => H / 2 + (z - BIGMAP.cz) * k;
  const D = S.DATA;
  c.fillStyle = "#7c7a48"; c.fillRect(0, 0, W, H);
  c.fillStyle = "#5d7b78";
  const rx = (D.river.axis - CY) * SCALE, rh = D.river.half * SCALE;
  c.fillRect(sx(rx - rh), 0, rh * 2 * k, H);
  for (const r of D.river.borders || []){ const z = (r.axis - CX) * SCALE, h2 = r.half * SCALE; c.fillRect(0, sz(z - h2), W, h2 * 2 * k); }
  c.strokeStyle = "#c7ac78"; c.lineCap = "round";
  for (const [ax, az, bx, bz, hw] of roadSegs){
    c.lineWidth = Math.max(1.5, hw * 2 * k); c.beginPath(); c.moveTo(sx(ax), sz(az)); c.lineTo(sx(bx), sz(bz)); c.stroke();
  }
  c.fillStyle = "#7d7466";
  for (const m of S.mountains || []){
    const x = sx(m.x), z = sz(m.z), r = Math.max(3, m.r * k);
    c.beginPath(); c.moveTo(x, z - r); c.lineTo(x + r, z + r * 0.7); c.lineTo(x - r, z + r * 0.7); c.closePath(); c.fill();
  }
  // Under the haze: only seen where you have been.
  const marks = [];                                       // drawn over the haze
  for (const p of Object.values(S.places)){
    if (p.kind === "claim" && !landShown(p.owner, p.c)) continue;
    const always = p.kind !== "claim" || p.owner === G.you || sharedLocations(p.owner);
    (always ? marks : []).push(["place", p]);
    if (!always){ c.fillStyle = "#b59a63aa"; c.beginPath(); c.arc(sx(p.c.x), sz(p.c.z), Math.max(3, p.r * k * 0.8), 0, 7); c.fill(); }
  }
  for (const v of S.buildings.values()){
    if (!landShown(v.b.owner, v.pos)) continue;
    marks.push(["building", v]);
  }
  for (const [owner, v] of S.homeObjs) if (landShown(owner, v.pos)) marks.push(["home", {owner, pos: v.pos}]);
  for (const [owner, v] of SMOKE) if (v.group.visible) marks.push(["smoke", {owner, pos: v.group.position}]);
  drawFog(sx, sz, k, W, H, c);
  // Over the haze: what you know is there.
  c.textAlign = "center"; c.font = "600 12px Nunito, sans-serif";
  const label = (t, x, z, col) => { c.fillStyle = "#000a"; c.fillText(t, x + 1, z + 1); c.fillStyle = col; c.fillText(t, x, z); };
  const markets = new Set(((D.cities) || []).map(k2 => k2.market));
  for (const [kind, o] of marks){
    if (kind === "place"){
      const p = o, x = sx(p.c.x), z = sz(p.c.z);
      c.fillStyle = markets.has(p.name) ? "#e9c25a" : p.owner === G.you ? "#d8b65a" : "#b59a63";
      c.beginPath(); c.arc(x, z, Math.max(4, p.r * k * 0.8), 0, 7); c.fill();
      if (k > 0.35 || markets.has(p.name)) label(markets.has(p.name) ? `\u2696 ${p.name}` : p.name, x, z - 10, "#fff");
    } else if (kind === "building"){
      const v = o, x = sx(v.pos.x), z = sz(v.pos.z), tav = /Tavern/.test(v.b.type);
      c.fillStyle = v.b.owner === G.you ? "#d8b65a" : tav ? "#e07b0a" : "#3a2c1e";
      c.fillRect(x - 4, z - 4, 8, 8);
      if (tav || k > 0.9) label(tav ? "\u{1F37A}" : (SHORT_TYPE[v.b.type] || v.b.type.split(" /")[0]), x, z - 8, "#fff");
    } else if (kind === "smoke"){
      const x = sx(o.pos.x), z = sz(o.pos.z);
      c.fillStyle = "rgba(235,230,220,0.75)";
      for (const [dx, dz, r] of [[0, 0, 5], [3, -6, 4], [-2, -11, 3]]){ c.beginPath(); c.arc(x + dx, z + dz, r, 0, 7); c.fill(); }
      if (k > 0.4) label("smoke: someone lives here", x, z + 14, "#e8e2d6");
    } else {
      const x = sx(o.pos.x), z = sz(o.pos.z);
      label("\u{1F3E0}", x, z + 4, "#fff");
      if (k > 0.6) label(o.owner === G.you ? "Your home" : short(ownerName(o.owner)), x, z - 10, "#ffe9b8");
    }
  }
  for (const p of (S.ST && S.ST.you.pins) || []){
    const cc = toScene(p.x, p.y), x = sx(cc.x), z = sz(cc.z);
    c.fillStyle = "#e8463a"; c.beginPath(); c.arc(x, z - 8, 5, 0, 7); c.fill();
    c.beginPath(); c.moveTo(x - 4, z - 6); c.lineTo(x, z); c.lineTo(x + 4, z - 6); c.fill();
    label(p.label, x, z - 16, "#ffd0c8");
  }
  if (S.waypoint){
    const x = sx(S.waypoint.x), z = sz(S.waypoint.z);
    c.strokeStyle = "#ffd966"; c.lineWidth = 3;
    c.beginPath(); c.moveTo(x - 7, z - 7); c.lineTo(x + 7, z + 7); c.moveTo(x + 7, z - 7); c.lineTo(x - 7, z + 7); c.stroke();
  }
  if (S.player){
    const P = S.player.root.position, px = sx(P.x), pz = sz(P.z);
    c.save(); c.translate(px, pz); c.rotate(-S.player.heading + Math.PI);
    c.fillStyle = "#e8463a"; c.strokeStyle = "#fff"; c.lineWidth = 2;
    c.beginPath(); c.moveTo(0, -10); c.lineTo(7, 8); c.lineTo(0, 4); c.lineTo(-7, 8); c.closePath(); c.fill(); c.stroke();
    c.restore();
  }
}
setInterval(() => { if (BIGMAP.open) drawBigMap(); }, 1000);

{ const b = $("t-map"); if (b) b.onclick = () => openBigMap(); }

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
let drawnAt = 0;
function animate(now){
  requestAnimationFrame(animate);
  // A frame cap (GRAPHICS above): at 30 a second the GPU idles half the time.
  if (now - drawnAt < 1000 / GFX.fps - 4) return;
  drawnAt = now;
  frame(now);
}
/* A hidden tab gets no animation frames at all. The world still moves on the
   server, so a fallback timer keeps the page up to date -- and it is what lets
   the page be checked from a browser that is not on screen -- once a second,
   so a tab left in the background does not keep the laptop warm. */
setInterval(() => { const now = performance.now(); if (now - last > (document.hidden ? 1000 : 250)) frame(now); }, 100);
function frame(now){
  if (!S.player) return;
  const dt = Math.min(0.1, (now - last) / 1000); last = now;
  S.HOUR = liveHour();
  updatePlayer(dt);
  updateCamera(dt);
  updateAgents(dt);
  updateFamily(dt);
  updateCompass();
  updateFog(now);
  updateSmoke(now);
  updateGangs(dt);
  updateHUD(now);
  updateCamp();
  if (GRASS) GRASS.update(camMode === "strategy" ? focus : S.player.root.position);
  FIGHT.update(dt, now);
  CONVOY.update(dt, now);
  CONVOY.dressWalker(S.player, CONVOY.load(), riding());
  updateDonkey(dt, now);
  scaleUnits();
  HEXMAP.updateScouts(dt, unitScale());
  HEXMAP.camp(S.player && mapDriven() ? S.player.root.position : null, unitScale());
  if (HEXMAP.grid) HEXMAP.grid.visible = camMode === "strategy";
  if (outposts() && S.ST && S.ST.map) HEXMAP.drawGrid();
  if (border && border.userData.edge){
    const pulse = 0.5 + 0.5 * Math.sin(now / 420);
    border.userData.line.opacity = 0.7 + 0.3 * pulse;
  }
  if (S.water && S.water.map) S.water.map.offset.y += dt * 0.01;
  if (S.water && S.water.normalMap){ S.water.normalMap.offset.x += dt * 0.006; S.water.normalMap.offset.y += dt * 0.011; }
  WIND.value += dt;
  const glow = 0.5 + 0.5 * Math.sin(now / 220);
  hoverSq.userData.ring.material.opacity = 0.6 + 0.4 * glow;
  if (placing){
    placing.ghost.userData.mat.opacity = 0.5 + 0.15 * glow;
    placing.ghost.position.y = groundAt(placing.ghost.position.x, placing.ghost.position.z) + 0.15;
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
  grade.uniforms.uTime.value = (now % 10000) / 1000;
  composer.render();
  labels.render(scene, camera);
}

/* For poking at from the console: window.convoy.camera, .S, .scene. */
window.convoy = {camera, scene, S, renderer, set idleAt(v){ IDLE_AT = v; for (const p of [S.player, ...S.agents.values()]) if (p && p.acts.idle){ p.acts.idle.time = v * p.acts.idle.getClip().duration; } }, get yaw(){ return yaw; }, get pitch(){ return pitch; }, get dist(){ return dist; },
  view(y, p, d){ yaw = y ?? yaw; pitch = p ?? pitch; dist = d ?? dist; },
  get mode(){ return camMode; }, third: () => enterThird(), overview: (d) => { if (d) sDist = d; enterStrategy(); },
  look(x, z, d){ focusGoal.set(x, 0, z); focus.copy(focusGoal); if (d) sDist = d; },
  hold(k, ms){ keys.add(k); setTimeout(() => keys.delete(k), ms); },
  teleport(x, z){ S.player.root.position.set(x, groundAt(x, z), z); if (riding() && DONKEY.root) DONKEY.root.position.set(x, groundAt(x, z), z); },
  tune: TUNE, walker: WALKER.s, rider: RIDER.s, riding: () => riding(),
  floors(id, n){ const v = S.buildings.get(id); if (v) setFloors(v.root, n); },
  haze(on){ GROUND_HAZE.off = !on; GROUND_HAZE.n = -1; drawHaze(); },
  get trek(){ return CONVOY.trek; }, trekSkip: share => CONVOY.skip(share), convoyPanel: () => CONVOY.open(),
  get fight(){ return FIGHT; }, get hexmap(){ return HEXMAP; }};

/* ------------------------------------------------------------ start */
const UI = createUI({api, S, walkToPlace, walkToBuilding, fastTravel, findMe, short,
  onStatus: () => { checkTravel(); checkKnown(); defaultView(); gangBanner(); CONVOY.sync(S.ST);
    if (riding() !== LAST_RIDING){ LAST_RIDING = riding(); modeChanged(); } }, toggleCamera: () => toggleCamera(), mode: () => camMode,
  foundOn: (p, c, t) => foundOn(p, c, t), buyOn: (p, c) => buyOn(p, c), clearSelection: () => clearSelection(),
  startPlacing: t => startPlacing(t), stopPlacing: () => stopPlacing(),
  // A delivery taken: down into the saddle, Red Dead style -- and if the
  // goods are already on you, off by convoy.
  onDelivery: () => { if (camMode !== "third") enterThird(); if (CONVOY.load() > 0) CONVOY.open(); },
  setOut: () => CONVOY.open(), convoyOn: () => CONVOY.active,
  pickTarget: (label, body) => { if (camMode !== "strategy") enterStrategy(S.player.root.position); HEXMAP.pick(label, body); }});
const FIGHT = createFight({THREE, scene, S, api, makePerson, setAnim, CSS2DObject, UI, placeAt, campInfo, groundAt,
  banditModel: () => CAST.m[CAST.m.length > 1 ? 1 : 0], makeMount: () => makeDonkey(), short, convoy: () => CONVOY.active});
/* THE CONVOY (2026-11-01, convoy.js; the score in convoy/trek.py). */
const CONVOY = createConvoy({THREE, scene, S, api, UI, SCALE, roadSegs, distToRoads, groundAt, placeAt, short,
  you: () => G.you, FIGHT: () => FIGHT, makePerson, setAnim, makeMount: () => makeDonkey(),
  enterThird: () => { if (camMode !== "third") enterThird(); },
  stopMount: () => { if (riding()){ RIDER.s.speed = Math.min(RIDER.s.speed, 1.5); RIDER.setGait(0); } },
  teleport: (x, z) => window.convoy.teleport(x, z), found: c => !outposts() || HEXMAP.knownPlace(c)});
/* THE MAP, HEX BY HEX (2026-11-01, hexmap.js; the rules in convoy/journey.py). */
const HEXMAP = createHexMap({THREE, scene, S, api, UI, SCALE, toScene, toWorld: v => toWorld(v), groundAt, makePerson, setAnim, CSS2DObject});
/* Moving is the map's, not your feet's: with outposts, outside a convoy. */
function mapDriven(){ return outposts() && !!(S.ST && S.ST.map && S.ST.map.hex) && !CONVOY.active; }
function mapMode(){ return mapDriven() && camMode === "strategy"; }
/* Units drawn big on the map, as Civilization's are; life size close up. */
function unitScale(){ return camMode === "strategy" && outposts() ? Math.max(1.6, Math.min(5, sDist / 16)) : 1; }
function scaleUnits(){
  const k = unitScale(), P = S.player;
  if (P) P.root.scale.setScalar(k);
  if (DONKEY.root){ DONKEY.root.userData.base = DONKEY.root.userData.base || DONKEY.root.scale.x; DONKEY.root.scale.setScalar(DONKEY.root.userData.base * k); }
  for (const v of S.agents.values()) v.root.scale.setScalar(k);
  for (const v of S.family.values()) v.root.scale.setScalar((v.m && !v.m.adult ? 0.68 : 1) * k);
}
/* Your unit, where the server's map says: on its hex, or crossing to the
   next in time with the clock. Riding, the donkey carries you. */
function updateMapUnit(dt){
  const P = S.player, u = HEXMAP.unitAt(liveHour() * 3600); if (!u) return;
  const ride = riding(), body = ride ? DONKEY.root : P.root, cur = body.position;
  const d = Math.hypot(u.pos.x - cur.x, u.pos.z - cur.z);
  if (d > 60){ cur.x = u.pos.x; cur.z = u.pos.z; }
  else { const k = Math.min(1, dt * 3); cur.x += (u.pos.x - cur.x) * k; cur.z += (u.pos.z - cur.z) * k; }
  cur.y = groundAt(cur.x, cur.z);
  if (u.moving) P.heading = u.heading;
  if (ride){
    DONKEY.root.rotation.y = P.heading; DONKEY.heading = P.heading;
    RIDER.s.heading = P.heading; RIDER.s.speed = u.moving ? 2.5 : 0;
    P.root.position.set(cur.x, cur.y + SADDLE * unitScale(), cur.z);
    setAnim(P, "idle", 1);
  } else {
    WALKER.s.vx = WALKER.s.vz = 0; WALKER.s.y = cur.y;
    setAnim(P, u.moving ? "walk" : "idle", 1);
  }
  P.root.rotation.y = P.heading;
  P.mixer.update(dt);
}
/* BANDIT GANGS (2026-10-30, convoy/robbery.py): a gang coming for one of
   your buildings walks in from its hideout in the hills, then mills about
   the building while it loots; a red banner counts the hour down. Only
   gangs you know of -- seen by your lookouts, or at your door. */
const GANGS = new Map();                         // robbery id -> {people, label}
function activeGangs(){
  return ((S.ST && S.ST.you.robberies) || []).filter(r => r.status === "coming" || r.status === "looting");
}
function updateGangs(dt){
  const list = activeGangs(), live = new Set(list.map(r => r.id));
  for (const [id, g] of GANGS) if (!live.has(id)){
    g.people.forEach(p => scene.remove(p.root));
    if (g.label) g.label.element.remove();          // a CSS2D label outlives its object otherwise
    GANGS.delete(id);
  }
  const now = S.HOUR * 3600;
  for (const r of list){
    if (r.x == null) continue;
    let g = GANGS.get(r.id);
    if (!g){
      g = {people: []};
      for (let i = 0; i < r.bandits; i++){
        const p = makePerson(CAST.m[CAST.m.length > 1 ? 1 : 0]);
        p.root.traverse(o => { o.userData.pick = {kind: "gang", id: r.id}; });
        scene.add(p.root); g.people.push(p);
      }
      const el = document.createElement("div"); el.className = "lbl-gang"; el.textContent = "\u2694 Bandits";
      g.label = new CSS2DObject(el); g.label.position.set(0, HUMAN_H + 0.9, 0); g.people[0].root.add(g.label);
      GANGS.set(r.id, g);
    }
    const from = toScene(r.hideout[0], r.hideout[1]), to = toScene(r.x, r.y);
    const k = Math.min(1, Math.max(0, (now - r.set_out) / Math.max(1, r.arrives_at - r.set_out)));
    g.people.forEach((p, i) => {
      let x, z;
      if (r.status === "looting" || k >= 1){
        const a = now / 400 + i * 2.1;                 // round the yard, taking what they can
        x = to.x + Math.cos(a) * (BUILDING_W * 0.6 + i); z = to.z + Math.sin(a) * (BUILDING_W * 0.6 + i);
      } else {
        const off = (i - (g.people.length - 1) / 2) * 2.4;
        x = from.x + (to.x - from.x) * k + off; z = from.z + (to.z - from.z) * k - off * 0.6;
      }
      const prev = p.root.position.clone();
      p.root.position.set(x, groundAt(x, z), z);
      const mv = p.root.position.clone().sub(prev).setY(0);
      const moving = mv.lengthSq() > 1e-5 && mv.lengthSq() < 400;
      if (moving) p.root.rotation.y = Math.atan2(mv.x, mv.z);
      setAnim(p, moving ? "walk" : "idle");
      p.mixer.update(dt);
    });
  }
}
function gangBanner(){
  const list = activeGangs();
  let el = $("gang-banner");
  if (!list.length){ if (el) el.remove(); return; }
  if (!el){ el = document.createElement("div"); el.id = "gang-banner"; document.body.appendChild(el); }
  const r = list.find(x => x.status === "looting") || list[0];
  const what = `your ${(r.type || "building").split(" /")[0]} at ${r.place}`;
  const html = `<b>\u2694 ${r.status === "looting" ? `${r.bandits} bandits are robbing ${esc(what)}` : `${r.bandits} bandits are heading for ${esc(what)}`}</b>`
    + `<span>${r.status === "looting" ? `${r.ends_in_min} min before they are gone with a share of its goods and purse.` : `About ${r.arrives_in_min} min away.`}`
    + ` ${r.lookouts ? `${r.lookouts} lookout${r.lookouts > 1 ? "s" : ""} on watch nearby.` : "No lookouts nearby: hire some at a security firm."}</span>`
    + `<div class="acts"><button data-gang="show">Show me</button><button data-gang="go">Ride there</button></div>`;
  if (el.dataset.html === html) return;
  el.dataset.html = html; el.innerHTML = html;
  el.querySelector('[data-gang="show"]').onclick = () => { const p = S.places[r.place]; if (p){ S.waypoint = p.c.clone(); flyTo(p.c, 90); } };
  el.querySelector('[data-gang="go"]').onclick = () => { const p = S.places[r.place]; if (p){ S.waypoint = p.c.clone(); walkToPlace(r.place); UI.toast("Riding to your building: fighting them yourself comes next"); } };
}
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
    msg.textContent = "Laying the land…";
    await loadLand();
    buildWorld(S.DATA, PLOTS.totals || {});
    bar.style.width = "10%";
    msg.textContent = "Calling the townsfolk…";
    await loadModels(k => { bar.style.width = `${10 + k * 80}%`; });
    await UI.boot();
    // You look like who you chose to be.
    try { const H = await api.get("/api/household"); if (H.you && H.you.sex === "f") PLAYER_CHARACTER = CAST.f[0]; } catch (e) {}
    const st = S.ST, place = (S.OBS && S.OBS.you.location) || (st && st.location);
    S.HOUR = st ? st.hour : S.DATA.end_hour;
    startLife(); syncLand(); syncBuildings(); syncAgents(); pollProduction();
    S.ready = true;
    setInterval(pollPlots, 4000);
    pollFamily(); setInterval(pollFamily, 3000);
    spawnPlayer(place);
    drawPortrait();
    findMe();
    // Open over your shoulder (2026-10-30): your home is already put down,
    // so there is nothing to place first. Tab gives the overview.
    camera.position.copy(S.player.root.position).add(new THREE.Vector3(0, 4, 9));
    // THE MAP FIRST (2026-11-01): with outposts the game opens on the map;
    // Tab looks round over your shoulder.
    if (outposts()){ sDist = 70; enterStrategy(S.player.root.position); } else enterThird();
    POV_SET = true;
    bar.style.width = "100%";
    setTimeout(() => $("cover").remove(), 250);
    requestAnimationFrame(animate);
    setInterval(async () => {
      try {
        const d = await api.get("/replay");
        if (d && d.places){
          S.DATA = d;
          for (const p of d.places) if (p.kind === "claim" && !S.places[p.name]) addClaimPlace(p, true);
          for (const p of d.places) if (p.kind === "claim" && p.path && p.path.length) drawClaimRoad(p.name, p.path);
          syncLand(); syncBuildings(); syncAgents();
        }
      } catch (e) { /* the next one will do */ }
    }, 4000);
  } catch (err) {
    console.error(err);
    msg.textContent = `Something went wrong: ${err.message || err}`;
  }
})();
