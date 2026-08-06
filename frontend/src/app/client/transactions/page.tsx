"use client";
/**
 * /client/transactions — Activity (Feb 2026 rewrite, i18n).
 */
import { useState, useMemo } from "react";
import Link from "next/link";
import { useTranslations } from "next-intl";
import { Download, FilterIcon, ExternalLink } from "lucide-react";
import { PageHeader, Badge } from "@prosper/ui";
import { RefreshButton } from "@/components/PageActions";
import { useTxHistory } from "@/lib/alfred";
import {
  statusLabel, statusTone, fmtAmount, fmtDateTime, typeLabel,
} from "@/lib/portal-format";

const STELLAR_EXPLORER_TX = "https://stellar.expert/explorer/public/tx";

const ALL_TYPES = [
  "arsa_deposit", "usdc_deposit",
  "invest", "redeem",
  "arsa_withdraw", "usdc_withdraw",
];
const TYPE_KEYS: Record<string, string> = {
  arsa_deposit:  "type_arsa_deposit",
  usdc_deposit:  "type_usdc_deposit",
  invest:        "type_invest",
  redeem:        "type_redeem",
  arsa_withdraw: "type_arsa_withdraw",
  usdc_withdraw: "type_usdc_withdraw",
};

const ALL_STATUS = ["pending", "pending_onchain", "confirmed", "failed", "cancelled"];
const STATUS_KEYS: Record<string, string> = {
  pending:         "status_pending",
  pending_onchain: "status_pending_onchain",
  confirmed:       "status_confirmed",
  failed:          "status_failed",
  cancelled:       "status_cancelled",
};

const ALL_ASSETS = ["arsa", "usdc"];
const ASSET_LABELS: Record<string, string> = { arsa: "ARSa", usdc: "USDC" };

const TYPE_TONE: Record<string, "success" | "warning" | "info" | "default"> = {
  arsa_deposit: "success",
  usdc_deposit: "success",
  invest:       "info",
  redeem:       "warning",
  arsa_withdraw: "default",
  usdc_withdraw: "default",
};


