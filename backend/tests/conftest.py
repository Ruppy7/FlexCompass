import sqlite3
from collections.abc import Iterator
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
    opened: list[Path] = []
    real_connect = sqlite3.connect

    def guarded_connect(
        database: str | Path,
        *args: object,
        **kwargs: object,
    ) -> sqlite3.Connection:
        resolved = Path(database).resolve()
        if resolved != test_db.resolve():
            raise AssertionError(f"application opened unexpected DB: {resolved}")
        opened.append(resolved)
        return real_connect(str(resolved), *args, **kwargs)

    original_db = config.db_path
    object.__setattr__(config, "db_path", test_db)
    try:
        monkeypatch.setattr(app_db.sqlite3, "connect", guarded_connect)

        # Importing app is allowed earlier because it performs no DB I/O;
        # entering lifespan must happen only after the guard.
        from app.main import app

        with TestClient(
            app,
            raise_server_exceptions=False,
        ) as client:
            yield client, test_db
    finally:
        object.__setattr__(config, "db_path", original_db)

    # Startup no longer opens a database; zero connections is valid. If an
    # application connection returns, it must still fail closed to this path.
    allowed_databases = {test_db.resolve()}
    assert set(opened) <= allowed_databases


@pytest.fixture
def client(
    isolated_api_client: tuple[TestClient, Path],
) -> TestClient:
    return isolated_api_client[0]
