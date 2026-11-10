/* Shahar Arena — 3D shahar rejimi (three.js r149).
 * Ochiq shahar: piyoda yurish, istalgan mashinaga o'tirish, transport oqimi, piyodalar,
 * kun/tun almashinuvi, politsiya ta'qibi, topshiriqlar va tangalar.
 * game.html dagi umumiy funksiyalardan foydalanadi: P, getMove, input, toast, sfx, haptic, $, esc, fmt,
 * CAR_STATS, MISSION_COINS, PICKUP_COINS, SOUND, AC.
 */
(function () {
'use strict';
const T = window.THREE;
const N = 8, BL = 46, RD = 14, CELL = BL + RD, WORLD = N * CELL + RD, SW = 2.6, LANE = 3.4;
const roadC = i => i * CELL + RD / 2;
const cl = (v, a, b) => v < a ? a : v > b ? b : v;
const rr = (a, b) => a + Math.random() * (b - a);
const ad = (a, b) => { let d = a - b; while (d > Math.PI) d -= 2 * Math.PI; while (d < -Math.PI) d += 2 * Math.PI; return d; };
const dxz = (a, b) => Math.hypot(a.x - b.x, a.z - b.z);
const pick = a => a[Math.floor(Math.random() * a.length)];
let sd = 90210;
const srnd = () => { sd |= 0; sd = sd + 0x6D2B79F5 | 0; let t = Math.imul(sd ^ sd >>> 15, 1 | sd); t = t + Math.imul(t ^ t >>> 7, 61 | t) ^ t; return ((t ^ t >>> 14) >>> 0) / 4294967296; };
let QUALITY = 1;
try { const q = localStorage.getItem('sa_q'); if (q !== null) QUALITY = +q; } catch (e) {}

// ═════════════ DUNYO ═════════════
const blocks = [];
const PAL = [0xd9d4c7, 0xc9b8a0, 0xa9b4c2, 0xe0c9a6, 0xb7c4b0, 0xcfa79a, 0x9fb1c9, 0xe5e1d8, 0xb8a6c9, 0x8e9aa8, 0xd8c3a5, 0x9aa7a0];
(function gen() {
  const mid = WORLD / 2;
  for (let j = 0; j < N; j++) for (let i = 0; i < N; i++) {
    const x = i * CELL + RD, z = j * CELL + RD, r = srnd();
    const df = 1 - Math.min(1, Math.hypot(x + BL / 2 - mid, z + BL / 2 - mid) / (WORLD * 0.5));
    const b = {i, j, x, z, type: r < 0.11 ? 'park' : r < 0.16 ? 'plaza' : r < 0.23 ? 'lot' : 'build', solids: [], trees: [], spots: []};
    if (b.type === 'build') {
      const m = SW + 0.8, g = 3, S = BL - 2 * m, sp = Math.floor(srnd() * 4), Hh = (S - g) / 2;
      const rects = sp === 0 ? [[0, 0, S, S]] : sp === 1 ? [[0, 0, S, Hh], [0, Hh + g, S, Hh]] : sp === 2 ? [[0, 0, Hh, S], [Hh + g, 0, Hh, S]]
        : [[0, 0, Hh, Hh], [Hh + g, 0, Hh, Hh], [0, Hh + g, Hh, Hh], [Hh + g, Hh + g, Hh, Hh]];
      for (const q of rects) {
        const h = 7 + srnd() * 12 + df * df * srnd() * 75;
        b.solids.push({x: x + m + q[0], z: z + m + q[1], w: q[2], d: q[3], h, top: h, c: PAL[Math.floor(srnd() * PAL.length)]});
      }
    } else if (b.type === 'park') {
      for (let k = 0; k < 9; k++) b.trees.push({x: x + 6 + srnd() * (BL - 12), z: z + 6 + srnd() * (BL - 12), r: 0.5});
    } else if (b.type === 'plaza') {
      b.trees.push({x: x + BL / 2, z: z + BL / 2, r: 4.4, fountain: true});
      for (const [a, c] of [[7, 7], [BL - 7, 7], [7, BL - 7], [BL - 7, BL - 7]]) b.trees.push({x: x + a, z: z + c, r: 0.5});
    } else {
      for (let k = 0; k < 6; k++) for (const side of [-1, 1]) b.spots.push({x: x + 8 + k * 6, z: z + BL / 2 + side * 7.5, yaw: side > 0 ? Math.PI : 0});
    }
    blocks.push(b);
  }
})();
// chiroq ustunlari (chorrahalar burchagida)
const poles = {};
for (let j = 0; j <= N; j++) for (let i = 0; i <= N; i++) {
  const cx = roadC(i), cz = roadC(j), o = RD / 2 + 1.1, list = [];
  for (const [sx, sz] of [[1, 1], [-1, -1]]) {
    const x = cx + sx * o, z = cz + sz * o;
    if (x > 1 && z > 1 && x < WORLD - 1 && z < WORLD - 1) list.push({x, z, r: 0.25, yaw: Math.atan2(cx - x, cz - z)});
  }
  poles[i + ',' + j] = list;
}
function blockIdx(x, z) { return [Math.floor((x - RD) / CELL), Math.floor((z - RD) / CELL)]; }
function circleOut(e, cx, cz, r, hitR) {
  let dx = e.x - cx, dz = e.z - cz; const d = Math.hypot(dx, dz) || 0.001, R = hitR + r;
  if (d >= R) return null;
  dx /= d; dz /= d; e.x = cx + dx * R; e.z = cz + dz * R; return {nx: dx, nz: dz};
}
function collide(e, r) {
  let hit = null;
  const [bi, bj] = blockIdx(e.x, e.z);
  for (let j = bj - 1; j <= bj + 1; j++) for (let i = bi - 1; i <= bi + 1; i++) {
    if (i < 0 || j < 0 || i >= N || j >= N) continue;
    const b = blocks[j * N + i];
    for (const s of b.solids) {
      const cx = cl(e.x, s.x, s.x + s.w), cz = cl(e.z, s.z, s.z + s.d);
      let dx = e.x - cx, dz = e.z - cz; const q = dx * dx + dz * dz;
      if (q >= r * r) continue;
      if (q < 1e-6) {
        const o = [[e.x - s.x, -1, 0], [s.x + s.w - e.x, 1, 0], [e.z - s.z, 0, -1], [s.z + s.d - e.z, 0, 1]].sort((a, c) => a[0] - c[0])[0];
        e.x += o[1] * (o[0] + r); e.z += o[2] * (o[0] + r); hit = {nx: o[1], nz: o[2]};
      } else { const d = Math.sqrt(q); dx /= d; dz /= d; e.x += dx * (r - d); e.z += dz * (r - d); hit = {nx: dx, nz: dz}; }
    }
    for (const t of b.trees) { const h = circleOut(e, t.x, t.z, t.r, r); if (h) hit = h; }
  }
  const ni = Math.round((e.x - RD / 2) / CELL), nj = Math.round((e.z - RD / 2) / CELL);
  for (const p of poles[ni + ',' + nj] || []) { const h = circleOut(e, p.x, p.z, p.r, r); if (h) hit = h; }
  if (e.x < r) { e.x = r; hit = {nx: 1, nz: 0}; } if (e.x > WORLD - r) { e.x = WORLD - r; hit = {nx: -1, nz: 0}; }
  if (e.z < r) { e.z = r; hit = {nx: 0, nz: 1}; } if (e.z > WORLD - r) { e.z = WORLD - r; hit = {nx: 0, nz: -1}; }
  return hit;
}
function solidAt(x, z, y) {
  const [i, j] = blockIdx(x, z);
  if (i < 0 || j < 0 || i >= N || j >= N) return false;
  for (const s of blocks[j * N + i].solids) if (x > s.x && x < s.x + s.w && z > s.z && z < s.z + s.d && y < s.top + 1) return true;
  return false;
}
function roadPoint() {
  const k = Math.floor(Math.random() * (N + 1)), along = rr(15, WORLD - 15), off = rr(-RD / 3, RD / 3);
  return Math.random() < 0.5 ? {x: along, z: roadC(k) + off} : {x: roadC(k) + off, z: along};
}
function farPoint(from, mn, mx) {
  let best = null;
  for (let i = 0; i < 80; i++) { const p = roadPoint(), d = dxz(p, from); if (d >= mn && d <= mx) return p; if (!best || Math.abs(d - mn) < Math.abs(dxz(best, from) - mn)) best = p; }
  return best;
}

// ═════════════ GRAFIKA ═════════════
let renderer, scene, camera, sun, hemi, bldMat, bulbMat, headL, vehMat, gl, maxAniso = 1;
const texCache = {};
function canvasTex(c, repeat) {
  const t = new T.CanvasTexture(c); t.anisotropy = maxAniso;
  if (repeat) { t.wrapS = t.wrapT = T.RepeatWrapping; }
  return t;
}
function shade(hex, k) { const c = new T.Color(hex); c.multiplyScalar(k); return c.getHex(); }
const bx = (w, h, d, x, y, z, c) => { const g = new T.BoxGeometry(w, h, d).toNonIndexed(); g.translate(x, y, z); return {g, c}; };
const cy = (r, w, x, y, z, c, seg) => { const g = new T.CylinderGeometry(r, r, w, seg || 10).toNonIndexed(); g.rotateZ(Math.PI / 2); g.translate(x, y, z); return {g, c}; };
function merge(parts) {
  let n = 0; for (const p of parts) n += p.g.attributes.position.count;
  const pos = new Float32Array(n * 3), nor = new Float32Array(n * 3), col = new Float32Array(n * 3), c = new T.Color();
  let o = 0;
  for (const p of parts) {
    const cnt = p.g.attributes.position.count;
    pos.set(p.g.attributes.position.array, o * 3); nor.set(p.g.attributes.normal.array, o * 3);
    c.setHex(p.c); for (let i = 0; i < cnt; i++) { col[(o + i) * 3] = c.r; col[(o + i) * 3 + 1] = c.g; col[(o + i) * 3 + 2] = c.b; }
    o += cnt; p.g.dispose();
  }
  const g = new T.BufferGeometry();
  g.setAttribute('position', new T.BufferAttribute(pos, 3)); g.setAttribute('normal', new T.BufferAttribute(nor, 3)); g.setAttribute('color', new T.BufferAttribute(col, 3));
  g.computeBoundingSphere();
  return g;
}

function buildGround() {
  const S = 2048, k = S / WORLD, c = document.createElement('canvas'); c.width = c.height = S;
  const g = c.getContext('2d');
  g.fillStyle = '#3a3d44'; g.fillRect(0, 0, S, S);
  for (let i = 0; i < 14000; i++) { g.fillStyle = Math.random() < 0.5 ? '#35383e' : '#42454c'; g.fillRect(Math.random() * S, Math.random() * S, 2, 2); }
  for (const b of blocks) {
    const X = b.x * k, Z = b.z * k, Bk = BL * k, s = SW * k;
    g.fillStyle = '#a7a7a2'; g.fillRect(X, Z, Bk, Bk);
    g.strokeStyle = '#96968f'; g.lineWidth = 1;
    for (let q = 2; q < BL; q += 2) { g.beginPath(); g.moveTo(X + q * k, Z); g.lineTo(X + q * k, Z + s); g.moveTo(X + q * k, Z + Bk - s); g.lineTo(X + q * k, Z + Bk); g.moveTo(X, Z + q * k); g.lineTo(X + s, Z + q * k); g.moveTo(X + Bk - s, Z + q * k); g.lineTo(X + Bk, Z + q * k); g.stroke(); }
    g.strokeStyle = '#d6d6d0'; g.lineWidth = 3; g.strokeRect(X + 1.5, Z + 1.5, Bk - 3, Bk - 3);
    const ix = X + s, iz = Z + s, iw = Bk - 2 * s;
    if (b.type === 'build') { g.fillStyle = '#74777e'; g.fillRect(ix, iz, iw, iw); }
    else if (b.type === 'park') {
      g.fillStyle = '#4f8f3e'; g.fillRect(ix, iz, iw, iw);
      for (let q = 0; q < 300; q++) { g.fillStyle = Math.random() < 0.5 ? '#468436' : '#5a9a48'; g.fillRect(ix + Math.random() * iw, iz + Math.random() * iw, 3, 3); }
      g.strokeStyle = '#cdb88e'; g.lineWidth = 2.2 * k; g.beginPath(); g.moveTo(ix, iz + iw / 2); g.quadraticCurveTo(ix + iw / 2, iz + iw * 0.15, ix + iw, iz + iw / 2); g.stroke();
      g.beginPath(); g.moveTo(ix + iw / 2, iz + iw); g.quadraticCurveTo(ix + iw * 0.6, iz + iw * 0.6, ix + iw / 2, iz + iw * 0.3); g.stroke();
    } else if (b.type === 'plaza') {
      g.fillStyle = '#cdb994'; g.fillRect(ix, iz, iw, iw);
      g.strokeStyle = '#b7a37c'; g.lineWidth = 1.5; for (let q = 0; q < iw; q += 3 * k) { g.beginPath(); g.moveTo(ix + q, iz); g.lineTo(ix + q, iz + iw); g.moveTo(ix, iz + q); g.lineTo(ix + iw, iz + q); g.stroke(); }
    } else {
      g.fillStyle = '#44474e'; g.fillRect(ix, iz, iw, iw);
      g.strokeStyle = '#e9e9e9'; g.lineWidth = 0.2 * k;
      for (let q = 0; q <= 6; q++) for (const side of [-1, 1]) {
        const lx = (b.x + 5 + q * 6) * k, lz = (b.z + BL / 2 + side * 7.5) * k;
        g.beginPath(); g.moveTo(lx, lz - 2.8 * k); g.lineTo(lx, lz + 2.8 * k); g.stroke();
      }
    }
  }
  // yo'l chiziqlari
  for (let r = 0; r <= N; r++) {
    const c0 = roadC(r) * k;
    for (let i = 0; i < N; i++) {
      const a = (i * CELL + RD) * k, b2 = ((i + 1) * CELL) * k;
      g.fillStyle = '#e6c34a';
      for (let s = a + 3 * k; s < b2 - 3 * k; s += 6 * k) { g.fillRect(s, c0 - 0.12 * k, 3 * k, 0.24 * k); g.fillRect(c0 - 0.12 * k, s, 0.24 * k, 3 * k); }
      g.fillStyle = '#e8e8e8';
      g.fillRect(a, c0 - (RD / 2 - 0.6) * k, b2 - a, 0.15 * k); g.fillRect(a, c0 + (RD / 2 - 0.75) * k, b2 - a, 0.15 * k);
      g.fillRect(c0 - (RD / 2 - 0.6) * k, a, 0.15 * k, b2 - a); g.fillRect(c0 + (RD / 2 - 0.75) * k, a, 0.15 * k, b2 - a);
    }
  }
  // piyodalar o'tish joylari
  g.fillStyle = '#e4e4e4';
  for (let j = 0; j <= N; j++) for (let i = 0; i <= N; i++) {
    const cx = roadC(i) * k, cz = roadC(j) * k, h = RD / 2 * k;
    for (let s = -RD / 2 + 0.8; s < RD / 2 - 0.8; s += 1.3) {
      g.fillRect(cx + h + 0.6 * k, cz + s * k, 3 * k, 0.65 * k); g.fillRect(cx - h - 3.6 * k, cz + s * k, 3 * k, 0.65 * k);
      g.fillRect(cx + s * k, cz + h + 0.6 * k, 0.65 * k, 3 * k); g.fillRect(cx + s * k, cz - h - 3.6 * k, 0.65 * k, 3 * k);
    }
  }
  const tex = canvasTex(c);
  const m = new T.Mesh(new T.PlaneGeometry(WORLD, WORLD), new T.MeshLambertMaterial({map: tex}));
  m.rotation.x = -Math.PI / 2; m.position.set(WORLD / 2, 0, WORLD / 2); m.receiveShadow = true; scene.add(m);
  const out = new T.Mesh(new T.PlaneGeometry(WORLD * 5, WORLD * 5), new T.MeshLambertMaterial({color: 0x3f5b36}));
  out.rotation.x = -Math.PI / 2; out.position.set(WORLD / 2, -0.05, WORLD / 2); scene.add(out);
  // mini-xarita uchun rasm
  const mm = document.createElement('canvas'); mm.width = mm.height = 512;
  mm.getContext('2d').drawImage(c, 0, 0, 512, 512);
  const mg = mm.getContext('2d'); mg.fillStyle = 'rgba(20,24,34,.55)';
  for (const b of blocks) for (const s of b.solids) mg.fillRect(s.x / WORLD * 512, s.z / WORLD * 512, s.w / WORLD * 512, s.d / WORLD * 512);
  API.mapImg = mm;
}

function buildBuildings() {
  const S = 512, a = document.createElement('canvas'), e = document.createElement('canvas');
  a.width = a.height = e.width = e.height = S;
  const g = a.getContext('2d'), h = e.getContext('2d');
  g.fillStyle = '#ffffff'; g.fillRect(0, 0, S, S); h.fillStyle = '#000'; h.fillRect(0, 0, S, S);
  for (let y = 0; y < 8; y++) for (let x = 0; x < 8; x++) {
    const X = x * 64, Y = y * 64;
    g.fillStyle = '#e4e4e4'; g.fillRect(X, Y + 56, 64, 6);
    g.fillStyle = '#34404f'; g.fillRect(X + 14, Y + 12, 36, 36);
    g.fillStyle = '#4f617a'; g.fillRect(X + 14, Y + 12, 36, 9);
    g.fillStyle = '#cfcfcf'; g.fillRect(X + 31, Y + 12, 2, 36);
    if (Math.random() < 0.38) { const l = 170 + Math.random() * 85 | 0; h.fillStyle = `rgb(${l},${l * 0.84 | 0},${l * 0.52 | 0})`; h.fillRect(X + 14, Y + 12, 36, 36); }
  }
  const map = canvasTex(a, true), emi = canvasTex(e, true);
  const P = [], Nn = [], U = [], C = [], col = new T.Color();
  function quad(p, n, uv, hex) {
    col.setHex(hex);
    for (const i of [0, 1, 2, 0, 2, 3]) { P.push(p[i][0], p[i][1], p[i][2]); Nn.push(n[0], n[1], n[2]); U.push(uv[i][0], uv[i][1]); C.push(col.r, col.g, col.b); }
  }
  const Z4 = [[0.001, 0.001], [0.001, 0.001], [0.001, 0.001], [0.001, 0.001]];
  function box(x0, y0, z0, w, hh, d, hex, roof, win) {
    const x1 = x0 + w, y1 = y0 + hh, z1 = z0 + d, u0 = win ? Math.floor(Math.random() * 8) / 8 : 0, v0 = y0 / 28;
    const uvw = len => win ? [[u0, v0], [u0 + len / 32, v0], [u0 + len / 32, v0 + hh / 28], [u0, v0 + hh / 28]] : Z4;
    quad([[x0, y0, z1], [x1, y0, z1], [x1, y1, z1], [x0, y1, z1]], [0, 0, 1], uvw(w), hex);
    quad([[x1, y0, z0], [x0, y0, z0], [x0, y1, z0], [x1, y1, z0]], [0, 0, -1], uvw(w), hex);
    quad([[x1, y0, z1], [x1, y0, z0], [x1, y1, z0], [x1, y1, z1]], [1, 0, 0], uvw(d), hex);
    quad([[x0, y0, z0], [x0, y0, z1], [x0, y1, z1], [x0, y1, z0]], [-1, 0, 0], uvw(d), hex);
    quad([[x0, y1, z1], [x1, y1, z1], [x1, y1, z0], [x0, y1, z0]], [0, 1, 0], Z4, roof);
  }
  for (const b of blocks) for (const s of b.solids) {
    const roof = shade(s.c, 0.6);
    box(s.x, 0, s.z, s.w, s.h, s.d, s.c, roof, true);
    box(s.x - 0.15, s.h, s.z - 0.15, s.w + 0.3, 0.6, s.d + 0.3, shade(s.c, 0.8), roof, false);
    let top = s.h + 0.6;
    if (s.h > 28 && Math.random() < 0.65) {
      const k = 0.22, h2 = 6 + Math.random() * 14;
      box(s.x + s.w * k, top, s.z + s.d * k, s.w * (1 - 2 * k), h2, s.d * (1 - 2 * k), s.c, roof, true);
      top += h2;
      if (Math.random() < 0.5) { box(s.x + s.w / 2 - 0.2, top, s.z + s.d / 2 - 0.2, 0.4, 7, 0.4, 0x8a8a8a, 0xff3030, false); top += 7; }
    }
    for (let n = 0; n < 2; n++) box(s.x + 1 + Math.random() * (s.w - 5), s.h + 0.6, s.z + 1 + Math.random() * (s.d - 5), 2.6, 1.4, 2, 0xa0a0a0, 0x8a8a8a, false);
    s.top = top;
    // kirish eshigi va soyabon
    box(s.x + s.w / 2 - 1.6, 0, s.z + s.d - 0.05, 3.2, 2.8, 0.15, 0x2a2f38, 0x2a2f38, false);
    box(s.x + s.w / 2 - 2.2, 3, s.z + s.d - 0.1, 4.4, 0.18, 1.4, pick([0xb03a2e, 0x1f618d, 0x117a65, 0x7d3c98]), 0x555555, false);
  }
  const geo = new T.BufferGeometry();
  geo.setAttribute('position', new T.Float32BufferAttribute(P, 3)); geo.setAttribute('normal', new T.Float32BufferAttribute(Nn, 3));
  geo.setAttribute('uv', new T.Float32BufferAttribute(U, 2)); geo.setAttribute('color', new T.Float32BufferAttribute(C, 3));
  bldMat = new T.MeshLambertMaterial({map, emissiveMap: emi, emissive: 0xffffff, emissiveIntensity: 0, vertexColors: true});
  const m = new T.Mesh(geo, bldMat); m.castShadow = m.receiveShadow = true; scene.add(m);
}

function buildProps() {
  const trees = [];
  for (const b of blocks) for (const t of b.trees) if (!t.fountain) trees.push(t);
  const tg = new T.CylinderGeometry(0.2, 0.3, 2.4, 6); tg.translate(0, 1.2, 0);
  const trunk = new T.InstancedMesh(tg, new T.MeshLambertMaterial({color: 0x6b4a2b}), trees.length);
  const crown = new T.InstancedMesh(new T.IcosahedronGeometry(2, 0), new T.MeshLambertMaterial({color: 0xffffff}), trees.length);
  const o = new T.Object3D(), c = new T.Color();
  trees.forEach((t, i) => {
    const s = 0.8 + Math.random() * 0.6;
    o.position.set(t.x, 0, t.z); o.scale.set(s, s, s); o.rotation.set(0, Math.random() * 6, 0); o.updateMatrix(); trunk.setMatrixAt(i, o.matrix);
    o.position.y = 3.3 * s; o.updateMatrix(); crown.setMatrixAt(i, o.matrix);
    crown.setColorAt(i, c.setHSL(0.27 + Math.random() * 0.08, 0.45, 0.28 + Math.random() * 0.1));
  });
  trunk.castShadow = crown.castShadow = true; scene.add(trunk, crown);
  // chiroq ustunlari
  const all = Object.values(poles).flat();
  const pg = merge([bx(0.18, 6.6, 0.18, 0, 3.3, 0, 0x50555c), bx(0.12, 0.12, 2, 0, 6.5, 1, 0x50555c), bx(0.5, 0.06, 0.5, 0, 6.6, 1.9, 0x3d4147)]);
  const pole = new T.InstancedMesh(pg, new T.MeshLambertMaterial({vertexColors: true}), all.length);
  const bg = new T.BoxGeometry(0.42, 0.14, 0.42); bg.translate(0, 6.48, 1.9);
  bulbMat = new T.MeshLambertMaterial({color: 0x666666, emissive: 0xffe2a0, emissiveIntensity: 0});
  const bulb = new T.InstancedMesh(bg, bulbMat, all.length);
  all.forEach((p, i) => { o.position.set(p.x, 0, p.z); o.scale.set(1, 1, 1); o.rotation.set(0, p.yaw, 0); o.updateMatrix(); pole.setMatrixAt(i, o.matrix); bulb.setMatrixAt(i, o.matrix); });
  pole.castShadow = true; scene.add(pole, bulb);
  // favvoralar va o'rindiqlar
  const stone = new T.MeshLambertMaterial({color: 0x9c958a}), water = new T.MeshLambertMaterial({color: 0x4fa8e0, emissive: 0x0a2a44});
  for (const b of blocks) for (const t of b.trees) if (t.fountain) {
    const base = new T.Mesh(new T.CylinderGeometry(4.4, 4.6, 0.7, 24), stone); base.position.set(t.x, 0.35, t.z); base.receiveShadow = base.castShadow = true;
    const w = new T.Mesh(new T.CylinderGeometry(3.9, 3.9, 0.1, 24), water); w.position.set(t.x, 0.68, t.z);
    const col = new T.Mesh(new T.CylinderGeometry(0.5, 0.8, 2.2, 10), stone); col.position.set(t.x, 1.6, t.z); col.castShadow = true;
    const jet = new T.Mesh(new T.CylinderGeometry(0.15, 0.6, 2.4, 10), new T.MeshLambertMaterial({color: 0xbfe6ff, transparent: true, opacity: 0.7})); jet.position.set(t.x, 3.6, t.z);
    scene.add(base, w, col, jet);
  }
}

// ── transport modellari ──
const GLASS = 0x1b2633, TIRE = 0x161616;
const VT = {
  sedan: {L: 4.4, W: 1.85, bh: 0.62, ch: 0.56, cl: 2.25, co: -0.2},
  taxi: {L: 4.4, W: 1.85, bh: 0.62, ch: 0.56, cl: 2.25, co: -0.2},
  police: {L: 4.6, W: 1.9, bh: 0.64, ch: 0.56, cl: 2.3, co: -0.2},
  suv: {L: 4.7, W: 2.0, bh: 0.88, ch: 0.74, cl: 2.8, co: -0.35},
  sport: {L: 4.5, W: 1.95, bh: 0.5, ch: 0.44, cl: 1.9, co: -0.3},
  super: {L: 4.6, W: 2.0, bh: 0.46, ch: 0.42, cl: 1.7, co: -0.2},
  van: {L: 5.2, W: 2.05, bh: 0.95, ch: 1.0, cl: 3.8, co: -0.5},
};
const carGeoCache = {};
function carGeometry(type, color) {
  const key = type + ':' + color;
  if (carGeoCache[key]) return carGeoCache[key];
  const v = VT[type], y0 = 0.32, p = [];
  p.push(bx(v.W, v.bh, v.L, 0, y0 + v.bh / 2, 0, color));
  p.push(bx(v.W * 0.9, v.ch, v.cl, 0, y0 + v.bh + v.ch / 2, v.co, GLASS));
  p.push(bx(v.W * 0.92, 0.07, v.cl * 0.86, 0, y0 + v.bh + v.ch + 0.035, v.co, color));
  p.push(bx(v.W * 0.1, v.ch * 0.95, 0.12, 0, y0 + v.bh + v.ch / 2, v.co + v.cl / 2 - 0.05, color));
  p.push(bx(v.W + 0.04, 0.22, 0.2, 0, y0 + 0.12, v.L / 2, 0x2a2a2a), bx(v.W + 0.04, 0.22, 0.2, 0, y0 + 0.12, -v.L / 2, 0x2a2a2a));
  for (const s of [-1, 1]) {
    p.push(bx(0.42, 0.15, 0.06, s * (v.W / 2 - 0.32), y0 + v.bh * 0.68, v.L / 2 + 0.02, 0xfff3c4));
    p.push(bx(0.42, 0.14, 0.06, s * (v.W / 2 - 0.32), y0 + v.bh * 0.68, -v.L / 2 - 0.02, 0xd8161b));
    for (const t of [-1, 1]) {
      p.push(cy(0.36, 0.3, s * (v.W / 2 - 0.1), 0.36, t * (v.L / 2 - 0.85), TIRE));
      p.push(cy(0.2, 0.32, s * (v.W / 2 - 0.1), 0.36, t * (v.L / 2 - 0.85), 0xa8acb2, 8));
    }
  }
  if (type === 'taxi') { p.push(bx(0.75, 0.24, 0.34, 0, y0 + v.bh + v.ch + 0.19, v.co, 0xffd400)); p.push(bx(v.W + 0.02, 0.1, v.L * 0.5, 0, y0 + v.bh * 0.5, 0, 0x111111)); }
  if (type === 'police') p.push(bx(v.W + 0.02, v.bh * 0.5, v.L * 0.42, 0, y0 + v.bh * 0.48, 0, 0x101828));
  if (type === 'sport' || type === 'super') {
    p.push(bx(v.W * 0.9, 0.06, 0.38, 0, y0 + v.bh + 0.36, -v.L / 2 + 0.25, color));
    for (const s of [-1, 1]) p.push(bx(0.06, 0.32, 0.1, s * v.W * 0.3, y0 + v.bh + 0.18, -v.L / 2 + 0.25, 0x222222));
  }
  if (type === 'super') p.push(bx(v.W + 0.02, 0.08, v.L, 0, y0 + v.bh * 0.55, 0, 0x1a1a1a));
  return (carGeoCache[key] = merge(p));
}
// ── odam modeli ──
const SKINS = [0xf1c27d, 0xe0ac69, 0xc68642, 0x8d5524, 0xffdbac];
const SHIRTS = [0xc0392b, 0x2980b9, 0x27ae60, 0x8e44ad, 0xf39c12, 0x34495e, 0xecf0f1, 0x16a085, 0xd35400, 0x7f8c8d];
const PANTS = [0x2c3e50, 0x1c1c1c, 0x4a3b2a, 0x34495e, 0x5d6d7e];
function personGeo(shirt, pants, skin, hair) {
  return merge([
    bx(0.2, 0.86, 0.24, -0.12, 0.43, 0, pants), bx(0.2, 0.86, 0.24, 0.12, 0.43, 0, pants),
    bx(0.52, 0.64, 0.3, 0, 1.18, 0, shirt), bx(0.15, 0.62, 0.17, -0.34, 1.16, 0, shirt), bx(0.15, 0.62, 0.17, 0.34, 1.16, 0, shirt),
    bx(0.3, 0.3, 0.3, 0, 1.68, 0, skin), bx(0.32, 0.1, 0.32, 0, 1.86, 0, hair), bx(0.06, 0.05, 0.02, -0.07, 1.7, 0.15, 0x222222), bx(0.06, 0.05, 0.02, 0.07, 1.7, 0.15, 0x222222),
  ]);
}

// ═════════════ OBYEKTLAR ═════════════
const vehicles = [], peds = [], police = [];
let player = null, cur = null; // cur — hozir boshqarilayotgan mashina (yoki null)
function specFor(type, own) {
  const key = type === 'van' ? 'sedan' : type === 'police' ? 'sport' : type;
  const S = CAR_STATS[key] || CAR_STATS.sedan, u = (P && P.up) || {}, vb = P && P.vip ? 1.15 : 1;
  let max = S.max * 0.1167, acc = S.acc / 30, turn = S.turn * 0.72;
  if (type === 'van') { max *= 0.85; acc *= 0.8; turn *= 0.85; }
  let cap = 1.5, re = 0.15;
  if (own) {
    max *= (1 + 0.06 * (u.engine || 0)) * vb; acc *= (1 + 0.06 * (u.engine || 0)) * vb; turn *= 1 + 0.05 * (u.handling || 0);
    cap = 2.5 * (1 + 0.2 * (u.nitro || 0)); re = (P.vip ? 0.36 : 0.22) * (1 + 0.1 * (u.nitro || 0));
  }
  return {max, acc, turn, cap, re};
}
function makeVehicle(type, color, x, z, yaw, ai) {
  const mesh = new T.Mesh(carGeometry(type, color), vehMat);
  mesh.castShadow = QUALITY > 0; mesh.position.set(x, 0, z); mesh.rotation.y = yaw; scene.add(mesh);
  const v = {type, color, mesh, x, z, yaw, vx: 0, vz: 0, ai, L: VT[type].L, W: VT[type].W, own: false, stun: 0, spec: specFor(type, false), nitro: 1.5};
  if (type === 'police') {
    const red = new T.Mesh(new T.BoxGeometry(0.5, 0.16, 0.3), new T.MeshBasicMaterial({color: 0xff2020}));
    const blue = new T.Mesh(new T.BoxGeometry(0.5, 0.16, 0.3), new T.MeshBasicMaterial({color: 0x2050ff}));
    const top = 0.32 + VT.police.bh + VT.police.ch + 0.15;
    red.position.set(-0.28, top, VT.police.co); blue.position.set(0.28, top, VT.police.co);
    mesh.add(red, blue); v.bar = [red, blue];
  }
  vehicles.push(v); return v;
}
function removeVehicle(v) {
  scene.remove(v.mesh); const i = vehicles.indexOf(v); if (i >= 0) vehicles.splice(i, 1);
  const j = police.indexOf(v); if (j >= 0) police.splice(j, 1);
}
const TTYPES = ['sedan', 'sedan', 'sedan', 'suv', 'van', 'taxi', 'sport', 'sedan', 'suv'];
const TCOL = [0xe6e6e6, 0x2b2b2b, 0xb03a2e, 0x2471a3, 0x7f8c8d, 0x16a085, 0x6c3483, 0xca6f1e, 0xd4ac0d, 0x5d6d7e, 0x1b4f72, 0xf0f0f0];
function laneOf(v) {
  return v.ax === 'x' ? {x: v.along, z: roadC(v.k) + v.dir * LANE, yaw: v.dir > 0 ? Math.PI / 2 : -Math.PI / 2}
    : {x: roadC(v.k) - v.dir * LANE, z: v.along, yaw: v.dir > 0 ? 0 : Math.PI};
}
function spawnTraffic() {
  const n = QUALITY > 0 ? 34 : 22;
  for (let i = 0; i < n; i++) {
    const type = pick(TTYPES), v = makeVehicle(type, type === 'taxi' ? 0xf2c200 : pick(TCOL), 0, 0, 0, 'traffic');
    v.ax = Math.random() < 0.5 ? 'x' : 'z'; v.k = Math.floor(Math.random() * (N + 1)); v.dir = Math.random() < 0.5 ? 1 : -1;
    v.along = rr(20, WORLD - 20); v.sp = rr(8, 13); v.cv = 0; v.lastNode = -1;
    const l = laneOf(v); v.x = l.x; v.z = l.z; v.yaw = l.yaw;
  }
}
function spawnParked() {
  for (const b of blocks) for (const s of b.spots) if (Math.random() < 0.35) {
    const type = pick(['sedan', 'suv', 'sport', 'sedan', 'van']);
    makeVehicle(type, pick(TCOL), s.x, s.z, s.yaw, 'parked');
  }
}
function pedPath(b, s) {
  const a = 1.3, L = BL - 2 * a, Pm = 4 * L, x0 = b.x + a, z0 = b.z + a;
  s = ((s % Pm) + Pm) % Pm;
  if (s < L) return [x0 + s, z0]; if (s < 2 * L) return [x0 + L, z0 + s - L];
  if (s < 3 * L) return [x0 + L - (s - 2 * L), z0 + L]; return [x0, z0 + L - (s - 3 * L)];
}
const pedGeos = [];
function spawnPeds() {
  for (let i = 0; i < 10; i++) pedGeos.push(personGeo(pick(SHIRTS), pick(PANTS), pick(SKINS), pick([0x1a1a1a, 0x3b2a1a, 0x6b4a2b, 0x222222, 0xb08d57])));
  const pm = new T.MeshLambertMaterial({vertexColors: true}), n = QUALITY > 0 ? 40 : 24;
  for (let i = 0; i < n; i++) {
    const mesh = new T.Mesh(pick(pedGeos), pm); mesh.castShadow = QUALITY > 0; scene.add(mesh);
    const b = pick(blocks), s = Math.random() * 200;
    const [x, z] = pedPath(b, s);
    peds.push({mesh, b, s, dir: Math.random() < 0.5 ? 1 : -1, sp: rr(1.1, 1.7), x, z, ox: 0, oz: 0, down: 0, flee: 0, yaw: 0, ph: Math.random() * 6});
  }
}
function makePlayer() {
  const g = new T.Group(), M = c => new T.MeshLambertMaterial({color: c});
  const shirtM = M(0x2f6fe0), pantsM = M(0x22262e), skinM = M(0xe0ac69), hairM = M(0x1d1d1d), shoeM = M(0xf0f0f0);
  const part = (w, h, d, m, x, y, z, parent) => { const s = new T.Mesh(new T.BoxGeometry(w, h, d), m); s.position.set(x, y, z); s.castShadow = true; (parent || g).add(s); return s; };
  const pivot = (x, y) => { const p = new T.Group(); p.position.set(x, y, 0); g.add(p); return p; };
  const legL = pivot(-0.12, 0.9), legR = pivot(0.12, 0.9), armL = pivot(-0.35, 1.48), armR = pivot(0.35, 1.48);
  part(0.2, 0.84, 0.24, pantsM, 0, -0.42, 0, legL); part(0.2, 0.84, 0.24, pantsM, 0, -0.42, 0, legR);
  part(0.22, 0.1, 0.32, shoeM, 0, -0.86, 0.04, legL); part(0.22, 0.1, 0.32, shoeM, 0, -0.86, 0.04, legR);
  part(0.15, 0.6, 0.17, shirtM, 0, -0.3, 0, armL); part(0.15, 0.6, 0.17, shirtM, 0, -0.3, 0, armR);
  part(0.13, 0.12, 0.14, skinM, 0, -0.66, 0, armL); part(0.13, 0.12, 0.14, skinM, 0, -0.66, 0, armR);
  part(0.54, 0.64, 0.3, shirtM, 0, 1.2, 0); part(0.3, 0.3, 0.3, skinM, 0, 1.69, 0); part(0.32, 0.1, 0.33, hairM, 0, 1.87, -0.01);
  part(0.32, 0.18, 0.06, hairM, 0, 1.78, -0.15);
  part(0.06, 0.05, 0.02, M(0x111111), -0.07, 1.71, 0.155); part(0.06, 0.05, 0.02, M(0x111111), 0.07, 1.71, 0.155);
  scene.add(g);
  return {g, legL, legR, armL, armR, shirtM, x: 0, z: 0, y: 0, vy: 0, yaw: 0, ph: 0, sp: 0};
}

// ── markerlar, tangalar, strelka ──
const spriteCache = {};
function iconSprite(txt, color) {
  const key = txt + color;
  if (!spriteCache[key]) {
    const c = document.createElement('canvas'); c.width = c.height = 128; const g = c.getContext('2d');
    g.fillStyle = color; g.beginPath(); g.arc(64, 64, 56, 0, 7); g.fill();
    g.lineWidth = 8; g.strokeStyle = '#fff'; g.stroke();
    g.font = 'bold 64px sans-serif'; g.textAlign = 'center'; g.textBaseline = 'middle'; g.fillStyle = '#fff'; g.fillText(txt, 64, 70);
    spriteCache[key] = new T.SpriteMaterial({map: canvasTex(c), depthTest: false, transparent: true});
  }
  const s = new T.Sprite(spriteCache[key]); s.scale.set(2.6, 2.6, 1); s.renderOrder = 10; return s;
}
function makeMarker(color, icon) {
  const g = new T.Group();
  const beam = new T.Mesh(new T.CylinderGeometry(2.6, 2.6, 60, 20, 1, true), new T.MeshBasicMaterial({color, transparent: true, opacity: 0.22, depthWrite: false, side: T.DoubleSide}));
  beam.position.y = 30;
  const ring = new T.Mesh(new T.RingGeometry(2.3, 3, 32), new T.MeshBasicMaterial({color, transparent: true, opacity: 0.85, side: T.DoubleSide}));
  ring.rotation.x = -Math.PI / 2; ring.position.y = 0.06;
  const s = iconSprite(icon, '#' + new T.Color(color).getHexString()); s.position.y = 4;
  g.add(beam, ring, s); g.ring = ring; g.icon = s; scene.add(g); g.visible = false; return g;
}
let giverMk = [], targetMk = null, arrow = null, coinMesh = null;
function buildMarkers() {
  for (let i = 0; i < 3; i++) giverMk.push(makeMarker(0xf5c542, '!'));
  targetMk = makeMarker(0x34c759, '➜');
  const sh = new T.Shape(); sh.moveTo(0, 0.9); sh.lineTo(0.75, -0.3); sh.lineTo(0, 0); sh.lineTo(-0.75, -0.3); sh.closePath();
  const ag = new T.ShapeGeometry(sh); ag.rotateX(Math.PI / 2);
  arrow = new T.Mesh(ag, new T.MeshBasicMaterial({color: 0x34c759, depthTest: false, transparent: true, opacity: 0.85, side: T.DoubleSide}));
  arrow.renderOrder = 11; scene.add(arrow); arrow.visible = false;
}
const COINS = 60;
function buildCoins() {
  const g = new T.CylinderGeometry(0.55, 0.55, 0.14, 16); g.rotateX(Math.PI / 2);
  coinMesh = new T.InstancedMesh(g, new T.MeshLambertMaterial({color: 0xf5c542, emissive: 0x5a3c00}), COINS);
  coinMesh.frustumCulled = false; scene.add(coinMesh); coinMesh.visible = false;
}

// ═════════════ SOZLASH ═════════════
function setup() {
  gl = document.getElementById('gl');
  renderer = new T.WebGLRenderer({canvas: gl, antialias: QUALITY > 0, powerPreference: 'high-performance'});
  renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, QUALITY > 0 ? 2 : 1));
  renderer.setSize(innerWidth, innerHeight);
  renderer.shadowMap.enabled = QUALITY > 0; renderer.shadowMap.type = T.PCFSoftShadowMap;
  maxAniso = Math.min(8, renderer.capabilities.getMaxAnisotropy());
  scene = new T.Scene(); scene.background = new T.Color(0x9fd0ff); scene.fog = new T.Fog(0x9fd0ff, 90, 320);
  camera = new T.PerspectiveCamera(62, innerWidth / innerHeight, 0.3, 800);
  hemi = new T.HemisphereLight(0xcfe6ff, 0x5a5040, 0.65); scene.add(hemi);
  sun = new T.DirectionalLight(0xfff1dc, 1); sun.castShadow = QUALITY > 0;
  sun.shadow.mapSize.set(QUALITY > 1 ? 2048 : 1024, QUALITY > 1 ? 2048 : 1024);
  Object.assign(sun.shadow.camera, {left: -45, right: 45, top: 45, bottom: -45, near: 1, far: 320}); sun.shadow.bias = -0.0006;
  scene.add(sun, sun.target);
  vehMat = new T.MeshLambertMaterial({vertexColors: true});
  buildGround(); buildBuildings(); buildProps(); buildMarkers(); buildCoins();
  spawnTraffic(); spawnParked(); spawnPeds();
  player = makePlayer(); player.g.visible = false;
  headL = new T.SpotLight(0xfff2cc, 0, 70, 0.6, 0.5, 1); scene.add(headL, headL.target);
  addEventListener('resize', () => { renderer.setSize(innerWidth, innerHeight); camera.aspect = innerWidth / innerHeight; camera.updateProjectionMatrix(); });
}

