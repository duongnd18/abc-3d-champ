// ===== Helper library (prepended to every module; the model writes only build(THREE)) =====
// Every helper takes THREE as its first parameter, as the organiser's checker requires.
// Points are plain arrays; the helpers convert them (no NaN from forgetting THREE.Vector2).

// Lathe from a profile [[radius, y], ...] listed bottom → top. Radius is clamped to ≥ 0.
// Starts at angle π: the texture seam sits at the back (−Z) and the middle of a texture (u = 0.5) faces the camera.
function lathe(THREE, profile, segments) {
  return new THREE.LatheGeometry(profile.map((p) => new THREE.Vector2(Math.max(0, p[0]), p[1])), segments || 48,
    Math.PI);
}

// Vessel with a real wall: outer profile bottom → top, then the inner wall back down (wall = thickness).
function hollowLathe(THREE, outer, wall, segments) {
  const inner = outer.slice().reverse().map((p) => [Math.max(0, p[0] - wall), Math.max(outer[0][1] + wall, p[1])]);
  return lathe(THREE, outer.concat(inner), segments);
}

function roundRectShape(THREE, w, h, r) {
  const x = -w / 2, y = -h / 2;
  r = Math.max(0, Math.min(r, w / 2, h / 2));
  const s = new THREE.Shape();
  s.moveTo(x + r, y); s.lineTo(x + w - r, y); s.quadraticCurveTo(x + w, y, x + w, y + r);
  s.lineTo(x + w, y + h - r); s.quadraticCurveTo(x + w, y + h, x + w - r, y + h);
  s.lineTo(x + r, y + h); s.quadraticCurveTo(x, y + h, x, y + h - r);
  s.lineTo(x, y + r); s.quadraticCurveTo(x, y, x + r, y);
  return s;
}

// Box with rounded vertical edges (radius r) and bevelled faces; exact outer size w × h × d, centred.
function roundedBox(THREE, w, h, d, r) {
  const b = Math.min(r * 0.5, d * 0.25, w * 0.25, h * 0.25);
  const g = new THREE.ExtrudeGeometry(roundRectShape(THREE, w - 2 * b, h - 2 * b, Math.max(0, r - b)),
    { depth: Math.max(1e-4, d - 2 * b), bevelEnabled: b > 0, bevelThickness: b, bevelSize: b, bevelSegments: 3, curveSegments: 8 });
  g.center();
  return g;
}

// Flat outline [[x, y], ...] in XY, optional holes (list of outlines), extruded along Z to total
// thickness `depth` (bevel included, so the outline does not grow), centred on Z.
function extrudeOutline(THREE, pts, depth, bevel, holes) {
  const b = Math.min(bevel || 0, depth * 0.45);
  const shrink = (ring) => ring.map((p) => new THREE.Vector2(p[0], p[1]));
  const s = new THREE.Shape(shrink(pts));
  (holes || []).forEach((h) => s.holes.push(new THREE.Path(shrink(h))));
  const g = new THREE.ExtrudeGeometry(s, { depth: Math.max(1e-4, depth - 2 * b), bevelEnabled: b > 0,
    bevelThickness: b, bevelSize: b * 0.6, bevelSegments: 2, curveSegments: 16 });
  g.translate(0, 0, -(depth - 2 * b) / 2);
  return g;
}

// Tube along a smooth curve through [[x, y, z], ...] (handles, cords, rails, rims).
function tube(THREE, pts, radius, closed, radialSegments) {
  const curve = new THREE.CatmullRomCurve3(pts.map((p) => new THREE.Vector3(p[0], p[1], p[2])), !!closed);
  return new THREE.TubeGeometry(curve, Math.max(24, pts.length * 12), radius, radialSegments || 12, !!closed);
}

