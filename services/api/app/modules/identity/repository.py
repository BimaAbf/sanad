"""All SQL for identity. No business rules here — those live in service.py."""

from __future__ import annotations

import datetime as dt
from typing import Any, cast
from uuid import UUID

from sqlalchemy import CursorResult, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.identity.models import (
    AuthOtp,
    Caregiver,
    CaregiverChild,
    PlayPinAttempts,
    RefreshToken,
)


class IdentityRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    # --- caregivers --------------------------------------------------------

    async def get_caregiver(self, caregiver_id: UUID) -> Caregiver | None:
        return await self.session.get(Caregiver, caregiver_id)

    async def find_caregiver_by_phone(self, phone_e164: str) -> Caregiver | None:
        stmt = select(Caregiver).where(Caregiver.phone_e164 == phone_e164)
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def create_caregiver(self, *, phone_e164: str) -> Caregiver:
        caregiver = Caregiver(phone_e164=phone_e164)
        self.session.add(caregiver)
        await self.session.flush()
        await self.session.refresh(caregiver)
        return caregiver

    async def touch_last_login(self, caregiver_id: UUID, now: dt.datetime) -> None:
        await self.session.execute(
            update(Caregiver).where(Caregiver.id == caregiver_id).values(last_login_at=now)
        )

    # --- OTP ---------------------------------------------------------------

    async def create_otp(
        self,
        *,
        phone_e164: str,
        code_hash: str,
        expires_at: dt.datetime,
        created_ip: str | None,
    ) -> AuthOtp:
        otp = AuthOtp(
            phone_e164=phone_e164,
            code_hash=code_hash,
            expires_at=expires_at,
            created_ip=created_ip,
        )
        self.session.add(otp)
        await self.session.flush()
        return otp

    async def latest_unconsumed_otp(self, phone_e164: str) -> AuthOtp | None:
        """The most recent unconsumed OTP for a number.

        Ordered by created_at DESC so requesting a second code invalidates the
        first by ignoring it, rather than leaving two valid codes in flight.
        """
        stmt = (
            select(AuthOtp)
            .where(AuthOtp.phone_e164 == phone_e164, AuthOtp.consumed_at.is_(None))
            .order_by(AuthOtp.created_at.desc())
            .limit(1)
            .with_for_update()
        )
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def increment_otp_attempts(self, otp_id: UUID) -> None:
        await self.session.execute(
            update(AuthOtp).where(AuthOtp.id == otp_id).values(attempts=AuthOtp.attempts + 1)
        )

    async def consume_otp(self, otp_id: UUID, now: dt.datetime) -> None:
        await self.session.execute(
            update(AuthOtp).where(AuthOtp.id == otp_id).values(consumed_at=now)
        )

    # --- refresh tokens ----------------------------------------------------

    async def create_refresh_token(
        self,
        *,
        caregiver_id: UUID,
        token_hash: str,
        family_id: UUID,
        expires_at: dt.datetime,
        user_agent: str | None,
    ) -> RefreshToken:
        token = RefreshToken(
            caregiver_id=caregiver_id,
            token_hash=token_hash,
            family_id=family_id,
            expires_at=expires_at,
            user_agent=user_agent,
        )
        self.session.add(token)
        await self.session.flush()
        return token

    async def find_refresh_token(self, token_hash: str) -> RefreshToken | None:
        stmt = select(RefreshToken).where(RefreshToken.token_hash == token_hash)
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def revoke_refresh_token(self, token_id: UUID, now: dt.datetime) -> None:
        await self.session.execute(
            update(RefreshToken)
            .where(RefreshToken.id == token_id, RefreshToken.revoked_at.is_(None))
            .values(revoked_at=now)
        )

    async def revoke_family(self, family_id: UUID, now: dt.datetime) -> int:
        """Revoke every token in a rotation family. Returns how many were live."""
        result = await self.session.execute(
            update(RefreshToken)
            .where(RefreshToken.family_id == family_id, RefreshToken.revoked_at.is_(None))
            .values(revoked_at=now)
        )
        # session.execute() is typed as Result; an UPDATE always returns a
        # CursorResult, which is the only variant carrying rowcount.
        return int(cast("CursorResult[Any]", result).rowcount or 0)

    # --- child links -------------------------------------------------------

    async def get_link(self, *, caregiver_id: UUID, child_id: UUID) -> CaregiverChild | None:
        stmt = select(CaregiverChild).where(
            CaregiverChild.caregiver_id == caregiver_id,
            CaregiverChild.child_id == child_id,
        )
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def list_links(self, caregiver_id: UUID) -> list[CaregiverChild]:
        stmt = select(CaregiverChild).where(CaregiverChild.caregiver_id == caregiver_id)
        return list((await self.session.execute(stmt)).scalars())

    async def list_links_with_names(self, caregiver_id: UUID) -> list[tuple[UUID, str, str]]:
        """(child_id, display_name, role) for every child this caregiver has.

        A separate method rather than a change to `list_links`, which returns
        ORM rows a dozen callers use for authorisation. This one exists for
        `/me`, whose response carried an empty `display_name` for every child —
        the comment beside it said the children module would fill it in "once it
        exists", and it has existed since 0003. A caregiver choosing between
        three unnamed cards cannot choose.

        Raw SQL because `children` and `caregiver_child` are mapped in different
        modules and this join is the only place the two are read together.
        """
        rows = await self.session.execute(
            text(
                "SELECT cc.child_id, c.display_name, cc.role::text AS role "
                "FROM caregiver_child cc JOIN children c ON c.id = cc.child_id "
                # `archived_at`, which is the column 0003 actually has. The
                # first draft filtered on `deleted_at` — a column from no
                # migration in this repository — and `/me` was a 500 for every
                # caregiver until it was run against a database.
                "WHERE cc.caregiver_id = :caregiver_id AND c.archived_at IS NULL "
                "ORDER BY c.created_at"
            ),
            {"caregiver_id": caregiver_id},
        )
        return [(row.child_id, str(row.display_name), str(row.role)) for row in rows]

    async def link_child(
        self, *, caregiver_id: UUID, child_id: UUID, role: str, invited_by: UUID | None
    ) -> CaregiverChild:
        link = CaregiverChild(
            caregiver_id=caregiver_id,
            child_id=child_id,
            role=role,
            invited_by=invited_by,
        )
        self.session.add(link)
        await self.session.flush()
        return link

    async def count_owners(self, child_id: UUID) -> int:
        stmt = select(CaregiverChild).where(
            CaregiverChild.child_id == child_id, CaregiverChild.role == "owner"
        )
        return len(list((await self.session.execute(stmt)).scalars()))

    # --- play PIN lockout --------------------------------------------------

    async def get_pin_attempts(self, caregiver_id: UUID) -> PlayPinAttempts | None:
        return await self.session.get(PlayPinAttempts, caregiver_id)

    async def upsert_pin_attempts(
        self,
        *,
        caregiver_id: UUID,
        failed_attempts: int,
        locked_until: dt.datetime | None,
        now: dt.datetime,
    ) -> None:
        existing = await self.session.get(PlayPinAttempts, caregiver_id)
        if existing is None:
            self.session.add(
                PlayPinAttempts(
                    caregiver_id=caregiver_id,
                    failed_attempts=failed_attempts,
                    locked_until=locked_until,
                    updated_at=now,
                )
            )
        else:
            existing.failed_attempts = failed_attempts
            existing.locked_until = locked_until
            existing.updated_at = now
        await self.session.flush()

    async def set_play_pin(self, caregiver_id: UUID, pin_hash: str) -> None:
        await self.session.execute(
            update(Caregiver).where(Caregiver.id == caregiver_id).values(play_pin_hash=pin_hash)
        )
