// Records the footage for the `Nemi` video: a scripted Chromium session on a local run of Nemi's site reading the live
// engine, the same recipe as record-watchlist.mjs (laid out at 1920×1080, drawn at 2×, filmed SLOW times slower, then
// public/nemi/app.mp4 at 30 fps plus every step's time in public/nemi/events.json).
//
//   cd ~/dev/nemi && VITE_ENGINE_URL=https://engine-production-fcc0.up.railway.app VITE_CLERK_PUBLISHABLE_KEY= \
//     VITE_POSTHOG_KEY= npx vite --port 5174 --strictPort
//   node scripts/record-nemi.mjs            # APP=http://localhost:5174 by default
//
// Sign-in is off locally, so the site shows the engine's own strategies (vwap-rider, entry-bands): the ones the video
// is about. The engine only allows localhost:5173 and nemi.markets, so the browser skips the cross-origin check; it
// only reads. "not connected yet" (sign-in off) is hidden. The trades opened are vwap-rider's real ones: SLIP walked
// the book, PARTIAL got 460 of 500, REFUSED found nothing for sale. Every number is the engine's live read.
import { chromium } from "playwright";
import { execFileSync } from "node:child_process";
import { mkdirSync, rmSync, writeFileSync } from "node:fs";
import path from "node:path";

const APP = process.env.APP || "http://localhost:5174";
const ENGINE = process.env.ENGINE || "https://engine-production-fcc0.up.railway.app";
const STRATEGY = process.env.STRATEGY || "vwap-rider";
const SLIP = process.env.SLIP || "276", PARTIAL = process.env.PARTIAL || "192", REFUSED = process.env.REFUSED || "170";
const OUT = path.resolve("public/nemi");
const FRAMES = path.join(OUT, "frames");
const Z = 2;
const SLOW = Number(process.env.SLOW || 2.5);

// The trades must be what the video says they are.
const trades = {};
for (const id of [SLIP, PARTIAL, REFUSED]) trades[id] = await (await fetch(`${ENGINE}/api/trades/${id}`)).json();
if (trades[PARTIAL].status !== "partial" || trades[REFUSED].status !== "refused" || !(trades[SLIP].slippage > 0))
  throw new Error(`trades aren't slip/partial/refused: ${JSON.stringify(Object.values(trades).map((t) => [t.id, t.status, t.slippage]))}`);
const strategy = (await (await fetch(`${ENGINE}/api/strategies`)).json()).find((s) => s.id === STRATEGY);

rmSync(FRAMES, { recursive: true, force: true });
mkdirSync(FRAMES, { recursive: true });

const browser = await chromium.launch({ args: ["--disable-web-security"] });
const page = await browser.newPage({ viewport: { width: 1920 * Z, height: 1080 * Z }, colorScheme: "dark" });

