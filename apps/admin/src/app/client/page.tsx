"use client";
import Link from "next/link";
import { useEffect, useState } from "react";
import useSWR from "swr";
import { useTranslations } from "next-intl";
import { PageHeader, KpiCard, Badge } from "@prosper/ui";
import { RefreshButton } from "@/components/PageActions";
import { YieldChart } from "@/components/client/YieldChart";
import { TodayYieldCard } from "@/components/client/TodayYieldCard";
import { ArsaAccountCard } from "@/components/client/ArsaAccountCard";
import { MovementsCard } from "@/components/client/RampMovementsAndForms";
import {
  Coins, Wallet, LineChart, CalendarClock, Hash,
} from "lucide-react";
import { useClientMe, useClientDashboard } from "@/lib/client-portal";
import { usePortfolioSnapshot } from "@/lib/portfolio-snapshot";
import { api } from "@/lib/api";
import { statusLabel, statusTone, fmtAmount } from "@/lib/portal-format";
import PendingDepositCard from "@/components/client/PendingDepositCard";
import NewMovementBadge from "@/components/client/NewMovementBadge";

interface DashboardSummary {
  aum: {
    arsa: { principal: number; yield_accrued: number; yield_claimed: number;
             positions: number; active: number };
    usdc: { principal: number; yield_accrued: number; yield_claimed: number;
             positions: number; active: number };
  };
  cash: {
    usdc: number;
    usdc_platform: number;
    usdc_stellar: number;
    arsa: number;
    arsa_cvu: number;
    arsa_stellar: number;
  };
  breakdown: Array<{ asset: string; modality: string; count: number; principal: number }>;
  fetched_at: string;
}

const fmtNative = (v: number, unit: "ARSa" | "USDC") => fmtAmount(v, unit);

