// The workspace for a market type whose unit is a market (long-dated BTC; later politics, sports): one tile per
// market, every buy across markets on one chart, one market's replay over the weeks it was held, and its fills.
// Same stage slots as the 15-minute windows (views.js), drawn from kind "market" tiles and replays (marketdata.js).
import { html, useState, useEffect, useRef, useMemo } from '../vendor/htm-preact-3.1.1.module.js';
import { money, signedMoney, cents, shares, plural } from './format.js';
import { flagsFor, splitFlagged } from './store.js';
import { MARKET_FILTERS, filterMarkets, marketTally, eventGroups, eventLegs, legsText, buyDots, ruleChip, statusText, profitWord, exitWord, moveText, dateOf, shortDate, dateTime, days, heldText, usdt, marketFacts, marketBursts, matchText, goalLabel, scoreText } from './marketdata.js';

// a text with the numbers the check flagged struck where they stand (as views.js `flagged`)
const flagged = (text, flags) => splitFlagged(text, flags).map(p => (p.flag ? html`<span class="flagnum" title="Didn't match the data">${p.text}</span>` : p.text));
const stepWord = s => ({ 60: 'minute', 900: '15 minutes', 3600: 'hour', 14400: '4 hours' }[s] || `${Math.round(s / 60)} minutes`);
// sides are neutral colours (never good or bad): the first outcome (Yes) and the second (No)
const sideColor = (w, o) => ((w.outcomes || []).indexOf(o) === 1 ? 'var(--down)' : 'var(--up)');

export function useWidth(fallback = 760) {
  const [wd, setW] = useState(fallback), ro = useRef(null);
  const ref = el => {
    if (ro.current) { ro.current.disconnect(); ro.current = null; }
    if (!el) return;
    ro.current = new ResizeObserver(([e]) => setW(Math.max(280, Math.floor(e.contentRect.width))));
    ro.current.observe(el);
  };
  useEffect(() => () => ro.current && ro.current.disconnect(), []);
  return [ref, wd];
}

// ---------- tiles: one per market
function MarketSpark({ s, width = 200, height = 54 }) {
  const pts = s.spark || [];
  if (!pts.length) return html`<svg viewBox=${`0 0 ${width} ${height}`} aria-hidden="true"><rect width=${width} height=${height} fill="url(#rhatch)" /></svg>`;
  const from = Math.min(pts[0].t, ...(s.entries || []).map(e => e.t)), to = Math.max(pts[pts.length - 1].t, s.end || 0);
  const X = t => 2 + (t - from) / Math.max(1, to - from) * (width - 4), Y = p => 3 + (1 - p) * (height - 16);
  const d = pts.map((p, i) => (i ? 'L' : 'M') + X(p.t).toFixed(1) + ' ' + Y(p.p).toFixed(1)).join('');
  const col = o => ((s.outcomes || []).indexOf(o) === 1 ? 'var(--down)' : 'var(--up)');
  return html`<svg viewBox=${`0 0 ${width} ${height}`} aria-hidden="true">
    <line x1="2" x2=${width - 2} y1=${Y(0.5)} y2=${Y(0.5)} stroke="var(--line)" stroke-dasharray="2 2" />
    <path d=${d} fill="none" stroke=${col(s.spark_side)} stroke-width="1.3" />
    ${(s.entries || []).map(e => html`<line x1=${X(e.t)} x2=${X(e.t)} y1=${e.action === 'buy' ? height - 10 : height - 6} y2=${e.action === 'buy' ? height - 6 : height - 1} stroke=${col(e.side)} stroke-width="1" opacity=".75" />`)}</svg>`;
}

