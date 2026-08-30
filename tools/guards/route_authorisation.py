#!/usr/bin/env python
"""GUARD 1 — every child-scoped route declares require_child_access.

A route that takes a child_id and forgets the authorisation dependency is an
IDOR against a child's clinical record. Normal tests do not catch it because the
happy path works perfectly.

A route may declare the dependency in either of two sanctioned ways:

    async def read_child(child_id: UUID, _a: ChildAccess) -> ...        # alias
    async def read_child(child_id: UUID,
                         _a = Depends(require_child_access)) -> ...     # direct

The alias form is what the codebase actually uses, and the first version of this
guard did not understand it — it failed the build on correctly-protected routes.
A guard that cries wolf on correct code is worse than no guard, because the fix
people reach for is to switch it off. So the aliases are recognised explicitly,
AND `_verify_aliases` checks that each one really is defined in terms of
`require_child_access`, so a decoy alias cannot be used to wave a route through.
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

#: Annotated aliases that wrap the dependency. Verified below, not trusted.
ACCESS_ALIASES = frozenset({"ChildAccess", "OwnerAccess", "TherapistAccess"})

DEPS_MODULE = APP_ROOT / "modules" / "identity" / "deps.py"

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
    """The dependency itself, or one of the verified aliases."""
    for child in ast.walk(node):
        if isinstance(child, ast.Name) and (
            child.id == REQUIRED_DEPENDENCY or child.id in ACCESS_ALIASES
        ):
            return True
        if isinstance(child, ast.Attribute) and (
            child.attr == REQUIRED_DEPENDENCY or child.attr in ACCESS_ALIASES
        ):
            return True
    return False


def _verify_aliases(result: GuardResult, deps_module: Path) -> None:
    """Each alias must genuinely resolve to require_child_access.

    Without this the alias list would be a hole: anyone could name a parameter
    `ChildAccess` and satisfy the guard while doing nothing.
    """
    if not deps_module.exists():
        return
    tree = ast.parse(deps_module.read_text(encoding="utf-8"), filename=str(deps_module))
    defined: dict[str, bool] = {}
    for node in ast.walk(tree):
        if not isinstance(node, ast.AnnAssign | ast.Assign):
            continue
        targets = (
            [node.target] if isinstance(node, ast.AnnAssign) else list(node.targets)
        )
        names = [t.id for t in targets if isinstance(t, ast.Name)]
        alias_names = [name for name in names if name in ACCESS_ALIASES]
        if not alias_names or node.value is None:
            continue
        wraps = any(
            (isinstance(inner, ast.Name) and inner.id == REQUIRED_DEPENDENCY)
            or (isinstance(inner, ast.Attribute) and inner.attr == REQUIRED_DEPENDENCY)
            for inner in ast.walk(node.value)
        )
        for name in alias_names:
            defined[name] = wraps

    for alias, wraps in sorted(defined.items()):
        if not wraps:
            result.violation(
                deps_module,
                1,
                f"alias {alias!r} does not resolve to {REQUIRED_DEPENDENCY} — "
                f"routes relying on it are unprotected",
            )


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


def check(
    modules_root: Path = MODULES_ROOT, deps_module: Path | None = None
) -> GuardResult:
    result = GuardResult("route-authorisation")
    router_files = [p for p in python_files(modules_root) if p.name == "router.py"]
    if not router_files:
        result.skip("no app/modules/*/router.py yet — activates with P01/P02")
        return result

    _verify_aliases(result, deps_module or DEPS_MODULE)

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
