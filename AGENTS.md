# This repo

Signals, on the uselayer SDK: signal discovery and trading intelligence, not a copy-trading app. A Leaderboard of
Polymarket traders' track records (Kalshi too when switched on, see below), a page per trader, a Watchlist, cross-venue links (with Kalshi on), and
for every open trade what buying it now would really cost. It runs on the user's
machine (`uv run signals`) and is hosted at usesignals.app: the same engine with `SIGNALS_HOSTED=1` on Railway,
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
  win rate, so the evaluation reads those first (`board` in `due`, right after presented traders and `top`, the most profit
  over 30 days first, made due at launch by `board_due_now`). Every other record is read again every 2 days as the
  queue allows (about a week behind on 5 Nov), but the wallets profiles are opened for are read again once last
  looked at 4 hours ago (`top` in `due`, right after presented traders: `board_top`, the Leaderboard's first
  `SIGNALS_BOARD_FRESH_TOP` (300) by 30-day profit, each market chip's first 100, and every followed trader;
  `SIGNALS_BOARD_FRESH_HOURS`), on the background's budget like the rest (~0.3 reads a second), so a trader's page
  mostly finds a record under 6 hours old instead of reading one on the spot. Facts only: no tier, no "recommended", nothing about whether they'll make money next.
  One tag, never a verdict: a "Bot" pill (amber robot; `bot` 1: 100+ trades a day, the SDK score's rule, worked out by
  `records._bot` from the trades a record already reads; a record read before it falls back to the wallet's last score
  tag, `directory.bot_tag`), else a "Human" pill (blue person; `bot` 0), and none when nothing says (`whoBadge`): the
  Leaderboard's Human/Bot column (beside the name on a phone), a trader's page and Watchlist header, Explore's rows and
  the Breakdowns header (from `/api/worth`). The
  background reads a record for each wallet instead of the skill test; `SIGNALS_SKILL_TEST=1` brings back the skill
  test, Recommended and Explore as they were. With it off, no verdict reaches anything (`_worth_load` and
  `_stored_score` give nothing, and the once-a-day check doesn't run): the Feed's second part is **Top traders**
  (`#/recommended`, `/api/live` with `pool` "top": the Leaderboard's first `FEED_TOP` by trading profit over 30 days,
  neutral cards, copying offered for nobody); a trader's page is their record (`record_page`: one read within 6
  hours as kept, else read now on the checks' budget, under "Check now"'s limits: an older one is shown at once,
  "Refreshing…", and the page waits on the read behind it (`wait=1`), swaps the new figures in place, and after a
  failed read says why, tries twice more by itself and offers "Try again" (`retry=1`); only a wallet with no record
  kept waits on its first read; no tier, "Why they're here" or checks); alerts name traders from the directory. A win rate always shows the average price they paid over 30
  days beside it (`paid_30d`, from the trades the quick check reads, each outcome once): a price is the market's
  chance, so paying 97¢ wins about 97% of the time by buying alone.
- Signals is Polymarket-only for now; the SDK stays multi-venue. `SIGNALS_VENUES` (`VENUES` in `app.py`, default
  `polymarket`; `polymarket,kalshi` adds Kalshi back) is the one switch: every read passes it to the SDK
  (`big_trades(venues=…)`, `top(venue=…)`), and a venue that's off is refused, never read and then hidden. The
  page gets it from `/api/config` and hides Kalshi's views (Top profit's venue choice, Kalshi trader pages,
  "Same person on the other venue?") while it's off.
