"""Phase 04 — Portfolio snapshot endpoint (client-scoped, read-only).

The single source for the client polling loop. Backed by a 12s Redis
cache so that running the loop at 20s does not amplify load on Horizon
or on the DB.

NOT a place to expose new fields ad-hoc. Add them to
`services/portfolio_snapshot.build_snapshot` and document in PRD.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Response

from auth import CurrentUser, get_current_user
from services.portfolio_snapshot import CACHE_TTL_SECONDS, get_or_build

router = APIRouter(prefix="/client/me/portfolio",
                    tags=["client-portfolio"])


@router.get("/snapshot")
async def portfolio_snapshot(
    response: Response,
    user: CurrentUser = Depends(get_current_user),
):
    """User-scoped portfolio snapshot. Cached for 12s in Redis per user.

    Response headers communicate cache state to the browser:
      * `Cache-Control: private, max-age=<TTL>` — same TTL as Redis.
      * `X-Snapshot-Source` — `cache` | `fresh`.
      * `X-Snapshot-As-Of` — the `fetched_at` ISO timestamp.
    """
    doc = await get_or_build(user)
    response.headers["Cache-Control"] = f"private, max-age={CACHE_TTL_SECONDS}"
    response.headers["X-Snapshot-Source"] = doc.get("snapshot_source", "fresh")
    response.headers["X-Snapshot-As-Of"]  = doc.get("fetched_at", "")
    return doc
