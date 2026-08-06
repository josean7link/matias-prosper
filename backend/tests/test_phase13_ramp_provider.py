"""Phase 13 — RampProvider abstraction tests.

Covers:
  1. Capability declaration per adapter (alfred / andeslabs / mocks)
  2. Mock adapter behaviour (idempotency, in-memory store, simulator helper)
  3. Registry resolution order (per-org override → global → env-fallback)
  4. Andes adapter stub returns NotSupportedByProvider when gateway is down
  5. Alfred adapter shim integrates with existing /webhooks HMAC

Live Alfred / real Mongo tests live in other files; this suite is mostly
in-memory + a tiny bit of Mongo for the registry config table.
"""
from __future__ import annotations

import asyncio
import os
import sys
import pytest

sys.path.insert(0, "/app/backend")

from ramp import (
    AvailableChain, FiatAccountParams, FiatAccountType, NotSupportedByProvider,
    RampProviderCapabilities, WalletAsset, get_registry,
)
from ramp.adapters.mock import RampMockAdapter
from ramp.adapters.alfred import AlfredRampAdapter
from ramp.adapters.andes import AndesAdapter
from ramp.registry import RampProviderRegistry, ensure_default_provider_config, reset_registry


# ---------------------------------------------------------------------------
# Capability matrix — PRD §2.1
# ---------------------------------------------------------------------------
class TestCapabilities:
    def test_mock_alfred_caps(self):
        caps = RampMockAdapter(provider_id="alfred").capabilities()
        assert caps.id == "alfred"
        assert caps.onrampModel == "order"
        assert caps.supportsDedicatedAccounts is False
        assert WalletAsset.USDC in caps.producedAssets

    def test_mock_andes_caps(self):
        caps = RampMockAdapter(provider_id="andeslabs").capabilities()
        assert caps.id == "andeslabs"
        assert caps.onrampModel == "deposit-driven"
        assert caps.supportsDedicatedAccounts is True
        assert caps.supportsInternationalOfframp is True
        assert WalletAsset.ARSA in caps.producedAssets

    def test_alfred_shim_caps_match_mock(self):
        a = AlfredRampAdapter().capabilities()
        b = RampMockAdapter(provider_id="alfred").capabilities()
        assert a.id == b.id == "alfred"
        assert a.onrampModel == "order"

    def test_andes_stub_caps_match_mock(self):
        a = AndesAdapter().capabilities()
        b = RampMockAdapter(provider_id="andeslabs").capabilities()
        assert a.id == b.id == "andeslabs"
        assert a.onrampModel == "deposit-driven"


