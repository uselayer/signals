// Records the Watchlist footage for the `Watchlist` video: a scripted Chromium session on a local run of Signals
// (main, nothing gated). Chrome's screencast sends frames at the page's CSS size whatever the device scale, so the
// page is laid out at 1920×1080 and drawn at 2× (a 3840×2160 viewport, the body zoomed 2×): sharp when the video zooms
// in. At 2× Chrome sends only ~16 frames a second, so it's filmed in slow motion (SLOW: the page's animations slowed
// and every move of the script stretched by it), then sped back up: ffmpeg turns the frames into
// public/watchlist/app.mp4 at a constant 30 fps, and every step's time goes to public/watchlist/events.json so the
// composition can cut and zoom on it.
//
//   SIGNALS_STORE_DIR=<scratch> SIGNALS_DIRECTORY=0 SIGNALS_EVALUATE=0 SIGNALS_CATEGORY_READS=0 SIGNALS_PORT=8791 uv run signals
//   node scripts/record-watchlist.mjs            # APP=http://127.0.0.1:8791 by default
//
// What differs from usesignals.app, and how it's evened out: locally signing in is off, so the lookup ends with "Open
// their page" (relabelled with what a signed-in person sees, "Follow <name>", then the app's own toast) and the
// Watchlist body says signing in is off (hidden); the trader directory is off, so the lookup's record has no name
// (filled from the lookup's own result, as usesignals.app shows it). Every number is the local run's live read.
import { chromium } from "playwright";
import { execFileSync } from "node:child_process";
import { mkdirSync, rmSync, writeFileSync } from "node:fs";
import path from "node:path";

const APP = process.env.APP || "http://127.0.0.1:8791";
const WALLET = process.env.WALLET || "0x606ffc68a29ebf92f9dc1d041fec5d0127571083";  // SleeperHunter
const PASTE = process.env.PASTE || "https://polymarket.com/@SleeperHunter";
const PICK = Number(process.env.PICK || 2);  // which change to open in Explained (0 = newest)
const OUT = path.resolve("public/watchlist");
const FRAMES = path.join(OUT, "frames");
const Z = 2;  // drawn at 2×; every coordinate below is in the 1920×1080 layout
const SLOW = Number(process.env.SLOW || 2.5);  // filmed this many times slower than it plays; every time below is as it plays

// Warm the engine's caches first so nothing on camera waits on a read.
let name = null;
for (const p of [`/api/find?q=${encodeURIComponent(PASTE)}`, `/api/worth/${WALLET}?score=0`, `/api/categories/${WALLET}`, `/api/watch/${WALLET}`]) {
  const r = await fetch(APP + p);
  if (!r.ok) throw new Error(`${p}: ${r.status}`);
  if (p.startsWith("/api/find")) name = (await r.json()).results?.[0]?.name;
}
if (!name) throw new Error(`no trader found for ${PASTE}`);

rmSync(FRAMES, { recursive: true, force: true });
mkdirSync(FRAMES, { recursive: true });

const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: 1920 * Z, height: 1080 * Z }, colorScheme: "dark" });
await page.route(`**/api/worth/${WALLET}?score=0`, async (route) => {
  const r = await route.fetch(), d = await r.json();
  await route.fulfill({ response: r, json: { ...d, name: d.name || name } });
});

