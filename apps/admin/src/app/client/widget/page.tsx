"use client";
import { useState, useEffect } from "react";
import { toast } from "sonner";
import { Sparkles, Wand2, Eye } from "lucide-react";
import { PageHeader, Badge } from "@prosper/ui";
import { CodeBlock, CodeTabs } from "@/components/CodeBlock";
import { api } from "@/lib/api";
import { useWidgetConfig, type WidgetConfig } from "@/lib/developer";
import { useProducts } from "@/lib/invest";

const DEFAULTS: WidgetConfig = {
  theme: "light",
  color: "#2B6BFF",
  locale: "es",
  amount: undefined,
  product_id: "liquid_v1",
  show_branding: true,
};

export default function WidgetBuilderPage() {
  const { data: cfgData, mutate } = useWidgetConfig();
  const { data: prodData } = useProducts();
  const products = prodData?.items || [];

  const [cfg, setCfg] = useState<WidgetConfig>(DEFAULTS);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (cfgData?.config) setCfg({ ...DEFAULTS, ...cfgData.config });
  }, [cfgData]);

  const save = async () => {
    setSaving(true);
    try {
      await api("/v1/client/widget/config", {
        method: "PUT", body: JSON.stringify(cfg),
      });
      toast.success("Configuración guardada");
      mutate();
    } catch (err) {
      toast.error((err as Error).message);
    } finally {
      setSaving(false);
    }
  };

  const apiKey = "pk_sandbox_REPLACE_ME";

  const htmlSnippet = `<script src="https://widget.prosper.foundation/v1/widget.js"></script>
<div id="prosper-widget"
     data-api-key="${apiKey}"
     data-theme="${cfg.theme}"
     data-color="${cfg.color}"
     data-locale="${cfg.locale}"
     data-amount="${cfg.amount ?? ""}"
     data-product="${cfg.product_id}"
     data-show-branding="${cfg.show_branding}">
</div>`;

  const reactSnippet = `import { ProsperWidget } from '@prosper/widget-react';

<ProsperWidget
  apiKey="${apiKey}"
  config={${JSON.stringify({
    theme: cfg.theme,
    color: cfg.color,
    locale: cfg.locale,
    amount: cfg.amount,
    productId: cfg.product_id,
    showBranding: cfg.show_branding,
  }, null, 2).replace(/\n/g, "\n  ")}}
/>`;

  return (
    <div data-testid="widget-builder">
      <PageHeader
        breadcrumbs={[{ label: "Inicio", href: "/client" }, { label: "Widget" }]}
        title="Widget builder"
        subtitle="Embebé el flow Prosper en tu sitio. Configurá el look y copiá el snippet."
        actions={
          <button onClick={save} disabled={saving}
            className="prosper-btn-primary h-9 px-3 text-xs gap-1.5"
            data-testid="widget-save">
            <Wand2 size={13}/> {saving ? "Guardando…" : "Guardar config"}
          </button>
        }
      />

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* LEFT — Config */}
        <div className="space-y-4" data-testid="widget-config">
          <Field label="Tema">
            <div className="grid grid-cols-2 gap-2">
              {(["light", "dark"] as const).map((t) => (
                <button key={t} type="button" onClick={() => setCfg({ ...cfg, theme: t })}
                  className={`p-3 rounded border text-sm font-display font-semibold capitalize
                              ${cfg.theme === t ? "border-primary bg-primary/5 ring-1 ring-primary"
                                                 : "border-border hover:bg-surface-hover"}`}
                  data-testid={`widget-theme-${t}`}>
                  {t}
                </button>
              ))}
            </div>
          </Field>

          <Field label="Color primario">
            <div className="flex items-center gap-3">
              <input type="color" value={cfg.color}
                onChange={(e) => setCfg({ ...cfg, color: e.target.value })}
                className="h-10 w-16 rounded border border-border cursor-pointer"
                data-testid="widget-color" />
              <input value={cfg.color}
                onChange={(e) => setCfg({ ...cfg, color: e.target.value })}
                className="prosper-input flex-1 h-10 text-sm font-mono" />
            </div>
          </Field>

          <Field label="Idioma">
            <div className="grid grid-cols-3 gap-2">
              {(["es", "en", "auto"] as const).map((l) => (
                <button key={l} type="button" onClick={() => setCfg({ ...cfg, locale: l })}
                  className={`py-2 rounded border text-xs font-display font-semibold uppercase
                              ${cfg.locale === l ? "border-primary bg-primary/5 ring-1 ring-primary"
                                                   : "border-border hover:bg-surface-hover"}`}
                  data-testid={`widget-locale-${l}`}>
                  {l}
                </button>
              ))}
            </div>
          </Field>

          <Field label="Monto preset (opcional)">
            <input type="number" value={cfg.amount ?? ""}
              onChange={(e) => setCfg({ ...cfg, amount: e.target.value ? Number(e.target.value) : undefined })}
              placeholder="Permitir al usuario elegir"
              className="prosper-input w-full h-10 text-sm"
              data-testid="widget-amount" />
          </Field>

          <Field label="Producto pre-seleccionado">
            <select value={cfg.product_id}
              onChange={(e) => setCfg({ ...cfg, product_id: e.target.value })}
              className="prosper-input w-full h-10 text-sm"
              data-testid="widget-product">
              {products.map((p) => (
                <option key={p.product_id} value={p.product_id}>
                  {p.name} — APR {(p.apr_bps / 100).toFixed(2)}%
                </option>
              ))}
            </select>
          </Field>

          <Field label="Branding 'Powered by Prosper'">
            <label className="flex items-center gap-2 cursor-pointer">
              <input type="checkbox" checked={cfg.show_branding}
                onChange={(e) => setCfg({ ...cfg, show_branding: e.target.checked })}
                className="h-4 w-4 rounded border-border text-primary"
                data-testid="widget-branding" />
              <span className="text-sm text-fg-muted">
                Mostrar "Powered by Prosper" abajo del widget
              </span>
            </label>
          </Field>
        </div>

        {/* RIGHT — Preview */}
        <div className="lg:sticky lg:top-20 self-start">
          <div className="text-[10px] font-mono uppercase tracking-[0.18em] text-fg-subtle mb-2
                           flex items-center gap-1">
            <Eye size={11}/> Preview en vivo
          </div>
          <WidgetPreview cfg={cfg} orgName={cfgData?.org_name} products={products} />
        </div>
      </div>

      {/* Snippets */}
      <div className="mt-8 space-y-4">
        <h2 className="font-display font-bold text-xl text-fg">Snippet de integración</h2>
        <CodeTabs tabs={[
          { id: "html", label: "HTML", lang: "html", code: htmlSnippet },
          { id: "react", label: "React", lang: "tsx",  code: reactSnippet },
        ]} testid="widget-snippet" />
        <p className="text-xs text-fg-subtle">
          El widget hace onramp + compra automática Prosper en el contexto del usuario final.
          Funciona en cualquier sitio. Carga &lt; 80kb gz.
        </p>
      </div>
    </div>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div>
      <div className="text-[10px] font-mono uppercase tracking-wider text-fg-subtle mb-2">
        {label}
      </div>
      {children}
    </div>
  );
}

