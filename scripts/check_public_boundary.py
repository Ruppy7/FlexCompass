from __future__ import annotations

import argparse
import re
from dataclasses import dataclass
from pathlib import Path

FORBIDDEN_NAMES = {".env"}
FORBIDDEN_SUFFIXES = {".db", ".sqlite", ".sqlite3"}
SKIP_NAMES = {
    ".git",
    ".next",
    ".pytest_cache",
    ".venv",
    "__pycache__",
    "node_modules",
}
CREDENTIAL_PATTERN = re.compile(
    r"(?m)^\s*(?:PASSWORD|SECRET|TOKEN|API[_-]?KEY)\s*=\s*[^\s#][^\r\n]*$"
)


@dataclass(frozen=True)
class Violation:
    path: Path
    reason: str


def scan_tree(root: Path) -> list[Violation]:
    violations: list[Violation] = []
    for path in root.rglob("*"):
        if any(part in SKIP_NAMES for part in path.parts):
            continue
        if (
            path.name.lower() in FORBIDDEN_NAMES
            or path.suffix.lower() in FORBIDDEN_SUFFIXES
        ):
            violations.append(Violation(path, "private or generated artifact"))
            continue
        if not path.is_file():
            continue
        try:
            content = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        if CREDENTIAL_PATTERN.search(content):
            violations.append(Violation(path, "possible embedded credential"))
    return violations


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Check a source tree for private or generated artifacts."
    )
    parser.add_argument("root", nargs="?", type=Path, default=Path.cwd())
    args = parser.parse_args()
    violations = scan_tree(args.root.resolve())
    for violation in violations:
        print(f"{violation.path}: {violation.reason}")
    return 1 if violations else 0


if __name__ == "__main__":
    raise SystemExit(main())
