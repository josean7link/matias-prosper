import { PageHeader } from "@prosper/ui";
import { ComingSoon } from "@/components/Page";
import { RefreshButton } from "@/components/PageActions";

export default function Page() {
  return (
    <div>
      <PageHeader
        breadcrumbs={[
          { label: "Admin", href: "/admin" },
          { label: "Negocio" },
        ]}
        kicker="Admin"
        title="Negocio"
        subtitle="AUM, TVL, utilización, performance y APYs por producto."
        actions={<RefreshButton />}
      />
      <ComingSoon what="Negocio" />
    </div>
  );
}
