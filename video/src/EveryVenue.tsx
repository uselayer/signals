import type { CSSProperties, ReactNode } from "react";
import { AbsoluteFill, Audio, Easing, Sequence, getStaticFiles, interpolate, spring, staticFile, useCurrentFrame,
  useVideoConfig } from "remotion";
import { loadFont } from "@remotion/fonts";
import data from "./every-venue.json";

// "One game, every venue": Novig joins Layer (11-03). One real market, Manchester City to beat RB Leipzig
// (Champions League, Nov 4), listed under five names on five venues, each paired with Kalshi's, then one call.
// Every fact is in src/every-venue.json, read from the venues' public APIs and Layer's live API. Same look as
// SameGame (Layer's site: paper, ink, one yellow); SameGame itself is unchanged.
const C = {
  paper: "#f2f0e9", ink: "#141519", rule: "#d3cfc4", muted: "#67655f", accent: "#e6c229",
  termFg: "#ece9e1", termMuted: "#9b988f", termRule: "#2e3036",
};
const SANS = "Host Grotesk", MONO = "IBM Plex Mono";
loadFont({ family: SANS, url: staticFile("HostGrotesk-latin-var.woff2"), weight: "300 800" });
loadFont({ family: MONO, url: staticFile("IBMPlexMono-latin-400.woff2"), weight: "400" });
loadFont({ family: MONO, url: staticFile("IBMPlexMono-latin-500.woff2"), weight: "500" });

// Scene starts, in frames at 30 fps.
const HOOK = 0, HUB = 90, NAMES = 240, MATCH = 450, CODE = 570, END = 680;
export const EVERY_VENUE_DURATION = 750;

const clamp = { extrapolateLeft: "clamp", extrapolateRight: "clamp" } as const;
const ease = (f: number, from: number, dur: number) =>
  interpolate(f, [from, from + dur], [0, 1], { ...clamp, easing: Easing.out(Easing.cubic) });

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

const Mark = ({ text, delay }: { text: string; delay: number }) => {
  const t = ease(useCurrentFrame(), delay, 16);
  return (
    <span style={{ backgroundImage: `linear-gradient(${C.accent}, ${C.accent})`, backgroundRepeat: "no-repeat",
      backgroundSize: `${t * 100}% 100%`, padding: "0 6px", boxDecorationBreak: "clone" }}>{text}</span>
  );
};

const Typed = ({ text, delay, cps = 40 }: { text: string; delay: number; cps?: number }) => {
  const f = useCurrentFrame(), { fps } = useVideoConfig();
  return <>{text.slice(0, Math.max(0, Math.floor(((f - delay) / fps) * cps)))}</>;
};
const CODE_CPS = 110;

const Scene = ({ len, children }: { len: number; children: ReactNode }) => {
  const out = interpolate(useCurrentFrame(), [len - 10, len], [1, 0], clamp);
  return <AbsoluteFill style={{ padding: "170px 96px 120px", opacity: out, justifyContent: "center" }}>{children}</AbsoluteFill>;
};

type Venue = "kalshi" | "polymarket" | "polymarket_us" | "hyperliquid" | "novig";
const NAME: Record<Venue, string> = { kalshi: "kalshi", polymarket: "polymarket", polymarket_us: "polymarket us",
  hyperliquid: "hyperliquid", novig: "novig" };

const Hook = () => (
  <Scene len={HUB - HOOK}>
    {/* Already in at frame 0: X shows the first frame before the video plays. */}
    <Label>new venue · novig</Label>
    <H size={124} style={{ marginTop: 36 }}>Layer now matches Novig.</H>
    <Rise delay={30} style={{ marginTop: 72 }}>
      <H size={112} style={{ lineHeight: 1.1 }}>Five venues.<br /><Mark text="One API." delay={42} /></H>
    </Rise>
  </Scene>
);

// Hub and spoke: Layer pairs every venue with Kalshi, never two of the others with each other (layer/app/v0/matches),
// so the lines run to Kalshi only and a square rides each one in.
const SPOKES: Venue[] = ["polymarket", "polymarket_us", "hyperliquid", "novig"];
const DW = 888, DH = 600, NW = 260, NH = 80, KW = 280, KH = 150;
const spokeXY = (i: number): [number, number] => [i % 2 === 0 ? NW / 2 : DW - NW / 2, i < 2 ? NH / 2 + 10 : DH - NH / 2 - 10];

