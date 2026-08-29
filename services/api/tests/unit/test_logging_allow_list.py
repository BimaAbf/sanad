"""The allow-list is the PII backstop. These tests are the reason it is safe."""

from __future__ import annotations

import json

import structlog

from app.core.logging import (
    ALLOWED_FIELDS,
    FORBIDDEN_SUBSTRINGS,
    configure_logging,
    field_allow_list,
    set_request_id,
)


def test_disallowed_field_is_dropped() -> None:
    event = field_allow_list(None, "info", {"event": "x", "child_name": "سارة"})
    assert "child_name" not in event
    assert event["dropped_fields"] == ["child_name"]


def test_allowed_field_survives() -> None:
    event = field_allow_list(None, "info", {"event": "x", "child_id": "abc"})
    assert event["child_id"] == "abc"
    assert "dropped_fields" not in event


def test_forbidden_substring_beats_allow_list() -> None:
    """Even if a dangerous key were added to ALLOWED_FIELDS, it is still dropped."""
    for substring in FORBIDDEN_SUBSTRINGS:
        key = f"user_{substring}"
        event = field_allow_list(None, "info", {"event": "x", key: "secret-value"})
        assert key not in event, f"{key} leaked"


def test_no_allowed_field_contains_a_forbidden_substring() -> None:
    from app.core.logging import EXEMPT_FIELDS

    for field in ALLOWED_FIELDS - EXEMPT_FIELDS:
        lowered = field.lower()
        offenders = [s for s in FORBIDDEN_SUBSTRINGS if s in lowered]
        assert not offenders, f"{field} contains {offenders}"


def test_rendered_record_is_json_with_request_id(capsys) -> None:  # type: ignore[no-untyped-def]
    configure_logging(level="DEBUG", service="misk-api")
    set_request_id("req-123")
    structlog.get_logger("t").info("event_name", child_id="c1", phone_number="+201234")
    captured = capsys.readouterr().out.strip().splitlines()[-1]
    record = json.loads(captured)
    assert record["request_id"] == "req-123"
    assert record["child_id"] == "c1"
    assert "phone_number" not in record
    assert "+201234" not in captured


def test_exempt_fields_are_counters_not_credentials() -> None:
    """The exemption list may only ever hold token *counts*."""
    from app.core.logging import EXEMPT_FIELDS

    assert EXEMPT_FIELDS <= ALLOWED_FIELDS
    for field in EXEMPT_FIELDS:
        assert field.endswith("tokens"), field
