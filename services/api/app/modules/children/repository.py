"""All SQL for children and consent."""

from __future__ import annotations

import datetime as dt
from typing import Any
from uuid import UUID

from sqlalchemy import select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.children.models import (
    CaregiverInvite,
    Child,
    Consent,
    ConsentDefinition,
)


class ChildrenRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    # --- children ----------------------------------------------------------

    async def get_child(self, child_id: UUID) -> Child | None:
        return await self.session.get(Child, child_id)

    async def create_child(self, **fields: Any) -> Child:
        child = Child(**fields)
        self.session.add(child)
        await self.session.flush()
        await self.session.refresh(child)
        return child

    async def patch_child(
        self, *, child_id: UUID, changes: dict[str, Any], now: dt.datetime
    ) -> None:
        await self.session.execute(
            update(Child).where(Child.id == child_id).values(**changes, updated_at=now)
        )

    async def patch_child_if_unmodified(
        self,
        *,
        child_id: UUID,
        changes: dict[str, Any],
        if_unmodified_since: dt.datetime,
        now: dt.datetime,
    ) -> bool:
        """Optimistic concurrency. False means someone else wrote first.

        The `updated_at <= :since` predicate is what makes this atomic: two
        concurrent PATCHes both read the same updated_at, but only one UPDATE
        matches a row, so the loser gets rowcount 0 rather than silently
        clobbering the winner.

        Compared with a one-second tolerance because HTTP-date headers have
        whole-second resolution, so a client echoing back a header it received
        would otherwise never match a microsecond-precision timestamp.
        """
        result = await self.session.execute(
            text("""
                UPDATE children SET updated_at = :now
                WHERE id = :child_id
                  AND updated_at <= :since + interval '1 second'
                RETURNING id
            """),
            {"child_id": child_id, "since": if_unmodified_since, "now": now},
        )
        if result.first() is None:
            return False
        if changes:
            await self.session.execute(update(Child).where(Child.id == child_id).values(**changes))
        return True

    async def archive_child(self, child_id: UUID, now: dt.datetime) -> None:
        await self.session.execute(
            update(Child).where(Child.id == child_id).values(archived_at=now, updated_at=now)
        )

    # --- consent -----------------------------------------------------------

    async def list_consent_definitions(self) -> list[ConsentDefinition]:
        stmt = select(ConsentDefinition).order_by(ConsentDefinition.key)
        return list((await self.session.execute(stmt)).scalars())

    async def get_consent_definition(self, key: str) -> ConsentDefinition | None:
        return await self.session.get(ConsentDefinition, key)

    async def record_consent(
        self,
        *,
        child_id: UUID,
        caregiver_id: UUID,
        consent_key: str,
        version: int,
        granted: bool,
        now: dt.datetime,
        source_ip: str | None = None,
        user_agent: str | None = None,
    ) -> Consent:
        """Append a row. Never updates an existing one — the ledger is the audit."""
        consent = Consent(
            child_id=child_id,
            caregiver_id=caregiver_id,
            consent_key=consent_key,
            version=version,
            status="granted" if granted else "withdrawn",
            granted_at=now,
            withdrawn_at=None if granted else now,
            source_ip=source_ip,
            user_agent=user_agent,
        )
        self.session.add(consent)
        await self.session.flush()
        return consent

    async def current_consents(self, child_id: UUID) -> dict[str, Consent]:
        """Most recent row per key."""
        stmt = (
            select(Consent)
            .where(Consent.child_id == child_id)
            .order_by(Consent.consent_key, Consent.granted_at.desc(), Consent.id.desc())
        )
        latest: dict[str, Consent] = {}
        for consent in (await self.session.execute(stmt)).scalars():
            latest.setdefault(consent.consent_key, consent)
        return latest

    # --- invites -----------------------------------------------------------

    async def create_invite(
        self,
        *,
        child_id: UUID,
        invited_by: UUID,
        phone_e164: str,
        role: str,
        token_hash: str,
        expires_at: dt.datetime,
    ) -> CaregiverInvite:
        invite = CaregiverInvite(
            child_id=child_id,
            invited_by=invited_by,
            phone_e164=phone_e164,
            role=role,
            token_hash=token_hash,
            expires_at=expires_at,
        )
        self.session.add(invite)
        await self.session.flush()
        await self.session.refresh(invite)
        return invite

    async def find_invite(self, token_hash: str) -> CaregiverInvite | None:
        stmt = select(CaregiverInvite).where(CaregiverInvite.token_hash == token_hash)
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def accept_invite(self, *, invite_id: UUID, caregiver_id: UUID, now: dt.datetime) -> None:
        await self.session.execute(
            update(CaregiverInvite)
            .where(CaregiverInvite.id == invite_id)
            .values(accepted_by=caregiver_id, accepted_at=now)
        )
