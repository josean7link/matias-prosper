import { useState } from "react";
import { Link } from "react-router-dom";
import Logo from "@/components/Logo";
import { useApp } from "@/contexts/AppContext";
import { toast } from "sonner";
import {
  ArrowUpRight, Copy, Check, Sun, Moon, Code, Lightning, ShieldCheck,
  Webhooks, Key, CurrencyDollar, Book, ArrowRight, Terminal
} from "@phosphor-icons/react";

const ENDPOINTS = [
  {
    section: "Authentication",
    icon: Key,
    items: [
      {
        id: "auth-login", method: "POST", path: "/api/auth/session",
        title: "Exchange OAuth session",
        desc: "Exchange a one-time session_id from Emergent Google OAuth for a long-lived session_token cookie.",
        request: { session_id: "abc123…" },
        response: { user: { user_id: "user_...", email: "ops@prosper.foundation", platform_role: "super_admin" }, session_token: "...eyJhbGci…" },
      },
      {
        id: "auth-me", method: "GET", path: "/api/auth/me",
        title: "Current user",
        desc: "Returns the currently authenticated user's profile and role.",
        response: { user_id: "user_abc", email: "alice@alemany.capital", platform_role: "client_admin", org_id: "org_e0d081eab53d" },
      },
    ],
  },
  {
    section: "Subscribe & Redeem",
    icon: CurrencyDollar,
    items: [
      {
        id: "subscribe", method: "POST", path: "/api/positions/subscribe",
        title: "Subscribe to a yield product",
        desc: "Create a position by converting USDC → PROS. Anchored by a prosperTxId (UUID v4) for idempotency. Returns the new position and the associated transaction.",
        request: { org_id: "org_e0d081eab53d", product_id: "prod_2aaa3d28e4a8", amount: 5000, user_reference_id: "cust_12345" },
        response: { position: { position_id: "pos_...", principal: 5000, status: "active", maturity_date: "2026-07-18T…" }, transaction: { tx_id: "tx_...", prosper_tx_id: "uuid4", status: "submitted", tx_hash: "…" }, prosper_tx_id: "uuid4" },
      },
      {
        id: "redeem", method: "POST", path: "/api/positions/{position_id}/redeem",
        title: "Redeem a position",
        desc: "Settle principal + accrued interest back to the subscriber's account. Requires the calling user to own the position (or be internal Prosper staff).",
        response: { transaction: { type: "redeem", amount: 5102.34, asset_code: "USDC", status: "submitted" }, prosper_tx_id: "uuid4" },
      },
    ],
  },
  {
    section: "Mint (two-signer)",
    icon: ShieldCheck,
    items: [
      {
        id: "mint", method: "POST", path: "/api/transactions/mint",
        title: "Request a PROS mint",
        desc: "Requests a mint. Never executes directly — always creates an Approval. A second user (≠ requester) must approve in the Operations Queue. MFA challenge is enforced if the approver has TOTP enabled.",
        headers: { "Idempotency-Key": "<uuid-v4-per-request>" },
        request: { fund_id: "fund_abc123", amount: 100000, reason: "Q1 2026 Quirón PyMEs inflow batch" },
        response: { status: "pending_approval", approval: { approval_id: "apv_...", required_approvals: 1 }, prosper_tx_id: "uuid4" },
      },
      {
        id: "approve", method: "POST", path: "/api/approvals/{approval_id}/approve",
        title: "Approve a pending request",
        desc: "Second signer approves. Body may include an MFA code if the approver has MFA enabled.",
        request: { mfa_code: "123456" },
        response: { status: "executed", result: { transaction: { tx_id: "tx_..." } } },
      },
    ],
  },
  {
    section: "Webhooks",
    icon: Webhooks,
    items: [
      {
        id: "webhook-create", method: "POST", path: "/api/integrations/webhooks",
        title: "Register a webhook endpoint",
        desc: "Create a webhook endpoint. A plaintext signing secret (whsec_...) is returned ONCE on creation — store it in a secret manager.",
        request: { url: "https://api.yourco.com/hooks/prosper", org_id: "org_abc", app_id: "app_abc", environment: "production", events: ["transaction.confirmed", "position.matured"] },
        response: { endpoint_id: "hook_...", webhook_secret_plaintext: "whsec_abc…", signing_instructions: "X-Prosper-Signature: t=<ts>,v1=<hmac-sha256>" },
      },
    ],
  },
  {
    section: "Transactions & Audit",
    icon: Lightning,
    items: [
      {
        id: "tx-list", method: "GET", path: "/api/transactions",
        title: "List transactions",
        desc: "Supports filters: env, type, status, org_id, search, from (YYYY-MM-DD), to (YYYY-MM-DD). Pagination via page & page_size.",
        queryParams: "?env=production&type=subscribe&from=2026-01-01&page=1&page_size=50",
        response: { items: ["…"], total: 121, page: 1, page_size: 50, has_more: true },
      },
      {
        id: "search", method: "GET", path: "/api/search",
        title: "Global search (⌘K)",
        desc: "Searches across clients, transactions, positions, api keys, onboarding. Returns top 6 per group.",
        queryParams: "?q=alemany",
      },
    ],
  },
];

