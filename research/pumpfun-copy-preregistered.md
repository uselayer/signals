# Pre-registered test: can you make money copying pump.fun's top traders fast? (written 2026-10-21, before any copy was replayed)

## The question

`pumpfun-findings.md` found that most consistent winners on pump.fun's boards trade like bots (20+ coins a day,
~100% win rate). The idea: copy them, buying when they buy and selling when they sell, within milliseconds. Does
a copier make money, and how fast does it have to be? Nothing in Signals changes because of this test.

## Wallets (fixed)

From the 206 wallets in `pumpfun-boards.json`, by pace in the study (distinct coins per day in a board's window,
the fastest board counting):

- **Bots:** 20+ coins/day. Up to 30, picked in a seeded random order (seed 21).
- **People:** under 5 coins/day. Up to 30, same seed.

## Trades (per wallet)

- The wallet's trades from public `GET /user-trades/{wallet}` over the 72 hours before the run, at most 3,000.
- A coin counts if the wallet's first trade on it in those 72 hours is a buy. Up to 40 coins per wallet, seeded
  random; up to 30 trades per coin.

## The copy

- For each of the leader's trades, the copier trades the same dollar amount (buys) or the same share of its
  holding (sells), at the price of the first other trade on that coin's public tape
  (`GET /trades/{chain}/{mint}`) that lands **k blocks** after the leader's trade.
- **k = 0:** the very next trade in the same block, which is only possible if the copy lands right behind the
  leader. **k = 1, 3, 5, 10** ≈ 0.4, 1.2, 2 and 4 seconds.
- Tokens still held at the end are valued at the coin's latest tape price. The leader is valued the same way
  using their own prices, as a check.
- The copier's own effect on the price is ignored, so the results are the **best case** for the copier.
- Costs: shown at 0%, 1% and 2% per side (venue fee, priority fees, the copy service's cut).

## Measures

Per group and delay: return on money in (all coins pooled), the share of wallets whose copy made money, and the
leader's own return on the same coins.

## Verdict line

**Copying works** if, at k = 1 with 1% per side, the bot group's pooled return is > 0 **and** at least half the
bot wallets' copies made money. Otherwise it doesn't. People are reported the same way, not judged.

## Changes after the plan (2026-10-21, written before the full results were read)

- **Excluded coins:** wrapped SOL and dollar coins (USDC, USDT, USD1). They aren't memecoins, and wrapped SOL's tape
  is too busy to page. Applied to every wallet.
- **Retries:** the first pass hit pump.fun's rate limits; 30 wallets were re-read later with slower requests.
  Their 72 hours end at their own read time (`readAt` per wallet), up to ~2 hours after the first pass.
- **Selection bias, stated:** wallets were picked from boards ranking the recent days, and the 72 hours overlap that
  period. That favours copying. A bot loss is therefore conservative; a people gain is not evidence. A forward
  run on trades **after** 2026-10-21 2:34 PM PT is the fair test for people.