- Keys come from the environment (hosted: Railway's service variables), are never logged, returned by the
  engine or written to disk.
- Trader directory: wallets found, and where, in the store's `directory.db`, with
  each one's evaluation (status, last scored, last active) and every score worked out. Found is not checked and
  not recommended, and a kept score is a record, not a pick: never say a found wallet is any good, and scoring and
  its thresholds stay as they are. The rest of this point is the skill test's (`SIGNALS_SKILL_TEST=1`) only, and
  the sweep is off on the hosted app (`SIGNALS_DIRECTORY=0`, the owner's choice). Traders shows the directory only with `SIGNALS_DISCOVERY=directory` (phase 5,
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
  It's for seeing how the page is used, and (since 10 Nov, through `ph` in the engine) what people do in Telegram:
  connected, alerts sent/failed/tapped, "Fewer alerts", alert rules (setup started, saved with which parts, edited,
  paused, a typed amount that wasn't one: never what was typed), stops, votes; the account id only (Clerk id or a Telegram-only
  follower's random `tg_` id), never a chat id. Counting (above) stays the record of alerts and follows. Named events go
  through `track` (README lists them) and say where on the page (`from`) and, since 7 Nov (the owner: a trader's
  page link carried the wallet anyway), which trader: `traderFacts` (wallet, the name Signals shows, main category,
  categories), only from what the page has read, never made up. Still never anything about the person.
- Signals is a consumer website (usesignals.app); running it locally is for development. It places an order only
  when the user taps "Copy" under an alert (one-tap copy, owner 11 Nov 2026: "Copying a trade" below), from their
  own wallet: no automatic copying, no other in-app trading, and it never holds anyone's funds or their wallet's
  owner key. Everywhere else buying means "What buying now costs", then "Buy on Polymarket ↗", where the user buys
  it themselves. A session never places a real-money order, not even a test one: the owner or a tester taps Copy.
- Copying a trade (`signals/copying.py`, `signals/copy_service.py`, `copy-web/`): only accounts in
  `SIGNALS_COPY_USERS` (the owner's flag; only the owner's account until the owner says otherwise) see it. A
  follower sets it up on /copy: Polymarket's geoblock is asked from their own browser and where Polymarket doesn't
  allow new trades (the US and the rest of its list) it stops there; they keep the alert's Polymarket US / Kalshi
  links. Privy holds their wallet's owner key; Polymarket deploys their Deposit Wallet (gas paid by Signals' builder
  key, only for relayer calls, `SIGNS_PER_HOUR`); they approve one Signals trading key (a Polymarket session key,
  scope CLOB: trades, never withdraws, 180 days, revocable). That key is made, encrypted and used only by the order
  service, which runs in a region Polymarket takes orders from (the engine runs in the US and never places an
  order) and refuses to send one while Polymarket's geoblock blocks its own IP. A tap is a FAK buy of
  `SIGNALS_COPY_USD` (default $25) at most `COLLAR` (3¢) above the price the alert showed, kept as "placing" first
  so a second tap never buys twice; the reply says what was bought or plainly why nothing was. Never a sell, never
  without a tap, never a size the follower didn't choose.
- The owner's own copy on Kalshi and Polymarket US (`signals/own_trading.py`, owner 11 Nov 2026): only the account in
  `SIGNALS_OWN_UID`, with the owner's own exchange keys, so Signals' software trades its owner's own account (Kalshi's
  Developer Agreement allows "a member's own trading"). Never anyone else's exchange keys: Kalshi (Developer Agreement
  §3.2, "Facilitating trading ... by other members") and Polymarket US (Participant Agreement §I.24, credentials
  never shared) forbid it; other people in the US get there only through an exchange partner programme. A buy alert
  whose outcome has a verified match gets "Copy $25 on Kalshi / Polymarket US"; a tap is an IOC buy at most 3¢
  above the alert's price, once per alert, at most `SIGNALS_OWN_DAILY_USD` a day; "may have gone through" is said
  so and never re-sent.
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
- Traders (the leaderboard, Top profit), trader pages and an alert's "Check your price" (`#/check`, `/api/bet`)
  need no account: Telegram opens alert links in its own browser, signed out, and people who follow from Telegram
  may have no account (5 Nov: Zach had to sign in again on two alert taps). With `SIGNALS_TG_LOGIN=1` (and
  `CLERK_SECRET_KEY`, the one Clerk secret Signals holds, also used to read new sign-ups for `signals/welcome.py`) an alert's "Check current price" is
  also a Telegram login button: `/tg/in` checks Telegram's signed data (our bot token, under 10 minutes old, used
  once) and signs in the account the tapper's chat is connected to, with a one-time Clerk pass the page uses and
  drops from the address. The tapper, never the alert's recipient, so a forwarded alert opens no one else's account;
  anything short of that opens the trade signed out. Telegram refuses the whole message when the bot isn't linked
  to the site (BOT_DOMAIN_INVALID, 5–7 Nov: 2,072 alerts lost); since then a refused alert is sent again without
  the button, no alert carries it until a restart (`_tg["login_refused"]`) and the owner is told
  (`owner_check`). Everything else in the Feed (Following,
  Top traders, Big trades) is behind signing in (Clerk: Google, or Telegram as a custom OpenID Connect provider).
  Signed out, a Feed page is the sign-in page ("Sign in to see the Feed", Sign in, Browse traders), and the engine
  refuses its reads (`feed_reader`: `/api/live`, `/api/trading-now`) without a valid session. Without Clerk's key (running locally) nothing is gated. On a trader's page the Follow
  button says what you get ("Follow · get an alert after they trade"). Signed out, with alerts on, Follow needs no
  account (owner, 29 Oct: visitors left at the sign-in box): it opens Telegram with a one-time link that carries the
  trader (`/api/follow/telegram`), and Start there follows them with alerts on (`_follow_from_chat`): on the chat's
  account if it has one, else a Telegram-only follower (`TG_ONLY` plus a random id, never the chat's). Connecting
  that chat to an account later moves its follows and choices there; `/stop` forgets a Telegram-only follower. The
  page keeps such follows in this browser only (`signals.tgfollows`) and never signs anyone in. Alerts go
  to Telegram (`alert_pass` in `app.py`). Signals is trader discovery and trading intelligence first, copying
  second: following is research, so every buy by a trader you follow alerts you, whatever the amount and whoever
  the trader (their buys of one outcome within 30 minutes add up, across rounds and restarts, shown as the total
  at the average price), unless you set a rule for them (below). Every alert gives the same facts for every trader
  (`_trade_text`), short (owner, 10 Nov: "too much words"; people think in their own time zone, not UTC): "**Sam**
  bought **Yes** · Market", then "$1,240 at 41¢ · 6 min ago. Now 42¢.", where it traded, and the links. How long ago
  is measured from the trade's Polymarket timestamp (`_ago`: minutes, at least "1 min ago", then "2 h ago"), never
  "just now", "live" or a UTC time. A buy sent because it passed a rule starts with the rule it matched (`_rule_tag`:
  "Matches your rule · $500+ in Politics", from the parts that are set).
  Outside the "can still get in" range it says "Now 60¢, price already moved.", whoever the trader. Nothing about
  copying (no copy line: the copy estimate isn't shown anywhere) and never a cost in the alert: costs, the fill, liquidity and risks are the
  trade page's. Every alert links "Check current price" (`#/check/<wallet>/<market>`, the trade's own page,
  neutral for every trader), and "Buy on Polymarket", which only opens the market. Sells by a trader you follow
  alert too, whatever the amount (`_sell_text`, as short): who sold which outcome and the market, then how much at
  what price and how long ago; while they still hold some, the price now and "Check current price"; once they hold none,
  "They no longer hold it." and no price (never a made-up one). A sell is information only: never "sell too",
  never a copy line, never grouped, "Open on Polymarket" for the market. No alert at all when the price
  now is settled (2¢ or less, 98¢ or more), or a sell's price is. A restart (a deploy) neither skips nor repeats one:
  what each round looked at is kept in alerts.db (`watched`, `seen_trades`), so a trade made while it was down is
  alerted once after; only a new follow's existing trades are just noted. Delivery (`_send`, `_attempt`): each
  alert is kept with its message before Telegram is asked, and never sent twice. It's tried again (after Telegram's
  wait or 30 s, 1, 2, 4 min, for up to 30 minutes, after a restart too) only when Telegram surely didn't take it:
  it was never reached, or it said 429. When it may have (a 5xx, no answer once the request went out, the engine
  stopping mid-request) it's recorded as unknown, with why, never asked again. A refusal fails it, and a chat that
  blocked the bot is disconnected. Every trade of a trader you follow alerts unless you set a rule for them
  (owner, 10 Nov: 4,140 alerts in 30 days, 0.2% tapped; one follower at the 200 cap every day). The rule is
  `alert_for[wallet]` in follows.json (`_rule` reads it, `_change_rule` writes it, `_wants` applies it): `mode` and
  `usd` as before (every trade, only trades of `usd` or more, or a summary every 6 hours, which then sums up only what
  passes the rule and says the time it covers as alerts do, "over the last 6 h", never a clock time or time zone:
  owner, 11 Nov), plus `cats` (markets, the same INTEREST_CHOICES as big-trade interests; [] or none = all; a market
  whose category couldn't be read doesn't match, as for big trades), `first_only`, `px` ([lo, hi] cents, ends
  included, on the trade's average price) and `paused_until` (unix time). A field that's missing is its default, so
  an older follows.json reads as it did, and the page's choice (`PUT …/alerts`, mode and amount only) keeps the
  other fields. **first_only** skips a buy that adds to an outcome they already held: from the same reads the alert
  already makes (no new read), the open position the poller read with the buy (Polymarket's positions, which give
  the price now) less the contracts this alert's buys add up to, plus any of it they sold since the first of those
  buys, is worth $1 or more at what they paid and over 1% of the position (`_held_before`). When Polymarket's
  positions haven't caught up with the buy, that can only call an add a first buy (an alert too many), never skip a
  first buy. While `paused_until` is ahead, nothing from that trader comes, buys or sells; otherwise a sale of
  something their alert told you about always comes, whatever the rule (`_told`). A buy the rule skips never joins a
  grouped alert. Big-trade alerts have no rules. In Telegram (`_on_rule`, buttons `r…:<wallet>`): right after a follow
  with Telegram connected (from the site or the bot's Follow link), "You're following X. They made about N trades a
  day last week. Choose which ones reach you?" (the pace sentence only when `_measure_pace` measured it; it replaced the
  busy-trader warning) with Set my rule / Every trade. It is the one message that names the trader (owner, 11 Nov:
  the name once): a follow from the bot's link sends no "You're following X" of its own (a new chat gets the help
  with no names in it first), and waits at most 8 s for the pace (`FOLLOW_PACE_WAIT_S`), then asks without it. Set my rule is three steps (the smallest buy: $100, $500,
  $1,000, the amount about 3 of their buys a day reached last week worded as an estimate, never a promise, or Type my
  own; which markets; what to skip: "Adds to a position they already hold", "Prices above 90¢ or below 10¢"), each
  saved at once, then "Saved: X" with the rule and, only when the pace measure already read it (the whole week, under a
  day old, a rule of amount and prices only), "About N buy alerts last week instead of M." "Markets with little
  trading" is left out: the engine has no fresh volume for a market without a new read. Type my own: the chat's next
  plain message is the amount ("750", "$750", "1,000"), else "That's not an amount. Send a number, like 750." and it
  keeps waiting; the wait is per chat in alerts.db (`typing`, so a deploy doesn't lose it), ends after 10 minutes, and
  any /command cancels it. Under an alert about one trader: Edit rule (the rule; Minimum size, Markets, Skip,
  Delivery, and "Stop alerts from X") and Pause 24 h ("X paused for 24 hours." with Undo), then Useful / Not useful.
  /rules lists everyone you follow, a line and a button each. Alerts sent before 10 Nov keep "Stop alerts" (`unf:`)
  and "Fewer alerts" (`few:`, `am:`), which still work. The suggested amount and pace come from `_measure_pace`, kept
  in alerts.db `pace`. At most 200 alerts per person per UTC day (a safety limit), then
  one message that says how long until alerts resume ("Alerts resume in 5 h 12 min": no clock time; the day ends 00:00 UTC) and nothing until the next day. When 2+ traders you follow buy the same outcome, each within 6 hours of the one before (1 hour in
  Sports and Esports), the second buy sends one grouped alert (each one's price and how long ago they bought, the
  price now) and later buys edit it in place; it counts once. Every alert has
  "Useful / Not useful" (one vote per alert and account, changeable). Big trades ($10,000 or more) in your chosen
  markets alert you whoever the trader, with the same facts, at most 5
  a day within the daily cap. Only a choice made where the page asks (onboarding, or the Feed's "Your markets · Change")
  is kept on the account (per account like follows); Traders' chips only filter the view, and nothing saved or []
  (Skip, all markets) means no big-trade alerts. An alert is never "you can still get in" and never green.
  Every alert and trade card keeps the link to the market, whoever the trader. The Feed says
  how late it can be for where its trades come from, never a blanket figure and never "instant": a trader you
  follow is read on their own about every 30 seconds (Polymarket returns their trades there within seconds); big trades
  come from Polymarket's feed of every trade, which typically runs 3–5 minutes behind (the Feed's Big trades).
  Telegram alerts no longer carry the "Traded 14:02 UTC, 6 min before this alert." line or the delay sentences
  ("Signals typically reads…", "Big trades come from…"): the owner's decision, 10 Nov ("too much words"; people think
  in PST/EST, not UTC). A trade's time is its Polymarket timestamp (its transaction's block time), and every alert
  measures from it ("6 min ago"). The website's delay notes stay. The engine checks Clerk's session token itself (public keys,
  no Clerk secret). Never let one account see or change another's follows, and never let an answer about a
  signed-in person be cached.
