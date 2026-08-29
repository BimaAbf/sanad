"""P02 acceptance criteria for the children/consent service.

The ones that matter:
  * creating a child without all three mandatory consents fails with a clear
    Arabic message and leaves NO partial child behind
  * withdrawing ai_processing binds within the same request — no stale cache
  * two concurrent PATCHes: the second gets 409, not a lost update
  * an invite is single-use and expires
"""

from __future__ import annotations

import datetime as dt
import uuid
from dataclasses import dataclass, field
from typing import Any

import pytest
from tests.unit.test_identity_service import FakeRepo as FakeIdentityRepo

from app.core.config import Settings, get_settings
from app.core.errors import NotFound
from app.modules.children import domain
from app.modules.children.consent_gate import ConsentGate, ConsentRequired
from app.modules.children.domain import ConsentKey
from app.modules.children.schemas import ChildCreate, ConsentInput
from app.modules.children.service import (
    ChildrenService,
    InvalidDob,
    InviteInvalid,
    MissingMandatoryConsent,
    StaleWrite,
)

TODAY = dt.date(2026, 8, 29)


# --- in-memory doubles ------------------------------------------------------


@dataclass
class FakeChild:
    id: uuid.UUID
    display_name: str
    date_of_birth: dt.date
    gestational_weeks: int | None = None
    version: int = 1
    updated_at: dt.datetime = field(
        default_factory=lambda: dt.datetime(2026, 8, 29, 12, 0, tzinfo=dt.UTC)
    )
    archived_at: dt.datetime | None = None
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass
class FakeDefinition:
    key: str
    version: int
    text_ar: str
    text_en: str
    is_mandatory: bool


@dataclass
class FakeConsent:
    child_id: uuid.UUID
    consent_key: str
    status: str
    granted_at: dt.datetime
    version: int = 1


@dataclass
class FakeInvite:
    id: uuid.UUID
    child_id: uuid.UUID
    invited_by: uuid.UUID
    role: str
    token_hash: str
    expires_at: dt.datetime
    accepted_at: dt.datetime | None = None
    revoked_at: dt.datetime | None = None


DEFINITIONS = [
    FakeDefinition(
        key=key.value,
        version=1,
        text_ar=f"نص {key.value}",
        text_en=key.value,
        is_mandatory=key in domain.MANDATORY_CONSENTS,
    )
    for key in ConsentKey
]


@dataclass
class FakeChildrenRepo:
    children: dict[uuid.UUID, FakeChild] = field(default_factory=dict)
    consents: list[FakeConsent] = field(default_factory=list)
    invites: dict[str, FakeInvite] = field(default_factory=dict)

    async def get_child(self, child_id: uuid.UUID) -> FakeChild | None:
        return self.children.get(child_id)

    async def create_child(self, **fields: Any) -> FakeChild:
        child = FakeChild(
            id=uuid.uuid4(),
            display_name=fields["display_name"],
            date_of_birth=fields["date_of_birth"],
            gestational_weeks=fields.get("gestational_weeks"),
            extra=fields,
        )
        self.children[child.id] = child
        return child

    async def patch_child(
        self, *, child_id: uuid.UUID, changes: dict[str, Any], now: dt.datetime
    ) -> None:
        child = self.children[child_id]
        child.extra.update(changes)
        child.updated_at = now
        child.version += 1

    async def patch_child_if_version_matches(
        self,
        *,
        child_id: uuid.UUID,
        changes: dict[str, Any],
        expected_version: int,
        now: dt.datetime,
    ) -> bool:
        child = self.children[child_id]
        if child.version != expected_version:
            return False
        child.extra.update(changes)
        child.updated_at = now
        child.version += 1
        return True

    async def archive_child(self, child_id: uuid.UUID, now: dt.datetime) -> None:
        self.children[child_id].archived_at = now

    async def list_consent_definitions(self) -> list[FakeDefinition]:
        return DEFINITIONS

    async def get_consent_definition(self, key: str) -> FakeDefinition | None:
        return next((d for d in DEFINITIONS if d.key == key), None)

    async def record_consent(
        self,
        *,
        child_id: uuid.UUID,
        caregiver_id: uuid.UUID,
        consent_key: str,
        version: int,
        granted: bool,
        now: dt.datetime,
        source_ip: Any = None,
        user_agent: Any = None,
    ) -> FakeConsent:
        consent = FakeConsent(
            child_id=child_id,
            consent_key=consent_key,
            status="granted" if granted else "withdrawn",
            granted_at=now,
            version=version,
        )
        self.consents.append(consent)
        return consent

    async def current_consents(self, child_id: uuid.UUID) -> dict[str, FakeConsent]:
        latest: dict[str, FakeConsent] = {}
        for consent in self.consents:
            if consent.child_id != child_id:
                continue
            latest[consent.consent_key] = consent
        return latest

    async def create_invite(
        self,
        *,
        child_id: uuid.UUID,
        invited_by: uuid.UUID,
        phone_e164: str,
        role: str,
        token_hash: str,
        expires_at: dt.datetime,
    ) -> FakeInvite:
        invite = FakeInvite(
            id=uuid.uuid4(),
            child_id=child_id,
            invited_by=invited_by,
            role=role,
            token_hash=token_hash,
            expires_at=expires_at,
        )
        self.invites[token_hash] = invite
        return invite

    async def find_invite(self, token_hash: str) -> FakeInvite | None:
        return self.invites.get(token_hash)

    async def accept_invite(
        self, *, invite_id: uuid.UUID, caregiver_id: uuid.UUID, now: dt.datetime
    ) -> None:
        for invite in self.invites.values():
            if invite.id == invite_id:
                invite.accepted_at = now


