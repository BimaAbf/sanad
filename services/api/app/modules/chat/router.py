"""Chat routes.

Every route that touches a child's transcript carries `{child_id}` and declares
`ChildAccess`, which `tools/guards/route_authorisation.py` checks mechanically.

`/chat/speech/capabilities` deliberately has no `{child_id}`: it reports whether
a server-side recogniser or synthesiser is configured in this deployment, which
is a property of the deployment and not of any child. Putting a child id on it
would imply the answer could differ per child, and a client would start caching
it per child for no reason.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_session
from app.core.errors import ProblemDetail, ServiceUnavailable
from app.modules.chat.domain import Surface
from app.modules.chat.schemas import (
    CaregiverAskRequest,
    CaregiverAskResponse,
    ChatHistoryResponse,
    ChatMessageOut,
    ChildSayRequest,
    ChildSayResponse,
    SpeechCapabilitiesResponse,
    SpeechCapabilityOut,
)
from app.modules.chat.service import ChatService
from app.modules.identity.deps import ChildAccess, CurrentCaregiver

router = APIRouter(prefix="/chat", tags=["chat"])

ChatServiceFactory = Callable[[AsyncSession], ChatService]

_service_factory: ChatServiceFactory | None = None


class SpeechNotImplemented(ProblemDetail):
    """501, not 500 and not 503.

    503 says "try again later", which is wrong -- no amount of retrying makes an
    unconfigured provider appear. 501 says the server does not implement this,
    which is exactly true and is what the client feature-detects on before
    falling back to the browser.
    """

    status = 501
    code = "speech_not_implemented"
    title = "Speech Not Implemented"
    message_ar = "الخدمة دي مش مفعّلة على السيرفر. المتصفح هيقوم بيها."


def set_chat_service_factory(factory: ChatServiceFactory | None) -> None:
    global _service_factory
    _service_factory = factory


async def get_chat_service(
    session: Annotated[AsyncSession, Depends(get_session)],
) -> AsyncIterator[ChatService]:
    if _service_factory is None:
        raise ServiceUnavailable(detail="Chat service is not configured.")
    yield _service_factory(session)


ChatServiceDep = Annotated[ChatService, Depends(get_chat_service)]


@router.post("/children/{child_id}/ask", response_model=CaregiverAskResponse)
async def ask(
    child_id: UUID,
    body: CaregiverAskRequest,
    caregiver_id: CurrentCaregiver,
    _access: ChildAccess,
    service: ChatServiceDep,
) -> CaregiverAskResponse:
    """One caregiver turn, grounded in this child's retrieved history.

    403 when `ai_processing` consent is missing, raised by the service before
    anything is assembled. Not a soft failure: there is no deterministic answer
    to fall back to here, and a canned sentence would read as an answer.
    """
    turn = await service.ask_caregiver(
        child_id=str(child_id), caregiver_id=str(caregiver_id), message=body.message
    )
    return CaregiverAskResponse(
        text_ar=turn.text_ar,
        outcome=turn.outcome.value,
        grounded_in=list(turn.grounded_in),
    )


@router.post("/children/{child_id}/say", response_model=ChildSayResponse)
async def say(
    child_id: UUID,
    body: ChildSayRequest,
    caregiver_id: CurrentCaregiver,
    _access: ChildAccess,
    service: ChatServiceDep,
) -> ChildSayResponse:
    """One child turn. Returns one of the seven reviewed phrases, always."""
    turn = await service.ask_child(
        child_id=str(child_id), caregiver_id=str(caregiver_id), heard=body.heard
    )
    return ChildSayResponse(
        text_ar=turn.text_ar,
        outcome=turn.outcome.value,
        phrase_id=turn.phrase_id,
        audio_key=turn.audio_key,
    )


@router.get("/children/{child_id}/history", response_model=ChatHistoryResponse)
async def history(
    child_id: UUID,
    _access: ChildAccess,
    service: ChatServiceDep,
    surface: Surface = Surface.CAREGIVER,
    limit: int = 20,
) -> ChatHistoryResponse:
    messages = await service.history(str(child_id), surface, limit=min(max(limit, 1), 100))
    return ChatHistoryResponse(
        surface=surface.value,
        messages=[
            ChatMessageOut(
                role=message.role.value,
                text_ar=message.text_ar,
                at=message.created_at.isoformat() if message.created_at else "",
                outcome=message.outcome.value,
            )
            for message in messages
        ],
    )


@router.get("/speech/capabilities", response_model=SpeechCapabilitiesResponse)
async def speech_capabilities(service: ChatServiceDep) -> SpeechCapabilitiesResponse:
    """What this deployment can do server-side. Both are false today.

    The client reads `client_fallback` rather than assuming what to do, so
    turning on a server provider later does not need a matching client release.
    """
    return SpeechCapabilitiesResponse(
        tts=_capability(service.tts.capability()),
        stt=_capability(service.stt.capability()),
    )


def _capability(capability: Any) -> SpeechCapabilityOut:
    return SpeechCapabilityOut(
        supported=capability.supported,
        provider=capability.provider,
        client_fallback=capability.client_fallback,
        detail_ar=capability.detail_ar,
    )


__all__ = ["SpeechNotImplemented", "router", "set_chat_service_factory"]
