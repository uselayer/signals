// An investigation's state, built only from its events (docs/research-contract.md, events 1–11), so a reload or a
// reconnect replays to the same page. v1 events (start, tool_call, answer, done…) are understood too, so the page
// works against the service before v2 lands. `ui` is the page's own state (what's open), never sent anywhere.

export function emptyInv(id) {
  return {
    id, title: '', subject: null, question: '', origin: null, scope: null,
    plans: {}, planOrder: [], tools: [], coverage: null, summaries: [], walkthroughs: {}, findings: {},
    feed: [], running: false, done: false, error: null, lastSeq: -1, log: [], focus: null, usage: null,
  };
}

export function emptyUi() {
  return { stage: 'plan', win: null, step: 0, ph: null, full: false, raw: false, hl: null, ctx: null, pin: null,
    tab: 'findings', tradeFilter: null, pop: null, followAgent: true, wf: null };
}

const feedPush = (s, item) => { s.feed.push(item); };
const working = s => s.feed.find(x => x.type === 'working' && !x.closed);
const workLine = (s, text) => { let w = working(s); if (!w) { w = { type: 'working', lines: [] }; s.feed.push(w); } w.lines.forEach(l => { l.done = true; }); w.lines.push({ text }); };
const closeWork = s => { const w = working(s); if (w) { w.closed = true; s.feed = s.feed.filter(x => x !== w); } };
export const KNOWN_V = 2;

// The agent column's feed by question: each question with what came back for it. A plan's Start isn't a new
// question: its run answers the question that made the plan.
export function groups(feed) {
  const out = [];
  for (const it of feed) {
    if (it.type === 'ask' && !(it.start && out.length)) { out.push({ ask: it, items: [], askIds: it.ask_id != null ? [it.ask_id] : [] }); continue; }
    if (!out.length) out.push({ ask: null, items: [], askIds: [] });
    if (it.type !== 'ask') out[out.length - 1].items.push(it);
    else if (it.ask_id != null) out[out.length - 1].askIds.push(it.ask_id); // a Start's run answers this question
  }
  return out;
}
// An accepted next step, as the user said it: the service sends "Yes, go ahead: <the agent's suggestion>" (owner,
// 11 Nov: the column read "Yes: Yes, go ahead: Next, I'd look at…").
export function yesText(t) {
  t = String(t ?? '').replace(/^\s*yes(,\s*go ahead)?\s*[:.]?\s*/i, '').replace(/^next,\s*/i, '').trim();
  return t.charAt(0).toUpperCase() + t.slice(1);
}

// The column's questions by run (owner, 11 Nov: after Start on a next step, "the chat is just so bombarded with
// previous findings"). A run is what one scope answered: the first question, then each accepted next step and each
// question that widened the breakdown (it came back with a plan). A question about the same scope stays in its run.
export function runs(gs) {
  const out = [];
  for (const g of gs) {
    if (!out.length || (g.ask && g.ask.proposal) || g.items.some(x => x.type === 'plan')) out.push({ groups: [g] });
    else out[out.length - 1].groups.push(g);
  }
  for (const r of out) r.askIds = r.groups.flatMap(g => g.askIds || []); // the server's run ids that answered it
  return out;
}

// One question's windows (owner, 11 Nov: the page mixed every question's windows and added their totals). Each tile
// keeps the runs that drew it (window.summary `run`); a breakdown with no tagged tile shows them all.
export function runSummaries(s, r) {
  if (!r || !s.summaries.some(x => x.asks && x.asks.length)) return s.summaries;
  const ids = new Set(r.askIds);
  return s.summaries.filter(x => !(x.asks || []).length || x.asks.some(a => ids.has(a))); // untagged: never hidden
}
// A finished question that drew no windows of its own (owner, 11 Nov: "how many seconds after Chainlink…" counted
// fills in the first question's windows, and its Windows tab said "Windows appear here as the agent draws them"
// under "Done"): the windows its findings name, else the breakdown's. Null when it has its own, or none exist.
export function borrowedWindows(s, r) {
  if (!r || runSummaries(s, r).length || !s.summaries.length) return null;
  const ids = new Set(r.groups.flatMap(g => g.items).filter(x => x.type === 'finding').map(x => s.findings[x.id]).filter(Boolean)
    .flatMap(f => { const ev = f.evidence || {}; return [...(ev.supporting_window_ids || ev.supporting || []), ...(ev.against_window_ids || ev.against || [])]; }));
  const named = s.summaries.filter(x => ids.has(x.window_id));
  return { sums: named.length ? named : s.summaries, named: named.length > 0 };
}
// A question's plan: the one its column shows, else (the first question) the breakdown's first plan.
export function planOfRun(s, r, i) {
  const it = r.groups.flatMap(g => g.items).find(x => x.type === 'plan');
  return (it ? s.plans[it.plan_id] : i === 0 ? s.plans[s.planOrder[0]] : null) || null;
}