const Box = ({ x, y, w, h, label, delay, fill }:
  { x: number; y: number; w: number; h: number; label: ReactNode; delay: number; fill?: string }) => {
  const t = ease(useCurrentFrame(), delay, 14);
  return (
    <div style={{ position: "absolute", left: x - w / 2, top: y - h / 2, width: w, height: h, background: fill ?? C.paper,
      border: `2px solid ${C.ink}`, display: "flex", alignItems: "center", justifyContent: "center", textAlign: "center",
      fontFamily: MONO, fontSize: 26, opacity: t, transform: `scale(${0.9 + t * 0.1})` }}>{label}</div>
  );
};

const Hub = () => {
  const f = useCurrentFrame();
  const [cx, cy] = [DW / 2, DH / 2];
  const ride = (o: number) => ((((f - 64 + o) % 36) + 36) % 36) / 36;
  return (
    <Scene len={NAMES - HUB}>
      <H size={88}>Every venue,<br />matched to Kalshi.</H>
      <Rise delay={6} style={{ fontSize: 34, color: C.muted, marginTop: 28, lineHeight: 1.35 }}>
        Layer pairs each venue's markets with Kalshi's, so any two of them meet through it.
      </Rise>
      <div style={{ position: "relative", width: DW, height: DH, marginTop: 48 }}>
        <svg width={DW} height={DH} style={{ position: "absolute", inset: 0, overflow: "visible" }}>
          {SPOKES.map((_, i) => {
            const [x, y] = spokeXY(i);
            return <line key={i} x1={x} y1={y} x2={cx} y2={cy} stroke={C.ink} strokeWidth={2} pathLength={1}
              strokeDasharray={1} strokeDashoffset={1 - ease(f, 24 + i * 6, 20)} />;
          })}
          {f >= 64 && SPOKES.map((_, i) => {
            const [x, y] = spokeXY(i), t = ride(i * 9);
            return <rect key={i} x={x + (cx - x) * t - 9} y={y + (cy - y) * t - 6} width={18} height={12} fill={C.accent}
              stroke={C.ink} strokeWidth={1.5} />;
          })}
        </svg>
        {SPOKES.map((v, i) => {
          const [x, y] = spokeXY(i);
          return <Box key={v} x={x} y={y} w={NW} h={NH} delay={14 + i * 6} label={NAME[v]}
            fill={v === "novig" ? C.paper : undefined} />;
        })}
        <Box x={cx} y={cy} w={KW} h={KH} delay={8} fill={C.accent} label={
          <div>
            <div style={{ fontFamily: SANS, fontSize: 44, fontWeight: 600, letterSpacing: "-0.03em" }}>kalshi</div>
            <div style={{ fontSize: 22, marginTop: 8 }}>the hub</div>
          </div>
        } />
        {/* "new" tag on Novig, the venue this video is for. */}
        <div style={{ position: "absolute", left: DW - NW + 8, top: DH - NH - 10 - 30, fontFamily: MONO, fontSize: 20,
          background: C.ink, color: C.accent, padding: "2px 10px", opacity: ease(f, 44, 10) }}>new</div>
      </div>
    </Scene>
  );
};

// One market, five names, with each venue's bid / ask for it.
const cents = (v: number, dp: number) => `${v.toFixed(dp)}¢`;
const prices = data.prices as Record<Venue, [number, number]>;

const Names = () => {
  const f = useCurrentFrame();
  return (
    <Scene len={MATCH - NAMES}>
      <Label>{data.league} · {data.game} · {data.kickoff}</Label>
      <H size={78} style={{ marginTop: 18 }}>One outcome. Five names.</H>
      <div style={{ position: "relative", marginTop: 30 }}>
        {data.rows.map((r, i) => {
          const v = r.venue as Venue, t = ease(f, 10 + i * 12, 16);
          const [bid, ask] = prices[v];
          return (
            <div key={v} style={{ display: "grid", gridTemplateColumns: "200px 1fr 230px", alignItems: "center", gap: 16,
              borderTop: `2px solid ${C.ink}`, padding: "12px 0", opacity: t, transform: `translateX(${(1 - t) * -40}px)` }}>
              <Label style={{ fontSize: 24 }}>{NAME[v]}</Label>
              <div>
                <div style={{ fontSize: 19, color: C.muted, lineHeight: 1.25 }}>{r.event}</div>
                <div style={{ fontSize: 29, lineHeight: 1.15, letterSpacing: "-0.02em", marginTop: 4,
                  fontFamily: v === "novig" ? MONO : SANS, ...(v === "novig" ? { fontSize: 23 } : {}) }}>{r.outcome}</div>
              </div>
              <div style={{ fontFamily: MONO, fontSize: 23, textAlign: "center", position: "relative" }}>
                {/* The prices get a highlighter pass, top to bottom, once all five rows are in. */}
                <span style={{ backgroundImage: `linear-gradient(${C.accent}, ${C.accent})`, backgroundRepeat: "no-repeat",
                  backgroundSize: `${ease(f, 92 + i * 5, 12) * 100}% 100%`, padding: "4px 8px" }}>{cents(bid, r.dp)} / {cents(ask, r.dp)}</span>
              </div>
            </div>
          );
        })}
        <div style={{ borderTop: `2px solid ${C.ink}` }} />
      </div>
      <Label style={{ marginTop: 10, textAlign: "right", fontSize: 22 }}>bid / ask · Man City to win</Label>
      <Rise delay={120} style={{ marginTop: 22 }}><H size={60}>Same outcome. <Mark text="Asks within a cent." delay={132} /></H></Rise>
    </Scene>
  );
};

