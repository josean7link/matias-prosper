"use client";
import useSWR from "swr";
import { api } from "@/lib/api";

/**
 * CMS protocol product (Feb 2026).
 *
 * The catalog is fixed by the Prosper smart contract: 12-month staking
 * cycle with two settlement modalities (`end` or `month`) per asset
 * (USDC or ARSa). The wizard reads this catalog read-only — operators
 * can only pause a row in case of incident.
 */
export interface Product {
  product_id: string;          // usdc_end | usdc_month | arsa_end | arsa_month
  name: string;
  description?: string;
  apr_bps: number;             // canonical rate echoes from the contract
  min_amount: number;
  max_amount: number;
  status: "active" | "paused" | "archived" | "inactive";

  // CMS protocol fields ----------------------------------------------------
  asset?: "usdc" | "arsa";              // what the user deposits
  yield_asset?: "usdc" | "arsa";        // ALWAYS == asset (no bridge)
  payout_asset?: "usdc" | "arsa";       // ALWAYS == asset
  modality?: "end" | "month";           // CMS cashin frequency
  term_months?: number;                 // 12 in current protocol
  term_days?: number;                   // 365 — kept for legacy callers
  payout_schedule?: "at_maturity" | "monthly" | "daily";
  arsa_native_enabled?: boolean;
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
  // Phase 20 v2 — attribution + display asset
  end_customer_id?: string;
  asset?: "usdc" | "arsa";
  display_currency?: "ARSa" | "USDC";
  // CMS protocol — per-staking on-chain memo
  memo?: string;
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