# ---------------------------------------------------------------------------
# Mock adapter behaviour — PRD §10
# ---------------------------------------------------------------------------
class TestMockAdapter:
    def test_create_account_idempotent(self):
        m = RampMockAdapter(provider_id="andeslabs")
        a1 = asyncio.run(m.create_account(org_id="org_x",
                                             end_customer_id="cust_1",
                                             display_name="Cust 1"))
        a2 = asyncio.run(m.create_account(org_id="org_x",
                                             end_customer_id="cust_1"))
        assert a1.id == a2.id
        assert a1.provider_user_id == a2.provider_user_id
        assert a1.provider == "andeslabs"

    def test_ensure_wallet_idempotent_per_pair(self):
        m = RampMockAdapter(provider_id="andeslabs")
        acc = asyncio.run(m.create_account(org_id="o", end_customer_id="c"))
        w1 = asyncio.run(m.ensure_wallet(andes_user_id=acc.provider_user_id,
                                            asset=WalletAsset.ARSA,
                                            chain=AvailableChain.STELLAR))
        w2 = asyncio.run(m.ensure_wallet(andes_user_id=acc.provider_user_id,
                                            asset=WalletAsset.ARSA,
                                            chain=AvailableChain.STELLAR))
        w3 = asyncio.run(m.ensure_wallet(andes_user_id=acc.provider_user_id,
                                            asset=WalletAsset.USDC,
                                            chain=AvailableChain.BASE))
        assert w1.id == w2.id and w1.address == w2.address
        assert w3.id != w1.id and w3.chain == AvailableChain.BASE
        assert w3.address.startswith("0x")

    def test_fiat_account_completed_and_funding(self):
        m = RampMockAdapter(provider_id="andeslabs")
        acc = asyncio.run(m.create_account(org_id="o", end_customer_id="c"))
        fa = asyncio.run(m.ensure_fiat_account(FiatAccountParams(
            org_id="o", end_customer_id="c",
            account_type=FiatAccountType.USER,
            chain=AvailableChain.STELLAR,
            holder_name="Juan Perez", holder_tax_id="20-50001091-2")))
        assert fa.cvu and len(fa.cvu) == 22
        assert fa.alias and ".prosper.mock" in fa.alias
        assert fa.status.value == "completed"
        funding = asyncio.run(m.get_funding_instructions(
            andes_user_id=acc.provider_user_id))
        assert funding["cvu"] == fa.cvu

    def test_alfred_mock_rejects_fiat_account(self):
        m = RampMockAdapter(provider_id="alfred")
        with pytest.raises(NotSupportedByProvider):
            asyncio.run(m.ensure_fiat_account(FiatAccountParams(
                org_id="o", end_customer_id="c",
                account_type=FiatAccountType.USER,
                chain=AvailableChain.STELLAR,
                holder_name="X")))

    def test_simulate_deposit_increments_balance(self):
        m = RampMockAdapter(provider_id="andeslabs")
        acc = asyncio.run(m.create_account(org_id="o", end_customer_id="c"))
        m.simulate_deposit(andes_user_id=acc.provider_user_id, amount=15000)
        bal = asyncio.run(m.get_balances(andes_user_id=acc.provider_user_id))
        arsa = next(b for b in bal if b.asset == WalletAsset.ARSA)
        assert float(arsa.balance) == 15000.0
        m.simulate_deposit(andes_user_id=acc.provider_user_id, amount=2500)
        bal = asyncio.run(m.get_balances(andes_user_id=acc.provider_user_id))
        arsa = next(b for b in bal if b.asset == WalletAsset.ARSA)
        assert float(arsa.balance) == 17500.0

    def test_onramp_instructions_shape(self):
        m_alfred = RampMockAdapter(provider_id="alfred")
        m_andes  = RampMockAdapter(provider_id="andeslabs")
        # Alfred → order-based: deposit_address present, no CVU.
        inst = asyncio.run(m_alfred.initiate_onramp(andes_user_id="x"))
        assert inst.deposit_address and inst.cvu is None
        # Andes → deposit-driven: CVU present after fiat account exists.
        acc = asyncio.run(m_andes.create_account(org_id="o",
                                                    end_customer_id="c"))
        asyncio.run(m_andes.ensure_fiat_account(FiatAccountParams(
            org_id="o", end_customer_id="c",
            account_type=FiatAccountType.USER,
            chain=AvailableChain.STELLAR, holder_name="Y")))
        inst = asyncio.run(m_andes.initiate_onramp(
            andes_user_id=acc.provider_user_id))
        assert inst.cvu and inst.alias

    def test_webhook_verification_hmac(self):
        import hmac
        import hashlib
        import json
        m = RampMockAdapter(provider_id="andeslabs")
        body = json.dumps({"type": "fiat.deposit.success",
                            "amount": "10000"}).encode()
        sig = hmac.new(
            (os.environ.get("RAMP_MOCK_WEBHOOK_SECRET")
             or "ramp-mock-secret-change-me").encode(),
            body, hashlib.sha256).hexdigest()
        headers = {"X-Webhook-Signature": sig,
                    "X-Webhook-Delivery-Id": "deliv_1"}
        assert m.verify_webhook(body, headers) is True
        evt = m.parse_webhook(body, headers)
        assert evt.signature_valid is True
        assert evt.delivery_id == "deliv_1"
        assert evt.event_type == "fiat.deposit.success"
        # Bad signature
        assert m.verify_webhook(body, {"X-Webhook-Signature": "bad"}) is False


