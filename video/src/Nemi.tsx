import type { CSSProperties, ReactNode } from "react";
import { AbsoluteFill, Audio, Easing, OffthreadVideo, Sequence, getStaticFiles, interpolate, staticFile,
  useCurrentFrame } from "remotion";
import { loadFont } from "@remotion/fonts";
import rec from "../public/nemi/events.json";

// "Paper trade on Nemi": the launch, mostly the real app. public/nemi/app.mp4 is a scripted recording of Nemi's site
// reading the live engine (npm run record:nemi); its step times are in events.json, and each shot below plays a stretch
// of it with a camera on what matters, in the order the story needs (the recording opens the trades in another order).
// Colors and fonts are the site's own (~/dev/nemi src/index.css: black, mint-tinted ink, one neon mint accent).
const C = { bg: "#000000", raised: "#0e0e10", ink: "#e6f5ef", ink2: "#a3b5ae", ink3: "#6b7c76", rule: "#1c1c1f",
  accent: "#3dffc5", accentSoft: "#06251c" };
const SERIF = "Newsreader", SANS = "Inter", MONO = "JetBrains Mono";
loadFont({ family: SERIF, url: staticFile("nemi/newsreader-latin-400-normal.woff2"), weight: "400" });
loadFont({ family: SERIF, url: staticFile("nemi/newsreader-latin-500-normal.woff2"), weight: "500" });
loadFont({ family: SANS, url: staticFile("nemi/inter-latin-wght-normal.woff2"), weight: "100 900" });
loadFont({ family: MONO, url: staticFile("nemi/jetbrains-mono-latin-400-normal.woff2"), weight: "400" });

const FPS = 30, W = 1920, H = 1080;
const ev = rec.events;
const ease = Easing.inOut(Easing.cubic);

// A stretch of the recording [from, to] (seconds in app.mp4) played at `rate`, under a caption (and a smaller line),
// with camera keyframes [source second, center x, center y, zoom] in the recording's 1920×1080 layout.
// `showcase`: the shot is of rec.showcase's page (entry-bands), not the trades' strategy (rec.strategy, vwap-rider).
type Shot = { from: number; to: number; rate: number; caption: string; sub?: string; top?: boolean; showcase?: boolean;
  cam: [number, number, number, number][] };
const DRAWER = 1640;  // the trade drawer's middle, x
const SHOTS: Shot[] = [
  { from: ev.new - 0.3, to: ev.strategy - 0.1, rate: 1.25, caption: "Pick a strategy", showcase: true,
    sub: "It trades Polymarket's Bitcoin 15-minute markets",
    // On entry-bands' card (x 548–955); the right edge stays ≤ 1069, short of vwap-rider's "−79.7%" (x 1087).
    cam: [[ev.new - 0.3, 650, 300, 2.3], [ev.pick, 700, 382, 2.6]] },
  { from: ev.strategy, to: ev.slip - 0.15, rate: 1.4, caption: "Paper money, real order books", showcase: true,
    // The frame's left edge stays at x ≥ 222: the sidebar (x < 210) shows vwap-rider, out of money since 10-27.
    cam: [[ev.strategy, 770, 170, 1.75], [ev.statsSeen, 950, 190, 1.75]] },
  { from: ev.slip, to: ev.slipCostScroll, rate: 1.05, caption: "Big orders walk the book",
    sub: "Asked 47¢. Paid 48.3¢ on average, level by level.",
    cam: [[ev.slip, DRAWER, 300, 1.85], [ev.slip + 0.9, DRAWER, 440, 2.25], [ev.slipBook, DRAWER, 540, 2.25]] },
  { from: ev.slipCostScroll + 0.2, to: ev.slipEndScroll, rate: 1.05, caption: "Polymarket's fee, every trade",
    sub: "$8.74 fee + 1.3¢ a share more = $15.39 to get in",
    cam: [[ev.slipCostScroll + 0.2, DRAWER, 430, 2.1], [ev.slipCost, DRAWER, 520, 2.3]] },
  { from: ev.partial, to: ev.refused - 0.15, rate: 1.1, caption: "Only what's for sale gets filled",
    sub: "Wanted 500 at 99¢. Got 460.",
    cam: [[ev.partial, DRAWER, 260, 2.0], [ev.partialNote, DRAWER, 430, 2.3]] },
  { from: ev.refused, to: ev.report - 0.2, rate: 1.1, caption: "Nothing for sale? No trade.",
    sub: "Live wouldn't have filled it either.",
    cam: [[ev.refused, DRAWER, 240, 2.0], [ev.refusedNote, DRAWER, 300, 2.3]] },
  // The drawer's end is the recording's bottom edge, so this caption sits at the top.
  { from: ev.settle - 0.15, to: ev.settleEnd, rate: 1.05, caption: "Settled by Polymarket's own result", top: true,
    cam: [[ev.settle - 0.15, DRAWER, 760, 2.0], [ev.settleEnd, DRAWER, 900, 2.25]] },
  { from: ev.report, to: ev.end - 0.3, rate: 1.3, caption: "See where the money went", showcase: true,
    cam: [[ev.report, 825, 390, 1.6], [ev.waterfallSeen, 825, 420, 1.6], [ev.stats, 910, 430, 1.4]] },  // left edge ≥ 222
];
const XF = 8;
const HOOK = 105;
const starts: number[] = [];
let at = HOOK - XF;
for (const s of SHOTS) { starts.push(at); at += Math.round(((s.to - s.from) / s.rate) * FPS) - XF; }
const END = at;
export const NEMI_DURATION = END + 100;
const len = (i: number) => Math.round(((SHOTS[i].to - SHOTS[i].from) / SHOTS[i].rate) * FPS);
const frameOf = (t: number) => {
  const i = SHOTS.findIndex((s) => t >= s.from && t <= s.to);
  return starts[i] + Math.round(((t - SHOTS[i].from) / SHOTS[i].rate) * FPS);
};

