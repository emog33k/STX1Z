import logging
from typing import Any

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.exceptions import (
    AppError,
    AuthenticationError,
    ConflictError,
    NotFoundError,
    PermissionDeniedError,
    ValidationError,
)
from app.core.middleware import REQUEST_ID_HEADER
from app.schemas import ErrorOut

logger = logging.getLogger(__name__)

_STATUS_BY_ERROR: tuple[tuple[type[AppError], int], ...] = (
    (NotFoundError, status.HTTP_404_NOT_FOUND),
    (ValidationError, status.HTTP_422_UNPROCESSABLE_ENTITY),
    (ConflictError, status.HTTP_409_CONFLICT),
    (AuthenticationError, status.HTTP_401_UNAUTHORIZED),
    (PermissionDeniedError, status.HTTP_403_FORBIDDEN),
)

_HTTP_ERROR_CODES = {
    400: "bad_request",
    401: "unauthorized",
    403: "forbidden",
    404: "not_found",
    405: "method_not_allowed",
    409: "conflict",
    422: "validation_error",
}


def _status_for(error: AppError) -> int:
    for error_type, http_status in _STATUS_BY_ERROR:
        if isinstance(error, error_type):
            return http_status
    return status.HTTP_500_INTERNAL_SERVER_ERROR


def _request_id(request: Request) -> str | None:
    return getattr(request.state, "request_id", None)


def _json_error(
    request: Request,
    *,
    http_status: int,
    code: str,
    message: str,
    details: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
) -> JSONResponse:
    request_id = _request_id(request)
    body = ErrorOut.model_validate(
        {
            "error": {"code": code, "message": message, "details": details or {}},
            "request_id": request_id,
        }
    )
    response_headers = dict(headers or {})
    if request_id:
        response_headers[REQUEST_ID_HEADER] = request_id
    return JSONResponse(
        status_code=http_status,
        content=body.model_dump(mode="json"),
        headers=response_headers,
    )


async def handle_app_error(request: Request, exc: AppError) -> JSONResponse:
    http_status = _status_for(exc)
    if http_status >= status.HTTP_500_INTERNAL_SERVER_ERROR:
        logger.exception(f"Доменная ошибка -> 500: {exc!r}")
    else:
        logger.info(f"{request.method} {request.url.path} -> {http_status} ({exc.code})")

    headers = None
    if isinstance(exc, AuthenticationError):
        headers = {"WWW-Authenticate": "tma"}

    return _json_error(
        request,
        http_status=http_status,
        code=exc.code,
        message=exc.message,
        details=exc.details,
        headers=headers,
    )


async def handle_request_validation_error(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    errors = []
    for error in exc.errors():
        location = ".".join(str(part) for part in error.get("loc", ()) if part != "body")
        errors.append(
            {
                "field": location or "body",
                "message": error.get("msg", "неверное значение"),
                "type": error.get("type", "value_error"),
            }
        )
    return _json_error(
        request,
        http_status=status.HTTP_422_UNPROCESSABLE_ENTITY,
        code="validation_error",
        message="Запрос не прошёл валидацию",
        details={"errors": errors},
    )


async def handle_http_exception(
    request: Request, exc: StarletteHTTPException
) -> JSONResponse:
    detail = exc.detail if isinstance(exc.detail, str) else "Ошибка запроса"
    return _json_error(
        request,
        http_status=exc.status_code,
        code=_HTTP_ERROR_CODES.get(exc.status_code, "http_error"),
        message=detail,
        headers=dict(exc.headers or {}),
    )


async def handle_unexpected_error(request: Request, exc: Exception) -> JSONResponse:
    logger.exception(f"Необработанное исключение: {exc!r}")
    return _json_error(
        request,
        http_status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        code="internal_error",
        message="Внутренняя ошибка сервера",
    )


def register_error_handlers(app: FastAPI) -> None:
    app.add_exception_handler(AppError, handle_app_error)
    app.add_exception_handler(RequestValidationError, handle_request_validation_error)
    app.add_exception_handler(StarletteHTTPException, handle_http_exception)
    app.add_exception_handler(Exception, handle_unexpected_error)
