"use client";
import useSWR from "swr";
import { api } from "@/lib/api";

const fetcher = <T,>(p: string) => api<T>(p);

export interface ClientRow {
  org_id: string; legal_name: string; commercial_name: string;
  country: string; type: string; env: string; kyb_status: string;
  tier: string; tax_id: string; primary_email: string;
  created_at: string; last_login_at: string | null;
  users_count: number; volume_total: number;
  critical_alerts: number; kyb_refresh_due: boolean; paused: boolean;
}
export interface ClientListResp { items: ClientRow[]; total: number; page: number; page_size: number }
export function useClients(params: {
  kyb_status?: string[]; type?: string[]; env?: string[];
  q?: string; page?: number; page_size?: number;
}) {
  const p = new URLSearchParams();
  params.kyb_status?.forEach((s) => p.append("kyb_status", s));
  params.type?.forEach((s)        => p.append("type", s));
  params.env?.forEach((s)         => p.append("env", s));
  if (params.q) p.set("q", params.q);
  if (params.page) p.set("page", String(params.page));
  if (params.page_size) p.set("page_size", String(params.page_size));
  return useSWR<ClientListResp>(`/v1/admin/clients?${p}`, fetcher);
}

export interface ClientDetail {
  org: any;
  metrics: { volume_total_usd: number; tx_count: number;
              active_positions: number; users_count: number; alerts_open: number };
  risk: any | null;
}
export function useClient(orgId: string | null) {
  return useSWR<ClientDetail>(orgId ? `/v1/admin/clients/${orgId}` : null, fetcher);
}
export async function createClient(body: any) {
  return api<{ ok: boolean; org: any; primary_user_id: string; invite_link: string }>(
    "/v1/admin/clients", { method: "POST", body: JSON.stringify(body) });
}
export async function patchClient(orgId: string, body: any) {
  return api(`/v1/admin/clients/${orgId}`, { method: "PATCH", body: JSON.stringify(body) });
}
export async function pauseClient(orgId: string) {
  return api(`/v1/admin/clients/${orgId}/pause`, { method: "POST" });
}
export async function reactivateClient(orgId: string) {
  return api(`/v1/admin/clients/${orgId}/reactivate`, { method: "POST" });
}

// Users
export function useClientUsers(orgId: string | null) {
  return useSWR<{ items: any[]; total: number }>(
    orgId ? `/v1/admin/clients/${orgId}/users` : null, fetcher);
}
export async function inviteUser(orgId: string, body: any) {
  return api(`/v1/admin/clients/${orgId}/users`, { method: "POST", body: JSON.stringify(body) });
}
export async function patchUser(orgId: string, userId: string, body: any) {
  return api(`/v1/admin/clients/${orgId}/users/${userId}`, { method: "PATCH", body: JSON.stringify(body) });
}
export async function revokeUser(orgId: string, userId: string) {
  return api(`/v1/admin/clients/${orgId}/users/${userId}`, { method: "DELETE" });
}

// Links
export async function makeLink(orgId: string,
    purpose: "kyb" | "reset_password" | "invite", body: { email?: string; name?: string; send_email?: boolean }) {
  return api<{ url: string; link_id: string; expires_at: string }>(
    `/v1/admin/clients/${orgId}/links/${purpose}`, {
      method: "POST", body: JSON.stringify(body) });
}
export function useClientLinks(orgId: string | null) {
  return useSWR<{ items: any[] }>(
    orgId ? `/v1/admin/clients/${orgId}/links` : null, fetcher);
}

// API keys
export function useApiKeys(orgId: string | null) {
  return useSWR<{ items: any[] }>(
    orgId ? `/v1/admin/clients/${orgId}/api-keys` : null, fetcher);
}
export async function createApiKey(orgId: string, body: any) {
  return api<{ key_id: string; plaintext: string; prefix: string; name: string; scope: string }>(
    `/v1/admin/clients/${orgId}/api-keys`, { method: "POST", body: JSON.stringify(body) });
}
export async function rotateApiKey(orgId: string, keyId: string) {
  return api<{ plaintext: string; prefix: string }>(
    `/v1/admin/clients/${orgId}/api-keys/${keyId}/rotate`, { method: "POST" });
}
export async function revokeApiKey(orgId: string, keyId: string) {
  return api(`/v1/admin/clients/${orgId}/api-keys/${keyId}`, { method: "DELETE" });
}

// Webhooks
export function useWebhooks(orgId: string | null) {
  return useSWR<{ items: any[]; available_events: string[] }>(
    orgId ? `/v1/admin/clients/${orgId}/webhooks` : null, fetcher);
}
export async function createWebhook(orgId: string, body: any) {
  return api<{ webhook: any; secret: string }>(
    `/v1/admin/clients/${orgId}/webhooks`, { method: "POST", body: JSON.stringify(body) });
}
export async function deleteWebhook(orgId: string, whId: string) {
  return api(`/v1/admin/clients/${orgId}/webhooks/${whId}`, { method: "DELETE" });
}
export async function revealWebhookSecret(orgId: string, whId: string) {
  return api<{ secret: string }>(
    `/v1/admin/clients/${orgId}/webhooks/${whId}/reveal-secret`, { method: "POST" });
}
export async function testWebhook(orgId: string, whId: string) {
  return api(`/v1/admin/clients/${orgId}/webhooks/${whId}/test`, { method: "POST" });
}
export function useWebhookDeliveries(orgId: string | null, whId: string | null) {
  return useSWR<{ items: any[] }>(
    orgId && whId ? `/v1/admin/clients/${orgId}/webhooks/${whId}/deliveries` : null, fetcher);
}

// Audit log + positions/transactions + emails
export function useClientAuditLog(orgId: string | null) {
  return useSWR<{ items: any[] }>(
    orgId ? `/v1/admin/clients/${orgId}/audit-log` : null, fetcher);
}
export function useClientPositions(orgId: string | null) {
  return useSWR<{ items: any[] }>(
    orgId ? `/v1/admin/clients/${orgId}/positions` : null, fetcher);
}
export function useClientTransactions(orgId: string | null) {
  return useSWR<{ items: any[] }>(
    orgId ? `/v1/admin/clients/${orgId}/transactions` : null, fetcher);
}
export function useClientEmails(orgId: string | null) {
  return useSWR<{ items: any[] }>(
    orgId ? `/v1/admin/clients/${orgId}/emails` : null, fetcher);
}
