import type { CSSProperties, ReactNode } from "react";
import { AbsoluteFill, Audio, Easing, Sequence, getStaticFiles, interpolate, staticFile, useCurrentFrame,
  useVideoConfig } from "remotion";
import { loadFont } from "@remotion/fonts";
import data from "./one-schema.json";

// "One schema" (Nov 3): Layer began with Kalshi and Polymarket and now adds Hyperliquid and Novig. Each venue's own
// format goes in; one match object comes out, with the same fields whatever the market: a game, Bitcoin, the Fed,
// an election. Every value is from a live Layer match (src/one-schema.json, trimmed for the screen). The crypto
// match's other side is Polymarket's US exchange (polymarket.com has no crypto matches yet); it's shown as
// "polymarket" with its real id and polymarket.us url. Same look as SameGame.
const C = {
  paper: "#f2f0e9", ink: "#141519", rule: "#d3cfc4", muted: "#67655f", accent: "#e6c229",
  termFg: "#ece9e1", termMuted: "#9b988f", termRule: "#2e3036",
};
const SANS = "Host Grotesk", MONO = "IBM Plex Mono";
loadFont({ family: SANS, url: staticFile("HostGrotesk-latin-var.woff2"), weight: "300 800" });
loadFont({ family: MONO, url: staticFile("IBMPlexMono-latin-400.woff2"), weight: "400" });
loadFont({ family: MONO, url: staticFile("IBMPlexMono-latin-500.woff2"), weight: "500" });

// Scene starts, in frames at 30 fps. The sports beat shows its three matches in turn, LEG frames each.
const HOOK = 0, HUB = 100, BEATS = 270, LEG = 60, BEAT = 90;
const BEAT_STARTS = [0, 3 * LEG, 3 * LEG + BEAT, 3 * LEG + 2 * BEAT];
const END = BEATS + 3 * LEG + 3 * BEAT;
export const ONE_SCHEMA_DURATION = END + 80;

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

const Scene = ({ len, children }: { len: number; children: ReactNode }) => {
  const out = interpolate(useCurrentFrame(), [len - 10, len], [1, 0], clamp);
  return <AbsoluteFill style={{ padding: "170px 96px 120px", opacity: out, justifyContent: "center" }}>{children}</AbsoluteFill>;
};

const Hook = () => (
  <Scene len={HUB - HOOK}>
    {/* Already in at frame 0: X shows the first frame before the video plays. */}
    <Label>new venues</Label>
    <H size={112} style={{ marginTop: 32, lineHeight: 1.05 }}>Kalshi and Polymarket, matched.</H>
    <Rise delay={32} style={{ marginTop: 64 }}>
      <H size={112} style={{ lineHeight: 1.1 }}>Now <Mark text="Hyperliquid" delay={44} /><br /><Mark text="and Novig" delay={52} /> too.</H>
    </Rise>
  </Scene>
);

// Layer in the middle, the four venues around it, each in its own format (the same Man City market's id and name on
// each), feeding one schema out below.
const DW = 888, DH = 560, BW = 404, BH = 116, LW = 230, LH = 104;
const corner = (i: number): [number, number] => [i % 2 === 0 ? BW / 2 : DW - BW / 2, i < 2 ? BH / 2 : DH - BH / 2 - 150];