// The 2× zoom on the body, and a visible cursor (headless Chrome draws none) outside it, on the root, so it sits at the
// mouse's own coordinates; a ring on each click.
await page.addInitScript((z) => {
  addEventListener("DOMContentLoaded", () => {
    const s = document.createElement("style");
    s.textContent = `body{zoom:${z}}
      #rec-cursor{position:fixed;left:0;top:0;width:${26 * z}px;height:${26 * z}px;margin:${-3 * z}px 0 0 ${-3 * z}px;z-index:99999;
        pointer-events:none;transition:transform .08s ease-out;filter:drop-shadow(0 ${2 * z}px ${4 * z}px rgba(0,0,0,.6))}
      #rec-cursor.down{transform:scale(.86)}
      .rec-ring{position:fixed;width:${44 * z}px;height:${44 * z}px;margin:${-22 * z}px 0 0 ${-22 * z}px;border-radius:50%;
        border:${3 * z}px solid #ff4d1f;z-index:99998;pointer-events:none;animation:rec-ring .5s ease-out forwards}
      @keyframes rec-ring{from{opacity:.9;transform:scale(.3)}to{opacity:0;transform:scale(1.4)}}`;
    document.head.append(s);
    const c = document.createElement("div");
    c.id = "rec-cursor";
    c.innerHTML = `<svg viewBox="0 0 24 24" width="100%" height="100%"><path d="M3 2l17 9.5-7.2 1.6L9.6 20z" fill="#fff" stroke="#111" stroke-width="1.4" stroke-linejoin="round"/></svg>`;
    document.documentElement.append(c);
    addEventListener("mousemove", (e) => { c.style.left = `${e.clientX}px`; c.style.top = `${e.clientY}px`; }, true);
    addEventListener("mousedown", (e) => {
      c.classList.add("down");
      const r = document.createElement("div");
      r.className = "rec-ring"; r.style.left = `${e.clientX}px`; r.style.top = `${e.clientY}px`;
      document.documentElement.append(r); setTimeout(() => r.remove(), 600);
    }, true);
    addEventListener("mouseup", () => c.classList.remove("down"), true);
  });
}, Z);

// The screencast: Chrome sends a frame whenever the page changes, each with its time.
const cdp = await page.context().newCDPSession(page);
await cdp.send("Animation.enable");
await cdp.send("Animation.setPlaybackRate", { playbackRate: 1 / SLOW });
const frames = [];
let t0 = null;
cdp.on("Page.screencastFrame", async ({ data, metadata, sessionId }) => {
  const i = frames.length;
  writeFileSync(path.join(FRAMES, `${String(i).padStart(5, "0")}.jpg`), Buffer.from(data, "base64"));
  frames.push(metadata.timestamp);
  await cdp.send("Page.screencastFrameAck", { sessionId }).catch(() => {});
});

const events = {};
const mark = (n) => { events[n] = (Date.now() / 1000 - t0) / SLOW; console.log(n, events[n].toFixed(2)); };
const wait = (ms) => page.waitForTimeout(ms * SLOW);
let mouse = { x: 1500 * Z, y: 700 * Z };
// Glide the cursor to an element, or a point in the 1920×1080 layout, at a pace you can follow.
async function glide(target, ms = 700) {
  let x, y;
  if (typeof target === "string") {
    const b = await page.locator(target).first().boundingBox();
    [x, y] = [b.x + b.width / 2, b.y + b.height / 2];
  } else [x, y] = [target[0] * Z, target[1] * Z];
  const from = { ...mouse }, t = Date.now(), len = ms * SLOW;  // paced by the clock: a slow frame doesn't slow the glide
  for (let k = 0; k < 1;) {
    k = Math.min(1, (Date.now() - t) / len);
    const e = k < 0.5 ? 4 * k * k * k : 1 - (-2 * k + 2) ** 3 / 2;  // ease in-out
    await page.mouse.move(from.x + (x - from.x) * e, from.y + (y - from.y) * e);
    await page.waitForTimeout(8);
  }
  mouse = { x, y };
}
async function click(target, ms) { await glide(target, ms); await wait(180); await page.mouse.down(); await wait(90); await page.mouse.up(); }
async function scroll(dy, ms) {
  const t = Date.now(), len = ms * SLOW;
  for (let done = 0, k = 0; k < 1;) {
    k = Math.min(1, (Date.now() - t) / len);
    const to = dy * Z * (k < 0.5 ? 2 * k * k : 1 - (-2 * k + 2) ** 2 / 2);  // ease in-out
    await page.mouse.wheel(0, to - done); done = to;
    await page.waitForTimeout(8);
  }
}

