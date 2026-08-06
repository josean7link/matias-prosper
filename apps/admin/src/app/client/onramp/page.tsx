"use client";
/**
 * /client/onramp — Add funds hub (P0·#2, Feb 2026).
 */
import Link from "next/link";
import { useTranslations } from "next-intl";
import {
  AlertTriangle, ArrowRight, Banknote,
  Clock, Coins, Sparkles,
} from "lucide-react";
import { PageHeader, Badge } from "@prosper/ui";
import { useClientMe } from "@/lib/client-portal";
import { ArsaAccountCard } from "@/components/client/ArsaAccountCard";

export default function OnrampHubPage() {
  const t  = useTranslations("onramp_hub");
  const tc = useTranslations("common");
  const { data: me } = useClientMe();
  const canOperate = me?.features?.can_operate ?? false;
  const orgId      = me?.org?.org_id;

  return (
    <div data-testid="onramp-hub-page">
      <PageHeader
        breadcrumbs={[{ label: tc("home"), href: "/client" }, { label: t("breadcrumb") }]}
        title={t("title")}
        subtitle={t("subtitle")}
      />

      {!canOperate && <BlockedCard />}

      {canOperate && (
        <>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4 mb-8"
                data-testid="onramp-rails-grid">
            <RailCard
              testid="rail-arsa"
              eyebrow={t("rail_arsa_eyebrow")}
              title={t("rail_arsa_title")}
              desc={t("rail_arsa_desc")}
              icon={<Banknote size={20} />}
              tone="primary"
              href="#cvu-card"
            />
            <RailCard
              testid="rail-usdc"
              eyebrow={t("rail_usdc_eyebrow")}
              title={t("rail_usdc_title")}
              desc={t("rail_usdc_desc")}
              icon={<Coins size={20} />}
              tone="default"
              href="/client/cargar-usdc"
            />
          </div>

          {orgId && (
            <div id="cvu-card" className="scroll-mt-20"
                  data-testid="onramp-arsa-cvu-card">
              <ArsaAccountCard orgId={orgId} />
            </div>
          )}

          {/* Coming soon · international onramp (Alfred) */}
          <div className="prosper-card p-5 mt-2 bg-warning/5 border-warning/30"
                data-testid="onramp-international-soon">
            <div className="flex items-start gap-3">
              <div className="h-10 w-10 rounded-full bg-warning/15 text-warning
                                flex items-center justify-center shrink-0">
                <Sparkles size={18} />
              </div>
              <div className="flex-1">
                <div className="flex items-center gap-2 mb-1">
                  <h3 className="font-display font-bold text-base text-fg">
                    {t("international_title")}
                  </h3>
                  <Badge tone="warning" size="sm" data-testid="onramp-soon-badge">
                    {tc("coming_soon")}
                  </Badge>
                </div>
                <p className="text-sm text-fg-muted leading-relaxed">
                  {t("international_desc")}
                </p>
                <div className="mt-3 flex flex-wrap gap-2">
                  {["USD", "CLP", "BRL", "MXN"].map((c) => (
                    <span key={c}
                          className="text-[10px] font-mono uppercase tracking-wider
                                      px-2 py-0.5 rounded-full
                                      bg-bg-elevated text-fg-subtle border border-border">
                      {c} · soon
                    </span>
                  ))}
                </div>
              </div>
              <Clock size={14} className="text-fg-subtle shrink-0 mt-1" />
            </div>
          </div>
        </>
      )}
    </div>
  );
}

function RailCard({ eyebrow, title, desc, icon, href, tone, testid }: {
  eyebrow: string; title: string; desc: string;
  icon: React.ReactNode; href: string;
  tone: "primary" | "default"; testid: string;
}) {
  const ring = tone === "primary"
    ? "border-primary/30 hover:border-primary"
    : "border-border hover:border-fg/30";
  const accent = tone === "primary"
    ? "bg-primary/10 text-primary"
    : "bg-fg/5 text-fg";
  return (
    <Link href={href} data-testid={testid}
           className={`prosper-card p-5 border ${ring} transition-all
                       hover:bg-surface-hover group block`}>
      <div className="flex items-start gap-3">
        <div className={`h-11 w-11 rounded-full ${accent}
                          flex items-center justify-center shrink-0`}>
          {icon}
        </div>
        <div className="flex-1 min-w-0">
          <div className="text-[10px] font-mono uppercase tracking-[0.18em] text-fg-subtle">
            {eyebrow}
          </div>
          <h3 className="font-display font-bold text-base text-fg mt-0.5">
            {title}
          </h3>
          <p className="text-sm text-fg-muted mt-1 leading-relaxed">{desc}</p>
        </div>
        <ArrowRight size={16} className="text-fg-subtle shrink-0
                                            transition-transform
                                            group-hover:translate-x-0.5
                                            group-hover:text-fg" />
      </div>
    </Link>
  );
}

function BlockedCard() {
  const t = useTranslations("onramp_hub");
  return (
    <div className="prosper-card p-10 text-center" data-testid="onramp-blocked">
      <div className="mx-auto h-12 w-12 rounded-full bg-warning/10 text-warning
                        flex items-center justify-center mb-3">
        <AlertTriangle size={20} />
      </div>
      <h2 className="font-display font-bold text-lg text-fg">{t("blocked_title")}</h2>
      <p className="text-sm text-fg-muted mt-2 max-w-sm mx-auto">
        {t("blocked_msg")}
      </p>
      <Link href="/apply"
             className="prosper-btn-primary inline-flex h-10 px-5 mt-5 text-sm">
        {t("blocked_cta")} <ArrowRight size={14} />
      </Link>
    </div>
  );
}
