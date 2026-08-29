"""RFC 9457 Problem Details.

Two rules this module exists to enforce:

1. Every error response carries ``message_ar`` — Egyptian-colloquial Arabic that
   is *always* safe to render to a caregiver. It never contains an identifier, a
   stack frame, or anything a child's parent should not read.
2. An unhandled exception never leaks. It becomes a 500 Problem Details with a
   generic ``message_ar`` and a correlation id the support team can look up.
"""

from __future__ import annotations

from typing import Any

import structlog
from fastapi import FastAPI, Request, status
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.logging import get_request_id

logger = structlog.get_logger(__name__)

PROBLEM_CONTENT_TYPE = "application/problem+json"
PROBLEM_BASE_URI = "https://sanad.app/problems"

GENERIC_MESSAGE_AR = "حصلت مشكلة مؤقتة. جرّب تاني بعد شوية."


class ProblemDetail(Exception):
    """Base class for every error this API raises deliberately.

    Subclasses set ``status``, ``code`` and ``message_ar``. ``detail`` is for
    developers and appears in the response body; it must never contain PII.
    """

    status: int = status.HTTP_500_INTERNAL_SERVER_ERROR
    code: str = "internal_error"
    title: str = "Internal Server Error"
    message_ar: str = GENERIC_MESSAGE_AR

    def __init__(
        self,
        detail: str | None = None,
        *,
        message_ar: str | None = None,
        extra: dict[str, Any] | None = None,
    ) -> None:
        self.detail = detail or self.title
        if message_ar is not None:
            self.message_ar = message_ar
        self.extra = extra or {}
        super().__init__(self.detail)

    def to_response(self, request: Request) -> JSONResponse:
        body: dict[str, Any] = {
            "type": f"{PROBLEM_BASE_URI}/{self.code}",
            "title": self.title,
            "status": self.status,
            "detail": self.detail,
            "instance": str(request.url.path),
            "code": self.code,
            "message_ar": self.message_ar,
            "request_id": get_request_id(),
        }
        body.update(self.extra)
        return JSONResponse(
            status_code=self.status,
            content=jsonable_encoder(body),
            media_type=PROBLEM_CONTENT_TYPE,
        )


class BadRequest(ProblemDetail):
    status = status.HTTP_400_BAD_REQUEST
    code = "bad_request"
    title = "Bad Request"
    message_ar = "البيانات اللي اتبعتت مش مظبوطة."


class ValidationProblem(ProblemDetail):
    status = 422
    code = "validation_error"
    title = "Validation Error"
    message_ar = "في حاجة ناقصة أو مكتوبة غلط. راجع البيانات من فضلك."


class Unauthorised(ProblemDetail):
    status = status.HTTP_401_UNAUTHORIZED
    code = "unauthorised"
    title = "Unauthorised"
    message_ar = "محتاج تسجّل دخول تاني."


class Forbidden(ProblemDetail):
    status = status.HTTP_403_FORBIDDEN
    code = "forbidden"
    title = "Forbidden"
    message_ar = "معندكش صلاحية للخطوة دي."


class NotFound(ProblemDetail):
    status = status.HTTP_404_NOT_FOUND
    code = "not_found"
    title = "Not Found"
    message_ar = "مش لاقيين الحاجة دي."


class Conflict(ProblemDetail):
    status = status.HTTP_409_CONFLICT
    code = "conflict"
    title = "Conflict"
    message_ar = "الحاجة دي موجودة بالفعل."


class RateLimited(ProblemDetail):
    status = status.HTTP_429_TOO_MANY_REQUESTS
    code = "rate_limited"
    title = "Too Many Requests"
    message_ar = "جرّبت كتير في وقت قصير. استنى شوية وحاول تاني."


class ServiceUnavailable(ProblemDetail):
    status = status.HTTP_503_SERVICE_UNAVAILABLE
    code = "service_unavailable"
    title = "Service Unavailable"
    message_ar = "الخدمة مش متاحة دلوقتي. جرّب كمان شوية."


_STATUS_TITLES: dict[int, tuple[str, str, str]] = {
    400: ("bad_request", "Bad Request", BadRequest.message_ar),
    401: ("unauthorised", "Unauthorised", Unauthorised.message_ar),
    403: ("forbidden", "Forbidden", Forbidden.message_ar),
    404: ("not_found", "Not Found", NotFound.message_ar),
    405: ("method_not_allowed", "Method Not Allowed", BadRequest.message_ar),
    409: ("conflict", "Conflict", Conflict.message_ar),
    422: ("validation_error", "Validation Error", ValidationProblem.message_ar),
    429: ("rate_limited", "Too Many Requests", RateLimited.message_ar),
    503: ("service_unavailable", "Service Unavailable", ServiceUnavailable.message_ar),
}


def install_error_handlers(app: FastAPI) -> None:
    """Register the handlers that guarantee every error is Problem Details."""

    @app.exception_handler(ProblemDetail)
    async def _problem_handler(request: Request, exc: ProblemDetail) -> JSONResponse:
        logger.info("problem_detail", code=exc.code, status=exc.status, path=request.url.path)
        return exc.to_response(request)

    @app.exception_handler(RequestValidationError)
    async def _validation_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
        # Field locations are structural, not user data; the messages are not
        # echoed back, only the field paths.
        fields = [".".join(str(p) for p in err.get("loc", ())) for err in exc.errors()]
        problem = ValidationProblem(
            detail="One or more fields failed validation.",
            extra={"errors": fields},
        )
        return problem.to_response(request)

    @app.exception_handler(StarletteHTTPException)
    async def _http_handler(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        code, title, message_ar = _STATUS_TITLES.get(
            exc.status_code, ("error", "Error", GENERIC_MESSAGE_AR)
        )
        problem = ProblemDetail(detail=str(exc.detail), message_ar=message_ar)
        problem.status = exc.status_code
        problem.code = code
        problem.title = title
        return problem.to_response(request)

    @app.exception_handler(Exception)
    async def _unhandled_handler(request: Request, exc: Exception) -> JSONResponse:
        # exc_info goes to the log; nothing about it goes to the client.
        logger.error(
            "unhandled_exception",
            path=request.url.path,
            method=request.method,
            exc_type=type(exc).__name__,
            exc_info=exc,
        )
        problem = ProblemDetail(
            detail="An unexpected error occurred. It has been logged with this request id."
        )
        return problem.to_response(request)
