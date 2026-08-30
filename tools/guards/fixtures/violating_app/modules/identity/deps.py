"""VIOLATION FIXTURE — a DECOY alias that protects nothing.

Named to satisfy a guard that only pattern-matched on the alias name, while
resolving to a dependency that performs no authorisation at all.
"""

from typing import Annotated

from fastapi import Depends


def require_child_access(min_role: str = "co_caregiver"):  # noqa: ANN201
    async def dependency() -> str:
        return min_role

    return dependency


async def _no_op() -> str:
    return "anyone"


ChildAccess = Annotated[str, Depends(_no_op)]
