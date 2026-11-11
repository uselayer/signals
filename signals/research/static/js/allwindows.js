// Every window at once, from the tiles alone (window.summary): no read, no model. Two different things are kept
// apart, because a wallet that buys both Up and Down can buy more of the winning side and still lose money:
//  - the market: did it buy more shares of the side that won (`favWon`)? Its shares bought per side vs the result.
//  - the money: did the window make money (`made`)? Its profit from fills and the payout of shares held at the end.

// What a tile counts as. A window without a result (or a profit) yet is neither, and is left out of both counts.
export function windowFacts(s) {
  const r = s.result === 'Up' || s.result === 'Down' ? s.result : null;
  const sh = s.shares || {}, won = r ? sh[r.toLowerCase()] || 0 : 0, lost = r ? sh[r === 'Up' ? 'down' : 'up'] || 0 : 0;
  return {
    made: s.profit != null && Math.round(s.profit * 100) > 0, lostMoney: s.profit != null && Math.round(s.profit * 100) < 0,
    favWon: r != null && won > lost, favLost: r != null && lost > won,
  };
}

export const FILTERS = [
  ['made', 'Made money', f => f.made], ['lostMoney', 'Lost money', f => f.lostMoney],
  ['favWon', 'Bought more of the winning side', f => f.favWon], ['favLost', 'Bought more of the losing side', f => f.favLost],
];

export function filterTiles(tiles, key) {
  const f = FILTERS.find(x => x[0] === key);
  return f ? tiles.filter(s => f[2](windowFacts(s))) : tiles;
}

// The counts the Windows tab says in one line, and what each filter would show.
export function tally(tiles) {
  const n = { made: 0, lostMoney: 0, favWon: 0, favLost: 0, profitMade: 0, profitLost: 0, decided: 0 };
  for (const s of tiles) {
    const f = windowFacts(s);
    if (s.profit != null) n.decided += 1;
    for (const k of ['made', 'lostMoney', 'favWon', 'favLost']) if (f[k]) n[k] += 1;
    if (f.made) n.profitMade += s.profit; else if (f.lostMoney) n.profitLost += s.profit;
  }
  return n;
}

// Binance BTCUSDT at t from a tile's line (a point every ~15 s), straight between points; null outside it.
export function sparkAt(pts, t) {
  if (!pts || !pts.length || t < pts[0].t || t > pts[pts.length - 1].t) return null;
  let i = 1; while (i < pts.length && pts[i].t < t) i += 1;
  if (i >= pts.length) return pts[pts.length - 1].p;
  const a = pts[i - 1], b = pts[i];
  return b.t === a.t ? b.p : a.p + (b.p - a.p) * (t - a.t) / (b.t - a.t);
}

// One point per buy: when in the window (seconds from its start) and how far BTC was from the price to beat, toward
// the side it bought ($, positive = BTC was on that side: above the line for Up, below it for Down). Where Chainlink
// BTC/USD was recorded (the feed the price to beat is averaged from), that's Chainlink against the price to beat
// (`basis: 'ptb'`). Before that, Binance BTCUSDT's move since the window opened (`basis: 'open'`, the tile's dashed
// line): Binance is BTC in Tether, about 0.1% above Chainlink, so it's never measured against the price to beat
// itself. Windows with neither line are counted, not drawn.
export function buyPoints(tiles) {
  const pts = []; let noLine = 0;
  for (const s of tiles) {
    const cl = s.chainlink_spark, sp = s.spark || [], facts = windowFacts(s);
    const ptb = cl && cl.length && s.price_to_beat != null;
    const line = ptb ? cl : sp, ref = ptb ? s.price_to_beat : (sp.find(p => p.t >= s.start) || {}).p;
    if (ref == null) { noLine += 1; continue; }
    for (const e of s.entries || []) {
      if (e.action !== 'buy' || (e.side !== 'Up' && e.side !== 'Down')) continue;
      const p = sparkAt(line, e.t);
      if (p == null) continue;
      pts.push({ window_id: s.window_id, start: s.start, t: e.t - s.start, side: e.side, toward: (p - ref) * (e.side === 'Up' ? 1 : -1),
        basis: ptb ? 'ptb' : 'open',
        sideWon: s.result === e.side, sideLost: (s.result === 'Up' || s.result === 'Down') && s.result !== e.side, made: facts.made, lostMoney: facts.lostMoney, profit: s.profit });
    }
  }
  return { pts, noLine };
}
