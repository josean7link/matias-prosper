"use client";
import useSWR from "swr";
import { api } from "@/lib/api";

/** Phase 14/15 — Andes / RampProvider client helpers.
 *
 * Endpoints are mounted at `/api/v1/ramp/*` and scoped to the JWT's org.
 * ARSa is treated as a first-class asset (label "ARSa", symbol "$",
 * caption "peso digital 1:1") across the whole UI.
 */

export type OnboardingStatus =
  | "approved"
  | "pending_approval"
  | "kyc_docs_required"
  | "kyc_docs_submitted"
  /** @deprecated Phase 22+ alias of `kyc_docs_required` */
  | "kyc_pending_andes"
  | "rejected"
  | "error";

export interface RampAccount {
  end_customer_id: string;
  provider: string;
  provider_user_id: string;
  account_name: string | null;
  wallet_address: string | null;
  wallet_chain: "stellar" | "base" | null;
  wallet_status: "pending" | "active" | null;
  wallet_activated_at: string | null;
  cvu: string | null;
  alias: string | null;
  cvu_status: "pending" | "completed";
  onboarding_status: OnboardingStatus;
  onboarding_message: string | null;
  created_at: string;
  updated_at: string;
}

export interface RampBalance {
  asset_code: string;        // "arsa", "usdc", "usdt"
  asset_label: string;       // "ARSa"
  asset_symbol: string;      // "$"
  asset_caption: string;     // "peso digital 1:1"
  chain: string;
  amount: string;
  as_of: string;
}

export interface RampBalances {
  end_customer_id: string;
  provider: string;
  items: RampBalance[];
}

const fetcher = (p: string) => api(p);

function withOrg(path: string, orgId?: string | null): string {
  if (!orgId) return path;
  return path + (path.includes("?") ? "&" : "?") + "org_id=" + encodeURIComponent(orgId);
}

// ---------------------------------------------------------------- hooks
export function useRampAccounts(orgId?: string | null) {
  return useSWR<RampAccount[]>(withOrg("/v1/ramp/accounts", orgId), fetcher, {
    refreshInterval: 30_000,
  });
}

export function useRampAccount(
  endCustomerId: string | undefined | null,
  orgId?: string | null,
) {
  return useSWR<RampAccount>(
    endCustomerId
      ? withOrg(`/v1/ramp/accounts/${endCustomerId}`, orgId)
      : null,
    fetcher,
  );
}

export function useRampBalances(
  endCustomerId: string | undefined | null,
  orgId?: string | null,
) {
  return useSWR<RampBalances>(
    endCustomerId
      ? withOrg(`/v1/ramp/accounts/${endCustomerId}/balances`, orgId)
      : null,
    fetcher,
    { refreshInterval: 20_000 },
  );
}

// ---------------------------------------------------------------- mutations
export async function createRampAccount(payload: {
  end_customer_id?: string;
  display_name?: string;
  holder_name?: string;
  holder_tax_id?: string;
  alias?: string;
} = {}, orgId?: string | null): Promise<RampAccount> {
  return api(withOrg("/v1/ramp/accounts", orgId), {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export async function retryRampAccount(
  endCustomerId: string,
  orgId?: string | null,
): Promise<RampAccount> {
  return api(withOrg(`/v1/ramp/accounts/${endCustomerId}/retry`, orgId),
              { method: "POST" });
}

// Phase 18 — poll gateway for the current wallet status (fallback when the
// wallet.active webhook is delayed).
export async function refreshWalletStatus(
  endCustomerId: string,
  orgId?: string | null,
): Promise<RampAccount> {
  return api(
    withOrg(`/v1/ramp/accounts/${endCustomerId}/refresh-wallet-status`, orgId),
    { method: "POST" });
}

/** Phase 18 — wallet activation helper. Returns true when the Stellar wallet
 *  is still being provisioned and deposits cannot land yet. EVM (Base) wallets
 *  are always active immediately. */
export function isWalletActivating(acc: RampAccount | null | undefined): boolean {
  if (!acc) return false;
  return acc.wallet_status === "pending";
}

/** Phase 18 — explorer URL per chain. Returns null if we don't know the chain.
 *  Stellar uses stellar.expert; Base uses basescan.org. */
export function explorerUrl(chain: string | null | undefined,
                                address: string | null | undefined): string | null {
  if (!chain || !address) return null;
  if (chain === "stellar")
    return `https://stellar.expert/explorer/public/account/${address}`;
  if (chain === "base")
    return `https://basescan.org/address/${address}`;
  return null;
}

/** Phase 18 — pretty chain label used across the UI. */
export function chainLabel(chain: string | null | undefined): string {
  if (chain === "stellar") return "Stellar";
  if (chain === "base")    return "Base";
  return chain || "—";
}

// ---------------------------------------------------------------- Phase 15
export type TxStatus = "Pending" | "TransferPending" | "Success" | "Failed";

export interface RampMovement {
  id: string;
  kind: "deposit" | "withdrawal";
  asset: string;            // "arsa"
  asset_label: string;      // "ARSa"
  asset_symbol: string;     // "$"
  chain: string;
  amount: string;
  status: TxStatus;
  fail_reason: string | null;
  destination_cvu: string | null;
  destination_alias: string | null;
  destination_name: string | null;
  external_id: string | null;
  prosper_tx_id: string | null;
  created_at: string;
  settled_at: string | null;
}

export interface CvuLookup {
  cvu: string | null;
  alias: string | null;
  holder_name: string | null;
  holder_tax_id: string | null;
  bank: string | null;
}

export function useRampMovements(
  endCustomerId: string | undefined | null,
  orgId?: string | null,
) {
  return useSWR<RampMovement[]>(
    endCustomerId
      ? withOrg(`/v1/ramp/accounts/${endCustomerId}/movements`, orgId)
      : null,
    fetcher,
    { refreshInterval: 15_000 },
  );
}

export async function cvuLookup(
  q: { cvu?: string; alias?: string },
): Promise<CvuLookup> {
  const params = new URLSearchParams();
  if (q.cvu)   params.set("cvu", q.cvu);
  if (q.alias) params.set("alias", q.alias);
  return api(`/v1/ramp/cvu-lookup?${params.toString()}`);
}

export async function submitWithdraw(
  endCustomerId: string,
  payload: {
    amount: string;
    to_cvu?: string;
    to_alias?: string;
    holder_name_confirmed?: string;
  },
  idempotencyKey: string,
  orgId?: string | null,
): Promise<RampMovement> {
  return api(withOrg(`/v1/ramp/accounts/${endCustomerId}/withdraw`, orgId), {
    method: "POST",
    headers: { "Idempotency-Key": idempotencyKey },
    body: JSON.stringify(payload),
  });
}

// ---------------------------------------------------------------- formatting
/** Format an ARSa amount string from the backend into a localized $ string.
 *  ARSa is a 1:1 peso digital, so we display Argentine peso conventions
 *  (thousands with dot, decimals with comma). */
export function fmtArsa(amount: string | number): string {
  const n = typeof amount === "string" ? parseFloat(amount) : amount;
  if (Number.isNaN(n)) return "$ 0,00";
  return (
    "$ " +
    new Intl.NumberFormat("es-AR", {
      minimumFractionDigits: 2,
      maximumFractionDigits: 2,
    }).format(n)
  );
}

export function shortCvu(cvu: string | null | undefined): string {
  if (!cvu) return "—";
  // 22-digit CVU → group in 4-4-4-4-4-2 for readability
  return cvu.replace(/(.{4})(?=.)/g, "$1 ");
}
