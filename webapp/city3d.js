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
// Toshkent uslubidagi maxsus joylar (barcha mijozlarda bir xil joyda)
const SPECIAL = {dome: [3, 3], tower: [5, 2], fuel: [2, 5], paint: [5, 5]};
const ZONES = {};
for (const [type, [si, sj]] of Object.entries(SPECIAL)) {
  const b = blocks[sj * N + si], cx = b.x + BL / 2, cz = b.z + BL / 2;
  b.type = type; b.solids = []; b.trees = []; b.spots = [];
  if (type === 'dome') {
    b.solids.push({x: cx - 12, z: cz - 12, w: 24, d: 20, h: 12, top: 27, custom: true});
    b.trees.push({x: cx - 15, z: cz + 11, r: 1.5}, {x: cx + 15, z: cz + 11, r: 1.5});
    for (const [a, c] of [[6, 6], [BL - 6, 6], [6, BL - 6], [BL - 6, BL - 6]]) b.trees.push({x: b.x + a, z: b.z + c, r: 0.5});
  } else if (type === 'tower') {
    b.trees.push({x: cx, z: cz, r: 3.4, tower: true});
    for (let k = 0; k < 8; k++) { const a = k / 8 * Math.PI * 2; b.trees.push({x: cx + Math.cos(a) * 14, z: cz + Math.sin(a) * 14, r: 0.5}); }
  } else if (type === 'fuel') {
    b.solids.push({x: b.x + 9, z: b.z + 5, w: 28, d: 8, h: 4.5, top: 5, custom: true});
    for (const [a, c] of [[-10, -3], [10, -3], [-10, 5], [10, 5]]) b.trees.push({x: cx + a, z: cz + 4 + c, r: 0.35, pillar: true});
    b.trees.push({x: cx - 4, z: cz + 5, r: 0.6, pump: true}, {x: cx + 4, z: cz + 5, r: 0.6, pump: true});
    ZONES.fuel = {x: cx - 13, z: cz - 2, w: 26, d: 14};
  } else {
    b.solids.push({x: b.x + 7, z: b.z + 4, w: 32, d: 13, h: 8, top: 8.5, custom: true});
    ZONES.paint = {x: cx - 7, z: cz + 2, w: 14, d: 12};
  }
}
const inZone = (z, p) => z && p.x > z.x && p.x < z.x + z.w && p.z > z.z && p.z < z.z + z.d;
const DISTRICTS = [['Olmazor', 'Shayxontohur', 'Yunusobod'], ['Chilonzor', 'Markaz', 'Mirzo Ulug\'bek'], ['Sergeli', 'Yakkasaroy', 'Mirobod']];
function districtAt(x, z) {
  const gi = cl(Math.floor((x / WORLD) * 3), 0, 2), gj = cl(Math.floor((z / WORLD) * 3), 0, 2);
  return DISTRICTS[gj][gi];
}
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
let signMat = null;
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
    else if (b.type === 'dome') {
      g.fillStyle = '#d8c7a0'; g.fillRect(ix, iz, iw, iw);
      g.strokeStyle = '#c4b088'; g.lineWidth = 1.5; for (let q = 0; q < iw; q += 2 * k) { g.beginPath(); g.moveTo(ix + q, iz); g.lineTo(ix + q, iz + iw); g.moveTo(ix, iz + q); g.lineTo(ix + iw, iz + q); g.stroke(); }
      g.fillStyle = '#2a8fa3'; g.fillRect(X + Bk / 2 - 2 * k, Z + Bk / 2 + 8 * k, 4 * k, Bk / 2 - 8 * k);
    } else if (b.type === 'tower') {
      g.fillStyle = '#4f8f3e'; g.fillRect(ix, iz, iw, iw);
      g.fillStyle = '#cdb88e'; g.beginPath(); g.arc(X + Bk / 2, Z + Bk / 2, 9 * k, 0, 7); g.fill();
    } else if (b.type === 'fuel' || b.type === 'paint') {
      g.fillStyle = '#4a4d54'; g.fillRect(ix, iz, iw, iw);
      g.strokeStyle = b.type === 'fuel' ? '#f5c542' : '#3fa9f5'; g.lineWidth = 0.25 * k; g.strokeRect(ix + 4 * k, iz + 14 * k, iw - 8 * k, iw - 18 * k);
    }
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
  const SP = [], SU = [];
  const signQuad = (x0, x1, y0, y1, z, cell) => {
    const col = cell % 2, row = Math.floor(cell / 2), u0 = col / 2, u1 = u0 + 0.5, v1 = 1 - row / 8, v0 = v1 - 1 / 8;
    for (const [px, py, u, v] of [[x0, y0, u0, v0], [x1, y0, u1, v0], [x1, y1, u1, v1], [x0, y0, u0, v0], [x1, y1, u1, v1], [x0, y1, u0, v1]]) { SP.push(px, py, z); SU.push(u, v); }
  };
  for (const b of blocks) for (const s of b.solids) {
    if (s.custom) continue;
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
    const sw2 = Math.min(2.6, s.w / 2 - 0.5), mx = s.x + s.w / 2;
    signQuad(mx - sw2, mx + sw2, 3.35, 3.35 + sw2 * 0.4, s.z + s.d + 0.06, Math.floor(srnd() * 16));
  }
  const geo = new T.BufferGeometry();
  geo.setAttribute('position', new T.Float32BufferAttribute(P, 3)); geo.setAttribute('normal', new T.Float32BufferAttribute(Nn, 3));
  geo.setAttribute('uv', new T.Float32BufferAttribute(U, 2)); geo.setAttribute('color', new T.Float32BufferAttribute(C, 3));
  bldMat = new T.MeshLambertMaterial({map, emissiveMap: emi, emissive: 0xffffff, emissiveIntensity: 0, vertexColors: true});
  const m = new T.Mesh(geo, bldMat); m.castShadow = m.receiveShadow = true; scene.add(m);
  // peshtaxtalar (bitta tekstura atlasida 16 ta nom)
  const SIGNS = ['CHOYXONA', 'NON', 'SOMSA', 'DORIXONA', 'MARKET', 'OSHXONA', 'KAFE', 'SARTAROSH', 'GULLAR', 'TELEFONLAR', 'KIYIMLAR', 'MEVALAR', 'KITOBLAR', 'SHIRINLIKLAR', 'BANK', 'POYABZAL'];
  const SBG = ['#1f6f8b', '#b03a2e', '#117a65', '#7d3c98', '#c0392b', '#1a5276', '#d35400', '#2c3e50'];
  const sc = document.createElement('canvas'); sc.width = 1024; sc.height = 1024; const sg = sc.getContext('2d');
  SIGNS.forEach((t, i) => {
    const X = (i % 2) * 512, Y = Math.floor(i / 2) * 128;
    sg.fillStyle = SBG[i % SBG.length]; sg.fillRect(X, Y, 512, 128);
    sg.strokeStyle = '#ffffff55'; sg.lineWidth = 8; sg.strokeRect(X + 6, Y + 6, 500, 116);
    sg.fillStyle = '#fff'; sg.font = 'bold 64px sans-serif'; sg.textAlign = 'center'; sg.textBaseline = 'middle'; sg.fillText(t, X + 256, Y + 68, 470);
  });
  const st = canvasTex(sc);
  const sgeo = new T.BufferGeometry();
  sgeo.setAttribute('position', new T.Float32BufferAttribute(SP, 3)); sgeo.setAttribute('uv', new T.Float32BufferAttribute(SU, 2)); sgeo.computeVertexNormals();
  signMat = new T.MeshLambertMaterial({map: st, emissiveMap: st, emissive: 0xffffff, emissiveIntensity: 0});
  scene.add(new T.Mesh(sgeo, signMat));
}

