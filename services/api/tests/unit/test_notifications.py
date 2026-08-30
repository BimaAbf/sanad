"""T10–T11 — the anti-nagging rules.

Every test here is really the same test: *does this product respect a tired
parent's attention*. That is why the numbers are asserted exactly (3, not
"about 3") and why the DST cases are in here rather than in a timezone utility
suite — a digest that arrives at 07:00 for six months of the year is the bug
this file exists to prevent.
"""

from __future__ import annotations

import datetime as dt

import pytest
from tools.lint.banned_terms import BANNED_AR, BANNED_EN

from app.modules.notifications.channels import (
    IGNORED_PUSHES_BEFORE_SMS,
    NotificationSender,
    NullTransport,
    choose_channel,
)
from app.modules.notifications.domain.policy import (
    PGEE_DUE_DAYS,
    PRODUCT_TZ,
    REDUCED_WEEKLY_CAP,
    STREAK_WEEKLY_CAP,
    WEEKLY_CAP,
    Channel,
    Kind,
    NotificationRejected,
    Scheduled,
    check_body,
    decide,
    dedupe_key,
    in_quiet_hours,
    iso_week,
    next_allowed_moment,
    pgee_nudge_due,
    weekly_cap_for,
)
from app.workers.schedule import JOBS, job_names, utc_hour_for

BANNED = (*BANNED_EN, *BANNED_AR)

#: A Tuesday at 14:00 Cairo — comfortably outside quiet hours.
MIDDAY = dt.datetime(2026, 8, 25, 11, 0, tzinfo=dt.UTC)

SAFE_BODY = "النهارده لعبتوا مع بعض ١٠ دقايق. برافو!"


def note(
    kind: Kind = Kind.WEEKLY_DIGEST,
    *,
    at: dt.datetime = MIDDAY,
    channel: Channel = Channel.PUSH,
    body: str = SAFE_BODY,
    key: str = "k1",
) -> Scheduled:
    return Scheduled(
        caregiver_id="cg1",
        kind=kind,
        channel=channel,
        dedupe_key=key,
        scheduled_for=at,
        body_ar=body,
        child_id="c1",
    )


# --- the weekly cap --------------------------------------------------------


def test_ten_eligible_notifications_in_a_week_deliver_exactly_three() -> None:
    """T11 §7 — the headline rule, simulated end to end through the gate."""
    sent = 0
    delivered: list[str] = []
    for index in range(10):
        decision = decide(note(key=f"k{index}"), sent_this_week=sent, banned_terms=BANNED)
        if decision.will_send:
            delivered.append(f"k{index}")
            sent += 1
    assert len(delivered) == WEEKLY_CAP == 3


def test_the_cap_spans_every_kind_not_each_kind() -> None:
    """Nine jobs each politely limiting themselves is how you send nine."""
    kinds = [Kind.WEEKLY_DIGEST, Kind.PGEE_DUE, Kind.REPORT_READY, Kind.STREAK]
    sent = 0
    for index, kind in enumerate(kinds):
        decision = decide(note(kind, key=f"k{index}"), sent_this_week=sent, banned_terms=BANNED)
        if decision.will_send:
            sent += 1
    assert sent == WEEKLY_CAP


def test_fewer_reminders_sets_a_one_per_week_cap() -> None:
    assert weekly_cap_for(fewer_reminders=True) == REDUCED_WEEKLY_CAP == 1
    first = decide(note(), sent_this_week=0, fewer_reminders=True, banned_terms=BANNED)
    second = decide(note(), sent_this_week=1, fewer_reminders=True, banned_terms=BANNED)
    assert first.will_send
    assert not second.will_send
    assert second.dropped


