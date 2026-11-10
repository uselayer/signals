// The agent's column: what it's doing, its evidence (findings, answers), its proposals, and the question box. The
// conversation steers; what it finds lands as cards that open the windows and fills behind them.
import { html, useState, useRef, useEffect } from '../vendor/htm-preact-3.1.1.module.js';
import { flagged } from './views.js';
import { flagsFor } from './store.js';
import { money } from './format.js';

export function AgentColumn({ inv, ui, act, fixtures }) {
  const feedRef = useRef(), n = inv.feed.length;
  useEffect(() => { const el = feedRef.current; if (el && ui.tab === 'findings') el.scrollTop = el.scrollHeight; }, [n, ui.tab]);
  const working = inv.running;
  const last = inv.plans[inv.planOrder[inv.planOrder.length - 1]], waiting = !working && last && last.status === 'proposed';
  const nCards = inv.feed.filter(x => x.type === 'finding' || x.type === 'answer').length;
  return html`<aside class="agent" aria-label="The research agent">
    <div class="agent-head"><span class=${'dot ' + (working ? 'live' : inv.done && !waiting ? 'ok' : '')}></span>
      <div><div class="t">Signals agent</div><div class="s">${working ? 'Working' : inv.error ? 'Stopped on an error' : waiting ? 'Waiting for you to start the plan' : inv.done ? 'Done · saved' : waitingFor(inv)}</div></div></div>
    <div class="atabs" role="tablist"><button role="tab" class=${ui.tab === 'findings' ? 'on' : ''} onClick=${() => act.tab('findings')}>Findings${nCards ? ` · ${nCards}` : ''}</button>
      <button role="tab" class=${ui.tab === 'activity' ? 'on' : ''} onClick=${() => act.tab('activity')}>Activity and data</button></div>
    <div class="feed" ref=${feedRef}>${ui.tab === 'activity' ? html`<${Activity} inv=${inv} />` : html`
      ${inv.needsReload && html`<div class="banner err">This page is older than the research service. Reload to see everything.</div>`}
      ${inv.feed.length === 0 && html`<div class="note"><span class="dot"></span><p class="muted">The plan appears in the workspace first. Nothing runs until you press Start.</p></div>`}
      ${inv.feed.map((it, i) => html`<${Item} key=${i} it=${it} inv=${inv} act=${act} />`)}`}</div>
    <${Composer} inv=${inv} ui=${ui} act=${act} fixtures=${fixtures} />
  </aside>`;
}

const waitingFor = inv => { const p = inv.plans[inv.planOrder[inv.planOrder.length - 1]]; return p && p.status === 'proposed' ? 'Waiting for you to start the plan' : 'Ready'; };

function Item({ it, inv, act }) {
  if (it.type === 'note') return html`<div class="note"><span class="dot ok"></span><p>${it.text}</p></div>`;
  if (it.type === 'error') return html`<div class="banner err">${it.text}</div>`;
  if (it.type === 'working') return html`<div class="working"><span class="dot live"></span><div>${it.lines.map(l => html`<p class=${l.done ? 'done' : ''}>${l.done ? '✓ ' : ''}${l.text}</p>`)}</div></div>`;
  if (it.type === 'ask') return html`<div class="ask"><div class="k">You asked${it.ctx ? html` about <span class="ctx">${it.ctx}</span>` : ''}</div><p>${it.text}</p></div>`;
  if (it.type === 'finding') return html`<${Finding} f=${inv.findings[it.id]} inv=${inv} act=${act} />`;
  if (it.type === 'answer') return html`<${Answer} a=${it} act=${act} />`;
  if (it.type === 'proposal') return html`<div class=${'proposal ' + (it.state !== 'open' ? 'done' : '')}><div class="k">Next, I'd look at</div><p>${it.text}</p>
    ${it.state === 'open' ? html`<div style="display:flex;gap:6px"><button class="btn sm primary" onClick=${() => act.proposal(it, true)}>${it.accept_label || 'Yes'}</button><button class="btn sm ghost" onClick=${() => act.proposal(it, false)}>Not now</button></div>`
      : html`<p class="muted small">${it.state === 'accepted' ? 'You said yes.' : 'Skipped. Ask anything else below.'}</p>`}</div>`;
  if (it.type === 'plan') { const p = inv.plans[it.plan_id]; if (!p) return null;
    return html`<div class="proposal"><div class="k">${p.status === 'proposed' ? "This widens the investigation, so here's the plan first" : 'Plan'}</div><p><b>${p.title}</b></p>
      <ol style="margin:0;padding-left:1.2em;font-size:13.5px;display:flex;flex-direction:column;gap:3px">${p.steps.map(s => html`<li>${s.title}${s.source ? html` <span class="muted">(${s.source})</span>` : ''}</li>`)}</ol>
      ${p.estimate_usd != null && html`<p class="muted small">About ${money(p.estimate_usd)} of model time.</p>`}
      ${p.status === 'proposed' ? html`<div style="display:flex;gap:6px"><button class="btn sm primary" onClick=${() => act.approve(p.plan_id)}>Start</button><button class="btn sm ghost" onClick=${() => act.editPlan(p.plan_id)}>Change the plan</button></div>` : html`<p class="muted small">Started.</p>`}</div>`; }
  return null;
}