// The 15-minute windows a plan's scope covers ({from: "9 Nov 2026 11:00 UTC", to: …}), as start times in seconds;
// null when the range can't be read or is longer than four days.
const MON = { Jan: 0, Feb: 1, Mar: 2, Apr: 3, May: 4, Jun: 5, Jul: 6, Aug: 7, Sep: 8, Oct: 9, Nov: 10, Dec: 11 };
const scopeTime = t => {
  const m = /(\d{1,2}) ([A-Z][a-z]{2})\w* (\d{4}),? (\d{1,2}):(\d{2})/.exec(String(t || ''));
  return m && MON[m[2]] != null ? Date.UTC(+m[3], MON[m[2]], +m[1], +m[4], +m[5]) / 1000 : null;
};
export function scopeSlots(scope) {
  // only 15-minute windows have slots: a market type whose unit is a market (long-dated BTC) has none
  if (scope && scope.market_type && scope.market_type !== 'btc-updown-15m') return null;
  const a = scope && scopeTime(scope.from), b = scope && scopeTime(scope.to);
  if (a == null || b == null || b <= a || b - a > 4 * 86400) return null;
  const out = [];
  for (let t = Math.ceil(a / 900) * 900; t < b; t += 900) out.push(t);
  return out.length ? out : null;
}
// A run's name: the breakdown's title for the first, else its plan's title, else what was asked.
export function runTitle(s, r, i) {
  const planIt = r.groups.flatMap(g => g.items).find(x => x.type === 'plan');
  const t = i === 0 ? (s.title || (r.groups[0].ask || {}).text) : (planIt && s.plans[planIt.plan_id] ? s.plans[planIt.plan_id].title : (r.groups[0].ask || {}).text);
  return t || 'Breakdown';
}
export const runCards = (s, r) => r.groups.flatMap(g => g.items).filter(x => (x.type === 'finding' && (s.findings[x.id] || {}).counts !== false) || x.type === 'answer').length;

// The plan the page shows: the current run's. Null while an accepted next step is still working its plan out.
export function currentPlan(s) {
  if (s.runPlan === null && (s.running || s.starting)) return null;
  return s.plans[s.runPlan ?? s.planOrder[s.planOrder.length - 1]] || null;
}

// What the column shows under the latest question while nothing else says the agent is busy: from the click (the
// page's own "Starting…") until its first progress line, so the column is never still while it works.
export function thinking(s, g) {
  if (!(s.running || s.starting)) return null;
  if (s.feed.some(x => x.type === 'working' && !x.closed)) return null; // its own progress lines show
  if (g.items.some(x => x.type === 'answer')) return null;
  const planned = g.items.some(x => x.type === 'plan') || (s.planOrder.length > 0 && !(g.ask && g.ask.proposal));
  const last = s.log.length > (s.runLog ?? s.log.length) ? s.log[s.log.length - 1].text : null;
  return { text: s.starting ? 'Starting…' : planned ? 'Working…' : 'Drafting a plan…', sub: s.starting ? null : last };
}

const ctxLabel = c =>c.trade_id ? 'a trade' : c.window_id && c.t != null ? 'a moment' : c.finding_id ? 'a finding' : '';
const toolName = n => ({ wallet_trades: 'Read its trades', wallet_profile: "Read its Signals record", window: 'Built a window', market: 'Built a market', wallet_markets: 'Listed its markets', outside_prices: 'Read Binance and Chainlink prices', code: 'Ran a calculation', make_chart: 'Drew a chart',
  propose_plan: 'Proposed a plan', step_status: 'Updated a step', show_windows: 'Showed windows', focus: 'Moved the view', walkthrough: 'Wrote a walkthrough', finding: 'Added a finding', answer: 'Wrote the answer', propose: 'Offered a next step' }[n] || n);
