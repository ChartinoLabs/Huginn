"""Documentation hygiene check: no em-dashes allowed in documentation files.

Em-dashes (U+2014) are visually similar to hyphens but are typed differently
across operating systems and rarely render consistently in plain-text editors,
diffs, and code reviews. The project convention is to use plain ASCII hyphens
with a single space on either side (` - `) instead.

This test scans every Markdown file under `docs/` and the top-level `mkdocs.yml`
for em-dashes. Any occurrence fails the test with file paths and line numbers
to make remediation straightforward.
"""

from __future__ import annotations

from pathlib import Path

import pytest

EM_DASH = "—"
REPO_ROOT = Path(__file__).resolve().parent.parent
SCAN_PATHS: tuple[Path, ...] = (
    REPO_ROOT / "docs",
    REPO_ROOT / "mkdocs.yml",
)


def _iter_text_files() -> list[Path]:
    """Return every Markdown file under docs/ plus mkdocs.yml if present."""
    files: list[Path] = []
    for path in SCAN_PATHS:
        if path.is_file():
            files.append(path)
        elif path.is_dir():
            files.extend(sorted(path.rglob("*.md")))
    return files


def _find_em_dashes(path: Path) -> list[tuple[int, str]]:
    """Return (line_number, line_text) tuples for each line containing an em-dash."""
    matches: list[tuple[int, str]] = []
    for line_number, line in enumerate(
        path.read_text(encoding="utf-8").splitlines(),
        start=1,
    ):
        if EM_DASH in line:
            matches.append((line_number, line.rstrip()))
    return matches


def test_no_em_dashes_in_documentation() -> None:
    """Fail if any Markdown file under docs/ or mkdocs.yml contains an em-dash.

    The project convention is plain ASCII hyphens with a single space on
    either side (` - `). If this test fails, replace each em-dash listed
    below accordingly.
    """
    offenders: dict[Path, list[tuple[int, str]]] = {}
    for path in _iter_text_files():
        matches = _find_em_dashes(path)
        if matches:
            offenders[path] = matches

    if not offenders:
        return

    lines = ["Em-dash characters (U+2014) found in documentation:"]
    for path, matches in offenders.items():
        rel = path.relative_to(REPO_ROOT)
        for line_number, line_text in matches:
            lines.append(f"  {rel}:{line_number}: {line_text}")
    lines.append("")
    lines.append("Replace each em-dash with ' - ' (space, hyphen, space).")
    pytest.fail("\n".join(lines))
