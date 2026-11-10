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
export const plural = (n, one, many) => `${count(n)} ${n === 1 ? one : (many || one + 's')}`;
export const esc = s => String(s ?? '').replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
