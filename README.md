# Signals

See the traders on Polymarket: their track record, what they hold now and every trade they make, and what buying
the same thing would cost you right now. It's a leaderboard of facts, not picks: no tiers, no "recommended".

Signals places no orders. You buy on the exchange yourself. It's built on the [uselayer](https://uselayer.sh)
Python SDK (`client.whales`) and hosted at [usesignals.app](https://usesignals.app). The SDK calls behind each part
are listed on [Layer's Signals page](https://uselayer.sh/docs/signals).

## Run it locally

You need [uv](https://docs.astral.sh/uv/); it fetches Python 3.11+ if you don't have it.

```sh
git clone https://github.com/uselayer/signals
cd signals
uv sync
LAYER_API_KEY=lyr_... SIGNALS_EVALUATE=1 uv run signals
```

Then open http://127.0.0.1:8790. Data is kept in `~/.uselayer/signals`.

- **The Layer key is optional.** Without it everything works except the Kalshi and Polymarket US matches. Get one
  at [uselayer.sh](https://uselayer.sh).
- **`SIGNALS_EVALUATE=1` fills the leaderboard.** On a new machine Signals first finds wallets (Polymarket's
  leaderboards and busy markets), then reads each one's track record, a few reads per trader. The list grows over
  a few hours. Without it, only traders whose page you open get a record.
- **Signing in, alerts and the AI note are off** until their keys are set (see [Settings](#settings)). Without
  sign-in, nothing is gated, but you can't follow anyone, so the Watchlist and Following stay empty.

Tests: `uv run pytest -q`.

## What's on the page

Three tabs: **Feed**, **Watchlist** and **Traders**. Traders and trader pages need no account; the Feed and the
Watchlist need signing in. Signed out, you land on the Leaderboard, and the Watchlist page says what it does before
asking you to sign in. Your first Feed visit, once signed in, asks which markets interest you (Politics, Sports,
Crypto, Esports, or Skip for all). The choice is kept in your browser, and the Feed follows it.

### Traders: the Leaderboard

One list of every Polymarket trader with a buy in the last 30 days and at least 5 positions closed in 90 days. A
trader is listed only once every column has a figure. Each row shows:

- **Weeks up**: of the last 12, with a bar per week.
- **Trading profit** for the period, with profit per $ traded and how much they traded.
- **Trend**: their profit line over the period.
- **Win rate**: positions closed in profit (sold or settled), from 10 closed, with "pays X¢ on average" beside it.
  A price is the market's chance, so someone who pays 97¢ wins about 97% of the time just by buying.
- **Usual trade**: half the money they put in over 30 days went in trades this size or bigger, and how often they
  trade.

Sort by trading profit, profit per $ traded, win rate, volume or most weeks up, over 7D, 30D, 90D or All. Filter by
market (each trader's main category). Accounts with under 4 weeks of history are hidden unless you turn on **Show
new accounts**. Search by name or wallet; a wallet that isn't listed still opens its own page.

Records come from Polymarket's profit history, their positions closed and their latest trades, read again every 2
days; the top 300 by 30-day profit, each market's top 100 and everyone followed, every 4 hours. **Top profit** (linked at the foot) is Polymarket's own leaderboard.

### A trader's profile

Their realized profit and open profit (after fees), their wallet (cash plus open positions), weeks up and the
streak they're on, their worst drop from a high, win rate with the average price they paid, usual trade, a profit
chart (7D / 30D / 90D) and realized profit by category. A figure Signals can't give has no row; it never shows a
made-up number or $0.

Two tabs: **Positions**, one line per outcome with what they put in and what it's worth now (or what they got back,
once closed), and **Recent trades**, each buy and sell. **Follow** adds them to your Watchlist and alerts.

### Watchlist

Follow up to 20 traders: from their page, or with **+ Follow a trader** (paste a Polymarket profile link or wallet,
or type their username). Each one gets a card with their record, what they hold and their latest changes.

Signed out, the page says what you get (every trader you follow on a card, every change with the facts behind it,
baskets, Telegram) above **Sign in**; **+ Follow a trader** works there too, and it links an example watch page from
the top of the Leaderboard.

A trader's **watch page** (`#/watch/<wallet>`, no account needed) shows what they hold and every change over the
last 30 days: a new position, more bought, some sold, all sold. Pick one to see the facts behind it: their
position now, its size against their usual trade, their record in that category and the price now. It's worked out
from their last 500 trades and open positions.

With `OPENROUTER_API_KEY` set, one sentence written by AI (Claude Haiku 5.5) sits above the facts, labelled so.
Signals picks the facts that stand out and works out every figure; the AI only joins them. A sentence with a number
the facts don't have isn't shown, and when nothing stands out there's no sentence.

### Feed

A switch at the top:

- **Following** (the default): every trade from the traders you follow over the last 24 hours.
- **Top traders**: trades of $1,000 or more from the 100 traders with the most trading profit over 30 days.

One card per trade: the market, their pick, what they paid, the price now and how much they put in. "Only buys I
can still get into" keeps the ones priced between 5¢ below and 3¢ above what they paid. A trade at 2¢ or less, 98¢
or more, or one they no longer hold, shows as Won, Lost or Closed. **All big trades right now** (`#/big`, at the
foot) lists every Polymarket trade of $250 or more.

Followed traders are read every 30 seconds. Big trades come from Polymarket's feed of every trade, which runs 3–5
minutes behind. A trade's time is when it was made on Polymarket.

### Alerts on Telegram

"Connect Telegram" on a trader's page links your chat to the bot. You then get a message after a trader you follow
buys or sells: who, what, at what price, the price now, and how long before the alert they traded.

Signed out, Follow needs no account: it opens the bot, and Start there follows that trader from your chat with
alerts on. Connecting the same chat to an account later keeps those follows.

- Every trade by default. Per trader you can choose only trades over an amount, or one summary every 6 hours.
- Two or more followed traders buying the same outcome make one message, updated as more buy.
- Trades of $10,000 or more in the markets you picked alert you too, at most 5 a day.
- Following a very busy trader (over 20 alerts a day last week) says so first.
- At most 200 alerts a day. In the chat, `/list` shows who you follow and `/stop` turns alerts off.

### What buying now costs

Every trade has **Check your price**. Pick an amount and Signals prices it from the order book right now: what it
fills at (up to 3¢ above the cheapest price for sale), the fee, what's for sale within that limit, and what you get
if it wins. The trader's price is shown for context only. It's an estimate, not a guaranteed fill.

When Layer has a verified match for the market on **Kalshi**, the estimate is priced on Kalshi and **Buy on
Kalshi** comes first, with every way the two may pay out differently. When there's a verified match on
**Polymarket US**, the trade links to it too. Otherwise **Buy on Polymarket** opens the market there.

## Settings

All optional.

| Variable | What it does |
|---|---|
| `LAYER_API_KEY` | Finds the same market on Kalshi and Polymarket US. |
| `SIGNALS_PORT` | Port to serve on. Default `8790`. |
| `SIGNALS_STORE_DIR` | Where data is kept. Default `~/.uselayer/signals`. |
| `SIGNALS_EVALUATE` | `1` reads each found wallet's track record for the leaderboard. Off by default. |
| `SIGNALS_DIRECTORY` | `0` stops the daily search for new wallets. On by default. |
| `SIGNALS_BOARD_FRESH_TOP` | How many of the leaderboard's top traders (by 30-day profit, plus each market's top 100 and everyone followed) get their record read again ahead of everyone else, so their pages open on a fresh one. Default `300`; `0` turns it off. |
| `SIGNALS_BOARD_FRESH_HOURS` | How old their records get before that. Default `4`. |
| `SIGNALS_BACKGROUND_RATE` | Polymarket reads a second for the background work above. Default `4`. |
| `SIGNALS_CHECK_RATE` | Polymarket reads a second for reading a trader on the spot. Default `3`. |
| `SIGNALS_VENUES` | `polymarket,kalshi` adds Kalshi traders. Default `polymarket`. |
| `CLERK_PUBLISHABLE_KEY` | Turns on signing in (Clerk). No secret key needed. |
| `SIGNALS_SITE` | The site sign-ins must come from. Default `https://usesignals.app`. |
| `TELEGRAM_BOT_TOKEN` | Turns on Telegram alerts. |
| `SIGNALS_TG_LOGIN` | `1` makes an alert's "Check current price" a Telegram login button that opens it signed in. Off by default. |
| `CLERK_SECRET_KEY` | Needed for that button (it makes the one-time sign-in) and for new sign-ups (it reads Clerk's newest users). |
| `RESEND_API_KEY` | A send-only Resend key: the notes to new sign-ups and the sign-up alert (`signals/welcome.py`). Nothing is emailed without it. |
| `SIGNALS_WELCOME_FROM` | Turns on David's plain-text notes to new sign-ups, chosen by what they've done (`signals/welcome.py` lists who gets which and when), e.g. `David from Signals <david@uselayer.sh>`. |
| `SIGNALS_ALERT_FROM` | Turns on the email to the owner about each new sign-up, e.g. `Signals alerts <alerts@uselayer.sh>`. |
| `SIGNALS_SIGNUP_ALERT_TO` | Who gets that email. Default `pemakenemi56@gmail.com`. `SIGNALS_WELCOME_REPLY` is where replies to the note go (default `david@uselayer.sh`); `SIGNALS_OWNER_EMAILS` lists sign-ups never emailed (default the owner's). |
| `OPENROUTER_API_KEY` | Turns on the AI sentence on watch pages. |
| `SIGNALS_WHY_MODEL` | The model for it. Default `anthropic/claude-haiku-5.5`. |
| `SIGNALS_WHY_DAILY` | At most this many AI calls a day. Default `3000` (about $0.15). |
| `SIGNALS_POSTHOG_KEY` | Turns on PostHog analytics (hosted only). |
| `SIGNALS_METRICS_KEY` | Opens the owner's counts to whoever sends it (hosted). |
| `SIGNALS_OWNER_USER` | Your Clerk user id: Signals messages the Telegram chat connected on that account when it breaks. |
| `SIGNALS_OWNER_CHAT` | A Telegram chat id for those messages instead (wins over `SIGNALS_OWNER_USER`). |
| `SIGNALS_HOSTED` | `1` on the hosted engine. Set by the `Dockerfile`. |

`SIGNALS_SKILL_TEST=1` brings back the old skill test and its Recommended list in place of the Leaderboard. The
switches that only matter with it on (`SIGNALS_DISCOVERY`, `SIGNALS_DISCOVERY_LIMIT`, `SIGNALS_EXPLORE`,
`SIGNALS_WORTH_WALLETS`, `SIGNALS_CATEGORY_READS`, `SIGNALS_MOCK`) are left out above.

## Hosting

usesignals.app is the same engine with `SIGNALS_HOSTED=1`:

- **Railway** runs the engine from the `Dockerfile` (one process, `railway.json`), with a volume at `/data` for the
  data. Keys go in the service's variables and never reach the browser.
- **Vercel** holds the domain and forwards every request to Railway (`web/vercel.json`, deployed from `web/`).

### Setting up sign-in and alerts (owner)

1. **Telegram bot**: in Telegram, @BotFather → `/newbot`. Put its token in Railway as `TELEGRAM_BOT_TOKEN`. The
   bot uses long polling, so there's no webhook to set up.
2. **Clerk**: turn on Google (a production instance needs your own Google OAuth credentials) and make email
   optional (Telegram doesn't share one). Add Telegram as a custom provider (SSO connections → Add connection → For
   all users → Custom provider): discovery endpoint `https://oauth.telegram.org/.well-known/openid-configuration`,
   with the Client ID and Client Secret from @BotFather → your bot → Login Widget, where you also add Clerk's
   redirect URL as an Allowed URL.
3. **Domain**: a Clerk production instance asks for DNS records on usesignals.app (such as
   `clerk.usesignals.app`); add them where the domain's DNS is managed.
4. **Railway**: set `CLERK_PUBLISHABLE_KEY` (pk_live_…).
5. **Signed in from alerts** (optional): in Telegram, @BotFather → `/setdomain` → your bot → `usesignals.app`. Only
   then set `CLERK_SECRET_KEY` (sk_live_…, Clerk's dashboard → API keys) and `SIGNALS_TG_LOGIN=1` in Railway: until the
   domain is linked, Telegram refuses the button. Signals then sends the alert again without it, leaves the button
   off every alert until the next restart, and tells the owner (owner alerts) what to do.

Follows are kept in `/data/follows.json` by Clerk user id; alerts and counts in `/data/alerts.db`; wallets and
track records in `/data/directory.db`.

### When something breaks (owner)

Set `SIGNALS_OWNER_USER` to your Clerk user id (Clerk's dashboard → Users → you), with Telegram connected on your
Signals account, and Signals messages you there within a minute or so when:

- the disk under `/data` is 85% full, or 85% of its file slots are used (at 100% the Traders page stops working);
- any page answers with a server error (500), counted over 10 minutes;
- trader scoring fails every round for 30 minutes.

Each problem is told once, again every 6 hours while it lasts, and once more when it's fixed. The messages go
straight to Telegram, never through the disk, so they still go when the disk is what broke. To check they reach you:

```sh
curl -X POST -H "Authorization: Bearer $SIGNALS_METRICS_KEY" https://usesignals.app/api/owner-alerts/test
```

### Counting

What was sent, how it was delivered, taps on alert links, votes, follows and unfollows are counted in `alerts.db`,
with nothing personal beyond the signed-in account (no IPs). Price checks are counted with no id at all. To read the
summary:

- locally: `curl http://127.0.0.1:8790/api/metrics` (same machine only);
- hosted: set `SIGNALS_METRICS_KEY` in Railway, then
  `curl -H "Authorization: Bearer $SIGNALS_METRICS_KEY" https://usesignals.app/api/metrics`. Add `?days=7` to change
  the period (default 30). Without the key it answers 404.

The same key opens `/api/monitoring` (how the wallet search and reads are going, and what they cost) and
`/api/directory` (wallet counts).

### Analytics

With `SIGNALS_POSTHOG_KEY` set: page views, clicks, scroll depth and session replay in PostHog, plus the named events
below. It's sent through `/lyr` on usesignals.app (`web/vercel.json`), so it only works behind Vercel. A signed-in
person is known by their Clerk user id only: never their name, email, Telegram account or chat id, or anything from
`/api/me`. Replays mask every field and Clerk's menus.

Since 7 Nov an event about a trader says which one (a trader's page link carried the wallet anyway): `wallet`;
`name` when Signals shows one (never its made-up "Trader 0x91…76"); `category`, their main one as the Leaderboard's
chips classify them (Sports, Politics, Crypto, Esports, Economics, …); `categories`, every one known (their score's,
and the ones they made or lost money in). A fact the page hasn't read is left out. `from` is where on the page it
happened: `trader page`, `watch page`, `follow sheet`, or for the follow sheet `watchlist`, `empty watchlist`, `new
basket`.

- `trader page viewed`: a trader's profile or watch page opened, with the trader.
- `trader followed` and `trader unfollowed`, with the trader; `via: "telegram"` when followed with no account.
- `follow telegram opened`: Follow signed out, opening the bot; with the trader.
- `telegram connect opened`: "Connect Telegram" tapped; `telegram connected`: the bot confirmed the link while the
  page was open. Both carry the trader whose page it was tapped on.
- `follow sheet opened` (only where from: no trader yet) and `trader looked up` (`by`, `found`, and the trader when
  the search named one).
- Baskets: `basket picked`, `basket tab`, `basket trader opened`, `basket sheet opened`, `basket created`,
  `basket changed`, `basket deleted`; no trader.

Counting (above) stays the record of alerts and follows; nothing here changes it.

## Research agent

A signed-in trader names a wallet and asks, e.g. "Analyze 0x… BTC 15-minute trades since Nov 8: when does it enter,
at what prices, and what's its strategy?" Claude Opus 5.5 investigates with code: it reads the wallet's trades,
lines each Bitcoin 15-minute window up with Polymarket's prices, Binance's and the window's start price and result,
draws charts, and answers with what it observed and what it infers, each figure traced to the data. Follow-ups stay
in the same investigation.

It's `signals/research/`, its own service (`Dockerfile.research`, `railway.research.json`), never inside the engine:
investigations are long and read a lot, and the engine keeps alerts first.

- **The loop** (`agent.py`): `claude-opus-5-5`, adaptive thinking, code execution. Its five tools are called from its
  code (programmatic tool calling), so a wallet's thousands of trades go to the code, never into the chat:
  `wallet_trades` (uselayer 0.19 `whales.trades_between`, filtered to `btc-updown-15m-` slugs, paged past full
  reads), `wallet_profile` (the engine's public `/api/record` and `/api/account`), `window` (a window's start price,
  final price, result, Up/Down prices about every minute, everyone's trades in it, coverage; from Layer's recording
  when there is one: top-10 books, Chainlink and Binance by the second, the recording's own coverage), `outside_prices`
  (Binance spot candles from `data-api.binance.vision`; Chainlink once Layer's recordings are readable) and
  `make_chart` (a Vega-Lite spec with its data inline).
- **Every number traces to data** (`trace.py`): before an answer is shown, each figure in it must match (rounded,
  as $, k, ¢ or %) something a tool returned or its code printed. A miss gets one retry; what's still unmatched is
  shown flagged (`unverified`).
- **Reads** (`data.py`): Polymarket through the SDK on the service's own budget (`RESEARCH_READ_RATE`, 4 a second),
  never the engine's. Order books and Chainlink come from Layer's recorded windows (`recorded.py`: layer#642's
  `derived/windows/btc-15m/…json.gz` in R2, read with a read-only token); without the token, or for a window not
  recorded, `window` reads Polymarket's API and says the book isn't available, rather than returning nothing.
- **Kept** (`store.py`, SQLite in `RESEARCH_STORE_DIR`): investigations, the conversation, every event, charts, and
  per question its tokens and cost (`/api/research/runs`, the owner's).

| Route | |
|---|---|
| `POST /api/research/sessions` | a new investigation |
| `GET /api/research/sessions` | yours |
| `GET /api/research/sessions/{id}` | one, with every event so far |
| `POST /api/research/sessions/{id}/ask` `{question}` | starts answering (202), one at a time per person |
| `GET /api/research/sessions/{id}/events?after=N` | server-sent events from N on, live until `done` |
| `GET /api/research/charts/{id}` | a chart's spec |

Events have `type`, `v` (1) and `run`: `start`, `progress` (the agent's notes between steps), `code`, `tool_call`,
`tool_result` (counts, coverage, errors), `code_result`, `chart` (`chart_id`, `spec`), `check`, `answer` (`text`,
`unverified`), `notice` (e.g. an expired working state being rebuilt), `usage` (tokens, `token_usd`, `code_runs`,
`container_s`, `container_usd`, `cost_usd`), `error`, `done`. Trades carry a stable `id`.

A follow-up reuses the investigation's code container (its variables). Containers expire 30 days after they're made:
when the API refuses one (or it's 29 days old), the question runs in a new container, the page gets a `notice`, and
the agent is told to read again what it needs. Container time is billed by execution time, at least 5 minutes a
question ($0.05 an hour after 1,550 free hours a month); `container_s` is an estimate from when the container was
first used to the end of the question.

Settings: `ANTHROPIC_API_KEY` (off without it), `CLERK_PUBLISHABLE_KEY` (required with `RESEARCH_HOSTED=1`),
`RESEARCH_MAX_USD` per question (3), `RESEARCH_USER_DAILY_USD` (10), `RESEARCH_DAILY_USD` for everyone (30),
`RESEARCH_AT_ONCE` (2), `RESEARCH_MAX_ROUNDS` (40), `RESEARCH_EFFORT` (high), `SIGNALS_ENGINE_URL`,
`RESEARCH_METRICS_KEY`, and for Layer's recorded windows a read-only R2 token on `layer-history`: `R2_ACCOUNT_ID`,
`R2_ACCESS_KEY_ID`, `R2_SECRET_ACCESS_KEY` (`R2_BUCKET`, default layer-history).

**The page** (`signals/research/static/`, served by the service at `/research`; the main site's nav links to it as
Investigations, and its ask bar opens it with `?q=`). An investigation is a saved case file: the plan waits for
Start; the agent's events fill a workspace (tiles of every window, one window's replay with steps, its fills) and a
column of findings, answers and proposals; you can point at a fill or a moment and ask about it. The replay draws
Binance BTCUSDT, Chainlink BTC/USD (when recorded), the price to beat, the Up and Down prices, the wallet's fills and
its position on one time axis, with the pre-open band, recording gaps hatched and once-a-minute prices dotted. Preact
and htm (one pinned, vendored file, no build step) and hand-drawn SVG, so every fill is an element to point at. The
shapes it reads are `docs/research-contract.md`. Re-runs, alerts and "+ New view" show as later.

Locally: `uv run signals-research`, then http://127.0.0.1:8791/research/ (with `ANTHROPIC_API_KEY` to ask), or
http://127.0.0.1:8791/research/?fixtures for the page against recorded windows and a sample event log, with no key
and no sign-in. `uv run python tests/research_sample.py` rewrites that sample from the fixtures (a test checks it's
current). http://127.0.0.1:8791/api/research/dev is the bare page for trying the agent.

Hosting it (owner): a Railway service in the `signals` project from this repo with config `railway.research.json`,
a volume at `/research`, and its variables; then a rewrite in `web/vercel.json` above the catch-all,
`{ "source": "/api/research/(.*)", "destination": "https://<research service>/api/research/$1" }`.

## Good to know

- **Polymarket International only.** Its trades are public; every wallet is public. Signals reads them through the
  SDK from Polymarket's public data API. It doesn't see trades on Polymarket US or Kalshi.
- **Kalshi is off by default.** `SIGNALS_VENUES=polymarket,kalshi` adds Kalshi traders and leaderboards. Kalshi's
  trader data comes from undocumented endpoints behind kalshi.com, and most Kalshi traders hide their trades.
- **A record is the past.** Win rate, weeks up and profit say what a trader did, not what they'll do next.
- **Names, never wallets.** A trader without a Polymarket username shows as "Trader 0x91…76".

## License

MIT. See [LICENSE](LICENSE).
