#!/usr/bin/env node
// bb.mjs: a filmed browser an agent drives one step at a time.
//
//   node bb.mjs start <feature> [--phone] [--port 7701]   start a recorded browser (runs in the background)
//   node bb.mjs go <url> [caption]                          open a page
//   node bb.mjs click <target> [caption]                    click (target: css, text=..., role=button[name="..."])
//   node bb.mjs type <target> <text> [caption]              fill a field
//   node bb.mjs press <key> [caption]                       press a key (Enter, Escape, ...)
//   node bb.mjs hover <target> [caption]
//   node bb.mjs scroll <pixels> [caption]
//   node bb.mjs say <caption>                               change the caption only
//   node bb.mjs look [name]                                 screenshot + url + visible text + new console/network errors
//   node bb.mjs ok <what worked>                            mark a check passed (green flash in the video)
//   node bb.mjs bug <title> [details]                       file a bug (red banner in the video + screenshot)
//   node bb.mjs stop                                        finish: video.mp4 (or .webm), report.md, bugs.json
//
// Everything lands in runs/<feature>-<utc time>/. The caption bar at the bottom of the video says what the
// agent is doing, a dot shows where it clicks, and each bug flashes red with its time in report.md.
import { spawn, execFileSync } from 'node:child_process';
import fs from 'node:fs';
import http from 'node:http';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const argv = process.argv.slice(2);
const flag = (name) => { const i = argv.indexOf(name); if (i < 0) return null; const v = argv[i + 1]; argv.splice(i, 2); return v; };
const bool = (name) => { const i = argv.indexOf(name); if (i < 0) return false; argv.splice(i, 1); return true; };
const PORT = Number(flag('--port') || process.env.BB_PORT || 7701);

async function send(cmd, args) {
  const body = JSON.stringify({ cmd, args });
  return new Promise((resolve, reject) => {
    const req = http.request({ host: '127.0.0.1', port: PORT, method: 'POST', path: '/', headers: { 'content-type': 'application/json' } }, (res) => {
      let s = ''; res.on('data', (d) => (s += d)); res.on('end', () => resolve(s));
    });
    req.on('error', reject); req.end(body);
  });
}

// ---------- client ----------
if (argv[0] !== '__serve') {
  const [cmd, ...args] = argv;
  if (!cmd) { console.log(fs.readFileSync(fileURLToPath(import.meta.url), 'utf8').split('\n').slice(1, 19).join('\n')); process.exit(0); }
  if (cmd === 'start') {
    const feature = (args[0] || 'bash').replace(/[^a-z0-9-]/gi, '-').toLowerCase();
    const phone = bool('--phone') || args.includes('--phone');
    const out = path.join(HERE, 'runs', `${feature}-${new Date().toISOString().replace(/[:.]/g, '').slice(0, 15)}Z`);
    fs.mkdirSync(out, { recursive: true });
    const log = fs.openSync(path.join(out, 'server.log'), 'a');
    spawn(process.execPath, [fileURLToPath(import.meta.url), '__serve', feature, out, phone ? 'phone' : 'desk', '--port', String(PORT)], { detached: true, stdio: ['ignore', log, log] }).unref();
    for (let i = 0; i < 60; i++) {
      try { const r = await send('ping', []); console.log(r); process.exit(0); } catch { await new Promise((r) => setTimeout(r, 500)); }
    }
    console.error(`browser did not start; see ${out}/server.log`); process.exit(1);
  }
  try { console.log(await send(cmd, args)); } catch (e) { console.error(`no recorder on port ${PORT}: run "node bb.mjs start <feature>" first (${e.code})`); process.exit(1); }
  process.exit(0);
}

// ---------- server ----------
const [, FEATURE, OUT, MODE] = argv;
const { chromium } = await import('playwright');
const size = MODE === 'phone' ? { width: 390, height: 844 } : { width: 1440, height: 900 };
const browser = await chromium.launch({ headless: true });
const context = await browser.newContext({ viewport: size, recordVideo: { dir: OUT, size }, isMobile: MODE === 'phone', hasTouch: MODE === 'phone', deviceScaleFactor: 1 });
const t0 = Date.now();
const at = () => (Date.now() - t0) / 1000;
const mmss = (s) => `${String(Math.floor(s / 60)).padStart(2, '0')}:${String(Math.floor(s % 60)).padStart(2, '0')}`;

