"use client";
import { useEffect, useRef, useState } from "react";
import type { OpsQueue } from "@/lib/dashboard";

export type WsStatus = "connecting" | "live" | "polling" | "error";

/**
 * Subscribes to /api/v1/admin/dashboard/ws/ops-queue.
 * If the WS fails to connect 2x, returns null (and `status='polling'`) so the
 * caller can fall back to the SWR/HTTP hook seamlessly.
 */
export function useOpsQueueWS(): { data: OpsQueue | null; status: WsStatus } {
  const [data, setData] = useState<OpsQueue | null>(null);
  const [status, setStatus] = useState<WsStatus>("connecting");
  const wsRef = useRef<WebSocket | null>(null);
  const failsRef = useRef(0);

  useEffect(() => {
    if (typeof window === "undefined") return;
    let cancelled = false;
    let retryTimer: ReturnType<typeof setTimeout> | null = null;

    const connect = () => {
      try {
        const proto = window.location.protocol === "https:" ? "wss:" : "ws:";
        const url = `${proto}//${window.location.host}/api/v1/admin/dashboard/ws/ops-queue`;
        const ws = new WebSocket(url);
        wsRef.current = ws;
        setStatus("connecting");

        ws.onopen = () => {
          if (cancelled) { ws.close(); return; }
          failsRef.current = 0;
          setStatus("live");
        };
        ws.onmessage = (ev) => {
          try {
            const msg = JSON.parse(ev.data);
            if (msg && msg.approvals) setData(msg as OpsQueue);
          } catch {/* ignore */}
        };
        ws.onerror = () => { /* close handler will retry */ };
        ws.onclose = () => {
          if (cancelled) return;
          failsRef.current += 1;
          if (failsRef.current >= 2) {
            setStatus("polling");
            return;
          }
          setStatus("error");
          retryTimer = setTimeout(connect, 1500 * failsRef.current);
        };
      } catch {
        setStatus("polling");
      }
    };
    connect();

    return () => {
      cancelled = true;
      if (retryTimer) clearTimeout(retryTimer);
      try { wsRef.current?.close(); } catch {/* noop */}
    };
  }, []);

  return { data, status };
}
