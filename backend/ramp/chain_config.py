"""Phase 17 — ARSa chain selection (Stellar | Base).

Resolves the effective chain for a given org or ramp account, with the
following precedence:

    1. account-level override (`ramp_accounts.arsa_chain_override`)
    2. org-level default      (`ramp_provider_config.default_arsa_chain`
                                where scope == org_id)
    3. global default         (`ramp_provider_config.default_arsa_chain`
                                where scope == 'global')
    4. env-var fallback       (`ANDES_DEFAULT_CHAIN`)
    5. hard-coded default     `stellar`

Concept: a wallet in Andes is keyed by (asset, chain). ARSa-stellar and
ARSa-base are distinct tokens on distinct chains with separate balances.
Selecting the chain decides where a new wallet gets minted; it never moves
or converts existing balances.

Allowed chains are constrained by `allowed_arsa_chains` on the same row
(default: ['stellar', 'base']).
"""
from __future__ import annotations

from typing import Optional

from db import col, RAMP_ACCOUNTS
from .provider import AvailableChain
from .registry import RAMP_PROVIDER_CONFIG

ARSA_CHAINS: list[str] = ["stellar", "base"]
DEFAULT_ARSA_CHAIN: str = "stellar"


def _coerce_chain(v: Optional[str]) -> Optional[AvailableChain]:
    if not v:
        return None
    try:
        return AvailableChain(v.lower())
    except ValueError:
        return None


async def _org_row(org_id: str) -> dict:
    row = await col(RAMP_PROVIDER_CONFIG).find_one(
        {"scope": org_id}, {"_id": 0,
                              "default_arsa_chain": 1,
                              "allowed_arsa_chains": 1}) or {}
    return row


async def _global_row() -> dict:
    row = await col(RAMP_PROVIDER_CONFIG).find_one(
        {"scope": "global"}, {"_id": 0,
                                 "default_arsa_chain": 1,
                                 "allowed_arsa_chains": 1}) or {}
    return row


async def get_org_arsa_chain_config(org_id: str) -> dict:
    """Return {default, allowed, source} for an org (with global fallback)."""
    import os
    org   = await _org_row(org_id)
    glob  = await _global_row()

    if org.get("default_arsa_chain"):
        return {
            "default": org["default_arsa_chain"],
            "allowed": org.get("allowed_arsa_chains") or ARSA_CHAINS,
            "source":  "org_override",
        }
    if glob.get("default_arsa_chain"):
        return {
            "default": glob["default_arsa_chain"],
            "allowed": glob.get("allowed_arsa_chains") or ARSA_CHAINS,
            "source":  "global",
        }
    env_default = (os.environ.get("ANDES_DEFAULT_CHAIN")
                     or DEFAULT_ARSA_CHAIN).lower()
    if env_default not in ARSA_CHAINS:
        env_default = DEFAULT_ARSA_CHAIN
    return {"default": env_default,
              "allowed": ARSA_CHAINS,
              "source": "env_default"}


async def resolve_arsa_chain(
        org_id: str,
        end_customer_id: Optional[str] = None) -> AvailableChain:
    """Resolve the effective ARSa chain for a (org_id, end_customer_id).

    See module docstring for the precedence rules. Always returns a valid
    `AvailableChain` member.
    """
    # 1) Per-account override
    if end_customer_id:
        acc = await col(RAMP_ACCOUNTS).find_one(
            {"org_id": org_id, "end_customer_id": end_customer_id},
            {"_id": 0, "arsa_chain_override": 1}) or {}
        ov = _coerce_chain(acc.get("arsa_chain_override"))
        if ov is not None:
            return ov

    # 2/3) Org / global default
    cfg = await get_org_arsa_chain_config(org_id)
    coerced = _coerce_chain(cfg["default"]) or AvailableChain(DEFAULT_ARSA_CHAIN)
    return coerced


async def resolve_arsa_chain_with_source(
        org_id: str,
        end_customer_id: Optional[str] = None) -> dict:
    """Like resolve_arsa_chain but also returns the source of the decision."""
    # account override first
    if end_customer_id:
        acc = await col(RAMP_ACCOUNTS).find_one(
            {"org_id": org_id, "end_customer_id": end_customer_id},
            {"_id": 0, "arsa_chain_override": 1}) or {}
        ov = _coerce_chain(acc.get("arsa_chain_override"))
        if ov is not None:
            return {"chain": ov.value, "source": "account_override"}
    cfg = await get_org_arsa_chain_config(org_id)
    return {"chain": cfg["default"], "source": cfg["source"]}
