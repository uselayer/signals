# This repo

Signals, on the uselayer SDK: signal discovery and trading intelligence, not a copy-trading app. Top traders on
Polymarket (Kalshi too when switched on, see below), a page per trader, cross-venue links (with Kalshi on), and
for every open trade what buying it now would really cost. It runs on the user's
machine (`uv run signals`) and is hosted at usesignals.app: the same engine with `SIGNALS_HOSTED=1` on Render,
behind Vercel (see README, "Hosting").

- All venue reads, links and copies go through `client.whales` in the SDK. Don't add venue calls or matching
  logic here; put it in the SDK. One approved stopgap: `_open_positions` (the Feed's poller) calls the SDK's
  internals for a positions-only read until uselayer has a public one (uselayer-sdk#23); don't add others. Track
  records read the profit history through the public `whales.profit_history` (uselayer 0.15).
- Leaderboard (`SIGNALS_SKILL_TEST` off, the default): Traders is one list of every public wallet with a track
  record (`signals/records.py`: profit, volume, profit per $ traded, win rate from positions closed, weeks up, usual
  trade; about 6 reads), a buy in the last 30 days and 5+ positions closed in 90 days, ranked by what they did
  (`/api/leaderboard`). A row is listed only with every column (owner, 19 Oct: "if they don't have all values for
  all columns, remove them"): a profit for the period, a usual trade and a win rate from 10 positions closed
  (`_complete`); a search still finds anyone, and the foot says how many wait. Records copied from scores have no
  win rate, so the evaluation reads those first (`board` in `due`, right after presented traders, the most profit
  over 30 days first, made due at launch by `board_due_now`). Facts only: no tier, no "recommended", nothing about whether they'll make money next. The
  background reads a record for each wallet instead of the skill test; `SIGNALS_SKILL_TEST=1` brings back the skill
  test, Recommended and Explore as they were. With it off, no verdict reaches anything (`_worth_load` and
  `_stored_score` give nothing, and the once-a-day check doesn't run): the Feed's second part is **Top traders**
  (`#/recommended`, `/api/live` with `pool` "top": the Leaderboard's first `FEED_TOP` by trading profit over 30 days,
  neutral cards, copying offered for nobody); a trader's page is their record (`record_page`: one read within 6
  hours as kept, else read now on the checks' budget, under "Check now"'s limits; no tier, "Why they're here" or
  checks); alerts name traders from the directory. A win rate always shows the average price they paid over 30
  days beside it (`paid_30d`, from the trades the quick check reads, each outcome once): a price is the market's
  chance, so paying 97¢ wins about 97% of the time by buying alone.
- Signals is Polymarket-only for now; the SDK stays multi-venue. `SIGNALS_VENUES` (`VENUES` in `app.py`, default
  `polymarket`; `polymarket,kalshi` adds Kalshi back) is the one switch: every read passes it to the SDK
  (`big_trades(venues=…)`, `top(venue=…)`), and a venue that's off is refused, never read and then hidden. The
  page gets it from `/api/config` and hides Kalshi's views (Top profit's venue choice, Kalshi trader pages,
  "Same person on the other venue?") while it's off.
- Keys come from the environment (hosted: the Render service's Environment), are never logged, returned by the
  engine or written to disk.
- Trader directory (README, "Trader directory"): wallets found, and where, in the store's `directory.db`, with
  each one's evaluation (status, last scored, last active) and every score worked out. Found is not checked and
  not recommended, and a kept score is a record, not a pick: never say a found wallet is any good, and scoring and
  its thresholds stay as they are. Traders shows the directory only with `SIGNALS_DISCOVERY=directory` (phase 5,
  the owner's flag; `check`, the default, is the Worth following check's own 200): its latest fresh scores in the
  check's shape and order, through `_worth_load`, so the Feed, alerts and trader pages follow. At most
  `SIGNALS_DISCOVERY_LIMIT` (the page and the Feed's poller stay their size); Explore is never limited by it. Explore's
  style facts (average price, new positions a day, bot-like, rewards) and its "Market makers and arbitrage" group come
  from stored scores only, never a read; the resting-orders and held-to-settlement shares stay out of it while the
  profile hides them. The check keeps
  running beside it, once a day (`WORTH_MAX_AGE_S`: it's only the fallback and the way back now), so going back is
  one switch, to a list up to a day old; `/api/discovery` compares the two (the owner's). Keeping a score
  costs no reads: it's written where a score is already made (`_worth_run`, `_score_of`, the launch import), and
  a score never replaces a newer one. It keeps wallets only (a follow keeps the wallet, never who follows). Its
  sweep reads through the SDK (`find_wallets`) at `DIRECTORY_RATE`, below the per-host limit with room for the
  Feed's poller, and holds while the Worth following check runs. Scoring a wallet on the spot ("Check now", a
  trader page) reads through `checker()`, on its own budget (`CHECK_RATE`, 3 a second); never through `reads`
  directly, so manual checks can't take the Feed's share. The background's and the checks' budgets give way (half
  rate) while the poller reads followed traders, so alerts come first. Pages and the check never write to it
  themselves: `_directory_note_later` and `_directory_later` (the writer thread; a failed write is never theirs).
- Counting (README, "Counting"): per alert and per follow, in the store's `alerts.db`, never anything personal
  beyond the signed-in account (no IPs, no user agents; an interest pick is counted with no id at all). Quotes
  (`quotes`: how each ended, Polymarket reads, milliseconds) and pages a wallet with no Polymarket profile stopped
  (`no_profile`) are counted with no id, wallet or trade at all: watch reads per quote, latency and rate limits
  there as traffic grows. Alert
  links go through `/go/<alert id>/<target>`, which redirects to Polymarket or Signals only, and still redirects
  when counting fails. `/api/metrics` is the owner's: locally, or with `SIGNALS_METRICS_KEY`; never public.
- Analytics (README, "Analytics"): PostHog on the page, off unless `SIGNALS_POSTHOG_KEY` is set, sent through
  `/lyr` (`web/vercel.json`). A signed-in person is identified by their Clerk user id only: never send PostHog a
  name, email, Telegram account or anything from `/api/me`, and keep fields and Clerk's menus masked in replays.
  It's for seeing how the page is used; Counting (above) stays the record of alerts and follows.
- Signals is a consumer website (usesignals.app); running it locally is for development. It places no orders:
  no sandbox, no in-app trading, no automatic copying, and it never holds anyone's keys or funds. Buying means
  "What buying now costs", then "Buy on Polymarket ↗", where the user buys it themselves. A session never
  places a real-money order, not even a test one.
- "What buying now costs" (`/api/trade/preview`, the page's `costBox`) is on every trade with a market,
  whoever made it: a quote only, never an order. Pricing a trade reads no score, and no copy estimate is shown
  beside it (below). The engine reads everything it
  shows, never trusting a price from the page: whether the market is closed or not taking orders comes from
  Polymarket's market status (the SDK's `preview_copy`), never from the price, and the amount is priced from
  the cheapest price for sale now, up to `BUY_LIMIT` (3¢) above it, a limit the page discloses. It shows the
  estimated cost, what's for sale within the limit, the fee, the estimated slippage and when the book was read
  (and that their trade's time is when it was made on Polymarket). Three prices, each with its own name every time: theirs is context, never a target
  ("Your estimated price: 33¢ a contract (34.1¢ with the fee). Trader paid 31¢."), and the sheet's "Market price now"
  (`price_now`, Polymarket's position price, never called the mid) is "Not a price you can buy at". Profit or loss
  comes first, then the total back ("+$19.11 profit · $29.00 back in total", "−$9.89 loss · You get nothing back"),
  uncoloured, with "Not spent" for what's left of the amount. International's button sits right under its estimate;
  Polymarket US is one line after it ("US prices and fees differ. The estimate above doesn't apply.", "View US market
  ↗"), with how the two may pay out differently in view and how they were matched folded ("Match details"). With a
  verified Kalshi match (`kalshi_of`, looked up by the engine, never sent by the page) the whole estimate is Kalshi's
  (owner, 20 Oct: the SDK's `preview_kalshi`, Kalshi's public book and fees, no key): "Kalshi estimate", "Trader paid
  49¢ on Polymarket International.", "Buy on Kalshi ↗" right under it, how the two may pay out differently in view,
  "Or buy on Polymarket International, where they traded ↗", then the US line. When Kalshi doesn't list the market or
  isn't taking orders on it, International prices it and the sheet says why (`kalshi_closed`). It's always an estimate: never imply a guaranteed fill (it may fill higher, in part, or not
  at all), and no green or "you can still get in" in it. A quote that fails shows no price: when the book moved
  between the reads (`price_changed`) it says "Price changed—refresh quote", never that nothing is for sale;
  "Only $X is for sale" is only for an amount bigger than the book holds within the limit. Transparency over a
  quote that always succeeds.
- Traders (the leaderboard, Top profit) and trader pages need no account; everything in the Feed (Following,
  Recommended, Big trades, an alert's "Check your price") is behind signing in (Clerk: Google, or Telegram as a
  custom OpenID Connect provider). Signed out, a Feed page is the sign-in page ("Sign in to see the Feed", Sign in,
  Browse traders), and the engine refuses its reads (`feed_reader`: `/api/live`, `/api/trading-now`, `/api/bet`)
  without a valid session. Without Clerk's key (running locally) nothing is gated. On a trader's page the Follow
  button says why you'd sign in ("Follow · get an alert after they trade"). Alerts go
  to Telegram (`alert_pass` in `app.py`). Signals is trader discovery and trading intelligence first, copying
  second: following is research, so every buy by a trader you follow alerts you, whatever the amount and whoever
  the trader (their buys of one outcome within 30 minutes add up, across rounds and restarts, shown as the total
  at the average price). Every alert gives the same facts for every trader (`_trade_text`): who bought which
  outcome at what price and for how much, the market, the price now, and when they traded with how long before
  the alert that was, measured ("Traded 14:02 UTC, 6 min before this alert."), never "just now" or "live".
  Outside the "can still get in" range it says "Now 60¢, price already moved.", whoever the trader. Nothing about
  copying (no copy line: the copy estimate isn't shown anywhere) and never a cost in the alert: costs, the fill, liquidity and risks are the
  trade page's. Every alert links "Check current price" (`#/check/<wallet>/<market>`, the trade's own page,
  neutral for every trader), and "Buy on Polymarket", which only opens the market. Sells by a trader you follow
  alert too, whatever the amount (`_sell_text`): who sold which outcome at what price and for how much, the market
  and when, measured; while they still hold some, the price now and "Check current price"; once they hold none,
  "They no longer hold it." and no price (never a made-up one). A sell is information only: never "sell too",
  never a copy line, never grouped, "Open on Polymarket" for the market. No alert at all when the price
  now is settled (2¢ or less, 98¢ or more), or a sell's price is. A restart (a deploy) neither skips nor repeats one:
  what each round looked at is kept in alerts.db (`watched`, `seen_trades`), so a trade made while it was down is
  alerted once after; only a new follow's existing trades are just noted. Delivery (`_send`, `_attempt`): each
  alert is kept with its message before Telegram is asked, and never sent twice. It's tried again (after Telegram's
  wait or 30 s, 1, 2, 4 min, for up to 30 minutes, after a restart too) only when Telegram surely didn't take it:
  it was never reached, or it said 429. When it may have (a 5xx, no answer once the request went out, the engine
  stopping mid-request) it's recorded as unknown, with why, never asked again. A refusal fails it, and a chat that
  blocked the bot is disconnected. Every trade of a trader you follow alerts unless you chose fewer for them
  (`alert_for` in follows.json: only trades over an amount, or a summary every 6 hours; `_wants`), and a sale of
  something their alert told you about always comes. Following a busy trader (over 20 alerts a day over the past
  week: `_measure_pace`, kept in alerts.db `pace`) says so with an amount about 3 of their bets a day reached, worded
  as an estimate from last week, never a promise. At most 200 alerts per person per UTC day (a safety limit), then
  one message that says when alerts resume (00:00 UTC, and how long until then) and nothing until the next day. When 2+ traders you follow buy the same outcome, each within 6 hours of the one before (1 hour in
  Sports and Esports), the second buy sends one grouped alert (each one's price and buy time, the price now, how
  long before the alert the latest buy was) and later buys edit it in place; it counts once. Every alert has
  "Useful / Not useful" (one vote per alert and account, changeable). Big trades ($10,000 or more) in your chosen
  markets alert you whoever the trader, with the same facts, at most 5
  a day within the daily cap. Only a choice made where the page asks (onboarding, or the Feed's "Your markets · Change")
  is kept on the account (per account like follows); Traders' chips only filter the view, and nothing saved or []
  (Skip, all markets) means no big-trade alerts. An alert is never "you can still get in" and never green.
  Every alert and trade card keeps the link to the market, whoever the trader. Every alert, and the Feed, says
  how late it can be for where its trades come from, never a blanket figure and never "instant": a trader you
  follow is read on their own about every 30 seconds (Polymarket returns their trades there within seconds), so
  their alerts say "Signals typically reads followed traders' trades every 30 seconds" (`FOLLOW_DELAY`); big trades
  come from Polymarket's feed of every trade, which typically runs 3–5 minutes behind (`BIG_DELAY`, and the Feed's Big
  trades). A trade's time is its Polymarket timestamp (its transaction's block time), and every alert measures
  from it ("Traded 14:02 UTC, 6 min before this alert."). The engine checks Clerk's session token itself (public keys,
  no Clerk secret). Never let one account see or change another's follows, and never let an answer about a
  signed-in person be cached.
- Deploys and changes to the hosting (Render, Vercel, the domain) only when the owner asks.
- Never say a link *is* someone: show the tier ("likely" / "possible") and the evidence.
- The page is a consumer app, not an analyst's spreadsheet. It helps people find traders worth following and
  understand why: who they are, how they trade, and what the evidence does and doesn't show. Before anyone buys,
  show what it would really cost them now (above): what their amount fills at, the fee, the slippage, what's for
  sale. Nothing on the page may imply that copying makes money. Three tabs (Feed, Watchlist, Traders).
  - The Watchlist (`#/watchlist`, signed in) is the follow list (one list: Follow on a trader's page, "+ Follow a
    trader" there, alerts and the Feed's Following all use follows.json), a card per trader, read from what's kept
    (`/api/me/watchlist` reads nothing). A trader's watch page (`#/watch/<wallet>`, no account) is `/api/watch`: their
    last 500 trades and open positions on the checks' budget under "Check now"'s limits, kept 30 s for everyone,
    worked out by `signals/watch.py`. A change (new, bought more, sold some, sold all) comes from walking back from what
    they hold now; where that isn't known (not held, last move a buy: it settled or was paid out) it's only "Bought" or
    "Sold", never guessed. Its explanation is facts only (no AI write-up, no verdict, nothing about what happens next),
    every change label neutral, and every buy keeps "Check your price".
  - Onboarding (first visit, once per browser) asks one question: which markets interest you (Politics, Sports,
    Crypto, Esports; Skip means all markets). Nothing else: no budget, goals or signup. The choice is kept in
    localStorage (and, when picked here or with the Feed's Change, on the account for big-trade alerts), every read and write in try/catch; if storage is blocked it holds for the visit, and no one is
    ever stuck on that screen.
  - Two separate readings, never merged: profit (track record) and skill (the tier). The tier is skill and track
    record only (uselayer 0.10's `segment`; a kept older result is re-tiered with the SDK's `segment_of`). Nothing
    may present a trader's activity as a tested way to make money: following and the Feed are for learning what
    traders do, not a signal to buy (`NOT_A_TIP`).
  - No copy estimate on the page or in alerts (the owner, 18 Oct: it isn't reliable yet). The engine still works
    out a copy status (`copy_status`, `copy_offer`; `copy_label`, `copy_ok`, `copy_why`, `copy_return…` in the API)
    from the SDK's `copyable`, but nothing anyone sees shows it or follows it: no copy status, figure, range,
    column, sort, filter, "Copying is paused" callout, How-we-pick tab, copy line in an alert, the SDK's
    "Copyable" check on a trader page, or colour (an open trade reads the same for every trader). A guard test
    keeps the page's words free of "Copy", "Copyable" and "Copying". Bringing it back is the owner's call.
  - Traders lists the traders we recommend in one section, **Sharps** (the engine's `section_of`: every recommended
    tier), with its ranks and "Show more" in the sort picked (by default Recommended's tier order); "See all checked
    traders" is one flat list. Recommended never vouches for a brand-new account or one it can't show in full (owner,
    19 Oct): a recommended tier needs a figure in every column (trading profit, trend, a win rate from 10 settled
    trades, usual trade) and 4 weeks of history (`VOUCH_WEEKS`), or `held_back` moves the trader to Limited evidence
    wherever the checked traders are read (`_worth_load`: Traders, the Feed's Recommended, alerts, their page),
    keeping `held_back_from` and why. The SDK's Proven and Rising both read "Sharp" (chip and colour), and Quiet reads
    "Quiet sharp", a style (fewer, bigger trades): the owner, 19 Oct, after Sharp and Rising had indistinguishable
    next-month results. Presentation only: the segment ("rising" stays in the data and the API), which tiers are
    recommended and the thresholds are the SDK's. Nothing a visitor reads says "Rising" (a guard test), and no new
    label or "hot" list. A Rising trader's "Why they're here" is a plain fact with no hedge ("The price has tended
    to move their way after they buy, over 12 trades so far."), never "too few to be sure" beside a Sharp chip,
    and never "it holds without their best trades" (not shown for them). An open trade (their page, a Feed card, a trader page) says only "Now 52¢ · they paid 49¢", for every
    trader, never green or "you can still get in". The "Buy on Polymarket" link, which only opens the market, "Check your price" and "What buying now
    costs" stay for everyone: neutral market data. Every figure names its period: only profit and trend follow the 7D/30D/90D switch; consistency is 12 weeks,
    win record and usual trade the last 30 days. Consistency is "X of N weeks up", where a week counts profit
    taken plus the change in value of trades still open.
    On a trader's profile only, right under "Weeks up", "Streak" is the run they're on now (`weekStreak`), counted
    back from their latest week with data in the same 12 weeks: "Up 3 weeks in a row" or "Down 3 weeks in a row",
    with "Past results, not a prediction". A flat week or a week with no data ends it, and a run under 2 weeks has no
    row. It's never on the traders list or the Feed, never a column, sort or filter, and there's no "hot" list (the
    owner, 19 Oct: traders up 3 of their last 4 weeks made money the next month 63% of the time against 26%, but
    copying them still lost after costs).
    One bar: filters on the left (market chips = the onboarding choice), how you view the list on
    the right (search name or wallet, period, sort). Columns are grouped as Track record and Style.
    Recommendations never include Big profit, edge unproven; Profit rests on one win (big profit that's a loss
    without their biggest win: the only tier that says luck); Our price test didn't show skill (the SDK's "Edge not
    proven"); Not enough data (too few trades could be checked: never shown as a verdict on skill); or Market maker or
    arbitrage traders (the SDK's "No view"), and the checks are never loosened to
    fill the list: an empty result says so and names the interests that had no one. "See all checked traders" may
    show the rest, each marked.
  - A profile figure we can't give has no row, never "—" (the owner, 19 Oct: "better to remove than just have missing
    data"); a row still loading ("…") is shown. Open P&L adds up Polymarket's figure for each open position (priced
    between 0 and 1: one at 2¢ or 98¢ hasn't settled and counts), read up to 500 at once; when Polymarket's list may
    hold more (`positions_cut`), there's no row. "Made money on X of N positions" (`/api/completed`) is on neither
    profile: a hit rate, not skill, slow for busy traders and given for only 18 of 50 recommended traders (dropped
    19 Oct). The worst drop from a high is the score's `worst_drop` (every hourly point); a score kept before 0.14
    has none and no row. "Realized profit by category, all time" (`/api/categories`, the SDK's
    `realized_by_category`, parlays included) has a row per category and "Other markets" (the engine's "Uncategorised",
    markets Polymarket puts in no category: no row under $1 or under 0.1% of their total, the owner, 19 Oct, on +$1.17
    beside $9.1M); "All categories" only
    with more than one row and "All except Sports" only with Sports and two or more others, so no row repeats
    another; with the caveat "Polymarket's figures, updated every few hours. Trades still open aren't counted."
    It's read on the checks' budget (`checker`: 12 reads), kept per wallet (1 h), and under "Check now"'s limits
    (`limited_read`: CHECKS_AT_ONCE turns, CHECKS_PER_CLIENT wallets per visitor); past one the card says "Busy,
    try again in a minute.", never an error or $0.
  - A profile's Positions tab is one line per outcome (every buy added up) and Recent trades each buy and sell, each
    tab with a line saying so. A position says what they put in, in dollars (contracts × their average price, the
    contracts in the hover); open, what it's worth now, with the price they paid and the price now as its neutral
    status; closed, what they got back and how it ended with Polymarket's profit after fees (the owner, 19 Oct: "how
    much did they put in?").
  - Traders' category picker ("Any category", Polymarket's categories, "Other markets", "All except Sports"): picking
    one sorts by realized profit in it (all time) and offers "Made money in X". Only the traders already listed are
    sorted or filtered: no new tier or label, no recommendation loosened, no raw-profit leaderboard beyond this sort.
    Its figures come from what's kept, never a read on a page load: a daily job (`_categories_loop`,
    `categories_round`) reads each recommended trader's realized profit by category once a day on the
    background's budget (`background`, ~1,300 reads a day for ~110 traders) into directory.db
    (`realized_categories`); a trader profile uses the kept one while it's under a day old, with no turn. A kept
    figure over CATEGORY_KEPT_S old, or a trader not read yet, shows "—" and is never counted as having made money. SIGNALS_CATEGORY_READS=0 stops the reads.
  - Never a made-up number for a real trader on the hosted app. A figure the data doesn't have yet shows "—";
    sample values (`SIGNALS_MOCK=1`) are for reviewing the page locally only. The SDK's per-dollar figure is a return per dollar traded, never "ROI".
  - Words: say "trade", never "bet"; never "sandbox" or "paper". Every trade with a market has "Check your
    price", which opens what buying now costs; there is no "Copy trader". Following a trader (alerts) is how you
    hear about their next trades.
  - One idea per card. The market title is the biggest text; status is one line with a dot.
  - Color means something: green and red are gains and losses (a profit, Won, Lost); an open trade's status
    (where the price is) is neutral for every trader. Nothing else is colored.
  - Plain words, sentence case, one font (Host Grotesk, as on Layer's site), tabular numbers, whole cents (tenths
    only under 1¢ or when two prices would look equal). No UPPERCASE headers, no tooltip-on-header help.
  - Methodology (tests, z-scores, margins) stays out of the main view: in "How we pick traders" or a Details fold.
  - No wallet addresses on screen: unnamed traders get "Trader 0x91…76" and an identicon.
  - Must look good at 390px as well as desktop. One width: the header, Feed, Traders and trader profiles share
    the 1200px container (Top profit keeps a 680px reading column), so the account sits at the header's right and
    nothing moves between tabs. Feed cards are a grid: three across on desktop, one on a phone. Keep loading,
    empty and error states.
  - The Feed has two parts. **Following** (`#/`, the default, `/api/me/feed`): every trade from the last day of
    the traders you follow, whoever they are (following is also research). **Recommended** (`#/recommended`, `/api/live`): trades of $1,000 or more (`RECOMMENDED_MIN_USD`) from
    the traders in Sharps, with the same neutral cards as Following. Recommended
    stays quiet (fewer, bigger trades) and never more prominent than Following: second in the switch, never the
    default. Both keep the switch "Only trades I can still get into", one card per outcome with "Also bought
    by", and the delay line. Big trades (`#/big`) is linked from the foot of Recommended. Traders' trades come from
    one background poller (`_live_loop`, one read at a time, in 30 s rounds: everyone followed each round,
    Recommended's every 60 s while the round's slot allows, oldest first, so a bigger pool is read less often,
    never faster). Per trader it reads their trades, and their open positions only when there's a trade from the
    last day to price (kept while their trades don't change, for 90 s); never the profile or stats. Polymarket's
    shared $1,000+ trades feed (one read for everyone) moves a Recommended trader who just traded to the front.
    Pages only read what it keeps, so a busy Feed never adds Polymarket reads: a view reads at most 3 traders the
    poller hasn't read yet itself ("Still reading N traders"), and "Updated" is when the oldest of it was read.
    The Feed never says "None of … traded" for traders it hasn't read: it says it's still reading them, or that
    they couldn't be read, and notes when some of it was last read over 5 minutes ago. Everyone followed is read
    once every round however many there are (Recommended keeps a floor of 4 reads a round); alerts read what the
    poller keeps, never on their own; a gap of more than 100 trades between reads is read further back (500);
    a rate limit ends the round.
  - Market chips live on Traders only. The Feed follows the same choice and says so in one line ("Your markets:
    Politics, Sports · Change"); Change opens the onboarding picker. Never a second set of filter chips.
  - A trade at 2¢ or less, 98¢ or more, or no longer held is settled (Won / Lost / Closed), never a bargain
    (`bet_status` in `app.py`). "You can still get in" only from 5¢ below to 3¢ above what they paid; further
    either way is "Price moved away" (a big drop means the market turned against them, not a bargain).
- Pull requests: sessions never merge. Only the owner merges, when they say "merge #N".

## Deploying (only when the owner asks)

- **Engine** (Render service `signals`, from `render.yaml`): nothing deploys on a commit. The owner deploys main's
  latest commit with Manual Deploy in Render's dashboard, or `render deploys create <service id>`. It builds the
  `Dockerfile`; the store is on the service's disk at `/data`. A deploy stops the server for a few seconds, and a
  Worth following check that hasn't finished starts over (20–30 min).
- **After any deploy**, check the live page actually serves the new code: fetch https://usesignals.app and look
  for something only the new code has.
- **Forwarding layer** (Vercel project `signals`, holds usesignals.app): `vercel deploy --prod` inside `web/`.
  Only needed when `web/vercel.json` changes. A new folder isn't linked yet: `vercel link --project signals` in `web/`.
- Keys are set by the owner in the Render service's Environment, never by a session.
- Railway ran the engine until October 2026 (`railway.json`, `railway up . --path-as-root --service signals`); the
  move to Render is `deploy/render/README.md`. Until usesignals.app points at Render, deploys still go to Railway.
