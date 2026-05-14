"""MockProsperAdapter — deterministic, idempotent, in-process state.

Idempotency by `prosper_tx_id`: replaying the same tx returns the same result
(matching real Prosper backend semantics).
"""
from __future__ import annotations

import hashlib
import secrets
from typing import Any

from .adapter import (
    BalancesResp, ProsperAdapter, ProsperError, TokenOpResp, WalletResp,
)

# Process-local state
_WALLETS:    dict[str, dict[str, Any]] = {}   # user_ref_id -> {address, ...}
_BALANCES:   dict[str, float]          = {}   # user_ref_id -> token balance
_XLM:        dict[str, float]          = {}   # user_ref_id -> XLM balance
_TX_BY_PTX:  dict[str, dict[str, Any]] = {}   # prosper_tx_id -> response
_TXS_BY_USER:dict[str, list[dict]]     = {}   # user_ref_id -> [tx, ...]
_LEDGER_SEQ = [1_000_000]


def _next_ledger() -> str:
    _LEDGER_SEQ[0] += 1
    return str(_LEDGER_SEQ[0])


def _tx_hash(ptx: str) -> str:
    return hashlib.sha256(ptx.encode()).hexdigest()


def _stellar_addr(user_ref: str) -> str:
    h = hashlib.sha256(user_ref.encode()).hexdigest().upper()
    return "G" + h[:55]


class MockProsperAdapter(ProsperAdapter):
    """All operations are idempotent by `prosper_tx_id`."""

    mode = "mock"

    async def create_user_wallet(self, *, user_reference_id, prosper_tx_id) -> WalletResp:
        if prosper_tx_id in _TX_BY_PTX:
            return WalletResp(**_TX_BY_PTX[prosper_tx_id])
        if user_reference_id in _WALLETS:
            w = _WALLETS[user_reference_id]
            payload = {"address": w["address"], "tx_hash": w["tx_hash"],
                       "ledger": w["ledger"], "status": "success"}
            _TX_BY_PTX[prosper_tx_id] = payload
            return WalletResp(**payload)
        address = _stellar_addr(user_reference_id)
        tx_hash = _tx_hash(prosper_tx_id)
        ledger  = _next_ledger()
        _WALLETS[user_reference_id] = {"address": address, "tx_hash": tx_hash,
                                         "ledger": ledger}
        _BALANCES[user_reference_id] = 0.0
        _XLM[user_reference_id]      = 5.0  # XLM seed for fees
        payload = {"address": address, "tx_hash": tx_hash,
                   "ledger": ledger, "status": "success"}
        _TX_BY_PTX[prosper_tx_id] = payload
        return WalletResp(**payload)

    async def _ensure_wallet(self, user_ref: str) -> None:
        if user_ref not in _WALLETS:
            await self.create_user_wallet(
                user_reference_id=user_ref,
                prosper_tx_id="auto_" + secrets.token_hex(6))

    async def deposit_tokens(self, *, user_reference_id, amount, prosper_tx_id) -> TokenOpResp:
        if prosper_tx_id in _TX_BY_PTX:
            return TokenOpResp(**_TX_BY_PTX[prosper_tx_id])
        if amount <= 0:
            raise ProsperError("amount must be > 0")
        await self._ensure_wallet(user_reference_id)
        _BALANCES[user_reference_id] = (_BALANCES.get(user_reference_id, 0) + amount)
        bal = _BALANCES[user_reference_id]
        tx_hash = _tx_hash(prosper_tx_id)
        ledger  = _next_ledger()
        payload = {"tx_hash": tx_hash, "ledger": ledger, "status": "success",
                   "address": _WALLETS[user_reference_id]["address"],
                   "balance": str(bal)}
        _TX_BY_PTX[prosper_tx_id] = payload
        _TXS_BY_USER.setdefault(user_reference_id, []).append({
            "type": "deposit", "amount": str(amount), "prosper_tx_id": prosper_tx_id,
            "tx_hash": tx_hash, "ledger": ledger, "status": "success",
        })
        return TokenOpResp(**payload)

    async def withdraw_tokens(self, *, user_reference_id, amount, prosper_tx_id) -> TokenOpResp:
        if prosper_tx_id in _TX_BY_PTX:
            return TokenOpResp(**_TX_BY_PTX[prosper_tx_id])
        await self._ensure_wallet(user_reference_id)
        bal = _BALANCES.get(user_reference_id, 0)
        if amount <= 0:
            raise ProsperError("amount must be > 0")
        if amount > bal:
            raise ProsperError(f"Insufficient balance: have {bal}, need {amount}")
        _BALANCES[user_reference_id] = bal - amount
        tx_hash = _tx_hash(prosper_tx_id)
        ledger  = _next_ledger()
        payload = {"tx_hash": tx_hash, "ledger": ledger, "status": "success",
                   "address": _WALLETS[user_reference_id]["address"],
                   "balance": str(_BALANCES[user_reference_id])}
        _TX_BY_PTX[prosper_tx_id] = payload
        _TXS_BY_USER.setdefault(user_reference_id, []).append({
            "type": "withdraw", "amount": str(amount), "prosper_tx_id": prosper_tx_id,
            "tx_hash": tx_hash, "ledger": ledger, "status": "success",
        })
        return TokenOpResp(**payload)

    async def transfer_tokens(self, *, amount, from_user_id, to_user_id,
                                prosper_tx_id, metadata=None) -> TokenOpResp:
        if prosper_tx_id in _TX_BY_PTX:
            return TokenOpResp(**_TX_BY_PTX[prosper_tx_id])
        await self._ensure_wallet(from_user_id)
        await self._ensure_wallet(to_user_id)
        if amount <= 0:
            raise ProsperError("amount must be > 0")
        if _BALANCES.get(from_user_id, 0) < amount:
            raise ProsperError("from user has insufficient balance")
        _BALANCES[from_user_id] -= amount
        _BALANCES[to_user_id]    = _BALANCES.get(to_user_id, 0) + amount
        tx_hash = _tx_hash(prosper_tx_id)
        ledger  = _next_ledger()
        payload = {"tx_hash": tx_hash, "ledger": ledger, "status": "success",
                   "address": _WALLETS[from_user_id]["address"],
                   "balance": str(_BALANCES[from_user_id])}
        _TX_BY_PTX[prosper_tx_id] = payload
        return TokenOpResp(**payload)

    async def get_user_balances(self, user_id: str) -> BalancesResp:
        await self._ensure_wallet(user_id)
        return BalancesResp(
            address=_WALLETS[user_id]["address"],
            balance_prosper=str(_BALANCES.get(user_id, 0)),
            balance_xlm=str(_XLM.get(user_id, 0)),
        )

    async def get_user_transactions(self, user_id: str) -> dict:
        return {"transactions": _TXS_BY_USER.get(user_id, [])}

    async def get_assets(self) -> dict:
        return {
            "Issue":    {"address": "GISSUER_" + "X" * 48,
                          "assetCode": "PROS"},
            "Treasure": {"address": "GTREASURE_" + "X" * 46,
                          "balance": "10000000"},
        }


# Test helper
def reset_state() -> None:
    _WALLETS.clear(); _BALANCES.clear(); _XLM.clear()
    _TX_BY_PTX.clear(); _TXS_BY_USER.clear()
    _LEDGER_SEQ[0] = 1_000_000
