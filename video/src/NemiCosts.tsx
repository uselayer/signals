import type { CSSProperties, ReactNode } from "react";
import { AbsoluteFill, Audio, Easing, Sequence, getStaticFiles, interpolate, staticFile, useCurrentFrame } from "remotion";
import { loadFont } from "@remotion/fonts";
import data from "./nemi-costs.json";

// "What paper hides": one strategy's same orders, ideal paper against Nemi's real fills. Every figure is from
// src/nemi-costs.json, made by research/make_costs.py from the live engine's own API (research/nemi_raw.json): paper =
// each order filled in full at the price it asked, no fee; real = what Nemi filled and charged. Motion graphics only,
// no screen recording. 4:5 for the phone. Colors and fonts are the site's (~/dev/nemi src/index.css).
const C = { bg: "#000000", raised: "#0e0e10", ink: "#e6f5ef", ink2: "#a3b5ae", ink3: "#6b7c76", rule: "#1c1c1f",
  accent: "#3dffc5", accentSoft: "#06251c", loss: "#ff4d4d" };
const SERIF = "Newsreader", SANS = "Inter", MONO = "JetBrains Mono";
loadFont({ family: SERIF, url: staticFile("nemi/newsreader-latin-400-normal.woff2"), weight: "400" });
loadFont({ family: SERIF, url: staticFile("nemi/newsreader-latin-500-normal.woff2"), weight: "500" });
loadFont({ family: SANS, url: staticFile("nemi/inter-latin-wght-normal.woff2"), weight: "100 900" });
loadFont({ family: MONO, url: staticFile("nemi/jetbrains-mono-latin-400-normal.woff2"), weight: "400" });

const FPS = 30;
const HOOK = 90, COSTS = 90, PUNCH = 330, END = 420;
export const NEMI_COSTS_DURATION = 540;
const FEE_AT = COSTS + 30, SLIP_AT = COSTS + 95, LAND = COSTS + 170;  // when each cost starts eating, and the landing

const clamp = { extrapolateLeft: "clamp", extrapolateRight: "clamp" } as const;
const out3 = Easing.out(Easing.cubic);
const money = (v: number) => `${v < 0 ? "−" : ""}$${Math.abs(v).toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
const cents = (p: number) => `${Math.round(p * 1000) / 10}¢`;
const hours = Math.round((Date.parse(data.to) - Date.parse(data.from)) / 3.6e6);
const times = (data.real / data.paper).toFixed(1);
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
        <Big value={data.paper} color={C.ink} /></div>
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

const Costs = () => {
  const f = useCurrentFrame() + COSTS;
  const feeT = interpolate(f, [FEE_AT, FEE_AT + 60], [0, 1], { ...clamp, easing: Easing.inOut(Easing.cubic) });
  const slipT = interpolate(f, [SLIP_AT, SLIP_AT + 60], [0, 1], { ...clamp, easing: Easing.inOut(Easing.cubic) });
  const rest = interpolate(f, [LAND - 20, LAND], [0, 1], clamp);
  const real = f >= LAND ? data.real : data.paper - data.fees * feeT - data.slippage * slipT - data.other * rest;
  const landed = interpolate(f, [LAND, LAND + 10], [0, 1], { ...clamp, easing: out3 });
  const pulse = 1 + 0.06 * Math.sin(Math.min(1, Math.max(0, (f - LAND) / 10)) * Math.PI);
  const ex = data.example;
  return (
    <div style={{ position: "absolute", left: 90, right: 90, top: 500 }}>
      <Rise at={-2} style={{ fontFamily: SERIF, fontSize: 78, color: C.ink }}>Live order book said</Rise>
      <div style={{ marginTop: 10, transformOrigin: "0 50%", transform: `scale(${pulse})` }}>
        <Big value={real} color={landed > 0 ? C.loss : C.ink} /></div>
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
    <Rise style={{ fontFamily: SANS, fontWeight: 700, fontSize: 230, letterSpacing: -10, color: C.loss, lineHeight: 1 }}>{times}×</Rise>
    <Rise at={6} style={{ fontFamily: SERIF, fontSize: 82, color: C.ink, marginTop: 20, lineHeight: 1.1 }}>the loss paper showed.</Rise>
    <Rise at={20} style={{ fontSize: 40, color: C.ink2, marginTop: 44, lineHeight: 1.35 }}>
      ${gap} in fees, slippage and missed fills that a paper test never charged.</Rise>
  </AbsoluteFill>
);

const EndCard = () => (
  <AbsoluteFill style={{ background: C.bg, justifyContent: "center", alignItems: "center", textAlign: "center", padding: "0 80px",
    opacity: interpolate(useCurrentFrame(), [0, 10], [0, 1], clamp) }}>
    <Rise><Wordmark size={170} /></Rise>
    <Rise at={6} style={{ fontFamily: SERIF, fontSize: 66, marginTop: 26, lineHeight: 1.15, color: C.ink }}>
      Paper trading that charges you<br /><span style={{ color: C.accent }}>like live does.</span></Rise>
    <Rise at={12} style={{ fontFamily: MONO, fontSize: 56, marginTop: 52, color: C.accent }}>nemi.markets</Rise>
    <Rise at={18} style={{ fontSize: 26, marginTop: 60, color: C.ink3, lineHeight: 1.45 }}>
      Real paper trades by Nemi's example strategy {data.strategy}, Oct 26–27.<br />
      Paper: each order filled in full at the price it asked, no fees.</Rise>
  </AbsoluteFill>
);

// Sound: the owner's pick of music when it's in public/ (not in git), from `from` seconds at `gain`; a tick as each
// cost starts and as the real number lands. No track: the ticks only.
export type NemiCostsProps = { music: string; from: number; gain: number };
export const NEMI_COSTS_DEFAULTS: NemiCostsProps = { music: "nemi-music.wav", from: 27.34, gain: 0.95 };
const TICKS = [FEE_AT, SLIP_AT, LAND, PUNCH];
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
    <Sequence from={END}><EndCard /></Sequence>
    <div style={{ position: "absolute", left: 90, bottom: 60, opacity: interpolate(useCurrentFrame(), [COSTS + 60, COSTS + 75, PUNCH, PUNCH + 8, END - 10, END], [1, 0, 0, 1, 1, 0], clamp) }}>
      <Wordmark size={44} /></div>
  </AbsoluteFill>
);
