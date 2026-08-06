"use client";
import { toast } from "sonner";
import {
  Banknote, Layers, CreditCard, ShoppingBag, Repeat, Bell, Check,
} from "lucide-react";
import { PageHeader } from "@prosper/ui";
import { api } from "@/lib/api";
import { useFeatureInterest } from "@/lib/developer";

const FEATURES = [
  {
    id: "lending",
    title: "Lending",
    icon: Banknote,
    eta: "Q3 2026",
    pitch: "Pedí préstamos en USDC con tus tokens Prosper como colateral. Mantén tu yield y obtené liquidez al instante.",
    accent: "from-success/15 to-success/0",
  },
  {
    id: "multi_asset",
    title: "Multi-asset",
    icon: Layers,
    eta: "Q4 2026",
    pitch: "Tokenizados de US Treasuries, MBS LATAM y fondos soberanos. Diversificá tu yield sin salir de la app.",
    accent: "from-primary/15 to-primary/0",
  },
  {
    id: "card",
    title: "Tarjeta Prosper",
    icon: CreditCard,
    eta: "2027",
    pitch: "Gastá tus rendimientos directamente con una tarjeta de débito Mastercard. Auto-convert USDC → fiat al swipe.",
    accent: "from-warning/15 to-warning/0",
  },
  {
    id: "marketplace",
    title: "Marketplace",
    icon: ShoppingBag,
    eta: "2027",
    pitch: "Mercado secundario para transferir tokens entre clientes Prosper sin pasar por offramp + onramp.",
    accent: "from-danger/15 to-danger/0",
  },
  {
    id: "yield_aggregator",
    title: "Yield aggregator",
    icon: Repeat,
    eta: "2027",
    pitch: "Rebalancing automático entre productos según APR objetivo. Vos definís el riesgo y nosotros optimizamos.",
    accent: "from-success/15 to-primary/0",
  },
] as const;

export default function ComingSoonPage() {
  const { data, mutate } = useFeatureInterest();
  const registered = new Set(data?.registered ?? []);

  const onRegister = async (id: string) => {
    if (registered.has(id)) {
      toast("Ya estás registrado para esta feature");
      return;
    }
    try {
      await api(`/v1/client/feature-interest`, {
        method: "POST", body: JSON.stringify({ feature: id }),
      });
      toast.success("Te avisaremos por email cuando esté disponible.");
      mutate();
    } catch (err) {
      toast.error((err as Error).message);
    }
  };

  return (
    <div data-testid="coming-soon-page">
      <PageHeader
        breadcrumbs={[{ label: "Inicio", href: "/client" }, { label: "Próximamente" }]}
        kicker="Roadmap · Q3 2026 →"
        title="Lo que viene en Prosper"
        subtitle="Activá notificaciones para enterarte primero cuando lancemos cada producto."
      />

      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-4">
        {FEATURES.map((f) => {
          const Icon = f.icon;
          const isRegistered = registered.has(f.id);
          return (
            <div key={f.id}
                 className="prosper-card relative p-5 overflow-hidden flex flex-col"
                 data-testid={`feature-${f.id}`}>
              <div className={`absolute inset-0 bg-gradient-to-br ${f.accent} pointer-events-none`} />
              <div className="relative flex-1 flex flex-col">
                <div className="flex items-center justify-between mb-3">
                  <div className="h-10 w-10 rounded-full bg-fg/10 text-fg flex items-center justify-center">
                    <Icon size={18} />
                  </div>
                  <span className="text-[10px] font-mono uppercase tracking-[0.18em]
                                    text-fg-subtle">
                    {f.eta}
                  </span>
                </div>
                <h3 className="font-display font-bold text-lg text-fg tracking-tight">
                  {f.title}
                </h3>
                <p className="text-xs text-fg-muted mt-1.5 flex-1">{f.pitch}</p>

                <button
                  onClick={() => onRegister(f.id)}
                  disabled={isRegistered}
                  className={`mt-4 h-10 px-3 rounded text-xs font-display font-semibold
                              inline-flex items-center justify-center gap-1.5 transition-colors
                              ${isRegistered
                                ? "bg-success/10 text-success cursor-default"
                                : "bg-fg text-bg hover:opacity-90"}`}
                  data-testid={`feature-cta-${f.id}`}>
                  {isRegistered ? (
                    <><Check size={12}/> Anotado</>
                  ) : (
                    <><Bell size={12}/> Notificame</>
                  )}
                </button>
              </div>
            </div>
          );
        })}
      </div>

      <div className="mt-8 prosper-card p-5 text-center">
        <p className="text-xs text-fg-muted">
          ¿Tenés ideas para Prosper? Escribinos a{" "}
          <a href="mailto:product@prosper.foundation"
              className="text-primary hover:underline">
            product@prosper.foundation
          </a>.
        </p>
      </div>
    </div>
  );
}
