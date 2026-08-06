"use client";
import Link from "next/link";
import { Package, Github, Download, Zap } from "lucide-react";
import { PageHeader } from "@prosper/ui";
import { CodeBlock } from "@/components/CodeBlock";

const JS_INIT = `import { Prosper } from '@prosper/sdk';

const prosper = new Prosper({
  apiKey: process.env.PROSPER_API_KEY!,
  env: 'sandbox',  // 'production' cuando estés listo
});`;

const JS_FLOW = `// Onramp end-to-end con auto-buy en Prosper
const quote = await prosper.onramp.quote({
  sourceCurrency: 'ARS',
  sourceAmount: 100_000,
});

const order = await prosper.onramp.create({
  quoteId: quote.quoteId,
  sourceCurrency: 'ARS',
  sourceAmount: 100_000,
  paymentMethod: 'transfer',
});

// Redirigí al usuario a Alfred:
window.location.href = order.checkoutUrl;

// Al volver, vas a ver una posición Prosper activa.`;

const PY_INIT = `from prosper_sdk import Prosper

client = Prosper(
    api_key=os.environ["PROSPER_API_KEY"],
    env="sandbox",
)`;

const PY_FLOW = `quote = client.onramp.quote(
    source_currency="ARS",
    source_amount=100_000,
)

order = client.onramp.create(
    quote_id=quote.quote_id,
    source_currency="ARS",
    source_amount=100_000,
    payment_method="transfer",
)

print(f"Redirigir usuario a: {order.checkout_url}")`;

const POSTMAN_COLLECTION = {
  info: {
    name: "Prosper API",
    description: "Endpoints públicos del portal cliente Prosper.",
    schema: "https://schema.getpostman.com/json/collection/v2.1.0/collection.json",
  },
  auth: { type: "bearer", bearer: [{ key: "token", value: "{{api_key}}" }] },
  variable: [
    { key: "base_url", value: "https://api.prosper.foundation" },
    { key: "api_key",  value: "pk_sandbox_REPLACE_ME" },
  ],
  item: [
    {
      name: "Onramp · quote",
      request: { method: "POST", url: "{{base_url}}/v1/client/onramp/quote",
        body: { mode: "raw",
          raw: JSON.stringify({ source_currency: "ARS", source_amount: 100000 }, null, 2),
          options: { raw: { language: "json" } } } },
    },
    {
      name: "Onramp · create order",
      request: { method: "POST", url: "{{base_url}}/v1/client/onramp/orders",
        body: { mode: "raw",
          raw: JSON.stringify({ quote_id: "qt_...", source_currency: "ARS",
                                  source_amount: 100000, payment_method: "transfer" }, null, 2) } },
    },
    {
      name: "Positions · list",
      request: { method: "GET", url: "{{base_url}}/v1/client/positions" },
    },
    {
      name: "Positions · redeem",
      request: { method: "POST", url: "{{base_url}}/v1/client/positions/:id/redeem" },
    },
    {
      name: "Balances",
      request: { method: "GET", url: "{{base_url}}/v1/client/balances" },
    },
  ],
};

export default function SdkPage() {
  const downloadPostman = () => {
    const blob = new Blob([JSON.stringify(POSTMAN_COLLECTION, null, 2)],
                          { type: "application/json" });
    const url  = URL.createObjectURL(blob);
    const a    = document.createElement("a");
    a.href     = url;
    a.download = "prosper-postman-collection.json";
    document.body.appendChild(a); a.click(); a.remove();
    URL.revokeObjectURL(url);
  };

  return (
    <div data-testid="sdk-page">
      <PageHeader
        breadcrumbs={[{ label: "Inicio", href: "/client" }, { label: "SDK" }]}
        title="Integrá Prosper en minutos"
        subtitle="SDKs oficiales para JavaScript y Python + Postman collection."
      />

      <div className="grid grid-cols-1 md:grid-cols-2 gap-5 mb-6">
        <SdkCard
          title="JavaScript / TypeScript"
          install="npm install @prosper/sdk"
          init={JS_INIT}
          flow={JS_FLOW}
          testid="sdk-js"
        />
        <SdkCard
          title="Python"
          install="pip install prosper-sdk"
          init={PY_INIT}
          flow={PY_FLOW}
          lang="python"
          testid="sdk-py"
        />
      </div>

      <div className="prosper-card p-5 flex items-center gap-4" data-testid="sdk-postman">
        <div className="h-12 w-12 rounded-full bg-warning/10 text-warning flex items-center justify-center">
          <Download size={22}/>
        </div>
        <div className="flex-1">
          <h3 className="font-display font-bold text-fg">Postman collection</h3>
          <p className="text-xs text-fg-muted">
            Importá los endpoints en Postman para explorar la API sin escribir código.
          </p>
        </div>
        <button onClick={downloadPostman}
          className="prosper-btn-primary h-10 px-4 text-xs gap-1.5"
          data-testid="sdk-postman-download">
          <Download size={13}/> Descargar JSON
        </button>
      </div>

      <p className="text-xs text-fg-subtle mt-5 text-center">
        ¿Falta algo? Escribinos a{" "}
        <a className="text-primary hover:underline"
           href="mailto:developers@prosper.foundation">developers@prosper.foundation</a>.
      </p>
    </div>
  );
}

function SdkCard({ title, install, init, flow, lang = "ts", testid }:
  { title: string; install: string; init: string; flow: string;
    lang?: string; testid: string }) {
  return (
    <div className="prosper-card p-5 space-y-3" data-testid={testid}>
      <div className="flex items-center gap-2">
        <Package size={16} className="text-primary"/>
        <h3 className="font-display font-bold text-fg">{title}</h3>
      </div>
      <CodeBlock code={install} lang="bash" />
      <div>
        <div className="text-[10px] font-mono uppercase tracking-wider text-fg-subtle mb-1">
          Inicialización
        </div>
        <CodeBlock code={init} lang={lang} />
      </div>
      <div>
        <div className="text-[10px] font-mono uppercase tracking-wider text-fg-subtle mb-1">
          Flow onramp + auto-buy
        </div>
        <CodeBlock code={flow} lang={lang} />
      </div>
      <Link
        href="/client/developers"
        className="text-[11px] font-mono uppercase tracking-wider text-primary hover:underline
                   inline-flex items-center gap-1">
        <Zap size={11}/> Ver doc completa →
      </Link>
      <a
        href="https://github.com/prosper-foundation/sdk"
        target="_blank" rel="noopener noreferrer"
        className="text-[11px] font-mono uppercase tracking-wider text-fg-subtle
                   hover:text-fg inline-flex items-center gap-1 ml-3">
        <Github size={11}/> GitHub
      </a>
    </div>
  );
}
