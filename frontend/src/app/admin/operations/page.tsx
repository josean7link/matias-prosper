import { PageHeader } from "@prosper/ui";
import { ComingSoon } from "@/components/Page";
import { RefreshButton } from "@/components/PageActions";

export default function Page() {
  return (
    <div>
      <PageHeader
        breadcrumbs={[
          { label: "Admin", href: "/admin" },
          { label: "Operaciones" },
        ]}
        kicker="Admin"
        title="Operaciones"
        subtitle="Cola two-signer, mints, redenciones, reconciliación."
        actions={<RefreshButton />}
      />
      <ComingSoon what="Operaciones" />
    </div>
  );
}
