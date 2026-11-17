# Bug bash: trader-page (desk)

Video: video.mp4 · 02:35 long · 2026-11-17T06:09:39.393Z

## Bugs (4)
1. **Their numbers table overflows its card** (video 00:34) — On the top trader's page the 7/30/90 days table is wider than its card: the 90 days column is cut off at the card edge and 'too many to count' runs past it.
   - Page: https://usesignals.app/#/worth/0x2c335066fe58fe9237c3d3dc7b275c2a034a0563
   - Screenshot: 04-bug-1.png
2. **No 'What buying now costs' on open trades** (video 01:18) — On the top trader's Positions and Recent trades, clicking or hovering rows did nothing; no Check your price or buying-cost entry anywhere (only a Polymarket link and 'No verified US match found').
   - Page: https://usesignals.app/#/worth/0x2c335066fe58fe9237c3d3dc7b275c2a034a0563
   - Screenshot: 12-bug-2.png
3. **30-day profit differs from the Leaderboard row** (video 01:53) — BreakTheBank's board row says +$1.8M over 30D (+2.9% per $62.7M traded), but the trader page's 30 days column says +$2.9M profit taken, with the same +2.9% per $ traded.
   - Page: https://usesignals.app/#/worth/0xf0318c32136c2db7fec88b84869aee6a1106c80c
   - Screenshot: 15-bug-3.png
4. **Made-up wallet shows a broken page, not 'no record'** (video 02:13) — Opening #/worth/0x…0001 gave a 502 from the trader API, a Human pill, a $10 wallet, empty tables and a raw red 'polymarket doesn't know that: profile not found' with Follow still offered; no plain 'no record' message.
   - Page: https://usesignals.app/#/worth/0x0000000000000000000000000000000000000001
   - Screenshot: 17-bug-4.png

## Checks passed (3)
- 00:37 Top trader page loads with record, Bot pill, avg price 56¢, weeks up 7 of 12, usual trade $50K matching the board
- 01:56 Human trader page loads: Human pill, avg price 57¢, 8 of 12 weeks up, usual trade $74.4K match the board; Open P&L filled in after loading
- 02:15 Made-up wallet page doesn't crash or spin forever

## Steps
- 00:00 go https://usesignals.app/#/traders Opening the Leaderboard
- 00:08 click text=Trader 0×2c…63 Opening the top trader (a Bot) → FAILED: locator.scrollIntoViewIfNeeded: Timeout 8000ms exceeded.
- 00:23 click text=/Trader 0.2c…63/ Opening the top trader (a Bot)
- 00:34 bug Their numbers table overflows its card On the top trader's page the 7/30/90 days table is wider than its card: the 90 days column is cut off at the card edge and 'too many to count' runs past it.
- 00:37 ok Top trader page loads with record, Bot pill, avg price 56¢, weeks up 7 of 12, usual trade $50K matching the board
- 00:39 scroll 700 Scrolling to open trades
- 00:43 hover a:has-text("Polymarket International ↗") >> nth=0 Hovering the Polymarket link
- 00:45 click text=Pepperdine Waves vs. Oregon Ducks Opening an open trade
- 00:53 click text=Now 50¢ · they paid 88¢ Tapping the trade's status to open its price check
- 01:00 click text=Recent trades Opening Recent trades
- 01:08 hover text=Singapore vs. Brazil: O/U 5.5 >> nth=0 Hovering a trade row for its price check
- 01:10 click text=Singapore vs. Brazil: O/U 5.5 >> nth=0 Clicking the trade
- 01:18 bug No 'What buying now costs' on open trades On the top trader's Positions and Recent trades, clicking or hovering rows did nothing; no Check your price or buying-cost entry anywhere (only a Polymarket link and 'No verified US match found').
- 01:21 go https://usesignals.app/#/traders Back to the Leaderboard
- 01:24 click text=BreakTheBank Opening a Human trader
- 01:53 bug 30-day profit differs from the Leaderboard row BreakTheBank's board row says +$1.8M over 30D (+2.9% per $62.7M traded), but the trader page's 30 days column says +$2.9M profit taken, with the same +2.9% per $ traded.
- 01:56 ok Human trader page loads: Human pill, avg price 57¢, 8 of 12 weeks up, usual trade $74.4K match the board; Open P&L filled in after loading
- 01:57 go https://usesignals.app/#/worth/0x0000000000000000000000000000000000000001 Trying a made-up wallet
- 02:13 bug Made-up wallet shows a broken page, not 'no record' Opening #/worth/0x…0001 gave a 502 from the trader API, a Human pill, a $10 wallet, empty tables and a raw red 'polymarket doesn't know that: profile not found' with Follow still offered; no plain 'no record' message.
- 02:15 ok Made-up wallet page doesn't crash or spin forever

## Console and network errors (3)
- 00:02 console: Failed to load resource: net::ERR_TUNNEL_CONNECTION_FAILED
- 02:00 HTTP 502 GET https://usesignals.app/api/trader/polymarket/0x0000000000000000000000000000000000000001
- 02:00 console: Failed to load resource: the server responded with a status of 502 (Bad Gateway)
