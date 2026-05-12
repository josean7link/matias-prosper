import { PageHeader } from "@prosper/ui";
import { ComingSoon } from "@/components/Page";
import { RefreshButton } from "@/components/PageActions";

export default function Page() {
  return (
    <div>
      <PageHeader
        breadcrumbs={[
          { label: "Admin", href: "/admin" },
          { label: "Compliance" },
        ]}
        kicker="Admin"
        title="Compliance"
        subtitle="KYB / KYC, sanciones, PEP, travel-rule y audit log."
        actions={<RefreshButton />}
      />
      <ComingSoon what="Compliance" />
    </div>
  );
}
