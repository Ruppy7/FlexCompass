from pathlib import Path

from scripts.check_public_boundary import scan_tree


def test_boundary_scanner_reports_embedded_credentials(tmp_path: Path) -> None:
    credential_name = "API" + "_KEY"
    (tmp_path / "bad.py").write_text(
        f"{credential_name}=not-empty", encoding="utf-8"
    )

    violations = scan_tree(tmp_path)

    assert {violation.reason for violation in violations} == {
        "possible embedded credential"
    }


def test_boundary_scanner_reports_private_artifacts(tmp_path: Path) -> None:
    (tmp_path / ".env").write_text("PUBLIC_SETTING=example", encoding="utf-8")
    (tmp_path / "snapshot.db").write_bytes(b"sqlite")

    violations = scan_tree(tmp_path)

    assert {violation.path.name for violation in violations} == {
        ".env",
        "snapshot.db",
    }


def test_boundary_scanner_accepts_public_grid_research(tmp_path: Path) -> None:
    (tmp_path / "README.md").write_text(
        "Public NGED, SPEN, ENWL, SSEN and NESO research data.",
        encoding="utf-8",
    )

    assert scan_tree(tmp_path) == []
