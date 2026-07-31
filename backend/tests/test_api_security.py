import asyncio
import json
import logging
from collections.abc import AsyncIterator
from importlib.util import find_spec

import pytest
from app.api_errors import (
    PublicExceptionMiddleware,
    public_exception_response,
    validation_exception_response,
)
from app.config import _cors_origins_from_env
from app.main import app
from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.testclient import TestClient
from pydantic import BaseModel, model_validator
from starlette.background import BackgroundTask


class SecretBearingProbe(BaseModel):
    value: str

    @model_validator(mode="after")
    def reject(self) -> "SecretBearingProbe":
        raise ValueError(f"invalid submitted value {self.value}")


class SecretKeyProbe(BaseModel):
    values: dict[str, int]


class SecretFieldProbe(BaseModel):
    attacker_named_field: int


class ServerLoggingProbe:
    """Represent the server boundary that logs escaped ASGI exceptions."""

    def __init__(self, application):
        self.application = application
        self.escaped_exception_types: list[str] = []
        self.response_complete = False

    async def __call__(self, scope, receive, send) -> None:
        response_started = False

        async def tracked_send(message) -> None:
            nonlocal response_started
            await send(message)
            if message["type"] == "http.response.start":
                response_started = True
            elif (
                message["type"] == "http.response.body"
                and not message.get("more_body", False)
            ):
                self.response_complete = True

        try:
            await self.application(scope, receive, tracked_send)
            if (
                scope["type"] == "http"
                and response_started
                and not self.response_complete
            ):
                raise AssertionError("ASGI response did not complete")
        except Exception as exc:
            if scope["type"] == "http":
                self.escaped_exception_types.append(type(exc).__name__)
                logging.getLogger("uvicorn.error").exception(
                    "Exception in ASGI application"
                )
            raise


def test_public_openapi_has_no_ingest_or_drift_paths() -> None:
    paths = app.openapi()["paths"]
    assert all("ingest" not in path and "drift" not in path for path in paths)


def test_unverified_mutation_modules_are_retired() -> None:
    retired = (
        "app.ingest",
        "app.ingest_nged",
        "app.ingest_spen",
        "app.ingest_enwl",
        "app.ingest_ssen",
        "app.drift",
    )
    assert all(find_spec(name) is None for name in retired)


def test_browser_mutation_routes_are_absent_without_dispatch() -> None:
    paths = app.openapi()["paths"]
    assert "/api/ingest" not in paths
    assert "/api/drift/check" not in paths


def test_default_cors_is_local_and_never_wildcard() -> None:
    assert _cors_origins_from_env(None) == (
        "http://127.0.0.1:3000",
        "http://localhost:3000",
    )
    with pytest.raises(ValueError, match="wildcard"):
        _cors_origins_from_env("*")


def test_cors_origins_are_normalised_and_deduplicated() -> None:
    assert _cors_origins_from_env(
        " HTTPS://EXAMPLE.TEST:443/,http://LOCALHOST:80,"
        "https://BÜCHER.example,http://[2001:0DB8::1]:80,"
        "http://example.test:8080,https://example.test"
    ) == (
        "https://example.test",
        "http://localhost",
        "https://xn--bcher-kva.example",
        "http://[2001:db8::1]",
        "http://example.test:8080",
    )


def test_cors_uses_non_transitional_uts46_for_deviation_characters() -> None:
    assert _cors_origins_from_env(
        "https://fa\u00df.de,https://fass.de,"
        "https://\u03c2.example,https://\u03c3.example"
    ) == (
        "https://xn--fa-hia.de",
        "https://fass.de",
        "https://xn--3xa.example",
        "https://xn--4xa.example",
    )


@pytest.mark.parametrize(
    "value",
    [
        "file:///tmp/socket",
        "https://user@example.test",
        "https://example.test/path",
        "https://example.test?token=secret",
        "https://example.test#fragment",
        "https://@example.test",
        "https://example.test:not-a-port",
        "https://example.test:70000",
        "https://*",
        "https://bad_host.example",
        "https://-bad.example",
        "https://example..test",
        "https://999.999.999.999",
        "http://[fe80::1%25eth0]",
        "https://exa\nmple.test",
        "example.test",
    ],
)
def test_cors_rejects_values_that_are_not_origins(value: str) -> None:
    with pytest.raises(ValueError, match=r"absolute HTTP\(S\) origins"):
        _cors_origins_from_env(value)


