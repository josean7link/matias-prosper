import { PageHeader, ComingSoon } from "@/components/Page";

export default function AdminOperationsPage() {
  return (
    <div>
      <PageHeader kicker="Admin" title="Operaciones" subtitle="Cola two-signer, mints, redenciones, reconciliación." />
      <ComingSoon what="Operaciones" />
    </div>
  );
}
