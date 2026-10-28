import type { CSSProperties, ReactNode } from "react";
import { AbsoluteFill, Audio, Easing, Sequence, getStaticFiles, interpolate, spring, staticFile, useCurrentFrame,
  useVideoConfig } from "remotion";
import { loadFont } from "@remotion/fonts";
import data from "./baskets.json";

// "Where the traders you follow agree": the Baskets launch. The app is drawn here, not recorded (a basket needs a
// signed-in account), as the site draws it (signals/static/index.html: .bk-*), from the owner's real basket read on
// usesignals.app (src/baskets.json). Avatars are the site's identicons, from each wallet's hue and cells. Colors are
// the site's dark theme.
const C = {
  bg: "#0e0e0f", card: "#161617", fg: "#ececec", muted: "#8f8f95", faint: "#838389", line: "#26262a", soft: "#1b1b1e",
  raised: "#26262a", accent: "#ff4d1f",
};
const FONT = "Host Grotesk";
loadFont({ family: FONT, url: staticFile("HostGrotesk-latin-var.woff2"), weight: "300 800" });

const FPS = 30, W = 1920, H = 1080;
const clamp = { extrapolateLeft: "clamp", extrapolateRight: "clamp" } as const;
const ease = Easing.inOut(Easing.cubic);
const out = Easing.out(Easing.cubic);

// The scenes, in frames.
const HOOK = 96, CARDS = 156, APP = 420, END = 126;
const T_CARDS = HOOK, T_APP = T_CARDS + CARDS, T_END = T_APP + APP;
export const BASKETS_DURATION = T_END + END;
const SPLIT_AT = 290; // into the app scene: the camera moves to where they split