def test_cors_middleware_is_origin_only_without_credentials(client) -> None:
    allowed = client.options(
        "/api/health",
        headers={
            "Origin": "http://localhost:3000",
            "Access-Control-Request-Method": "GET",
        },
    )
    assert allowed.status_code == 200
    assert allowed.headers["access-control-allow-origin"] == (
        "http://localhost:3000"
    )
    assert "access-control-allow-credentials" not in allowed.headers

    rejected = client.get(
        "/api/health",
        headers={"Origin": "https://attacker.example"},
    )
    assert "access-control-allow-origin" not in rejected.headers
    assert "access-control-allow-credentials" not in rejected.headers


def test_public_exception_never_echoes_or_logs_secret(caplog) -> None:
    secret = "https://example.test/?token=do-not-leak"
    request_path = "/request-derived/private/path"
    request = Request(
        {
            "type": "http",
            "method": "GET",
            "scheme": "http",
            "server": ("testserver", 80),
            "path": request_path,
            "raw_path": request_path.encode(),
            "query_string": b"",
            "headers": [],
        }
    )
    with caplog.at_level(logging.ERROR):
        response = public_exception_response(request, RuntimeError(secret))
    body = response.body.decode()
    assert secret not in body
    assert secret not in caplog.text
    assert request_path not in body
    assert request_path not in caplog.text
    assert json.loads(body) == {
        "detail": "Internal server error",
        "code": "internal_error",
    }


def test_unhandled_exception_never_reaches_server_logging(caplog) -> None:
    secret = "https://example.test/?token=server-log-secret"
    original_routes = list(app.router.routes)
    original_openapi = app.openapi_schema

    def secret_probe() -> None:
        raise RuntimeError(secret)

    app.add_api_route("/_test/unhandled", secret_probe)
    app.openapi_schema = None
    server_probe = ServerLoggingProbe(app)
    try:
        with caplog.at_level(logging.ERROR):
            response = TestClient(
                server_probe,
                raise_server_exceptions=False,
            ).get("/_test/unhandled")
    finally:
        app.router.routes[:] = original_routes
        app.openapi_schema = original_openapi

    assert response.status_code == 500
    assert response.json() == {
        "detail": "Internal server error",
        "code": "internal_error",
    }
    assert secret not in response.text
    assert secret not in caplog.text
    assert server_probe.escaped_exception_types == []


def test_streaming_exception_safely_finishes_started_body(caplog) -> None:
    secret = "stream-secret-must-not-reach-server-log"
    original_routes = list(app.router.routes)
    original_openapi = app.openapi_schema

    async def secret_stream() -> AsyncIterator[bytes]:
        yield b"visible-prefix"
        raise RuntimeError(secret)

    def stream_probe() -> StreamingResponse:
        return StreamingResponse(secret_stream(), media_type="text/plain")

    app.add_api_route("/_test/streaming", stream_probe)
    app.openapi_schema = None
    server_probe = ServerLoggingProbe(app)
    try:
        with caplog.at_level(logging.ERROR):
            response = TestClient(
                server_probe,
                raise_server_exceptions=False,
            ).get("/_test/streaming")
    finally:
        app.router.routes[:] = original_routes
        app.openapi_schema = original_openapi

    assert response.status_code == 200
    assert response.content == b"visible-prefix"
    assert secret not in response.text
    assert secret not in caplog.text
    assert server_probe.escaped_exception_types == []


