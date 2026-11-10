// One window's replay, ready to draw: window.ready (absolute unix seconds, prices 0–1) turned into seconds from the
// window's start (negative = before the open), cents, dense per-second lookups, buys grouped into bursts, and the
// default walkthrough when the agent hasn't sent one. Pure: no DOM, so it runs in tests too.
import { money, cents, shares, btc, signedBtc, clock, plural, mmss } from './format.js';

const BURST_GAP = 10; // fills of one side and action within 10 s of each other draw as one mark

export function prep(r, summary) {
  const s = r.start, rel = t => Math.round(t - s);
  const from = Math.min(rel(r.axis.from), 0), to = Math.max(rel(r.axis.to), r.end - s);
  const n = to - from + 1, ix = t => Math.round(t) - from;
  const dense = rows => { const a = new Array(n).fill(null); for (const q of rows || []) { const i = ix(rel(q.t)); if (i >= 0 && i < n) a[i] = q; } return a; };
  const cov = r.coverage || {};
  const holes = (cov.missing_seconds || []).map(([a, len]) => [a - s, len]);
  const inHole = t => holes.some(([a, len]) => t >= a && t < a + len);
  const bnRows = dense(r.binance), clRows = r.chainlink ? dense(r.chainlink) : null;
  const upRows = dense(r.up), dnRows = dense(r.down);
  const w = {
    raw: r, id: r.window_id, start: s, end: r.end - s, from, to, title: r.title, ptb: r.price_to_beat, final: r.final_price,
    result: r.result, cov, holes, inHole,
    lost: (cov.lost || []).map(l => ({ from: l.from - s, to: l.to - s, why: l.why })),
    hasBook: !!cov.book && (r.up || []).length > 0, hasCL: !!r.chainlink && r.chainlink.length > 0,
    clFull: cov.chainlink === 'full',
    mf: r.minute_fallback ? { up: r.minute_fallback.up.map(q => [rel(q.t), q.p * 100]), down: r.minute_fallback.down.map(q => [rel(q.t), q.p * 100]) } : null,
  };
  // lookups: the value at a second, or the last one before it (within 5 s for prices, so a gap stays a gap)
  const back = (rows, t, f, lim = 5) => { for (let i = ix(t), k = 0; i >= 0 && k <= lim; i--, k++) if (rows[i]) return f(rows[i]); return null; };
  w.bn = t => back(bnRows, t, q => q.p, 30);
  w.cl = t => clRows ? back(clRows, t, q => q.p, 0) : null; // a second the feed skipped stays missing
  w.up = t => (w.hasBook && !inHole(t)) ? back(upRows, t, q => [q.bid * 100, q.ask * 100]) : null;
  w.down = t => (w.hasBook && !inHole(t)) ? back(dnRows, t, q => [q.bid * 100, q.ask * 100]) : null;
  w.upMinute = t => { if (!w.mf) return null; let v = null; for (const [tt, p] of w.mf.up) { if (tt <= t) v = p; else break; } return v; };
  w.bn0 = r.binance_at_start ?? w.bn(0); // Binance BTCUSDT at the start: BTC in Tether, about 0.1% from Chainlink
  // BTC's move from where the window started: Chainlink BTC/USD against the price to beat when recorded, else
  // Binance BTCUSDT against its own price at the start (the two are different prices; neither stands in for the other)
  w.move = t => { const c = w.cl(t); if (c != null && t >= 0) return c - w.ptb; const b = w.bn(t); return b == null || w.bn0 == null ? null : b - w.bn0; };
  w.moveSource = t => (w.cl(t) != null && t >= 0) ? 'Chainlink BTC/USD against the price to beat' : 'Binance BTCUSDT from its price at the start';

  w.trades = (r.trades || []).map((x, i) => ({
    ...x, i, t: rel(x.t), price: x.price * 100,
    liq: x.liquidity ?? (x.paid_ask === true ? 'taker' : x.paid_ask === false ? 'maker' : null),
  })).sort((a, b) => a.t - b.t || a.i - b.i);
  w.pos = (r.position || []).map(p => [rel(p.t), p.up, p.down]).sort((a, b) => a[0] - b[0]);
  w.posAt = t => { let u = 0, d = 0; for (const [tt, a, b] of w.pos) { if (tt <= t) { u = a; d = b; } else break; } return [u, d]; };
  w.bursts = bursts(w.trades);
  const buys = w.trades.filter(x => x.action === 'buy'), sells = w.trades.filter(x => x.action === 'sell');
  const [fu, fd] = w.posAt(to);
  w.totals = { cost: sum(buys, 'usd'), sold: sum(sells, 'usd'), up: fu, down: fd };
  w.totals.payout = w.result === 'Up' ? fu : w.result === 'Down' ? fd : 0;
  w.totals.profit = w.totals.payout + w.totals.sold - w.totals.cost;
  // the service's own figures win when it sent them, so the tile and the replay never disagree
  if (summary && summary.profit != null) Object.assign(w.totals, { cost: summary.cost, sold: summary.sold_for || 0, payout: summary.payout, profit: summary.profit, note: summary.profit_note });
  w.pre = w.trades.filter(x => x.t < 0);
  w.both = w.pos.some(([, a, b]) => a > 0 && b > 0);
  return w;
}

const sum = (rows, k) => rows.reduce((s, x) => s + (x[k] || 0), 0);