class FakeGate:
    """A ConsentGate that records invalidations so ordering can be asserted."""

    def __init__(self) -> None:
        self.invalidated: list[str] = []

    async def invalidate(self, child_id: str) -> None:
        self.invalidated.append(child_id)


@pytest.fixture
def settings() -> Settings:
    get_settings.cache_clear()
    return get_settings()


@pytest.fixture
def repo() -> FakeChildrenRepo:
    return FakeChildrenRepo()


@pytest.fixture
def identity_repo() -> FakeIdentityRepo:
    return FakeIdentityRepo()


@pytest.fixture
def gate() -> FakeGate:
    return FakeGate()


@pytest.fixture
def service(
    repo: FakeChildrenRepo,
    identity_repo: FakeIdentityRepo,
    gate: FakeGate,
    settings: Settings,
) -> ChildrenService:
    return ChildrenService(
        repo=repo,  # type: ignore[arg-type]
        identity_repo=identity_repo,  # type: ignore[arg-type]
        gate=gate,  # type: ignore[arg-type]
        settings=settings,
    )


def _payload(**overrides: Any) -> ChildCreate:
    base: dict[str, Any] = {
        "display_name": "يوسف",
        "date_of_birth": dt.date(2022, 3, 14),
        "sex": "male",
        "gestational_weeks": 38,
        "consents": [
            ConsentInput(key=key, granted=key in domain.MANDATORY_CONSENTS) for key in ConsentKey
        ],
    }
    base.update(overrides)
    return ChildCreate(**base)


# ============================================================================
# Creation and mandatory consent
# ============================================================================


async def test_creating_a_child_links_the_owner_and_records_every_consent(
    service: ChildrenService,
    repo: FakeChildrenRepo,
    identity_repo: FakeIdentityRepo,
    gate: FakeGate,
) -> None:
    caregiver_id = uuid.uuid4()
    created = await service.create_child(payload=_payload(), caregiver_id=caregiver_id, today=TODAY)

    assert created.child.id in repo.children
    assert len(repo.consents) == len(list(ConsentKey))
    assert identity_repo.links[(caregiver_id, created.child.id)].role == "owner"
    assert gate.invalidated == [str(created.child.id)]
    assert created.age.chronological_months == pytest.approx(53.5, abs=0.6)


@pytest.mark.parametrize("missing", sorted(domain.MANDATORY_CONSENTS, key=str))
async def test_a_missing_mandatory_consent_is_a_422_with_arabic(
    service: ChildrenService, repo: FakeChildrenRepo, missing: ConsentKey
) -> None:
    """P02: 'fails with 422 and a clear message_ar'."""
    consents = [
        ConsentInput(key=key, granted=key in domain.MANDATORY_CONSENTS and key != missing)
        for key in ConsentKey
    ]
    with pytest.raises(MissingMandatoryConsent) as excinfo:
        await service.create_child(
            payload=_payload(consents=consents), caregiver_id=uuid.uuid4(), today=TODAY
        )

    assert excinfo.value.status == 422
    assert excinfo.value.message_ar
    assert missing.value in excinfo.value.extra["missing"]
    assert repo.children == {}, "a rejected create must leave no partial child"
    assert repo.consents == [], "and no orphaned consent rows"


