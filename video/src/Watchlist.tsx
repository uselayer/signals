import type { CSSProperties, ReactNode } from "react";
import { AbsoluteFill, Audio, Easing, OffthreadVideo, Sequence, interpolate, spring, staticFile, useCurrentFrame,
  useVideoConfig } from "remotion";
import { loadFont } from "@remotion/fonts";
import data from "./watchlist.json";
import rec from "../public/watchlist/events.json";

// "Follow any Polymarket trader": the Watchlist launch, mostly the real app. public/watchlist/app.mp4 is a scripted
// recording of a local run of Signals (npm run record:watchlist); its step times are in events.json, and each segment
// below plays a stretch of it at its own speed with a camera that pushes in on what matters. The alert is drawn here,
// worded as Signals' real ones from one real trade (src/watchlist.json). Colors are the site's dark theme.
const C = {
  bg: "#0e0e0f", card: "#161617", fg: "#ececec", muted: "#8f8f95", line: "#26262a", soft: "#1b1b1e",
  gain: "#3ecf8e", accent: "#ff4d1f",
};
const FONT = "Host Grotesk";
loadFont({ family: FONT, url: staticFile("HostGrotesk-latin-var.woff2"), weight: "300 800" });

const FPS = 30, W = 1920, H = 1080;
const ev = rec.events;
const ease = Easing.inOut(Easing.cubic);

