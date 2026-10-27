// Screenshots of each Nemi screen on a local run of the site (for planning shots): node scripts/peek-nemi.mjs <dir> [path...]
import { chromium } from "playwright";
const [out, ...paths] = process.argv.slice(2);
const APP = process.env.APP || "http://localhost:5174";
const b = await chromium.launch({ args: ["--disable-web-security"] });
const p = await b.newPage({ viewport: { width: 1920, height: 1080 } });
const list = paths.length ? paths : ["/", "/s/vwap-rider", "/s/vwap-rider/activity", "/s/vwap-rider/report", "/new", "/s/vwap-rider/code"];
for (const [i, u] of list.entries()) {
  await p.goto(APP + u); await p.waitForTimeout(3500);
  await p.screenshot({ path: `${out}/${i}.png`, fullPage: !!process.env.FULL });
  console.log(i, u);
}
await b.close();
