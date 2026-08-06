"""Phase 13 — Alfred adapter wrapping the existing integration.

This file is a **thin shim**: it implements `RampProvider` by delegating to
the already-tested `integrations/alfred/` codebase. **No Alfred business
logic is duplicated here** so existing tests (`test_phase8_alfred*`,
`test_alfred_real_live`, …) keep passing without modification.

The shim deliberately keeps method bodies tiny — for anything that Alfred
doesn't support (CVU per user, international off-ramp, balances-by-andes-id),
it raises `NotSupportedByProvider` so the UI knows to hide the feature.
"""
from __future__ import annotations

import logging
import secrets
from typing import Any, Optional

from integrations.alfred import current_mode, get_adapter as _get_alfred_adapter
from integrations.alfred.kyc import get_kyc_adapter as _get_alfred_kyc

from ..provider import (
    AvailableChain, FiatAccountParams, IntlQuote, KycFiles,
    NotSupportedByProvider, OnrampInstructions, RampAccount, RampBalance,
    RampFiatAccount, RampMovement, RampOrder, RampProvider,
    RampProviderCapabilities, RampWallet, RampWebhookEvent, TxStatus,
    WalletAsset,
)

logger = logging.getLogger("prosper.ramp.alfred")


_CAPS = RampProviderCapabilities(
    id="alfred", fiatRails=["AR_CVU"],
    producedAssets=[WalletAsset.USDC],
    chains=[AvailableChain.STELLAR],
    supportsDedicatedAccounts=False,
    supportsBalances=False,                  # surfaced via Prosper/Stellar, not Alfred
    supportsOnramp=True,
    supportsOfframp=True,
    supportsInternationalOfframp=False,
    onrampModel="order")


