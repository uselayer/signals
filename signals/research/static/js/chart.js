// The window replay: three panels on one time axis (seconds from the window's start, the pre-open band before 0):
// BTC (Binance BTCUSDT, Chainlink BTC/USD when recorded, the price to beat), the Up and Down prices on Polymarket,
// and the wallet's position (Up above the line, Down below: a wallet can hold both). Hand-drawn SVG so every burst
// of fills is a real element to click, focus and ask about; the playhead moves by attribute, never a re-render.
import { html, useMemo, useRef, useEffect } from '../vendor/htm-preact-3.1.1.module.js';
import { btc, cents, shares, mmss } from './format.js';

export function geometry(w, W, compact, raw) {
  const ml = compact ? 6 : 70, mr = compact ? 6 : 118, top = compact ? 6 : 12;
  const hB = compact ? 116 : 196, hP = compact ? 60 : 116, hQ = compact ? 44 : 76, g = compact ? 8 : 18, ax = compact ? 16 : 30;
  const yB0 = top, yP0 = yB0 + hB + g, yQ0 = yP0 + hP + g, H = yQ0 + hQ + ax;
  const X = t => ml + (t - w.from) / (w.to - w.from) * (W - ml - mr);
  const tOf = px => Math.max(w.from, Math.min(w.to, Math.round(w.from + (px - ml) / (W - ml - mr) * (w.to - w.from))));
  // Binance BTCUSDT is drawn from its own price at the start, lined up on the price to beat, unless "raw" (it isn't
  // Chainlink, and before 10 Nov 05:27 UTC there is no recorded Chainlink to draw)
  const off = raw || w.hasCL || w.bn0 == null ? 0 : w.bn0 - w.ptb; // lined up only when there's no Chainlink line to confuse it with
  const bnv = t => { const b = w.bn(t); return b == null ? null : b - off; };
  let lo = w.ptb, hi = w.ptb;
  for (let t = w.from; t <= w.to; t += 3) { for (const v of [bnv(t), w.cl(t)]) if (v != null) { lo = Math.min(lo, v); hi = Math.max(hi, v); } }
  const pad = (hi - lo) * 0.1 + 4; lo -= pad; hi += pad;
  const YB = v => yB0 + hB - (v - lo) / (hi - lo) * hB, YP = c => yP0 + hP - c / 100 * hP;
  let qmax = 1; for (const [, a, b] of w.pos) qmax = Math.max(qmax, a, b);
  const yQm = yQ0 + hQ / 2, YQ = v => yQm - v / qmax * (hQ / 2 - 3);
  return { ml, mr, W, H, yB0, hB, yP0, hP, yQ0, hQ, yQm, X, tOf, YB, YP, YQ, bnv, off, lo, hi, compact };
}

function path(G, w, fn, step, skip) {
  let p = '', pen = false;
  for (let t = w.from; t <= w.to; t += step) {
    const v = skip && skip(t) ? null : fn(t);
    if (v == null) { pen = false; continue; }
    p += (pen ? 'L' : 'M') + G.X(t).toFixed(1) + ' ' + v.toFixed(1); pen = true;
  }
  return p;
}

