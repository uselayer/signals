# Pre-registered test: does pump.fun's profit leaderboard show skill or luck? (written 2026-10-21, before any wallet record was pulled)

## The question

pump.fun's leaderboard ranks traders by profit over a day, a week or a month. Is a place on it evidence of a
trader who wins repeatedly, or mostly of one coin that ran and hasn't been sold? The answer decides whether
honest track records for memecoin traders (what Signals does for Polymarket) have a story worth building on.
Nothing in Signals changes because of this test.

## Pool (fixed)

- The top 100 of each board (`daily`, `weekly`, `monthly`, default sort) from pump.fun's public
  `GET frontend-api-v3.pump.fun/pnl-leaderboard`, read once on 2026-10-21 and saved as `pumpfun-boards.json`.
- Each wallet is counted once per board. A wallet on several boards is pulled once.
- Window start W = the board's own `windowStartSec`.

## Records (per wallet)

- Every position from public `GET /user-portfolio/{wallet}?filter=all` (all pages, at most 50 pages = 5,000
  positions; capped wallets are reported).
- A position counts if it isn't `potentialSpam` and at least $10 went in (`amountBoughtUsd`).
- **Closed before the window:** `isExited` and `updatedAt` < W. Profit = `realizedPnlUsd`.
- **Win:** a closed position with profit > 0.
- **Trimmed:** the same total without the wallet's single best closed position.

## Measures

1. **Paper vs closed (board fields only).** Share of the board's total profit that is unrealized, and the
   number of wallets whose realized profit in the window is below zero.
2. **One coin.** For positions with `updatedAt` ≥ W, the share of their summed profit (`pnlUsd`) that comes
   from the single biggest one. A position's profit is its whole life, not just the window: stated, not fixed.
3. **Record before the window.** For wallets with ≥ 20 closed positions before W: total realized profit,
   trimmed total, win rate by count, and the share of money that went into winners.
4. **Warning signs.** Share of positions with `hasTransfers` (tokens arrived without a buy), and wallets
   with fewer than 5 positions in all.

## Verdict lines (monthly board, wallets with ≥ 20 closed positions before W)

- **Skill-like:** ≥ 60% have a positive trimmed total before the window, and the median trimmed total is > 0.
- **Luck-like:** ≤ 40% have a positive trimmed total.
- **Mixed:** anything between.

Weekly and daily boards are reported the same way, not judged.

## Not tested here

- Whether a record predicts the *next* week. The snapshot is saved so a forward check can be run on
  2026-10-28 with the same rules.
- Copying. On Polymarket, skill persisted and copying still lost after costs; memecoins are likely worse.