const count = (n, one, many) => `${n} ${n === 1 ? one : many}`;
const scalars = o => Object.entries(o).filter(([k, v]) => v != null && typeof v !== 'object' && k !== 'ms').map(([k, v]) => `${k} ${v}`).join(', ');
// A tool result's line in the activity log. `summary` is the tool's own short figures, an object whose shape depends
// on the tool (docs/research-contract.md, tool.result): put it in words, never print the object itself.
export function resultText(e) {
  const s = e.summary, tool = e.tool || e.name;
  if (typeof s === 'string') return s || (e.ok === false ? 'failed' : 'done');
  if (!s || typeof s !== 'object') return e.rows != null ? count(e.rows, 'row', 'rows') : e.ok === false ? 'failed' : 'done';
  if (typeof s.text === 'string' && s.text) return s.text;
  if (e.ok === false || s.error) return s.error === 'stopped' ? 'not run: the breakdown was stopped' : `failed${typeof s.error === 'string' ? `: ${s.error}` : ''}`;
  const checked = s.number_check === false ? ', a number flagged' : '';
  switch (tool) {
    case 'wallet_trades': if (s.rows != null) return `${count(s.rows, 'trade', 'trades')}${s.windows != null ? ` in ${count(s.windows, 'window', 'windows')}` : ''}`; break;
    case 'wallet_profile': return s.name ? `found ${s.name}` : 'no Polymarket name';
    case 'window': if (s.slug) return `${s.slug}${s.result ? `, ended ${s.result}` : ''}`; break;
    case 'market': if (s.slug) return `${count(s.fills || 0, 'fill', 'fills')}${s.result ? `, resolved ${s.result}` : s.profit_kind === 'open' ? ', still open' : ''}`; break;
    case 'wallet_markets': if (s.rows != null) return `${count(s.rows, 'market', 'markets')}${s.matched != null && s.matched > s.rows ? ` of ${s.matched}` : ''}${s.complete === false ? ', trades cut short' : ''}`; break;
    case 'outside_prices': if (s.points != null) return s.available === false ? `${s.source || 'prices'}: not available` : `${count(s.points, 'price', 'prices')}${s.source ? ` from ${s.source}` : ''}`; break;
    case 'make_chart': if (s.title) return s.title; break;
    case 'propose_plan': if (s.steps != null) return count(s.steps, 'step', 'steps'); break;
    case 'step_status': if (s.step_id != null) return `step ${s.step_id} ${s.status || ''}`.trim(); break;
    case 'show_windows': if (s.rows != null) return `${count(s.rows, 'window', 'windows')}${s.failed ? `, ${s.failed} couldn't be built` : ''}`; break;
    case 'focus': if (s.stage) return `to ${s.stage}`; break;
    case 'walkthrough': if (s.steps != null) return count(s.steps, 'step', 'steps') + checked; break;
    case 'finding': if (s.finding_id) return s.finding_id; break;
    case 'answer': return 'shown' + checked;
    case 'propose': if (s.proposal_id) return s.proposal_id; break;
    default: break;
  }
  return scalars(s) || (e.rows != null ? count(e.rows, 'row', 'rows') : 'done');
}
const argsText = e => { const a = e.args ?? e.args_plain ?? e.summary; if (!a) return ''; if (typeof a === 'string') return a; if (a.code) return ''; return Object.entries(a).filter(([, v]) => v != null && typeof v !== 'object').map(([k, v]) => `${k} ${v}`).join(', ').slice(0, 140); };
const at = e => (e.started_at || e.at) ? new Date(((e.started_at || e.at) > 1e12 ? (e.started_at || e.at) : (e.started_at || e.at) * 1000)).toISOString().slice(11, 19) : '';

