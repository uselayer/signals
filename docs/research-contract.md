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
| `GET /api/research/sessions` | yours → `{sessions: [{id, created, title, running?, progress?}]}`; a running one has `running: true` and `progress {started_at, typical_s, limit_s, steps?, done?, step?}` (steps only for a Started plan, counted from `step.status`) |
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
- `ask.started` `{ask_id, text, context, started_at, limit_s, typical_s}`: each question or Start. `started_at`
  (unix seconds, the server's clock) is what the page's timer counts from, so a reload keeps counting; `limit_s` is
  the run's time limit (`RESEARCH_MAX_SECONDS`); `typical_s` is how long runs of the same kind (a Start, or any other
  question) usually take: the median seconds of the latest 20 that ran to their end, once there are 5
  (`Store.typical_seconds`), else null. The page shows "about N min left" only from `typical_s`; past it, or without
  one, it says when the limit stops the run (`runClock` in `static/js/store.js`).
- `plan.proposed` `{plan_id, ask_id, title, scope: {wallet, family, from, to}, steps: [{id, title, source, estimate_s}],
  scope_options: [{id, text}], estimate_usd, estimate_s, needs_approval: true}`. Every new investigation shows its plan and waits;
  a follow-up that widens the scope (more windows, a longer range, another wallet) does too. The run ends after it.
  `estimate_usd` is the server's, never the agent's: the median `cost_usd` of the latest 20 Starts that ran to their
  end (an answer, or the cost or time limit), once there are 5 (`Store.start_cost`); null before, and the page then
  shows only the time. The plan's `estimate_s` is the same for time (`Store.typical_seconds` of Starts); null before,
  and the page then sums the steps' own `estimate_s`.
- `step.status` `{step_id, status: queued|running|done|warning|failed, progress: {done, total}|null, summary,
  warnings: [{kind, text, window_ids}]}`
