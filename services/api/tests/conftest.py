"""Test environment.

These are set at *import* time, not in a fixture: ``app.main`` builds an app at
module scope (so ``uvicorn app.main:app`` works), and that import happens during
collection, before any fixture has run.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

# `tools/` holds the CI guards and the banned-terms list. Tests assert against
# them directly rather than re-declaring the lists, so a term added to the lint
# is immediately a term the notification send path rejects. That needs the repo
# root importable, and the api package is two levels below it.
REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

REQUIRED_ENV: dict[str, str] = {
    "MISK_ENVIRONMENT": "ci",
    "MISK_DATABASE_URL": "postgresql+asyncpg://misk:misk@localhost:55432/misk_test",
    "MISK_REDIS_URL": "redis://localhost:56379/1",
    "MISK_S3_ENDPOINT_URL": "http://localhost:59000",
    "MISK_S3_REGION": "us-east-1",
    "MISK_S3_BUCKET": "misk-media",
    # The docker-compose MinIO credentials, so the integration tests can reach
    # a real bucket. Not a real credential anywhere but this machine.
    "MISK_S3_ACCESS_KEY_ID": "miskminio",
    "MISK_S3_SECRET_ACCESS_KEY": "miskminio-dev-secret",
    "MISK_CORS_ORIGINS": "http://localhost:3000",
}

for _key, _value in REQUIRED_ENV.items():
    os.environ.setdefault(_key, _value)