const Hub = () => {
  const f = useCurrentFrame();
  const [cx, cy] = [DW / 2, (DH - 150) / 2];
  const ride = (o: number) => ((((f - 60 + o) % 36) + 36) % 36) / 36;
  const outT = ease(f, 74, 16);
  return (
    <Scene len={BEATS - HUB}>
      <H size={84}>Four formats in.<br /><Mark text="One schema out." delay={84} /></H>
      <div style={{ position: "relative", width: DW, height: DH, marginTop: 48 }}>
        <svg width={DW} height={DH} style={{ position: "absolute", inset: 0, overflow: "visible" }}>
          {data.formats.map((_, i) => {
            const [x, y] = corner(i);
            return <line key={i} x1={x} y1={y} x2={cx} y2={cy} stroke={C.ink} strokeWidth={2} pathLength={1}
              strokeDasharray={1} strokeDashoffset={1 - ease(f, 20 + i * 6, 20)} />;
          })}
          <line x1={cx} y1={cy} x2={cx} y2={DH - 62} stroke={C.ink} strokeWidth={2} pathLength={1} strokeDasharray={1}
            strokeDashoffset={1 - ease(f, 66, 12)} />
          {f >= 60 && data.formats.map((_, i) => {
            const [x, y] = corner(i), t = ride(i * 9);
            return <rect key={i} x={x + (cx - x) * t - 9} y={y + (cy - y) * t - 6} width={18} height={12} fill={C.accent}
              stroke={C.ink} strokeWidth={1.5} />;
          })}
        </svg>
        {data.formats.map((v, i) => {
          const [x, y] = corner(i), t = ease(f, 8 + i * 6, 14);
          return (
            <div key={v.venue} style={{ position: "absolute", left: x - BW / 2, top: y - BH / 2, width: BW, height: BH,
              background: C.paper, border: `2px solid ${C.ink}`, padding: "14px 18px", opacity: t,
              transform: `scale(${0.92 + t * 0.08})` }}>
              <div style={{ fontFamily: SANS, fontSize: 30, fontWeight: 600, letterSpacing: "-0.02em" }}>{v.venue[0].toUpperCase() + v.venue.slice(1)}</div>
              <div style={{ fontFamily: MONO, fontSize: 18, color: C.muted, marginTop: 6, whiteSpace: "nowrap", overflow: "hidden",
                textOverflow: "ellipsis" }}>{v.id}</div>
              <div style={{ fontFamily: MONO, fontSize: 18, color: C.muted, whiteSpace: "nowrap", overflow: "hidden",
                textOverflow: "ellipsis" }}>{v.name}</div>
            </div>
          );
        })}
        <div style={{ position: "absolute", left: cx - LW / 2, top: cy - LH / 2, width: LW, height: LH, background: C.accent,
          border: `2px solid ${C.ink}`, display: "flex", alignItems: "center", justifyContent: "center", gap: 12,
          fontSize: 44, fontWeight: 600, letterSpacing: "-0.03em", opacity: ease(f, 4, 14) }}>
          <Logo size={1.5} />layer
        </div>
        <div style={{ position: "absolute", left: 0, right: 0, bottom: 0, height: 124, background: C.ink, color: C.termFg,
          fontFamily: MONO, fontSize: 24, display: "flex", alignItems: "center", justifyContent: "center", opacity: outT,
          transform: `translateY(${(1 - outT) * 20}px)` }}>
          <span>{"{ "}<K>market_id</K>, <K>url</K>, <K>basis</K>, <K>confidence</K>, <K>caveats</K>{" }"}</span>
        </div>
      </div>
    </Scene>
  );
};

const K = ({ children }: { children: ReactNode }) => <span style={{ color: C.accent }}>{children}</span>;
const S = ({ children }: { children: ReactNode }) => <span style={{ color: C.termFg }}>"{children}"</span>;

type Leg = { venue: string; market_id: string; url: string; basis: string; confidence: number; caveats: string[] };
type Beat = (typeof data.beats)[number];

