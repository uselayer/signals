import type { CSSProperties, ReactNode } from "react";
import { AbsoluteFill, Audio, Easing, Img, Sequence, getStaticFiles, interpolate, staticFile, useCurrentFrame } from "remotion";
import { loadFont } from "@remotion/fonts";
import data from "./nemi-costs.json";
import shot from "../public/nemi/strategy.json";

// "What paper hides": one strategy's same orders, ideal paper against Nemi's real fills. Every figure is from
// src/nemi-costs.json, made by research/make_costs.py from the live engine's own API (research/nemi_raw.json): paper =
// each order filled in full at the price it asked, no fee; real = what Nemi filled and charged. Motion graphics, then
// the product itself: a still of a strategy's page (public/nemi/strategy.png, scripts/shot-nemi.mjs). 4:5 for the phone. Colors and fonts are the site's (~/dev/nemi src/index.css).
const C = { bg: "#000000", raised: "#0e0e10", ink: "#e6f5ef", ink2: "#a3b5ae", ink3: "#6b7c76", rule: "#1c1c1f",
  accent: "#3dffc5", accentSoft: "#06251c", win: "#00d26a", loss: "#ff4d4d" };
const SERIF = "Newsreader", SANS = "Inter", MONO = "JetBrains Mono";
loadFont({ family: SERIF, url: staticFile("nemi/newsreader-latin-400-normal.woff2"), weight: "400" });
loadFont({ family: SERIF, url: staticFile("nemi/newsreader-latin-500-normal.woff2"), weight: "500" });
loadFont({ family: SANS, url: staticFile("nemi/inter-latin-wght-normal.woff2"), weight: "100 900" });
loadFont({ family: MONO, url: staticFile("nemi/jetbrains-mono-latin-400-normal.woff2"), weight: "400" });

const FPS = 30;
const HOOK = 90, COSTS = 90, PUNCH = 330, PLATFORM = 420, END = 540;
export const NEMI_COSTS_DURATION = 660;
const FEE_AT = COSTS + 30, SLIP_AT = COSTS + 95, LAND = COSTS + 170;  // when each cost starts eating, and the landing

