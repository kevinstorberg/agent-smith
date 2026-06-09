import logging
from http import HTTPStatus
from typing import Any
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from starlette.datastructures import Headers, MutableHeaders
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from assets.errors import InvalidStorageKey
from src.security.headers import apply_security_headers
from src.settings import get_settings

REQUEST_ID_HEADER = "X-Request-ID"
MAX_REQUEST_ID_LENGTH = 128

logger = logging.getLogger(__name__)


class ErrorDetail(BaseModel):
    field: str | None = None
    message: str
    type: str


class ErrorBody(BaseModel):
    code: str
    message: str
    details: list[ErrorDetail] = Field(default_factory=list)
    request_id: str


class ErrorEnvelope(BaseModel):
    error: ErrorBody


class APIException(Exception):
    def __init__(
        self,
        *,
        status_code: int,
        code: str,
        message: str,
        details: list[ErrorDetail | dict[str, Any]] | None = None,
        headers: dict[str, str] | None = None,
    ) -> None:
        self.status_code = status_code
        self.code = code
        self.message = message
        self.details = _coerce_details(details or [])
        self.headers = headers
        super().__init__(message)


class RequestIDMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        request_id = normalize_request_id(Headers(scope=scope).get(REQUEST_ID_HEADER))
        scope.setdefault("state", {})["request_id"] = request_id

        async def send_with_request_id(message: Message) -> None:
            if message["type"] == "http.response.start":
                MutableHeaders(scope=message)[REQUEST_ID_HEADER] = request_id
            await send(message)

        await self.app(scope, receive, send_with_request_id)


def register_error_handlers(app: FastAPI) -> None:
    app.add_exception_handler(APIException, api_exception_handler)
    app.add_exception_handler(InvalidStorageKey, invalid_storage_key_handler)
    app.add_exception_handler(StarletteHTTPException, http_exception_handler)
    app.add_exception_handler(RequestValidationError, validation_exception_handler)
    app.add_exception_handler(Exception, unhandled_exception_handler)


def normalize_request_id(value: str | None) -> str:
    if value is None:
        return str(uuid4())

    request_id = value.strip()
    if not request_id or len(request_id) > MAX_REQUEST_ID_LENGTH or "\n" in request_id or "\r" in request_id:
        return str(uuid4())
    return request_id


def request_id_from_request(request: Request) -> str:
    request_id = getattr(request.state, "request_id", None)
    if request_id:
        return request_id

    request_id = normalize_request_id(request.headers.get(REQUEST_ID_HEADER))
    request.state.request_id = request_id
    return request_id


def build_error_response(
    request: Request,
    *,
    status_code: int,
    code: str,
    message: str,
    details: list[ErrorDetail | dict[str, Any]] | None = None,
    headers: dict[str, str] | None = None,
) -> JSONResponse:
    request_id = request_id_from_request(request)
    envelope = ErrorEnvelope(
        error=ErrorBody(
            code=code,
            message=message,
            details=_coerce_details(details or []),
            request_id=request_id,
        )
    )
    response_headers = {REQUEST_ID_HEADER: request_id}
    if headers:
        response_headers.update(headers)

    response = JSONResponse(
        status_code=status_code,
        content=envelope.model_dump(exclude_none=True),
        headers=response_headers,
    )
    _apply_security_headers_from_app_state(request, response)
    return response


async def api_exception_handler(request: Request, exc: APIException) -> JSONResponse:
    return build_error_response(
        request,
        status_code=exc.status_code,
        code=exc.code,
        message=exc.message,
        details=exc.details,
        headers=exc.headers,
    )


async def invalid_storage_key_handler(request: Request, exc: InvalidStorageKey) -> JSONResponse:
    return build_error_response(
        request,
        status_code=400,
        code="invalid_storage_key",
        message=str(exc),
    )


async def http_exception_handler(request: Request, exc: StarletteHTTPException) -> JSONResponse:
    return build_error_response(
        request,
        status_code=exc.status_code,
        code=_http_error_code(exc.status_code),
        message=_http_message(exc),
        details=_http_details(exc.detail),
        headers=exc.headers,
    )


async def validation_exception_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    return build_error_response(
        request,
        status_code=422,
        code="validation_error",
        message="Request validation failed",
        details=normalize_validation_errors(exc.errors()),
    )


async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    request_id = request_id_from_request(request)
    logger.exception("Unhandled API exception", extra={"request_id": request_id})

    details: list[ErrorDetail] = []
    if get_settings().DEBUG_ERRORS:
        details.append(ErrorDetail(message=str(exc), type=exc.__class__.__name__))

    return build_error_response(
        request,
        status_code=500,
        code="internal_server_error",
        message="Internal server error",
        details=details,
    )


def normalize_validation_errors(errors: list[dict[str, Any]]) -> list[ErrorDetail]:
    details: list[ErrorDetail] = []
    for error in errors:
        details.append(
            ErrorDetail(
                field=_format_validation_location(error.get("loc", ())),
                message=str(error.get("msg", "Invalid value")),
                type=str(error.get("type", "validation_error")),
            )
        )
    return details


def _coerce_details(details: list[ErrorDetail | dict[str, Any]]) -> list[ErrorDetail]:
    return [detail if isinstance(detail, ErrorDetail) else ErrorDetail.model_validate(detail) for detail in details]


def _format_validation_location(location: Any) -> str | None:
    if not location:
        return None
    if not isinstance(location, (list, tuple)):
        return str(location)
    return ".".join(str(part) for part in location)


def _http_error_code(status_code: int) -> str:
    return {
        400: "bad_request",
        401: "unauthorized",
        403: "forbidden",
        404: "not_found",
        409: "conflict",
        422: "validation_error",
    }.get(status_code, "http_error")


def _http_message(exc: StarletteHTTPException) -> str:
    if isinstance(exc.detail, str):
        return exc.detail
    try:
        return HTTPStatus(exc.status_code).phrase
    except ValueError:
        return "HTTP error"


def _http_details(detail: Any) -> list[ErrorDetail]:
    if isinstance(detail, str) or detail is None:
        return []
    return [ErrorDetail(message=str(detail), type="http_error")]


def _apply_security_headers_from_app_state(request: Request, response: JSONResponse) -> None:
    config = getattr(request.app.state, "config", None)
    settings = getattr(request.app.state, "settings", None)
    if config is None or settings is None:
        return

    apply_security_headers(
        response.headers,
        headers_config=config.security.headers,
        hsts_enabled=settings.SECURE_HEADERS_HSTS_ENABLED,
    )
