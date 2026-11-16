// A market that isn't a 15-minute window (a long-dated BTC market; later politics, sports): its tile and its replay,
// ready to draw. The service sends window.summary / window.ready with kind "market" (docs/research-contract.md):
// absolute unix seconds everywhere (a market runs for weeks, so nothing here counts seconds from a start), prices
// 0–1, the outside line (Binance BTCUSDT for BTC price markets) as candle closes with each candle's high and low.
// Pure: no DOM, so it runs in tests too.
import { money, cents, shares, plural } from './format.js';

export const isMarket = x => !!x && typeof x === 'object' && x.kind === 'market';

// The market type a breakdown studies, from its plans (plan.proposed carries `market` {id, label, unit}); a plan from
// before market types is BTC 15-minute windows.
export const WINDOWS_15M = { id: 'btc-updown-15m', label: 'BTC Up or Down 15m', unit: 'window' };
export function marketTypeOf(inv, plan) {
  const p = plan || [...(inv.planOrder || [])].reverse().map(id => inv.plans[id]).find(Boolean);
  if (p && p.market) return p.market;
  if (inv.summaries && inv.summaries.length && inv.summaries.every(isMarket)) return { id: 'market', label: 'Markets', unit: 'market' };
  return WINDOWS_15M;
}

const MON = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
export const dateOf = t => { const d = new Date(t * 1000); return `${d.getUTCDate()} ${MON[d.getUTCMonth()]} ${d.getUTCFullYear()}`; };
export const shortDate = t => { const d = new Date(t * 1000); return `${d.getUTCDate()} ${MON[d.getUTCMonth()]}`; };
export const dateTime = t => `${shortDate(t)} ${new Date(t * 1000).toISOString().slice(11, 16)} UTC`;
export const days = s => { const d = s / 86400; return d < 1 ? `${Math.max(1, Math.round(s / 3600))} h` : `${d < 10 ? Math.round(d * 10) / 10 : Math.round(d)} days`; };

// What a tile counts as: made or lost money (resolved, or sold out before the end), or still open (valued at
// today's price: never counted as made or lost).
export function marketFacts(s) {
  const open = s.profit_kind === 'open', p = s.profit == null ? null : Math.round(s.profit * 100);
  return { open, made: !open && p != null && p > 0, lostMoney: !open && p != null && p < 0 };
}
export const MARKET_FILTERS = [['made', 'Made money', f => f.made], ['lostMoney', 'Lost money', f => f.lostMoney], ['open', 'Still open', f => f.open]];
export function filterMarkets(tiles, key) {
  const f = MARKET_FILTERS.find(x => x[0] === key);
  return f ? tiles.filter(s => f[2](marketFacts(s))) : tiles;
}
export function marketTally(tiles) {
  const n = { made: 0, lostMoney: 0, open: 0, decided: 0, profitMade: 0, profitLost: 0, profitOpen: 0, uncounted: 0 };
  for (const s of tiles) {
    const f = marketFacts(s);
    if (s.profit == null) { n.uncounted += 1; continue; }
    if (f.open) { n.open += 1; n.profitOpen += s.profit; continue; }
    n.decided += 1;
    if (f.made) { n.made += 1; n.profitMade += s.profit; } else if (f.lostMoney) { n.lostMoney += 1; n.profitLost += s.profit; }
  }
  return n;
}

// Strikes of one event held together ("What price will Bitcoin hit in November?"), or one market per candidate or date
// ("Who will win…?"): the events with 2+ of its markets. `strikes` when every one has a price in its question.
export function eventGroups(tiles) {
  const by = new Map();
  for (const s of tiles) if (s.event_slug) { const g = by.get(s.event_slug) || { event_slug: s.event_slug, title: s.event_title || s.event_slug, markets: [] }; g.markets.push(s); by.set(s.event_slug, g); }
  return [...by.values()].filter(g => g.markets.length > 1).map(g => ({ ...g, strikes: g.markets.every(s => s.rule && s.rule.strike) }))
    .sort((a, b) => b.markets.length - a.markets.length);
}