// ═════════════ KUN / TUN ═════════════
let dayT = 0.06, night = 0;
const SKY_DAY = new T.Color(0x9fd0ff), SKY_SET = new T.Color(0xff9e6b), SKY_NIGHT = new T.Color(0x0b1026), tmpC = new T.Color();
function updateDay(dt, fx, fz) {
  dayT = (dayT + dt / 300) % 1;
  const a = dayT * Math.PI * 2, h = Math.sin(a);
  const day = cl(h * 2.2 + 0.25, 0, 1); night = 1 - day;
  const dusk = Math.max(0, 1 - Math.abs(h) * 4) * (h > -0.25 ? 1 : 0);
  tmpC.copy(SKY_NIGHT).lerp(SKY_DAY, day).lerp(SKY_SET, dusk * 0.55);
  scene.background.copy(tmpC); scene.fog.color.copy(tmpC);
  sun.position.set(fx + Math.cos(a) * 90, Math.max(h, 0.15) * 120, fz + 50);
  sun.target.position.set(fx, 0, fz);
  sun.intensity = 0.1 + 0.95 * day; sun.color.setHex(dusk > 0.3 ? 0xffc9a0 : 0xfff1dc);
  hemi.intensity = 0.28 + 0.45 * day;
  bldMat.emissiveIntensity = night * 1.1; bulbMat.emissiveIntensity = night * 1.6;
}
function clockText() {
  const m = Math.floor(((dayT * 24 + 6) % 24) * 60);
  return String(Math.floor(m / 60)).padStart(2, '0') + ':' + String(m % 60).padStart(2, '0');
}