export function bursts(trades) {
  const out = [], open = {};
  for (const x of trades) {
    const k = x.side + x.action, b = open[k];
    if (b && x.t - b.t1 <= BURST_GAP) { b.fills.push(x); b.t1 = x.t; continue; }
    open[k] = { side: x.side, action: x.action, t0: x.t, t1: x.t, fills: [x] };
    out.push(open[k]);
  }
  for (const b of out) {
    b.id = b.fills[0].trade_id; b.shares = sum(b.fills, 'shares'); b.usd = sum(b.fills, 'usd');
    b.avg = b.shares ? b.usd / b.shares * 100 : 0;
    b.lo = Math.min(...b.fills.map(x => x.price)); b.hi = Math.max(...b.fills.map(x => x.price));
    b.taker = b.fills.filter(x => x.liq === 'taker').length; b.maker = b.fills.filter(x => x.liq === 'maker').length;
    b.unknown = b.fills.length - b.taker - b.maker;
  }
  return out.sort((a, b) => a.t0 - b.t0);
}

export const posText = (w, t) => { const [u, d] = w.posAt(t), a = []; if (u > 0) a.push(`${shares(u)} Up`); if (d > 0) a.push(`${shares(d)} Down`); return a.length ? a.join(' and ') : 'nothing'; };
const priceRange = b => (Math.round(b.lo) === Math.round(b.hi) ? cents(b.lo) : `${cents(b.lo)}–${cents(b.hi)}`);
const liqText = b => {
  const p = [];
  if (b.taker) p.push(`${b.taker} paid the asking price`);
  if (b.maker) p.push(`${b.maker} ${b.maker === 1 ? 'was a resting buy' : 'were resting buys'} filled`);
  if (b.unknown) p.push(`${b.unknown} can't be checked (no recorded book then)`);
  return p.join(', ');
};
export const burstText = (w, b) => {
  const verb = b.action === 'buy' ? 'Buys' : 'Sells';
  const dur = b.t1 - b.t0, mv = w.move(b.t0);
  return `${verb} ${shares(b.shares)} ${b.side} in ${plural(b.fills.length, 'fill')}${dur ? ` over ${dur} s` : ''}, at ${priceRange(b)} (${money(b.usd)}). `
    + `${liqText(b)}. `
    + (b.t0 < 0 ? `That's ${-b.t0} s before the window opens. ` : mv != null ? `BTC was ${signedBtc(mv)} (${w.moveSource(b.t0)}). ` : '')
    + `Holding ${posText(w, b.t1)}.`;
};

// The default walkthrough, from the data alone (no readings): before the open, the buys before it, the open, the
// window's biggest bursts, the result. The agent's walkthrough.ready replaces it.
export function autoSteps(w, maxBursts = 6) {
  const st = [];
  const pre = w.bursts.filter(b => b.t0 < 0), after = w.bursts.filter(b => b.t0 >= 0);
  if (pre.length) {
    const f = pre.flatMap(b => b.fills), su = sum(f.filter(x => x.side === 'Up'), 'shares'), sd = sum(f.filter(x => x.side === 'Down'), 'shares');
    st.push({ t: w.from, title: 'Before the window opens', observed: `The market trades before the start. There is no price to beat yet: it's set from Chainlink BTC/USD at ${clock(w.start)} UTC.`, annotations: [{ kind: 'region', t0: w.from, t1: 0, label: 'before the open' }] });
    st.push({ t: pre[0].t0, title: 'Buys before the open', trade_ids: f.map(x => x.trade_id),
      observed: `${plural(f.length, 'fill')} before the start, the first ${-pre[0].t0} s early: ${[su > 0 && `${shares(su)} Up`, sd > 0 && `${shares(sd)} Down`].filter(Boolean).join(' and ')} for ${money(sum(f, 'usd'))}.`,
      annotations: [{ kind: 'span', t0: pre[0].t0, t1: 0, label: `${-pre[0].t0} s early` }] });
  }
  const up0 = w.up(0);
  st.push({ t: 0, title: 'The window opens', observed: `Price to beat ${btc(w.ptb)}, Chainlink BTC/USD at ${clock(w.start)} UTC.${up0 ? ` The Up price on Polymarket is ${cents(up0[0])}/${cents(up0[1])}.` : ''} Holding ${posText(w, 0)}.` });
  const big = [...after].sort((a, b) => b.usd - a.usd).slice(0, maxBursts).sort((a, b) => a.t0 - b.t0);
  for (const b of big) st.push({ t: b.t0, title: `${b.action === 'buy' ? 'Buys' : 'Sells'} ${shares(b.shares)} ${b.side}`, observed: burstText(w, b), trade_ids: b.fills.map(x => x.trade_id),
    annotations: b.t1 > b.t0 ? [{ kind: 'span', t0: b.t0, t1: b.t1, label: `${b.t1 - b.t0} s` }] : [{ kind: 'point', t0: b.t0, label: `${b.fills.length} fills` }] });
  const T = w.totals;
  st.push({ t: w.end, title: `Resolves ${w.result}`, observed: `Chainlink BTC/USD finished at ${btc(w.final)} against the price to beat of ${btc(w.ptb)}, so ${w.result} won. Holding ${posText(w, w.end)}, the ${w.result} shares pay ${money(T.payout)}. It spent ${money(T.cost)}${T.sold ? ` and sold for ${money(T.sold)}` : ''}: ${T.profit < 0 ? '−' : '+'}${money(T.profit)} on this window, from its fills.` });
  return st.map((x, i) => ({ index: i, inferred: null, trade_ids: [], annotations: [], ...x, auto: true }));
}

// A walkthrough from the agent: its times may be unix seconds; the replay works in seconds from the start.
export const agentSteps = (w, steps) => steps.map((x, i) => ({ index: i, ...x, t: x.t > 1e9 ? x.t - w.start : x.t,
  annotations: (x.annotations || []).map(a => ({ ...a, t0: a.t0 > 1e9 ? a.t0 - w.start : a.t0, t1: a.t1 > 1e9 ? a.t1 - w.start : a.t1 })) }));

export const fmtWhen = (w, t) => `${mmss(t)} · ${clock(w.start + t)} UTC`;
