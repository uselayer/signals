# Signals videos

Short videos for X, made with [Remotion](https://www.remotion.dev) (React → MP4). Not part of the app.

`TraderStory` (20 s, 1080×1350): "Lucky or good?" — one Leaderboard trader's record, then the alert you'd get
when they buy. Every number comes from `src/data.json`.

`SameGame` (23 s, 1080×1350, for Layer's account, in Layer's site colours): "Same game?" — one real Hyperliquid ↔
Kalshi pair: different names, same outcomes, prices a cent apart, the same rule quoted from both, then the API call.
Every fact comes from `src/hyperliquid.json`; set its `"sample": true` and a red band marks every frame as not real.

`Watchlist` (27 s, 1920×1080): "Follow any Polymarket trader" — the Watchlist launch, mostly the real app: paste a
profile, follow, their watch page (tiles, changes, Explained, holdings), then the Telegram alert and usesignals.app. The
footage is `public/watchlist/app.mp4` (not in git; a copy is in `~/Desktop/Motion Graphics/Signals/watchlist-footage/`),
recorded from a local run of Signals by `npm run record:watchlist` (see the script's header for the run command and
what it evens out against usesignals.app); `events.json` holds each step's time and the composition cuts on it, so a
new recording re-times the video by itself. The alert is one real trade worded as Signals sends it (`src/watchlist.json`).
Music is the owner's pick, not in git: `public/watchlist-music.mp3` (East Side Boulevard) by default, or another track in
`public/` from its drop, e.g. `npm run render:watchlist -- --props='{"music":"watchlist-music-traders.wav","from":81.85,"gain":0.68}'`.

```sh
npm install
npm run pull -- Kch-Temp   # a Leaderboard name or wallet: refreshes src/data.json from usesignals.app
npm run studio             # preview and scrub in the browser
npm run render             # out/trader-story.mp4
npm run render:hl          # out/same-game.mp4
npm run record:watchlist   # public/watchlist/app.mp4 + events.json, from a local run on :8791 (Playwright's Chromium)
npm run render:watchlist   # out/signals-watchlist.mp4
```

Sound: `public/tick.wav` and `public/ping.wav` are made with ffmpeg. Music is `public/music.mp3`, not in git
(Pixabay's licence doesn't allow sharing the file on its own): download "GRAM (Gunna Trap Type Beat)" from
[Pixabay](https://pixabay.com/music/beats-gram-gunna-trap-type-beat-264952/) and save it there. Without it
the video renders with the sound effects only.

Remotion is free for individuals and companies of up to 3 people; past that it needs a company licence.