def test_streaming_exception_before_first_chunk_completes_response(
    caplog,
) -> None:
    secret = "pre-yield-stream-secret-must-not-reach-server-log"
    original_routes = list(app.router.routes)
    original_openapi = app.openapi_schema

    async def secret_stream() -> AsyncIterator[bytes]:
        raise RuntimeError(secret)
        yield b"unreachable"

    def stream_probe() -> StreamingResponse:
        return StreamingResponse(secret_stream(), media_type="text/plain")

    app.add_api_route("/_test/streaming-before-yield", stream_probe)
    app.openapi_schema = None
    server_probe = ServerLoggingProbe(app)
    try:
        with caplog.at_level(logging.ERROR):
            response = TestClient(
                server_probe,
                raise_server_exceptions=False,
            ).get("/_test/streaming-before-yield")
    finally:
        app.router.routes[:] = original_routes
        app.openapi_schema = original_openapi

    assert response.status_code == 200
    assert response.content == b""
    assert secret not in response.text
    assert secret not in caplog.text
    assert server_probe.response_complete is True
    assert server_probe.escaped_exception_types == []


def test_background_exception_after_complete_response_does_not_escape(
    caplog,
) -> None:
    secret = "background-secret-must-not-reach-server-log"
    original_routes = list(app.router.routes)
    original_openapi = app.openapi_schema

    def background_failure() -> None:
        raise RuntimeError(secret)

    def background_probe() -> JSONResponse:
        return JSONResponse(
            {"status": "sent"},
            background=BackgroundTask(background_failure),
        )

    app.add_api_route("/_test/background", background_probe)
    app.openapi_schema = None
    server_probe = ServerLoggingProbe(app)
    try:
        with caplog.at_level(logging.ERROR):
            response = TestClient(
                server_probe,
                raise_server_exceptions=False,
            ).get("/_test/background")
    finally:
        app.router.routes[:] = original_routes
        app.openapi_schema = original_openapi

    assert response.status_code == 200
    assert response.json() == {"status": "sent"}
    assert secret not in response.text
    assert secret not in caplog.text
    assert server_probe.escaped_exception_types == []


def _http_scope(path: str) -> dict[str, object]:
    return {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "GET",
        "scheme": "http",
        "path": path,
        "raw_path": path.encode(),
        "query_string": b"",
        "headers": [],
        "server": ("testserver", 80),
        "client": ("testclient", 50000),
    }


async def _receive_disconnect() -> dict[str, str]:
    return {"type": "http.disconnect"}


def test_safe_500_send_failure_is_type_only_logged_and_swallowed(caplog) -> None:
    original_secret = "original-before-start-secret"
    recovery_secret = "safe-500-send-secret"

    class OriginalSecretError(Exception):
        pass

    class RecoverySecretError(Exception):
        pass

    async def failing_app(scope, receive, send) -> None:
        raise OriginalSecretError(original_secret)

    async def failing_send(message) -> None:
        raise RecoverySecretError(recovery_secret)

    middleware = PublicExceptionMiddleware(failing_app)
    with caplog.at_level(logging.ERROR):
        asyncio.run(
            middleware(
                _http_scope("/_test/recovery-before-start"),
                _receive_disconnect,
                failing_send,
            )
        )

    assert "OriginalSecretError" in caplog.text
    assert "RecoverySecretError" in caplog.text
    assert original_secret not in caplog.text
    assert recovery_secret not in caplog.text
    assert [record.getMessage() for record in caplog.records] == [
        "Unhandled API exception type=OriginalSecretError",
        "Unhandled API exception type=RecoverySecretError",
    ]