// Which side it bought in one market of an event, from dollars bought ({Yes: $, No: $}) or shares (a tile's `shares`).
export const sideBought = bought => { const k = Object.entries(bought || {}).filter(([, v]) => v > 0).map(([o]) => o); return k.length > 1 ? 'both sides' : k[0] || null; };
// An event's markets as "Yes on Lula, No on Bolsonaro", from the selection's events (every market it traded in the
// event, past the tiles shown) or, without them, from the tiles.
export function eventLegs(g, events) {
  const e = (events || []).find(x => x.event_slug === g.event_slug);
  const legs = e ? e.legs.map(l => ({ name: l.name, side: sideBought(l.bought_in_range), shown: l.shown }))
    : g.markets.map(s => ({ name: s.group_item || s.title, side: sideBought(s.shares), shown: true }));
  return { legs, markets: e ? e.markets : g.markets.length, shown: e ? e.shown : g.markets.length };
}
export const legsText = L => L.legs.filter(l => l.side).map(l => `${l.side === 'both sides' ? 'both sides of' : `${l.side} on`} ${l.name}`).join(', ');

// Each buy across markets: how many days before its market's end, at what price, in a market that made money, lost
// money or is still open. The cross-market view (Drew, 10 Nov: patterns across windows, not only single replays).
export function buyDots(tiles) {
  const out = [];
  for (const s of tiles) {
    const f = marketFacts(s), end = s.market_end;
    for (const e of s.entries || []) {
      if (e.action !== 'buy' || end == null) continue;
      out.push({ window_id: s.window_id, title: s.title, t: e.t, daysLeft: Math.max(0, (end - e.t) / 86400), price: 100 * e.price, side: e.side, usd: e.usd,
        outside: e.outside, strike: s.rule && s.rule.strike, made: f.made, lostMoney: f.lostMoney, open: f.open, profit: s.profit });
    }
  }
  return out;
}

// What resolves one market, in a few words for a chip (the rule's own sentence is in `says`).
// one leg of a "which / where / who" event is one outcome of several, decided by its deadline (never "By a date")
export const ruleChip = r => (!r || !r.kind ? null : r.kind === 'one_of' ? `One of several outcomes${r.deadline && !isNaN(Date.parse(r.deadline)) ? ` · by ${shortDate(Date.parse(r.deadline) / 1000)}` : ''}`
  : { touch_high: 'Any-time high', touch_low: 'Any-time low', close_above: 'One close, on a date', close_below: 'One close, on a date', all_time_high: 'New all-time high', result: 'Who wins', by_date: 'By a date', season: 'End of the season', match: 'One match' }[r.kind] || 'See its rules');

// How it got out (value.exit): sold, merged, both; held to the result; open; or not known (its merges weren't read).
const OUT = { sold: 'Sold out', merged: 'Merged out', sold_and_merged: 'Sold and merged out' };
export const exitWord = x => (x && OUT[x.how]) || null;
export const statusText = s => {
  if (s.profit_kind === 'open') return 'Open';
  const out = exitWord(s.exit);
  if (s.result) return out ? `${out}, resolved ${s.result}` : `Resolved ${s.result}`;
  return out || (s.profit_kind === 'closed' ? 'Sold out' : 'Closed');
};
export const profitWord = s => (s.profit_kind === 'open' ? 'open, at today\'s price' : s.profit_kind === 'closed' ? 'got out before the end' : 'from its fills and the payout');

const BURST_GAP = 3600; // fills of one outcome and action within an hour of each other draw as one mark