const clamp = { extrapolateLeft: "clamp", extrapolateRight: "clamp" } as const;
const out3 = Easing.out(Easing.cubic);
const money = (v: number) => `${v < 0 ? "−" : v > 0 ? "+" : ""}$${Math.abs(v).toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
const cents = (p: number) => `${Math.round(p * 1000) / 10}¢`;
const hours = Math.round((Date.parse(data.to) - Date.parse(data.from)) / 3.6e6);
const whole = (v: number) => `$${Math.trunc(Math.abs(v)).toLocaleString("en-US")}`;  // the cents dropped, never rounded up
const pnlColor = (v: number) => (v < 0 ? C.loss : v > 0 ? C.win : C.ink);
const gap = Math.round(data.paper - data.real).toLocaleString("en-US");

const Rise = ({ at = 0, children, style }: { at?: number; children: ReactNode; style?: CSSProperties }) => {
  const t = interpolate(useCurrentFrame(), [at, at + 14], [0, 1], { ...clamp, easing: out3 });
  return <div style={{ opacity: t, transform: `translateY(${(1 - t) * 28}px)`, ...style }}>{children}</div>;
};
const Wordmark = ({ size }: { size: number }) =>
  <span style={{ fontFamily: SERIF, fontSize: size, fontWeight: 400, letterSpacing: -size * 0.02, color: C.ink }}>Nemi</span>;
const Big = ({ value, color, size = 168 }: { value: number; color: string; size?: number }) =>
  <div style={{ fontFamily: SANS, fontWeight: 700, fontSize: size, letterSpacing: -size * 0.045, color,
    fontVariantNumeric: "tabular-nums", lineHeight: 1 }}>{money(value)}</div>;

// The same orders on paper: in at frame 0, since X shows the first frame before the video plays.
const Paper = () => {
  const f = useCurrentFrame();
  const shrink = interpolate(f, [HOOK - 10, HOOK + 6], [1, 0], { ...clamp, easing: out3 });
  return (
    <div style={{ position: "absolute", left: 90, right: 90, top: interpolate(shrink, [0, 1], [150, 300]) }}>
      <div style={{ fontSize: 30, color: C.ink3, letterSpacing: 0.4 }}>
        Same strategy · {data.orders} orders · {hours} hours</div>
      <div style={{ fontFamily: SERIF, fontSize: interpolate(shrink, [0, 1], [52, 78]), color: C.ink2, marginTop: 34 }}>Paper said</div>
      <div style={{ marginTop: 10, transformOrigin: "0 50%", transform: `scale(${interpolate(shrink, [0, 1], [0.5, 1])})` }}>
        <Big value={data.paper} color={pnlColor(data.paper)} /></div>
      <div style={{ fontSize: 28, color: C.ink3, marginTop: interpolate(shrink, [0, 1], [-60, 26]), opacity: shrink }}>
        Every order filled at the price it asked. No fees.</div>
    </div>
  );
};

// One cost row: label, what it took, a bar that fills while the real number falls.
const Row = ({ at, label, sub, value, children }: { at: number; label: string; sub: string; value: number; children?: ReactNode }) => {
  const f = useCurrentFrame();
  const t = interpolate(f, [at, at + 60], [0, 1], { ...clamp, easing: Easing.inOut(Easing.cubic) });
  return (
    <Rise at={at - 8} style={{ marginTop: 34, borderTop: `2px solid ${C.rule}`, paddingTop: 26 }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline" }}>
        <div style={{ fontSize: 40, fontWeight: 600, color: C.ink }}>{label}</div>
        <div style={{ fontFamily: SANS, fontSize: 44, fontWeight: 700, color: C.loss, fontVariantNumeric: "tabular-nums" }}>
          {money(-value * t)}</div>
      </div>
      <div style={{ fontSize: 27, color: C.ink2, marginTop: 8 }}>{sub}</div>
      {children}
    </Rise>
  );
};

// Order #239 walking the book: each level it bought from lights up in turn, its price climbing past the one it asked.
const Book = ({ at }: { at: number }) => {
  const f = useCurrentFrame();
  const ex = data.example, most = Math.max(...ex.levels.map((l) => l[1]));
  return (
    <div style={{ marginTop: 20, display: "flex", gap: 12, alignItems: "flex-end", height: 150 }}>
      {ex.levels.map(([p, q], i) => {
        const on = interpolate(f, [at + i * 7, at + i * 7 + 8], [0, 1], clamp);
        return (
          <div key={p} style={{ flex: 1, display: "flex", flexDirection: "column", alignItems: "center", gap: 8 }}>
            <div style={{ width: "100%", height: 20 + (q / most) * 90, borderRadius: 6,
              background: on > 0.5 ? (i === 0 ? C.accent : C.loss) : C.raised, opacity: 0.35 + on * 0.65 }} />
            <div style={{ fontFamily: MONO, fontSize: 24, color: on > 0.5 ? C.ink : C.ink3 }}>{cents(p)}</div>
          </div>
        );
      })}
    </div>
  );
};

// The live number at frame f: paper, less each cost as it eats in; exactly the real result from the landing on.
const realAt = (f: number) => {
  if (f >= LAND) return data.real;
  const feeT = interpolate(f, [FEE_AT, FEE_AT + 60], [0, 1], { ...clamp, easing: Easing.inOut(Easing.cubic) });
  const slipT = interpolate(f, [SLIP_AT, SLIP_AT + 60], [0, 1], { ...clamp, easing: Easing.inOut(Easing.cubic) });
  const rest = interpolate(f, [LAND - 20, LAND], [0, 1], clamp);
  return data.paper - data.fees * feeT - data.slippage * slipT - data.other * rest;
};
// When it crosses zero (a win on paper turning into a loss), if it does: a tick there too.
const ZERO = data.paper > 0 && data.real < 0 ? Array.from({ length: LAND - COSTS }, (_, i) => COSTS + i).find((f) => realAt(f) < 0) : undefined;

const Costs = () => {
  const f = useCurrentFrame() + COSTS;
  const real = realAt(f);
  const pulse = 1 + 0.06 * Math.sin(Math.min(1, Math.max(0, (f - LAND) / 10)) * Math.PI);
  const ex = data.example;
  return (
    <div style={{ position: "absolute", left: 90, right: 90, top: 500 }}>
      <Rise at={-2} style={{ fontFamily: SERIF, fontSize: 78, color: C.ink }}>Live order book said</Rise>
      <div style={{ marginTop: 10, transformOrigin: "0 50%", transform: `scale(${pulse})` }}>
        <Big value={real} color={pnlColor(real)} /></div>
      <Row at={FEE_AT - COSTS} label="Polymarket's fee" sub="Charged on every fill. Paper tests skip it." value={data.fees} />
      <Row at={SLIP_AT - COSTS} label="Slippage" value={data.slippage}
        sub={`Big orders walk the book: asked ${cents(ex.asked)}, paid ${cents(ex.paid)} on average`}>
        <Book at={SLIP_AT - COSTS + 4} />
      </Row>
    </div>
  );
};

const Punch = () => (
  <AbsoluteFill style={{ background: C.bg, justifyContent: "center", padding: "0 90px",
    opacity: interpolate(useCurrentFrame(), [0, 8], [0, 1], clamp) }}>
    <Rise style={{ fontFamily: SERIF, fontSize: 84, color: C.ink, lineHeight: 1.1, whiteSpace: "nowrap" }}>
      {data.paper >= 0 ? "Won " : "Lost "}<span style={{ color: pnlColor(data.paper) }}>{whole(data.paper)}</span> on paper.</Rise>
    <Rise at={10} style={{ fontFamily: SERIF, fontSize: 84, color: C.ink, lineHeight: 1.1, marginTop: 14, whiteSpace: "nowrap" }}>
      {data.real >= 0 ? "Won " : "Lost "}<span style={{ color: pnlColor(data.real) }}>{whole(data.real)}</span> live.</Rise>
    <Rise at={20} style={{ fontSize: 40, color: C.ink2, marginTop: 44, lineHeight: 1.35 }}>
      ${gap} in fees, slippage and missed fills that a paper test never charged.</Rise>
  </AbsoluteFill>
);

// The product: the strategy page's stat tiles (Costs ringed), then into its trades table (asked, filled, slip and fee
// ringed). Camera keyframes [frame, center x, center y, zoom] in the still's layout pixels (1920×1200, drawn at 2×); the
// frame's left edge stays right of the sidebar (x < 220), which lists the other example strategy.
const SW = 1920, SH = 1200, FW = 1080, FH = 1350;
const CAM: [number, number, number, number][] = [[0, 800, 371, 0.92], [48, 800, 371, 0.92], [82, 1053, 584, 1.75], [120, 1053, 600, 1.75]];
const COLS = { x: 914, y: 404, w: 278, h: 482 };  // Asked, Filled, Slip and Fee: header and the first rows (Book at fill: x 1204)
const Ring = ({ box, at, pad = 10 }: { box: { x: number; y: number; w: number; h: number }; at: number; pad?: number }) => {
  const t = interpolate(useCurrentFrame(), [at, at + 10], [0, 1], { ...clamp, easing: out3 });
  return <div style={{ position: "absolute", left: box.x - pad, top: box.y - pad, width: box.w + pad * 2, height: box.h + pad * 2,
    border: `3px solid ${C.accent}`, borderRadius: 10, opacity: t, transform: `scale(${1.08 - 0.08 * t})`,
    boxShadow: `0 0 28px ${C.accent}55` }} />;
};
const Platform = () => {
  const f = useCurrentFrame(), n = END - PLATFORM;
  const pick = (j: number) => interpolate(f, CAM.map((c) => c[0]), CAM.map((c) => c[j]), { ...clamp, easing: Easing.inOut(Easing.cubic) });
  const z = pick(3), cx = pick(1), cy = pick(2);
  const fade = interpolate(f, [0, 8, n - 8, n], [0, 1, 1, 0], clamp);
  return (
    <AbsoluteFill style={{ background: C.bg, overflow: "hidden", opacity: fade }}>
      <div style={{ position: "absolute", width: SW, height: SH, transformOrigin: "0 0",
        transform: `translate(${FW / 2 - cx * z}px, ${FH / 2 - cy * z}px) scale(${z})` }}>
        <Img src={staticFile("nemi/strategy.png")} style={{ width: SW, height: SH }} />
        {shot.costs && <Ring box={shot.costs} at={14} />}
        <Ring box={COLS} at={84} pad={4} />
      </div>
      <div style={{ position: "absolute", left: 0, right: 0, top: 0, height: 400,
        background: `linear-gradient(to bottom, ${C.bg} 72%, ${C.bg}00)` }} />
      <Rise at={2} style={{ position: "absolute", left: 90, right: 90, top: 70, fontFamily: SERIF, fontSize: 70, fontWeight: 500,
        letterSpacing: -1.2, lineHeight: 1.05, color: C.ink }}>Nemi shows every<br />fee and fill.</Rise>
      <Rise at={10} style={{ position: "absolute", left: 92, top: 236, fontSize: 28, color: C.ink2 }}>
        On every strategy, every trade. Here: {shot.strategy}, live.</Rise>
    </AbsoluteFill>
  );
};

const EndCard = () => (
  <AbsoluteFill style={{ background: C.bg, justifyContent: "center", alignItems: "center", textAlign: "center", padding: "0 80px",
    opacity: interpolate(useCurrentFrame(), [0, 10], [0, 1], clamp) }}>
    <Rise><Wordmark size={170} /></Rise>
    <Rise at={6} style={{ fontFamily: SERIF, fontSize: 66, marginTop: 26, lineHeight: 1.15, color: C.ink }}>
      Paper trading that charges you<br /><span style={{ color: C.accent }}>like live does.</span></Rise>
    <Rise at={12} style={{ fontFamily: MONO, fontSize: 56, marginTop: 52, color: C.accent }}>nemi.markets</Rise>
    <Rise at={18} style={{ fontSize: 26, marginTop: 60, color: C.ink3, lineHeight: 1.45 }}>
      Real paper trades by Nemi's example strategy {data.strategy}:<br />its first {data.orders} orders, Oct 26–27.<br />
      Paper: each order filled in full at the price it asked, no fees.</Rise>
  </AbsoluteFill>
);

// Sound: the owner's pick of music when it's in public/ (not in git), from `from` seconds at `gain`; a tick as each
// cost starts and as the real number lands. No track: the ticks only.
export type NemiCostsProps = { music: string; from: number; gain: number };
// "Still I Rise" (the owner's pick, 10-30) from 190.5 s: a near-silent gap, its build under the hook, and the drop into
// the track's loudest stretch (about 193.5–214 s) as "Live order book said" comes in.
export const NEMI_COSTS_DEFAULTS: NemiCostsProps = { music: "still-i-rise.wav", from: 190.5, gain: 0.9 };
const TICKS = [FEE_AT, SLIP_AT, ...(ZERO ? [ZERO] : []), LAND, PUNCH];
const Sound = ({ music, from, gain }: NemiCostsProps) => (
  <>
    {getStaticFiles().some((f) => f.name === music) && (
      <Audio src={staticFile(music)} trimBefore={Math.round(from * FPS)}
        volume={(f) => interpolate(f, [0, 10, NEMI_COSTS_DURATION - 36, NEMI_COSTS_DURATION], [0, gain, gain, 0], clamp)} />
    )}
    {TICKS.map((t) => <Sequence key={t} from={t} durationInFrames={6}><Audio src={staticFile("tick.wav")} volume={0.6} /></Sequence>)}
  </>
);

export const NemiCosts = (music: NemiCostsProps) => (
  <AbsoluteFill style={{ background: C.bg, color: C.ink, fontFamily: SANS }}>
    <Sound {...music} />
    <Sequence from={0} durationInFrames={PUNCH}><Paper /></Sequence>
    <Sequence from={COSTS} durationInFrames={PUNCH - COSTS}><Costs /></Sequence>
    <Sequence from={PUNCH} durationInFrames={END - PUNCH}><Punch /></Sequence>
    <Sequence from={PLATFORM} durationInFrames={END - PLATFORM}><Platform /></Sequence>
    <Sequence from={END}><EndCard /></Sequence>
    <div style={{ position: "absolute", left: 90, bottom: 60, opacity: interpolate(useCurrentFrame(), [COSTS + 60, COSTS + 75, PUNCH, PUNCH + 8, PLATFORM - 8, PLATFORM], [1, 0, 0, 1, 1, 0], clamp) }}>
      <Wordmark size={44} /></div>
  </AbsoluteFill>
);
