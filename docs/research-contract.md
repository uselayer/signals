# Research: the UI-to-agent contract

The research service (`signals/research/`) and the research page (`signals/research/static/`, at `/research`) speak
through this contract. It is the single source of truth for shapes: change it here first, and tell the page's
builder before the change lands. Events carry `v` (the event version, now **2**); a page that sees a higher `v`
than it knows should say it needs a reload.

Principle: **the agent decides what to show; the server builds the data.** Series, fills, positions and coverage
are assembled by the server from the same reads the agent's tools made, so no drawn number passes through the model.

## Transport

| Route | |
|---|---|
| `GET /api/research/config` | `{clerk_key, event_version}` |
| `POST /api/research/sessions` `{title?}` | a new investigation → `{id}` |
| `GET /api/research/sessions` | yours → `{sessions: [{id, created, title}]}` |
| `GET /api/research/sessions/{id}` | `{id, title, created, running, events}` (every event so far) |
| `POST /api/research/sessions/{id}/ask` `{question}` | starts a run → 202 `{started, after}`; 409 one of yours is running; 429 busy |
| `GET /api/research/sessions/{id}/events?after=N` | server-sent events after `seq` N, then live until `done` |
| `GET /api/research/sessions/{id}/windows` | `{windows: [window.summary], coverage: per_source}` |
| `GET /api/research/sessions/{id}/windows/{window_id}` | `window.ready` (kept, else built now) |
| `GET /api/research/charts/{id}` | a later "+ New view" chart |

- **Auth:** Clerk's session token as `Authorization: Bearer …` on every route (the engine's check). Read the stream
  with `fetch()` and that header, never a token in the URL (URLs land in proxy logs).
- **Stream:** each event is `id: <seq>` + `data: <json>`; the JSON also has `seq`, monotonic per investigation.
  Reconnect with `after` = the last `seq`. A keep-alive comment (`: still working`) comes about every 15 s.
- Every event has `type`, `v`, `run` (the run it belongs to: one question or one Start).

## Ids (stable across runs)

- Investigation: `id` (the session id).
- Window: its slug, `btc-updown-15m-<start unix s>`.
- **Trade:** `trade_id` = the first 12 hex characters of
  `sha1("{tx}|{asset}|{action}|{price:.4f}|{size:.6f}|{unix seconds}")`: tx = transaction hash, asset = the outcome
  token id, action = `buy`|`sell`, price in dollars per share, size in shares. Python: `signals.research.data.trade_id`.
  Layer's window reader computes the same id when it marks a wallet's fills.
- Plan: `plan-<run>`. Proposal: `P<n>`. Finding (M4): `F<n>`. Ask: the run number.

## Events

### Start and plan
- `investigation.created` `{id, title, question, subject: {wallet|null, name|null}, scope: null, origin}`: the
  first question of an investigation.
- `ask.started` `{ask_id, text, context}`: each question or Start.
- `plan.proposed` `{plan_id, ask_id, title, scope: {wallet, family, from, to}, steps: [{id, title, source, estimate_s}],
  scope_options: [{id, text}], estimate_usd, needs_approval: true}`. Every new investigation shows its plan and waits;
  a follow-up that widens the scope (more windows, a longer range, another wallet) does too. The run ends after it.
- `step.status` `{step_id, status: queued|running|done|warning|failed, progress: {done, total}|null, summary,
  warnings: [{kind, text, window_ids}]}`
- `tool.call` `{id, tool, args, started_at}` and `tool.result` `{id, tool, ok, rows, limit_hit, ms, summary}`: the
  activity log. Code runs are `tool: "code"` with `args.code`, and their result carries `stdout` (cut at 4,000
  characters, `cut`), `stderr`, `return_code`. `limit_hit` true means a wallet's history is partial.
- `answer.progress` `{ask_id, text}`: the agent's notes between steps.

### Data the workspace draws
- `coverage` `{per_source: {windows, chainlink: {complete, total}, book: {complete, total}, outage: {windows}},
  windows: [window coverage]}`
