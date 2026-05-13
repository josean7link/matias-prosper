import { AppShell } from "@/components/AppShell";
import { ClientGateBanner } from "@/components/ClientGateBanner";

export default function ClientLayout({ children }: { children: React.ReactNode }) {
  return (
    <AppShell surface="client">
      <ClientGateBanner />
      <div>{children}</div>
    </AppShell>
  );
}
