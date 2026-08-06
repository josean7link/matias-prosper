"use client";
import { useState } from "react";
import Link from "next/link";
import {
  Rocket, KeyRound, Webhook as WebhookIcon, Code, Package,
  AlertCircle, Zap,
} from "lucide-react";
import { PageHeader } from "@prosper/ui";
import { CodeBlock, CodeTabs } from "@/components/CodeBlock";

const SECTIONS = [
  { id: "quickstart",   label: "Quickstart",         icon: Rocket },
  { id: "auth",         label: "Authentication",     icon: KeyRound },
  { id: "endpoints",    label: "Endpoints",          icon: Code },
  { id: "webhooks",     label: "Webhooks",           icon: WebhookIcon },
  { id: "sdks",         label: "SDKs",               icon: Package },
  { id: "errors",       label: "Errors",             icon: AlertCircle },
] as const;

const QUICKSTART_CURL = `# 1. Conseguí tu API key en /client/api-keys
# 2. Hacé tu primera llamada
curl -X POST https://api.prosper.foundation/v1/client/onramp/quote \\
  -H "Authorization: Bearer pk_sandbox_..." \\
  -H "Content-Type: application/json" \\
  -d '{"source_currency": "ARS", "source_amount": 100000}'`;

const QUICKSTART_JS = `import { Prosper } from '@prosper/sdk';

const prosper = new Prosper({ apiKey: 'pk_sandbox_...' });

const quote = await prosper.onramp.quote({
  sourceCurrency: 'ARS',
  sourceAmount: 100000,
});
console.log(quote.targetAmount, 'USDC');`;

const QUICKSTART_PY = `from prosper_sdk import Prosper

client = Prosper(api_key="pk_sandbox_...")

quote = client.onramp.quote(
    source_currency="ARS",
    source_amount=100_000,
)
print(quote.target_amount, "USDC")`;

const AUTH_TABS = [
  { id: "bearer", label: "Bearer", lang: "http",
    code: `GET /v1/client/positions HTTP/1.1
Host: api.prosper.foundation
Authorization: Bearer pk_sandbox_a1b2c3...
Idempotency-Key: 5e8f0e6d-...`},
];

const ENDPOINT_LIST: Array<{
  method: string; path: string; desc: string;
  tabs: { id: string; label: string; lang?: string; code: string }[];
}> = [
  {
    method: "POST", path: "/v1/client/onramp/quote",
    desc: "Devuelve cotización de fiat → USDC con TTL de 60s.",
    tabs: [
      { id: "curl", label: "curl", lang: "bash",
        code: `curl -X POST https://api.prosper.foundation/v1/client/onramp/quote \\
  -H "Authorization: Bearer $PROSPER_KEY" \\
  -d '{"source_currency":"ARS","source_amount":100000}'` },
      { id: "js", label: "JavaScript", lang: "ts",
        code: `await prosper.onramp.quote({
  sourceCurrency: 'ARS',
  sourceAmount: 100000,
});` },
      { id: "py", label: "Python", lang: "python",
        code: `client.onramp.quote(
    source_currency="ARS",
    source_amount=100_000,
)` },
    ],
  },
  {
    method: "POST", path: "/v1/client/onramp/orders",
    desc: "Crea una orden de onramp (devuelve checkout_url de Alfred).",
    tabs: [
      { id: "curl", label: "curl", lang: "bash",
        code: `curl -X POST https://api.prosper.foundation/v1/client/onramp/orders \\
  -H "Authorization: Bearer $PROSPER_KEY" \\
  -d '{"quote_id":"qt_...","source_currency":"ARS",
       "source_amount":100000,"payment_method":"transfer"}'` },
      { id: "js", label: "JavaScript", lang: "ts",
        code: `await prosper.onramp.create({
  quoteId: q.quoteId,
  sourceCurrency: 'ARS',
  sourceAmount: 100000,
  paymentMethod: 'transfer',
});` },
    ],
  },
  {
    method: "POST", path: "/v1/client/offramp/orders",
    desc: "Crea una orden de offramp con HMAC-firmada bank_account.",
    tabs: [
      { id: "curl", label: "curl", lang: "bash",
        code: `curl -X POST https://api.prosper.foundation/v1/client/offramp/orders \\
  -H "Authorization: Bearer $PROSPER_KEY" \\
  -d '{"quote_id":"qt_...","usdc_amount":100,
       "target_currency":"ARS","source":"balance",
       "bank_account":{"holder_name":"Acme SA",
                        "country":"AR","cbu_or_iban":"..."}}'` },
    ],
  },
  {
    method: "GET", path: "/v1/client/positions",
    desc: "Lista todas tus posiciones (active, matured, redeemed).",
    tabs: [
      { id: "curl", label: "curl", lang: "bash",
        code: `curl https://api.prosper.foundation/v1/client/positions \\
  -H "Authorization: Bearer $PROSPER_KEY"` },
      { id: "js", label: "JavaScript", lang: "ts",
        code: `const { items } = await prosper.positions.list();` },
    ],
  },
  {
    method: "POST", path: "/v1/client/positions/{id}/redeem",
    desc: "Redime una posición liquid o ya madurada.",
    tabs: [
      { id: "curl", label: "curl", lang: "bash",
        code: `curl -X POST https://api.prosper.foundation/v1/client/positions/pos_abc/redeem \\
  -H "Authorization: Bearer $PROSPER_KEY"` },
      { id: "js", label: "JavaScript", lang: "ts",
        code: `await prosper.positions.redeem('pos_abc');` },
    ],
  },
  {
    method: "GET", path: "/v1/client/balances",
    desc: "Saldo libre USDC + balance Prosper + balance XLM Stellar.",
    tabs: [
      { id: "curl", label: "curl", lang: "bash",
        code: `curl https://api.prosper.foundation/v1/client/balances \\
  -H "Authorization: Bearer $PROSPER_KEY"` },
    ],
  },
];