def test_an_escalation_acknowledgement_ignores_the_cap_and_quiet_hours() -> None:
    """A human replying to a worried parent is not marketing."""
    late = dt.datetime(2026, 8, 25, 20, 0, tzinfo=dt.UTC)  # 22:00 Cairo
    decision = decide(
        note(Kind.ESCALATION_ACK, at=late, channel=Channel.SMS),
        sent_this_week=99,
        banned_terms=BANNED,
    )
    assert decision.will_send
    assert not decision.deferred
    assert decision.send_at == late


def test_the_streak_nudge_has_its_own_lower_cap() -> None:
    over = decide(
        note(Kind.STREAK),
        sent_this_week=0,
        kind_sent_this_week=STREAK_WEEKLY_CAP,
        banned_terms=BANNED,
    )
    assert not over.will_send
    assert over.reason == "streak_cap"


# --- quiet hours -----------------------------------------------------------


@pytest.mark.parametrize(
    ("local_hour", "quiet"),
    [(20, False), (21, True), (23, True), (0, True), (7, True), (8, False), (12, False)],
)
def test_quiet_hours_window(local_hour: int, quiet: bool) -> None:
    moment = dt.datetime(2026, 8, 25, local_hour, 0, tzinfo=PRODUCT_TZ)
    assert in_quiet_hours(moment) is quiet


def test_a_notification_at_2200_is_delivered_at_0800_not_dropped() -> None:
    """T11 §8. A dropped notification is a missed six-month assessment."""
    at_ten_pm = dt.datetime(2026, 8, 25, 22, 0, tzinfo=PRODUCT_TZ)
    decision = decide(note(at=at_ten_pm), sent_this_week=0, banned_terms=BANNED)

    assert decision.will_send
    assert decision.deferred
    assert not decision.dropped
    local_send = decision.send_at.astimezone(PRODUCT_TZ)  # type: ignore[union-attr]
    assert (local_send.hour, local_send.minute) == (8, 0)
    assert local_send.date() == dt.date(2026, 8, 26)


def test_an_early_morning_notification_waits_for_the_same_day() -> None:
    at_three_am = dt.datetime(2026, 8, 26, 3, 0, tzinfo=PRODUCT_TZ)
    send_at = next_allowed_moment(at_three_am).astimezone(PRODUCT_TZ)
    assert send_at.date() == dt.date(2026, 8, 26)
    assert send_at.hour == 8


def test_a_moment_outside_quiet_hours_is_returned_unchanged() -> None:
    assert next_allowed_moment(MIDDAY) == MIDDAY


def test_the_cap_is_checked_before_quiet_hours() -> None:
    """Order matters: deferring first would push a dropped notification into
    next week and quietly turn it into a delivery."""
    at_ten_pm = dt.datetime(2026, 8, 25, 22, 0, tzinfo=PRODUCT_TZ)
    decision = decide(note(at=at_ten_pm), sent_this_week=WEEKLY_CAP, banned_terms=BANNED)
    assert decision.dropped
    assert not decision.deferred


# --- DST -------------------------------------------------------------------
#
# Egypt reintroduced DST in 2023: clocks go forward on the last Friday of April
# and back on the last Thursday of October. Both directions are tested because
# they fail differently — forward makes a job an hour early, back makes it an
# hour late, and only one of those is noticeable in staging.


def test_cairo_offset_changes_across_the_year() -> None:
    winter = dt.datetime(2026, 1, 15, 8, 0, tzinfo=PRODUCT_TZ)
    summer = dt.datetime(2026, 7, 15, 8, 0, tzinfo=PRODUCT_TZ)
    assert winter.utcoffset() != summer.utcoffset(), (
        "the tz database on this machine has no Egyptian DST rules; "
        "the DST tests below would pass vacuously"
    )


@pytest.mark.parametrize("date", [dt.date(2026, 1, 15), dt.date(2026, 7, 15)])
def test_the_digest_lands_at_1800_local_on_both_sides_of_dst(date: dt.date) -> None:
    digest = next(job for job in JOBS if job.name == "weekly_digest")
    utc_hour = utc_hour_for(digest, on=date)
    assert utc_hour is not None
    back = dt.datetime(date.year, date.month, date.day, utc_hour, tzinfo=dt.UTC)
    assert back.astimezone(PRODUCT_TZ).hour == 18


