# Breakdowns, sample mode (desktop)

Start: `node bb.mjs start breakdowns-sample` then `go https://usesignals.app/breakdowns/?sample`

Sample mode shows finished breakdowns without signing in or spending anything.

Try:
- The sample opens: header with the trader's name and pill, an answer card on top, findings, and the window chart.
- Market pickers (BTC 15-minute, BTC monthly, BTC yearly, politics, soccer and any others shown): each switches the
  view, or says plainly that there's no sample for it.
- The wallet / trader picker and the Breakdowns list (filter by market): rows open the right breakdown.
- The window chart: hover over it (the readout should follow the mouse) and click a fill dot. The popover should open
  and close with Close. Don't press "Why here?".
- Text: answer first, plain words, no "edge", "alpha", "smart money", "bet" or advice. Numbers in the answer should
  match the tiles and findings.
- Visit `https://usesignals.app/breakdowns/` without `?sample`. A signed-out visitor should get a clear way in, never
  an error.

Never press Start, "Break it down", Ask, "Why here?" or "Ask about this moment" (they start paid runs), and never sign in.
