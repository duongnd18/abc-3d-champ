// ===== Framing (appended by the pipeline after build(THREE); not shown to the model) =====

// Tips a flat object (height under half its width or depth) 15° towards the camera.
function tiltTowardCamera(THREE, obj) {
  obj.updateMatrixWorld(true);
  const size = new THREE.Vector3();
  new THREE.Box3().setFromObject(obj).getSize(size);
  if (size.y < 0.5 * Math.max(size.x, size.z)) obj.rotation.x += (15 * Math.PI) / 180;
}

// Last resort when a module stays over the checker's 250,000 vertices after its repair: drop the parts that cost the
// most vertices for their size (small, finely tessellated parts first) until it fits. Used only for such modules.
function capVertices(THREE, root) {
  const LIMIT = 240000;
  const count = (o) => {
    let n = 0;
    o.traverse((c) => { if ((c.isMesh || c.isLine || c.isPoints) && c.geometry && c.geometry.attributes.position) n += c.geometry.attributes.position.count; });
    return n;
  };
  let total = count(root);
  if (total <= LIMIT) return;
  root.updateMatrixWorld(true);
  const parts = [];
  root.traverse((o) => {
    if (!(o.isMesh || o.isLine || o.isPoints) || !o.geometry || !o.geometry.attributes.position) return;
    const box = new THREE.Box3().setFromObject(o);
    const size = box.isEmpty() ? 0 : box.getSize(new THREE.Vector3()).length();
    parts.push({ o, cost: o.geometry.attributes.position.count / Math.max(size, 1e-4) });
  });
  parts.sort((a, b) => b.cost - a.cost);
  const attached = (o) => {
    for (let p = o; p; p = p.parent) if (p === root) return true;
    return false;
  };
  for (const { o } of parts) {
    if (total <= LIMIT) break;
    if (o === root || !o.parent || !attached(o)) continue;
    total -= count(o);
    o.parent.remove(o);
  }
}

// Centres the object and scales its longest side to 0.99, inside the organiser's [-0.5, 0.5] cube.
function fitToUnitCube(THREE, root) {
  root.updateMatrixWorld(true);
  const box = new THREE.Box3().setFromObject(root);
  const size = new THREE.Vector3(), center = new THREE.Vector3();
  box.getSize(size); box.getCenter(center);
  const s = 0.99 / Math.max(size.x, size.y, size.z, 1e-6);
  root.scale.setScalar(s);
  root.position.set(-center.x * s, -center.y * s, -center.z * s);
}

// Safety nets for modules over the checker's limits (they act only above the limit, so they never change a module
// the checker accepts): over 200 draw calls, merge opaque meshes per material with world matrices baked in (renders
// pixel-identical); over 4 MiB of DataTexture, share identical textures and halve the largest. From the team's
// AI-3D-Generation-phase2-mdt (bundle-a, MT198/MT200), MIT.
// A function, not a const: the renderer calls generate() before top-level consts are initialised.
function __gen3dMapKeys() {
  return ['map', 'normalMap', 'roughnessMap', 'metalnessMap', 'aoMap', 'emissiveMap', 'bumpMap',
    'alphaMap', 'displacementMap', 'clearcoatMap', 'clearcoatNormalMap', 'clearcoatRoughnessMap',
    'sheenColorMap', 'sheenRoughnessMap', 'specularColorMap', 'specularIntensityMap', 'transmissionMap',
    'thicknessMap', 'iridescenceMap', 'iridescenceThicknessMap', 'anisotropyMap', 'lightMap', 'envMap',
    'gradientMap', 'matcap', 'specularMap'];
}