function seriesMarkup(G, w) {
  const st = G.compact ? 4 : 2, out = [];
  out.push(html`<path d=${path(G, w, t => { const v = G.bnv(t); return v == null ? null : G.YB(v); }, st)} fill="none" stroke="var(--binance)" stroke-width=${G.compact ? 1 : 1.3} />`);
  if (w.hasCL) out.push(html`<path d=${path(G, w, t => { const v = w.cl(t); return v == null ? null : G.YB(v); }, 1)} fill="none" stroke="var(--fg)" stroke-width=${G.compact ? 1.4 : 1.8} />`);
  if (w.hasBook) {
    const mid = (f, side) => t => { const q = f(t); return q ? G.YP(side === 'Up' ? (q[0] + q[1]) / 2 : (q[0] + q[1]) / 2) : null; };
    out.push(html`<path d=${path(G, w, mid(w.up, 'Up'), st)} fill="none" stroke="var(--up)" stroke-width="1.6" />`);
    out.push(html`<path d=${path(G, w, mid(w.down, 'Down'), st)} fill="none" stroke="var(--down)" stroke-width="1.6" />`);
  }
  if (w.mf) { // Polymarket's once-a-minute prices: dotted, because nothing in between was recorded
    for (const [k, c] of [['up', 'var(--up)'], ['down', 'var(--down)']]) {
      const d = w.mf[k].map(([t, p], i) => (i ? 'L' : 'M') + G.X(t).toFixed(1) + ' ' + G.YP(p).toFixed(1)).join('');
      out.push(html`<path d=${d} fill="none" stroke=${c} stroke-width="1.5" stroke-dasharray="2 3" />`);
    }
  }
  // position: steps at each change, Up above the line, Down below
  for (const [k, sgn, c] of [[1, 1, 'var(--up)'], [2, -1, 'var(--down)']]) {
    let d = `M${G.X(w.from)} ${G.yQm}`, prev = 0;
    for (const p of w.pos) { const v = p[k]; d += `L${G.X(p[0]).toFixed(1)} ${G.YQ(sgn * prev).toFixed(1)}L${G.X(p[0]).toFixed(1)} ${G.YQ(sgn * v).toFixed(1)}`; prev = v; }
    d += `L${G.X(w.to)} ${G.YQ(sgn * prev).toFixed(1)}L${G.X(w.to)} ${G.yQm}Z`;
    out.push(html`<path d=${d} fill=${c} opacity=".26" />`);
  }
  return out;
}

const burstR = b => Math.min(11, 3.5 + Math.sqrt(b.shares) / 3.2);

function marksMarkup(G, w, onBurst, sel) {
  return w.bursts.map(b => {
    const x = G.X(b.t0), up = b.side === 'Up', s = G.compact ? Math.min(6, burstR(b) * .7) : burstR(b);
    const bv = w.cl(b.t0) ?? G.bnv(b.t0); const y = bv == null ? G.yB0 + G.hB / 2 : G.YB(bv);
    const yy = up ? y - s - 3 : y + s + 3; // above the line for Up, below for Down
    const fill = up ? 'var(--up)' : 'var(--down)';
    const shape = b.action === 'sell'
      ? html`<rect class="shape" x=${x - s} y=${yy - s} width=${2 * s} height=${2 * s} fill="var(--card)" stroke=${fill} stroke-width="2" />`
      : html`<path class="shape" d=${`M${x} ${up ? yy - s : yy + s}L${x - s} ${up ? yy + s * .75 : yy - s * .75}H${x + s}Z`} fill=${fill} stroke="var(--card)" stroke-width="1.2" />`;
    const label = `${b.action === 'buy' ? 'Bought' : 'Sold'} ${shares(b.shares)} ${b.side}, ${b.fills.length} fills from ${mmss(b.t0)}`;
    const on = sel === b.id;
    return html`<g class="burst" key=${b.id} tabindex=${G.compact ? -1 : 0} role="button" aria-label=${label}
      onClick=${e => { e.stopPropagation(); onBurst && onBurst(b); }} onKeyDown=${e => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); onBurst && onBurst(b); } }}>
      <line x1=${x} x2=${x} y1=${G.yB0} y2=${G.yQ0 + G.hQ} stroke=${fill} stroke-opacity=${on ? .7 : .14} />
      <circle cx=${x} cy=${yy} r=${s + 6} fill="transparent" />${shape}
      <circle cx=${x} cy=${G.YP(b.avg)} r=${G.compact ? 2.4 : 3.2} fill=${fill} stroke="var(--card)" stroke-width="1" /></g>`;
  });
}

