"""Public-safe API exception responses."""

from __future__ import annotations

import logging

from fastapi import Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

logger = logging.getLogger(__name__)
DEMO_PATHS = {
    "/api/demo/portfolios",
    "/api/demo/analyse",
    "/api/demo/report",
    "/api/demo/asset-groups/generate",
}


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
    logger.error("Unhandled API exception type=%s", type(exc).__name__)
    return JSONResponse(
        status_code=500,
        content=_public_error_content(
            request,
            {"detail": "Internal server error", "code": "internal_error"},
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
