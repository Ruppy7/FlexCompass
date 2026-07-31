"""Exact GET-only collector for the reviewed public SSEN NaFIRS HV source."""

from __future__ import annotations

import hashlib
import http.client
import json
import multiprocessing
import os
import re
import ssl
import struct
import time
import uuid
from collections.abc import Callable
from datetime import datetime, timezone
from multiprocessing.connection import Connection
from pathlib import Path
from typing import Any, Literal, Protocol
from urllib.parse import urlsplit

from pydantic import BaseModel, model_validator

from app.config import config
from app.outage_store import (
    commit_ingestion_run,
    record_failed_ingestion_run,
)
from app.outages import (
    PARSER_VERSION,
    OutageFetchAttemptPublicV1,
    OutageReject,
    SourceResource,
    SourceSnapshot,
    SyncResult,
    source_snapshot_id,
)
from app.ssen_nafirs import (
    SEPD_COLUMNS,
    SEPD_RESOURCE_ID,
    SHEPD_COLUMNS,
    SHEPD_RESOURCE_ID,
    OutageRowError,
    SourceContractError,
    iter_ssen_hv_csv,
)

SOURCE_MAX_RESPONSE_BYTES = 134_217_728
SOURCE_CONNECT_TIMEOUT_SECONDS = 10
SOURCE_READ_TIMEOUT_SECONDS = 60
SOURCE_TOTAL_DEADLINE_SECONDS = 180
PROCESS_CLEANUP_GRACE_SECONDS = 0.25
_REDIRECT_HOST = (
    "83025b28472d6aa2bf5ae59f3724aa78.r2.cloudflarestorage.com"
)
_REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
_SOURCE_MANIFEST_PATH = _REPOSITORY_ROOT / "data/sources/ssen-nafirs-hv.json"
_EXPECTED_RESOURCE_IDS = tuple(sorted((SEPD_RESOURCE_ID, SHEPD_RESOURCE_ID)))
_PROCESS_MESSAGE_SUCCESS = b"O"
_PROCESS_MESSAGE_ERROR = b"E"
_PROCESS_ERROR_REQUEST_FAILED = 1
_PROCESS_ERROR_DEADLINE = 2
_PROCESS_ERROR_INITIAL_STATUS = 3
_PROCESS_ERROR_REDIRECT = 4
_PROCESS_ERROR_FINAL_STATUS = 5
_PROCESS_ERROR_MEDIA_TYPE = 6
_PROCESS_ERROR_CONTENT_LENGTH = 7
_PROCESS_ERROR_RESPONSE_SIZE = 8
_PROCESS_ERROR_MESSAGES = {
    _PROCESS_ERROR_REQUEST_FAILED: (
        "SSEN resource request failed",
        "request_failed",
    ),
    _PROCESS_ERROR_DEADLINE: (
        "SSEN resource total deadline exceeded",
        "total_deadline_exceeded",
    ),
    _PROCESS_ERROR_INITIAL_STATUS: (
        "SSEN resource did not return the required redirect",
        "unexpected_initial_status",
    ),
    _PROCESS_ERROR_REDIRECT: (
        "SSEN resource returned an unapproved redirect",
        "unapproved_redirect",
    ),
    _PROCESS_ERROR_FINAL_STATUS: (
        "SSEN redirected resource did not return 200",
        "unexpected_final_status",
    ),
    _PROCESS_ERROR_MEDIA_TYPE: (
        "SSEN redirected resource is not text/csv",
        "unexpected_media_type",
    ),
    _PROCESS_ERROR_CONTENT_LENGTH: (
        "SSEN resource content length is invalid",
        "invalid_content_length",
    ),
    _PROCESS_ERROR_RESPONSE_SIZE: (
        "SSEN resource exceeds the response size limit",
        "response_size_exceeded",
    ),
}
_PROCESS_ERROR_IDS = {
    details[1]: error_id for error_id, details in _PROCESS_ERROR_MESSAGES.items()
}