// ── diqqatga sazovor joylar ──
function textPlane(text, w, h, bg, fg) {
  const c = document.createElement('canvas'); c.width = 512; c.height = Math.round(512 * h / w); const g = c.getContext('2d');
  g.fillStyle = bg; g.fillRect(0, 0, c.width, c.height);
  g.fillStyle = fg; g.font = `bold ${Math.round(c.height * 0.55)}px sans-serif`; g.textAlign = 'center'; g.textBaseline = 'middle'; g.fillText(text, 256, c.height * 0.55, 480);
  const t = canvasTex(c);
  return new T.Mesh(new T.PlaneGeometry(w, h), new T.MeshLambertMaterial({map: t, emissiveMap: t, emissive: 0xffffff, emissiveIntensity: 0.2}));
}
let towerLamp = null;
function buildLandmarks() {
  const M = (c, e) => new T.MeshLambertMaterial(Object.assign({color: c}, e || {}));
  const add = (geo, mat, x, y, z, shadow) => { const m = new T.Mesh(geo, mat); m.position.set(x, y, z); if (shadow !== false) { m.castShadow = true; m.receiveShadow = true; } scene.add(m); return m; };
  const sand = M(0xead8b0), tile = M(0x2aa7b8), deep = M(0x1d5f8a), gold = M(0xe0b84a);
  for (const b of blocks) {
    const cx = b.x + BL / 2, cz = b.z + BL / 2;
    if (b.type === 'dome') {
      // madrasa: asos, peshtoq, baraban, ko'k gumbaz, ikki minora
      add(new T.BoxGeometry(24, 12, 20), sand, cx, 6, cz - 2);
      add(new T.BoxGeometry(12, 17, 2.4), sand, cx, 8.5, cz + 8.6);
      add(new T.BoxGeometry(7, 11, 0.6), deep, cx, 6.2, cz + 9.9, false);
      add(new T.CylinderGeometry(3.5, 3.5, 0.6, 20, 1, false, 0, Math.PI), deep, cx, 11.7, cz + 9.9, false).rotation.x = Math.PI / 2;
      add(new T.BoxGeometry(12.4, 1.2, 2.6), tile, cx, 16.4, cz + 8.6);
      add(new T.CylinderGeometry(7, 7.4, 4, 24), tile, cx, 14, cz - 2);
      const dome = add(new T.SphereGeometry(7.2, 28, 14, 0, Math.PI * 2, 0, Math.PI / 2), tile, cx, 16, cz - 2); dome.scale.y = 1.25;
      add(new T.CylinderGeometry(0.25, 0.25, 2.4, 6), gold, cx, 26, cz - 2);
      for (const t of b.trees) if (t.r === 1.5) {
        add(new T.CylinderGeometry(1.2, 1.6, 24, 14), sand, t.x, 12, t.z);
        add(new T.CylinderGeometry(1.75, 1.75, 1, 14), tile, t.x, 18, t.z);
        add(new T.CylinderGeometry(1.9, 1.3, 1.6, 14), sand, t.x, 24.8, t.z);
        add(new T.SphereGeometry(1.3, 14, 8, 0, Math.PI * 2, 0, Math.PI / 2), tile, t.x, 25.6, t.z);
      }
    } else if (b.type === 'tower') {
      // teleminora
      add(new T.CylinderGeometry(1.2, 3.2, 90, 16), M(0xb8bcc4), cx, 45, cz);
      for (let k = 0; k < 3; k++) { const a = k / 3 * Math.PI * 2; const leg = add(new T.CylinderGeometry(0.5, 0.9, 40, 8), M(0x9aa0aa), cx + Math.cos(a) * 5, 18, cz + Math.sin(a) * 5); leg.rotation.set(Math.sin(a) * 0.12, 0, -Math.cos(a) * 0.12); }
      add(new T.SphereGeometry(6, 20, 12), M(0x8fa5b8), cx, 72, cz).scale.y = 0.7;
      add(new T.CylinderGeometry(6.6, 6.6, 1.2, 20), M(0x2b3442, {emissive: 0xffd27a, emissiveIntensity: 0}), cx, 72, cz);
      for (let k = 0; k < 6; k++) add(new T.CylinderGeometry(0.55 - k * 0.06, 0.6 - k * 0.06, 6, 8), M(k % 2 ? 0xffffff : 0xd32f2f), cx, 93 + k * 6, cz);
      towerLamp = add(new T.SphereGeometry(0.7, 8, 6), new T.MeshBasicMaterial({color: 0xff2020}), cx, 129.5, cz, false);
    } else if (b.type === 'fuel') {
      add(new T.BoxGeometry(28, 4.5, 8), M(0xf2f2f2), cx, 2.25, b.z + 9);
      add(new T.BoxGeometry(28.2, 1, 8.2), M(0xd32f2f), cx, 4.2, b.z + 9);
      const sg = textPlane("⛽ YOQILG'I", 10, 1.6, '#d32f2f', '#fff'); sg.position.set(cx, 3.3, b.z + 13.06); scene.add(sg);
      add(new T.BoxGeometry(26, 0.8, 14), M(0xffffff), cx, 5.8, cz + 5);
      add(new T.BoxGeometry(26.2, 0.5, 14.2), M(0xd32f2f), cx, 5.3, cz + 5);
      for (const t of b.trees) {
        if (t.pillar) add(new T.BoxGeometry(0.6, 5.4, 0.6), M(0xdddddd), t.x, 2.7, t.z);
        if (t.pump) { add(new T.BoxGeometry(1, 1.8, 0.7), M(0x2b3442), t.x, 0.9, t.z); add(new T.BoxGeometry(0.8, 0.5, 0.05), M(0x111111, {emissive: 0x4fc3ff, emissiveIntensity: 0.6}), t.x, 1.4, t.z + 0.38, false); }
      }
    } else if (b.type === 'paint') {
      add(new T.BoxGeometry(32, 8, 13), M(0x5b6b8c), cx, 4, b.z + 10.5);
      add(new T.BoxGeometry(10, 6, 0.3), M(0x1b1f27), cx, 3, b.z + 17.1, false);
      const sg = textPlane("🎨 BO'YASH", 12, 2, '#1f6fe0', '#fff'); sg.position.set(cx, 7, b.z + 17.07); scene.add(sg);
      for (let k = 0; k < 5; k++) add(new T.BoxGeometry(2, 0.3, 0.2), M([0xe53935, 0xf5c542, 0x43a047, 0x1e88e5, 0x8e24aa][k]), cx - 13 + k * 2.4, 6.2, b.z + 17.1, false);
    }
  }
}

