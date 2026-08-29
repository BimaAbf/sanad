"""One send path, three channels.

docs/04a §C10: Web Push (VAPID) primary, SMS only for `pgee_due` after two
ignored pushes and for escalation acknowledgements, in-app always.

The important structural property is that `NotificationSender.send` is the only
function that talks to a channel, so `policy.decide` cannot be bypassed by a
job that reaches for a provider directly.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Protocol

import structlog

from app.modules.notifications.domain.policy import (
    Channel,
    Decision,
    Kind,
    Scheduled,
    decide,
)

logger = structlog.get_logger(__name__)

#: docs/04a §C10 — SMS for pgee_due only after this many ignored pushes.
IGNORED_PUSHES_BEFORE_SMS = 2


class ChannelTransport(Protocol):
    name: str

    async def deliver(
        self, *, recipient: str, body_ar: str, payload: dict[str, object]
    ) -> bool: ...


class NullTransport:
    """Records instead of delivering. The CI default and the local default."""

    def __init__(self, name: str, *, healthy: bool = True) -> None:
        self.name = name
        self.healthy = healthy
        self.delivered: list[tuple[str, str]] = []

    async def deliver(self, *, recipient: str, body_ar: str, payload: dict[str, object]) -> bool:
        if not self.healthy:
            return False
        self.delivered.append((recipient, body_ar))
        return True


class NotificationStore(Protocol):
    async def sent_this_week(self, caregiver_id: str, *, at: dt.datetime) -> int: ...

    async def sent_this_week_of_kind(
        self, caregiver_id: str, kind: str, *, at: dt.datetime
    ) -> int: ...

    async def claim(self, notification: Scheduled, send_at: dt.datetime) -> bool: ...

    async def mark_sent(self, dedupe_key: str, at: dt.datetime) -> None: ...

    async def preferences(self, caregiver_id: str) -> dict[str, object]: ...


@dataclass
class NotificationSender:
    store: NotificationStore
    transports: dict[Channel, ChannelTransport]
    banned_terms: Sequence[str] = field(default_factory=tuple)

    async def send(self, notification: Scheduled, *, now: dt.datetime, recipient: str) -> Decision:
        """Gate, claim, deliver. In that order, and never a different one.

        The claim is a database insert on `dedupe_key`, so a duplicate is
        refused by the UNIQUE index rather than by a read-then-write check that
        two workers can both pass.
        """
        preferences = await self.store.preferences(notification.caregiver_id)
        decision = decide(
            notification,
            sent_this_week=await self.store.sent_this_week(notification.caregiver_id, at=now),
            kind_sent_this_week=await self.store.sent_this_week_of_kind(
                notification.caregiver_id, notification.kind.value, at=now
            ),
            fewer_reminders=bool(preferences.get("fewer_reminders", False)),
            banned_terms=self.banned_terms,
        )
        if decision.send_at is None:
            logger.info(
                "notification_dropped",
                kind=notification.kind.value,
                reason=decision.reason,
            )
            return decision

        if not await self.store.claim(notification, decision.send_at):
            # The unique index refused it. Another worker already owns this one.
            return Decision(send_at=None, dropped=True, reason="duplicate")

        if decision.deferred:
            # Queued for 08:00 rather than delivered now. Not dropped.
            logger.info("notification_deferred", kind=notification.kind.value)
            return decision

        transport = self.transports.get(notification.channel)
        if transport is None or not await transport.deliver(
            recipient=recipient, body_ar=notification.body_ar, payload={}
        ):
            # A dead channel is not a dead notification: it stays claimed and
            # unsent, and the next drain retries it.
            logger.info("notification_delivery_failed", channel=notification.channel.value)
            return Decision(send_at=decision.send_at, reason="delivery_failed")

        await self.store.mark_sent(notification.dedupe_key, now)
        return decision


def choose_channel(*, kind: Kind, ignored_pushes: int, push_subscribed: bool) -> Channel:
    """docs/04a §C10's channel table, as a function.

    In-app is the floor: a caregiver with no push subscription and no SMS
    eligibility still gets the notification the next time they open the app.
    """
    if kind is Kind.ESCALATION_ACK:
        return Channel.SMS
    if kind is Kind.PGEE_DUE and ignored_pushes >= IGNORED_PUSHES_BEFORE_SMS:
        return Channel.SMS
    if push_subscribed:
        return Channel.PUSH
    return Channel.IN_APP
