"use client";
import Link from "next/link";
import { useMemo } from "react";
import { useTranslations } from "next-intl";
import {
  Coins, Plus, ArrowRight, ExternalLink, Hash, CalendarClock, Lock,
} from "lucide-react";
import { PageHeader, Badge } from "@prosper/ui";
import { RefreshButton } from "@/components/PageActions";
import { useClientMe } from "@/lib/client-portal";
import { usePositions, type Position } from "@/lib/invest";
import { statusLabel, statusTone, fmtAmount, modalityLabel } from "@/lib/portal-format";

/**
 * /client/investments — P1-2 (Feb 2026)
 *
 * CMS-aligned positions list. Each asset keeps its native currency
 * end-to-end (no cross-asset conversion).
 */

const STELLAR_EXPLORER_TX = "https://stellar.expert/explorer/public/tx";

const fmtCur = (v: number, unit: "ARSa" | "USDC") => fmtAmount(v, unit);

export default function InvestmentsPage() {
  const t   = useTranslations("investments_page");
  const tc  = useTranslations("common");
  const { data: me } = useClientMe();
  const { data, isLoading, mutate } = usePositions();
  const positions = data?.items ?? [];
  const canOperate = me?.features?.can_operate ?? false;

  const groups = useMemo(() => {
    const arsa: Position[] = [];
    const usdc: Position[] = [];
    for (const p of positions) {
      if ((p.asset ?? "usdc") === "arsa") arsa.push(p);
      else usdc.push(p);
    }
    return { arsa, usdc };
  }, [positions]);

  const totals = (rows: Position[]) => {
    const active = rows.filter((p) => p.status === "active");
    const principal = active.reduce(
      (s, p) => s + (p.principal_native ?? p.principal_usd ?? 0), 0);
    const accrued = rows.reduce((s, p) => s + (p.accrued_interest || 0), 0);
    return { activeCount: active.length, principal, accrued };
  };
  const tArsa = totals(groups.arsa);
  const tUsdc = totals(groups.usdc);

  return (
    <div data-testid="investments-page">
      <PageHeader
        breadcrumbs={[{ label: tc("home"), href: "/client" }, { label: t("breadcrumb") }]}
        kicker={t("kicker")}
        title={t("title")}
        subtitle={t("subtitle")}
        actions={
          <div className="flex items-center gap-2">
            <RefreshButton onClick={() => mutate()} />
            <Link
              href="/client/invest"
              className={`prosper-btn-primary h-9 px-3 text-xs gap-1.5
                          ${!canOperate ? "opacity-40 pointer-events-none" : ""}`}
              data-testid="invest-new"
            >
              <Plus size={13} /> {t("new_investment")}
            </Link>
          </div>
        }
      />

      {isLoading ? (
        <div className="prosper-card p-8 animate-pulse h-32" />
      ) : positions.length === 0 ? (
        <div className="prosper-card p-10 text-center" data-testid="positions-empty">
          <Coins size={28} className="mx-auto text-fg-subtle mb-2" />
          <h2 className="font-display font-bold text-lg text-fg">{t("empty_title")}</h2>
          <p className="text-sm text-fg-muted mt-2 max-w-sm mx-auto">
            {t("empty_msg")}
          </p>
          {canOperate && (
            <Link href="/client/invest"
              className="prosper-btn-primary inline-flex h-10 px-5 mt-4 text-sm gap-2">
              <Plus size={14}/> {t("invest_now")}
            </Link>
          )}
        </div>
      ) : (
        <div className="space-y-8" data-testid="positions-grouped">
          <AssetSection
            asset="arsa"
            assetUnit="ARSa"
            label={t("asset_section_arsa")}
            rows={groups.arsa}
            totals={tArsa}
          />
          <AssetSection
            asset="usdc"
            assetUnit="USDC"
            label={t("asset_section_usdc")}
            rows={groups.usdc}
            totals={tUsdc}
          />
        </div>
      )}
    </div>
  );
}

function AssetSection({ asset, assetUnit, label, rows, totals }:
  { asset: "arsa" | "usdc"; assetUnit: "ARSa" | "USDC";
    label: string; rows: Position[];
    totals: { activeCount: number; principal: number; accrued: number } }) {
  const t = useTranslations("investments_page");
  if (rows.length === 0) {
    return (
      <section data-testid={`section-${asset}`}>
        <SectionHead label={label} totals={totals} assetUnit={assetUnit} />
        <div className="prosper-card p-6 text-center text-xs text-fg-subtle">
          {t("empty_for_asset", { asset: assetUnit })}
        </div>
      </section>
    );
  }
  return (
    <section data-testid={`section-${asset}`}>
      <SectionHead label={label} totals={totals} assetUnit={assetUnit} />
      <div className="space-y-3" data-testid={`positions-${asset}`}>
        {rows.map((p) => (
          <PositionRow key={p.position_id} pos={p} assetUnit={assetUnit} />
        ))}
      </div>
    </section>
  );
}

