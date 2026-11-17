# Breakdowns, sample mode (desktop)

Start: `node bb.mjs start breakdowns-sample` then `go https://usesignals.app/breakdowns/?sample`

Sample mode (`?sample` in the URL) plays a breakdown recorded from a real run, with no sign-in and nothing spent: the
page has no service behind it. It opens on the question form with the sample's question filled in.

Try:
- **Only while the URL has `?sample`:** press "Break it down" and watch the recording play. It should plan, read
  and chart the trades, then show an answer card, findings and the window chart. Allow up to ~60 s.
- The answer card, findings and tiles: plain words, answer first, and numbers that agree with each other. No "edge",
  "alpha", "smart money", "bet" or advice.
- The window chart: hover over it (the readout should follow the mouse) and click a fill dot. The popover should open
  and close with Close.
- The sample's end asks the visitor to sign in to run their own. That should read clearly, never as an error.
- Long text: the question box and finding cards shouldn't cut words off or overlap.
- Visit `https://usesignals.app/breakdowns/` without `?sample`. A signed-out visitor should get a clear way in, never
  an error.

Never press "Break it down", Start, Ask, "Why here?" or "Ask about this moment" on a page without `?sample` in the
URL (those start paid runs), and never sign in. In the sample, a follow-up's Start only asks you to sign in: don't
sign in.
