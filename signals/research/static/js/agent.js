// The agent's column: what it's doing, its answers (on top), its evidence (findings, one line each, the proof one
// tap away), and the question box with the one next step. What it finds opens the windows and fills behind them.
import { html, useState, useRef, useEffect } from '../vendor/htm-preact-3.1.1.module.js';
import { flagged, SigninCard } from './views.js';
import { flagsFor, groups, runs, runTitle, runCards, thinking } from './store.js';
import { RunProgress } from './clock.js';
import { money, shortWallets } from './format.js';


export function AgentColumn({ inv, ui, act, fixtures }) {
  const feedRef = useRef(), n = inv.feed.length;
  const [open, setOpen] = useState(null); // the one finding opened to its proof
  const [openRuns, setOpenRuns] = useState(() => new Set()); // earlier runs opened again from their folded line
  // a new item keeps the latest question in view, its answer on top (not the bottom of a long feed)
  useEffect(() => {
    const el = feedRef.current; if (!el || ui.tab !== 'findings') return;
    const last = el.querySelector(':scope > .group:last-child'); // not one inside an earlier run opened again
    if (last) el.scrollTop += last.getBoundingClientRect().top - el.getBoundingClientRect().top - 12;
  }, [n, ui.tab]);
  const toggle = f => {
    if (open === f.finding_id) { setOpen(null); act.clearHl(); return; }
    setOpen(f.finding_id);
    const ev = f.evidence || {};
    if (f.kind !== 'data' && (ev.supporting_window_ids || ev.supporting || []).length) act.highlight(f); else act.clearHl();
  };
  const working = inv.running;
  const last = inv.plans[inv.planOrder[inv.planOrder.length - 1]];
  const queued = !working && last && last.status === 'queued', waiting = queued || (!working && last && last.status === 'proposed');
  // earlier runs fold to one line each; the Findings count is the current run's
  const rs = runs(groups(inv.feed)), cur = rs[rs.length - 1], many = rs.length > 1;
  const nCards = cur ? runCards(inv, cur) : 0;
  const flip = i => setOpenRuns(s => { const t = new Set(s); if (t.has(i)) t.delete(i); else t.add(i); return t; });
  const lastG = cur && cur.groups[cur.groups.length - 1];
  const showGroups = (gs, think) => gs.map((g, i) => html`<${Group} key=${i} g=${g} inv=${inv} act=${act} open=${open} toggle=${toggle} think=${think && g === lastG ? thinking(inv, g) : null} />`);
  return html`<aside class="agent" aria-label="The research agent">
    <div class="agent-head"><span class=${'dot ' + (working || inv.starting ? 'live' : inv.done && !waiting ? 'ok' : '')}></span>
      <div><div class="t">Signals agent</div><div class="s">${working ? html`Working · <${RunProgress} inv=${inv} />` : inv.starting ? 'Starting…' : inv.error ? 'Stopped on an error' : queued ? 'Queued · starts when your other breakdown finishes' : waiting ? 'Waiting for you to start the plan' : inv.done ? 'Done · saved' : waitingFor(inv)}</div></div></div>
    <div class="atabs" role="tablist"><button role="tab" class=${ui.tab === 'findings' ? 'on' : ''} onClick=${() => act.tab('findings')}>Findings${nCards ? ` · ${nCards}` : ''}</button>
      <button role="tab" class=${ui.tab === 'activity' ? 'on' : ''} onClick=${() => act.tab('activity')}>Activity and data</button></div>
    <div class="feed" ref=${feedRef}>${ui.tab === 'activity' ? html`<${Activity} inv=${inv} />` : html`
      ${inv.needsReload && html`<div class="banner err">This page is older than the research service. Reload to see everything.</div>`}
      ${inv.feed.length === 0 && html`<div class="note"><span class="dot"></span><p class="muted">The plan appears in the workspace first. Nothing runs until you press Start.</p></div>`}
      ${many && rs.slice(0, -1).map((r, i) => html`<div class="runfold-wrap" key=${'r' + i}>
        <button class="runfold" aria-expanded=${openRuns.has(i) ? 'true' : 'false'} onClick=${() => flip(i)}>
          <span><b>Earlier question</b> · ${shortWallets(runTitle(inv, r, i))}${runCards(inv, r) ? ` · ${runCards(inv, r)} finding${runCards(inv, r) === 1 ? '' : 's'}` : ''}</span>
          <span class="muted">${openRuns.has(i) ? 'Hide' : 'Open'}</span></button>
        ${openRuns.has(i) && html`<div class="runpast">${showGroups(r.groups, false)}</div>`}</div>`)}
      ${many && html`<div class="rundiv">New question${cur.groups[0].ask && cur.groups[0].ask.at ? ` · started ${new Date(cur.groups[0].ask.at * 1000).toISOString().slice(11, 16)} UTC` : ''}</div>`}
      ${cur && showGroups(cur.groups, true)}`}</div>
    <${Composer} inv=${inv} ui=${ui} act=${act} fixtures=${fixtures} />
  </aside>`;
}

