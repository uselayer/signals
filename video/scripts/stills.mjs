// Stills from a video at given seconds, for checking a recording or render: node scripts/stills.mjs <video> <dir> <t>...
import { execFileSync } from "node:child_process";
import { mkdirSync } from "node:fs";
const [video, dir, ...ts] = process.argv.slice(2);
mkdirSync(dir, { recursive: true });
for (const t of ts) {
  execFileSync("ffmpeg", ["-y", "-loglevel", "error", "-ss", t, "-i", video, "-frames:v", "1", "-vf", "scale=960:-1", `${dir}/t${t}.png`]);
  console.log(`${dir}/t${t}.png`);
}
