"""Anti-nagging. The most product-critical file in C10.

docs/04a §C10 lists four rules and one sentence that explains all of them:

    Bring caregivers back at the right moments **without becoming another
    anxiety source.**

The parent of a child with Down syndrome already has a phone full of
appointment reminders. A learning app that adds three notifications a day to
that is not engaging; it is one more thing failing them. So:

* a hard cap of **3 per caregiver per week**, across every kind, enforced in the
  send path rather than per job — nine jobs each politely limiting themselves is
  how you end up sending nine;
* quiet hours 21:00–08:00 Africa/Cairo, **deferred, never dropped** — a dropped
  notification is a missed six-month assessment;
* `pgee_due` nudges at 180, 194 and 208 days and then **never again, ever**;
* one tap sets a 1/week cap for good.

And one rule that is not about frequency at all: a notification body that
implies the child is behind must be **impossible to send**. That is a call into
the same banned-terms list the i18n bundle is linted against, made at the send
path so no job can bypass it.

Pure. No I/O.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum
from zoneinfo import ZoneInfo

PRODUCT_TZ = ZoneInfo("Africa/Cairo")

#: docs/04a §C10. Across ALL kinds, per caregiver, per ISO week.
WEEKLY_CAP = 3
#: What the one-tap "fewer reminders" control sets.
REDUCED_WEEKLY_CAP = 1

#: Quiet hours, local. 21:00 inclusive through 08:00 exclusive.
QUIET_START_HOUR = 21
QUIET_END_HOUR = 8

#: docs/04a §C10 — three nudges maximum, ever, per assessment cycle.
PGEE_DUE_DAYS: tuple[int, ...] = (180, 194, 208)

#: docs/04a §C10 — `streak_encourage` is capped separately and lower.
STREAK_WEEKLY_CAP = 2


class Kind(StrEnum):
    PGEE_DUE = "pgee_due"
    WEEKLY_DIGEST = "weekly_digest"
    REPORT_READY = "report_ready"
    ESCALATION_ACK = "escalation_ack"
    STREAK = "streak"


class Channel(StrEnum):
    PUSH = "push"
    SMS = "sms"
    IN_APP = "in_app"


#: docs/04a §C10 — SMS only for `pgee_due` after two ignored pushes, and for
#: escalation acknowledgements. Everything else is push or in-app.
SMS_ELIGIBLE: frozenset[Kind] = frozenset({Kind.PGEE_DUE, Kind.ESCALATION_ACK})

#: An escalation acknowledgement is a human replying to a worried parent. It is
#: not marketing and it does not wait for morning.
BYPASSES_QUIET_HOURS: frozenset[Kind] = frozenset({Kind.ESCALATION_ACK})
BYPASSES_WEEKLY_CAP: frozenset[Kind] = frozenset({Kind.ESCALATION_ACK})


class NotificationRejected(ValueError):
    """The notification must not be sent at all. `reason` is a stable code."""

    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)


@dataclass(frozen=True, slots=True)
class Scheduled:
    """One notification, as it exists before the send path has ruled on it."""

    caregiver_id: str
    kind: Kind
    channel: Channel
    dedupe_key: str
    scheduled_for: dt.datetime
    body_ar: str
    child_id: str | None = None


@dataclass(frozen=True, slots=True)
class Decision:
    """What the send path decided, and why. `reason` is never shown to a user."""

    send_at: dt.datetime | None
    deferred: bool = False
    dropped: bool = False
    reason: str = ""

    @property
    def will_send(self) -> bool:
        return self.send_at is not None


def local(moment: dt.datetime) -> dt.datetime:
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=dt.UTC)
    return moment.astimezone(PRODUCT_TZ)


def iso_week(moment: dt.datetime) -> tuple[int, int]:
    date = local(moment).date()
    year, week, _ = date.isocalendar()
    return year, week


def in_quiet_hours(moment: dt.datetime) -> bool:
    hour = local(moment).hour
    return hour >= QUIET_START_HOUR or hour < QUIET_END_HOUR


def next_allowed_moment(moment: dt.datetime) -> dt.datetime:
    """The next 08:00 Cairo at or after `moment`.

    Computed by constructing 08:00 on the correct local *date* and letting
    zoneinfo resolve the offset, rather than by adding hours. Egypt reintroduced
    DST in 2023, so adding a fixed number of hours across the April or October
    transition lands an hour out — which is how a "morning" notification arrives
    at 07:00 or 09:00 twice a year.
    """
    here = local(moment)
    if not in_quiet_hours(here):
        return moment

    target_date = here.date()
    if here.hour >= QUIET_START_HOUR:
        target_date = target_date + dt.timedelta(days=1)
    return dt.datetime.combine(target_date, dt.time(QUIET_END_HOUR), tzinfo=PRODUCT_TZ).astimezone(
        dt.UTC
    )


def weekly_cap_for(*, fewer_reminders: bool) -> int:
    return REDUCED_WEEKLY_CAP if fewer_reminders else WEEKLY_CAP


def pgee_nudge_due(*, days_since_assessment: int, nudges_sent: int) -> bool:
    """Is a `pgee_due` nudge owed right now?

    Three, ever. The count is per assessment cycle and is reset only by a
    completed assessment — never by time passing, and never by the caregiver
    dismissing one.
    """
    if nudges_sent >= len(PGEE_DUE_DAYS):
        return False
    return days_since_assessment >= PGEE_DUE_DAYS[nudges_sent]


def check_body(body: str, banned_terms: Sequence[str]) -> None:
    """Raise if the copy implies the child is behind.

    Called on every notification, in the send path. A job that composed a
    perfectly reasonable sentence containing "متأخر" gets a hard failure rather
    than a delivery.
    """
    lowered = body.lower()
    hits = [
        term
        for term in banned_terms
        if (term.lower() in lowered if term.isascii() else term in body)
    ]
    if hits:
        raise NotificationRejected(f"banned_term:{hits[0]}")


def decide(
    notification: Scheduled,
    *,
    sent_this_week: int,
    fewer_reminders: bool = False,
    banned_terms: Sequence[str] = (),
    kind_sent_this_week: int = 0,
) -> Decision:
    """The single send-path gate. Every notification passes through here.

    Order matters and is deliberate:

    1. **Content** first. A notification that must never be sent is not made
       acceptable by being under the cap or outside quiet hours.
    2. **Cap** next — a drop, because a fourth notification this week is not
       wanted tomorrow either.
    3. **Quiet hours** last — a *deferral*, because the notification is fine and
       only the moment is wrong.

    Checking quiet hours before the cap would defer a notification into next
    week and quietly convert a drop into a delivery.
    """
    check_body(notification.body_ar, banned_terms)

    if notification.channel is Channel.SMS and notification.kind not in SMS_ELIGIBLE:
        raise NotificationRejected(f"sms_not_allowed_for:{notification.kind.value}")

    if notification.kind is Kind.STREAK and kind_sent_this_week >= STREAK_WEEKLY_CAP:
        return Decision(send_at=None, dropped=True, reason="streak_cap")

    if notification.kind not in BYPASSES_WEEKLY_CAP:
        cap = weekly_cap_for(fewer_reminders=fewer_reminders)
        if sent_this_week >= cap:
            return Decision(send_at=None, dropped=True, reason=f"weekly_cap:{cap}")

    if notification.kind in BYPASSES_QUIET_HOURS:
        return Decision(send_at=notification.scheduled_for)

    if in_quiet_hours(notification.scheduled_for):
        return Decision(
            send_at=next_allowed_moment(notification.scheduled_for),
            deferred=True,
            reason="quiet_hours",
        )

    return Decision(send_at=notification.scheduled_for)


def dedupe_key(*, caregiver_id: str, kind: Kind, child_id: str | None, discriminator: str) -> str:
    """The value the UNIQUE index enforces.

    Built here rather than by each job so that two jobs cannot produce two
    different keys for the same logical notification — which is the only way a
    unique index fails to prevent a double send.
    """
    return ":".join([kind.value, caregiver_id, child_id or "-", discriminator])