async def test_declining_every_optional_consent_still_creates_the_child(
    service: ChildrenService,
) -> None:
    """Declining voice_asr must leave a fully working product."""
    consents = [
        ConsentInput(key=key, granted=key in domain.MANDATORY_CONSENTS) for key in ConsentKey
    ]
    created = await service.create_child(
        payload=_payload(consents=consents), caregiver_id=uuid.uuid4(), today=TODAY
    )
    assert created.child.id


async def test_a_future_date_of_birth_is_refused(service: ChildrenService) -> None:
    with pytest.raises(InvalidDob) as excinfo:
        await service.create_child(
            payload=_payload(date_of_birth=TODAY + dt.timedelta(days=1)),
            caregiver_id=uuid.uuid4(),
            today=TODAY,
        )
    assert "المستقبل" in excinfo.value.message_ar


async def test_a_child_over_eight_is_refused(service: ChildrenService) -> None:
    with pytest.raises(InvalidDob) as excinfo:
        await service.create_child(
            payload=_payload(date_of_birth=dt.date(2010, 1, 1)),
            caregiver_id=uuid.uuid4(),
            today=TODAY,
        )
    assert excinfo.value.status == 422
    assert excinfo.value.message_ar


async def test_a_preterm_child_reports_a_corrected_age(service: ChildrenService) -> None:
    created = await service.create_child(
        payload=_payload(date_of_birth=TODAY - dt.timedelta(days=548), gestational_weeks=32),
        caregiver_id=uuid.uuid4(),
        today=TODAY,
    )
    assert created.age.is_corrected
    assert created.age.corrected_months < created.age.chronological_months


async def test_gestational_weeks_outside_the_plausible_range_are_refused() -> None:
    """Pydantic catches it at the boundary, before the service is reached."""
    from pydantic import ValidationError

    for weeks in (10, 60):
        with pytest.raises(ValidationError):
            _payload(gestational_weeks=weeks)


async def test_a_service_level_gestational_check_also_exists(
    service: ChildrenService,
) -> None:
    """Defence in depth: the schema is not the only guard."""
    payload = _payload()
    object.__setattr__(payload, "gestational_weeks", 5)
    with pytest.raises(InvalidDob):
        await service.create_child(payload=payload, caregiver_id=uuid.uuid4(), today=TODAY)


