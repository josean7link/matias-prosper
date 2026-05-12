import { PageHeader, ComingSoon } from "@/components/Page";
export default function AdminClientsPage() {
  return (<div>
    <PageHeader kicker="Admin" title="Clientes" subtitle="Organizaciones, usuarios, API keys y webhooks." />
    <ComingSoon what="Clientes" />
  </div>);
}