def test_deferral_across_the_spring_transition_still_lands_at_0800() -> None:
    """Clocks go forward overnight; adding "10 hours" would land at 09:00."""
    # 2026-04-24 is the last Friday of April.
    evening = dt.datetime(2026, 4, 23, 22, 0, tzinfo=PRODUCT_TZ)
    send_at = next_allowed_moment(evening).astimezone(PRODUCT_TZ)
    assert (send_at.hour, send_at.minute) == (8, 0)
    assert send_at.date() == dt.date(2026, 4, 24)


def test_deferral_across_the_autumn_transition_still_lands_at_0800() -> None:
    # Late October, when clocks go back.
    evening = dt.datetime(2026, 10, 28, 23, 30, tzinfo=PRODUCT_TZ)
    send_at = next_allowed_moment(evening).astimezone(PRODUCT_TZ)
    assert (send_at.hour, send_at.minute) == (8, 0)
    assert send_at.date() == dt.date(2026, 10, 29)


def test_iso_week_is_computed_in_local_time() -> None:
    # 23:30 UTC on a Sunday is Monday 01:30 in Cairo — a different ISO week.
    late_sunday = dt.datetime(2026, 8, 30, 23, 30, tzinfo=dt.UTC)
    assert iso_week(late_sunday) == (2026, 36)


# --- pgee_due: three nudges, ever -----------------------------------------


def test_pgee_due_fires_at_180_194_and_208_then_never_again() -> None:
    """T11 §9."""
    assert PGEE_DUE_DAYS == (180, 194, 208)
    sent = 0
    fired_on: list[int] = []
    for day in range(150, 400):
        if pgee_nudge_due(days_since_assessment=day, nudges_sent=sent):
            fired_on.append(day)
            sent += 1
    assert fired_on == [180, 194, 208]
    assert not pgee_nudge_due(days_since_assessment=10_000, nudges_sent=3)


def test_pgee_due_does_not_fire_early() -> None:
    assert not pgee_nudge_due(days_since_assessment=179, nudges_sent=0)
    assert pgee_nudge_due(days_since_assessment=180, nudges_sent=0)
    assert not pgee_nudge_due(days_since_assessment=193, nudges_sent=1)


# --- banned content --------------------------------------------------------


def test_a_body_containing_the_word_delayed_cannot_be_sent() -> None:
    """T11 §11. "متأخر" is the word the product exists to avoid."""
    with pytest.raises(NotificationRejected) as exc:
        decide(note(body="ابنك متأخر شوية"), sent_this_week=0, banned_terms=BANNED)
    assert exc.value.reason.startswith("banned_term:")


def test_the_check_runs_before_the_cap_and_before_quiet_hours() -> None:
    """A notification that must never be sent is not made acceptable by being
    over the cap, or by arriving at a convenient hour."""
    at_ten_pm = dt.datetime(2026, 8, 25, 22, 0, tzinfo=PRODUCT_TZ)
    with pytest.raises(NotificationRejected):
        decide(
            note(body="ابنك متأخر", at=at_ten_pm),
            sent_this_week=99,
            banned_terms=BANNED,
        )


@pytest.mark.parametrize("term", ["delay", "behind", "failed", "IQ", "أطفال طبيعيين"])
def test_every_banned_term_is_rejected(term: str) -> None:
    with pytest.raises(NotificationRejected):
        check_body(f"prefix {term} suffix", BANNED)


def test_english_terms_are_matched_case_insensitively() -> None:
    with pytest.raises(NotificationRejected):
        check_body("Your child is BEHIND", BANNED)


def test_safe_copy_passes() -> None:
    check_body(SAFE_BODY, BANNED)
    check_body("", BANNED)