const waitingFor = inv => { const p = inv.plans[inv.planOrder[inv.planOrder.length - 1]]; return p && p.status === 'proposed' ? 'Waiting for you to start the plan' : 'Ready'; };

const startedPlan = p => !!p && p.status !== 'proposed' && p.status !== 'signin';

// One question: its answer first, then each finding on one line, then what's still running. A proposal isn't
// here: it's the one next step, above the ask box.
function Group({ g, inv, act, open, toggle, think }) {
  const answers = g.items.filter(x => x.type === 'answer');
  const fs = g.items.filter(x => x.type === 'finding').map(x => inv.findings[x.id]).filter(Boolean);
  const rows = [...fs.filter(f => f.kind !== 'data'), ...fs.filter(f => f.kind === 'data')]; // what's missing last
  // A started plan is what this question set going, so it sits with the question on top (owner, 11 Nov: under the
  // findings, "● Plan started" read as the status while the header said "Done · saved").
  const started = g.items.filter(x => x.type === 'plan' && startedPlan(inv.plans[x.plan_id])).map(x => inv.plans[x.plan_id]);
  const rest = g.items.filter(x => x.type !== 'answer' && x.type !== 'finding' && x.type !== 'proposal' && !(x.type === 'plan' && startedPlan(inv.plans[x.plan_id])));
  return html`<section class="group">
    ${(g.ask || started.length > 0) && html`<p class="asked" title=${[g.ask && g.ask.text, ...started.map(p => p.title)].filter(Boolean).join('\n')}>
      ${g.ask && html`<span class="clamp"><span class="muted">${g.ask.proposal ? 'You said yes to' : html`You asked${g.ask.ctx ? html` about <span class="ctx">${g.ask.ctx}</span>` : ''}`}:</span> ${g.ask.text}</span>`}
      ${started.map(p => html`<span class="clamp" key=${p.plan_id}><span class="muted">${g.ask ? 'Plan' : 'You started'}:</span> ${p.title}</span>`)}</p>`}
    ${answers.map((a, i) => html`<${Answer} key=${i} a=${a} inv=${inv} act=${act} />`)}
    ${rows.length > 0 && html`<div class="frows">${answers.length > 0 && html`<h5>What it found</h5>`}
      ${rows.map(f => html`<${Finding} key=${f.finding_id} f=${f} inv=${inv} act=${act} open=${open === f.finding_id} toggle=${() => toggle(f)} />`)}</div>`}
    ${rest.map((it, i) => html`<${Item} key=${i} it=${it} inv=${inv} act=${act} />`)}
    ${think && html`<div class="typing" role="status"><span class="dots" aria-hidden="true"><i></i><i></i><i></i></span><div><p>${think.text}</p>${think.sub && html`<p class="muted small">${think.sub}</p>`}</div></div>`}
  </section>`;
}

