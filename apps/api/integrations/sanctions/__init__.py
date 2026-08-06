"""
Sanctions / PEP screening — provider-agnostic adapter.

The platform calls `provider().screen(subject)` after Andes confirms identity
(`fiat.account.created`). Result drives the client activation gate:

    sanctions_status  client_can_operate?
    ──────────────    ───────────────────
    pending           NO (banner "estamos revisando")
    clear             YES (kyb_status may flip to `approved`)
    flagged           NO (blocked, compliance reviews)

The default provider (`SANCTIONS_PROVIDER=manual`) returns `pending` so a
human reviewer must explicitly mark each subject `clear`/`flagged` from the
super_admin queue. Swapping to ComplyAdvantage / Truora / Refinitiv is a
single-class change (`integrations/sanctions/comply_advantage.py`) — the
domain code (webhook + activation gate) does not change.

Env:
    SANCTIONS_PROVIDER=manual      # default, dev/MVP
    SANCTIONS_PROVIDER=mock_clear  # for E2E tests — auto-clear
    SANCTIONS_PROVIDER=comply_advantage|truora|…  # TODO real adapters
"""
from __future__ import annotations

import os
import logging
from dataclasses import dataclass, field
from typing import Literal, Optional

logger = logging.getLogger("prosper.sanctions")

ScreeningStatus = Literal["pending", "clear", "flagged"]


@dataclass
class ScreeningSubject:
    """Minimum data needed to run a sanctions/PEP screening."""
    subject_type: Literal["individual", "business"]
    org_id: str
    full_name: str
    cuit: Optional[str] = None            # Argentine tax id (11 digits)
    birthdate: Optional[str] = None       # YYYY-MM-DD
    country: str = "AR"


@dataclass
class ScreeningResult:
    status: ScreeningStatus
    provider: str
    reason: Optional[str] = None
    raw: dict = field(default_factory=dict)


class SanctionsProvider:
    name: str = "base"

    async def screen(self, subject: ScreeningSubject) -> ScreeningResult:
        raise NotImplementedError


class ManualProvider(SanctionsProvider):
    """No external API; compliance officer decides from the admin queue.

    Always returns ``pending``. The org sits in `sanctions_status=pending`
    until super_admin posts /admin/sanctions/{org_id}/decision.
    """
    name = "manual"

    async def screen(self, subject: ScreeningSubject) -> ScreeningResult:
        logger.info("sanctions.manual.queued org=%s subject=%s cuit=%s",
                       subject.org_id, subject.full_name, subject.cuit)
        return ScreeningResult(
            status="pending",
            provider=self.name,
            reason="awaiting manual review by compliance officer",
        )


class MockClearProvider(SanctionsProvider):
    """E2E-test convenience — returns `clear` immediately. NEVER use in prod."""
    name = "mock_clear"

    async def screen(self, subject: ScreeningSubject) -> ScreeningResult:
        return ScreeningResult(status="clear", provider=self.name,
                                  reason="mock provider — auto-cleared")


def get_provider() -> SanctionsProvider:
    p = (os.environ.get("SANCTIONS_PROVIDER") or "manual").strip().lower()
    if p == "manual":
        return ManualProvider()
    if p == "mock_clear":
        return MockClearProvider()
    # TODO: comply_advantage / truora / refinitiv — implement adapter then
    #       register here. Until then, default to manual so we never silently
    #       auto-clear an unmapped provider name.
    logger.warning("Unknown SANCTIONS_PROVIDER=%s — falling back to manual", p)
    return ManualProvider()
