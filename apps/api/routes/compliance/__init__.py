"""Phase 5 — Compliance module routes (split into 6 sub-files)."""
from fastapi import APIRouter

from .legacy import router as _legacy_router
from .kyc import router as _kyc_router
from .kyb import router as _kyb_router
from .kyt import router as _kyt_router
from .risk_routes import router as _risk_router
from .alerts_routes import router as _alerts_router
from .limits import router as _limits_router

router = APIRouter()
# Keep /compliance/* paths used by the existing /admin/compliance legacy page.
router.include_router(_legacy_router)
# New /admin/compliance/* family
router.include_router(_kyc_router)
router.include_router(_kyb_router)
router.include_router(_kyt_router)
router.include_router(_risk_router)
router.include_router(_alerts_router)
router.include_router(_limits_router)
