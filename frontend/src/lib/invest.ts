"use client";
import useSWR from "swr";
import { api } from "@/lib/api";

export interface Product {
  product_id: string;
  name: string;
  term_days: number;
  apr_bps: number;
  min_amount: number;
  max_amount: number;
  status: "active" | "paused" | "archived";
  description?: string;
}

export interface Position {
  position_id: string;
  product_id: string;
  principal_usd: number;
  accrued_interest: number;
  apr_bps: number;
  start: string;
  maturity?: string | null;
  status: "active" | "matured" | "redeemed";
  prosper_tx_id: string;
  last_accrued_date?: string;
}

export interface Balances {
  available_usdc: number;
  address?: string | null;
  balance_prosper?: number | null;
  balance_xlm?: number | null;
  mode: string;
}

const fetcher = (p: string) => api(p);

export function useProducts() {
  return useSWR<{ items: Product[] }>("/v1/client/products", fetcher);
}

export function usePositions() {
  return useSWR<{ items: Position[] }>("/v1/client/positions", fetcher);
}

export function usePosition(id: string | null) {
  return useSWR<{
    position: Position;
    events: Array<{ tx_id: string; type: string; amount: number;
                     status: string; created_at: string; tx_hash?: string;
                     memo?: string }>;
  }>(id ? `/v1/client/positions/${id}` : null, fetcher);
}

export function useInvestBalances() {
  return useSWR<Balances>("/v1/client/balances", fetcher);
}

export const fmtPct = (apr_bps: number) => (apr_bps / 100).toFixed(2) + "%";

export const STELLAR_EXPLORER = "https://stellar.expert/explorer/public/tx";
