# ruff: noqa: INP001
"""Pytest configuration shared across backend tests."""

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# Tests should fail fast if auth-mode wiring breaks, but still need deterministic
# defaults during import-time settings initialization, regardless of shell env.
os.environ["AUTH_MODE"] = "local"
os.environ["LOCAL_AUTH_TOKEN"] = "test-local-token-0123456789-0123456789-0123456789x"
os.environ["BASE_URL"] = "http://localhost:8000"

# Pre-import the models package so SQLModel.metadata is fully populated before
# any test calls ``SQLModel.metadata.create_all``. Tests that import only a
# subset of model modules (and don't go through ``app.db.session``) still need
# every cross-table FK to resolve.
import app.models  # noqa: E402, F401
