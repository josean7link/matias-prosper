import { AppShell } from "@/components/AppShell";
import { EnvProvider, type Env } from "@/contexts/EnvContext";
import { cookies } from "next/headers";

export default function AdminLayout({ children }: { children: React.ReactNode }) {
  // Read env from cookies on the server so the first paint already shows the
  // correct sidebar tone + sandbox banner (no flash of production-style UI).
  const c = cookies().get("prosper_env")?.value;
  const initial: Env = c === "sandbox" ? "sandbox" : "production";
  return (
    <EnvProvider initial={initial}>
      <AppShell surface="admin">{children}</AppShell>
    </EnvProvider>
  );
}