class SsenResourceTransport(Protocol):
    """Deadline-aware owner of all resources used for one source request."""

    def download(self, resource: SourceResource, *, deadline: float) -> bytes: ...

    def close(self) -> None: ...


ProcessWorker = Callable[[Connection, dict[str, Any], float], None]
ConnectionFactory = Callable[[str, int, float], Any]


def _remaining_timeout(deadline: float, maximum: float) -> float:
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise SourceContractError(
            "SSEN resource total deadline exceeded",
            error_code="total_deadline_exceeded",
        )
    return min(maximum, remaining)


def _total_deadline_error() -> SourceContractError:
    return SourceContractError(
        "SSEN resource total deadline exceeded",
        error_code="total_deadline_exceeded",
    )


def _create_https_connection(
    host: str,
    port: int,
    timeout: float,
) -> http.client.HTTPSConnection:
    return http.client.HTTPSConnection(
        host,
        port=port,
        timeout=timeout,
        context=ssl.create_default_context(),
    )


def _set_connection_timeout(connection: Any, timeout: float) -> None:
    sock = getattr(connection, "sock", None)
    if sock is None:
        raise SourceContractError(
            "SSEN resource request failed",
            error_code="request_failed",
        )
    sock.settimeout(timeout)


def _open_https_response(
    url: str,
    deadline: float,
    connection_factory: ConnectionFactory,
) -> tuple[Any, Any]:
    try:
        parsed = urlsplit(url)
        port = parsed.port or 443
        host = parsed.hostname
    except ValueError:
        raise SourceContractError(
            "SSEN resource request failed",
            error_code="request_failed",
        ) from None
    if parsed.scheme != "https" or host is None:
        raise SourceContractError(
            "SSEN resource request failed",
            error_code="request_failed",
        )
    connection = connection_factory(
        host,
        port,
        _remaining_timeout(deadline, SOURCE_CONNECT_TIMEOUT_SECONDS),
    )
    try:
        connection.connect()
        _remaining_timeout(deadline, SOURCE_CONNECT_TIMEOUT_SECONDS)
        _set_connection_timeout(
            connection,
            _remaining_timeout(deadline, SOURCE_READ_TIMEOUT_SECONDS),
        )
        target = parsed.path or "/"
        if parsed.query:
            target += "?" + parsed.query
        connection.request("GET", target, headers={"accept": "text/csv"})
        _set_connection_timeout(
            connection,
            _remaining_timeout(deadline, SOURCE_READ_TIMEOUT_SECONDS),
        )
        response = connection.getresponse()
        _remaining_timeout(deadline, SOURCE_READ_TIMEOUT_SECONDS)
        return connection, response
    except SourceContractError:
        connection.close()
        raise
    except BaseException:
        connection.close()
        if time.monotonic() >= deadline:
            raise SourceContractError(
                "SSEN resource total deadline exceeded",
                error_code="total_deadline_exceeded",
            ) from None
        raise SourceContractError(
            "SSEN resource request failed",
            error_code="request_failed",
        ) from None


def _approved_redirect(location: str, resource_id: str) -> bool:
    if not location or any(ord(character) < 32 or ord(character) == 127 for character in location):
        return False
    try:
        parsed = urlsplit(location)
        port = parsed.port
    except ValueError:
        return False
    prefix = f"/dx-sse-prod/resources/{resource_id}/"
    if not parsed.path.startswith(prefix):
        return False
    filename = parsed.path[len(prefix) :]
    return (
        parsed.scheme == "https"
        and parsed.hostname == _REDIRECT_HOST
        and parsed.username is None
        and parsed.password is None
        and port in (None, 443)
        and parsed.fragment == ""
        and bool(parsed.query)
        and "%" not in parsed.path
        and re.fullmatch(r"[A-Za-z0-9](?:[A-Za-z0-9._-]*[A-Za-z0-9])?", filename)
        is not None
    )