// The replay of one market, ready to draw. Times stay absolute (unix seconds).
export function prepMarket(r, summary) {
  const outcomes = r.outcomes || [];
  const prices = Object.fromEntries(outcomes.map(o => [o, ((r.prices || {})[o] || []).map(q => [q.t, q.p * 100])]));
  const out = r.outside ? { name: r.outside.name, unit: r.outside.unit, step: r.outside.step, pts: (r.outside.points || []).map(q => [q.t, q.p]), ranges: (r.outside.ranges || []).map(q => [q.t, q.h, q.l]), highest: r.outside.highest, lowest: r.outside.lowest } : null;
  const w = {
    kind: 'market', raw: r, id: r.window_id, title: r.title, from: r.axis.from, to: r.axis.to, start: r.axis.from, end: r.axis.to,
    outcomes, prices, out, rule: r.rule || {}, rules: r.rules, league: r.league || null, result: r.result, closed: r.closed, marketEnd: r.closed_at || r.market_end,
    marketStart: r.market_start, event: r.event_title, cov: r.coverage || {}, hold: r.hold || {}, value: r.value || {},
    moves: (r.moves || []).map((m, i) => ({ ...m, i })).sort((a, b) => a.t - b.t || a.i - b.i), exit: (r.value || {}).exit || null,
  };
  const back = (rows, t) => { let lo = 0, hi = rows.length - 1, best = null; while (lo <= hi) { const m = (lo + hi) >> 1; if (rows[m][0] <= t) { best = rows[m]; lo = m + 1; } else hi = m - 1; } return best; };
  w.priceAt = (o, t) => { const q = back(prices[o] || [], t); return q ? q[1] : null; };
  w.outAt = t => (out ? (back(out.pts, t) || [])[1] ?? null : null);
  w.trades = (r.trades || []).map((x, i) => ({ ...x, i, price: x.price * 100, liq: null })).sort((a, b) => a.t - b.t || a.i - b.i);
  w.pos = (r.position || []).map(p => [p.t, p.held || {}]);
  w.posAt = t => { let h = {}; for (const [tt, v] of w.pos) { if (tt <= t) h = v; else break; } return h; };
  w.match = prepMatch(r.match);
  // fills during the match draw a mark per minute, not per hour (a match is decided in 90 minutes)
  const ax = w.match && w.match.axis;
  w.bursts = marketBursts(w.trades, ax ? x => (x.t >= ax.from && x.t <= ax.to ? MATCH_BURST_GAP : null) : null);
  w.scoreAt = t => scoreAt(w.match, t);
  const v = r.value || {};
  w.totals = { cost: v.cost || 0, sold: v.sold_for || 0, payout: v.payout, valueNow: v.value_now, profit: v.profit, kind: v.profit_kind, note: summary && summary.profit_note, exit: v.exit || null };
  w.side = (summary && summary.spark_side) || outcomes[0];
  return w;
}

export function marketBursts(trades, gapFor = null) {
  const out = [], open = {};
  // a busy market (hundreds of fills over months) draws a mark per day or per six hours, not per hour
  const gap = trades.length > 400 ? 86400 : trades.length > 150 ? 6 * 3600 : BURST_GAP;
  for (const x of trades) {
    const own = gapFor && gapFor(x), k = x.side + x.action + (own ? 'm' : ''), b = open[k];
    if (b && x.t - b.t1 <= (own || gap)) { b.fills.push(x); b.t1 = x.t; continue; }
    open[k] = { side: x.side, action: x.action, t0: x.t, t1: x.t, fills: [x] };
    out.push(open[k]);
  }
  for (const b of out) {
    b.id = b.fills[0].trade_id; b.shares = b.fills.reduce((s, x) => s + x.shares, 0); b.usd = b.fills.reduce((s, x) => s + (x.usd || 0), 0);
    b.avg = b.shares ? (b.usd / b.shares) * 100 : 0;
    b.lo = Math.min(...b.fills.map(x => x.price)); b.hi = Math.max(...b.fills.map(x => x.price));
  }
  return out.sort((a, b) => a.t0 - b.t0);
}

// ---------- a match market's score line (r.match: Layer's recording of polymarket.com's live sports feed)
const MATCH_BURST_GAP = 60;
export const scoreText = s => String(s || '').replace('-', '–');

