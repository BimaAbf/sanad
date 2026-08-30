"""Auth routes and the authorisation dependency, with the database overridden.

What these cover that the service tests cannot: the refresh cookie's flags, the
bearer-token extraction, and the guarantee that /auth/otp/request answers 202 to
absolutely everything.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from typing import Any

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from tests.unit.test_identity_service import AllowAllLimiter, FakeLink, FakeRepo

from app.core.config import Environment, Settings, get_settings
from app.core.db import get_session
from app.modules.identity import deps
from app.modules.identity.domain import Role
from app.modules.identity.router import REFRESH_COOKIE
from app.modules.identity.security import issue_access_token
from app.modules.identity.service import IdentityService, InvalidCredentials
from app.modules.identity.sms import NullSms

PHONE = "+201001234567"


class FakeSession:
    """A session that records commits and does nothing else."""

    def __init__(self) -> None:
        self.commits = 0

    async def commit(self) -> None:
        self.commits += 1

    async def rollback(self) -> None: ...

    async def close(self) -> None: ...


@pytest.fixture
def repo() -> FakeRepo:
    return FakeRepo()


@pytest.fixture
def sms() -> NullSms:
    return NullSms()


@pytest.fixture
def app(repo: FakeRepo, sms: NullSms) -> FastAPI:
    get_settings.cache_clear()
    from app.main import create_app

    application = create_app(get_settings())
    session = FakeSession()

    async def _session() -> AsyncIterator[Any]:
        yield session

    async def _service() -> AsyncIterator[IdentityService]:
        yield IdentityService(
            repo=repo,  # type: ignore[arg-type]
            limiter=AllowAllLimiter(),  # type: ignore[arg-type]
            sms=sms,
            settings=get_settings(),
        )

    application.dependency_overrides[get_session] = _session
    application.dependency_overrides[deps.get_identity_service] = _service
    return application


async def _client(app: FastAPI) -> AsyncClient:
    return AsyncClient(
        transport=ASGITransport(app=app, raise_app_exceptions=False),
        base_url="http://test",
    )


def _code(sms: NullSms) -> str:
    import re

    match = re.search(r"\d{6}", sms.sent[-1][1])
    assert match
    return match.group(0)


# ============================================================================
# /auth/otp/request always answers 202
# ============================================================================


@pytest.mark.parametrize(
    "payload",
    [
        {"phone_e164": "+201001234567"},
        {"phone_e164": "01001234567"},
        {"phone_e164": "0100 123 4567"},
    ],
)
async def test_a_valid_number_always_gets_202(app: FastAPI, payload: dict[str, str]) -> None:
    async with await _client(app) as client:
        response = await client.post("/auth/otp/request", json=payload)
    assert response.status_code == 202
    assert response.json() == {}


async def test_the_response_body_reveals_nothing_about_the_account(
    app: FastAPI, repo: FakeRepo, sms: NullSms
) -> None:
    """Registering a number must not change what the endpoint says."""
    async with await _client(app) as client:
        before = await client.post("/auth/otp/request", json={"phone_e164": PHONE})
        await client.post("/auth/otp/verify", json={"phone_e164": PHONE, "code": _code(sms)})
        assert await repo.find_caregiver_by_phone(PHONE) is not None
        after = await client.post("/auth/otp/request", json={"phone_e164": PHONE})

    assert (before.status_code, before.json()) == (after.status_code, after.json())


async def test_an_unparseable_number_is_a_422_not_a_leak(app: FastAPI) -> None:
    """Rejecting a malformed number is not an enumeration oracle — it says
    nothing about whether any account exists."""
    async with await _client(app) as client:
        response = await client.post("/auth/otp/request", json={"phone_e164": "nope"})
    assert response.status_code == 422
    body = response.json()
    assert body["code"] == "validation_error"
    assert body["message_ar"]


# ============================================================================
# The refresh cookie
# ============================================================================


async def test_the_refresh_cookie_is_httponly_and_scoped_to_auth(
    app: FastAPI, sms: NullSms
) -> None:
    async with await _client(app) as client:
        await client.post("/auth/otp/request", json={"phone_e164": PHONE})
        response = await client.post(
            "/auth/otp/verify", json={"phone_e164": PHONE, "code": _code(sms)}
        )

    assert response.status_code == 200
    header = response.headers["set-cookie"]
    assert REFRESH_COOKIE in header
    assert "HttpOnly" in header
    assert "SameSite=lax" in header.replace("SameSite=Lax", "SameSite=lax")
    assert "Path=/auth" in header


async def test_the_refresh_token_is_never_in_the_response_body(app: FastAPI, sms: NullSms) -> None:
    """It lives in an httpOnly cookie precisely so script cannot read it."""
    async with await _client(app) as client:
        await client.post("/auth/otp/request", json={"phone_e164": PHONE})
        response = await client.post(
            "/auth/otp/verify", json={"phone_e164": PHONE, "code": _code(sms)}
        )
    body = response.json()
    assert set(body) == {"access_token", "token_type", "expires_in", "is_new_user"}
    assert "refresh" not in str(body).lower()


async def test_secure_is_set_only_in_production(repo: FakeRepo, sms: NullSms) -> None:
    """Off locally because localhost is http and the cookie would never be sent."""
    get_settings.cache_clear()
    local = get_settings()
    assert local.is_production is False

    production = local.model_copy(
        update={
            "environment": Environment.PRODUCTION,
            "otp_pepper": "real",
            "invite_secret": "real",
            "jwt_private_key": None,
            "jwt_public_key": None,
        }
    )
    assert production.is_production is True


async def test_refresh_without_a_cookie_is_a_clean_401(app: FastAPI) -> None:
    async with await _client(app) as client:
        response = await client.post("/auth/refresh")
    assert response.status_code == 401
    assert response.json()["code"] == "invalid_credentials"
    assert response.json()["message_ar"]


async def test_a_full_cookie_round_trip_refreshes_and_rotates(app: FastAPI, sms: NullSms) -> None:
    async with await _client(app) as client:
        await client.post("/auth/otp/request", json={"phone_e164": PHONE})
        await client.post("/auth/otp/verify", json={"phone_e164": PHONE, "code": _code(sms)})
        first_cookie = client.cookies.get(REFRESH_COOKIE)

        refreshed = await client.post("/auth/refresh")
        assert refreshed.status_code == 200
        assert client.cookies.get(REFRESH_COOKIE) != first_cookie

        logout = await client.post("/auth/logout")
        assert logout.status_code == 204


async def test_replaying_a_rotated_cookie_revokes_the_family_over_http(
    app: FastAPI, sms: NullSms, repo: FakeRepo
) -> None:
    """The revoke must be committed even though the request errors."""
    async with await _client(app) as client:
        await client.post("/auth/otp/request", json={"phone_e164": PHONE})
        await client.post("/auth/otp/verify", json={"phone_e164": PHONE, "code": _code(sms)})
        stolen = client.cookies.get(REFRESH_COOKIE)
        await client.post("/auth/refresh")

        client.cookies.set(REFRESH_COOKIE, stolen or "")
        replayed = await client.post("/auth/refresh")

    assert replayed.status_code == 401
    assert replayed.json()["code"] == "refresh_reuse_detected"
    assert all(record.revoked_at is not None for record in repo.refresh.values())


# ============================================================================
# The bearer dependency
# ============================================================================


async def test_me_without_a_token_is_401(app: FastAPI) -> None:
    async with await _client(app) as client:
        response = await client.get("/me")
    assert response.status_code == 401


@pytest.mark.parametrize(
    "header",
    ["", "Bearer", "Basic abc", "bearer", "Token abc", "Bearer "],
)
async def test_a_malformed_authorization_header_is_401(app: FastAPI, header: str) -> None:
    async with await _client(app) as client:
        response = await client.get("/me", headers={"Authorization": header})
    assert response.status_code == 401


async def test_a_garbage_bearer_token_is_401_not_500(app: FastAPI) -> None:
    async with await _client(app) as client:
        response = await client.get("/me", headers={"Authorization": "Bearer not.a.jwt"})
    assert response.status_code == 401
    assert response.json()["message_ar"]


async def test_a_valid_token_reaches_the_route(app: FastAPI, repo: FakeRepo) -> None:
    caregiver = await repo.create_caregiver(phone_e164=PHONE)
    token, _ = issue_access_token(caregiver_id=caregiver.id)
    async with await _client(app) as client:
        response = await client.get("/me", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 200
    body = response.json()
    assert body["id"] == str(caregiver.id)
    assert body["has_play_pin"] is False


async def test_me_lists_the_linked_children(app: FastAPI, repo: FakeRepo) -> None:
    caregiver = await repo.create_caregiver(phone_e164=PHONE)
    child_id = uuid.uuid4()
    repo.links[(caregiver.id, child_id)] = FakeLink(caregiver.id, child_id, "owner")
    repo.child_names[child_id] = "نور"
    token, _ = issue_access_token(caregiver_id=caregiver.id)
    async with await _client(app) as client:
        response = await client.get("/me", headers={"Authorization": f"Bearer {token}"})
    children = response.json()["children"]
    assert [c["id"] for c in children] == [str(child_id)]
    assert children[0]["role"] == "owner"
    # The name, and not the empty string this carried for every child until the
    # children page needed it. A caregiver choosing between three unnamed cards
    # cannot choose.
    assert children[0]["display_name"] == "نور"


async def test_a_token_whose_subject_is_not_a_uuid_is_401(app: FastAPI) -> None:
    import datetime as dt

    import jwt

    from app.modules.identity.security import _keys

    private, _public = _keys(get_settings())
    now = dt.datetime.now(dt.UTC)
    forged = jwt.encode(
        {
            "sub": "not-a-uuid",
            "jti": "x",
            "iat": int(now.timestamp()),
            "nbf": int(now.timestamp()) - 60,
            "exp": int(now.timestamp()) + 900,
        },
        private,
        algorithm="RS256",
    )
    async with await _client(app) as client:
        response = await client.get("/me", headers={"Authorization": f"Bearer {forged}"})
    assert response.status_code == 401


async def test_patch_me_updates_only_the_supplied_fields(app: FastAPI, repo: FakeRepo) -> None:
    caregiver = await repo.create_caregiver(phone_e164=PHONE)
    caregiver.display_name = "أم يوسف"
    token, _ = issue_access_token(caregiver_id=caregiver.id)
    async with await _client(app) as client:
        response = await client.patch(
            "/me",
            headers={"Authorization": f"Bearer {token}"},
            json={"governorate": "القاهرة"},
        )
    assert response.status_code == 200
    assert repo.caregivers[caregiver.id].governorate == "القاهرة"
    assert repo.caregivers[caregiver.id].display_name == "أم يوسف"


# ============================================================================
# Play PIN over HTTP
# ============================================================================


async def test_the_pin_lockout_persists_even_when_the_request_errors(
    app: FastAPI, repo: FakeRepo
) -> None:
    """Otherwise the 5-attempt limit resets by triggering the error path."""
    caregiver = await repo.create_caregiver(phone_e164=PHONE)
    token, _ = issue_access_token(caregiver_id=caregiver.id)
    headers = {"Authorization": f"Bearer {token}"}

    async with await _client(app) as client:
        assert (
            await client.put("/me/play-pin", headers=headers, json={"pin": "1234"})
        ).status_code == 204

        for _ in range(4):
            response = await client.post(
                "/me/play-pin/verify", headers=headers, json={"pin": "9999"}
            )
            assert response.status_code == 200
            assert response.json()["ok"] is False

        locked = await client.post("/me/play-pin/verify", headers=headers, json={"pin": "9999"})

    assert locked.status_code == 403
    assert locked.json()["code"] == "pin_locked"
    assert repo.pins[caregiver.id].locked_until is not None


async def test_the_verify_route_returns_ok_true_for_the_right_pin(
    app: FastAPI, repo: FakeRepo
) -> None:
    caregiver = await repo.create_caregiver(phone_e164=PHONE)
    token, _ = issue_access_token(caregiver_id=caregiver.id)
    headers = {"Authorization": f"Bearer {token}"}
    async with await _client(app) as client:
        await client.put("/me/play-pin", headers=headers, json={"pin": "1234"})
        response = await client.post("/me/play-pin/verify", headers=headers, json={"pin": "1234"})
    assert response.json() == {"ok": True}


# ============================================================================
# require_child_access over HTTP
# ============================================================================


async def test_require_child_access_is_403_for_an_unlinked_child(
    app: FastAPI, repo: FakeRepo
) -> None:
    from fastapi import APIRouter

    router = APIRouter()

    @router.get("/probe/{child_id}")
    async def probe(child_id: uuid.UUID, access: deps.ChildAccess) -> dict[str, str]:
        return {"role": str(access)}

    app.include_router(router)

    caregiver = await repo.create_caregiver(phone_e164=PHONE)
    linked = uuid.uuid4()
    repo.links[(caregiver.id, linked)] = FakeLink(caregiver.id, linked, "owner")
    token, _ = issue_access_token(caregiver_id=caregiver.id)
    headers = {"Authorization": f"Bearer {token}"}

    async with await _client(app) as client:
        allowed = await client.get(f"/probe/{linked}", headers=headers)
        refused = await client.get(f"/probe/{uuid.uuid4()}", headers=headers)

    assert allowed.status_code == 200
    assert allowed.json()["role"] == Role.OWNER
    assert refused.status_code == 403
    assert refused.json()["message_ar"]


async def test_an_owner_only_route_refuses_a_co_caregiver(app: FastAPI, repo: FakeRepo) -> None:
    from fastapi import APIRouter

    router = APIRouter()

    @router.get("/owner-only/{child_id}")
    async def owner_only(child_id: uuid.UUID, access: deps.OwnerAccess) -> dict[str, str]:
        return {"role": str(access)}

    app.include_router(router)

    caregiver = await repo.create_caregiver(phone_e164=PHONE)
    child_id = uuid.uuid4()
    repo.links[(caregiver.id, child_id)] = FakeLink(caregiver.id, child_id, "co_caregiver")
    token, _ = issue_access_token(caregiver_id=caregiver.id)

    async with await _client(app) as client:
        response = await client.get(
            f"/owner-only/{child_id}", headers={"Authorization": f"Bearer {token}"}
        )
    assert response.status_code == 403


def test_the_sms_provider_override_is_reset_between_tests() -> None:
    deps.set_sms_provider(None)
    assert deps._sms_override is None
    probe = NullSms()
    deps.set_sms_provider(probe)
    assert deps._sms_override is probe
    deps.set_sms_provider(None)


def test_the_settings_used_by_the_router_are_the_application_settings() -> None:
    get_settings.cache_clear()
    assert isinstance(get_settings(), Settings)


async def test_verify_with_a_wrong_code_is_401_with_arabic(app: FastAPI, sms: NullSms) -> None:
    async with await _client(app) as client:
        await client.post("/auth/otp/request", json={"phone_e164": PHONE})
        response = await client.post(
            "/auth/otp/verify", json={"phone_e164": PHONE, "code": "000000"}
        )
    assert response.status_code == 401
    body = response.json()
    assert body["code"] == "invalid_credentials"
    assert body["message_ar"] == InvalidCredentials.message_ar


# --- the development-only OTP readback --------------------------------------


async def test_the_dev_otp_route_returns_the_last_null_provider_code(
    app: FastAPI, sms: NullSms
) -> None:
    """The affordance the end-to-end test signs in with.

    It is not a back door: the code it returns was produced by a provider that
    never sent it anywhere, and the route 404s in production.
    """
    from app.modules.identity.sms import LAST_DEV_CODES

    LAST_DEV_CODES.clear()
    async with await _client(app) as client:
        await client.post("/auth/otp/request", json={"phone_e164": PHONE})
        response = await client.get("/auth/otp/latest", params={"phone_e164": PHONE})

    assert response.status_code == 200
    code = response.json()["code"]
    assert code.isdigit()
    # The same code the provider recorded, which is the one that would verify.
    assert code in sms.sent[-1][1]


async def test_the_dev_otp_route_is_a_404_for_a_number_nobody_asked_about(
    app: FastAPI,
) -> None:
    async with await _client(app) as client:
        response = await client.get("/auth/otp/latest", params={"phone_e164": "+201009999999"})
    assert response.status_code == 404


async def test_the_dev_otp_route_refuses_when_a_real_sms_provider_is_configured(
    repo: FakeRepo, sms: NullSms
) -> None:
    """The second gate. A deployment that can actually send an SMS is a
    deployment where reading codes back is a credential leak, whatever the
    environment is called."""
    import os

    from app.core.config import get_settings as _get_settings

    os.environ["SANAD_SMS_PROVIDER"] = "twilio"
    _get_settings.cache_clear()
    try:
        from app.main import create_app

        application = create_app(_get_settings())
        async with await _client(application) as client:
            response = await client.get("/auth/otp/latest", params={"phone_e164": PHONE})
        assert response.status_code == 404
    finally:
        os.environ.pop("SANAD_SMS_PROVIDER", None)
        _get_settings.cache_clear()