def _download_resource_in_child(
    resource_payload: dict[str, Any],
    deadline: float,
    *,
    connection_factory: ConnectionFactory | None = None,
) -> bytes:
    active_connection_factory = connection_factory or _create_https_connection
    try:
        resource = SourceResource.model_validate(resource_payload)
        _validate_stable_resource_url(resource)
    except BaseException:
        raise SourceContractError(
            "SSEN resource request failed",
            error_code="request_failed",
        ) from None

    first_connection, first = _open_https_response(
        resource.stable_url,
        deadline,
        active_connection_factory,
    )
    try:
        if first.status != 302:
            raise SourceContractError(
                "SSEN resource did not return the required redirect",
                response_status=first.status,
                error_code="unexpected_initial_status",
            )
        location = first.getheader("location", "") or ""
        if not _approved_redirect(location, resource.source_resource_id):
            raise SourceContractError(
                "SSEN resource returned an unapproved redirect",
                error_code="unapproved_redirect",
            )
    finally:
        first.close()
        first_connection.close()

    second_connection, second = _open_https_response(
        location,
        deadline,
        active_connection_factory,
    )
    chunks: list[bytes] = []
    total = 0
    try:
        if second.status != 200:
            raise SourceContractError(
                "SSEN redirected resource did not return 200",
                response_status=second.status,
                error_code="unexpected_final_status",
            )
        media_type = (second.getheader("content-type", "") or "").split(
            ";", 1
        )[0].strip().lower()
        if media_type != "text/csv":
            raise SourceContractError(
                "SSEN redirected resource is not text/csv",
                error_code="unexpected_media_type",
            )
        declared = second.getheader("content-length")
        declared_size: int | None = None
        if declared is not None:
            try:
                declared_size = int(declared, 10)
            except ValueError:
                raise SourceContractError(
                    "SSEN resource content length is invalid",
                    error_code="invalid_content_length",
                ) from None
            if declared_size < 0 or declared_size > SOURCE_MAX_RESPONSE_BYTES:
                raise SourceContractError(
                    "SSEN resource exceeds the response size limit",
                    error_code="response_size_exceeded",
                )
        while True:
            _set_connection_timeout(
                second_connection,
                _remaining_timeout(deadline, SOURCE_READ_TIMEOUT_SECONDS),
            )
            try:
                chunk = second.read(64 * 1024)
            except BaseException:
                if time.monotonic() >= deadline:
                    raise SourceContractError(
                        "SSEN resource total deadline exceeded",
                        error_code="total_deadline_exceeded",
                    ) from None
                raise SourceContractError(
                    "SSEN resource request failed",
                    error_code="request_failed",
                ) from None
            _remaining_timeout(deadline, SOURCE_READ_TIMEOUT_SECONDS)
            if not chunk:
                break
            total += len(chunk)
            if total > SOURCE_MAX_RESPONSE_BYTES:
                raise SourceContractError(
                    "SSEN resource exceeds the response size limit",
                    error_code="response_size_exceeded",
                )
            chunks.append(chunk)
        if declared_size is not None and total != declared_size:
            raise SourceContractError(
                "SSEN resource content length is invalid",
                error_code="invalid_content_length",
            )
    finally:
        second.close()
        second_connection.close()
    return b"".join(chunks)


def _ssen_download_process_worker(
    send_connection: Connection,
    resource_payload: dict[str, Any],
    deadline: float,
    connection_factory: ConnectionFactory | None = None,
) -> None:
    try:
        content = _download_resource_in_child(
            resource_payload,
            deadline,
            connection_factory=connection_factory,
        )
    except SourceContractError as error:
        error_id = _PROCESS_ERROR_IDS.get(
            error.code,
            _PROCESS_ERROR_REQUEST_FAILED,
        )
        status = error.response_status
        safe_status = status if status is not None and 0 <= status < 0xFFFF else 0xFFFF
        send_connection.send_bytes(
            _PROCESS_MESSAGE_ERROR + struct.pack("!BH", error_id, safe_status)
        )
        return
    except BaseException:
        send_connection.send_bytes(
            _PROCESS_MESSAGE_ERROR
            + struct.pack("!BH", _PROCESS_ERROR_REQUEST_FAILED, 0xFFFF)
        )
        return
    send_connection.send_bytes(_PROCESS_MESSAGE_SUCCESS + content)