// The match as the replay draws it: goals (each score change, when the feed said so), periods, the clock, the
// final score and the match view's span. Null for any other market.
export function prepMatch(m) {
  if (!m) return null;
  const cov = m.coverage || {};
  return {
    home: m.home, away: m.away, side: m.side, kickoff: m.kickoff, firstLive: m.first_live_update, final: m.final,
    goals: m.goals || [], periods: m.periods || [], clock: (m.clock || []).map(c => [c.t, c.minute, c.period, c.score]),
    axis: m.axis, counts: m.counts || {}, recorded: !!cov.recorded && (cov.updates || 0) > 0, why: cov.why,
    gaps: cov.gaps || [], gapS: cov.gap_s || 0, updates: cov.updates || 0, corrections: cov.corrections || 0,
  };
}

// The match at t as the feed had it: {minute, period, score}, null before its first update.
export function scoreAt(m, t) {
  if (!m || !m.clock.length || t < m.clock[0][0]) return null;
  let lo = 0, hi = m.clock.length - 1;
  while (lo < hi) { const mid = (lo + hi + 1) >> 1; if (m.clock[mid][0] <= t) lo = mid; else hi = mid - 1; }
  const [, minute, period, score] = m.clock[lo];
  return { minute, period, score };
}

const PHASE = { pre_kickoff: 'before kick-off', half_time: 'at half-time', after_full_time: 'after full time', unknown: 'before the feed said the match had started' };
// One fill's match context in a few words: "54' · 0–2 · 31 s after a goal" (x.match is server-built).
export function matchText(x) {
  const m = x && x.match;
  if (!m) return '–';
  if (m.phase !== 'in_play') return PHASE[m.phase] ? `${PHASE[m.phase][0].toUpperCase()}${PHASE[m.phase].slice(1)}${m.phase === 'half_time' && m.score ? ` · ${scoreText(m.score)}` : ''}` : '–';
  const after = m.since_goal_s == null ? '' : m.since_goal_s < 90 ? ` · ${Math.round(m.since_goal_s)} s after a goal` : m.since_goal_s < 600 ? ` · ${Math.round(m.since_goal_s / 60)} min after a goal` : '';
  return `${m.minute != null ? `${m.minute}' · ` : ''}${scoreText(m.score)}${after}${m.in_gap ? ' · in a recording gap' : ''}`;
}

// A goal's label on the chart: "0–1 45'", a goal the feed took back "1–3 66', taken back".
export const goalLabel = g => `${scoreText(g.score)}${g.minute != null ? ` ${g.minute}'` : ''}${g.retracted ? ', taken back' : ''}`;

// A merge, split or conversion in words ("Merges 3,200 pairs of Yes and No into $3,200").
export function moveText(w, m) {
  const pair = (w.outcomes || []).join(' and ');
  if (m.kind === 'merge') return `Merges ${shares(m.shares)} pairs of ${pair} into ${money(m.usd || m.shares)}, $1 a pair. Holding ${heldText(w, m.t)}.`;
  if (m.kind === 'split') return `Splits ${money(m.usd || m.shares)} into ${shares(m.shares)} pairs of ${pair}. Holding ${heldText(w, m.t)}.`;
  return `Converts ${shares(m.shares)} shares across this event's markets (Polymarket doesn't list which sides), so its position here isn't counted.`;
}
export const moveTitle = m => ({ merge: 'Merges out', split: 'Splits dollars into pairs', conversion: 'Converts shares' }[m.kind] || 'Moves shares');

export const heldText = (w, t) => { const h = w.posAt(t), a = Object.entries(h).filter(([, v]) => v >= 0.01).map(([o, v]) => `${shares(v)} ${o}`); return a.length ? a.join(' and ') : 'nothing'; };
const range = b => (Math.round(b.lo) === Math.round(b.hi) ? cents(b.lo) : `${cents(b.lo)}–${cents(b.hi)}`);
export const usdt = v => '$' + Math.round(v).toLocaleString('en-US');

