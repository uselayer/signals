// The research page (usesignals.app/breakdowns; /research/ on the service): Breakdowns, and one breakdown's workspace (an "investigation" in the code and contract). Routes: #/ (yours, and a new
// one), #/i/<id> (an investigation). ?fixtures plays recorded data with no service; ?sample is the same recorded run
// for visitors (no sign-in: the signed-out page's "Watch a sample breakdown"); ?signin opens Sign in at once; ?q=
// prefills a question (the main site's ask bar sends it).
import { html, render, useState, useEffect, useRef, useMemo } from '../vendor/htm-preact-3.1.1.module.js';
import { live, startAuth, openSignIn, mountUser, copyTradingOn } from './api.js';
import { fixtureApi } from './fixtures.js';
import { emptyInv, emptyUi, apply, planProgress, rowProgress, rowState, yesText, groups, runs, runTitle, currentPlan, runSummaries, borrowedWindows, planOfRun, RANGES, defaultRange, askScope } from './store.js';
import { prep, autoSteps, agentSteps, burstText, posText } from './windowdata.js';
import { PlanStage, WindowsStage, ReplayStage, TradesStage } from './views.js';
import { AgentColumn } from './agent.js';
import { isMarket, marketTypeOf, prepMarket, marketAutoSteps, marketAgentSteps, marketTally, shortDate, dateTime } from './marketdata.js';
import { MarketsStage, MarketReplay, MarketTrades } from './marketview.js';
import { Hatch } from './chart.js';
import { traderName, windowLabel, signedMoney, money, mmss, clock, signedBtc, cents, shares, plural, shortWallets, count } from './format.js';

