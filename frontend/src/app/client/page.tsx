import { PageHeader, KpiCard } from "@prosper/ui";
import { RefreshButton } from "@/components/PageActions";

export default function ClientHomePage() {
  return (
    <div>
      <PageHeader
        breadcrumbs={[{ label: "Client", href: "/client" }, { label: "Dashboard" }]}
        kicker="Phase 0 · Client portal"
        title="Bienvenido a Prosper"
        subtitle="Tu portal de inversión en yield tokenizado regulado."
        actions={<RefreshButton />}
      />

      <div className="grid grid-cols-1 md:grid-cols-3 gap-4 mb-8">
        <KpiCard label="Saldo disponible"       value="—" hint="Disponible en próximas fases" />
        <KpiCard label="Total invertido"        value="—" hint="Disponible en próximas fases" />
        <KpiCard label="Rendimiento acumulado"  value="—" hint="Disponible en próximas fases" />
      </div>

      <div className="prosper-card p-6">
        <div className="text-[10px] font-mono uppercase tracking-[0.18em] text-fg-subtle mb-2">
          Hola
        </div>
        <h2 className="font-display font-bold text-xl text-fg mb-3">
          Tu cuenta está lista
        </h2>
        <p className="text-sm text-fg-muted">
          Estamos terminando de configurar las capacidades de carga, inversión y
          rendimientos. Te avisaremos por email cuando estén disponibles. Por ahora
          podés ver el shell del portal y la navegación.
        </p>
      </div>
    </div>
  );
}
