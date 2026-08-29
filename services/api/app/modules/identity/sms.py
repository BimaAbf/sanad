"""SMS delivery adapters.

`NullSms` is the default everywhere except production. It prints the code to the
log so the full auth flow works with no aggregator account — which is why
`SETUP.md` lists SMS credentials as needed only for real-device testing.

The code is deliberately logged *only* by NullSms, and only outside production.
No other adapter, and no other module, ever sees a code in a log line.
"""

from __future__ import annotations

from typing import Protocol

import structlog

from app.core.config import Settings

logger = structlog.get_logger(__name__)


class SmsProvider(Protocol):
    """Send one message. Implementations must not raise on delivery failure.

    A caregiver waiting for an OTP should not receive a 500 because an
    aggregator is down; the endpoint returns 202 regardless and a retry job
    handles the rest (docs/04a §C01 failure modes).
    """

    name: str

    async def send(self, *, phone_e164: str, message: str) -> bool: ...


class NullSms:
    """Test and local-development provider. Records, never sends."""

    name = "null"

    def __init__(self) -> None:
        self.sent: list[tuple[str, str]] = []

    async def send(self, *, phone_e164: str, message: str) -> bool:
        self.sent.append((phone_e164, message))
        # The message body carries the OTP. It is written to stdout only, never
        # through structlog, so it cannot reach a log aggregator.
        print(f"[NullSms] -> {phone_e164}: {message}")  # noqa: T201
        return True


class TwilioSms:
    """Twilio adapter.

    Not wired up: it needs credentials, which SETUP.md §2 defers to real-device
    testing. It raises rather than silently pretending to send, because a
    provider that claims success without sending is worse than one that fails.
    """

    name = "twilio"

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    async def send(self, *, phone_e164: str, message: str) -> bool:
        raise NotImplementedError(
            "TwilioSms needs credentials — see SETUP.md §2. "
            "Set SANAD_SMS_PROVIDER=null to run without SMS."
        )


class LocalAggregatorSms:
    """Egyptian local aggregator adapter. Same reasoning as TwilioSms."""

    name = "local_aggregator"

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    async def send(self, *, phone_e164: str, message: str) -> bool:
        raise NotImplementedError(
            "LocalAggregatorSms needs credentials — see SETUP.md §2. "
            "Set SANAD_SMS_PROVIDER=null to run without SMS."
        )


def build_sms_provider(settings: Settings) -> SmsProvider:
    match settings.sms_provider:
        case "twilio":
            return TwilioSms(settings)
        case "local_aggregator":
            return LocalAggregatorSms(settings)
        case _:
            return NullSms()
