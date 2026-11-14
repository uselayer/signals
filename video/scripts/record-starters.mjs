// Records the footage for the `StarterBot` video: a scripted Chromium session on a local run of Layer's Starter bot
// page (uselayer.sh/dashboard/starters, as someone who answered "a trading bot" sees it). Same method as
// record-watchlist.mjs: laid out at 1920×1080, drawn at 2× (sharp when the video zooms), filmed in slow motion
// (Chrome's screencast only sends ~16 frames a second at 2×), sped back up into public/starters/app.mp4 at 30 fps,
// with each step's time in public/starters/events.json.
//
// The local run: a Layer worktree with an uncommitted /film route that renders the page's own <Starters> component
// without the dashboard's sign-in or sidebar, its live rows read from the public API with the owner's key (the same
// /v0/matches the real page reads), so every price is live.
//
//   FILM_API_KEY=$(security find-generic-password -s layer-api-key -w) npx next dev -p 3918   # in that worktree
//   node scripts/record-starters.mjs                                                         # APP=http://localhost:3918/film
import { chromium } from "playwright";
import { execFileSync } from "node:child_process";
import { mkdirSync, rmSync, writeFileSync } from "node:fs";
import path from "node:path";

const APP = process.env.APP || "http://localhost:3918/film";
const OUT = path.resolve("public/starters");
const FRAMES = path.join(OUT, "frames");
const Z = 2;
const SLOW = Number(process.env.SLOW || 2.5);

rmSync(FRAMES, { recursive: true, force: true });
mkdirSync(FRAMES, { recursive: true });

const browser = await chromium.launch(process.env.CHROME ? { executablePath: process.env.CHROME } : {});
const ctx = await browser.newContext({ viewport: { width: 1920 * Z, height: 1080 * Z }, colorScheme: "light" });
await ctx.grantPermissions(["clipboard-read", "clipboard-write"], { origin: new URL(APP).origin });
const page = await ctx.newPage();

// The page's clock runs SLOW times slower too, so "updated 4 s ago · next in 26 s" counts at its real pace once sped up.
await page.addInitScript((slow) => {
  const real = Date.now.bind(Date), start = real();
  Date.now = () => start + (real() - start) / slow;
  // and its timers, so "Copied" stays up as long as it does for a person
  const st = window.setTimeout, si = window.setInterval;
  window.setTimeout = (f, d, ...a) => st(f, (d || 0) * slow, ...a);
  window.setInterval = (f, d, ...a) => si(f, (d || 0) * slow, ...a);
}, SLOW);
await page.addInitScript((z) => {
  addEventListener("DOMContentLoaded", () => {
    const s = document.createElement("style");
    s.textContent = `body{zoom:${z}} nextjs-portal{display:none!important}
      #rec-cursor{position:fixed;left:0;top:0;width:${26 * z}px;height:${26 * z}px;margin:${-3 * z}px 0 0 ${-3 * z}px;z-index:99999;
        pointer-events:none;transition:transform .08s ease-out;filter:drop-shadow(0 ${2 * z}px ${4 * z}px rgba(0,0,0,.35))}
      #rec-cursor.down{transform:scale(.86)}
      .rec-ring{position:fixed;width:${44 * z}px;height:${44 * z}px;margin:${-22 * z}px 0 0 ${-22 * z}px;border-radius:50%;
        border:${3 * z}px solid #141519;z-index:99998;pointer-events:none;animation:rec-ring .5s ease-out forwards}
      @keyframes rec-ring{from{opacity:.9;transform:scale(.3)}to{opacity:0;transform:scale(1.4)}}`;
    document.head.append(s);
    const c = document.createElement("div");
    c.id = "rec-cursor";
    c.innerHTML = `<svg viewBox="0 0 24 24" width="100%" height="100%"><path d="M3 2l17 9.5-7.2 1.6L9.6 20z" fill="#141519" stroke="#fff" stroke-width="1.4" stroke-linejoin="round"/></svg>`;
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

const cdp = await ctx.newCDPSession(page);
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
let mouse = { x: 1500 * Z, y: 760 * Z };
async function glide(target, ms = 700) {
  let x, y;
  if (typeof target !== "object" || !Array.isArray(target)) {
    const b = await (typeof target === "string" ? page.locator(target).first() : target).boundingBox();
    [x, y] = [b.x + b.width / 2, b.y + b.height / 2];
  } else [x, y] = [target[0] * Z, target[1] * Z];
  const from = { ...mouse }, t = Date.now(), len = ms * SLOW;
  for (let k = 0; k < 1;) {
    k = Math.min(1, (Date.now() - t) / len);
    const e = k < 0.5 ? 4 * k * k * k : 1 - (-2 * k + 2) ** 3 / 2;
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
    const to = dy * Z * (k < 0.5 ? 2 * k * k : 1 - (-2 * k + 2) ** 2 / 2);
    await page.mouse.wheel(0, to - done); done = to;
    await page.waitForTimeout(8);
  }
}

await page.goto(APP);
// Wait for the live table, then for a fresh read so the clip starts at "updated 0 s ago".
await page.locator("table tbody tr").nth(5).waitFor({ timeout: 120000 });
await page.mouse.move(mouse.x, mouse.y);
await wait(600);

await cdp.send("Page.startScreencast", { format: "jpeg", quality: 92, maxWidth: 1920 * Z, maxHeight: 1080 * Z, everyNthFrame: 1 });
t0 = Date.now() / 1000;
mark("start");
await wait(1400);

// 1. The live table: the summary, then the top row across to what you could save.
await glide([1640, 330], 900);
mark("summary");
await wait(1000);
await glide([200, 540], 900);
mark("rowStart");
await glide([1650, 540], 1700);
mark("rowSaved");
await wait(900);

// 2. Down to "Run it on your laptop" and copy the prompt (no key made: that would create a real one).
await glide([1100, 760], 500);
const runTop = await page.getByText("Run it on your laptop", { exact: true }).first().evaluate((e) => e.getBoundingClientRect().top);
mark("scroll");
await scroll(runTop / Z - 140, 1600);
await wait(500);
mark("run");
const copy = page.getByRole("button", { name: /Copy prompt for your coding agent/ });
await click(copy, 900);
mark("copied");
await wait(250);
await glide([1500, 640], 700);
await wait(1100);
mark("end");

await cdp.send("Page.stopScreencast");
await wait(300);
await browser.close();

const file = (i) => path.join(FRAMES, `${String(i).padStart(5, "0")}.jpg`);
const list = frames.map((t, i) => `file '${file(i)}'\nduration ${(((frames[i + 1] ?? t + 0.5) - t) / SLOW).toFixed(4)}`);
writeFileSync(path.join(OUT, "frames.txt"), `${list.join("\n")}\nfile '${file(frames.length - 1)}'\n`);
execFileSync("ffmpeg", ["-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", path.join(OUT, "frames.txt"),
  "-vf", "fps=30,format=yuv420p", "-c:v", "libx264", "-crf", "16", "-preset", "slow", path.join(OUT, "app.mp4")], { stdio: "inherit" });
const offset = (frames[0] - t0) / SLOW;
writeFileSync(path.join(OUT, "events.json"), JSON.stringify({ recorded: new Date().toISOString(), frames: frames.length,
  events: Object.fromEntries(Object.entries(events).map(([k, v]) => [k, Number((v - offset).toFixed(3))])) }, null, 2));
rmSync(FRAMES, { recursive: true, force: true });
console.log(`${frames.length} frames over ${((frames.at(-1) - frames[0]) / SLOW).toFixed(1)} s → public/starters/app.mp4`);
