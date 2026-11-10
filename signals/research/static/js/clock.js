// A working run's clock, shown in the agent's header and on the plan while it runs.
import { html, useState, useEffect } from '../vendor/htm-preact-3.1.1.module.js';
import { runClock } from './store.js';

// A working run's time so far and what's left ("1:42 · about 3 min left"), ticking each second, with a thin bar.
export function RunClock({ inv, bar = true }) {
  const [, tick] = useState(0);
  useEffect(() => { if (!inv.running) return undefined; const t = setInterval(() => tick(x => x + 1), 1000); return () => clearInterval(t); }, [inv.running]);
  const c = runClock(inv);
  if (!c) return null;
  return html`<span class="runclock" role="timer" aria-live="off"><span class="el">${c.elapsed}</span>${c.left && ` · ${c.left}`}
    ${bar && c.frac != null && html`<span class="bar" aria-hidden="true"><i style=${`width:${Math.round(100 * c.frac)}%`}></i></span>`}</span>`;
}
