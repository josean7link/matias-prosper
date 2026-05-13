"use client";
import useSWR from "swr";
import { api } from "@/lib/api";

const fetcher = <T,>(p: string) => api<T>(p);

export interface DocLink { title: string; url: string }
export interface IntegrationField {
  key: string; label: string; required: boolean; secret: boolean;
  placeholder: string; env_var: string | null; help: string | null;
  value: string | null;
  source: "env" | "db" | null;
  is_set: boolean;
}
export interface IntegrationTestResult {
  ok: boolean; message: string; status_code: number | null;
  details: Record<string, unknown> | null;
  tested_at?: string; tested_by?: string;
}
export interface Integration {
  provider: string; name: string; category: string; description: string;
  supports_mode: boolean; supports_test: boolean; badge_color: string;
  status: "active" | "partial" | "missing";
  mode: "sandbox" | "live";
  fields: IntegrationField[];
  docs: DocLink[]; notes: string;
  last_test: IntegrationTestResult | null;
  updated_at?: string; updated_by?: string;
  required_filled: number; required_total: number;
  filled_total: number; fields_total: number;
}
export function useIntegrations() {
  return useSWR<{ items: Integration[]; total: number }>(
    "/v1/admin/settings/integrations", fetcher);
}
export async function patchIntegration(provider: string, body: Partial<{
  fields: Record<string, unknown>;
  mode: "sandbox" | "live";
  docs: DocLink[];
  notes: string;
}>) {
  return api<Integration>(`/v1/admin/settings/integrations/${provider}`, {
    method: "PATCH", body: JSON.stringify(body),
  });
}
export async function testIntegration(provider: string) {
  return api<IntegrationTestResult>(`/v1/admin/settings/integrations/${provider}/test`, {
    method: "POST",
  });
}
