import type { CSSProperties, ReactNode } from "react";
import { AbsoluteFill, Audio, Easing, Sequence, getStaticFiles, interpolate, spring, staticFile, useCurrentFrame,
  useVideoConfig } from "remotion";
import { loadFont } from "@remotion/fonts";
import data from "./hyperliquid.json";

// "Same game?": Layer matches Hyperliquid's sports markets to Kalshi's, outcome by outcome, and reads both
// rulebooks. One real pair, every fact from src/hyperliquid.json. For Layer's X account, so it wears Layer's
// site (layer/app/globals.css): paper, ink, one yellow.
const C = {
  paper: "#f2f0e9", ink: "#141519", rule: "#d3cfc4", muted: "#67655f", accent: "#e6c229",
  termFg: "#ece9e1", termMuted: "#9b988f", termRule: "#2e3036",
};
const SANS = "Host Grotesk", MONO = "IBM Plex Mono";
loadFont({ family: SANS, url: staticFile("HostGrotesk-latin-var.woff2"), weight: "300 800" });
loadFont({ family: MONO, url: staticFile("IBMPlexMono-latin-400.woff2"), weight: "400" });
loadFont({ family: MONO, url: staticFile("IBMPlexMono-latin-500.woff2"), weight: "500" });

// Scene starts, in frames at 30 fps.
const HOOK = 0, CARD = 95, NAMES = 225, RULES = 375, CODE = 480, END = 620;
export const SAME_GAME_DURATION = 680;

const clamp = { extrapolateLeft: "clamp", extrapolateRight: "clamp" } as const;
const ease = (f: number, from: number, dur: number) =>
  interpolate(f, [from, from + dur], [0, 1], { ...clamp, easing: Easing.out(Easing.cubic) });
// Kalshi quotes whole cents, Hyperliquid tenths.
const cents = (v: number, dp: number) => `${v.toFixed(dp)}¢`;

// Layer's mark (layer/app/page.tsx Logo).
const Logo = ({ size }: { size: number }) => (
  <svg width={28 * size} height={20 * size} viewBox="0 0 28 20">
    <path d="M1 3H8L14 10M1 10H14M1 17H8L14 10" fill="none" stroke={C.ink} strokeWidth={2} />
    <rect x={14} y={7} width={13} height={6} fill={C.accent} stroke={C.ink} strokeWidth={1} />
  </svg>
);

const Rise = ({ delay = 0, children, style }: { delay?: number; children: ReactNode; style?: CSSProperties }) => {
  const t = ease(useCurrentFrame(), delay, 18);
  return <div style={{ opacity: t, transform: `translateY(${(1 - t) * 36}px)`, ...style }}>{children}</div>;
};

const Label = ({ children, style }: { children: ReactNode; style?: CSSProperties }) =>
  <div style={{ fontFamily: MONO, fontSize: 26, color: C.muted, letterSpacing: 0.5, ...style }}>{children}</div>;

const H = ({ children, size = 104, style }: { children: ReactNode; size?: number; style?: CSSProperties }) =>
  <div style={{ fontSize: size, fontWeight: 300, letterSpacing: "-0.045em", lineHeight: 1, ...style }}>{children}</div>;

// A yellow highlighter pass over `text`, left to right from `delay`.
const Mark = ({ text, delay }: { text: string; delay: number }) => {
  const t = ease(useCurrentFrame(), delay, 16);
  return (
    <span style={{ backgroundImage: `linear-gradient(${C.accent}, ${C.accent})`, backgroundRepeat: "no-repeat",
      backgroundSize: `${t * 100}% 100%`, padding: "0 6px", boxDecorationBreak: "clone" }}>{text}</span>
  );
};

// `text` with `mark` highlighted where it appears.
const Quote = ({ text, mark, delay }: { text: string; mark: string; delay: number }) => {
  const i = text.indexOf(mark);
  if (i < 0) return <>{text}</>;
  return <>{text.slice(0, i)}<Mark text={mark} delay={delay} />{text.slice(i + mark.length)}</>;
};

// Types `text` out from `delay`, `cps` characters a second.
const Typed = ({ text, delay, cps = 40 }: { text: string; delay: number; cps?: number }) => {
  const f = useCurrentFrame(), { fps } = useVideoConfig();
  return <>{text.slice(0, Math.max(0, Math.floor(((f - delay) / fps) * cps)))}</>;
};
const CODE_CPS = 100;

