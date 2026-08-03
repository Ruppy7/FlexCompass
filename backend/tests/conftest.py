import sqlite3
from collections.abc import Iterator
from dataclasses import replace
from pathlib import Path

import app.db as app_db
import pytest
from app.config import config
from fastapi.testclient import TestClient


@pytest.fixture
def isolated_api_client(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[tuple[TestClient, Path]]:
    test_db = tmp_path / "flexcompass-test.sqlite3"
    outage_test_db = tmp_path / "flexcompass-outages-test.sqlite3"
    catalogue_test_db = tmp_path / "flexcompass-catalogue-test.sqlite3"
    catalogue_snapshots = tmp_path / "catalogue-snapshots"
    opened: list[Path] = []
    real_connect = sqlite3.connect

    def guarded_connect(
        database: str | Path,
        *args: object,
        **kwargs: object,
    ) -> sqlite3.Connection:
        resolved = Path(database).resolve()
        if resolved not in {
            test_db.resolve(),
            outage_test_db.resolve(),
            catalogue_test_db.resolve(),
        }:
            raise AssertionError(f"application opened unexpected DB: {resolved}")
        opened.append(resolved)
        return real_connect(str(resolved), *args, **kwargs)

    injected_config = replace(
        config,
        db_path=test_db,
        outage_db_path=outage_test_db,
        catalogue_db_path=catalogue_test_db,
        catalogue_snapshot_dir=catalogue_snapshots,
    )
    monkeypatch.setattr(app_db.sqlite3, "connect", guarded_connect)

    # Importing app is allowed earlier because it performs no DB I/O;
    # entering lifespan must happen only after the guard.
    from app.main import create_app

    with TestClient(
        create_app(injected_config),
        raise_server_exceptions=False,
    ) as client:
        yield client, test_db

    # Startup opens only the independently injected outage and catalogue
    # stores. All application connections remain fail-closed to the three
    # explicit temporary paths.
    allowed_databases = {
        test_db.resolve(),
        outage_test_db.resolve(),
        catalogue_test_db.resolve(),
    }
    assert set(opened) <= allowed_databases
    assert outage_test_db.resolve() in opened
    assert catalogue_test_db.resolve() in opened


@pytest.fixture
def client(
    isolated_api_client: tuple[TestClient, Path],
) -> TestClient:
    return isolated_api_client[0]
