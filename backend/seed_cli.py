"""CLI entrypoint:  python -m seed_cli  (or `python seed_cli.py`)
Re-runs the Phase 1 seed against the configured Mongo. Idempotent."""
import asyncio
import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / ".env")

from db import ensure_indexes  # noqa: E402
from seed import seed_phase1   # noqa: E402


async def main():
    await ensure_indexes()
    out = await seed_phase1()
    print("✓ seed applied:")
    print(f"  orgs:  {out['orgs']}")
    print(f"  users: {out['users']}")
    print(f"  db:    {os.environ.get('DB_NAME')}")


if __name__ == "__main__":
    asyncio.run(main())