def _safe_process_entry(
    worker_target: ProcessWorker,
    send_connection: Connection,
    resource_payload: dict[str, Any],
    deadline: float,
    connection_factory: ConnectionFactory | None,
) -> None:
    """Run an importable child target without reflecting child exception state."""
    try:
        if connection_factory is None:
            worker_target(send_connection, resource_payload, deadline)
        else:
            _ssen_download_process_worker(
                send_connection,
                resource_payload,
                deadline,
                connection_factory,
            )
    except BaseException:
        try:
            send_connection.send_bytes(
                _PROCESS_MESSAGE_ERROR
                + struct.pack("!BH", _PROCESS_ERROR_REQUEST_FAILED, 0xFFFF)
            )
        except BaseException:
            pass
    finally:
        try:
            send_connection.close()
        except BaseException:
            pass


def _terminate_and_join(process: multiprocessing.Process) -> None:
    cleanup_deadline = time.monotonic() + PROCESS_CLEANUP_GRACE_SECONDS
    if process.is_alive():
        process.terminate()
        process.join(
            min(
                PROCESS_CLEANUP_GRACE_SECONDS / 2,
                max(0.0, cleanup_deadline - time.monotonic()),
            )
        )
    if process.is_alive():
        process.kill()
        process.join(max(0.0, cleanup_deadline - time.monotonic()))
    else:
        process.join(0)
    if process.is_alive():
        raise SourceContractError(
            "SSEN resource worker cleanup failed",
            error_code="worker_cleanup_failed",
        )


