import type { CSSProperties, ReactNode } from "react";
import { AbsoluteFill, Audio, Easing, Sequence, getStaticFiles, interpolate, spring, staticFile, useCurrentFrame,
  useVideoConfig } from "remotion";
import { loadFont } from "@remotion/fonts";
import data from "./data.json";

// "Lucky or good?": one Leaderboard trader's record, then the alert you'd get when they buy. Every number comes
// from src/data.json (npm run pull). Colors are the site's dark theme (signals/static/index.html).
const C = {
  bg: "#0e0e0f", card: "#161617", fg: "#ececec", muted: "#8f8f95", line: "#26262a", soft: "#1b1b1e",
  gain: "#3ecf8e", accent: "#ff4d1f",
};
const FONT = "Host Grotesk";
loadFont({ family: FONT, url: staticFile("HostGrotesk-latin-var.woff2"), weight: "300 800" });

// Scene starts, in frames at 30 fps.
const HOOK = 0, RECORD = 105, VERDICT = 330, ALERT = 435, END = 555;
export const DURATION = 600;

const money = (v: number) =>
  Math.abs(v) >= 1e6 ? `$${(v / 1e6).toFixed(v >= 1e7 ? 1 : 2)}M` : `$${Math.round(v).toLocaleString("en-US")}`;
const cents = (p: number) => `${Math.round(p * 100)}¢`;
const winPct = Math.round((data.won30 / data.closed30) * 100);

// The site's avatar (index.html's avatar()): FNV-1a + murmur3 finish, a mirrored 5×5 grid tinted by the hash.
function hash32(s: string) {
  let h = 2166136261;
  for (let i = 0; i < s.length; i++) { h ^= s.charCodeAt(i); h = Math.imul(h, 16777619); }
  h ^= h >>> 16; h = Math.imul(h, 0x85ebca6b); h ^= h >>> 13; h = Math.imul(h, 0xc2b2ae35); h ^= h >>> 16;
  return h >>> 0;
}
const Avatar = ({ seed, size }: { seed: string; size: number }) => {
  const s = seed.toLowerCase(), h = hash32(s) % 360, bits = hash32(`${s}#cells`);
  const cells: ReactNode[] = [];
  for (let y = 0; y < 5; y++) for (let x = 0; x < 3; x++) {
    if (!((bits >>> (y * 3 + x)) & 1)) continue;
    cells.push(<rect key={`${x}${y}`} x={x} y={y} width={1} height={1} />);
    if (x < 2) cells.push(<rect key={`${4 - x}${y}m`} x={4 - x} y={y} width={1} height={1} />);
  }
  return (
    <div style={{ width: size, height: size, borderRadius: "50%", flex: "none", display: "grid", placeItems: "center",
      background: `hsl(${h} 30% 22%)`, color: `hsl(${h} 45% 66%)` }}>
      <svg viewBox="0 0 5 5" fill="currentColor" shapeRendering="crispEdges" style={{ width: "62%", height: "62%" }}>{cells}</svg>
    </div>
  );
};

const Logo = ({ size }: { size: number }) => (
  <svg viewBox="0 0 26 26" width={size} height={size}>
    <rect width="26" height="26" rx="8" fill={C.accent} />
    <g fill={C.bg} transform="translate(5 5) scale(.8)">
      <rect x="3" y="11" width="3" height="6" rx="1" /><rect x="8.5" y="7" width="3" height="10" rx="1" />
      <rect x="14" y="3" width="3" height="14" rx="1" />
    </g>
  </svg>
);

// Rises into place over `dur` frames from `delay`.
const useRise = (delay = 0, dur = 18) => {
  const f = useCurrentFrame();
  const t = interpolate(f, [delay, delay + dur], [0, 1], { extrapolateLeft: "clamp", extrapolateRight: "clamp",
    easing: Easing.out(Easing.cubic) });
  return { opacity: t, transform: `translateY(${(1 - t) * 40}px)` } as CSSProperties;
};
const Rise = ({ delay, children, style }: { delay?: number; children: ReactNode; style?: CSSProperties }) =>
  <div style={{ ...useRise(delay), ...style }}>{children}</div>;

