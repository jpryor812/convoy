/* THE LAND (designer direction, 2026-10-19): "the map is janky ... aim for Red
   Dead Redemption 2's colourway and vibe, with Civilization V's bird's-eye
   view as an option ... slightly more muted colours and grittier design."

   Rolling ground instead of a flat green sheet. Hills rise in the open
   country and lie flat where people are -- under every road, every place and
   claim, and along the rivers -- so towns, plots and roads keep their level
   footing, and the land between them has shape. Foothills gather round the
   mountains. The grass is muted sage and olive with dry ochre patches and
   darker hollows, broken up by tufts that move in the wind.

   heightAt(x, z) is the one source of truth for "where is the ground here";
   people, trees and the cursor all stand on it. reground() re-levels an area
   after the map changes (a new claim and its track). */

export function createTerrain({THREE, w, d, roadSegs, places, rivers, mountains, windUniform, tex, haze}){
  const STEP = 4;                                   // scene units between vertices
  const SNOWLINE = Math.max(40, Math.max(0, ...mountains.map(m => m.h || 0)) * 0.6);
  const nx = Math.ceil(w / STEP) + 1, nz = Math.ceil(d / STEP) + 1;
  const x0 = -w / 2, z0 = -d / 2;
  const H = new Float32Array(nx * nz);

  // ---- noise: value noise, a few octaves -------------------------------------
  const hash2 = (i, j) => { const s = Math.sin(i * 127.1 + j * 311.7) * 43758.5453; return s - Math.floor(s); };
  const smooth = t => t * t * (3 - 2 * t);
  function vnoise(x, z){
    const i = Math.floor(x), j = Math.floor(z), fx = smooth(x - i), fz = smooth(z - j);
    const a = hash2(i, j), b = hash2(i + 1, j), c = hash2(i, j + 1), e = hash2(i + 1, j + 1);
    return a + (b - a) * fx + (c - a) * fz + (a - b - c + e) * fx * fz;
  }
  function fbm(x, z, oct = 4){
    let s = 0, amp = 0.5, f = 1;
    for (let o = 0; o < oct; o++){ s += amp * vnoise(x * f, z * f); f *= 2.03; amp *= 0.5; }
    return s / 0.9375;
  }

  // ---- what keeps ground flat: roads (bucketed), places, rivers ---------------
  const BUCKET = 48, buckets = new Map();
  function bucketRoads(){
    buckets.clear();
    for (const s of roadSegs){
      const [ax, az, bx, bz, hw] = s, pad = hw + 30;
      const i0 = Math.floor((Math.min(ax, bx) - pad) / BUCKET), i1 = Math.floor((Math.max(ax, bx) + pad) / BUCKET);
      const j0 = Math.floor((Math.min(az, bz) - pad) / BUCKET), j1 = Math.floor((Math.max(az, bz) + pad) / BUCKET);
      for (let i = i0; i <= i1; i++) for (let j = j0; j <= j1; j++){
        const k = i * 100003 + j; let arr = buckets.get(k); if (!arr) buckets.set(k, arr = []); arr.push(s);
      }
    }
  }
  function roadDist(x, z){
    const arr = buckets.get(Math.floor(x / BUCKET) * 100003 + Math.floor(z / BUCKET));
    if (!arr) return 1e9;
    let best = 1e9;
    for (const [ax, az, bx, bz, hw] of arr){
      const vx = bx - ax, vz = bz - az, l2 = vx * vx + vz * vz || 1;
      const t = Math.max(0, Math.min(1, ((x - ax) * vx + (z - az) * vz) / l2));
      best = Math.min(best, Math.hypot(x - ax - vx * t, z - az - vz * t) - hw);
    }
    return best;
  }
  const ramp = (v, a, b) => { const t = Math.max(0, Math.min(1, (v - a) / (b - a))); return t * t * (3 - 2 * t); };
  function flatness(x, z){
    let m = ramp(roadDist(x, z), 3, 26);
    if (m <= 0) return 0;
    for (const p of Object.values(places)){
      const dd = Math.hypot(x - p.c.x, z - p.c.z) - p.r;
      if (dd < 34) m = Math.min(m, ramp(dd, 2, 34));
      if (m <= 0) return 0;
    }
    for (const r of rivers.x) m = Math.min(m, ramp(Math.abs(x - r.at) - r.half, 2, 26));
    for (const r of rivers.z) m = Math.min(m, ramp(Math.abs(z - r.at) - r.half, 2, 26));
    return m;
  }
  /* RIVERS LIE IN A CHANNEL (2026-10-19): the bed is sunk below the water,
     the banks wander a little (noise along the river), and where a road
     crosses it is a shallow ford. Returns {depth, bank}: how far below the
     plain, and 0..1 how much this is wet bank. */
  function river(x, z){
    let depth = 0, bank = 0;
    const one = (off, along, half) => {
      const wob = (vnoise(along * 0.045, 3.7) - 0.5) * 5 + (vnoise(along * 0.17, 9.1) - 0.5) * 1.6;
      const d = Math.abs(off) - (half + 1.5 + wob);
      if (d < 0) depth = Math.max(depth, Math.min(1, -d / 2.5) * 1.8 + 0.25);
      bank = Math.max(bank, 1 - ramp(d, -1, 5));
    };
    for (const r of rivers.x) one(x - r.at, z, r.half);
    for (const r of rivers.z) one(z - r.at, x, r.half);
    if (depth > 0){
      const ford = 1 - ramp(roadDist(x, z), 2, 10);
      depth *= 1 - ford * 0.9;
    }
    return {depth, bank};
  }
  function heightFn(x, z){
    const rv = river(x, z);
    if (rv.depth > 0) return -rv.depth;
    const m = flatness(x, z);
    if (m <= 0) return 0;
    const n = fbm(x * 0.0065 + 17.3, z * 0.0065 - 4.1);
    let h = Math.pow(Math.max(0, n - 0.18) / 0.82, 1.4) * 9;          // rolling hills, flats between
    h += (fbm(x * 0.03, z * 0.03, 2) - 0.5) * 0.8;                     // small undulation
    let peak = 0;
    for (const mt of mountains){
      const dist = Math.hypot(x - mt.x, z - mt.z);
      const dd = dist - mt.r * 0.85;
      if (dd < 80) h += Math.pow(1 - Math.max(0, dd) / 80, 2) * 8;    // foothills
      if (tex && mt.h){
        // THE MOUNTAIN ITSELF, part of the ground (2026-10-19): a ridged peak,
        // not a cone set on the grass. Ridges are |noise| folded sharp.
        const R = mt.r * 1.25, k = 1 - dist / R;
        if (k > 0){
          const ridge = 1 - Math.abs(fbm(x * 0.02 + mt.x, z * 0.02 - mt.z, 4) * 2 - 1);
          peak = Math.max(peak, mt.h * Math.pow(k, 1.5) * (0.62 + 0.55 * ridge * ridge));
        }
      }
    }
    return Math.max(0, h) * m + peak * Math.max(m, 0.15);
  }

  // ---- the mesh -------------------------------------------------------------
  const geo = new THREE.PlaneGeometry(w, d, nx - 1, nz - 1);
  geo.rotateX(-Math.PI / 2);                       // x across, z down the plane, y up
  const pos = geo.attributes.position;
  const col = new Float32Array(pos.count * 3);
  geo.setAttribute("color", new THREE.BufferAttribute(col, 3));
  // How much of each ground the vertex shows: mossy patches, dry earth, worn trail.
  const spl = new Float32Array(pos.count * 3);
  geo.setAttribute("splat", new THREE.BufferAttribute(spl, 3));
  const wet = new Float32Array(pos.count);
  geo.setAttribute("wet", new THREE.BufferAttribute(wet, 1));
  // RDR2-ish grass: sage, olive, dry ochre, dark hollows.
  const SAGE = new THREE.Color("#93a062"), OLIVE = new THREE.Color("#a29d5e"), DRY = new THREE.Color("#c2b07a"),
        DARK = new THREE.Color("#6c7844"), WORN = new THREE.Color("#b3a27c"), tmp = new THREE.Color();
  function shade(i, x, z, h){
    const a = fbm(x * 0.012 + 40, z * 0.012 - 9, 3), b = fbm(x * 0.05 - 3, z * 0.05 + 8, 2);
    tmp.copy(SAGE).lerp(OLIVE, a);
    tmp.lerp(DRY, ramp(b, 0.55, 0.85) * 0.6 + ramp(h, 6, 14) * 0.25);   // dry patches, sunburnt tops
    tmp.lerp(DARK, ramp(0.45 - a, 0, 0.3) * 0.5);                        // damp hollows
    const worn = 1 - ramp(roadDist(x, z), 0, 9);                         // trodden verges
    tmp.lerp(WORN, worn * 0.55);
    if (tex){
      // Photographed ground does the detail; the vertex colour only nudges
      // the tone across the land, around white.
      const k = 0.92 + a * 0.16;
      col[i * 3] = k * (1.02 + (b - 0.5) * 0.06); col[i * 3 + 1] = k; col[i * 3 + 2] = k * (0.94 - (b - 0.5) * 0.05);
      spl[i * 3] = ramp(a, 0.45, 0.75);                                         // mossy patches
      spl[i * 3 + 1] = Math.min(1, ramp(b, 0.58, 0.82) * 0.8 + ramp(h, 7, 12) * 0.4); // dry, sunburnt
      spl[i * 3 + 2] = worn;                                                    // trodden
      wet[i] = river(x, z).bank;                                                // sand and mud by the water
    } else { col[i * 3] = tmp.r; col[i * 3 + 1] = tmp.g; col[i * 3 + 2] = tmp.b; }
  }
  function fill(ix0, iz0, ix1, iz1){
    for (let iz = iz0; iz <= iz1; iz++) for (let ix = ix0; ix <= ix1; ix++){
      const i = iz * nx + ix, x = x0 + ix * STEP, z = z0 + iz * STEP;
      const h = heightFn(x, z);
      H[i] = h; pos.setY(i, h); shade(i, x, z, h);
    }
  }
  bucketRoads();
  fill(0, 0, nx - 1, nz - 1);
  geo.computeVertexNormals();

  // A fine, near-white grain on top of the vertex colours: close up the grass
  // has texture; far off the colours carry it.
  const c = document.createElement("canvas"); c.width = c.height = 256;
  const g = c.getContext("2d"); g.fillStyle = "#e9e6dc"; g.fillRect(0, 0, 256, 256);
  for (let i = 0; i < 9000; i++){
    const v = 200 + Math.random() * 55 | 0, x = Math.random() * 256, y = Math.random() * 256;
    g.fillStyle = `rgb(${v},${v - 4},${v - 18})`;
    for (const ox of [0, -256]) for (const oy of [0, -256]) g.fillRect(x + ox, y + oy, 1 + Math.random() * 2, 1 + Math.random() * 3);
  }
  const grain = new THREE.CanvasTexture(c);
  grain.wrapS = grain.wrapT = THREE.RepeatWrapping; grain.repeat.set(w / 10, d / 10);
  grain.colorSpace = THREE.SRGBColorSpace; grain.anisotropy = 8;
  const mesh = new THREE.Mesh(geo, withHaze(tex ? splatMaterial() : new THREE.MeshLambertMaterial({vertexColors: true, map: grain})));

  /* HAZE (2026-10-28): with outposts, ground you have not explored is veiled.
     `haze.tHaze` is a texture over the whole ground (alpha = how hazy) and
     `haze.uHazeBox` its corner and size in scene units. */
  function withHaze(mat){
    if (!haze) return mat;
    const before = mat.onBeforeCompile;
    mat.onBeforeCompile = (sh, r) => {
      if (before) before.call(mat, sh, r);
      Object.assign(sh.uniforms, haze);
      sh.vertexShader = sh.vertexShader
        .replace("#include <common>", "#include <common>\nvarying vec2 vHazeXZ;")
        .replace("#include <begin_vertex>", "#include <begin_vertex>\nvHazeXZ = (modelMatrix * vec4(transformed, 1.0)).xz;");
      sh.fragmentShader = sh.fragmentShader
        .replace("#include <common>", "#include <common>\nuniform sampler2D tHaze; uniform vec4 uHazeBox; uniform float uHazeOn; varying vec2 vHazeXZ;")
        .replace("#include <dithering_fragment>", `#include <dithering_fragment>
          float hz = uHazeOn * texture2D(tHaze, (vHazeXZ - uHazeBox.xy) / uHazeBox.zw).a;
          gl_FragColor.rgb = mix(gl_FragColor.rgb, vec3(0.87, 0.84, 0.78), hz * 0.86);`);
    };
    return mat;
  }
  mesh.receiveShadow = true; mesh.name = "ground";

  /* PHOTOGRAPHED GROUND (2026-10-19, Poly Haven, CC0): prairie grass, mossy
     patches, cracked dry earth, a stony trail and rock, blended by the splat
     weights and by slope, in world space so nothing stretches over a hill.
     Each is sampled at two scales and mixed, so the tiling does not show. */
  function splatMaterial(){
    // Fine relief from the grass's normal map, tiled over the whole ground:
    // the light catches tussocks and ruts instead of a smooth sheet.
    const mat = new THREE.MeshStandardMaterial({vertexColors: true, roughness: 0.97, metalness: 0,
      normalMap: tex.grassN || null, normalScale: new THREE.Vector2(0.7, 0.7)});
    mat.onBeforeCompile = sh => {
      Object.assign(sh.uniforms, {tGrass: {value: tex.grass}, tMoss: {value: tex.moss}, tDry: {value: tex.dry},
                                  tTrail: {value: tex.trail}, tRock: {value: tex.rock}, uSnow: {value: SNOWLINE},
                                  tSand: {value: tex.sand || tex.dry}});
      sh.vertexShader = sh.vertexShader
        .replace("#include <common>", "#include <common>\nattribute vec3 splat; attribute float wet; varying vec3 vSplat; varying float vWet; varying vec3 vWPos; varying vec3 vWNrm;")
        .replace("#include <begin_vertex>", "#include <begin_vertex>\nvSplat = splat; vWet = wet; vWPos = (modelMatrix * vec4(transformed, 1.0)).xyz; vWNrm = normalize(mat3(modelMatrix) * objectNormal);");
      sh.fragmentShader = sh.fragmentShader
        .replace("#include <common>", `#include <common>
          uniform sampler2D tGrass, tMoss, tDry, tTrail, tRock, tSand; uniform float uSnow; varying float vWet; varying vec3 vSplat; varying vec3 vWPos; varying vec3 vWNrm;
          vec3 two(sampler2D t, vec2 p){ return mix(texture2D(t, p * 0.16).rgb, texture2D(t, p * 0.037 + 0.31).rgb, 0.45); }`)
        .replace("#include <map_fragment>", `
          vec2 p = vWPos.xz;
          vec3 g = two(tGrass, p);
          g = mix(g, two(tMoss, p * 1.3), vSplat.x * 0.7);
          g = mix(g, two(tDry, p * 0.8), vSplat.y * 0.75);
          g = mix(g, texture2D(tTrail, p * 0.22).rgb, clamp(vSplat.z * 1.1, 0.0, 1.0));
          // Banks: gravelly sand, darkening to wet mud toward the water.
          vec3 sand = two(tSand, p * 0.9);
          g = mix(g, sand, smoothstep(0.15, 0.7, vWet));
          g *= mix(1.0, 0.62, smoothstep(-0.05, -0.9, vWPos.y));
          float steep = smoothstep(0.80, 0.62, normalize(vWNrm).y);
          g = mix(g, texture2D(tRock, p * 0.09).rgb, steep);
          float snow = smoothstep(uSnow, uSnow + 14.0, vWPos.y + (texture2D(tRock, p * 0.05).r - 0.5) * 12.0) * smoothstep(0.35, 0.7, normalize(vWNrm).y);
          g = mix(g, vec3(0.93, 0.93, 0.95) * 1.1, snow);
          diffuseColor.rgb *= g;
          if (snow > 0.0) diffuseColor.rgb = mix(diffuseColor.rgb, g, snow);`);
    };
    return mat;
  }

  function heightAt(x, z){
    const fx = (x - x0) / STEP, fz = (z - z0) / STEP;
    const ix = Math.max(0, Math.min(nx - 2, Math.floor(fx))), iz = Math.max(0, Math.min(nz - 2, Math.floor(fz)));
    const tx = Math.max(0, Math.min(1, fx - ix)), tz = Math.max(0, Math.min(1, fz - iz));
    const a = H[iz * nx + ix], b = H[iz * nx + ix + 1], cc = H[(iz + 1) * nx + ix], e = H[(iz + 1) * nx + ix + 1];
    // The plane is split into two triangles per square; follow the same split.
    return tx + tz <= 1 ? a + (b - a) * tx + (cc - a) * tz : e + (cc - e) * (1 - tx) + (b - e) * (1 - tz);
  }
  function reground(xa, za, xb, zb){
    bucketRoads();
    const ix0 = Math.max(0, Math.floor((Math.min(xa, xb) - 40 - x0) / STEP)), ix1 = Math.min(nx - 1, Math.ceil((Math.max(xa, xb) + 40 - x0) / STEP));
    const iz0 = Math.max(0, Math.floor((Math.min(za, zb) - 40 - z0) / STEP)), iz1 = Math.min(nz - 1, Math.ceil((Math.max(za, zb) + 40 - z0) / STEP));
    fill(ix0, iz0, ix1, iz1);
    pos.needsUpdate = true; geo.attributes.color.needsUpdate = true; geo.attributes.splat.needsUpdate = true;
    geo.attributes.wet.needsUpdate = true;
    geo.computeVertexNormals();
  }

  // ---- grass tufts ----------------------------------------------------------
  function tufts(count){
    const blade = new THREE.BufferGeometry();
    const v = [];
    for (let k = 0; k < 3; k++){
      const a = k * Math.PI / 3, cx = Math.cos(a) * 0.32, cz = Math.sin(a) * 0.32;
      v.push(-cx, 0, -cz, cx, 0, cz, 0.05, 0.9, 0.02);
    }
    blade.setAttribute("position", new THREE.Float32BufferAttribute(v, 3));
    blade.computeVertexNormals();
    const mat = new THREE.MeshLambertMaterial({color: "#ffffff", side: THREE.DoubleSide});
    mat.onBeforeCompile = sh => {
      sh.uniforms.uWind = windUniform;
      sh.vertexShader = "uniform float uWind;\n" + sh.vertexShader.replace("#include <begin_vertex>",
        `#include <begin_vertex>
         float ph = instanceMatrix[3].x * 0.37 + instanceMatrix[3].z * 0.29;
         transformed.x += sin(uWind * 2.2 + ph) * position.y * 0.22;
         transformed.z += cos(uWind * 1.7 + ph) * position.y * 0.12;`);
    };
    const im = new THREE.InstancedMesh(blade, mat, count);
    const m4 = new THREE.Matrix4(), q = new THREE.Quaternion(), s = new THREE.Vector3(), p = new THREE.Vector3(), e = new THREE.Euler();
    const tint = new THREE.Color();
    let n = 0, seed = 3;
    const rnd = () => (seed = (seed * 16807) % 2147483647) / 2147483647;
    for (let tries = 0; n < count && tries < count * 4; tries++){
      const x = x0 + rnd() * w, z = z0 + rnd() * d;
      if (flatness(x, z) < 0.15 && roadDist(x, z) < 6) continue;      // not on the road itself
      let onPlace = false;
      for (const pl of Object.values(places)) if (Math.hypot(x - pl.c.x, z - pl.c.z) < pl.r * 0.8){ onPlace = true; break; }
      if (onPlace) continue;
      if (rivers.x.some(r => Math.abs(x - r.at) < r.half + 1) || rivers.z.some(r => Math.abs(z - r.at) < r.half + 1)) continue;
      const k = 0.7 + rnd() * 1.1;
      e.set(0, rnd() * 6.28, 0); q.setFromEuler(e); s.set(k, k * (0.7 + rnd() * 0.8), k); p.set(x, heightAt(x, z), z);
      m4.compose(p, q, s); im.setMatrixAt(n, m4);
      const a = fbm(x * 0.012 + 40, z * 0.012 - 9, 3);
      tint.copy(SAGE).lerp(DRY, rnd() * 0.5 + (a < 0.4 ? 0 : 0.2)).multiplyScalar(0.85 + rnd() * 0.25);
      im.setColorAt(n, tint);
      n++;
    }
    im.count = n;
    im.raycast = () => {};
    return im;
  }

  /* Where grass grows: open ground off roads, places and water. */
  function spots(count){
    const out = [];
    let seed2 = 5;
    const rnd = () => (seed2 = (seed2 * 16807) % 2147483647) / 2147483647;
    for (let tries = 0; out.length < count && tries < count * 4; tries++){
      const x = x0 + rnd() * w, z = z0 + rnd() * d;
      if (roadDist(x, z) < 4) continue;
      let onPlace = false;
      for (const pl of Object.values(places)) if (Math.hypot(x - pl.c.x, z - pl.c.z) < pl.r * 0.8){ onPlace = true; break; }
      if (onPlace) continue;
      if (rivers.x.some(r => Math.abs(x - r.at) < r.half + 1) || rivers.z.some(r => Math.abs(z - r.at) < r.half + 1)) continue;
      const y = heightAt(x, z);
      if (y > SNOWLINE - 10) continue;
      out.push([x, y - 0.05, z, 0.8 + rnd() * 1.0]);
    }
    return out;
  }
  /* Can grass grow here? Off roads, places, water and snow. */
  function grassy(x, z){
    if (roadDist(x, z) < 3.5) return false;
    for (const pl of Object.values(places)) if (Math.hypot(x - pl.c.x, z - pl.c.z) < pl.r * 0.75) return false;
    if (river(x, z).bank > 0.3) return false;
    return heightAt(x, z) < SNOWLINE - 12;
  }
  return {mesh, heightAt, reground, tufts, spots, grassy};
}