await page.goto(`${APP}/#/watchlist`);
await page.addStyleTag({ content: "#wlbody{visibility:hidden}" });
await page.mouse.move(mouse.x, mouse.y);
await wait(800);

await cdp.send("Page.startScreencast", { format: "jpeg", quality: 90, maxWidth: 1920 * Z, maxHeight: 1080 * Z, everyNthFrame: 1 });
t0 = Date.now() / 1000;
mark("start");
await wait(1200);

// 1. Find them.
await click("#wladd", 900);
mark("followSheet");
await wait(700);
await glide("#wlq", 500);
await page.keyboard.insertText(PASTE);  // pasted, all at once
mark("pasted");
await wait(900);
await click("#wlfind button[type=submit]", 600);
mark("lookUp");
const go = page.locator("#wlfound a.btn.wide");
await go.waitFor({ timeout: 30000 });
await go.evaluate((a, n) => { a.textContent = `Follow ${n}`; }, name);
mark("found");
await wait(1800);
await click("#wlfound a.btn.wide", 700);
await page.evaluate((n) => toast(`Following ${n}. New changes show up within about 30 seconds.`), name);
mark("followed");

// 2. Their watch page.
await page.locator(".wt-tiles .tile").nth(4).waitFor({ timeout: 60000 });
mark("watch");
await glide([700, 280], 400);
await wait(400);
await glide([1450, 270], 1800);  // along the tiles
mark("tilesSeen");
await wait(300);
await glide([900, 640], 700);
mark("scrollDown");
await scroll(1100, 2200);
await wait(500);
mark("scrollUp");
await scroll(-1100, 1400);
await wait(400);

// 3. Explained.
await click(`.wt-move >> nth=${PICK}`, 800);
mark("picked");
await wait(500);
await glide([1240, 530], 600);
await glide([1240, 650], 1800);  // down the facts
mark("explainSeen");
await wait(900);

// 4. Holding now: a jump down the page (the composition cuts here).
await page.evaluate((z) => {
  const h = [...document.querySelectorAll(".pf-card")].find((c) => c.querySelector("h2")?.textContent.startsWith("Holding now"));
  scrollTo(0, h.getBoundingClientRect().top + scrollY - 90 * z);
}, Z);
mouse = { x: 1700 * Z, y: 900 * Z };
await page.mouse.move(mouse.x, mouse.y);
mark("holding");
await wait(500);
await glide([900, 330], 700);
await glide([900, 640], 1800);
await wait(800);
mark("end");

await cdp.send("Page.stopScreencast");
await wait(300);
await browser.close();

// Frames → a constant 30 fps MP4: each frame held until the next one arrived.
const file = (i) => path.join(FRAMES, `${String(i).padStart(5, "0")}.jpg`);
const list = frames.map((t, i) => `file '${file(i)}'\nduration ${(((frames[i + 1] ?? t + 0.5) - t) / SLOW).toFixed(4)}`);
writeFileSync(path.join(OUT, "frames.txt"), `${list.join("\n")}\nfile '${file(frames.length - 1)}'\n`);
execFileSync("ffmpeg", ["-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", path.join(OUT, "frames.txt"),
  "-vf", "fps=30,format=yuv420p", "-c:v", "libx264", "-crf", "16", "-preset", "slow", path.join(OUT, "app.mp4")], { stdio: "inherit" });
const offset = (frames[0] - t0) / SLOW;  // the first frame comes a hair after "start": times are from that frame
writeFileSync(path.join(OUT, "events.json"), JSON.stringify({ wallet: WALLET, name, recorded: new Date().toISOString(),
  frames: frames.length, events: Object.fromEntries(Object.entries(events).map(([k, v]) => [k, Number((v - offset).toFixed(3))])) }, null, 2));
rmSync(FRAMES, { recursive: true, force: true });
console.log(`${frames.length} frames over ${((frames.at(-1) - frames[0]) / SLOW).toFixed(1)} s → public/watchlist/app.mp4`);