// Each scene fades out over its last 10 frames so cuts feel like one piece.
const Scene = ({ len, children }: { len: number; children: ReactNode }) => {
  const f = useCurrentFrame();
  const out = interpolate(f, [len - 10, len], [1, 0], { extrapolateLeft: "clamp", extrapolateRight: "clamp" });
  return <AbsoluteFill style={{ padding: 88, opacity: out, justifyContent: "center" }}>{children}</AbsoluteFill>;
};

const Hook = () => {
  const f = useCurrentFrame();
  // Already mostly in at frame 0: X shows the first frame before the video plays.
  const n = interpolate(f, [-16, 40], [0, data.profitAll], { extrapolateLeft: "clamp", extrapolateRight: "clamp",
    easing: Easing.out(Easing.quad) });
  return (
    <Scene len={RECORD - HOOK}>
      <Rise delay={-14} style={{ display: "flex", alignItems: "center", gap: 28 }}>
        <Avatar seed={data.wallet} size={112} />
        <div>
          <div style={{ fontSize: 56, fontWeight: 650 }}>{data.name}</div>
          <div style={{ fontSize: 34, color: C.muted }}>{data.category} trader on Polymarket</div>
        </div>
      </Rise>
      <Rise delay={-10} style={{ marginTop: 72 }}>
        <div style={{ fontSize: 180, fontWeight: 700, letterSpacing: -6, color: C.gain, lineHeight: 1 }}>
          +{money(n)}
        </div>
        <div style={{ fontSize: 38, color: C.muted, marginTop: 16 }}>trading profit, all time</div>
      </Rise>
      <Rise delay={56} style={{ marginTop: 96, fontSize: 104, fontWeight: 700, letterSpacing: -3 }}>
        Lucky or <span style={{ color: C.accent }}>good?</span>
      </Rise>
    </Scene>
  );
};

// The 90-day profit curve, drawn left to right.
const Curve = ({ delay }: { delay: number }) => {
  const f = useCurrentFrame();
  const W = 904, H = 380, pts = data.curve90;
  const lo = Math.min(0, ...pts), hi = Math.max(...pts);
  const xy = pts.map((v, i) => [(i / (pts.length - 1)) * W, H - ((v - lo) / (hi - lo)) * (H - 20) - 10]);
  const shown = interpolate(f, [delay, delay + 60], [0, 1], { extrapolateLeft: "clamp", extrapolateRight: "clamp",
    easing: Easing.inOut(Easing.cubic) });
  const k = Math.max(1, Math.round(shown * (xy.length - 1)));
  const line = xy.slice(0, k + 1).map(([x, y], i) => `${i ? "L" : "M"}${x.toFixed(1)},${y.toFixed(1)}`).join("");
  const [ex, ey] = xy[k];
  const zero = H - ((0 - lo) / (hi - lo)) * (H - 20) - 10;
  return (
    <svg width={W} height={H} style={{ overflow: "visible" }}>
      <defs>
        <linearGradient id="fill" x1="0" x2="0" y1="0" y2="1">
          <stop offset="0" stopColor={C.gain} stopOpacity={0.28} /><stop offset="1" stopColor={C.gain} stopOpacity={0} />
        </linearGradient>
      </defs>
      <line x1={0} x2={W} y1={zero} y2={zero} stroke={C.line} strokeWidth={2} strokeDasharray="6 8" />
      <path d={`${line}L${ex},${H}L0,${H}Z`} fill="url(#fill)" />
      <path d={line} fill="none" stroke={C.gain} strokeWidth={6} strokeLinejoin="round" strokeLinecap="round" />
      <circle cx={ex} cy={ey} r={11} fill={C.gain} />
    </svg>
  );
};

const Stat = ({ label, value, sub, delay }: { label: string; value: string; sub: string; delay: number }) => (
  <Rise delay={delay} style={{ background: C.card, border: `2px solid ${C.line}`, borderRadius: 24, padding: "28px 32px" }}>
    <div style={{ fontSize: 30, color: C.muted }}>{label}</div>
    <div style={{ fontSize: 76, fontWeight: 700, letterSpacing: -2, marginTop: 4 }}>{value}</div>
    <div style={{ fontSize: 26, color: C.muted, marginTop: 2 }}>{sub}</div>
  </Rise>
);