class OwnedProcessSsenTransport:
    """Spawn-owned synchronous HTTPS boundary on spawn-capable platforms.

    The absolute deadline ends network and child work. Synchronous process
    startup is a supported-platform boundary that cannot itself be cancelled;
    it is checked immediately on return. Final cleanup may then use only the
    separate bounded ``PROCESS_CLEANUP_GRACE_SECONDS`` allowance.
    """

    def __init__(
        self,
        *,
        worker_target: ProcessWorker | None = None,
        connection_factory: ConnectionFactory | None = None,
        max_response_bytes: int = SOURCE_MAX_RESPONSE_BYTES,
        poll_interval_seconds: float = 0.05,
    ) -> None:
        if worker_target is not None and connection_factory is not None:
            raise ValueError(
                "worker_target and connection_factory cannot be combined"
            )
        self._worker_target = worker_target or _ssen_download_process_worker
        self._connection_factory = connection_factory
        self._max_response_bytes = max_response_bytes
        self._poll_interval_seconds = poll_interval_seconds
        self._context = multiprocessing.get_context("spawn")
        self._start_process: Callable[[multiprocessing.Process], None] = (
            lambda process: process.start()
        )

    def download(self, resource: SourceResource, *, deadline: float) -> bytes:
        if time.monotonic() >= deadline:
            raise _total_deadline_error()
        receive_connection, send_connection = self._context.Pipe(duplex=False)
        process = self._context.Process(
            target=_safe_process_entry,
            args=(
                self._worker_target,
                send_connection,
                resource.model_dump(mode="python"),
                deadline,
                self._connection_factory,
            ),
            name="ssen-download-worker",
        )
        started = False
        message: bytes | None = None
        try:
            try:
                self._start_process(process)
            except BaseException:
                raise SourceContractError(
                    "SSEN resource process startup is unsupported",
                    error_code="process_startup_unsupported",
                ) from None
            started = True
            send_connection.close()
            if time.monotonic() >= deadline:
                raise _total_deadline_error()
            while message is None:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise _total_deadline_error()
                if receive_connection.poll(
                    min(remaining, self._poll_interval_seconds)
                ):
                    try:
                        message = receive_connection.recv_bytes(
                            self._max_response_bytes + 1
                        )
                    except (EOFError, OSError):
                        raise SourceContractError(
                            "SSEN resource worker protocol failed"
                        ) from None
                    if time.monotonic() >= deadline:
                        raise _total_deadline_error()
                    break
                if not process.is_alive():
                    raise SourceContractError(
                        "SSEN resource worker protocol failed"
                    )

            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise _total_deadline_error()
            process.join(remaining)
            if process.is_alive() or time.monotonic() >= deadline:
                raise _total_deadline_error()
            duplicate_message = False
            try:
                has_trailing_data = receive_connection.poll(0)
            except (EOFError, OSError):
                has_trailing_data = False
            if has_trailing_data:
                try:
                    receive_connection.recv_bytes(self._max_response_bytes + 1)
                except EOFError:
                    pass
                except OSError:
                    duplicate_message = True
                else:
                    duplicate_message = True
            if process.exitcode != 0 or duplicate_message:
                raise SourceContractError(
                    "SSEN resource worker protocol failed"
                )
            return self._decode_message(message)
        except SourceContractError:
            raise
        except BaseException:
            raise SourceContractError(
                "SSEN resource worker protocol failed"
            ) from None
        finally:
            process_was_started = started or process.pid is not None
            if process_was_started:
                _terminate_and_join(process)
            if not process.is_alive():
                process.close()
            receive_connection.close()
            try:
                send_connection.close()
            except BaseException:
                pass

    def _decode_message(self, message: bytes) -> bytes:
        if not message:
            raise SourceContractError("SSEN resource worker protocol failed")
        if message[:1] == _PROCESS_MESSAGE_SUCCESS:
            return message[1:]
        if message[:1] != _PROCESS_MESSAGE_ERROR or len(message) != 4:
            raise SourceContractError("SSEN resource worker protocol failed")
        error_id, response_status = struct.unpack("!BH", message[1:])
        details = _PROCESS_ERROR_MESSAGES.get(error_id)
        if details is None:
            raise SourceContractError("SSEN resource worker protocol failed")
        message_text, error_code = details
        raise SourceContractError(
            message_text,
            response_status=None if response_status == 0xFFFF else response_status,
            error_code=error_code,
        )

    def close(self) -> None:
        """No persistent child resource survives an individual download."""


class SourceLicenceEvidenceArtifactV1(BaseModel):
    schema_version: Literal[1] = 1
    evidence_url: str
    observed_at: datetime
    catalogue_observation_id: str
    portal_id: Literal["ssen"]
    source_dataset_id: str
    package_id: str
    source_resource_ids: tuple[str, str]
    licence_id: str
    licence_title: str
    licence_url: str
    attribution: str
    source_byte_redistribution: Literal["permitted_with_attribution"]
    catalogue_observation_content_sha256: str

    @model_validator(mode="after")
    def validate_public_canonical_evidence(self) -> SourceLicenceEvidenceArtifactV1:
        parsed = urlsplit(self.evidence_url)
        if (
            parsed.scheme != "https"
            or parsed.hostname != "data.ssen.co.uk"
            or parsed.username is not None
            or parsed.password is not None
            or parsed.port not in (None, 443)
            or parsed.query
            or parsed.fragment
            or parsed.path != "/dataset/nafirs-hv-faults"
        ):
            raise ValueError("licence evidence URL must be the stable public page")
        if self.observed_at.tzinfo is None or self.observed_at.utcoffset() is None:
            raise ValueError("licence evidence observation must be timezone-aware")
        if self.source_resource_ids != _EXPECTED_RESOURCE_IDS:
            raise ValueError("licence evidence must bind the exact resource set")
        for value in (
            self.catalogue_observation_content_sha256,
        ):
            if len(value) != 64 or any(item not in "0123456789abcdef" for item in value):
                raise ValueError("licence evidence hash must be lowercase SHA-256")
        return self