function Item({ it, inv, act }) {
  if (it.type === 'note') return html`<div class="note"><span class="dot ok"></span><p>${it.text}</p></div>`;
  if (it.type === 'error') return html`<div class="banner err">${it.text}</div>`;
  if (it.type === 'working') return html`<div class="working"><span class="dot live"></span><div>${it.lines.map(l => html`<p class=${l.done ? 'done' : ''}>${l.done ? '✓ ' : ''}${l.text}</p>`)}</div></div>`;
  if (it.type === 'plan') { const p = inv.plans[it.plan_id]; if (!p) return null;
    if (p.status === 'signin') return html`<${SigninCard} p=${p} />`; // the sample's end: run it on your own
    if (p.status !== 'proposed') return null; // started: shown with its question, at the top of the group
    // its steps are in the workspace (the Plan tab shows the current run's plan): here, what it is and Start
    return html`<div class="proposal"><div class="k">This widens the breakdown, so here's the plan first</div><p><b>${p.title}</b></p>
      <p class="muted small">${p.steps.length} step${p.steps.length === 1 ? '' : 's'}${p.estimate_usd != null ? `, about ${money(p.estimate_usd)} of model time` : ''}. <button class="link" onClick=${() => act.stage('plan')}>See the steps</button></p>
      <div style="display:flex;gap:6px"><button class="btn sm primary" onClick=${() => act.approve(p.plan_id)}>Start</button><button class="btn sm ghost" onClick=${() => act.editPlan(p.plan_id)}>Change the plan</button></div></div>`; }
  return null;
}

