// PostHog on Breakdowns (README, "Analytics"): the main page's setup (signals/static/index.html startAnalytics), off
// unless the research service has the project key (/api/research/config posthog_key). Page views (each hash route),
// clicks, scroll depth and session replay, loaded through /lyr on our domain (web/vercel.json) so ad blockers don't
// drop it; the person is known by their Clerk user id only, the same person as on the rest of Signals.
//
// The person's question is their own words: never in an event. Replays mask every field and the text that shows a
// question (class ph-sensitive), and block the parts that also carry one in a tooltip; autocapture leaves out the text
// and attributes of anything ph-sensitive; the tab's title (it names the breakdown) is dropped from every event; and
// app.js takes ?q= (the main site's ask bar) out of the address before this starts.
const CLERK_UI = ['[class^="cl-"]', '[class*=" cl-"]'];
export const QUESTION_TEXT = '.ph-sensitive';
export const QUESTION_TOOLTIPS = ['.brow > a', '.qrun', '.asked'];
export const OPTIONS = {
  api_host: '/lyr', ui_host: 'https://us.posthog.com', defaults: '2026-05-30',
  capture_pageview: { path: true, hash: true },
  session_recording: {
    maskAllInputs: true,
    maskTextSelector: [...CLERK_UI, QUESTION_TEXT, 'title'].join(', '),
    blockSelector: [...CLERK_UI.map(c => `${c} img`), ...QUESTION_TOOLTIPS].join(', '),
  },
  before_send: e => scrub(e),
};

// Every event, before it leaves: no page title.
export function scrub(e) {
  if (e && e.properties) { delete e.properties.title; delete e.properties.$title; }
  return e;
}

// 'off' (no key, blocked or down), 'loading', 'on'. Events while it loads wait (a few), then go; off drops them.
let state = 'off', who = null, told = null, waiting = [];
const WAIT_MAX = 20;

function loadScript(src) {
  return new Promise((ok, fail) => {
    const s = document.createElement('script');
    Object.assign(s, { src, async: true, onload: ok, onerror: fail });
    document.head.appendChild(s);
  });
}

export function startAnalytics(key, load = loadScript) {
  if (!key || state !== 'off') return;
  state = 'loading';
  load('/lyr/static/array.js').then(() => {
    window.posthog.init(key, OPTIONS);
    state = 'on';
    tellWho();
    for (const [event, props] of waiting.splice(0)) window.posthog.capture(event, props);
  }).catch(() => { state = 'off'; waiting = []; }); // blocked or down: the page works the same without it
}

// Signing in links this browser's visits to the account (Clerk user id); signing out starts a new anonymous visitor.
export function accountIs(uid) { who = uid || null; if (state === 'on') tellWho(); }
function tellWho() {
  if (who && who !== told) { window.posthog.identify(who); told = who; }
  else if (!who && told) { window.posthog.reset(); told = null; }
}

// A named event (README lists them): what page views and clicks can't say. Facts about the breakdown only (its id,
// market, plan cost, how it was started), never the question or anything about the person.
export function track(event, props) {
  if (state === 'on') window.posthog.capture(event, props);
  else if (state === 'loading' && waiting.length < WAIT_MAX) waiting.push([event, props]);
}

// For tests: back to off.
export function _reset() { state = 'off'; who = null; told = null; waiting = []; }
