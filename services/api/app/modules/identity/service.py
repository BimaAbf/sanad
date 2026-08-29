"""Identity business rules.

The three that carry real weight:

1. `/auth/otp/request` returns 202 for every input and takes the same time
   whether or not the number exists. A caller with a stopwatch learns nothing.
2. A refresh token is single-use. Presenting a consumed one is treated as theft:
   the entire rotation family is revoked immediately.
3. Nothing here ever logs a code, a token, or a hash. The allow-list in
   `app/core/logging.py` is the backstop; not passing them is the rule.
"""

from __future__ import annotations

import asyncio
import datetime as dt
import secrets
from dataclasses import dataclass
from uuid import UUID, uuid4

import structlog

from app.core.config import Settings
from app.core.errors import Forbidden, NotFound, RateLimited, Unauthorised
from app.modules.identity import domain
from app.modules.identity.models import Caregiver
from app.modules.identity.ratelimit import (
    OTP_PER_IP,
    OTP_PER_PHONE,
    VERIFY_PER_IP,
    RateLimiter,
)
from app.modules.identity.repository import IdentityRepository
from app.modules.identity.security import hash_secret, issue_access_token, verify_secret
from app.modules.identity.sms import SmsProvider

logger = structlog.get_logger(__name__)

OTP_MESSAGE_AR = "كود الدخول لمِسك: {code}\nالكود صالح ٥ دقايق. متديهوش لحد."


class InvalidCredentials(Unauthorised):
    code = "invalid_credentials"
    title = "Invalid Credentials"
    message_ar = "الكود غلط أو انتهت صلاحيته. اطلب كود جديد."


class OtpLocked(Unauthorised):
    code = "otp_locked"
    title = "OTP Locked"
    message_ar = "جرّبت كتير. اطلب كود جديد من فضلك."


class RefreshReuseDetected(Unauthorised):
    code = "refresh_reuse_detected"
    title = "Refresh Token Reuse Detected"
    message_ar = "لازم تسجّل دخول تاني عشان أمان حسابك."


class PinLocked(Forbidden):
    code = "pin_locked"
    title = "PIN Locked"
    message_ar = "قفلنا إدخال الرقم السري ربع ساعة. تقدر تدخل بحسابك عادي."


@dataclass(frozen=True, slots=True)
class IssuedTokens:
    access_token: str
    expires_in: int
    refresh_token: str
    is_new_user: bool


