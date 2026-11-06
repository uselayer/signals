import type { CSSProperties, ReactNode } from "react";
import { AbsoluteFill, Audio, Easing, OffthreadVideo, Sequence, getStaticFiles, interpolate, staticFile, useCurrentFrame } from "remotion";
import { loadFont } from "@remotion/fonts";
import out from "./starters.json";
import rec from "../public/starters/events.json";

// "Starter bots" on Layer: the Starter bot page as someone who answered "a trading bot" sees it, then the same bot on a
// laptop. public/starters/app.mp4 is a scripted recording of the real page component with live prices
// (npm run record:starters); src/starters.json is a real run of price_gaps.py --once (the file uselayer.sh serves).
// Colors and fonts are uselayer.sh's own (app/globals.css: paper, ink, accent; Host Grotesk + IBM Plex Mono).
const C = { paper: "#f2f0e9", ink: "#141519", muted: "#67655f", rule: "#d3cfc4", accent: "#e6c229",
  term: "#141519", termFg: "#ece9e1", termMuted: "#9b988f", termRule: "#2e3036", termGreen: "#6fbf87" };
const FONT = "Host Grotesk", MONO = "IBM Plex Mono";
loadFont({ family: FONT, url: staticFile("HostGrotesk-latin-var.woff2"), weight: "300 800" });
loadFont({ family: MONO, url: staticFile("IBMPlexMono-latin-400.woff2"), weight: "400" });
loadFont({ family: MONO, url: staticFile("IBMPlexMono-latin-500.woff2"), weight: "500" });

const FPS = 30, W = 1920, H = 1080;
const ev = rec.events;
const ease = Easing.inOut(Easing.cubic);
const clamp = { extrapolateLeft: "clamp", extrapolateRight: "clamp" } as const;

// Stretches of the recording, each with a caption and camera keyframes [source second, center x, center y, zoom]
// in the page's 1920×1080 layout.
type Shot = { from: number; to: number; rate: number; caption: string; cam: [number, number, number, number][] };
const SHOTS: Shot[] = [
  { from: 0.2, to: ev.scroll, rate: 1.2, caption: "The same market on two venues, priced live",
    cam: [[0.2, 960, 560, 1.12], [ev.summary - 0.6, 1350, 330, 1.55], [ev.summary + 1.2, 1350, 330, 1.55],
      [ev.rowStart, 760, 520, 1.6], [ev.rowSaved, 1250, 520, 1.6], [ev.scroll, 1100, 540, 1.3]] },
  { from: ev.scroll, to: ev.end - 0.1, rate: 1.25, caption: "Copy one prompt into your coding agent",
    cam: [[ev.scroll, 1100, 540, 1.3], [ev.run, 900, 640, 1.35], [ev.copied, 600, 630, 1.75], [ev.end, 600, 630, 1.75]] },
];
const XF = 8, HOOK = 72, TERM = 168, ENDLEN = 96;
const starts: number[] = [];
let at = HOOK - XF;
for (const s of SHOTS) { starts.push(at); at += Math.round(((s.to - s.from) / s.rate) * FPS) - XF; }
const TERM_AT = at, END_AT = TERM_AT + TERM - XF;
export const STARTER_BOT_DURATION = END_AT + ENDLEN;
const len = (i: number) => Math.round(((SHOTS[i].to - SHOTS[i].from) / SHOTS[i].rate) * FPS);
const frameOf = (t: number) => {
  const i = SHOTS.findIndex((s) => t >= s.from && t <= s.to);
  return starts[i] + Math.round(((t - SHOTS[i].from) / SHOTS[i].rate) * FPS);
};

const useRise = (delay = 0, dur = 16) => {
  const t = interpolate(useCurrentFrame(), [delay, delay + dur], [0, 1], { ...clamp, easing: Easing.out(Easing.cubic) });
  return { opacity: t, transform: `translateY(${(1 - t) * 30}px)` } as CSSProperties;
};
const Rise = ({ delay, children, style }: { delay?: number; children: ReactNode; style?: CSSProperties }) =>
  <div style={{ ...useRise(delay), ...style }}>{children}</div>;
// The page's own highlight: the yellow behind the cheaper price.
const Mark = ({ children }: { children: ReactNode }) =>
  <span style={{ background: C.accent, padding: "0 .12em", boxDecorationBreak: "clone", WebkitBoxDecorationBreak: "clone" }}>{children}</span>;
