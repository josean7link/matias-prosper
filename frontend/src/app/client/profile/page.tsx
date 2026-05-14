"use client";
import { useState } from "react";
import {
  UserCircle, ShieldCheck, Monitor, Bell, AlertOctagon,
} from "lucide-react";
import { PageHeader } from "@prosper/ui";
import { RefreshButton } from "@/components/PageActions";
import { useClientMe } from "@/lib/client-portal";
import { useProfile } from "@/lib/profile";
import { AccountTab } from "@/components/client/profile/AccountTab";
import { SecurityTab } from "@/components/client/profile/SecurityTab";
import { SessionsTab } from "@/components/client/profile/SessionsTab";
import { NotificationsTab } from "@/components/client/profile/NotificationsTab";
import { DangerTab } from "@/components/client/profile/DangerTab";

type TabKey = "account" | "security" | "sessions" | "notifications" | "danger";

const TABS: Array<{ key: TabKey; label: string; icon: typeof UserCircle }> = [
  { key: "account",       label: "Cuenta",         icon: UserCircle },
  { key: "security",      label: "Seguridad",      icon: ShieldCheck },
  { key: "sessions",      label: "Sesiones",       icon: Monitor },
  { key: "notifications", label: "Notificaciones", icon: Bell },
  { key: "danger",        label: "Eliminar cuenta", icon: AlertOctagon },
];

export default function ClientProfilePage() {
  const { data: meData, mutate: mutateMe } = useClientMe();
  const { data: profile, isLoading, mutate: mutateProfile } = useProfile();
  const [tab, setTab] = useState<TabKey>("account");

  const refresh = () => { mutateProfile(); mutateMe(); };

  return (
    <div data-testid="client-profile">
      <PageHeader
        breadcrumbs={[{ label: "Client", href: "/client" }, { label: "Perfil" }]}
        kicker="Client · Sprint 11B"
        title="Perfil y seguridad"
        subtitle="Datos personales, MFA, sesiones activas, notificaciones y gestión de cuenta."
        actions={<RefreshButton onClick={refresh} />}
      />

      {/* Tab bar */}
      <div className="border-b border-border mb-6 overflow-x-auto"
           data-testid="profile-tabs">
        <nav className="flex gap-1 min-w-max">
          {TABS.map((t) => {
            const Icon = t.icon;
            const active = tab === t.key;
            return (
              <button key={t.key} onClick={() => setTab(t.key)}
                className={`relative h-11 px-4 text-sm font-display font-semibold transition-colors
                            flex items-center gap-1.5 whitespace-nowrap
                            ${active
                              ? "text-primary"
                              : "text-fg-muted hover:text-fg"}`}
                data-testid={`profile-tab-${t.key}`}
                aria-current={active ? "page" : undefined}>
                <Icon size={14}/> {t.label}
                {active && (
                  <span className="absolute left-2 right-2 -bottom-px h-0.5 bg-primary rounded-t" />
                )}
              </button>
            );
          })}
        </nav>
      </div>

      {isLoading || !profile ? (
        <div className="prosper-card p-8 animate-pulse h-40" />
      ) : (
        <>
          {tab === "account" && (
            <AccountTab
              profile={profile}
              orgInfo={meData?.org ?? null}
              onUpdated={refresh}
            />
          )}
          {tab === "security"      && <SecurityTab profile={profile} onUpdated={refresh} />}
          {tab === "sessions"      && <SessionsTab />}
          {tab === "notifications" && <NotificationsTab profile={profile} onUpdated={refresh} />}
          {tab === "danger"        && <DangerTab profile={profile} onUpdated={refresh} />}
        </>
      )}
    </div>
  );
}
