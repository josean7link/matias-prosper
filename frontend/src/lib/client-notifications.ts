"use client";
/**
 * Client-portal notifications hooks (SWR-based).
 *
 * Backed by `/api/v1/client/me/notifications`. All requests are
 * implicitly user-scoped via the JWT — no `user_id` query param exists.
 */
import useSWR from "swr";
import { api } from "@/lib/api";

export interface ClientNotification {
  notification_id: string;
  type: "deposit_credited_arsa" | "deposit_credited_usdc";
  title: string;
  body:  string;
  data:  {
    asset?:      "arsa" | "usdc";
    amount?:     string;
    currency?:   string;
    deposit_id?: string;
    tx_hash?:    string | null;
    ref?:        string | null;
    occurred_at?: string;
    event_id?:   string;
    source?:     string;
  };
  channels: { inapp: string; email?: string };
  read:      boolean;
  created_at: string;
  read_at:   string | null;
}

export interface NotificationsPage {
  items: ClientNotification[];
  next_cursor: string | null;
  has_more: boolean;
}

export function useClientNotifications(
  opts?: { unreadOnly?: boolean; limit?: number },
) {
  const qs = new URLSearchParams();
  if (opts?.unreadOnly) qs.set("unread_only", "true");
  if (opts?.limit)      qs.set("limit", String(opts.limit));
  const key = `/v1/client/me/notifications${qs.toString() ? "?" + qs : ""}`;
  return useSWR<NotificationsPage>(key,
    (k: string) => api<NotificationsPage>(k));
}

export function useClientUnreadCount() {
  return useSWR<{ count: number }>(
    "/v1/client/me/notifications/unread-count",
    (k: string) => api<{ count: number }>(k),
    { refreshInterval: 60_000 },   // mild background poll for the badge
  );
}

export async function markNotificationRead(id: string) {
  return api(`/v1/client/me/notifications/${id}/read`, { method: "POST" });
}

export async function markAllNotificationsRead() {
  return api("/v1/client/me/notifications/read-all", { method: "POST" });
}