// ═════════════ FIZIKA ═════════════
function drive(v, dt, thr, steer, hand, boost) {
  const s = v.spec, fx = Math.sin(v.yaw), fz = Math.cos(v.yaw), rx = -fz, rz = fx;
  let vF = v.vx * fx + v.vz * fz, vL = v.vx * rx + v.vz * rz;
  const max = s.max * (boost ? 1.35 : 1), acc = s.acc * (boost ? 1.8 : 1);
  if (thr > 0) { if (vF < -0.5) vF += s.acc * 2.4 * thr * dt; else if (vF < max) vF = Math.min(max, vF + acc * thr * dt * (1 - 0.55 * Math.max(0, vF) / max)); }
  else if (thr < 0) { if (vF > 0.5) vF += s.acc * 2.6 * thr * dt; else vF = Math.max(-9, vF + s.acc * 0.7 * thr * dt); }
  else vF -= vF * 0.55 * dt;
  if (vF > max) vF -= (vF - max) * 1.5 * dt;
  if (hand) vF -= vF * 0.8 * dt;
  vL *= Math.exp(-(hand ? 1.4 : 9) * dt);
  v.vx = fx * vF + rx * vL; v.vz = fz * vF + rz * vL;
  const sp = Math.abs(vF);
  v.yaw -= steer * s.turn * (1 - 0.45 * Math.min(1, sp / s.max)) * (hand ? 1.5 : 1) * Math.min(1, sp / 4) * Math.sign(vF || 1) * dt;
  v.x += v.vx * dt; v.z += v.vz * dt;
  v.vF = vF;
  return carCollide(v);
}
function carCollide(v) {
  const fx = Math.sin(v.yaw), fz = Math.cos(v.yaw), off = v.L * 0.27, r = v.W * 0.55;
  let impact = 0;
  for (const sgn of [1, -1]) {
    const p = {x: v.x + fx * off * sgn, z: v.z + fz * off * sgn}, ox = p.x, oz = p.z;
    const hit = collide(p, r);
    if (hit) {
      v.x += p.x - ox; v.z += p.z - oz;
      const vn = v.vx * hit.nx + v.vz * hit.nz;
      if (vn < 0) { v.vx -= hit.nx * vn * 1.3; v.vz -= hit.nz * vn * 1.3; v.vx *= 0.85; v.vz *= 0.85; impact = Math.max(impact, -vn); }
    }
  }
  return impact;
}
function vehPush(a, b) {
  const dx = a.x - b.x, dz = a.z - b.z, d = Math.hypot(dx, dz), R = (a.L + b.L) * 0.3;
  if (d >= R || d === 0) return 0;
  const nx = dx / d, nz = dz / d, k = (R - d);
  const am = a.ai === 'traffic' ? 0 : 1, bm = b.ai === 'traffic' ? 0 : 1, tot = am + bm || 1;
  a.x += nx * k * am / tot; a.z += nz * k * am / tot; b.x -= nx * k * bm / tot; b.z -= nz * k * bm / tot;
  const rel = (a.vx - b.vx) * nx + (a.vz - b.vz) * nz;
  if (rel < 0) {
    if (am) { a.vx -= nx * rel * 0.7 * (bm ? 0.5 : 1); a.vz -= nz * rel * 0.7 * (bm ? 0.5 : 1); }
    if (bm) { b.vx += nx * rel * 0.5; b.vz += nz * rel * 0.5; }
  }
  return -rel;
}

