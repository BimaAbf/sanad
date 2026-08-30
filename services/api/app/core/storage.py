"""S3-compatible object storage (MinIO locally, Cloudflare R2 in deployment)."""

from __future__ import annotations

from typing import Any

import aioboto3

from app.core.config import Settings


def session_for(settings: Settings) -> aioboto3.Session:
    return aioboto3.Session(
        aws_access_key_id=settings.s3_access_key_id,
        aws_secret_access_key=settings.s3_secret_access_key,
        region_name=settings.s3_region,
    )


async def check_storage(settings: Settings) -> dict[str, Any]:
    """Readiness probe for object storage. Never raises."""
    try:
        session = session_for(settings)
        async with session.client("s3", endpoint_url=settings.s3_endpoint_url) as client:
            await client.head_bucket(Bucket=settings.s3_bucket)
        return {"status": "ok"}
    except Exception as exc:  # noqa: BLE001 -- probe reports, never propagates
        return {"status": "error", "reason": type(exc).__name__}
