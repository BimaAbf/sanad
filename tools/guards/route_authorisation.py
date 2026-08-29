#!/usr/bin/env python
"""GUARD 1 — every child-scoped route declares require_child_access.

A route that takes a child_id and forgets the authorisation dependency is an
IDOR against a child's clinical record. Normal tests do not catch it because the
happy path works perfectly.

STATUS: fully implemented, currently SKIPping because app/modules/ is empty.
        It activates the moment P01 lands `require_child_access` and P02 lands
        the first child-scoped router. TODO(P02): remove nothing — just confirm
        this reports PASS rather than SKIP once modules exist.
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

from _common import APP_ROOT, GuardResult, python_files

MODULES_ROOT = APP_ROOT / "modules"

#: The dependency that resolves caregiver_child and 403s on an unlinked child.
REQUIRED_DEPENDENCY = "require_child_access"

#: A path parameter named any of these makes a route child-scoped.
CHILD_PARAMS = frozenset({"child_id", "childId"})

HTTP_METHODS = frozenset({"get", "post", "put", "patch", "delete"})


def _is_route_decorator(node: ast.expr) -> str | None:
    """Return the path literal if this decorator is a FastAPI route."""
    if not isinstance(node, ast.Call):
        return None
    func = node.func
    if not isinstance(func, ast.Attribute) or func.attr not in HTTP_METHODS:
        return None
    if not node.args:
        return None
    first = node.args[0]
    if isinstance(first, ast.Constant) and isinstance(first.value, str):
        return first.value
    return None


def _mentions_dependency(node: ast.AST) -> bool:
    for child in ast.walk(node):
        if isinstance(child, ast.Name) and child.id == REQUIRED_DEPENDENCY:
            return True
        if isinstance(child, ast.Attribute) and child.attr == REQUIRED_DEPENDENCY:
            return True
    return False


def _check_function(
    func: ast.FunctionDef | ast.AsyncFunctionDef, path: Path, result: GuardResult
) -> None:
    routes = [p for p in (_is_route_decorator(d) for d in func.decorator_list) if p]
    if not routes:
        return
    child_scoped = any(f"{{{param}}}" in route for route in routes for param in CHILD_PARAMS)
    if not child_scoped:
        return
    # The dependency may sit in the route decorator's dependencies=[...] or in
    # the signature as a Depends(...) default. Both are accepted.
    in_decorator = any(_mentions_dependency(d) for d in func.decorator_list)
    in_signature = _mentions_dependency(func.args)
    if not (in_decorator or in_signature):
        result.violation(
            path,
            func.lineno,
            f"{func.name}() is child-scoped ({routes[0]}) but does not declare "
            f"{REQUIRED_DEPENDENCY} — this is an IDOR against a child's record",
        )


def check(modules_root: Path = MODULES_ROOT) -> GuardResult:
    result = GuardResult("route-authorisation")
    router_files = [p for p in python_files(modules_root) if p.name == "router.py"]
    if not router_files:
        result.skip("no app/modules/*/router.py yet — activates with P01/P02")
        return result

    for path in router_files:
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except SyntaxError as exc:
            result.violation(path, exc.lineno or 0, f"could not parse: {exc.msg}")
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
                _check_function(node, path, result)
    return result


if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).parent))
    sys.exit(check().report())