const LANGS = ["curl", "javascript", "python"];

export default function DevPortal() {
  const { theme, toggleTheme } = useApp();
  const [activeId, setActiveId] = useState(ENDPOINTS[0].items[0].id);
  const [lang, setLang] = useState("curl");

  const active = ENDPOINTS.flatMap(s => s.items).find(e => e.id === activeId) || ENDPOINTS[0].items[0];

  const copy = (s) => {
    navigator.clipboard.writeText(s);
    toast.success("Copied");
  };

  return (
    <div className="min-h-screen" style={{ background: "var(--bg)" }} data-testid="dev-portal">
      {/* Header */}
      <header className="border-b border-[var(--border)] bg-[var(--surface)] px-6 md:px-10 py-4 flex items-center justify-between sticky top-0 z-30">
        <Link to="/" data-testid="dev-logo"><Logo size={28} /></Link>
        <div className="flex items-center gap-2 text-sm text-[var(--fg-muted)]">
          <Book size={14} weight="bold" />
          <span className="font-mono uppercase tracking-[0.15em] text-xs">Developers</span>
          <span className="px-2 py-0.5 rounded-full bg-[var(--primary-soft)] text-[var(--primary)] text-[10px] font-mono uppercase tracking-wider">v0.1</span>
        </div>
        <div className="flex items-center gap-2">
          <button onClick={toggleTheme}
                  className="w-9 h-9 rounded-full border border-[var(--border)] hover:bg-[var(--surface-hover)] flex items-center justify-center"
                  data-testid="theme-toggle">
            {theme === "dark" ? <Sun size={15} weight="bold" /> : <Moon size={15} weight="bold" />}
          </button>
          <Link to="/login" className="btn-pill btn-primary text-sm" data-testid="dev-launch">
            Launch App
            <span className="arrow-box"><ArrowUpRight size={11} weight="bold" /></span>
          </Link>
        </div>
      </header>

      {/* Hero */}
      <section className="border-b border-[var(--border)] px-6 md:px-10 py-14 max-w-7xl mx-auto">
        <div className="text-xs font-medium tracking-[0.25em] uppercase text-[var(--primary)] mb-4">
          Prosper API
        </div>
        <h1 className="font-display font-black text-4xl md:text-6xl tracking-tight leading-[0.98] text-[var(--fg)] mb-4 max-w-3xl">
          Tokenized yield,<br/>
          <span className="text-[var(--fg-muted)]">programmable over HTTPS.</span>
        </h1>
        <p className="text-[var(--fg-muted)] text-base max-w-2xl mb-6">
          Subscribe, redeem, mint, and reconcile PROS across the Stellar rail — all anchored by a
          <code className="mx-1 px-2 py-0.5 rounded bg-[var(--surface)] border border-[var(--border)] font-mono text-xs">prosperTxId</code>
          for perfect idempotency between off-chain and on-chain.
        </p>
        <div className="flex items-center gap-3 flex-wrap">
          <a href="#quickstart" className="btn-pill btn-primary text-sm">
            <Terminal size={14} weight="bold" /> Quickstart
          </a>
          <a href="#endpoints" className="btn-pill btn-outline text-sm">
            Endpoint reference <ArrowRight size={13} weight="bold" />
          </a>
          <a href="/openapi.json" target="_blank" rel="noreferrer" className="btn-pill btn-ghost text-sm">
            OpenAPI schema <ArrowUpRight size={13} />
          </a>
        </div>

        {/* Quick cards */}
        <div className="grid grid-cols-1 md:grid-cols-3 gap-3 mt-10">
          <FeatureCard icon={ShieldCheck} title="Regulated infrastructure"
                       desc="CNV-regulated Quirón PyMEs fund, Moody's Local AA rating, institutional custody on Stellar." />
          <FeatureCard icon={Lightning} title="Idempotent by design"
                       desc="Every write mutation accepts an Idempotency-Key header and uses prosperTxId as the reconciliation anchor." />
          <FeatureCard icon={Code} title="SDK-ready"
                       desc="OpenAPI 3.1 schema, typed REST with ISO-8601 timestamps, webhook HMAC signatures." />
        </div>
      </section>

      {/* Quickstart */}
      <section id="quickstart" className="border-b border-[var(--border)] px-6 md:px-10 py-14 max-w-7xl mx-auto">
        <div className="text-xs font-medium tracking-[0.25em] uppercase text-[var(--primary)] mb-2">Quickstart</div>
        <h2 className="font-display font-bold text-3xl mb-6">Subscribe an end customer in 30 seconds</h2>
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-8">
          <Step n="1" title="Get an API key">
            From the backoffice, go to <code className="text-xs">API Keys → New Key</code>. Copy the plaintext value once; we never show it again.
          </Step>
          <Step n="2" title="Call /positions/subscribe">
            Pass <code className="text-xs">amount</code> (USDC), <code className="text-xs">product_id</code>, and your internal <code className="text-xs">user_reference_id</code>. You'll receive a <code className="text-xs">prosperTxId</code> and a Stellar <code className="text-xs">tx_hash</code>.
          </Step>
          <Step n="3" title="Listen to webhooks">
            Register a webhook endpoint. We'll POST <code className="text-xs">transaction.confirmed</code> with <code className="text-xs">X-Prosper-Signature: t=…,v1=…</code>. Verify HMAC-SHA256.
          </Step>
        </div>
      </section>

      {/* Endpoint reference */}
      <section id="endpoints" className="max-w-7xl mx-auto px-6 md:px-10 py-14">
        <div className="text-xs font-medium tracking-[0.25em] uppercase text-[var(--primary)] mb-2">Reference</div>
        <h2 className="font-display font-bold text-3xl mb-8">Endpoints</h2>

        <div className="grid grid-cols-1 lg:grid-cols-[260px_1fr] gap-8">
          {/* Sidebar */}
          <nav className="lg:sticky lg:top-20 lg:self-start lg:max-h-[calc(100vh-120px)] lg:overflow-y-auto space-y-5 pb-4">
            {ENDPOINTS.map((s) => (
              <div key={s.section}>
                <div className="flex items-center gap-2 mb-2 text-[10px] uppercase tracking-[0.15em] text-[var(--fg-muted)]">
                  <s.icon size={12} weight="bold" />
                  <span>{s.section}</span>
                </div>
                <ul className="space-y-0.5">
                  {s.items.map((it) => (
                    <li key={it.id}>
                      <button onClick={() => setActiveId(it.id)}
                              data-testid={`nav-endpoint-${it.id}`}
                              className={`w-full text-left px-3 py-1.5 rounded-md text-sm transition-colors ${
                                activeId === it.id ? "bg-[var(--primary-soft)] text-[var(--primary)] font-medium"
                                                   : "text-[var(--fg-muted)] hover:bg-[var(--surface-hover)]"
                              }`}>
                        <Method m={it.method} />
                        <span className="ml-2 font-mono text-xs">{it.path.replace("/api", "")}</span>
                      </button>
                    </li>
                  ))}
                </ul>
              </div>
            ))}
          </nav>

          {/* Active endpoint detail */}
          <div data-testid={`endpoint-${active.id}`}>
            <div className="flex items-center gap-3 mb-3 flex-wrap">
              <Method m={active.method} large />
              <code className="font-mono text-sm md:text-base bg-[var(--surface)] border border-[var(--border)] px-3 py-1.5 rounded-full">{active.path}</code>
              <button onClick={() => copy(active.path)} className="p-2 rounded-full hover:bg-[var(--surface-hover)]" data-testid={`copy-${active.id}`}>
                <Copy size={12} />
              </button>
            </div>
            <h3 className="font-display font-bold text-2xl mb-2">{active.title}</h3>
            <p className="text-[var(--fg-muted)] mb-6">{active.desc}</p>

            {active.headers && (
              <Block title="Required headers">
                <CodeBlock code={JSON.stringify(active.headers, null, 2)} onCopy={copy} />
              </Block>
            )}

            {active.queryParams && (
              <Block title="Query parameters">
                <CodeBlock code={active.path + active.queryParams} onCopy={copy} />
              </Block>
            )}

            {active.request && (
              <Block title="Request body">
                <CodeBlock code={JSON.stringify(active.request, null, 2)} onCopy={copy} />
              </Block>
            )}

            {/* Example requests */}
            <div className="mt-6">
              <div className="flex items-center gap-2 mb-3">
                <div className="text-[10px] uppercase tracking-[0.15em] text-[var(--fg-muted)] mr-2">Example</div>
                <div className="flex p-0.5 rounded-full bg-[var(--surface)] border border-[var(--border)]">
                  {LANGS.map((l) => (
                    <button key={l} onClick={() => setLang(l)}
                            data-testid={`lang-${l}`}
                            className={`px-3 py-1 rounded-full text-xs font-mono uppercase tracking-wider transition-colors ${
                              lang === l ? "bg-[var(--primary)] text-white"
                                         : "text-[var(--fg-muted)] hover:text-[var(--fg)]"
                            }`}>{l}</button>
                  ))}
                </div>
              </div>
              <CodeBlock code={buildExample(lang, active)} onCopy={copy} />
            </div>

            {active.response && (
              <Block title="Response">
                <CodeBlock code={JSON.stringify(active.response, null, 2)} onCopy={copy} />
              </Block>
            )}
          </div>
        </div>
      </section>

      {/* Footer */}
      <footer className="border-t border-[var(--border)] px-6 md:px-10 py-8 text-center text-xs text-[var(--fg-muted)] font-mono">
        Prosper · CNV Regulated · Built on Stellar · <a href="/login" className="text-[var(--primary)] hover:underline">Launch backoffice</a>
      </footer>
    </div>
  );
}