// Each scene fades out over its last 10 frames so cuts feel like one piece.
const Scene = ({ len, children }: { len: number; children: ReactNode }) => {
  const out = interpolate(useCurrentFrame(), [len - 10, len], [1, 0], clamp);
  return <AbsoluteFill style={{ padding: "170px 96px 120px", opacity: out, justifyContent: "center" }}>{children}</AbsoluteFill>;
};

const Hook = () => (
  <Scene len={CARD - HOOK}>
    {/* Already in at frame 0: X shows the first frame before the video plays. */}
    <Label>new venue · sports</Label>
    <H size={124} style={{ marginTop: 36 }}>Hyperliquid has sports markets now.</H>
    <Rise delay={36} style={{ marginTop: 72 }}>
      <H size={124}>Same game as <Mark text="Kalshi?" delay={48} /></H>
    </Rise>
  </Scene>
);

// One row of the card, as on Layer's homepage: a mono venue name, then the market.
const Row = ({ venue, delay, bg, children, last }:
  { venue: string; delay: number; bg?: string; children: ReactNode; last?: boolean }) => {
  const t = ease(useCurrentFrame(), delay, 16);
  return (
    <div style={{ display: "grid", gridTemplateColumns: "240px 1fr", background: bg, opacity: t,
      transform: `translateX(${(1 - t) * -40}px)`, borderBottom: last ? undefined : `2px solid ${C.ink}` }}>
      <div style={{ padding: "32px 28px", fontFamily: MONO, fontSize: 27, color: bg ? C.ink : C.muted }}>{venue}</div>
      <div style={{ padding: "26px 28px 26px 0" }}>{children}</div>
    </div>
  );
};

const Card = () => (
  <Scene len={NAMES - CARD}>
    <Rise><Label>one game, two venues · {data.league} · {data.kickoff.split(",")[0]}</Label></Rise>
    <div style={{ border: `2px solid ${C.ink}`, marginTop: 28 }}>
      <Row venue="kalshi" delay={8}>
        <div style={{ fontSize: 40, lineHeight: 1.2, letterSpacing: "-0.02em" }}>{data.kalshi.title}</div>
      </Row>
      <Row venue="hyperliquid" delay={22}>
        <div style={{ fontSize: 40, lineHeight: 1.2, letterSpacing: "-0.02em" }}>{data.hyperliquid.title}</div>
      </Row>
      <Row venue="layer" delay={46} bg={C.accent}>
        <div style={{ fontFamily: MONO, fontSize: 30, lineHeight: 1.45, paddingTop: 4 }}>
          <Typed text={`same game · ${data.basis} · ${Math.round(data.confidence * 100)}% confidence`} delay={54} />
        </div>
      </Row>
      <Row venue="your bot" delay={100} last>
        <div style={{ fontSize: 34, paddingTop: 2, color: C.muted }}>decides what to do with it</div>
      </Row>
    </div>
  </Scene>
);

// Each Kalshi outcome joined to its Hyperliquid twin by a line Layer draws, prices underneath.
const Pair = ({ o, delay }: { o: (typeof data.outcomes)[number]; delay: number }) => {
  const f = useCurrentFrame();
  const t = ease(f, delay, 16), line = ease(f, delay + 10, 18);
  const side = (name: string, [bid, ask]: number[], dp: number, align: "left" | "right") => (
    <div style={{ textAlign: align }}>
      <div style={{ fontSize: 44, letterSpacing: "-0.02em", whiteSpace: "nowrap" }}>{name}</div>
      <div style={{ fontFamily: MONO, fontSize: 26, color: C.muted, marginTop: 6 }}>{cents(bid, dp)} / {cents(ask, dp)}</div>
    </div>
  );
  return (
    <div style={{ display: "grid", gridTemplateColumns: "1fr 110px 1fr", alignItems: "center", opacity: t,
      padding: "26px 0", borderTop: `2px solid ${C.rule}` }}>
      {side(o.kalshi, o.kalshiBidAsk, 0, "left")}
      <div style={{ position: "relative", height: 14 }}>
        <div style={{ position: "absolute", left: 10, top: 6, height: 2, width: `${line * 90}px`, background: C.ink }} />
        <div style={{ position: "absolute", left: 41, top: 0, width: 28, height: 14, background: C.accent,
          border: `2px solid ${C.ink}`, opacity: line }} />
      </div>
      {side(o.hyperliquid, o.hyperliquidBidAsk, 1, "right")}
    </div>
  );
};