- `tool.call` `{id, tool, args, started_at}` and `tool.result` `{id, tool, ok, rows, limit_hit, ms, summary}`: the
  activity log. Code runs are `tool: "code"` with `args.code`, and their result carries `stdout` (cut at 4,000
  characters, `cut`), `stderr`, `return_code`. `limit_hit` true means a wallet's history is partial. `summary` is
  the tool's own short figures, an object whose keys depend on the tool (`wallet_trades` `{rows, windows,
  complete, limit_hit, ms}`, `finding` `{finding_id}`, `step_status` `{step_id, status}`, `propose_plan` `{steps}`,
  a failure `{error}`…); the page puts it in words (`resultText` in `static/js/store.js`), never prints the object.
- `answer.progress` `{ask_id, text}`: the agent's notes between steps.

### Data the workspace draws
- `coverage` `{per_source: {windows, chainlink: {complete, total}, book: {complete, total}, outage: {windows}},
  windows: [window coverage]}`
- `window.summary` (a tile) `{window_id, start, end, result, price_to_beat, entries: [{t, side, action}],
  first_entry_s, shares: {up, down}, cost, sold_for, payout, profit, profit_note, spark: [{t, p}],
  coverage: {chainlink, book, outage}}`. `cost`/`sold_for` are the fills' `usd`; `payout` is $1 per share held of the
  winning side at the end; merges and redemptions aren't in the fills (`profit_note`). A tile counts the whole
  window: every fill of the wallet's in it, pre-open buys included (read from 30 minutes before it opens). On Start
  the scope's tiles are the windows that start in it (`from` <= start < `to`), so 05:30–06:45 is 05:30 to 06:30 and
  never the 06:45 window, even when a fill bought into it before 06:45. A window a read only cut through (the agent's
  own range, say) is read again whole before it gets a tile (`fills_complete` in the store).
- `window.ready` (a replay) `{window_id, start, end, axis: {from, to}, title, price_to_beat, final_price, result,
  binance: [{t, p}], binance_at_start, chainlink: [{t, p}]|null, units: {binance: "USDT", chainlink: "USD",
  price_to_beat: "USD, Chainlink's 60-second average"}, up: [{t, bid, ask}], down: [{t, bid, ask}], minute_fallback:
  {up: [{t, p}], down: [{t, p}]}|null, trades: [{trade_id, t, side, action, shares, price, usd, paid_ask, liquidity,
  pre_open}], position: [{t, up, down}], tags, coverage}`
  - `axis` starts 30 s before the earlier of the window's start and the first fill (at most 30 min early).
  - `up`/`down`: best bid and ask every second, carried forward from each recorded change; empty without a recorded
    book, and then `minute_fallback` has Polymarket's ~1-minute prices.
  - `chainlink`: only for windows from 10 Nov 2026 05:27 UTC (when recording began); before that `null`, and the
    window's `price_to_beat` and `result` are all there is ("start_and_result"). When Layer hasn't built the window's
    file yet, Chainlink comes from Layer's raw recording of the live feed (`coverage.chainlink_source`).
  - `coverage.book_status`: `recorded` (the book is drawn), `not_processed` (Layer recorded it but hasn't built
    the window yet: say "the order book isn't processed yet") or `not_recorded` (before 2 Nov 17:00 UTC).
  - **Units:** Binance is BTC in USDT (Tether); Chainlink and the price to beat are US dollars, and the price to beat
    is a 60-second average. They sit about 0.1% apart, so never draw or compare Binance against the price to beat as
    if they were the same line. Without Chainlink, show Binance lined up to its own value at the start
    (`binance_at_start`), and say so whenever both appear.
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
- `finding.added` `{finding_id, ask_id, kind: pattern|read|unsure|data|change, label: observed|inferred, title,
  stat: {count, out_of, unit, text}|null, rule, evidence: {supporting_window_ids, against_window_ids, trade_ids},
  example: {window_id, step_index}|null, based_on: [finding_id], would_change_mind, number_check, counts}`.
  `counts` is false when its numbers didn't check out: it's left out of the Findings total and nothing inferred can
  rest on it. Evidence ids are checked against the investigation's own fills and windows.
- `finding.updated`: the same fields plus `previous` `{title, stat, rule, label, number_check}` and `history`
  (every earlier version). "Ask the agent to fix it" = an ask with `{finding_id}`; the agent rewrites the card from
  the data and it comes back as `finding.updated`.
- `answer.card` `{ask_id, label, observed: [text], inferred: [text], annotations: [{window_id, kind, t0, t1, panel,
  label}], focus, finding_ids, number_check}`, the answer to a question; a `view.focus` comes first when `focus` is
  set. The run ends on it. Fallback when the agent writes plain text instead: `{ask_id, text, truncated,
  number_check}` (flagged field `text`).
- `GET /api/research/sessions/{id}/findings` → `{findings: [latest version each], counted}`.

### Number check
Text the agent writes (walkthrough steps, answers, later findings) is checked when written: every number must match a
value in a tool result or the agent's printed output (rounded; $, k/M; ¢ and % as ×100 of a share, never a dollar
amount). A first miss goes back to the agent to fix; a second is shown flagged:
`number_check: {passed, flagged: {<field>: [{value_text, start, end, data_value|null}]}}`. Field names: a finding's
`title`, `stat` (its text, then its count and out_of), `rule`, `would_change_mind`; a walkthrough step's own
`number_check` (one per step) `title`, `observed`, `inferred`; a structured `answer.card`'s `label`, `observed 1…`,
`inferred 1…` (the line's index, from 1); a plain-text `answer.card`'s `text`. `start`/`end` are
character offsets into that field's text; `data_value` is the data's closest value (within 10%), or null. Times,
dates, wallet addresses and slugs aren't checked.

### Run end
- `notice` `{text}` (e.g. an expired working state being rebuilt), `error` `{message}`,
  `usage` `{input_tokens, output_tokens, cache_read_input_tokens, cache_creation_input_tokens, token_usd, code_runs,
  container_s, container_usd, cost_usd, rounds, tool_calls, seconds, phases: {plan, first_tile, tiles_done,
  first_finding, walkthrough, answer}}` (seconds from the run's start; a phase that didn't happen is absent), then
  `done`.
- A question has a time budget (`RESEARCH_MAX_SECONDS`, 600 by default) besides its cost cap. At 80% the agent is
  told to answer from the findings so far. A run that stops (time, steps, money, an error) with findings but no
  answer ends on an `answer.card` built from the findings that counted, with `partial: true`, then a `notice` saying
  why, never on an `error`. An `error` means there was nothing to show.
- The time budget is a wall clock (a watchdog in the service), not only checked between model rounds: a model
  request or a read that's blocked or slow still ends the run at the limit, the same way.
- A run the service stops (a deploy: SIGTERM) ends the same way, its findings kept, with the `notice` "This breakdown
  was interrupted by an update. Ask again to finish it." (also when there are no findings, then without a card), then
  `done`. A run the process died in before it could (killed, crashed) gets those events when the service next
  starts, so a reloaded breakdown never stays "Working". Asking again goes on in the same conversation; tool calls
  the cut-off run left unanswered are answered as not run.
- `GET /api/research/health` `{ok, model_key, running}`: `running` is how many breakdowns are going. Deploy only at
  0 (README, "Hosting Breakdowns").

## Client calls
- **Ask** `POST /api/research/sessions/{id}/ask` `{question, context?, origin?}`. `context`: none, `{trade_id}`,
  `{trade_ids: [...]}` (a burst, up to 50), `{window_id, t}` (t in unix seconds), `{finding_id}` or
  `{finding_id, stat}`. The server reads what it points at from the
  investigation's data (the fill as drawn, or the prices, position and fills within 10 s at that moment) and gives
  the agent those facts with the question; 404 when it isn't in this investigation. `ask.started.context` echoes it.
  Follow-ups answer directly unless they widen the scope, which proposes a plan and waits.
- **Plan** `POST /api/research/sessions/{id}/plan` `{plan_id, action: approve|edit, text?, scope_option_ids?}` →
  202 and a run ("Start", or "change the plan: …", which re-plans). 404 unknown plan, 409 already answered, 400 an
  edit with no text. Emits `plan.answered` `{plan_id, action, scope_option_ids, text}`.
- **Proposal** `POST /api/research/sessions/{id}/proposals/{proposal_id}` `{action: accept|decline}`: accept → 202
  and a run; decline → 200 `{started: false}`, no run. 409 when already answered. Emits `proposal.answered`
  `{proposal_id, action}`.
- 409 also means one of your runs is still going; 429 that research is busy.
