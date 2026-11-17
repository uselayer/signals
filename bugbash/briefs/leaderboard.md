# Leaderboard (desktop)

Start: `node bb.mjs start leaderboard` then `go https://usesignals.app/#/traders`

Try:
- The list loads in under ~8 s and every row has every column (profit, volume, win rate with the average price paid
  beside it, usual trade). The Leaderboard only lists complete rows, so a blank or "—" in a row is a bug.
- Each Human / Bot / Unknown pill matches its icon and colour (Human blue person, Bot amber robot, Unknown grey dashed).
- Switch every period and every market chip. The order and numbers should change sensibly, and the count in the
  foot should match what's shown.
- Sort by each sortable column, both directions.
- Search for a name you can see in the list, then for a wallet address (0x…), then for nonsense. Each should give a
  sensible result or a clear "nothing found".
- Open a trader from the list and come back with the browser Back button: the period, chip and scroll position should
  survive.
- Words: facts only. No "recommended", "smart money", tiers or advice anywhere.

Never press Copy or anything that buys, and never sign in.
