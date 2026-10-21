# pump.fun's profit leaderboard: people on it look lucky, the consistent winners are bots

Plan: `pumpfun-preregistered.md` (written before any record was pulled). Numbers: `pumpfun-results.txt`
(pre-registered) and `pumpfun-followup.txt` (split by trading pace, **not** pre-registered). Data: the top 100 of
pump.fun's daily, weekly and monthly boards read 2026-10-21 2:34 PM PT, 206 wallets, every position from
pump.fun's public API (no keys). Raw positions (39 MB) are outside git in
`~/dev/research-data/pumpfun-2026-10-21/`.

## What the boards show

| | Day | Week | Month |
|---|---|---|---|
| Board profit that is still unsold | 77% | 75% | 22% |
| Traders whose biggest coin is ≥ half their gains | 90% | 74% | 27% |
| Profitable before this run, without their best coin | 36% | 49% | 84% |

The pre-registered verdict on the monthly board is **skill-like**. It doesn't mean what it seems to.

## Who the consistent winners are

Splitting by how many different coins a trader touched per day in the window:

| Monthly board | Traders | Board profit unsold | Typical position | Profitable before, without best coin | Win rate |
|---|---|---|---|---|---|
| Under 5 coins/day (people) | 26 | 72% | $1,689 | 5/14 (36%) | 33% |
| 5–20 coins/day | 7 | 1% | $746 | 3/6 (50%) | 35% |
| 20+ coins/day (bots) | 67 | 2% | $236 | 63/65 (97%) | 100% |

The daily and weekly boards split the same way. Human-paced traders there: 15–17% profitable before the run
without their best coin, median −$32K to −$41K, 29% win rate, about 90% of their board profit unsold. The 20+
coins/day group: 87–97% profitable, 86–98% win rate.

## What it means

- **The people on these boards mostly hold one coin that ran and haven't sold it.** Before this run, most of
  them were losing money. A place on the day or week board is close to no evidence of skill.
- **The traders who win every time are bots** (sniping, market-making or similar): thousands of coins, small
  positions, near-100% win rates. Their record is real but it isn't something a person can follow.
- **So the honest-record angle has a real story:** pump.fun's board mixes paper gains, one-coin luck and bots,
  and doesn't say which is which. Separating them takes only the public data used here.

## Limits

- A position's profit is its whole life, not only the window; `updatedAt` is its last activity.
- Wallets with over 5,000 positions were cut at 5,000 (18 day, 26 week, 55 month). All are bot-paced.
- One snapshot. Whether a record predicts the next week is untested; the boards are saved for a 2026-10-28
  re-read under the same rules.
- "Bot" is inferred from pace (20+ coins a day), not confirmed.