const HMAC_VERIFY = `import crypto from 'crypto';

function verifySignature(payload, signature, secret) {
  const expected = crypto
    .createHmac('sha256', secret)
    .update(payload)
    .digest('hex');
  return crypto.timingSafeEqual(
    Buffer.from(expected),
    Buffer.from(signature),
  );
}`;

const ERROR_FMT = `{
  "detail": "Excede cap diario USD 250000 (usaste 100000)",
  "error_code": "cap_exceeded",
  "request_id": "req_5e8f0e6d..."
}`;

export default function DevelopersPage() {
  const [section, setSection] = useState<typeof SECTIONS[number]["id"]>("quickstart");

  return (
    <div data-testid="developers-page">
      <PageHeader
        breadcrumbs={[{ label: "Inicio", href: "/client" }, { label: "Developers" }]}
        title="Documentación API"
        subtitle="Guías rápidas, referencia de endpoints y verificación de webhooks."
      />

      <div className="grid grid-cols-1 lg:grid-cols-[200px_1fr] gap-6">
        {/* SIDEBAR */}
        <aside className="lg:sticky lg:top-20 self-start" data-testid="docs-sidebar">
          <nav className="space-y-0.5">
            {SECTIONS.map((s) => {
              const Icon = s.icon;
              const active = section === s.id;
              return (
                <button key={s.id} onClick={() => setSection(s.id)}
                  className={`w-full text-left flex items-center gap-2 px-3 py-2 rounded text-xs
                              font-display font-semibold transition-colors
                              ${active ? "bg-primary/10 text-primary"
                                        : "text-fg-muted hover:text-fg hover:bg-surface-hover"}`}
                  data-testid={`docs-nav-${s.id}`}>
                  <Icon size={13}/> {s.label}
                </button>
              );
            })}
          </nav>
        </aside>

        {/* CONTENT */}
        <article className="space-y-6 max-w-3xl" data-testid="docs-content">
          {section === "quickstart" && (
            <Section title="Quickstart" subtitle="En 30 segundos hacés tu primera llamada.">
              <Step n={1} title="Conseguí tu API key">
                <p className="text-sm text-fg-muted">
                  Generala desde{" "}
                  <Link href="/client/api-keys"
                        className="text-primary hover:underline">/client/api-keys</Link>.
                  Empezá con scope <code className="px-1 py-0.5 bg-surface rounded text-[11px]">sandbox</code>.
                </p>
              </Step>
              <Step n={2} title="Hacé tu primera llamada">
                <CodeTabs tabs={[
                  { id: "curl", label: "curl", lang: "bash", code: QUICKSTART_CURL },
                  { id: "js",   label: "JavaScript", lang: "ts", code: QUICKSTART_JS },
                  { id: "py",   label: "Python",     lang: "python", code: QUICKSTART_PY },
                ]} testid="quickstart-call" />
              </Step>
              <Step n={3} title="Escuchá webhooks">
                <p className="text-sm text-fg-muted mb-2">
                  Registrá un endpoint en{" "}
                  <Link href="/client/webhooks" className="text-primary hover:underline">
                    /client/webhooks
                  </Link> y verificá la firma HMAC con el secret que te damos.
                </p>
                <CodeBlock code={HMAC_VERIFY} lang="js" testid="quickstart-verify" />
              </Step>
            </Section>
          )}

          {section === "auth" && (
            <Section title="Authentication" subtitle="Bearer token + idempotency.">
              <p className="text-sm text-fg-muted">
                Todas las requests llevan tu API key en el header{" "}
                <code className="px-1 py-0.5 bg-surface rounded text-[11px]">Authorization</code>.
                Para POSTs idempotentes, agregá <code className="px-1 py-0.5 bg-surface rounded text-[11px]">Idempotency-Key</code>{" "}
                con un UUID v4.
              </p>
              <CodeTabs tabs={AUTH_TABS} testid="auth-headers" />
              <div className="prosper-card p-4 border-warning/30 bg-warning/5">
                <div className="text-[10px] font-mono uppercase tracking-wider text-warning mb-1">
                  Rate limits
                </div>
                <p className="text-xs text-fg-muted">
                  Sandbox: <strong>100 req/min</strong>. Production: <strong>1000 req/min</strong>.
                  Excederlos devuelve <code>429</code> con header <code>Retry-After</code>.
                </p>
              </div>
            </Section>
          )}

          {section === "endpoints" && (
            <Section title="Endpoints reference">
              {ENDPOINT_LIST.map((e) => (
                <div key={e.path} className="prosper-card p-5"
                     data-testid={`endpoint-${e.path.replace(/[/{}]/g, "_")}`}>
                  <div className="flex items-center gap-2 mb-1">
                    <Badge color={methodColor(e.method)}>{e.method}</Badge>
                    <code className="font-mono text-sm text-fg">{e.path}</code>
                  </div>
                  <p className="text-xs text-fg-muted mb-3">{e.desc}</p>
                  <CodeTabs tabs={e.tabs} />
                </div>
              ))}
            </Section>
          )}

          {section === "webhooks" && (
            <Section title="Webhooks" subtitle="HTTP push events firmados con HMAC SHA-256.">
              <div className="prosper-card p-5">
                <div className="text-xs font-display font-semibold mb-2">Events disponibles</div>
                <div className="flex flex-wrap gap-1.5">
                  {["onramp.confirmed", "onramp.failed", "offramp.completed", "offramp.failed",
                    "subscribe.confirmed", "redeem.confirmed", "position.matured",
                    "kyc.approved", "kyc.rejected", "alert.critical"].map((e) => (
                    <span key={e} className="text-[11px] font-mono px-2 py-0.5 rounded
                                              bg-bg-muted text-fg-muted border border-border">
                      {e}
                    </span>
                  ))}
                </div>
              </div>
              <Step n={1} title="Verificá la firma HMAC">
                <CodeBlock code={HMAC_VERIFY} lang="js" testid="webhook-verify" />
                <p className="text-[11px] text-fg-subtle mt-2">
                  Header: <code>X-Prosper-Signature</code> · Algoritmo: <code>sha256</code>
                </p>
              </Step>
              <Step n={2} title="Retry policy">
                <p className="text-sm text-fg-muted">
                  Si tu endpoint devuelve 5xx, reintentamos con backoff exponencial:{" "}
                  <code>1m, 5m, 15m, 1h, 6h, 24h</code>. Después de 6 fallos consecutivos,
                  el endpoint pasa a status <code>failing</code> y te avisamos por email.
                </p>
              </Step>
            </Section>
          )}

          {section === "sdks" && (
            <Section title="SDKs">
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                <div className="prosper-card p-5">
                  <div className="font-display font-bold text-fg flex items-center gap-2">
                    <Zap size={14} className="text-primary"/> JavaScript SDK
                  </div>
                  <p className="text-xs text-fg-muted mt-1 mb-3">
                    TypeScript-first. Node + browser. Soporta widget React.
                  </p>
                  <CodeBlock code="npm install @prosper/sdk" lang="bash" />
                  <Link href="/client/sdk"
                        className="text-[11px] font-mono uppercase tracking-wider
                                   text-primary hover:underline mt-3 inline-block">
                    Ver guía completa →
                  </Link>
                </div>
                <div className="prosper-card p-5">
                  <div className="font-display font-bold text-fg flex items-center gap-2">
                    <Zap size={14} className="text-primary"/> Python SDK
                  </div>
                  <p className="text-xs text-fg-muted mt-1 mb-3">
                    Sync + async. Type hints completos.
                  </p>
                  <CodeBlock code="pip install prosper-sdk" lang="bash" />
                </div>
              </div>
            </Section>
          )}

          {section === "errors" && (
            <Section title="Errors" subtitle="Códigos consistentes + request_id para soporte.">
              <p className="text-sm text-fg-muted">
                Todos los errores devuelven JSON con esta forma:
              </p>
              <CodeBlock code={ERROR_FMT} lang="json" testid="error-format" />
              <div className="text-xs space-y-1.5">
                <ErrRow code="400" name="bad_request">Validación falló. Detalle en <code>detail</code>.</ErrRow>
                <ErrRow code="401" name="unauthorized">API key inválida o revocada.</ErrRow>
                <ErrRow code="403" name="forbidden">KYB pending, org paused, o role insuficiente.</ErrRow>
                <ErrRow code="404" name="not_found">El recurso no existe en tu org.</ErrRow>
                <ErrRow code="429" name="rate_limited">Excediste el rate limit. Mirá <code>Retry-After</code>.</ErrRow>
                <ErrRow code="502" name="upstream_failed">Alfred o Prosper Stellar fallaron. Reintentá.</ErrRow>
              </div>
            </Section>
          )}
        </article>
      </div>
    </div>
  );
}