// What Layer says about each pair: three identical, Novig's matched with a caveat, said as it is.
const Match = () => {
  const f = useCurrentFrame(), { fps } = useVideoConfig();
  const stamp = spring({ frame: f - 78, fps, config: { damping: 12, mass: 0.7 } });
  return (
    <Scene len={CODE - MATCH}>
      <H size={96}>One Layer match.</H>
      <div style={{ border: `2px solid ${C.ink}`, marginTop: 44 }}>
        <div style={{ display: "grid", gridTemplateColumns: "330px 1fr", background: C.accent, borderBottom: `2px solid ${C.ink}`,
          opacity: ease(f, 6, 14) }}>
          <div style={{ padding: "26px 28px", fontFamily: MONO, fontSize: 27 }}>kalshi</div>
          <div style={{ padding: "22px 28px 22px 0", fontSize: 36, letterSpacing: "-0.02em" }}>Manchester City wins</div>
        </div>
        {data.pairs.map((p, i) => {
          const t = ease(f, 16 + i * 10, 14);
          return (
            <div key={p.venue} style={{ display: "grid", gridTemplateColumns: "330px 1fr", opacity: t,
              transform: `translateX(${(1 - t) * -40}px)`, borderBottom: i === data.pairs.length - 1 ? undefined : `2px solid ${C.ink}` }}>
              <div style={{ padding: "24px 28px", fontFamily: MONO, fontSize: 26, color: C.muted }}>↳ {NAME[p.venue as Venue]}</div>
              <div style={{ padding: "24px 28px 24px 0", fontFamily: MONO, fontSize: 26 }}>
                {p.basis} · {p.confidence.toFixed(2)}
              </div>
            </div>
          );
        })}
      </div>
      <div style={{ marginTop: 48, alignSelf: "flex-start", fontFamily: MONO, fontSize: 32, fontWeight: 500,
        background: C.ink, color: C.accent, padding: "18px 28px", opacity: Math.min(1, stamp * 1.5),
        transform: `scale(${1.25 - stamp * 0.25}) rotate(${(1 - stamp) * -4}deg)`, transformOrigin: "left center" }}>
        5 venues · 1 market · checked
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
      <div style={{ marginTop: 40, background: C.ink, color: C.termFg, fontFamily: MONO, fontSize: 22, lineHeight: 1.45 }}>
        <div style={{ display: "flex", gap: 12, padding: "16px 24px", borderBottom: `2px solid ${C.termRule}` }}>
          {[0, 1, 2].map((i) => <div key={i} style={{ width: 16, height: 16, background: C.termRule }} />)}
        </div>
        <pre style={{ margin: 0, padding: "24px 30px", whiteSpace: "pre", fontFamily: "inherit", minHeight: 110 }}>
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
      <Label style={{ marginTop: 16 }}>response trimmed · venue=polymarket, polymarket_us or hyperliquid work the same way</Label>
    </Scene>
  );
};

