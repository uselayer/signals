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
Watchlist need signing in. The first visit asks which markets interest you (Politics, Sports, Crypto, Esports, or
Skip for all). The choice is kept in your browser, and the Feed follows it.

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
days. **Top profit** (linked at the foot) is Polymarket's own leaderboard.

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
| `SIGNALS_BACKGROUND_RATE` | Polymarket reads a second for the background work above. Default `4`. |
| `SIGNALS_CHECK_RATE` | Polymarket reads a second for reading a trader on the spot. Default `3`. |
| `SIGNALS_VENUES` | `polymarket,kalshi` adds Kalshi traders. Default `polymarket`. |
| `CLERK_PUBLISHABLE_KEY` | Turns on signing in (Clerk). No secret key needed. |
| `SIGNALS_SITE` | The site sign-ins must come from. Default `https://usesignals.app`. |
| `TELEGRAM_BOT_TOKEN` | Turns on Telegram alerts. |
| `OPENROUTER_API_KEY` | Turns on the AI sentence on watch pages. |
| `SIGNALS_WHY_MODEL` | The model for it. Default `anthropic/claude-haiku-5.5`. |
| `SIGNALS_WHY_DAILY` | At most this many AI calls a day. Default `3000` (about $0.15). |
| `SIGNALS_POSTHOG_KEY` | Turns on PostHog analytics (hosted only). |
| `SIGNALS_METRICS_KEY` | Opens the owner's counts to whoever sends it (hosted). |
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

Follows are kept in `/data/follows.json` by Clerk user id; alerts and counts in `/data/alerts.db`; wallets and
track records in `/data/directory.db`.

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

With `SIGNALS_POSTHOG_KEY` set: page views, clicks, scroll depth and session replay in PostHog, plus a few named
events (`trader followed`, `trader unfollowed`, `follow sheet opened`, `trader looked up`), never which trader. It's
sent through `/lyr` on usesignals.app (`web/vercel.json`), so it only works behind Vercel. A signed-in person is
known by their Clerk user id only. Replays mask every field and Clerk's menus.

## Good to know

- **Polymarket International only.** Its trades are public; every wallet is public. Signals reads them through the
  SDK from Polymarket's public data API. It doesn't see trades on Polymarket US or Kalshi.
- **Kalshi is off by default.** `SIGNALS_VENUES=polymarket,kalshi` adds Kalshi traders and leaderboards. Kalshi's
  trader data comes from undocumented endpoints behind kalshi.com, and most Kalshi traders hide their trades.
- **A record is the past.** Win rate, weeks up and profit say what a trader did, not what they'll do next.
- **Names, never wallets.** A trader without a Polymarket username shows as "Trader 0x91…76".

## License

MIT. See [LICENSE](LICENSE).