// ═════════════ O'YIN HOLATI ═════════════
let G = null;
let camYaw = 0, camPitch = 0.32, camDrag = 0, camDist = 6, tNow = 0;
function newGiver() { const types = ['deliver', 'taxi', 'race']; return Object.assign(farPoint(player, 50, 220), {type: pick(types)}); }
function start() {
  G = {missions: 0, pickups: 0, wanted: 0, mission: null, givers: [], coins: [], bust: 0, calm: 0, crashCd: 0, time: 0, shake: 0, hitPedCd: 0};
  // o'yinchi va uning mashinasi
  const sx = roadC(4) + RD / 2 + 1.0, sz = roadC(4) + 24;
  Object.assign(player, {x: sx, z: sz, y: 0, vy: 0, yaw: Math.PI, sp: 0});
  player.shirtM.color.setHex(P.vip ? 0xd4af37 : 0x2f6fe0);
  player.g.visible = true; cur = null;
  for (const v of vehicles.filter(v => v.own)) removeVehicle(v);
  for (const v of police.slice()) removeVehicle(v);
  const type = CAR_STATS[P.car] ? P.car : 'sedan';
  const col = {sedan: 0x3a7bd5, taxi: 0xf2c200, suv: 0x2e7d4f, sport: 0xd32f2f, super: 0xd4af37}[type];
  const mine = makeVehicle(type, col, roadC(4) + RD / 2 - 1.5, sz - 2.5, Math.PI, 'parked');
  mine.own = true; mine.spec = specFor(type, true); mine.nitro = mine.spec.cap;
  for (let i = 0; i < 3; i++) G.givers.push(newGiver());
  for (let i = 0; i < COINS; i++) G.coins.push(Object.assign(roadPoint(), {ph: Math.random() * 6}));
  coinMesh.visible = true; arrow.visible = true;
  camYaw = Math.PI; camPitch = 0.3; dayT = 0.06;
  toast('🏙 Xush kelibsiz!', 'Mashinangiz yoningizda — yaqinlashib O\'TIRISH ni bosing');
  engineStart();
}
function stop() {
  engineStop();
  if (G) { for (const m of giverMk) m.visible = false; targetMk.visible = false; }
  coinMesh.visible = false; arrow.visible = false; player.g.visible = false;
  if (cur) { cur.ai = 'parked'; cur = null; }
  headL.intensity = 0;
}
function sessionCoins() { return G ? (G.missions * MISSION_COINS + G.pickups * PICKUP_COINS) * (P.vip ? 2 : 1) : 0; }
function addWanted(n, msg) {
  if (G.wanted >= 5) return;
  G.wanted = Math.min(5, G.wanted + n); G.calm = 0;
  toast('⭐'.repeat(G.wanted), msg || 'Politsiya sizni qidirmoqda!'); sfx(440, 0.12, 'square', 0.05); setTimeout(() => sfx(330, 0.18, 'square', 0.05), 130);
}
const MNAME = {deliver: '📦 Yetkazib berish', taxi: '🚕 Taksi', race: '🏁 Poyga'};
function startMission(g) {
  if ((g.type === 'taxi' || g.type === 'race') && !cur) { if (!G.needCarT || G.needCarT < tNow) { toast(MNAME[g.type], 'Buning uchun mashinaga o\'tiring'); G.needCarT = tNow + 3; } return false; }
  const me = pos(); let pts = [], total = 0, from = me, speed = 14;
  if (g.type === 'deliver') pts = [farPoint(me, 150, 300)];
  else if (g.type === 'taxi') { const a = farPoint(me, 60, 130); pts = [a, farPoint(a, 150, 270)]; }
  else { speed = 19; for (let i = 0; i < 4; i++) { const p = farPoint(from, 80, 140); pts.push(p); from = p; } }
  from = me; for (const p of pts) { total += dxz(from, p); from = p; }
  G.mission = {type: g.type, pts, idx: 0, time: total / speed + 14};
  toast(MNAME[g.type], 'Vaqt: ' + Math.round(G.mission.time) + ' soniya'); sfx(660, 0.12); sfx(880, 0.15); haptic('medium');
  return true;
}
function missionLabel(m) {
  if (m.type === 'deliver') return '📦 Posilkani manzilga yetkazing';
  if (m.type === 'taxi') return m.idx === 0 ? '🚕 Yo\'lovchini oling' : '🚕 Yo\'lovchini manzilga olib boring';
  return `🏁 Nazorat nuqtasi ${m.idx + 1}/${m.pts.length}`;
}
const pos = () => cur ? {x: cur.x, z: cur.z} : {x: player.x, z: player.z};

