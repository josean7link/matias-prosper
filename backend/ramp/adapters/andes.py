"""Phase 14 — Andes adapter (REAL, talks to andes-gateway).

The gateway lives at `services/andes-gateway/` and wraps the official
`@andeslabs/mint-sdk`. This Python adapter only does HTTP. It uses an
internal token (env `GATEWAY_INTERNAL_TOKEN`) on every request.

Capabilities (PRD §2.1):
    id='andeslabs',
    producedAssets=[ARSA, USDC, USDT],
    chains=[stellar, base, worldchain],
    supportsDedicatedAccounts=True, onrampModel='deposit-driven',
    supportsInternationalOfframp=True.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import secrets
from typing import Any, Optional

import httpx

from ..provider import (
    AvailableChain, FiatAccountParams, FiatAccountStatus, IntlQuote, KycFiles,
    NotSupportedByProvider, OnboardingStatus, OnrampInstructions, RampAccount,
    RampBalance, RampFiatAccount, RampMovement, RampOrder, RampProvider,
    RampProviderCapabilities, RampWallet, RampWebhookEvent, TxStatus,
    WalletAsset,
)

logger = logging.getLogger("prosper.ramp.andes")


_CAPS = RampProviderCapabilities(
    id="andeslabs", fiatRails=["AR_CVU"],
    producedAssets=[WalletAsset.ARSA, WalletAsset.USDC, WalletAsset.USDT],
    chains=[AvailableChain.STELLAR, AvailableChain.BASE, AvailableChain.WORLDCHAIN],
    supportsDedicatedAccounts=True,
    supportsBalances=True,
    supportsOnramp=True,
    supportsOfframp=True,
    supportsInternationalOfframp=True,
    onrampModel="deposit-driven")


def _gateway_url() -> str:
    return (os.environ.get("ANDES_GATEWAY_URL")
              or "http://andes-gateway:8090").rstrip("/")


def _internal_token() -> str:
    return os.environ.get("GATEWAY_INTERNAL_TOKEN",
                            "dev-internal-token-change-me")


class AndesAdapter(RampProvider):
    provider_id = "andeslabs"

    def __init__(self) -> None:
        self._base = _gateway_url()
        self._token = _internal_token()

    # ------------------------------------------------------------------ caps
    def capabilities(self) -> RampProviderCapabilities:
        return _CAPS

    # ------------------------------------------------------------------ HTTP
    async def _gateway(self, method: str, path: str,
                        json_body: dict | None = None,
                        files: Optional[dict[str, tuple]] = None,
                        data: Optional[dict[str, Any]] = None,
                        ok_404_as_empty: bool = False) -> dict:
        url = f"{self._base}{path}"
        headers = {"X-Internal-Token": self._token, "Accept": "application/json"}
        if json_body is not None and files is None and data is None:
            headers["Content-Type"] = "application/json"
        try:
            async with httpx.AsyncClient(timeout=30.0) as cx:
                r = await cx.request(method, url, headers=headers,
                                       json=json_body if files is None else None,
                                       files=files, data=data)
        except httpx.HTTPError as e:
            raise NotSupportedByProvider(
                f"andes-gateway unreachable at {url}: {e}") from e

        if r.status_code == 404 and ok_404_as_empty:
            return {}
        if r.status_code == 409:
            # Already exists — caller may want to treat as "already provisioned"
            try:
                payload = r.json()
            except ValueError:
                payload = {"error": r.text[:200]}
            payload["__conflict__"] = True
            return payload
        if r.status_code >= 400:
            preview = r.text[:400].replace("\n", " ")
            raise NotSupportedByProvider(
                f"andes-gateway {r.status_code} on {path}: {preview}")
        if not r.text:
            return {}
        try:
            return r.json()
        except ValueError as e:
            raise NotSupportedByProvider(
                f"non-JSON from gateway {path}: {r.text[:200]!r}") from e

    # ------------------------------------------------------------------ accounts
    async def create_account(self, *, org_id, end_customer_id, display_name=None):
        # PRD: name must be unique + traceable across the Andes tenant
        name = display_name or f"{org_id}:{end_customer_id}"
        resp = await self._gateway("POST", "/accounts", {"name": name})
        user_id = str(resp.get("userId") or "")
        if not user_id:
            raise NotSupportedByProvider(
                f"gateway /accounts returned no userId: {resp!r}")
        return RampAccount(
            id="acc_" + secrets.token_hex(6),
            org_id=org_id, end_customer_id=end_customer_id,
            provider=self.provider_id, provider_user_id=user_id,
            account_name=name, raw=resp)

    # ------------------------------------------------------------------ wallets
    async def ensure_wallet(self, *, andes_user_id, asset, chain):
        body = {"user_id": andes_user_id,
                  "asset": asset.value, "chain": chain.value}
        resp = await self._gateway("POST", "/wallets", body)
        # 409 = already exists — treat as "ensure" semantics
        addr = (resp.get("address")
                  or (resp.get("wallet") or {}).get("address") or "")
        if not addr and resp.get("__conflict__"):
            # Re-query to fetch the existing wallet's address
            forUser = await self._gateway("GET", f"/wallets/{andes_user_id}")
            for w in (forUser.get("items") or []):
                if (w or {}).get("asset") == asset.value \
                        and (w or {}).get("chain") == chain.value:
                    addr = w.get("address", "")
                    resp = w
                    break
        return RampWallet(
            id="w_" + secrets.token_hex(6),
            org_id="", ramp_account_id="",
            provider=self.provider_id,
            provider_user_id=andes_user_id,
            asset=asset, chain=chain, address=addr, raw=resp)

    # ------------------------------------------------------------------ fiat / CVU
    async def ensure_fiat_account(self, params: FiatAccountParams,
                                    files: Optional[KycFiles] = None,
                                    *,
                                    andes_user_id: Optional[str] = None):
        # Map params → Andes Prod shape (snake_case, per @andeslabs/mint-sdk
        # types/fiat.d.ts). Real SDK fields per type:
        #   POST /fiat           → CreateFiatAccountRequest (individual + KYC)
        #     { user_id, chain, email, cuit, name, last_name, phone,
        #       birthdate } + multipart files: face, id_front, id_back
        #   POST /fiat/business  → CreateBusinessFiatAccountRequest
        #     { user_id, chain, holder_name }
        path = ("/fiat/business" if params.account_type.value == "business"
                  else "/fiat")

        # The Andes user_id is *not* the prosper end_customer_id; it's the
        # uuid returned by accounts.create. Callers (orchestrator) pass it
        # explicitly. Legacy callers may rely on end_customer_id which only
        # works when both are equal — keep that as a fallback for tests.
        user_id = andes_user_id or params.end_customer_id

        if path == "/fiat/business":
            body = {
                "user_id":     user_id,
                "chain":       params.chain.value,
                "holder_name": params.holder_name,
            }
            resp = await self._gateway("POST", path, json_body=body)
        else:
            # Individual: snake_case form fields + KYC files
            form_data: dict = {
                "user_id":   user_id,
                "chain":     params.chain.value,
                "name":      params.holder_name or "",
                "last_name": getattr(params, "last_name", "") or "",
                "email":     getattr(params, "email", "") or "",
                "cuit":      params.holder_tax_id or "",
                "phone":     getattr(params, "phone", "") or "",
                "birthdate": getattr(params, "birthdate", "") or "",
            }
            file_field = None
            if files and files.files:
                file_field = {name: (name, content, "application/octet-stream")
                               for name, content in files.files.items()}
            resp = await self._gateway(
                "POST", path,
                files=file_field or {"_": ("", b"", "application/octet-stream")},
                data=form_data)
        # SDK returns snake_case: fiat_account_id, onboarding_status
        fid = str(resp.get("fiat_account_id")
                    or resp.get("fiatAccountId")
                    or resp.get("id") or "")
        try:
            status = FiatAccountStatus(resp.get("status", "pending"))
        except ValueError:
            status = FiatAccountStatus.PENDING
        try:
            onb = OnboardingStatus(
                resp.get("onboarding_status")
                or resp.get("onboardingStatus")
                or "pending_approval")
        except ValueError:
            onb = OnboardingStatus.PENDING_APPROVAL
        return RampFiatAccount(
            id="fa_" + secrets.token_hex(6),
            org_id=params.org_id,
            ramp_account_id="",
            provider=self.provider_id,
            fiat_account_id=fid,
            account_type=params.account_type,
            cvu=resp.get("cvu"),
            alias=resp.get("alias") or params.alias,
            holder_name=params.holder_name,
            holder_tax_id=params.holder_tax_id,
            status=status,
            onboarding_status=onb,
            raw=resp)

    async def get_funding_instructions(self, *, andes_user_id):
        resp = await self._gateway("GET", f"/fiat/{andes_user_id}",
                                       ok_404_as_empty=True)
        items = resp.get("items") if isinstance(resp, dict) else []
        if not items:
            return {"cvu": None, "alias": None}
        first = items[0]
        return {"cvu": first.get("cvu"), "alias": first.get("alias")}

    # ------------------------------------------------------------------ balances
    async def get_balances(self, *, andes_user_id):
        resp = await self._gateway("GET", f"/wallets/{andes_user_id}",
                                       ok_404_as_empty=True)
        items = resp.get("items") if isinstance(resp, dict) else []
        out: list[RampBalance] = []
        for b in (items or []):
            try:
                asset = WalletAsset((b.get("asset") or "arsa").lower())
                chain = AvailableChain((b.get("chain") or "stellar").lower())
                out.append(RampBalance(
                    asset=asset, chain=chain,
                    balance=str(b.get("balance", "0"))))
            except Exception as e:
                logger.warning("ignored balance row %s · %s", b, e)
        return out

    # ------------------------------------------------------------------ on-chain transfer (P0 Feb-2026)
    async def initiate_onchain_transfer(
        self,
        *,
        andes_user_id: str,
        asset: str,
        chain: str,
        to_address: str,
        amount: float,
        max_retries_425: int = 3,
        max_retry_after_seconds: int = 60,
    ) -> dict:
        """Trigger an on-chain transfer FROM the user's Andes wallet TO an
        external address (typically the Prosper Treasury wallet for a given
        org × modality).

        Talks to gateway `POST /wallets/transfers`, which wraps
        `andes.wallets.transfers.create({user_id, chain, asset, to_address,
        amount})` per Andes docs:
        https://docs.andeslabs.io/api-reference/transfers#post-mint-v1-accounts-wallets-transfers

        The first outbound transfer from a freshly-created Stellar wallet
        may return HTTP 425 ("Too Early") while Andes funds the wallet
        reserve. We retry up to `max_retries_425` times, honoring the
        `Retry-After` header (capped at `max_retry_after_seconds`).

        Returns the gateway response on success:
            {transactionId, wallet_transaction_id, status, tx_hash?,
             from_address, to_address, amount, asset, chain, started_at}

        Raises `NotSupportedByProvider` on persistent failure.
        """
        url = f"{self._base}/wallets/transfers"
        headers = {
            "X-Internal-Token":  self._token,
            "Content-Type":      "application/json",
            "Accept":            "application/json",
        }
        body = {
            "user_id":    andes_user_id,
            "chain":      chain,
            "asset":      asset,
            "to_address": to_address,
            "amount":     amount,
        }

        attempt = 0
        last_err = ""
        while attempt <= max_retries_425:
            try:
                async with httpx.AsyncClient(timeout=30.0) as cx:
                    r = await cx.post(url, headers=headers, json=body)
            except httpx.HTTPError as e:
                raise NotSupportedByProvider(
                    f"andes-gateway unreachable at {url}: {e}") from e

            # 425 = wallet reserve still settling on Stellar — retry with backoff
            if r.status_code == 425 and attempt < max_retries_425:
                ra = (r.headers.get("Retry-After")
                       or r.headers.get("retry-after") or "")
                try:
                    wait_s = float(ra)
                except (TypeError, ValueError):
                    wait_s = 2.0 * (attempt + 1)  # exponential-ish fallback
                wait_s = min(max(wait_s, 1.0), float(max_retry_after_seconds))
                logger.info("andes transfer 425 Too Early — retry %d/%d "
                              "in %.1fs (user=%s)",
                              attempt + 1, max_retries_425, wait_s,
                              andes_user_id)
                await asyncio.sleep(wait_s)
                attempt += 1
                continue

            if r.status_code >= 400:
                preview = r.text[:400].replace("\n", " ")
                last_err = (f"andes-gateway {r.status_code} "
                              f"on /wallets/transfers: {preview}")
                raise NotSupportedByProvider(last_err)

            try:
                resp = r.json()
            except ValueError as e:
                raise NotSupportedByProvider(
                    f"non-JSON from gateway /wallets/transfers: "
                    f"{r.text[:200]!r}") from e
            return resp

        raise NotSupportedByProvider(
            f"andes transfer still 425 after {max_retries_425} retries; "
            f"last={last_err or '<no body>'}")

    # ------------------------------------------------------------------ onramp / offramp
    async def initiate_onramp(self, *, andes_user_id, **kwargs):
        funding = await self.get_funding_instructions(andes_user_id=andes_user_id)
        return OnrampInstructions(
            cvu=funding.get("cvu"), alias=funding.get("alias"),
            payment_reference="andes-" + secrets.token_hex(4),
            extra={"model": "deposit-driven"})

    async def initiate_offramp(self, *, andes_user_id, fiat_account_id,
                                 amount, to_cvu=None, to_alias=None):
        # TODO FASE 15 — gateway POST /fiat/withdraw (andes.fiat.withdraw)
        raise NotSupportedByProvider(
            "initiate_offramp wires in Phase 15 (withdraw + on-chain transfer)")

    async def quote_international(self, **kwargs):
        # TODO FASE 16 — international quote
        raise NotSupportedByProvider("international quote wires in Phase 16")

    async def initiate_international_offramp(self, **kwargs):
        # TODO FASE 16 — international offramp
        raise NotSupportedByProvider("international offramp wires in Phase 16")

    # ------------------------------------------------------------------ movements
    async def list_movements(self, *, andes_user_id: str,
                                limit: int = 200) -> list[dict]:
        """Fetch the CVU movement history for a given Andes user.

        Talks to gateway `GET /fiat/movements?user_id=…` which wraps
        `andes.fiat.movementsForUser(userId)`. Returns the raw rows from
        the Andes SDK; callers map them to the local `ramp_movements`
        schema. NOT cached here — the caller decides retention.
        """
        resp = await self._gateway("GET",
            f"/fiat/movements?user_id={andes_user_id}&limit={int(limit)}")
        items = resp.get("items") if isinstance(resp, dict) else None
        return items if isinstance(items, list) else []

    # ------------------------------------------------------------------ webhooks
    def verify_webhook(self, raw_body, headers):
        # TODO FASE 15 — ES256 verify using the gateway's /webhooks/signing-key
        return bool(headers.get("X-Webhook-Signature")
                     or headers.get("x-webhook-signature"))

    def parse_webhook(self, raw_body, headers=None):
        headers = headers or {}
        try:
            payload = json.loads(raw_body)
        except Exception:
            payload = {}
        return RampWebhookEvent(
            delivery_id=(headers.get("X-Webhook-Delivery-Id")
                          or "andes_" + secrets.token_hex(4)),
            event_type=str(payload.get("type") or "unknown"),
            payload=payload,
            signature_valid=self.verify_webhook(raw_body, headers),
            headers=headers)
