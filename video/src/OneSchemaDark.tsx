import type { CSSProperties, ReactNode } from "react";
import { AbsoluteFill, Audio, Easing, Sequence, getStaticFiles, interpolate, staticFile, useCurrentFrame } from "remotion";
import { loadFont } from "@remotion/fonts";

// "One schema", dark cut (11-03): the OneSchema story and its live Layer matches, kept simple and cut to the beat.
//   1. Kalshi + Polymarket, now Hyperliquid + Novig.
//   2. The same market's id on all four venues collapses into one Layer object (yellow).
//   3. The object stays put; only its values change, game → Bitcoin → the Fed → an election.
//   4. One API for all prediction markets (yellow).
// The object is GET /v0/match's shape, trimmed. The crypto match's other side is Polymarket's US exchange
// (polymarket.com has no crypto matches yet), shown as "polymarket" with its real id.
//
// Music: Wavy Bounce (2), 95.2 BPM, from 13.385 s so its first 808 lands on frame 0. HITS are the track's 808s
// (sub-90 Hz onsets), in seconds from the start of the video; every cut and every value change sits on one.
const HITS = [0, 0.65, 1.28, 3.36, 4.0, 4.63, 6.72, 7.36, 7.98, 9.45, 10.08, 10.71, 11.34, 13.42, 14.07, 14.7, 16.78,
  17.43, 18.05, 18.89, 19.52, 20.15, 20.78, 21.41, 22.85, 24.14, 24.76, 25.38, 26.23, 27.49, 28.11];
const FPS = 30;
const H = (i: number) => Math.round(HITS[i] * FPS);
export const ONE_SCHEMA_DARK_DURATION = Math.round(29.6 * FPS);

const C = { bg: "#0d0e10", fg: "#f1efe8", muted: "#8b8a84", dim: "#4d4d49", accent: "#e6c229", ink: "#0d0e10" };
const SANS = "Host Grotesk", MONO = "IBM Plex Mono";
loadFont({ family: SANS, url: staticFile("HostGrotesk-latin-var.woff2"), weight: "300 800" });
loadFont({ family: MONO, url: staticFile("IBMPlexMono-latin-400.woff2"), weight: "400" });
loadFont({ family: MONO, url: staticFile("IBMPlexMono-latin-500.woff2"), weight: "500" });

const clamp = { extrapolateLeft: "clamp", extrapolateRight: "clamp" } as const;
const expo = Easing.out(Easing.exp);

// Slams in on frame `at`: fully there on the hit, a 4-frame drop into place, then it holds. No fades.
const Slam = ({ at, from = 26, children, style }: { at: number; from?: number; children: ReactNode; style?: CSSProperties }) => {
  const f = useCurrentFrame();
  if (f < at) return null;
  const t = interpolate(f, [at, at + 4], [0, 1], { ...clamp, easing: expo });
  return <div style={{ transform: `translateY(${(1 - t) * from}px)`, ...style }}>{children}</div>;
};

const Abs = ({ x, y, style, children }: { x: number; y: number; style?: CSSProperties; children: ReactNode }) =>
  <div style={{ position: "absolute", left: x, top: y, whiteSpace: "pre", ...style }}>{children}</div>;

const Mark = ({ size, ink }: { size: number; ink?: boolean }) => (
  <svg width={28 * size} height={20 * size} viewBox="0 0 28 20">
    <path d="M1 3H8L14 10M1 10H14M1 17H8L14 10" fill="none" stroke={ink ? C.ink : C.fg} strokeWidth={2.2} />
    <rect x={14} y={7} width={13} height={6} fill={ink ? C.ink : C.accent} />
  </svg>
);
const Brand = ({ ink }: { ink?: boolean }) => (
  <Abs x={96} y={84} style={{ display: "flex", alignItems: "center", gap: 14, fontSize: 36, fontWeight: 700,
    letterSpacing: "-0.04em", color: ink ? C.ink : C.fg }}>
    <Mark size={1.35} ink={ink} />layer
  </Abs>
);

const BIG: CSSProperties = { fontSize: 132, fontWeight: 760, letterSpacing: "-0.04em", lineHeight: 1 };

// ── 1 ───────────────────────────────────────────────────────────────────────────────────────────────────────────
const Intro = () => (
  <AbsoluteFill>
    <Brand />
    <div style={{ position: "absolute", left: 96, top: 360 }}>
      <Slam at={0} style={BIG}>Kalshi +</Slam>
      <Slam at={H(1)} style={BIG}>Polymarket.</Slam>
      <Slam at={H(3)} style={{ ...BIG, color: C.muted, marginTop: 70 }}>Now</Slam>
      <Slam at={H(4)} style={BIG}>Hyperliquid +</Slam>
      <Slam at={H(5)} style={BIG}>Novig.</Slam>
    </div>
  </AbsoluteFill>
);

