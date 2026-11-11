// The workspace's stages: the plan, the windows (tiles), one window's replay with its steps, and the trades.
import { html, useState, useEffect, useRef, useMemo } from '../vendor/htm-preact-3.1.1.module.js';
import { Chart, Spark } from './chart.js';
import { money, signedMoney, cents, shares, btc, signedBtc, mmss, clock, windowLabel, hm, day, plural } from './format.js';
import { posText, fmtWhen } from './windowdata.js';
import { splitFlagged, flagsFor } from './store.js';
import { RunClock } from './clock.js';
import { FILTERS, filterTiles, tally, buyPoints } from './allwindows.js';

const reduced = typeof matchMedia !== 'undefined' && matchMedia('(prefers-reduced-motion: reduce)').matches;

// ---------- plan
// How long Start usually takes: the server's measure of recent Starts (estimate_s) once it has one, else the sum of
// the plan's own step guesses.
const planMinutes = p => Math.max(1, Math.round((p.estimate_s ?? p.steps.reduce((s, x) => s + (x.est || 0), 0)) / 60));
const MARK = { queued: '', running: '…', done: '✓', warning: '!', failed: '×' };
export function PlanStage({ inv, act }) {
  const p = inv.plans[inv.planOrder[0]];
  if (!p) return html`<div class="plan"><div style="display:flex;gap:12px"><span class=${'dot ' + (inv.running ? 'live' : '')}></span><div><h3>${inv.running ? 'Working out a plan' : 'No plan yet'}</h3><p class="muted small">${inv.running ? 'The agent shows its plan here before it reads anything.' : 'Ask a question to start.'}</p></div></div></div>`;
  return html`<div class="plan">
    <div style="display:flex;gap:12px;align-items:flex-start"><span class=${'dot ' + (p.status === 'approved' && inv.running ? 'live' : p.status === 'done' ? 'ok' : '')} style="margin-top:6px"></span>
      <div><h3>${p.status === 'proposed' ? 'Here is my plan' : p.status === 'done' || inv.done ? 'What I did' : 'Working on it'}</h3>
      <p class="muted small">${p.title}${p.estimate_usd != null && p.status === 'proposed' ? ` · about ${money(p.estimate_usd)} of model time` : ''}${p.status === 'proposed' ? `, about ${planMinutes(p)} min. Nothing runs until you press Start.` : '. If you leave, the results stay here.'}</p>
      ${inv.running && p.status !== 'proposed' && html`<p class="muted small"><${RunClock} inv=${inv} bar=${false} /></p>`}</div></div>
    <ol>${p.steps.map((s, i) => html`<li class=${'ps ' + s.status}><span class="mk">${MARK[s.status] || i + 1}</span><div>
      <div class="ti">${s.title}</div>${s.source && html`<div class="src">${s.source}</div>`}
      ${s.summary && s.status !== 'queued' && html`<div class="sum">${s.summary}</div>`}
      ${s.progress && s.status === 'running' && html`<div class="bar"><i style=${`width:${Math.round(100 * s.progress.done / Math.max(1, s.progress.total))}%`}></i></div>`}
      ${(s.warnings || []).map(w => html`<div class="warn">${w.text}</div>`)}</div></li>`)}</ol>
    ${p.scope && html`<div class="scope"><div><b>Scope:</b> ${p.scope.from ? `${p.scope.from} to ${p.scope.to}` : 'as asked'}.</div>
      ${(p.scope_options || []).map(o => html`<label><input type="checkbox" id=${'so-' + o.id} disabled=${p.status !== 'proposed'} checked=${act.scopeOpts.has(o.id)} onChange=${e => act.toggleScope(o.id, e.target.checked)} /> ${o.text}</label>`)}</div>`}
    ${p.status === 'proposed' && html`<div style="display:flex;gap:8px"><button class="btn primary" onClick=${() => act.approve(p.plan_id)}>Start</button><button class="btn ghost" onClick=${() => act.editPlan(p.plan_id)}>Change the plan</button></div>`}
  </div>`;
}

