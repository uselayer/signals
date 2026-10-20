# Pre-registered study: does mixing trading activity with news give a strategy? (written 2026-10-19, before any outcome was computed)

## Why

The owner wants an intelligent trading workspace: one place that puts a market's price, the big money in it and
the news about it on one timeline, and turns an idea into a rule you can test on the past and then watch live.
Before building it, this study asks whether that mix tells you anything a price chart alone doesn't. Two
questions, both on plain facts only (no skill test, no trader verdicts):

1. **News spikes.** When a market jumps on news, does the jump hold, keep going, or fade?
2. **Big money and news.** Do big buys made before any news on a market do better afterwards than big buys made
   after the news was out?

Nothing in Signals or the SDK changes because of this study. It reads public data only.

## Dates (fixed)

- **Period P** = 2026-08-01 00:00 UTC to 2026-10-12 00:00 UTC (72 days). Events are taken from P only.
- **Outcome window** = up to 72 hours after each event, or the market's settlement if sooner. 2026-10-12 leaves
  7 days so every event's 72 hours has happened.
- Polymarket serves 5-minute prices for all of P (checked 2026-10-19: 1,153 five-minute points for Aug 1–5 on a
  closed market).

## Markets (no hindsight)

- Polymarket markets with total volume ≥ $100,000 that traded during P, open or closed, from Gamma.
- Categories from the SDK's `category_of`. **Sports and Esports games are kept out of the news questions**:
  their moves come from the game, not the news. They're counted in a price-only row, reported separately.
- One outcome per market (the first token, "Yes"). Parlays never count.
- If more than 1,500 markets qualify, 1,500 are drawn at random (seed 19), stratified by category.

## Study 1: news spikes

**A spike** is a move of 10¢ or more within 60 minutes, measured on 5-minute prices, where:

- the price before was between 10¢ and 90¢;
- it starts at least 24 hours before the market's end date (moves into settlement are not news reactions);
- it is the first spike in that market that day (one per market per UTC day, so one story isn't counted many
  times).

Its **start** is the last 5-minute point before the move began, its **top** the extreme within the 60 minutes.

**News found for it.**

- GDELT's DOC 2.0 API, from 24 hours before the start to 6 hours after: English articles with their first-seen
  time (15-minute steps).
- The query is the market's subject: the named people, places or organisations in its title (written once per
  market, before any prices are looked at, and kept in `workspace-queries.json`).
- An article counts as about the market when its headline names that subject. 100 matches, drawn at random
  (seed 7), are checked by hand. The share that are really about the market is reported. If it's below 80%, the
  rule is tightened once, and both versions are reported.

**Groups.**

| Group | Rule |
|---|---|
| **News first** | an article seen before the start, or within 15 minutes after it |
| **News later** | the first article seen 15 minutes to 6 hours after the start |
| **No news found** | none within 6 hours |

GDELT's 15-minute steps mean "news first" can't be split finer. The report says so.

**Outcomes (each separately).**

- **Kept share** at 6, 24 and 72 hours: (price then − price at start) ÷ (price at top − price at start). 1 means
  the whole jump held, 0 means it all came back, above 1 means it kept going.
- **Fade trade:** take the other side 15 minutes after the top and hold for 24 hours (or to settlement). Profit
  per $1 is net of costs: 1.5¢ per side, with 0.5¢ and 3¢ shown too. Polymarket's past order books aren't
  available, so costs are assumed, not measured, and the report says so.
- **Follow trade:** the same, but on the jump's side.

## Study 2: big money and news

**A big buy** is one wallet buying one outcome for $5,000 or more within 30 minutes, adding up its fills of
$1,000 or more. These come from Polymarket's trades for each market (`filterType=CASH&filterAmount=1000`).
Single fills of $10,000+ are rare: on Brazil's $15M "Tarcísio" market there were 2. Smaller fills are left out,
so a big buy made of many small fills is missed. The report says how many markets hit Polymarket's paging
limit, so their oldest trades are missing.

Other conditions:

- The price paid is between 10¢ and 90¢.
- The buy starts at least 24 hours before the end date.
- At most 3 per market per day: the largest.

**Groups.** Same news rule as Study 1, around the buy's first fill:

| Group | Rule |
|---|---|
| **Before news** | no article in the 24 hours before the buy, and one within 24 hours after |
| **After news** | an article in the 6 hours before the buy |
| **No news found** | none within 24 hours either side |

**Outcomes.**

- Price move in the buy's direction at 6, 24 and 72 hours, from the price 15 minutes after the buy (when someone
  who saw it could act), net of 1.5¢ per side.
- Settlement where settled.
- The wallet's place on Signals' Leaderboard today is reported, never used.

## Statistics

- Ranges are 95% from a bootstrap over markets (2,000 resamples, seed 1), because spikes and buys in one market
  aren't independent.
- Each result is shown for the first and second halves of P separately (split at 2026-09-06).
- No other cuts are tested for a pass. Category splits are shown for description only.

## What counts as a yes (fixed now)

A rule **passes** if all of these hold:

- its net profit per $1 at 1.5¢ costs has a 95% range above zero;
- it is above zero in both halves of P;
- it has at least 100 events from at least 40 markets.

| Question | Yes if |
|---|---|
| **Study 1** | the fade trade or the follow trade passes in at least one news group, **and** that group's kept share differs from the no-news group by a range that excludes zero. Then news tells you something the price doesn't. |
| **Study 2** | "before news" buys pass, **and** beat "after news" buys by a range that excludes zero |

Both "no" is a real answer: the workspace would then be a research timeline, not a strategy tool.

## Sizes (expected, not required)

- About 300–600 non-sports spikes and 1,000–3,000 big buys.
- GDELT allows one request every 5 seconds: about one query per spike and per buy market, roughly 2–4 hours in
  all.
- Polymarket reads are paced at 3 per second.
- No paid data and no AI calls. Headline matching is the keyword rule above, checked by hand.

## What happens with the answer

| Answer | Next |
|---|---|
| **Yes to either** | Write up the passing rule. Sketch the workspace around it: a market timeline (price, big buys, news), the rule as an alert, and its past results beside it. |
| **No to both** | Report it. The timeline may still be worth building as context, but not sold as a strategy. |

Whether the workspace places orders is the owner's decision and is not part of this study. Signals places none
today.

## Files

Scripts and results go in `research/` as `workspace_*.py`, `workspace-results.txt` and `workspace-findings.md`.
