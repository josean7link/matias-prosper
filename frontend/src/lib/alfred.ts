"use client";
import useSWR from "swr";
import { api } from "@/lib/api";

export interface Quote {
  quote_id: string;
  direction: "onramp" | "offramp";
  source_currency: string;
  source_amount: number;
  target_currency: string;
  target_amount: number;
  rate: number;
  fee_amount: number;
  fee_currency: string;
  ttl_seconds: number;
  expires_at: string;
  mode: "mock" | "sandbox" | "production";
  usdc_amount?: number;
}

export interface OnrampOrder {
  onramp_id: string;
  org_id: string;
  user_id: string;
  alfred_id: string;
  coelsa_id?: string | null;
  source_currency: string;
  source_amount: number;
  target_currency: string;
  expected_usdc: number;
  usdc_received?: number | null;
  rate: number;
  fee_amount: number;
  fee_currency: string;
  payment_method: string;
  checkout_url: string;
  status: "pending" | "confirmed" | "failed" | "completed";
  mode: "mock" | "sandbox" | "production";
  created_at: string;
  updated_at: string;
  settled_at?: string;
}

export interface OfframpOrder {
  offramp_id: string;
  alfred_id: string;
  usdc_sent: number;
  target_currency: string;
  expected_fiat: number;
  fiat_received?: number | null;
  bank_account: {
    holder_name: string;
    country: string;
    cbu_or_iban?: string;
    bank_name?: string;
    account_alias?: string;
  };
  source: "balance" | "position";
  position_id?: string;
  status: "pending" | "completed" | "failed";
  mode: "mock" | "sandbox" | "production";
  timeline: Array<{ key: string; label: string; done: boolean; skipped?: boolean }>;
  created_at: string;
  settled_at?: string;
}

export interface RampCurrency {
  code: string;
  label: string;
  flag: string;
}

export const ONRAMP_CURRENCIES: RampCurrency[] = [
  { code: "ARS", label: "Peso Argentino",  flag: "🇦🇷" },
  { code: "USD", label: "Dólar US",        flag: "🇺🇸" },
  { code: "CLP", label: "Peso Chileno",    flag: "🇨🇱" },
  { code: "BRL", label: "Real Brasileño",  flag: "🇧🇷" },
  { code: "MXN", label: "Peso Mexicano",   flag: "🇲🇽" },
];

export const PAYMENT_METHODS = [
  { code: "transfer",    label: "Transferencia bancaria", hint: "1-2 días hábiles", available: true },
  { code: "mercadopago", label: "Mercado Pago",            hint: "Instantáneo",      available: false },
  { code: "crypto",      label: "USDC desde otra wallet",  hint: "Wallet a wallet",  available: true },
  { code: "card",        label: "Tarjeta",                 hint: "+3% fee",          available: false },
] as const;

export type PaymentMethod = (typeof PAYMENT_METHODS)[number];

export const fetcher = (p: string) => api(p);

export function useOnrampOrder(id: string | null) {
  return useSWR<{
    order: OnrampOrder;
    subscribe_tx?: { tx_id: string; tx_hash?: string; status: string;
                     amount: number; ledger?: string;
                     metadata?: { product_id?: string; apr_bps?: number } };
    position?: { position_id: string; product_id: string; principal_usd: number;
                  apr_bps: number; maturity?: string | null; status: string };
  }>(
    id ? `/v1/client/onramp/orders/${id}` : null,
    fetcher,
    { refreshInterval: (data) => (data?.order?.status === "pending" ? 5000 : 0) }
  );
}

export function useOfframpOrder(id: string | null) {
  return useSWR<{ order: OfframpOrder }>(
    id ? `/v1/client/offramp/orders/${id}` : null,
    fetcher,
    { refreshInterval: (data) => (data?.order?.status === "pending" ? 5000 : 0) }
  );
}

export interface HistoryTx {
  tx_id:           string;
  type:            string;     // arsa_deposit | arsa_withdraw | usdc_deposit | usdc_withdraw | invest | redeem
  amount:          number;
  status:          string;     // confirmed | pending | pending_onchain | failed | cancelled
  created_at:      string;
  asset:           string;     // "arsa" | "usdc"
  memo?:           string;
  tx_hash?:        string | null;
  destination_cvu?: string | null;
  position_id?:    string | null;
  source?:         string;     // ramp_movements | positions | onramp_orders | offramp_orders
}

export function useTxHistory(opts: { type?: string; status?: string;
                                       asset?: string } = {}) {
  const params = new URLSearchParams();
  if (opts.type)   params.set("type", opts.type);
  if (opts.status) params.set("status", opts.status);
  if (opts.asset)  params.set("asset", opts.asset);
  const qs = params.toString();
  return useSWR<{ items: HistoryTx[]; total: number }>(
    `/v1/client/transactions/history${qs ? "?" + qs : ""}`,
    fetcher,
  );
}

/**
 * Format a number with its currency code.
 *
 * Handles two families:
 *   1. ISO 4217 codes (USD, EUR, …) → uses `Intl.NumberFormat` for proper
 *      localization. `USDC` is mapped to `USD` so the `$` symbol shows up.
 *   2. Non-ISO codes (ARSa, USDCp, …) → fall back to a plain decimal
 *      formatter and append the code as a suffix. We need this fallback
 *      because `Intl.NumberFormat({currency:"ARSa"})` throws RangeError
 *      ("Invalid currency code"). Same approach used for any token-style
 *      asset code that doesn't exist in the ISO registry.
 */
const _ISO_ALIASES: Record<string, string> = {
  USDC: "USD",
};

export const fmtCur = (n: number, cur: string) => {
  const code = (cur || "").trim();
  const iso  = _ISO_ALIASES[code] || code;
  // Reject anything that isn't a 3-letter A-Z ISO code (covers ARSa,
  // USDCp, plus any future token symbols).
  const isISOish = /^[A-Z]{3}$/.test(iso);
  if (!isISOish) {
    return n.toLocaleString("es-AR", {
      minimumFractionDigits: 2, maximumFractionDigits: 2,
    }) + " " + code;
  }
  try {
    return new Intl.NumberFormat("en-US", {
      style: "currency", currency: iso,
      maximumFractionDigits: 2,
    }).format(n).replace("US$", "$");
  } catch {
    return n.toLocaleString("es-AR", {
      minimumFractionDigits: 2, maximumFractionDigits: 2,
    }) + " " + code;
  }
};
