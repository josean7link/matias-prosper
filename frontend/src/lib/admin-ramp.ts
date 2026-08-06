"use client";
import useSWR from "swr";
import { api } from "@/lib/api";

/** Phase 16 — Admin ramp helpers. All endpoints are at /api/v1/admin/ramp/*
 *  and gated to backoffice roles by the backend. */

export interface ProviderConfigRow {
  scope: string;            // "global" or org_id
  provider: "alfred" | "andeslabs";
  mode: "mock" | "sandbox" | "real";
  enabled: boolean;
  updated_by?: string;
  updated_at?: string;
}
export interface ConnectivityResult {
  provider: string;
  enabled: boolean;
  reachable: boolean;
  authenticated: boolean;
  error: string | null;
  latency_ms?: number;
  details: Record<string, unknown>;
}
export interface AccountKpis {
  total_arsa_under_management: string;
  accounts_active: number;
  accounts_pending_kyc: number;
  accounts_error: number;
}
export interface RampAccountRow {
  id: string;
  org_id: string;
  end_customer_id: string;
  provider: string;
  provider_user_id: string;
  account_name: string | null;
  wallet_address: string | null;
  cvu: string | null;
  alias: string | null;
  cvu_status: string;
  onboarding_status: string;
  onboarding_message: string | null;
  created_at: string;
  updated_at: string;
  arsa_balance: string;
}
export interface AdminMovement {
  id: string;
  org_id: string;
  kind: "deposit" | "withdrawal" | "transfer" | "intl_offramp";
  asset: string;
  chain: string;
  amount: string;
  status: "Pending" | "TransferPending" | "Success" | "Failed";
  destination_cvu: string | null;
  destination_alias: string | null;
  destination_name: string | null;
  external_id: string | null;
  prosper_tx_id: string | null;
  fail_reason: string | null;
  created_at: string;
  settled_at: string | null;
  is_stale: boolean;
  provider?: string;
}
export interface WebhookEvent {
  delivery_id: string;
  event_type: string;
  processed: boolean;
  signature_valid: boolean;
  received_at: string;
  processed_at?: string;
  error?: string;
}

const f = (p: string) => api(p);

export function useProviderConfig() {
  return useSWR<{ rows: ProviderConfigRow[]; org_names: Record<string, string> }>(
    "/v1/admin/ramp/provider-config", f);
}
export function useConnectivity() {
  // Auto-probe on mount; refresh every 60s
  return useSWR<ConnectivityResult[]>(
    "/v1/admin/ramp/connectivity", f, { refreshInterval: 60_000 });
}
export function useCapabilities() {
  return useSWR<Record<string, any>>("/v1/admin/ramp/capabilities", f);
}
export function useAdminAccountsKpis() {
  return useSWR<AccountKpis>("/v1/admin/ramp/accounts/kpis", f,
    { refreshInterval: 30_000 });
}
export function useAdminAccounts(qs: string) {
  return useSWR<{ items: RampAccountRow[]; total: number }>(
    `/v1/admin/ramp/accounts${qs}`, f, { refreshInterval: 30_000 });
}
export function useAdminMovements(qs: string) {
  return useSWR<{ items: AdminMovement[]; total: number }>(
    `/v1/admin/ramp/movements${qs}`, f, { refreshInterval: 20_000 });
}
export function useAdminWebhooks(qs: string) {
  return useSWR<{ items: WebhookEvent[]; total: number }>(
    `/v1/admin/ramp/webhooks${qs}`, f, { refreshInterval: 20_000 });
}
export function useWebhookDeliveries() {
  return useSWR<{ items: any[]; mode: string; note?: string;
                    received_count: number; delivered_count: number }>(
    "/v1/admin/ramp/webhooks/deliveries", f);
}
export function useProjectStats() {
  return useSWR<Record<string, any>>("/v1/admin/ramp/stats", f,
    { refreshInterval: 60_000 });
}
export function useStatsTimeseries() {
  return useSWR<{ points: any[]; window: string; bucket: string; mode: string }>(
    "/v1/admin/ramp/stats/timeseries?window=30d&bucket=1d", f);
}