export function MarketsStage({ inv, ui, act, plan, live, borrowed }) {
  const all = inv.summaries;
  const waits = plan && (plan.status === 'proposed' || plan.status === 'queued');
  const empty = inv.winsLoading ? 'Loading its markets…' : waits ? 'Markets appear here once the plan starts.'
    : live || inv.starting || !inv.done ? 'Markets appear here as they are read.' : "This question didn't need markets. What it found is in the column.";
  if (!all.length) return html`<div class="ov"><div class="ghostbox">${empty}</div></div>`;
  const hl = ui.hl, n = marketTally(all), tiles = filterMarkets(all, ui.wf), groups = eventGroups(all);
  const sel = inv.coverage && inv.coverage.per_source && inv.coverage.per_source.selection;
  const fl = MARKET_FILTERS.find(f => f[0] === ui.wf), cnt = k => all.filter(s => marketFacts(s)[k]).length;
  return html`<div class="ov">
    ${borrowed && html`<p class="muted small">${borrowed.named ? 'The markets its findings read, from your earlier question.' : 'Markets from your earlier question: this one read none of its own.'}</p>`}
    ${sel && html`<p class="muted small">${sel.label}: its ${plural(sel.shown, 'market')} with the most money traded from ${shortDate(sel.from)} to ${shortDate(sel.to)}${sel.matched > sel.shown ? `, of ${sel.matched} that match` : ''}${sel.markets_traded > sel.markets_looked_at ? ` (the ${sel.markets_looked_at} markets it traded most were checked, of ${sel.markets_traded})` : ''}${sel.min_days > 0 ? `; only markets that run ${sel.min_days} days or more${sel.also_short ? `, and ${sel.also_short} whatever their length` : ''}` : ''}.${sel.trades_complete === false ? ` It trades so often that only ${shortDate(sel.from)} onward was read (newest first, up to 30,000 trades), not all ${Math.round((sel.to - (sel.asked_from || sel.from)) / 86400)} days asked for.` : ''}</p>`}
    <p class="tally">${n.decided > 0 ? html`Made money in <b>${n.made} of ${plural(n.decided, 'market')}</b> that ended or it sold out of (<span class="gain">${signedMoney(n.profitMade)}</span>) and lost money in <b>${n.lostMoney}</b> (<span class="loss">${signedMoney(n.profitLost)}</span>).` : 'No market here has ended or been sold out of yet.'}
      ${n.open > 0 && html` <b>${plural(n.open, 'market')}</b> still open: <b class=${n.profitOpen >= 0 ? 'gain' : 'loss'}>${signedMoney(n.profitOpen)}</b> at today's prices, not a result.`}
      ${n.uncounted > 0 && html` ${plural(n.uncounted, 'market')} not counted: it sold shares its fills don't show it buying.`}</p>
    ${sel && sel.near_left_out && sel.near_left_out.says ? html`<p class="muted small">${sel.near_left_out.says}${(sel.skipped_near || []).length ? html` For example ${sel.skipped_near.slice(0, 3).map((x, i) => html`${i ? '; ' : ''}“${x.question}”`)}.` : ''}</p>`
      : sel && (sel.skipped_near || []).length > 0 && html`<p class="muted small">Read and left out as not ${sel.label.toLowerCase()} by Polymarket's own tags: ${sel.skipped_near.slice(0, 3).map((x, i) => html`${i ? '; ' : ''}“${x.question}” (${x.category})`)}.</p>`}
    ${groups.filter(g => g.strikes).length > 0 && html`<p class="muted small">Several strikes of one event: ${groups.filter(g => g.strikes).slice(0, 3).map((g, i) => html`${i ? '; ' : ''}<b>${g.title}</b> (${plural(g.markets.length, 'market')})`)}.</p>`}
    ${groups.filter(g => !g.strikes).length > 0 && html`<div class="muted small evlegs">Several markets of one event: <ul>${groups.filter(g => !g.strikes).slice(0, 4).map(g => { const L = eventLegs(g, sel && sel.events); return html`<li><b>${g.title}</b>: ${legsText(L)}${L.markets > L.shown ? ` (${L.shown} of its ${L.markets} markets shown)` : ''}.</li>`; })}</ul></div>`}
    <div class="wfilter" role="group" aria-label="Show markets">
      <button class=${!ui.wf ? 'on' : ''} onClick=${() => act.filter(null)}>All · ${all.length}</button>
      ${MARKET_FILTERS.map(([k, label]) => html`<button class=${ui.wf === k ? 'on' : ''} disabled=${!cnt(k)} onClick=${() => act.filter(k)}>${label} · ${cnt(k)}</button>`)}</div>
    <${EveryBuyChart} tiles=${tiles} act=${act} />
    <p class="muted small">Each tile is one market over the time it was held: the price of the side it bought most, its buys (lower ticks) and sells (upper ticks). Click one to replay it.${fl ? ` Showing only: ${fl[1].toLowerCase()}.` : ''}</p>
    ${hl && html`<div class="hl"><span>Showing <b>${hl.label}</b>: matching markets outlined.</span><button class="link" onClick=${() => act.clearHl()}>Show all</button></div>`}
    <div class="tiles mtiles">${tiles.map(s => {
      const cls = hl ? (hl.match.has(s.window_id) ? 'match' : (hl.base && hl.base.has(s.window_id) ? '' : 'dim')) : '';
      const c = s.coverage || {}, rc = ruleChip(s.rule);
      return html`<button class=${'tile mtile ' + cls} key=${s.window_id} onClick=${() => act.openWin(s.window_id)} aria-label=${s.title}>
        <div class="mt">${s.title}</div>
        ${s.match && html`<div class="mscore">${s.match.recorded ? html`${s.match.home} <b>${s.match.final ? scoreText(s.match.final.score) : 'v'}</b> ${s.match.away}${(s.match.counts || {}).buys ? html` · <span title="Buys while the match was being played, by the recorded score">${plural((s.match.counts.buys_in_play || {}).fills || 0, 'buy')} in play</span>` : ''}` : html`<span class="muted">No score recorded</span>`}</div>`}
        <div class="tt"><span>${shortDate(s.start)} → ${s.open ? 'now' : shortDate(s.end)}</span><span class=${s.open ? 'open' : 'res'}>${statusText(s)}</span></div>
        <${MarketSpark} s=${s} />
        <div class="tf"><span>${plural((s.entries || []).length, 'fill')} · held ${s.held_days == null ? '–' : days(s.held_days * 86400)}</span><span class=${s.profit == null ? 'muted' : s.profit >= 0 ? 'gain' : 'loss'}>${s.profit == null ? 'not counted' : signedMoney(s.profit)}${s.open && s.profit != null ? ' open' : ''}</span></div>
        <div class="badges">${s.league && html`<span class="badge" title="League or competition">${s.league}</span>`}${rc && html`<span class="badge" title=${(s.rule || {}).says || ''}>${rc}</span>`}${s.group_item && s.event_title && html`<span class="badge" title=${s.event_title}>${s.group_item}</span>`}
          ${(s.moves || []).some(m => m.kind === 'merge') && html`<span class="badge">merged</span>`}${c.moves_read === false && html`<span class="badge warn" title="Its merges and splits couldn't be read, so whether it held to the end isn't known">merges unread</span>`}${Object.values(s.shares || {}).filter(v => v > 0).length > 1 && html`<span class="badge">both sides</span>`}
          ${c.fills_complete === false && html`<span class="badge warn" title=${c.shares_not_from_fills ? 'It sold more shares than its fills bought: the rest came some way fills don\'t show, such as splitting dollars into both outcomes' : 'Polymarket listed more fills than one read holds'}>${c.shares_not_from_fills ? 'shares not from fills' : 'fills cut short'}</span>`}</div></button>`;
    })}</div></div>`;
}

// ---------- every buy across markets: days before its market's end against the price paid
function EveryBuyChart({ tiles, act }) {
  const [box, width] = useWidth();
  const pts = useMemo(() => buyDots(tiles), [tiles]);
  if (!pts.length) return null;
  const H = 240, L = 44, R = 12, T = 12, B = 30;
  const maxD = Math.max(7, ...pts.map(p => p.daysLeft));
  // one market listed years ahead (a 2028 nomination) would squeeze every other buy into the right edge: then the
  // days are drawn on a square-root scale, and the axis says so
  const sorted = pts.map(p => p.daysLeft).sort((a, b) => a - b), p90 = sorted[Math.floor(0.9 * (sorted.length - 1))];
  const root = maxD > 4 * Math.max(7, p90), f = d => (root ? Math.sqrt(d) : d);
  const X = d => L + (1 - f(d) / f(maxD)) * (width - L - R), Y = c => T + (1 - c / 100) * (H - T - B);
  const fill = p => (p.open ? 'none' : p.made ? 'var(--gain)' : p.lostMoney ? 'var(--loss)' : 'var(--faint)');
  const stroke = p => (p.open ? 'var(--fg)' : 'none');
  // a phone has room for three labels ("326 d before" is wide: a season's futures are listed a year ahead)
  const narrow = width < 520;
  const ticksD = (narrow ? (root ? [maxD, maxD / 4, 0] : [maxD, maxD / 2, 0])
    : root ? [maxD, maxD * 0.5625, maxD / 4, maxD / 16, 0] : [maxD, maxD * 0.75, maxD / 2, maxD / 4, 0]).map(d => Math.round(d));
  const n = new Set(pts.map(p => p.window_id)).size, high = pts.filter(p => p.price >= 90).length;
  return html`<figure class="allwin">
    <div class="allwin-head"><b>Every buy, across ${plural(n, 'market')}: how long before the end, at what price</b></div>
    <div ref=${box}><svg viewBox=${`0 0 ${width} ${H}`} width=${width} height=${H} role="img" aria-label="Every buy: days before its market's end against the price paid, in cents a share">
      ${[0, 25, 50, 75, 100].map(c => html`<g><line x1=${L} x2=${width - R} y1=${Y(c)} y2=${Y(c)} stroke="var(--line)" /><text class="axs" x=${L - 6} y=${Y(c) + 4} text-anchor="end">${c}¢</text></g>`)}
      ${ticksD.map((d, i) => html`<text class="axs" x=${X(d)} y=${H - 10} text-anchor=${i === 0 ? 'start' : i === ticksD.length - 1 ? 'end' : 'middle'}>${d === 0 ? 'the end' : `${d} d before`}</text>`)}
      ${pts.map(p => html`<circle cx=${X(p.daysLeft)} cy=${Y(p.price)} r=${Math.min(7, 2.4 + Math.sqrt(p.usd || 0) / 30)} fill=${fill(p)} fill-opacity=".55" stroke=${stroke(p)} stroke-opacity=".6" onClick=${() => act.openWin(p.window_id)}>
        <title>${`${p.title}: bought ${p.side} at ${cents(p.price)} for ${money(p.usd || 0)}, ${days(p.daysLeft * 86400)} before the end${p.outside != null ? `; Binance BTCUSDT ${usdt(p.outside)}` : ''}. ${p.open ? 'Still open.' : p.profit == null ? '' : `The market ${signedMoney(p.profit)} from its fills.`} Click to open it.`}</title></circle>`)}
    </svg></div>
    <figcaption class="muted small">
      <span class="keys"><span class="key"><i style="background:var(--gain)"></i>market made money</span><span class="key"><i style="background:var(--loss)"></i>market lost money</span><span class="key"><i style="border:1px solid var(--fg)"></i>still open</span></span>
      <span>Each dot is one buy: how many days before its market's end (left: earlier${root ? '; days on a square-root scale, so the last weeks get more room' : ''}), and the price paid (a price is the market's chance). Size: dollars paid. ${high ? `${high} of ${pts.length} buys were at 90¢ or more.` : ''}</span></figcaption>
  </figure>`;
}

// ---------- one market's replay
function chartGeom(w, W, compact) {
  const ml = compact ? 8 : 74, mr = compact ? 8 : 112, top = w.matchView ? 16 + (labelRows(compact) + 1) * LABEL_ROW_H : 10;
  // no outside line (politics): no empty panel for it, the market's own price comes first
  const hB = !w.out ? 0 : compact ? 120 : 180, hP = compact ? 90 : 120, hQ = compact ? 50 : 70, g = compact ? 10 : 18, ax = 26;
  const yB0 = top, yP0 = yB0 + hB + (w.out ? g : 6), yQ0 = yP0 + hP + g, H = yQ0 + hQ + ax;
  const X = t => ml + (t - w.from) / Math.max(1, w.to - w.from) * (W - ml - mr);
  const tOf = px => Math.max(w.from, Math.min(w.to, Math.round(w.from + (px - ml) / (W - ml - mr) * (w.to - w.from))));
  let lo = Infinity, hi = -Infinity;
  for (const [, h, l] of (w.out ? w.out.ranges : [])) { lo = Math.min(lo, l); hi = Math.max(hi, h); }
  for (const [, p] of (w.out ? w.out.pts : [])) { lo = Math.min(lo, p); hi = Math.max(hi, p); }
  const k = w.rule && w.rule.strike;
  if (k && isFinite(lo)) { lo = Math.min(lo, k); hi = Math.max(hi, k); }
  if (!isFinite(lo)) { lo = 0; hi = 1; }
  const pad = (hi - lo) * 0.08 || 1; lo -= pad; hi += pad;
  const YB = v => yB0 + hB - (v - lo) / (hi - lo) * hB, YP = c => yP0 + hP - c / 100 * hP;
  let qmax = 1; for (const [, h] of w.pos) for (const v of Object.values(h)) qmax = Math.max(qmax, v);
  const YQ = v => yQ0 + hQ - Math.max(0, v) / qmax * (hQ - 4);
  return { ml, mr, W, H, yB0, hB, yP0, hP, yQ0, hQ, X, tOf, YB, YP, YQ, lo, hi, compact };
}

function dateTicks(w, n) {
  if (w.to - w.from < 2 * 86400) {  // the match view: times of day, every 15 minutes to 6 hours
    const span = w.to - w.from, st = [900, 1800, 3600, 7200, 21600].find(s => span / s <= n) || 43200, out = [];
    for (let t = Math.ceil(w.from / st) * st; t <= w.to; t += st) out.push(t);
    return out;
  }
  const span = w.to - w.from, stepD = [1, 2, 7, 14, 30, 60].find(d => span / (d * 86400) <= n) || 90, out = [];
  for (let t = Math.ceil(w.from / 86400 / stepD) * stepD * 86400; t <= w.to; t += stepD * 86400) out.push(t);
  return out;
}

// The match on the chart: in the match view its halves and half-time, kick-off, full time, each goal (when the feed
// said so; one it took back dashed) and the recording's gaps (hatched); in the whole market's view a band for it.
const LABEL_ROW_H = 13, labelRows = compact => (compact ? 4 : 3);
function matchMarks(w, G) {
  const m = w.match, y0 = G.yP0, y1 = G.yQ0 + G.hQ, out = [], vis = t => t >= w.from && t <= w.to, cx = t => Math.max(G.ml, Math.min(G.W - G.mr, G.X(t)));
  if (!w.matchView) {
    const a = m.axis.from, b = m.axis.to;
    if (b < w.from || a > w.to) return out;
    out.push(html`<rect x=${cx(a)} y=${y0} width=${Math.max(2, cx(b) - cx(a))} height=${y1 - y0} fill="var(--accent)" opacity=".08"><title>The match: open “The match” to see it minute by minute</title></rect>`);
    return out;
  }
  for (const p of m.periods) {
    const a = p.from, b = p.to || w.to;
    if (b < w.from || a > w.to) continue;
    const brk = p.period === 'HT' || p.period === 'ETHT';
    if (brk) out.push(html`<rect x=${cx(a)} y=${y0} width=${Math.max(1, cx(b) - cx(a))} height=${y1 - y0} fill="var(--soft)" />`);
    if (['1H', '2H', 'HT', 'ET1', 'ET2'].includes(p.period) && cx(b) - cx(a) > (G.compact ? 26 : 40)) out.push(html`<text class="axs" x=${(cx(a) + cx(b)) / 2} y=${G.yQ0 - 5} text-anchor="middle">${{ '1H': '1st half', '2H': '2nd half', HT: 'Half-time', ET1: 'Extra time', ET2: 'Extra time' }[p.period]}</text>`);
  }
  for (const g of m.gaps) if (g.to > w.from && g.from < w.to) out.push(html`<rect x=${cx(g.from)} y=${y0} width=${Math.max(2, cx(g.to) - cx(g.from))} height=${y1 - y0} fill="url(#rhatch)"><title>${`${g.why}: ${dateTime(g.from)} to ${new Date(g.to * 1000).toISOString().slice(11, 19)} UTC. The score here is only known from the next update.`}</title></rect>`);
  // labels above the price panel, each in the first of LABEL_ROWS rows with room for it (goals close together, a goal
  // the feed took back and given again, kick-off and full time never print over each other)
  const marks = [];
  if (m.kickoff && vis(m.kickoff) && (!m.firstLive || Math.abs(m.firstLive - m.kickoff) > 120)) marks.push({ t: m.kickoff, dash: true, text: G.compact ? 'KO' : 'Kick-off (scheduled)', strong: false, title: `${dateTime(m.kickoff)}: the scheduled kick-off. The feed's first live update came at ${m.firstLive ? new Date(m.firstLive * 1000).toISOString().slice(11, 19) : '–'} UTC.` });
  if (m.final && vis(m.final.t)) marks.push({ t: m.final.t, dash: false, text: `FT ${scoreText(m.final.score)}`, strong: false, title: `${dateTime(m.final.t)}: full time, ${scoreText(m.final.score)}, as the feed said it.` });
  for (const g of m.goals) {
    if (g.kind === 'correction' || !vis(g.t)) continue;
    // a phone has room for the score only ("(1–3)": one the feed took back); the minute is in its title and the readout
    marks.push({ t: g.t, dash: g.retracted, text: G.compact ? (g.retracted ? `(${scoreText(g.score)})` : scoreText(g.score)) : goalLabel(g), strong: !g.retracted, title: `${dateTime(g.t)}: the feed showed ${scoreText(g.score)}${g.minute != null ? ` in the ${g.minute}th minute` : ''}${g.retracted ? ', then took it back' : ''}${g.reinstated ? ' again, after taking it back' : ''}${g.after_gap ? '. It came after a recording gap, so it may have happened earlier' : ''}.` });
  }
  marks.sort((a, b) => a.t - b.t);
  const edge = Array(labelRows(G.compact)).fill(-1e9), cw = 6.4;  // 11 px text
  for (const k of marks) {
    const x = G.X(k.t), wd = k.text.length * cw + 8;
    const right = x + wd <= G.W - 2;  // a label that would run off the edge sits to the left of its line
    const from = right ? x : x - wd;
    const row = edge.findIndex(e => e < from);  // -1: no row has room, the line is drawn without its label
    if (row >= 0) edge[row] = right ? x + wd : x + 4;
    const yl = y0 - 8 - (Math.max(0, row) + 1) * LABEL_ROW_H;  // above the panel's own caption
    out.push(html`<g><title>${k.title}</title><line x1=${x} x2=${x} y1=${row < 0 ? y0 : yl + 3} y2=${y1} stroke="var(--fg)" stroke-width=${k.strong ? 1.3 : 1} stroke-dasharray=${k.dash ? '4 3' : null} opacity=${k.strong ? 0.75 : 0.45} />
      ${row >= 0 && html`<text class="axs goal" x=${right ? x + 3 : x - 3} y=${yl} text-anchor=${right ? 'start' : 'end'}>${k.text}</text>`}</g>`);
  }
  return out;
}

