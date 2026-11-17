// Fixtures mode (/research/?fixtures): the page against recorded data, no service, no sign-in. It answers the same
// calls as api.js `live`, from fixtures/: real windows from the service, and a sample event log
// (tests/research_sample.py) played out with the pauses a run has. Start on the plan plays the second run; the
// sample questions have recorded answers; anything else gets a note that only those answer here.

const SID = 'sample';
const pause = e => ({ 'tool.call': 500, 'tool.result': 350, 'step.status': 450, 'window.summary': 160, 'finding.added': 420, 'answer.progress': 700, 'answer.card': 300 }[e.type] ?? 250);

export async function fixtureApi(base = './fixtures/') {
  const sample = await (await fetch(base + 'events.sample.json')).json();
  const log = []; let wake = () => {}; let running = false;
  const push = e => { log.push({ ...e, v: 2, seq: log.length, at: Date.now() / 1000 }); wake(); };
  const play = async (events, slow = true) => {
    running = true;
    for (const e of events) { if (slow) await new Promise(r => setTimeout(r, pause(e))); push(e); }
    running = false; wake();
  };
  const windows = sample.runs[1].filter(e => e.type === 'window.summary').map(({ type, ...s }) => s);
  let asked = 2;
  const gone = new Set(); // deleted in the list (Undo brings one back)
  return {
    fixtures: true,
    config: async () => ({ clerk_key: null, event_version: 2, fixtures: true, market_types: [
      { id: 'btc-updown-15m', label: 'BTC Up or Down 15m', unit: 'window', min_days: 0 },
      { id: 'btc-monthly', label: 'BTC monthly', unit: 'market', min_days: 7 },
      { id: 'btc-yearly', label: 'BTC yearly', unit: 'market', min_days: 7 },
      { id: 'politics', label: 'Politics', unit: 'market', min_days: 7 },
      { id: 'soccer', label: 'Soccer', unit: 'market', min_days: 7, aliases: ['premier-league', 'epl'] }] }),
    sessions: async () => (gone.has(SID) ? [] : [{ id: SID, title: sample.runs[0][0].title, created: Date.now() / 1000 - 3600, sample: true, wallet: null, name: null, market: 'btc-updown-15m' }]),
    remove: async id => { gone.add(id); return { deleted: true }; },
    restore: async id => { gone.delete(id); return { deleted: false }; },
    // the wallet field's list, as /api/research/suggestions answered on 16 Nov (Politics from Signals' Leaderboard;
    // the 15-minute pair are the sample traders, with Polymarket's 30-day crypto figures)
    suggestions: async () => ({ ready: true, built_at: 1794800000, types: [
      { id: 'btc-updown-15m', label: 'BTC Up or Down 15m', wallets: [
        { wallet: '0x329df14a9e177b5bade2228b9062265697a5b047', name: 'HuskyTrade', bot: null, category: 'Crypto', rank: null, profit_30d: 14778, traded_30d: 966691 },
        { wallet: '0xbdaacd345fec209cd09d933e62f92e8b530afd60', name: 'the.prod.dt', bot: null, category: 'Crypto', rank: null, profit_30d: -33531, traded_30d: 3952450 }] },
      { id: 'politics', label: 'Politics', wallets: [
        { wallet: '0xc301c1e034e71e1a6ce9684f029c4674a00466aa', name: 'Contestable-Parfait', bot: 1, category: 'Politics', rank: 1, profit_30d: 539553, traded_30d: 6185629 },
        { wallet: '0x23d81ba9371e576015c1e562db09c689f56b0288', name: 'flawfence', bot: 0, category: 'Politics', rank: 2, profit_30d: 493257, traded_30d: 1586361 },
        { wallet: '0x94c4fe3b18435aa92024c7c1589537fcda3f43ca', name: 'Railcool', bot: 0, category: 'Politics', rank: 3, profit_30d: 398290, traded_30d: 134743 }] }] }),
    create: async () => SID,
    session: async () => ({ id: SID, title: sample.runs[0][0].title, running, events: [...log] }),
    ask: async (id, question, context) => {
      if (running) throw Object.assign(new Error('A breakdown of yours is still running. Wait for it to finish.'), { status: 409 });
      if (!log.length) { play(sample.runs[0]); return { started: true, after: -1 }; }
      asked += 1;
      // context.answer: in fixtures mode the page works out a pointed question's answer from the window itself
      const { answer, ...ctx } = context || {};
      const recorded = sample.asks[question];
      const ev = [{ type: 'ask.started', ask_id: asked, text: question, context: context ? ctx : null }];
      if (answer) ev.push({ type: 'answer.progress', ask_id: asked, text: 'Reading that part of the window.' }, { type: 'answer.card', ask_id: asked, ...answer }, { type: 'done' });
      else if (recorded) ev.push(...recorded.map(e => ({ ...e, ask_id: e.ask_id ?? asked })));
      else ev.push({ type: 'answer.card', ask_id: asked, text: 'In the sample only the suggested questions have recorded answers. Click a buy on the chart and choose "Why here?", or pick a suggestion.', number_check: { passed: true, flagged: {} }, fixtures_note: true }, { type: 'done' });
      const after = log.length - 1;
      play(ev);
      return { started: true, after };
    },
    plan: async (id, planId, action, text) => {
      push({ type: 'plan.answered', plan_id: planId, action, text: text || null, run: null });
      if (action === 'approve' && planId === 'plan-1') { play(sample.runs[1]); return { started: true }; }
      if (action === 'approve') { play([{ type: 'ask.started', ask_id: ++asked, text: 'Start', context: { plan_id: planId } }, { type: 'notice', text: 'There are no more recorded windows, so the sample stops here. With the service, this plan would run now.' }, { type: 'done' }]); return { started: true }; }
      play([{ type: 'notice', text: 'Tell me what to change, for example "only 9 Nov" or "include October". I\'ll redo the plan before anything runs.' }]);
      return { started: false };
    },
    proposal: async (id, proposalId, action) => {
      push({ type: 'proposal.answered', proposal_id: proposalId, action, run: null });
      if (action !== 'accept') return { started: false };
      const q = 'Read every BTC 15-minute window it traded on 9 Nov';
      asked += 1;
      play([{ type: 'ask.started', ask_id: asked, text: q, context: { proposal_id: proposalId } }, ...sample.asks[q].map(e => ({ ...e, ask_id: asked }))]);
      return { started: true };
    },
    windows: async () => ({ windows, coverage: sample.runs[1].find(e => e.type === 'coverage').per_source }),
    window: async (id, slug) => (await fetch(`${base}window.ready.${slug}.json`)).json(),
    summaryOf: slug => windows.find(w => w.window_id === slug),
    follow: async (id, after, onEvent, signal) => {
      let at = after;
      while (!signal.aborted) {
        while (at < log.length - 1) { at += 1; onEvent(log[at]); }
        await new Promise(r => { wake = r; signal.addEventListener('abort', r, { once: true }); });
      }
    },
  };
}
