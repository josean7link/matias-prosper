"""Auto-load backend/.env for pytest sessions so tests can hit MongoDB."""
import os
import sys
from pathlib import Path

# Make `backend/` importable regardless of cwd
BACKEND = Path(__file__).resolve().parent.parent
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

# Load .env if not already in the environment
if "MONGO_URL" not in os.environ:
    from dotenv import load_dotenv
    load_dotenv(BACKEND / ".env")
