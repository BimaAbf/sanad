"""Child profile and consent business rules."""

from __future__ import annotations

import datetime as dt
import hashlib
import hmac
import secrets
from dataclasses import dataclass
from uuid import UUID

import structlog

from app.core.config import Settings
from app.core.errors import Conflict, NotFound, ValidationProblem
from app.modules.children import domain
from app.modules.children.consent_gate import ConsentGate
from app.modules.children.models import Child
from app.modules.children.repository import ChildrenRepository
from app.modules.children.schemas import ChildCreate
from app.modules.identity.repository import IdentityRepository

logger = structlog.get_logger(__name__)

INVITE_TTL = dt.timedelta(days=7)


class MissingMandatoryConsent(ValidationProblem):
    code = "missing_mandatory_consent"
    title = "Missing Mandatory Consent"
    message_ar = "محتاجين موافقتك على الشروط الأساسية عشان نبدأ."


class InvalidDob(ValidationProblem):
    code = "invalid_date_of_birth"
    title = "Invalid Date of Birth"
    message_ar = "تاريخ الميلاد مش مظبوط. راجعه من فضلك."


class StaleWrite(Conflict):
    code = "stale_write"
    title = "Stale Write"
    message_ar = "حد تاني عدّل البيانات دي. حدّث الصفحة وحاول تاني."


class InviteInvalid(NotFound):
    code = "invite_invalid"
    title = "Invite Invalid"
    message_ar = "الدعوة دي مش صالحة أو انتهت."


class LastOwner(Conflict):
    code = "last_owner"
    title = "Last Owner"
    message_ar = "لازم يفضل ولي أمر واحد على الأقل. حوّل الملكية الأول."


@dataclass(frozen=True, slots=True)
class CreatedChild:
    child: Child
    age: domain.Age


