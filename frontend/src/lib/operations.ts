"use client";
import useSWR from "swr";
import { api } from "@/lib/api";

const fetcher = <T,>(p: string) => api<T>(p);

export type LifecycleStatus = "ok" | "error" | "pending" | "skipped";
export interface LifecycleStep {
  step_id: string;
  title: string;
  status: LifecycleStatus;
  timestamp: string;
  details: Record<string, any>;
  payload?: Record<string, any> | null;
  retry_requested_by?: string;
  retry_requested_at?: string;
}

export interface TxRow {
  tx_id: string; prosper_tx_id: string;
  org_id: string; org_name: string;
  type: "subscribe" | "redeem" | "mint" | "transfer" | "onramp" | "offramp" | string;
  amount: number; asset: string;
  status: "confirmed" | "pending" | "failed" | string;
  fee_amount: number;
  tx_hash?: string | null;
  memo?: string;
  created_at: string;
}

export interface TxList {
  items: TxRow[]; total: number; page: number; limit: number; pages: number;
}

export interface TxFilters {
  type?: string[]; status?: string[]; org_id?: string;
  date_from?: string; date_to?: string;
  search?: string; only_errors?: boolean;
  page?: number; limit?: number;
}

function qs(f: TxFilters): string {
  const p = new URLSearchParams();
  f.type?.forEach((t) => p.append("type", t));
  f.status?.forEach((s) => p.append("status", s));
  if (f.org_id)    p.set("org_id", f.org_id);
  if (f.date_from) p.set("date_from", f.date_from);
  if (f.date_to)   p.set("date_to", f.date_to);
  if (f.search)    p.set("search", f.search);
  if (f.only_errors) p.set("only_errors", "true");
  p.set("page",  String(f.page  ?? 1));
  p.set("limit", String(f.limit ?? 50));
  return p.toString();
}

export function useTransactions(filters: TxFilters) {
  return useSWR<TxList>(`/v1/admin/transactions?${qs(filters)}`, fetcher,
    { keepPreviousData: true });
}

export interface LifecyclePayload {
  transaction: TxRow & { lifecycle?: LifecycleStep[] };
  org: { org_id: string; commercial_name?: string; legal_name?: string };
  lifecycle: LifecycleStep[];
}

export function useLifecycle(txId: string | null) {
  return useSWR<LifecyclePayload>(
    txId ? `/v1/admin/transactions/${txId}/lifecycle` : null, fetcher,
    { refreshInterval: 15_000 });
}

export interface FundsState {
  fund: {
    fund_id: string; name: string;
    nav: number; nav_delta_24h: number | null;
    supply_circulating: number;
    invested_usd: number;
    treasury_usd: number;
    positions: number;
    asset_code: string;
  };
  stellar_accounts: { label: string; address: string;
                      balance_usd: number; balance_xlm: number;
                      is_native?: boolean }[];
  xlm_reserve_total: number;
  generated_at: string;
}
export function useFundsState() {
  return useSWR<FundsState>("/v1/admin/funds/state", fetcher,
    { refreshInterval: 30_000 });
}

export interface UpstreamStatus {
  enabled: boolean; reachable: boolean; authenticated: boolean;
  environment: string; upstream_url: string; note?: string; checked_at: string;
}
export function useUpstreamStatus() {
  return useSWR<UpstreamStatus>("/v1/admin/prosper-upstream/status", fetcher,
    { refreshInterval: 60_000 });
}

export interface ByClientRow {
  org_id: string; org_name: string;
  total: number; ok: number; failed: number;
  success_pct: number; failed_pct: number;
  last_at: string; sparkline: number[];
}
export function useByClientStats() {
  return useSWR<{ items: ByClientRow[] }>(
    "/v1/admin/operations/by-client/stats", fetcher);
}

export interface VolByClientRow {
  org_id: string; org_name: string;
  vol_24h: number; vol_7d: number; vol_30d: number;
  vol_total: number; vol_prev_30d: number;
  delta_pct_30d: number; share_pct_30d: number;
}
export function useVolumeByClient() {
  return useSWR<{ items: VolByClientRow[]; total_volume_30d: number }>(
    "/v1/admin/operations/volume-by-client", fetcher);
}

export function csvExportUrl(filters: TxFilters): string {
  // returns an API URL that, when navigated, downloads the CSV
  const u = new URLSearchParams(qs(filters));
  u.delete("page"); u.delete("limit");
  return `/api/v1/admin/transactions/export.csv?${u.toString()}`;
}

export async function retryStep(txId: string, stepId: string) {
  return api(`/v1/admin/transactions/${txId}/retry-step?step_id=${stepId}`,
             { method: "POST" });
}
