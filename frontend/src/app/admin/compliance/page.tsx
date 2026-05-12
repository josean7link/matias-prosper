import { PageHeader, ComingSoon } from "@/components/Page";
export default function AdminCompliancePage() {
  return (<div>
    <PageHeader kicker="Admin" title="Compliance" subtitle="KYB / KYC, sanciones, PEP, travel-rule, audit log." />
    <ComingSoon what="Compliance" />
  </div>);
}