# --- channels --------------------------------------------------------------


def test_sms_is_only_allowed_for_two_kinds() -> None:
    with pytest.raises(NotificationRejected) as exc:
        decide(
            note(Kind.WEEKLY_DIGEST, channel=Channel.SMS),
            sent_this_week=0,
            banned_terms=BANNED,
        )
    assert exc.value.reason.startswith("sms_not_allowed_for:")


def test_channel_selection_follows_the_table() -> None:
    assert (
        choose_channel(kind=Kind.ESCALATION_ACK, ignored_pushes=0, push_subscribed=True)
        is Channel.SMS
    )
    assert (
        choose_channel(kind=Kind.PGEE_DUE, ignored_pushes=0, push_subscribed=True) is Channel.PUSH
    )
    assert (
        choose_channel(
            kind=Kind.PGEE_DUE,
            ignored_pushes=IGNORED_PUSHES_BEFORE_SMS,
            push_subscribed=True,
        )
        is Channel.SMS
    )
    # In-app is the floor: a caregiver with no push subscription still gets it.
    assert (
        choose_channel(kind=Kind.WEEKLY_DIGEST, ignored_pushes=9, push_subscribed=False)
        is Channel.IN_APP
    )


# --- dedupe ----------------------------------------------------------------


def test_dedupe_keys_are_built_in_one_place() -> None:
    """Two jobs producing two keys for one logical notification is the only way
    a UNIQUE index fails to prevent a double send."""
    a = dedupe_key(caregiver_id="cg1", kind=Kind.PGEE_DUE, child_id="c1", discriminator="180")
    b = dedupe_key(caregiver_id="cg1", kind=Kind.PGEE_DUE, child_id="c1", discriminator="180")
    c = dedupe_key(caregiver_id="cg1", kind=Kind.PGEE_DUE, child_id="c1", discriminator="194")
    assert a == b
    assert a != c
    assert dedupe_key(caregiver_id="cg1", kind=Kind.STREAK, child_id=None, discriminator="x")


def test_the_dedupe_index_is_declared_not_null_in_the_migration() -> None:
    """T11 §10 asserts the DATABASE rejects a duplicate. That needs Postgres,
    which is blocked (BLOCKED.md #1). What can be asserted without one is that
    the DDL says what it must: NOT NULL plus UNIQUE, because a nullable unique
    column admits any number of NULLs and would make the guarantee vacuous for
    exactly the jobs that forgot a key."""
    from pathlib import Path

    ddl = (
        Path(__file__).resolve().parents[2] / "migrations" / "versions" / "0006_notifications.py"
    ).read_text(encoding="utf-8")
    assert "dedupe_key    text NOT NULL" in ddl
    assert "CREATE UNIQUE INDEX notifications_dedupe_uq ON notifications (dedupe_key)" in ddl
    assert "pgee_nudges_never_exceed_three CHECK (nudges_sent <= 3)" in ddl


# --- the send path ---------------------------------------------------------


class FakeStore:
    def __init__(self, *, sent: int = 0, of_kind: int = 0, claimable: bool = True) -> None:
        self.sent = sent
        self.of_kind = of_kind
        self.claimable = claimable
        self.claims: list[str] = []
        self.marked: list[str] = []
        self.prefs: dict[str, object] = {}

    async def sent_this_week(self, caregiver_id: str, *, at: dt.datetime) -> int:
        return self.sent

    async def sent_this_week_of_kind(self, caregiver_id: str, kind: str, *, at: dt.datetime) -> int:
        return self.of_kind

    async def claim(self, notification: Scheduled, send_at: dt.datetime) -> bool:
        if not self.claimable or notification.dedupe_key in self.claims:
            return False
        self.claims.append(notification.dedupe_key)
        return True

    async def mark_sent(self, dedupe_key: str, at: dt.datetime) -> None:
        self.marked.append(dedupe_key)

    async def preferences(self, caregiver_id: str) -> dict[str, object]:
        return self.prefs


