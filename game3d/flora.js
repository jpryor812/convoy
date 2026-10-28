/* TREES AND GRASS FROM PHOTOGRAPHS (2026-10-19). Poly Haven's scanned trees
   are millions of polygons -- film assets, not game ones -- so these are built
   the way games build them: a trunk, and "cards" (flat quads) textured with
   photographed branches, cut out by their alpha. A fir is tiers of drooping
   branch cards that shrink toward the top; a broadleaf tree is a crown of leaf
   cards round a forked trunk; grass is a few crossed cards of blades.

   Everything is one geometry per kind, drawn instanced: thousands of trees for
   a handful of draw calls. Textures: art/generated/3d/polyhaven/CREDITS.md. */

export function createFlora({THREE, tex, wind}){
  // ---- geometry helpers -------------------------------------------------------
  function quad(pos, uv, idx, a, b, c, d, u0, v0, u1, v1){
    const o = pos.length / 3;
    pos.push(...a, ...b, ...c, ...d);
    uv.push(u0, v0, u1, v0, u1, v1, u0, v1);
    idx.push(o, o + 1, o + 2, o, o + 2, o + 3);
  }
  function build(pos, uv, idx){
    const g = new THREE.BufferGeometry();
    g.setAttribute("position", new THREE.Float32BufferAttribute(pos, 3));
    g.setAttribute("uv", new THREE.Float32BufferAttribute(uv, 2));
    g.setIndex(idx); g.computeVertexNormals();
    // Cards lit as if they were the crown's surface: normals point out from the
    // trunk and up, so a tree is lit like a volume, not like flat paper.
    const p = g.attributes.position, n = g.attributes.normal;
    for (let i = 0; i < p.count; i++){
      const x = p.getX(i), y = p.getY(i), z = p.getZ(i), l = Math.hypot(x, z) || 1;
      const nx = x / l * 0.7, nz = z / l * 0.7, ny = 0.6, k = Math.hypot(nx, ny, nz);
      n.setXYZ(i, nx / k, ny / k, nz / k);
    }
    return g;
  }
  let seed = 9;
  const rnd = () => (seed = (seed * 16807) % 2147483647) / 2147483647;

  // A fir: tiers of branch cards. The twig atlas's branches sit in its upper
  // right; cards sample that region.
  function firFoliage(){
    const pos = [], uv = [], idx = [];
    const H = 9.5, tiers = 14;
    for (let t = 0; t < tiers; t++){
      const k = t / (tiers - 1), y = 1.3 + k * (H - 1.9);
      const R = 3.3 * Math.pow(1 - k, 0.8) + 0.45, n = 8 - Math.floor(k * 4);
      for (let i = 0; i < n; i++){
        const a = (i / n) * Math.PI * 2 + t * 0.9 + rnd() * 0.5;
        const cx = Math.cos(a), cz = Math.sin(a), px = -cz, pz = cx, w = R * 0.72, drop = R * 0.5;
        // from the trunk outward, drooping: a flat card, and a second one
        // standing on edge along it, so the branch reads from any side.
        const base = [0, y + 0.3, 0], tip = [cx * R * 1.05, y - drop, cz * R * 1.05];
        quad(pos, uv, idx,
          [base[0] - px * w * 0.3, base[1], base[2] - pz * w * 0.3], [base[0] + px * w * 0.3, base[1], base[2] + pz * w * 0.3],
          [tip[0] + px * w, tip[1], tip[2] + pz * w], [tip[0] - px * w, tip[1], tip[2] - pz * w],
          0.6, 0.18, 0.97, 0.62);
        quad(pos, uv, idx,
          [base[0], base[1] - w * 0.3, base[2]], [base[0], base[1] + w * 0.3, base[2]],
          [tip[0], tip[1] + w * 0.8, tip[2]], [tip[0], tip[1] - w * 0.8, tip[2]],
          0.6, 0.18, 0.97, 0.62);
      }
    }
    // the leader
    quad(pos, uv, idx, [-0.6, H - 1.6, 0], [0.6, H - 1.6, 0], [0.6, H + 0.3, 0], [-0.6, H + 0.3, 0], 0.62, 0.66, 0.95, 0.97);
    quad(pos, uv, idx, [0, H - 1.6, -0.6], [0, H - 1.6, 0.6], [0, H + 0.3, 0.6], [0, H + 0.3, -0.6], 0.62, 0.66, 0.95, 0.97);
    return build(pos, uv, idx);
  }
  // A broadleaf crown: leaf cards on a rough sphere.
  function leafCrown(){
    const pos = [], uv = [], idx = [];
    const C = [0, 5.2, 0], R = 2.6;
    for (let i = 0; i < 34; i++){
      const u = rnd() * 2 - 1, a = rnd() * Math.PI * 2, r = R * (0.55 + rnd() * 0.5);
      const dir = [Math.sqrt(1 - u * u) * Math.cos(a), u * 0.75, Math.sqrt(1 - u * u) * Math.sin(a)];
      const c = [C[0] + dir[0] * r, C[1] + dir[1] * r, C[2] + dir[2] * r];
      const s = 1.5 + rnd() * 0.7, ang = rnd() * Math.PI;
      const ax = [Math.cos(ang) * s, 0, Math.sin(ang) * s], ay = [0, s, 0];
      quad(pos, uv, idx,
        [c[0] - ax[0] - ay[0] * 0.5, c[1] - ay[1] * 0.5, c[2] - ax[2]], [c[0] + ax[0], c[1] - ay[1] * 0.5, c[2] + ax[2]],
        [c[0] + ax[0], c[1] + ay[1] * 0.5, c[2] + ax[2]], [c[0] - ax[0], c[1] + ay[1] * 0.5, c[2] - ax[2]],
        0.02, 0.05, 0.55, 0.95);
    }
    return build(pos, uv, idx);
  }
  function grassClump(){
    const pos = [], uv = [], idx = [];
    for (let i = 0; i < 5; i++){
      const a = i * Math.PI / 5 + rnd() * 0.3, cx = Math.cos(a) * 0.55, cz = Math.sin(a) * 0.55;
      const ox = (rnd() - 0.5) * 0.4, oz = (rnd() - 0.5) * 0.4, lean = (rnd() - 0.5) * 0.25;
      quad(pos, uv, idx, [ox - cx, 0, oz - cz], [ox + cx, 0, oz + cz], [ox + cx * 0.9 + lean, 0.75, oz + cz * 0.9], [ox - cx * 0.9 + lean, 0.75, oz - cz * 0.9], 0, 0, 1, 1);
    }
    const g = new THREE.BufferGeometry();
    g.setAttribute("position", new THREE.Float32BufferAttribute(pos, 3));
    g.setAttribute("uv", new THREE.Float32BufferAttribute(uv, 2));
    g.setIndex(idx);
    // Darker at the root, sunlit at the tip.
    const col = []; for (let i = 1; i < pos.length; i += 3){ const t = pos[i] / 0.75; const v = 0.62 + 0.38 * t; col.push(v, v, v * 0.95); }
    g.setAttribute("color", new THREE.Float32BufferAttribute(col, 3));
    const n = new Float32Array(pos.length); for (let i = 1; i < n.length; i += 3) n[i] = 1;   // lit from above, like the ground
    g.setAttribute("normal", new THREE.BufferAttribute(n, 3));
    return g;
  }
  function trunk(h, r){
    const g = new THREE.CylinderGeometry(r * 0.55, r, h, 7, 1, true);
    g.translate(0, h / 2, 0);
    const uvs = g.attributes.uv; for (let i = 0; i < uvs.count; i++) uvs.setXY(i, uvs.getX(i) * 2, uvs.getY(i) * h / 3);
    return g;
  }

  // ---- materials ----------------------------------------------------------------
  function swaying(mat, amount){
    mat.onBeforeCompile = sh => {
      sh.uniforms.uWind = wind;
      sh.vertexShader = "uniform float uWind;\n" + sh.vertexShader.replace("#include <begin_vertex>",
        `#include <begin_vertex>
         float ph = instanceMatrix[3].x * 0.21 + instanceMatrix[3].z * 0.17;
         float k = max(0.0, position.y - 1.0) * ${amount.toFixed(3)};
         transformed.x += sin(uWind * 1.4 + ph) * k;
         transformed.z += cos(uWind * 1.1 + ph * 1.3) * k * 0.6;`);
    };
    return mat;
  }
  function cardMat(map, alpha, amount, colour){
    const m = swaying(new THREE.MeshLambertMaterial({map, alphaMap: alpha, alphaTest: 0.45, side: THREE.DoubleSide,
      color: colour}), amount);
    return m;
  }
  function depthFor(alpha){
    return new THREE.MeshDepthMaterial({depthPacking: THREE.RGBADepthPacking, alphaMap: alpha, alphaTest: 0.45, side: THREE.DoubleSide});
  }
  const bark = new THREE.MeshLambertMaterial({map: tex.bark, color: "#b5a99a"});
  const firMat = cardMat(tex.twig, tex.twigA, 0.03, "#e9ecd2");
  const leafMat = cardMat(tex.leaves, tex.leavesA, 0.025, "#d8d0a8");
  // The photographed blades give the shape (alpha); the colour is straw and
  // sage, so a field reads as dry prairie grass in the late sun.
  const grassMat = swaying(new THREE.MeshLambertMaterial({alphaMap: tex.grassA, alphaTest: 0.4, vertexColors: true,
    side: THREE.DoubleSide, color: "#d2c690"}), 0.2);

  const GEO = {firTrunk: trunk(8.5, 0.22), fir: firFoliage(), oakTrunk: trunk(5, 0.38), crown: leafCrown(), grass: grassClump()};

  /* Plant `trees` ([x, y, z, scale, kind]) and `grass` ([x, y, z, scale]). */
  function plant(trees, grass){
    const firs = trees.filter(t => t[4] === "fir"), oaks = trees.filter(t => t[4] !== "fir");
    const out = [];
    const put = (geo, mat, list, castShadow, depth, tint) => {
      const im = new THREE.InstancedMesh(geo, mat, Math.max(1, list.length));
      const m4 = new THREE.Matrix4(), q = new THREE.Quaternion(), s = new THREE.Vector3(), p = new THREE.Vector3(), e = new THREE.Euler();
      const c = new THREE.Color();
      list.forEach(([x, y, z, k], i) => {
        e.set(0, (x * 13.7 + z * 3.1) % 6.28, 0); q.setFromEuler(e); s.set(k, k * (0.9 + ((x * 7) % 1) * 0.2), k); p.set(x, y, z);
        m4.compose(p, q, s); im.setMatrixAt(i, m4);
        if (tint){ const v = 0.82 + (((x * 31 + z * 17) % 1 + 1) % 1) * 0.3; c.setRGB(v, v * (0.97 + (((z * 11) % 1 + 1) % 1) * 0.06), v * 0.92); im.setColorAt(i, c); }
      });
      im.count = list.length;
      im.castShadow = castShadow; im.receiveShadow = true;
      if (depth) im.customDepthMaterial = depth;
      im.raycast = () => {};
      out.push(im);
    };
    put(GEO.firTrunk, bark, firs, true);
    put(GEO.fir, firMat, firs, true, depthFor(tex.twigA), true);
    put(GEO.oakTrunk, bark, oaks, true);
    put(GEO.crown, leafMat, oaks, true, depthFor(tex.leavesA), true);
    put(GEO.grass, grassMat, grass, false, null, true);
    return out;
  }
  /* THE GRASS AROUND YOU: a dense field within FIELD_R of the camera's
     focus, on a fixed world grid (so blades do not swim as you move),
     re-laid when you have moved a few metres. Further off, the photographed
     ground carries the grass. */
  function grassField(groundAt, grassy){
    const FIELD_R = 64, STEP = 1.05, N = Math.ceil((Math.PI * FIELD_R * FIELD_R) / (STEP * STEP));
    const im = new THREE.InstancedMesh(GEO.grass, grassMat, N);
    im.frustumCulled = false; im.raycast = () => {}; im.receiveShadow = false;
    const m4 = new THREE.Matrix4(), q = new THREE.Quaternion(), s = new THREE.Vector3(), p = new THREE.Vector3(), e = new THREE.Euler();
    const c = new THREE.Color();
    const h = (i, j, k) => { const v = Math.sin(i * 127.1 + j * 311.7 + k * 74.7) * 43758.5453; return v - Math.floor(v); };
    let at = null;
    function update(center){
      if (at && Math.hypot(center.x - at.x, center.z - at.z) < 6) return;
      at = {x: center.x, z: center.z};
      const i0 = Math.floor((center.x - FIELD_R) / STEP), i1 = Math.ceil((center.x + FIELD_R) / STEP);
      const j0 = Math.floor((center.z - FIELD_R) / STEP), j1 = Math.ceil((center.z + FIELD_R) / STEP);
      let n = 0;
      for (let i = i0; i <= i1 && n < N; i++) for (let j = j0; j <= j1 && n < N; j++){
        const x = (i + h(i, j, 1)) * STEP, z = (j + h(i, j, 2)) * STEP;
        const dd = Math.hypot(x - center.x, z - center.z);
        if (dd > FIELD_R || h(i, j, 3) < 0.18 || !grassy(x, z)) continue;
        const k = (0.5 + h(i, j, 4) * 0.55) * (dd > FIELD_R * 0.8 ? 1 - (dd - FIELD_R * 0.8) / (FIELD_R * 0.2) : 1);
        e.set(0, h(i, j, 5) * 6.28, 0); q.setFromEuler(e); s.set(k, k * (0.75 + h(i, j, 6) * 0.6), k); p.set(x, groundAt(x, z) - 0.04, z);
        m4.compose(p, q, s); im.setMatrixAt(n, m4);
        // Some clumps greener, some straw-dry.
        const v = 0.8 + h(i, j, 7) * 0.3, dry = h(i, j, 8);
        c.setRGB(v * (0.95 + dry * 0.15), v, v * (0.75 + (1 - dry) * 0.1)); im.setColorAt(n, c);
        n++;
      }
      im.count = n;
      im.instanceMatrix.needsUpdate = true; if (im.instanceColor) im.instanceColor.needsUpdate = true;
    }
    return {mesh: im, update};
  }
  return {plant, grassField};
}