const End = () => (
  <Scene len={EVERY_VENUE_DURATION - END + 10}>
    <Rise style={{ display: "flex", alignItems: "center", gap: 28 }}>
      <Logo size={4.4} /><span style={{ fontSize: 112, fontWeight: 600, letterSpacing: "-0.04em" }}>layer</span>
    </Rise>
    <Rise delay={8} style={{ marginTop: 64 }}>
      <H size={92} style={{ lineHeight: 1.05 }}>One API for prediction markets.</H>
    </Rise>
    <Rise delay={14} style={{ marginTop: 32, fontSize: 38, color: C.muted, lineHeight: 1.3 }}>
      Kalshi, Polymarket, Polymarket US, Hyperliquid and Novig.
    </Rise>
    <Rise delay={20} style={{ marginTop: 40, display: "flex", flexWrap: "wrap", gap: 14 }}>
      {data.categories.map((c) => (
        <span key={c} style={{ fontFamily: MONO, fontSize: 24, border: `2px solid ${C.ink}`, padding: "8px 14px" }}>{c}</span>
      ))}
    </Rise>
    <Rise delay={28} style={{ marginTop: 56, alignSelf: "flex-start", background: C.accent, border: `2px solid ${C.ink}`,
      fontSize: 44, padding: "18px 32px" }}>uselayer.sh</Rise>
  </Scene>
);

const Frame = () => (
  <>
    <div style={{ position: "absolute", inset: "0 48px", borderLeft: `2px solid ${C.ink}`, borderRight: `2px solid ${C.ink}` }} />
    <div style={{ position: "absolute", left: 48, right: 48, top: 0, height: 116, borderBottom: `2px solid ${C.ink}`,
      display: "flex", alignItems: "center", justifyContent: "space-between", padding: "0 48px" }}>
      <div style={{ display: "flex", alignItems: "center", gap: 16, fontSize: 40, fontWeight: 600, letterSpacing: "-0.03em" }}>
        <Logo size={1.6} />layer
      </div>
      <span style={{ fontFamily: MONO, fontSize: 22, border: `2px solid ${C.ink}`, padding: "6px 12px" }}>+ NOVIG</span>
    </div>
  </>
);

const Footer = () => (
  <div style={{ position: "absolute", left: 96, right: 96, bottom: 40, fontFamily: MONO, fontSize: 20, color: C.muted }}>
    Prices from each venue's public order book, {data.asOf}.
  </div>
);

// Same sound as SameGame: tick and ping, over public/layer-music.mp3 ("Cold Concrete", ElevenLabs Music, kept out of
// git) from its drop. `music: false` renders it silent.
const MUSIC = "layer-music.mp3", MUSIC_FROM = 27.43;
const hasMusic = getStaticFiles().some((f) => f.name === MUSIC);
const TICKS: [number, number][] = [
  [HUB + 8, 0.55], ...SPOKES.map((_, i) => [HUB + 14 + i * 6, 0.4] as [number, number]),
  ...[0, 1, 2, 3, 4].map((i) => [NAMES + 10 + i * 12, 0.45] as [number, number]),
  [MATCH + 6, 0.55], ...[0, 1, 2, 3].map((i) => [MATCH + 16 + i * 10, 0.4] as [number, number]),
  [END + 28, 0.5],
];
const Sound = ({ music }: { music: boolean }) => {
  const { fps } = useVideoConfig();
  return (
    <>
      {music && hasMusic && (
        <Audio src={staticFile(MUSIC)} trimBefore={Math.round(MUSIC_FROM * fps)}
          volume={(f) => interpolate(f, [0, 3, EVERY_VENUE_DURATION - 30, EVERY_VENUE_DURATION], [0, 0.55, 0.55, 0], clamp)} />
      )}
      {music && TICKS.map(([at, vol]) => (
        <Sequence key={at} from={at} durationInFrames={6}><Audio src={staticFile("tick.wav")} volume={vol} /></Sequence>
      ))}
      {music && <Sequence from={MATCH + 78} durationInFrames={30}><Audio src={staticFile("ping.wav")} volume={1} /></Sequence>}
    </>
  );
};

export const EVERY_VENUE_DEFAULTS = { music: true };

export const EveryVenue = ({ music }: { music: boolean }) => (
  <AbsoluteFill style={{ background: C.paper, color: C.ink, fontFamily: SANS }}>
    <Sound music={music} />
    <Frame />
    <Sequence from={HOOK} durationInFrames={HUB - HOOK}><Hook /></Sequence>
    <Sequence from={HUB} durationInFrames={NAMES - HUB}><Hub /></Sequence>
    <Sequence from={NAMES} durationInFrames={MATCH - NAMES}><Names /></Sequence>
    <Sequence from={MATCH} durationInFrames={CODE - MATCH}><Match /></Sequence>
    <Sequence from={CODE} durationInFrames={END - CODE}><Code /></Sequence>
    <Sequence from={END}><End /></Sequence>
    <Footer />
  </AbsoluteFill>
);