// Each trader's identicon, as the site draws it (hue and cells from their wallet, read on the page).
const FACES: Record<string, { h: number; bits: number }> = {
  "NM-P": { h: 52, bits: 174198200 }, gopfan2: { h: 7, bits: 919576265 }, vibing123: { h: 119, bits: 389700543 },
  BreakTheBank: { h: 293, bits: 569553464 },
};
const Avatar = ({ name, size, ring }: { name: string; size: number; ring?: boolean }) => {
  const { h, bits } = FACES[name];
  const cells: ReactNode[] = [];
  for (let y = 0; y < 5; y++) for (let x = 0; x < 3; x++) {
    if (!((bits >>> (y * 3 + x)) & 1)) continue;
    cells.push(<rect key={`${x}${y}`} x={x} y={y} width={1} height={1} />);
    if (x < 2) cells.push(<rect key={`${4 - x}${y}m`} x={4 - x} y={y} width={1} height={1} />);
  }
  return (
    <span style={{ width: size, height: size, borderRadius: "50%", display: "inline-grid", placeItems: "center", flex: "none",
      background: `hsl(${h} 30% 22%)`, color: `hsl(${h} 45% 66%)`, boxShadow: ring ? `0 0 0 3px ${C.card}` : undefined }}>
      <svg viewBox="0 0 5 5" width={size * 0.62} height={size * 0.62} fill="currentColor" shapeRendering="crispEdges">{cells}</svg>
    </span>
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

const useRise = (delay = 0, dur = 16) => {
  const t = interpolate(useCurrentFrame(), [delay, delay + dur], [0, 1], { ...clamp, easing: out });
  return { opacity: t, transform: `translateY(${(1 - t) * 36}px)` } as CSSProperties;
};
const Rise = ({ delay, children, style }: { delay?: number; children: ReactNode; style?: CSSProperties }) =>
  <div style={{ ...useRise(delay), ...style }}>{children}</div>;

const Kind = ({ children }: { children: ReactNode }) => (
  <span style={{ flex: "none", fontSize: 17, fontWeight: 500, border: `1.5px solid ${C.line}`, borderRadius: 8, padding: "0 9px",
    lineHeight: "27px", whiteSpace: "nowrap" }}>{children}</span>
);
const Tag = ({ children }: { children: ReactNode }) => (
  <span style={{ fontSize: 19, fontWeight: 600, background: C.raised, borderRadius: 8, padding: "2px 11px" }}>{children}</span>
);
const Caption = ({ text, frames }: { text: string; frames: number }) => {
  const f = useCurrentFrame();
  const t = interpolate(f, [4, 18, frames - 8, frames], [0, 1, 1, 0], clamp);
  return (
    <>
      <div style={{ position: "absolute", left: 0, right: 0, bottom: 0, height: 330,
        background: `linear-gradient(to top, ${C.bg} 48%, ${C.bg}00)` }} />
      <div style={{ position: "absolute", left: 96, bottom: 70, opacity: t, transform: `translateY(${(1 - t) * 20}px)`,
        fontSize: 64, fontWeight: 650, letterSpacing: -1.5 }}>{text}</div>
    </>
  );
};

// ---- 1. the hook ----
const Hook = () => {
  const f = useCurrentFrame();
  return (
    <AbsoluteFill style={{ justifyContent: "center", alignItems: "center", opacity: interpolate(f, [HOOK - 12, HOOK], [1, 0], clamp) }}>
      {/* Mostly in at frame 0: X shows the first frame before the video plays. */}
      <Rise delay={-10} style={{ display: "flex", alignItems: "center", gap: 22 }}>
        <Logo size={72} /><span style={{ fontSize: 56, fontWeight: 650 }}>Signals</span>
        <span style={{ fontSize: 30, fontWeight: 600, color: C.accent, border: `2px solid ${C.accent}`, borderRadius: 999,
          padding: "6px 18px", marginLeft: 8 }}>New: Baskets</span>
      </Rise>
      <Rise delay={-6} style={{ fontSize: 124, fontWeight: 700, letterSpacing: -4.5, marginTop: 44, textAlign: "center", lineHeight: 1.04 }}>
        Where do the traders<br />you follow <span style={{ color: C.accent }}>agree?</span>
      </Rise>
    </AbsoluteFill>
  );
};

// ---- 2. four traders, four cards, then one basket ----
const CARD_W = 760, CARD_H = 300;
const CARD_AT = [[160, 150], [1000, 150], [160, 500], [1000, 500]];
const Cards = () => {
  const f = useCurrentFrame(), { fps } = useVideoConfig();
  const fly = interpolate(f, [100, 134], [0, 1], { ...clamp, easing: ease });
  const chip = spring({ frame: f - 122, fps, config: { damping: 14 } });
  return (
    <AbsoluteFill style={{ opacity: interpolate(f, [0, 8, CARDS - 8, CARDS], [0, 1, 1, 0], clamp) }}>
      {data.cards.map((c, i) => {
        const pop = spring({ frame: f - 4 - i * 6, fps, config: { damping: 16 } });
        const [x, y] = CARD_AT[i];
        const tx = (W / 2 - CARD_W / 2 - x) * fly, ty = (430 - CARD_H / 2 - y) * fly;
        return (
          <div key={c.name} style={{ position: "absolute", left: x, top: y, width: CARD_W, height: CARD_H, background: C.card,
            border: `1.5px solid ${C.line}`, borderRadius: 18, padding: "26px 30px", boxSizing: "border-box",
            opacity: pop * (1 - fly), transform: `translate(${tx}px, ${ty + (1 - pop) * 40}px) scale(${1 - fly * 0.75})` }}>
            <div style={{ display: "flex", alignItems: "center", gap: 16 }}>
              <Avatar name={c.name} size={56} /><span style={{ fontSize: 30, fontWeight: 600 }}>{c.name}</span>
              <span style={{ marginLeft: "auto", background: C.accent, color: C.bg, fontSize: 18, fontWeight: 600,
                borderRadius: 999, padding: "2px 12px" }}>{c.moves.length} new</span>
            </div>
            <div style={{ borderTop: `1.5px solid ${C.line}`, marginTop: 22, paddingTop: 16, display: "grid", gap: 12 }}>
              {c.moves.map((m, j) => {
                const t = interpolate(f, [16 + i * 6 + j * 9, 26 + i * 6 + j * 9], [0, 1], { ...clamp, easing: out });
                return (
                  <div key={j} style={{ display: "flex", alignItems: "center", gap: 12, fontSize: 21, opacity: t,
                    transform: `translateX(${(1 - t) * -24}px)`, whiteSpace: "nowrap", overflow: "hidden" }}>
                    <span style={{ width: 9, height: 9, borderRadius: "50%", background: C.accent, flex: "none" }} />
                    <Kind>{m[0]}</Kind><span style={{ overflow: "hidden", textOverflow: "ellipsis" }}>{m[1]} · {m[2]}</span>
                  </div>
                );
              })}
            </div>
          </div>
        );
      })}
      <div style={{ position: "absolute", left: 0, right: 0, top: 380, display: "flex", justifyContent: "center",
        opacity: chip, transform: `scale(${0.6 + chip * 0.4})` }}>
        <span style={{ display: "inline-flex", alignItems: "center", gap: 18, background: C.fg, color: C.bg, borderRadius: 999,
          padding: "22px 44px", fontSize: 56, fontWeight: 650 }}>
          {data.basket} <span style={{ opacity: 0.6, fontWeight: 500 }}>{data.traders.length}</span>
        </span>
      </div>
      <Sequence from={0} durationInFrames={104}><Caption text="Checking each one?" frames={104} /></Sequence>
      <Sequence from={118}><Caption text="Put them in one basket." frames={CARDS - 118} /></Sequence>
    </AbsoluteFill>
  );
};

// ---- 3. the basket: where they agree, then where they split ----
const PAD = 140, MAIN_W = 1060, SIDE_X = PAD + MAIN_W + 28, SIDE_W = W - PAD - SIDE_X;
const Bars = ({ count, of, t }: { count: number; of: number; t: number }) => (
  <span style={{ display: "flex", gap: 5 }}>
    {Array.from({ length: of }, (_, i) => (
      <span key={i} style={{ width: 28, height: 10, borderRadius: 5, background: C.line, overflow: "hidden" }}>
        {i < count && <span style={{ display: "block", height: "100%", background: C.fg,
          width: `${interpolate(t * count - i, [0, 1], [0, 100], clamp)}%` }} />}
      </span>
    ))}
  </span>
);
type Agree = (typeof data.agree)[number];
const AgreeRow = ({ r, t, fill }: { r: Agree; t: number; fill: number }) => (
  <div style={{ borderTop: `1.5px solid ${C.line}`, padding: "24px 28px", display: "grid", gap: 16, opacity: t,
    transform: `translateY(${(1 - t) * 30}px)` }}>
    <div style={{ display: "flex", alignItems: "flex-start", gap: 16 }}>
      <span style={{ flex: 1, fontSize: 25, fontWeight: 600, lineHeight: 1.25 }}>{r.title}</span>
      <span style={{ display: "flex", alignItems: "center", gap: 12, fontSize: 25, fontWeight: 600, whiteSpace: "nowrap" }}>
        <Tag>{r.side}</Tag>{r.count} of {r.of}</span>
    </div>
    <div style={{ display: "flex", alignItems: "center", gap: 18, fontSize: 20, color: C.muted }}>
      <Bars count={r.count} of={r.of} t={fill} />
      <span style={{ display: "flex" }}>{r.who.map((n) => <span key={n} style={{ marginRight: -8 }}><Avatar name={n} size={34} ring /></span>)}</span>
      <span style={{ marginLeft: 6 }}>{r.who.join(", ")}{r.other ? ` · ${r.other}` : ""}</span>
    </div>
    {r.putIn && (
      <div style={{ display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: 12 }}>
        {[["They put in", r.putIn], ["They paid on average", r.paid], ["Market price now", r.now]].map(([k, v]) => (
          <div key={k} style={{ background: C.soft, borderRadius: 12, padding: "12px 16px" }}>
            <div style={{ fontSize: 17, color: C.muted }}>{k}</div><div style={{ fontSize: 28, fontWeight: 600 }}>{v}</div>
          </div>
        ))}
      </div>
    )}
    {r.last && (
      <div style={{ display: "flex", alignItems: "center", gap: 12, fontSize: 20 }}>
        <Kind>Bought</Kind><span>{r.last}</span>
        <span style={{ marginLeft: "auto", textDecoration: "underline", textDecorationColor: C.line, textUnderlineOffset: 5 }}>Check your price</span>
      </div>
    )}
  </div>
);

const Screen = () => {
  const f = useCurrentFrame();
  const row = (i: number) => interpolate(f, [34 + i * 22, 50 + i * 22], [0, 1], { ...clamp, easing: out });
  const fill = (i: number) => interpolate(f, [52 + i * 22, 76 + i * 22], [0, 1], { ...clamp, easing: ease });
  const split = (i: number) => interpolate(f, [SPLIT_AT - 30 + i * 12, SPLIT_AT - 14 + i * 12], [0, 1], { ...clamp, easing: out });
  return (
    <div style={{ position: "absolute", width: W, height: H, background: C.bg }}>
      <div style={{ height: 84, borderBottom: `1.5px solid ${C.line}`, display: "flex", alignItems: "center", gap: 40, padding: `0 ${PAD}px` }}>
        <span style={{ display: "flex", alignItems: "center", gap: 12, fontSize: 26, fontWeight: 600 }}><Logo size={36} />Signals</span>
        <span style={{ fontSize: 21, color: C.muted }}>Feed</span>
        <span style={{ fontSize: 21, color: C.accent, background: "#3a1a12", borderRadius: 999, padding: "6px 16px" }}>Watchlist</span>
        <span style={{ fontSize: 21, color: C.muted }}>Traders</span>
      </div>
      <div style={{ position: "absolute", left: PAD, top: 116 }}>
        <div style={{ fontSize: 40, fontWeight: 600, letterSpacing: -0.8 }}>Watchlist</div>
        <div style={{ display: "flex", gap: 12, marginTop: 22 }}>
          {[["Everyone you follow", 4, false], [data.basket, 4, true]].map(([n, c, on]) => (
            <span key={String(n)} style={{ display: "inline-flex", gap: 10, alignItems: "center", fontSize: 21, borderRadius: 999,
              padding: "10px 20px", border: `1.5px solid ${on ? C.fg : C.line}`, background: on ? C.fg : C.card,
              color: on ? C.bg : C.fg, fontWeight: on ? 600 : 400 }}>{n} <span style={{ opacity: 0.6 }}>{c}</span></span>
          ))}
          <span style={{ fontSize: 21, borderRadius: 999, padding: "10px 20px", border: `1.5px dashed ${C.line}`, color: C.muted }}>+ New basket</span>
        </div>
      </div>
      <div style={{ position: "absolute", left: PAD, right: PAD, top: 268, height: 100, background: C.card, border: `1.5px solid ${C.line}`,
        borderRadius: 18, display: "flex", alignItems: "center", gap: 22, padding: "0 28px", opacity: row(-1) }}>
        <span style={{ display: "flex" }}>{data.traders.map((n) => <span key={n} style={{ marginRight: -12 }}><Avatar name={n} size={50} ring /></span>)}</span>
        <span style={{ marginLeft: 12 }}><div style={{ fontSize: 25, fontWeight: 600 }}>{data.basket}</div>
          <div style={{ fontSize: 19, color: C.muted }}>{data.traders.join(", ")}</div></span>
        <span style={{ marginLeft: "auto", fontSize: 20, border: `1.5px solid ${C.line}`, borderRadius: 999, padding: "10px 20px" }}>Edit basket</span>
      </div>
      <div style={{ position: "absolute", left: PAD, top: 392, width: MAIN_W, bottom: -400, background: C.card,
        border: `1.5px solid ${C.line}`, borderRadius: 18, overflow: "hidden" }}>
        <div style={{ padding: "24px 28px 18px" }}>
          <div style={{ fontSize: 27, fontWeight: 600 }}>Where they agree</div>
          <div style={{ fontSize: 19, color: C.muted, marginTop: 4 }}>Markets where 2 or more of this basket hold the same side. Most agreement first.</div>
        </div>
        {data.agree.map((r, i) => <AgreeRow key={i} r={r} t={row(i)} fill={fill(i)} />)}
      </div>
      <div style={{ position: "absolute", left: SIDE_X, top: 392, width: SIDE_W, background: C.card, border: `1.5px solid ${C.line}`,
        borderRadius: 18, overflow: "hidden", opacity: interpolate(f, [SPLIT_AT - 46, SPLIT_AT - 32], [0.35, 1], clamp) }}>
        <div style={{ padding: "24px 26px 18px" }}>
          <div style={{ fontSize: 27, fontWeight: 600 }}>Where they split</div>
          <div style={{ fontSize: 19, color: C.muted, marginTop: 4 }}>On different sides of the same market.</div>
        </div>
        {data.split.map((s, i) => (
          <div key={i} style={{ borderTop: `1.5px solid ${C.line}`, padding: "18px 26px", display: "grid", gap: 10, opacity: split(i),
            transform: `translateY(${(1 - split(i)) * 24}px)` }}>
            <div style={{ fontSize: 21, fontWeight: 500, lineHeight: 1.3 }}>{s.title}</div>
            <div style={{ display: "flex", alignItems: "center", gap: 10, fontSize: 19 }}>
              <Tag>{s.sides[0][0]}</Tag>{s.sides[0][1]}<span style={{ color: C.muted }}>vs</span><Tag>{s.sides[1][0]}</Tag>{s.sides[1][1]}
            </div>
            <div style={{ fontSize: 18, color: C.muted }}>{s.who}</div>
          </div>
        ))}
      </div>
    </div>
  );
};

// The camera over the app: [frame, center x, center y, zoom].
const CAM: [number, number, number, number][] = [
  [0, 960, 540, 1], [70, 960, 540, 1], [110, 690, 640, 1.42], [200, 690, 690, 1.42], [236, 700, 640, 1.18],
  [SPLIT_AT - 40, 760, 600, 1.12], [SPLIT_AT, 1460, 600, 1.42], [APP, 1460, 640, 1.48],
];
const App = () => {
  const f = useCurrentFrame();
  const pick = (j: number) => interpolate(f, CAM.map((c) => c[0]), CAM.map((c) => c[j]), { ...clamp, easing: ease });
  const z = pick(3);
  const cx = Math.min(Math.max(pick(1), W / 2 / z), W - W / 2 / z), cy = Math.min(Math.max(pick(2), H / 2 / z), H - H / 2 / z);
  return (
    <AbsoluteFill style={{ background: C.bg, overflow: "hidden", opacity: interpolate(f, [0, 10, APP - 10, APP], [0, 1, 1, 0], clamp) }}>
      <div style={{ position: "absolute", width: W, height: H, transformOrigin: "0 0",
        transform: `translate(${W / 2 - cx * z}px, ${H / 2 - cy * z}px) scale(${z})` }}><Screen /></div>
      <Sequence from={20} durationInFrames={SPLIT_AT - 50}><Caption text="See where they agree" frames={SPLIT_AT - 50} /></Sequence>
      <Sequence from={SPLIT_AT - 24}><Caption text="…and where they split" frames={APP - SPLIT_AT + 24} /></Sequence>
      <div style={{ position: "absolute", right: 96, bottom: 84, fontSize: 24, color: C.muted }}>A real basket, live Polymarket data, {data.recorded}</div>
    </AbsoluteFill>
  );
};

const End = () => (
  <AbsoluteFill style={{ justifyContent: "center", alignItems: "center", textAlign: "center",
    opacity: interpolate(useCurrentFrame(), [0, 10], [0, 1], clamp) }}>
    <Rise style={{ display: "flex", alignItems: "center", gap: 26 }}>
      <Logo size={104} /><span style={{ fontSize: 92, fontWeight: 700, letterSpacing: -3 }}>Signals</span>
    </Rise>
    <Rise delay={6} style={{ fontSize: 50, marginTop: 40, lineHeight: 1.25 }}>
      Baskets: group the traders you follow.<br />See where they agree.
    </Rise>
    <Rise delay={12} style={{ fontSize: 56, marginTop: 40, color: C.accent, fontWeight: 650 }}>usesignals.app</Rise>
    <Rise delay={18} style={{ fontSize: 24, marginTop: 44, color: C.muted }}>Past trades, not advice. Signals places no orders.</Rise>
  </AbsoluteFill>
);

// Sound: the owner's pick of music when it's in public/ (not in git), from its drop so the video opens on the beat, and
// ticks as the cards land in the basket and each agreement row comes in (public/tick.wav). Defaults as the Watchlist
// video: "East Side Boulevard" from 62.58 s; other tracks are props.
export type BasketsProps = { music: string; from: number; gain: number };
export const BASKETS_DEFAULTS: BasketsProps = { music: "watchlist-music.mp3", from: 62.58, gain: 0.68 };
const TICKS = [T_CARDS + 122, T_APP + 34, T_APP + 56, T_APP + 78, T_APP + SPLIT_AT - 30];
const Sound = ({ music, from, gain }: BasketsProps) => (
  <>
    {getStaticFiles().some((s) => s.name === music) && (
      <Audio src={staticFile(music)} trimBefore={Math.round(from * FPS)}
        volume={(f) => interpolate(f, [0, 2, BASKETS_DURATION - 36, BASKETS_DURATION], [0, gain, gain, 0], clamp)} />
    )}
    {TICKS.map((t) => <Sequence key={t} from={t} durationInFrames={6}><Audio src={staticFile("tick.wav")} volume={0.6} /></Sequence>)}
  </>
);

export const Baskets = (music: BasketsProps) => (
  <AbsoluteFill style={{ background: C.bg, color: C.fg, fontFamily: FONT }}>
    <Sound {...music} />
    <Sequence from={0} durationInFrames={HOOK}><Hook /></Sequence>
    <Sequence from={T_CARDS} durationInFrames={CARDS}><Cards /></Sequence>
    <Sequence from={T_APP} durationInFrames={APP}><App /></Sequence>
    <Sequence from={T_END}><End /></Sequence>
  </AbsoluteFill>
);
