# Bug bash: leaderboard (desk)

Video: video.mp4 · 05:11 long · 2026-11-17T06:12:23.764Z

## Bugs (3)
1. **Usual trade text cut off** (video 00:52) — On market chip All, 90D, row 3 (ZhangMuZhi..) the Usual trade cell reads 'fewer than one market a' and is clipped at the column edge.
   - Page: https://usesignals.app/#/traders
   - Screenshot: 09-bug-1.png
2. **No way to reverse a sort** (video 02:24) — Clicked the Win rate column header twice and the sort stays the same; only the dropdown sorts, highest first, so the brief's 'both directions' can't be done (may be by design).
   - Page: https://usesignals.app/#/traders
   - Screenshot: 20-bug-2.png
3. **Back link and Traders tab do nothing on a trader page** (video 04:19) — Opened gettingdrained from the Leaderboard, then clicked '← Traders', the Traders tab and Alt+Left: the URL and page stayed on the trader page each time (3 tries), so Back-to-list state could not be checked.
   - Page: https://usesignals.app/#/worth/0x9f300e1b1b086290fa04c4c8f40cb6a10e95bb5a
   - Screenshot: 33-bug-3.png

## Checks passed (8)
- 00:08 List loads fast with all columns on top rows; Bot/Human pills match icons
- 00:22 Foot explains the count and says how many wait; 50 rows with Show 50 more
- 00:35 7D period re-sorts the list and changes profit figures
- 01:17 Every market chip and period gives a different, sensibly ordered list
- 02:51 Search by name finds the trader
- 03:08 Nonsense search says No trader matches, clearly
- 03:33 Trader page 90-day profit (+$336) matches the list row
- 04:34 No 'recommended', tier or advice wording anywhere on the Leaderboard

## Steps
- 00:00 go https://usesignals.app/#/traders Opening the Leaderboard
- 00:08 ok List loads fast with all columns on top rows; Bot/Human pills match icons
- 00:09 scroll 3000 Scrolling to the foot of the list
- 00:16 scroll 20000 Jumping to the very end
- 00:22 ok Foot explains the count and says how many wait; 50 rows with Show 50 more
- 00:23 scroll -30000 Back to the top
- 00:24 click #/traders >> text=7D Switching period to 7D → FAILED: locator.scrollIntoViewIfNeeded: Unexpected token "#" while parsing css selector "#/traders". Did you mean to CSS.escape it?
- 00:24 click text=7D Switching period to 7D
- 00:35 ok 7D period re-sorts the list and changes profit figures
- 00:37 click text=90D >> nth=0 Switching period to 90D
- 00:42 click text=All >> nth=0 Switching period to All
- 00:52 bug Usual trade text cut off On market chip All, 90D, row 3 (ZhangMuZhi..) the Usual trade cell reads 'fewer than one market a' and is clipped at the column edge.
- 00:55 click text=All >> nth=1 Switching period to All time
- 01:00 click button:has-text('Politics') Market chip: Politics
- 01:05 click button:has-text('Crypto') Market chip: Crypto
- 01:10 click button:has-text('Esports') Market chip: Esports
- 01:17 ok Every market chip and period gives a different, sensibly ordered list
- 01:18 scroll 20000 Checking the foot count for Esports
- 01:26 scroll -30000 Back to the top
- 01:27 click select Sorting by Profit per $ traded
- 01:29 type select Profit per $ traded → FAILED: locator.fill: Error: Element is not an <input>, <textarea> or [contenteditable] element
- 01:30 click select Sorting by Win rate
- 01:31 type select Win rate → FAILED: locator.fill: Error: Element is not an <input>, <textarea> or [contenteditable] element
- 01:32 click select Sorting by Volume
- 01:34 type select Volume → FAILED: locator.fill: Error: Element is not an <input>, <textarea> or [contenteditable] element
- 01:34 click select Sorting by Most weeks up
- 01:36 type select Most weeks up → FAILED: locator.fill: Error: Element is not an <input>, <textarea> or [contenteditable] element
- 01:41 click select Opening the sort menu
- 01:43 press ArrowDown Next sort option
- 01:44 press Enter
- 01:48 click select Opening the sort menu
- 01:50 press ArrowDown Next sort option
- 01:51 press Enter
- 01:55 click select Opening the sort menu
- 01:57 press ArrowDown Next sort option
- 01:58 press Enter
- 02:02 click select Opening the sort menu
- 02:03 press ArrowDown Next sort option
- 02:04 press Enter
- 02:12 click text=Win rate >> nth=1 Clicking a column header to sort
- 02:15 click text=Win rate >> nth=1 Clicking again to reverse
- 02:24 bug No way to reverse a sort Clicked the Win rate column header twice and the sort stays the same; only the dropdown sorts, highest first, so the brief's 'both directions' can't be done (may be by design).
- 02:27 click text=All >> nth=0 Back to all markets
- 02:28 type input BreakTheBank Searching for a name seen in the list
- 02:40 type input >> nth=0  Clearing the header box (not used)
- 02:42 type input[placeholder*='Search any trader'] BreakTheBank Searching the Leaderboard for a name from the list
- 02:51 ok Search by name finds the trader
- 02:52 type input[placeholder*='Search any trader'] 0x2c Searching part of a wallet address
- 02:58 type input[placeholder*='Search any trader'] zzqqxxnotatrader Searching nonsense
- 03:08 ok Nonsense search says No trader matches, clearly
- 03:10 type input[placeholder*='Search any trader']  Clearing the search
- 03:12 click text=Politics Choosing Politics, then 90D
- 03:13 click text=90D 90D
- 03:18 scroll 700 Scrolling down the list
- 03:25 click text=gettingdrained Opening a trader from the list
- 03:33 ok Trader page 90-day profit (+$336) matches the list row
- 03:35 press Alt+ArrowLeft Browser Back
- 03:43 press Alt+Left Browser Back → FAILED: keyboard.press: Unknown key: "Left"
- 03:49 click text=← Traders Using the page's back link
- 03:57 click a:has-text('← Traders'), button:has-text('← Traders') Clicking the back arrow link again
- 04:06 click header >> text=Traders Using the Traders tab instead
- 04:15 click text=90D >> nth=0 Checking the page still responds: chart 90D
- 04:19 bug Back link and Traders tab do nothing on a trader page Opened gettingdrained from the Leaderboard, then clicked '← Traders', the Traders tab and Alt+Left: the URL and page stayed on the trader page each time (3 tries), so Back-to-list state could not be checked.
- 04:25 go https://usesignals.app/#/traders Reopening the Leaderboard by address
- 04:34 ok No 'recommended', tier or advice wording anywhere on the Leaderboard

## Console and network errors (1)
- 00:02 console: Failed to load resource: net::ERR_TUNNEL_CONNECTION_FAILED
