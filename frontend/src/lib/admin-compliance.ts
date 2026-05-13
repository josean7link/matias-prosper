"use client";
import useSWR from "swr";
import { api } from "@/lib/api";

const fetcher = <T,>(p: string) => api<T>(p);

// ────────── KYC ──────────
export interface KycDocument { label: string; kind: "image" | "pdf"; url: string }
export interface KycCheck { aml: string; sanctions: string; pep: string; travel_rule: string }
export interface KycTimelineEntry { ts: string; by: string; what: string; meta?: Record<string, unknown> }
export interface KycCase {
  case_id: string; first_name: string; last_name: string; email: string;
  country: string; doc_id: string; doc_type: string;
  documents: KycDocument[];
  provider: string; provider_score: number; provider_confidence: number;
  provider_flags: string[]; checks: KycCheck;
  status: string; applied_at: string;
  sla_hours_left: number; sla_color: "red" | "amber" | "green";
  org_id: string | null; timeline: KycTimelineEntry[];
}
export function useKycQueue(filters: { status?: string[]; provider?: string[] } = {}) {
  const p = new URLSearchParams();
  filters.status?.forEach((s) => p.append("status", s));
  filters.provider?.forEach((s) => p.append("provider", s));
  return useSWR<{ items: KycCase[]; total: number }>(
    `/v1/admin/compliance/kyc/queue?${p}`, fetcher);
}
export function useKycCase(caseId: string | null) {
  return useSWR<KycCase>(
    caseId ? `/v1/admin/compliance/kyc/${caseId}` : null, fetcher);
}
export async function decideKyc(caseId: string,
    body: { action: "approve" | "reject" | "request_info"; reason: string }) {
  return api(`/v1/admin/compliance/kyc/${caseId}/decision`, {
    method: "POST", body: JSON.stringify(body) });
}

// ────────── KYB ──────────
export interface Ubo { name: string; ownership_pct: number;
  nationality: string; is_pep: boolean; verified: boolean }
export interface ChecklistItem { key: string; label: string; checked: boolean;
  checked_by?: string | null; checked_at?: string | null }
export interface KybCase {
  case_id: string; legal_name: string; commercial_name: string;
  country: string; type: string; tax_id: string; incorporation_date: string;
  documents: KycDocument[]; ubos: Ubo[]; checklist: ChecklistItem[];
  provider: string; provider_score: number; provider_confidence: number;
  provider_flags: string[]; checks: KycCheck;
  status: string; applied_at: string;
  sla_hours_left: number; sla_color: "red" | "amber" | "green";
  timeline: KycTimelineEntry[];
  checklist_progress: { checked: number; total: number; ready_to_approve: boolean };
}
export function useKybQueue() {
  return useSWR<{ items: KybCase[]; total: number }>(
    `/v1/admin/compliance/kyb/queue`, fetcher);
}
export function useKybCase(caseId: string | null) {
  return useSWR<KybCase>(
    caseId ? `/v1/admin/compliance/kyb/${caseId}` : null, fetcher);
}
export async function patchKybChecklist(caseId: string, key: string, checked: boolean) {
  return api(`/v1/admin/compliance/kyb/${caseId}/checklist`, {
    method: "PATCH", body: JSON.stringify({ key, checked }) });
}
export async function decideKyb(caseId: string,
    body: { action: "approve" | "reject" | "request_info"; reason: string }) {
  return api(`/v1/admin/compliance/kyb/${caseId}/decision`, {
    method: "POST", body: JSON.stringify(body) });
}

// ────────── KYT ──────────
export interface KytRule {
  rule_id: string; name: string; description: string;
  enabled: boolean; param_name: string; param_value: number | string;
  param_unit: string; severity: "info" | "warning" | "critical";
}
export function useKytRules() {
  return useSWR<{ items: KytRule[] }>(`/v1/admin/compliance/kyt/rules`, fetcher);
}
export async function patchKytRule(ruleId: string,
    body: Partial<{ enabled: boolean; param_value: number | string;
                    severity: "info" | "warning" | "critical" }>) {
  return api(`/v1/admin/compliance/kyt/rules/${ruleId}`, {
    method: "PATCH", body: JSON.stringify(body) });
}

export interface KytAlert {
  alert_id: string; rule_id: string; rule_name: string;
  severity: "info" | "warning" | "critical";
  status: "open" | "acknowledged" | "resolved";
  tx_id: string; prosper_tx_id: string;
  org_id: string; org_name?: string | null;
  amount: number; score: number;
  assigned_to: string | null;
  created_at: string; updated_at: string;
}
export function useKytAlerts(filters: { severity?: string[]; status?: string[] } = {}) {
  const p = new URLSearchParams();
  filters.severity?.forEach((s) => p.append("severity", s));
  filters.status?.forEach((s) => p.append("status", s));
  return useSWR<{ items: KytAlert[]; total: number }>(
    `/v1/admin/compliance/kyt/alerts?${p}`, fetcher);
}