// Apply one event. Returns what the page should do about it (e.g. move the workspace on view.focus).
export function apply(s, e, ui) {
  if (e.seq != null) { if (e.seq <= s.lastSeq) return; s.lastSeq = e.seq; }
  if (e.v > KNOWN_V) s.needsReload = true;
  const t = e.type;
  switch (t) {
    case 'investigation.created':
      Object.assign(s, { title: e.title || s.title, subject: e.subject || null, question: e.question || '', origin: e.origin || null, scope: e.scope || null });
      break;
    case 'start': case 'ask.started': { // v1 'start', v2 'ask.started' (a question, or a plan's Start)
      const prop = !!(e.context && e.context.proposal_id);
      const text = e.context && e.context.plan_id ? 'Start the plan' : prop ? yesText(e.text) : (e.text ?? e.question);
      s.running = true; s.done = false; s.starting = false; if (!s.question) s.question = text;
      if (e.ask_id != null) s.curAsk = e.ask_id; // tiles without a run id (fixtures) belong to the run going on
      // the run's clock: the server's start time (a reload keeps counting from it), its limit, how long runs like it usually take
      s.clock = { start: e.started_at ?? Date.now() / 1000, limit: e.limit_s ?? null, typical: e.typical_s ?? null };
      s.feed = s.feed.filter(x => !x.pending); // the page's own echo of what was sent, now the server's
      s.runLog = s.log.length; // the activity lines from here on are this run's
      if (prop) s.runPlan = null; // an accepted next step is a new run: its plan is still to come
      feedPush(s, { type: 'ask', text, proposal: prop, at: e.started_at ?? null, ctx: e.context ? (e.context.label || ctxLabel(e.context)) : null, ask_id: e.ask_id, start: !!(e.context && e.context.plan_id) });
      break;
    }
    case 'plan.proposed': {
      const p = { ...e, status: 'proposed', steps: (e.steps || []).map(x => ({ status: 'queued', est: x.estimate_s ?? x.est_s, ...x })) };
      s.plans[e.plan_id] = p; if (!s.planOrder.includes(e.plan_id)) s.planOrder.push(e.plan_id);
      s.runPlan = e.plan_id;
      if (s.planOrder.length > 1) feedPush(s, { type: 'plan', plan_id: e.plan_id }); // a follow-up's plan: in the column
      if (ui && s.planOrder.length === 1) ui.stage = 'plan';
      break;
    }
    case 'plan.answered': { const p = s.plans[e.plan_id]; if (p) p.status = e.action === 'approve' ? 'approved' : 'edited'; if (e.action !== 'approve') s.starting = false; break; }
    // Start pressed while another breakdown of yours works: it waits, then starts by itself (plan.answered then);
    // unqueued: it never started (a restart), so the plan waits for Start again
    case 'plan.queued': { const p = s.plans[e.plan_id]; if (p) p.status = 'queued'; s.starting = false; break; }
    case 'plan.unqueued': { const p = s.plans[e.plan_id]; if (p) p.status = 'proposed'; if (e.text) feedPush(s, { type: 'note', text: e.text }); break; }
    case 'proposal.answered': { const it = s.feed.find(x => x.type === 'proposal' && x.proposal_id === e.proposal_id); if (it) it.state = e.action === 'accept' ? 'accepted' : 'declined'; break; }
    case 'step.status': {
      for (const p of Object.values(s.plans)) { const st = p.steps.find(x => x.id === e.step_id); if (st) Object.assign(st, { status: e.status, progress: e.progress, summary: e.summary ?? st.summary, warnings: e.warnings ?? st.warnings }); }
      if (e.status === 'running' && e.summary) workLine(s, e.summary);
      break;
    }
    case 'tool.call': case 'tool_call':
      s.tools.push({ id: e.id, step_id: e.step_id, tool: e.tool || e.name, args: argsText(e), at: at(e) });
      s.log.push({ at: at(e), text: `${toolName(e.tool || e.name)}${argsText(e) ? ': ' + argsText(e) : ''}` });
      if (t === 'tool_call') workLine(s, `Reading: ${e.name}`);
      break;
    case 'tool.result': case 'tool_result': {
      const c = s.tools.find(x => x.id === e.id); if (c) Object.assign(c, { rows: e.rows, ok: e.ok !== false, limit_hit: e.limit_hit });
      s.log.push({ at: at(e), text: `${toolName(e.tool || e.name || 'result')}: ${resultText(e)}${e.ms ? ` (${(e.ms / 1000).toFixed(1)} s)` : ''}${e.limit_hit ? '. Stopped at the read limit: the history is partial.' : ''}`, flagged: e.ok === false || e.limit_hit });
      if (e.limit_hit) s.partial = true;
      break;
    }
    case 'progress': workLine(s, e.text); break; // v1: the agent's own note on what it's doing
    case 'code': s.log.push({ at: at(e), text: 'Ran a calculation' }); break;
    case 'coverage': s.coverage = e; break;
    case 'window.summary': {
      const i = s.summaries.findIndex(x => x.window_id === e.window_id);
      const row = { ...e }; delete row.type; delete row.seq;
      // which runs drew it: the event's run; a tile reloaded from /windows (no seq) adds none
      const tag = e.run ?? (e.seq != null ? s.curAsk : null);
      row.asks = [...new Set([...((i >= 0 && s.summaries[i].asks) || []), ...(tag != null ? [tag] : [])])];
      if (i >= 0) s.summaries[i] = row; else s.summaries.push(row);
      s.summaries.sort((a, b) => a.start - b.start);
      break;
    }
    case 'walkthrough.ready': s.walkthroughs[e.window_id] = e.steps || []; break;
    case 'view.focus':
      s.focus = e;
      if (ui && ui.followAgent) {
        ui.stage = e.stage || ui.stage; if (e.window_id) ui.win = e.window_id;
        if (e.step_index != null) { ui.step = e.step_index; ui.ph = null; }
        if (e.highlight_window_ids && e.highlight_window_ids.length) ui.hl = { label: e.label || 'the windows the agent picked', match: new Set(e.highlight_window_ids), base: null };
      }
      break;
    case 'finding.added': case 'finding.updated': {
      const prev = s.findings[e.finding_id];
      s.findings[e.finding_id] = { ...(prev || {}), ...e, previous: e.previous ?? (prev && t === 'finding.updated' ? { stat: prev.stat, title: prev.title } : undefined) };
      if (!prev) feedPush(s, { type: 'finding', id: e.finding_id });
      break;
    }
    case 'proposal': feedPush(s, { ...e, type: 'proposal', state: 'open' }); break;
    case 'answer.progress': workLine(s, e.text); break;
    case 'answer.card':
      closeWork(s); feedPush(s, { ...e, type: 'answer' });
      if (ui && e.annotations && e.annotations.length) ui.extraAnn = e.annotations; // what the answer points at, drawn
      break;
    case 'chart': s.charts = [...(s.charts || []), e]; break; // the later "+ New view"
    case 'note': case 'notice': feedPush(s, { type: 'note', text: e.text }); break;
    case 'check': // v1: the number check on the answer
      if (!e.retrying && e.unmatched && e.unmatched.length) s.log.push({ at: at(e), text: `Numbers not found in the data: ${e.unmatched.join(', ')}`, flagged: true });
      break;
    case 'answer': // v1: a plain answer, numbers checked; unmatched ones flagged
      closeWork(s);
      feedPush(s, { type: 'answer', label: null, text: e.text, number_check: { passed: !(e.unverified || []).length, flagged: (e.unverified || []).map(v => ({ value_text: String(v) })) }, truncated: e.truncated });
      break;
    case 'usage': s.usage = e; break;
    case 'error': closeWork(s); s.error = e.message; s.running = false; s.starting = false; feedPush(s, { type: 'error', text: e.message }); break;
    case 'done': closeWork(s); s.running = false; s.starting = false; s.done = true; for (const p of Object.values(s.plans)) if (p.status === 'approved') p.status = 'done'; break;
    default: break;
  }
}

