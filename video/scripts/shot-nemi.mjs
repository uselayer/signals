// A still of a strategy's page on Nemi's site, for NemiCosts' platform shot: public/nemi/strategy.png (1920×1200 laid
// out, drawn at 2×) and where its stat tiles and trades table sit, in public/nemi/strategy.json (layout pixels).
//
//   cd <nemi checkout> && VITE_ENGINE_URL=https://engine-production-fcc0.up.railway.app VITE_CLERK_PUBLISHABLE_KEY= \
//     VITE_POSTHOG_KEY= npx vite --port 5174 --strictPort
//   node scripts/shot-nemi.mjs            # APP=http://localhost:5174, STRATEGY=entry-bands
//
// Sign-in is off locally, so it's one of the engine's own strategies and no one's account. The engine only allows
// localhost:5173 and nemi.markets, so the browser skips the cross-origin check; it only reads.
import { chromium } from "playwright";
import { writeFileSync } from "node:fs";
import path from "node:path";

const APP = process.env.APP || "http://localhost:5174";
const STRATEGY = process.env.STRATEGY || "entry-bands";
const OUT = path.resolve("public/nemi");
const W = 1920, H = 1200;

const browser = await chromium.launch({ args: ["--disable-web-security"] });
const page = await browser.newPage({ viewport: { width: W, height: H }, deviceScaleFactor: 2, colorScheme: "dark" });
await page.goto(`${APP}/s/${STRATEGY}`, { waitUntil: "networkidle" });
await page.getByText("fees + slippage").waitFor({ timeout: 30000 });
await page.getByText(/^Trades/).first().waitFor({ timeout: 30000 });
await page.waitForTimeout(1500);
await page.evaluate(() => {  // sign-in is off here, which the live site never says
  for (const el of document.querySelectorAll("body *")) if (/not connected yet/i.test(el.textContent || "") && !el.children.length) el.style.visibility = "hidden";
});
const box = async (loc) => { const b = await loc.first().boundingBox(); return b && { x: b.x, y: b.y, w: b.width, h: b.height }; };
const where = {
  strategy: STRATEGY, at: new Date().toISOString(),
  stats: await box(page.getByText("fees + slippage").locator("xpath=ancestor::*[count(*) >= 4][1]")),
  costs: await box(page.getByText("fees + slippage").locator("xpath=..")),
  trades: await box(page.locator("table").last()),
};
await page.screenshot({ path: path.join(OUT, "strategy.png") });
writeFileSync(path.join(OUT, "strategy.json"), JSON.stringify(where, null, 1) + "\n");
console.log(JSON.stringify(where));
await browser.close();
