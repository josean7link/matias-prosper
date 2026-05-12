import { PageHeader } from "@prosper/ui";
import { ComingSoon } from "@/components/Page";
import { RefreshButton } from "@/components/PageActions";

export default function Page() {
  return (
    <div>
      <PageHeader
        breadcrumbs={[
          { label: "Client", href: "/client" },
          { label: "Inversiones" },
        ]}
        kicker="Client"
        title="Inversiones"
        subtitle="Tus posiciones abiertas y su estado en tiempo real."
        actions={<RefreshButton />}
      />
      <ComingSoon what="Inversiones" />
    </div>
  );
}