def sender(store: FakeStore, *, healthy: bool = True) -> tuple[NotificationSender, NullTransport]:
    push = NullTransport("push", healthy=healthy)
    return (
        NotificationSender(
            store=store,
            transports={Channel.PUSH: push, Channel.IN_APP: NullTransport("in_app")},
            banned_terms=BANNED,
        ),
        push,
    )


async def test_the_send_path_delivers_and_marks_sent() -> None:
    store = FakeStore()
    send, push = sender(store)
    decision = await send.send(note(), now=MIDDAY, recipient="cg1")
    assert decision.will_send
    assert push.delivered == [("cg1", SAFE_BODY)]
    assert store.marked == ["k1"]


async def test_a_duplicate_claim_is_refused_by_the_store() -> None:
    store = FakeStore()
    send, push = sender(store)
    await send.send(note(), now=MIDDAY, recipient="cg1")
    second = await send.send(note(), now=MIDDAY, recipient="cg1")
    assert second.dropped
    assert second.reason == "duplicate"
    assert len(push.delivered) == 1


async def test_a_deferred_notification_is_claimed_but_not_delivered_yet() -> None:
    store = FakeStore()
    send, push = sender(store)
    at_ten_pm = dt.datetime(2026, 8, 25, 22, 0, tzinfo=PRODUCT_TZ)
    decision = await send.send(note(at=at_ten_pm), now=MIDDAY, recipient="cg1")
    assert decision.deferred
    assert store.claims == ["k1"]
    assert push.delivered == []


async def test_a_dead_channel_leaves_the_notification_unsent_for_retry() -> None:
    store = FakeStore()
    send, _ = sender(store, healthy=False)
    decision = await send.send(note(), now=MIDDAY, recipient="cg1")
    assert decision.reason == "delivery_failed"
    assert store.marked == []


async def test_an_unknown_channel_is_a_failure_not_a_crash() -> None:
    store = FakeStore()
    send = NotificationSender(store=store, transports={}, banned_terms=BANNED)
    decision = await send.send(note(), now=MIDDAY, recipient="cg1")
    assert decision.reason == "delivery_failed"


async def test_the_send_path_reads_the_fewer_reminders_preference() -> None:
    store = FakeStore(sent=1)
    store.prefs = {"fewer_reminders": True}
    send, push = sender(store)
    decision = await send.send(note(), now=MIDDAY, recipient="cg1")
    assert decision.dropped
    assert push.delivered == []


async def test_the_send_path_cannot_be_bypassed_for_banned_copy() -> None:
    store = FakeStore()
    send, _ = sender(store)
    with pytest.raises(NotificationRejected):
        await send.send(note(body="متأخر"), now=MIDDAY, recipient="cg1")
    assert store.claims == []


# --- the job table ---------------------------------------------------------


def test_all_nine_jobs_from_the_design_are_declared() -> None:
    assert set(job_names()) == {
        "pgee_due_scan",
        "weekly_digest",
        "streak_encourage",
        "report_ready",
        "escalation_sla",
        "rollup_rebuild",
        "bkt_decay",
        "tts_pregen",
        "cost_report",
    }


def test_event_driven_jobs_have_no_local_hour() -> None:
    for job in JOBS:
        if job.event_driven:
            assert job.local_hour is None
            assert utc_hour_for(job, on=dt.date(2026, 1, 1)) is None


def test_a_naive_timestamp_is_read_as_utc() -> None:
    """Everything reaching the send path comes from a timestamptz column or a
    client clock. Guessing "local" for a naive value would shift quiet hours by
    two or three hours depending on the season."""
    from app.modules.notifications.domain.policy import local

    naive = dt.datetime(2026, 8, 25, 20, 0)  # noqa: DTZ001 -- naive on purpose
    assert local(naive).hour == 23
    assert in_quiet_hours(naive)
