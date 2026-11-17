# Bug bash: phone (phone)

Video: video.mp4 · 01:56 long · 2026-11-17T06:09:04.352Z

## Bugs (5)
1. **Trader names cut to 'Trad…' on phone leaderboard** (video 00:17) — On the 390px Leaderboard, rows show names truncated to 4 letters ('Trad…', 'Brea…', 'UpT…') because the Bot/Human pill and sparkline squeeze the name column; expected a readable name.
   - Page: https://usesignals.app/#/traders
   - Screenshot: 03-bug-1.png
2. **Home URL opens Breakdowns, not the main site** (video 00:20) — Opened https://usesignals.app/ and landed on the Breakdowns teaser (no Feed/Watchlist/Traders tabs); expected the main site home.
   - Page: https://usesignals.app/#/traders
   - Screenshot: 04-bug-2.png
3. **Their numbers table spills past its card** (video 00:51) — On a trader page at 390px the 90-day column ('+$1.3M', 'too many to count') runs past the right edge of the card; expected it to fit.
   - Page: https://usesignals.app/#/worth/0xa19cbababc312f9df185e49d7004c249ed1ade6b
   - Screenshot: 10-bug-3.png
4. **Profit chart axis labels unreadably small** (video 01:03) — On the trader page the chart's axis labels (+$83.2K, 30 days ago, 2h ago) render at about 6px; expected readable text on a phone.
   - Page: https://usesignals.app/#/worth/0xa19cbababc312f9df185e49d7004c249ed1ade6b
   - Screenshot: 14-bug-4.png
5. **Sample question box cuts the question mid-sentence** (video 01:43) — On the phone sample page the question box shows 'Analyze this wallet's BTC 15-minute trades. Plot ... show how its positions' and stops; the rest can't be seen or scrolled to without pressing Break it down.
   - Page: https://usesignals.app/breakdowns/?sample
   - Screenshot: 18-bug-5.png

## Checks passed (4)
- 01:06 Leaderboard chips and period switch fit without sideways scroll
- 01:07 Leaderboard foot text and Top profit link readable
- 01:45 Sample page has no sideways scroll and the header fits
- 01:47 Trader page Human/Bot pill reads clearly beside the name

## Steps
- 00:00 go https://usesignals.app/ Opening the home page on a phone
- 00:08 go https://usesignals.app/#/traders Opening the Leaderboard
- 00:17 bug Trader names cut to 'Trad…' on phone leaderboard On the 390px Leaderboard, rows show names truncated to 4 letters ('Trad…', 'Brea…', 'UpT…') because the Bot/Human pill and sparkline squeeze the name column; expected a readable name.
- 00:20 bug Home URL opens Breakdowns, not the main site Opened https://usesignals.app/ and landed on the Breakdowns teaser (no Feed/Watchlist/Traders tabs); expected the main site home.
- 00:23 scroll 700 Scrolling the list
- 00:30 scroll -2000 Back to the top
- 00:31 click text=Crypto Picking the Crypto market chip
- 00:33 click text=90D Switching the period to 90 days
- 00:35 scroll 8000 Scrolling toward the foot
- 00:36 scroll 8000 Further
- 00:41 scroll -9000 Back up
- 00:42 click text=Tokor Opening a trader page
- 00:51 bug Their numbers table spills past its card On a trader page at 390px the 90-day column ('+$1.3M', 'too many to count') runs past the right edge of the card; expected it to fit.
- 00:54 scroll 650 Scrolling the trader page
- 00:55 scroll 650 Scrolling the trader page
- 00:56 scroll 650 Scrolling the trader page
- 01:03 bug Profit chart axis labels unreadably small On the trader page the chart's axis labels (+$83.2K, 30 days ago, 2h ago) render at about 6px; expected readable text on a phone.
- 01:06 ok Leaderboard chips and period switch fit without sideways scroll
- 01:07 ok Leaderboard foot text and Top profit link readable
- 01:09 go https://usesignals.app/breakdowns/?sample Opening the sample breakdown
- 01:19 click text=0xb945 Tapping the wallet field (market picker) → FAILED: locator.scrollIntoViewIfNeeded: Timeout 8000ms exceeded.
- 01:30 click text=Analyze this wallet Tapping the question box → FAILED: locator.scrollIntoViewIfNeeded: Timeout 8000ms exceeded.
- 01:38 scroll 600 Scrolling the sample page
- 01:43 bug Sample question box cuts the question mid-sentence On the phone sample page the question box shows 'Analyze this wallet's BTC 15-minute trades. Plot ... show how its positions' and stops; the rest can't be seen or scrolled to without pressing Break it down.
- 01:45 ok Sample page has no sideways scroll and the header fits
- 01:47 ok Trader page Human/Bot pill reads clearly beside the name

## Console and network errors (2)
- 00:03 console: Failed to load resource: net::ERR_TUNNEL_CONNECTION_FAILED
- 00:09 console: Failed to load resource: net::ERR_TUNNEL_CONNECTION_FAILED