// While a run works: its time so far ("1:42"), what's left in words, and how far along the bar is (0–1). "About N
// min left" only from the server's measured typical_s (recent runs of the same kind); past it, or without one, the
// time limit is the only promise. Never 100% until it's done.
export function runClock(s, now = Date.now() / 1000) {
  if (!s.running || !s.clock) return null;
  const { start, limit, typical } = s.clock;
  const e = Math.max(0, now - start), m = Math.floor(e / 60);
  const elapsed = `${m}:${String(Math.floor(e % 60)).padStart(2, '0')}`;
  const cap = limit ? `it stops by ${Math.round(limit / 60)} min` : '';
  let left, frac;
  // with a typical time the bar fills to 80% by then, and creeps on to 95% by the limit (never backwards)
  if (typical && e < typical) { left = `about ${Math.max(1, Math.ceil((typical - e) / 60))} min left`; frac = 0.8 * e / typical; }
  else if (typical) { left = `taking longer than usual${cap ? `, ${cap}` : ''}`; frac = 0.8 + (limit > typical ? 0.15 * (e - typical) / (limit - typical) : 0.15); }
  else { left = cap ? `${cap} at the latest` : ''; frac = limit ? e / limit : 0; }
  return { elapsed, left, frac: limit || typical ? Math.min(0.95, Math.max(0.02, frac)) : null }; // no bar with nothing to measure against
}