await context.addInitScript(({ feature }) => {
  const mount = () => {
    if (document.getElementById('__bb')) return;
    const st = document.createElement('style');
    st.textContent = `#__bb{position:fixed;left:0;right:0;bottom:0;z-index:2147483647;pointer-events:none;font:600 15px/1.35 -apple-system,Segoe UI,Roboto,sans-serif;color:#fff;background:rgba(17,17,23,.88);padding:10px 16px;display:flex;gap:12px;align-items:center}
#__bb b{background:#5b5bd6;border-radius:6px;padding:2px 8px;font-size:12px;letter-spacing:.04em;text-transform:uppercase;white-space:nowrap}
#__bb span{overflow:hidden;text-overflow:ellipsis}
#__bb.bug{background:rgba(200,30,40,.95)} #__bb.ok{background:rgba(20,130,70,.95)}
#__bbdot{position:fixed;z-index:2147483647;pointer-events:none;width:22px;height:22px;margin:-11px 0 0 -11px;border-radius:50%;background:rgba(255,60,80,.35);border:2px solid #ff3c50;transition:left .45s ease,top .45s ease;left:-40px;top:-40px}
#__bbdot.tap{animation:__bbtap .35s ease}@keyframes __bbtap{50%{transform:scale(1.8)}}`;
    const bar = document.createElement('div'); bar.id = '__bb'; bar.innerHTML = `<b>Agent · ${feature}</b><span></span>`;
    const dot = document.createElement('div'); dot.id = '__bbdot';
    document.documentElement.append(st, bar, dot);
    try { const s = sessionStorage.getItem('__bbcap'); if (s) bar.querySelector('span').textContent = s; } catch {}
  };
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', mount); else mount();
  window.__bbSay = (text, kind) => { mount(); const bar = document.getElementById('__bb'); bar.querySelector('span').textContent = text; bar.className = kind || ''; try { sessionStorage.setItem('__bbcap', text); } catch {} };
  window.__bbDot = (x, y, tap) => { mount(); const d = document.getElementById('__bbdot'); d.style.left = x + 'px'; d.style.top = y + 'px'; if (tap) { d.classList.remove('tap'); void d.offsetWidth; d.classList.add('tap'); } };
}, { feature: FEATURE });

