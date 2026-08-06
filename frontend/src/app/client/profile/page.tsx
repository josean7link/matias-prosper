"use client";
import { useState } from "react";
import { useTranslations } from "next-intl";
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

export default function ClientProfilePage() {
  const t  = useTranslations("profile_page");
  const tc = useTranslations("common");
  const { data: meData, mutate: mutateMe } = useClientMe();
  const { data: profile, isLoading, mutate: mutateProfile } = useProfile();
  const [tab, setTab] = useState<TabKey>("account");

  const refresh = () => { mutateProfile(); mutateMe(); };

  const TABS: Array<{ key: TabKey; label: string; icon: typeof UserCircle }> = [
    { key: "account",       label: t("tab_account"),        icon: UserCircle },
    { key: "security",      label: t("tab_security"),       icon: ShieldCheck },
    { key: "sessions",      label: t("tab_sessions"),       icon: Monitor },
    { key: "notifications", label: t("tab_notifications"),  icon: Bell },
    { key: "danger",        label: t("tab_danger"),         icon: AlertOctagon },
  ];

  return (
    <div data-testid="client-profile">
      <PageHeader
        breadcrumbs={[{ label: tc("home"), href: "/client" }, { label: t("breadcrumb") }]}
        title={t("title")}
        subtitle={t("subtitle")}
        actions={<RefreshButton onClick={refresh} />}
      />

      <div className="border-b border-border mb-6 overflow-x-auto"
           data-testid="profile-tabs">
        <nav className="flex gap-1 min-w-max">
          {TABS.map((tdef) => {
            const Icon = tdef.icon;
            const active = tab === tdef.key;
            return (
              <button key={tdef.key} onClick={() => setTab(tdef.key)}
                className={`relative h-11 px-4 text-sm font-display font-semibold transition-colors
                            flex items-center gap-1.5 whitespace-nowrap
                            ${active
                              ? "text-primary"
                              : "text-fg-muted hover:text-fg"}`}
                data-testid={`profile-tab-${tdef.key}`}
                aria-current={active ? "page" : undefined}>
                <Icon size={14}/> {tdef.label}
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