// ── 2 ───────────────────────────────────────────────────────────────────────────────────────────────────────────
const FORMATS: [string, string][] = [
  ["Kalshi", "KXUCLGAME-26NOV04RBLMCI-MCI"],
  ["Polymarket", "0xa4c2fac1…6093bc49"],
  ["Hyperliquid", "#222460"],
  ["Novig", "01a178fd-7e0e-…-a4c6d8a9d663"],
];
const Formats = ({ s }: { s: number }) => {
  const f = useCurrentFrame();
  const collapse = H(11) - s;
  // From the collapse hit, all four rows accelerate onto one line and meet on the next 808, the cut to yellow.
  const c = interpolate(f, [collapse, H(12) - s], [0, 1], { ...clamp, easing: Easing.in(Easing.cubic) });
  return (
    <AbsoluteFill>
      <Brand />
      {FORMATS.map(([venue, id], i) => {
        const y = interpolate(c, [0, 1], [330 + i * 200, 330 + 1.5 * 200]);
        return (
          <div key={venue} style={{ position: "absolute", left: 96, top: y }}>
            <Slam at={H(6 + i) - s} from={0} style={{ fontSize: 34, fontWeight: 600, color: C.muted, opacity: 1 - c }}>{venue}</Slam>
            <Slam at={H(6 + i) - s} style={{ fontFamily: MONO, fontWeight: 500, fontSize: 46, marginTop: 8 }}>{id}</Slam>
          </div>
        );
      })}
    </AbsoluteFill>
  );
};

const Yellow = ({ children }: { children: ReactNode }) => (
  <AbsoluteFill style={{ background: C.accent, color: C.ink }}>
    <Brand ink />
    {children}
  </AbsoluteFill>
);

// ── 3 ───────────────────────────────────────────────────────────────────────────────────────────────────────────
type Step = { at: number; head: string; sub: string; src: [string, string]; venue: string; id: string; basis: string; conf: string };
const MC: [string, string] = ["KXUCLGAME-26NOV04RBLMCI-MCI", "Manchester City"];
const STEPS = (s: number): Step[] => [
  { at: 0, head: "Sports", sub: "Man City to beat RB Leipzig", src: MC, venue: "polymarket", id: "0xa4c2…bc49", basis: "identical", conf: "0.95" },
  { at: H(14) - s, head: "Sports", sub: "Man City to beat RB Leipzig", src: MC, venue: "hyperliquid", id: "#222460", basis: "identical", conf: "0.95" },
  { at: H(15) - s, head: "Sports", sub: "Man City to beat RB Leipzig", src: MC, venue: "novig", id: "01a178fd-…:01a178fd-…d663", basis: "equivalent_with_caveats", conf: "0.92" },
  { at: H(16) - s, head: "Crypto", sub: "Bitcoin at $70,000 or above, Nov 6", src: ["KXBTCD-26NOV0617-T69999.99", "$70,000 or above"], venue: "polymarket", id: "cpc-btc-above-wk-2026-11-06-70000", basis: "equivalent_with_caveats", conf: "1" },
  { at: H(20) - s, head: "Economics", sub: "Fed cuts 25 bps in December", src: ["KXFEDDECISION-26DEC-C25", "Cut 25bps"], venue: "polymarket", id: "0xf17a…d0b8", basis: "equivalent_with_caveats", conf: "0.85" },
  { at: H(24) - s, head: "Politics", sub: "Iowa Senate race: Ashley Hinson", src: ["KXIASENATE-26-AHIN", "Ashley Hinson"], venue: "polymarket", id: "0x38a1…01a2", basis: "equivalent_with_caveats", conf: "0.9" },
];

// A value: when it changes, the new one drops in over three frames on the hit; the old one is simply gone.
const Val = ({ steps, pick, quoted = true }: { steps: Step[]; pick: (s: Step) => string; quoted?: boolean }) => {
  const f = useCurrentFrame();
  let i = 0;
  for (let k = 0; k < steps.length; k++) if (f >= steps[k].at) i = k;
  let since = steps[i].at;
  for (let k = i; k > 0 && pick(steps[k - 1]) === pick(steps[i]); k--) since = steps[k - 1].at;
  const t = since === 0 ? 1 : interpolate(f, [since, since + 3], [0, 1], { ...clamp, easing: expo });
  return (
    <span style={{ display: "inline-block", transform: `translateY(${(1 - t) * 18}px)` }}>
      {quoted && <span style={{ color: C.dim }}>"</span>}{pick(steps[i])}{quoted && <span style={{ color: C.dim }}>"</span>}
    </span>
  );
};
const K = ({ k }: { k: string }) => <><span style={{ color: C.dim }}>"</span><span style={{ color: C.muted }}>{k}</span><span style={{ color: C.dim }}>":</span></>;
const P = ({ children }: { children: ReactNode }) => <span style={{ color: C.dim }}>{children}</span>;