// Material presets tuned for the judge's neutral lighting (it has an environment map, so metals reflect).
// Metals stay at metalness ≤ 0.6: fully metallic surfaces render as dark mirrors and lose duels. 'glass' is a tinted
// see-through shell (opacity) for hollow glass and clear plastic.
// color: 0xrrggbb or '#rrggbb'. preset: chrome | steel | brushed | brass | gold | copper | gloss | plastic |
// matte | rubber | ceramic | wood | fabric | paint | glass | emissive. extra: any material fields to override.
function mat(THREE, preset, color, extra) {
  const P = { chrome: [0.6, 0.14], steel: [0.55, 0.28], brushed: [0.5, 0.42], brass: [0.55, 0.28],
    gold: [0.6, 0.24], copper: [0.55, 0.3], gloss: [0, 0.22], plastic: [0, 0.45], matte: [0, 0.8],
    rubber: [0, 0.92], ceramic: [0, 0.18], wood: [0, 0.68], fabric: [0, 0.95], paint: [0.2, 0.35] };
  const o = extra || {};
  if (preset === 'glass') {
    return new THREE.MeshPhysicalMaterial(Object.assign({ color: color, metalness: 0, roughness: 0.08,
      clearcoat: 1, clearcoatRoughness: 0.05, transparent: true, opacity: 0.4, depthWrite: false,
      side: THREE.DoubleSide }, o));
  }
  if (preset === 'emissive') {
    return new THREE.MeshStandardMaterial(Object.assign({ color: color, emissive: color, emissiveIntensity: 1.2, roughness: 0.4 }, o));
  }
  const p = P[preset] || P.plastic;
  return new THREE.MeshStandardMaterial(Object.assign({ color: color, metalness: p[0], roughness: p[1] }, o));
}

// Smooth procedural colour texture (size × size): kind 'grain' (wood rings), 'stripes', 'speckle'.
// Deterministic (no Math.random). Use as material.map; primitives already have UVs.
function patternTexture(THREE, kind, colorA, colorB, size, scale) {
  const n = size || 128, k = scale || 8, a = new THREE.Color(colorA), c = new THREE.Color(colorB);
  const data = new Uint8Array(n * n * 4);
  for (let y = 0; y < n; y++) {
    for (let x = 0; x < n; x++) {
      const u = x / n, v = y / n;
      let t;
      if (kind === 'grain') t = 0.5 + 0.5 * Math.sin((u * k + 0.15 * Math.sin(v * 9)) * Math.PI * 2);
      else if (kind === 'stripes') t = Math.sin(v * k * Math.PI * 2) > 0 ? 1 : 0;
      else t = 0.5 + 0.5 * Math.sin(u * 91.7 * k + Math.sin(v * 53.3 * k) * 3.1);
      const i = (y * n + x) * 4;
      data[i] = Math.round(255 * (a.r + (c.r - a.r) * t));
      data[i + 1] = Math.round(255 * (a.g + (c.g - a.g) * t));
      data[i + 2] = Math.round(255 * (a.b + (c.b - a.b) * t));
      data[i + 3] = 255;
    }
  }
  const tex = new THREE.DataTexture(data, n, n);
  tex.colorSpace = THREE.SRGBColorSpace;
  tex.wrapS = THREE.RepeatWrapping; tex.wrapT = THREE.RepeatWrapping;
  // DataTexture defaults to NearestFilter without mipmaps, which renders fine patterns as speckle.
  tex.magFilter = THREE.LinearFilter; tex.minFilter = THREE.LinearMipmapLinearFilter; tex.generateMipmaps = true;
  tex.needsUpdate = true;
  return tex;
}

// `count` copies of one geometry/material on a circle of `radius` around the Y axis at height y,
// each turned to face outward (bolts, studs, teeth, petals, spokes). One draw call.
function ringOf(THREE, geometry, material, count, radius, y, tiltX) {
  const im = new THREE.InstancedMesh(geometry, material, count);
  const o = new THREE.Object3D();
  for (let i = 0; i < count; i++) {
    const a = (i / count) * Math.PI * 2;
    o.position.set(Math.sin(a) * radius, y, Math.cos(a) * radius);
    o.rotation.set(tiltX || 0, a, 0);
    o.updateMatrix();
    im.setMatrixAt(i, o.matrix);
  }
  im.instanceMatrix.needsUpdate = true;
  return im;
}

// Position / rotate (radians) an object and return it.
function place(obj, x, y, z, rx, ry, rz) {
  obj.position.set(x || 0, y || 0, z || 0);
  obj.rotation.set(rx || 0, ry || 0, rz || 0);
  return obj;
}
// ===== end of helper library =====