// ── svetoforlar (hamma chorrahada bir xil fazada) ──
const lampMats = {x: {}, z: {}};
function lightState(axis, t) {
  const p = t % 16;
  if (axis === 'x') return p < 7 ? 'g' : p < 8.5 ? 'y' : 'r';
  return p >= 8.5 && p < 15 ? 'g' : p >= 15 ? 'y' : 'r';
}
function buildLights() {
  const heads = [];
  for (const [key, list] of Object.entries(poles)) list.forEach((p, idx) => heads.push({p, axis: idx === 0 ? 'x' : 'z'}));
  const housing = new T.InstancedMesh(new T.BoxGeometry(0.42, 1.25, 0.42), new T.MeshLambertMaterial({color: 0x22262c}), heads.length);
  const o = new T.Object3D();
  heads.forEach((h, i) => { o.position.set(h.p.x, 4.4, h.p.z); o.rotation.set(0, 0, 0); o.updateMatrix(); housing.setMatrixAt(i, o.matrix); });
  scene.add(housing);
  const COL = {r: 0xff2a2a, y: 0xffc21a, g: 0x2aff6a}, OFF = {r: 0x3a1010, y: 0x3a3010, g: 0x103a18};
  for (const axis of ['x', 'z']) {
    const hs = heads.filter(h => h.axis === axis);
    ['r', 'y', 'g'].forEach((c, ci) => {
      const g = axis === 'x' ? merge([bx(0.06, 0.26, 0.26, 0.22, 0, 0, 0xffffff), bx(0.06, 0.26, 0.26, -0.22, 0, 0, 0xffffff)])
                             : merge([bx(0.26, 0.26, 0.06, 0, 0, 0.22, 0xffffff), bx(0.26, 0.26, 0.06, 0, 0, -0.22, 0xffffff)]);
      const mat = new T.MeshBasicMaterial({color: OFF[c]}); mat.userData = {on: COL[c], off: OFF[c]};
      const im = new T.InstancedMesh(g, mat, hs.length);
      hs.forEach((h, i) => { o.position.set(h.p.x, 4.8 - ci * 0.38, h.p.z); o.updateMatrix(); im.setMatrixAt(i, o.matrix); });
      scene.add(im); lampMats[axis][c] = mat;
    });
  }
}
function updateLights(t) {
  for (const axis of ['x', 'z']) {
    const st = lightState(axis, t);
    for (const c of ['r', 'y', 'g']) { const m = lampMats[axis][c]; if (m) m.color.setHex(c === st ? m.userData.on : m.userData.off); }
  }
}