function frameMarkup(G, w) {
  const f = [], ml = G.ml, R = G.W - G.mr, x0 = G.X(0);
  f.push(html`<rect x=${G.X(w.from)} y=${G.yB0} width=${x0 - G.X(w.from)} height=${G.yQ0 + G.hQ - G.yB0} fill="var(--soft)" />`);
  if (w.to > w.end) f.push(html`<rect x=${G.X(w.end)} y=${G.yB0} width=${G.X(w.to) - G.X(w.end)} height=${G.yQ0 + G.hQ - G.yB0} fill="var(--soft)" opacity=".6" />`);
  for (const [a, len] of w.holes) f.push(html`<rect x=${G.X(a)} y=${G.yP0} width=${Math.max(1.5, G.X(a + len) - G.X(a))} height=${G.hP} fill="url(#rhatch)"><title>${(w.lost.find(l => l.from <= a + 1 && l.to >= a) || {}).why || 'Not recorded'}</title></rect>`);
  if (!w.hasBook && !w.mf) f.push(html`<rect x=${x0} y=${G.yP0} width=${G.X(w.end) - x0} height=${G.hP} fill="url(#rhatch)" />`);
  if (!G.compact) {
    const span = G.hi - G.lo, raw = span / 4, stepv = [5, 10, 20, 25, 50, 100, 200, 500].find(s => s >= raw) || 1000;
    for (let v = Math.ceil(G.lo / stepv) * stepv; v <= G.hi; v += stepv) f.push(html`<line class="gridl" x1=${ml} x2=${R} y1=${G.YB(v)} y2=${G.YB(v)} /><text class="ax" x=${ml - 8} y=${G.YB(v) + 3.5} text-anchor="end">$${Math.round(v).toLocaleString('en-US')}</text>`);
    for (const c of [0, 50, 100]) f.push(html`<line class="gridl" x1=${ml} x2=${R} y1=${G.YP(c)} y2=${G.YP(c)} /><text class="ax" x=${ml - 8} y=${G.YP(c) + 3.5} text-anchor="end">${c}¢</text>`);
    f.push(html`<line class="gridl" x1=${ml} x2=${R} y1=${G.yQm} y2=${G.yQm} /><text class="axs" x=${ml - 8} y=${G.yQ0 + 10} text-anchor="end">Up shares</text><text class="axs" x=${ml - 8} y=${G.yQ0 + G.hQ - 2} text-anchor="end">Down</text>`);
    for (let m = Math.ceil(w.from / 60); m * 60 <= w.to; m++) {
      const x = G.X(m * 60); f.push(html`<line x1=${x} x2=${x} y1=${G.yQ0 + G.hQ} y2=${G.yQ0 + G.hQ + (m % 3 ? 3 : 6)} stroke="var(--faint)" />`);
      if (m % 3 === 0) f.push(html`<text class="ax" x=${x} y=${G.yQ0 + G.hQ + 18} text-anchor="middle">${m < 0 ? '−' : ''}${Math.abs(m)}:00</text>`);
    }
    f.push(html`<text class="axs" x=${R + 10} y=${G.yQ0 + G.hQ + 18}>min from start</text>`);
    f.push(html`<text class="axs" x=${x0 + 4} y=${G.yP0 - 5}>Up and Down on Polymarket (¢ a share)</text><text class="axs" x=${x0 + 4} y=${G.yQ0 - 5}>Position (shares)</text>`);
    if (!w.hasBook) f.push(html`<text class="axs" x=${x0 + 8} y=${G.yP0 + 12}>${w.mf ? "No order book for this window: dotted lines are Polymarket's once-a-minute prices" : 'No Up or Down prices for this window'}</text>`);
  }
  f.push(html`<line x1=${x0} x2=${x0} y1=${G.yB0} y2=${G.yQ0 + G.hQ} stroke="var(--faint)" stroke-width="1.2" />`);
  f.push(html`<line x1=${x0} x2=${G.X(w.end)} y1=${G.YB(w.ptb)} y2=${G.YB(w.ptb)} stroke="var(--faint)" stroke-width="1.2" stroke-dasharray="5 4" />`);
  if (!w.clFull) f.push(html`<circle cx=${x0} cy=${G.YB(w.ptb)} r=${G.compact ? 3 : 4} fill="var(--fg)" />`);
  if (!G.compact) {
    const ends = [{ y: G.YB(w.ptb), t: 'Price to beat', c: 'var(--muted)' }];
    const bE = G.bnv(w.end); if (bE != null) ends.push({ y: G.YB(bE), t: G.off ? 'Binance (lined up)' : 'Binance BTCUSDT', c: 'var(--binance)' });
    if (w.hasCL && w.cl(w.end) != null) ends.push({ y: G.YB(w.cl(w.end)), t: `Chainlink ${btc(w.cl(w.end))}`, c: 'var(--fg)' });
    ends.push({ y: G.YB(w.final ?? w.ptb) + (w.result === 'Up' ? -14 : 14), t: `Settled ${w.result}`, c: w.result === 'Up' ? 'var(--up)' : 'var(--down)' });
    ends.sort((a, b) => a.y - b.y); for (let i = 1; i < ends.length; i++) if (ends[i].y - ends[i - 1].y < 13) ends[i].y = ends[i - 1].y + 13;
    for (const e of ends) f.push(html`<text class="endl" x=${R + 8} y=${e.y + 4} fill=${e.c}>${e.t}</text>`);
    const [u, d] = w.posAt(w.to);
    f.push(html`<text class="endl" x=${R + 8} y=${G.YQ(u) + 4} fill="var(--up)">${shares(u)} Up</text><text class="endl" x=${R + 8} y=${G.YQ(-d) + 4} fill="var(--down)">${shares(d)} Down</text>`);
    if (!w.clFull) f.push(html`<text class="axs" x=${x0 + 8} y=${G.YB(w.ptb) + 14}>Chainlink BTC/USD not recorded here: its start price (the price to beat) and the result only</text>`);
  }
  return f;
}