function Section({ title, subtitle, children }:
  { title: string; subtitle?: string; children: React.ReactNode }) {
  return (
    <section className="space-y-4">
      <header>
        <h2 className="font-display font-bold text-2xl text-fg tracking-tight">{title}</h2>
        {subtitle && <p className="text-sm text-fg-muted mt-1">{subtitle}</p>}
      </header>
      {children}
    </section>
  );
}

function Step({ n, title, children }:
  { n: number; title: string; children: React.ReactNode }) {
  return (
    <div className="flex gap-4">
      <div className="shrink-0 h-7 w-7 rounded-full bg-primary text-white flex items-center justify-center
                       font-mono text-xs font-bold">{n}</div>
      <div className="flex-1">
        <h3 className="text-sm font-display font-bold text-fg mb-1.5">{title}</h3>
        {children}
      </div>
    </div>
  );
}

function Badge({ children, color }: { children: React.ReactNode; color: string }) {
  return (
    <span className={`text-[10px] font-mono font-bold px-1.5 py-0.5 rounded ${color}`}>
      {children}
    </span>
  );
}

function methodColor(method: string) {
  switch (method) {
    case "POST":   return "bg-success/15 text-success";
    case "GET":    return "bg-primary/15 text-primary";
    case "DELETE": return "bg-danger/15 text-danger";
    case "PATCH":  return "bg-warning/15 text-warning";
    default:       return "bg-bg-muted text-fg-muted";
  }
}

function ErrRow({ code, name, children }:
  { code: string; name: string; children: React.ReactNode }) {
  return (
    <div className="flex items-start gap-2 py-1 border-b border-border/40 last:border-0">
      <code className="px-1.5 py-0.5 bg-bg-muted rounded text-[10px] font-mono text-fg shrink-0">
        {code}
      </code>
      <code className="text-[10px] font-mono text-fg-subtle shrink-0">{name}</code>
      <span className="text-fg-muted flex-1">{children}</span>
    </div>
  );
}
