# Copying pump.fun's top traders fast: copying the bots loses, at any speed

Plan: `pumpfun-copy-preregistered.md` (with its dated changes). Numbers: `pumpfun-copy-results.txt`. Data:
`pumpfun-copy-trades.jsonl.gz`, 30 bot-paced and 30 people-paced wallets from the 2026-10-21 boards, every trade in
the 72 hours before each was read, and each coin's next trades 0–10 blocks later, from pump.fun's public API.

## Bots: the copy loses even when it lands in the same block

| Copy lands | Return before costs | After 1% per side | Bot wallets whose copy made money (1%) |
|---|---|---|---|
| Same block, right behind | −9.4% | −11.3% | 8/29 |
| ≈0.4 s (1 block) | −9.7% | −11.6% | 6/29 |
| ≈1.2 s | −10.0% | −11.9% | 7/29 |
| ≈2 s | −7.2% | −9.2% | 7/29 |
| ≈4 s | −3.8% | −5.8% | 7/29 |

The bots themselves made **+6.1%** on the same 1,056 coins ($481K in). **Pre-registered verdict: copying does not
work.**

Why: a bot buys first and other buyers pile in behind it, often in the same block, so a copier's buy price is
already higher. Then the bot sells into those buyers within seconds. One example: the month board's #1 bought a
new coin, and seven other buyers in the same block lifted the price 72%. The bot sold 3–6 seconds later at
roughly 30–45% above its own buy, which is below where a copier would have bought. Faster doesn't fix it; the copier
*is* the crowd the bot sells to.

This is the best case for the copier: it ignores the copier's own effect on the price, and the bias below favours
copying.

## People: copying matched their result, and speed didn't matter, but it isn't evidence yet

- 22 of 30 traded in the window, across 232 coins. They made +18.1%; a copy at 1% per side made about **+19%** at
  every delay (15 of 22 copies made money).
- **46%** of the copy's end value is coins still held, valued at their latest price.
- They were picked for a good recent run over the same days, so this is in-sample. The fair test is forward:
  `pumpfun_copy_collect.py --since 1792618459` on the same wallets, a few days from now.

## What it means for the product

- Signals shouldn't offer fast copying of bot-paced wallets. It loses money for the user however fast it is.
- For people, speed isn't the edge. Seconds made no difference, so alerts or a slower mirror lose nothing to a
  millisecond bot. Whether copying people works at all is the open question, and the forward run answers it.
- An honest leaderboard should label bot-paced wallets as "not copyable".

## Limits

- 72 hours, 60 wallets, one snapshot of the boards. Up to 40 coins and 30 trades per coin per wallet.
- About 6% of bot trades (293 of 4,461) had no later trade on the coin; those use its latest price.
- 3 coins were skipped after repeated rate limits. 8 people and 1 bot had no trades in the window.
- Costs are assumed (0/1/2% per side). Dawn's copy fee and speed are unpublished.

## Forward run (first 6–7 hours after the boards were read)

`pumpfun-copy-forward-results.txt`: the same 60 wallets, trades from 2026-10-21 2:34 PM PT to ~9:20 PM PT.

- **Bots:** confirmed out of sample. They made +5.7%; a copy at ≈0.4 s lost −6.5% before costs and −8.5% after 1% per
  side (8 of 23 copies made money).
- **People:** too thin to judge. Only 7 of 30 traded (16 coins, 38 trades, $12.6K). The pooled copy was +25% after
  1% per side, but 68% of it is unsold and the median copy was −0.8%, with 3 of 7 making money. Re-run with
  `--since 1792618459` after ~2026-10-24 for a real answer.