const Names = () => (
  <Scene len={RULES - NAMES}>
    <H size={96}>Different names.</H>
    <div style={{ display: "grid", gridTemplateColumns: "1fr 110px 1fr", marginTop: 56, marginBottom: 14 }}>
      <Label>kalshi</Label><Label style={{ textAlign: "center" }}>bid/ask</Label><Label style={{ textAlign: "right" }}>hyperliquid</Label>
    </div>
    {data.outcomes.map((o, i) => <Pair key={o.kalshi} o={o} delay={14 + i * 14} />)}
    <Rise delay={84} style={{ marginTop: 48 }}><H size={88}>Same outcomes. Prices <Mark text="about a cent apart." delay={96} /></H></Rise>
  </Scene>
);

const Rule = ({ venue, m, delay }: { venue: string; m: { rule: string; mark: string }; delay: number }) => (
  <Rise delay={delay} style={{ borderTop: `2px solid ${C.ink}`, paddingTop: 24, marginTop: 44 }}>
    <Label>{venue} rules</Label>
    <div style={{ fontSize: 46, lineHeight: 1.3, marginTop: 14, letterSpacing: "-0.02em" }}>
      “<Quote text={m.rule} mark={m.mark} delay={delay + 20} />”
    </div>
  </Rise>
);

const Rules = () => {
  const f = useCurrentFrame(), { fps } = useVideoConfig();
  const stamp = spring({ frame: f - 70, fps, config: { damping: 12, mass: 0.7 } });
  return (
    <Scene len={CODE - RULES}>
      <H size={96}>Same rules.</H>
      <Rule venue="kalshi" m={data.kalshi} delay={10} />
      <Rule venue="hyperliquid" m={data.hyperliquid} delay={24} />
      <div style={{ marginTop: 56, alignSelf: "flex-start", fontFamily: MONO, fontSize: 34, fontWeight: 500,
        background: C.ink, color: C.accent, padding: "18px 28px", opacity: Math.min(1, stamp * 1.5),
        transform: `scale(${1.25 - stamp * 0.25}) rotate(${(1 - stamp) * -4}deg)`, transformOrigin: "left center" }}>
        basis: "{data.basis}" · caveats: []
      </div>
    </Scene>
  );
};

const Code = () => {
  const f = useCurrentFrame(), { fps } = useVideoConfig();
  const codeText = data.code.join("\n");
  const typedEnd = 8 + (codeText.length / CODE_CPS) * fps;
  return (
    <Scene len={END - CODE}>
      <H size={88}>One call.</H>
      <div style={{ marginTop: 40, background: C.ink, color: C.termFg, fontFamily: MONO, fontSize: 25, lineHeight: 1.45 }}>
        <div style={{ display: "flex", gap: 12, padding: "16px 24px", borderBottom: `2px solid ${C.termRule}` }}>
          {[0, 1, 2].map((i) => <div key={i} style={{ width: 16, height: 16, background: C.termRule }} />)}
        </div>
        <pre style={{ margin: 0, padding: "24px 30px", whiteSpace: "pre", fontFamily: "inherit", minHeight: 160 }}>
          <Typed text={codeText} delay={8} cps={CODE_CPS} />
        </pre>
        <pre style={{ margin: 0, padding: "22px 30px 28px", borderTop: `2px solid ${C.termRule}`, whiteSpace: "pre",
          fontFamily: "inherit", color: C.termMuted }}>
          {data.response.map((line, i) => {
            const hit = data.highlight.some((h) => line.includes(h));
            return <div key={i} style={{ opacity: ease(f, typedEnd + 4 + i * 2, 8), color: hit ? C.accent : undefined }}>{line}</div>;
          })}
        </pre>
      </div>
    </Scene>
  );
};

