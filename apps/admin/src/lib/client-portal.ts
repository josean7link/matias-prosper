"use client";
import useSWR from "swr";
import { api } from "@/lib/api";

export interface ClientMe {
  user: { user_id: string; email: string; full_name?: string; role: string; org_id: string | null };
  org: {
    org_id: string;
    legal_name?: string;
    commercial_name?: string;
    country?: string;
    /** Onboarding-time org type. `fintech` = partner/business that
     *  integrates Prosper; `personal` = individual investor (default).
     *  Used by the AppShell to gate the developer section. */
    type?: "personal" | "fintech";
    kyb_status: "pending" | "in_review" | "approved" | "rejected" | "needs_info";
    sanctions_status?: "pending" | "clear" | "flagged";
    travel_rule_status?: "pending" | "clear" | "na" | "flagged";
    env: "sandbox" | "production";
    tier: string;
    paused: boolean;
    kyb_reject_reason?: string | null;
  };
  features: { can_operate?: boolean; can_view_data?: boolean; can_edit_profile?: boolean;
                kyb_locked?: boolean; kyc_pending?: boolean; mfa_required?: boolean;
                mfa_enabled?: boolean; is_internal?: boolean };
  onboarding: {
    stage: "not_started" | "applied" | "in_review" | "needs_info" | "approved" | "rejected";
    percent: number;
    checklist_done: number;
    checklist_total: number;
    docs_count: number;
    has_case: boolean;
  };
}

export interface ClientKpis {
  available_usdc: number;
  token_balance: number;
  token_value_usd: number;
  principal_invested: number;
  accrued_total: number;
  avg_apr_bps: number;
  avg_apr_pct: number;
}

export interface ClientPosition {
  position_id: string;
  product: string;
  asset?: "arsa" | "usdc";
  principal: number;
  accrued: number;
  apr_bps: number;
  apr_pct: number;
  start_date: string;
  maturity_date: string;
  status: string;
  modality?: "end" | "month";
  days_to_maturity: number | null;
}

export interface ClientTx {
  tx_id: string;
  prosper_tx_id?: string;
  type: string;
  amount: number;
  status: string;
  created_at: string;
}

export interface ClientDashboard {
  kpis: ClientKpis;
  positions: ClientPosition[];
  recent_transactions: ClientTx[];
  monthly_yield: Array<{ month: string; arsa: number; usdc: number }>;
  daily_yield: Array<{ date: string; arsa: number; usdc: number }>;
  today_yield: {
    earned:      number;
    earning_now: number;
    total:       number;
    as_of:       string;
    /** Per-asset split (P2 Feb 2026). Same shape as the legacy top-level
     *  keys, but never mixed across currencies. */
    by_asset?: {
      arsa: { earned: number; earning_now: number; total: number };
      usdc: { earned: number; earning_now: number; total: number };
    };
  };
  projection: { realized_ytd: number; projected_annual: number };
  kyb_status: string;
  paused: boolean;
}

const fetcher = (p: string) => api(p);

export function useClientMe() {
  return useSWR<ClientMe>("/v1/client/me", fetcher);
}

export function useClientDashboard() {
  return useSWR<ClientDashboard>("/v1/client/dashboard", fetcher, {
    refreshInterval: 30_000,
  });
}

export interface ApplyContext {
  org_id: string;
  legal_name?: string;
  commercial_name?: string;
  country?: string;
  tax_id?: string;
  type?: string;
  primary_email?: string;
  primary_name?: string;
}

export interface UBOInput {
  full_name: string;
  ownership_pct: number;
  nationality?: string;
  is_pep?: boolean;
}

export interface DocInput { label: string; kind: string; url: string }

export interface ApplyPayload {
  token: string;
  personal: {
    first_name: string;
    last_name: string;
    dob: string;
    gender: string;
    nationality: string;
    doc_id: string;
  };
  corporate: { legal_name?: string };
  ubos: UBOInput[];
  documents: DocInput[];
  accept_terms: boolean;
}

export const fmtUsd = (n: number) =>
  new Intl.NumberFormat("en-US", { style: "currency", currency: "USD", maximumFractionDigits: 2 }).format(n);

export const fmtNum = (n: number) =>
  new Intl.NumberFormat("en-US", { maximumFractionDigits: 2 }).format(n);
