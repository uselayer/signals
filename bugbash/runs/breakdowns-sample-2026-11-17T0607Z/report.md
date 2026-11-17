# Bug bash: breakdowns-sample (desk)

Video: video.mp4 · 01:17 long · 2026-11-17T06:08:19.532Z

## Bugs (1)
1. **Sample opens on the ask form, no finished breakdown** (video 00:44) — Opened /breakdowns/?sample signed out; expected a finished breakdown (answer card, findings, chart) per the brief, saw only the question form where the recorded run plays after pressing Break it down (not pressed). No market pickers or breakdowns list shown either.
   - Page: https://usesignals.app/breakdowns/?sample#/
   - Screenshot: 05-bug-1.png

## Checks passed (2)
- 00:55 Signed-out /breakdowns/ shows a clear teaser, Sign in and sample links, no error
- 01:06 Sample links and Traders tab navigate correctly

## Steps
- 00:00 go https://usesignals.app/breakdowns/?sample Opening the sample breakdown
- 00:07 click text=0xb945 Opening the wallet picker → FAILED: locator.scrollIntoViewIfNeeded: Timeout 8000ms exceeded.
- 00:18 click text=0xb945 Clicking the wallet field → FAILED: locator.scrollIntoViewIfNeeded: Timeout 8000ms exceeded.
- 00:26 click text=/0xb945/ Clicking the wallet field → FAILED: locator.scrollIntoViewIfNeeded: Timeout 8000ms exceeded.
- 00:37 click input >> nth=0 Clicking the wallet field
- 00:38 click text=Breakdowns Opening the Breakdowns tab
- 00:44 bug Sample opens on the ask form, no finished breakdown Opened /breakdowns/?sample signed out; expected a finished breakdown (answer card, findings, chart) per the brief, saw only the question form where the recorded run plays after pressing Break it down (not pressed). No market pickers or breakdowns list shown either.
- 00:47 go https://usesignals.app/breakdowns/ Visiting Breakdowns without sample
- 00:55 ok Signed-out /breakdowns/ shows a clear teaser, Sign in and sample links, no error
- 00:56 click text=Watch a sample breakdown Clicking Watch a sample breakdown
- 00:59 click text=Traders Opening the Traders tab
- 01:06 ok Sample links and Traders tab navigate correctly

## Console and network errors (2)
- 00:49 console: Failed to load resource: net::ERR_TUNNEL_CONNECTION_FAILED
- 01:01 console: Failed to load resource: net::ERR_TUNNEL_CONNECTION_FAILED