def test_terminal_body_send_failure_is_type_only_logged_and_swallowed(
    caplog,
) -> None:
    original_secret = "original-after-start-secret"
    recovery_secret = "terminal-body-send-secret"
    attempted_message_types: list[str] = []

    class OriginalSecretError(Exception):
        pass

    class RecoverySecretError(Exception):
        pass

    async def failing_app(scope, receive, send) -> None:
        await send(
            {
                "type": "http.response.start",
                "status": 200,
                "headers": [],
            }
        )
        raise OriginalSecretError(original_secret)

    async def failing_terminal_send(message) -> None:
        attempted_message_types.append(message["type"])
        if message["type"] == "http.response.body":
            raise RecoverySecretError(recovery_secret)

    middleware = PublicExceptionMiddleware(failing_app)
    with caplog.at_level(logging.ERROR):
        asyncio.run(
            middleware(
                _http_scope("/_test/recovery-after-start"),
                _receive_disconnect,
                failing_terminal_send,
            )
        )

    assert attempted_message_types == [
        "http.response.start",
        "http.response.body",
    ]
    assert "OriginalSecretError" in caplog.text
    assert "RecoverySecretError" in caplog.text
    assert original_secret not in caplog.text
    assert recovery_secret not in caplog.text
    assert [record.getMessage() for record in caplog.records] == [
        "Unhandled API exception type=OriginalSecretError",
        "Unhandled API exception type=RecoverySecretError",
    ]


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        (
            "/_test/http-exception",
            {"detail": "Request failed", "code": "http_error"},
        ),
        (
            "/api/demo/analyse",
            {
                "detail": "Request failed",
                "code": "http_error",
                "workflow_kind": "synthetic_demo",
                "portal_data_used": False,
            },
        ),
    ],
)
def test_http_exception_never_echoes_detail_or_headers(
    path: str,
    expected: dict[str, object],
) -> None:
    secret = "secret-from-request"
    original_routes = list(app.router.routes)
    original_openapi = app.openapi_schema

    def secret_probe() -> None:
        raise HTTPException(
            status_code=400,
            detail=secret,
            headers={"X-Secret": secret, "WWW-Authenticate": secret},
        )

    app.add_api_route(path, secret_probe)
    app.openapi_schema = None
    try:
        response = TestClient(app).get(path)
    finally:
        app.router.routes[:] = original_routes
        app.openapi_schema = original_openapi

    assert response.status_code == 400
    assert response.json() == expected
    assert secret not in response.text
    assert "x-secret" not in response.headers
    assert "www-authenticate" not in response.headers


def test_validation_handler_never_echoes_custom_secret() -> None:
    secret = "do-not-echo-validator-input"
    test_app = FastAPI()
    test_app.add_exception_handler(
        RequestValidationError,
        validation_exception_response,
    )

    @test_app.post("/probe")
    def probe(payload: SecretBearingProbe) -> None:
        return None

    client = TestClient(test_app, raise_server_exceptions=False)
    response = client.post("/probe", json={"value": secret})
    assert response.status_code == 422
    assert secret not in response.text
    assert response.json()["errors"][0]["loc"] == ["body"]


def test_validation_handler_never_echoes_attacker_controlled_location() -> None:
    secret_key = "attacker-controlled-secret-key"
    test_app = FastAPI()
    test_app.add_exception_handler(
        RequestValidationError,
        validation_exception_response,
    )

    @test_app.post("/probe")
    def probe(payload: SecretKeyProbe) -> None:
        return None

    response = TestClient(
        test_app,
        raise_server_exceptions=False,
    ).post("/probe", json={"values": {secret_key: "not-an-int"}})
    assert response.status_code == 422
    assert secret_key not in response.text
    assert response.json()["errors"][0]["loc"] == ["body"]


def test_validation_handler_never_echoes_custom_field_name() -> None:
    secret_field = "attacker_named_field"
    test_app = FastAPI()
    test_app.add_exception_handler(
        RequestValidationError,
        validation_exception_response,
    )

    @test_app.post("/probe")
    def probe(payload: SecretFieldProbe) -> None:
        return None

    response = TestClient(
        test_app,
        raise_server_exceptions=False,
    ).post("/probe", json={secret_field: "not-an-int"})
    assert response.status_code == 422
    assert secret_field not in response.text
    assert response.json()["errors"][0]["loc"] == ["body"]


def test_validation_handler_uses_request_for_unknown_error_roots() -> None:
    request = Request(
        {
            "type": "http",
            "method": "GET",
            "scheme": "http",
            "server": ("testserver", 80),
            "path": "/probe",
            "raw_path": b"/probe",
            "query_string": b"",
            "headers": [],
        }
    )
    exc = RequestValidationError(
        [
            {
                "type": "invalid",
                "loc": ("attacker-root", "secret-segment"),
                "msg": "private-message",
                "input": "private-value",
            }
        ]
    )
    response = validation_exception_response(request, exc)
    assert json.loads(response.body) == {
        "detail": "Request validation failed",
        "code": "validation_error",
        "errors": [
            {
                "loc": ["request"],
                "code": "invalid",
                "message": "Invalid value",
            }
        ],
    }