// ── tovush (dvigatel) ──
let eng = null;
function engineStart() {
  if (!SOUND) return;
  try {
    AC = AC || new (window.AudioContext || window.webkitAudioContext)();
    const o = AC.createOscillator(), f = AC.createBiquadFilter(), g = AC.createGain();
    o.type = 'sawtooth'; o.frequency.value = 40; f.type = 'lowpass'; f.frequency.value = 380; g.gain.value = 0;
    o.connect(f); f.connect(g); g.connect(AC.destination); o.start(); eng = {o, g};
  } catch (e) { eng = null; }
}
function engineStop() { if (eng) { try { eng.o.stop(); } catch (e) {} eng = null; } }

// ═════════════ YANGILASH ═════════════
function updateTraffic(dt) {
  const me = cur || (player.g.visible ? player : null);
  for (const v of vehicles) {
    if (v.ai !== 'traffic') continue;
    if (v.stun > 0) v.stun -= dt;
    let want = v.stun > 0 ? 0 : v.sp;
    const fx = Math.sin(v.yaw), fz = Math.cos(v.yaw);
    const ahead = o => { const dx = o.x - v.x, dz = o.z - v.z, f = dx * fx + dz * fz, l = Math.abs(dx * fz - dz * fx); return f > 0 && f < 10 && l < 2.4; };
    if (me && ahead(me)) want = 0;
    else for (const o of vehicles) if (o !== v && Math.abs(o.x - v.x) < 11 && Math.abs(o.z - v.z) < 11 && ahead(o)) { want = Math.min(want, (o.cv || 0) * 0.8); break; }
    for (const p of peds) if (!p.down && Math.abs(p.x - v.x) < 8 && Math.abs(p.z - v.z) < 8 && ahead(p)) { want = 0; break; }
    v.cv += cl(want - v.cv, -14 * dt, 5 * dt);
    const prev = v.along; v.along += v.dir * v.cv * dt;
    const lo = Math.min(prev, v.along), hi = Math.max(prev, v.along), m = Math.round((v.along - RD / 2) / CELL), node = roadC(m);
    if (m >= 0 && m <= N && node >= lo && node <= hi && m !== v.lastNode) {
      v.lastNode = m;
      if (Math.random() < 0.35) {
        const l = laneOf(v), cross = v.ax === 'x' ? l.z : l.x;
        v.ax = v.ax === 'x' ? 'z' : 'x'; v.k = m; v.along = cross; v.dir = Math.random() < 0.5 ? 1 : -1;
        v.lastNode = Math.round((v.along - RD / 2) / CELL);
      }
    }
    if (v.along < 12 || v.along > WORLD - 12) { v.dir *= -1; v.along = cl(v.along, 12, WORLD - 12); }
    const l = laneOf(v), k = 1 - Math.exp(-6 * dt);
    v.x += (l.x - v.x) * k; v.z += (l.z - v.z) * k; v.yaw += ad(l.yaw, v.yaw) * Math.min(1, dt * 5);
    v.vx = Math.sin(v.yaw) * v.cv; v.vz = Math.cos(v.yaw) * v.cv;
  }
}
function updatePeds(dt) {
  const fast = cur && Math.abs(cur.vF || 0) > 5 ? cur : null;
  for (const p of peds) {
    p.ph += dt * 7;
    if (p.down > 0) { p.down -= dt; p.mesh.rotation.set(-Math.PI / 2, p.yaw, 0, 'YXZ'); p.mesh.position.set(p.x, 0.3, p.z); continue; }
    if (fast && Math.abs(fast.x - p.x) < 9 && Math.abs(fast.z - p.z) < 9) {
      const dx = p.x - fast.x, dz = p.z - fast.z, d = Math.hypot(dx, dz) || 1;
      if ((fast.vx * dx + fast.vz * dz) / d > 3 && p.flee <= 0) {
        const side = Math.sign(dx * Math.cos(fast.yaw) - dz * Math.sin(fast.yaw)) || 1;
        p.ox += Math.cos(fast.yaw) * side * 0.1; p.oz += -Math.sin(fast.yaw) * side * 0.1; p.flee = 1.2; p.jx = Math.cos(fast.yaw) * side * 5; p.jz = -Math.sin(fast.yaw) * side * 5;
      }
      if (d < 1.6 && G && G.hitPedCd <= 0) {
        p.down = 4; G.hitPedCd = 1.5; sfx(120, 0.2, 'triangle', 0.06); haptic('heavy'); addWanted(1, 'Piyodani urib yubordingiz!');
        continue;
      }
    }
    let speed = p.sp;
    if (p.flee > 0) { p.flee -= dt; p.ox += p.jx * dt; p.oz += p.jz * dt; p.jx *= 0.93; p.jz *= 0.93; speed *= 2.4; }
    else { p.ox *= 1 - dt * 0.8; p.oz *= 1 - dt * 0.8; }
    const ps = p.s; p.s += p.dir * speed * dt;
    const [ax, az] = pedPath(p.b, ps), [bx2, bz2] = pedPath(p.b, p.s);
    p.x = bx2 + p.ox; p.z = bz2 + p.oz;
    const e = {x: p.x, z: p.z}; if (collide(e, 0.35)) { p.ox += e.x - p.x; p.oz += e.z - p.z; p.x = e.x; p.z = e.z; }
    if (Math.abs(bx2 - ax) + Math.abs(bz2 - az) > 1e-4) p.yaw = Math.atan2(bx2 - ax, bz2 - az);
    p.mesh.rotation.set(0, p.yaw, 0); p.mesh.position.set(p.x, Math.abs(Math.sin(p.ph)) * 0.06, p.z);
  }
}
function updatePlayerFoot(dt) {
  const m = getMove(), fx = Math.sin(camYaw), fz = Math.cos(camYaw);
  let dx = fx * -m.y + -fz * m.x, dz = fz * -m.y + fx * m.x;
  const mag = Math.min(1, Math.hypot(dx, dz));
  const run = input.a ? 1.85 : 1, sp = 4.2 * (P.vip ? 1.1 : 1) * run * mag;
  if (mag > 0.1) { const l = Math.hypot(dx, dz); dx /= l; dz /= l; player.yaw += ad(Math.atan2(dx, dz), player.yaw) * Math.min(1, dt * 12); }
  const tvx = mag > 0.1 ? dx * sp : 0, tvz = mag > 0.1 ? dz * sp : 0;
  player.vx = (player.vx || 0) + (tvx - (player.vx || 0)) * Math.min(1, dt * 10);
  player.vz = (player.vz || 0) + (tvz - (player.vz || 0)) * Math.min(1, dt * 10);
  player.x += player.vx * dt; player.z += player.vz * dt;
  if (input.bHit && player.y <= 0.001) { player.vy = 5.5; sfx(500, 0.06, 'triangle', 0.03); }
  player.vy -= 15 * dt; player.y = Math.max(0, player.y + player.vy * dt); if (player.y === 0) player.vy = 0;
  collide(player, 0.38);
  for (const v of vehicles) {
    if (Math.abs(v.x - player.x) > 5 || Math.abs(v.z - player.z) > 5) continue;
    const e = {x: player.x, z: player.z}, fx2 = Math.sin(v.yaw), fz2 = Math.cos(v.yaw);
    for (const t of [-0.3, 0, 0.3]) circleOut(e, v.x + fx2 * v.L * t, v.z + fz2 * v.L * t, v.W * 0.55, 0.38);
    player.x = e.x; player.z = e.z;
  }
  for (const p of peds) if (!p.down && Math.abs(p.x - player.x) < 1 && Math.abs(p.z - player.z) < 1) { const e = {x: player.x, z: player.z}; circleOut(e, p.x, p.z, 0.35, 0.38); player.x = e.x; player.z = e.z; }
  player.sp = Math.hypot(player.vx, player.vz);
  player.ph += player.sp * dt * 2.3;
  const sw = Math.sin(player.ph) * Math.min(1, player.sp / 3) * 0.75;
  player.legL.rotation.x = sw; player.legR.rotation.x = -sw; player.armL.rotation.x = -sw * 0.9; player.armR.rotation.x = sw * 0.9;
  if (player.y > 0) { player.armL.rotation.x = player.armR.rotation.x = -2.6; }
  player.g.position.set(player.x, player.y, player.z); player.g.rotation.y = player.yaw;
}
function nearestCar() {
  let best = null, bd = 4.2;
  for (const v of vehicles) { if (v.ai === 'police') continue; const d = dxz(v, player); if (d < bd) { bd = d; best = v; } }
  return best;
}
function enterCar(v) {
  if (v.ai === 'traffic') {
    addWanted(1, 'Mashina o\'g\'irlandi!');
    const p = peds.find(q => !q.down && dxz(q, v) > 40) || peds[0];
    p.ox = v.x - pedPath(p.b, p.s)[0] + 2; p.oz = v.z - pedPath(p.b, p.s)[1]; p.flee = 2; p.jx = rr(-6, 6); p.jz = rr(-6, 6);
  }
  v.ai = 'player'; v.vF = 0; cur = v; player.g.visible = false;
  camDrag = 0; sfx(200, 0.15, 'triangle', 0.05); haptic('medium');
}
function exitCar() {
  const v = cur, rx = -Math.cos(v.yaw), rz = Math.sin(v.yaw);
  player.x = v.x + rx * (v.W / 2 + 0.8); player.z = v.z + rz * (v.W / 2 + 0.8); player.y = 0; player.vx = player.vz = 0;
  collide(player, 0.38);
  player.yaw = v.yaw; player.g.visible = true;
  v.ai = 'parked'; cur = null; camYaw = v.yaw;
  sfx(260, 0.1, 'triangle', 0.04);
}
function updateCar(dt) {
  const v = cur, m = getMove();
  const thr = -m.y, steer = m.x;
  const boost = input.a && v.nitro > 0.05 && (v.vF || 0) > 2;
  if (boost) v.nitro = Math.max(0, v.nitro - dt); else if (!input.a) v.nitro = Math.min(v.spec.cap, v.nitro + v.spec.re * dt);
  const imp = drive(v, dt, Math.abs(thr) < 0.12 ? 0 : thr, Math.abs(steer) < 0.1 ? 0 : steer, input.b, boost);
  if (imp > 7) { G.shake = Math.min(0.6, imp / 30); sfx(90, 0.18, 'sawtooth', 0.07); haptic(imp > 14 ? 'heavy' : 'medium'); }
  for (const o of vehicles) {
    if (o === v || Math.abs(o.x - v.x) > 7 || Math.abs(o.z - v.z) > 7) continue;
    const rel = vehPush(v, o);
    if (rel > 1) {
      if (o.ai === 'traffic') o.stun = 1.5;
      if (rel > 7 && G.crashCd <= 0) {
        G.crashCd = 1.2; G.shake = 0.5; sfx(80, 0.25, 'sawtooth', 0.08); haptic('heavy');
        if ((o.ai === 'traffic' || o.ai === 'police') && Math.abs(v.vF || 0) > 7) addWanted(1, o.ai === 'police' ? 'Politsiyaga urildingiz!' : 'Avariya! Politsiya kelyapti');
      }
    }
  }
  v.mesh.position.set(v.x, 0, v.z); v.mesh.rotation.set(0, v.yaw, 0);
  // kuzov qiyshayishi
  const lat = (v.vx * -Math.cos(v.yaw) + v.vz * Math.sin(v.yaw));
  v.mesh.rotation.z = cl(lat * 0.012, -0.06, 0.06);
  // fara
  headL.intensity = night * 2.2;
  headL.position.set(v.x + Math.sin(v.yaw) * 2, 1.0, v.z + Math.cos(v.yaw) * 2);
  headL.target.position.set(v.x + Math.sin(v.yaw) * 20, 0, v.z + Math.cos(v.yaw) * 20);
  if (eng) { eng.o.frequency.value = 38 + Math.abs(v.vF || 0) * 3.2 + (boost ? 30 : 0); eng.g.gain.value = 0.035; }
}
function updateParked(dt) {
  for (const v of vehicles) {
    if (v.ai !== 'parked') continue;
    if (Math.abs(v.vx) + Math.abs(v.vz) < 0.01) continue;
    v.vx *= Math.exp(-2.5 * dt); v.vz *= Math.exp(-2.5 * dt);
    v.x += v.vx * dt; v.z += v.vz * dt; carCollide(v);
    v.mesh.position.set(v.x, 0, v.z); v.mesh.rotation.y = v.yaw;
  }
}
function updatePolice(dt) {
  const me = pos();
  while (police.length < G.wanted) {
    const p = farPoint(me, 120, 190), v = makeVehicle('police', 0xf4f6f8, p.x, p.z, Math.atan2(me.x - p.x, me.z - p.z), 'police');
    v.spec = specFor('police', false); v.node = null; v.slow = 0; v.rev = 0; police.push(v);
  }
  let near = false;
  for (const v of police) {
    v.spec.max = (cur ? cur.spec.max : 30) * (0.88 + 0.035 * G.wanted);
    const d = dxz(v, me); if (d < 80) near = true;
    let tx = me.x, tz = me.z;
    if (d > 45) {
      if (!v.node || Math.hypot(roadC(v.node.i) - v.x, roadC(v.node.j) - v.z) < 9) {
        const ci = cl(Math.round((v.x - RD / 2) / CELL), 0, N), cj = cl(Math.round((v.z - RD / 2) / CELL), 0, N);
        const here = Math.hypot(roadC(ci) - v.x, roadC(cj) - v.z);
        if (here > 9) v.node = {i: ci, j: cj};
        else {
          let best = null, bd = 1e9;
          for (const [a, b] of [[1, 0], [-1, 0], [0, 1], [0, -1]]) { const ni = ci + a, nj = cj + b; if (ni < 0 || nj < 0 || ni > N || nj > N) continue; const dd = Math.hypot(roadC(ni) - me.x, roadC(nj) - me.z); if (dd < bd) { bd = dd; best = {i: ni, j: nj}; } }
          v.node = best;
        }
      }
      tx = roadC(v.node.i); tz = roadC(v.node.j);
    } else v.node = null;
    const diff = ad(Math.atan2(tx - v.x, tz - v.z), v.yaw);
    let thr = 1, steer = cl(-diff * 2, -1, 1);
    if (Math.abs(diff) > 1.2 && Math.abs(v.vF || 0) > 12) thr = -0.6;
    if (!cur && d < 9) thr = (v.vF || 0) > 1 ? -1 : 0;
    if (v.rev > 0) { v.rev -= dt; thr = -1; steer = -steer; }
    else if (Math.abs(v.vF || 0) < 1 && thr > 0) { v.slow += dt; if (v.slow > 1.3) { v.rev = 1; v.slow = 0; } } else v.slow = 0;
    drive(v, dt, thr, steer, false, false);
    for (const o of vehicles) if (o !== v && o !== cur && Math.abs(o.x - v.x) < 6 && Math.abs(o.z - v.z) < 6) vehPush(v, o);
    v.mesh.position.set(v.x, 0, v.z); v.mesh.rotation.set(0, v.yaw, 0);
    const f = (tNow * 8 | 0) % 2; v.bar[0].visible = !!f; v.bar[1].visible = !f;
  }
  if (G.wanted > 0) {
    const close = police.some(v => dxz(v, me) < 6.5);
    const slow = cur ? Math.abs(cur.vF || 0) < 3 : true;
    if (close && slow) G.bust += dt; else G.bust = Math.max(0, G.bust - dt * 0.6);
    if (G.bust > 2.3) {
      const lost = Math.floor(G.pickups * 0.3);
      G.pickups -= lost; G.wanted = 0; G.bust = 0;
      for (const v of police.slice()) removeVehicle(v);
      if (cur) { cur.vx = cur.vz = 0; }
      toast('🚓 Qo\'lga tushdingiz!', lost ? `−${lost * PICKUP_COINS * (P.vip ? 2 : 1)} tanga jarima` : 'Bu safar ogohlantirish'); sfx(200, 0.4, 'triangle', 0.08); haptic('heavy');
    }
    if (!near) { G.calm += dt; if (G.calm > 10) { G.calm = 0; G.wanted--; const v = police[police.length - 1]; if (v) removeVehicle(v); if (!G.wanted) toast('😎 Qochib qutuldingiz!', ''); } } else G.calm = 0;
  }
}
const _o = new T.Object3D();
function updateWorldObjs(dt) {
  const me = pos(), ry = cur ? 1.0 : 1.2;
  // tangalar
  for (let i = 0; i < G.coins.length; i++) {
    const k = G.coins[i];
    if (Math.abs(k.x - me.x) < (cur ? 2.6 : 1.6) && Math.abs(k.z - me.z) < (cur ? 2.6 : 1.6)) {
      G.pickups++; sfx(1200, 0.06, 'square', 0.03); Object.assign(k, roadPoint());
    }
    _o.position.set(k.x, ry + Math.sin(tNow * 3 + k.ph) * 0.2, k.z); _o.rotation.set(0, tNow * 3 + k.ph, 0); _o.updateMatrix();
    coinMesh.setMatrixAt(i, _o.matrix);
  }
  coinMesh.instanceMatrix.needsUpdate = true;
  // topshiriqlar
  const ms = G.mission;
  if (!ms) {
    for (let i = 0; i < 3; i++) {
      const g = G.givers[i], mk = giverMk[i];
      mk.visible = true; mk.position.set(g.x, 0, g.z); mk.ring.scale.setScalar(1 + Math.sin(tNow * 4) * 0.08);
      if (dxz(g, me) < 3.5 && startMission(g)) { G.givers[i] = newGiver(); break; }
    }
    targetMk.visible = false;
  } else {
    for (const mk of giverMk) mk.visible = false;
    ms.time -= dt;
    const p = ms.pts[ms.idx];
    targetMk.visible = true; targetMk.position.set(p.x, 0, p.z); targetMk.ring.scale.setScalar(1 + Math.sin(tNow * 5) * 0.1);
    if (dxz(p, me) < 4.5) {
      ms.idx++; sfx(990, 0.1); haptic('light');
      if (ms.type === 'taxi' && ms.idx === 1) toast('🙋 Yo\'lovchi o\'tirdi', 'Manzilga olib boring');
      if (ms.idx >= ms.pts.length) {
        G.missions++; G.mission = null; sfx(1320, 0.25, 'triangle', 0.06); haptic('heavy');
        toast('✅ Bajarildi!', `+${MISSION_COINS * (P.vip ? 2 : 1)} tanga`);
      } else if (ms.type === 'race') ms.time += 4;
    } else if (ms.time <= 0) { G.mission = null; toast('⌛ Vaqt tugadi', 'Topshiriq bajarilmadi'); sfx(160, 0.3, 'triangle', 0.06); }
  }
  // yo'nalish strelkasi
  const tgt = G.mission ? G.mission.pts[G.mission.idx] : G.givers.reduce((a, b) => dxz(a, me) < dxz(b, me) ? a : b);
  arrow.material.color.setHex(G.mission ? 0x34c759 : 0xf5c542);
  const aa = Math.atan2(tgt.x - me.x, tgt.z - me.z), ar = (cur ? 4.2 : 1.6) + Math.sin(tNow * 5) * 0.15;
  arrow.position.set(me.x + Math.sin(aa) * ar, 0.12, me.z + Math.cos(aa) * ar);
  arrow.rotation.y = aa; arrow.scale.setScalar(cur ? 1.3 : 0.75);
  arrow.visible = dxz(tgt, me) > 8;
  return tgt;
}

