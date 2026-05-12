import { PageHeader } from "@prosper/ui";
import { ComingSoon } from "@/components/Page";
import { RefreshButton } from "@/components/PageActions";

export default function Page() {
  return (
    <div>
      <PageHeader
        breadcrumbs={[
          { label: "Client", href: "/client" },
          { label: "Cargar / Retirar" },
        ]}
        kicker="Client"
        title="Cargar / Retirar"
        subtitle="Mové USDC dentro y fuera de tu cuenta Prosper."
        actions={<RefreshButton />}
      />
      <ComingSoon what="Cargar / Retirar" />
    </div>
  );
}
