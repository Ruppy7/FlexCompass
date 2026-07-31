"""Public-safe API exception responses."""

from __future__ import annotations

import logging

from fastapi import Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.types import ASGIApp, Message, Receive, Scope, Send

logger = logging.getLogger(__name__)
DEMO_PATHS = {
    "/api/demo/portfolios",
    "/api/demo/analyse",
    "/api/demo/report",
    "/api/demo/asset-groups/generate",
}


class PublicExceptionMiddleware:
    """Keep unhandled application exceptions inside the public boundary."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(
        self,
        scope: Scope,
        receive: Receive,
        send: Send,
    ) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        response_started = False
        response_complete = False

        async def tracked_send(message: Message) -> None:
            nonlocal response_started, response_complete
            await send(message)
            if message["type"] == "http.response.start":
                response_started = True
            elif message["type"] == "http.response.body":
                if not message.get("more_body", False):
                    response_complete = True

        try:
            await self.app(scope, receive, tracked_send)
        except Exception as exc:
            if not response_started:
                response = public_exception_response(Request(scope), exc)
                try:
                    await response(scope, receive, send)
                except Exception as recovery_exc:
                    _log_exception_type(recovery_exc)
                return

            _log_exception_type(exc)
            if not response_complete:
                try:
                    await send(
                        {
                            "type": "http.response.body",
                            "body": b"",
                            "more_body": False,
                        }
                    )
                except Exception as recovery_exc:
                    _log_exception_type(recovery_exc)


def _public_error_content(
    request: Request | None,
    content: dict[str, object],
) -> dict[str, object]:
    if request is not None and request.url.path in DEMO_PATHS:
        return {
            **content,
            "workflow_kind": "synthetic_demo",
            "portal_data_used": False,
        }
    return content


def public_exception_response(
    request: Request | None,
    exc: Exception,
) -> JSONResponse:
    _log_exception_type(exc)
    return JSONResponse(
        status_code=500,
        content=_public_error_content(
            request,
            {"detail": "Internal server error", "code": "internal_error"},
        ),
    )


def _log_exception_type(exc: Exception) -> None:
    logger.error("Unhandled API exception type=%s", type(exc).__name__)


def http_exception_response(
    request: Request,
    exc: StarletteHTTPException,
) -> JSONResponse:
    return JSONResponse(
        status_code=exc.status_code,
        content=_public_error_content(
            request,
            {"detail": "Request failed", "code": "http_error"},
        ),
    )


def validation_exception_response(
    request: Request,
    exc: RequestValidationError,
) -> JSONResponse:
    safe_roots = {"body", "query", "path", "header", "cookie"}
    errors = [
        {
            "loc": [
                item["loc"][0]
                if item["loc"] and item["loc"][0] in safe_roots
                else "request"
            ],
            "code": item["type"],
            "message": "Invalid value",
        }
        for item in exc.errors()
    ]
    return JSONResponse(
        status_code=422,
        content=_public_error_content(
            request,
            {
                "detail": "Request validation failed",
                "code": "validation_error",
                "errors": errors,
            },
        ),
    )