// Where a Started plan has got to (Drew, 10 Nov: "how far along is it?"): "Step 2 of 4" and one bar segment per
// step, from the steps' statuses (step.status), so the bar only moves when the agent finishes a step. Only while a
// run works on an approved plan; a question's run has no steps, and the page shows its clock alone.
export function planProgress(s) {
  if (!s.running) return null;
  const p = [...s.planOrder].reverse().map(id => s.plans[id]).find(x => x && x.status === 'approved');
  return p && p.steps.length ? stepProgress(p.steps) : null;
}
const FINISHED = new Set(['done', 'warning', 'failed']);
// The step being worked on is the one running, else the first not finished; with all finished it's writing up.
// frac: how far the running step is, only when the agent counted it (step.status progress {done, total}).
export function stepProgress(steps) {
  const total = steps.length, done = steps.filter(x => FINISHED.has(x.status)).length;
  let i = steps.findIndex(x => x.status === 'running');
  if (i < 0) i = steps.findIndex(x => !FINISHED.has(x.status));
  const cur = i < 0 ? null : steps[i];
  const frac = cur && cur.status === 'running' && cur.progress && cur.progress.total > 0 ? Math.min(1, Math.max(0, cur.progress.done / cur.progress.total)) : null;
  return { total, done, step: i < 0 ? total : i + 1, finishing: i < 0, label: i < 0 ? 'Finishing up' : `Step ${i + 1} of ${total}`,
           segs: steps.map((x, k) => (FINISHED.has(x.status) ? 'done' : k === i ? 'run' : '')), frac };
}

// A running breakdown's row in the list, from the server's run_progress: "Running · step 2 of 4 · about 3 min left".
export function rowProgress(p, now = Date.now() / 1000) {
  p = p || {};
  const c = p.started_at ? runClock({ running: true, clock: { start: p.started_at, limit: p.limit_s ?? null, typical: p.typical_s ?? null } }, now) : null;
  const step = p.steps ? (p.done >= p.steps ? 'finishing up' : `step ${p.step} of ${p.steps}`) : null;
  return ['Running', step, c && c.left].filter(Boolean).join(' · ');
}

// A breakdown that isn't running, in the list: "ready" when its latest run ended cleanly after you last opened it (and
// after `since`, the first visit with this code, within a day), "stopped" when it ended on an error, else "saved".
// `opened` {id: seconds} is what you opened (signals.breakdowns.opened, shared with the main page's pill).
export function rowState(r, opened, since, now = Date.now() / 1000) {
  if (r.running) return 'running';
  if (r.queued) return 'queued';
  if (r.stopped) return 'stopped';
  return r.ended && r.ended > since && r.ended > (opened[r.id] || 0) && now - r.ended < 86400 ? 'ready' : 'saved';
}

// Every number in a text, split around the ones the check flagged ({value_text, start, end}): so a card can strike
// exactly the flagged number where it stands.
export function splitFlagged(text, flagged) {
  if (!flagged || !flagged.length || !text) return [{ text: text || '' }];
  const spans = flagged.map(f => (f.start != null && f.end != null) ? f : (() => { const i = text.indexOf(f.value_text); return i < 0 ? null : { ...f, start: i, end: i + f.value_text.length }; })())
    .filter(Boolean).sort((a, b) => a.start - b.start);
  const out = []; let i = 0;
  for (const f of spans) { if (f.start < i) continue; out.push({ text: text.slice(i, f.start) }); out.push({ text: text.slice(f.start, f.end), flag: f }); i = f.end; }
  out.push({ text: text.slice(i) });
  return out;
}

// The number check's flags for one field of a finding/step/answer: the service keys them by field ("observed",
// "step 2 observed"); a plain list applies to every field.
export const flagsFor = (check, field) => {
  if (!check || check.passed !== false) return [];
  const f = check.flagged || [];
  if (Array.isArray(f)) return f.filter(x => !x.field || x.field === field);
  return f[field] || [];
};
