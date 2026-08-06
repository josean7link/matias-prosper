"use client";
/**
 * Client-portal notifications bell. Mirrors `AlertsBell` ergonomics but
 * scoped to the authenticated user — never to admin alerts.
 *
 * The badge updates from `unread-count` (60s background poll). Items
 * are loaded lazily when the dropdown opens.
 */
import { useEffect, useRef, useState } from "react";
import { Bell } from "lucide-react";
import { useTranslations } from "next-intl";
import { toast } from "sonner";
import { mutate } from "swr";

import {
  useClientNotifications,
  useClientUnreadCount,
  markAllNotificationsRead,
  markNotificationRead,
  type ClientNotification,
} from "@/lib/client-notifications";
import { cn, fmtDate } from "@/lib/utils";

export default function ClientNotificationsBell() {
  const t = useTranslations("notifications");
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  const countSwr = useClientUnreadCount();
  const listSwr  = useClientNotifications({ limit: 20 });
  const count = countSwr.data?.count ?? 0;

  // Surface a toast when the unread count climbs WHILE the user is in
  // session — keeps the user aware of newly-arrived notifications
  // without needing a server push.
  const lastSeenRef = useRef<number | null>(null);
  useEffect(() => {
    if (countSwr.data?.count == null) return;
    if (lastSeenRef.current != null
        && countSwr.data.count > lastSeenRef.current) {
      toast(t("toast_new"), { duration: 4000 });
      void listSwr.mutate();
    }
    lastSeenRef.current = countSwr.data.count;
  }, [countSwr.data?.count]);   // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    if (!open) return;
    const onClick = (e: MouseEvent) => {
      if (!ref.current?.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", onClick);
    return () => document.removeEventListener("mousedown", onClick);
  }, [open]);

  const onItemClick = async (n: ClientNotification) => {
    if (n.read) return;
    try {
      await markNotificationRead(n.notification_id);
      void countSwr.mutate();
      void listSwr.mutate();
    } catch (err) {
      // Soft: bell never breaks the page
      console.error("mark-read failed", err);
    }
  };

  const onMarkAll = async () => {
    try {
      await markAllNotificationsRead();
      void mutate("/v1/client/me/notifications/unread-count");
      void mutate("/v1/client/me/notifications?limit=20");
      void listSwr.mutate();
    } catch (err) {
      console.error("mark-all failed", err);
    }
  };

  const items = listSwr.data?.items ?? [];

  return (
    <div className="relative" ref={ref}>
      <button
        onClick={() => setOpen((v) => !v)}
        className="prosper-btn-ghost h-9 w-9 p-0 relative"
        aria-label={t("bell_label")}
        data-testid="client-notifications-bell"
      >
        <Bell size={16} />
        {count > 0 && (
          <span
            data-testid="client-notifications-bell-count"
            className={cn(
              "absolute -top-0.5 -right-0.5 min-w-[16px] h-[16px] rounded-full px-1",
              "text-[9px] font-mono tabular flex items-center justify-center text-white bg-primary",
            )}
          >
            {count > 99 ? "99+" : count}
          </span>
        )}
      </button>
      {open && (
        <div
          className="absolute right-0 top-full mt-1.5 w-80 z-30 prosper-card p-2 shadow-card-hover animate-fade-in"
          data-testid="client-notifications-menu"
        >
          <div className="px-2 py-1.5 flex items-center justify-between border-b border-border mb-1">
            <span className="text-[10px] font-mono uppercase tracking-wider text-fg-subtle">
              {t("heading")}
            </span>
            {count > 0 && (
              <button
                onClick={onMarkAll}
                className="text-[10px] font-mono uppercase tracking-wider text-primary hover:underline"
                data-testid="client-notifications-mark-all"
              >
                {t("mark_all_read")}
              </button>
            )}
          </div>
          <div className="max-h-80 overflow-y-auto space-y-1">
            {items.length === 0 && (
              <div className="text-fg-subtle text-xs px-2 py-3 text-center">
                {t("empty")}
              </div>
            )}
            {items.map((n) => (
              <button
                key={n.notification_id}
                onClick={() => onItemClick(n)}
                data-testid={`client-notif-item-${n.notification_id}`}
                className={cn(
                  "block w-full text-left px-2 py-2 rounded transition-colors",
                  n.read ? "hover:bg-surface-hover" : "bg-primary/5 hover:bg-primary/10",
                )}
              >
                <div className="flex items-start justify-between gap-2">
                  <div className="flex-1 min-w-0">
                    <div className="text-[12px] text-fg font-medium truncate">{n.title}</div>
                    <div className="text-[11px] text-fg-muted line-clamp-2 mt-0.5">{n.body}</div>
                  </div>
                  {!n.read && (
                    <span
                      className="mt-1.5 w-1.5 h-1.5 rounded-full bg-primary shrink-0"
                      aria-label={t("unread_dot")}
                    />
                  )}
                </div>
                <div className="text-[10px] text-fg-subtle font-mono mt-1">
                  {fmtDate(n.created_at)}
                </div>
              </button>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
