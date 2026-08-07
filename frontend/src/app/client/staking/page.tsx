"use client";
/**
 * Staking — portal cliente (/client/staking).
 * Mismo módulo que el admin (directiva del usuario: mismo acceso para
 * cualquier cliente, en especial client_admin), sin widgets de tesorería.
 * i18n: namespace `staking` (next-intl, EN/ES).
 */
import { Coins } from "lucide-react";
import { useTranslations } from "next-intl";
import { PageHeader } from "@prosper/ui";
import { StakingTabs } from "@/components/staking/StakingTabs";

export default function ClientStakingPage() {
  const t = useTranslations("staking.page");
  return (
    <div data-testid="client-staking-page">
      <PageHeader
        breadcrumbs={[{ label: t("client_breadcrumb_home"), href: "/client" }, { label: t("breadcrumb") }]}
        kicker={t("client_kicker")}
        title={t("title")}
        subtitle={t("client_subtitle")}
        actions={<Coins size={20} className="text-[rgb(var(--fg-muted))]" />}
      />
      <StakingTabs base="/v1/client/staking" allowManualCashin={false} />
    </div>
  );
}
