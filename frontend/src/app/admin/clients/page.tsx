import { PageHeader } from "@prosper/ui";
import { ComingSoon } from "@/components/Page";
import { RefreshButton } from "@/components/PageActions";

export default function Page() {
  return (
    <div>
      <PageHeader
        breadcrumbs={[
          { label: "Admin", href: "/admin" },
          { label: "Clientes" },
        ]}
        kicker="Admin"
        title="Clientes"
        subtitle="Organizaciones, usuarios, API keys y webhooks."
        actions={<RefreshButton />}
      />
      <ComingSoon what="Clientes" />
    </div>
  );
}