const recorded = new Date(rec.recorded).toLocaleDateString("en-US", { month: "short", day: "numeric", timeZone: "America/Chicago" });
const clamp = { extrapolateLeft: "clamp", extrapolateRight: "clamp" } as const;
const useRise = (delay = 0, dur = 16) => {
  const t = interpolate(useCurrentFrame(), [delay, delay + dur], [0, 1], { ...clamp, easing: Easing.out(Easing.cubic) });
  return { opacity: t, transform: `translateY(${(1 - t) * 30}px)` } as CSSProperties;
};
const Rise = ({ delay, children, style }: { delay?: number; children: ReactNode; style?: CSSProperties }) =>
  <div style={{ ...useRise(delay), ...style }}>{children}</div>;

const ShotView = ({ shot, frames }: { shot: Shot; frames: number }) => {
  const f = useCurrentFrame();
  const t = shot.from + (f / FPS) * shot.rate;
  const k = shot.cam, ts = k.map((c) => c[0]);
  const pick = (j: number) => ts.length === 1 ? k[0][j] : interpolate(t, ts, k.map((c) => c[j]), { ...clamp, easing: ease });
  const z = pick(3);
  const cx = Math.min(Math.max(pick(1), W / 2 / z), W - W / 2 / z), cy = Math.min(Math.max(pick(2), H / 2 / z), H - H / 2 / z);
  const fade = interpolate(f, [0, XF], [0, 1], clamp);
  const cap = interpolate(f, [4, 18, frames - 6, frames], [0, 1, 1, 0], clamp);
  const sub = interpolate(f, [10, 24, frames - 6, frames], [0, 1, 1, 0], clamp);
  return (
    <AbsoluteFill style={{ opacity: fade, background: C.bg, overflow: "hidden" }}>
      <div style={{ position: "absolute", width: W, height: H, transformOrigin: "0 0",
        transform: `translate(${W / 2 - cx * z}px, ${H / 2 - cy * z}px) scale(${z})` }}>
        <OffthreadVideo src={staticFile("nemi/app.mp4")} muted trimBefore={Math.round(shot.from * FPS)}
          playbackRate={shot.rate} style={{ width: W, height: H }} />
      </div>
      <div style={{ position: "absolute", left: 0, right: 0, height: 330, [shot.top ? "top" : "bottom"]: 0,
        background: `linear-gradient(to ${shot.top ? "bottom" : "top"}, ${C.bg} 30%, ${C.bg}00)` }} />
      <div style={{ position: "absolute", left: 96, right: 96, ...(shot.top ? { top: 64 } : { bottom: shot.sub ? 118 : 74 }), opacity: cap,
        transform: `translateY(${(1 - cap) * 20}px)`, fontFamily: SERIF, fontSize: 70, fontWeight: 500, letterSpacing: -1.2,
        color: C.ink }}>{shot.caption}</div>
      {shot.sub && <div style={{ position: "absolute", left: 98, bottom: 66, opacity: sub, transform: `translateY(${(1 - sub) * 14}px)`,
        fontSize: 32, color: C.ink2 }}>{shot.sub}</div>}
      {!shot.top && <div style={{ position: "absolute", right: 96, bottom: 74, fontSize: 22, color: C.ink3, opacity: cap }}>
        Real paper trades from {(shot.showcase ? rec.showcase : rec.strategy).id}, {recorded}</div>}
    </AbsoluteFill>
  );
};