const Wordmark = ({ size }: { size: number }) => (
  <span style={{ display: "inline-flex", alignItems: "center", gap: size * 0.4, fontSize: size, fontWeight: 600, letterSpacing: -size * 0.03 }}>
    <svg viewBox="0 0 28 20" width={size * 1.15} height={size * 0.82}>
      {/* uselayer.sh's own mark (components/account/logo.tsx) */}
      <path d="M1 3H8L14 10M1 10H14M1 17H8L14 10" fill="none" stroke={C.ink} strokeWidth={2} />
      <rect x={14} y={7} width={13} height={6} fill={C.ink} />
    </svg>layer
  </span>
);

const ShotView = ({ shot, frames }: { shot: Shot; frames: number }) => {
  const f = useCurrentFrame();
  const t = shot.from + (f / FPS) * shot.rate;
  const k = shot.cam, ts = k.map((c) => c[0]);
  const pick = (j: number) => interpolate(t, ts, k.map((c) => c[j]), { ...clamp, easing: ease });
  const z = pick(3);
  const cx = Math.min(Math.max(pick(1), W / 2 / z), W - W / 2 / z), cy = Math.min(Math.max(pick(2), H / 2 / z), H - H / 2 / z);
  const fade = interpolate(f, [0, XF], [0, 1], clamp);
  const cap = interpolate(f, [4, 18, frames - 6, frames], [0, 1, 1, 0], clamp);
  return (
    <AbsoluteFill style={{ opacity: fade, background: C.paper, overflow: "hidden" }}>
      <div style={{ position: "absolute", width: W, height: H, transformOrigin: "0 0",
        transform: `translate(${W / 2 - cx * z}px, ${H / 2 - cy * z}px) scale(${z})` }}>
        <OffthreadVideo src={staticFile("starters/app.mp4")} muted trimBefore={Math.round(shot.from * FPS)}
          playbackRate={shot.rate} style={{ width: W, height: H }} />
      </div>
      <div style={{ position: "absolute", left: 0, right: 0, bottom: 0, height: 250,
        background: `linear-gradient(to top, ${C.paper} 30%, ${C.paper}00)` }} />
      <div style={{ position: "absolute", left: 96, bottom: 66, opacity: cap, transform: `translateY(${(1 - cap) * 20}px)`,
        fontSize: 58, fontWeight: 600, letterSpacing: -1.6, color: C.ink }}>{shot.caption}</div>
    </AbsoluteFill>
  );
};

const Hook = () => {
  const f = useCurrentFrame();
  const out = interpolate(f, [HOOK - 12, HOOK], [1, 0], clamp);
  return (
    <AbsoluteFill style={{ background: C.paper, justifyContent: "center", alignItems: "center", opacity: out }}>
      <AbsoluteFill style={{ opacity: 0.16, filter: "blur(16px)", transform: "scale(1.06)" }}>
        <OffthreadVideo src={staticFile("starters/app.mp4")} muted trimBefore={Math.round(ev.rowStart * FPS)} style={{ width: W, height: H }} />
      </AbsoluteFill>
      {/* Mostly in at frame 0: X shows the first frame before the video plays. */}
      <Rise delay={-10} style={{ display: "flex", alignItems: "center", gap: 26 }}>
        <Wordmark size={54} />
        <span style={{ fontSize: 28, fontWeight: 500, border: `2px solid ${C.ink}`, padding: "6px 16px", marginLeft: 6 }}>New: starter bots</span>
      </Rise>
      <Rise delay={-6} style={{ fontSize: 124, fontWeight: 600, letterSpacing: -4.5, marginTop: 44, textAlign: "center", lineHeight: 1.06 }}>
        Your trading bot,<br /><Mark>already running.</Mark>
      </Rise>
    </AbsoluteFill>
  );
};