export interface WatchlistEntry {
  entry_id: string; kind: "wallet" | "client"; value: string;
  reason: string; added_by: string; created_at: string;
}
export function useWatchlist() {
  return useSWR<{ items: WatchlistEntry[]; total: number }>(
    `/v1/admin/compliance/kyt/watchlist`, fetcher);
}
export async function addWatchlist(entry: { kind: "wallet" | "client";
    value: string; reason: string }) {
  return api(`/v1/admin/compliance/kyt/watchlist`, {
    method: "POST", body: JSON.stringify(entry) });
}
export async function screenWallet(address: string) {
  return api<{ address: string; internal_watchlist_hit: boolean;
    internal_entry: WatchlistEntry | null;
    external: { status: string; error_reason?: string;
                risk_score: number | null; is_sanctioned: boolean;
                risks: { category: string; severity: string; label: string; description: string }[];
                entity_type: string | null; entity_name: string | null } }>(
    `/v1/admin/compliance/kyt/screen-wallet`, {
      method: "POST", body: JSON.stringify({ address }) });
}

export interface TravelRuleRow {
  tx_id: string; prosper_tx_id: string; org_id: string; amount: number;
  created_at: string; type: string;
  counterparty_verified?: boolean; counterparty_name?: string | null;
  travel_rule_status: "verified" | "missing";
}
export function useTravelRule() {
  return useSWR<{ items: TravelRuleRow[]; total: number }>(
    `/v1/admin/compliance/kyt/travel-rule`, fetcher);
}

// ────────── Risk ──────────
export interface RiskDriver { key: string; label: string; weight: number; score: number }
export interface RiskClient {
  org_id: string; name: string; score: number;
  profile: "low" | "medium" | "high" | "critical";
  drivers: RiskDriver[];
  volume_30d_usd: number; kyc_age_days: number; refreshed_at: string;
}
export function useRiskOverview() {
  return useSWR<{ distribution: Record<string, number>;
    top10: RiskClient[]; total: number }>(
    `/v1/admin/compliance/risk/overview`, fetcher);
}
export function useRiskClients() {
  return useSWR<{ items: RiskClient[]; total: number }>(
    `/v1/admin/compliance/risk/clients`, fetcher);
}
export function useRiskClient(orgId: string | null) {
  return useSWR<RiskClient>(
    orgId ? `/v1/admin/compliance/risk/clients/${orgId}` : null, fetcher);
}
export async function generateSar(body: { org_id: string; summary: string }) {
  return api(`/v1/admin/compliance/risk/reports/sar`, {
    method: "POST", body: JSON.stringify(body) });
}
export async function generateStr(body: { tx_id: string; summary: string }) {
  return api(`/v1/admin/compliance/risk/reports/str`, {
    method: "POST", body: JSON.stringify(body) });
}

// ────────── Alerts feed ──────────
export interface AlertItem {
  alert_id: string; type: "kyt" | "operational" | "compliance" | "technical";
  severity: "info" | "warning" | "critical";
  title: string; description: string;
  org_id: string | null; org_name?: string | null;
  rule_id: string | null; status: "open" | "acknowledged" | "resolved";
  assigned_to: string | null;
  context: Record<string, unknown>;
  created_at: string; updated_at: string;
}
export function useAlerts(filters: { severity?: string[]; type?: string[]; status?: string[] } = {}) {
  const p = new URLSearchParams();
  filters.severity?.forEach((s) => p.append("severity", s));
  filters.type?.forEach((s) => p.append("type", s));
  filters.status?.forEach((s) => p.append("status", s));
  return useSWR<{ items: AlertItem[]; total: number }>(
    `/v1/admin/alerts?${p}`, fetcher);
}
export function useAlertsSummary() {
  return useSWR<{ open_count: number; open_critical_count: number; latest: AlertItem[] }>(
    `/v1/admin/alerts/summary`, fetcher, { refreshInterval: 30_000 });
}
export async function patchAlert(alertId: string,
    body: Partial<{ status: "open" | "acknowledged" | "resolved";
                    assigned_to: string; note: string }>) {
  return api(`/v1/admin/alerts/${alertId}`, {
    method: "PATCH", body: JSON.stringify(body) });
}
export async function bulkPatchAlerts(body:
    { alert_ids: string[]; status?: "acknowledged" | "resolved"; assigned_to?: string }) {
  return api(`/v1/admin/alerts/bulk`, {
    method: "POST", body: JSON.stringify(body) });
}

// ────────── Limits ──────────
export interface LimitRow {
  org_id: string; name: string;
  type: string | null; country: string | null;
  kyb_status: string;
  subscribe_daily_cap_usd: number; subscribe_monthly_cap_usd: number;
  redeem_daily_cap_usd: number;    redeem_monthly_cap_usd: number;
}
export function useLimits() {
  return useSWR<{ items: LimitRow[]; total: number }>(
    `/v1/admin/compliance/limits`, fetcher);
}
export async function patchLimit(orgId: string,
    key: "subscribe_daily_cap_usd" | "subscribe_monthly_cap_usd"
       | "redeem_daily_cap_usd"    | "redeem_monthly_cap_usd",
    value: number) {
  return api(`/v1/admin/compliance/limits/${orgId}`, {
    method: "PATCH", body: JSON.stringify({ key, value }) });
}
export function useLimitsHistory(orgId: string | null) {
  return useSWR<{ items: { key: string; old_value: number;
    new_value: number; changed_by: string; changed_at: string }[] }>(
    orgId ? `/v1/admin/compliance/limits/${orgId}/history` : null, fetcher);
}