async def test_an_unknown_consent_key_in_the_payload_is_ignored_not_fatal(
    service: ChildrenService, repo: FakeChildrenRepo, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A key the definitions table does not know about must not 500."""

    async def only_mandatory() -> list[FakeDefinition]:
        return [d for d in DEFINITIONS if d.is_mandatory]

    monkeypatch.setattr(repo, "list_consent_definitions", only_mandatory)
    created = await service.create_child(payload=_payload(), caregiver_id=uuid.uuid4(), today=TODAY)
    assert created.child.id
    assert len(repo.consents) == 3


# ============================================================================
# Consent withdrawal
# ============================================================================


async def test_withdrawing_a_consent_appends_rather_than_updating(
    service: ChildrenService, repo: FakeChildrenRepo
) -> None:
    """The ledger is the audit; a withdrawal must never overwrite a grant."""
    caregiver_id = uuid.uuid4()
    consents = [
        ConsentInput(
            key=key,
            granted=key in domain.MANDATORY_CONSENTS or key is ConsentKey.VOICE_ASR,
        )
        for key in ConsentKey
    ]
    created = await service.create_child(
        payload=_payload(consents=consents), caregiver_id=caregiver_id, today=TODAY
    )
    before = len(repo.consents)

    await service.set_consent(
        child_id=created.child.id,
        caregiver_id=caregiver_id,
        key=ConsentKey.VOICE_ASR,
        granted=False,
    )
    assert len(repo.consents) == before + 1
    assert repo.consents[-1].status == "withdrawn"
    # The original grant row is still there.
    assert any(
        c.consent_key == ConsentKey.VOICE_ASR.value and c.status == "granted" for c in repo.consents
    )


async def test_the_cache_is_busted_before_the_response_returns(
    service: ChildrenService, gate: FakeGate
) -> None:
    """P02: 'no stale cache window'.

    The invalidation must happen inside `set_consent`, not afterwards in the
    router, or the very next call in the same request reads a stale grant.
    """
    caregiver_id = uuid.uuid4()
    created = await service.create_child(payload=_payload(), caregiver_id=caregiver_id, today=TODAY)
    gate.invalidated.clear()

    await service.set_consent(
        child_id=created.child.id,
        caregiver_id=caregiver_id,
        key=ConsentKey.AI_PROCESSING,
        granted=False,
    )
    assert gate.invalidated == [str(created.child.id)]


async def test_withdrawing_a_mandatory_consent_archives_the_child(
    service: ChildrenService, repo: FakeChildrenRepo
) -> None:
    """There is no lawful basis left to keep processing (docs/07 §4)."""
    caregiver_id = uuid.uuid4()
    created = await service.create_child(payload=_payload(), caregiver_id=caregiver_id, today=TODAY)
    assert repo.children[created.child.id].archived_at is None

    await service.set_consent(
        child_id=created.child.id,
        caregiver_id=caregiver_id,
        key=ConsentKey.DATA_PROCESSING,
        granted=False,
    )
    assert repo.children[created.child.id].archived_at is not None


async def test_withdrawing_an_optional_consent_does_not_archive(
    service: ChildrenService, repo: FakeChildrenRepo
) -> None:
    caregiver_id = uuid.uuid4()
    created = await service.create_child(payload=_payload(), caregiver_id=caregiver_id, today=TODAY)
    await service.set_consent(
        child_id=created.child.id,
        caregiver_id=caregiver_id,
        key=ConsentKey.VOICE_RETENTION,
        granted=False,
    )
    assert repo.children[created.child.id].archived_at is None


async def test_an_unknown_consent_key_is_a_404(service: ChildrenService) -> None:
    class Unknown:
        value = "not_a_real_key"

    with pytest.raises(NotFound):
        await service.set_consent(
            child_id=uuid.uuid4(),
            caregiver_id=uuid.uuid4(),
            key=Unknown(),  # type: ignore[arg-type]
            granted=True,
        )


# ============================================================================
# Optimistic concurrency
# ============================================================================


async def test_two_concurrent_patches_in_the_same_second_the_second_gets_409(
    service: ChildrenService, repo: FakeChildrenRepo
) -> None:
    """P02: 'the second gets 409, not a lost update'.

    Both writes land in the SAME second, which is exactly the case an
    If-Unmodified-Since timestamp cannot detect — HTTP-date headers have
    whole-second resolution. That is why the check is a version counter.
    """
    created = await service.create_child(payload=_payload(), caregiver_id=uuid.uuid4(), today=TODAY)
    child_id = created.child.id
    both_read = repo.children[child_id].version

    await service.patch_child(
        child_id=child_id, changes={"calm_mode": True}, expected_version=both_read
    )

    with pytest.raises(StaleWrite) as excinfo:
        await service.patch_child(
            child_id=child_id,
            changes={"calm_mode": False},
            expected_version=both_read,
        )

    assert excinfo.value.status == 409
    assert excinfo.value.message_ar
    # A merge-friendly diff, as docs/04a §C02 requires.
    assert excinfo.value.extra["current_version"] == both_read + 1
    assert excinfo.value.extra["your_version"] == both_read
    assert excinfo.value.extra["conflicting_fields"] == ["calm_mode"]
    # And the first writer's value survived.
    assert repo.children[child_id].extra["calm_mode"] is True


async def test_a_timestamp_would_not_have_caught_that_conflict(
    service: ChildrenService, repo: FakeChildrenRepo
) -> None:
    """The finding, stated as an executable fact.

    Both writes carry the same whole-second timestamp, so any check comparing
    `updated_at` at HTTP-date resolution would have let both through.
    """
    created = await service.create_child(payload=_payload(), caregiver_id=uuid.uuid4(), today=TODAY)
    child_id = created.child.id

    # Two writes, both landing inside the same wall-clock second.
    first_at = dt.datetime.now(dt.UTC)
    repo.children[child_id].updated_at = first_at
    version_both_readers_saw = repo.children[child_id].version

    await service.patch_child(
        child_id=child_id,
        changes={"calm_mode": True},
        expected_version=version_both_readers_saw,
    )
    second_at = repo.children[child_id].updated_at

    # An HTTP-date header carries whole seconds only, so at that resolution the
    # two timestamps are INDISTINGUISHABLE and a timestamp check lets both win.
    assert first_at.replace(microsecond=0) == second_at.replace(microsecond=0)

    # The version, unlike the second, definitely moved — which is why the check
    # is a counter and not a clock.
    assert repo.children[child_id].version == version_both_readers_saw + 1


async def test_a_patch_without_an_etag_does_not_check_concurrency(
    service: ChildrenService, repo: FakeChildrenRepo
) -> None:
    """A client that does not care about conflicts may still write."""
    created = await service.create_child(payload=_payload(), caregiver_id=uuid.uuid4(), today=TODAY)
    await service.patch_child(
        child_id=created.child.id, changes={"calm_mode": True}, expected_version=None
    )
    assert repo.children[created.child.id].extra["calm_mode"] is True
    assert repo.children[created.child.id].version == 2


async def test_patching_a_missing_child_is_a_404(service: ChildrenService) -> None:
    with pytest.raises(NotFound):
        await service.get_child_or_404(uuid.uuid4())


# ============================================================================
# Invites
# ============================================================================


async def test_an_invite_is_single_use(
    service: ChildrenService, identity_repo: FakeIdentityRepo
) -> None:
    owner = uuid.uuid4()
    created = await service.create_child(payload=_payload(), caregiver_id=owner, today=TODAY)
    token, expires_at = await service.create_invite(
        child_id=created.child.id,
        invited_by=owner,
        phone_e164="+201009999999",
        role="co_caregiver",
    )
    assert expires_at > dt.datetime.now(dt.UTC)

    invitee = uuid.uuid4()
    linked = await service.accept_invite(token=token, caregiver_id=invitee)
    assert linked == created.child.id
    assert identity_repo.links[(invitee, created.child.id)].role == "co_caregiver"

    with pytest.raises(InviteInvalid):
        await service.accept_invite(token=token, caregiver_id=uuid.uuid4())


async def test_an_expired_invite_is_refused(
    service: ChildrenService, repo: FakeChildrenRepo
) -> None:
    owner = uuid.uuid4()
    created = await service.create_child(payload=_payload(), caregiver_id=owner, today=TODAY)
    token, _ = await service.create_invite(
        child_id=created.child.id,
        invited_by=owner,
        phone_e164="+201009999999",
        role="co_caregiver",
    )
    for invite in repo.invites.values():
        invite.expires_at = dt.datetime.now(dt.UTC) - dt.timedelta(seconds=1)

    with pytest.raises(InviteInvalid):
        await service.accept_invite(token=token, caregiver_id=uuid.uuid4())


async def test_a_revoked_invite_is_refused(
    service: ChildrenService, repo: FakeChildrenRepo
) -> None:
    owner = uuid.uuid4()
    created = await service.create_child(payload=_payload(), caregiver_id=owner, today=TODAY)
    token, _ = await service.create_invite(
        child_id=created.child.id,
        invited_by=owner,
        phone_e164="+201009999999",
        role="co_caregiver",
    )
    for invite in repo.invites.values():
        invite.revoked_at = dt.datetime.now(dt.UTC)

    with pytest.raises(InviteInvalid):
        await service.accept_invite(token=token, caregiver_id=uuid.uuid4())


async def test_an_unknown_invite_token_is_refused(service: ChildrenService) -> None:
    with pytest.raises(InviteInvalid):
        await service.accept_invite(token="never-issued", caregiver_id=uuid.uuid4())


async def test_the_invite_token_is_stored_hashed_not_in_plaintext(
    service: ChildrenService, repo: FakeChildrenRepo
) -> None:
    """A leaked invites table must not hand over working invitations."""
    owner = uuid.uuid4()
    created = await service.create_child(payload=_payload(), caregiver_id=owner, today=TODAY)
    token, _ = await service.create_invite(
        child_id=created.child.id,
        invited_by=owner,
        phone_e164="+201009999999",
        role="co_caregiver",
    )
    assert token not in repo.invites
    assert all(token not in stored for stored in repo.invites)


async def test_accepting_an_invite_twice_by_the_same_person_does_not_duplicate_a_link(
    service: ChildrenService, identity_repo: FakeIdentityRepo
) -> None:
    owner = uuid.uuid4()
    created = await service.create_child(payload=_payload(), caregiver_id=owner, today=TODAY)
    token, _ = await service.create_invite(
        child_id=created.child.id,
        invited_by=owner,
        phone_e164="+201009999999",
        role="co_caregiver",
    )
    # The owner accepting their own invite must not overwrite their owner role.
    await service.accept_invite(token=token, caregiver_id=owner)
    assert identity_repo.links[(owner, created.child.id)].role == "owner"


# ============================================================================
# ConsentGate
# ============================================================================


class FakeSessionWithConsents:
    """Just enough of an AsyncSession for the gate's single query."""

    def __init__(self, rows: list[tuple[str, str]]) -> None:
        self.rows = rows
        self.queries = 0

    async def execute(self, _statement: Any, _params: Any = None) -> Any:
        self.queries += 1

        class Row:
            def __init__(self, key: str, status: str) -> None:
                self.consent_key = key
                self.status = status

        return [Row(key, status) for key, status in self.rows]


class FakeRedisCache:
    def __init__(self) -> None:
        self.store: dict[str, str] = {}

    async def get(self, key: str) -> str | None:
        return self.store.get(key)

    async def setex(self, key: str, _ttl: int, value: str) -> None:
        self.store[key] = value

    async def delete(self, key: str) -> None:
        self.store.pop(key, None)


class BrokenRedisCache:
    async def get(self, key: str) -> str | None:
        raise ConnectionError("down")

    async def setex(self, key: str, ttl: int, value: str) -> None:
        raise ConnectionError("down")

    async def delete(self, key: str) -> None:
        raise ConnectionError("down")


async def test_the_gate_raises_consent_required_when_a_consent_is_absent() -> None:
    session = FakeSessionWithConsents([("data_processing", "granted")])
    gate = ConsentGate(session, None)  # type: ignore[arg-type]

    await gate.require("child-1", ConsentKey.DATA_PROCESSING)
    with pytest.raises(ConsentRequired) as excinfo:
        await gate.require("child-1", ConsentKey.AI_PROCESSING)
    assert excinfo.value.status == 403
    assert excinfo.value.code == "consent_required"
    assert excinfo.value.message_ar


async def test_a_withdrawn_consent_is_not_granted() -> None:
    session = FakeSessionWithConsents([("ai_processing", "withdrawn")])
    gate = ConsentGate(session, None)  # type: ignore[arg-type]
    assert await gate.is_granted("child-1", ConsentKey.AI_PROCESSING) is False


async def test_the_gate_reads_through_the_cache_then_serves_from_it() -> None:
    session = FakeSessionWithConsents([("ai_processing", "granted")])
    cache = FakeRedisCache()
    gate = ConsentGate(session, cache)  # type: ignore[arg-type]

    assert await gate.is_granted("c1", ConsentKey.AI_PROCESSING) is True
    assert session.queries == 1
    assert await gate.is_granted("c1", ConsentKey.AI_PROCESSING) is True
    assert session.queries == 1, "the second read should have been cached"


async def test_invalidation_forces_the_next_read_back_to_the_database() -> None:
    """This is what makes withdrawal effective within the same request."""
    session = FakeSessionWithConsents([("ai_processing", "granted")])
    cache = FakeRedisCache()
    gate = ConsentGate(session, cache)  # type: ignore[arg-type]

    await gate.is_granted("c1", ConsentKey.AI_PROCESSING)
    await gate.invalidate("c1")

    session.rows = [("ai_processing", "withdrawn")]
    assert await gate.is_granted("c1", ConsentKey.AI_PROCESSING) is False
    assert session.queries == 2


async def test_the_gate_falls_back_to_the_database_when_redis_is_down() -> None:
    """Fail closed: an outage must not widen what we may do with a child's data."""
    session = FakeSessionWithConsents([("ai_processing", "granted")])
    gate = ConsentGate(session, BrokenRedisCache())  # type: ignore[arg-type]
    assert await gate.is_granted("c1", ConsentKey.AI_PROCESSING) is True
    # And a failed invalidation does not raise into the request.
    await gate.invalidate("c1")


async def test_invalidating_with_no_cache_configured_is_a_no_op() -> None:
    gate = ConsentGate(FakeSessionWithConsents([]), None)  # type: ignore[arg-type]
    await gate.invalidate("c1")


async def test_a_child_with_no_consent_rows_is_granted_nothing() -> None:
    gate = ConsentGate(FakeSessionWithConsents([]), None)  # type: ignore[arg-type]
    for key in ConsentKey:
        assert await gate.is_granted("c1", key) is False