// price_gaps.py --once, as it printed: the command, then its table (the first rows) and its closing note.
const LINES = [...out.lines.slice(0, 11), out.lines[out.lines.length - 1]];  // header, the first 9 rows, the closing note
const Terminal = () => {
  const f = useCurrentFrame();
  const cmd = "python price_gaps.py --once";
  const typed = Math.round(interpolate(f, [16, 40], [0, cmd.length], clamp));
  const fade = interpolate(f, [0, XF, TERM - 10, TERM], [0, 1, 1, 0], clamp);
  const pop = interpolate(f, [0, 18], [0, 1], { ...clamp, easing: Easing.out(Easing.cubic) });
  return (
    <AbsoluteFill style={{ background: C.paper, opacity: fade }}>
      <Rise delay={2} style={{ position: "absolute", left: 96, top: 62, fontSize: 58, fontWeight: 600, letterSpacing: -1.6 }}>
        It runs on your laptop
      </Rise>
      <div style={{ position: "absolute", left: 96, right: 96, top: 176, background: C.term, border: `2px solid ${C.ink}`,
        transform: `translateY(${(1 - pop) * 40}px)`, opacity: pop, fontFamily: MONO, color: C.termFg, overflow: "hidden" }}>
        <div style={{ height: 52, borderBottom: `1px solid ${C.termRule}`, display: "flex", alignItems: "center", padding: "0 22px", gap: 10 }}>
          {["#ec6a5e", "#f4bf4f", "#61c554"].map((c) => <span key={c} style={{ width: 15, height: 15, borderRadius: 8, background: c }} />)}
          <span style={{ flex: 1, textAlign: "center", fontSize: 20, color: C.termMuted, marginRight: 70 }}>layer-price-gaps</span>
        </div>
        <div style={{ padding: "22px 30px", fontSize: 26.5, lineHeight: 1.5, whiteSpace: "pre" }}>
          <div><span style={{ color: C.termGreen }}>~/layer-price-gaps</span> <span style={{ color: C.termMuted }}>$</span> {cmd.slice(0, typed)}
            {f < 50 && <span style={{ opacity: Math.floor(f / 8) % 2 ? 0 : 1, background: C.termFg }}> </span>}</div>
          {LINES.map((l, i) => {
            const at = 52 + i * 4;
            const head = i < 2, top = i >= 2 && i < 7, note = i === LINES.length - 1;
            return (
              <div key={i} style={{ opacity: interpolate(f, [at, at + 5], [0, 1], clamp),
                color: head || note ? C.termMuted : C.termFg, fontWeight: top ? 500 : 400,
                background: top ? "rgba(230,194,41,.16)" : undefined, marginTop: note ? 8 : 0 }}>{l || " "}</div>
            );
          })}
        </div>
      </div>
    </AbsoluteFill>
  );
};

const End = () => (
  <AbsoluteFill style={{ background: C.paper, justifyContent: "center", alignItems: "center", textAlign: "center",
    opacity: interpolate(useCurrentFrame(), [0, 10], [0, 1], clamp) }}>
    <Rise><Wordmark size={96} /></Rise>
    <Rise delay={6} style={{ fontSize: 50, marginTop: 40, lineHeight: 1.25 }}>
      Tell us what you&apos;re building.<br />Get a starter bot for it, running live.
    </Rise>
    <Rise delay={12} style={{ fontSize: 56, marginTop: 42, fontWeight: 600 }}><Mark>uselayer.sh</Mark></Rise>
    <Rise delay={18} style={{ fontSize: 24, marginTop: 44, color: C.muted }}>Starter bots read market data. None places an order.</Rise>
  </AbsoluteFill>
);

// Ticks on the clicks; music is the owner's pick by ear (a file in public/, not in git), off until one is chosen.
export type StarterBotProps = { music: string; from: number; gain: number };
export const STARTER_BOT_DEFAULTS: StarterBotProps = { music: "", from: 0, gain: 0.6 };
const CLICKS = [frameOf(ev.copied - 0.05)];
const Sound = ({ music, from, gain }: StarterBotProps) => (
  <>
    {music && getStaticFiles().some((f) => f.name === music) && (
      <Audio src={staticFile(music)} trimBefore={Math.round(from * FPS)}
        volume={(f) => interpolate(f, [0, 2, STARTER_BOT_DURATION - 36, STARTER_BOT_DURATION], [0, gain, gain, 0], clamp)} />
    )}
    {CLICKS.map((c) => <Sequence key={c} from={c} durationInFrames={6}><Audio src={staticFile("tick.wav")} volume={0.6} /></Sequence>)}
  </>
);

export const StarterBot = (props: StarterBotProps) => (
  <AbsoluteFill style={{ background: C.paper, color: C.ink, fontFamily: FONT }}>
    <Sound {...props} />
    {SHOTS.map((s, i) => (
      <Sequence key={i} from={starts[i]} durationInFrames={len(i)}><ShotView shot={s} frames={len(i)} /></Sequence>
    ))}
    <Sequence from={0} durationInFrames={HOOK}><Hook /></Sequence>
    <Sequence from={TERM_AT} durationInFrames={TERM}><Terminal /></Sequence>
    <Sequence from={END_AT}><End /></Sequence>
  </AbsoluteFill>
);
