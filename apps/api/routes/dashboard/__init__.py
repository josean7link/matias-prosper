"""Phase 2 — Admin dashboard router (split into one file per endpoint)."""
from fastapi import APIRouter

from .kpis import router as kpis_router
from .nav_history import router as nav_router
from .volume import router as volume_router
from .revenue import router as revenue_router
from .top_clients import router as top_clients_router
from .ops_queue import router as ops_queue_router
from .recent_activity import router as recent_router
from .ws import router as ws_router

router = APIRouter(prefix="/admin/dashboard", tags=["admin-dashboard"])
for r in (kpis_router, nav_router, volume_router, revenue_router,
          top_clients_router, ops_queue_router, recent_router, ws_router):
    router.include_router(r)