function Method({ m, large }) {
  const map = { GET: "var(--primary)", POST: "var(--success)", PATCH: "var(--warning)", DELETE: "var(--danger)" };
  return (
    <span className={`font-mono font-semibold uppercase tracking-wider ${large ? "text-sm px-3 py-1" : "text-[10px] px-2 py-0.5"} rounded-full`}
          style={{ background: `${map[m]}20`, color: map[m] }}>{m}</span>
  );
}

function FeatureCard({ icon: Icon, title, desc }) {
  return (
    <div className="prosper-card p-5">
      <Icon size={20} weight="duotone" className="text-[var(--primary)] mb-3" />
      <div className="font-display font-bold mb-1">{title}</div>
      <p className="text-sm text-[var(--fg-muted)]">{desc}</p>
    </div>
  );
}

function Step({ n, title, children }) {
  return (
    <div className="prosper-card p-5">
      <div className="flex items-center gap-2 mb-2">
        <span className="w-6 h-6 rounded-full bg-[var(--primary)] text-white text-xs font-bold flex items-center justify-center">{n}</span>
        <div className="font-display font-bold">{title}</div>
      </div>
      <p className="text-sm text-[var(--fg-muted)]">{children}</p>
    </div>
  );
}

function Block({ title, children }) {
  return (
    <div className="mt-6">
      <div className="text-[10px] uppercase tracking-[0.15em] text-[var(--fg-muted)] mb-2">{title}</div>
      {children}
    </div>
  );
}

