// The research page (usesignals.app/breakdowns; /research/ on the service): Breakdowns, and one breakdown's workspace (an "investigation" in the code and contract). Routes: #/ (yours, and a new
// one), #/i/<id> (an investigation). ?fixtures plays recorded data with no service; ?sample is the same recorded run
// for visitors (no sign-in: the signed-out page's "Watch a sample breakdown"); ?signin opens Sign in at once; ?q=
// prefills a question (the main site's ask bar sends it).
import { html, render, useState, useEffect, useRef, useMemo } from '../vendor/htm-preact-3.1.1.module.js';
import { live, startAuth, openSignIn, mountUser } from './api.js';
import { fixtureApi } from './fixtures.js';
import { emptyInv, emptyUi, apply } from './store.js';
import { prep, autoSteps, agentSteps, burstText, posText } from './windowdata.js';
import { PlanStage, WindowsStage, ReplayStage, TradesStage } from './views.js';
import { AgentColumn } from './agent.js';
import { Hatch } from './chart.js';
import { traderName, windowLabel, signedMoney, money, mmss, clock, signedBtc, cents, shares, plural, shortWallets, count } from './format.js';

const LOGO = html`<svg width="16" height="16" viewBox="0 0 20 20" fill="currentColor" aria-hidden="true"><rect x="3" y="11" width="3" height="6" rx="1" /><rect x="8.5" y="7" width="3" height="10" rx="1" /><rect x="14" y="3" width="3" height="14" rx="1" /></svg>`;
const params = new URLSearchParams(location.search);
const SAMPLE = params.has('sample'), FIXTURES = SAMPLE || params.has('fixtures');
const route = () => { const m = /^#\/i\/([\w-]+)/.exec(location.hash); return m ? { inv: m[1] } : { home: true }; };

function Top({ fixtures }) {
  const acct = useRef();
  useEffect(() => mountUser(acct.current));
  return html`<header class="top"><div class="in">
    <a class="brand" href="/"><span class="logo">${LOGO}</span>Signals</a>
    <nav class="tabs" aria-label="Main"><a class="on new" href="#/">Breakdowns</a><a href="/#/">Feed</a><a href="/#/watchlist">Watchlist</a><a href="/#/traders">Traders</a></nav>
    <div class="acct">${SAMPLE ? html`<span class="chip">Sample: a recorded breakdown</span><a class="btn sm primary" href="./?signin#/">Sign in to ask your own</a>`
      : fixtures ? html`<span class="chip">Fixtures: recorded data, no service</span>` : html`<div ref=${acct}></div>`}</div></div></header>`;
}

function App() {
  const [api, setApi] = useState(null), [r, setR] = useState(route()), [gate, setGate] = useState(null), [err, setErr] = useState(null);
  useEffect(() => { const f = () => setR(route()); addEventListener('hashchange', f); return () => removeEventListener('hashchange', f); }, []);
  useEffect(() => { (async () => {
    try {
      const a = FIXTURES ? await fixtureApi() : live;
      const cfg = await a.config();
      if (cfg.event_version > 2) setErr('This page is older than the research service. Reload to get the new one.');
      const au = FIXTURES ? { signedIn: true } : await startAuth(cfg.clerk_key);
      if (!au.signedIn) { setGate('signin'); if (params.has('signin')) openSignIn(); window.Clerk && window.Clerk.addListener(() => { if (window.Clerk.isSignedIn) setGate(null); }); }
      setApi(a);
    } catch (e) { setErr(e.message || 'The research service isn\'t reachable.'); }
  })(); }, []);
  return html`<${Hatch} /><${Top} fixtures=${FIXTURES} />
    ${err && html`<div class="home"><div class="banner err"><div><p>${err}</p><p class="small muted" style="margin-top:4px">To see the page with recorded data, open <a class="link" href="?fixtures#/">fixtures mode</a>.</p></div></div></div>`}
    ${!err && !api && html`<div class="home"><p class="muted">Loading…</p></div>`}
    ${api && gate === 'signin' && html`<${Teaser} />`}
    ${api && !gate && (r.inv ? html`<${Investigation} key=${r.inv} api=${api} id=${r.inv} />` : html`<${Home} api=${api} />`)}`;
}

// Example questions under the ask box (owner, 10 Nov: four, small, one row, and each must say WHICH wallet). Each card
// shows a different kind of answer (owner, 10 Nov): an explanation, a chart, a replay, a comparison. Two sample traders
// share them (owner: mix and match two traders across the four), both active in every BTC 15-minute window. With the
// wallet field empty, or holding a sample trader's wallet, each card names its own trader and a click fills both fields;
// with any other wallet typed, every card names that one (shortened) and fills the question only. A click never starts
// anything: Break it down still shows the plan and its cost first. BTC 15-minute only.
const SAMPLE_TRADERS = [
  { wallet: '0xbdaacd345fec209cd09d933e62f92e8b530afd60', name: 'the.prod.dt' },
  { wallet: '0x329df14a9e177b5bade2228b9062265697a5b047', name: 'HuskyTrade' },
];
const EXAMPLES = [  // [sample trader, card, question]
  [0, w => `How does ${w} make money?`, w => `How does ${w} make money on BTC 15-minute markets?`],
  [1, w => `Chart ${w}'s buys against the BTC price`, w => `In BTC 15-minute markets, chart ${w}'s buys against the BTC price over its latest windows.`],
  [0, w => `Replay ${w}'s latest window`, w => `Replay ${w}'s latest finished BTC 15-minute window: when did it buy Up and Down, and where was BTC?`],
  [1, w => `Compare ${w}'s winning and losing windows`, w => `In BTC 15-minute markets, compare ${w}'s winning and losing windows: what did it do differently?`],
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

function Home({ api }) {
  const [list, setList] = useState(null), [wallet, setWallet] = useState(FIXTURES ? '0xb945…db68' : ''), [q, setQ] = useState(params.get('q') || (FIXTURES ? "Analyze this wallet's BTC 15-minute trades. Plot its entries against Binance and Polymarket prices, show how its positions change over time, and help me understand its trading strategy." : ''));
  const [busy, setBusy] = useState(false), [err, setErr] = useState(null);
  // after a card: focus Break it down
  const go = useRef(), focusNext = useRef(null);
  useEffect(() => { const el = focusNext.current; focusNext.current = null; if (el && el.current) el.current.focus(); });
  // whom card i names: its own sample trader by name (also once a card filled a sample address in), else the wallet typed
  const isSample = w => !w.trim() || SAMPLE_TRADERS.some(t => t.wallet === w.trim().toLowerCase());
  const whoOf = (w, i) => (isSample(w) ? SAMPLE_TRADERS[EXAMPLES[i][0]].name : shortWallets(w.trim()));
  const pick = i => { if (isSample(wallet)) setWallet(SAMPLE_TRADERS[EXAMPLES[i][0]].wallet); setQ(EXAMPLES[i][2](whoOf(wallet, i))); focusNext.current = go; };
  // a card's question follows the wallet field, so it never names one trader while the field holds another
  const onWallet = w => { setWallet(w); const i = EXAMPLES.findIndex(([, , question], j) => question(whoOf(wallet, j)) === q); if (i >= 0) setQ(EXAMPLES[i][2](whoOf(w, i))); };
  useEffect(() => { if (!SAMPLE) api.sessions().then(setList, e => setErr(e.message)); }, []);
  const start = async () => {
    if (!q.trim()) return; setBusy(true); setErr(null);
    try {
      const question = wallet.trim() && !q.includes(wallet.trim()) ? `${q.trim()}\n\nWallet: ${wallet.trim()}` : q.trim();
      const id = await api.create(q.trim().slice(0, 120));
      await api.ask(id, question, null, 'pasted wallet');
      location.hash = `#/i/${id}`;
    } catch (e) { setErr(e.message); setBusy(false); }
  };
  return html`<main class="home">
    <div style="display:flex;flex-direction:column;gap:10px"><h1>What do you want to find out?</h1>
      <p class="muted">${SAMPLE ? 'This is a sample: a breakdown recorded from a real run, with its question filled in. Press Break it down to watch it plan, read and chart the trades. Sign in to ask your own.' : 'Polymarket only. Research, no trading.'}</p>
      <div class="compose-big">
        <input id="wallet" aria-label="Wallet" placeholder="Wallet address or Polymarket name" value=${wallet} readOnly=${SAMPLE} onInput=${e => onWallet(e.target.value)} />
        <textarea id="q" rows="3" aria-label="Your question" placeholder="How does this wallet trade BTC 15-minute markets?" value=${q} readOnly=${SAMPLE} onInput=${e => setQ(e.target.value)}></textarea>
        <div class="foot"><span class="muted small">You'll see the plan and what it costs before it runs.</span><button ref=${go} class="btn primary" disabled=${busy || !q.trim()} onClick=${start}>${busy ? 'Starting…' : 'Break it down'}</button></div></div>
      ${!SAMPLE && html`<div class="examples" aria-label="Example questions">
        <p class="muted small">Try asking</p>
        <div class="ex-grid">${EXAMPLES.map(([, label, question], i) => html`<button type="button" class=${'ex' + (q === question(whoOf(wallet, i)) ? ' on' : '')} onClick=${() => pick(i)}>${label(whoOf(wallet, i))}</button>`)}</div></div>`}
      ${err && html`<div class="banner err">${err}</div>`}</div>
    ${!SAMPLE && html`<div style="display:flex;flex-direction:column;gap:10px"><h3>Your breakdowns</h3>
      ${list == null ? html`<p class="muted">Loading…</p>` : list.length === 0 ? html`<p class="muted">None yet. Your first one appears here and stays here.</p>`
        : html`<div class="list">${list.map(s => html`<a href=${`#/i/${s.id}`}><div><div class="t">${shortWallets(s.title) || 'Untitled breakdown'}</div><div class="s">${s.sample ? 'Sample, from recorded data · ' : ''}Started ${new Date(s.created * 1000).toISOString().slice(0, 16).replace('T', ' ')} UTC</div></div><span class="r">Saved</span></a>`)}</div>`}</div>`}
    <p class="muted small">Later: re-running a breakdown when the wallet trades again, with Telegram alerts, comes after the first version.</p>
  </main>`;
}

function Investigation({ api, id }) {
  const st = useRef(null); if (!st.current) st.current = { inv: emptyInv(id), ui: emptyUi(), wins: new Map(), scope: new Set() };
  const { inv, ui, wins } = st.current;
  const [, tick] = useState(0);
  const raf = useRef(0), follow = useRef(null);
  const redraw = () => { if (!raf.current) raf.current = requestAnimationFrame(() => { raf.current = 0; tick(x => x + 1); }); };
  const onEvent = e => { apply(inv, e, ui); if (e.type === 'view.focus' && e.window_id) loadWin(e.window_id); redraw(); };
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
        if (s.running || api.fixtures || !inv.done) startFollow();
        if (api.fixtures && !s.events.length && !s.running) await api.ask(id, 'start'); // opened straight from the list
        if (inv.done && api.windows) { const w = await api.windows(id).catch(() => null); if (w) for (const x of w.windows) apply(inv, { type: 'window.summary', ...x }, null); }
        if (ui.win) loadWin(ui.win);
        redraw();
      } catch (e) { inv.loadError = e.message; redraw(); }
    })();
    return () => { if (follow.current) follow.current.abort(); };
  }, [id]);

  const loadWin = slug => {
    if (wins.has(slug)) return;
    wins.set(slug, 'loading'); redraw();
    api.window(id, slug).then(r => { wins.set(slug, prep(r, inv.summaries.find(s => s.window_id === slug))); redraw(); },
      e => { wins.set(slug, { error: e.message }); redraw(); });
  };
  const winOf = slug => wins.get(slug);
  const stepsOf = w => (w && w.id && inv.walkthroughs[w.id] ? agentSteps(w, inv.walkthroughs[w.id]) : w && w.id ? (w._auto || (w._auto = autoSteps(w))) : []);
  if (!ui.win && inv.summaries.length) ui.win = inv.summaries[0].window_id;
  const cur = ui.win ? winOf(ui.win) : null;
  if (ui.win && !cur) loadWin(ui.win);
  const steps = cur && cur.id ? stepsOf(cur) : [];

  const runCall = async p => { try { await p; startFollow(); } catch (e) { inv.feed.push({ type: 'error', text: e.message }); redraw(); } };
  const act = {
    scopeOpts: st.current.scope,
    toggleScope: (oid, on) => { on ? st.current.scope.add(oid) : st.current.scope.delete(oid); redraw(); },
    approve: pid => runCall(api.plan(id, pid, 'approve', null, [...st.current.scope])),
    editPlan: pid => { ui.composeFocus = true; ui.composeText = 'Change the plan: '; ui.editing = pid; redraw(); },
    composed: () => { ui.composeFocus = false; ui.composeText = null; },
    proposal: (it, yes) => { it.state = yes ? 'accepted' : 'declined'; redraw(); runCall(api.proposal(id, it.proposal_id, yes ? 'accept' : 'decline')); },
    ask: q => {
      if (ui.editing && /^Change the plan:/.test(q)) { const pid = ui.editing; ui.editing = null; return runCall(api.plan(id, pid, 'edit', q.replace(/^Change the plan:\s*/, ''))); }
      const c = ui.ctx; ui.ctx = null; ui.pin = null;
      let context = null;
      if (c) context = api.fixtures ? { ...c.context, answer: localAnswer(c, q) } : c.context;
      redraw(); runCall(api.ask(id, q, context));
    },
    askBurst: (w, b) => { ui.pop = null; ui.ctx = { kind: 'burst', label: `${shares(b.shares)} ${b.side} at ${mmss(b.t0)}, ${clock(w.start).slice(0, 5)} window`, w, b, context: { trade_ids: b.fills.slice(0, 50).map(x => x.trade_id) } };
      ui.extraAnn = [{ window_id: w.id, kind: 'point', t0: b.t0, label: 'this fill' }]; act.ask('Why here?'); },
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
  };

  // The wallet's Signals record (the trader page's: every Polymarket position, not just these windows), read once
  // from the engine's /api/worth/<wallet> as the trader page does. Not in the sample: no service there.
  const wallet = (inv.subject && inv.subject.wallet) || ((inv.plans[inv.planOrder[0]] || {}).scope || {}).wallet || null;
  useEffect(() => {
    if (!wallet || api.fixtures || !/^0x[0-9a-f]{40}$/i.test(wallet)) return;
    fetch(`/api/worth/${wallet.toLowerCase()}`).then(r => (r.ok ? r.json() : null)).then(r => { if (r && r.record) { st.current.record = r; redraw(); } }).catch(() => {});
  }, [wallet]);
  const rec = st.current.record;

  const totalProfit = inv.summaries.reduce((s, x) => s + (x.profit || 0), 0);
  const tabs = [['plan', 'Plan and data'], ['windows', `Windows${inv.summaries.length ? ' · ' + inv.summaries.length : ''}`]];
  if (cur && cur.id) tabs.push(['window', `Window: ${windowLabel(cur.start, cur.start + cur.end).replace(' UTC', '')}`], ['trades', `Fills · ${cur.trades.length}`]);
  return html`<div class="inv">
    <section class="main" aria-label="Workspace">
      <div class="head">
        <div class="muted small"><a href="#/">Breakdowns</a> /</div>
        <h1>${shortWallets(inv.title) || 'Breakdown'}</h1>
        <div class="meta">${inv.subject && html`<span class="chip">${traderName(inv.subject)}</span>`}<span>BTC Up or Down 15m</span>
          ${inv.summaries.length > 0 && html`<span>· ${plural(inv.summaries.length, 'window')}</span><span>· <b class=${totalProfit >= 0 ? 'gain' : 'loss'}>${signedMoney(totalProfit)}</b> from its fills</span>`}
          ${inv.partial && html`<span class="cov">· Partial history: it stopped at the read limit</span>`}</div>
        ${rec && html`<${RecordLine} r=${rec} wallet=${wallet} />`}
        <div class="acts"><button class="btn sm later" onClick=${() => { ui.laterOpen = !ui.laterOpen; redraw(); }}>Watch for new trades · later</button></div>
        ${ui.laterOpen && html`<div class="later-pop"><span class="tag plain" style="align-self:flex-start">Later, not in this version</span><b>Keep this breakdown up to date</b>
          <p>Re-run it when the wallet trades a new window, and tell you on Telegram when a pattern breaks or something new shows up. Those alerts will count in Signals' 20 a day.</p>
          <p class="muted small">For now the breakdown is saved: reopen it any time from Breakdowns.</p><button class="btn sm" onClick=${() => { ui.laterOpen = false; redraw(); }}>OK</button></div>`}
      </div>
      ${SAMPLE && html`<div class="banner sample"><span>A sample breakdown, recorded from a real run: real windows, with the agent's steps played back. <a class="link" href="./?signin#/">Sign in to ask your own.</a></span></div>`}
      ${FIXTURES && !SAMPLE && html`<div class="banner sample"><span>Fixtures mode: real windows recorded from the service, with a sample of the agent's events around them. Findings marked as samples show what's still to come.</span></div>`}
      ${inv.loadError && html`<div class="banner err">${inv.loadError}</div>`}
      <div class="stabs" role="tablist">${tabs.map(([k, l]) => html`<button role="tab" class=${ui.stage === k ? 'on' : ''} onClick=${() => act.stage(k)}>${l}</button>`)}
        <button class=${'later ' + (ui.stage === 'later' ? 'on' : '')} onClick=${() => act.stage('later')}>+ New view</button></div>
      ${ui.stage === 'plan' && html`<${PlanStage} inv=${inv} act=${act} />`}
      ${ui.stage === 'windows' && html`<${WindowsStage} inv=${inv} ui=${ui} act=${act} />`}
      ${ui.stage === 'window' && html`<${ReplayStage} inv=${inv} ui=${ui} act=${act} w=${cur} steps=${steps} />`}
      ${ui.stage === 'trades' && html`<${TradesStage} w=${cur} act=${act} />`}
      ${ui.stage === 'later' && html`<div class="ghostbox"><b>Your own views come here later.</b><br />Ask for any chart or table ("plot its average fill price by minute"), and it's kept in this breakdown and refreshes with new trades. Not in this version.</div>`}
    </section>
    <${AgentColumn} inv=${inv} ui=${ui} act=${act} fixtures=${!!api.fixtures} />
  </div>`;
}

// The track record beside the breakdown, worded as the Leaderboard words it: a win rate is positions closed in
// profit (from 10 closed), always with the average price paid beside it (a price is the market's chance, so paying
// 97¢ wins about 97% of the time by buying alone), and it covers every market, not only these windows.
const WIN_MIN = 10;
function RecordLine({ r, wallet }) {
  const w = r.win && (r.win['90d'] || r.win['30d'] || r.win['7d']);
  const win = w && w.closed >= WIN_MIN ? `${Math.round(100 * w.won / w.closed)}% of positions closed in profit (${count(w.won)} of ${count(w.closed)}, last ${w.days} days)` : null;
  const paid = r.paid_30d != null ? `pays ${cents(100 * r.paid_30d)} on average over 30 days` : null;
  return html`<p class="recline muted small"><b>Its Signals record, every Polymarket market:</b> ${[win, paid].filter(Boolean).join('; ') || 'no win rate yet'}. <a class="link" href=${`/#/worth/${wallet.toLowerCase()}`}>See its record</a></p>`;
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
