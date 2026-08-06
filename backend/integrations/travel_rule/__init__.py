"""
Travel Rule (FATF / UIF) screening — provider-agnostic adapter.

Mirrors the sanctions adapter pattern but for the third regulatory gate.

The platform calls `provider().screen(subject)` after Andes confirms identity.
Result drives the activation gate alongside sanctions:

    travel_rule_status  client_can_operate?
    ──────────────────  ───────────────────
    pending             NO (banner "verificando datos travel-rule")
    clear               YES (data complete, VASP exchange ready)
    na                  YES (customer below threshold / not applicable)
    flagged             NO (compliance review needed)

Default provider (`TRAVEL_RULE_PROVIDER=manual`) returns `pending` so a
super_admin / finance must override manually until a real VASP travel-rule
provider (Notabene, Sumsub TR, TRP) is connected.

Env:
    TRAVEL_RULE_PROVIDER=manual         # default, MVP
    TRAVEL_RULE_PROVIDER=mock_clear     # E2E tests — auto-clear
    TRAVEL_RULE_PROVIDER=notabene|sumsub_tr|trp   # TODO real adapters
"""
from __future__ import annotations

import os
import logging
from dataclasses import dataclass, field
from typing import Literal, Optional

logger = logging.getLogger("prosper.travel_rule")

TravelRuleStatus = Literal["pending", "clear", "na", "flagged"]


@dataclass
class TravelRuleSubject:
    """Minimum data needed to assess travel-rule readiness for a customer."""
    subject_type: Literal["individual", "business"]
    org_id: str
    full_name: str
    cuit: Optional[str] = None
    country: str = "AR"
    # Expected monthly volume in USD — used by real adapters to decide if
    # the customer crosses the FATF threshold. Manual provider ignores it.
    expected_monthly_volume_usd: Optional[float] = None


@dataclass
class TravelRuleResult:
    status: TravelRuleStatus
    provider: str
    reason: Optional[str] = None
    raw: dict = field(default_factory=dict)


class TravelRuleProvider:
    name: str = "base"

    async def screen(self, subject: TravelRuleSubject) -> TravelRuleResult:
        raise NotImplementedError


class ManualProvider(TravelRuleProvider):
    name = "manual"

    async def screen(self, subject: TravelRuleSubject) -> TravelRuleResult:
        logger.info("travel_rule.manual.queued org=%s subject=%s",
                       subject.org_id, subject.full_name)
        return TravelRuleResult(
            status="pending",
            provider=self.name,
            reason="awaiting manual review by compliance officer")


class MockClearProvider(TravelRuleProvider):
    name = "mock_clear"

    async def screen(self, subject: TravelRuleSubject) -> TravelRuleResult:
        return TravelRuleResult(status="clear", provider=self.name,
                                   reason="mock provider — auto-cleared")


def get_provider() -> TravelRuleProvider:
    p = (os.environ.get("TRAVEL_RULE_PROVIDER") or "manual").strip().lower()
    if p == "manual":
        return ManualProvider()
    if p == "mock_clear":
        return MockClearProvider()
    logger.warning("Unknown TRAVEL_RULE_PROVIDER=%s — falling back to manual", p)
    return ManualProvider()
