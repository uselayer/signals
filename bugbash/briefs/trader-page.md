# Trader page (desktop)

Start: `node bb.mjs start trader-page` then `go https://usesignals.app/#/traders`, and open traders from the list.

Open three traders: the top one, one with a Bot pill and one with a Human pill.

Try, on each:
- The page loads and shows the record: profit, volume, win rate with the average price paid, weeks up, usual trade,
  and the Human/Bot/Unknown pill. Numbers must match the trader's Leaderboard row (same period).
- If it says "Refreshing…", it should swap in new numbers or say plainly why it couldn't, and offer "Try again".
  It should never spin forever (wait up to ~30 s).
- Open trades show "What buying now costs". "Buy on Polymarket ↗" links must point to polymarket.com (hover to check
  them, don't buy anything).
- Long names, long market titles and big numbers shouldn't overflow or overlap.
- Paste a made-up wallet into the URL (`#/worth/0x0000000000000000000000000000000000000001`). It should say clearly
  that there's no record, not show a broken page.

Never press Copy, Follow or anything that needs an account, and never sign in.