// A stretch of the recording [from, to] (seconds in app.mp4) played at `rate`, under a caption, with camera keyframes
// [source second, center x, center y, zoom] in the recording's 1920×1080 layout.
type Shot = { from: number; to: number; rate: number; caption: string; cam: [number, number, number, number][] };
const SHOTS: Shot[] = [
  { from: ev.followSheet - 0.75, to: ev.followed + 0.08, rate: 1.25, caption: "Paste any trader's Polymarket profile",
    cam: [[0, 1280, 360, 1.5], [ev.followSheet - 0.1, 1280, 360, 1.5], [ev.followSheet + 0.5, 960, 540, 2], [ev.found + 0.1, 960, 540, 2],
      [ev.found + 0.7, 960, 540, 1.72]] },
  { from: ev.watch, to: ev.tilesSeen + 0.25, rate: 1, caption: "Their record at a glance",
    cam: [[ev.watch, 960, 420, 1.32], [ev.tilesSeen, 960, 360, 1.55]] },
  { from: ev.tilesSeen + 0.25, to: ev.picked - 0.3, rate: 1.6, caption: "Every change they make",
    cam: [[ev.tilesSeen + 0.25, 960, 420, 1.5], [ev.scrollDown, 960, 560, 1.26], [ev.picked, 960, 560, 1.26]] },
  { from: ev.picked - 0.3, to: ev.holding - 0.05, rate: 1, caption: "Each one, explained",
    cam: [[ev.picked - 0.3, 960, 560, 1.26], [ev.picked + 0.1, 960, 560, 1.26], [ev.picked + 0.75, 1270, 545, 1.85]] },
  { from: ev.holding, to: ev.end - 0.4, rate: 1.1, caption: "What they hold right now",
    cam: [[ev.holding, 960, 430, 1.42], [ev.end, 960, 480, 1.5]] },
];
const XF = 8;  // frames each shot fades in over the one before
const HOOK = 75;
const starts: number[] = [];
let at = HOOK - XF;
for (const s of SHOTS) { starts.push(at); at += Math.round(((s.to - s.from) / s.rate) * FPS) - XF; }
const ALERT = at, END = ALERT + 115;
export const WATCHLIST_DURATION = END + 80;
const len = (i: number) => Math.round(((SHOTS[i].to - SHOTS[i].from) / SHOTS[i].rate) * FPS);
// A moment of the recording, as a frame of the video (the first shot that shows it).
const frameOf = (t: number) => {
  const i = SHOTS.findIndex((s) => t >= s.from && t <= s.to);
  return starts[i] + Math.round(((t - SHOTS[i].from) / SHOTS[i].rate) * FPS);
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

const clamp = { extrapolateLeft: "clamp", extrapolateRight: "clamp" } as const;
const useRise = (delay = 0, dur = 16) => {
  const t = interpolate(useCurrentFrame(), [delay, delay + dur], [0, 1], { ...clamp, easing: Easing.out(Easing.cubic) });
  return { opacity: t, transform: `translateY(${(1 - t) * 36}px)` } as CSSProperties;
};
const Rise = ({ delay, children, style }: { delay?: number; children: ReactNode; style?: CSSProperties }) =>
  <div style={{ ...useRise(delay), ...style }}>{children}</div>;

// One shot: the recording, framed by its camera, with its caption.
const ShotView = ({ shot, frames }: { shot: Shot; frames: number }) => {
  const f = useCurrentFrame();
  const t = shot.from + (f / FPS) * shot.rate;  // where in the recording we are
  const k = shot.cam, ts = k.map((c) => c[0]);
  const pick = (j: number) => ts.length === 1 ? k[0][j] : interpolate(t, ts, k.map((c) => c[j]), { ...clamp, easing: ease });
  const z = pick(3);
  const cx = Math.min(Math.max(pick(1), W / 2 / z), W - W / 2 / z), cy = Math.min(Math.max(pick(2), H / 2 / z), H - H / 2 / z);
  const fade = interpolate(f, [0, XF], [0, 1], clamp);
  const cap = interpolate(f, [4, 18, frames - 6, frames], [0, 1, 1, 0], clamp);
  return (
    <AbsoluteFill style={{ opacity: fade, background: C.bg, overflow: "hidden" }}>
      <div style={{ position: "absolute", width: W, height: H, transformOrigin: "0 0",
        transform: `translate(${W / 2 - cx * z}px, ${H / 2 - cy * z}px) scale(${z})` }}>
        <OffthreadVideo src={staticFile("watchlist/app.mp4")} muted trimBefore={Math.round(shot.from * FPS)}
          playbackRate={shot.rate} style={{ width: W, height: H }} />
      </div>
      <div style={{ position: "absolute", left: 0, right: 0, bottom: 0, height: 260,
        background: `linear-gradient(to top, ${C.bg}f2 25%, ${C.bg}00)` }} />
      <div style={{ position: "absolute", left: 96, bottom: 70, opacity: cap, transform: `translateY(${(1 - cap) * 20}px)`,
        fontSize: 60, fontWeight: 650, letterSpacing: -1.5, textShadow: "0 4px 24px rgba(0,0,0,.6)" }}>{shot.caption}</div>
    </AbsoluteFill>
  );
};

const Hook = () => {
  const f = useCurrentFrame();
  const out = interpolate(f, [HOOK - 14, HOOK], [1, 0], clamp);
  return (
    <AbsoluteFill style={{ background: C.bg, justifyContent: "center", alignItems: "center", opacity: out }}>
      <AbsoluteFill style={{ opacity: 0.22, filter: "blur(18px)", transform: "scale(1.08)" }}>
        <OffthreadVideo src={staticFile("watchlist/app.mp4")} muted trimBefore={Math.round((ev.tilesSeen - 0.5) * FPS)}
          style={{ width: W, height: H }} />
      </AbsoluteFill>
      {/* Mostly in at frame 0: X shows the first frame before the video plays. */}
      <Rise delay={-10} style={{ display: "flex", alignItems: "center", gap: 22 }}>
        <Logo size={72} /><span style={{ fontSize: 56, fontWeight: 650 }}>Signals</span>
        <span style={{ fontSize: 30, fontWeight: 600, color: C.accent, border: `2px solid ${C.accent}`, borderRadius: 999,
          padding: "6px 18px", marginLeft: 8 }}>New: Watchlist</span>
      </Rise>
      <Rise delay={-6} style={{ fontSize: 132, fontWeight: 700, letterSpacing: -4.5, marginTop: 44, textAlign: "center", lineHeight: 1.02 }}>
        Follow any<br /><span style={{ color: C.accent }}>Polymarket trader.</span>
      </Rise>
    </AbsoluteFill>
  );
};

// The alert, as a phone shows it: a notification from the Signals bot on Telegram, the text exactly as Signals sends
// it (signals/app.py _alert_text: who bought which outcome at what price for how much, the market, the price now, when).
const a = data.alert;
const TelegramIcon = ({ size }: { size: number }) => (
  <div style={{ width: size, height: size, borderRadius: size * 0.24, background: "linear-gradient(#37aee2, #1e96c8)",
    display: "grid", placeItems: "center" }}>
    <svg viewBox="0 0 24 24" width={size * 0.6} height={size * 0.6}><path d="M2.5 11.3l17.6-6.8c.8-.3 1.6.2 1.3 1.4l-3 14.1c-.2 1-.8 1.2-1.7.8l-4.6-3.4-2.2 2.1c-.3.3-.5.5-1 .5l.3-4.7 8.6-7.8c.4-.3-.1-.5-.6-.2L6.5 13.9 2 12.5c-1-.3-1-1 .5-1.2z" fill="#fff" /></svg>
  </div>
);
const Alert = () => {
  const f = useCurrentFrame(), { fps } = useVideoConfig();
  const drop = spring({ frame: f - 22, fps, config: { damping: 15, mass: 0.8 } });
  const phone = spring({ frame: f, fps, config: { damping: 18 } });
  const out = interpolate(f, [END - ALERT - 10, END - ALERT], [1, 0], clamp);
  return (
    <AbsoluteFill style={{ background: C.bg, opacity: Math.min(out, interpolate(f, [0, XF], [0, 1], clamp)) }}>
      <div style={{ position: "absolute", left: 120, top: 330, width: 760 }}>
        <Rise delay={2} style={{ fontSize: 96, fontWeight: 700, letterSpacing: -3, lineHeight: 1.02 }}>
          Know when<br /><span style={{ color: C.accent }}>they trade.</span>
        </Rise>
        <Rise delay={10} style={{ fontSize: 38, color: C.muted, marginTop: 32, lineHeight: 1.3 }}>
          On Telegram, within about 30 seconds of their trade.
        </Rise>
        <Rise delay={18} style={{ fontSize: 24, color: C.muted, marginTop: 40, opacity: 0.8 }}>
          A real {data.name} trade, {a.date}.
        </Rise>
      </div>
      <div style={{ position: "absolute", right: 150, top: 60 + (1 - phone) * 260, width: 640, height: 1140, borderRadius: 84,
        border: "14px solid #2a2a2e", background: "radial-gradient(120% 80% at 30% 0%, #3a2a24 0%, #17151a 55%, #0b0b0d 100%)",
        boxShadow: "0 40px 120px rgba(0,0,0,.7)", overflow: "hidden" }}>
        <div style={{ position: "absolute", top: 18, left: "50%", marginLeft: -64, width: 128, height: 36, borderRadius: 20, background: "#000" }} />
        <div style={{ textAlign: "center", marginTop: 96, color: "#f2efe9" }}>
          <div style={{ fontSize: 26, fontWeight: 600, opacity: 0.85 }}>Sunday, October 18</div>
          <div style={{ fontSize: 140, fontWeight: 600, letterSpacing: -4, lineHeight: 1 }}>10:30</div>
        </div>
        <div style={{ position: "absolute", left: 16, right: 16, top: 320, transform: `translateY(${(1 - drop) * -140}px) scale(${0.92 + drop * 0.08})`,
          opacity: Math.min(1, drop * 1.5), background: "rgba(48,46,52,.86)", backdropFilter: "blur(20px)", borderRadius: 34,
          padding: "22px 24px", color: "#f4f4f6", boxShadow: "0 20px 50px rgba(0,0,0,.45)" }}>
          <div style={{ display: "flex", alignItems: "center", gap: 14 }}>
            <TelegramIcon size={52} />
            <div style={{ flex: 1, fontSize: 29, fontWeight: 650 }}>Signals</div>
            <div style={{ fontSize: 24, color: "#a9a9b0" }}>now</div>
          </div>
          <div style={{ fontSize: 28.5, lineHeight: 1.34, marginTop: 14 }}>
            <div><b>{data.name}</b> bought <b>{a.outcome}</b> at {a.paid} ({a.usd})</div>
            <div>{a.title}</div>
            <div>{a.now}</div>
            <div>{a.traded}</div>
          </div>
        </div>
      </div>
    </AbsoluteFill>
  );
};

const End = () => (
  <AbsoluteFill style={{ background: C.bg, justifyContent: "center", alignItems: "center", textAlign: "center",
    opacity: interpolate(useCurrentFrame(), [0, 10], [0, 1], clamp) }}>
    <Rise style={{ display: "flex", alignItems: "center", gap: 26 }}>
      <Logo size={104} /><span style={{ fontSize: 92, fontWeight: 700, letterSpacing: -3 }}>Signals</span>
    </Rise>
    <Rise delay={6} style={{ fontSize: 50, marginTop: 40, lineHeight: 1.25 }}>
      Follow any Polymarket trader.<br />See every trade, explained.
    </Rise>
    <Rise delay={12} style={{ fontSize: 56, marginTop: 40, color: C.accent, fontWeight: 650 }}>usesignals.app</Rise>
    <Rise delay={18} style={{ fontSize: 24, marginTop: 44, color: C.muted }}>Past trades, not advice. Signals places no orders.</Rise>
  </AbsoluteFill>
);

// Sound: ticks on the clicks and a ping when the alert lands (public/tick.wav, ping.wav). No music: the owner picks it.
const CLICKS = [ev.followSheet, ev.lookUp, ev.followed - 0.06, ev.picked].map((t) => frameOf(t - 0.09));
const Sound = () => (
  <>
    {CLICKS.map((c) => <Sequence key={c} from={c} durationInFrames={6}><Audio src={staticFile("tick.wav")} volume={0.6} /></Sequence>)}
    <Sequence from={ALERT + 22} durationInFrames={30}><Audio src={staticFile("ping.wav")} volume={1} /></Sequence>
  </>
);

export const Watchlist = () => (
  <AbsoluteFill style={{ background: C.bg, color: C.fg, fontFamily: FONT }}>
    <Sound />
    {SHOTS.map((s, i) => (
      <Sequence key={i} from={starts[i]} durationInFrames={len(i)}><ShotView shot={s} frames={len(i)} /></Sequence>
    ))}
    <Sequence from={0} durationInFrames={HOOK}><Hook /></Sequence>
    <Sequence from={starts[0]} durationInFrames={ALERT - starts[0]}>
      <div style={{ position: "absolute", right: 96, bottom: 84, fontSize: 24, color: C.muted }}>
        Live Polymarket data, recorded {data.recorded}</div>
    </Sequence>
    <Sequence from={ALERT} durationInFrames={END - ALERT}><Alert /></Sequence>
    <Sequence from={END}><End /></Sequence>
  </AbsoluteFill>
);