// ═════════════ KAMERA ═════════════
function updateCamera(dt, menu) {
  if (menu) {
    const a = tNow * 0.04;
    camera.position.set(WORLD / 2 + Math.cos(a) * 190, 85, WORLD / 2 + Math.sin(a) * 190);
    camera.lookAt(WORLD / 2, 0, WORLD / 2); camera.fov = 55; camera.updateProjectionMatrix();
    return;
  }
  const d = input.dragX || 0, e = input.dragY || 0;
  if (d || e) { camYaw -= d * 0.0065; camPitch = cl(camPitch + e * 0.004, 0.02, 1.1); camDrag = 1.6; input.dragX = input.dragY = 0; }
  camDrag -= dt;
  let tx, ty, tz, dist, fov = 62;
  if (cur) {
    const sp = Math.abs(cur.vF || 0);
    if (camDrag <= 0) {
      const back = (cur.vF || 0) < -2 ? Math.PI : 0;
      camYaw += ad(cur.yaw + back, camYaw) * Math.min(1, dt * 3.2);
      camPitch += (0.26 - camPitch) * Math.min(1, dt * 2);
    }
    dist = 8.8 + sp * 0.07; tx = cur.x; ty = 1.6; tz = cur.z; fov = 62 + Math.min(18, sp * 0.4) + (input.a && cur.nitro > 0.05 ? 6 : 0);
  } else {
    if (camDrag <= 0 && player.sp > 1 && getMove().y < -0.5) camYaw += ad(player.yaw, camYaw) * Math.min(1, dt * 1.5);
    dist = 5.2; tx = player.x; ty = 1.55 + player.y; tz = player.z;
  }
  camDist += (dist - camDist) * Math.min(1, dt * 4);
  const fx = Math.sin(camYaw), fz = Math.cos(camYaw), ch = Math.cos(camPitch), shh = Math.sin(camPitch);
  let k = 1;
  for (let i = 1; i <= 10; i++) {
    const t = i / 10, x = tx - fx * camDist * ch * t, z = tz - fz * camDist * ch * t, y = ty + camDist * shh * t + 0.6 * t;
    if (solidAt(x, z, y)) { k = Math.max(0.15, (i - 1) / 10); break; }
  }
  const sh = G && G.shake ? G.shake : 0; if (G) G.shake = Math.max(0, G.shake - dt * 2);
  camera.position.set(tx - fx * camDist * ch * k + rr(-sh, sh), ty + (camDist * shh + 0.6) * k + rr(-sh, sh), tz - fz * camDist * ch * k);
  camera.lookAt(tx, ty + 0.4, tz);
  if (Math.abs(camera.fov - fov) > 0.2) { camera.fov += (fov - camera.fov) * Math.min(1, dt * 3); camera.updateProjectionMatrix(); }
}

