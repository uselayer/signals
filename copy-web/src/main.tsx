// The /copy page: set up one-tap copy (signals/copying.py). Only accounts in the owner's flag get past the first
// check (/api/me/copy is 404 for everyone else). Steps, each signed by the follower in their own Privy wallet:
// 1. Polymarket's geoblock, from this browser: where Polymarket doesn't allow new trades, it stops here.
// 2. Privy sign-in (email or Google): makes the follower's wallet, whose key never leaves Privy.
// 3. Their Polymarket Deposit Wallet (deployed for them, gas paid by Signals' builder key).
// 4. Trading approvals, then their approval of the Signals trading key (a session key: trades only, can't withdraw).
// Then: where to send funds (Polymarket's bridge) and the balance.
import { createSecureClient, remoteBuilderSigning } from "@polymarket/client";
import { signerFrom } from "@polymarket/client/viem";
import { PrivyProvider, usePrivy, useWallets } from "@privy-io/react-auth";
import { StrictMode, useCallback, useEffect, useState } from "react";
import { createRoot } from "react-dom/client";
import { createPublicClient, createWalletClient, custom, erc20Abi, formatUnits, http } from "viem";
import { polygon } from "viem/chains";

const PUSD = "0xC011a7E12a19f7B1f670d46F03B03f3342E82DFB"; // Polymarket's collateral (6 decimals)

type Clerk = {
  load: (o: unknown) => Promise<void>;
  isSignedIn?: boolean;
  session?: { getToken: () => Promise<string | null> } | null;
  openSignIn: () => void;
  addListener: (f: () => void) => void;
};
declare global {
  interface Window {
    Clerk?: Clerk;
    __internal_ClerkUICtor?: unknown;
  }
}

type CopyState = {
  state: "none" | "key" | "ready";
  signer: string | null;
  wallet: string | null;
  owner: string | null;
  usd: number;
  collar: number;
  privy_app_id: string;
  builder_code: string | null;
};
type Geo = { blocked: boolean; country?: string; region?: string };

class ApiError extends Error {
  constructor(message: string, readonly status: number) {
    super(message);
  }
}

