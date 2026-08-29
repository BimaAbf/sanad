"""structlog JSON logging with a hard field allow-list.

The allow-list is the point of this module. In a product handling children's
developmental data, the cheapest way to leak PII is a well-meaning
``logger.info("saved", child=child)``. Anything not on ``ALLOWED_FIELDS`` is
dropped before the record is rendered, and the drop is itself recorded so the
omission is visible in review rather than silent.
"""

from __future__ import annotations

import logging
import sys
import uuid
from contextvars import ContextVar
from typing import Any

import structlog
from structlog.types import EventDict, WrappedLogger

_request_id: ContextVar[str | None] = ContextVar("misk_request_id", default=None)

#: The only keys permitted in a log record. Identifiers are opaque (uuid) and
#: safe; anything free-text, personal, or secret-shaped is absent by design.
ALLOWED_FIELDS: frozenset[str] = frozenset(
    {
        # structlog / stdlib structure
        "event",
        "level",
        "logger",
        "timestamp",
        "exc_info",
        "exception",
        "stack",
        # correlation
        "request_id",
        "trace_id",
        "span_id",
        "service",
        "environment",
        # http
        "method",
        "path",
        "status_code",
        "duration_ms",
        "client_ip_hash",
        # domain — opaque identifiers and enums only
        "caregiver_id",
        "child_id",
        "assessment_id",
        "session_id",
        "skill_id",
        "item_id",
        "activity_id",
        "decision_point",
        "guardrail_outcome",
        "guardrail_layer",
        "mastery_state",
        "domain_code",
        "provider",
        "model",
        "attempt",
        "count",
        "code",
        "status",
        "reason",
        "outcome",
        "cache_read_input_tokens",
        "input_tokens",
        "output_tokens",
        "latency_ms",
        "exc_type",
    }
)

#: Metering counters whose names collide with a forbidden substring but which
#: are integers, not credentials. Kept explicit and short so that adding to it
#: is a deliberate act visible in review.
EXEMPT_FIELDS: frozenset[str] = frozenset(
    {"input_tokens", "output_tokens", "cache_read_input_tokens"}
)

#: Substrings that must never appear as a field name even if someone adds them
#: to ALLOWED_FIELDS by accident.
FORBIDDEN_SUBSTRINGS: tuple[str, ...] = (
    "password",
    "secret",
    "token",
    "otp",
    "code_hash",
    "pin",
    "authorization",
    "api_key",
    "phone",
    "email",
    "dob",
    "name",
    "address",
    "audio",
)


def get_request_id() -> str | None:
    return _request_id.get()


def set_request_id(value: str | None = None) -> str:
    request_id = value or str(uuid.uuid4())
    _request_id.set(request_id)
    return request_id


def _is_allowed(key: str) -> bool:
    if key in EXEMPT_FIELDS:
        return key in ALLOWED_FIELDS
    lowered = key.lower()
    if any(bad in lowered for bad in FORBIDDEN_SUBSTRINGS):
        return False
    return key in ALLOWED_FIELDS


def field_allow_list(_logger: WrappedLogger, _method: str, event_dict: EventDict) -> EventDict:
    """Drop every key that is not explicitly allowed."""
    dropped = [key for key in event_dict if not _is_allowed(key)]
    for key in dropped:
        del event_dict[key]
    if dropped:
        event_dict["dropped_fields"] = sorted(dropped)
    return event_dict


def inject_request_id(_logger: WrappedLogger, _method: str, event_dict: EventDict) -> EventDict:
    request_id = _request_id.get()
    if request_id is not None:
        event_dict["request_id"] = request_id
    return event_dict


def configure_logging(*, level: str = "INFO", service: str = "misk-api") -> None:
    """Install the structlog + stdlib pipeline. Idempotent."""
    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=getattr(logging, level.upper(), logging.INFO),
        force=True,
    )

    def _add_service(_logger: WrappedLogger, _method: str, event_dict: EventDict) -> EventDict:
        event_dict["service"] = service
        return event_dict

    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.stdlib.add_log_level,
            structlog.stdlib.add_logger_name,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            inject_request_id,
            _add_service,
            structlog.processors.format_exc_info,
            # allow-list runs LAST, after everything that adds fields, so that
            # nothing added downstream of it can slip through.
            field_allow_list,
            structlog.processors.JSONRenderer(ensure_ascii=False),
        ],
        wrapper_class=structlog.stdlib.BoundLogger,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )


def get_logger(name: str | None = None) -> Any:
    return structlog.get_logger(name)