export default function TransactionsHistoryPage() {
  const t  = useTranslations("transactions_page");
  const tc = useTranslations("common");
  const [type, setType]     = useState("");
  const [status, setStatus] = useState("");
  const [asset, setAsset]   = useState("");
  const [expanded, setExpanded] = useState<string | null>(null);
  const { data, isLoading, mutate } = useTxHistory({ type, status, asset });
  const rows = data?.items ?? [];

  const typeLabels  = Object.fromEntries(ALL_TYPES.map(k => [k, t(TYPE_KEYS[k] as any)]));
  const statusLabels = Object.fromEntries(ALL_STATUS.map(k => [k, t(STATUS_KEYS[k] as any)]));

  const exportCsv = useMemo(() => () => {
    const headers = ["created_at", "type", "amount", "asset", "status",
                       "tx_id", "tx_hash", "destination_cvu", "position_id", "memo"];
    const csv = [
      headers.join(","),
      ...rows.map((r) => [
        r.created_at, r.type, r.amount, r.asset, r.status, r.tx_id,
        r.tx_hash || "", r.destination_cvu || "", r.position_id || "",
        `"${(r.memo || "").replace(/"/g, '""')}"`,
      ].join(",")),
    ].join("\n");
    const blob = new Blob([csv], { type: "text/csv;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `prosper-activity-${new Date().toISOString().slice(0,10)}.csv`;
    document.body.appendChild(a); a.click(); a.remove();
    URL.revokeObjectURL(url);
  }, [rows]);

  return (
    <div data-testid="tx-history">
      <PageHeader
        breadcrumbs={[{ label: tc("home"), href: "/client" }, { label: t("breadcrumb") }]}
        title={t("title")}
        subtitle={t("subtitle")}
        actions={<div className="flex gap-2">
          <button onClick={exportCsv}
                  className="prosper-btn-ghost h-9 text-xs gap-1.5"
                  data-testid="export-csv-btn">
            <Download size={13} /> {t("export_csv")}
          </button>
          <RefreshButton onClick={() => mutate()} />
        </div>}
      />

      <div className="prosper-card p-3 mb-4 flex flex-wrap items-center gap-2"
            data-testid="tx-filters">
        <FilterIcon size={12} className="text-fg-subtle ml-2" />
        <Select label={t("filter_type")}   value={type}   setValue={setType}
                 options={ALL_TYPES}  labels={typeLabels}   testid="filter-type" allLabel={tc("all")} />
        <Select label={t("filter_status")} value={status} setValue={setStatus}
                 options={ALL_STATUS} labels={statusLabels} testid="filter-status" allLabel={tc("all")} />
        <Select label={t("filter_currency")} value={asset}  setValue={setAsset}
                 options={ALL_ASSETS} labels={ASSET_LABELS}  testid="filter-asset" allLabel={tc("all")} />
        {(type || status || asset) && (
          <button onClick={() => { setType(""); setStatus(""); setAsset(""); }}
            className="text-[10px] font-mono uppercase tracking-wider text-fg-subtle hover:text-fg ml-2"
            data-testid="filter-clear">
            {t("clear")}
          </button>
        )}
        <span className="ml-auto text-[11px] font-mono text-fg-subtle">
          {isLoading
            ? t("loading")
            : (rows.length === 1
                ? t("results_one", { count: rows.length })
                : t("results_other", { count: rows.length }))}
        </span>
      </div>

      <div className="prosper-card overflow-hidden">
        {rows.length === 0 ? (
          <EmptyState filtered={!!(type || status || asset)} />
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm" data-testid="tx-table">
              <thead>
                <tr className="text-[10px] font-mono uppercase tracking-wider text-fg-subtle border-b border-border bg-bg-elevated/40">
                  <Th>{t("th_date")}</Th>
                  <Th>{t("th_type")}</Th>
                  <Th>{t("th_currency")}</Th>
                  <Th right>{t("th_amount")}</Th>
                  <Th>{t("th_status")}</Th>
                  <Th>{t("th_detail")}</Th>
                </tr>
              </thead>
              <tbody>
                {rows.map((r) => {
                  const assetUnit: "ARSa" | "USDC" =
                    (r.asset || "").toLowerCase() === "arsa" ? "ARSa" : "USDC";
                  const isExpanded = expanded === r.tx_id;
                  return (
                  <>
                  <tr key={r.tx_id}
                      className="border-b border-border/50 hover:bg-surface-hover cursor-pointer"
                      onClick={() => setExpanded(isExpanded ? null : r.tx_id)}
                      data-testid={`tx-row-${r.tx_id}`}>
                    <Td>
                      <span className="text-xs font-mono text-fg-muted">
                        {fmtDateTime(r.created_at)}
                      </span>
                    </Td>
                    <Td>
                      <Badge tone={TYPE_TONE[r.type] || "default"} size="sm">
                        {typeLabels[r.type] || typeLabel(r.type)}
                      </Badge>
                    </Td>
                    <Td>
                      <span className="text-[11px] font-mono uppercase tracking-wider text-fg-muted">
                        {ASSET_LABELS[r.asset] || r.asset.toUpperCase()}
                      </span>
                    </Td>
                    <Td right>
                      <span className="font-mono tabular-nums">
                        {fmtAmount(r.amount, assetUnit)}
                      </span>
                    </Td>
                    <Td>
                      <Badge tone={statusTone(r.status)} size="sm">
                        {statusLabels[r.status] || statusLabel(r.status)}
                      </Badge>
                    </Td>
                    <Td>
                      <span className="text-xs text-fg-muted line-clamp-1">
                        {r.memo || "—"}
                      </span>
                    </Td>
                  </tr>
                  {isExpanded && (
                    <tr className="bg-bg-elevated/30 border-b border-border/50"
                        data-testid={`tx-detail-${r.tx_id}`}>
                      <td colSpan={6} className="px-5 py-4">
                        <RowDetail r={r} />
                      </td>
                    </tr>
                  )}
                  </>);
                })}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
}

function RowDetail({ r }: { r: import("@/lib/alfred").HistoryTx }) {
  const t = useTranslations("transactions_page");
  return (
    <div className="grid grid-cols-1 md:grid-cols-2 gap-3 text-xs">
      <DetailRow label={t("detail_id")} value={r.tx_id} mono />
      {r.tx_hash && (
        <DetailRow
          label={t("detail_hash")}
          value={
            <a href={`${STELLAR_EXPLORER_TX}/${r.tx_hash}`}
               target="_blank" rel="noopener noreferrer"
               className="font-mono text-primary hover:underline inline-flex items-center gap-1"
               data-testid={`stellar-expert-${r.tx_id}`}>
              {r.tx_hash.slice(0, 10)}…{r.tx_hash.slice(-6)}
              <ExternalLink size={10} />
            </a>
          }
        />
      )}
      {r.destination_cvu && (
        <DetailRow label={t("detail_cvu_dest")}
                    value={<code className="font-mono text-fg">{r.destination_cvu}</code>} />
      )}
      {r.position_id && (
        <DetailRow
          label={t("detail_position")}
          value={
            <Link href={`/client/investments/${r.position_id}`}
                  className="font-mono text-primary hover:underline inline-flex items-center gap-1"
                  data-testid={`position-link-${r.tx_id}`}>
              {r.position_id} <ExternalLink size={10} />
            </Link>
          }
        />
      )}
      <DetailRow label={t("detail_memo")}
                  value={<span className="text-fg-muted">{r.memo || "—"}</span>}
                  fullWidth />
    </div>
  );
}

function DetailRow({ label, value, mono, fullWidth }:
  { label: string; value: React.ReactNode; mono?: boolean; fullWidth?: boolean }) {
  return (
    <div className={fullWidth ? "md:col-span-2" : ""}>
      <div className="text-[9px] font-mono uppercase tracking-[0.18em] text-fg-subtle mb-0.5">
        {label}
      </div>
      <div className={`text-xs text-fg ${mono ? "font-mono" : ""}`}>{value}</div>
    </div>
  );
}

function EmptyState({ filtered }: { filtered: boolean }) {
  const t = useTranslations("transactions_page");
  if (filtered) {
    return (
      <div className="p-10 text-center text-fg-subtle text-sm"
            data-testid="tx-empty-filtered">
        {t("empty_filtered_title")}
        <div className="text-[11px] text-fg-subtle mt-1">
          {t("empty_filtered_msg")}
        </div>
      </div>
    );
  }
  return (
    <div className="p-10 text-center" data-testid="tx-empty">
      <div className="text-sm font-display font-semibold text-fg">
        {t("empty_title")}
      </div>
      <div className="text-[12px] text-fg-muted mt-1 max-w-sm mx-auto">
        {t("empty_msg")}
      </div>
      <Link href="/client/onramp"
             className="inline-flex items-center gap-1 mt-4 h-9 px-4 rounded-full
                         bg-primary text-white text-[11px] font-mono uppercase
                         tracking-wider hover:bg-primary/90 transition"
             data-testid="tx-empty-cta">
        {t("empty_cta")} →
      </Link>
    </div>
  );
}

function Select({ label, value, setValue, options, labels, testid, allLabel }:
  { label: string; value: string; setValue: (v: string) => void;
    options: string[]; labels: Record<string, string>; testid: string;
    allLabel: string }) {
  return (
    <label className="flex items-center gap-1 text-xs">
      <span className="text-fg-subtle">{label}</span>
      <select value={value} onChange={(e) => setValue(e.target.value)}
        className="prosper-input h-8 text-xs px-2"
        data-testid={testid}>
        <option value="">{allLabel}</option>
        {options.map((o) =>
          <option key={o} value={o}>{labels[o] ?? o}</option>)}
      </select>
    </label>
  );
}

function Th({ children, right }: { children: React.ReactNode; right?: boolean }) {
  return <th className={`px-5 py-2 ${right ? "text-right" : "text-left"} font-normal`}>{children}</th>;
}
function Td({ children, right }: { children: React.ReactNode; right?: boolean }) {
  return <td className={`px-5 py-2 ${right ? "text-right" : "text-left"} align-top`}>{children}</td>;
}
