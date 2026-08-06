"use client";
/**
 * Phase 04 — Client portfolio snapshot polling hook.
 *
 * Polls `/v1/client/me/portfolio/snapshot` every 20s. SWR's global key
 * cache means multiple screens mounting the hook simultaneously share
 * a single in-flight request.
 *
 * Visibility-gated: polling pauses while `document.hidden`, resumes on
 * `visibilitychange`. This drops idle-tab traffic to zero. The backend
 * cache (12s Redis TTL) is the second line of defense.
 *
 * `isNewMovement` flips true for 8s whenever `last_movement_cursor`
 * advances. The hook also surfaces the most recent movement so the
 * caller can build a rail-correct toast (ARSa-only or USDC-only copy).
 */
import { useCallback, useEffect, useRef, useState } from "react";
import useSWR from "swr";
import { api } from "@/lib/api";

export interface SnapshotMovement {
  movement_id: string;
  kind:        string;
  asset:       "arsa" | "usdc";
  amount:      string;
  status:      string;
  memo?:       string | null;
  created_at:  string;
  external_id?: string;
  provider?:   string;
}

export interface PortfolioSnapshot {
  balances: {
    arsa: {
      cvu: number; stellar: number; total: number;
      pending_detected: number; as_of: string;
    };
    usdc: {
      platform: number; stellar: number; total: number;
      pending_detected: number; as_of: string;
    };
  };
  recent_movements:     SnapshotMovement[];
  last_movement_cursor: string | null;
  snapshot_source:      "cache" | "fresh";
  fetched_at:           string;
}

export interface SnapshotHook {
  snapshot:     PortfolioSnapshot | undefined;
  isLoading:    boolean;
  error:        unknown;
  isPaused:     boolean;
  isNewMovement: boolean;
  newestMovement: SnapshotMovement | null;
  refresh:       () => Promise<PortfolioSnapshot | undefined>;
}

const KEY = "/v1/client/me/portfolio/snapshot";

function useIsVisible(): boolean {
  const [vis, setVis] = useState(
    typeof document !== "undefined" ? !document.hidden : true,
  );
  useEffect(() => {
    const onVis = () => setVis(!document.hidden);
    document.addEventListener("visibilitychange", onVis);
    return () => document.removeEventListener("visibilitychange", onVis);
  }, []);
  return vis;
}

export function usePortfolioSnapshot(
  opts?: { intervalMs?: number },
): SnapshotHook {
  const interval = opts?.intervalMs ?? 20_000;
  const visible = useIsVisible();

  // The hook deliberately uses a SINGLE global key (no per-user
  // suffix). The backend scopes by JWT — never trust client to disambiguate.
  const swr = useSWR<PortfolioSnapshot>(
    KEY,
    (k: string) => api<PortfolioSnapshot>(k),
    {
      // Pause polling when the tab is hidden — saves backend + Horizon.
      refreshInterval: visible ? interval : 0,
      revalidateOnFocus: true,
    },
  );

  // Track the previous cursor across renders to detect new movements.
  const lastCursorRef = useRef<string | null>(null);
  const [isNewMovement, setIsNewMovement] = useState(false);
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    const cur = swr.data?.last_movement_cursor ?? null;
    if (!cur) return;
    // First snapshot in this session — record as baseline, no toast.
    if (lastCursorRef.current === null) {
      lastCursorRef.current = cur;
      return;
    }
    if (cur > lastCursorRef.current) {
      lastCursorRef.current = cur;
      setIsNewMovement(true);
      if (timerRef.current) clearTimeout(timerRef.current);
      timerRef.current = setTimeout(() => setIsNewMovement(false), 8_000);
    }
  }, [swr.data?.last_movement_cursor]);

  useEffect(() => () => {
    if (timerRef.current) clearTimeout(timerRef.current);
  }, []);

  const refresh = useCallback(
    async () => (await swr.mutate()) as PortfolioSnapshot | undefined,
    [swr],
  );

  const newestMovement = swr.data?.recent_movements?.[0] ?? null;

  return {
    snapshot:       swr.data,
    isLoading:      swr.isLoading,
    error:          swr.error,
    isPaused:       !visible,
    isNewMovement,
    newestMovement,
    refresh,
  };
}