function annMarkup(G, anns, pin) {
  const out = [];
  for (const a of anns || []) {
    if (a.kind === 'point') { const x = G.X(a.t0); out.push(html`<line class="ann" x1=${x} x2=${x} y1=${G.yB0} y2=${G.yB0 + G.hB} stroke-dasharray="4 3" /><text class="ann-t" x=${x + 4} y=${G.yB0 + 12}>${a.label}</text>`); }
    if (a.kind === 'span') { const x0 = G.X(a.t0), x1 = G.X(a.t1), y = G.yB0 + (G.compact ? 10 : 20); out.push(html`<path class="ann" d=${`M${x0} ${y + 5}V${y}H${x1}V${y + 5}`} /><text class="ann-t" x=${(x0 + x1) / 2} y=${y - 4} text-anchor="middle">${a.label}</text>`); }
    if (a.kind === 'region') { const x0 = G.X(a.t0), x1 = G.X(a.t1); out.push(html`<rect class="ann-rg" x=${x0} y=${G.yB0} width=${Math.max(2, x1 - x0)} height=${G.hB} /><text class="ann-t" x=${x0 + 4} y=${G.yB0 + G.hB - 8}>${a.label}</text>`); }
  }
  if (pin != null) { const x = G.X(pin); out.push(html`<line x1=${x} x2=${x} y1=${G.yB0} y2=${G.yQ0 + G.hQ} stroke="var(--fg)" stroke-dasharray="2 3" /><circle cx=${x} cy=${G.yB0 + 3} r="4" fill="var(--fg)" /><text class="ann-t" x=${x + 7} y=${G.yB0 + 12} style="fill:var(--fg)">${mmss(pin)}</text>`); }
  return out;
}

