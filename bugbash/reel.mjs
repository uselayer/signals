#!/usr/bin/env node
// reel.mjs: turn bug-bash run folders into one page of videos and findings.
//
//   node reel.mjs <out dir> <run dir> [<run dir> ...] [--title "..."] [--triage triage.json]
//
// Each run dir holds video.mp4 (or .webm) and bugs.json from bb.mjs. Writes <out>/index.html and <out>/videos/.
// triage.json (optional) labels bugs after a person or Claude checked them:
//   { "<feature>": { "<bug number, 1-based>": { "label": "confirmed|likely|check|design|brief", "note": "..." } } }
import fs from 'node:fs';
import path from 'node:path';

const argv = process.argv.slice(2);
const opt = (n) => { const i = argv.indexOf(n); if (i < 0) return null; const v = argv[i + 1]; argv.splice(i, 2); return v; };
const title = opt('--title');
const triageFile = opt('--triage');
const [out, ...dirs] = argv;
if (!out || !dirs.length) { console.error('usage: node reel.mjs <out dir> <run dir>... [--title ..] [--triage triage.json]'); process.exit(1); }
const triage = triageFile ? JSON.parse(fs.readFileSync(triageFile, 'utf8')) : {};
fs.mkdirSync(path.join(out, 'videos'), { recursive: true });

const esc = (s) => String(s ?? '').replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
const secs = (mmss) => { const [m, s] = String(mmss).split(':').map(Number); return m * 60 + s; };
const LABELS = { confirmed: ['c-real', 'Confirmed'], likely: ['c-likely', 'Likely real'], check: ['c-check', 'Worth checking'], design: ['c-design', 'By design'], brief: ['c-design', 'Brief mistake'] };
const counts = { flagged: 0, confirmed: 0, likely: 0, check: 0, design: 0, untriaged: 0 };
let when = '';

const runs = dirs.map((dir) => {
  const data = JSON.parse(fs.readFileSync(path.join(dir, 'bugs.json'), 'utf8'));
  const feature = data.feature;
  const vid = ['video.mp4', 'video.webm'].find((f) => fs.existsSync(path.join(dir, f)));
  const vname = `${feature}${path.extname(vid || '.mp4')}`;
  if (vid) fs.copyFileSync(path.join(dir, vid), path.join(out, 'videos', vname));
  const report = fs.existsSync(path.join(dir, 'report.md')) ? fs.readFileSync(path.join(dir, 'report.md'), 'utf8') : '';
  const long = (report.match(/· (\d\d:\d\d) long/) || [])[1] || '';
  when = when || (report.match(/long · (\S+)/) || [])[1] || '';
  const tri = triage[feature] || {};
  const bugs = data.bugs.map((b, i) => {
    const t = tri[String(i + 1)] || {};
    counts.flagged += 1;
    const key = t.label === 'brief' ? 'design' : t.label;
    if (key && key in counts) counts[key] += 1; else counts.untriaged += 1;
    return { ...b, label: t.label, note: t.note };
  });
  const order = { confirmed: 0, likely: 1, check: 2, undefined: 3, design: 4, brief: 5 };
  bugs.sort((a, b) => (order[a.label] ?? 3) - (order[b.label] ?? 3));
  return { feature, mode: data.mode, vname, long, bugs, passed: data.passed || [], id: `v-${feature}` };
});

const chip = (cls, text) => `<span class="chip ${cls}">${esc(text)}</span>`;
const tally = [chip('c-plain', `${counts.flagged} flagged`),
  counts.confirmed && chip('c-real', `${counts.confirmed} confirmed`), counts.likely && chip('c-likely', `${counts.likely} likely real`),
  counts.check && chip('c-check', `${counts.check} worth checking`), counts.design && chip('c-design', `${counts.design} not bugs`),
  counts.untriaged && chip('c-plain', `${counts.untriaged} not triaged yet`)].filter(Boolean).join('\n    ');

const section = (r) => `<section class="run">
  <div class="vid${r.mode === 'phone' ? ' phone' : ''}"><h2>${esc(r.feature.replace(/-/g, ' '))} <small>${r.mode === 'phone' ? '390 × 844' : 'desktop'}${r.long ? ` · ${r.long.replace(/^0/, '')}` : ''}</small></h2>
    <video id="${r.id}" src="videos/${esc(r.vname)}" controls muted playsinline preload="metadata"></video></div>
  <div class="log">
${r.bugs.length ? r.bugs.map((b) => `    <div class="bug"><button class="t" data-v="${r.id}" data-s="${secs(b.at)}">${esc(b.at.replace(/^0/, ''))}</button><b>${esc(b.title)}</b><p>${esc(b.note || b.details)}</p>${b.label ? chip(...LABELS[b.label]) : ''}</div>`).join('\n') : '    <p class="none">No bugs found.</p>'}
    <p class="passed">✓ ${r.passed.length} check${r.passed.length === 1 ? '' : 's'} passed${r.passed.length ? `: ${esc(r.passed.map((p) => p.what).join('; '))}` : ''}.</p>
  </div>
</section>`;

const css = fs.readFileSync(new URL('./reel.css', import.meta.url), 'utf8');
const heading = title || `${runs.length} agent${runs.length === 1 ? '' : 's'}, ${runs.length} cloud computer${runs.length === 1 ? '' : 's'}, one pass over the site`;
const html = `<title>Signals Bug Bash Reel</title>
<meta name="claude:viewport-fit-sides" content="cover">
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@500;600;700&family=Inter:wght@400;500;600&family=JetBrains+Mono:wght@500&display=swap">
<style>
${css}</style>

<div class="wrap">
<header>
  <div class="eyebrow">Signals · agent bug bash${when ? ` · ${esc(when.slice(0, 16).replace('T', ' '))} UTC` : ''}</div>
  <h1>${esc(heading)}</h1>
  <p class="lede">Each agent tested one feature on its own cloud machine in a filmed browser, signed out and spending nothing. The caption bar shows what it is doing, the red dot is where it clicks and a red banner marks each bug. Click a time to jump the video there.</p>
  <div class="tally">
    ${tally}
  </div>
</header>

${runs.map(section).join('\n\n')}
</div>

<script>
document.querySelectorAll('.t').forEach(b=>b.addEventListener('click',()=>{
  const v=document.getElementById(b.dataset.v); if(!v) return;
  const s=Math.max(0,Number(b.dataset.s)-2);
  const go=()=>{v.currentTime=s; v.play().catch(()=>{});};
  if(v.readyState>=1) go(); else {v.addEventListener('loadedmetadata',go,{once:true}); v.load();}
  v.scrollIntoView({behavior:matchMedia('(prefers-reduced-motion: reduce)').matches?'auto':'smooth',block:'center'});
}));
</script>
`;
fs.writeFileSync(path.join(out, 'index.html'), html);
console.log(`wrote ${path.join(out, 'index.html')} (${runs.length} runs, ${counts.flagged} bugs, ${counts.untriaged} untriaged)`);