class ChildrenService:
    def __init__(
        self,
        *,
        repo: ChildrenRepository,
        identity_repo: IdentityRepository,
        gate: ConsentGate,
        settings: Settings,
    ) -> None:
        self.repo = repo
        self.identity_repo = identity_repo
        self.gate = gate
        self.settings = settings

    # --- creation ----------------------------------------------------------

    async def create_child(
        self,
        *,
        payload: ChildCreate,
        caregiver_id: UUID,
        today: dt.date | None = None,
        source_ip: str | None = None,
        user_agent: str | None = None,
    ) -> CreatedChild:
        """Child, consents and the owner link in one transaction.

        The mandatory-consent check happens before anything is written, so a
        rejected request leaves no partial child behind.
        """
        today = today or domain.today()

        problem = domain.check_dob(payload.date_of_birth, today)
        if problem is domain.DobProblem.IN_FUTURE:
            raise InvalidDob(
                detail="Date of birth is in the future.",
                message_ar="تاريخ الميلاد في المستقبل. راجعه من فضلك.",
            )
        if problem is domain.DobProblem.TOO_OLD:
            raise InvalidDob(
                detail=f"Child is older than {domain.MAX_AGE_YEARS} years.",
                message_ar="سند دلوقتي للأطفال لحد ٨ سنين.",
            )
        if not domain.check_gestational_weeks(payload.gestational_weeks):
            raise InvalidDob(
                detail="Gestational weeks out of range.",
                message_ar="عدد أسابيع الحمل مش مظبوط.",
            )

        granted = {c.key.value for c in payload.consents if c.granted}
        missing = domain.missing_mandatory_consents(granted)
        if missing:
            raise MissingMandatoryConsent(
                detail="Missing mandatory consents: " + ", ".join(k.value for k in missing),
                extra={"missing": [k.value for k in missing]},
            )

        child = await self.repo.create_child(
            display_name=payload.display_name,
            name_vowelised=payload.name_vowelised,
            date_of_birth=payload.date_of_birth,
            sex=payload.sex,
            gestational_weeks=payload.gestational_weeks,
            diagnosis_note=payload.diagnosis_note,
            comms_level=payload.comms_level,
            wait_time_ms=payload.wait_time_ms,
            max_choices=payload.max_choices,
            audio_rate_pct=payload.audio_rate_pct,
            calm_mode=payload.calm_mode,
            session_minutes=payload.session_minutes,
            hearing_aid=payload.hearing_aid,
            glasses=payload.glasses,
        )

        now = dt.datetime.now(dt.UTC)
        definitions = {d.key: d for d in await self.repo.list_consent_definitions()}
        for entry in payload.consents:
            definition = definitions.get(entry.key.value)
            if definition is None:
                continue
            await self.repo.record_consent(
                child_id=child.id,
                caregiver_id=caregiver_id,
                consent_key=entry.key.value,
                version=definition.version,
                granted=entry.granted,
                now=now,
                source_ip=source_ip,
                user_agent=user_agent,
            )

        await self.identity_repo.link_child(
            caregiver_id=caregiver_id, child_id=child.id, role="owner", invited_by=None
        )
        await self.gate.invalidate(str(child.id))
        logger.info("child_created", child_id=str(child.id), caregiver_id=str(caregiver_id))
        return CreatedChild(
            child=child,
            age=domain.age_months(child.date_of_birth, today, child.gestational_weeks),
        )

    # --- read / update -----------------------------------------------------

    async def get_child_or_404(self, child_id: UUID) -> Child:
        child = await self.repo.get_child(child_id)
        if child is None:
            raise NotFound(detail="Child not found.")
        return child

    async def patch_child(
        self,
        *,
        child_id: UUID,
        changes: dict[str, object],
        expected_version: int | None = None,
    ) -> Child:
        """Update a child, optionally under optimistic concurrency.

        `expected_version` comes from the ETag the client was served. A
        timestamp cannot do this job: HTTP-date headers have whole-second
        resolution, so two writes in the same second are indistinguishable and
        both would win. See docs/adr/003-consent-model.md.
        """
        now = dt.datetime.now(dt.UTC)
        if expected_version is not None:
            ok = await self.repo.patch_child_if_version_matches(
                child_id=child_id,
                changes=changes,
                expected_version=expected_version,
                now=now,
            )
            if not ok:
                current = await self.get_child_or_404(child_id)
                raise StaleWrite(
                    detail="The child was modified by someone else.",
                    extra={
                        "current_version": current.version,
                        "your_version": expected_version,
                        "current_updated_at": current.updated_at.isoformat(),
                        "conflicting_fields": sorted(changes),
                    },
                )
        else:
            await self.repo.patch_child(child_id=child_id, changes=changes, now=now)
        return await self.get_child_or_404(child_id)

    # --- consent -----------------------------------------------------------

    async def set_consent(
        self,
        *,
        child_id: UUID,
        caregiver_id: UUID,
        key: domain.ConsentKey,
        granted: bool,
        source_ip: str | None = None,
        user_agent: str | None = None,
    ) -> None:
        """Append a consent row and bust the cache before returning.

        Withdrawing a mandatory consent is permitted — a caregiver may always
        withdraw — but it archives the child, because there is no lawful basis
        left to keep processing (docs/07 §4).
        """
        definition = await self.repo.get_consent_definition(key.value)
        if definition is None:
            raise NotFound(detail=f"Unknown consent key '{key.value}'.")

        now = dt.datetime.now(dt.UTC)
        await self.repo.record_consent(
            child_id=child_id,
            caregiver_id=caregiver_id,
            consent_key=key.value,
            version=definition.version,
            granted=granted,
            now=now,
            source_ip=source_ip,
            user_agent=user_agent,
        )
        # Before the response is returned, so the next request cannot read a
        # stale grant. This ordering is the whole point of the gate.
        await self.gate.invalidate(str(child_id))

        if not granted and key in domain.MANDATORY_CONSENTS:
            await self.repo.archive_child(child_id, now)
            logger.info("child_archived", child_id=str(child_id), reason=key.value)

        if not granted and key is domain.ConsentKey.VOICE_RETENTION:
            # 5-minute SLA (docs/04a §C02). Enqueued by the router once the
            # worker pool exists; recorded here so the trigger point is visible.
            logger.info("voice_purge_required", child_id=str(child_id))

    # --- invites -----------------------------------------------------------

    def _sign_invite(self, token: str) -> str:
        return hmac.new(
            self.settings.invite_secret.encode(), token.encode(), hashlib.sha256
        ).hexdigest()

    async def create_invite(
        self, *, child_id: UUID, invited_by: UUID, phone_e164: str, role: str
    ) -> tuple[str, dt.datetime]:
        token = secrets.token_urlsafe(32)
        expires_at = dt.datetime.now(dt.UTC) + INVITE_TTL
        await self.repo.create_invite(
            child_id=child_id,
            invited_by=invited_by,
            phone_e164=phone_e164,
            role=role,
            token_hash=self._sign_invite(token),
            expires_at=expires_at,
        )
        return token, expires_at

    async def accept_invite(self, *, token: str, caregiver_id: UUID) -> UUID:
        """Single use. Returns the child id that was linked."""
        invite = await self.repo.find_invite(self._sign_invite(token))
        now = dt.datetime.now(dt.UTC)
        if (
            invite is None
            or invite.accepted_at is not None
            or invite.revoked_at is not None
            or now >= invite.expires_at
        ):
            raise InviteInvalid(detail="Invite is unknown, used, revoked or expired.")

        existing = await self.identity_repo.get_link(
            caregiver_id=caregiver_id, child_id=invite.child_id
        )
        if existing is None:
            await self.identity_repo.link_child(
                caregiver_id=caregiver_id,
                child_id=invite.child_id,
                role=invite.role,
                invited_by=invite.invited_by,
            )
        await self.repo.accept_invite(invite_id=invite.id, caregiver_id=caregiver_id, now=now)
        return invite.child_id