class AlfredRampAdapter(RampProvider):
    """RampProvider wrapper around the existing Alfred integration package.

    Nothing here mutates Alfred's behavior. The legacy `integrations/alfred/`
    code is the source of truth — this shim only adapts its DTOs to the
    RampProvider shape.
    """

    provider_id = "alfred"

    # ------------------------------------------------------------------ caps
    def capabilities(self) -> RampProviderCapabilities:
        return _CAPS

    # ------------------------------------------------------------------ accounts
    async def create_account(self, *, org_id, end_customer_id,
                               display_name=None) -> RampAccount:
        # Alfred's `create_kyb_customer` is the closest match: it creates a
        # `customerId` we use as `provider_user_id` for the rest of the flow.
        kyc = _get_alfred_kyc()
        resp = await kyc.create_kyb_customer(
            org_id=org_id,
            business={
                "legal_name": display_name or end_customer_id,
                "primary_contact": {"email":
                    f"{end_customer_id}@prosper.partner".lower()},
            },
            redirect_uri="")
        return RampAccount(
            id="acc_" + secrets.token_hex(6),
            org_id=org_id, end_customer_id=end_customer_id,
            provider=self.provider_id,
            provider_user_id=resp.customer_id,
            account_name=display_name or end_customer_id,
            raw={"alfred_iframe_url": resp.iframe_url,
                  "alfred_status": resp.status,
                  "mode": resp.mode})

    # ------------------------------------------------------------------ wallets
    async def ensure_wallet(self, *, andes_user_id, asset, chain):
        # Alfred doesn't host wallets — they live on Prosper Stellar. The
        # RampProvider contract here just records the intended wallet for the
        # given customer. Real provisioning lives in `routes/onramp_flow.py`
        # via `ensure_org_prosper_wallet()`.
        raise NotSupportedByProvider(
            "Alfred does not provision wallets — use Prosper Stellar provisioning")

    # ------------------------------------------------------------------ fiat / CVU
    async def ensure_fiat_account(self, params: FiatAccountParams,
                                    files: Optional[KycFiles] = None,
                                    *,
                                    andes_user_id: Optional[str] = None):
        raise NotSupportedByProvider(
            "Alfred does not support per-user CVU; capabilities.supportsDedicatedAccounts=False")

    async def get_funding_instructions(self, *, andes_user_id):
        # Alfred surfaces a deposit address per order, not a permanent CVU.
        return {"cvu": None, "alias": None}

    # ------------------------------------------------------------------ balances
    async def get_balances(self, *, andes_user_id):
        # Alfred doesn't expose a balances endpoint — capabilities.supportsBalances=False
        return []

    # ------------------------------------------------------------------ onramp
    async def initiate_onramp(self, *, andes_user_id, **kwargs):
        # Order-based onramp. The full flow uses
        # `routes/client_alfred.py::create_onramp`; here we just surface the
        # deposit address shape so callers that only need instructions get
        # something usable (kwargs forwarded for compatibility).
        addr = kwargs.get("deposit_address")
        return OnrampInstructions(
            deposit_address=addr,
            network="stellar",
            payment_reference=kwargs.get("payment_reference"),
            extra={"alfred_customer_id": andes_user_id,
                    "alfred_mode": current_mode()})

    # ------------------------------------------------------------------ offramp
    async def initiate_offramp(self, *, andes_user_id, fiat_account_id,
                                 amount, to_cvu=None, to_alias=None):
        # The legacy adapter expects a richer `bank_account` dict, but for
        # Phase 13's RampProvider contract we surface a minimal RampOrder
        # built from Alfred's response. Existing `/v1/client/offramp/orders`
        # route keeps the legacy code path untouched.
        adapter = _get_alfred_adapter()
        bank_account = {"fiat_account_id": fiat_account_id,
                          "cvu": to_cvu, "alias": to_alias}
        # Need a quote first — call /quote/offramp synchronously via adapter.
        quote = await adapter.create_offramp_quote(
            usdc_amount=float(amount), target_currency="ARS")
        resp = await adapter.create_offramp_order(
            quote_id=quote.quote_id, usdc_amount=float(amount),
            target_currency="ARS",
            bank_account=bank_account, user_id=andes_user_id,
            org_id="alfred-managed",
            callback_url="")
        return RampOrder(
            id="ord_" + secrets.token_hex(6),
            provider=self.provider_id,
            external_id=resp.alfred_id,
            status=_alfred_status_to_tx(resp.status),
            asset=WalletAsset.USDC,
            chain=AvailableChain.STELLAR,
            amount=str(amount),
            destination_cvu=to_cvu,
            raw={"alfred": resp.raw if hasattr(resp, "raw") else {}})

    # ------------------------------------------------------------------ international
    async def quote_international(self, **kwargs) -> IntlQuote:
        raise NotSupportedByProvider(
            "Alfred does not offer international off-ramp")

    async def initiate_international_offramp(self, **kwargs):
        raise NotSupportedByProvider(
            "Alfred does not offer international off-ramp")

    # ------------------------------------------------------------------ movements
    async def list_movements(self, *, andes_user_id=None, filter=None
                                ) -> list[RampMovement]:
        # Not exposed in Alfred's API today; reconciliation reads from
        # `transactions` + `onramp_orders` collections instead.
        return []

    # ------------------------------------------------------------------ webhooks
    def verify_webhook(self, raw_body, headers):
        # Delegated to the existing Alfred webhook handler so we don't
        # duplicate HMAC logic. Returns False if the secret is missing.
        import hashlib as _h
        import hmac as _hm
        import os as _os
        secret = (_os.environ.get("ALFRED_WEBHOOK_SECRET") or "").encode()
        if not secret:
            return False
        sig = (headers.get("X-Alfred-Signature")
                  or headers.get("x-alfred-signature")
                  or headers.get("Signature")
                  or "")
        expected = _hm.new(secret, raw_body, _h.sha256).hexdigest()
        return _hm.compare_digest(sig.lower(), expected.lower())

    def parse_webhook(self, raw_body, headers=None):
        import json as _json
        headers = headers or {}
        try:
            payload = _json.loads(raw_body)
        except Exception:
            payload = {}
        return RampWebhookEvent(
            delivery_id=(headers.get("X-Webhook-Delivery-Id")
                          or payload.get("event_id")
                          or payload.get("transactionId")
                          or "alfred_" + secrets.token_hex(4)),
            event_type=(payload.get("type") or payload.get("status") or "unknown").lower(),
            payload=payload,
            signature_valid=self.verify_webhook(raw_body, headers),
            headers=headers)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
_ALFRED_TO_TX = {
    "FIAT_DEPOSIT_RECEIVED":   TxStatus.PENDING,
    "TRADE_COMPLETED":         TxStatus.PENDING,
    "ON_CHAIN_TX_SUBMITTED":   TxStatus.PENDING,
    "ON_CHAIN_TX_CONFIRMED":   TxStatus.SUCCESS,
    "COMPLETED":               TxStatus.SUCCESS,
    "SUCCESS":                 TxStatus.SUCCESS,
    "FAILED":                  TxStatus.FAILED,
    "REJECTED":                TxStatus.FAILED,
    "PENDING":                 TxStatus.PENDING,
}


def _alfred_status_to_tx(status: str) -> TxStatus:
    return _ALFRED_TO_TX.get((status or "").upper(), TxStatus.PENDING)
