"""Prosper Phase 0 — FastAPI passwordless-OTP auth.

Endpoints (per fase_00_bootstrap.md):
  POST /api/v1/auth/passwordless-login   { email } -> { code }
  POST /api/v1/auth/passwordless-token   { code, token } -> { accessToken }
  GET  /api/v1/auth/me                                  -> { email }
  POST /api/v1/auth/logout                              -> { ok: true }
  GET  /api/health                                      -> { ok: true }

Storage: MongoDB Motor (sessions) + Redis (OTP codes, 10-min TTL).
Email: Resend (RESEND_API_KEY); falls back to logging the OTP if not configured.
"""
from __future__ import annotations
import os
import secrets
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import FastAPI, APIRouter, HTTPException, Response, Request, Depends
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, EmailStr
from motor.motor_asyncio import AsyncIOMotorClient
import redis.asyncio as aioredis
import httpx
import jwt
from dotenv import load_dotenv
from pathlib import Path

ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / ".env")

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
MONGO_URL = os.environ["MONGO_URL"]
DB_NAME = os.environ["DB_NAME"]
REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
JWT_SECRET = os.environ.get("JWT_SECRET", "phase0-dev-secret-change-me")
JWT_ALGORITHM = "HS256"
JWT_TTL_SECONDS = 7 * 24 * 3600
OTP_TTL_SECONDS = 600  # 10 minutes
RESEND_API_KEY = os.environ.get("RESEND_API_KEY")
RESEND_FROM = os.environ.get("RESEND_FROM", "onboarding@resend.dev")
COOKIE_SECURE = os.environ.get("COOKIE_SECURE", "true").lower() == "true"

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("prosper")

# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------
app = FastAPI(title="Prosper Platform API", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=os.environ.get("CORS_ORIGINS", "*").split(","),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

mongo: AsyncIOMotorClient | None = None
redis_client: aioredis.Redis | None = None


@app.on_event("startup")
async def startup():
    global mongo, redis_client
    mongo = AsyncIOMotorClient(MONGO_URL)
    try:
        redis_client = aioredis.from_url(REDIS_URL, decode_responses=True)
        await redis_client.ping()
        logger.info("Redis connected.")
    except Exception as e:
        logger.warning(f"Redis unavailable ({e}); falling back to Mongo for OTP storage.")
        redis_client = None


@app.on_event("shutdown")
async def shutdown():
    if mongo:
        mongo.close()
    if redis_client:
        await redis_client.close()


def db():
    return mongo[DB_NAME]


# ---------------------------------------------------------------------------
# OTP storage (Redis-first, Mongo fallback for hot-reload dev without redis)
# ---------------------------------------------------------------------------
async def otp_put(token: str, code: str, email: str):
    payload = f"{code}|{email}"
    if redis_client:
        await redis_client.setex(f"otp:{token}", OTP_TTL_SECONDS, payload)
    else:
        await db()["otp_codes"].update_one(
            {"token": token},
            {"$set": {"token": token, "code": code, "email": email,
                      "expires_at": (datetime.now(timezone.utc) +
                                     timedelta(seconds=OTP_TTL_SECONDS)).isoformat()}},
            upsert=True,
        )


async def otp_pop(token: str) -> Optional[tuple[str, str]]:
    if redis_client:
        raw = await redis_client.get(f"otp:{token}")
        if raw:
            await redis_client.delete(f"otp:{token}")
            code, email = raw.split("|", 1)
            return code, email
        return None
    doc = await db()["otp_codes"].find_one_and_delete({"token": token})
    if not doc:
        return None
    if doc["expires_at"] < datetime.now(timezone.utc).isoformat():
        return None
    return doc["code"], doc["email"]


# ---------------------------------------------------------------------------
# Mail (Resend) — falls back to log line when API key missing
# ---------------------------------------------------------------------------
async def send_otp_email(email: str, code: str):
    subject = "Your Prosper sign-in code"
    body = (
        f"<p>Hi,</p>"
        f"<p>Your Prosper verification code is:</p>"
        f"<p style='font-family:monospace;font-size:28px;letter-spacing:4px'>"
        f"<b>{code}</b></p>"
        f"<p>This code expires in 10 minutes.</p>"
        f"<p>— Prosper</p>"
    )
    if not RESEND_API_KEY:
        logger.warning(f"[DEV OTP] {email} -> {code}  (set RESEND_API_KEY to send real emails)")
        return
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.post(
                "https://api.resend.com/emails",
                headers={"Authorization": f"Bearer {RESEND_API_KEY}",
                         "Content-Type": "application/json"},
                json={"from": RESEND_FROM, "to": [email],
                      "subject": subject, "html": body},
            )
            r.raise_for_status()
            logger.info(f"OTP email sent to {email}")
    except Exception as e:
        logger.error(f"Resend send failed: {e}; OTP for {email} was {code}")


# ---------------------------------------------------------------------------
# Auth helpers
# ---------------------------------------------------------------------------
def make_jwt(email: str) -> str:
    now = datetime.now(timezone.utc)
    return jwt.encode(
        {"sub": email, "iat": int(now.timestamp()),
         "exp": int((now + timedelta(seconds=JWT_TTL_SECONDS)).timestamp())},
        JWT_SECRET, algorithm=JWT_ALGORITHM,
    )


def parse_jwt(token: str) -> dict:
    try:
        return jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
    except jwt.PyJWTError:
        raise HTTPException(401, "Invalid or expired token")


async def get_current_user(request: Request) -> str:
    token = request.cookies.get("prosper_session")
    if not token:
        auth = request.headers.get("Authorization", "")
        if auth.startswith("Bearer "):
            token = auth[7:]
    if not token:
        raise HTTPException(401, "Not authenticated")
    payload = parse_jwt(token)
    return payload["sub"]


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------
api = APIRouter(prefix="/api")
v1 = APIRouter(prefix="/v1")


class LoginRequest(BaseModel):
    email: EmailStr


class LoginResponse(BaseModel):
    code: str  # opaque continuation token (NOT the OTP itself)


class TokenRequest(BaseModel):
    code: str       # the continuation token
    token: str      # the 4-digit OTP the user typed


class TokenResponse(BaseModel):
    accessToken: str


@v1.post("/auth/passwordless-login", response_model=LoginResponse)
async def passwordless_login(body: LoginRequest):
    otp = f"{secrets.randbelow(10000):04d}"
    continuation = secrets.token_urlsafe(24)
    await otp_put(continuation, otp, body.email.lower())
    await send_otp_email(body.email, otp)
    return {"code": continuation}


@v1.post("/auth/passwordless-token", response_model=TokenResponse)
async def passwordless_token(body: TokenRequest, response: Response):
    stored = await otp_pop(body.code)
    if not stored:
        raise HTTPException(401, "Code expired or already used")
    expected, email = stored
    if body.token.strip() != expected:
        # Re-insert so the user can retry (with a short grace period)
        await otp_put(body.code, expected, email)
        raise HTTPException(401, "Invalid OTP")
    access = make_jwt(email)
    response.set_cookie(
        "prosper_session", access,
        httponly=True, secure=COOKIE_SECURE, samesite="lax",
        path="/", max_age=JWT_TTL_SECONDS,
    )
    # Upsert user record
    await db()["users"].update_one(
        {"email": email},
        {"$set": {"email": email, "last_login": datetime.now(timezone.utc).isoformat()},
         "$setOnInsert": {"created_at": datetime.now(timezone.utc).isoformat()}},
        upsert=True,
    )
    return {"accessToken": access}


@v1.get("/auth/me")
async def me(email: str = Depends(get_current_user)):
    user = await db()["users"].find_one({"email": email}, {"_id": 0})
    return {"email": email, "user": user}


@v1.post("/auth/logout")
async def logout(response: Response):
    response.delete_cookie("prosper_session", path="/")
    return {"ok": True}


@api.get("/health")
async def health():
    return {"ok": True, "service": "prosper-api", "version": app.version}


api.include_router(v1)
app.include_router(api)