// ═════════════ HUD ═════════════
let mmCtx = null;
function drawMinimap(tgt) {
  const c = $('mm'); if (!c) return;
  mmCtx = mmCtx || c.getContext('2d');
  const S = c.width, g = mmCtx, me = pos(), R = 110, k = 512 / WORLD, sc = S / (2 * R * k);
  g.save(); g.clearRect(0, 0, S, S);
  g.beginPath(); g.arc(S / 2, S / 2, S / 2, 0, 7); g.clip();
  g.fillStyle = '#20262f'; g.fillRect(0, 0, S, S);
  const rot = -Math.PI / 2 - Math.atan2(Math.cos(camYaw), Math.sin(camYaw));
  g.translate(S / 2, S / 2); g.rotate(rot); g.scale(sc, sc); g.translate(-me.x * k, -me.z * k);
  g.drawImage(API.mapImg, 0, 0);
  const dot = (x, z, col, r) => { g.fillStyle = col; g.beginPath(); g.arc(x * k, z * k, r / sc, 0, 7); g.fill(); };
  if (G.mission) { const p = G.mission.pts[G.mission.idx]; dot(p.x, p.z, '#34c759', 5); } else for (const q of G.givers) dot(q.x, q.z, '#f5c542', 4.5);
  for (const v of police) dot(v.x, v.z, (tNow * 6 | 0) % 2 ? '#ff3b30' : '#3b6bff', 4);
  for (const v of vehicles) if (v.own && v !== cur) dot(v.x, v.z, '#4fc3ff', 3.5);
  g.restore();
  // o'yinchi strelkasi
  const yaw = cur ? cur.yaw : player.yaw, a = rot + Math.atan2(Math.cos(yaw), Math.sin(yaw));
  g.save(); g.translate(S / 2, S / 2); g.rotate(a);
  g.fillStyle = '#fff'; g.beginPath(); g.moveTo(8, 0); g.lineTo(-6, -5); g.lineTo(-3, 0); g.lineTo(-6, 5); g.closePath(); g.fill(); g.restore();
  g.strokeStyle = '#ffffff66'; g.lineWidth = 2; g.beginPath(); g.arc(S / 2, S / 2, S / 2 - 1, 0, 7); g.stroke();
  // shimol yo'nalishi chetga
  if (tgt && dxz(tgt, me) > R) {
    const ta = rot + Math.atan2(tgt.z - me.z, tgt.x - me.x);
    g.fillStyle = G.mission ? '#34c759' : '#f5c542'; g.beginPath(); g.arc(S / 2 + Math.cos(ta) * (S / 2 - 7), S / 2 + Math.sin(ta) * (S / 2 - 7), 5, 0, 7); g.fill();
  }
}
let lastCtx = '';
function hud(tgt) {
  $('h-coins').textContent = fmt(sessionCoins());
  $('stars').innerHTML = '<b>' + '★'.repeat(G.wanted) + '</b>' + '★'.repeat(5 - G.wanted);
  $('h-speed').textContent = cur ? Math.round(Math.abs(cur.vF || 0) * 3.6) + ' km/soat' : '🚶 piyoda';
  $('h-clock').textContent = (night > 0.5 ? '🌙 ' : '☀️ ') + clockText();
  const mEl = $('mission');
  if (G.mission) mEl.innerHTML = esc(missionLabel(G.mission)) + `<small>⏱ ${Math.ceil(G.mission.time)} s · ${Math.round(dxz(pos(), G.mission.pts[G.mission.idx]))} m</small>`;
  else mEl.innerHTML = 'Sariq <b style="color:#f5c542">!</b> belgisiga boring<small>Topshiriq oling</small>';
  // tugmalar
  const near = !cur ? nearestCar() : null;
  const ctxKey = cur ? 'car' : near ? 'near' : 'foot';
  if (ctxKey !== lastCtx) {
    lastCtx = ctxKey;
    $('bE').classList.toggle('hide', ctxKey === 'foot');
    $('bE').querySelector('span').textContent = cur ? '🚶' : '🚗'; $('lE').textContent = cur ? 'TUSHISH' : 'O\'TIRISH';
    $('bA').querySelector('span').textContent = cur ? '🔥' : '🏃'; $('lA').textContent = cur ? 'NITRO' : 'YUGURISH';
    $('bB').querySelector('span').textContent = cur ? '🛑' : '⤴️'; $('lB').textContent = cur ? 'TORMOZ' : 'SAKRASH';
  }
  const nb = $('nitro');
  if (cur) { nb.classList.remove('hide'); nb.firstElementChild.style.width = (cur.nitro / cur.spec.cap * 100) + '%'; } else nb.classList.add('hide');
  $('bust').classList.toggle('hide', G.bust < 0.25);
  drawMinimap(tgt);
}