- `window.summary` (a tile) `{window_id, start, end, result, price_to_beat, entries: [{t, side, action}],
  first_entry_s, shares: {up, down}, cost, sold_for, payout, profit, profit_note, spark: [{t, p}],
  coverage: {chainlink, book, outage}}`. `cost`/`sold_for` are the fills' `usd`; `payout` is $1 per share held of the
  winning side at the end; merges and redemptions aren't in the fills (`profit_note`).
- `window.ready` (a replay) `{window_id, start, end, axis: {from, to}, title, price_to_beat, final_price, result,
  binance: [{t, p}], chainlink: [{t, p}]|null, up: [{t, bid, ask}], down: [{t, bid, ask}], minute_fallback:
  {up: [{t, p}], down: [{t, p}]}|null, trades: [{trade_id, t, side, action, shares, price, usd, paid_ask, liquidity,
  pre_open}], position: [{t, up, down}], tags, coverage}`
  - `axis` starts 30 s before the earlier of the window's start and the first fill (at most 30 min early).
  - `up`/`down`: best bid and ask every second, carried forward from each recorded change; empty without a recorded
    book, and then `minute_fallback` has Polymarket's ~1-minute prices.
  - `chainlink`: only for windows from 10 Nov 2026 05:27 UTC (when recording began); before that `null`, and the
    window's `price_to_beat` and `result` are all there is ("start_and_result").
  - `paid_ask`: a buy at or above the recorded best ask just before the trade reached the stream; `false` = below
    it (its resting order filled); `null` = not checked (no book, not on the tape, inside a recording gap, or a sell).
    `liquidity` says the same in words: `taker`|`maker`|`null`.
  - `pre_open`: the fill came before the window opened.
  - Fills are the wallet's own (from its trade history), never matched off the market tape (which lists takers only).
- Window `coverage` `{window_id, source, chainlink: full|start_and_result, book, missing_seconds: [[start, length]],
  lost: [{from, to, why}], seconds_without_book, market_trades: {recorded, polymarket, pct}|{read, complete},
  outage, reasons, notes, pre_open_entries: {fills, first_s_before, before_axis}}`. `why` is plain English for the
  chart's hatching.
- `walkthrough.ready` `{window_id, steps: [{index, t, title, observed, inferred|null, trade_ids, annotations: [{kind:
  point|span|region, t0, t1, panel: btc|prices|position, label}], number_check}]}`
- `view.focus` `{stage: windows|window|trades, window_id, step_index, highlight_window_ids, label}`: the agent moves
  the workspace. A `window.ready` for that window comes first in the same run.
- `chart` `{chart_id, title, caption, spec}`: Vega-Lite, for the later "+ New view" only.

### Evidence
- `proposal` `{proposal_id, ask_id, text, accept_label}`
- `answer.card` `{ask_id, text, truncated, number_check}`: the answer to a question (M4 makes it structured:
  label, observed lines, inferred lines, annotations, focus, finding ids).
- `finding.added` / `finding.updated` (M4).

### Number check
Text the agent writes (walkthrough steps, answers, later findings) is checked when written: every number must match a
value in a tool result or the agent's printed output (rounded; $, k/M; ¢ and % as ×100 of a share, never a dollar
amount). A first miss goes back to the agent to fix; a second is shown flagged:
`number_check: {passed, flagged: {<field>: [{value_text, start, end, data_value|null}]}}`. `start`/`end` are
character offsets into that field's text; `data_value` is the data's closest value (within 10%), or null. Times,
dates, wallet addresses and slugs aren't checked.

### Run end
- `notice` `{text}` (e.g. an expired working state being rebuilt), `error` `{message}`,
  `usage` `{input_tokens, output_tokens, cache_read_input_tokens, cache_creation_input_tokens, token_usd, code_runs,
  container_s, container_usd, cost_usd, rounds, tool_calls}`, then `done`.

## Client calls (M3, coming)
- `plan.approve` / `plan.edit` `{plan_id, text?, scope_option_ids?}` → a new run.
- `proposal.accept` / `proposal.decline` `{proposal_id}`: decline starts no run.
- `ask` `{question, context: null | {trade_id} | {window_id, t} | {finding_id} | {finding_id, stat}}`.