class SourceLicenceEvidenceV1(SourceLicenceEvidenceArtifactV1):
    evidence_artifact_path: Literal[
        "data/sources/evidence/ssen-nafirs-hv-licence.json"
    ]
    evidence_artifact_sha256: str
    evidence_sha256: str


class SsenSourceManifestV1(BaseModel):
    schema_version: Literal[1]
    source_contract_version: Literal["ssen-nafirs-hv-v1"]
    source_id: Literal["ssen-nafirs-hv"]
    source_dataset_id: str
    package_id: str
    resources: list[SourceResource]
    request_method: Literal["GET"]
    redirect_host: str
    redirect_path_prefix: str
    licence_id: str
    licence_title: str
    licence_url: str
    attribution: str
    licence_evidence: SourceLicenceEvidenceV1
    source_byte_redistribution: Literal["permitted_with_attribution"]
    max_response_bytes: Literal[134217728]
    connect_timeout_seconds: Literal[10]
    read_timeout_seconds: Literal[60]
    total_deadline_seconds: Literal[180]
    analytical_role: Literal["historical_hv_outage_evidence"]
    limitations: list[str]
    timezone_name: None
    publisher_cadence: None

    @model_validator(mode="after")
    def validate_exact_source_contract(self) -> SsenSourceManifestV1:
        evidence = self.licence_evidence
        shared = (
            "source_dataset_id",
            "package_id",
            "licence_id",
            "licence_title",
            "licence_url",
            "attribution",
            "source_byte_redistribution",
        )
        if any(getattr(self, name) != getattr(evidence, name) for name in shared):
            raise ValueError("manifest and licence evidence fields differ")
        resource_ids = tuple(sorted(item.source_resource_id for item in self.resources))
        if resource_ids != _EXPECTED_RESOURCE_IDS or resource_ids != evidence.source_resource_ids:
            raise ValueError("manifest resource set differs from reviewed evidence")
        if len(self.resources) != 2:
            raise ValueError("manifest must contain exactly two resources")
        if self.redirect_host != _REDIRECT_HOST:
            raise ValueError("manifest redirect host differs from reviewed contract")
        if self.redirect_path_prefix != "/dx-sse-prod/resources/":
            raise ValueError("manifest redirect path differs from reviewed contract")
        for resource in self.resources:
            if (
                resource.source_dataset_id != self.source_dataset_id
                or resource.package_id != self.package_id
                or resource.format != "CSV"
                or resource.media_type != "text/csv"
                or resource.datastore_active is not True
            ):
                raise ValueError("manifest resource differs from reviewed contract")
            _validate_stable_resource_url(resource)
        return self


def _canonical_json_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode()


def _validate_stable_resource_url(resource: SourceResource) -> None:
    try:
        parsed = urlsplit(resource.stable_url)
        port = parsed.port
    except ValueError as error:
        raise ValueError("manifest resource URL is invalid") from error
    expected = (
        f"/dataset/{resource.package_id}/resource/"
        f"{resource.source_resource_id}/download/"
    )
    filename = parsed.path.removeprefix(expected)
    if (
        parsed.scheme != "https"
        or parsed.hostname != "data-api.ssen.co.uk"
        or parsed.username is not None
        or parsed.password is not None
        or port not in (None, 443)
        or parsed.query
        or parsed.fragment
        or not parsed.path.startswith(expected)
        or not filename
        or "/" in filename
    ):
        raise ValueError("manifest resource URL differs from reviewed contract")