const LOGO = html`<svg width="16" height="16" viewBox="0 0 20 20" fill="currentColor" aria-hidden="true"><rect x="3" y="11" width="3" height="6" rx="1" /><rect x="8.5" y="7" width="3" height="10" rx="1" /><rect x="14" y="3" width="3" height="14" rx="1" /></svg>`;
const params = new URLSearchParams(location.search);
const SAMPLE = params.has('sample'), FIXTURES = SAMPLE || params.has('fixtures');
const route = () => { const m = /^#\/i\/([\w-]+)/.exec(location.hash); return m ? { inv: m[1] } : { home: true }; };

// The main site's tabs, the same order; Copy trading only for an account with copying on (as the main site's header).
function Top({ fixtures, copyTrading }) {
  const acct = useRef();
  useEffect(() => mountUser(acct.current));
  return html`<header class="top"><div class="in">
    <a class="brand" href="/"><span class="logo">${LOGO}</span>Signals</a>
    <nav class="tabs" aria-label="Main"><a class="on new" href="#/">Breakdowns</a><a href="/#/">Feed</a><a href="/#/watchlist">Watchlist</a><a href="/#/traders">Traders</a>${copyTrading && html`<a href="/#/copies">Copy trading</a>`}</nav>
    <div class="acct">${SAMPLE ? html`<span class="chip">Sample: a recorded breakdown</span><a class="btn sm primary" href="./?signin#/">Sign in to ask your own</a>`
      : fixtures ? html`<span class="chip">Fixtures: recorded data, no service</span>` : html`<div ref=${acct}></div>`}</div></div></header>`;
}

function App() {
  const [api, setApi] = useState(null), [r, setR] = useState(route()), [gate, setGate] = useState(null), [err, setErr] = useState(null), [types, setTypes] = useState(null), [copyTrading, setCopyTrading] = useState(false);
  useEffect(() => { const f = () => setR(route()); addEventListener('hashchange', f); return () => removeEventListener('hashchange', f); }, []);
  useEffect(() => { (async () => {
    try {
      const a = FIXTURES ? await fixtureApi() : live;
      const cfg = await a.config();
      if (cfg.event_version > 2) setErr('This page is older than the research service. Reload to get the new one.');
      setTypes(cfg.market_types && cfg.market_types.length ? cfg.market_types : null);
      const au = FIXTURES ? { signedIn: true } : await startAuth(cfg.clerk_key);
      if (!au.signedIn) { setGate('signin'); if (params.has('signin')) openSignIn(); window.Clerk && window.Clerk.addListener(() => { if (window.Clerk.isSignedIn) { setGate(null); copyTradingOn().then(setCopyTrading); } }); }
      else if (!FIXTURES) copyTradingOn().then(setCopyTrading);
      setApi(a);
    } catch (e) { setErr(e.message || 'The research service isn\'t reachable.'); }
  })(); }, []);
  return html`<${Hatch} /><${Top} fixtures=${FIXTURES} copyTrading=${copyTrading} />
    ${err && html`<div class="home"><div class="banner err"><div><p>${err}</p><p class="small muted" style="margin-top:4px">To see the page with recorded data, open <a class="link" href="?fixtures#/">fixtures mode</a>.</p></div></div></div>`}
    ${!err && !api && html`<div class="home"><p class="muted">Loading…</p></div>`}
    ${api && gate === 'signin' && html`<${Teaser} />`}
    ${api && !gate && (r.inv ? html`<${Investigation} key=${r.inv} api=${api} id=${r.inv} />` : html`<${Home} api=${api} types=${types || MARKET_TYPES} />`)}`;
}

// Example questions under the ask box (owner, 10 Nov: four, small, one row, and each must say WHICH wallet; 16 Nov:
// the goal first, the wallet it uses under it). Three use the sample traders; the fourth is "Pick one for me". Two sample traders
// share them (owner: mix and match two traders across the four), both active in every BTC 15-minute window. With the
// wallet field empty, or holding a sample trader's wallet, each card names its own trader and a click fills both fields;
// with any other wallet typed, every card names that one (shortened) and fills the question only. A click never starts
// anything: Break it down still shows the plan and its cost first. BTC 15-minute only.
const SAMPLE_TRADERS = [
  { wallet: '0xbdaacd345fec209cd09d933e62f92e8b530afd60', name: 'the.prod.dt' },
  { wallet: '0x329df14a9e177b5bade2228b9062265697a5b047', name: 'HuskyTrade' },
];
// The ask box's Market choice when the service doesn't list its types (an older service): 15-minute windows only.
const MARKET_TYPES = [{ id: 'btc-updown-15m', label: 'BTC Up or Down 15m', unit: 'window', min_days: 0 }];
const EXAMPLES = [  // [sample trader, card (the goal), question]
  [1, () => `Learn a BTC 15-minute trader's pattern`, w => `How does ${w} trade BTC 15-minute markets? Which side does it buy, when in the window, and at what prices?`],
  [0, () => `Replay its latest 15-minute window`, w => `Replay ${w}'s latest finished BTC 15-minute window: when did it buy Up and Down, and where was BTC?`],
  [1, () => `Compare its winning and losing windows`, w => `In BTC 15-minute markets, compare ${w}'s winning and losing windows: what did it do differently?`],
];

// Signed out: what a breakdown is, the recorded one to watch (no sign-in, no model run), and Sign in to ask your own.
function Teaser() {
  return html`<main class="home teaser">
    <div style="display:flex;flex-direction:column;gap:10px"><span class="tag new">New</span><h1>Breakdowns</h1>
      <p class="muted">Paste a wallet or name a trader, then ask in your own words. The agent shows its plan before it reads anything, then lays every trade out on a chart you can replay. Polymarket only; research, no trading.</p></div>
    <a class="sample-card" href="?sample#/">
      <span class="muted small">A sample breakdown, recorded</span>
      <q>Analyze this wallet's BTC 15-minute trades. Plot its entries against Binance and Polymarket prices, show how its positions change over time, and help me understand its trading strategy.</q>
      <span class="go">Watch it run →</span></a>
    <div class="row"><button class="btn primary" onClick=${openSignIn}>Sign in to ask your own</button><a class="btn" href="?sample#/">Watch a sample breakdown</a></div>
    <p class="muted small">Your breakdowns are only ever yours.</p>
  </main>`;
}

// What you opened and when (the main page's pill reads it too: same origin), and since when "ready" counts.
const OPENED = 'signals.breakdowns.opened', SINCE = 'signals.breakdowns.since';
// On a phone, one quiet line near the top of a breakdown, once a session (owner, 15 Nov): the charts and the market
// list are long there. Shown in the first breakdown opened on a phone; Dismiss hides it until the next session.
const PHONE_NOTE = 'breakdowns.phoneNote';
let phoneNoteOn = null; // decided once a page load
function phoneNoteShown() {
  if (phoneNoteOn === null) {
    let seen = false;
    try { seen = sessionStorage.getItem(PHONE_NOTE) === '1'; } catch {}
    const phone = typeof matchMedia === 'function' && matchMedia('(max-width: 600px)').matches;
    phoneNoteOn = phone && !seen;
    if (phoneNoteOn) try { sessionStorage.setItem(PHONE_NOTE, '1'); } catch {}
  }
  return phoneNoteOn;
}
function PhoneNote() {
  const [on, setOn] = useState(phoneNoteShown);
  if (!on) return null;
  return html`<p class="phonenote muted small" role="note"><span>Breakdowns read best on a computer: the charts and market list are long on a phone.</span>
    <button class="link" onClick=${() => { phoneNoteOn = false; setOn(false); }}>Dismiss</button></p>`;
}

const readLs = (k, d) => { try { return JSON.parse(localStorage.getItem(k)) ?? d; } catch { return d; } };
const writeLs = (k, v) => { try { localStorage.setItem(k, JSON.stringify(v)); } catch {} };
function since() {
  let s = readLs(SINCE, null);
  if (typeof s !== 'number') { s = Date.now() / 1000; writeLs(SINCE, s); }
  return s;
}
since();
// You've seen breakdown `id` now: its Ready ends, here and on the main page. The 50 latest are kept.
function markOpened(id) {
  const o = readLs(OPENED, {});
  o[id] = Date.now() / 1000;
  writeLs(OPENED, Object.fromEntries(Object.entries(o).sort((a, b) => b[1] - a[1]).slice(0, 50)));
}
function rowLabel(s) {
  const st = rowState(s, readLs(OPENED, {}), since());
  if (st === 'running') return html`<span class="r run"><span class="dot live"></span>${rowProgress(s.progress)}</span>`;
  if (st === 'ready') return html`<span class="r ready">✓ Ready</span>`;
  if (st === 'queued') return html`<span class="r queued">Queued · starts after your current one</span>`;
  return html`<span class="r">${st === 'stopped' ? 'Stopped' : 'Saved'}</span>`;
}

// Wallets to study (owner, 16 Nov: someone with no wallet to reverse-engineer needs one to start from). The wallet
// field opens a list: "Pick one for me" first, then each market type's top wallets by trading profit over 30 days on
// Signals' Leaderboard (server: signals/research/suggest.py), facts only, never "recommended". Picking one fills the
// field with its name and sets Market to its type; typing filters it by name. "Pick one for me" sends the top wallet
// of the Market chosen, and the plan's page shows which one was picked, why, and the others to swap to before Start.
const PICK = { pick: true };
const PICKED = 'breakdowns.picked'; // {breakdown id: {wallet, name, why, others}}, the 20 latest, this browser only
const compactMoney = (v, signed) => {
  if (v == null) return '—';
  const a = Math.abs(v), s = signed ? (v < 0 ? '−' : '+') : '';
  return s + '$' + (a >= 1e6 ? `${(a / 1e6).toFixed(a >= 1e7 ? 1 : 2)}M` : a >= 1e3 ? `${Math.round(a / 1e3)}K` : Math.round(a));
};
const whyOf = r => (r.rank ? `#${r.rank} in ${r.category} by trading profit, 30 days` : 'A sample trader, in every BTC 15-minute window');
const shortLabel = t => t.label.replace(' Up or Down ', ' '); // as the Market pills say it
const marketWords = t => (t.unit === 'window' ? 'BTC 15-minute' : t.id === 'politics' ? 'politics' : t.label);
const pickQuestion = t => `How does this wallet make money on ${marketWords(t)} markets?`;
function savePick(id, p) { const o = readLs(PICKED, {}); o[id] = { ...p, at: Date.now() / 1000 }; writeLs(PICKED, Object.fromEntries(Object.entries(o).sort((a, b) => b[1].at - a[1].at).slice(0, 20))); }
const pickOf = id => readLs(PICKED, {})[id] || null;

function useSuggestions(api) {
  const [s, setS] = useState(null);
  useEffect(() => {
    if (SAMPLE || !api.suggestions) return undefined;
    let t = 0, tries = 0;
    const load = () => api.suggestions().then(j => { setS(j); if (!j.ready && ++tries < 8) t = setTimeout(load, 6000); }, () => setS({ types: [], ready: true, failed: true }));
    load();
    return () => clearTimeout(t);
  }, []);
  return s;
}

function WhoTag({ bot }) {
  if (bot === 1 || bot === true) return html`<span class="who-tag bot">${BOT_ICON}Bot</span>`;
  if (bot === 0 || bot === false) return html`<span class="who-tag human">${HUMAN_ICON}Human</span>`;
  return null;
}

// The wallet field as a combobox: its list is "Pick one for me" and the suggestions, by market type.
function WalletField({ wallet, chosen, sugg, onText, onChoose, onClear }) {
  const [open, setOpen] = useState(false), [active, setActive] = useState(-1);
  const input = useRef();
  const text = wallet.trim().toLowerCase();
  const groupsShown = ((sugg && sugg.types) || []).map(g => ({ ...g, wallets: g.wallets.filter(w => !text || (w.name || '').toLowerCase().includes(text) || w.wallet.startsWith(text)) })).filter(g => g.wallets.length);
  const opts = [...(text ? [] : [{ pick: true }]), ...groupsShown.flatMap(g => g.wallets.map(w => ({ w, g })))];
  const loading = !text && (!sugg || !sugg.ready);
  const shown = open && !chosen && (opts.length > 0 || loading);
  const choose = o => { setOpen(false); setActive(-1); onChoose(o.pick ? PICK : o.w, o.g); };
  const key = e => {
    if (e.key === 'ArrowDown' || e.key === 'ArrowUp') { e.preventDefault(); setOpen(true); const n = opts.length; if (n) setActive(a => (e.key === 'ArrowDown' ? (a + 1) % n : (a - 1 + n) % n)); }
    else if (e.key === 'Enter' && shown && active >= 0 && opts[active]) { e.preventDefault(); choose(opts[active]); }
    else if (e.key === 'Escape') { setOpen(false); setActive(-1); }
    else if (chosen && (e.key === 'Backspace' || e.key === 'Delete')) { e.preventDefault(); onClear(); }
  };
  let i = -1;
  const optId = n => `wopt-${n}`;
  const row = (o, n) => html`<li id=${optId(n)} role="option" aria-selected=${active === n ? 'true' : 'false'} class=${'wopt' + (active === n ? ' on' : '')}
      onMouseDown=${e => e.preventDefault()} onClick=${() => choose(o)} onMouseEnter=${() => setActive(n)}>${o.pick
    ? html`<span class="wpick-ic" aria-hidden="true">${PICK_ICON}</span><span class="wmain"><b>Pick one for me</b><span class="muted small">Just ask your question. The top trader for the Market you choose is picked and named on the plan, before anything runs.</span></span>`
    : html`<span class="wmain"><span class="wname"><b>${traderName(o.w)}</b><${WhoTag} bot=${o.w.bot} /></span><span class="muted small">${whyOf(o.w)}</span></span>
      <span class="wnum"><b class=${(o.w.profit_30d || 0) >= 0 ? 'gain' : 'loss'}>${compactMoney(o.w.profit_30d, true)}</b><span class="muted small">${compactMoney(o.w.traded_30d)} traded</span></span>`}</li>`;
  return html`<div class="wfield">
    <input id="wallet" ref=${input} role="combobox" aria-label="Wallet" aria-autocomplete="list" aria-expanded=${shown ? 'true' : 'false'} aria-controls="wallet-list"
      aria-activedescendant=${shown && active >= 0 ? optId(active) : undefined} autocomplete="off" spellcheck="false"
      placeholder="Pick a wallet, or paste a 0x wallet or Polymarket name" readOnly=${!!chosen}
      value=${chosen ? (chosen.pick ? 'Pick one for me' : traderName(chosen)) : wallet}
      onFocus=${() => setOpen(true)} onClick=${() => setOpen(true)} onBlur=${() => setTimeout(() => setOpen(false), 120)}
      onInput=${e => { setOpen(true); setActive(-1); onText(e.target.value); }} onKeyDown=${key} />
    ${chosen ? html`<button type="button" class="wclear" aria-label="Clear the wallet" onClick=${() => { onClear(); setTimeout(() => input.current && input.current.focus(), 0); }}>×</button>`
      : html`<button type="button" class="wcaret" aria-label="Show wallets to study" tabIndex="-1" onMouseDown=${e => e.preventDefault()} onClick=${() => { setOpen(o => !o); if (input.current) input.current.focus(); }}>${CARET_ICON}</button>`}
    ${shown && html`<div class="wmenu"><ul id="wallet-list" role="listbox" aria-label="Wallets to study">
      ${opts[0] && opts[0].pick && row(opts[0], ++i)}
      ${groupsShown.map(g => html`<li role="presentation" class="wgrp"><b>${g.label}</b><span>trading profit, last 30 days</span></li>
        ${g.wallets.map(w => row({ w, g }, ++i))}`)}</ul>
      ${loading && html`<p class="muted small wnote">Finding wallets to study…</p>`}
      ${sugg && sugg.failed && !text && html`<p class="muted small wnote">Wallets to study couldn't load just now. Paste one, or browse Traders.</p>`}
      <div class="wfoot"><span>Picking one sets Market to its kind.</span><a class="link" href="/#/traders" onMouseDown=${e => e.preventDefault()}>Browse all traders →</a></div></div>`}
  </div>`;
}
const PICK_ICON = html`<svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><circle cx="10.5" cy="10.5" r="6.5"/><path d="M15.5 15.5 20 20"/><path d="M8 11.5l1.8-2 1.6 1.4 2-2.4"/></svg>`;
const CARET_ICON = html`<svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M6 9l6 6 6-6"/></svg>`;

// Above a plan that hasn't started: which wallet "Pick one for me" chose, why, and the others to study instead
// ("Change the plan" with that wallet: the same breakdown gets a new plan, nothing runs until Start).
function PickedCard({ pick, plan, act }) {
  if (!pick || !plan || plan.status !== 'proposed') return null;
  return html`<div class="picked">
    <div class="pk-head"><span class="muted small">Picked for you</span><b>${traderName(pick)}</b><${WhoTag} bot=${pick.bot} /><span class="muted small">${pick.why}${pick.profit_30d != null ? html` · <span class=${pick.profit_30d >= 0 ? 'gain' : 'loss'}>${compactMoney(pick.profit_30d, true)}</span> on ${compactMoney(pick.traded_30d)} traded` : ''}</span></div>
    ${pick.others && pick.others.length > 0 && html`<div class="pk-swap"><span class="muted small">Study instead:</span>${pick.others.map(o => html`<button type="button" class="btn sm" onClick=${() => act.swapWallet(plan.plan_id, o)}>${traderName(o)}</button>`)}</div>`}
  </div>`;
}

function Home({ api, types }) {
  // Market and Time range (store.js RANGES): what the plan will study, chosen before asking and sent with the question
  const [mid, setMid] = useState(() => (types.find(t => t.id === params.get('market')) || types[0]).id), [hours, setHours] = useState(null);
  const type = types.find(t => t.id === mid) || types[0], ranges = RANGES[type.unit] || RANGES.window;
  const h = ranges.some(([x]) => x === hours) ? hours : defaultRange(type.unit);
  const onMarket = id => { setMid(id); setHours(null); };
  // a wallet in the link (Traders' "Break it down"): the field holds it, by its name when the link carries one
  const linked = (params.get('wallet') || '').trim().toLowerCase(), linkedOk = /^0x[0-9a-f]{40}$/.test(linked);
  const [list, setList] = useState(null), [wallet, setWallet] = useState(FIXTURES ? '0xb945…db68' : linkedOk && !params.get('name') ? linked : ''), [q, setQ] = useState(params.get('q') || (FIXTURES ? "Analyze this wallet's BTC 15-minute trades. Plot its entries against Binance and Polymarket prices, show how its positions change over time, and help me understand its trading strategy." : ''));
  const [chosen, setChosen] = useState(() => (linkedOk && params.get('name') ? { wallet: linked, name: params.get('name').slice(0, 60) } : null));
  const sugg = useSuggestions(api);
  const [busy, setBusy] = useState(false), [err, setErr] = useState(null);
  // after a card: focus Break it down
  const go = useRef(), focusNext = useRef(null);
  useEffect(() => { const el = focusNext.current; focusNext.current = null; if (el && el.current) el.current.focus(); });
  // whom card i names: its own sample trader by name (also once a card filled a sample address in), else the wallet
  // in the field (by its name when it came from the list)
  const listed = chosen && !chosen.pick ? chosen : null;
  const typed = listed ? listed.wallet : wallet;
  const isSample = w => !w.trim() || SAMPLE_TRADERS.some(t => t.wallet === w.trim().toLowerCase());
  const whoOf = (w, i) => (isSample(w) ? SAMPLE_TRADERS[EXAMPLES[i][0]].name : listed && w === listed.wallet ? traderName(listed) : shortWallets(w.trim()));
  const isExample = s => !s.trim() || s === pickQuestion(type) || EXAMPLES.some(([, , question], j) => question(whoOf(typed, j)) === s);
  // the cards are BTC 15-minute questions, so a card also sets Market to it
  const pick = i => {
    if (chosen && chosen.pick) setChosen(null);
    if (!listed && isSample(wallet)) setWallet(SAMPLE_TRADERS[EXAMPLES[i][0]].wallet);
    setQ(EXAMPLES[i][2](whoOf(typed, i))); if (mid !== MARKET_TYPES[0].id) onMarket(MARKET_TYPES[0].id); focusNext.current = go;
  };
  const pickForMe = () => { setChosen(PICK); setWallet(''); setQ(pickQuestion(type)); focusNext.current = go; };
  // a card's question follows the wallet field, so it never names one trader while the field holds another
  const onWallet = w => { setWallet(w); const i = EXAMPLES.findIndex(([, , question], j) => question(whoOf(wallet, j)) === q); if (i >= 0) setQ(EXAMPLES[i][2](whoOf(w, i))); };
  const onChoose = (c, g) => {
    const t = (g && types.find(x => x.id === g.id)) || type;
    if (t.id !== mid) onMarket(t.id);
    setChosen(c); setWallet('');
    if (isExample(q)) setQ(c.pick ? pickQuestion(t) : `How does ${traderName(c)} make money on ${marketWords(t)} markets?`);
    focusNext.current = go;
  };
  const onClear = () => { if (chosen && chosen.pick && q === pickQuestion(type)) setQ(''); setChosen(null); };
  useEffect(() => { if (!SAMPLE) api.sessions().then(setList, e => setErr(e.message)); }, []);
  // while one of yours runs, its row's step and time left stay current
  const anyRunning = !!(list && list.some(s => s.running));
  useEffect(() => {
    if (!anyRunning) return undefined;
    const t = setInterval(() => api.sessions().then(setList, () => {}), 10000);
    return () => clearInterval(t);
  }, [anyRunning]);
  const start = async () => {
    if (!q.trim()) return;
    // "Pick one for me": the top wallet suggested for the Market chosen; the others are offered on the plan
    let w = wallet.trim(), named = null, picked = null, origin = 'pasted wallet';
    if (chosen && chosen.pick) {
      const g = ((sugg && sugg.types) || []).find(x => x.id === type.id);
      if (!g || !g.wallets.length) { setErr(sugg && sugg.ready ? `No wallets to pick from for ${shortLabel(type)} yet. Paste one, or choose another Market.` : 'Still finding wallets to pick from. Try again in a few seconds.'); return; }
      const [first, ...rest] = g.wallets;
      picked = { ...first, why: whyOf(first), others: rest.map(o => ({ ...o, why: whyOf(o) })) };
      w = first.wallet; named = first.name; origin = 'picked for you';
    } else if (listed) { w = listed.wallet; named = listed.name; origin = linkedOk && listed.wallet === linked ? 'trader page' : 'wallet list'; }
    else if (linkedOk && w === linked) origin = 'trader page';
    setBusy(true); setErr(null);
    try {
      const text = picked ? q.trim().replace(/\bthis wallet\b/, traderName(picked)) : q.trim();
      const walletLine = w && !text.includes(w) ? `Wallet: ${w}${named ? ` (${named} on Polymarket)` : ''}` : null;
      const lines = [walletLine, picked ? `Picked for the person asking, as the top ${type.label} wallet on Signals' Leaderboard: ${picked.why}.` : null, SAMPLE ? null : askScope(type, h)].filter(Boolean);
      const question = lines.length ? `${text}\n\n${lines.join('\n')}` : text;
      const id = await api.create(text.length <= 120 ? text : text.slice(0, 119).replace(/\s+\S*$/, '').replace(/[\s,;:(\-'"]+$/, '') + '…');
      if (picked) savePick(id, picked);
      await api.ask(id, question, null, origin);
      location.hash = `#/i/${id}`;
    } catch (e) { setErr(e.message); setBusy(false); }
  };
  return html`<main class="home">
    <div style="display:flex;flex-direction:column;gap:10px"><h1>What do you want to find out?</h1>
      <p class="muted">${SAMPLE ? 'This is a sample: a breakdown recorded from a real run, with its question filled in. Press Break it down to watch it plan, read and chart the trades. Sign in to ask your own.' : 'Polymarket only. Research, no trading.'}</p>
      <div class="compose-big">
        ${SAMPLE ? html`<input id="wallet" aria-label="Wallet" placeholder="Wallet address or Polymarket name" value=${wallet} readOnly />`
          : html`<${WalletField} wallet=${wallet} chosen=${chosen} sugg=${sugg} onText=${w => { setChosen(null); onWallet(w); }} onChoose=${onChoose} onClear=${onClear} />`}
        ${!SAMPLE && html`<div class="pickers" role="group" aria-label="What to study">
          <div class="prow"><span class="pl" id="market-l">Market</span><div class="seg" id="market" role="radiogroup" aria-labelledby="market-l">${types.map(t => html`<button type="button" role="radio" aria-checked=${t.id === type.id ? 'true' : 'false'} class=${t.id === type.id ? 'on' : ''} data-v=${t.id} onClick=${() => onMarket(t.id)}>${t.label.replace(' Up or Down ', ' ')}</button>`)}</div></div>
          <div class="prow"><span class="pl" id="range-l">Time range</span><div class="seg" id="range" role="radiogroup" aria-labelledby="range-l">${ranges.map(([x, label]) => html`<button type="button" role="radio" aria-checked=${x === h ? 'true' : 'false'} class=${x === h ? 'on' : ''} data-v=${String(x)} onClick=${() => setHours(x)}>${label}</button>`)}</div></div>
          <span class="muted small">${type.unit === 'window' ? 'Every window it traded. For a month or two, pick a market type with longer markets.' : `Its 20 markets with the most money${type.min_days ? `, of those that run ${type.min_days}+ days` : ''}.`}</span></div>`}
        <textarea id="q" rows="3" aria-label="Your question" placeholder=${type.unit === 'window' ? 'How does this wallet trade BTC 15-minute markets?' : `How does this wallet trade ${type.label} markets?`} value=${q} readOnly=${SAMPLE} onInput=${e => setQ(e.target.value)}></textarea>
        <div class="foot"><span class="muted small">${chosen && chosen.pick ? `The top ${shortLabel(type)} wallet is picked and named on the plan. Nothing runs until you press Start.` : "You'll see the plan and what it costs before it runs."}</span><button ref=${go} class="btn primary" disabled=${busy || !q.trim()} onClick=${start}>${busy ? 'Starting…' : 'Break it down'}</button></div></div>
      ${!SAMPLE && html`<div class="examples" aria-label="Example questions">
        <p class="muted small">Try asking</p>
        <div class="ex-grid">${EXAMPLES.map(([, label, question], i) => html`<button type="button" class=${'ex' + (q === question(whoOf(typed, i)) ? ' on' : '')} onClick=${() => pick(i)}><span>${label()}</span><span class="who">uses ${whoOf(typed, i)}</span></button>`)}
          <button type="button" class=${'ex' + (chosen && chosen.pick ? ' on' : '')} onClick=${pickForMe}><span>No wallet? Let us pick one</span><span class="who">the top ${shortLabel(type)} trader</span></button></div></div>`}
      ${err && html`<div class="banner err">${err}</div>`}</div>
    ${!SAMPLE && html`<div style="display:flex;flex-direction:column;gap:10px"><h3>Your breakdowns</h3>
      ${list == null ? html`<p class="muted">Loading…</p>` : list.length === 0 ? html`<p class="muted">None yet. Your first one appears here and stays here.</p>`
        : html`<div class="list">${list.map(s => html`<a href=${`#/i/${s.id}`}><div><div class="t">${shortWallets(s.title) || 'Untitled breakdown'}</div><div class="s">${s.sample ? 'Sample, from recorded data · ' : ''}Started ${new Date(s.created * 1000).toISOString().slice(0, 16).replace('T', ' ')} UTC</div></div>${rowLabel(s)}</a>`)}</div>`}</div>`}
    <p class="muted small">Later: re-running a breakdown when the wallet trades again, with Telegram alerts, comes after the first version.</p>
  </main>`;
}

const PAGE_TITLE = document.title;
// a market's question, short enough for a tab ("Will Bitcoin reach $100,000 by December 31, 2026?" → "Bitcoin reach $100,000 by Dec 31")
const shortTitle = t => { const s = String(t || 'Market').replace(/^Will (the price of )?/i, '').replace(/\?$/, '').replace(/, \d{4}$/, '').replace(/December/, 'Dec').replace(/November/, 'Nov').replace(/September/, 'Sep').replace(/October/, 'Oct'); return s.length > 36 ? s.slice(0, 35) + '…' : s; };

function Investigation({ api, id }) {
  const st = useRef(null); if (!st.current) st.current = { inv: emptyInv(id), ui: emptyUi(), wins: new Map(), scope: new Set() };
  const { inv, ui, wins } = st.current;
  const [, tick] = useState(0);
  const raf = useRef(0), follow = useRef(null);
  const redraw = () => { if (!raf.current) raf.current = requestAnimationFrame(() => { raf.current = 0; tick(x => x + 1); }); };
  // The tab's title says where it is: "(2/4) …" while a Started plan runs, "(✓) …" when it finished while you were in
  // another tab, until you look. Set on each event, not on redraw: a hidden tab doesn't draw.
  const titled = useRef({ wasRunning: false, unseen: false });
  const setTitle = () => {
    const tt = titled.current, name = `${shortWallets(inv.title) || 'Breakdown'} · Breakdowns`;
    if (tt.wasRunning && !inv.running && inv.done && document.hidden) tt.unseen = true;
    tt.wasRunning = inv.running;
    const pp = planProgress(inv);
    document.title = inv.running ? `(${pp ? `${pp.step}/${pp.total}` : '…'}) ${name}` : tt.unseen ? `(✓) ${name}` : name;
    if (!document.hidden && !inv.running && !api.fixtures) markOpened(id); // you're looking at it finished: not "ready" any more
  };
  useEffect(() => {
    const onVis = () => { if (!document.hidden) titled.current.unseen = false; setTitle(); };
    document.addEventListener('visibilitychange', onVis);
    return () => { document.removeEventListener('visibilitychange', onVis); document.title = PAGE_TITLE; };
  }, [id]);
  const onEvent = e => { apply(inv, e, ui); setTitle(); if (e.type === 'view.focus' && e.window_id) loadWin(e.window_id); redraw(); };
  const startFollow = () => {
    if (follow.current) return;
    const ac = new AbortController(); follow.current = ac;
    api.follow(id, inv.lastSeq, onEvent, ac.signal).catch(err => { inv.loadError = err.message; redraw(); }).finally(() => { if (follow.current === ac) follow.current = null; });
  };
  useEffect(() => {
    (async () => {
      try {
        const s = await api.session(id);
        for (const e of s.events) apply(inv, e, ui);
        if (!inv.title) inv.title = s.title || '';
        setTitle();
        inv.loaded = true; // its history is in: the plan, findings and title are real from here, not an empty breakdown
        if (inv.done && api.windows) inv.winsLoading = true;
        redraw();
        if (s.running || api.fixtures || !inv.done) startFollow();
        if (api.fixtures && !s.events.length && !s.running) await api.ask(id, 'start'); // opened straight from the list
        if (inv.done && api.windows) { const w = await api.windows(id).catch(() => null); inv.winsLoading = false; if (w) for (const x of w.windows) apply(inv, { type: 'window.summary', ...x }, null); }
        if (ui.win) loadWin(ui.win);
        redraw();
      } catch (e) { inv.loadError = e.message; redraw(); }
    })();
    return () => { if (follow.current) follow.current.abort(); };
  }, [id]);

  const loadWin = slug => {
    if (wins.has(slug)) return;
    wins.set(slug, 'loading'); redraw();
    api.window(id, slug).then(r => { const sm = inv.summaries.find(s => s.window_id === slug); wins.set(slug, isMarket(r) ? prepMarket(r, sm) : prep(r, sm)); redraw(); },
      e => { wins.set(slug, { error: e.message }); redraw(); });
  };
  const winOf = slug => wins.get(slug);
  const stepsOf = w => (w && w.kind === 'market' ? (inv.walkthroughs[w.id] ? marketAgentSteps(w, inv.walkthroughs[w.id]) : (w._auto || (w._auto = marketAutoSteps(w))))
    : w && w.id && inv.walkthroughs[w.id] ? agentSteps(w, inv.walkthroughs[w.id]) : w && w.id ? (w._auto || (w._auto = autoSteps(w))) : []);
  if (!ui.win && inv.summaries.length) ui.win = inv.summaries[0].window_id;
  const cur = ui.win ? winOf(ui.win) : null;
  if (ui.win && !cur) loadWin(ui.win);
  const steps = cur && cur.id ? stepsOf(cur) : [];

  // A plan waiting for Start while another breakdown of yours works: Start becomes "Queue it", with where that one is
  // (the list's row for it, read every 15 s while this plan waits).
  const lastPlan = inv.plans[inv.planOrder[inv.planOrder.length - 1]];
  const mayQueue = !api.fixtures && !inv.running && !!lastPlan && lastPlan.status === 'proposed';
  useEffect(() => {
    if (!mayQueue) { if (st.current.other) { st.current.other = null; redraw(); } return undefined; }
    const look = () => api.sessions().then(rows => { st.current.other = rows.find(r => r.running && r.id !== id) || null; redraw(); }, () => {});
    look();
    const t = setInterval(look, 15000);
    return () => clearInterval(t);
  }, [mayQueue, id]);

  const runCall = async p => { try { const r = await p; if (r && r.started === false) { inv.starting = false; redraw(); } startFollow(); } catch (e) { inv.starting = false; inv.feed = inv.feed.filter(x => !x.pending); inv.feed.push({ type: 'error', text: e.message }); redraw(); } };
  // The click shows at once (owner, 11 Nov: after Start the column sat still for up to a minute): what was sent goes
  // in the column, the agent shows as starting, and the server's own ask.started replaces both.
  const sending = (text, extra) => { if (text != null) inv.feed.push({ type: 'ask', text, pending: true, ...extra }); inv.starting = true; ui.tab = 'findings'; };
  // A new run (an accepted next step, a plan's Start): the workspace moves to its plan, not the last run's chart.
  const toPlan = () => { ui.stage = 'plan'; ui.followAgent = true; ui.hl = null; ui.runView = null; };
  const act = {
    scopeOpts: st.current.scope,
    other: st.current.other || null,
    toggleScope: (oid, on) => { on ? st.current.scope.add(oid) : st.current.scope.delete(oid); redraw(); },
    approve: pid => {
      // The sample's recording ends at its first plan: a follow-up's Start asks the visitor to sign in and run it
      // (owner, 11 Nov: "There are no more recorded windows" was a dead end), nothing is played
      if (SAMPLE && pid !== inv.planOrder[0] && inv.plans[pid]) { inv.plans[pid].status = 'signin'; toPlan(); redraw(); return; }
      sending(null); toPlan(); redraw(); runCall(api.plan(id, pid, 'approve', null, [...st.current.scope])); },
    // "Pick one for me" chose a wallet: study another instead, as a change to the plan (nothing runs until Start)
    swapWallet: (pid, o) => {
      const p = pickOf(id);
      if (p) savePick(id, { ...o, others: [{ ...p, others: undefined }, ...(p.others || []).filter(x => x.wallet !== o.wallet)] });
      sending(null); redraw();
      runCall(api.plan(id, pid, 'edit', `Study ${traderName(o)} (wallet ${o.wallet}) instead, picked for the person asking as ${o.why}. Same question, same market and time range.`));
    },
    editPlan: pid => { ui.composeFocus = true; ui.composeText = 'Change the plan: '; ui.editing = pid; redraw(); },
    composed: () => { ui.composeFocus = false; ui.composeText = null; },
    proposal: (it, yes) => {
      it.state = yes ? 'accepted' : 'declined';
      if (yes) { sending(yesText(it.text), { proposal: true }); inv.runPlan = null; toPlan(); }
      redraw(); runCall(api.proposal(id, it.proposal_id, yes ? 'accept' : 'decline'));
    },
    ask: q => {
      if (ui.editing && /^Change the plan:/.test(q)) { const pid = ui.editing; ui.editing = null; sending(null); redraw(); return runCall(api.plan(id, pid, 'edit', q.replace(/^Change the plan:\s*/, ''))); }
      const c = ui.ctx; ui.ctx = null; ui.pin = null;
      let context = null;
      if (c) context = api.fixtures ? { ...c.context, answer: localAnswer(c, q) } : c.context;
      sending(q, { ctx: c ? c.label : null });
      redraw(); runCall(api.ask(id, q, context));
    },
    askBurst: (w, b) => { ui.pop = null; ui.ctx = { kind: 'burst', label: `${shares(b.shares)} ${b.side} at ${mmss(b.t0)}, ${clock(w.start).slice(0, 5)} window`, w, b, context: { trade_ids: b.fills.slice(0, 50).map(x => x.trade_id) } };
      ui.extraAnn = [{ window_id: w.id, kind: 'point', t0: b.t0, label: 'this fill' }]; act.ask('Why here?'); },
    // a burst of fills in a market's replay (fills within an hour): its date, not a time in a window
    askMarketBurst: (w, b) => { ui.pop = null; ui.ctx = { kind: 'burst', label: `${shares(b.shares)} ${b.side} on ${dateTime(b.t0)}`, w, b, context: { trade_ids: b.fills.slice(0, 50).map(x => x.trade_id) } }; act.ask('Why here?'); },
    askFix: f => runCall(api.ask(id, 'Fix the number that didn\'t match the data in this finding.', { finding_id: f.finding_id })),
    pinMoment: (w, t) => { ui.pin = { window_id: w.id, t }; ui.pop = null; ui.ctx = { kind: 'moment', label: `${mmss(t)} in the ${clock(w.start).slice(0, 5)} window`, w, t, context: { window_id: w.id, t: w.start + t } }; ui.composeFocus = true; redraw(); },
    clearCtx: () => { ui.ctx = null; ui.pin = null; redraw(); },
    pop: bid => { ui.pop = bid; redraw(); },
    stage: s => { ui.stage = s; ui.followAgent = false; redraw(); },
    tab: t => { ui.tab = t; redraw(); },
    openWin: (slug, step) => { ui.win = slug; ui.stage = 'window'; ui.full = false; ui.pop = null; ui.ph = null; ui.step = step ?? 0; ui.followAgent = false; loadWin(slug); redraw(); },
    openAt: (slug, t) => { const w = winOf(slug); const s = stepsOf(w); let i = s.findIndex(x => x.t >= t); if (i < 0) i = s.length - 1; ui.stage = 'window'; ui.step = i; ui.ph = t; redraw(); },
    setStep: i => { ui.step = i; ui.ph = null; ui.full = false; ui.pop = null; redraw(); },
    setFull: v => { ui.full = v; redraw(); },
    setRaw: v => { ui.raw = v; redraw(); },
    highlight: f => { const ev = f.evidence || {}, sup = ev.supporting_window_ids || ev.supporting || [], ag = ev.against_window_ids || ev.against || []; ui.hl = { label: `${f.stat ? f.stat.text : ''} · ${f.title}`, match: new Set(sup), base: new Set([...sup, ...ag]) }; ui.stage = 'windows'; redraw(); },
    clearHl: () => { ui.hl = null; redraw(); },
    filter: k => { ui.wf = k; redraw(); },
    // the question switcher: an earlier question (its windows, else its plan), or back to the new one (the agent moves
    // the view again from there)
    viewRun: (i, n) => {
      const last = i === n - 1, r = runs(groups(inv.feed))[i];
      ui.runView = last ? null : i; ui.followAgent = last; ui.hl = null; ui.wf = null; ui.pop = null;
      ui.stage = !last && r && (runSummaries(inv, r).length || borrowedWindows(inv, r)) ? 'windows' : last && inv.running ? 'plan' : last && inv.summaries.length ? 'windows' : 'plan';
      redraw();
    },
  };

  // The wallet's Signals record (the trader page's: every Polymarket position, not just these windows), read once
  // from the engine's /api/worth/<wallet> as the trader page does. Not in the sample: no service there.
  const wallet = (inv.subject && inv.subject.wallet) || ((inv.plans[inv.planOrder[0]] || {}).scope || {}).wallet || null;
  useEffect(() => {
    if (!wallet || api.fixtures || !/^0x[0-9a-f]{40}$/i.test(wallet)) return;
    fetch(`/api/worth/${wallet.toLowerCase()}`).then(r => (r.ok ? r.json() : null)).then(r => { if (r && r.record) { st.current.record = r; redraw(); } }).catch(() => {});
  }, [wallet]);
  const rec = st.current.record;

  // 11 Nov (owner): opening a saved breakdown showed "No plan yet / Ask a question to start" and the agent "Ready"
  // until its history arrived, as if it were empty. Until then, say it's opening.
  if (!inv.loaded && !inv.loadError) return html`<div class="inv"><section class="main" aria-label="Workspace">
      <div class="head"><div class="muted small"><a href="#/">Breakdowns</a> /</div><h1>Opening this breakdown…</h1></div>
      <div class="plan"><div style="display:flex;gap:12px"><span class="dot live"></span><div><h3>Loading its plan, windows and findings</h3><p class="muted small">Nothing is re-run: this is the saved breakdown.</p></div></div></div>
    </section></div>`;
  // More than one question (owner, 11 Nov): the workspace shows one at a time, the new one unless an earlier one is
  // picked in the switcher; its windows, total and plan only, never every question's added together.
  const rs = runs(groups(inv.feed)), many = rs.length > 1;
  const idx = many && ui.runView != null && ui.runView < rs.length - 1 ? ui.runView : rs.length - 1, past = many && idx < rs.length - 1;
  const working = !past && (inv.running || inv.starting);
  const borrowed = many && !working ? borrowedWindows(inv, rs[idx]) : null; // a finished question with none of its own
  const vsum = borrowed ? borrowed.sums : many ? runSummaries(inv, rs[idx]) : inv.summaries;
  const vinv = many ? { ...inv, summaries: vsum } : inv;
  const vplan = past ? planOfRun(inv, rs[idx], idx) : currentPlan(inv);
  const totalProfit = vsum.reduce((s, x) => s + (x.profit || 0), 0);
  // what this breakdown studies (the plan's market type): BTC 15-minute windows, or one tile per market
  const mk = marketTypeOf(inv, vplan), byMarket = mk.unit === 'market' || (vsum.length > 0 && vsum.every(isMarket));
  const mt = byMarket ? marketTally(vsum) : null;
  const cp = currentPlan(inv), runWaits = cp && (cp.status === 'proposed' || cp.status === 'queued') ? cp.status : null;
  const tabs = [['plan', 'Plan and data'], ['windows', `${byMarket ? 'Markets' : 'Windows'}${vsum.length ? ' · ' + vsum.length : ''}`]];
  // the Window (or Market) and Fills tabs only for one of the question shown
  if (cur && cur.id && (!many || vsum.some(s => s.window_id === cur.id))) tabs.push(['window', cur.kind === 'market' ? `Market: ${shortTitle(cur.title)}` : `Window: ${windowLabel(cur.start, cur.start + cur.end).replace(' UTC', '')}`], ['trades', `Fills · ${cur.trades.length}`]);
  return html`<div class="inv">
    <section class="main" aria-label="Workspace">
      <div class="head">
        <div class="muted small"><a href="#/">Breakdowns</a> /</div>
        <h1>${shortWallets(inv.title) || 'Breakdown'}</h1>
        ${many && html`<div class="qruns" role="group" aria-label="Your questions"><span class="lbl">Your questions</span>
          ${rs.map((r, i) => { const last = i === rs.length - 1;
            const stt = !last ? 'done' : inv.running || inv.starting ? 'working' : runWaits === 'queued' ? 'queued' : runWaits ? 'waiting for Start' : cp && cp.status === 'signin' ? 'sign in to run' : 'done';
            return html`<button class="qrun" key=${i} aria-pressed=${i === idx ? 'true' : 'false'} title=${runTitle(inv, r, i)} onClick=${() => act.viewRun(i, rs.length)}>
              <span class="qt">${shortWallets(runTitle(inv, r, i))}</span><span class=${'st' + (stt === 'working' ? ' live' : '')}>${stt}</span></button>`; })}</div>`}
        ${past && html`<div class="banner"><span>You're looking at an earlier question. It's finished and won't change.</span><button class="link" onClick=${() => act.viewRun(rs.length - 1, rs.length)}>Back to the new question →</button></div>`}
        <div class="meta">${inv.subject && html`<span class="chip">${traderName(inv.subject)}</span>`}${isBot(rec) ? html`<span class="who-tag bot" title="100 or more orders a day, from its Signals record">${BOT_ICON}Bot</span>`
          : isHuman(rec) ? html`<span class="who-tag human" title="Fewer than 100 orders a day, from its Signals record">${HUMAN_ICON}Human</span>`
          : rec ? html`<span class="who-tag unknown" title="Not read since this label was added: Human or Bot once their trades are read again">${UNKNOWN_ICON}Unknown</span>` : null}<span>${mk.label}</span>
          ${vsum.length > 0 && !byMarket && html`<span>· ${plural(vsum.length, 'window')}</span><span>· <b class=${totalProfit >= 0 ? 'gain' : 'loss'}>${signedMoney(totalProfit)}</b> from its fills${!past && inv.running ? ' so far' : ''}</span>`}
          ${vsum.length > 0 && byMarket && html`<span>· ${plural(vsum.length, 'market')}</span>${mt.decided > 0 && html`<span>· <b class=${mt.profitMade + mt.profitLost >= 0 ? 'gain' : 'loss'}>${signedMoney(mt.profitMade + mt.profitLost)}</b> on ${plural(mt.decided, 'market')} ended or sold out</span>`}${mt.open > 0 && html`<span>· ${signedMoney(mt.profitOpen)} open, at today's prices</span>`}`}
          ${inv.partial && html`<span class="cov">· Partial history: it stopped at the read limit</span>`}</div>
        ${rec && html`<${RecordLine} r=${rec} wallet=${wallet} />`}
      </div>
      <${PhoneNote} />
      ${SAMPLE && html`<div class="banner sample"><span>A sample breakdown, recorded from a real run: real windows, with the agent's steps played back. <a class="link" href="./?signin#/">Sign in to ask your own.</a></span></div>`}
      ${FIXTURES && !SAMPLE && html`<div class="banner sample"><span>Fixtures mode: real windows recorded from the service, with a sample of the agent's events around them. Findings marked as samples show what's still to come.</span></div>`}
      ${inv.loadError && html`<div class="banner err">${inv.loadError}</div>`}
      <div class="stabs" role="tablist">${tabs.map(([k, l]) => html`<button role="tab" class=${ui.stage === k ? 'on' : ''} onClick=${() => act.stage(k)}>${l}</button>`)}</div>
      ${ui.stage === 'plan' && !past && html`<${PickedCard} pick=${pickOf(id)} plan=${vplan} act=${act} />`}
      ${ui.stage === 'plan' && html`<${PlanStage} inv=${vinv} act=${act} plan=${vplan} past=${past} />`}
      ${ui.stage === 'windows' && (byMarket ? html`<${MarketsStage} inv=${vinv} ui=${ui} act=${act} plan=${vplan} live=${!past && inv.running} borrowed=${borrowed} />`
        : html`<${WindowsStage} inv=${vinv} ui=${ui} act=${act} plan=${vplan} live=${!past && inv.running} borrowed=${borrowed} />`)}
      ${ui.stage === 'window' && (cur && cur.kind === 'market' ? html`<${MarketReplay} inv=${vinv} ui=${ui} act=${act} w=${cur} steps=${steps} />` : html`<${ReplayStage} inv=${vinv} ui=${ui} act=${act} w=${cur} steps=${steps} />`)}
      ${ui.stage === 'trades' && (cur && cur.kind === 'market' ? html`<${MarketTrades} w=${cur} act=${act} />` : html`<${TradesStage} w=${cur} act=${act} />`)}
    </section>
    <${AgentColumn} inv=${inv} ui=${ui} act=${act} fixtures=${!!api.fixtures} />
  </div>`;
}

// The track record beside the breakdown, worded as the Leaderboard words it: a win rate is positions closed in
// profit (from 10 closed), always with the average price paid beside it (a price is the market's chance, so paying
// 97¢ wins about 97% of the time by buying alone), and it covers every market, not only these windows.
const WIN_MIN = 10;
// Tagged a bot by its record (100+ orders a day) or score: the header's "Bot", else "Human", as the Leaderboard shows it
const isBot = r => !!r && (r.bot === 1 || r.bot === true || (Array.isArray(r.tags) && r.tags.includes('bot')));
const isHuman = r => !!r && !isBot(r) && (r.bot === 0 || r.bot === false || (r.bot == null && Array.isArray(r.tags)));
const HUMAN_ICON = html`<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><circle cx="12" cy="8" r="4"/><path d="M4 21v-1a6 6 0 0 1 6-6h4a6 6 0 0 1 6 6v1"/></svg>`;
const UNKNOWN_ICON = html`<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><circle cx="12" cy="12" r="9"/><path d="M9.5 9.5a2.5 2.5 0 1 1 3.5 2.3c-.6.3-1 .8-1 1.5v.7"/><path d="M12 17h.01"/></svg>`;
const BOT_ICON = html`<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><rect x="4" y="8" width="16" height="12" rx="2"/><path d="M12 8V4"/><path d="M9 13v2"/><path d="M15 13v2"/><path d="M2 14h2"/><path d="M20 14h2"/></svg>`;
function RecordLine({ r, wallet }) {
  const w = r.win && (r.win['90d'] || r.win['30d'] || r.win['7d']);
  const win = w && w.closed >= WIN_MIN ? `${Math.round(100 * w.won / w.closed)}% of positions closed in profit (${count(w.won)} of ${count(w.closed)}, last ${w.days} days)` : null;
  const paid = r.paid_30d != null ? `pays ${cents(100 * r.paid_30d)} on average over 30 days` : null;
  return html`<p class="recline muted small"><b>Its Signals record, every Polymarket market:</b> ${[win, paid].filter(Boolean).join('; ') || 'no win rate yet'}. <a class="link" href=${`/#/worth/${wallet.toLowerCase()}`} target="_blank" rel="noopener">See its record</a></p>`;
}

// Fixtures mode only: a pointed question answered from the window itself, observed facts only (readings of why are
// the agent's, and need the service).
function localAnswer(c, q) {
  const w = c.w, note = "Worked out in the page from this window's data (fixtures mode). With the service, the agent answers, with its reading of why.";
  if (c.kind === 'burst') {
    const b = c.b, t = b.t0, before = w.move(Math.max(w.from, t - 60)), now = w.move(t);
    const lines = [`Observed: ${burstText(w, b)}`];
    if (t >= 0 && before != null && now != null) lines.push(`Observed: In the 60 s before, BTC moved ${signedBtc(now - before)} (${w.moveSource(t)}).`);
    const u0 = w.up(t), u1 = w.up(Math.min(w.to, t + 60));
    if (u0 && u1) lines.push(`Observed: the Up price on Polymarket was ${cents(u0[0])}/${cents(u0[1])} then, and ${cents(u1[0])}/${cents(u1[1])} 60 s later.`);
    else lines.push("Observed: There's no recorded order book at that second, so how it filled against the asking price can't be checked here.");
    return { text: lines.join('\n'), number_check: { passed: true, flagged: {} }, computed_note: note };
  }
  const t = c.t, mv = w.move(t), up = w.up(t);
  const near = w.trades.filter(x => Math.abs(x.t - t) <= 30);
  return { text: [`Observed: at ${mmss(t)} (${clock(w.start + t)} UTC) it held ${posText(w, t)}.`,
    mv != null && t >= 0 ? `Observed: BTC was ${signedBtc(mv)} from the start (${w.moveSource(t)}).` : null,
    up ? `Observed: the Up price on Polymarket was ${cents(up[0])}/${cents(up[1])}.` : 'Observed: Up and Down weren\'t recorded at that second.',
    `Observed: ${near.length ? plural(near.length, 'fill') + ' within 30 s of this moment' : 'no fills within 30 s of this moment'}.`].filter(Boolean).join('\n'),
    number_check: { passed: true, flagged: {} }, computed_note: note };
}

render(html`<${App} />`, document.getElementById('root'));
