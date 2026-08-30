"""Migration 0001 must match docs/02-data-model.md 2 exactly.

Transcribing twenty enums by hand is exactly the kind of thing that silently
drifts. This test parses the design document and compares.
"""

from __future__ import annotations

import importlib.util
import re
from pathlib import Path
from types import ModuleType

API_ROOT = Path(__file__).resolve().parents[2]
REPO_ROOT = API_ROOT.parents[1]
MIGRATION_PATH = API_ROOT / "migrations" / "versions" / "0001_enum_types.py"
DOCS = REPO_ROOT / "docs" / "02-data-model.md"


def _load_migration() -> ModuleType:
    spec = importlib.util.spec_from_file_location("migration_0001", MIGRATION_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _enums_from_docs() -> dict[str, tuple[str, ...]]:
    text = DOCS.read_text(encoding="utf-8")
    section = text.split("## 2. Enumerated types", 1)[1].split("## 3.", 1)[0]
    pattern = re.compile(r"CREATE TYPE\s+(\w+)\s+AS ENUM\s*\((.*?)\);", re.DOTALL)
    return {
        name: tuple(v.strip().strip("'") for v in body.split(",") if v.strip())
        for name, body in pattern.findall(section)
    }


def test_migration_declares_every_documented_enum() -> None:
    documented = _enums_from_docs()
    assert len(documented) == 19, f"parsed {len(documented)} enums from docs/02"
    declared = dict(_load_migration().ENUMS)
    assert set(declared) == set(documented)
    for name, values in documented.items():
        assert declared[name] == values, name
