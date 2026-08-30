#!/usr/bin/env python
"""Drop and rebuild the development database. `just db-reset`.

Everything in it is demo data. The point of the command is that the demo can be
shown from a known state — §30 of the demo specification asks for exactly this:
migrations, then seed, then the app, with no reliance on whatever the last run
left behind.

It refuses when `SANAD_ENVIRONMENT` is `production`, and it refuses when the
database URL is not the local one, because "drop every table" is not a command
that should be one typo away from a real one.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
API = REPO / "services" / "api"

#: The only hosts this command will touch. A database on any other host is not
#: a development database, whatever the environment variable says.
LOCAL_HOSTS = ("localhost", "127.0.0.1", "postgres")


def _database_url() -> str:
    env = os.environ.get("SANAD_DATABASE_URL")
    if env:
        return env
    for line in (REPO / ".env").read_text(encoding="utf-8").splitlines():
        if line.startswith("SANAD_DATABASE_URL="):
            return line.split("=", 1)[1].strip()
    raise SystemExit("db-reset: SANAD_DATABASE_URL is not set and .env has no entry for it.")


def _run(command: list[str], *, cwd: Path) -> None:
    print(f"$ {' '.join(command)}")
    result = subprocess.run(command, cwd=cwd, check=False)
    if result.returncode != 0:
        raise SystemExit(f"db-reset: `{' '.join(command)}` failed ({result.returncode}).")


def main() -> int:
    if os.environ.get("SANAD_ENVIRONMENT") == "production":
        print("db-reset: refusing to drop a production database.", file=sys.stderr)
        return 1

    url = _database_url()
    if not any(host in url for host in LOCAL_HOSTS):
        print(
            f"db-reset: refusing — {url.split('@')[-1]} is not a local database.",
            file=sys.stderr,
        )
        return 1

    # `DROP SCHEMA public CASCADE` rather than dropping the database: the
    # connection would have to be closed to drop its own database, and the
    # extensions live in the schema anyway so 0001 recreates them.
    _run(
        [
            "uv",
            "run",
            "python",
            "-c",
            (
                "import asyncio\n"
                "from sqlalchemy import text\n"
                "from app.core.config import get_settings\n"
                "from app.core.db import init_engine\n"
                "async def main():\n"
                "    engine = init_engine(get_settings())\n"
                "    async with engine.begin() as conn:\n"
                "        await conn.execute(text('DROP SCHEMA public CASCADE'))\n"
                "        await conn.execute(text('CREATE SCHEMA public'))\n"
                "    await engine.dispose()\n"
                "asyncio.run(main())"
            ),
        ],
        cwd=API,
    )
    _run(["uv", "run", "alembic", "upgrade", "head"], cwd=API)
    _run(["uv", "run", "python", "-m", "app.cli", "seed"], cwd=API)
    _run(["uv", "run", "python", "-m", "app.cli", "seed-demo"], cwd=API)
    print("db-reset: clean database, migrations applied, curriculum and demo family seeded.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