// ---------- tiles
export function WindowsStage({ inv, ui, act }) {
  const all = inv.summaries;
  if (!all.length) return html`<div class="ghostbox">Windows appear here as the agent draws them.</div>`;
  const hl = ui.hl, n = tally(all), tiles = filterTiles(all, ui.wf);
  const fl = FILTERS.find(f => f[0] === ui.wf);
  return html`<div class="ov">
    ${n.decided > 0 && html`<p class="tally">Made money in <b>${n.made} of ${plural(n.decided, 'window')}</b> (<span class="gain">${signedMoney(n.profitMade)}</span>) and lost money in <b>${n.lostMoney}</b> (<span class="loss">${signedMoney(n.profitLost)}</span>), from its fills. It bought more of the side that won in <b>${n.favWon} of ${n.decided}</b>.
      <span class="muted">Not the same thing: buying both Up and Down, it can back the winner and still lose money.</span></p>`}
    <div class="wfilter" role="group" aria-label="Show windows">
      <button class=${!ui.wf ? 'on' : ''} onClick=${() => act.filter(null)}>All · ${all.length}</button>
      ${FILTERS.map(([k, label]) => html`<button class=${ui.wf === k ? 'on' : ''} disabled=${!n[k]} onClick=${() => act.filter(k)}>${label} · ${n[k]}</button>`)}</div>
    <${AllWindowsChart} tiles=${tiles} ui=${ui} act=${act} />
    <p class="muted small">Each tile is one window: Binance BTCUSDT from its price at the start (the dashed line), with this wallet's fills along the bottom (Up above, Down below) and the time before the open shaded. Click one to step through it.${fl ? ` Showing only: ${fl[1].toLowerCase()}.` : ''}</p>
    ${hl && html`<div class="hl"><span>Showing <b>${hl.label}</b>: matching windows outlined.</span><button class="link" onClick=${() => act.clearHl()}>Show all</button></div>`}
    <div class="tiles">${tiles.map(s => {
      const cls = hl ? (hl.match.has(s.window_id) ? 'match' : (hl.base && hl.base.has(s.window_id) ? '' : 'dim')) : '';
      const c = s.coverage || {};
      return html`<button class=${'tile ' + cls} key=${s.window_id} onClick=${() => act.openWin(s.window_id)} aria-label=${windowLabel(s.start, s.end)}>
        <div class="tt"><span>${day(s.start)} ${hm(s.start)}</span><span class=${'res-' + s.result}>${s.result}</span></div>
        <${Spark} s=${s} />
        <div class="tf"><span>${plural((s.entries || []).length, 'fill')}${s.first_entry_s < 0 ? `, first ${-s.first_entry_s} s early` : ''}</span><span class=${s.profit >= 0 ? 'gain' : 'loss'}>${s.profit == null ? '' : signedMoney(s.profit)}</span></div>
        <div class="badges">${s.shares && s.shares.up > 0 && s.shares.down > 0 && html`<span class="badge">both sides</span>`}
          ${!c.book && html`<span class="badge warn">no order book</span>`}${c.book && c.book_usable === false && html`<span class="badge warn">book gaps</span>`}${c.outage && html`<span class="badge warn">recording lost</span>`}
          ${c.chainlink === 'start_and_result' && html`<span class="badge">Chainlink: start and result</span>`}</div></button>`;
    })}</div></div>`;
}

