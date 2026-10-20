// Pulls one Leaderboard trader's record and latest buy from usesignals.app into src/data.json, the video's only
// source of numbers. Usage: npm run pull -- <name or wallet>
import { writeFileSync } from "node:fs";

const SITE = "https://usesignals.app";
const who = (process.argv[2] || "").toLowerCase();
if (!who) throw new Error("usage: npm run pull -- <name or wallet>");

const get = async (path) => {
  const r = await fetch(SITE + path);
  if (!r.ok) throw new Error(`${path}: ${r.status}`);
  return r.json();
};

const { rows } = await get("/api/leaderboard");
const row = rows.find((r) => r.name.toLowerCase() === who || r.wallet === who);
if (!row) throw new Error(`${who} isn't on the Leaderboard's first page`);
const { trades } = await get(`/api/trader/polymarket/${row.wallet}`);

// The latest buy, every fill of that outcome merged as an alert does: their average price and the dollars in.
const last = trades.filter((t) => t.action === "buy").sort((a, b) => b.at.localeCompare(a.at))[0];
const fills = trades.filter((t) => t.action === "buy" && t.token === last.token);
const usd = fills.reduce((s, t) => s + t.usd, 0), size = fills.reduce((s, t) => s + t.size, 0);

const d30 = row.periods["30d"];
const data = {
  asOf: new Date().toISOString().slice(0, 10),
  wallet: row.wallet,
  name: row.name,
  category: row.category,
  profitAll: row.periods.all.trading_pnl,
  profit90: row.periods["90d"].trading_pnl,
  curve90: row.pnl_daily.map(([, v]) => v),  // profit since 90 days ago, one point a day
  won30: row.win.won,
  closed30: row.win.closed,
  paid30: row.paid_30d,
  weeksUp: row.weeks_up,
  weeksKnown: row.weeks_known,
  usualTrade: row.typical_usd,
  volume30: d30.volume,
  buy: { outcome: last.outcome, title: last.title, price: usd / size, usd, at: last.at, kalshi: !!last.us?.found },
};
writeFileSync(new URL("../src/data.json", import.meta.url), JSON.stringify(data, null, 2) + "\n");
console.log(`${data.name}: $${Math.round(data.profitAll).toLocaleString()} all time; bought ${data.buy.outcome} at ` +
  `${Math.round(data.buy.price * 100)}¢ ($${Math.round(usd).toLocaleString()})`);
