# Agent bug bash

One agent per feature, each on its own cloud machine, testing the live site in a filmed browser.
Each run leaves a video (with a caption bar saying what the agent is doing, a dot where it clicks and a red banner on
every bug) plus `report.md` and `bugs.json`. Nothing runs on a laptop.

## Running one

From Claude Code: `/bugbash` (every brief), `/bugbash trader-page phone` (some), or `/bugbash #301` / `/bugbash the
new Copy trading tab` (Claude writes a brief for what changed first). Claude starts one cloud agent per feature,
triages what they find, and republishes the results page with the videos.

Each cloud agent follows [AGENT.md](AGENT.md). It tests the **deployed** site (usesignals.app by default), so bash a
PR after it's merged and deployed, or pass `--url` for another deployment the cloud environment can reach.

## Files

- `bb.mjs`: the filmed browser. `node bb.mjs` with no arguments lists its commands (start, go, click, type, look,
  ok, bug, stop). Each run lands in `runs/<feature>-<time>/` (git-ignored; agents push theirs with `git add -f` to
  their own `claude/bugbash-*` branch).
- `briefs/*.md`: one per feature: how to start, what to try, what counts as broken. Add a feature = add a brief.
- `AGENT.md`: what each cloud agent does, start to finish.
- `reel.mjs` + `reel.css`: builds the results page from run folders:
  `node reel.mjs <out dir> <run dirs…> --triage triage.json`.
- `setup.sh`: installs Playwright's Chromium and ffmpeg on a fresh cloud machine and checks the site is reachable.

## Rules for every run (Signals)

- Signed out only, unless a brief says otherwise. Never sign up, sign in or enter anyone's details.
- Never spend: never press Copy, Start, "Break it down", Ask, "Why here?" or anything that starts a paid run or an
  order. The one exception is "Break it down" on a page whose URL has `?sample`: it replays a recording with no
  service behind it. If unsure what a button does, don't press it; note it in the report instead.
- A bug is something a user would notice: wrong or missing numbers, broken layout, dead buttons, errors, text that
  contradicts itself, slow loads (> 8 s). Console/HTTP errors count when they break something visible.
- Keep each video under about 6 minutes: short captions, no idle waits.

## Cloud setup (once)

The Claude Code cloud environment needs network access to the site and Playwright's download host
(usesignals.app, *.usesignals.app, cdn.playwright.dev, playwright.download.prss.microsoft.com, *.polymarket.com),
and the Claude GitHub app installed on this repo so agents can push their results.
