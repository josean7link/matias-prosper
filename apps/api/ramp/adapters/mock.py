"""Phase 13 — `RampMockAdapter` (PRD §10).

Generic in-memory mock parameterised by `provider_id` so it reports the
right `capabilities()` (alfred=order, andeslabs=deposit-driven, CVU, etc.).

Used when `RAMP_PROVIDER_MODE=mock`. Designed so that flipping
`mode=real` in `ramp_provider_config` is a zero-code change for callers.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import secrets
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from ..provider import (
    AvailableChain, FiatAccountParams, FiatAccountStatus, IntlQuote, KycFiles,
    OnboardingStatus, OnrampInstructions, RampAccount, RampBalance,
    RampFiatAccount, RampMovement, RampOrder, RampProvider,
    RampProviderCapabilities, RampWallet, RampWebhookEvent, TxStatus,
    WalletAsset, FiatMovementType,
)

logger = logging.getLogger("prosper.ramp.mock")


# ---------------------------------------------------------------------------
# Capability templates per provider (PRD §2.1)
# ---------------------------------------------------------------------------
_ALFRED_CAPS = RampProviderCapabilities(
    id="alfred", fiatRails=["AR_CVU"],
    producedAssets=[WalletAsset.USDC],
    chains=[AvailableChain.STELLAR],
    supportsDedicatedAccounts=False,
    supportsBalances=True,
    supportsOnramp=True,
    supportsOfframp=True,
    supportsInternationalOfframp=False,
    onrampModel="order")


_ANDES_CAPS = RampProviderCapabilities(
    id="andeslabs", fiatRails=["AR_CVU"],
    producedAssets=[WalletAsset.ARSA, WalletAsset.USDC, WalletAsset.USDT],
    chains=[AvailableChain.STELLAR, AvailableChain.BASE, AvailableChain.WORLDCHAIN],
    supportsDedicatedAccounts=True,
    supportsBalances=True,
    supportsOnramp=True,
    supportsOfframp=True,
    supportsInternationalOfframp=True,
    onrampModel="deposit-driven")


_CAPS = {"alfred": _ALFRED_CAPS, "andeslabs": _ANDES_CAPS}


def _mock_signing_secret() -> bytes:
    return (os.environ.get("RAMP_MOCK_WEBHOOK_SECRET")
              or "ramp-mock-secret-change-me").encode()


# ---------------------------------------------------------------------------
# Mock adapter
# ---------------------------------------------------------------------------
class RampMockAdapter(RampProvider):

    def __init__(self, provider_id: str = "alfred") -> None:
        if provider_id not in _CAPS:
            raise ValueError(f"Mock provider_id must be one of {list(_CAPS)}")
        self.provider_id = provider_id  # type: ignore[assignment]
        # In-memory stores keyed by mock user_id
        self._accounts: dict[str, RampAccount] = {}
        self._wallets: dict[str, list[RampWallet]] = defaultdict(list)
        self._fiat: dict[str, RampFiatAccount] = {}
        self._balances: dict[str, list[RampBalance]] = defaultdict(list)
        self._movements: list[RampMovement] = []

    # ------------------------------------------------------------------ caps
    def capabilities(self) -> RampProviderCapabilities:
        return _CAPS[self.provider_id]

    # ------------------------------------------------------------------ accounts
    async def create_account(self, *, org_id, end_customer_id, display_name=None):
        # Idempotent — same (org_id, end_customer_id) returns the same user_id
        cached = next((a for a in self._accounts.values()
                       if a.org_id == org_id and a.end_customer_id == end_customer_id),
                       None)
        if cached:
            return cached
        user_id = "u_" + secrets.token_hex(8)
        name = display_name or f"{org_id}:{end_customer_id}"
        acc = RampAccount(
            id="acc_" + secrets.token_hex(6),
            org_id=org_id, end_customer_id=end_customer_id,
            provider=self.provider_id, provider_user_id=user_id,
            account_name=name,
            raw={"mode": "mock"})
        self._accounts[user_id] = acc
        # Seed an empty ARSa balance for deposit-driven providers
        if self.provider_id == "andeslabs":
            self._balances[user_id] = [
                RampBalance(asset=WalletAsset.ARSA, chain=AvailableChain.STELLAR,
                              balance="0", as_of=_utcnow())]
        return acc

    # ------------------------------------------------------------------ wallets
    async def ensure_wallet(self, *, andes_user_id, asset, chain):
        wallets = self._wallets[andes_user_id]
        for w in wallets:
            if w.asset == asset and w.chain == chain:
                return w
        addr = _mock_address(chain)
        w = RampWallet(
            id="w_" + secrets.token_hex(6),
            org_id=self._org_for_user(andes_user_id),
            ramp_account_id=self._account_id_for_user(andes_user_id),
            provider=self.provider_id,
            provider_user_id=andes_user_id,
            asset=asset, chain=chain, address=addr,
            raw={"mode": "mock"})
        wallets.append(w)
        return w

    # ------------------------------------------------------------------ fiat
    async def ensure_fiat_account(self, params: FiatAccountParams,
                                    files: Optional[KycFiles] = None,
                                    *,
                                    andes_user_id: Optional[str] = None):
        caps = self.capabilities()
        if not caps.supportsDedicatedAccounts:
            from ..provider import NotSupportedByProvider
            raise NotSupportedByProvider(
                f"{self.provider_id} mock does not support dedicated fiat accounts")
        # Idempotent per (org_id, end_customer_id)
        cached = next((f for f in self._fiat.values()
                       if f.org_id == params.org_id
                       and f.holder_tax_id == params.holder_tax_id
                       and f.account_type == params.account_type),
                       None)
        if cached:
            return cached
        # Look up the ramp_account
        acc = next((a for a in self._accounts.values()
                     if a.org_id == params.org_id
                     and a.end_customer_id == params.end_customer_id), None)
        ramp_account_id = acc.id if acc else "acc_unknown"
        fa = RampFiatAccount(
            id="fa_" + secrets.token_hex(6),
            org_id=params.org_id,
            ramp_account_id=ramp_account_id,
            provider=self.provider_id,
            fiat_account_id="fid_" + secrets.token_hex(8),
            account_type=params.account_type,
            cvu=_fake_cvu(),
            alias=params.alias or _fake_alias(params.holder_name),
            holder_name=params.holder_name,
            holder_tax_id=params.holder_tax_id,
            status=FiatAccountStatus.COMPLETED,
            onboarding_status=OnboardingStatus.APPROVED,
            raw={"mode": "mock", "kyc_files": list((files or KycFiles()).files)})
        self._fiat[fa.fiat_account_id] = fa
        return fa

    async def get_funding_instructions(self, *, andes_user_id):
        # Find first fiat account associated with this user via ramp_account
        for fa in self._fiat.values():
            acc = next((a for a in self._accounts.values()
                         if a.id == fa.ramp_account_id
                         and a.provider_user_id == andes_user_id), None)
            if acc:
                return {"cvu": fa.cvu, "alias": fa.alias}
        return {"cvu": None, "alias": None}

    # ------------------------------------------------------------------ balances
    async def get_balances(self, *, andes_user_id):
        return list(self._balances.get(andes_user_id, []))

    # ------------------------------------------------------------------ onramp
    async def initiate_onramp(self, *, andes_user_id, **kwargs):
        caps = self.capabilities()
        if caps.onrampModel == "deposit-driven":
            inst = await self.get_funding_instructions(andes_user_id=andes_user_id)
            return OnrampInstructions(
                cvu=inst["cvu"], alias=inst["alias"],
                payment_reference="prosper-" + secrets.token_hex(4),
                expires_at=_utcnow() + timedelta(hours=24),
                extra={"mode": "mock", "model": "deposit-driven"})
        # Order-based: return a pretend deposit address
        return OnrampInstructions(
            deposit_address=_mock_address(AvailableChain.STELLAR),
            network="stellar",
            payment_reference="alfred-" + secrets.token_hex(4),
            expires_at=_utcnow() + timedelta(minutes=30),
            extra={"mode": "mock", "model": "order"})

    # ------------------------------------------------------------------ offramp
    async def initiate_offramp(self, *, andes_user_id, fiat_account_id,
                                 amount, to_cvu=None, to_alias=None):
        order = RampOrder(
            id="ord_" + secrets.token_hex(6),
            provider=self.provider_id,
            external_id="mockord_" + secrets.token_hex(8),
            status=TxStatus.PENDING,
            asset=WalletAsset.ARSA if self.provider_id == "andeslabs" else WalletAsset.USDC,
            chain=AvailableChain.STELLAR,
            amount=str(amount),
            destination_cvu=to_cvu,
            raw={"mode": "mock", "fiat_account_id": fiat_account_id})
        self._movements.append(_movement_from_order(order, andes_user_id,
                                                       FiatMovementType.WITHDRAWAL,
                                                       self._org_for_user(andes_user_id),
                                                       self._account_id_for_user(andes_user_id)))
        return order

    # ------------------------------------------------------------------ international
    async def quote_international(self, **kwargs):
        from_currency = kwargs.get("from_currency", "ARS")
        to_currency   = kwargs.get("to_currency", "BOB")
        from_amount   = kwargs.get("from_amount", "100000")
        # Pretend FX
        rate = "0.0050" if to_currency == "BOB" else "0.0025"
        to_amount = str(float(from_amount) * float(rate))
        return IntlQuote(
            quote_id="iq_" + secrets.token_hex(6),
            from_currency=from_currency, to_currency=to_currency,
            from_amount=str(from_amount), to_amount=to_amount,
            rate=rate, fee="0",
            expires_at=_utcnow() + timedelta(minutes=10),
            raw={"mode": "mock"})

    async def initiate_international_offramp(self, **kwargs):
        order = RampOrder(
            id="ord_" + secrets.token_hex(6),
            provider=self.provider_id,
            external_id="mockintl_" + secrets.token_hex(8),
            status=TxStatus.PENDING,
            asset=WalletAsset.ARSA,
            chain=AvailableChain.STELLAR,
            amount=str(kwargs.get("amount", 0)),
            raw={"mode": "mock", "intl": True, **kwargs})
        return order

    # ------------------------------------------------------------------ movements
    async def list_movements(self, *, andes_user_id=None, filter=None):
        if andes_user_id is None:
            return list(self._movements)
        acc_id = self._account_id_for_user(andes_user_id)
        return [m for m in self._movements if m.ramp_account_id == acc_id]

    # ------------------------------------------------------------------ webhooks
    def verify_webhook(self, raw_body, headers):
        sig = headers.get("X-Webhook-Signature") or headers.get("x-webhook-signature") or ""
        expected = hmac.new(_mock_signing_secret(), raw_body,
                              hashlib.sha256).hexdigest()
        return hmac.compare_digest(sig, expected)

    def parse_webhook(self, raw_body, headers=None):
        headers = headers or {}
        try:
            payload = json.loads(raw_body)
        except Exception:
            payload = {}
        return RampWebhookEvent(
            delivery_id=(headers.get("X-Webhook-Delivery-Id")
                          or headers.get("x-webhook-delivery-id")
                          or "mock_" + secrets.token_hex(6)),
            event_type=payload.get("type", "unknown"),
            payload=payload,
            signature_valid=self.verify_webhook(raw_body, headers),
            headers=headers)

    # ------------------------------------------------------------------ helpers
    # Public helper used by /v1/ramp/dev/simulate-deposit (PRD §10 simulator)
    def simulate_deposit(self, *, andes_user_id: str, amount: float,
                           asset: WalletAsset = WalletAsset.ARSA,
                           chain: AvailableChain = AvailableChain.STELLAR
                           ) -> RampMovement:
        """Bump the in-memory balance + record a movement so the end-to-end
        deposit-driven flow can be exercised without a real bank."""
        balances = self._balances.setdefault(andes_user_id, [])
        slot = next((b for b in balances if b.asset == asset and b.chain == chain), None)
        if slot is None:
            slot = RampBalance(asset=asset, chain=chain, balance="0",
                                as_of=_utcnow())
            balances.append(slot)
        slot.balance = str(round(float(slot.balance) + float(amount), 6))
        slot.as_of = _utcnow()

        mov = RampMovement(
            id="mov_" + secrets.token_hex(6),
            org_id=self._org_for_user(andes_user_id),
            ramp_account_id=self._account_id_for_user(andes_user_id),
            provider=self.provider_id,
            external_id="mockdep_" + secrets.token_hex(8),
            kind=FiatMovementType.DEPOSIT,
            asset=asset, chain=chain, amount=str(amount),
            status=TxStatus.SUCCESS,
            occurred_at=_utcnow(),
            raw={"mode": "mock", "simulator": True})
        self._movements.append(mov)
        return mov

    # ------------------------------------------------------------------ internals
    def _account_id_for_user(self, user_id: str) -> str:
        a = self._accounts.get(user_id)
        return a.id if a else "acc_unknown"

    def _org_for_user(self, user_id: str) -> str:
        a = self._accounts.get(user_id)
        return a.org_id if a else "org_unknown"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _mock_address(chain: AvailableChain) -> str:
    if chain == AvailableChain.STELLAR:
        return "C" + secrets.token_hex(28).upper()[:55]
    if chain == AvailableChain.BASE:
        return "0x" + secrets.token_hex(20)
    return "0x" + secrets.token_hex(20)  # worldchain placeholder


def _fake_cvu() -> str:
    """22-digit CVU. First 4 = banco fictisio + sucursal."""
    return "0000003" + str(secrets.randbelow(10**14)).zfill(14) + str(secrets.randbelow(10))


def _fake_alias(holder_name: str) -> str:
    seed = (holder_name or "client").lower().replace(" ", "")[:10]
    return f"{seed}.prosper.mock"


def _movement_from_order(order: RampOrder, andes_user_id: str,
                          kind: FiatMovementType, org_id: str,
                          ramp_account_id: str) -> RampMovement:
    return RampMovement(
        id="mov_" + secrets.token_hex(6),
        org_id=org_id, ramp_account_id=ramp_account_id,
        provider=order.provider, external_id=order.external_id,
        kind=kind, asset=order.asset, chain=order.chain,
        amount=order.amount, status=order.status,
        destination_cvu=order.destination_cvu,
        occurred_at=_utcnow(), raw={"mode": "mock", "from_order": order.id})
