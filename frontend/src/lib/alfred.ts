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
  { code: "transfer",    label: "Transferencia bancaria", hint: "1-2 días hábiles" },
  { code: "mercadopago", label: "Mercado Pago",            hint: "Instantáneo" },
  { code: "crypto",      label: "USDC desde otra wallet",  hint: "Wallet a wallet" },
  { code: "card",        label: "Tarjeta",                 hint: "+3% fee" },
];

export const fetcher = (p: string) => api(p);

export function useOnrampOrder(id: string | null) {
  return useSWR<{ order: OnrampOrder }>(
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
  tx_id: string;
  prosper_tx_id: string;
  type: string;
  amount: number;
  status: string;
  created_at: string;
  asset: string;
  memo?: string;
  metadata?: Record<string, unknown>;
}

export function useTxHistory(opts: { type?: string; status?: string } = {}) {
  const params = new URLSearchParams();
  if (opts.type)   params.set("tx_type", opts.type);
  if (opts.status) params.set("status", opts.status);
  const qs = params.toString();
  return useSWR<{ items: HistoryTx[]; total: number }>(
    `/v1/client/transactions/history${qs ? "?" + qs : ""}`,
    fetcher,
  );
}

export const fmtCur = (n: number, cur: string) =>
  new Intl.NumberFormat("en-US", {
    style: "currency", currency: cur === "USDC" ? "USD" : cur,
    maximumFractionDigits: 2,
  }).format(n).replace("US$", "$");