function SectionHead({ label, totals, assetUnit }:
  { label: string;
    totals: { activeCount: number; principal: number; accrued: number };
    assetUnit: "ARSa" | "USDC" }) {
  const t = useTranslations("investments_page");
  return (
    <div className="flex items-start justify-between mb-3">
      <div>
        <div className="text-[10px] font-mono uppercase tracking-[0.18em] text-fg-subtle">
          {label}
        </div>
        <h2 className="font-display font-bold text-base text-fg">
          {totals.activeCount === 1
            ? t("active_one", { count: totals.activeCount })
            : t("active_other", { count: totals.activeCount })}
        </h2>
      </div>
      <div className="text-right">
        <div className="text-[10px] font-mono uppercase tracking-wider text-fg-subtle">
          {t("principal_yield")}
        </div>
        <div className="text-sm font-mono tabular-nums">
          <span className="text-fg">{fmtCur(totals.principal, assetUnit)}</span>
          <span className="text-fg-subtle mx-1.5">·</span>
          <span className="text-success">{fmtCur(totals.accrued, assetUnit)}</span>
        </div>
      </div>
    </div>
  );
}

function PositionRow({ pos, assetUnit }:
  { pos: Position; assetUnit: "ARSa" | "USDC" }) {
  const t = useTranslations("investments_page");
  const daysToMaturity = pos.maturity
    ? Math.max(0, Math.ceil((new Date(pos.maturity).getTime() - Date.now()) / 86400_000))
    : null;
  const principal = pos.principal_native ?? pos.principal_usd ?? 0;
  const accrued   = pos.accrued_interest ?? 0;
  const ratePct   = (pos.apr_bps ?? 0) / 100;
  const modality  = (pos as Position & { modality?: string }).modality;
  const memo      = (pos as Position & { memo?: string | null }).memo;
  const hash      = (pos as Position & { hash?: string | null }).hash;

  return (
    <div
      className="prosper-card p-5 hover:border-primary/40 transition-colors"
      data-testid={`pos-${pos.position_id}`}
    >
      <div className="flex items-center gap-4">
        <div className={`h-10 w-10 rounded-full flex items-center justify-center shrink-0
                         ${modality === "month" ? "bg-warning/10 text-warning"
                                                  : "bg-primary/10 text-primary"}`}>
          {modality === "month"
            ? <CalendarClock size={16} />
            : <Lock size={16} />}
        </div>

        <div className="flex-1 grid grid-cols-2 sm:grid-cols-5 gap-2 sm:gap-4">
          <Cell label={t("cell_modality")} value={modalityLabel(modality)} mono />
          <Cell label={t("cell_principal")} value={fmtCur(principal, assetUnit)} />
          <Cell label={t("cell_rate")} value={`${ratePct.toFixed(2)}%`} success />
          <Cell label={t("cell_accrued")}
                value={fmtCur(accrued, assetUnit)}
                tone={accrued > 0 ? "success" : "muted"} />
          <Cell label={t("cell_maturity")}
                value={daysToMaturity != null
                          ? (daysToMaturity > 0 ? `${daysToMaturity}d`
                                                 : t("cell_matured"))
                          : "—"} />
        </div>

        <div className="hidden sm:flex items-center gap-2">
          <Badge tone={statusTone(pos.status)} size="sm">
            {statusLabel(pos.status)}
          </Badge>
          <Link href={`/client/investments/${pos.position_id}`}
                className="text-fg-subtle hover:text-fg"
                data-testid={`pos-detail-${pos.position_id}`}>
            <ArrowRight size={14} />
          </Link>
        </div>
      </div>

      {(memo || hash) && (
        <div className="mt-3 pt-3 border-t border-border flex flex-wrap items-center gap-4
                        text-[10px] font-mono text-fg-subtle">
          {memo && (
            <span className="inline-flex items-center gap-1" data-testid="pos-memo">
              <Hash size={10} /> {t("memo")}:{" "}
              <span className="text-fg-muted">{memo}</span>
            </span>
          )}
          {hash && (
            <a href={`${STELLAR_EXPLORER_TX}/${hash}`}
               target="_blank" rel="noopener noreferrer"
               className="inline-flex items-center gap-1 text-primary hover:underline"
               data-testid="pos-hash-link">
              <ExternalLink size={10} />
              {t("hash")}: {hash.slice(0, 6)}…{hash.slice(-4)}
            </a>
          )}
        </div>
      )}
    </div>
  );
}

function Cell({ label, value, mono, success, tone }:
  { label: string; value: string; mono?: boolean; success?: boolean;
    tone?: "success" | "muted" }) {
  const color = tone === "success" ? "text-success"
              : tone === "muted"   ? "text-fg-subtle"
              : success            ? "text-success font-bold"
              :                       "text-fg";
  return (
    <div>
      <div className="text-[10px] font-mono uppercase tracking-wider text-fg-subtle">{label}</div>
      <div className={`text-sm ${mono ? "font-mono" : ""} ${color} tabular-nums`}>
        {value}
      </div>
    </div>
  );
}
