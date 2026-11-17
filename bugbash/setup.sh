#!/usr/bin/env bash
# One-time setup on a fresh cloud machine: Playwright + Chromium + ffmpeg, then a reachability check.
set -u
cd "$(dirname "$0")"
npm install --no-audit --no-fund --loglevel=error
npx playwright install --with-deps chromium 2>/dev/null || npx playwright install chromium
if ! command -v ffmpeg >/dev/null; then
  (sudo -n apt-get install -y -qq ffmpeg || apt-get install -y -qq ffmpeg) >/dev/null 2>&1 \
    || echo "no ffmpeg: videos stay .webm (still plays in a browser)"
fi
code=$(curl -s -o /dev/null -w '%{http_code}' https://usesignals.app/ || true)
echo "usesignals.app answered HTTP $code"
[ "$code" = "200" ] || echo "CANNOT REACH usesignals.app: the cloud environment's network access must allow it"