- The weekly email (`signals/weekly.py`, owner 11 Nov 2026, Layer's weekly update for Signals): the only email to
  every account. Drafted by Claude from the week's merged pull requests the afternoon before the send day, previewed to
  the owner, and sent only after the owner clicks "Approve and send" (never by a session, never without that click);
  9 AM in each reader's time zone; every email has a one-click unsubscribe, and an unsubscribed reader is never
  emailed again. The writer's rules (`SYSTEM`) keep only what every user can open today: nothing owner-only or behind
  a flag (copying, the skill test, Kalshi), the page's words ("trade", never "bet"; never "copy", "paper",
  "sandbox"), no advice and nothing that implies following makes money; a draft that breaks one is flagged in the
  owner's preview (`NEVER`).
- The owner's alerts (`signals/owner_alerts.py`, README "When something breaks"): a Telegram message to the owner
  (`SIGNALS_OWNER_USER`'s connected chat, or `SIGNALS_OWNER_CHAT`) when the disk is 85% full, a page answers 500, or
  trader scoring fails for 30 min (2026-11-02→04: a full volume broke Traders for ~50 hours and nobody knew). Sent
  straight through `tg`, never through alerts.db or anything on the disk, and kept in memory only: they must work when
  the disk is what broke. Told once, every 6 hours while it lasts, and "fixed".
- Deploys and changes to the hosting (Railway, Vercel, the domain) only when the owner asks.
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
    "Sold", never guessed. Its explanation is facts (no verdict, nothing about what happens next), every change label
    neutral, and every buy keeps "Check your price". The one exception is one sentence under the headline written by
    AI (owner, 23 Oct; `signals/why.py`, Claude Haiku 5.5 through OpenRouter, off without `OPENROUTER_API_KEY`),
    labelled "Written by AI from the facts below": the engine picks the one or two facts that stand out and works out
    every figure, the model only joins them, and a sentence with a number or a comparison its facts don't have, a
    guess, advice or "bet" isn't shown. Nothing stands out, or it failed: no sentence, never a placeholder. Keep the
    model to wording: never hand it a fact to judge or a figure to work out.
  - Baskets (owner, 28 Oct: "when deciding on a trade, show me whether several traders I trust agree"): tabs over the
    Watchlist, "Everyone you follow" (the cards) first. A basket is a name and 2+ traders you follow (follows.json
    `baskets`, at most `MAX_BASKETS`; unfollowing takes a trader out). Its view (`/api/me/baskets/<id>/view`,
    `signals/basket.py`) is where they agree (most of a market's holders in the basket on one side, 2 or more) and
    where they split, from what each holds now: one positions read per trader on the checks' budget, kept
    `HELD_TTL_S` for everyone, `BASKET_READS` at a time so "Check now" keeps a turn; a trader whose read failed is
    left out and named. Holding a side means $10+ put in at a price still open (2¢–98¢). Counts and what they paid
    are facts, never a verdict or a promise; "Market price now", not a price you can buy at; buys keep "Check your
    price". The view is consumer-simple (owner, 29 Oct: "too much text"): one Agree / Disagree switch, a card per
    market, a row per trader (a bar for their share of the side's money, what their position is worth now, never what
    they once put in, and their last buy or sell of it with an arrow); tapping a row shows when they opened it, what
    they paid, bought and sold, and its rank among their own open positions. No explainer paragraphs, no "latest
    changes" list. Each card opens with one plain line (owner, 30 Oct: show whose money it is and what they're doing):
    "Mostly X's money" (one trader has `basket.MOSTLY` of it), "Led by X" or "Shared evenly" (within `basket.EVEN`),
    with the dollars ("$211K of the $245K on Yes"), then what they did last, a move being their trades one way each
    within `watch.MOVE_S` of the one before ("They sold $67.6K of it yesterday"; over more than a day, "since Oct 28").
    Times follow the viewer's calendar. No score, no verdict. The history is one more read per trader of their trades in just the markets they agree on (the
    SDK's Polymarket reader, `BASKET_HISTORY_IDS` markets a read, kept like the positions), so a busy trader's is
    whole. A fact that wasn't read (a failed read, or more trades than `BASKET_HISTORY_ROWS`) is left out, never
    guessed or shown as "no trades".
  - Onboarding (the first Feed page once signed in, once per browser; the owner, 7 Nov: a signed-out visitor lands on
    the Leaderboard, and the Watchlist signed out says what it does, with "+ Follow a trader" and an example watch
    page, before Sign in) asks one question: which markets interest you (Politics, Sports,
    Crypto, Esports; Skip means all markets), with Sports already picked (owner, 29 Oct: niching to sports; people
    from X picked it first). The Leaderboard opens on the one market picked (`boardCatOf`: Sports before any
    choice, All for Skip or several). Nothing else: no budget, goals or signup. The choice is kept in
    localStorage (and, when picked here or with the Feed's Change, on the account for big-trade alerts), every read and write in try/catch; if storage is blocked it holds for the visit, and no one is
    ever stuck on that screen.
  - With the skill test on only: two separate readings, never merged: profit (track record) and skill (the tier). The tier is skill and track
    record only (uselayer 0.10's `segment`; a kept older result is re-tiered with the SDK's `segment_of`). Nothing
    may present a trader's activity as a tested way to make money: following and the Feed are for learning what
    traders do, not a signal to buy (`NOT_A_TIP`).
  - No copy estimate on the page or in alerts (the owner, 18 Oct: it isn't reliable yet). The engine still works
    out a copy status (`copy_status`, `copy_offer`; `copy_label`, `copy_ok`, `copy_why`, `copy_return…` in the API)
    from the SDK's `copyable`, but nothing anyone sees shows it or follows it: no copy status, figure, range,
    column, sort, filter, "Copying is paused" callout, How-we-pick tab, copy line in an alert, the SDK's
    "Copyable" check on a trader page, or colour (an open trade reads the same for every trader). A guard test
    keeps the page's words free of "Copy", "Copyable" and "Copying". Bringing it back is the owner's call.
  - Traders is the Leaderboard (above): facts only, no tier, chip, "Sharp", "Recommended" or "Why they're here".
    Only with the skill test on (`SIGNALS_SKILL_TEST=1`), the old way back: Traders lists the traders we recommend
    in one section, **Sharps** (the engine's `section_of`: every recommended tier), with its ranks and "Show more" in the sort picked (by default Recommended's tier order); "See all checked
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
    and never "it holds without their best trades" (not shown for them). For everyone, whichever list: an open trade (their page, a Feed card, a trader page) says only "Now 52¢ · they paid 49¢", for every
    trader, never green or "you can still get in". The "Buy on Polymarket" link, which only opens the market, "Check your price" and "What buying now
    costs" stay for everyone: neutral market data. Every figure names its period: only profit and trend follow the 7D/30D/90D switch; on a trader's
    profile, "Their numbers" shows 7, 30 and 90 days side by side (profit taken, per $ traded, win rate) and its switch moves the chart only; consistency is 12 weeks,
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
    With the skill test on, recommendations never include Big profit, edge unproven; Profit rests on one win (big profit that's a loss
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
    `categories_round`) reads each recommended trader's realized profit by category once a day (with the skill test
    off there are no recommended traders, so it reads no one, and a profile reads its own on demand) on the
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
  - Methodology (tests, z-scores, margins) stays out of the main view: in a Details fold.
  - No wallet addresses on screen: unnamed traders get "Trader 0x91…76" and an identicon.
  - Must look good at 390px as well as desktop. One width: the header, Feed, Traders and trader profiles share
    the 1200px container (Top profit keeps a 680px reading column), so the account sits at the header's right and
    nothing moves between tabs. Feed cards are a grid: three across on desktop, one on a phone. Keep loading,
    empty and error states.
  - The Feed has two parts. **Following** (`#/`, the default, `/api/me/feed`): every trade from the last day of
    the traders you follow, whoever they are (following is also research). **Top traders** (`#/recommended`, `/api/live`, `pool` "top"): trades of $1,000 or more (`RECOMMENDED_MIN_USD`) from
    the Leaderboard's first `FEED_TOP` by trading profit over 30 days (with the skill test on, this part is
    **Recommended**, from the traders in Sharps), with the same neutral cards as Following. It
    stays quiet (fewer, bigger trades) and never more prominent than Following: second in the switch, never the
    default. Both keep the switch "Only trades I can still get into", one card per outcome with "Also bought
    by", and the delay line. Big trades (`#/big`) is linked from the foot of Top traders. Traders' trades come from
    one background poller (`_live_loop`, one read at a time, in 30 s rounds: everyone followed each round,
    Top traders' every 60 s while the round's slot allows, oldest first, so a bigger pool is read less often,
    never faster). Per trader it reads their trades, and their open positions only when there's a trade from the
    last day to price (kept while their trades don't change, for 90 s); never the profile or stats. Polymarket's
    shared $1,000+ trades feed (one read for everyone) moves a top trader who just traded to the front.
    Pages only read what it keeps, so a busy Feed never adds Polymarket reads: a view reads at most 3 traders the
    poller hasn't read yet itself ("Still reading N traders"), and "Updated" is when the oldest of it was read.
    The Feed never says "None of … traded" for traders it hasn't read: it says it's still reading them, or that
    they couldn't be read, and notes when some of it was last read over 5 minutes ago. Everyone followed is read
    once every round however many there are (Top traders keeps a floor of 4 reads a round); alerts read what the
    poller keeps, never on their own; a gap of more than 100 trades between reads is read further back (500);
    a rate limit ends the round.
  - Market chips live on Traders only. The Feed follows the same choice and says so in one line ("Your markets:
    Politics, Sports · Change"); Change opens the onboarding picker. Never a second set of filter chips.
  - A trade at 2¢ or less, 98¢ or more, or no longer held is settled (Won / Lost / Closed), never a bargain
    (`bet_status` in `app.py`). "You can still get in" only from 5¢ below to 3¢ above what they paid; further
    either way is "Price moved away" (a big drop means the market turned against them, not a bargain).
- Pull requests: sessions never merge. Only the owner merges, when they say "merge #N".

## Research agent (`signals/research`, README "Research agent")

- Its own service, never inside the engine (`app.py`): no agent run, model call or research read in the engine's
  process. Its Polymarket reads go through the SDK on its own budget (`Budget(…, name="research")`).
- Every number it shows traces to data (`trace.py`): a figure that doesn't match a tool result or its code's printed
  output is never shown as fact (one retry, then flagged `unverified`). Don't loosen the check to make answers pass.
- Wording: "Research wording" below (confirmed by the owner, 10 Nov).
- Binance and Chainlink are different prices: never call one the other. Order books and Chainlink come only from
  Layer's recordings.
- Signed in only, and an investigation, its events and charts are only ever its owner's. Costs are capped per
  question, per person and per day (`RESEARCH_*_USD`); raising them is the owner's call.
- Signed out, `/research` is a teaser (owner, 10 Nov: tease visitors into signing up): what a breakdown is, "Sign in
  to ask your own", and "Watch a sample breakdown" (`?sample`): the recorded run fixtures mode plays (`fixtures.js`),
  question locked, no service call and no model spend. The Breakdowns tab carries a dotted accent outline
  (`class="new"`, main page and research page) for everyone while it's new; taking it off is the owner's call.
- Keys (`ANTHROPIC_API_KEY`) are set by the owner in the service's variables, never by a session.

### Research wording (confirmed by the owner, 10 Nov)

Research is for traders and researchers, so it may say more than the consumer pages (how a wallet trades, its
patterns, why it might trade that way), but the consumer rules above still hold: plain words, facts before
readings, no advice. The agent's instructions (`SYSTEM` in `signals/research/agent.py`, "# Wording") carry all
nine; change both together.

1. **Observed or Inferred, every finding.** Observed: what the data shows, with its numbers ("Observed: it bought
   Up in 41 of 52 windows, at 92¢ on average, in the last 90 seconds"). Inferred: a reading of why, said as a
   reading, with what would confirm or refute it ("Inferred: it seems to buy once the outcome looks settled. If so,
   its entries should cluster when BTC is far from the price to beat; the window chart shows that for 3 of 4
   windows"). Intent is never stated as fact: no "it's a bot", "it's front-running", "it knows".
2. **Every number traces to data** (`trace.py`), names its period and unit ("over 10 Nov 00:00–24:00 UTC", "$",
   "contracts", "¢ a contract") and is rounded the way the consumer pages round (whole cents; tenths only under 1¢).
   A figure that wasn't read is left out, never estimated; "Unverified" numbers are shown as such, never hidden.
3. **Say what's missing, plainly, where it matters.** Partial history ("Polymarket couldn't list every trade after
   14:02 UTC, so this covers 14:02 back to 00:00"), recording gaps, no order book, no Chainlink before 10 Nov 05:27
   UTC, maker vs taker unknown. One sentence each, never a disclaimer block.
4. **Prices by their names.** "Chainlink BTC/USD" (what windows settle on), "Binance BTCUSDT", "the price to beat",
   "the Up price on Polymarket". Never one called another, never "the BTC price" alone, never "mid".
5. **Profit is the window's or the period's, worked out from fills** ("made $212 on these 52 windows after what it
   paid; Polymarket's all-time figure is +$40.1k"). Never "ROI", "edge", "alpha", "smart money", "win streak".
   A strategy's past profit is never framed as something the reader could repeat.
6. **No advice, no predictions, no copying.** No "you could", "worth following", "likely to keep winning", "buy
   when". "Trade", never "bet". Nothing about placing orders.
7. **People.** The wallet asked about by its Polymarket name, else "Trader 0x91…76"; its full address only where the
   user typed it. Other wallets only shortened, never named as the same person as anyone ("likely"/"possible" with
   the evidence, as the consumer rule says). No judgments of the trader ("genius", "reckless", "manipulating").
8. **Shape.** One or two plain sentences first (the pattern in short), then findings, then what the data doesn't
   show. Short paragraphs, sentence case, times in UTC. Methodology (how a figure was worked out) only when asked,
   or one clause.
9. **Charts.** A plain title that says what's shown ("Window 10 Nov 04:30 UTC: BTC on Binance and Chainlink, their
   entries"), axes with units, a one-sentence caption. Green and red only for gains and losses; sides (Up/Down) in
   neutral colours. No chart of a figure the answer doesn't trace.

## Deploying (only when the owner asks)

- **Engine** (Railway project and service `signals`): `railway up --service signals` from the repo root. It
  builds the `Dockerfile`; the store is on the service's volume at `/data`. A deploy restarts the server, and
  record reads in progress start over (with the skill test on, an unfinished Worth following check takes 20–30 min).
- **From a worktree** (`.claude/worktrees/…`), run `railway up . --path-as-root --service signals`. Without
  `--path-as-root` it uploads the linked folder (the owner's main checkout), which can be stale: this briefly
  put old code live on 12 Oct.
- **After any deploy**, check the live page actually serves the new code: fetch https://usesignals.app and look
  for something only the new code has.
- **Forwarding layer** (Vercel project `signals`, holds usesignals.app): `vercel deploy --prod` inside `web/`.
  Only needed when `web/vercel.json` changes.
- A new checkout or folder isn't linked yet: run `railway link` (project and service `signals`) in the repo root
  and `vercel link --project signals` in `web/` first.
- Keys are set by the owner in Railway's service variables, never by a session.
- `railway.json` works until 2026-12-01; after that Railway needs `railway config migrate`.