await page.addInitScript((z) => {
  addEventListener("DOMContentLoaded", () => {
    const s = document.createElement("style");
    s.textContent = `body{zoom:${z}}
      #rec-cursor{position:fixed;left:0;top:0;width:${26 * z}px;height:${26 * z}px;margin:${-3 * z}px 0 0 ${-3 * z}px;z-index:99999;
        pointer-events:none;transition:transform .08s ease-out;filter:drop-shadow(0 ${2 * z}px ${4 * z}px rgba(0,0,0,.35))}
      #rec-cursor.down{transform:scale(.86)}
      .rec-ring{position:fixed;width:${44 * z}px;height:${44 * z}px;margin:${-22 * z}px 0 0 ${-22 * z}px;border-radius:50%;
        border:${3 * z}px solid #8a4b00;z-index:99998;pointer-events:none;animation:rec-ring .5s ease-out forwards}
      @keyframes rec-ring{from{opacity:.9;transform:scale(.3)}to{opacity:0;transform:scale(1.4)}}`;
    document.head.append(s);
    const c = document.createElement("div");
    c.id = "rec-cursor";
    c.innerHTML = `<svg viewBox="0 0 24 24" width="100%" height="100%"><path d="M3 2l17 9.5-7.2 1.6L9.6 20z" fill="#1f1f1f" stroke="#fff" stroke-width="1.4" stroke-linejoin="round"/></svg>`;
    document.documentElement.append(c);
    addEventListener("mousemove", (e) => { c.style.left = `${e.clientX}px`; c.style.top = `${e.clientY}px`; }, true);
    addEventListener("mousedown", (e) => {
      c.classList.add("down");
      const r = document.createElement("div");
      r.className = "rec-ring"; r.style.left = `${e.clientX}px`; r.style.top = `${e.clientY}px`;
      document.documentElement.append(r); setTimeout(() => r.remove(), 600);
    }, true);
    addEventListener("mouseup", () => c.classList.remove("down"), true);
    // Sign-in is off locally: drop the "not connected yet" notes the signed-in site doesn't show.
    new MutationObserver(() => {
      for (const el of document.querySelectorAll("span")) if (el.textContent.trim() === "not connected yet") el.remove();
    }).observe(document.body, { childList: true, subtree: true });
  });
}, Z);

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
async function glide(target, ms = 700) {
  let x, y;
  if (typeof target === "string") {
    const b = await page.locator(target).first().boundingBox();
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
// In-app navigation (React Router listens to popstate), so the page never reloads on camera.
const go = (url) => page.evaluate((u) => { history.pushState(null, "", u); dispatchEvent(new PopStateEvent("popstate")); }, url);
const drawer = (heading) => page.locator(`text=${heading}`).last();
async function openTrade(id, title) {
  await go(`/s/${STRATEGY}?trade=${id}`);
  await page.getByText(title, { exact: false }).first().waitFor({ timeout: 30000 });
}

// Warm everything the camera will see.
await page.goto(`${APP}/s/${STRATEGY}/report`);
await page.getByText("Where the money went").waitFor({ timeout: 30000 });
for (const id of [SLIP, PARTIAL, REFUSED]) { await openTrade(id, "What it bought"); await page.getByText("How it ended").last().waitFor({ timeout: 30000 }); }
await page.goto(`${APP}/`);
await page.getByText(STRATEGY).first().waitFor({ timeout: 30000 });
await page.mouse.move(mouse.x, mouse.y);
await wait(1500);

await cdp.send("Page.startScreencast", { format: "jpeg", quality: 90, maxWidth: 1920 * Z, maxHeight: 1080 * Z, everyNthFrame: 1 });
t0 = Date.now() / 1000;
mark("start");
await wait(1000);

// 1. My strategies, then pick a template.
mark("home");
await glide([1000, 390], 900);
await wait(900);
await click('a[href="/new"] >> nth=-1', 800);
await page.getByText("OR PICK A TEMPLATE", { exact: false }).waitFor();
mark("new");
await wait(500);
await glide("text=Buys the side Bitcoin", 900);
mark("pick");
await page.mouse.down(); await wait(90); await page.mouse.up();
await wait(1400);

// 2. The strategy, running.
await go(`/s/${STRATEGY}`);
await page.getByText("Trades ·", { exact: false }).waitFor();
mark("strategy");
await glide([300, 150], 500);
await glide([1250, 150], 2000);  // along the stats
mark("statsSeen");
await wait(400);
await glide([700, 470], 700);
await wait(400);

// 3. A fill that walked the book: what it bought, what it cost, how it ended.
await openTrade(SLIP, "What it bought");
mark("slip");
await glide([1650, 380], 700);
await glide([1650, 560], 1500);  // down the book levels
mark("slipBook");
await wait(600);
mark("slipCostScroll");
await scroll(330, 1100);
mark("slipCost");
await glide([1650, 300], 500);
await wait(1600);
mark("slipEndScroll");
await scroll(600, 1100);
mark("settle");
await glide([1650, 520], 900);
await wait(2000);
mark("settleEnd");

// 4. A partial fill.
await openTrade(PARTIAL, "of 500");
await page.locator("aside, [role=dialog]").first().evaluate((el) => el.scrollTo?.(0, 0)).catch(() => {});
mark("partial");
await glide([1650, 330], 600);
await glide([1650, 470], 1200);
mark("partialNote");
await wait(1800);

// 5. A refused order.
await openTrade(REFUSED, "none bought");
await page.locator("aside, [role=dialog]").first().evaluate((el) => el.scrollTo?.(0, 0)).catch(() => {});
mark("refused");
await glide([1650, 250], 600);
await glide([1650, 360], 1100);
mark("refusedNote");
await wait(1800);

// 6. Where the money went.
await go(`/s/${STRATEGY}/report`);
await page.getByText("Where the money went").waitFor();
mark("report");
await glide([500, 330], 600);
await glide([500, 480], 1800);  // down the waterfall
mark("waterfallSeen");
await wait(500);
mark("reportScroll");
await scroll(420, 1300);
mark("stats");
await glide([700, 300], 900);
await wait(1800);
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
const pick = (t) => ({ id: t.id, time: t.time, market: t.marketTitle, side: t.side, token: t.token, askedQty: t.askedQty,
  askedPrice: t.askedPrice, filledQty: t.filledQty, filledAvgPrice: t.filledAvgPrice, fee: t.fee, slippage: t.slippage, status: t.status });
writeFileSync(path.join(OUT, "events.json"), JSON.stringify({ recorded: new Date().toISOString(), frames: frames.length,
  strategy: { id: strategy.id, startingBalance: strategy.startingBalance, balance: strategy.balance, pnl: strategy.pnl, pnlPct: strategy.pnlPct },
  trades: { slip: pick(trades[SLIP]), partial: pick(trades[PARTIAL]), refused: pick(trades[REFUSED]) },
  events: Object.fromEntries(Object.entries(events).map(([k, v]) => [k, Number((v - offset).toFixed(3))])) }, null, 2));
rmSync(FRAMES, { recursive: true, force: true });
console.log(`${frames.length} frames over ${((frames.at(-1) - frames[0]) / SLOW).toFixed(1)} s → public/nemi/app.mp4`);