function WidgetPreview({ cfg, orgName, products }:
  { cfg: WidgetConfig; orgName?: string;
    products: Array<{ product_id: string; name: string; apr_bps: number }> }) {
  const isDark = cfg.theme === "dark";
  const product = products.find((p) => p.product_id === cfg.product_id);
  return (
    <div className="rounded-xl overflow-hidden border border-border"
         data-testid="widget-preview">
      <div className="px-3 py-2 flex items-center gap-2 bg-bg-muted border-b border-border">
        <span className="h-2.5 w-2.5 rounded-full bg-danger" />
        <span className="h-2.5 w-2.5 rounded-full bg-warning" />
        <span className="h-2.5 w-2.5 rounded-full bg-success" />
        <span className="ml-auto text-[10px] font-mono text-fg-subtle">
          tusitio.com / invertir
        </span>
      </div>
      <div
        className="p-6 transition-colors duration-300"
        style={{
          background: isDark ? "#0B0F19" : "#F8FAFC",
          color:      isDark ? "#E2E8F0" : "#0F172A",
        }}
      >
        <div className="max-w-sm mx-auto rounded-2xl shadow-lg overflow-hidden"
             style={{ background: isDark ? "#111827" : "#FFFFFF",
                       border: `1px solid ${isDark ? "#1F2937" : "#E2E8F0"}` }}>
          <div className="px-5 py-3 flex items-center gap-2 border-b"
               style={{ borderColor: isDark ? "#1F2937" : "#E2E8F0" }}>
            <Sparkles size={14} style={{ color: cfg.color }} />
            <span className="text-xs font-semibold tracking-wider uppercase"
                  style={{ color: cfg.color }}>
              Invertir con Prosper
            </span>
          </div>
          <div className="p-5 space-y-3">
            <div className="text-[10px] uppercase tracking-wider opacity-60">
              {cfg.locale === "en" ? "You're investing" : "Estás invirtiendo"}
            </div>
            <div className="text-3xl font-bold tabular-nums">
              {cfg.amount ? cfg.amount.toLocaleString() : "—"}
              <span className="text-base ml-1 opacity-60">ARS</span>
            </div>
            <div className="rounded-lg p-3 text-xs space-y-1"
                 style={{ background: isDark ? "#0B0F1955" : "#F8FAFC" }}>
              <div className="flex justify-between opacity-80">
                <span>{cfg.locale === "en" ? "Product" : "Producto"}</span>
                <span className="font-mono">{product?.name || cfg.product_id}</span>
              </div>
              <div className="flex justify-between">
                <span>APR</span>
                <span className="font-mono font-bold" style={{ color: cfg.color }}>
                  {product ? (product.apr_bps / 100).toFixed(2) : "—"}%
                </span>
              </div>
            </div>
            <button className="w-full h-10 rounded-lg text-sm font-bold text-white"
                    style={{ background: cfg.color }}>
              {cfg.locale === "en" ? "Continue" : "Continuar"}
            </button>
          </div>
          {cfg.show_branding && (
            <div className="px-5 pb-3 text-[10px] opacity-50 text-center">
              Powered by Prosper · {orgName || "Tu organización"}
            </div>
          )}
        </div>
        <div className="text-center mt-4">
          <Badge tone="info" size="sm">Preview · no funcional</Badge>
        </div>
      </div>
    </div>
  );
}
