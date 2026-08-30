#!/usr/bin/env python
"""Create .env from .env.example if it is not already there.

A one-line shell conditional would do this, but it would be a different one line
on PowerShell and on sh. This is the same on every platform, and it never
overwrites an existing .env — losing a developer's local configuration to a
`just bootstrap` would be an unpleasant surprise.
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    example = REPO_ROOT / ".env.example"
    target = REPO_ROOT / ".env"
    if target.exists():
        print(".env already present, leaving it alone")
        return 0
    if not example.exists():
        print(f"{example} is missing", file=sys.stderr)
        return 1
    shutil.copyfile(example, target)
    print("created .env from .env.example")
    return 0


if __name__ == "__main__":
    sys.exit(main())