const page = await context.newPage();
const steps = [], bugs = [], oks = [], errors = [];
let unseen = [];
page.on('console', (m) => { if (m.type() === 'error') { const e = `console: ${m.text().slice(0, 300)}`; errors.push({ t: at(), e }); unseen.push(e); } });
page.on('pageerror', (err) => { const e = `page error: ${String(err.message).slice(0, 300)}`; errors.push({ t: at(), e }); unseen.push(e); });
page.on('response', (r) => { if (r.status() >= 400 && !/\/lyr\//.test(r.url())) { const e = `HTTP ${r.status()} ${r.request().method()} ${r.url().slice(0, 200)}`; errors.push({ t: at(), e }); unseen.push(e); } });

const say = async (text, kind) => { try { await page.evaluate(([t, k]) => window.__bbSay && window.__bbSay(t, k), [text, kind || '']); } catch {} };
const pause = (ms) => page.waitForTimeout(ms);
const loc = (target) => page.locator(target).first();
async function point(target, tap) {
  const l = loc(target);
  await l.scrollIntoViewIfNeeded({ timeout: 8000 });
  const b = await l.boundingBox();
  if (b) { await page.evaluate(([x, y, t]) => window.__bbDot && window.__bbDot(x, y, t), [b.x + b.width / 2, b.y + b.height / 2, !!tap]); await pause(500); }
  return l;
}
let shots = 0;
async function shot(name) {
  shots += 1;
  const file = path.join(OUT, `${String(shots).padStart(2, '0')}-${(name || 'look').replace(/[^a-z0-9-]/gi, '-').slice(0, 40)}.png`);
  await page.screenshot({ path: file });
  return file;
}
async function look(name) {
  const file = await shot(name);
  const text = (await page.evaluate(() => (document.body ? document.body.innerText : '')).catch(() => '')).replace(/\n{3,}/g, '\n\n').slice(0, 3500);
  const fresh = unseen; unseen = [];
  return [`url: ${page.url()}`, `title: ${await page.title().catch(() => '')}`, `screenshot: ${file}`, fresh.length ? `NEW ERRORS (${fresh.length}):\n- ${fresh.slice(0, 15).join('\n- ')}` : 'new errors: none', `--- visible text ---\n${text}`].join('\n');
}

const handlers = {
  ping: async () => `recording "${FEATURE}" (${MODE}, ${size.width}x${size.height}) into ${OUT}`,
  go: async ([url, cap]) => { await say(cap || `Opening ${url}`); await page.goto(url, { waitUntil: 'domcontentloaded', timeout: 45000 }); await page.waitForLoadState('networkidle', { timeout: 15000 }).catch(() => {}); await say(cap || `Opened ${url}`); await pause(800); return `at ${page.url()}`; },
  click: async ([target, cap]) => { await say(cap || `Clicking ${target}`); const l = await point(target, true); await l.click({ timeout: 10000 }); await page.waitForLoadState('networkidle', { timeout: 10000 }).catch(() => {}); await pause(900); return `clicked ${target}; now at ${page.url()}`; },
  type: async ([target, text, cap]) => { await say(cap || `Typing "${text}"`); const l = await point(target, true); await l.click({ timeout: 10000 }).catch(() => {}); await l.fill(''); await l.pressSequentially(text, { delay: 55 }); await pause(900); return `typed into ${target}`; },
  press: async ([key, cap]) => { await say(cap || `Pressing ${key}`); await page.keyboard.press(key); await pause(900); return `pressed ${key}`; },
  hover: async ([target, cap]) => { await say(cap || `Hovering ${target}`); const l = await point(target); await l.hover({ timeout: 10000 }); await pause(900); return `hovering ${target}`; },
  scroll: async ([px, cap]) => { await say(cap || 'Scrolling'); await page.mouse.wheel(0, Number(px) || 600); await pause(900); return `scrolled ${px}`; },
  say: async (words) => { await say(words.join(' ')); await pause(1200); return 'ok'; },
  look: async ([name]) => look(name),
  ok: async (words) => { const what = words.join(' '); oks.push({ t: at(), what }); await say(`✓ ${what}`, 'ok'); await pause(1400); await say(what); return `passed @ ${mmss(at())}`; },
  bug: async ([title, ...rest]) => { const t = at(); await say(`BUG: ${title}`, 'bug'); await pause(400); const file = await shot(`bug-${bugs.length + 1}`); bugs.push({ t, at: mmss(t), title, details: rest.join(' '), url: page.url(), screenshot: path.basename(file) }); await pause(2200); await say(`Filed bug: ${title}`); return `bug ${bugs.length} filed @ ${mmss(t)}: ${file}`; },
  stop: async () => {
    await say(`Done · ${bugs.length} bug${bugs.length === 1 ? '' : 's'}, ${oks.length} check${oks.length === 1 ? '' : 's'} passed`, bugs.length ? 'bug' : 'ok');
    await pause(2500);
    const video = page.video();
    await context.close(); await browser.close();
    const webm = path.join(OUT, 'video.webm');
    await video.saveAs(webm).catch(async () => { fs.renameSync(await video.path(), webm); });
    let movie = webm;
    try { execFileSync('ffmpeg', ['-y', '-loglevel', 'error', '-i', webm, '-c:v', 'libx264', '-pix_fmt', 'yuv420p', '-crf', '23', '-movflags', '+faststart', path.join(OUT, 'video.mp4')]); movie = path.join(OUT, 'video.mp4'); fs.unlinkSync(webm); } catch {}
    for (const f of fs.readdirSync(OUT)) if (/^[0-9a-f]{32}\.webm$/.test(f)) fs.unlinkSync(path.join(OUT, f));
    fs.writeFileSync(path.join(OUT, 'bugs.json'), JSON.stringify({ feature: FEATURE, mode: MODE, bugs, passed: oks, errors }, null, 2));
    const md = [`# Bug bash: ${FEATURE} (${MODE})`, '', `Video: ${path.basename(movie)} · ${mmss(at())} long · ${new Date().toISOString()}`, '',
      `## Bugs (${bugs.length})`, ...(bugs.length ? bugs.map((b, i) => `${i + 1}. **${b.title}** (video ${b.at}) — ${b.details || ''}\n   - Page: ${b.url}\n   - Screenshot: ${b.screenshot}`) : ['None found.']), '',
      `## Checks passed (${oks.length})`, ...oks.map((o) => `- ${mmss(o.t)} ${o.what}`), '',
      `## Steps`, ...steps.map((s) => `- ${mmss(s.t)} ${s.cmd} ${s.args.join(' ')}${s.error ? ` → FAILED: ${s.error}` : ''}`), '',
      `## Console and network errors (${errors.length})`, ...errors.slice(0, 50).map((e) => `- ${mmss(e.t)} ${e.e}`)].join('\n');
    fs.writeFileSync(path.join(OUT, 'report.md'), md + '\n');
    setTimeout(() => process.exit(0), 200);
    return `saved ${movie}\nreport ${path.join(OUT, 'report.md')}`;
  },
};

http.createServer((req, res) => {
  let s = ''; req.on('data', (d) => (s += d));
  req.on('end', async () => {
    const { cmd, args } = JSON.parse(s || '{}');
    const h = handlers[cmd];
    if (!h) { res.end(`unknown command "${cmd}"`); return; }
    const step = { t: at(), cmd, args: args || [] };
    if (!['ping', 'look', 'stop'].includes(cmd)) steps.push(step);
    try { res.end(String(await h(args || []))); }
    catch (e) { step.error = String(e.message || e).split('\n')[0].slice(0, 200); await say(`Step failed: ${cmd} ${args?.[0] || ''}`); res.end(`FAILED: ${step.error}\n(the step failing may itself be a bug: look, then decide)`); }
  });
}).listen(PORT, '127.0.0.1');