// Over the checker's 200 draw calls, merge opaque meshes into one mesh per material: (a) the same material
// object, then (b) equal material parameters without textures, then (c) materials that differ only in colour,
// with the colour moved into vertex colours. World matrices are baked in, so the picture does not change.
// Below the limit nothing is touched.
function __gen3dMergeDraws(THREE, root) {
  const LIMIT = 200;
  const draws = () => {
    let n = 0;
    root.traverse((o) => { if (o.isMesh || o.isLine || o.isPoints) n++; });
    return n;
  };
  if (draws() <= LIMIT) return;
  const ATTRS = ['position', 'normal', 'uv', 'uv1', 'tangent', 'color'];
  const KEYS = __gen3dMapKeys();
  const textured = (m) => KEYS.some((k) => m[k]);
  const shown = (o) => {
    for (let p = o; p; p = p.parent) if (!p.visible) return false;
    return true;
  };
  const eligible = (o) => {
    if (!o.isMesh || o.isInstancedMesh || o.isSkinnedMesh || o.isBatchedMesh || !shown(o)) return false;
    const m = o.material, g = o.geometry;
    if (!m || Array.isArray(m) || m.isShaderMaterial || m.transparent || m.transmission > 0) return false;
    if (Object.hasOwn(m, 'onBeforeCompile') || !g || !g.isBufferGeometry || !g.attributes.position) return false;
    if (Object.keys(g.morphAttributes).length || g.drawRange.start !== 0 || g.drawRange.count !== Infinity) return false;
    if (g.index && g.index.isInterleavedBufferAttribute) return false;
    return !Object.values(g.attributes).some((a) => a.isInterleavedBufferAttribute) && o.layers.mask === 1;
  };
  const names = (o) => ATTRS.filter((n) => o.geometry.attributes[n] && (n !== 'color' || o.material.vertexColors)
    && (textured(o.material) || (n !== 'uv' && n !== 'uv1' && n !== 'tangent')));
  const ids = new Map();
  const idOf = (m) => {
    if (!ids.has(m)) ids.set(m, ids.size);
    return 'm' + ids.get(m);
  };
  const params = (m, dropColour) => {
    try {
      const d = m.toJSON();
      delete d.uuid; delete d.name;
      if (dropColour) { delete d.color; delete d.vertexColors; }
      return JSON.stringify(d);
    } catch (e) {
      return idOf(m);
    }
  };
  // tint: the colour goes into the vertex colours (level c); the item's own vertex colours are multiplied in.
  const tintable = (o) => {
    const m = o.material, c = o.geometry.attributes.color;
    return !textured(m) && m.color && m.color.isColor && (!m.vertexColors || (c && c.itemSize === 3));
  };
  const keyOf = (o, level) => {
    const m = o.material, tint = level === 2 && tintable(o);
    const attrs = names(o).filter((n) => !(tint && n === 'color'));
    const mat = level === 0 || textured(m) ? idOf(m) : params(m, tint);
    return [tint ? 't' : 'p', mat, attrs.map((n) => n + o.geometry.attributes[n].itemSize).join(','),
      o.castShadow, o.receiveShadow, o.renderOrder].join('|');
  };
  const bake = (items, tint, inv) => {
    const attrs = names(items[0]).filter((n) => !(tint && n === 'color'));
    const size = (n) => items[0].geometry.attributes[n].itemSize;
    let verts = 0, tris = 0;
    for (const o of items) {
      const g = o.geometry;
      verts += g.attributes.position.count;
      tris += g.index ? g.index.count : g.attributes.position.count;
    }
    const out = {};
    for (const n of attrs) out[n] = new Float32Array(verts * size(n));
    const colour = tint ? new Float32Array(verts * 3) : null;
    const index = verts > 65535 ? new Uint32Array(tris) : new Uint16Array(tris);
    const v = new THREE.Vector3();
    let base = 0, at = 0;
    for (const o of items) {
      const g = o.geometry, m = o.material, count = g.attributes.position.count;
      const m4 = new THREE.Matrix4().multiplyMatrices(inv, o.matrixWorld);
      const nm = new THREE.Matrix3().getNormalMatrix(m4);
      for (const n of attrs) {
        const a = g.attributes[n], s = size(n), dst = out[n];
        for (let i = 0; i < count; i++) {
          const j = (base + i) * s;
          if (n === 'position') {
            v.fromBufferAttribute(a, i).applyMatrix4(m4);
            dst[j] = v.x; dst[j + 1] = v.y; dst[j + 2] = v.z;
          } else if (n === 'normal') {
            v.fromBufferAttribute(a, i).applyMatrix3(nm).normalize();
            dst[j] = v.x; dst[j + 1] = v.y; dst[j + 2] = v.z;
          } else if (n === 'tangent') {
            v.set(a.getX(i), a.getY(i), a.getZ(i)).transformDirection(m4);
            dst[j] = v.x; dst[j + 1] = v.y; dst[j + 2] = v.z; dst[j + 3] = a.getW(i);
          } else {
            for (let c = 0; c < s; c++) dst[j + c] = a.getComponent(i, c);
          }
        }
      }
      if (tint) {
        const a = m.vertexColors ? g.attributes.color : null;
        for (let i = 0; i < count; i++) {
          const j = (base + i) * 3;
          colour[j] = m.color.r * (a ? a.getX(i) : 1);
          colour[j + 1] = m.color.g * (a ? a.getY(i) : 1);
          colour[j + 2] = m.color.b * (a ? a.getZ(i) : 1);
        }
      }
      const flip = m4.determinant() < 0;
      const n = g.index ? g.index.count : count;
      for (let i = 0; i < n; i++) {
        const k = flip && i % 3 !== 0 && i - (i % 3) + 2 < n ? i + (i % 3 === 1 ? 1 : -1) : i;
        index[at++] = base + (g.index ? g.index.getX(k) : k);
      }
      base += count;
    }
    const geo = new THREE.BufferGeometry();
    for (const n of attrs) geo.setAttribute(n, new THREE.BufferAttribute(out[n], size(n)));
    if (tint) geo.setAttribute('color', new THREE.BufferAttribute(colour, 3));
    geo.setIndex(new THREE.BufferAttribute(index, 1));
    let mat = items[0].material;
    if (tint) {
      mat = mat.clone();
      mat.color.setRGB(1, 1, 1);
      mat.vertexColors = true;
    }
    const mesh = new THREE.Mesh(geo, mat);
    mesh.castShadow = items[0].castShadow;
    mesh.receiveShadow = items[0].receiveShadow;
    mesh.renderOrder = items[0].renderOrder;
    return mesh;
  };
  // A merged mesh with children leaves an empty group with its transform, so the children stay where they are.
  const detach = (o) => {
    const p = o.parent;
    if (!o.children.length) {
      p.remove(o);
      return;
    }
    const g = new THREE.Group();
    g.name = o.name;
    g.position.copy(o.position); g.quaternion.copy(o.quaternion); g.scale.copy(o.scale);
    g.matrixAutoUpdate = o.matrixAutoUpdate; g.matrix.copy(o.matrix); g.matrixWorld.copy(o.matrixWorld);
    while (o.children.length) g.add(o.children[0]);
    p.children[p.children.indexOf(o)] = g;
    g.parent = p;
    o.parent = null;
  };
  for (let level = 0; level < 3 && draws() > LIMIT; level++) {
    root.updateMatrixWorld(true);
    const inv = root.matrixWorld.clone().invert();
    const buckets = new Map();
    root.traverse((o) => {
      if (!eligible(o)) return;
      const key = keyOf(o, level);
      if (!buckets.has(key)) buckets.set(key, []);
      buckets.get(key).push(o);
    });
    for (const [key, items] of buckets) {
      if (items.length < 2) continue;
      const mesh = bake(items, key[0] === 't', inv);
      for (const o of items) detach(o);
      root.add(mesh);
    }
  }
}