// A finding (contract: finding.added/updated) on one line: its title and count, with a tag only when it's a reading
// (Inferred) or a number failed its check. Opening it shows the proof (how it was counted, what it rests on, what
// would change it, an example to step through) and lights its windows. A finding whose numbers didn't check out
// (counts: false) isn't counted.
function Finding({ f, inv, act, open, toggle }) {
  const inferred = f.label === 'inferred', nc = f.number_check, data = f.kind === 'data';
  const isFlagged = (nc && nc.passed === false) || f.counts === false;
  const ev = f.evidence || {}, sup = new Set(ev.supporting_window_ids || ev.supporting || []);
  const against = ev.against_window_ids || ev.against || [], base = [...sup, ...against];
  const order = inv.summaries.map(s => s.window_id).filter(id => base.includes(id));
  const allFlags = isFlagged ? ['title', 'stat', 'rule', 'would_change_mind'].flatMap(k => flagsFor(nc, k)) : [];
  const prev = f.previous && f.previous.stat && f.stat && f.previous.stat.text !== f.stat.text ? f.previous.stat.text : null;
  const ex = f.example && f.example.window_id ? f.example : null;
  const ruleLines = (f.rule || '').split('\n').filter(Boolean);
  const count = f.stat && f.stat.count != null && f.stat.out_of != null ? `${f.stat.count.toLocaleString('en-US')} of ${f.stat.out_of.toLocaleString('en-US')}` : null;
  const statText = f.stat && f.stat.text ? f.stat.text : null;
  const basedOn = (f.based_on || []).map(id => (inv.findings[id] ? inv.findings[id].title : id));
  const tag = html`<span class=${'tag ' + (inferred ? 'inferred' : 'observed')}>${inferred ? 'Inferred' : 'Observed'}</span>`;
  return html`<div class=${'frow' + (open ? ' open' : '') + (data ? ' data' : '')}>
    <button class="fline" aria-expanded=${open ? 'true' : 'false'} onClick=${toggle}>
      <span class="ft">${flagged(f.title, flagsFor(nc, 'title'))}</span>
      ${isFlagged ? html`<span class="tag flag">Number not verified</span>` : inferred ? html`<span class="tag inferred">Inferred</span>` : f.kind === 'unsure' ? html`<span class="tag plain">Not sure yet</span>` : null}
      ${data ? html`<span class="fs">${ruleLines.length} note${ruleLines.length === 1 ? '' : 's'}</span>` : count && html`<span class="fs">${count}</span>`}
      <span class="chev" aria-hidden="true"></span></button>
    ${open && html`<div class="fbody">
      ${data ? html`<ul>${ruleLines.map(l => html`<li>${l}</li>`)}</ul>` : html`
        ${!isFlagged && html`<p>${tag} ${statText ? flagged(statText, flagsFor(nc, 'stat')) : ''}${prev ? html` <span class="muted">(was ${prev})</span>` : ''}</p>`}
        ${order.length > 0 && html`<div class="waffle">${order.map(id => html`<button class=${sup.has(id) ? '' : 'no'} title=${id} aria-label=${id} onClick=${() => act.openWin(id)}></button>`)}</div>`}
        ${f.body && html`<p>${f.body}</p>`}
        ${ruleLines.length > 0 && html`<p class="muted small"><b>How I counted:</b> ${flagged(f.rule, flagsFor(nc, 'rule'))}</p>`}`}
      ${isFlagged && html`<div class="flagnote">${allFlags.length ? `${allFlags.length} number${allFlags.length === 1 ? '' : 's'} didn't match the data the agent read: ${allFlags.map(x => x.value_text).join(', ')}.${allFlags.some(x => x.data_value) ? ` The data shows ${allFlags.filter(x => x.data_value).map(x => x.data_value).join(', ')}.` : ''}` : "Its numbers didn't check out against the data."} Not counted, and nothing inferred rests on it, until it's fixed.</div>`}
      ${basedOn.length > 0 && html`<p class="muted small"><b>Based on:</b> ${basedOn.join('; ')}.</p>`}
      ${f.would_change_mind && html`<p class="muted small"><b>What would change this reading:</b> ${flagged(f.would_change_mind, flagsFor(nc, 'would_change_mind'))}</p>`}
      ${(ex || isFlagged || (f.history && f.history.length > 0)) && html`<div class="acts2">${ex && html`<button class="link" onClick=${() => act.openWin(ex.window_id, ex.step_index ?? ex.step)}>Step through an example</button>`}
        ${isFlagged && html`<button class="link" onClick=${() => act.askFix(f)}>Ask the agent to fix it</button>`}
        ${f.history && f.history.length > 0 && html`<span class="check">Rewritten ${f.history.length === 1 ? 'once' : f.history.length + ' times'}</span>`}</div>`}
      ${f.sample_note && html`<span class="check">${f.sample_note}</span>`}</div>`}
  </div>`;
}

// An answer: structured (label, observed lines, inferred lines) or, when the agent wrote plain text, text whose
// paragraphs starting "Observed:" / "Inferred:" get their tag. It sits above its question's findings.
function Answer({ a, inv, act }) {
  const nc = a.number_check, isFlagged = nc && nc.passed === false;
  const allFlags = isFlagged ? Object.values((nc && nc.flagged) || {}).flat() : [];
  let rows;
  if (a.observed || a.inferred) {
    rows = [...(a.observed || []).map((t, i) => ({ kind: 'Observed', t, fl: flagsFor(nc, `observed ${i + 1}`) })),
            ...(a.inferred || []).map((t, i) => ({ kind: 'Inferred', t, fl: flagsFor(nc, `inferred ${i + 1}`) }))];
  } else {
    const fl = flagsFor(nc, 'text'); let off = 0;
    rows = (a.text || '').split(/\n+/).filter(Boolean).map(p => {
      const start = (a.text || '').indexOf(p, off); off = start + p.length;
      const local = fl.filter(x => x.start == null || (x.start >= start && x.end <= start + p.length)).map(x => (x.start == null ? x : { ...x, start: x.start - start, end: x.end - start }));
      const m = /^(Observed|Inferred):\s*/.exec(p);
      if (!m) return { kind: null, t: p, fl: local };
      const rest = p.slice(m[0].length), shift = m[0].length; // same length after capitalising: flag offsets hold
      return { kind: m[1], t: rest.charAt(0).toUpperCase() + rest.slice(1), fl: local.map(x => (x.start == null ? x : { ...x, start: x.start - shift, end: x.end - shift })) };
    });
  }
  return html`<article class=${'card answer ' + (isFlagged ? 'flagged' : '')}>
    ${a.label && html`<div class="k">${flagged(a.label, flagsFor(nc, 'label'))}</div>`}
    ${rows.map(r => r.kind ? html`<div class=${'line2 ' + (r.kind === 'Inferred' ? 'inf' : '')}><span class=${'tag ' + r.kind.toLowerCase()}>${r.kind}</span><p>${flagged(r.t, r.fl)}</p></div>` : html`<p>${flagged(r.t, r.fl)}</p>`)}
    ${isFlagged && html`<div class="flagnote">${allFlags.length} number${allFlags.length === 1 ? '' : 's'} didn't match the data: ${allFlags.map(x => x.value_text).join(', ')}.</div>`}
    ${(a.annotations || []).length > 0 && html`<p class="muted small">Marked on the chart.</p>`}
    ${inv.summaries.length > 1 && html`<div class="acts2"><button class="link" onClick=${() => act.stage('windows')}>See all ${inv.summaries.length} windows on one chart</button></div>`}
    ${a.truncated && html`<p class="muted small">The answer was cut short. Ask again for the rest.</p>`}
    ${a.computed_note && html`<span class="check">${a.computed_note}</span>`}</article>`;
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
    ${inv.usage && inv.usage.cost_usd != null && html`<p class="muted small">This breakdown's model and tools so far: ${money(inv.usage.cost_usd)}.</p>`}</div>`;
}

function Composer({ inv, ui, act, fixtures }) {
  const [text, setText] = useState('');
  const ta = useRef();
  useEffect(() => { if (ui.composeFocus && ta.current) { if (ui.composeText != null) setText(ui.composeText); ta.current.focus(); act.composed(); } }, [ui.composeFocus]);
  const busy = inv.running || inv.starting;
  const ready = inv.done || inv.planOrder.length > 0;
  const send = q => { q = (q ?? text).trim(); if (!q || busy) return; setText(''); act.ask(q); };
  // one next step: the agent's latest proposal while it's open, else (in the sample) one question with a recorded
  // answer; pointing at something offers its two quick questions instead
  const lastP = [...inv.feed].reverse().find(x => x.type === 'proposal');
  const next = !busy && inv.done && !ui.ctx && lastP && lastP.state === 'open' ? lastP : null;
  const sugg = ui.ctx ? ['Why here?', 'What happened here?'] : next ? [] : (fixtures ? ['Why does it buy below the asking price?'] : []);
  return html`<div class="compose">
    ${next && html`<div class="next"><div class="k">The agent suggests</div><p>${next.text}</p><button class="btn sm primary" onClick=${() => act.proposal(next, true)}>${next.accept_label || 'Yes'}</button></div>`}
    ${!busy && inv.done && sugg.length > 0 && html`<div class="sugg">${sugg.map(s => html`<button onClick=${() => send(s)}>${s}</button>`)}</div>`}
    <div class="cbox">
      ${ui.ctx && html`<div><span class="ctx">${ui.ctx.label}<button aria-label="Remove" onClick=${() => act.clearCtx()}>×</button></span></div>`}
      <textarea ref=${ta} id="ask" rows="2" value=${text} disabled=${busy || !ready} aria-label="Ask the agent"
        placeholder=${busy ? 'The agent is working…' : ui.ctx ? 'Ask about this…' : 'Ask about this breakdown, or click anything in it'}
        onInput=${e => setText(e.target.value)} onKeyDown=${e => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); send(); } }}></textarea>
      <div class="row"><button class="btn sm primary" disabled=${busy || !ready || !text.trim()} onClick=${() => send()}>Ask</button></div></div></div>`;
}
