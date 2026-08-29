"""CONTROL FIXTURE — route-authorisation guard must PASS on this file."""

from fastapi import APIRouter, Depends

from app.modules.identity.deps import require_child_access

router = APIRouter()


@router.get("/children/{child_id}/progress")
async def read_progress(
    child_id: str, _auth: object = Depends(require_child_access)
) -> dict[str, str]:
    return {"child_id": child_id}


@router.get("/me")
async def read_me() -> dict[str, str]:
    # Not child-scoped, so no dependency is required.
    return {"ok": "yes"}
