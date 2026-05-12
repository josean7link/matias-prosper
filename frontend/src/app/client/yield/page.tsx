import { PageHeader } from "@prosper/ui";
import { ComingSoon } from "@/components/Page";
import { RefreshButton } from "@/components/PageActions";

export default function Page() {
  return (
    <div>
      <PageHeader
        breadcrumbs={[
          { label: "Client", href: "/client" },
          { label: "Rendimientos" },
        ]}
        kicker="Client"
        title="Rendimientos"
        subtitle="Yield acumulado, APR vigente y proyección por producto."
        actions={<RefreshButton />}
      />
      <ComingSoon what="Rendimientos" />
    </div>
  );
}