async function api<T>(path: string, body?: unknown): Promise<T> {
  const token = await window.Clerk?.session?.getToken().catch(() => null);
  const r = await fetch(path, {
    method: body === undefined ? "GET" : "POST",
    headers: { "Content-Type": "application/json", ...(token ? { Authorization: `Bearer ${token}` } : {}) },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  const data = await r.json().catch(() => ({}));
  if (!r.ok) throw new ApiError(typeof data.detail === "string" ? data.detail : `Something went wrong (${r.status}).`, r.status);
  return data as T;
}

function loadScript(src: string, attrs: Record<string, string> = {}): Promise<void> {
  return new Promise((ok, fail) => {
    const s = document.createElement("script");
    Object.assign(s, { src, async: true, crossOrigin: "anonymous", onload: () => ok(), onerror: fail });
    for (const [k, v] of Object.entries(attrs)) s.setAttribute(k, v);
    document.head.appendChild(s);
  });
}

// Clerk, as the main page loads it (signals/static/index.html startAuth).
async function startClerk(): Promise<boolean> {
  const cfg = await fetch("/api/config").then((r) => r.json());
  const key: string = cfg.clerk_key || "";
  const m = /^pk_(test|live)_(.+)$/.exec(key);
  const fapi = m ? atob(m[2].replace(/-/g, "+").replace(/_/g, "/")).replace(/\$$/, "") : "";
  if (!/^[a-z0-9.-]+$/i.test(fapi)) return false;
  await loadScript(`https://${fapi}/npm/@clerk/ui@1/dist/ui.browser.js`);
  await loadScript(`https://${fapi}/npm/@clerk/clerk-js@6/dist/clerk.browser.js`, { "data-clerk-publishable-key": key });
  await window.Clerk!.load({ ui: { ClerkUI: window.__internal_ClerkUICtor } });
  return true;
}

function Page({ children }: { children: React.ReactNode }) {
  return (
    <main>
      <a className="back" href="/#/">← Signals</a>
      <h1>Copy trades</h1>
      {children}
    </main>
  );
}

function Boot() {
  const [phase, setPhase] = useState<"loading" | "signin" | "off" | "blocked" | "go" | "error">("loading");
  const [state, setState] = useState<CopyState | null>(null);
  const [geo, setGeo] = useState<Geo | null>(null);
  const [error, setError] = useState("");

  const check = useCallback(async () => {
    if (!window.Clerk?.isSignedIn) return setPhase("signin");
    try {
      const s = await api<CopyState>("/api/me/copy");
      setState(s);
      if (s.state === "ready") return setPhase("go");
      const g: Geo = await fetch("https://polymarket.com/api/geoblock").then((r) => r.json());
      setGeo(g);
      setPhase(g.blocked ? "blocked" : "go");
    } catch (e) {
      if (e instanceof ApiError && e.status === 404) return setPhase("off");
      setError(e instanceof Error ? e.message : String(e));
      setPhase("error");
    }
  }, []);

  useEffect(() => {
    startClerk()
      .then((on) => {
        if (!on) return setPhase("off");
        window.Clerk!.addListener(() => void check());
        return check();
      })
      .catch(() => {
        setError("Sign-in couldn't load. Reload the page.");
        setPhase("error");
      });
  }, [check]);

  if (phase === "loading") return <Page><p className="muted">Loading…</p></Page>;
  if (phase === "signin")
    return (
      <Page>
        <p>Sign in to Signals to set up copying.</p>
        <button onClick={() => window.Clerk?.openSignIn()}>Sign in</button>
      </Page>
    );
  if (phase === "off") return <Page><p>Copying isn't available for your account yet.</p></Page>;
  if (phase === "error") return <Page><p className="error">{error}</p></Page>;
  if (phase === "blocked")
    return (
      <Page>
        <p>
          Polymarket doesn't allow new trades {geo?.country ? `in ${geo.country}` : "where you are"}, so copying isn't
          available there. Your alerts keep their Polymarket US and Kalshi links.
        </p>
      </Page>
    );
  if (!state) return null;
  if (state.state === "ready") return <Ready state={state} />;
  if (!state.privy_app_id) return <Page><p>Copying isn't set up here yet.</p></Page>;
  return (
    <PrivyProvider
      appId={state.privy_app_id}
      config={{
        loginMethods: ["email", "google"],
        embeddedWallets: { ethereum: { createOnLogin: "users-without-wallets" } },
        defaultChain: polygon,
        supportedChains: [polygon],
      }}
    >
      <Setup state={state} geo={geo!} onDone={check} />
    </PrivyProvider>
  );
}

function Setup({ state, geo, onDone }: { state: CopyState; geo: Geo; onDone: () => void }) {
  const { ready, authenticated, login } = usePrivy();
  const { wallets, ready: walletsReady } = useWallets();
  const wallet = wallets.find((w) => w.walletClientType === "privy");
  const [step, setStep] = useState("");
  const [error, setError] = useState("");

  const run = async () => {
    if (!wallet) return;
    setError("");
    try {
      setStep("Connecting your wallet…");
      await wallet.switchChain(polygon.id);
      const provider = await wallet.getEthereumProvider();
      const walletClient = createWalletClient({ account: wallet.address as `0x${string}`, chain: polygon, transport: custom(provider) });
      const { signer } = await api<{ signer: string }>("/api/me/copy/start", { owner: wallet.address, country: geo.country ?? null, blocked: geo.blocked });

      setStep("Creating your Polymarket wallet…");
      const client = await createSecureClient({
        signer: signerFrom(walletClient),
        apiKey: remoteBuilderSigning({
          url: "/api/copy/builder-sign",
          headers: async (): Promise<Record<string, string>> => {
            const t = await window.Clerk?.session?.getToken();
            return t ? { Authorization: `Bearer ${t}` } : {};
          },
        }),
      });

      setStep("Approving trading…");
      await client.setupTradingApprovals();

      setStep("Approving Signals to place your copies…");
      const keys = await client.fetchSessionKeys();
      if (!keys.some((k: { address: string }) => k.address.toLowerCase() === signer.toLowerCase())) {
        await client.authorizeSessionKey({ address: signer, scopes: ["CLOB"] } as Parameters<typeof client.authorizeSessionKey>[0]);
      }

      await api("/api/me/copy/finish", { wallet: client.account.wallet });
      setStep("");
      onDone();
    } catch (e) {
      setStep("");
      setError(e instanceof Error ? e.message : String(e));
    }
  };

  if (!ready) return <Page><p className="muted">Loading…</p></Page>;
  return (
    <Page>
      <p>
        Copy puts a <b>Copy ${state.usd}</b> button on your alerts. Tap it and Signals buys the same outcome on
        Polymarket for ${state.usd}, at most {Math.round(state.collar * 100)}¢ a share above the price in the alert. Nothing is
        bought unless you tap.
      </p>
      <ol className="steps">
        <li>Sign in to your wallet. It's yours: Signals never sees its key.</li>
        <li>Signals creates your Polymarket wallet and pays its set-up fees.</li>
        <li>You approve a Signals trading key. It can buy and sell for you, never withdraw. You can turn it off any time.</li>
      </ol>
      {!authenticated ? (
        <button onClick={login}>Sign in to your wallet</button>
      ) : !walletsReady || !wallet ? (
        <p className="muted">Creating your wallet…</p>
      ) : step ? (
        <p className="muted">{step} Approve each request in the window that opens.</p>
      ) : (
        <button onClick={run}>{state.state === "key" ? "Finish setting up" : "Set up copying"}</button>
      )}
      {error && <p className="error">{error}</p>}
    </Page>
  );
}

function Ready({ state }: { state: CopyState }) {
  const [deposit, setDeposit] = useState<string | null>(null);
  const [balance, setBalance] = useState<string | null>(null);
  const [error, setError] = useState("");
  const wallet = state.wallet as `0x${string}`;

  useEffect(() => {
    const headers: Record<string, string> = { "Content-Type": "application/json" };
    if (state.builder_code) headers["X-Builder-Code"] = state.builder_code;
    fetch("https://bridge.polymarket.com/deposit", { method: "POST", headers, body: JSON.stringify({ address: wallet }) })
      .then((r) => r.json())
      .then((d) => setDeposit(d?.address?.evm ?? null))
      .catch(() => setError("Couldn't get your deposit address just now. Reload to try again."));
    createPublicClient({ chain: polygon, transport: http() })
      .readContract({ address: PUSD, abi: erc20Abi, functionName: "balanceOf", args: [wallet] })
      .then((b) => setBalance(Number(formatUnits(b, 6)).toFixed(2)))
      .catch(() => setBalance(null));
  }, [wallet, state.builder_code]);

  return (
    <Page>
      <p>
        Copying is on. Your alerts now have a <b>Copy ${state.usd}</b> button.
      </p>
      <dl>
        <dt>Balance</dt>
        <dd>{balance === null ? "…" : `$${balance}`}</dd>
        <dt>Your Polymarket wallet</dt>
        <dd className="mono">{wallet}</dd>
      </dl>
      <h2>Add funds</h2>
      {deposit ? (
        <>
          <p>Send USDC on Polygon, Base, Arbitrum or Ethereum to this address. It arrives in your Polymarket wallet as pUSD, Polymarket's dollar.</p>
          <p className="mono box">{deposit}</p>
          <p className="muted">Send only USDC, from one of those networks. Each network has a minimum deposit.</p>
        </>
      ) : (
        !error && <p className="muted">Getting your deposit address…</p>
      )}
      {error && <p className="error">{error}</p>}
    </Page>
  );
}

const css = `
:root{--bg:#fff;--fg:#111;--muted:#666;--line:#e5e5e5;--accent:#111;--err:#b42318}
@media (prefers-color-scheme:dark){:root{--bg:#0b0b0c;--fg:#f2f2f2;--muted:#9a9a9a;--line:#26262a;--accent:#f2f2f2;--err:#ff6b5e}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--fg);font:16px/1.5 -apple-system,BlinkMacSystemFont,"Segoe UI",Inter,sans-serif}
main{max-width:560px;margin:0 auto;padding:24px 16px 64px}h1{font-size:24px;margin:16px 0}h2{font-size:18px;margin:28px 0 8px}
.back{color:var(--muted);text-decoration:none;font-size:14px}.muted{color:var(--muted)}.error{color:var(--err)}
button{background:var(--accent);color:var(--bg);border:0;border-radius:8px;padding:10px 16px;font:inherit;font-weight:600;cursor:pointer}
.steps{padding-left:20px;color:var(--muted)}.steps li{margin:6px 0}
dl{display:grid;grid-template-columns:auto 1fr;gap:6px 16px;margin:16px 0}dt{color:var(--muted)}dd{margin:0}
.mono{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:14px;word-break:break-all}
.box{border:1px solid var(--line);border-radius:8px;padding:10px 12px}
`;
const style = document.createElement("style");
style.textContent = css;
document.head.appendChild(style);

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <Boot />
  </StrictMode>,
);