const Record = () => (
  <Scene len={VERDICT - RECORD}>
    <Rise style={{ display: "flex", alignItems: "center", gap: 20 }}>
      <Avatar seed={data.wallet} size={64} />
      <div style={{ fontSize: 46, fontWeight: 650 }}>{data.name}'s record</div>
    </Rise>
    <Rise delay={6} style={{ marginTop: 44 }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline" }}>
        <div style={{ fontSize: 32, color: C.muted }}>Profit, last 90 days</div>
        <div style={{ fontSize: 48, fontWeight: 700, color: C.gain }}>+{money(data.profit90)}</div>
      </div>
      <div style={{ marginTop: 28 }}><Curve delay={12} /></div>
    </Rise>
    <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 24, marginTop: 52 }}>
      <Stat delay={70} label="Win rate" value={`${winPct}%`} sub={`${data.won30} of ${data.closed30} closed, 30 days`} />
      <Stat delay={82} label="Average price paid" value={cents(data.paid30)} sub="30 days" />
      <Stat delay={94} label="Weeks up" value={`${data.weeksUp} of ${data.weeksKnown}`} sub="last 12 weeks" />
      <Stat delay={106} label="Usual trade" value={money(data.usualTrade)} sub="typical bet size" />
    </div>
  </Scene>
);

// A price is the market's chance: paying 42¢ and winning 58% is beating the market, not riding favourites.
const Bar = ({ label, value, frac, color, delay }: { label: string; value: string; frac: number; color: string; delay: number }) => {
  const f = useCurrentFrame();
  const t = interpolate(f, [delay, delay + 30], [0, 1], { extrapolateLeft: "clamp", extrapolateRight: "clamp",
    easing: Easing.out(Easing.cubic) });
  return (
    <div style={{ marginTop: 36 }}>
      <div style={{ display: "flex", justifyContent: "space-between", fontSize: 36, marginBottom: 14 }}>
        <span style={{ color: C.muted }}>{label}</span><span style={{ fontWeight: 700, color }}>{value}</span>
      </div>
      <div style={{ height: 36, borderRadius: 18, background: C.soft }}>
        <div style={{ height: "100%", width: `${frac * t * 100}%`, borderRadius: 18, background: color }} />
      </div>
    </div>
  );
};

const Verdict = () => (
  <Scene len={ALERT - VERDICT}>
    <Rise style={{ fontSize: 112, fontWeight: 700, letterSpacing: -3, lineHeight: 1.02 }}>
      Not one<br />lucky bet.
    </Rise>
    <Rise delay={14} style={{ fontSize: 44, color: C.muted, marginTop: 36, lineHeight: 1.3 }}>
      The price is the market's odds. They buy at {cents(data.paid30)} and win {winPct}% of the time.
    </Rise>
    <div style={{ marginTop: 32 }}>
      <Bar delay={34} label="Price they pay" value={cents(data.paid30)} frac={data.paid30} color={C.muted} />
      <Bar delay={46} label="How often they win" value={`${winPct}%`} frac={winPct / 100} color={C.gain} />
    </div>
  </Scene>
);