function buildProps() {
  const trees = [];
  for (const b of blocks) for (const t of b.trees) if (!t.fountain && !t.tower && !t.pillar && !t.pump && t.r === 0.5) trees.push(t);
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
  bus: {L: 10.5, W: 2.5, bh: 2.5, ch: 0, cl: 0, co: 0, bus: true},
};
const carGeoCache = {};
function carGeometry(type, color) {
  const key = type + ':' + color;
  if (carGeoCache[key]) return carGeoCache[key];
  const v = VT[type], y0 = 0.32, p = [];
  if (v.bus) {
    p.push(bx(v.W, v.bh, v.L, 0, y0 + 0.2 + v.bh / 2, 0, color));
    p.push(bx(v.W + 0.04, 0.85, v.L - 1.6, 0, y0 + 0.2 + v.bh * 0.66, -0.4, GLASS));
    p.push(bx(v.W * 0.92, 1.3, 0.06, 0, y0 + 0.2 + v.bh * 0.62, v.L / 2 + 0.01, GLASS));
    p.push(bx(v.W + 0.02, 0.25, v.L, 0, y0 + 0.35, 0, 0x2a2a2a));
    p.push(bx(v.W * 0.7, 0.3, 0.06, 0, y0 + 0.2 + v.bh - 0.25, v.L / 2 + 0.02, 0xffb300));
    p.push(bx(v.W * 0.8, 0.25, v.L * 0.6, 0, y0 + 0.2 + v.bh + 0.12, -0.5, 0xdddddd));
    for (const sx of [-1, 1]) {
      p.push(bx(0.42, 0.2, 0.06, sx * (v.W / 2 - 0.35), y0 + 0.75, v.L / 2 + 0.02, 0xfff3c4), bx(0.42, 0.25, 0.06, sx * (v.W / 2 - 0.35), y0 + 0.8, -v.L / 2 - 0.02, 0xd8161b));
      for (const t of [-1, 1]) { p.push(cy(0.5, 0.36, sx * (v.W / 2 - 0.15), 0.5, t * (v.L / 2 - 1.8), TIRE)); p.push(cy(0.26, 0.38, sx * (v.W / 2 - 0.15), 0.5, t * (v.L / 2 - 1.8), 0xa8acb2, 8)); }
    }
    return (carGeoCache[key] = merge(p));
  }
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
  const key = type === 'van' || type === 'bus' ? 'sedan' : type === 'police' ? 'sport' : type;
  const S = CAR_STATS[key] || CAR_STATS.sedan, u = (P && P.up) || {}, vb = P && P.vip ? 1.15 : 1;
  let max = S.max * 0.1167, acc = S.acc / 30, turn = S.turn * 0.72;
  if (type === 'van') { max *= 0.85; acc *= 0.8; turn *= 0.85; }
  if (type === 'bus') { max *= 0.72; acc *= 0.5; turn *= 0.62; }
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
  for (let i = 0; i < 4; i++) {
    const v = makeVehicle('bus', [0x1e88e5, 0x43a047, 0xe53935, 0xfb8c00][i], 0, 0, 0, 'traffic');
    v.ax = i % 2 ? 'x' : 'z'; v.k = 1 + i * 2; v.dir = i < 2 ? 1 : -1; v.along = rr(40, WORLD - 40); v.sp = rr(7, 8.5); v.cv = 0; v.lastNode = -1;
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
// Personaj ranglari (server game.py dagi LOOK bilan bir xil tartibda)
const SKIN_C = [0xffdbac, 0xe0ac69, 0xc68642, 0x8d5524, 0x5c3a1e];
const HAIR_C = [0x1a1a1a, 0x3b2a1a, 0x7a4a24, 0xc8a165, 0x9e9e9e, 0xb5482a, 0x2f7cf6, 0xe14d9b];
const TOP_C = [0xc0392b, 0x2f6fe0, 0x27ae60, 0x8e44ad, 0xf39c12, 0x34495e, 0xecf0f1, 0x16a085, 0x1b1b1b, 0xe91e63, 0xd4af37];
const PANT_C = [0x22262e, 0x2c3e50, 0x4a3b2a, 0x5d6d7e, 0x1f3a5f, 0x7a7a7a];
const LOOK0 = {skin: 1, hair: 0, hc: 0, top: 0, tc: 1, pc: 0, acc: 0};
const matCache = {};
const LM = c => matCache[c] || (matCache[c] = new T.MeshLambertMaterial({color: c}));
function makeCharacter(look) {
  look = Object.assign({}, LOOK0, look || {});
  const g = new T.Group();
  const gold = look.top === 3;
  const topC = gold ? 0xd4af37 : TOP_C[look.tc] || TOP_C[1], skin = SKIN_C[look.skin] || SKIN_C[1], hair = HAIR_C[look.hc] || HAIR_C[0];
  const darker = shade(topC, 0.72);
  const part = (w, h, d, c, x, y, z, parent) => { const m = new T.Mesh(new T.BoxGeometry(w, h, d), LM(c)); m.position.set(x, y, z); m.castShadow = true; (parent || g).add(m); return m; };
  const pivot = (x, y) => { const p = new T.Group(); p.position.set(x, y, 0); g.add(p); return p; };
  const legL = pivot(-0.12, 0.9), legR = pivot(0.12, 0.9), armL = pivot(-0.35, 1.48), armR = pivot(0.35, 1.48);
  const pants = PANT_C[look.pc] || PANT_C[0];
  for (const L of [legL, legR]) { part(0.2, 0.84, 0.24, pants, 0, -0.42, 0, L); part(0.22, 0.1, 0.32, 0xf0f0f0, 0, -0.86, 0.04, L); }
  for (const A of [armL, armR]) {
    if (look.top === 0) { part(0.16, 0.26, 0.18, topC, 0, -0.13, 0, A); part(0.13, 0.36, 0.15, skin, 0, -0.44, 0, A); }
    else { part(0.16, 0.62, 0.18, look.top === 1 ? darker : topC, 0, -0.31, 0, A); part(0.13, 0.12, 0.14, skin, 0, -0.67, 0, A); }
  }
  part(0.54, 0.64, 0.3, topC, 0, 1.2, 0);
  if (look.top === 1) { part(0.14, 0.62, 0.02, 0xeeeeee, 0, 1.2, 0.155); part(0.56, 0.08, 0.32, darker, 0, 1.5, 0); }
  if (look.top === 2) { part(0.4, 0.3, 0.12, darker, 0, 1.52, -0.2); part(0.3, 0.14, 0.02, darker, 0, 1.06, 0.155); }
  if (gold) { part(0.12, 0.6, 0.02, 0x111111, 0, 1.2, 0.155); part(0.04, 0.4, 0.025, 0xb03030, 0, 1.25, 0.16); }
  part(0.3, 0.3, 0.3, skin, 0, 1.69, 0);
  part(0.06, 0.05, 0.02, 0x111111, -0.07, 1.71, 0.155); part(0.06, 0.05, 0.02, 0x111111, 0.07, 1.71, 0.155);
  const hs = look.hair;
  if (hs === 0) { part(0.32, 0.1, 0.33, hair, 0, 1.87, -0.01); part(0.32, 0.18, 0.06, hair, 0, 1.78, -0.15); }
  else if (hs === 1) { part(0.33, 0.1, 0.34, hair, 0, 1.87, -0.01); part(0.34, 0.5, 0.08, hair, 0, 1.62, -0.16); part(0.06, 0.32, 0.3, hair, -0.17, 1.72, -0.02); part(0.06, 0.32, 0.3, hair, 0.17, 1.72, -0.02); }
  else if (hs === 2) { part(0.34, 0.14, 0.34, 0xc0392b, 0, 1.89, 0); part(0.3, 0.04, 0.18, 0xc0392b, 0, 1.83, 0.24); }
  else if (hs === 4) { part(0.08, 0.2, 0.34, hair, 0, 1.94, -0.01); }
  else if (hs === 5) { part(0.38, 0.18, 0.38, hair, 0, 1.9, -0.02); part(0.38, 0.22, 0.1, hair, 0, 1.76, -0.16); }
  if (look.acc === 1 || look.acc === 2) {
    const c = look.acc === 2 ? 0x0a0a0a : 0x333333;
    part(0.11, 0.07, 0.02, c, -0.07, 1.71, 0.165); part(0.11, 0.07, 0.02, c, 0.07, 1.71, 0.165); part(0.32, 0.02, 0.02, c, 0, 1.73, 0.165);
  }
  if (look.acc === 3) { part(0.3, 0.08, 0.3, 0xffcc33, 0, 1.97 + (hs === 4 || hs === 5 ? 0.06 : 0), 0); for (const x of [-0.11, 0, 0.11]) part(0.05, 0.1, 0.05, 0xffcc33, x, 2.05 + (hs === 4 || hs === 5 ? 0.06 : 0), 0.13); }
  if (look.acc === 4) { part(0.36, 0.04, 0.04, 0xffcc33, 0, 1.5, 0.16); part(0.08, 0.08, 0.03, 0xffcc33, 0, 1.42, 0.17); }
  return {g, legL, legR, armL, armR};
}
function animChar(c, sp, ph, air) {
  const sw = Math.sin(ph) * Math.min(1, sp / 3) * 0.75;
  c.legL.rotation.x = sw; c.legR.rotation.x = -sw; c.armL.rotation.x = -sw * 0.9; c.armR.rotation.x = sw * 0.9;
  if (air) c.armL.rotation.x = c.armR.rotation.x = -2.6;
}
function makePlayer(look) {
  const ch = makeCharacter(look); scene.add(ch.g);
  return Object.assign(ch, {x: 0, z: 0, y: 0, vy: 0, yaw: 0, ph: 0, sp: 0});
}
function labelSprite(text, vip, bubble) {
  const c = document.createElement('canvas'); c.width = 512; c.height = 96; const g = c.getContext('2d');
  g.font = 'bold 44px sans-serif'; const w = Math.min(500, g.measureText(text).width + 40);
  g.fillStyle = bubble ? 'rgba(255,255,255,.95)' : 'rgba(0,0,0,.55)';
  g.beginPath(); g.roundRect ? g.roundRect(256 - w / 2, 10, w, 72, 22) : g.rect(256 - w / 2, 10, w, 72); g.fill();
  g.fillStyle = bubble ? '#111' : vip ? '#ffd54a' : '#fff'; g.textAlign = 'center'; g.textBaseline = 'middle'; g.fillText(text, 256, 48, 480);
  const s = new T.Sprite(new T.SpriteMaterial({map: canvasTex(c), transparent: true, depthWrite: false}));
  s.scale.set(3.2, 0.6, 1); s.renderOrder = 12; return s;
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
const PAINTS = [0x3a7bd5, 0xd32f2f, 0x2e7d4f, 0xf2c200, 0x161616, 0xf4f4f4, 0x8e24aa, 0xff6f00, 0x00acc1, 0xe91e63, 0x6d4c41, 0x546e7a, 0xd4af37, 0xcfd8dc];
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
  buildGround(); buildBuildings(); buildLandmarks(); buildLights(); buildProps(); buildMarkers(); buildCoins();
  spawnTraffic(); spawnParked(); spawnPeds();
  player = makePlayer(LOOK0); player.g.visible = false;
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
  bldMat.emissiveIntensity = night * 1.1; bulbMat.emissiveIntensity = night * 1.6; signMat.emissiveIntensity = 0.15 + night * 0.9;
  if (towerLamp) towerLamp.visible = ((tNow * 1.2) | 0) % 2 === 0;
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
  const fx = Math.sin(v.yaw), fz = Math.cos(v.yaw), r = v.W * 0.55;
  let impact = 0;
  for (const off of v.L > 6 ? [v.L * 0.36, 0, -v.L * 0.36] : [v.L * 0.27, -v.L * 0.27]) {
    const p = {x: v.x + fx * off, z: v.z + fz * off}, ox = p.x, oz = p.z;
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
  const st = {x: sx, z: sz, y: 0, vy: 0, yaw: Math.PI, sp: 0};
  scene.remove(player.g); player = Object.assign(makePlayer(P.look), st);
  player.g.visible = true; cur = null;
  for (const v of vehicles.filter(v => v.own)) removeVehicle(v);
  for (const v of police.slice()) removeVehicle(v);
  const type = CAR_STATS[P.car] ? P.car : 'sedan';
  const pi = P.paint && P.paint[type];
  const col = (pi != null && PAINTS[pi] != null) ? PAINTS[pi] : {sedan: 0x3a7bd5, taxi: 0xf2c200, suv: 0x2e7d4f, sport: 0xd32f2f, super: 0xd4af37}[type];
  const mine = makeVehicle(type, col, roadC(4) + RD / 2 - 1.5, sz - 2.5, Math.PI, 'parked');
  mine.own = true; mine.spec = specFor(type, true); mine.nitro = mine.spec.cap;
  for (let i = 0; i < 3; i++) G.givers.push(newGiver());
  for (let i = 0; i < COINS; i++) G.coins.push(Object.assign(roadPoint(), {ph: Math.random() * 6}));
  coinMesh.visible = true; arrow.visible = true;
  camYaw = Math.PI; camPitch = 0.3; dayT = 0.06;
  toast('🏙 Xush kelibsiz!', 'Mashinangiz yoningizda — yaqinlashib O\'TIRISH ni bosing');
  engineStart(); netStart();
}
function stop() {
  engineStop(); netStop();
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
function engineStop() {
  if (eng) { try { eng.o.stop(); } catch (e) {} eng = null; }
  if (siren) { try { siren.o.stop(); siren.lfo.stop(); } catch (e) {} siren = null; }
  if (radio) { radio.out.gain.value = 0; radio.paused = true; }
}

// ── sirena, radio, signal ──
function actx() { if (!SOUND) return null; try { AC = AC || new (window.AudioContext || window.webkitAudioContext)(); return AC; } catch (e) { return null; } }
let siren = null;
function updateSiren() {
  const ac = actx(), me = pos();
  let d = 1e9; for (const v of police) d = Math.min(d, dxz(v, me));
  const want = G && G.wanted > 0 && d < 160;
  if (want && ac && !siren) {
    const o = ac.createOscillator(), lfo = ac.createOscillator(), lg = ac.createGain(), g = ac.createGain();
    o.type = 'triangle'; o.frequency.value = 780; lfo.frequency.value = 0.55; lg.gain.value = 230;
    lfo.connect(lg); lg.connect(o.frequency); o.connect(g); g.connect(ac.destination); g.gain.value = 0;
    o.start(); lfo.start(); siren = {o, lfo, g};
  }
  if (siren) {
    if (!want) { try { siren.o.stop(); siren.lfo.stop(); } catch (e) {} siren = null; return; }
    siren.g.gain.value = 0.045 * Math.max(0, 1 - d / 160);
  }
}
const STATIONS = [
  {name: 'Radio o\'chiq'},
  {name: '📻 Shahar FM', bpm: 120, scale: [57, 60, 62, 64, 67, 69, 72, 74], roots: [45, 41, 43, 40], lead: 'square'},
  {name: '📻 Chill FM', bpm: 84, scale: [60, 62, 64, 67, 69, 72, 74, 76], roots: [48, 45, 41, 43], lead: 'triangle'},
  {name: '📻 Bazm FM', bpm: 132, scale: [62, 63, 66, 67, 69, 70, 74, 75], roots: [50, 50, 48, 46], lead: 'sawtooth'},
];
let station = 0, radio = null;
try { station = +(localStorage.getItem('sa_radio') || 1) % STATIONS.length; } catch (e) {}
const mtof = m => 440 * Math.pow(2, (m - 69) / 12);
let noiseBuf = null;
function noise(ac) {
  if (!noiseBuf) { noiseBuf = ac.createBuffer(1, ac.sampleRate * 0.5, ac.sampleRate); const d = noiseBuf.getChannelData(0); for (let i = 0; i < d.length; i++) d[i] = Math.random() * 2 - 1; }
  const s = ac.createBufferSource(); s.buffer = noiseBuf; return s;
}
function note(ac, out, type, f, t, dur, vol, cutoff) {
  const o = ac.createOscillator(), g = ac.createGain(); o.type = type; o.frequency.setValueAtTime(f, t);
  g.gain.setValueAtTime(0.0001, t); g.gain.exponentialRampToValueAtTime(vol, t + 0.01); g.gain.exponentialRampToValueAtTime(0.0001, t + dur);
  if (cutoff) { const fl = ac.createBiquadFilter(); fl.type = 'lowpass'; fl.frequency.value = cutoff; o.connect(fl); fl.connect(g); } else o.connect(g);
  g.connect(out); o.start(t); o.stop(t + dur + 0.02);
}
function drum(ac, out, kind, t) {
  if (kind === 'k') { const o = ac.createOscillator(), g = ac.createGain(); o.frequency.setValueAtTime(130, t); o.frequency.exponentialRampToValueAtTime(40, t + 0.12); g.gain.setValueAtTime(0.9, t); g.gain.exponentialRampToValueAtTime(0.0001, t + 0.22); o.connect(g); g.connect(out); o.start(t); o.stop(t + 0.25); return; }
  const n = noise(ac), f = ac.createBiquadFilter(), g = ac.createGain();
  f.type = kind === 'h' ? 'highpass' : 'bandpass'; f.frequency.value = kind === 'h' ? 7000 : 1800;
  const dur = kind === 'h' ? 0.04 : 0.14; g.gain.setValueAtTime(kind === 'h' ? 0.25 : 0.5, t); g.gain.exponentialRampToValueAtTime(0.0001, t + dur);
  n.connect(f); f.connect(g); g.connect(out); n.start(t); n.stop(t + dur + 0.02);
}
let melSeed = 1;
const mrnd = () => { melSeed = (melSeed * 16807) % 2147483647; return melSeed / 2147483647; };
function radioTick(on) {
  const ac = actx();
  if (!ac || !on || !station) { if (radio) { radio.out.gain.value = 0; radio.paused = true; } return; }
  const S = STATIONS[station];
  if (!radio || radio.st !== station) {
    if (radio) radio.out.disconnect();
    const out = ac.createGain(); out.gain.value = 0.05; out.connect(ac.destination);
    radio = {st: station, out, next: ac.currentTime + 0.1, step: 0, mel: []};
    melSeed = station * 7919 + 13;
    for (let b = 0; b < 4; b++) for (let i = 0; i < 16; i++) radio.mel.push(mrnd() < (station === 2 ? 0.3 : 0.55) ? S.scale[Math.floor(mrnd() * S.scale.length)] : 0);
  }
  if (radio.paused) { radio.paused = false; radio.next = ac.currentTime + 0.05; }
  radio.out.gain.value = 0.05;
  const sp = 60 / S.bpm / 4;
  while (radio.next < ac.currentTime + 0.3) {
    const t = radio.next, i = radio.step % 16, bar = Math.floor(radio.step / 16) % 4, root = S.roots[bar];
    if (station === 2) {
      if (i === 0) for (const iv of [0, 4, 7, 11]) note(ac, radio.out, 'triangle', mtof(root + 12 + iv), t, sp * 15, 0.08, 1200);
      if (i === 0 || i === 10) drum(ac, radio.out, 'k', t);
      if (i === 8) drum(ac, radio.out, 's', t);
      if (i % 4 === 2) drum(ac, radio.out, 'h', t);
    } else {
      if (i % 4 === 0) drum(ac, radio.out, 'k', t);
      if (i === 4 || i === 12) drum(ac, radio.out, 's', t);
      if (i % 2 === 1) drum(ac, radio.out, 'h', t);
      if (i % 2 === 0) note(ac, radio.out, 'sawtooth', mtof(root - 12 + (i % 8 === 6 ? 7 : 0)), t, sp * 1.6, 0.12, 500);
    }
    const m = radio.mel[(radio.step) % radio.mel.length];
    if (m) note(ac, radio.out, S.lead, mtof(m), t, sp * (station === 2 ? 3 : 1.4), station === 2 ? 0.06 : 0.05, 2600);
    radio.next += sp; radio.step++;
  }
}
function honk() {
  const ac = actx();
  if (ac) { const t = ac.currentTime; note(ac, ac.destination, 'square', 392, t, 0.4, 0.05, 1500); note(ac, ac.destination, 'square', 494, t, 0.4, 0.04, 1500); }
  const me = pos();
  for (const p of peds) if (!p.down && dxz(p, me) < 14 && p.flee <= 0) { p.flee = 0.8; const a = Math.atan2(p.x - me.x, p.z - me.z); p.jx = Math.sin(a) * 3; p.jz = Math.cos(a) * 3; }
}

// ═════════════ YANGILASH ═════════════
function updateTraffic(dt) {
  const me = cur || (player.g.visible ? player : null);
  for (const v of vehicles) {
    if (v.ai !== 'traffic') continue;
    if (v.stun > 0) v.stun -= dt;
    let want = v.stun > 0 ? 0 : v.sp;
    const fx = Math.sin(v.yaw), fz = Math.cos(v.yaw);
    const reach = v.L / 2 + 7;
    const ahead = o => { const dx = o.x - v.x, dz = o.z - v.z, f = dx * fx + dz * fz, l = Math.abs(dx * fz - dz * fx); return f > 0 && f < reach && l < 2.4; };
    const mA = v.dir > 0 ? Math.ceil((v.along - RD / 2) / CELL) : Math.floor((v.along - RD / 2) / CELL);
    if (mA >= 0 && mA <= N && lightState(v.ax, tNow) !== 'g') {
      const dStop = (roadC(mA) - v.along) * v.dir - RD / 2 - v.L / 2 - 0.6;
      if (dStop > -0.5 && dStop < 9) want = Math.min(want, Math.max(0, dStop * 1.4));
    }
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
  animChar(player, player.sp, player.ph, player.y > 0);
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
  if (G.race && tNow < G.race.startAt) { v.vx = v.vz = 0; v.vF = 0; v.mesh.position.set(v.x, 0, v.z); headL.intensity = night * 2.2; return; }
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
  // yoqilg'i shoxobchasi va bo'yash ustaxonasi
  if (inZone(ZONES.fuel, v)) {
    if (!G.inFuel) { G.inFuel = true; v.nitro = v.spec.cap; toast('⛽ Nitro to\'ldirildi!', 'Yoqilg\'i shoxobchasi'); sfx(520, 0.1, 'triangle', 0.05); setTimeout(() => sfx(780, 0.15, 'triangle', 0.05), 120); }
  } else G.inFuel = false;
  if (inZone(ZONES.paint, v)) {
    if (!G.inPaint && Math.abs(v.vF || 0) < 4) {
      G.inPaint = true;
      if (v.own) { v.vx = v.vz = 0; if (window.onPaintShop) window.onPaintShop(v.type); }
      else toast('🎨 Bo\'yash ustaxonasi', 'Faqat o\'z mashinangizni bo\'yatish mumkin');
    }
  } else G.inPaint = false;
  for (const r of remotes.values()) {
    if (!r.carT || Math.abs(r.x - v.x) > 7 || Math.abs(r.z - v.z) > 7) continue;
    const rel = vehPush(v, {x: r.x, z: r.z, L: 4.4, W: 1.9, ai: 'traffic', vx: 0, vz: 0});
    if (rel > 6 && G.crashCd <= 0) { G.crashCd = 1; G.shake = 0.4; sfx(80, 0.2, 'sawtooth', 0.07); haptic('heavy'); }
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
  // onlayn poyga
  if (G.race) {
    for (const mk of giverMk) mk.visible = false;
    const rc = G.race, p = rc.pts[Math.min(rc.idx, rc.pts.length - 1)];
    targetMk.visible = true; targetMk.position.set(p[0], 0, p[1]); targetMk.ring.scale.setScalar(1 + Math.sin(tNow * 6) * 0.12);
    const t = {x: p[0], z: p[1]};
    arrow.material.color.setHex(0xb388ff);
    const aa = Math.atan2(t.x - me.x, t.z - me.z), ar = (cur ? 4.2 : 1.6) + Math.sin(tNow * 5) * 0.15;
    arrow.position.set(me.x + Math.sin(aa) * ar, 0.12, me.z + Math.cos(aa) * ar); arrow.rotation.y = aa; arrow.visible = true;
    const left = rc.startAt - tNow, cEl = $('count');
    if (left > 0) { cEl.classList.remove('hide'); const n = Math.ceil(left); if (n !== rc.lastN) { rc.lastN = n; cEl.textContent = n; sfx(440, 0.12, 'square', 0.05); } }
    else if (!rc.go) { rc.go = true; cEl.textContent = 'GO!'; sfx(880, 0.3, 'square', 0.06); haptic('heavy'); setTimeout(() => cEl.classList.add('hide'), 700); }
    return t;
  }
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
  if (G.race) { const p = G.race.pts[Math.min(G.race.idx, G.race.pts.length - 1)]; dot(p[0], p[1], '#b388ff', 6); }
  else if (G.mission) { const p = G.mission.pts[G.mission.idx]; dot(p.x, p.z, '#34c759', 5); } else for (const q of G.givers) dot(q.x, q.z, '#f5c542', 4.5);
  for (const v of police) dot(v.x, v.z, (tNow * 6 | 0) % 2 ? '#ff3b30' : '#3b6bff', 4);
  for (const v of vehicles) if (v.own && v !== cur) dot(v.x, v.z, '#4fc3ff', 3.5);
  g.font = `${14 / sc}px sans-serif`; g.textAlign = 'center'; g.textBaseline = 'middle';
  for (const [type, [si, sj]] of Object.entries(SPECIAL)) {
    const b = blocks[sj * N + si];
    g.save(); g.translate((b.x + BL / 2) * k, (b.z + BL / 2) * k); g.rotate(-rot);
    g.fillText({dome: '🕌', tower: '📡', fuel: '⛽', paint: '🎨'}[type], 0, 0); g.restore();
  }
  g.restore();
  // o'yinchi strelkasi
  const yaw = cur ? cur.yaw : player.yaw, a = rot + Math.atan2(Math.cos(yaw), Math.sin(yaw));
  g.save(); g.translate(S / 2, S / 2); g.rotate(a);
  g.fillStyle = '#fff'; g.beginPath(); g.moveTo(8, 0); g.lineTo(-6, -5); g.lineTo(-3, 0); g.lineTo(-6, 5); g.closePath(); g.fill(); g.restore();
  g.strokeStyle = '#ffffff66'; g.lineWidth = 2; g.beginPath(); g.arc(S / 2, S / 2, S / 2 - 1, 0, 7); g.stroke();
  // shimol yo'nalishi chetga
  if (tgt && dxz(tgt, me) > R) {
    const ta = rot + Math.atan2(tgt.z - me.z, tgt.x - me.x);
    g.fillStyle = G.race ? '#b388ff' : G.mission ? '#34c759' : '#f5c542'; g.beginPath(); g.arc(S / 2 + Math.cos(ta) * (S / 2 - 7), S / 2 + Math.sin(ta) * (S / 2 - 7), 5, 0, 7); g.fill();
  }
}
let lastCtx = '';
function hud(tgt) {
  $('h-coins').textContent = fmt(sessionCoins());
  $('stars').innerHTML = '<b>' + '★'.repeat(G.wanted) + '</b>' + '★'.repeat(5 - G.wanted);
  $('h-speed').textContent = cur ? Math.round(Math.abs(cur.vF || 0) * 3.6) + ' km/soat' : '🚶 piyoda';
  $('h-clock').textContent = (night > 0.5 ? '🌙 ' : '☀️ ') + clockText();
  const me0 = pos(), dn = districtAt(me0.x, me0.z);
  if (dn !== G.district) { G.district = dn; $('h-dist').textContent = '📍 ' + dn; }
  const mEl = $('mission');
  if (G.race) mEl.innerHTML = `🏁 Poyga: ${Math.min(G.race.idx + 1, G.race.pts.length)}/${G.race.pts.length}<small>vs ${esc(G.race.vs)} — ${G.race.opp}/${G.race.pts.length}</small>`;
  else if (G.mission) mEl.innerHTML = esc(missionLabel(G.mission)) + `<small>⏱ ${Math.ceil(G.mission.time)} s · ${Math.round(dxz(pos(), G.mission.pts[G.mission.idx]))} m</small>`;
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
  $('bH').classList.toggle('hide', !cur); $('h-radio').classList.toggle('hide', !cur);
  const nb = $('nitro');
  if (cur) { nb.classList.remove('hide'); nb.firstElementChild.style.width = (cur.nitro / cur.spec.cap * 100) + '%'; } else nb.classList.add('hide');
  $('bust').classList.toggle('hide', G.bust < 0.25);
  drawMinimap(tgt);
}

// ═════════════ ONLAYN ═════════════
const PHRASES = ['👋 Salom!', '🏁 Poyga qilamizmi?', '🚗 Ortimdan yur!', '🔥 Zo\'r!', '😂😂😂', '🚓 Politsiya!', '👍 Ha', '👋 Xayr!'];
const remotes = new Map();
let net = null, netRetry = 0;
function netStart() {
  if (typeof GUEST !== 'undefined' && GUEST) return;
  netStop();
  try {
    const ws = new WebSocket((location.protocol === 'https:' ? 'wss://' : 'ws://') + location.host + '/ws/city');
    net = {ws, id: null, sendT: 0};
    ws.onopen = () => ws.send(JSON.stringify({t: 'hello', initData: INIT}));
    ws.onmessage = e => { try { onNet(JSON.parse(e.data)); } catch (x) {} };
    ws.onclose = () => {
      if (!net || net.ws !== ws) return;
      net = null; clearRemotes();
      if (G && player.g.visible !== undefined && API.active) netRetry = setTimeout(netStart, 4000);
    };
  } catch (e) { net = null; }
}
function netStop() {
  clearTimeout(netRetry);
  if (net) { const ws = net.ws; net = null; try { ws.close(); } catch (e) {} }
  clearRemotes();
}
function clearRemotes() { for (const id of [...remotes.keys()]) removeRemote(id); }
function addRemote(p) {
  if (remotes.has(p.id)) removeRemote(p.id);
  const ch = makeCharacter(p.look); scene.add(ch.g); ch.g.visible = false;
  const label = labelSprite((p.vip ? '👑 ' : '') + p.name, p.vip); scene.add(label); label.visible = false;
  remotes.set(p.id, Object.assign(ch, {id: p.id, name: p.name, vip: p.vip, label, tgt: null, x: 0, z: 0, y: 0, yaw: 0, ph: 0, sp: 0, car: null, carT: '', carC: 0, cyaw: 0, bubble: null, bubbleT: 0}));
}
function removeRemote(id) {
  const r = remotes.get(id); if (!r) return;
  scene.remove(r.g); scene.remove(r.label); if (r.car) scene.remove(r.car); if (r.bubble) scene.remove(r.bubble);
  remotes.delete(id);
}
function showBubble(r, text) {
  if (r.bubble) scene.remove(r.bubble);
  r.bubble = labelSprite(text, false, true); r.bubbleT = 4; scene.add(r.bubble);
}
function onNet(m) {
  if (m.t === 'welcome') { net.id = m.id; for (const p of m.players) addRemote(p); }
  else if (m.t === 'j') { addRemote(m); toast('👋 ' + m.name, 'shaharga keldi'); }
  else if (m.t === 'l') { removeRemote(m.id); }
  else if (m.t === 'w') {
    for (const row of m.p) {
      if (row[0] === net.id) continue;
      const r = remotes.get(row[0]); if (!r) continue;
      const first = !r.tgt; r.tgt = row;
      if (first) { r.x = row[1]; r.z = row[2]; r.yaw = row[4]; r.cyaw = row[8]; }
    }
  } else if (m.t === 'info') { toast('ℹ️ ' + m.m, '');
  } else if (m.t === 'ri') { if (window.onRaceInvite) window.onRaceInvite(m.from, m.name);
  } else if (m.t === 'rs') {
    G.mission = null;
    G.race = {pts: m.pts, idx: 0, opp: 0, vs: m.vs, vsId: m.vs_id, startAt: tNow + m.in, go: false};
    toast('🏁 Poyga: ' + m.vs, 'Tayyorlaning!'); haptic('heavy');
  } else if (m.t === 'rp') {
    if (G.race) { G.race.idx = m.i; sfx(990, 0.1); haptic('light'); if (m.i < G.race.pts.length) toast(`✅ ${m.i}/${G.race.pts.length}`, ''); }
  } else if (m.t === 'ro') { if (G.race) G.race.opp = m.i;
  } else if (m.t === 're') {
    const won = net && m.winner === net.id;
    if (G.race) {
      if (won) { toast('🏆 G\'ALABA!', m.coins ? `+${m.coins} tanga` : 'Bugungi tanga limiti tugagan'); sfx(523, 0.15, 'triangle', 0.08); setTimeout(() => sfx(784, 0.3, 'triangle', 0.08), 150); haptic('heavy'); }
      else if (m.winner) { toast('😔 ' + m.name + ' yutdi', 'Keyingi safar omad!'); sfx(200, 0.3, 'triangle', 0.06); }
      else toast('🏁 Poyga tugadi', m.reason === 'timeout' ? 'Vaqt tugadi' : 'Raqib chiqib ketdi');
      if (won && m.coins) G.raceCoins = (G.raceCoins || 0) + m.coins;
    }
    G.race = null;
  } else if (m.t === 'c') {
    const text = PHRASES[m.m] || '';
    if (m.id === net.id) showBubble(meBubble, text);
    else { const r = remotes.get(m.id); if (r) { showBubble(r, text); chatFeed(r.name + ': ' + text); } }
  }
}
const meBubble = {bubble: null, bubbleT: 0};
function chatFeed(t) {
  const el = $('chatfeed'); if (!el) return;
  const d = document.createElement('div'); d.textContent = t; el.appendChild(d);
  while (el.children.length > 3) el.removeChild(el.firstChild);
  setTimeout(() => d.remove(), 6000);
}
function updateNet(dt) {
  if (net && net.id !== null && net.ws.readyState === 1) {
    net.sendT -= dt;
    if (net.sendT <= 0) {
      net.sendT = 0.1;
      const p = cur ? [cur.x, cur.z, 0, cur.yaw, Math.abs(cur.vF || 0), cur.type, cur.color, cur.yaw] : [player.x, player.z, player.y, player.yaw, player.sp, '', 0, 0];
      net.ws.send(JSON.stringify({t: 's', p: p.map(v => typeof v === 'number' ? Math.round(v * 100) / 100 : v)}));
    }
  }
  const k = 1 - Math.exp(-10 * dt), me = pos();
  for (const r of remotes.values()) {
    if (!r.tgt) continue;
    const [, x, z, y, yaw, sp, ct, cc, cy] = r.tgt;
    r.x += (x - r.x) * k; r.z += (z - r.z) * k; r.y += (y - r.y) * k; r.yaw += ad(yaw, r.yaw) * k; r.cyaw += ad(cy, r.cyaw) * k; r.sp = sp;
    if (ct !== r.carT || cc !== r.carC) {
      if (r.car) { scene.remove(r.car); r.car = null; }
      r.carT = ct; r.carC = cc;
      if (ct && VT[ct]) { r.car = new T.Mesh(carGeometry(ct, cc), vehMat); r.car.castShadow = QUALITY > 0; scene.add(r.car); }
    }
    const far = Math.hypot(r.x - me.x, r.z - me.z) > 160;
    if (r.car) { r.car.visible = !far; r.car.position.set(r.x, 0, r.z); r.car.rotation.y = r.cyaw; r.g.visible = false; }
    else { r.g.visible = !far; r.g.position.set(r.x, r.y, r.z); r.g.rotation.y = r.yaw; r.ph += sp * dt * 2.3; animChar(r, sp, r.ph, r.y > 0.05); }
    const ly = r.car ? 2.9 : 2.45 + r.y;
    r.label.visible = Math.hypot(r.x - me.x, r.z - me.z) < 70; r.label.position.set(r.x, ly, r.z);
    if (r.bubble) { r.bubbleT -= dt; r.bubble.position.set(r.x, ly + 0.75, r.z); if (r.bubbleT <= 0) { scene.remove(r.bubble); r.bubble = null; } }
  }
  if (meBubble.bubble) {
    meBubble.bubbleT -= dt; meBubble.bubble.position.set(me.x, (cur ? 3.6 : 3.1 + player.y), me.z);
    if (meBubble.bubbleT <= 0) { scene.remove(meBubble.bubble); meBubble.bubble = null; }
  }
  const on = $('h-online');
  if (on) { on.classList.toggle('hide', !net); on.textContent = '👥 ' + (remotes.size + 1); }
}

// ── personaj ko'rinishi (garderob oynasi uchun) ──
let pv = null;
function preview(canvas, look) {
  if (!pv) {
    const r = new T.WebGLRenderer({canvas, antialias: true, alpha: true});
    r.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
    const sc = new T.Scene(), cam = new T.PerspectiveCamera(32, 1, 0.1, 50);
    cam.position.set(0, 1.4, 5.2); cam.lookAt(0, 1.05, 0);
    sc.add(new T.HemisphereLight(0xffffff, 0x445566, 0.9));
    const dl = new T.DirectionalLight(0xffffff, 0.8); dl.position.set(2, 4, 3); sc.add(dl);
    const base = new T.Mesh(new T.CylinderGeometry(0.9, 0.9, 0.06, 32), new T.MeshLambertMaterial({color: 0x2a3140})); base.position.y = -0.03; sc.add(base);
    pv = {r, sc, cam, ch: null, raf: 0, ang: 0.4, canvas};
  }
  if (pv.canvas !== canvas) { pv.r.forceContextLoss(); pv.r.dispose(); pv = null; return preview(canvas, look); }
  const w = canvas.clientWidth || 200, h = canvas.clientHeight || 200;
  pv.r.setSize(w, h, false); pv.cam.aspect = w / h; pv.cam.updateProjectionMatrix();
  if (pv.ch) pv.sc.remove(pv.ch.g);
  pv.ch = makeCharacter(look); pv.sc.add(pv.ch.g);
  cancelAnimationFrame(pv.raf);
  let ph = 0;
  const loop = () => {
    if (!document.body.contains(canvas)) { pv.raf = 0; return; }
    pv.ang += 0.012; ph += 0.09; pv.ch.g.rotation.y = pv.ang;
    animChar(pv.ch, 1.2, ph, false);
    pv.r.render(pv.sc, pv.cam); pv.raf = requestAnimationFrame(loop);
  };
  loop();
}

// ═════════════ API ═════════════
const API = {
  ok: false, mapImg: null,
  init() {
    try { setup(); API.ok = true; } catch (e) { console.error('3D init', e); API.ok = false; }
    return API.ok;
  },
  start() { lastCtx = ''; API.active = true; start(); },
  paints: PAINTS,
  radioNext() { station = (station + 1) % STATIONS.length; try { localStorage.setItem('sa_radio', String(station)); } catch (e) {} toast(STATIONS[station].name, ''); return STATIONS[station].name; },
  repaint(type, idx) { const v = vehicles.find(q => q.own); if (!v || v.type !== type) return; v.color = PAINTS[idx]; v.mesh.geometry = carGeometry(v.type, v.color); toast('🎨 Mashina bo\'yaldi!', ''); },
  phrases: PHRASES, preview,
  online() { return !!(net && net.id !== null); },
  inCar() { return !!cur; },
  players() { const me = pos(); return [...remotes.values()].filter(r => r.tgt).map(r => ({id: r.id, name: r.name, vip: r.vip, d: Math.round(Math.hypot(r.x - me.x, r.z - me.z))})).sort((a, b) => a.d - b.d); },
  raceInvite(id) { if (!cur) return toast('Avval mashinaga o\'tiring', ''); if (net && net.ws.readyState === 1) net.ws.send(JSON.stringify({t: 'ri', to: id})); },
  raceAccept(id) { if (!cur) return toast('Avval mashinaga o\'tiring', 'Keyin qabul qiling'); if (net && net.ws.readyState === 1) net.ws.send(JSON.stringify({t: 'ra', to: id})); },
  racing() { return !!(G && G.race); }, colors: {skin: SKIN_C, hc: HAIR_C, tc: TOP_C, pc: PANT_C},
  chat(i) { if (net && net.ws.readyState === 1) net.ws.send(JSON.stringify({t: 'c', m: i})); else toast('Onlayn emas', 'Chat faqat onlayn rejimda ishlaydi'); },
  stop() { API.active = false; stop(); },
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
    updateLights(tNow); updateTraffic(dt); updatePeds(dt); updateParked(dt); updatePolice(dt);
    const tgt = updateWorldObjs(dt);
    const me = pos(); updateDay(dt, me.x, me.z);
    updateCamera(dt, false);
    updateNet(dt); updateSiren(); radioTick(!!cur);
    if (input.hHit && cur) honk();
    hud(tgt);
  },
  render(menu, dt) {
    if (!API.ok) return;
    if (menu) {
      tNow += dt; updateLights(tNow); updateTraffic(dt); updatePeds(dt); updateDay(dt * 0.5, WORLD / 2, WORLD / 2); updateCamera(dt, true);
    }
    renderer.render(scene, camera);
  },
};
API._dbg = {cam: () => camera, day: t => { dayT = t; }, G: () => G, cur: () => cur, player: () => player, police: () => police};
window.City3D = API;
})();