// width: measured by the caller; ph: playhead (seconds) or null for the whole window; onHover(t|null), onMoment(t)
export function Chart({ w, width, compact, raw, ph, anns, pin, sel, onBurst, onHover, onMoment, phRef, id = 'c' }) {
  const G = useMemo(() => geometry(w, width, compact, raw), [w, width, compact, raw]);
  const series = useMemo(() => seriesMarkup(G, w), [G, w]);
  const frame = useMemo(() => frameMarkup(G, w), [G, w]);
  const marks = marksMarkup(G, w, onBurst, sel);
  const clip = useRef(), line = useRef(), xh = useRef(), svg = useRef();
  const reveal = ph != null;
  useEffect(() => { // the playhead moves by attribute: no re-render per animation frame
    if (!reveal) return; const x = G.X(ph);
    if (clip.current) clip.current.setAttribute('width', Math.max(0, x + 2));
    if (line.current) { line.current.setAttribute('x1', x); line.current.setAttribute('x2', x); }
  });
  if (phRef) phRef.current = t => { // Play moves the playhead between steps without a render per frame
    const x = G.X(t);
    if (clip.current) clip.current.setAttribute('width', Math.max(0, x + 2));
    if (line.current) { line.current.setAttribute('x1', x); line.current.setAttribute('x2', x); line.current.setAttribute('visibility', 'visible'); }
  };
  const tAt = e => { const r = svg.current.getBoundingClientRect(); return G.tOf((e.clientX - r.left) * (G.W / r.width)); };
  const body = reveal
    ? html`<g opacity=".17">${series}${marks}</g><g clip-path=${`url(#${id}r)`}>${series}${marks}</g>`
    : html`${series}${marks}`;
  return html`<svg ref=${svg} width=${G.W} height=${G.H} viewBox=${`0 0 ${G.W} ${G.H}`} role="img" aria-label=${`Window ${w.id}: BTC on Binance${w.hasCL ? ' and Chainlink' : ''}, Up and Down prices, the wallet's buys and position`} style="max-width:100%;height:auto">
    <defs><clipPath id=${`${id}r`}><rect ref=${clip} x="0" y="0" width=${reveal ? G.X(ph) + 2 : G.W} height=${G.H} /></clipPath></defs>
    ${frame}
    ${!compact && html`<rect class="hov" x=${G.ml} y=${G.yB0} width=${G.W - G.ml - G.mr} height=${G.yQ0 + G.hQ - G.yB0} fill="transparent"
      onMouseMove=${e => { const t = tAt(e); if (xh.current) { xh.current.setAttribute('x1', G.X(t)); xh.current.setAttribute('x2', G.X(t)); xh.current.setAttribute('visibility', 'visible'); } onHover && onHover(t); }}
      onMouseLeave=${() => { if (xh.current) xh.current.setAttribute('visibility', 'hidden'); onHover && onHover(null); }}
      onClick=${e => onMoment && onMoment(tAt(e))} />`}
    ${body}
    <g pointer-events="none">${annMarkup(G, anns, pin)}
      <line ref=${xh} x1="0" x2="0" y1=${G.yB0} y2=${G.yQ0 + G.hQ} stroke="var(--muted)" visibility="hidden" />
      <line ref=${line} x1=${reveal ? G.X(ph) : 0} x2=${reveal ? G.X(ph) : 0} y1=${G.yB0} y2=${G.yQ0 + G.hQ} stroke="var(--accent)" stroke-width="1.5" visibility=${reveal ? 'visible' : 'hidden'} /></g>
  </svg>`;
}

// A tile's small picture, from window.summary: BTC from where the window started (Binance), entries on the bottom edge
export function Spark({ s, width = 200, height = 50 }) {
  const pts = s.spark || [], t0 = s.start, t1 = s.end;
  if (!pts.length) return html`<svg viewBox=${`0 0 ${width} ${height}`} aria-hidden="true"><rect width=${width} height=${height} fill="url(#rhatch)" /></svg>`;
  const from = Math.min(pts[0].t, ...(s.entries || []).map(e => e.t)), to = Math.max(pts[pts.length - 1].t, t1);
  const X = t => 2 + (t - from) / (to - from) * (width - 4);
  const base = (pts.find(p => p.t >= t0) || pts[0]).p, m = Math.max(30, ...pts.map(p => Math.abs(p.p - base)));
  const mid = (height - 10) / 2, Y = v => mid - (v - base) / m * (mid - 3);
  const d = pts.map((p, i) => (i ? 'L' : 'M') + X(p.t).toFixed(1) + ' ' + Y(p.p).toFixed(1)).join('');
  const ticks = (s.entries || []).map(e => html`<line x1=${X(e.t)} x2=${X(e.t)} y1=${e.side === 'Up' ? height - 9 : height - 4} y2=${e.side === 'Up' ? height - 5 : height} stroke=${e.side === 'Up' ? 'var(--up)' : 'var(--down)'} stroke-width="1" opacity=".7" />`);
  return html`<svg viewBox=${`0 0 ${width} ${height}`} aria-hidden="true">
    <rect x=${X(from)} y="0" width=${X(t0) - X(from)} height=${height} fill="var(--soft)" />
    <line x1=${X(t0)} x2=${X(to)} y1=${mid} y2=${mid} stroke="var(--faint)" stroke-dasharray="2 2" />
    <path d=${d} fill="none" stroke="var(--fg)" stroke-width="1.1" />${ticks}</svg>`;
}

export const Hatch = () => html`<svg width="0" height="0" style="position:absolute" aria-hidden="true"><defs><pattern id="rhatch" width="6" height="6" patternUnits="userSpaceOnUse" patternTransform="rotate(45)"><line x1="0" y1="0" x2="0" y2="6" stroke="var(--hatch)" stroke-width="1.6" stroke-opacity=".5" /></pattern></defs></svg>`;
