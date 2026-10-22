# Signals videos

Short videos for X, made with [Remotion](https://www.remotion.dev) (React → MP4). Not part of the app.

`TraderStory` (20 s, 1080×1350): "Lucky or good?" — one Leaderboard trader's record, then the alert you'd get
when they buy. Every number comes from `src/data.json`.

`SameGame` (23 s, 1080×1350, for Layer's account, in Layer's site colours): "Same game?" — one real Hyperliquid ↔
Kalshi pair: different names, same outcomes, prices a cent apart, the same rule quoted from both, then the API call.
Every fact comes from `src/hyperliquid.json`; set its `"sample": true` and a red band marks every frame as not real.

```sh
npm install
npm run pull -- Kch-Temp   # a Leaderboard name or wallet: refreshes src/data.json from usesignals.app
npm run studio             # preview and scrub in the browser
npm run render             # out/trader-story.mp4
npm run render:hl          # out/same-game.mp4
```

Sound: `public/tick.wav` and `public/ping.wav` are made with ffmpeg. Music is `public/music.mp3`, not in git
(Pixabay's licence doesn't allow sharing the file on its own): download "GRAM (Gunna Trap Type Beat)" from
[Pixabay](https://pixabay.com/music/beats-gram-gunna-trap-type-beat-264952/) and save it there. Without it
the video renders with the sound effects only.

Remotion is free for individuals and companies of up to 3 people; past that it needs a company licence.
