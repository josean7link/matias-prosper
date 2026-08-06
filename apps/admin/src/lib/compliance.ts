"use client";
import useSWR from "swr";
import { api } from "@/lib/api";

const fetcher = <T,>(p: string) => api<T>(p);
const POLL = { refreshInterval: 15_000 };

export interface ComplianceSummary {
  kyb: { pending: number; approved: number; rejected: number };
  kyc: { pending: number };
  generated_at: string;
}

export interface OnboardingApplication {
  application_id: string;
  org_id: string;
  legal_name: string;
  commercial_name?: string;
  country: string;
  jurisdiction: string;
  status: "in_review" | "approved" | "rejected";
  kyb_status: "pending" | "in_review" | "approved" | "rejected";
  contact_email: string;
  contact_name: string;
  submitted_at: string;
  decision?: string | null;
  decision_at?: string | null;
  decision_by?: string | null;
  decision_note?: string | null;
  aiprise_session_id?: string | null;
  aiprise_mode?: "live" | "simulated" | null;
  hosted_url?: string | null;
  ubos?: { full_name: string; ownership_pct: number; role?: string }[];
  expected_monthly_volume_usd?: number | null;
  use_case?: string | null;
}

export interface KycCase {
  user_id: string;
  email: string;
  org_id?: string | null;
  role: string;
  kyc_status: "pending" | "in_review" | "approved" | "rejected";
  kyc_decision?: string | null;
  kyc_session_id?: string | null;
  kyc_mode?: "live" | "simulated" | null;
  updated_at: string;
}

export function useComplianceSummary() {
  return useSWR<ComplianceSummary>("/v1/compliance/summary", fetcher, POLL);
}
export function useApplications(status?: string) {
  const q = status ? `?status=${status}` : "";
  return useSWR<{ items: OnboardingApplication[]; total: number }>(
    `/v1/compliance/applications${q}`, fetcher, POLL);
}
export function useApplication(appId: string | null) {
  return useSWR<OnboardingApplication>(
    appId ? `/v1/compliance/applications/${appId}` : null, fetcher);
}
export function useKycCases(status?: string) {
  const q = status ? `?status=${status}` : "";
  return useSWR<{ items: KycCase[]; total: number }>(
    `/v1/compliance/kyc-cases${q}`, fetcher, POLL);
}

export async function decideApplication(appId: string, decision: string, note?: string) {
  return api(`/v1/compliance/applications/${appId}/decide`, {
    method: "POST", body: JSON.stringify({ decision, note }),
  });
}
export async function decideKyc(userId: string, decision: string, note?: string) {
  return api(`/v1/compliance/kyc-cases/${userId}/decide`, {
    method: "POST", body: JSON.stringify({ decision, note }),
  });
}
