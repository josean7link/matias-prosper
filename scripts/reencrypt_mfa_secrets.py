"""Fase 0 (Aug 2026) — MFA_FERNET_KEY rotation sweep.

Re-encrypts every user's TOTP secret from `MFA_FERNET_KEY_PREVIOUS`
to `MFA_FERNET_KEY`. Idempotent: rows already readable by the new key
are counted and skipped, never rewritten.

Usage:
    # Both keys must be exported in the environment. The script does
    # NOT read from files.
    export MFA_FERNET_KEY=<new_key>
    export MFA_FERNET_KEY_PREVIOUS=<old_key>
    python -m scripts.reencrypt_mfa_secrets

Never logs secret material. Progress lines only carry counts + user_id
(never the ciphertext, never the plaintext).
"""
from __future__ import annotations

import asyncio
import logging
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from cryptography.fernet import Fernet, InvalidToken   # noqa: E402
from db import USERS, col                                # noqa: E402

logger = logging.getLogger("prosper.mfa_rotate")
logging.basicConfig(level=logging.INFO,
                     format="%(asctime)s %(levelname)s %(message)s")

# Fields on the `users` doc that hold a Fernet ciphertext of a TOTP
# secret. Kept in one place — if we add more encrypted fields on User,
# extend this list.
_ENCRYPTED_FIELDS = ("mfa_secret", "mfa_pending")


def _load_key(name: str) -> Fernet:
    raw = os.environ.get(name)
    if not raw:
        raise SystemExit(f"env {name} is required")
    return Fernet(raw.encode() if isinstance(raw, str) else raw)


async def _reencrypt_one(doc: dict, new_key: Fernet, old_key: Fernet
                          ) -> dict:
    """Return {'user_id':…, 'field':…, 'action': 'rewrote'|'skipped_new'|
    'failed'} per encrypted field found. Never raises."""
    results = []
    updates: dict[str, str] = {}
    for field in _ENCRYPTED_FIELDS:
        ct = doc.get(field)
        if not ct:
            continue
        token = ct.encode() if isinstance(ct, str) else ct
        # Fast path: already readable with new key → nothing to do.
        try:
            new_key.decrypt(token)
            results.append({"field": field, "action": "skipped_new"})
            continue
        except InvalidToken:
            pass
        # Slow path: open with old key, rewrite with new key.
        try:
            plaintext = old_key.decrypt(token)
        except InvalidToken:
            results.append({"field": field, "action": "failed",
                             "reason": "unreadable_with_either_key"})
            continue
        updates[field] = new_key.encrypt(plaintext).decode()
        results.append({"field": field, "action": "rewrote"})
    if updates:
        await col(USERS).update_one({"user_id": doc["user_id"]},
                                       {"$set": updates})
    return {"user_id": doc.get("user_id"), "fields": results}


async def main() -> int:
    new_key = _load_key("MFA_FERNET_KEY")
    # PREVIOUS is required specifically for the sweep — if the operator
    # removed it already, they should not be re-running the sweep.
    old_key = _load_key("MFA_FERNET_KEY_PREVIOUS")

    query = {"$or": [{f: {"$exists": True, "$ne": None}}
                       for f in _ENCRYPTED_FIELDS]}
    total = await col(USERS).count_documents(query)
    logger.info("mfa-rotate: %d users hold at least one encrypted field",
                  total)

    rewrote = skipped_new = failed = 0
    async for doc in col(USERS).find(query, {"_id": 0,
                                                 "user_id": 1,
                                                 **{f: 1 for f in _ENCRYPTED_FIELDS}}):
        res = await _reencrypt_one(doc, new_key, old_key)
        for f in res["fields"]:
            if   f["action"] == "rewrote":      rewrote += 1
            elif f["action"] == "skipped_new":  skipped_new += 1
            elif f["action"] == "failed":       failed += 1
    logger.info("mfa-rotate: done. rewrote=%d skipped_new=%d failed=%d",
                  rewrote, skipped_new, failed)
    return 0 if failed == 0 else 2


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
