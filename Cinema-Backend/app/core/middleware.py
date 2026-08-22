import logging
import time
import uuid
from collections.abc import Awaitable, Callable

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from app.core.logs import request_id_var

logger = logging.getLogger("app.access")

REQUEST_ID_HEADER = "X-Request-ID"

_MAX_REQUEST_ID_LENGTH = 64


class RequestContextMiddleware(BaseHTTPMiddleware):
    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        incoming = request.headers.get(REQUEST_ID_HEADER, "")
        request_id = incoming.strip()[:_MAX_REQUEST_ID_LENGTH] or uuid.uuid4().hex[:12]

        token = request_id_var.set(request_id)
        request.state.request_id = request_id
        started = time.perf_counter()

        try:
            try:
                response = await call_next(request)
            except Exception:
                elapsed_ms = (time.perf_counter() - started) * 1000
                logger.exception(
                    f"{request.method} {request.url.path} -> "
                    f"необработанная ошибка за {elapsed_ms:.1f} мс"
                )
                raise

            response.headers[REQUEST_ID_HEADER] = request_id
            elapsed_ms = (time.perf_counter() - started) * 1000
            logger.info(
                f"{request.method} {request.url.path} -> "
                f"{response.status_code} за {elapsed_ms:.1f} мс"
            )
            return response
        finally:
            request_id_var.reset(token)
