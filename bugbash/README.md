# Agent bug bash

One agent per feature, each on its own cloud machine, testing the live site in a filmed browser.
Each run leaves a video (with a caption bar saying what the agent is doing, a dot where it clicks and a red
banner on every bug) plus `report.md` and `bugs.json`.

## Run one feature (what a cloud agent does)

```bash
bash bugbash/setup.sh                                   # Playwright + Chromium + ffmpeg, checks usesignals.app
cd bugbash
node bb.mjs start leaderboard                           # add --phone for a 390x844 phone
node bb.mjs go https://usesignals.app/#/traders "Opening the Leaderboard"
node bb.mjs look home                                   # screenshot + visible text + new console/HTTP errors
node bb.mjs click 'text=30 days' "Switching the period to 30 days"
node bb.mjs ok "Period switch re-sorts the list"
node bb.mjs bug "Win rate missing on row 3" "Row 3 shows '—' though the Leaderboard only lists complete rows"
node bb.mjs stop                                        # writes runs/<feature>-<time>/video.mp4 + report.md
```

Run `node bb.mjs` with no arguments for every command. Look at each screenshot (Read the png) before deciding
the next step: the agent judges what it sees, it doesn't follow a fixed script.

## Briefs

`briefs/*.md`, one per feature: what to try and what counts as broken. Add a feature = add a brief.

## Rules for every run (Signals)

- Signed out only, unless a brief says otherwise. Never sign up, sign in or enter anyone's details.
- Never spend: never press Copy, Start, "Break it down", Ask, "Why here?" or anything that starts a paid run or an
  order. The one exception is "Break it down" on a page whose URL has `?sample`: it replays a recording with no
  service behind it. If unsure what a button does, don't press it; note it in the report instead.
- A bug is something a user would notice: wrong or missing numbers, broken layout, dead buttons, errors, text that
  contradicts itself, slow loads (> 8 s). Console/HTTP errors count when they break something visible.
- Keep each video under about 6 minutes: short captions, no idle waits.

## Where results go

Each cloud run commits `bugbash/runs/<feature>-<time>/` with `git add -f` to its own branch
`bugbash-run/<feature>-<date>` and pushes it. Nothing is merged; delete those branches after review.
