import { PageHeader, ComingSoon } from "@/components/Page";
export default function AdminBusinessPage() {
  return (<div>
    <PageHeader kicker="Admin" title="Negocio" subtitle="AUM, TVL, utilización, performance, APYs por producto." />
    <ComingSoon what="Negocio" />
  </div>);
}
