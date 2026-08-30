"""CONTROL FIXTURE — route-authorisation guard must PASS on this file.

Uses the ALIAS form (`ChildAccess`), which is what the real routers use. The
first version of the guard did not understand it and failed the build on
correctly-protected routes; this fixture is what stops that regressing.
"""

from fastapi import APIRouter, Depends

from app.modules.identity.deps import ChildAccess, require_child_access

router = APIRouter()


@router.get("/children/{child_id}/progress")
async def read_progress(child_id: str, _access: ChildAccess) -> dict[str, str]:
    return {"child_id": child_id}


@router.get("/children/{child_id}/report")
async def read_report(
    child_id: str, _auth: object = Depends(require_child_access)
) -> dict[str, str]:
    """The direct form must keep working too."""
    return {"child_id": child_id}


@router.get("/me")
async def read_me() -> dict[str, str]:
    # Not child-scoped, so no dependency is required.
    return {"ok": "yes"}
