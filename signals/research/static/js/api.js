// Talking to the research service (/api/research/*, signals/research/server.py). Signed in with Clerk exactly as the
// engine's page is (same domain, same publishable key from /api/research/config); every call sends Clerk's
// short-lived session token in the Authorization header. The event stream is read with fetch(), never EventSource,
// so the token stays in a header and out of URLs (and so out of proxy logs).

let clerkReady = null;

function loadScript(src, attrs = {}) {
  return new Promise((ok, fail) => {
    const s = document.createElement('script');
    Object.assign(s, { src, async: true, crossOrigin: 'anonymous', onload: ok, onerror: fail });
    for (const [k, v] of Object.entries(attrs)) s.setAttribute(k, v);
    document.head.appendChild(s);
  });
}

// Clerk's frontend API host is inside the publishable key (as the engine's startAuth reads it)
function frontendApi(key) {
  const m = /^pk_(test|live)_(.+)$/.exec(key || '');
  if (!m) return null;
  try { const h = atob(m[2].replace(/-/g, '+').replace(/_/g, '/')).replace(/\$$/, ''); return /^[a-z0-9.-]+$/i.test(h) ? h : null; } catch { return null; }
}

export async function startAuth(key) {
  const fapi = frontendApi(key);
  if (!fapi) return { signedIn: true, local: true }; // the service runs without Clerk only locally
  if (!clerkReady) clerkReady = (async () => {
    await loadScript(`https://${fapi}/npm/@clerk/ui@1/dist/ui.browser.js`);
    await loadScript(`https://${fapi}/npm/@clerk/clerk-js@6/dist/clerk.browser.js`, { 'data-clerk-publishable-key': key });
    await window.Clerk.load({ ui: { ClerkUI: window.__internal_ClerkUICtor } });
  })();
  await clerkReady;
  return { signedIn: !!window.Clerk.isSignedIn, local: false };
}
export const openSignIn = () => window.Clerk && window.Clerk.openSignIn();
export const mountUser = el => { if (window.Clerk && window.Clerk.isSignedIn && el && !el.dataset.user) { el.dataset.user = '1'; window.Clerk.mountUserButton(el); } };

async function headers(extra = {}) {
  const h = { ...extra };
  const t = window.Clerk && window.Clerk.session ? await window.Clerk.session.getToken().catch(() => null) : null;
  if (t) h.authorization = `Bearer ${t}`;
  return h;
}

export class ApiError extends Error { constructor(status, message) { super(message); this.status = status; } }

async function call(method, path, body) {
  const res = await fetch(`/api/research${path}`, {
    method, headers: await headers(body ? { 'content-type': 'application/json' } : {}), body: body ? JSON.stringify(body) : undefined,
  });
  if (!res.ok) {
    let msg = `The research service answered ${res.status}.`;
    try { const j = await res.json(); if (j.detail) msg = typeof j.detail === 'string' ? j.detail : msg; } catch { /* not JSON */ }
    throw new ApiError(res.status, msg);
  }
  return res.status === 204 ? null : res.json();
}

export const live = {
  config: () => fetch('/api/research/config').then(r => (r.ok ? r.json() : Promise.reject(new ApiError(r.status, 'No research service here.')))),
  sessions: () => call('GET', '/sessions').then(j => j.sessions || []),
  create: title => call('POST', '/sessions', { title }).then(j => j.id),
  session: id => call('GET', `/sessions/${id}`),
  ask: (id, question, context, origin) => call('POST', `/sessions/${id}/ask`, { question, context: context || null, origin: origin || null }),
  // answers to a plan and to a proposal (docs/research-contract.md "Client calls"): approve/edit and accept start a run
  plan: (id, planId, action, text, scopeOptionIds) => call('POST', `/sessions/${id}/plan`, { plan_id: planId, action, text: text || null, scope_option_ids: scopeOptionIds || [] }),
  proposal: (id, proposalId, action) => call('POST', `/sessions/${id}/proposals/${proposalId}`, { action }),
  windows: id => call('GET', `/sessions/${id}/windows`),
  window: (id, slug) => call('GET', `/sessions/${id}/windows/${slug}`),
  follow: (id, after, onEvent, signal) => follow(id, after, onEvent, signal),
};

// text/event-stream over fetch: `id:` and `data:` lines, a blank line ends an event, `:` lines are keep-alives.
// Reconnects after a dropped connection from the last event seen; stops when the server ends the stream (the run
// is done) or the page aborts.
async function follow(id, after, onEvent, signal) {
  let last = after, tries = 0;
  while (!signal.aborted) {
    try {
      const res = await fetch(`/api/research/sessions/${id}/events?after=${last}`, { headers: await headers({ accept: 'text/event-stream' }), signal });
      if (!res.ok) throw new ApiError(res.status, `The event stream answered ${res.status}.`);
      tries = 0;
      const reader = res.body.getReader(), dec = new TextDecoder();
      let buf = '';
      for (;;) {
        const { value, done } = await reader.read();
        if (done) return; // the run finished and the server closed the stream
        buf += dec.decode(value, { stream: true });
        let cut;
        while ((cut = buf.indexOf('\n\n')) >= 0) {
          const block = buf.slice(0, cut); buf = buf.slice(cut + 2);
          let data = '';
          for (const line of block.split('\n')) {
            if (line.startsWith('data:')) data += line.slice(5).trimStart();
            else if (line.startsWith('id:')) last = Number(line.slice(3).trim());
          }
          if (data) { const e = JSON.parse(data); if (e.seq != null) last = e.seq; onEvent(e); }
        }
      }
    } catch (err) {
      if (signal.aborted) return;
      if (err instanceof ApiError && (err.status === 401 || err.status === 404)) throw err;
      tries += 1;
      await new Promise(r => setTimeout(r, Math.min(15000, 1000 * 2 ** Math.min(tries, 4))));
    }
  }
}