// ---------- every window on one chart
// Each buy: when in its window (x) and how far BTC was from the price to beat, toward the side it bought (y): Chainlink
// BTC/USD where it was recorded, else Binance BTCUSDT's move since the open, drawn hollow (buyPoints). Coloured by one
// of two different questions: did the window make money, or did the side bought win.
const COLOUR_BY = [['money', 'Did the window make money?'], ['side', 'Did the side it bought win?']];
function AllWindowsChart({ tiles, ui, act }) {
  const [box, width] = useWidth();
  const { pts, noLine } = useMemo(() => buyPoints(tiles), [tiles]);
  if (!pts.length) return null;
  const by = ui.colourBy || 'money', H = 260, L = 54, R = 10, T = 14, B = 30;
  const lo = Math.max(-300, Math.min(0, ...pts.map(p => p.t))), hi = 900;
  const sorted = pts.map(p => Math.abs(p.toward)).sort((a, b) => a - b);
  const m = Math.max(20, sorted[Math.floor(0.99 * (sorted.length - 1))]); // the top 1% clipped to the edge, not lost
  const X = t => L + (Math.max(lo, Math.min(hi, t)) - lo) / (hi - lo) * (width - L - R);
  const Y = v => T + (1 - (Math.max(-m, Math.min(m, v)) + m) / (2 * m)) * (H - T - B);
  const good = p => (by === 'money' ? p.made : p.sideWon), bad = p => (by === 'money' ? p.lostMoney : p.sideLost);
  const fill = p => (good(p) ? 'var(--gain)' : bad(p) ? 'var(--loss)' : 'var(--faint)');
  const share = sel => { const g = pts.filter(sel); return g.length ? Math.round(100 * g.filter(p => p.toward > 0).length / g.length) : null; };
  const [a, b] = [share(good), share(bad)];
  const names = by === 'money' ? ['of buys in windows that made money', 'in windows that lost money'] : ['of buys of the side that won', 'of buys of the side that lost'];
  const yTicks = [-m, -m / 2, 0, m / 2, m].map(v => Math.round(v));
  const nWin = new Set(pts.map(p => p.window_id)).size, nOpen = pts.filter(p => p.basis === 'open').length;
  return html`<figure class="allwin">
    <div class="allwin-head"><b>Every buy, across ${plural(nWin, 'window')}</b>
      <div class="wfilter small" role="group" aria-label="Colour the buys by">${COLOUR_BY.map(([k, label]) => html`<button class=${by === k ? 'on' : ''} onClick=${() => act.colourBy(k)}>${label}</button>`)}</div></div>
    <div ref=${box}><svg viewBox=${`0 0 ${width} ${H}`} width=${width} height=${H} role="img" aria-label=${`Every buy: minutes into its window against how far BTC was from the price to beat, toward the side it bought`}>
      ${yTicks.map(v => html`<g><line x1=${L} x2=${width - R} y1=${Y(v)} y2=${Y(v)} stroke="var(--line)" stroke-dasharray=${v === 0 ? '3 3' : ''} stroke-width=${v === 0 ? 1.2 : 1} />
        <text class="axs" x=${L - 6} y=${Y(v) + 4} text-anchor="end">${v === 0 ? '$0' : signedBtc(v).replace('.00', '')}</text></g>`)}
      ${lo < 0 && html`<rect x=${X(lo)} y=${T} width=${X(0) - X(lo)} height=${H - T - B} fill="var(--soft)" />`}
      ${[0, 300, 600, 900].map(t => html`<text class="axs" x=${X(t)} y=${H - 10} text-anchor=${t === hi ? 'end' : 'middle'}>${t / 60} min</text>`)}
      <text class="axs" x=${L + 6} y=${T + 12}>BTC on the side it bought ↑</text>
      <text class="axs" x=${L + 6} y=${H - B - 6}>BTC on the other side of the price to beat ↓</text>
      ${pts.map(p => html`<circle cx=${X(p.t)} cy=${Y(p.toward)} r="2.6" fill=${p.basis === 'open' ? 'none' : fill(p)} fill-opacity=".55"
        stroke=${p.basis === 'open' ? fill(p) : 'none'} stroke-width="1" onClick=${() => act.openWin(p.window_id)}>
        <title>${`${day(p.start)} ${hm(p.start)} window: bought ${p.side} at ${mmss(p.t)}, ${p.basis === 'ptb' ? `Chainlink BTC/USD ${signedBtc(p.toward)} from the price to beat, toward ${p.side}` : `Binance BTCUSDT ${signedBtc(p.toward)} toward ${p.side} since the open (no Chainlink recorded)`}. ${p.sideWon ? `${p.side} won` : `${p.side} lost`}; the window ${p.profit == null ? 'has no result yet' : `${signedMoney(p.profit)} from its fills`}. Click to open it.`}</title></circle>`)}
    </svg></div>
    <figcaption class="muted small">
      <span class="keys"><span class="key"><i style="background:var(--gain)"></i>${by === 'money' ? 'window made money' : 'the side it bought won'}</span>
        <span class="key"><i style="background:var(--loss)"></i>${by === 'money' ? 'window lost money' : 'the side it bought lost'}</span></span>
      ${a != null && b != null && html`<span>Bought the side BTC was already on: ${a}% ${names[0]}, ${b}% ${names[1]}.</span>`}
      <span>Each dot is one buy (${plural(pts.length, 'buy')}): minutes into its window, and how far Chainlink BTC/USD was from the price to beat, toward the side it bought (above it for Up, below it for Down).${nOpen ? ` Hollow dots (${plural(nOpen, 'buy')}) are from before Chainlink was recorded: Binance BTCUSDT's move since the window opened instead, close but not the same.` : ''} Click a dot to open its window.${noLine ? ` ${plural(noLine, 'window')} without a price line ${noLine === 1 ? 'isn\'t' : 'aren\'t'} drawn.` : ''}</span></figcaption>
  </figure>`;
}

