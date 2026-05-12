import { PageHeader } from "@prosper/ui";
import { ComingSoon } from "@/components/Page";
import { RefreshButton } from "@/components/PageActions";

export default function Page() {
  return (
    <div>
      <PageHeader
        breadcrumbs={[
          { label: "Client", href: "/client" },
          { label: "Servicios futuros" },
        ]}
        kicker="Client"
        title="Servicios futuros"
        subtitle="Próximas integraciones y módulos en desarrollo."
        actions={<RefreshButton />}
      />
      <ComingSoon what="Servicios futuros" />
    </div>
  );
}