const Alert = () => {
  const f = useCurrentFrame(), { fps } = useVideoConfig();
  const drop = spring({ frame: f - 16, fps, config: { damping: 14, mass: 0.8 } });
  const b = data.buy;
  return (
    <Scene len={END - ALERT}>
      <Rise style={{ fontSize: 76, fontWeight: 700, letterSpacing: -2, lineHeight: 1.05 }}>
        Follow them.<br /><span style={{ color: C.accent }}>Know when they trade.</span>
      </Rise>
      <div style={{ marginTop: 72, transform: `translateY(${(1 - drop) * -120}px) scale(${0.94 + drop * 0.06})`,
        opacity: Math.min(1, drop * 1.6), background: C.card, border: `2px solid ${C.line}`, borderRadius: 36,
        padding: 40, boxShadow: "0 30px 80px rgba(0,0,0,.6)" }}>
        <div style={{ display: "flex", alignItems: "center", gap: 18, fontSize: 30, color: C.muted }}>
          <Logo size={48} /><span style={{ color: C.fg, fontWeight: 600 }}>Signals</span><span>· now</span>
        </div>
        <div style={{ fontSize: 46, marginTop: 28, lineHeight: 1.25 }}>
          <b>{data.name}</b> bought <b>{b.outcome}</b> at {cents(b.price)} ({money(b.usd)})
        </div>
        <div style={{ fontSize: 32, color: C.muted, marginTop: 14, lineHeight: 1.3 }}>{b.title}</div>
        <div style={{ display: "flex", gap: 16, marginTop: 32, fontSize: 30, fontWeight: 600 }}>
          <div style={{ background: C.soft, borderRadius: 16, padding: "16px 24px" }}>Check current price</div>
          <div style={{ background: C.soft, borderRadius: 16, padding: "16px 24px" }}>
            {b.kalshi ? "View on Kalshi" : "Buy on Polymarket ↗"}
          </div>
        </div>
      </div>
    </Scene>
  );
};

const End = () => (
  <Scene len={DURATION - END + 10}>
    <div style={{ alignItems: "center", display: "flex", flexDirection: "column", textAlign: "center" }}>
      <Rise style={{ display: "flex", alignItems: "center", gap: 24 }}>
        <Logo size={112} /><span style={{ fontSize: 96, fontWeight: 700, letterSpacing: -3 }}>Signals</span>
      </Rise>
      <Rise delay={8} style={{ fontSize: 50, marginTop: 48, lineHeight: 1.25 }}>
        Know who's good.<br />Know when they trade.
      </Rise>
      <Rise delay={16} style={{ fontSize: 46, marginTop: 40, color: C.accent, fontWeight: 650 }}>usesignals.app</Rise>
    </div>
  </Scene>
);

// Sound: public/tick.wav and ping.wav (made with ffmpeg, nothing to license) on the beats above, and
// public/music.mp3 under it when there is one. MUSIC_FROM skips the track's intro, in seconds.
const MUSIC_FROM = 0;
const hasMusic = getStaticFiles().some((f) => f.name === "music.mp3");
const TICKS: [number, number][] = [
  ...Array.from({ length: 10 }, (_, i) => [i * 4, 0.35 - i * 0.025] as [number, number]),  // the count-up
  ...[70, 82, 94, 106].map((d) => [RECORD + d, 0.4] as [number, number]),  // each record tile
  [VERDICT + 34, 0.4], [VERDICT + 46, 0.4],  // the two bars
];
const Sound = () => {
  const { fps } = useVideoConfig();
  return (
    <>
      {hasMusic && (
        <Audio src={staticFile("music.mp3")} trimBefore={MUSIC_FROM * fps}
          volume={(f) => interpolate(f, [0, 12, DURATION - 30, DURATION], [0, 0.55, 0.55, 0],
            { extrapolateLeft: "clamp", extrapolateRight: "clamp" })} />
      )}
      {TICKS.map(([at, vol]) => (
        <Sequence key={at} from={at} durationInFrames={6}><Audio src={staticFile("tick.wav")} volume={vol} /></Sequence>
      ))}
      <Sequence from={ALERT + 16} durationInFrames={30}><Audio src={staticFile("ping.wav")} volume={0.8} /></Sequence>
    </>
  );
};

export const TraderStory = () => (
  <AbsoluteFill style={{ background: C.bg, color: C.fg, fontFamily: FONT }}>
    <Sound />
    <Sequence from={HOOK} durationInFrames={RECORD - HOOK}><Hook /></Sequence>
    <Sequence from={RECORD} durationInFrames={VERDICT - RECORD}><Record /></Sequence>
    <Sequence from={VERDICT} durationInFrames={ALERT - VERDICT}><Verdict /></Sequence>
    <Sequence from={ALERT} durationInFrames={END - ALERT}><Alert /></Sequence>
    <Sequence from={END}><End /></Sequence>
    <div style={{ position: "absolute", left: 88, bottom: 48, fontSize: 22, color: C.muted, opacity: 0.7 }}>
      Polymarket data as of {data.asOf}. Past results don't predict future ones.
    </div>
  </AbsoluteFill>
);