// Mutations
export async function putProviderConfig(
  scope: "global" | string,
  body: { provider: string; mode: string; enabled: boolean },
) {
  const path = scope === "global"
    ? "/v1/admin/ramp/provider-config"
    : `/v1/admin/ramp/provider-config/${scope}`;
  return api(path, { method: "PUT", body: JSON.stringify(body) });
}
export async function deleteOrgOverride(orgId: string) {
  return api(`/v1/admin/ramp/provider-config/${orgId}`, { method: "DELETE" });
}

// ---------------------------------------------------------------- Phase 17
//  ARSa chain config (default per org + override per account)
export interface ArsaChainConfig {
  default: "stellar" | "base";
  allowed: Array<"stellar" | "base">;
  source: "org_override" | "global" | "env_default";
}
export interface ArsaChainOverride {
  end_customer_id: string;
  effective_chain: "stellar" | "base";
  source: "account_override" | "org_override" | "global" | "env_default";
  override: "stellar" | "base" | null;
  has_wallet_on_other_chain: boolean;
  wallet_chain: string | null;
}

export function useArsaChainConfig() {
  return useSWR<ArsaChainConfig>("/v1/admin/ramp/arsa-chain", f);
}
export async function setArsaChainDefault(
  body: { default: "stellar" | "base"; allowed?: string[] },
) {
  return api("/v1/admin/ramp/arsa-chain",
              { method: "PUT", body: JSON.stringify(body) });
}
export function useAccountArsaChain(
  endCustomerId: string | undefined | null,
  orgId?: string | null,
) {
  const qs = orgId ? `?org_id=${encodeURIComponent(orgId)}` : "";
  return useSWR<ArsaChainOverride>(
    endCustomerId
      ? `/v1/admin/ramp/accounts/${endCustomerId}/arsa-chain${qs}`
      : null, f);
}
export async function setAccountArsaChain(
  endCustomerId: string,
  body: { override: "stellar" | "base" | null },
  orgId?: string | null,
) {
  const qs = orgId ? `?org_id=${encodeURIComponent(orgId)}` : "";
  return api(
    `/v1/admin/ramp/accounts/${endCustomerId}/arsa-chain${qs}`,
    { method: "PUT", body: JSON.stringify(body) });
}

// ───────────────────────────────────────────── Phase 15.2 — Stuck movements
export interface StuckMovement {
  id: string;
  org_id: string | null;
  kind: string;
  status: string;
  asset: string | null;
  chain: string | null;
  amount: string | null;
  country: string | null;
  end_customer_id: string | null;
  external_id: string | null;
  prosper_tx_id: string | null;
  occurred_at: string | null;
  created_at: string | null;
  age_hours: number;
}

export function useStuckMovements(thresholdHours = 24,
                                       kind?: string, orgId?: string) {
  const qs = new URLSearchParams({ threshold_hours: String(thresholdHours) });
  if (kind)   qs.set("kind", kind);
  if (orgId)  qs.set("org_id", orgId);
  return useSWR<StuckMovement[]>(
    `/v1/admin/ramp/movements/stuck?${qs.toString()}`, f);
}

export async function resyncMovement(mvId: string) {
  return api(`/v1/admin/ramp/movements/${mvId}/resync`, { method: "POST" });
}

export async function markMovementFailed(mvId: string,
                                              reason: string,
                                              refundBalance = true) {
  return api(`/v1/admin/ramp/movements/${mvId}/mark-failed`,
              { method: "POST",
                body: JSON.stringify({ reason, refund_balance: refundBalance }) });
}

// ───────────────────────────────────────────── Phase 15.2 — International
export interface IntlCotization {
  ars_usdt: string; usdt_bob: string; usdt_pen: string; usdt_pyg: string;
  updated_at?: string;
}
export interface IntlAccount {
  id: string; fiat_account_id: string;
  org_id: string; end_customer_id: string;
  country: "bob" | "pen" | "pyg";
  account_number: string; account_holder: string;
  account_holder_last_name: string;
  document_number: string; document_type: string;
  account_type: string; bank_code: string | null; bank_name: string | null;
  created_at: string;
}

