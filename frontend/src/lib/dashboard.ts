"use client";
import useSWR from "swr";
import { api } from "@/lib/api";

const fetcher = <T,>(path: string) => api<T>(path);

const REFRESH_60S = { refreshInterval: 60_000, revalidateOnFocus: true };

export interface DashboardKpis {
  aum_usd: number;
  aum_delta_24h: number | null;
  revenue_mtd: number;
  revenue_ytd: number;
  active_clients: number;
  volume_30d: number;
  operations_queue: number;
  supply_circulating: number;
  nav: number;
  nav_delta_24h: number | null;
}

export interface VolumePoint { date: string; subscribe: number; redeem: number }
export interface NavPoint    { date: string; nav: number }
export interface RevenuePoint { month: string; revenue: number }
export interface TopClient   { org_id: string; name: string; aum: number; positions_count: number }

export interface OpsQueueItem {
  approval_id?: string; alert_id?: string; org_id?: string;
  type?: string; severity?: string; kyb_status?: string;
  commercial_name?: string; created_at?: string;
}
export interface OpsQueueGroup { count: number; items: OpsQueueItem[] }
export interface OpsQueue {
  approvals: OpsQueueGroup; kyb: OpsQueueGroup; alerts: OpsQueueGroup;
  webhook_failing: OpsQueueGroup; reconciliation: OpsQueueGroup;
  generated_at: string;
}

export function useDashboardKpis(days = 30) {
  return useSWR<DashboardKpis>(`/v1/admin/dashboard/kpis?days=${days}`, fetcher, REFRESH_60S);
}
export function useNavHistory(days = 90) {
  return useSWR<{ items: NavPoint[] }>(`/v1/admin/dashboard/nav-history?days=${days}`, fetcher, REFRESH_60S);
}
export function useVolume(days = 30) {
  return useSWR<{ items: VolumePoint[] }>(`/v1/admin/dashboard/volume?days=${days}`, fetcher, REFRESH_60S);
}
export function useRevenue(months = 12) {
  return useSWR<{ items: RevenuePoint[] }>(`/v1/admin/dashboard/revenue?months=${months}`, fetcher, REFRESH_60S);
}
export function useTopClients(limit = 10) {
  return useSWR<{ items: TopClient[] }>(`/v1/admin/dashboard/top-clients?limit=${limit}`, fetcher, REFRESH_60S);
}
export function useOpsQueue() {
  return useSWR<OpsQueue>(`/v1/admin/dashboard/ops-queue`, fetcher, { refreshInterval: 30_000 });
}