// ---------- the replay
// the chart box's width, followed as it changes (a callback ref, so it attaches whenever the box appears)
function useWidth(fallback = 760) {
  const [w, setW] = useState(fallback), ro = useRef(null);
  const ref = el => {
    if (ro.current) { ro.current.disconnect(); ro.current = null; }
    if (!el) return;
    ro.current = new ResizeObserver(([e]) => setW(Math.max(300, Math.floor(e.contentRect.width))));
    ro.current.observe(el);
  };
  useEffect(() => () => ro.current && ro.current.disconnect(), []);
  return [ref, w];
}

export function ReplayStage({ inv, ui, act, w, steps, idx, total }) {
  const [box, width] = useWidth();
  const [hover, setHover] = useState(null);
  const [playing, setPlaying] = useState(false);
  const phRef = useRef(null), playTok = useRef(0);
  useEffect(() => () => { playTok.current += 1; }, []);
  if (w === 'loading') return html`<div class="ghostbox">Loading this window…</div>`;
  if (!w || w.error) return html`<div class="ghostbox">${w && w.error ? `This window couldn't be loaded: ${w.error}` : 'Pick a window from Windows.'}</div>`;
  const compact = width < 620;
  const step = steps[Math.min(ui.step, steps.length - 1)] || steps[0];
  const ph = ui.full ? null : (ui.ph ?? step.t);
  const rel = a => ({ ...a, t0: a.t0 > 1e9 ? a.t0 - w.start : a.t0, t1: a.t1 > 1e9 ? a.t1 - w.start : a.t1 }); // unix or from the start
  const anns = (ui.full ? [] : (step.annotations || [])).concat((ui.extraAnn || []).filter(a => a.window_id === w.id).map(rel));
  const go = i => { playTok.current += 1; setPlaying(false); act.setStep(Math.max(0, Math.min(steps.length - 1, i))); };
  const play = async () => {
    if (playing) { playTok.current += 1; setPlaying(false); return; }
    const tok = ++playTok.current; setPlaying(true);
    let i = ui.step >= steps.length - 1 ? 0 : ui.step; if (i === 0 && ui.step !== 0) act.setStep(0);
    while (tok === playTok.current && i < steps.length - 1) {
      const a = steps[i].t, b = steps[i + 1].t;
      await new Promise(res => {
        if (reduced) return res();
        const ms = Math.min(2200, 350 + Math.abs(b - a) * 6), t0 = performance.now();
        const f = now => { if (tok !== playTok.current) return res(); const k = Math.min(1, (now - t0) / ms); if (phRef.current) phRef.current(a + (b - a) * k); k < 1 ? requestAnimationFrame(f) : res(); };
        requestAnimationFrame(f);
      });
      if (tok !== playTok.current) return;
      i += 1; act.setStep(i);
      await new Promise(r => setTimeout(r, 1400));
    }
    if (tok === playTok.current) setPlaying(false);
  };
  const T = w.totals, cov = w.cov || {};
  const covLine = [
    !w.hasBook && (w.mf ? "No order book: Polymarket's once-a-minute prices, dotted" : 'No Up or Down prices'),
    cov.seconds_without_book ? `no order book for ${cov.seconds_without_book} of 900 s` : null,
    cov.market_trades && cov.market_trades.pct != null ? `${cov.market_trades.recorded.toLocaleString('en-US')} of ${cov.market_trades.polymarket.toLocaleString('en-US')} market trades recorded (${cov.market_trades.pct}%)` : null,
    cov.market_trades && cov.market_trades.read != null && !cov.market_trades.complete ? `market tape read in part (${cov.market_trades.read.toLocaleString('en-US')} trades)` : null,
  ].filter(Boolean);
  const ro = hover ?? ph ?? (w.end);
  const ws = inv.summaries, wi = ws.findIndex(s => s.window_id === w.id);
  const pop = ui.pop && w.bursts.find(b => b.id === ui.pop);
  return html`<div class="wv">
    <div class="wv-head"><h3>${windowLabel(w.start, w.start + w.end)}: BTC on Binance${w.hasCL ? ' and Chainlink' : ''}, the Up and Down prices, its fills</h3>
      <span class="tag observed">Resolved <span class=${'res-' + w.result}>${' ' + w.result}</span></span><span class="slug">${w.id}</span>
      <div class="nav"><button class="icon" aria-label="Previous window" disabled=${wi <= 0} onClick=${() => act.openWin(ws[wi - 1].window_id)}>‹</button>${wi >= 0 ? `Window ${wi + 1} of ${ws.length}` : ''}<button class="icon" aria-label="Next window" disabled=${wi < 0 || wi >= ws.length - 1} onClick=${() => act.openWin(ws[wi + 1].window_id)}>›</button></div></div>
    <div class="sum"><span><b>${plural(w.trades.length, 'fill')}</b>${w.pre.length ? `, ${w.pre.length} before the open (first ${-w.pre[0].t} s early)` : ''}</span>
      <span>Spent <b>${money(T.cost)}</b></span><span><b class=${T.profit >= 0 ? 'gain' : 'loss'}>${signedMoney(T.profit)}</b> on this window, from its fills</span>
      ${w.both && html`<span>Held <b>both sides</b> at once</span>`}${covLine.length > 0 && html`<span class="cov">${covLine.join(' · ')}</span>`}</div>
    <div class="legend">
      <span><i class="sw" style="border-color:var(--fg)"></i>Chainlink BTC/USD${w.clFull ? ', what the market settles on' : ': start (the price to beat) and result only, not recorded before 10 Nov 05:27 UTC'}</span>
      <span><i class="sw" style="border-color:var(--binance)"></i>Binance BTCUSDT: BTC in Tether, about 0.1% from Chainlink, not what the market settles on${ui.raw || w.hasCL ? '' : '. Lined up on its own price at the start'}</span>
      <span><i class="sw" style="border-color:var(--faint);border-top-style:dashed"></i>Price to beat</span>
      <span><i class="sw" style="border-color:var(--up)"></i>Up</span><span><i class="sw" style="border-color:var(--down)"></i>Down</span>
      <span><svg width="12" height="10"><path d="M6 1 L1 9 H11Z" fill="var(--up)" /></svg><svg width="12" height="10"><path d="M6 9 L1 1 H11Z" fill="var(--down)" /></svg>Its fills (size = shares)</span>
      <span><svg width="14" height="10"><rect width="14" height="10" fill="var(--soft)" stroke="var(--line)" /></svg>Before the open</span>
      ${(w.holes.length > 0 || (!w.hasBook && !w.mf)) && html`<span><svg width="14" height="10"><rect width="14" height="10" fill="url(#rhatch)" stroke="var(--line)" /></svg>Not recorded</span>`}</div>
    <${Readout} w=${w} t=${ro} hover=${hover != null} />
    <div class="chartbox" ref=${box}>
      <${Chart} w=${w} width=${width} compact=${compact} raw=${ui.raw} ph=${ph} anns=${anns} pin=${ui.pin && ui.pin.window_id === w.id ? ui.pin.t : null} sel=${ui.pop}
        onBurst=${b => act.pop(b.id)} onHover=${setHover} onMoment=${t => act.pinMoment(w, t)} phRef=${phRef} id="mc" />
      ${pop && html`<${BurstPop} w=${w} b=${pop} width=${width} act=${act} />`}
    </div>
    <div class="stepbar">
      <button class="icon" aria-label="Previous step" onClick=${() => go(ui.step - 1)}>◀</button>
      <button class="btn sm" onClick=${play}>${playing ? 'Pause' : 'Play'}</button>
      <button class="icon" aria-label="Next step" onClick=${() => go(ui.step + 1)}>▶</button>
      <span class="muted small">Step ${Math.min(ui.step, steps.length - 1) + 1} of ${steps.length}</span>
      <div class="dots">${steps.map((s, i) => html`<button class=${i === ui.step ? 'on' : i < ui.step ? 'past' : ''} title=${`${mmss(s.t)} ${s.title}`} onClick=${() => go(i)}>${i + 1}</button>`)}</div>
      <div class="opts"><label><input type="checkbox" id="fullwin" checked=${ui.full} onChange=${e => act.setFull(e.target.checked)} /> Whole window</label>
        ${!w.hasCL && html`<label><input type="checkbox" id="rawbn" checked=${ui.raw} onChange=${e => act.setRaw(e.target.checked)} /> Binance's own price</label>`}</div>
    </div>
    <div class="caption">
      <div class="ct"><h4>${flagged(step.title, flagsFor(step.number_check, 'title'))}</h4><span class="when">${fmtWhen(w, step.t)}</span><button class="link" onClick=${() => act.pinMoment(w, step.t)}>Ask about this moment</button></div>
      <div class="line2"><span class="tag observed">Observed</span><p>${flagged(step.observed, flagsFor(step.number_check, `step ${step.index} observed`).concat(flagsFor(step.number_check, 'observed')))}</p></div>
      ${step.inferred && html`<div class="line2 inf"><span class="tag inferred">Inferred</span><p>${flagged(step.inferred, flagsFor(step.number_check, `step ${step.index} inferred`).concat(flagsFor(step.number_check, 'inferred')))}</p></div>`}
      <span class="src-note">${step.auto ? "Steps drawn from this window's data. The agent's own walkthrough replaces them when it writes one." : 'Walkthrough written by the agent; its numbers were checked against the data.'}${T.note ? ' ' + T.note : ''}</span>
    </div></div>`;
}

// A text with its flagged numbers struck where they stand, the data's value beside them
export function flagged(text, flags) {
  return splitFlagged(text, flags).map(p => p.flag ? html`<span class="flagnum" title="Didn't match the data">${p.text}</span>${p.flag.data_value ? html` <b>${p.flag.data_value}</b>` : ''}` : p.text);
}

function Readout({ w, t, hover }) {
  t = Math.round(t);
  const up = w.up(t), dn = w.down(t), m = w.upMinute(t), cl = w.cl(t), bn = w.bn(t), mv = w.move(t);
  return html`<div class="readout" aria-live="off">
    <b>${mmss(t)}</b><span class="k">${clock(w.start + t)} UTC${t < 0 ? ', before the open' : t > w.end ? ', after the close' : ''}</span>
    <span><span class="k">Binance BTCUSDT</span> ${bn == null ? 'not read' : btc(bn)}</span>
    <span><span class="k">Chainlink BTC/USD</span> ${cl != null ? btc(cl) : t === 0 ? btc(w.ptb) : w.hasCL ? 'the feed skipped this second' : 'not recorded'}</span>
    ${mv != null && t >= 0 && html`<span><span class="k">BTC from the start</span> ${signedBtc(mv)}</span>`}
    <span>${up ? html`<span class="k">Up</span> ${cents(up[0])}/${cents(up[1])} <span class="k">Down</span> ${cents(dn[0])}/${cents(dn[1])}` : m != null ? html`<span class="k">Up</span> ${cents(m)} <span class="k">(once-a-minute price)</span>` : html`<span class="k">Up and Down not recorded at this second</span>`}</span>
    <span><span class="k">Holding</span> ${posText(w, t)}</span>
    ${!hover && html`<span class="k">· Hover to read any second; click a fill to ask about it</span>`}</div>`;
}

function BurstPop({ w, b, width, act }) {
  const left = Math.max(8, Math.min(width - 322, ((b.t0 - w.from) / (w.to - w.from)) * (width - 188) + 84));
  return html`<div class="pop" style=${`left:${left}px;top:16px`} role="dialog" aria-label="Fills">
    <h4>${b.action === 'buy' ? 'Bought' : 'Sold'} ${shares(b.shares)} <span class=${'side-' + b.side}>${b.side}</span> in ${plural(b.fills.length, 'fill')}</h4>
    <p class="muted small">${mmss(b.t0)}${b.t1 > b.t0 ? ` to ${mmss(b.t1)}` : ''} · ${money(b.usd)} · ${b.t0 < 0 ? 'before the window opened' : `BTC ${signedBtc(w.move(b.t0) ?? 0)} from the start`}</p>
    <div class="rows"><table><thead><tr><th>Time</th><th>Shares</th><th>Price</th><th>How it filled</th></tr></thead><tbody>
      ${b.fills.map(x => html`<tr><td>${mmss(x.t)}</td><td>${shares(x.shares)}</td><td>${cents(x.price)}</td><td>${x.liq === 'taker' ? 'Paid the asking price' : x.liq === 'maker' ? 'Resting buy filled' : 'Not checked'}</td></tr>`)}</tbody></table></div>
    <div class="acts"><button class="btn sm primary" onClick=${() => act.askBurst(w, b)}>Why here?</button><button class="btn sm" onClick=${() => act.pop(null)}>Close</button></div></div>`;
}

// ---------- trades (this window's fills)
export function TradesStage({ w, act }) {
  if (!w || w === 'loading' || w.error) return html`<div class="ghostbox">Open a window to see its fills.</div>`;
  return html`<div class="ov"><p class="muted small">This window's ${plural(w.trades.length, 'fill')}, from the wallet's own trade history. Click one to see it on the chart.</p>
    <div class="tablewrap"><table class="tr"><thead><tr><th>Time (UTC)</th><th>From start</th><th>Trade</th><th>Price</th><th>Paid</th><th>BTC from the start</th><th>How it filled</th></tr></thead><tbody>
    ${w.trades.map(x => html`<tr class="click" onClick=${() => act.openAt(w.id, x.t)}><td>${clock(w.start + x.t)}</td><td>${mmss(x.t)}${x.t < 0 ? ' (before the open)' : ''}</td>
      <td>${x.action === 'buy' ? 'Bought' : 'Sold'} ${shares(x.shares)} <span class=${'side-' + x.side}>${x.side}</span></td><td>${cents(x.price)}</td><td>${money(x.usd)}</td>
      <td>${x.t < 0 ? '–' : (w.move(x.t) == null ? '–' : signedBtc(w.move(x.t)))}</td><td class=${x.liq ? '' : 'muted'}>${x.liq === 'taker' ? 'Paid the asking price' : x.liq === 'maker' ? 'Resting buy filled' : 'Not checked'}</td></tr>`)}
    </tbody></table></div></div>`;
}