export function marketBurstText(w, b) {
  const o = w.outAt(b.t0), k = w.rule && w.rule.strike;
  const verb = b.action === 'buy' ? 'Buys' : 'Sells';
  return `${verb} ${shares(b.shares)} ${b.side} in ${plural(b.fills.length, 'fill')}${b.t1 > b.t0 ? ` over ${days(b.t1 - b.t0)}` : ''}, at ${range(b)} (${money(b.usd)}). `
    + (o != null ? `${w.out.name} was ${usdt(o)}${k ? `, ${Math.abs(Math.round(1000 * (k - o) / o) / 10)}% ${k >= o ? 'below' : 'above'} the ${usdt(k)} in the question` : ''}. ` : '')
    + (w.match && b.fills[0].match ? `The match: ${matchText(b.fills[0])}. ` : '')
    + `Holding ${heldText(w, b.t1)}.`;
}

// The default walkthrough, from the data alone (no readings): its first buy, its biggest buys and sells, and the end
// (the resolution, or today for a market still held). The agent's walkthrough replaces it.
export function marketAutoSteps(w, maxBursts = 6) {
  const st = [];
  if (w.bursts.length) {
    const first = w.bursts[0];
    st.push({ t: first.t0, title: `First ${first.action === 'buy' ? 'buy' : 'sell'}: ${first.side}`, observed: marketBurstText(w, first), trade_ids: first.fills.map(x => x.trade_id) });
  }
  const big = w.bursts.slice(1).sort((a, b) => b.usd - a.usd).slice(0, maxBursts).sort((a, b) => a.t0 - b.t0);
  for (const b of big) st.push({ t: b.t0, title: `${b.action === 'buy' ? 'Buys' : 'Sells'} ${shares(b.shares)} ${b.side}`, observed: marketBurstText(w, b), trade_ids: b.fills.map(x => x.trade_id) });
  for (const m of (w.moves || []).filter(m => m.kind !== 'merge' || m.shares >= 1).slice(0, maxBursts)) st.push({ t: m.t, title: moveTitle(m), observed: moveText(w, m), move: true });
  const T = w.totals, x = T.exit;
  const endT = Math.min(w.to, w.marketEnd || w.to);
  if (x && x.t && OUT[x.how] && w.result && x.t < endT) st.push({ t: x.t, title: `${OUT[x.how]} before the result`, observed: `Holding nothing from ${dateTime(x.t)}${x.merged_pairs ? `, after merging ${shares(x.merged_pairs)} pairs into ${money(x.merged_usd)}` : ''}. It spent ${money(T.cost)} and got back ${money(T.sold)} before the market resolved.` });
  st.sort((a, b) => a.t - b.t);
  if (T.kind === 'open') st.push({ t: w.to, title: 'Still held', observed: `Holding ${heldText(w, w.to)} on ${dateOf(w.to)}, worth ${T.valueNow == null ? 'an unknown amount' : money(T.valueNow)} at the latest price. It spent ${money(T.cost)}${T.sold ? ` and sold for ${money(T.sold)}` : ''}${T.profit == null ? '' : `: ${T.profit < 0 ? '−' : '+'}${money(T.profit)} so far, open, at today's price`}.` });
  else st.push({ t: endT, title: w.result ? `Resolves ${w.result}` : exitWord(x) || 'Sold out', observed: w.result ? `${w.title} resolved ${w.result}. Holding ${heldText(w, endT)}, the ${w.result} shares pay ${money(T.payout || 0)}. It spent ${money(T.cost)}${T.sold ? ` and ${x && x.merged_pairs ? 'got back' : 'sold for'} ${money(T.sold)}` : ''}${T.profit == null ? '' : `: ${T.profit < 0 ? '−' : '+'}${money(T.profit)} on this market, from its fills`}.` : `It ${x && x.how === 'merged' ? 'merged' : x && x.how === 'sold_and_merged' ? 'sold and merged' : 'sold'} out of this market before the end. It spent ${money(T.cost)} and ${x && x.merged_pairs ? 'got back' : 'sold for'} ${money(T.sold)}${T.profit == null ? '' : `: ${T.profit < 0 ? '−' : '+'}${money(T.profit)}`}.` });
  return st.map((x, i) => ({ index: i, inferred: null, trade_ids: [], annotations: [], ...x, auto: true }));
}

// The agent's walkthrough for a market: its times are unix seconds already.
export const marketAgentSteps = (w, steps) => steps.map((x, i) => ({ index: i, ...x }));