export function useIntlCotization() {
  return useSWR<IntlCotization>("/v1/ramp/international/cotization", f);
}
export function useIntlBanks(country: "bob" | "pen" | "pyg" | null) {
  return useSWR<any>(country
    ? `/v1/ramp/international/banks/${country}` : null, f);
}
export function useIntlAccounts(endCustomerId?: string | null,
                                     orgId?: string) {
  const q = new URLSearchParams();
  if (endCustomerId) q.set("end_customer_id", endCustomerId);
  if (orgId)         q.set("org_id", orgId);
  return useSWR<IntlAccount[]>(
    `/v1/ramp/international/accounts?${q.toString()}`, f);
}
export function useIntlOfframps(endCustomerId?: string | null,
                                     orgId?: string) {
  const q = new URLSearchParams();
  if (endCustomerId) q.set("end_customer_id", endCustomerId);
  if (orgId)         q.set("org_id", orgId);
  return useSWR<any[]>(
    `/v1/ramp/international/offramp?${q.toString()}`, f);
}

export async function createIntlAccount(body: {
  end_customer_id: string;
  country: "bob" | "pen" | "pyg";
  account_number: string; account_holder: string;
  account_holder_last_name: string; document_number: string;
  document_type?: string; account_type?: string;
  bank_code?: string; bank_name?: string; phone_number?: string;
}, orgId?: string) {
  const qs = orgId ? `?org_id=${encodeURIComponent(orgId)}` : "";
  return api(`/v1/ramp/international/accounts${qs}`,
              { method: "POST", body: JSON.stringify(body) });
}

export async function quoteIntl(country: "bob" | "pen" | "pyg",
                                     fromAmount?: string) {
  const body: any = { country };
  if (country !== "pyg" && fromAmount) body.from_amount = fromAmount;
  return api("/v1/ramp/international/quote",
              { method: "POST", body: JSON.stringify(body) });
}

export async function executeIntlOfframp(body: {
  end_customer_id: string; country: "bob" | "pen" | "pyg";
  fiat_account_id: string;
  ars_usdt_quote_id?: string; usdt_dest_quote_id?: string;
  quote_expiration?: string;
  ars_amount?: string; expected_to_amount?: string;
}, orgId?: string, idempotencyKey?: string) {
  const qs = orgId ? `?org_id=${encodeURIComponent(orgId)}` : "";
  const headers: any = { "Content-Type": "application/json" };
  if (idempotencyKey) headers["Idempotency-Key"] = idempotencyKey;
  return api(`/v1/ramp/international/offramp${qs}`,
              { method: "POST", body: JSON.stringify(body),
                /* extra headers passed via 4th param of fetch wrapper */ });
}

// ───────────────────────────────────────────── Phase 15.2 — Crypto transfer
export async function executeTransfer(endCustomerId: string,
                                            body: {
                                              asset: "arsa" | "usdc" | "usdt";
                                              chain: "stellar" | "base" | "worldchain";
                                              amount: string;
                                              to_address: string;
                                              memo?: string;
                                            },
                                            orgId?: string,
                                            idempotencyKey?: string) {
  const qs = orgId ? `?org_id=${encodeURIComponent(orgId)}` : "";
  return api(`/v1/ramp/accounts/${endCustomerId}/transfer${qs}`,
              { method: "POST", body: JSON.stringify(body) });
}


// Helpers
export function fmtArsaAdmin(amount: string | number): string {
  const n = typeof amount === "string" ? parseFloat(amount) : amount;
  if (Number.isNaN(n)) return "$ 0,00";
  return "$ " + new Intl.NumberFormat("es-AR", {
    minimumFractionDigits: 2, maximumFractionDigits: 2 }).format(n);
}
