"use client";
/**
 * StakingTabs — módulo de staking compartido (admin + portal cliente).
 * `base` define el prefijo de endpoints:
 *   admin  → /v1/admin/prosper   (stakings, cms/wallets, cms/cashin, cms/users, emails)
 *   client → /v1/client/staking  (mismos sufijos, mismo acceso por directiva del usuario)
 * i18n: namespace `staking` en messages/{en,es}.json (next-intl).
 */
import { Fragment, useMemo, useState } from "react";
import useSWR from "swr";
import {
  ChevronDown, ChevronRight, Copy, ExternalLink, Loader2, Plus,
  RefreshCw, Search, Wallet,
} from "lucide-react";
import { toast } from "sonner";
import { useLocale, useTranslations } from "next-intl";
import { Badge } from "@prosper/ui";
import { api } from "@/lib/api";

// ---------------------------------------------------------------- helpers

const fetcher = (p: string) => api<any>(p);

export function short(v?: string | null, head = 6, tail = 6): string {
  if (!v) return "—";
  return v.length <= head + tail + 1 ? v : `${v.slice(0, head)}…${v.slice(-tail)}`;
}

export function fmtAmount(v: unknown, asset?: string, loc = "es-AR"): string {
  const n = Number(v ?? 0);
  if (!isFinite(n)) return String(v ?? "—");
  const dec = asset === "usdc" ? 2 : 0;
  return n.toLocaleString(loc, { minimumFractionDigits: dec, maximumFractionDigits: dec });
}

export function fmtDate(v?: string | null, loc = "es-AR"): string {
  if (!v) return "—";
  try { return new Date(v).toLocaleString(loc, { dateStyle: "short", timeStyle: "short" }); }
  catch { return v; }
}

export function copyText(text: string, message: string) {
  navigator.clipboard.writeText(text).then(() => toast.success(message));
}

export function useLoc(): string {
  const locale = useLocale();
  return locale === "en" ? "en-US" : "es-AR";
}

const EXPERT = "https://stellar.expert/explorer/public";

const PAGE_SIZE = 10;