function Finding({ f, inv, act }) {
  if (!f) return null;
  const inferred = f.label === 'inferred', fl = flagsFor(f.number_check, 'body');
  const isFlagged = f.number_check && f.number_check.passed === false;
  const ev = f.evidence || {}, sup = new Set(ev.supporting || []), base = [...sup, ...(ev.against || [])];
  const order = inv.summaries.map(s => s.window_id).filter(id => base.includes(id));
  const lines = (f.body || '').split('\n');
  return html`<article class=${'card ' + (isFlagged ? 'flagged' : inferred ? 'inferred' : '')}>
    <div class="top2">${isFlagged ? html`<span class="tag flag">Number not verified</span>` : f.kind === 'data' ? html`<span class="tag plain">What's missing</span>` : html`<span class=${'tag ' + (inferred ? 'inferred' : 'observed')}>${inferred ? 'Inferred' : 'Observed'}</span>`}<span class="k">${f.kind === 'read' ? 'My reading' : f.finding_id}</span></div>
    <h4>${f.title}</h4>
    ${f.stat && html`<div class="statrow"><button class="stat" onClick=${() => act.highlight(f)} title="Show these windows">${f.stat.text}</button>${f.previous_stat && f.previous_stat.text !== f.stat.text && html`<span class="was">was ${f.previous_stat.text}</span>`}</div>`}
    ${order.length > 0 && html`<div class="waffle">${order.map(id => html`<button class=${sup.has(id) ? '' : 'no'} title=${id} aria-label=${id} onClick=${() => act.openWin(id)}></button>`)}</div>`}
    ${lines.length > 1 ? html`<ul>${lines.map(l => html`<li>${l}</li>`)}</ul>` : html`<p>${flagged(f.body, fl)}</p>`}
    ${isFlagged && html`<div class="flagnote">${fl.length} number${fl.length === 1 ? '' : 's'} didn't match the data the agent read: ${fl.map(x => x.value_text).join(', ')}.${fl.some(x => x.data_value) ? ` The data shows ${fl.filter(x => x.data_value).map(x => x.data_value).join(', ')}.` : ''} Not counted until it's fixed.</div>`}
    ${f.based_on && html`<p class="muted small">Based on ${f.based_on.join(', ')}.</p>`}
    ${f.would_change && html`<details open><summary>What would change this reading</summary><p>${f.would_change}</p></details>`}
    ${f.rule && html`<details><summary>How I counted</summary><p>${f.rule}</p></details>`}
    <div class="acts2">${f.example && f.example.window_id && html`<button class="link" onClick=${() => act.openWin(f.example.window_id, f.example.step)}>Step through an example</button>`}
      ${isFlagged && html`<button class="link" onClick=${() => act.askFix(f)}>Ask the agent to fix it</button>`}</div>
    ${f.sample_note && html`<span class="check">${f.sample_note}</span>`}
    ${!isFlagged && f.kind !== 'data' && html`<span class="check">✓ Numbers checked against the data</span>`}</article>`;
}

// An answer: v2 sends text; a paragraph that starts "Observed:" or "Inferred:" gets its tag
function Answer({ a, act }) {
  const fl = flagsFor(a.number_check, 'text');
  const paras = (a.text || '').split(/\n+/).filter(Boolean);
  const isFlagged = a.number_check && a.number_check.passed === false;
  let off = 0;
  return html`<article class=${'card ' + (isFlagged ? 'flagged' : '')}>
    ${a.label && html`<div class="top2"><span class="tag observed">${a.label}</span></div>`}
    ${paras.map(p => {
      const start = (a.text || '').indexOf(p, off); off = start + p.length;
      const local = fl.filter(x => x.start == null || (x.start >= start && x.end <= start + p.length)).map(x => (x.start == null ? x : { ...x, start: x.start - start, end: x.end - start }));
      const m = /^(Observed|Inferred):\s*/.exec(p);
      if (!m) return html`<p>${flagged(p, local)}</p>`;
      const rest = p.slice(m[0].length), body = rest.charAt(0).toUpperCase() + rest.slice(1), shift = m[0].length; // same length: flag offsets hold
      const lf = local.map(x => (x.start == null ? x : { ...x, start: x.start - shift, end: x.end - shift }));
      return html`<div class=${'line2 ' + (m[1] === 'Inferred' ? 'inf' : '')}><span class=${'tag ' + m[1].toLowerCase()}>${m[1]}</span><p>${flagged(body, lf)}</p></div>`;
    })}
    ${isFlagged && html`<div class="flagnote">${fl.length} number${fl.length === 1 ? '' : 's'} didn't match the data: ${fl.map(x => x.value_text).join(', ')}.</div>`}
    ${a.truncated && html`<p class="muted small">The answer was cut short. Ask again for the rest.</p>`}
    ${a.computed_note && html`<span class="check">${a.computed_note}</span>`}
    ${!isFlagged && !a.fixtures_note && !a.computed_note && html`<span class="check">✓ Numbers checked against the data</span>`}</article>`;
}

function Activity({ inv }) {
  const pc = inv.coverage && inv.coverage.per_source;
  return html`<div class="act">
    ${pc && html`<h5>Data used</h5><table><thead><tr><th>Source</th><th>Windows</th></tr></thead><tbody>
      <tr><td>Its trades (Polymarket trade history)</td><td>${inv.partial ? 'Partial: stopped at the read limit' : 'All read'}</td></tr>
      <tr><td>Binance BTCUSDT, each second</td><td>${pc.windows} of ${pc.windows}</td></tr>
      <tr><td>Chainlink BTC/USD (recorded from 10 Nov 05:27 UTC)</td><td>${pc.chainlink.complete} of ${pc.chainlink.total}; the rest start and result only</td></tr>
      <tr><td>Up/Down order book (Layer's recordings)</td><td>${pc.book.complete} of ${pc.book.total}</td></tr>
      <tr><td>Recording gaps</td><td>${(pc.outage.windows || []).length} window${(pc.outage.windows || []).length === 1 ? '' : 's'}</td></tr></tbody></table>`}
    <h5>Log</h5><div class="log">${inv.log.length ? inv.log.map(l => html`<div><span>${l.at}</span><p class=${l.flagged ? 'flagged' : ''}>${l.text}</p></div>`) : html`<p class="muted">Nothing yet.</p>`}</div>
    ${inv.usage && inv.usage.cost_usd != null && html`<p class="muted small">This investigation's model and tools so far: ${money(inv.usage.cost_usd)}.</p>`}</div>`;
}

function Composer({ inv, ui, act, fixtures }) {
  const [text, setText] = useState('');
  const ta = useRef();
  useEffect(() => { if (ui.composeFocus && ta.current) { if (ui.composeText != null) setText(ui.composeText); ta.current.focus(); act.composed(); } }, [ui.composeFocus]);
  const busy = inv.running;
  const ready = inv.done || inv.planOrder.length > 0;
  const send = q => { q = (q ?? text).trim(); if (!q || busy) return; setText(''); act.ask(q); };
  const sugg = ui.ctx ? ['Why here?', 'What happened here?'] : (fixtures ? ['Why does it buy below the asking price?', 'Read every BTC 15-minute window it traded on 9 Nov'] : []);
  return html`<div class="compose">
    ${!busy && inv.done && sugg.length > 0 && html`<div class="sugg">${sugg.map(s => html`<button onClick=${() => send(s)}>${s}</button>`)}</div>`}
    <div class="cbox">
      ${ui.ctx && html`<div><span class="ctx">${ui.ctx.label}<button aria-label="Remove" onClick=${() => act.clearCtx()}>×</button></span></div>`}
      <textarea ref=${ta} id="ask" rows="2" value=${text} disabled=${busy || !ready} aria-label="Ask the agent"
        placeholder=${busy ? 'The agent is working…' : ui.ctx ? 'Ask about this…' : 'Ask about this investigation, or click anything in it'}
        onInput=${e => setText(e.target.value)} onKeyDown=${e => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); send(); } }}></textarea>
      <div class="row"><span class="muted small">Answers land here and on the chart</span><button class="btn sm primary" disabled=${busy || !ready || !text.trim()} onClick=${() => send()}>Ask</button></div></div></div>`;
}
