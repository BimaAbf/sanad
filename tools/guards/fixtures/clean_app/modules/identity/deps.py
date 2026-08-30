"""CONTROL FIXTURE — a genuine alias that resolves to require_child_access."""

from typing import Annotated

from fastapi import Depends


def require_child_access(min_role: str = "co_caregiver"):  # noqa: ANN201
    async def dependency() -> str:
        return min_role

    return dependency


ChildAccess = Annotated[str, Depends(require_child_access())]
OwnerAccess = Annotated[str, Depends(require_child_access("owner"))]