// Over the checker's 4 MiB DataTexture limit, share byte-identical textures, then halve the largest RGBA8
// texture (2x2 box filter) until the total fits. Below the limit nothing is touched.
function __gen3dTextureBudget(THREE, root) {
  const LIMIT = 4 * 1024 * 1024;
  const KEYS = __gen3dMapKeys();
  const slots = [];
  root.traverse((node) => {
    const mats = Array.isArray(node.material) ? node.material : [node.material];
    for (const m of mats) {
      if (!m) continue;
      for (const k of KEYS) if (m[k] && m[k].isDataTexture && m[k].image && m[k].image.data) slots.push([m, k]);
    }
  });
  const unique = () => [...new Set(slots.map(([m, k]) => m[k]))];
  const total = () => unique().reduce((s, t) => s + t.image.data.byteLength, 0);
  if (total() <= LIMIT) return;
  const keyOf = (t) => {
    const d = new Uint8Array(t.image.data.buffer, t.image.data.byteOffset, t.image.data.byteLength);
    let h = 2166136261 >>> 0;
    for (let i = 0; i < d.length; i++) h = Math.imul(h ^ d[i], 16777619) >>> 0;
    return [t.image.width, t.image.height, t.format, t.type, d.length, h].join(':');
  };
  const first = new Map();
  for (const [m, k] of slots) {
    const key = keyOf(m[k]);
    if (!first.has(key)) first.set(key, m[k]);
    else if (first.get(key) !== m[k]) m[k] = first.get(key);
  }
  let guard = 0;
  while (total() > LIMIT && guard++ < 16) {
    const big = unique().filter((t) => t.image.data instanceof Uint8Array
      && t.image.data.length === t.image.width * t.image.height * 4)
      .sort((a, b) => b.image.data.byteLength - a.image.data.byteLength)[0];
    if (!big || big.image.width < 64 || big.image.height < 64) break;
    const W = big.image.width, w = W >> 1, h = big.image.height >> 1, src = big.image.data;
    const out = new Uint8Array(w * h * 4);
    for (let y = 0; y < h; y++) for (let x = 0; x < w; x++) for (let c = 0; c < 4; c++) {
      const i = (2 * y * W + 2 * x) * 4 + c;
      out[(y * w + x) * 4 + c] = (src[i] + src[i + 4] + src[i + W * 4] + src[i + W * 4 + 4] + 2) >> 2;
    }
    const t = new THREE.DataTexture(out, w, h, big.format, big.type);
    t.colorSpace = big.colorSpace; t.wrapS = big.wrapS; t.wrapT = big.wrapT; t.flipY = big.flipY;
    t.repeat.copy(big.repeat); t.offset.copy(big.offset); t.center.copy(big.center); t.rotation = big.rotation;
    t.magFilter = big.magFilter; t.minFilter = big.minFilter; t.generateMipmaps = big.generateMipmaps;
    t.anisotropy = big.anisotropy; t.needsUpdate = true;
    for (const s of slots) if (s[0][s[1]] === big) s[0][s[1]] = t;
  }
}
