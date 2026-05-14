"use client";
import useSWR from "swr";
import { api } from "@/lib/api";

export interface ApiKey {
  key_id: string;
  name: string;
  scope: "sandbox" | "production";
  prefix: string;
  status: "active" | "revoked";
  created_at: string;
  last_used_at?: string | null;
  last_used_ip?: string | null;
}

export interface CreatedApiKey {
  ok: boolean;
  key_id: string;
  name: string;
  scope: string;
  prefix: string;
  plaintext: string;
  warning: string;
}

export interface Webhook {
  webhook_id: string;
  url: string;
  events: string[];
  description?: string;
  status: "active" | "paused" | "failing";
  fail_count: number;
  last_delivery_at?: string | null;
  last_status?: "ok" | "failed" | null;
  secret_prefix?: string;
  created_at: string;
}

export interface Delivery {
  delivery_id: string;
  webhook_id: string;
  event: string;
  http_code?: number | null;
  retry_count: number;
  ts: string;
  payload: unknown;
  response_body?: string | null;
  error?: string | null;
}

export interface WidgetConfig {
  theme: "light" | "dark";
  color: string;
  locale: "es" | "en" | "auto";
  amount?: number | null;
  product_id: string;
  show_branding: boolean;
}

const fetcher = (p: string) => api(p);

export function useApiKeys() {
  return useSWR<{ items: ApiKey[] }>("/v1/client/api-keys", fetcher);
}

export function useWebhooks() {
  return useSWR<{ items: Webhook[]; available_events: string[] }>(
    "/v1/client/webhooks", fetcher);
}

export function useDeliveries(webhookId: string | null) {
  return useSWR<{ items: Delivery[] }>(
    webhookId ? `/v1/client/webhooks/${webhookId}/deliveries` : null,
    fetcher);
}

export function useWidgetConfig() {
  return useSWR<{ config: WidgetConfig; org_name?: string }>(
    "/v1/client/widget/config", fetcher);
}

export function useFeatureInterest() {
  return useSWR<{ items: Array<{ feature: string }>; registered: string[] }>(
    "/v1/client/feature-interest", fetcher);
}