const Wordmark = ({ size }: { size: number }) =>
  <span style={{ fontFamily: SERIF, fontSize: size, fontWeight: 400, letterSpacing: -size * 0.02, color: C.ink }}>Nemi</span>;

const Hook = () => {
  const f = useCurrentFrame();
  const out = interpolate(f, [HOOK - 12, HOOK], [1, 0], clamp);
  return (
    <AbsoluteFill style={{ background: C.bg, justifyContent: "center", alignItems: "center", opacity: out }}>
      <AbsoluteFill style={{ opacity: 0.16, filter: "blur(14px)", transform: "scale(1.06)" }}>
        <OffthreadVideo src={staticFile("nemi/app.mp4")} muted trimBefore={Math.round((ev.report + 0.4) * FPS)}
          style={{ width: W, height: H }} />
      </AbsoluteFill>
      {/* Mostly in at frame 0: X shows the first frame before the video plays. */}
      <Rise delay={-10} style={{ display: "flex", alignItems: "center", gap: 26 }}>
        <Wordmark size={76} />
        <span style={{ fontSize: 28, fontWeight: 600, color: C.accent, background: C.accentSoft, border: `2px solid ${C.accent}`,
          borderRadius: 999, padding: "6px 20px", marginTop: 6 }}>New: paper trading</span>
      </Rise>
      <Rise delay={-6} style={{ fontFamily: SERIF, fontSize: 132, fontWeight: 500, letterSpacing: -3.5, marginTop: 36,
        textAlign: "center", lineHeight: 1.02, color: C.ink }}>
        Paper trade on Nemi,<br /><span style={{ color: C.accent }}>as close to live as it gets.</span>
      </Rise>
      <Rise delay={14} style={{ fontSize: 34, color: C.ink2, marginTop: 40 }}>
        Fees, slippage, partial fills and refused orders. Just like live.
      </Rise>
    </AbsoluteFill>
  );
};

const End = () => (
  <AbsoluteFill style={{ background: C.bg, justifyContent: "center", alignItems: "center", textAlign: "center",
    opacity: interpolate(useCurrentFrame(), [0, 10], [0, 1], clamp) }}>
    <Rise><Wordmark size={150} /></Rise>
    <Rise delay={6} style={{ fontFamily: SERIF, fontSize: 64, marginTop: 24, lineHeight: 1.2, color: C.ink }}>
      Paper trade before you trade real money.
    </Rise>
    <Rise delay={12} style={{ fontFamily: MONO, fontSize: 52, marginTop: 44, color: C.accent }}>nemi.markets</Rise>
    <Rise delay={18} style={{ fontSize: 26, marginTop: 48, color: C.ink3 }}>
      Paper money. Polymarket's live order books. Bitcoin 15-minute Up or Down markets.
    </Rise>
  </AbsoluteFill>
);

// Sound: a tick on the click, over the owner's pick of music when it's in public/ (not in git): `music` from `from`
// seconds, at `gain`, faded in over a third of a second. No track: the tick only. The default is "Precision Pulse" from
// 27.34 s: its build-up plays under the hook and its drop (30.57 s) lands as the first shot cuts in (frame 97).
export type NemiProps = { music: string; from: number; gain: number };
export const NEMI_DEFAULTS: NemiProps = { music: "nemi-music.wav", from: 27.34, gain: 0.95 };
const CLICKS = [ev.pick].map((t) => frameOf(t + 0.05));
const Sound = ({ music, from, gain }: NemiProps) => (
  <>
    {getStaticFiles().some((f) => f.name === music) && (
      <Audio src={staticFile(music)} trimBefore={Math.round(from * FPS)}
        volume={(f) => interpolate(f, [0, 10, NEMI_DURATION - 36, NEMI_DURATION], [0, gain, gain, 0], clamp)} />
    )}
    {CLICKS.map((c) => <Sequence key={c} from={c} durationInFrames={6}><Audio src={staticFile("tick.wav")} volume={0.6} /></Sequence>)}
  </>
);

export const Nemi = (music: NemiProps) => (
  <AbsoluteFill style={{ background: C.bg, color: C.ink, fontFamily: SANS }}>
    <Sound {...music} />
    {SHOTS.map((s, i) => (
      <Sequence key={i} from={starts[i]} durationInFrames={len(i)}><ShotView shot={s} frames={len(i)} /></Sequence>
    ))}
    <Sequence from={0} durationInFrames={HOOK}><Hook /></Sequence>
    <Sequence from={END}><End /></Sequence>
  </AbsoluteFill>
);
