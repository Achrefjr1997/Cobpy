from __future__ import annotations

import logging
import re
import zipfile
from pathlib import Path
from typing import Any, Dict, List, Set

logger = logging.getLogger(__name__)


class ZipSlipError(Exception):
    """Raised when a ZIP entry attempts path traversal."""
    pass


class InvalidZipError(Exception):
    """Raised when the uploaded file is not a valid ZIP."""
    pass


def secure_extract_zip(zip_file_path: str | Path, extract_to: str | Path) -> Path:
    """Safely extract a ZIP file, guarding against Zip Slip traversal attacks.

    Args:
        zip_file_path: Path to the uploaded ZIP file.
        extract_to: Directory to extract into.

    Returns:
        Resolved Path of the extraction root.

    Raises:
        ZipSlipError: If any entry attempts absolute path or ``../`` traversal.
    """
    extract_path = Path(extract_to).resolve(strict=False)
    extract_path.mkdir(parents=True, exist_ok=True)

    with zipfile.ZipFile(str(zip_file_path), "r") as zf:
        for member in zf.namelist():
            # Normalize to forward slashes for path operations (handles Windows-created zips)
            member_normalized = member.replace("\\", "/")
            member_path = Path(member_normalized)

            if member_path.is_absolute():
                raise ZipSlipError(
                    f"Absolute path detected in ZIP entry: {member}"
                )

            if ".." in member_path.parts:
                raise ZipSlipError(
                    f"Path traversal detected in ZIP entry: {member}"
                )

            target = (extract_path / member_path).resolve()

            if not str(target).startswith(str(extract_path)):
                raise ZipSlipError(
                    f"Path traversal detected after resolution: {member} -> {target}"
                )

            if member_normalized.endswith("/"):
                target.mkdir(parents=True, exist_ok=True)
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                with zf.open(member) as src, open(target, "wb") as dst:
                    dst.write(src.read())

    logger.info("Extracted %d entries to %s", len(zf.namelist()), extract_path)
    return extract_path


_PROGRAM_ID_RE = re.compile(r"PROGRAM-ID\.\s*([A-Za-z0-9\-_]+)", re.IGNORECASE)
_CALL_RE = re.compile(
    r"CALL\s+(?:'([A-Za-z0-9\-_]+)'|\"([A-Za-z0-9\-_]+)\"|([A-Za-z0-9\-_]+))",
    re.IGNORECASE,
)
_COPY_RE = re.compile(
    r"COPY\s+(?:'([A-Za-z0-9\-_\.]+)'|\"([A-Za-z0-9\-_\.]+)\"|([A-Za-z0-9\-_\.]+))",
    re.IGNORECASE,
)

_COBOL_EXTENSIONS = {".cbl", ".cob", ".cobol", ".cpy"}


def scan_cobol_dependencies(extract_dir: Path) -> dict[str, dict[str, Any]]:
    """Scan extracted directory for COBOL files and build a dependency graph.

    For each ``.cbl`` / ``.cob`` / ``.cobol`` / ``.cpy`` file found under
    *extract_dir* (recursive), the function extracts:

    - ``program_id`` – from ``PROGRAM-ID`` or filename stem as fallback
    - ``file_path`` – relative path from the extraction root
    - ``calls`` – list of program names referenced in ``CALL`` statements
    - ``copies`` – list of copybook names referenced in ``COPY`` statements

    Returns:
        A dict mapping ``program_id`` → dependency record.
    """
    dependencies: dict[str, dict[str, Any]] = {}

    cobol_files: list[Path] = [
        p for p in extract_dir.rglob("*")
        if p.suffix.lower() in _COBOL_EXTENSIONS and p.is_file()
    ]

    for file_path in cobol_files:
        content = file_path.read_text(encoding="utf-8", errors="ignore")

        prog_match = _PROGRAM_ID_RE.search(content)
        program_id = (
            prog_match.group(1).strip().upper()
            if prog_match
            else file_path.stem.upper()
        )

        calls: set[str] = set()
        for m in _CALL_RE.finditer(content):
            called = (m.group(1) or m.group(2) or m.group(3)).strip().upper()
            calls.add(called)

        copies: set[str] = set()
        for m in _COPY_RE.finditer(content):
            copybook = (m.group(1) or m.group(2) or m.group(3)).strip().upper()
            copybook = copybook.removesuffix(".CPY").removesuffix(".cpy")
            copybook = copybook.removesuffix(".")
            copies.add(copybook)

        dependencies[program_id] = {
            "file_path": str(file_path.relative_to(extract_dir)),
            "source": content,
            "calls": sorted(calls),
            "copies": sorted(copies),
        }

    logger.info(
        "Scanned %d COBOL files, found %d unique programs",
        len(cobol_files),
        len(dependencies),
    )
    return dependencies


def topological_sort(graph: dict[str, dict[str, Any]]) -> list[str]:
    """Produce a dependency-ordered (leaf-first) list of program IDs.

    Uses Kahn's algorithm. Programs with cyclic dependencies are grouped
    at the end of the returned list and logged as a warning.

    Args:
        graph: Output of :func:`scan_cobol_dependencies`.

    Returns:
        Program IDs in migration order (no-dependency programs first).
    """
    in_degree: dict[str, int] = {pid: 0 for pid in graph}
    adjacency: dict[str, list[str]] = {pid: [] for pid in graph}

    for pid, info in graph.items():
        for dep in info.get("calls", []) + info.get("copies", []):
            if dep in graph:
                adjacency[dep].append(pid)
                in_degree[pid] = in_degree.get(pid, 0) + 1

    queue: list[str] = [pid for pid, deg in in_degree.items() if deg == 0]
    ordered: list[str] = []

    while queue:
        node = queue.pop(0)
        ordered.append(node)
        for dependent in adjacency.get(node, []):
            in_degree[dependent] -= 1
            if in_degree[dependent] == 0:
                queue.append(dependent)

    cycles = [pid for pid in graph if pid not in ordered]
    if cycles:
        logger.warning("Cycle(s) detected among programs: %s", cycles)
        ordered.extend(cycles)

    return ordered


def find_copybook_dirs(extract_dir: Path) -> list[str]:
    """Find all directories under *extract_dir* that contain ``.cpy`` files.

    Returns absolute paths suitable for ``cobc -I`` flags.
    """
    dirs: set[Path] = set()
    for p in extract_dir.rglob("*.cpy"):
        if p.is_file():
            dirs.add(p.parent)
    for p in extract_dir.rglob("*.CPY"):
        if p.is_file():
            dirs.add(p.parent)
    return sorted(str(d) for d in dirs)