// One match object: the keys never change (yellow), only the values (white) do.
const MatchJson = ({ beat, leg, swapAt }: { beat: Beat; leg: Leg; swapAt: number }) => {
  const f = useCurrentFrame();
  const v = ease(f, swapAt, 10);
  const Val = ({ children }: { children: ReactNode }) =>
    <span style={{ opacity: 0.25 + v * 0.75, display: "inline-block", transform: `translateY(${(1 - v) * 6}px)` }}>{children}</span>;
  // Values line up in one column per level: after "confidence": at the top, after "market_id": inside a venue.
  const pad = (k: string, w: number) => " ".repeat(Math.max(0, w - k.length) + 1);
  const lines: ReactNode[] = [
    <>{"{"}</>,
    <>  "<K>category</K>":{pad("category", 10)}<Val><S>{beat.category}</S></Val>,</>,
    <>  "<K>kalshi</K>": {"{"}</>,
    <>    "<K>market_id</K>":{pad("market_id", 9)}<Val><S>{beat.kalshi.market_id}</S></Val>,</>,
    <>    "<K>url</K>":{pad("url", 9)}<Val><S>{beat.kalshi.url}</S></Val> {"}"},</>,
    <>  "<K>{leg.venue}</K>": {"{"}</>,
    <>    "<K>market_id</K>":{pad("market_id", 9)}<Val><S>{leg.market_id}</S></Val>,</>,
    <>    "<K>url</K>":{pad("url", 9)}<Val><S>{leg.url}</S></Val> {"}"},</>,
    <>  "<K>basis</K>":{pad("basis", 10)}<Val><S>{leg.basis}</S></Val>,</>,
    <>  "<K>confidence</K>":{pad("confidence", 10)}<Val><span style={{ color: C.termFg }}>{leg.confidence}</span></Val>,</>,
    <>  "<K>caveats</K>":{pad("caveats", 10)}<Val><span style={{ color: C.termFg }}>[{leg.caveats.map((c) => `"${c}"`).join(", ")}]</span></Val></>,
    <>{"}"}</>,
  ];
  return (
    <div style={{ background: C.ink, color: C.termMuted, fontFamily: MONO, fontSize: 22, lineHeight: 1.5 }}>
      <div style={{ display: "flex", gap: 12, padding: "14px 24px", borderBottom: `2px solid ${C.termRule}` }}>
        {[0, 1, 2].map((i) => <div key={i} style={{ width: 14, height: 14, background: C.termRule }} />)}
      </div>
      <pre style={{ margin: 0, padding: "20px 28px 24px", fontFamily: "inherit", whiteSpace: "pre" }}>
        {lines.map((l, i) => <div key={i}>{l}</div>)}
      </pre>
    </div>
  );
};

const CATS = data.beats.map((b) => b.category);

const Beats = () => {
  const f = useCurrentFrame();
  const at = BEAT_STARTS.filter((s) => f >= s).length - 1;
  const beat = data.beats[at];
  const legIndex = at === 0 ? Math.min(2, Math.floor(f / LEG)) : 0;
  const leg = beat.legs[legIndex] as Leg;
  const swapAt = at === 0 ? legIndex * LEG : BEAT_STARTS[at];
  const titleT = ease(f, BEAT_STARTS[at], 12);
  return (
    <Scene len={END - BEATS}>
      <H size={84}>Same fields.<br /><Mark text="Any market." delay={8} /></H>
      <div style={{ display: "flex", gap: 14, marginTop: 36 }}>
        {CATS.map((c, i) => (
          <span key={c} style={{ fontFamily: MONO, fontSize: 24, border: `2px solid ${C.ink}`, padding: "8px 14px",
            background: i === at ? C.accent : i < at ? C.paper : C.paper, color: i <= at ? C.ink : C.muted }}>{c}</span>
        ))}
      </div>
      <div style={{ marginTop: 36, opacity: titleT, transform: `translateX(${(1 - titleT) * -30}px)` }}>
        <div style={{ fontSize: 46, letterSpacing: "-0.02em", lineHeight: 1.1 }}>{beat.title}</div>
        <Label style={{ marginTop: 10, fontSize: 24 }}>{beat.sub}</Label>
      </div>
      <div style={{ marginTop: 28 }}><MatchJson beat={beat} leg={leg} swapAt={swapAt} /></div>
      {at === 0 && (
        <Label style={{ marginTop: 14, fontSize: 22 }}>
          {beat.legs.map((l, i) => (
            <span key={l.venue} style={{ color: i === legIndex ? C.ink : C.muted, marginRight: 18 }}>
              {i === legIndex ? "● " : "○ "}{l.venue}
            </span>
          ))}
        </Label>
      )}
    </Scene>
  );
};

