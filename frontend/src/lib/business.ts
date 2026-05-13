"use client";
import useSWR from "swr";
import { api } from "@/lib/api";

const fetcher = <T,>(p: string) => api<T>(p);

export interface BizClient {
  org_id: string; name: string;
  type: string | null; status: string; tier: string;
  volume_total: number; revenue_total: number;
  started_at: string | null;
  apr_effective_bps: number; apr_effective_pct: number;
  yield_30d_pct: number;
  sparkline: number[];
}
export function useBizClients(filters: { type?: string[]; status?: string[]; tier?: string[] } = {}) {
  const p = new URLSearchParams();
  filters.type?.forEach((t) => p.append("type", t));
  filters.status?.forEach((s) => p.append("status", s));
  filters.tier?.forEach((t) => p.append("tier", t));
  return useSWR<{ items: BizClient[]; total: number }>(
    `/v1/admin/business/clients?${p.toString()}`, fetcher);
}

export interface RevenueSummary {
  revenue_total: number; revenue_mtd: number; revenue_prev_mo: number;
  mom_delta_pct: number | null;
  revenue_ytd: number; revenue_prev_yr: number;
  yoy_delta_pct: number | null; generated_at: string;
}
export function useRevenueSummary() {
  return useSWR<RevenueSummary>("/v1/admin/business/revenue/summary", fetcher);
}

export interface RevenueBreakdownItem {
  concept: "management" | "performance" | "onramp_spread" | "offramp_spread" | "other";
  amount: number; share_pct: number;
}
export function useRevenueBreakdown(period: "mtd" | "ytd" | "all" = "all") {
  return useSWR<{ items: RevenueBreakdownItem[]; total: number; period: string }>(
    `/v1/admin/business/revenue/breakdown?period=${period}`, fetcher);
}

export interface RevenueMonth {
  month: string;
  management: number; performance: number;
  onramp_spread: number; offramp_spread: number;
  other: number; total: number;
}
export function useRevenueByMonth(months = 12) {
  return useSWR<{ items: RevenueMonth[] }>(
    `/v1/admin/business/revenue/by-month?months=${months}`, fetcher);
}

export interface RevenueClient { org_id: string; name: string; revenue: number }
export function useRevenueByClient(limit = 10) {
  return useSWR<{ items: RevenueClient[] }>(
    `/v1/admin/business/revenue/by-client?limit=${limit}`, fetcher);
}

export interface YieldRow {
  org_id: string; name: string; positions: number;
  principal_usd: number; apr_bps: number; apr_pct: number;
  gross_apr_bps: number; gross_apr_pct: number;
  implicit_total_bps: number; implicit_total_pct: number;
  implicit_mgmt_30d_usd: number; implicit_perf_30d_usd: number;
  implicit_spread_30d_usd: number; implicit_total_30d_usd: number;
  accrued_30d: number; accrued_total: number;
  next_payout_at: string | null; next_payout_usd: number;
  benchmark_delta_bps: number;
}
export function useYieldByClient() {
  return useSWR<{ items: YieldRow[]; platform_apr_bps: number; platform_apr_pct: number }>(
    "/v1/admin/business/yield/by-client", fetcher);
}

export interface CohortRow {
  cohort_month: string;
  new_clients: number; active_now: number; churned: number;
  retention_pct: number;
  volume_total: number; revenue_total: number;
  avg_revenue_per_client: number;
}
export interface CohortsResponse {
  items: CohortRow[];
  total: number;
  totals: {
    new_clients: number; active_now: number; churned: number;
    volume_total: number; revenue_total: number;
    retention_pct: number;
  };
}
export function useCohorts(months = 12) {
  return useSWR<CohortsResponse>(
    `/v1/admin/business/cohorts?months=${months}`, fetcher);
}

export const CONCEPT_COLOR: Record<string, string> = {
  management:     "#2563FF",
  performance:    "#22C55E",
  onramp_spread:  "#8DB4FF",
  offramp_spread: "#E07B00",
  other:          "#6B7280",
};
export const CONCEPT_LABEL: Record<string, string> = {
  management:     "Management",
  performance:    "Performance",
  onramp_spread:  "Spread onramp",
  offramp_spread: "Spread offramp",
  other:          "Other",
};