const End = () => (
  <Scene len={SAME_GAME_DURATION - END + 10}>
    <Rise style={{ display: "flex", alignItems: "center", gap: 28 }}>
      <Logo size={4.4} /><span style={{ fontSize: 112, fontWeight: 600, letterSpacing: "-0.04em" }}>layer</span>
    </Rise>
    <Rise delay={8} style={{ marginTop: 64 }}>
      <H size={84} style={{ lineHeight: 1.05 }}>Hyperliquid sports, matched to Kalshi.</H>
    </Rise>
    <Rise delay={18} style={{ marginTop: 48, display: "flex", flexWrap: "wrap", gap: 14 }}>
      {data.leagues.map((l) => (
        <span key={l} style={{ fontFamily: MONO, fontSize: 24, border: `2px solid ${C.ink}`, padding: "8px 14px" }}>{l}</span>
      ))}
    </Rise>
    <Rise delay={28} style={{ marginTop: 64, alignSelf: "flex-start", background: C.accent, border: `2px solid ${C.ink}`,
      fontSize: 44, padding: "18px 32px" }}>uselayer.sh</Rise>
  </Scene>
);

// The site's frame: ink rules down both sides and a header bar, on every scene.
const Frame = () => (
  <>
    <div style={{ position: "absolute", inset: "0 48px", borderLeft: `2px solid ${C.ink}`, borderRight: `2px solid ${C.ink}` }} />
    <div style={{ position: "absolute", left: 48, right: 48, top: 0, height: 116, borderBottom: `2px solid ${C.ink}`,
      display: "flex", alignItems: "center", justifyContent: "space-between", padding: "0 48px" }}>
      <div style={{ display: "flex", alignItems: "center", gap: 16, fontSize: 40, fontWeight: 600, letterSpacing: "-0.03em" }}>
        <Logo size={1.6} />layer
      </div>
      <span style={{ fontFamily: MONO, fontSize: 22, border: `2px solid ${C.ink}`, padding: "6px 12px" }}>+ HYPERLIQUID</span>
    </div>
  </>
);

// While hyperliquid.json is a sample, a red band says so on every frame, so a render of it can't pass as real.
const Footer = () => (
  <div style={{ position: "absolute", left: 96, right: 96, bottom: 40, fontFamily: MONO, fontSize: 20, color: C.muted }}>
    {data.sample
      ? <span style={{ background: "#c8381f", color: "#fff", padding: "8px 14px", fontSize: 26 }}>SAMPLE · NOT REAL DATA</span>
      : `Prices from each venue's public order book, ${data.asOf}. Sports games only.`}
  </div>
);

// Sound: the same tick and ping as TraderStory, and public/music.mp3 under it when there is one.
const MUSIC_FROM = 15.95;
const hasMusic = getStaticFiles().some((f) => f.name === "music.mp3");
const TICKS: [number, number][] = [
  [CARD + 8, 0.55], [CARD + 22, 0.55], [CARD + 46, 0.55], [CARD + 100, 0.4],  // each card row
  [NAMES + 24, 0.5], [NAMES + 38, 0.5], [NAMES + 52, 0.5],  // each outcome joined
  [RULES + 10, 0.5], [RULES + 24, 0.5],  // each rule
  [END + 28, 0.5],
];
const Sound = () => {
  const { fps } = useVideoConfig();
  return (
    <>
      {hasMusic && (
        <Audio src={staticFile("music.mp3")} trimBefore={Math.round(MUSIC_FROM * fps)}
          volume={(f) => interpolate(f, [0, 3, SAME_GAME_DURATION - 30, SAME_GAME_DURATION], [0, 0.4, 0.4, 0], clamp)} />
      )}
      {TICKS.map(([at, vol]) => (
        <Sequence key={at} from={at} durationInFrames={6}><Audio src={staticFile("tick.wav")} volume={vol} /></Sequence>
      ))}
      <Sequence from={RULES + 70} durationInFrames={30}><Audio src={staticFile("ping.wav")} volume={1} /></Sequence>
    </>
  );
};

export const SameGame = () => (
  <AbsoluteFill style={{ background: C.paper, color: C.ink, fontFamily: SANS }}>
    <Sound />
    <Frame />
    <Sequence from={HOOK} durationInFrames={CARD - HOOK}><Hook /></Sequence>
    <Sequence from={CARD} durationInFrames={NAMES - CARD}><Card /></Sequence>
    <Sequence from={NAMES} durationInFrames={RULES - NAMES}><Names /></Sequence>
    <Sequence from={RULES} durationInFrames={CODE - RULES}><Rules /></Sequence>
    <Sequence from={CODE} durationInFrames={END - CODE}><Code /></Sequence>
    <Sequence from={END}><End /></Sequence>
    <Footer />
  </AbsoluteFill>
);
