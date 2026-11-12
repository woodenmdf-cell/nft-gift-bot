// Promo videolar: o'yindan avtomatik kliplar (virtual vaqt — har kadr aniq 1/30 s, sekin kompyuterda ham silliq).
// Ishlatish: o'yin serveri ishlab turganda  node tools/record_promo.js http://127.0.0.1:8099 promo/clips [klip_nomi]
// Natija: promo/clips/<nom>.mp4 (720x1280, H.264) — promo bot shu fayllarni guruhga chiqaradi.
const { chromium } = require('playwright');
const { execFileSync } = require('child_process');
const fs = require('fs'), path = require('path');
const [, , URL = 'http://127.0.0.1:8099', OUT = 'promo/clips', ONLY] = process.argv;
const FPS = 30;

// sahnalar: kun vaqti (0 = 06:00, 0.25 = 12:00, 0.5 = 18:00), mashina, davomiyligi, maxsus sozlash
const SCENES = {
  flyover: {sec: 10, day: 0.02, menu: true},
  supercar: {sec: 12, day: 0.47, car: 'super', sp: 26, nitro: true},
  chase: {sec: 13, day: 0.64, car: 'sport', sp: 22, police: 3},
  ambulance: {sec: 11, day: 0.18, mission: 'ambulance', sp: 15},
  scooter: {sec: 10, day: 0.1, car: 'scooter', sp: 9},
};

const INIT = () => {
  // yuklanguncha haqiqiy vaqt; window.__virt = true dan keyin — virtual vaqt (__step bilan kadrma-kadr)
  const realNow = performance.now.bind(performance), realRaf = window.requestAnimationFrame.bind(window);
  window.__vt = 0; window.__virt = false;
  performance.now = () => window.__virt ? window.__vt : realNow();
  const cbs = [];
  window.requestAnimationFrame = cb => window.__virt ? (cbs.push(cb), cbs.length) : realRaf(cb);
  window.__startVirt = () => { window.__vt = realNow(); window.__virt = true; };
  window.__step = ms => { window.__vt += ms; if (window.__auto) window.__auto(ms / 1000); for (const f of cbs.splice(0)) f(window.__vt); };
};

// avtopilot: mashina yo'l bo'lagi bo'ylab yuradi, chorrahalarda burilib shahar bo'ylab aylanadi
const AUTO = (sp) => {
  const CELL = 60, RD = 14, N = 14, WORLD = 854, LANE = 3.4, roadC = i => i * CELL + RD / 2;
  const a = {ax: 'x', k: 7, dir: 1, along: 160, sp, last: -1, t: 0};
  const lane = () => a.ax === 'x' ? {x: a.along, z: roadC(a.k) + a.dir * LANE, yaw: a.dir > 0 ? Math.PI / 2 : -Math.PI / 2}
    : {x: roadC(a.k) - a.dir * LANE, z: a.along, yaw: a.dir > 0 ? 0 : Math.PI};
  const ad = (x, y) => { let d = x - y; while (d > Math.PI) d -= 2 * Math.PI; while (d < -Math.PI) d += 2 * Math.PI; return d; };
  window.__ap = a;
  window.__place = () => { const c = City3D._dbg.cur(); if (!c) return; const l = lane(); c.x = l.x; c.z = l.z; c.yaw = l.yaw; };
  window.__auto = dt => {
    const c = City3D._dbg.cur(); if (!c || !window.__go) return;
    a.t += dt;
    const prev = a.along; a.along += a.dir * a.sp * dt;
    const m = Math.round((a.along - RD / 2) / CELL), node = roadC(m);
    if (m >= 0 && m <= N && node >= Math.min(prev, a.along) && node <= Math.max(prev, a.along) && m !== a.last) {
      a.last = m;
      const edge = (a.dir > 0 && m >= N - 1) || (a.dir < 0 && m <= 1);
      if (m > 0 && m < N && (edge || (a.t > 3 && Math.random() < 0.3))) {
        const l = lane(), cross = a.ax === 'x' ? l.z : l.x;
        a.ax = a.ax === 'x' ? 'z' : 'x'; a.k = m; a.along = cross; a.dir = cross < WORLD / 2 ? 1 : -1;
        a.last = Math.round((a.along - RD / 2) / CELL); a.t = 0;
      }
    }
    const l = lane(), k = 1 - Math.exp(-5 * dt);
    c.x += (l.x - c.x) * k; c.z += (l.z - c.z) * k; c.yaw += ad(l.yaw, c.yaw) * Math.min(1, dt * 4.5);
    c.vF = a.sp; c.vx = Math.sin(c.yaw) * a.sp; c.vz = Math.cos(c.yaw) * a.sp;
  };
};

