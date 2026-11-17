// How research pages write numbers, times and names (AGENTS.md "Research wording": whole cents, tenths only under
// 1¢; times in UTC; the wallet by its Polymarket name, else "Trader 0x91…76").

const n2 = { minimumFractionDigits: 2, maximumFractionDigits: 2 };
export const money = v => '$' + Math.abs(v).toLocaleString('en-US', n2);
export const signedMoney = v => (Math.round(v * 100) < 0 ? '−' : '+') + money(v);
export const btc = v => '$' + v.toLocaleString('en-US', n2);
export const signedBtc = v => (v < 0 ? '−' : '+') + '$' + Math.abs(v).toLocaleString('en-US', n2);
// c is in cents (0–100)
export const cents = c => (c == null ? '–' : (c < 1 || c > 99) ? c.toFixed(1) + '¢' : Math.round(c) + '¢');
export const shares = v => (Math.abs(v) >= 100 ? Math.round(v).toLocaleString('en-US') : (Math.round(v * 10) / 10).toLocaleString('en-US'));
export const count = v => v.toLocaleString('en-US');

// seconds from the window's start: "+5:43", "−0:47"
export const mmss = t => { t = Math.round(t); const neg = t < 0; t = Math.abs(t); return (neg ? '−' : '+') + Math.floor(t / 60) + ':' + String(t % 60).padStart(2, '0'); };
export const clock = unix => new Date(Math.round(unix) * 1000).toISOString().slice(11, 19);
export const hm = unix => new Date(unix * 1000).toISOString().slice(11, 16);
const MON = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
export const day = unix => { const d = new Date(unix * 1000); return d.getUTCDate() + ' ' + MON[d.getUTCMonth()]; };
export const windowLabel = (start, end) => `${day(start)}, ${hm(start)}–${hm(end)} UTC`;

export const traderName = s => (s && s.name) ? s.name : s && s.wallet ? `Trader ${s.wallet.slice(0, 4)}…${s.wallet.slice(-2)}` : 'this wallet';
// The wallet pills in "Your breakdowns" (owner, 16 Nov: a colour per wallet, so the groups read apart). Eight hues,
// no red or green (those mean losses and gains here). A wallet's hue comes from its address (the main app's avatar
// hash), so it stays the same visit to visit; one too close to the group above jumps four places, so two groups
// next to each other never look alike.
export const PILL_HUES = [45, 185, 205, 228, 250, 275, 300, 325];
const hash32 = s => {
  let h = 2166136261;
  for (let i = 0; i < s.length; i++) { h ^= s.charCodeAt(i); h = Math.imul(h, 16777619); }
  h ^= h >>> 16; h = Math.imul(h, 0x85ebca6b); h ^= h >>> 13; h = Math.imul(h, 0xc2b2ae35); h ^= h >>> 16;
  return h >>> 0;
};
// wallets in the order shown → their hues (null for a group with no wallet: a grey pill, and no neighbour to avoid)
export const pillHues = wallets => {
  const n = PILL_HUES.length;
  let prev = null;
  return wallets.map(w => {
    if (!w) { prev = null; return null; }
    let slot = hash32(String(w).toLowerCase()) % n;
    const near = prev !== null && Math.min((slot - prev + n) % n, (prev - slot + n) % n) < 2;
    if (near) slot = (slot + 4) % n;
    prev = slot;
    return PILL_HUES[slot];
  });
};
export const plural = (n, one, many) => `${count(n)} ${n === 1 ? one : (many || one + 's')}`;
export const esc = s => String(s ?? '').replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));

// a full wallet address in a title reads shortened ("No wallet addresses on screen"; the question keeps what was typed)
export const shortWallets = t => String(t || '').replace(/0x[0-9a-fA-F]{40}/g, a => `${a.slice(0, 6)}…${a.slice(-4)}`);

// how long ago, for the list of breakdowns (owner, 17 Nov: "18 h ago", never a UTC stamp there): minutes, hours, days
export const ago = (t, now = Date.now() / 1000) => {
  const s = Math.max(0, now - t);
  if (s < 3600) return `${Math.max(1, Math.round(s / 60))} min ago`;
  if (s < 86400) return `${Math.round(s / 3600)} h ago`;
  const d = Math.floor(s / 86400);
  return d === 1 ? 'yesterday' : `${d} days ago`;
};
