import { PageHeader } from "@prosper/ui";
import { ComingSoon } from "@/components/Page";

export default function Page() {
  return (
    <div data-testid="invest-page">
      <PageHeader
        breadcrumbs={[{ label: "Client", href: "/client" }, { label: "Inversiones" }]}
        kicker="Phase 9 · Próximamente"
        title="Inversiones"
        subtitle="Compra de Prosper Yield Token y gestión de posiciones."
      />
      <ComingSoon what="Inversiones · Comprar Prosper Yield Token" />
    </div>
  );
}
