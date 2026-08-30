"""`AudioSink` over S3-compatible storage: MinIO locally, Cloudflare R2 deployed.

`InMemoryAudioSink` in `service.py` calls itself "the shape the real one must
match". This is the real one. R2 is S3-compatible, so the only difference
between the two deployments is `SANAD_S3_ENDPOINT_URL` -- there is no code path
here that knows which it is talking to.
"""

from __future__ import annotations

from typing import Any

import structlog

from app.core.config import Settings
from app.core.storage import session_for

logger = structlog.get_logger(__name__)


class S3AudioSink:
    """Consented child audio. Nothing else is ever written through it."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def _client(self) -> Any:
        return session_for(self._settings).client("s3", endpoint_url=self._settings.s3_endpoint_url)

    async def put(self, key: str, data: bytes, *, content_type: str) -> str:
        async with self._client() as client:
            await client.put_object(
                Bucket=self._settings.s3_bucket,
                Key=key,
                Body=data,
                ContentType=content_type,
            )
        return key

    async def purge_prefix(self, prefix: str) -> int:
        """Delete everything under a prefix. The erasure path depends on this.

        Paginated because a 30-day retention window for one child can exceed the
        1000-key page S3 returns, and a single-page delete would report success
        having removed the first thousand objects.
        """
        deleted = 0
        async with self._client() as client:
            paginator = client.get_paginator("list_objects_v2")
            async for page in paginator.paginate(Bucket=self._settings.s3_bucket, Prefix=prefix):
                keys = [{"Key": item["Key"]} for item in page.get("Contents", [])]
                if not keys:
                    continue
                await client.delete_objects(
                    Bucket=self._settings.s3_bucket, Delete={"Objects": keys}
                )
                deleted += len(keys)
        logger.info("audio_purged", count=deleted)
        return deleted

    async def list_prefix(self, prefix: str) -> list[str]:
        keys: list[str] = []
        async with self._client() as client:
            paginator = client.get_paginator("list_objects_v2")
            async for page in paginator.paginate(Bucket=self._settings.s3_bucket, Prefix=prefix):
                keys.extend(str(item["Key"]) for item in page.get("Contents", []))
        return keys


__all__ = ["S3AudioSink"]