export default function ClientDashboardPage() {
  const t   = useTranslations("dashboard");
  const tc  = useTranslations("common");
  const { data: meData } = useClientMe();
  const { data, isLoading, mutate } = useClientDashboard();
  const { data: summary, mutate: mutSummary } = useSWR<DashboardSummary>(
    "/v1/client/dashboard-summary", (p: string) => api(p),
    { refreshInterval: 30_000 });
  // Phase 04 — live polling for balances + movements (20s, visibility-paused).
  const portfolio = usePortfolioSnapshot();
  const canOperate = meData?.features?.can_operate ?? false;
  const kybStatus  = meData?.org?.kyb_status;
  const aum  = summary?.aum;

  const orgName = meData?.org?.commercial_name || meData?.org?.legal_name;
  const greeting = orgName ? `${t("title_greeting")}, ${orgName}` : t("title_greeting");

  // P2·#2 (Feb 2026) — yield chart toggle.
  const defaultChartAsset: "arsa" | "usdc" =
    (aum?.arsa?.positions ?? 0) > 0 ? "arsa" : "usdc";
  const [chartAsset, setChartAsset] = useState<"arsa" | "usdc">(defaultChartAsset);
  useEffect(() => { setChartAsset(defaultChartAsset);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [aum?.arsa?.positions, aum?.usdc?.positions]);

  const monthlyYield = data?.monthly_yield || [];
  const dailySeries = (data?.daily_yield || []).map((d) => ({
    date: d.date, value: chartAsset === "arsa" ? d.arsa : d.usdc,
  }));
  const todayByAsset = data?.today_yield?.by_asset?.[chartAsset];

  const txLabel = (type: string): string => {
    const map: Record<string, string> = {
      subscribe: t("tx_labels.subscribe"),
      redeem:    t("tx_labels.redeem"),
      deposit:   t("tx_labels.deposit"),
      onramp:    t("tx_labels.onramp"),
      withdraw:  t("tx_labels.withdraw"),
      offramp:   t("tx_labels.offramp"),
      yield_accrual: t("tx_labels.yield_accrual"),
    };
    return map[type] || type;
  };

  if (!canOperate) {
    return (
      <div data-testid="client-dashboard-pre-kyb">
        <PageHeader
          breadcrumbs={[{ label: tc("home"), href: "/client" }, { label: t("breadcrumb") }]}
          title={greeting}
          subtitle={t("pre_kyb.intro")}
        />
        <PreKybCard
          kybStatus={kybStatus}
          applicantType={(meData as { applicant_type?: string })?.applicant_type}
          rampOnboardingStatus={(meData as { ramp_onboarding_status?: string })?.ramp_onboarding_status}
        />
      </div>
    );
  }

  return (
    <div data-testid="client-dashboard">
      <PageHeader
        breadcrumbs={[{ label: tc("home"), href: "/client" }, { label: t("breadcrumb") }]}
        title={greeting}
        subtitle={t("subtitle")}
        actions={
          <div className="flex items-center gap-2">
            <NewMovementBadge
              show={portfolio.isNewMovement}
              newestMovement={portfolio.newestMovement}
            />
            <RefreshButton onClick={() => {
              mutate(); mutSummary(); void portfolio.refresh();
            }} />
          </div>
        }
      />

      {/* Phase 04 — "Depósito en camino" cards. Rails kept separate;
          rendered only when pending_detected > 0 for that asset. */}
      {(portfolio.snapshot?.balances.arsa.pending_detected ?? 0) > 0 && (
        <div className="mb-3">
          <PendingDepositCard
            asset="arsa"
            amount={portfolio.snapshot!.balances.arsa.pending_detected}
          />
        </div>
      )}
      {(portfolio.snapshot?.balances.usdc.pending_detected ?? 0) > 0 && (
        <div className="mb-3">
          <PendingDepositCard
            asset="usdc"
            amount={portfolio.snapshot!.balances.usdc.pending_detected}
          />
        </div>
      )}

      {meData?.org?.org_id && <ArsaAccountCard orgId={meData.org.org_id} />}
      {meData?.org?.org_id && <MovementsCard endCustomerId={meData.org.org_id} />}

      {todayByAsset && todayByAsset.total > 0 && (
        <TodayYieldCard
          asset={chartAsset}
          earned={todayByAsset.earned}
          earningNow={todayByAsset.earning_now}
          total={todayByAsset.total}
          asOf={data?.today_yield?.as_of || ""}
          series={dailySeries}
        />
      )}

      <InvestmentSection
        aum={aum}
        positions={data?.positions || []}
      />

      <div className="prosper-card p-5 mb-6" data-testid="yield-card">
        <div className="flex items-center justify-between mb-3 flex-wrap gap-2">
          <div>
            <div className="text-[10px] font-mono uppercase tracking-[0.18em] text-fg-subtle">
              {t("yield_chart.section_label")}
            </div>
            <h3 className="font-display font-bold text-lg text-fg flex items-center gap-1.5 mt-0.5">
              <LineChart size={14} className="text-success" /> {t("yield_chart.title")}
            </h3>
          </div>

          <div className="flex items-center gap-2">
            <div className="flex items-center gap-1 p-1 rounded-full bg-surface-hover"
                  data-testid="yield-chart-toggle">
              {(["arsa", "usdc"] as const).map((a) => (
                <button
                  key={a}
                  type="button"
                  onClick={() => setChartAsset(a)}
                  data-testid={`yield-chart-toggle-${a}`}
                  className={`h-7 px-3 rounded-full text-[10px] font-mono uppercase
                                tracking-wider transition
                                ${chartAsset === a
                                  ? "bg-fg text-bg shadow-sm"
                                  : "text-fg-muted hover:text-fg"}`}>
                  {a === "arsa" ? "ARSa" : "USDC"}
                </button>
              ))}
            </div>
            {aum && (
              <Badge tone="success" size="sm" data-testid="apr-badge">
                {chartAsset === "arsa"
                  ? (aum.arsa.positions ? "ARSa" : t("yield_chart.no_arsa"))
                  : (aum.usdc.positions ? "USDC" : t("yield_chart.no_usdc"))}
              </Badge>
            )}
          </div>
        </div>
        {isLoading || !data ? (
          <div className="h-[220px] animate-pulse bg-bg-muted rounded" />
        ) : (
          <YieldChart data={monthlyYield} asset={chartAsset} />
        )}
        <p className="text-[10px] text-fg-subtle mt-3">
          {t("yield_chart.hint_prefix")}{" "}
          <strong className="text-fg">{chartAsset === "arsa" ? "ARSa" : "USDC"}</strong>.{" "}
          <Link href="/client/investments" className="text-primary hover:underline">
            {t("yield_chart.see_positions")}
          </Link>.
        </p>
      </div>

      {/* Positions + Recent tx */}
      <div className="grid grid-cols-1 lg:grid-cols-5 gap-5">
        <section className="prosper-card p-5 lg:col-span-3" data-testid="positions-card">
          <div className="flex items-center justify-between mb-3">
            <div>
              <div className="text-[10px] font-mono uppercase tracking-[0.18em] text-fg-subtle">
                {t("recent_positions.kicker")}
              </div>
              <h3 className="font-display font-bold text-lg text-fg mt-0.5">
                {t("recent_positions.title")}
              </h3>
            </div>
            <Link
              href="/client/investments"
              className="text-[11px] font-mono uppercase tracking-wider text-primary hover:underline"
              data-testid="positions-see-all"
            >
              {t("recent_positions.see_all")} →
            </Link>
          </div>

          {!data || data.positions.length === 0 ? (
            <EmptyHint
              icon={<Coins size={20} />}
              title={t("recent_positions.empty_title")}
              msg={t("recent_positions.empty_msg")}
              cta={{ href: "/client/invest", label: t("recent_positions.empty_cta") }}
            />
          ) : (
            <div className="overflow-x-auto -mx-5">
              <table className="w-full text-sm" data-testid="positions-table">
                <thead>
                  <tr className="text-[10px] font-mono uppercase tracking-wider text-fg-subtle border-b border-border">
                    <Th>{t("recent_positions.th_product")}</Th>
                    <Th right>{t("recent_positions.th_principal")}</Th>
                    <Th right>{t("recent_positions.th_apr")}</Th>
                    <Th right>{t("recent_positions.th_accrued")}</Th>
                    <Th>{t("recent_positions.th_maturity")}</Th>
                  </tr>
                </thead>
                <tbody>
                  {data.positions.slice(0, 6).map((p) => {
                    const unit = p.asset === "arsa" ? "ARSa" : "USDC";
                    const productKey =
                      p.asset === "arsa"
                        ? (p.modality === "month" ? "staking_arsa_month" : "staking_arsa_end")
                        : (p.modality === "month" ? "staking_usdc_month" : "staking_usdc_end");
                    const productLabel = t(`recent_positions.${productKey}` as any);
                    return (
                    <tr key={p.position_id}
                        className="border-b border-border/60 hover:bg-surface-hover"
                        data-testid={`position-${p.position_id}`}>
                      <Td>{productLabel}</Td>
                      <Td right>{fmtNative(p.principal, unit)}</Td>
                      <Td right>
                        <span className="text-success">{p.apr_pct.toFixed(2)}%</span>
                      </Td>
                      <Td right>{fmtNative(p.accrued, unit)}</Td>
                      <Td>
                        <span className="inline-flex items-center gap-1 text-fg-muted text-xs">
                          <CalendarClock size={11} />
                          {p.days_to_maturity != null ? `${p.days_to_maturity}d` : "—"}
                        </span>
                      </Td>
                    </tr>);
                  })}
                </tbody>
              </table>
            </div>
          )}
        </section>

        <section className="prosper-card p-5 lg:col-span-2" data-testid="recent-tx-card">
          <div className="flex items-center justify-between mb-3">
            <div>
              <div className="text-[10px] font-mono uppercase tracking-[0.18em] text-fg-subtle">
                {t("recent_tx.kicker")}
              </div>
              <h3 className="font-display font-bold text-lg text-fg mt-0.5">{t("recent_tx.title")}</h3>
            </div>
            <Link
              href="/client/transactions"
              className="text-[11px] font-mono uppercase tracking-wider text-primary hover:underline"
              data-testid="tx-see-all"
            >
              {t("recent_tx.history")} →
            </Link>
          </div>
          {!data || data.recent_transactions.length === 0 ? (
            <EmptyHint
              icon={<Wallet size={20} />}
              title={t("recent_tx.empty_title")}
              msg={t("recent_tx.empty_msg")}
              cta={{ href: "/client/onramp", label: t("recent_tx.empty_cta") }}
            />
          ) : (
            <ul className="space-y-2" data-testid="recent-tx-list">
              {data.recent_transactions.map((tx) => (
                <li
                  key={tx.tx_id}
                  className="flex items-center gap-3 py-2 border-b border-border/50 last:border-0"
                  data-testid={`tx-${tx.tx_id}`}
                >
                  <div className="shrink-0 h-8 w-8 rounded-full bg-surface flex items-center justify-center">
                    <Hash size={12} className="text-fg-subtle" />
                  </div>
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2">
                      <span className="text-sm text-fg truncate">
                        {txLabel(tx.type)}
                      </span>
                      <Badge tone={statusTone(tx.status)} size="sm">
                        {statusLabel(tx.status)}
                      </Badge>
                    </div>
                    <div className="text-[10px] font-mono text-fg-subtle">
                      {new Date(tx.created_at).toLocaleString(undefined,
                        { day: "2-digit", month: "2-digit", year: "numeric",
                            hour: "2-digit", minute: "2-digit" })}
                    </div>
                  </div>
                  <div className="text-sm font-mono text-fg shrink-0">
                    {tx.amount.toLocaleString(undefined,
                      { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
                  </div>
                </li>
              ))}
            </ul>
          )}
        </section>
      </div>
    </div>
  );
}

function Th({ children, right }: { children: React.ReactNode; right?: boolean }) {
  return (
    <th className={`px-5 py-2 ${right ? "text-right" : "text-left"} font-normal`}>{children}</th>
  );
}
function Td({ children, right }: { children: React.ReactNode; right?: boolean }) {
  return (
    <td className={`px-5 py-2 ${right ? "text-right font-mono" : "text-left"}`}>{children}</td>
  );
}

function EmptyHint({ icon, title, msg, cta }:
  { icon: React.ReactNode; title: string; msg: string;
    cta?: { href: string; label: string } }) {
  return (
    <div className="py-10 text-center text-fg-subtle">
      <div className="mx-auto mb-2 h-10 w-10 rounded-full bg-surface flex items-center justify-center">
        {icon}
      </div>
      <div className="text-sm font-display font-semibold text-fg">{title}</div>
      <div className="text-xs mt-1 max-w-xs mx-auto">{msg}</div>
      {cta && (
        <Link
          href={cta.href}
          className="inline-flex items-center gap-1 mt-4 h-8 px-3 rounded-full
                      bg-primary text-white text-[11px] font-mono uppercase
                      tracking-wider hover:bg-primary/90 transition"
          data-testid="empty-hint-cta">
          {cta.label} →
        </Link>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// PreKybCard — P2·#1 (Feb 2026)
// ---------------------------------------------------------------------------
function PreKybCard({ kybStatus, applicantType, rampOnboardingStatus }:
  { kybStatus?: string; applicantType?: string; rampOnboardingStatus?: string }) {
  const t = useTranslations("dashboard.pre_kyb");

  // Phase 22+ — Personal individuals trapped in kyc_docs_required (or the
  // deprecated alias kyc_pending_andes) get a direct CTA to the widget
  // instead of the passive "wait for onboarding" message.
  const isIndividualNeedsDocs =
    applicantType === "individual" &&
    (rampOnboardingStatus === "kyc_docs_required"
      || rampOnboardingStatus === "kyc_pending_andes");
  const isIndividualSubmitted =
    applicantType === "individual" &&
    rampOnboardingStatus === "kyc_docs_submitted";

  if (isIndividualNeedsDocs || isIndividualSubmitted) {
    return (
      <div className="prosper-card p-8 md:p-10 relative overflow-hidden"
            data-testid="pre-kyb-card-kyc-required">
        <div className="absolute inset-0 bg-gradient-to-br from-warning/8 via-transparent to-primary/5
                         pointer-events-none" />
        <div className="relative grid md:grid-cols-[1fr_auto] gap-6 items-center">
          <div>
            <Badge tone="warning" size="sm" data-testid="pre-kyb-status">
              {isIndividualSubmitted ? "Documentos enviados" : "Identidad pendiente"}
            </Badge>
            <h2 className="font-display font-bold text-2xl text-fg mt-3">
              {isIndividualSubmitted
                ? "Documentos enviados — esperando emisión de CVU"
                : "Subí tus documentos de identidad"}
            </h2>
            <p className="text-sm text-fg-muted mt-2 max-w-xl">
              {isIndividualSubmitted
                ? "Andes está procesando tu KYC y emitiendo tu CVU. Suele tardar 1–3 minutos. Te avisamos por mail cuando esté listo."
                : "Necesitamos una selfie y ambos lados de tu DNI para activar tu cuenta. Andes los verifica en 1–3 minutos."}
            </p>
            <div className="mt-6 flex flex-wrap gap-2">
              <Link href="/client/kyc-docs"
                     className="prosper-btn-primary h-11 px-5 text-sm gap-2"
                     data-testid="pre-kyb-kyc-docs-cta">
                {isIndividualSubmitted ? "Ver estado" : "Subir documentos"} →
              </Link>
            </div>
          </div>
          <div className="hidden md:block">
            <div className="h-44 w-44 rounded-full bg-gradient-to-br from-warning/20 to-primary/20
                              flex items-center justify-center">
              <Coins size={64} className="text-warning opacity-70" />
            </div>
          </div>
        </div>
      </div>
    );
  }

  const statusMap: Record<string, { tone: "warning" | "info" | "danger";
                                       labelKey: string; nudgeKey: string }> = {
    pending:    { tone: "warning", labelKey: "status_pending",   nudgeKey: "nudge_pending" },
    in_review:  { tone: "info",    labelKey: "status_review",    nudgeKey: "nudge_review" },
    needs_info: { tone: "warning", labelKey: "status_needs_info", nudgeKey: "nudge_needs_info" },
    rejected:   { tone: "danger",  labelKey: "status_rejected",   nudgeKey: "nudge_rejected" },
  };
  const s = statusMap[kybStatus || "pending"] || statusMap.pending;

  const bullets: Array<[string, string]> = [
    [t("bullet1_title"), t("bullet1_desc")],
    [t("bullet2_title"), t("bullet2_desc")],
    [t("bullet3_title"), t("bullet3_desc")],
    [t("bullet4_title"), t("bullet4_desc")],
  ];

  return (
    <div className="prosper-card p-8 md:p-10 relative overflow-hidden"
          data-testid="pre-kyb-card">
      <div className="absolute inset-0 bg-gradient-to-br from-primary/8 via-transparent to-success/5
                       pointer-events-none" />
      <div className="relative grid md:grid-cols-[1fr_auto] gap-6 items-center">
        <div>
          <Badge tone={s.tone} size="sm" data-testid="pre-kyb-status">
            {t(s.labelKey as any)}
          </Badge>
          <h2 className="font-display font-bold text-2xl text-fg mt-3">
            {t("title")}
          </h2>
          <p className="text-sm text-fg-muted mt-2 max-w-xl">
            {t(s.nudgeKey as any)} {t("list_intro")}
          </p>
          <ul className="mt-4 space-y-2 text-sm text-fg-muted">
            {bullets.map(([title, desc]) => (
              <li key={title} className="flex items-start gap-2">
                <span className="mt-1.5 h-1.5 w-1.5 rounded-full bg-success shrink-0" />
                <span>
                  <strong className="text-fg">{title}.</strong>{" "}
                  <span className="text-fg-subtle">{desc}</span>
                </span>
              </li>
            ))}
          </ul>
          <div className="mt-6 flex flex-wrap gap-2">
            <Link href="/apply"
                   className="prosper-btn-primary h-11 px-5 text-sm gap-2"
                   data-testid="pre-kyb-cta">
              {kybStatus === "needs_info" || kybStatus === "rejected"
                ? t("cta_resume")
                : t("cta_start")} →
            </Link>
            <Link href="/client/profile"
                   className="prosper-btn-ghost h-11 px-5 text-sm"
                   data-testid="pre-kyb-profile-cta">
              {t("cta_profile")}
            </Link>
          </div>
        </div>

        <div className="hidden md:block">
          <div className="h-44 w-44 rounded-full bg-gradient-to-br from-primary/20 to-success/20
                            flex items-center justify-center">
            <Coins size={64} className="text-primary opacity-70" />
          </div>
        </div>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// InvestmentSection (P3, Feb 2026)
// ---------------------------------------------------------------------------

interface AumAsset {
  principal: number; yield_accrued: number; yield_claimed: number;
  positions: number; active: number;
}
interface AumShape { arsa: AumAsset; usdc: AumAsset; }

type DashPosition = {
  position_id: string; asset?: "arsa" | "usdc"; principal: number;
  accrued: number; apr_bps: number; apr_pct: number;
  modality?: "end" | "month"; maturity_date: string; status: string;
};

function InvestmentSection({ aum, positions }:
  { aum?: AumShape; positions: DashPosition[] }) {
  const t = useTranslations("dashboard.investment_section");
  const hasArsa = (aum?.arsa.positions ?? 0) > 0;
  const hasUsdc = (aum?.usdc.positions ?? 0) > 0;
  const empty = !hasArsa && !hasUsdc;

  return (
    <section className="mb-6" data-testid="investment-section">
      <div className="flex items-baseline justify-between mb-3">
        <h2 className="font-display font-bold text-lg text-fg">
          {empty ? t("title_empty") : t("title_has")}
        </h2>
        {!empty && (
          <Link href="/client/investments"
                 className="text-[11px] font-mono uppercase tracking-wider
                             text-primary hover:underline"
                 data-testid="investment-section-see-all">
            {t("see_all")} →
          </Link>
        )}
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        {hasArsa && aum
          ? <AssetInvestmentCard asset="arsa" stats={aum.arsa}
                                    positions={positions.filter((p) => p.asset === "arsa")} />
          : <AssetInvitationCard asset="arsa" /> }
        {hasUsdc && aum
          ? <AssetInvestmentCard asset="usdc" stats={aum.usdc}
                                    positions={positions.filter((p) => p.asset === "usdc")} />
          : <AssetInvitationCard asset="usdc" /> }
      </div>
    </section>
  );
}

function AssetInvestmentCard({ asset, stats, positions }:
  { asset: "arsa" | "usdc"; stats: AumAsset; positions: DashPosition[] }) {
  const t = useTranslations("dashboard.asset_card");
  const unit: "ARSa" | "USDC" = asset === "arsa" ? "ARSa" : "USDC";
  const accent = asset === "arsa" ? "primary" : "success";

  const aprs       = Array.from(new Set(positions.map((p) => p.apr_pct)
                                           .filter((x) => x > 0)));
  const modalities = Array.from(new Set(positions.map((p) => p.modality)
                                           .filter(Boolean)));
  const aprLabel = aprs.length === 1
    ? `${aprs[0].toFixed(2).replace(/\.00$/, "")}% APR`
    : aprs.length > 1
    ? `${Math.min(...aprs).toFixed(0)}-${Math.max(...aprs).toFixed(0)}% APR`
    : "";
  const modLabel = modalities.length === 1
    ? (modalities[0] === "month" ? t("modality_month") : t("modality_end"))
    : modalities.length > 1 ? t("modality_mixed") : "";
  const badge = [modLabel, aprLabel].filter(Boolean).join(" · ");

  const active = positions.filter((p) => p.status === "active"
                                            || p.status === "pending_onchain");
  const nextMaturity = active
    .map((p) => p.maturity_date)
    .filter(Boolean)
    .sort()[0];

  return (
    <div
      className={`prosper-card p-5 border-2 ${accent === "primary"
        ? "border-primary/30 hover:border-primary/60"
        : "border-success/30 hover:border-success/60"}
        transition-all`}
      data-testid={`investment-card-${asset}`}>
      <div className="flex items-start justify-between mb-3">
        <div>
          <div className="text-[10px] font-mono uppercase tracking-[0.18em] text-fg-subtle">
            {t("label_investment", { asset: unit })}
          </div>
          {badge && (
            <div className="text-[11px] text-fg-muted mt-0.5"
                  data-testid={`investment-card-${asset}-badge`}>
              {badge}
            </div>
          )}
        </div>
        <div className={`h-9 w-9 rounded-full flex items-center justify-center
                          ${accent === "primary" ? "bg-primary/10 text-primary"
                                                  : "bg-success/10 text-success"}`}>
          <Coins size={16} />
        </div>
      </div>

      <div className="mb-3" data-testid={`investment-card-${asset}-aum`}>
        <div className="text-3xl font-display font-extrabold text-fg tabular-nums">
          {fmtNative(stats.principal, unit)}
        </div>
      </div>

      <div className="flex flex-wrap items-center gap-x-4 gap-y-1.5 mb-4 text-xs">
        <span className={stats.yield_accrued > 0 ? "text-success" : "text-fg-muted"}
              data-testid={`investment-card-${asset}-yield`}>
          <span className="font-mono">
            {stats.yield_accrued > 0 ? "+" : ""}
            {fmtNative(stats.yield_accrued, unit)}
          </span>
          <span className="text-[10px] font-mono uppercase tracking-wider text-fg-subtle ml-1">
            {t("yield_label")}
          </span>
        </span>
        <span className="text-fg-muted"
              data-testid={`investment-card-${asset}-positions`}>
          <span className="font-mono">{stats.active}</span>
          <span className="text-[10px] font-mono uppercase tracking-wider text-fg-subtle ml-1">
            {stats.active === 1 ? t("active_one") : t("active_other")}
          </span>
        </span>
        {nextMaturity && (
          <span className="text-fg-muted"
                data-testid={`investment-card-${asset}-maturity`}>
            <span className="font-mono">{fmtShortDate(nextMaturity)}</span>
            <span className="text-[10px] font-mono uppercase tracking-wider text-fg-subtle ml-1">
              {t("next_maturity")}
            </span>
          </span>
        )}
      </div>

      <Link href={`/client/investments?asset=${asset}`}
             className={`inline-flex items-center gap-1 text-[11px] font-mono
                          uppercase tracking-wider transition
                          ${accent === "primary" ? "text-primary hover:underline"
                                                  : "text-success hover:underline"}`}
             data-testid={`investment-card-${asset}-cta`}>
        {t("see_positions")} →
      </Link>
    </div>
  );
}

function AssetInvitationCard({ asset }: { asset: "arsa" | "usdc" }) {
  const t = useTranslations("dashboard.asset_card");
  const unit = asset === "arsa" ? "ARSa" : "USDC";
  const hint = asset === "arsa"
    ? t("empty_hint_arsa")
    : t("empty_hint_usdc");
  return (
    <div
      className="prosper-card p-5 border border-dashed border-border bg-bg-elevated/40"
      data-testid={`investment-card-${asset}-empty`}>
      <div className="flex items-start gap-3">
        <div className="h-9 w-9 rounded-full bg-fg/5 text-fg-subtle
                          flex items-center justify-center shrink-0">
          <Coins size={15} />
        </div>
        <div className="flex-1 min-w-0">
          <div className="text-[10px] font-mono uppercase tracking-[0.18em] text-fg-subtle">
            {unit}
          </div>
          <h3 className="text-sm font-display font-bold text-fg mt-0.5">
            {t("empty_title", { asset: unit })}
          </h3>
          <p className="text-[12px] text-fg-muted mt-1 leading-snug">{hint}</p>
          <Link href={`/client/invest?asset=${asset}`}
                 className="inline-flex items-center gap-1 mt-3 h-8 px-3 rounded-full
                             bg-surface border border-border hover:border-primary
                             hover:bg-primary/5 hover:text-primary transition
                             text-[11px] font-mono uppercase tracking-wider text-fg"
                 data-testid={`investment-card-${asset}-empty-cta`}>
            {t("empty_cta", { asset: unit })} →
          </Link>
        </div>
      </div>
    </div>
  );
}

function fmtShortDate(iso: string): string {
  try { return new Date(iso).toLocaleDateString(undefined,
    { day: "2-digit", month: "2-digit", year: "2-digit" }); }
  catch { return "—"; }
}