class IdentityService:
    def __init__(
        self,
        *,
        repo: IdentityRepository,
        limiter: RateLimiter,
        sms: SmsProvider,
        settings: Settings,
    ) -> None:
        self.repo = repo
        self.limiter = limiter
        self.sms = sms
        self.settings = settings

    # --- OTP ---------------------------------------------------------------

    async def request_otp(self, *, phone_e164: str, client_ip: str | None) -> None:
        """Always succeeds from the caller's point of view.

        Rate limiting is the only thing that produces a visible error, and it is
        keyed on the *caller*, not on whether the number is registered, so it
        leaks nothing either.
        """
        if not await self.limiter.check(OTP_PER_PHONE, phone_e164):
            raise RateLimited(detail="Too many codes requested for this number.")
        if client_ip and not await self.limiter.check(OTP_PER_IP, client_ip):
            raise RateLimited(detail="Too many codes requested from this address.")

        code = domain.generate_otp_code()
        now = domain.utcnow()
        await self.repo.create_otp(
            phone_e164=phone_e164,
            code_hash=domain.hash_otp_code(code, self.settings.otp_pepper),
            expires_at=domain.otp_expiry(now),
            created_ip=client_ip,
        )
        await self.sms.send(phone_e164=phone_e164, message=OTP_MESSAGE_AR.format(code=code))
        logger.info("otp_requested", provider=self.sms.name)

    @staticmethod
    async def enumeration_jitter() -> None:
        """Sleep 80-140 ms.

        Applied on the *send* path too, not only the no-send path: equalising the
        two is the point, and the send path is the one with a real network call
        in it, so the jitter has to cover both to be indistinguishable.
        """
        low, high = domain.ENUMERATION_JITTER_MS
        millis = low + secrets.randbelow(high - low + 1)
        await asyncio.sleep(millis / 1000)

    async def verify_otp(
        self,
        *,
        phone_e164: str,
        code: str,
        client_ip: str | None,
        user_agent: str | None,
    ) -> IssuedTokens:
        if client_ip and not await self.limiter.check(VERIFY_PER_IP, client_ip):
            raise RateLimited(detail="Too many verification attempts.")

        now = domain.utcnow()
        otp = await self.repo.latest_unconsumed_otp(phone_e164)
        if otp is None:
            raise InvalidCredentials(detail="No pending code for this number.")

        rejection = domain.check_otp_usable(
            domain.OtpState(
                attempts=otp.attempts,
                consumed_at=otp.consumed_at,
                expires_at=otp.expires_at,
            ),
            now,
        )
        if rejection is domain.OtpRejection.TOO_MANY_ATTEMPTS:
            raise OtpLocked(detail="Attempt limit reached for this code.")
        if rejection is not None:
            raise InvalidCredentials(detail=f"Code is {rejection.value}.")

        if not domain.verify_otp_code(code, otp.code_hash, self.settings.otp_pepper):
            # Recorded before the error is raised so a crash mid-flow cannot hand
            # an attacker a free attempt.
            await self.repo.increment_otp_attempts(otp.id)
            logger.info("otp_verify_failed", attempt=otp.attempts + 1)
            raise InvalidCredentials(detail="Code did not match.")

        await self.repo.consume_otp(otp.id, now)

        caregiver = await self.repo.find_caregiver_by_phone(phone_e164)
        is_new_user = caregiver is None
        if caregiver is None:
            caregiver = await self.repo.create_caregiver(phone_e164=phone_e164)
        await self.repo.touch_last_login(caregiver.id, now)

        access_token, expires_in, refresh_token = await self._issue_tokens(
            caregiver_id=caregiver.id, family_id=uuid4(), user_agent=user_agent, now=now
        )
        logger.info("auth_success", caregiver_id=str(caregiver.id))
        return IssuedTokens(
            access_token=access_token,
            expires_in=expires_in,
            refresh_token=refresh_token,
            is_new_user=is_new_user,
        )

    async def _issue_tokens(
        self,
        *,
        caregiver_id: UUID,
        family_id: UUID,
        user_agent: str | None,
        now: dt.datetime,
    ) -> tuple[str, int, str]:
        access_token, expires_in = issue_access_token(
            caregiver_id=caregiver_id, now=now, settings=self.settings
        )
        refresh_token = domain.generate_refresh_token()
        await self.repo.create_refresh_token(
            caregiver_id=caregiver_id,
            token_hash=domain.hash_refresh_token(refresh_token),
            family_id=family_id,
            expires_at=domain.refresh_token_expiry(now),
            user_agent=user_agent,
        )
        return access_token, expires_in, refresh_token

    # --- refresh -----------------------------------------------------------

    async def refresh(self, *, refresh_token: str, user_agent: str | None) -> IssuedTokens:
        """Rotate a refresh token, detecting reuse.

        A token that exists but is already revoked means one of two things: the
        legitimate client retried, or someone stole it. We cannot tell them
        apart, so we assume theft — revoke the whole family and force re-auth.
        Losing one session is a much better outcome than an attacker keeping a
        renewable foothold in a child's health record.
        """
        now = domain.utcnow()
        stored = await self.repo.find_refresh_token(domain.hash_refresh_token(refresh_token))
        if stored is None:
            raise InvalidCredentials(detail="Unknown refresh token.")

        if stored.revoked_at is not None:
            revoked = await self.repo.revoke_family(stored.family_id, now)
            logger.error(
                "refresh_reuse_detected",
                caregiver_id=str(stored.caregiver_id),
                count=revoked,
            )
            raise RefreshReuseDetected(detail="This token was already used.")

        if now >= stored.expires_at:
            await self.repo.revoke_refresh_token(stored.id, now)
            raise InvalidCredentials(detail="Refresh token expired.")

        await self.repo.revoke_refresh_token(stored.id, now)
        access_token, expires_in, new_refresh = await self._issue_tokens(
            caregiver_id=stored.caregiver_id,
            family_id=stored.family_id,
            user_agent=user_agent,
            now=now,
        )
        return IssuedTokens(
            access_token=access_token,
            expires_in=expires_in,
            refresh_token=new_refresh,
            is_new_user=False,
        )

    async def logout(self, *, refresh_token: str | None) -> None:
        """Revoke the whole family. Idempotent, and never errors."""
        if not refresh_token:
            return
        stored = await self.repo.find_refresh_token(domain.hash_refresh_token(refresh_token))
        if stored is not None:
            await self.repo.revoke_family(stored.family_id, domain.utcnow())

    # --- play PIN ----------------------------------------------------------

    async def set_play_pin(self, *, caregiver_id: UUID, pin: str) -> None:
        if not domain.is_valid_play_pin(pin):
            raise InvalidCredentials(detail="PIN must be 4 digits.")
        await self.repo.set_play_pin(caregiver_id, hash_secret(pin))
        await self.repo.upsert_pin_attempts(
            caregiver_id=caregiver_id,
            failed_attempts=0,
            locked_until=None,
            now=domain.utcnow(),
        )

    async def verify_play_pin(self, *, caregiver_id: UUID, pin: str) -> bool:
        caregiver = await self.repo.get_caregiver(caregiver_id)
        if caregiver is None:
            raise NotFound(detail="Caregiver not found.")
        if caregiver.play_pin_hash is None:
            raise NotFound(detail="No play PIN is set.")

        now = domain.utcnow()
        record = await self.repo.get_pin_attempts(caregiver_id)
        state = domain.PinLockState(
            failed_attempts=record.failed_attempts if record else 0,
            locked_until=record.locked_until if record else None,
        )
        if domain.is_pin_locked(state, now):
            raise PinLocked(detail="PIN entry is temporarily locked.")

        ok = verify_secret(pin, caregiver.play_pin_hash)
        next_state = domain.next_pin_lock_state(state, success=ok, now=now)
        await self.repo.upsert_pin_attempts(
            caregiver_id=caregiver_id,
            failed_attempts=next_state.failed_attempts,
            locked_until=next_state.locked_until,
            now=now,
        )
        if not ok and next_state.locked_until is not None:
            raise PinLocked(detail="PIN entry is now locked.")
        return ok

    # --- authorisation -----------------------------------------------------

    async def assert_child_access(
        self, *, caregiver_id: UUID, child_id: UUID, min_role: domain.Role
    ) -> domain.Role:
        """403 unless this caregiver is linked to this child at min_role or above.

        Deliberately does NOT distinguish "no such child" from "not your child": a
        404 for one and a 403 for the other would let anyone enumerate which child
        ids exist.
        """
        link = await self.repo.get_link(caregiver_id=caregiver_id, child_id=child_id)
        if link is None:
            logger.info("child_access_denied", child_id=str(child_id))
            raise Forbidden(detail="No access to this child.")
        role = domain.Role(link.role)
        if not domain.role_satisfies(role, min_role):
            raise Forbidden(detail="Insufficient role for this action.")
        return role

    async def get_caregiver_or_404(self, caregiver_id: UUID) -> Caregiver:
        caregiver = await self.repo.get_caregiver(caregiver_id)
        if caregiver is None:
            raise NotFound(detail="Caregiver not found.")
        return caregiver
