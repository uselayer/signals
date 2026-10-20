# Signals videos

Short videos for X, made with [Remotion](https://www.remotion.dev) (React → MP4). Not part of the app.

`TraderStory` (20 s, 1080×1350): "Lucky or good?" — one Leaderboard trader's record, then the alert you'd get
when they buy. Every number comes from `src/data.json`.

```sh
npm install
npm run pull -- Kch-Temp   # a Leaderboard name or wallet: refreshes src/data.json from usesignals.app
npm run studio             # preview and scrub in the browser
npm run render             # out/trader-story.mp4
```

Remotion is free for individuals and companies of up to 3 people; past that it needs a company licence.
