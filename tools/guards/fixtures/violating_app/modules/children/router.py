"""VIOLATION FIXTURE — route-authorisation guard must FAIL on this file."""

from fastapi import APIRouter

router = APIRouter()


@router.get("/children/{child_id}/progress")
async def read_progress(child_id: str) -> dict[str, str]:
    # No require_child_access: any authenticated caregiver can read any child.
    return {"child_id": child_id}