function Pager({ page, total, onPage, testid }:
  { page: number; total: number; onPage: (p: number) => void; testid: string }) {
  const t = useTranslations("staking.pager");
  const pages = Math.max(1, Math.ceil(total / PAGE_SIZE));
  if (total <= PAGE_SIZE) return null;
  const from = page * PAGE_SIZE + 1;
  const to = Math.min(total, (page + 1) * PAGE_SIZE);
  const btn = "rounded-md border border-[rgb(var(--border))] px-2.5 py-1 text-xs hover:bg-[rgb(var(--surface-hover))] disabled:opacity-40 disabled:cursor-not-allowed";
  return (
    <div className="flex items-center justify-between mt-3" data-testid={testid}>
      <span className="text-xs text-[rgb(var(--fg-muted))]" data-testid={`${testid}-info`}>
        {t("info", { from, to, total })}
      </span>
      <div className="flex items-center gap-1.5">
        <button className={btn} disabled={page === 0} onClick={() => onPage(page - 1)}
                data-testid={`${testid}-prev`}>{t("prev")}</button>
        <span className="text-xs text-[rgb(var(--fg-muted))] px-1">
          {page + 1} / {pages}
        </span>
        <button className={btn} disabled={page >= pages - 1} onClick={() => onPage(page + 1)}
                data-testid={`${testid}-next`}>{t("next")}</button>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------- types

interface StakingRow {
  position_id?: string; org_id?: string; asset?: string; modality?: string;
  principal_native?: number; status?: string; wallet?: string; memo?: string;
  hash?: string; external?: boolean; created_at?: string; updated_at?: string;
  maturity?: string | null; start?: string | null; rate?: number;
  apr_bps?: number; claimed_interest?: number; accrued_interest?: number;
  principal_redeemed?: number; projected_interest?: number;
  daily_interest?: number; next_payout?: string | number | null;
  contract_id?: string; contract_email?: string; deposit_hash?: string;
  contract_provides_interest?: boolean;
}
interface StakingsResp {
  ours: { items: StakingRow[]; by_org: { org_id: string; name: string;
    principal_arsa: number; principal_usdc: number; active_count: number }[];
    total: number };
  external: { items: StakingRow[]; total: number; note: string };
  total: number; fetched_at: string;
}
interface CmsWalletRow {
  prosperId?: string; userId?: string; email?: string | null;
  address?: string; cashin?: string; integration?: string;
  [k: string]: unknown;
}
interface CmsWalletsResp {
  items: CmsWalletRow[]; total: number; mode: string; fetched_at: string;
}
interface CashinResp {
  prosper_id: string; email?: string; modality: string;
  asset?: string | null; address: string; status: string; reused: boolean;
}

function Detail({ label, value, mono }:
  { label: string; value: string; mono?: boolean }) {
  return (
    <div>
      <p className="text-[10px] uppercase tracking-wider text-[rgb(var(--fg-muted))]">{label}</p>
      <p className={`mt-0.5 ${mono ? "font-mono text-[11px]" : ""}`}>{value}</p>
    </div>
  );
}
// ---------------------------------------------------------------- stakings

function StakingsTab({ base }: { base: string }) {
  const t = useTranslations("staking");
  const loc = useLoc();
  const [asset, setAsset] = useState<string>("");
  const [status, setStatus] = useState<string>("");
  const [scope, setScope] = useState<string>("all");
  const [page, setPage] = useState(0);

  const qs = new URLSearchParams({ scope });
  if (asset) qs.set("asset", asset);
  if (status) qs.set("status", status);
  const { data, error, isLoading, mutate } =
    useSWR<StakingsResp>(`${base}/stakings?${qs}`, fetcher,
                          { refreshInterval: 30_000 });

  const rows: (StakingRow & { _ext: boolean })[] = useMemo(() => {
    if (!data) return [];
    return [
      ...data.ours.items.map((r) => ({ ...r, _ext: false })),
      ...data.external.items.map((r) => ({ ...r, _ext: true })),
    ];
  }, [data]);

  const pageRows = useMemo(
    () => rows.slice(page * PAGE_SIZE, (page + 1) * PAGE_SIZE),
    [rows, page]);

  const [open, setOpen] = useState<string | null>(null);
  const rowKey = (r: StakingRow, i: number) => r.position_id || `${r.wallet}-${r.memo}-${i}`;

  const setFilter = (fn: (v: string) => void) => (v: string) => { fn(v); setPage(0); };

  const copyWallet = (w: string) =>
    copyText(w, t("copied", { label: t("wallet") }));

  const sel = "rounded-md border border-[rgb(var(--border))] bg-[rgb(var(--surface))] px-2.5 py-1.5 text-xs";
  return (
    <div data-testid="staking-tab-stakings">
      <div className="flex flex-wrap items-center gap-2 mb-4">
        <select value={scope} onChange={(e) => setFilter(setScope)(e.target.value)} className={sel}
                data-testid="staking-filter-scope">
          <option value="all">{t("filters.scope_all")}</option>
          <option value="ours">{t("filters.scope_ours")}</option>
          <option value="external">{t("filters.scope_external")}</option>
        </select>
        <select value={asset} onChange={(e) => setFilter(setAsset)(e.target.value)} className={sel}
                data-testid="staking-filter-asset">
          <option value="">{t("filters.asset_all")}</option>
          <option value="arsa">ARSa</option>
          <option value="usdc">USDC</option>
        </select>
        <select value={status} onChange={(e) => setFilter(setStatus)(e.target.value)} className={sel}
                data-testid="staking-filter-status">
          <option value="">{t("filters.status_all")}</option>
          <option value="active">{t("filters.status_active")}</option>
          <option value="matured">{t("filters.status_matured")}</option>
          <option value="redeemed">{t("filters.status_redeemed")}</option>
        </select>
        <button onClick={() => mutate()} className={`${sel} inline-flex items-center gap-1 hover:bg-[rgb(var(--surface-hover))]`}
                data-testid="staking-refresh-btn">
          <RefreshCw size={12} /> {t("filters.refresh")}
        </button>
        <span className="ml-auto text-xs text-[rgb(var(--fg-muted))]" data-testid="staking-total">
          {data ? t("list.total", { count: data.total }) : ""}
        </span>
      </div>

      {error && <p className="text-sm text-red-500" data-testid="staking-list-error">{t("list.error", { msg: String((error as any)?.message || error) })}</p>}
      {isLoading && <p className="text-sm text-[rgb(var(--fg-muted))]">{t("list.loading")}</p>}

      {data && scope !== "external" && data.ours.by_org.length > 0 && (
        <div className="flex flex-wrap gap-2 mb-4" data-testid="staking-by-org">
          {data.ours.by_org.map((g) => (
            <div key={g.org_id}
                 className="rounded-lg border border-[rgb(var(--border))] bg-[rgb(var(--surface))] px-3 py-2"
                 data-testid={`staking-by-org-${g.org_id}`}>
              <p className="text-xs font-medium">{g.name}</p>
              <p className="text-[11px] text-[rgb(var(--fg-muted))] font-mono mt-0.5">
                {g.principal_arsa > 0 && <>ARSa {fmtAmount(g.principal_arsa, "arsa", loc)} · </>}
                {g.principal_usdc > 0 && <>USDC {fmtAmount(g.principal_usdc, "usdc", loc)} · </>}
                {t("list.active_count", { count: g.active_count })}
              </p>
            </div>
          ))}
        </div>
      )}

      {data && rows.length === 0 && (
        <p className="text-sm text-[rgb(var(--fg-muted))] py-8 text-center" data-testid="staking-empty">
          {t("list.empty")}
        </p>
      )}

      {rows.length > 0 && (
        <div className="overflow-x-auto rounded-lg border border-[rgb(var(--border))]">
          <table className="w-full text-sm" data-testid="staking-table">
            <thead>
              <tr className="text-left text-[10px] uppercase tracking-wider text-[rgb(var(--fg-muted))] border-b border-[rgb(var(--border))]">
                <th className="px-2 py-2 w-8"></th>
                <th className="px-3 py-2">{t("table.client")}</th>
                <th className="px-3 py-2">{t("table.asset")}</th>
                <th className="px-3 py-2">{t("table.modality")}</th>
                <th className="px-3 py-2 text-right">{t("table.principal")}</th>
                <th className="px-3 py-2 text-right">{t("table.rate")}</th>
                <th className="px-3 py-2">{t("table.status")}</th>
                <th className="px-3 py-2">{t("table.maturity")}</th>
                <th className="px-3 py-2">{t("table.wallet")}</th>
                <th className="px-3 py-2">{t("table.hash")}</th>
                <th className="px-3 py-2">{t("table.origin")}</th>
              </tr>
            </thead>
            <tbody>
              {pageRows.map((r, i) => {
                const k = rowKey(r, i);
                const isOpen = open === k;
                return (
                  <Fragment key={k}>
                    <tr onClick={() => setOpen(isOpen ? null : k)}
                        className="border-b border-[rgb(var(--border))] last:border-0 hover:bg-[rgb(var(--surface-hover))] cursor-pointer"
                        data-testid={`staking-row-${i}`}>
                      <td className="px-2 py-2 text-[rgb(var(--fg-muted))]"
                          data-testid={`staking-row-expand-${i}`}>
                        {isOpen ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
                      </td>
                      <td className="px-3 py-2 text-xs">{r.contract_email || "—"}</td>
                      <td className="px-3 py-2 font-mono uppercase">{r.asset || "—"}</td>
                      <td className="px-3 py-2">{r.modality || "—"}</td>
                      <td className="px-3 py-2 text-right font-mono">{fmtAmount(r.principal_native, r.asset, loc)}</td>
                      <td className="px-3 py-2 text-right font-mono">
                        {r.rate != null ? `${r.rate}%` : r.apr_bps != null ? `${r.apr_bps / 100}%` : "—"}
                      </td>
                      <td className="px-3 py-2"><Badge tone="auto" size="sm">
                        {r.status && ["active", "matured", "redeemed"].includes(r.status)
                          ? t(`status_values.${r.status}`) : (r.status || "—")}
                      </Badge></td>
                      <td className="px-3 py-2 text-xs">{r.maturity ? fmtDate(r.maturity, loc).split(",")[0] : "—"}</td>
                      <td className="px-3 py-2 font-mono text-xs">
                        {r.wallet ? (
                          <button onClick={(e) => { e.stopPropagation(); copyWallet(r.wallet!); }}
                                  className="hover:underline">
                            {short(r.wallet)}
                          </button>
                        ) : "—"}
                      </td>
                      <td className="px-3 py-2 font-mono text-xs">
                        {r.hash ? (
                          <a href={`${EXPERT}/tx/${r.hash}`} target="_blank" rel="noreferrer"
                             onClick={(e) => e.stopPropagation()}
                             className="inline-flex items-center gap-1 hover:underline">
                            {short(r.hash, 6, 4)} <ExternalLink size={10} />
                          </a>
                        ) : "—"}
                      </td>
                      <td className="px-3 py-2">
                        <Badge tone={r._ext ? "warning" : "primary"} size="sm">
                          {r._ext ? t("table.external") : t("table.ours")}
                        </Badge>
                      </td>
                    </tr>
                    {isOpen && (
                      <tr className="border-b border-[rgb(var(--border))] bg-[rgb(var(--surface))]"
                          data-testid={`staking-row-detail-${i}`}>
                        <td colSpan={11} className="px-4 py-3">
                          <div className="grid grid-cols-2 md:grid-cols-4 gap-x-6 gap-y-2 text-xs">
                            <Detail label={t("detail.start")} value={fmtDate(r.start, loc)} />
                            <Detail label={t("detail.maturity")} value={fmtDate(r.maturity, loc)} />
                            <Detail label={t("detail.accrued")}
                                    value={r.accrued_interest != null
                                      ? fmtAmount(r.accrued_interest, r.asset, loc)
                                      : t("detail.accrued_na")} />
                            <Detail label={t("detail.claimed")} value={fmtAmount(r.claimed_interest, r.asset, loc)} />
                            <Detail label={t("detail.projected")}
                                    value={r.projected_interest != null ? fmtAmount(r.projected_interest, r.asset, loc) : "—"} />
                            <Detail label={t("detail.daily")}
                                    value={r.daily_interest != null ? fmtAmount(r.daily_interest, r.asset, loc) : "—"} />
                            <Detail label={t("detail.next_payout")}
                                    value={r.next_payout != null
                                      ? (typeof r.next_payout === "object"
                                          ? `${fmtDate((r.next_payout as any).fecha, loc)} · ${fmtAmount((r.next_payout as any).monto, r.asset, loc)} ${(r.asset || "").toUpperCase()}`
                                          : String(r.next_payout))
                                      : "—"} />
                            <Detail label={t("detail.redeemed")} value={fmtAmount(r.principal_redeemed, r.asset, loc)} />
                            <Detail label={t("detail.memo")} value={r.memo || "—"} mono />
                            <Detail label={t("detail.org")} value={r.org_id || t("detail.org_external")} mono />
                            <Detail label={t("detail.position_id")} value={r.position_id || "—"} mono />
                            <Detail label={t("detail.created_updated")}
                                    value={`${fmtDate(r.created_at, loc)} · ${fmtDate(r.updated_at, loc)}`} />
                            <div className="col-span-2 md:col-span-4 flex flex-wrap gap-4 mt-1">
                              {r.wallet && (
                                <button onClick={(e) => { e.stopPropagation(); copyWallet(r.wallet!); }}
                                        className="inline-flex items-center gap-1 font-mono text-[11px] hover:underline">
                                  <Copy size={10} /> {t("table.wallet")}: {r.wallet}
                                </button>
                              )}
                              {r.contract_id && (
                                <a href={`${EXPERT}/contract/${r.contract_id}`} target="_blank" rel="noreferrer"
                                   onClick={(e) => e.stopPropagation()}
                                   className="inline-flex items-center gap-1 font-mono text-[11px] hover:underline">
                                  <ExternalLink size={10} /> {t("detail.contract")}: {short(r.contract_id, 8, 8)}
                                </a>
                              )}
                              {r.deposit_hash && (
                                <a href={`${EXPERT}/tx/${r.deposit_hash}`} target="_blank" rel="noreferrer"
                                   onClick={(e) => e.stopPropagation()}
                                   className="inline-flex items-center gap-1 font-mono text-[11px] hover:underline">
                                  <ExternalLink size={10} /> {t("detail.deposit_hash")}: {short(r.deposit_hash, 8, 8)}
                                </a>
                              )}
                            </div>
                          </div>
                        </td>
                      </tr>
                    )}
                  </Fragment>
                );
              })}
            </tbody>
          </table>
        </div>
      )}

      {rows.length > 0 && (
        <Pager page={page} total={rows.length} onPage={setPage} testid="staking-pager" />
      )}

      {data && data.external.total > 0 && scope !== "ours" && (
        <p className="mt-3 text-[11px] text-[rgb(var(--fg-muted))]">{t("list.external_note")}</p>
      )}
    </div>
  );
}

// ---------------------------------------------------------------- wallets

function WalletsTab({ base, onRequestCashin }:
  { base: string; onRequestCashin: (email: string) => void }) {
  const t = useTranslations("staking");
  const { data, error, isLoading, mutate } =
    useSWR<CmsWalletsResp>(`${base}/cms/wallets`, fetcher);
  const [q, setQ] = useState("");
  const [page, setPage] = useState(0);
  const [newEmail, setNewEmail] = useState("");
  const [creating, setCreating] = useState(false);

  const copyWallet = (w: string) =>
    copyText(w, t("copied", { label: t("wallet") }));

  const createAccount = async () => {
    const email = newEmail.trim();
    if (!email || !email.includes("@")) { toast.error(t("wallets.invalid_email")); return; }
    setCreating(true);
    try {
      const r = await api<{ email: string; user_id: number }>(
        `${base}/cms/users`,
        { method: "POST", body: JSON.stringify({ email }) });
      toast.success(t("wallets.account_created", { id: r.user_id ?? "—" }));
      setNewEmail("");
      mutate();
    } catch (e: any) {
      toast.error(e?.message || t("wallets.account_failed"));
    } finally { setCreating(false); }
  };

  const items = useMemo(() => {
    const rows = data?.items || [];
    const needle = q.trim().toLowerCase();
    if (!needle) return rows;
    return rows.filter((r) =>
      [r.prosperId, r.userId, r.email, r.address, r.cashin]
        .some((v) => String(v || "").toLowerCase().includes(needle)));
  }, [data, q]);

  const pageItems = useMemo(
    () => items.slice(page * PAGE_SIZE, (page + 1) * PAGE_SIZE),
    [items, page]);

  return (
    <div data-testid="staking-tab-wallets">
      <div className="flex flex-wrap items-center gap-2 mb-3 rounded-lg border border-[rgb(var(--border))] bg-[rgb(var(--surface))] p-3"
           data-testid="staking-create-account-box">
        <p className="text-xs uppercase tracking-wider text-[rgb(var(--fg-muted))] w-full sm:w-auto">
          {t("wallets.new_account")}
        </p>
        <input value={newEmail} onChange={(e) => setNewEmail(e.target.value)}
               onKeyDown={(e) => e.key === "Enter" && createAccount()}
               placeholder={t("wallets.email_placeholder")}
               className="rounded-md border border-[rgb(var(--border))] bg-[rgb(var(--surface))] px-3 py-1.5 text-xs font-mono w-72"
               data-testid="staking-create-account-email" />
        <button onClick={createAccount} disabled={creating}
                className="inline-flex items-center gap-1.5 rounded-md bg-[#2B6BFF] text-white px-3 py-1.5 text-xs hover:opacity-90 disabled:opacity-50"
                data-testid="staking-create-account-btn">
          {creating ? <Loader2 size={12} className="animate-spin" /> : <Plus size={12} />}
          {t("wallets.create_account")}
        </button>
        <span className="text-[11px] text-[rgb(var(--fg-muted))]">
          {t("wallets.create_hint")}
        </span>
      </div>

      <div className="flex items-center gap-2 mb-4">
        <div className="relative">
          <Search size={13} className="absolute left-2.5 top-1/2 -translate-y-1/2 text-[rgb(var(--fg-muted))]" />
          <input value={q} onChange={(e) => setQ(e.target.value)}
                 placeholder={t("wallets.search_placeholder")}
                 className="rounded-md border border-[rgb(var(--border))] bg-[rgb(var(--surface))] pl-8 pr-3 py-1.5 text-xs w-72"
                 data-testid="staking-wallets-search" />
        </div>
        <button onClick={() => mutate()}
                className="inline-flex items-center gap-1 rounded-md border border-[rgb(var(--border))] px-2.5 py-1.5 text-xs hover:bg-[rgb(var(--surface-hover))]"
                data-testid="staking-wallets-refresh">
          <RefreshCw size={12} /> {t("filters.refresh")}
        </button>
        <span className="ml-auto text-xs text-[rgb(var(--fg-muted))]" data-testid="staking-wallets-total">
          {data ? t("wallets.total", { shown: items.length, total: data.total, mode: data.mode }) : ""}
        </span>
      </div>

      {error && <p className="text-sm text-red-500" data-testid="staking-wallets-error">{t("wallets.error", { msg: String((error as any)?.message || error) })}</p>}
      {isLoading && <p className="text-sm text-[rgb(var(--fg-muted))]">{t("wallets.loading")}</p>}

      {data && items.length === 0 && !error && (
        <p className="text-sm text-[rgb(var(--fg-muted))] py-8 text-center" data-testid="staking-wallets-empty">
          {t("wallets.empty")}
        </p>
      )}

      {items.length > 0 && (
        <div className="overflow-x-auto rounded-lg border border-[rgb(var(--border))]">
          <table className="w-full text-sm" data-testid="staking-wallets-table">
            <thead>
              <tr className="text-left text-[10px] uppercase tracking-wider text-[rgb(var(--fg-muted))] border-b border-[rgb(var(--border))]">
                <th className="px-3 py-2">{t("wallets.col_prosper_id")}</th>
                <th className="px-3 py-2">{t("wallets.col_email")}</th>
                <th className="px-3 py-2">{t("wallets.col_modality")}</th>
                <th className="px-3 py-2">{t("wallets.col_wallet")}</th>
                <th className="px-3 py-2">{t("wallets.col_integration")}</th>
                <th className="px-3 py-2 text-right">{t("wallets.col_actions")}</th>
              </tr>
            </thead>
            <tbody>
              {pageItems.map((r, i) => (
                <tr key={`${r.address}-${i}`}
                    className="border-b border-[rgb(var(--border))] last:border-0 hover:bg-[rgb(var(--surface-hover))]"
                    data-testid={`staking-wallet-row-${i}`}>
                  <td className="px-3 py-2 font-mono text-xs">{r.prosperId || r.userId || "—"}</td>
                  <td className="px-3 py-2 text-xs">{r.email || "—"}</td>
                  <td className="px-3 py-2">
                    <Badge tone={r.cashin === "month" ? "info" : "default"} size="sm">
                      {r.cashin || "—"}
                    </Badge>
                  </td>
                  <td className="px-3 py-2 font-mono text-xs">
                    {r.address ? (
                      <span className="inline-flex items-center gap-1.5">
                        <button onClick={() => copyWallet(r.address!)} className="hover:underline">
                          {short(r.address, 8, 8)}
                        </button>
                        <button onClick={() => copyWallet(r.address!)} title={t("wallets.copy")}>
                          <Copy size={11} className="text-[rgb(var(--fg-muted))]" />
                        </button>
                        <a href={`${EXPERT}/account/${r.address}`} target="_blank" rel="noreferrer" title={t("wallets.view_expert")}>
                          <ExternalLink size={11} className="text-[rgb(var(--fg-muted))]" />
                        </a>
                      </span>
                    ) : "—"}
                  </td>
                  <td className="px-3 py-2 text-xs text-[rgb(var(--fg-muted))]">{r.integration || "—"}</td>
                  <td className="px-3 py-2 text-right">
                    <button
                      onClick={() => onRequestCashin(String(r.email || r.prosperId || r.userId || ""))}
                      disabled={!(r.email || r.prosperId || r.userId)}
                      className="inline-flex items-center gap-1 rounded-md border border-[rgb(var(--border))] px-2 py-1 text-[11px] hover:bg-[rgb(var(--surface-hover))] disabled:opacity-40"
                      title={t("wallets.new_request_title")}
                      data-testid={`staking-wallet-cashin-btn-${i}`}>
                      <Plus size={11} /> {t("wallets.new_request")}
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {items.length > 0 && (
        <Pager page={page} total={items.length} onPage={setPage} testid="staking-wallets-pager" />
      )}
    </div>
  );
}

// ---------------------------------------------------------------- cash-in

function NewCashinTab({ base, onCreated, initialProsperId }:
  { base: string; onCreated: () => void; initialProsperId?: string }) {
  const t = useTranslations("staking");
  const [email, setEmail] = useState(initialProsperId || "");
  const [modality, setModality] = useState<"end" | "month">("end");
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<CashinResp | null>(null);
  const { data: emailsData } = useSWR<{ emails: string[] }>(`${base}/emails`, fetcher);
  const { data: walletsData } = useSWR<CmsWalletsResp>(`${base}/cms/wallets`, fetcher);
  const emailOptions = useMemo(() => {
    const set = new Set<string>(emailsData?.emails || []);
    (walletsData?.items || []).forEach((w) => { if (w.email) set.add(String(w.email).toLowerCase()); });
    return Array.from(set).sort();
  }, [emailsData, walletsData]);

  const submit = async () => {
    const mail = email.trim();
    if (!mail || !mail.includes("@")) { toast.error(t("cashin.email_required")); return; }
    setBusy(true);
    setResult(null);
    try {
      const r = await api<CashinResp>(`${base}/cms/cashin`, {
        method: "POST",
        body: JSON.stringify({ email: mail, modality }),
      });
      setResult(r);
      toast.success(r.reused ? t("cashin.success_reused") : t("cashin.success_created"));
      onCreated();
    } catch (e: any) {
      toast.error(e?.message || t("cashin.failed"));
    } finally { setBusy(false); }
  };

  const modBtn = (m: "end" | "month", label: string, desc: string) => (
    <button type="button" onClick={() => setModality(m)}
            className={`flex-1 rounded-lg border p-3 text-left transition-colors ${
              modality === m
                ? "border-[#2B6BFF] bg-[color-mix(in_srgb,#2B6BFF_8%,transparent)]"
                : "border-[rgb(var(--border))] hover:bg-[rgb(var(--surface-hover))]"}`}
            data-testid={`staking-cashin-modality-${m}`}>
      <p className="text-sm font-medium">{label}</p>
      <p className="text-[11px] text-[rgb(var(--fg-muted))] mt-0.5">{desc}</p>
    </button>
  );

  return (
    <div className="max-w-xl" data-testid="staking-tab-cashin">
      <p className="text-sm text-[rgb(var(--fg-muted))] mb-4">
        {t("cashin.intro")}
      </p>

      <label className="block text-xs uppercase tracking-wider text-[rgb(var(--fg-muted))] mb-1.5">
        {t("cashin.email_label")}
      </label>
      <input value={email} onChange={(e) => setEmail(e.target.value)}
             type="email"
             list="staking-cashin-email-options"
             placeholder={t("cashin.email_placeholder")}
             className="w-full rounded-md border border-[rgb(var(--border))] bg-[rgb(var(--surface))] px-3 py-2 text-sm font-mono mb-4"
             data-testid="staking-cashin-prosperid" />
      <datalist id="staking-cashin-email-options" data-testid="staking-cashin-email-options">
        {emailOptions.map((e) => <option key={e} value={e} />)}
      </datalist>

      <label className="block text-xs uppercase tracking-wider text-[rgb(var(--fg-muted))] mb-1.5">
        {t("cashin.modality_label")}
      </label>
      <div className="flex gap-3 mb-5">
        {modBtn("end", t("cashin.mod_end_label"), t("cashin.mod_end_desc"))}
        {modBtn("month", t("cashin.mod_month_label"), t("cashin.mod_month_desc"))}
      </div>

      <button onClick={submit} disabled={busy}
              className="inline-flex items-center gap-2 rounded-md bg-[#2B6BFF] text-white px-4 py-2 text-sm hover:opacity-90 disabled:opacity-50"
              data-testid="staking-cashin-submit">
        {busy ? <Loader2 size={14} className="animate-spin" /> : <Plus size={14} />}
        {t("cashin.submit")}
      </button>

      {result && (
        <div className="mt-5 rounded-lg border border-[rgb(var(--border))] bg-[rgb(var(--surface))] p-4"
             data-testid="staking-cashin-result">
          <div className="flex items-center gap-2 mb-2">
            <Wallet size={15} />
            <p className="text-sm font-medium">
              {result.reused ? t("cashin.wallet_reused") : t("cashin.wallet_assigned")}
            </p>
            <Badge tone="auto" size="sm">{result.status}</Badge>
          </div>
          <p className="text-xs text-[rgb(var(--fg-muted))]">
            {t("cashin.result_meta", {
              email: result.email || result.prosper_id,
              modality: result.modality })}
          </p>
          <div className="mt-2 flex items-center gap-2">
            <code className="text-xs font-mono break-all" data-testid="staking-cashin-address">
              {result.address || t("cashin.address_pending")}
            </code>
            {result.address && (
              <>
                <button onClick={() => copyText(result.address, t("copied", { label: t("wallet") }))} title={t("wallets.copy")}>
                  <Copy size={12} className="text-[rgb(var(--fg-muted))]" />
                </button>
                <a href={`${EXPERT}/account/${result.address}`} target="_blank" rel="noreferrer">
                  <ExternalLink size={12} className="text-[rgb(var(--fg-muted))]" />
                </a>
              </>
            )}
          </div>
          {result.address && (
            <p className="mt-2 text-[11px] text-[rgb(var(--fg-muted))]" data-testid="staking-cashin-instructions">
              {t("cashin.instructions")}
            </p>
          )}
        </div>
      )}
    </div>
  );
}
// ---------------------------------------------------------------- module

type Tab = "stakings" | "wallets" | "cashin";

export const StakingTabs = ({ base }: { base: string }) => {
  const t = useTranslations("staking.tabs");
  const [tab, setTab] = useState<Tab>("stakings");
  const [walletsVersion, setWalletsVersion] = useState(0);
  const [cashinPrefill, setCashinPrefill] = useState("");

  const goToCashin = (email: string) => {
    setCashinPrefill(email);
    setTab("cashin");
  };

  const tabBtn = (tb: Tab, label: string, testid: string) => (
    <button onClick={() => setTab(tb)}
            className={`px-3 py-1.5 rounded-md text-sm transition-colors ${
              tab === tb
                ? "bg-[rgb(var(--surface-hover))] font-medium"
                : "text-[rgb(var(--fg-muted))] hover:text-[rgb(var(--fg))]"}`}
            data-testid={testid}>
      {label}
    </button>
  );

  return (
    <div data-testid="staking-tabs">
      <div className="flex items-center gap-1.5 mb-4 border-b border-[rgb(var(--border))] pb-2">
        {tabBtn("stakings", t("stakings"), "staking-tab-btn-stakings")}
        {tabBtn("wallets", t("wallets"), "staking-tab-btn-wallets")}
        {tabBtn("cashin", t("cashin"), "staking-tab-btn-cashin")}
      </div>

      {tab === "stakings" && <StakingsTab base={base} />}
      {tab === "wallets" && <WalletsTab key={walletsVersion} base={base} onRequestCashin={goToCashin} />}
      {tab === "cashin" && (
        <NewCashinTab key={cashinPrefill || "manual"}
                      base={base}
                      initialProsperId={cashinPrefill}
                      onCreated={() => setWalletsVersion((v) => v + 1)} />
      )}
    </div>
  );
};
