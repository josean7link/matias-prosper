"""Phase 6 — Admin clients module."""
from fastapi import APIRouter
from .crud import router as _crud
from .users import router as _users
from .links import router as _links
from .api_keys import router as _keys
from .webhooks import router as _webhooks
from .emails import router as _emails

router = APIRouter()
router.include_router(_crud)
router.include_router(_users)
router.include_router(_links)
router.include_router(_keys)
router.include_router(_webhooks)
router.include_router(_emails)