function MarketChart({ w, width, compact, ph, sel, onBurst, onHover }) {
  const G = useMemo(() => chartGeom(w, width, compact), [w, width, compact]);
  const k = w.rule && w.rule.strike, f = [];
  const line = (pts, Yf) => pts.map(([t, v], i) => (i ? 'L' : 'M') + G.X(t).toFixed(1) + ' ' + Yf(v).toFixed(1)).join('');
  if (w.out && w.out.ranges.length) {
    const band = w.out.ranges.map(([t, h]) => `${G.X(t).toFixed(1)} ${G.YB(h).toFixed(1)}`).join('L') + 'L' + [...w.out.ranges].reverse().map(([t, , l]) => `${G.X(t).toFixed(1)} ${G.YB(l).toFixed(1)}`).join('L');
    f.push(html`<path d=${'M' + band + 'Z'} fill="var(--binance)" opacity=".18" />`);
  }
  if (w.out) f.push(html`<path d=${line(w.out.pts, G.YB)} fill="none" stroke="var(--binance)" stroke-width="1.3" />`);
  if (k) f.push(html`<line x1=${G.ml} x2=${G.W - G.mr} y1=${G.YB(k)} y2=${G.YB(k)} stroke="var(--fg)" stroke-dasharray="5 4" stroke-width="1.2" />`);
  for (const o of w.outcomes) f.push(html`<path d=${line(w.prices[o] || [], G.YP)} fill="none" stroke=${sideColor(w, o)} stroke-width="1.5" />`);
  for (const o of w.outcomes) {
    let d = `M${G.X(w.from)} ${G.YQ(0)}`, prev = 0;
    for (const [t, h] of w.pos) { const v = h[o] || 0; d += `L${G.X(t).toFixed(1)} ${G.YQ(prev).toFixed(1)}L${G.X(t).toFixed(1)} ${G.YQ(v).toFixed(1)}`; prev = v; }
    d += `L${G.X(w.to)} ${G.YQ(prev).toFixed(1)}L${G.X(w.to)} ${G.YQ(0)}Z`;
    f.push(html`<path d=${d} fill=${sideColor(w, o)} opacity=".22" />`);
  }
  const ax = [];
  if (!compact && w.out) {
    const span = G.hi - G.lo, raw = span / 4, stepv = [100, 250, 500, 1000, 2500, 5000, 10000, 25000].find(s => s >= raw) || 50000;
    for (let v = Math.ceil(G.lo / stepv) * stepv; v <= G.hi; v += stepv) ax.push(html`<line class="gridl" x1=${G.ml} x2=${G.W - G.mr} y1=${G.YB(v)} y2=${G.YB(v)} /><text class="ax" x=${G.ml - 8} y=${G.YB(v) + 3.5} text-anchor="end">${usdt(v)}</text>`);
  }
  if (!compact) {
    for (const c of [0, 50, 100]) ax.push(html`<line class="gridl" x1=${G.ml} x2=${G.W - G.mr} y1=${G.YP(c)} y2=${G.YP(c)} /><text class="ax" x=${G.ml - 8} y=${G.YP(c) + 3.5} text-anchor="end">${c}¢</text>`);
    ax.push(html`<text class="axs" x=${G.ml + 4} y=${G.yP0 - 5}>${w.outcomes.join(' and ')} on Polymarket (¢ a share)</text><text class="axs" x=${G.ml + 4} y=${G.yQ0 - 5}>Position (shares held)</text>`);
    if (k) ax.push(html`<text class="axs" x=${G.ml + 6} y=${G.YB(k) - 5}>${usdt(k)}, the price in the question</text>`);
    if (w.out && w.out.pts.length) { const last = w.out.pts[w.out.pts.length - 1]; ax.push(html`<text class="endl" x=${G.W - G.mr + 8} y=${G.YB(last[1]) + (k && Math.abs(G.YB(last[1]) - G.YB(k)) < 13 ? 16 : 4)} fill="var(--binance)">Binance ${usdt(last[1])}</text>`); }
    for (const o of w.outcomes) { const p = (w.prices[o] || []).slice(-1)[0]; if (p) ax.push(html`<text class="endl" x=${G.W - G.mr + 8} y=${G.YP(p[1]) + 4} fill=${sideColor(w, o)}>${o} ${cents(p[1])}</text>`); }
  }
  const hhmm = t => new Date(t * 1000).toISOString().slice(11, 16);
  for (const t of dateTicks(w, compact ? 4 : 8)) ax.push(html`<text class="ax" x=${G.X(t)} y=${G.yQ0 + G.hQ + 18} text-anchor="middle">${w.to - w.from < 2 * 86400 ? hhmm(t) : shortDate(t)}</text>`);
  if (w.match) f.unshift(...matchMarks(w, G));
  if (w.marketEnd && w.marketEnd <= w.to) ax.push(html`<line x1=${G.X(w.marketEnd)} x2=${G.X(w.marketEnd)} y1=${G.yB0} y2=${G.yQ0 + G.hQ} stroke="var(--faint)" stroke-dasharray="3 3" /><text class="axs" x=${G.X(w.marketEnd) - 4} y=${G.yB0 + 10} text-anchor="end">${w.result ? `resolved ${w.result}` : 'ended'}</text>`);
  const marks = w.bursts.map(b => {
    const x = G.X(b.t0), y = G.YP(b.avg), col = sideColor(w, b.side), s = Math.min(compact ? 4.5 : 6.5, 3 + Math.sqrt(b.shares) / 15), on = sel === b.id;
    return html`<g class="burst" key=${b.id} tabindex=${compact ? -1 : 0} role="button" aria-label=${`${b.action === 'buy' ? 'Bought' : 'Sold'} ${shares(b.shares)} ${b.side} on ${dateTime(b.t0)}`}
      onClick=${e => { e.stopPropagation(); onBurst(b); }} onKeyDown=${e => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); onBurst(b); } }}>
      ${on && html`<line x1=${x} x2=${x} y1=${G.yB0} y2=${G.yQ0 + G.hQ} stroke=${col} stroke-opacity=".7" />`}
      <circle cx=${x} cy=${y} r=${s + 6} fill="transparent" />
      ${b.action === 'sell' ? html`<rect x=${x - s} y=${y - s} width=${2 * s} height=${2 * s} fill="var(--card)" stroke=${col} stroke-width="2" />` : html`<path d=${`M${x} ${y - s}L${x - s} ${y + s * .8}H${x + s}Z`} fill=${col} stroke="var(--card)" stroke-width="1.2" />`}</g>`;
  });
  // merges, splits and conversions: a diamond on the position panel, at the time, with what it did
  for (const m of w.moves || []) {
    const x = G.X(m.t), y = G.yQ0 + 6, s2 = compact ? 4 : 5;
    marks.push(html`<g class="move" key=${'m' + m.i}><line x1=${x} x2=${x} y1=${G.yQ0} y2=${G.yQ0 + G.hQ} stroke="var(--fg)" stroke-dasharray="2 3" opacity=".5" />
      <path d=${`M${x} ${y - s2}L${x + s2} ${y}L${x} ${y + s2}L${x - s2} ${y}Z`} fill="var(--card)" stroke="var(--fg)" stroke-width="1.4"><title>${`${dateTime(m.t)}: ${moveText(w, m)}`}</title></path></g>`);
  }
  const move = e => { const r = e.currentTarget.getBoundingClientRect(); onHover(G.tOf((e.clientX - r.left) * (G.W / r.width))); };
  return html`<svg viewBox=${`0 0 ${G.W} ${G.H}`} width=${G.W} height=${G.H} role="img" aria-label=${`${w.title}: ${w.out ? w.out.name + ', ' : ''}the market's prices, its fills and its position`}
      onMouseMove=${move} onMouseLeave=${() => onHover(null)}>
    ${ax}${f}${marks}
    ${ph != null && html`<line x1=${G.X(ph)} x2=${G.X(ph)} y1=${G.yB0} y2=${G.yQ0 + G.hQ} stroke="var(--accent)" stroke-width="1.4" />`}</svg>`;
}

// A match market seen over the match only: its prices, position and fills from ten minutes before to ten after.
function matchView(w) {
  const { from, to } = w.match.axis, inV = t => t >= from && t <= to;
  const cut = rows => { const i = rows.findIndex(r => r[0] >= from); const before = i > 0 ? rows[i - 1] : i < 0 && rows.length ? rows[rows.length - 1] : null; return [...(before ? [[from, ...before.slice(1)]] : []), ...rows.filter(r => inV(r[0]))]; };
  const prices = Object.fromEntries(Object.entries(w.prices).map(([o, r]) => [o, cut(r)]));
  const pos = [[from, w.posAt(from)], ...w.pos.filter(p => inV(p[0]))];
  return { ...w, from, to, prices, pos, matchView: true, moves: (w.moves || []).filter(m => inV(m.t)), bursts: w.bursts.filter(b => inV(b.t0)) };
}

export function MarketReplay({ inv, ui, act, w, steps }) {
  const [box, width] = useWidth();
  const [hover, setHover] = useState(null);
  const [span, setSpan] = useState(null);  // null: the match unless the step being read is outside it
  if (w === 'loading') return html`<div class="ghostbox">Loading this market…</div>`;
  if (!w || w.error) return html`<div class="ghostbox">${w && w.error ? `This market couldn't be loaded: ${w.error}` : 'Pick a market from Markets.'}</div>`;
  const compact = width < 620;
  const step = steps[Math.min(ui.step, steps.length - 1)] || steps[0];
  const M = w.match, canMatch = !!(M && M.axis);
  const inMatch = t => canMatch && t >= M.axis.from && t <= M.axis.to;
  const view = !canMatch ? 'whole' : span || (step && !ui.full && !inMatch(step.t) ? 'whole' : 'match');
  const full = w;
  w = view === 'match' ? matchView(w) : w;
  const ph0 = hover ?? (ui.full || !step ? null : step.t);
  const ph = ph0 != null && (ph0 < w.from || ph0 > w.to) ? null : ph0;  // a step outside the match isn't drawn on it
  const T = w.totals, cov = w.cov || {}, ws = inv.summaries, wi = ws.findIndex(s => s.window_id === w.id);
  const go = i => act.setStep(Math.max(0, Math.min(steps.length - 1, i)));
  // a step reads where its own fills end, so "Holding" counts every fill the step describes
  const stepEnd = s => { const ids = new Set(s.trade_ids || []); return w.trades.reduce((m, x) => (ids.has(x.trade_id) ? Math.max(m, x.t) : m), s.t); };
  const ro = Math.round(hover ?? (ph != null && step ? stepEnd(step) : ph) ?? w.to), ob = w.outAt(ro);
  const pop = ui.pop && full.bursts.find(b => b.id === ui.pop);
  const covLine = [cov.price_step_s ? `the market's price every ${stepWord(cov.price_step_s)}${cov.match_price_step_s && cov.match_price_step_s !== cov.price_step_s ? `, the match itself every ${stepWord(cov.match_price_step_s)}` : ''}` : null,
    w.out ? `${w.out.name} in ${w.out.step} candles (their highs and lows shaded)` : cov.outside_none ? null : 'no outside price for this market',
    ...(cov.notes || [])].filter(Boolean);
  return html`<div class="wv">
    <div class="wv-head"><h3>${w.title}${/[?!.]$/.test(w.title || '') ? '' : ':'} ${w.out ? `${w.out.name}, ` : ''}${w.outcomes.join(' and ')} on Polymarket, its fills</h3>
      <span class="tag observed">${statusText({ profit_kind: T.kind, result: w.result, exit: T.exit })}</span>
      <div class="nav"><button class="icon" aria-label="Previous market" disabled=${wi <= 0} onClick=${() => act.openWin(ws[wi - 1].window_id)}>‹</button>${wi >= 0 ? `Market ${wi + 1} of ${ws.length}` : ''}<button class="icon" aria-label="Next market" disabled=${wi < 0 || wi >= ws.length - 1} onClick=${() => act.openWin(ws[wi + 1].window_id)}>›</button></div></div>
    <div class="sum"><span><b>${plural(full.trades.length, 'fill')}</b> from ${w.hold.from ? dateOf(w.hold.from) : '–'}, held ${w.hold.days == null ? '–' : days(w.hold.days * 86400)}</span>
      <span>Spent <b>${money(T.cost)}</b>${T.sold ? html`, ${(w.moves || []).some(m => m.kind === 'merge') ? 'got back' : 'sold for'} <b>${money(T.sold)}</b>` : ''}</span>
      <span>${T.profit == null ? html`<b class="muted">Profit not counted</b>` : html`<b class=${T.profit >= 0 ? 'gain' : 'loss'}>${signedMoney(T.profit)}</b>`} ${profitWord({ profit_kind: T.kind })}</span>
      ${w.league && html`<span><b>${w.league}</b></span>`}
      ${w.rule && w.rule.says && html`<span class="rule"><b>What resolves it:</b> ${w.rule.says}.</span>`}
      <span class="cov">${covLine.join(' · ')}</span></div>
    ${canMatch && html`<div class="spanpick"><div class="seg" role="radiogroup" aria-label="Chart span">${[['match', 'The match'], ['whole', 'Whole market']].map(([k, label]) => html`<button type="button" role="radio" aria-checked=${view === k ? 'true' : 'false'} class=${view === k ? 'on' : ''} onClick=${() => setSpan(k)}>${label}</button>`)}</div>
      <span class="muted small">${M.recorded ? `${M.home} ${M.final ? scoreText(M.final.score) : 'v'} ${M.away}${M.final ? '' : ' (not finished when read)'}: the score as polymarket.com's live feed said it, recorded by Layer${M.gaps.length ? `; ${M.gaps.length} recording gap${M.gaps.length > 1 ? 's' : ''} hatched` : ''}` : M.why || 'No score was recorded for this match.'}</span></div>`}
    <div class="legend">
      ${w.out && html`<span><i class="sw" style="border-color:var(--binance)"></i>${w.out.name} (${w.out.unit || 'USDT'}): what these markets resolve on</span>`}
      ${view === 'match' && M.recorded && html`<span><svg width="12" height="12"><line x1="6" x2="6" y1="0" y2="12" stroke="var(--fg)" stroke-width="1.3" /></svg>Goals, when the feed showed them${M.corrections ? ' (dashed: one it took back)' : ''}</span><span><i class="sw" style="border-color:var(--soft);border-top-width:8px"></i>Half-time</span>`}
      ${w.rule && w.rule.strike && html`<span><i class="sw" style="border-color:var(--fg);border-top-style:dashed"></i>${usdt(w.rule.strike)}, the price in the question</span>`}
      ${w.outcomes.map(o => html`<span><i class="sw" style=${`border-color:${sideColor(w, o)}`}></i>${o}</span>`)}
      ${(w.moves || []).length > 0 && html`<span><svg width="12" height="12"><path d="M6 1L11 6L6 11L1 6Z" fill="none" stroke="var(--fg)" stroke-width="1.4" /></svg>Merges and splits (on the position)</span>`}
      <span><svg width="12" height="10"><path d="M6 1 L1 9 H11Z" fill="var(--up)" /></svg>Buys <svg width="10" height="10"><rect x="1" y="1" width="8" height="8" fill="none" stroke="var(--up)" stroke-width="1.6" /></svg>Sells, at the price paid (${view === 'match' ? 'fills within a minute' : w.trades.length > 400 ? 'fills within a day' : w.trades.length > 150 ? 'fills within six hours' : 'fills within an hour'} drawn as one)</span></div>
    <div class="readout" aria-live="off"><b>${dateTime(ro)}</b>
      ${w.out && html`<span><span class="k">${w.out.name}</span> ${ob == null ? 'not read' : usdt(ob)}</span>`}
      ${w.outcomes.map(o => html`<span><span class="k">${o}</span> ${w.priceAt(o, ro) == null ? '–' : cents(w.priceAt(o, ro))}</span>`)}
      ${M && html`<span><span class="k">Match</span> ${(() => { const s = w.scoreAt(ro); return !M.recorded ? 'no score recorded' : !s ? (M.kickoff && ro < M.kickoff ? 'before kick-off' : 'not started') : `${s.minute != null && ['1H', '2H', 'ET1', 'ET2'].includes(s.period) ? `${s.minute}' ` : s.period === 'HT' ? 'half-time ' : ['FT', 'VFT', 'AET', 'PEN'].includes(s.period) ? 'full time ' : ''}${scoreText(s.score)}`; })()}</span>`}
      <span><span class="k">Holding</span> ${heldText(w, ro)}</span>${hover == null && html`<span class="k">· Hover to read any ${view === 'match' ? 'minute' : 'day'}; click a fill to ask about it</span>`}</div>
    <div class="chartbox" ref=${box}><${MarketChart} w=${w} width=${width} compact=${compact} ph=${ph} sel=${ui.pop} onBurst=${b => act.pop(b.id)} onHover=${setHover} />
      ${pop && html`<div class="pop" style="left:8px;top:16px" role="dialog" aria-label="Fills"><h4>${pop.action === 'buy' ? 'Bought' : 'Sold'} ${shares(pop.shares)} ${pop.side} in ${plural(pop.fills.length, 'fill')}</h4>
        <p class="muted small">${dateTime(pop.t0)} · ${money(pop.usd)}${w.outAt(pop.t0) != null ? ` · ${w.out.name} ${usdt(w.outAt(pop.t0))}` : ''}</p>
        <div class="rows"><table><thead><tr><th>Time (UTC)</th><th>Shares</th><th>Price</th>${M && html`<th>The match then</th>`}</tr></thead><tbody>${pop.fills.map(x => html`<tr><td>${M ? new Date(x.t * 1000).toISOString().slice(11, 19) : dateTime(x.t)}</td><td>${shares(x.shares)}</td><td>${cents(x.price)}</td>${M && html`<td>${matchText(x)}</td>`}</tr>`)}</tbody></table></div>
        <div class="acts"><button class="btn sm primary" onClick=${() => act.askMarketBurst(w, pop)}>Why here?</button><button class="btn sm" onClick=${() => act.pop(null)}>Close</button></div></div>`}</div>
    ${step && html`<div class="stepbar">
      <button class="icon" aria-label="Previous step" onClick=${() => go(ui.step - 1)}>◀</button>
      <button class="icon" aria-label="Next step" onClick=${() => go(ui.step + 1)}>▶</button>
      <span class="muted small">Step ${Math.min(ui.step, steps.length - 1) + 1} of ${steps.length}</span>
      <div class="dots">${steps.map((s, i) => html`<button class=${i === ui.step ? 'on' : i < ui.step ? 'past' : ''} title=${`${dateTime(s.t)} ${s.title}`} onClick=${() => go(i)}>${i + 1}</button>`)}</div>
      <div class="opts"><label><input type="checkbox" id="fullwin" checked=${ui.full} onChange=${e => act.setFull(e.target.checked)} /> Whole market</label></div></div>
    <div class="caption">
      <div class="ct"><h4>${flagged(step.title, flagsFor(step.number_check, 'title'))}</h4><span class="when">${dateTime(step.t)}</span></div>
      <div class="line2"><span class="tag observed">Observed</span><p>${flagged(step.observed, flagsFor(step.number_check, 'observed'))}</p></div>
      ${step.inferred && html`<div class="line2 inf"><span class="tag inferred">Inferred</span><p>${flagged(step.inferred, flagsFor(step.number_check, 'inferred'))}</p></div>`}
      <span class="src-note">${step.auto ? "Steps drawn from this market's data. The agent's own walkthrough replaces them when it writes one." : 'Walkthrough written by the agent; its numbers were checked against the data.'}${T.note ? ' ' + T.note : ''}</span></div>`}
  </div>`;
}

// ---------- this market's fills
export function MarketTrades({ w, act }) {
  if (!w || w === 'loading' || w.error) return html`<div class="ghostbox">Open a market to see its fills.</div>`;
  return html`<div class="ov"><p class="muted small">This market's ${plural(w.trades.length, 'fill')} over its whole life, from the wallet's own trade history. Click one to see it on the chart.</p>
    <div class="tablewrap"><table class="tr"><thead><tr><th>Time (UTC)</th><th>Trade</th><th>Price</th><th>Paid</th><th>${w.match ? 'The match then' : w.out ? w.out.name : 'Outside price'}</th><th>Holding after</th></tr></thead><tbody>
    ${w.trades.map(x => html`<tr class="click" onClick=${() => act.openAt(w.id, x.t)}><td>${dateTime(x.t)}</td>
      <td>${x.action === 'buy' ? 'Bought' : 'Sold'} ${shares(x.shares)} <span style=${`color:${sideColor(w, x.side)};font-weight:600`}>${x.side}</span></td><td>${cents(x.price)}</td><td>${money(x.usd || 0)}</td>
      <td>${w.match ? matchText(x) : x.outside == null ? '–' : usdt(x.outside)}</td><td>${heldText(w, x.t)}</td></tr>`)}
    </tbody></table></div></div>`;
}