const MatchObject = ({ s }: { s: number }) => {
  const steps = STEPS(s);
  const lines: ReactNode[] = [
    <P>{"{"}</P>,
    <>  <K k="source_market" /> <P>{"{"}</P></>,
    <>    <K k="venue" />     <span><span style={{ color: C.dim }}>"</span>kalshi<span style={{ color: C.dim }}>"</span></span><P>,</P></>,
    <>    <K k="market_id" /> <Val steps={steps} pick={(x) => x.src[0]} /><P>,</P></>,
    <>    <K k="outcome" />   <Val steps={steps} pick={(x) => x.src[1]} /></>,
    <>  <P>{"},"}</P></>,
    <>  <K k="matched_market" /> <P>{"{"}</P></>,
    <>    <K k="venue" />     <Val steps={steps} pick={(x) => x.venue} /><P>,</P></>,
    <>    <K k="market_id" /> <Val steps={steps} pick={(x) => x.id} /></>,
    <>  <P>{"},"}</P></>,
    <>  <K k="basis" />      <Val steps={steps} pick={(x) => x.basis} /><P>,</P></>,
    <>  <K k="confidence" /> <Val steps={steps} pick={(x) => x.conf} quoted={false} /></>,
    <P>{"}"}</P>,
  ];
  return (
    <AbsoluteFill>
      <Brand />
      <div style={{ position: "absolute", left: 96, top: 210 }}>
        <div style={{ fontSize: 124, fontWeight: 760, letterSpacing: "-0.04em", lineHeight: 1 }}>
          <Val steps={steps} pick={(x) => x.head} quoted={false} />
        </div>
        <div style={{ fontSize: 38, fontWeight: 500, marginTop: 18, color: C.muted }}>
          <Val steps={steps} pick={(x) => x.sub} quoted={false} />
        </div>
      </div>
      <div style={{ position: "absolute", left: 96, top: 490, fontFamily: MONO, fontSize: 28, lineHeight: "48px", color: C.fg }}>
        {lines.map((l, i) => <div key={i} style={{ whiteSpace: "pre", height: 48 }}>{l}</div>)}
      </div>
      <Abs x={96} y={1262} style={{ fontSize: 24, color: C.dim }}>Live Layer matches, Nov 3, 2026 · ids shortened</Abs>
    </AbsoluteFill>
  );
};

// GAIN lifts the track 1 dB, to about -15 LUFS integrated; it fades out over the last second.
const MUSIC = "layer-music-wavy-bounce-2.wav", MUSIC_FROM = 13.385, GAIN = 1.12;
const hasMusic = getStaticFiles().some((f) => f.name === MUSIC);

export const OneSchemaDark = () => {
  const d = ONE_SCHEMA_DARK_DURATION;
  return (
    <AbsoluteFill style={{ background: C.bg, color: C.fg, fontFamily: SANS }}>
      {hasMusic && (
        <Audio src={staticFile(MUSIC)} trimBefore={Math.round(MUSIC_FROM * FPS)}
          volume={(f) => interpolate(f, [0, d - 30, d], [GAIN, GAIN, 0], clamp)} />
      )}
      {/* Hard cuts, each on an 808. */}
      <Sequence from={0} durationInFrames={H(6)}><Intro /></Sequence>
      <Sequence from={H(6)} durationInFrames={H(12) - H(6)}><Formats s={H(6)} /></Sequence>
      <Sequence from={H(12)} durationInFrames={H(13) - H(12)}>
        <Yellow>
          <div style={{ position: "absolute", left: 96, top: 470 }}>
            <Slam at={0} style={{ ...BIG, fontSize: 168 }}>One</Slam>
            <Slam at={0} style={{ ...BIG, fontSize: 168 }}>schema.</Slam>
          </div>
        </Yellow>
      </Sequence>
      <Sequence from={H(13)} durationInFrames={H(28) - H(13)}><MatchObject s={H(13)} /></Sequence>
      <Sequence from={H(28)}>
        <Yellow>
          <div style={{ position: "absolute", left: 96, top: 380, width: 900 }}>
            <Slam at={0} style={{ ...BIG, whiteSpace: "normal" }}>One API for all prediction markets.</Slam>
          </div>
          <Abs x={96} y={1000} style={{ fontSize: 62, fontWeight: 760, letterSpacing: "-0.03em" }}>
            <Slam at={H(29) - H(28)} from={14}>uselayer.sh</Slam>
          </Abs>
        </Yellow>
      </Sequence>
    </AbsoluteFill>
  );
};