const End = () => (
  <Scene len={ONE_SCHEMA_DURATION - END + 10}>
    <Rise style={{ display: "flex", alignItems: "center", gap: 28 }}>
      <Logo size={4.4} /><span style={{ fontSize: 112, fontWeight: 600, letterSpacing: "-0.04em" }}>layer</span>
    </Rise>
    <Rise delay={8} style={{ marginTop: 64 }}>
      <H size={96} style={{ lineHeight: 1.05 }}>One API for all prediction markets.</H>
    </Rise>
    <Rise delay={16} style={{ marginTop: 40, fontFamily: MONO, fontSize: 30, color: C.muted }}>
      Kalshi · Polymarket · Hyperliquid · Novig
    </Rise>
    <Rise delay={26} style={{ marginTop: 56, alignSelf: "flex-start", background: C.accent, border: `2px solid ${C.ink}`,
      fontSize: 44, padding: "18px 32px" }}>uselayer.sh</Rise>
  </Scene>
);

const Frame = () => (
  <>
    <div style={{ position: "absolute", inset: "0 48px", borderLeft: `2px solid ${C.ink}`, borderRight: `2px solid ${C.ink}` }} />
    <div style={{ position: "absolute", left: 48, right: 48, top: 0, height: 116, borderBottom: `2px solid ${C.ink}`,
      display: "flex", alignItems: "center", padding: "0 48px" }}>
      <div style={{ display: "flex", alignItems: "center", gap: 16, fontSize: 40, fontWeight: 600, letterSpacing: "-0.03em" }}>
        <Logo size={1.6} />layer
      </div>
    </div>
  </>
);

const Footer = () => (
  <div style={{ position: "absolute", left: 96, right: 96, bottom: 40, fontFamily: MONO, fontSize: 20, color: C.muted }}>
    Live Layer matches, {data.readAt}. Ids and urls shortened.
  </div>
);

// Same sound as SameGame: tick and ping over public/layer-music.mp3 ("Cold Concrete", kept out of git) from its drop.
const MUSIC = "layer-music.mp3", MUSIC_FROM = 27.43;
const hasMusic = getStaticFiles().some((f) => f.name === MUSIC);
const TICKS: [number, number][] = [
  ...[0, 1, 2, 3].map((i) => [HUB + 8 + i * 6, 0.4] as [number, number]),
  [HUB + 74, 0.55],
  ...[0, 1, 2].map((i) => [BEATS + i * LEG, 0.45] as [number, number]),
  ...[1, 2, 3].map((i) => [BEATS + BEAT_STARTS[i], 0.5] as [number, number]),
  [END + 26, 0.5],
];
const Sound = ({ music }: { music: boolean }) => {
  const { fps } = useVideoConfig();
  if (!music) return null;
  return (
    <>
      {hasMusic && (
        <Audio src={staticFile(MUSIC)} trimBefore={Math.round(MUSIC_FROM * fps)}
          volume={(f) => interpolate(f, [0, 3, ONE_SCHEMA_DURATION - 30, ONE_SCHEMA_DURATION], [0, 0.55, 0.55, 0], clamp)} />
      )}
      {TICKS.map(([at, vol]) => (
        <Sequence key={at} from={at} durationInFrames={6}><Audio src={staticFile("tick.wav")} volume={vol} /></Sequence>
      ))}
      <Sequence from={END + 8} durationInFrames={30}><Audio src={staticFile("ping.wav")} volume={1} /></Sequence>
    </>
  );
};

export const ONE_SCHEMA_DEFAULTS = { music: true };

export const OneSchema = ({ music }: { music: boolean }) => (
  <AbsoluteFill style={{ background: C.paper, color: C.ink, fontFamily: SANS }}>
    <Sound music={music} />
    <Frame />
    <Sequence from={HOOK} durationInFrames={HUB - HOOK}><Hook /></Sequence>
    <Sequence from={HUB} durationInFrames={BEATS - HUB}><Hub /></Sequence>
    <Sequence from={BEATS} durationInFrames={END - BEATS}><Beats /></Sequence>
    <Sequence from={END}><End /></Sequence>
    <Footer />
  </AbsoluteFill>
);