async function record(name, sc) {
  const b = await chromium.launch({args: ['--use-gl=angle', '--use-angle=swiftshader', '--enable-unsafe-swiftshader']});
  const page = await b.newPage({viewport: {width: 360, height: 640}, deviceScaleFactor: 2});
  page.on('pageerror', e => console.log('  xato:', e.message));
  await page.route('https://telegram.org/**', r => r.fulfill({contentType: 'text/javascript', body: ''}));
  await page.addInitScript(INIT);
  await page.goto(URL + '/');
  await page.waitForFunction(() => document.getElementById('loading').classList.contains('hide'), null, {timeout: 120000});
  await page.evaluate(() => { window.__startVirt(); let sd = 12345; Math.random = () => { sd = (sd * 16807) % 2147483647; return (sd - 1) / 2147483646; }; });
  await page.waitForTimeout(300);
  const step = n => page.evaluate(n => { for (let i = 0; i < n; i++) window.__step(1000 / 30); }, n);
  if (sc.menu) {
    await page.evaluate(() => { document.getElementById('menu').style.display = 'none'; });
  } else {
    await page.evaluate(sc => { if (sc.car) { P.car = sc.car; P.vip = sc.car === 'super'; } }, sc);
    await page.click('.m-city'); await step(3);
    await page.evaluate(AUTO, sc.sp);
    if (sc.mission) {
      await page.evaluate(t => { const G = City3D._dbg.G(), pl = City3D._dbg.player(); G.givers[0] = {type: t, x: pl.x, z: pl.z, name: 'Klinika «Shifo»'}; }, sc.mission);
      await step(4);
    } else {
      for (let i = 0; i < 6 && !(await page.evaluate(() => !!City3D._dbg.cur())); i++) { await page.keyboard.press('e'); await step(4); }
    }
    await page.evaluate(() => { window.__place(); window.__go = true; for (const id of ['h-hint', 'h-chat']) { const e = document.getElementById(id); if (e) e.style.display = 'none'; } });
    if (sc.nitro) await page.evaluate(() => { input.a = true; });
    await step(20);
    if (sc.police) {
      await page.evaluate(n => { City3D._dbg.G().wanted = n; }, sc.police);
      await step(2);
      await page.evaluate(() => { const c = City3D._dbg.cur(); City3D._dbg.police().forEach((p, i) => { p.x = c.x - Math.sin(c.yaw) * (14 + i * 9) + (i % 2 ? 2 : -2); p.z = c.z - Math.cos(c.yaw) * (14 + i * 9); p.yaw = c.yaw; p.vx = Math.sin(c.yaw) * 20; p.vz = Math.cos(c.yaw) * 20; p.vF = 20; }); });
    }
  }
  await page.evaluate(d => City3D._dbg.day(d), sc.day);
  await step(10);
  const dir = path.join(OUT, '_' + name); fs.rmSync(dir, {recursive: true, force: true}); fs.mkdirSync(dir, {recursive: true});
  const n = sc.sec * FPS, t0 = Date.now();
  for (let i = 0; i < n; i++) {
    await step(1);
    await page.screenshot({path: path.join(dir, String(i).padStart(4, '0') + '.jpg'), type: 'jpeg', quality: 88});
  }
  await b.close();
  const out = path.join(OUT, name + '.mp4');
  execFileSync('ffmpeg', ['-y', '-loglevel', 'error', '-framerate', String(FPS), '-i', path.join(dir, '%04d.jpg'),
    '-vf', 'scale=720:1280', '-c:v', 'libx264', '-pix_fmt', 'yuv420p', '-crf', '27', '-preset', 'slow', '-movflags', '+faststart', out]);
  fs.rmSync(dir, {recursive: true, force: true});
  console.log(`${name}: ${n} kadr, ${Math.round((Date.now() - t0) / 1000)} s, ${(fs.statSync(out).size / 1e6).toFixed(1)} MB`);
}

(async () => {
  fs.mkdirSync(OUT, {recursive: true});
  for (const [name, sc] of Object.entries(SCENES)) if (!ONLY || ONLY === name) await record(name, sc);
})();
