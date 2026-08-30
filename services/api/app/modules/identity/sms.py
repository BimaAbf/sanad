"""SMS delivery adapters.

`NullSms` is the default everywhere except production. It prints the code to the
log so the full auth flow works with no aggregator account — which is why
`SETUP.md` lists SMS credentials as needed only for real-device testing.

The code is deliberately logged *only* by NullSms, and only outside production.
No other adapter, and no other module, ever sees a code in a log line.
"""

from __future__ import annotations

import sys
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


#: The last code `NullSms` "sent", per phone number.
#:
#: Module-level, and deliberately so: `build_sms_provider` is called per
#: request, so an instance attribute would be discarded before anything could
#: read it. This is what `GET /auth/otp/latest` returns, and that route refuses
#: to exist outside a non-production environment with the null provider
#: configured — so this dictionary can only ever hold codes that were never
#: sent to a real phone.
#:
#: It is bounded by the number of distinct phone numbers a developer types.
LAST_DEV_CODES: dict[str, str] = {}


class NullSms:
    """Test and local-development provider. Records, never sends."""

    name = "null"

    def __init__(self) -> None:
        self.sent: list[tuple[str, str]] = []

    async def send(self, *, phone_e164: str, message: str) -> bool:
        self.sent.append((phone_e164, message))
        # The OTP is written to stdout only, never through structlog, so it
        # cannot reach a log aggregator.
        #
        # Only the DIGITS, and never the Arabic message body. Printing the body
        # made every sign-in on Windows a 500: the default console encoding is
        # cp1252, `print` raised `UnicodeEncodeError` inside the request, and
        # the caregiver got "something went wrong" for a message that was in
        # fact sent. `errors="replace"` on the stream is the belt to that
        # brace — a console that cannot render a `+` should not be able to take
        # authentication down either.
        # ASCII digits only. `str.isdigit()` is true for Arabic-Indic digits
        # too, and the message body contains one ("صالح ٥ دقائق"), so the naive
        # filter printed `code=878572٥` — a code that does not exist and that a
        # developer would paste in and be refused for.
        digits = "".join(
            character for character in message if character.isascii() and character.isdigit()
        )
        LAST_DEV_CODES[phone_e164] = digits
        line = f"[NullSms] -> {phone_e164} code={digits}"
        try:
            print(line)  # noqa: T201
        except UnicodeEncodeError:  # pragma: no cover - console-encoding dependent
            sys.stdout.buffer.write(line.encode("ascii", "replace"))
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