def load_ssen_source_manifest(
    path: Path | None = None,
) -> SsenSourceManifestV1:
    """Load and hash-verify the tracked reviewed source contract."""
    manifest_path = path or _SOURCE_MANIFEST_PATH
    raw = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest = SsenSourceManifestV1.model_validate(raw)
    evidence_path = _REPOSITORY_ROOT / manifest.licence_evidence.evidence_artifact_path
    artifact_bytes = evidence_path.read_bytes()
    artifact_raw = json.loads(artifact_bytes.decode("utf-8"))
    expected_bytes = _canonical_json_bytes(artifact_raw) + b"\n"
    if artifact_bytes != expected_bytes:
        raise ValueError("licence evidence artifact is not exact canonical JSON")
    artifact_hash = hashlib.sha256(artifact_bytes).hexdigest()
    if artifact_hash != manifest.licence_evidence.evidence_artifact_sha256:
        raise ValueError("licence evidence artifact hash differs")
    artifact = SourceLicenceEvidenceArtifactV1.model_validate(artifact_raw)
    embedded = manifest.licence_evidence.model_dump()
    for extra in (
        "evidence_artifact_path",
        "evidence_artifact_sha256",
        "evidence_sha256",
    ):
        embedded.pop(extra)
    if artifact.model_dump() != embedded:
        raise ValueError("embedded licence evidence differs from artifact")
    evidence_raw = dict(raw["licence_evidence"])
    evidence_sha256 = evidence_raw.pop("evidence_sha256")
    if hashlib.sha256(_canonical_json_bytes(evidence_raw)).hexdigest() != evidence_sha256:
        raise ValueError("embedded licence evidence hash differs")
    return manifest


def download_ssen_hv_resource(
    transport: SsenResourceTransport,
    resource: SourceResource,
) -> bytes:
    """Download one resource through exactly one bounded approved redirect."""
    _validate_stable_resource_url(resource)
    try:
        return transport.download(
            resource,
            deadline=time.monotonic() + SOURCE_TOTAL_DEADLINE_SECONDS,
        )
    except SourceContractError:
        raise
    except BaseException:
        raise SourceContractError(
            "SSEN resource request failed",
            error_code="request_failed",
        ) from None


def _write_blob(
    content: bytes,
    content_sha256: str,
    snapshot_dir: Path,
    run_id: str,
) -> tuple[str, Path | None]:
    relative = Path("blobs") / content_sha256[:2] / f"{content_sha256}.csv"
    path = snapshot_dir / relative
    if path.exists():
        existing = path.read_bytes()
        if len(existing) != len(content) or hashlib.sha256(existing).hexdigest() != content_sha256:
            raise ValueError("existing outage blob failed hash and size verification")
        return relative.as_posix(), None
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{run_id.rsplit(':', 1)[-1]}.tmp")
    try:
        temporary.write_bytes(content)
        if temporary.stat().st_size != len(content):
            raise ValueError("outage blob atomic write size mismatch")
        if hashlib.sha256(temporary.read_bytes()).hexdigest() != content_sha256:
            raise ValueError("outage blob atomic write hash mismatch")
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()
    return relative.as_posix(), path


