import json
import logging
from importlib.util import find_spec

import pytest
from app.api_errors import (
    public_exception_response,
    validation_exception_response,
)
from app.config import _cors_origins_from_env
from app.main import app
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.testclient import TestClient
from pydantic import BaseModel, model_validator


class SecretBearingProbe(BaseModel):
    value: str

    @model_validator(mode="after")
    def reject(self) -> "SecretBearingProbe":
        raise ValueError(f"invalid submitted value {self.value}")


class SecretKeyProbe(BaseModel):
    values: dict[str, int]


class SecretFieldProbe(BaseModel):
    attacker_named_field: int


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
        " https://example.test/,http://localhost:8000,"
        "https://example.test"
    ) == ("https://example.test", "http://localhost:8000")


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