# ---------------------------------------------------------------------------
# Andes stub — gateway down should raise NotSupportedByProvider cleanly
# ---------------------------------------------------------------------------
class TestAndesStub:
    def test_gateway_unreachable_raises(self, monkeypatch):
        monkeypatch.setenv("ANDES_GATEWAY_URL", "http://does-not-exist.localhost:65535")
        # Need a fresh adapter so it picks up the new env
        from ramp.adapters import andes as andes_mod
        a = andes_mod.AndesAdapter()
        with pytest.raises(NotSupportedByProvider):
            asyncio.run(a.create_account(org_id="o", end_customer_id="c"))


# ---------------------------------------------------------------------------
# Registry — resolution order
# ---------------------------------------------------------------------------
class TestRegistry:
    def test_env_fallback_default_alfred_mock(self, monkeypatch):
        monkeypatch.delenv("RAMP_PROVIDER", raising=False)
        monkeypatch.delenv("RAMP_PROVIDER_MODE", raising=False)
        reset_registry()
        import db as _db
        _db._client = None
        reg = get_registry()
        from db import col, RAMP_PROVIDER_CONFIG

        async def _go():
            # Drop any existing config so env fallback kicks in
            await col(RAMP_PROVIDER_CONFIG).delete_many({})
            return await reg.resolve()

        provider = asyncio.run(_go())
        assert provider.capabilities().id == "alfred"
        # mock mode → produces a RampMockAdapter under the hood
        assert isinstance(provider, RampMockAdapter)

    def test_global_row_wins_over_env(self, monkeypatch):
        monkeypatch.setenv("RAMP_PROVIDER", "andeslabs")
        monkeypatch.setenv("RAMP_PROVIDER_MODE", "real")
        reset_registry()
        import db as _db
        _db._client = None  # force a fresh motor client for this loop
        from db import col, RAMP_PROVIDER_CONFIG

        async def _go():
            await col(RAMP_PROVIDER_CONFIG).delete_many({})
            await col(RAMP_PROVIDER_CONFIG).insert_one({
                "scope": "global", "provider": "alfred", "mode": "mock",
                "enabled": True, "updated_by": "test"})
            return await get_registry().resolve()

        provider = asyncio.run(_go())
        # Global row says alfred/mock — should override the env vars.
        assert isinstance(provider, RampMockAdapter)
        assert provider.capabilities().id == "alfred"

    def test_per_org_override_wins(self):
        reset_registry()
        import db as _db
        _db._client = None
        from db import col, RAMP_PROVIDER_CONFIG

        async def _go():
            await col(RAMP_PROVIDER_CONFIG).delete_many({})
            # Global = alfred/mock
            await col(RAMP_PROVIDER_CONFIG).insert_one({
                "scope": "global", "provider": "alfred", "mode": "mock",
                "enabled": True})
            # Per-org override → andeslabs/mock
            await col(RAMP_PROVIDER_CONFIG).insert_one({
                "scope": "org_special", "provider": "andeslabs",
                "mode": "mock", "enabled": True})
            return (await get_registry().resolve(),
                      await get_registry().resolve(org_id="org_special"))

        glob, ovr = asyncio.run(_go())
        assert glob.capabilities().id == "alfred"
        assert ovr.capabilities().id == "andeslabs"

    def test_seed_global_row_is_idempotent(self):
        import db as _db
        _db._client = None
        from db import col, RAMP_PROVIDER_CONFIG

        async def _go():
            await col(RAMP_PROVIDER_CONFIG).delete_many({})
            await ensure_default_provider_config()
            await ensure_default_provider_config()  # second call no-op
            return await col(RAMP_PROVIDER_CONFIG).count_documents({"scope": "global"})

        assert asyncio.run(_go()) == 1
