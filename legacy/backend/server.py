"""Prosper Platform FastAPI server."""
from fastapi import FastAPI, APIRouter
from dotenv import load_dotenv
from starlette.middleware.cors import CORSMiddleware
import os
import logging
from pathlib import Path

ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / '.env')

from routers import ALL_ROUTERS  # noqa: E402
import seed as seed_module  # noqa: E402
from db import col, FUNDS, ORGANIZATIONS  # noqa: E402
import workers  # noqa: E402
import storage  # noqa: E402

app = FastAPI(title="Prosper Platform API", version="0.1.0")
api_router = APIRouter(prefix="/api")


@api_router.get("/")
async def root():
    return {"service": "prosper-platform", "status": "ok"}


@api_router.get("/health")
async def health():
    return {"ok": True}


for r in ALL_ROUTERS:
    api_router.include_router(r)

app.include_router(api_router)

app.add_middleware(
    CORSMiddleware,
    allow_credentials=True,
    allow_origins=os.environ.get('CORS_ORIGINS', '*').split(','),
    allow_methods=["*"],
    allow_headers=["*"],
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("prosper")


@app.on_event("startup")
async def startup():
    # Auto-seed demo data on first boot if empty
    try:
        n = await col(FUNDS).count_documents({"is_demo": True})
        if n == 0:
            logger.info("Seeding demo data on startup...")
            await seed_module.seed_all()
        # Always refresh demo users/sessions on boot (fresh tokens even if data seeded)
        orgs = await col(ORGANIZATIONS).find({"is_demo": True}, {"_id": 0}).to_list(50)
        if orgs:
            await seed_module.seed_demo_users(orgs)
    except Exception as e:
        logger.warning(f"Seed skipped: {e}")
    # Start background workers
    try:
        workers.start_scheduler()
    except Exception as e:
        logger.warning(f"Scheduler not started: {e}")
    # Initialize object storage
    try:
        await storage.init_storage()
    except Exception as e:
        logger.warning(f"Storage init failed: {e}")


@app.on_event("shutdown")
async def shutdown():
    try:
        workers.shutdown_scheduler()
    except Exception:
        pass