function CodeBlock({ code, onCopy }) {
  const [copied, setCopied] = useState(false);
  const handle = () => { onCopy(code); setCopied(true); setTimeout(() => setCopied(false), 1200); };
  return (
    <div className="relative group">
      <pre className="bg-[var(--surface)] border border-[var(--border)] rounded-lg p-4 overflow-x-auto text-xs font-mono leading-relaxed text-[var(--fg)]">
        <code>{code}</code>
      </pre>
      <button onClick={handle}
              className="absolute top-2 right-2 p-1.5 rounded-md bg-[var(--bg)] border border-[var(--border)] opacity-0 group-hover:opacity-100 transition-opacity">
        {copied ? <Check size={12} style={{ color: "var(--success)" }} /> : <Copy size={12} />}
      </button>
    </div>
  );
}

function buildExample(lang, ep) {
  const baseUrl = "https://api.prosper.foundation";
  const url = `${baseUrl}${ep.path.replace("{approval_id}", "apv_abc").replace("{position_id}", "pos_abc")}${ep.queryParams || ""}`;
  const bodyJson = ep.request ? JSON.stringify(ep.request, null, 2) : "";
  if (lang === "curl") {
    const headerLines = [
      '-H "Authorization: Bearer pk_live_..."',
      ep.request ? '-H "Content-Type: application/json"' : null,
      ep.headers?.["Idempotency-Key"] ? '-H "Idempotency-Key: $(uuidgen)"' : null,
    ].filter(Boolean).join(" \\\n  ");
    return `curl -X ${ep.method} "${url}" \\\n  ${headerLines}${ep.request ? ` \\\n  -d '${bodyJson.replace(/\n/g, "")}'` : ""}`;
  }
  if (lang === "javascript") {
    const opts = `{
  method: "${ep.method}",
  headers: {
    "Authorization": "Bearer " + process.env.PROSPER_KEY,${ep.request ? '\n    "Content-Type": "application/json",' : ""}${ep.headers?.["Idempotency-Key"] ? '\n    "Idempotency-Key": crypto.randomUUID(),' : ""}
  },${ep.request ? `\n  body: JSON.stringify(${bodyJson}),` : ""}
}`;
    return `const res = await fetch("${url}", ${opts});
const data = await res.json();
console.log(data);`;
  }
  // python
  const body = ep.request ? `\n    json=${bodyJson.replace(/"/g, "'")}` : "";
  const idem = ep.headers?.["Idempotency-Key"] ? `, "Idempotency-Key": str(uuid.uuid4())` : "";
  return `import os, requests${ep.headers?.["Idempotency-Key"] ? ", uuid" : ""}

r = requests.${ep.method.toLowerCase()}(
    "${url}",
    headers={"Authorization": f"Bearer {os.environ['PROSPER_KEY']}"${idem}},${body}
)
print(r.json())`;
}