// ═════════════ API ═════════════
const API = {
  ok: false, mapImg: null,
  init() {
    try { setup(); API.ok = true; } catch (e) { console.error('3D init', e); API.ok = false; }
    return API.ok;
  },
  start() { lastCtx = ''; start(); },
  stop,
  stats() { return {missions: G ? G.missions : 0, pickups: G ? G.pickups : 0}; },
  coins: sessionCoins,
  quality() { return QUALITY; },
  setQuality(q) { try { localStorage.setItem('sa_q', String(q)); } catch (e) {} location.reload(); },
  update(dt) {
    tNow += dt; G.time += dt; G.crashCd -= dt; G.hitPedCd -= dt;
    if (input.eHit) {
      if (cur) { if (Math.abs(cur.vF || 0) < 6) exitCar(); else toast('Avval sekinlang', ''); }
      else { const v = nearestCar(); if (v) enterCar(v); }
    }
    if (cur) updateCar(dt); else { updatePlayerFoot(dt); if (eng) eng.g.gain.value = 0; headL.intensity = 0; }
    updateTraffic(dt); updatePeds(dt); updateParked(dt); updatePolice(dt);
    const tgt = updateWorldObjs(dt);
    const me = pos(); updateDay(dt, me.x, me.z);
    updateCamera(dt, false);
    hud(tgt);
  },
  render(menu, dt) {
    if (!API.ok) return;
    if (menu) {
      tNow += dt; updateTraffic(dt); updatePeds(dt); updateDay(dt * 0.5, WORLD / 2, WORLD / 2); updateCamera(dt, true);
    }
    renderer.render(scene, camera);
  },
};
API._dbg = {day: t => { dayT = t; }, G: () => G, cur: () => cur, player: () => player, police: () => police};
window.City3D = API;
})();
