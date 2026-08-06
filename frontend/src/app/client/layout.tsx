import { AppShell } from "@/components/AppShell";
import { ClientGateBanner } from "@/components/ClientGateBanner";
import ClientPortfolioPoll from "@/components/client/ClientPortfolioPoll";

export default function ClientLayout({ children }: { children: React.ReactNode }) {
  return (
    <AppShell surface="client">
      <ClientPortfolioPoll />
      <ClientGateBanner />
      <div>{children}</div>
    </AppShell>
  );
}