def sync_ssen_nafirs_hv(
    *,
    db_path: Path | None = None,
    snapshot_dir: Path | None = None,
    client: SsenResourceTransport | None = None,
) -> SyncResult:
    """Synchronise both reviewed resources into one atomic local evidence set."""
    manifest = load_ssen_source_manifest()
    resolved_db = db_path or config.outage_db_path
    resolved_snapshot_dir = snapshot_dir or config.outage_snapshot_dir
    run_id = f"ssen-nafirs-hv:{uuid.uuid4().hex}"
    snapshots: list[SourceSnapshot] = []
    events = []
    rejects: list[OutageReject] = []
    attempts: list[OutageFetchAttemptPublicV1] = []
    created_files: list[Path] = []
    own_transport = client is None
    active_transport = client or OwnedProcessSsenTransport()
    resources_seen = 0
    try:
        for resource in sorted(
            manifest.resources, key=lambda item: item.source_resource_id
        ):
            resources_seen += 1
            attempted_at = datetime.now(timezone.utc)
            try:
                content = download_ssen_hv_resource(active_transport, resource)
                digest = hashlib.sha256(content).hexdigest()
                snapshot_id = source_snapshot_id(resource.source_resource_id, digest)
                relative_path, created_path = _write_blob(
                    content, digest, resolved_snapshot_dir, run_id
                )
                if created_path is not None:
                    created_files.append(created_path)
                parsed = list(
                    iter_ssen_hv_csv(
                        content,
                        licence_area=resource.licence_area,
                        source_dataset_id=resource.source_dataset_id,
                        source_resource_id=resource.source_resource_id,
                        snapshot_id=snapshot_id,
                    )
                )
                resource_events = [item for item in parsed if not isinstance(item, OutageRowError)]
                resource_rejects = [item for item in parsed if isinstance(item, OutageRowError)]
                events.extend(resource_events)
                rejects.extend(
                    OutageReject(
                        run_id=run_id,
                        source_resource_id=resource.source_resource_id,
                        row_number=item.row_number or 1,
                        error_code=item.code,
                        error_message=item.message,
                        raw_row=item.raw_record,
                    )
                    for item in resource_rejects
                )
                observed_columns = list(
                    SEPD_COLUMNS if resource.licence_area == "SEPD" else SHEPD_COLUMNS
                )
                snapshot = SourceSnapshot(
                    snapshot_id=snapshot_id,
                    source_dataset_id=resource.source_dataset_id,
                    package_id=resource.package_id,
                    source_resource_id=resource.source_resource_id,
                    licence_area=resource.licence_area,
                    stable_source_url=resource.stable_url,
                    source_modified_at=resource.source_modified_at,
                    fetched_at=attempted_at,
                    content_sha256=digest,
                    byte_size=len(content),
                    row_count=len(parsed),
                    observed_columns=observed_columns,
                    licence_id=manifest.licence_id,
                    licence_title=manifest.licence_title,
                    licence_url=manifest.licence_url,
                    attribution=manifest.attribution,
                    parser_version=PARSER_VERSION,
                    local_snapshot_path=relative_path,
                )
                snapshots.append(snapshot)
                attempts.append(
                    OutageFetchAttemptPublicV1(
                        attempt_id=f"attempt:{uuid.uuid4().hex}",
                        run_id=run_id,
                        source_resource_id=resource.source_resource_id,
                        attempted_at=attempted_at,
                        status="completed",
                        response_status=200,
                        source_modified_at=resource.source_modified_at,
                        source_snapshot_id=snapshot_id,
                        content_sha256=digest,
                        byte_size=len(content),
                        error_code=None,
                    )
                )
            except Exception as error:
                attempts.append(
                    OutageFetchAttemptPublicV1(
                        attempt_id=f"attempt:{uuid.uuid4().hex}",
                        run_id=run_id,
                        source_resource_id=resource.source_resource_id,
                        attempted_at=attempted_at,
                        status="failed",
                        response_status=getattr(error, "response_status", None),
                        source_modified_at=resource.source_modified_at,
                        source_snapshot_id=None,
                        content_sha256=None,
                        byte_size=None,
                        error_code=getattr(
                            error,
                            "code",
                            "source_fetch_failed",
                        ),
                    )
                )
                raise
        return commit_ingestion_run(
            run_id=run_id,
            resources_seen=resources_seen,
            snapshots=snapshots,
            events=events,
            rejects=rejects,
            warnings=[],
            fetch_attempts=attempts,
            db_path=resolved_db,
        )
    except Exception as error:
        for path in reversed(created_files):
            if path.exists():
                path.unlink()
        return record_failed_ingestion_run(
            run_id=run_id,
            resources_seen=resources_seen,
            error=error,
            fetch_attempts=attempts,
            db_path=resolved_db,
        )
    finally:
        if own_transport:
            active_transport.close()
