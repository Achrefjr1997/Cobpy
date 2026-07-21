from __future__ import annotations

import logging
import re
from pathlib import Path

logger = logging.getLogger(__name__)

_MAX_COPY_DEPTH = 5

_COPY_LINE_RE = re.compile(
    r"^\s*COPY\s+(?:'([^']+)'|\"([^\"]+)\"|([A-Za-z0-9\-_\.]+))\s*\.?\s*$",
    re.IGNORECASE | re.MULTILINE,
)


def _detect_margin(source: str) -> int:
    """Detect the left margin (Area A start) of the COBOL source.

    Returns the column at which non-comment code starts (0-indexed).
    Defaults to 7 if no code lines are found.
    """
    for line in source.splitlines():
        stripped = line.rstrip("\n")
        text = stripped.strip()
        if text and not text.startswith("*") and not text.startswith("/"):
            return len(stripped) - len(stripped.lstrip())
    return 7


def _find_copybook(name: str, extract_dir: Path) -> Path | None:
    """Find a copybook file by name (case-insensitive) under *extract_dir*."""
    extract_dir = Path(extract_dir)
    cpy_name = name if name.lower().endswith(".cpy") else name + ".cpy"

    for p in extract_dir.rglob(cpy_name):
        if p.is_file():
            return p

    for p in extract_dir.rglob("*"):
        if (
            p.is_file()
            and p.suffix.lower() == ".cpy"
            and p.stem.upper() == name.upper()
        ):
            return p

    return None


def resolve_copybooks(
    source: str,
    extract_dir: Path,
    depth: int = 0,
    visited: set[str] | None = None,
) -> str:
    """Replace ``COPY <name>`` statements with inlined copybook content.

    Recursively resolves nested COPY statements up to
    ``_MAX_COPY_DEPTH`` (5). Tracks visited names to break cycles.
    Inlined lines are re-indented to match the parent's margin.

    Args:
        source: COBOL source code containing COPY statements.
        extract_dir: Directory tree to search for ``.cpy`` files.
        depth: Internal recursion counter (callers omit).
        visited: Internal set of already-resolved names (callers omit).

    Returns:
        Source code with COPY statements expanded in-place.
    """
    extract_dir = Path(extract_dir)

    if visited is None:
        visited = set()

    if depth >= _MAX_COPY_DEPTH:
        logger.warning("Max copybook recursion depth (%d) reached", _MAX_COPY_DEPTH)
        return source

    margin = _detect_margin(source)

    def replacer(match: re.Match) -> str:
        raw_name = (
            match.group(1) or match.group(2) or match.group(3)
        ).strip().upper().removesuffix(".")

        if raw_name in visited:
            return f"      * --- SKIPPED {raw_name} (cycle) ---"
        visited.add(raw_name)

        cpy_path = _find_copybook(raw_name, extract_dir)
        if cpy_path is None:
            logger.info("Copybook %s not found, leaving COPY as-is", raw_name)
            return match.group(0)

        content = cpy_path.read_text(encoding="utf-8", errors="ignore")
        content = resolve_copybooks(content, extract_dir, depth + 1, visited)

        # Re-indent: comment lines (* in col 7) get 6 spaces;
        # code lines get margin (Area A) spaces.
        indented_lines = []
        for line in content.splitlines():
            if line.strip():
                stripped = line.lstrip()
                if stripped.startswith("*") or stripped.startswith("/"):
                    indented_lines.append("      " + stripped)
                else:
                    indented_lines.append(" " * margin + stripped)
            else:
                indented_lines.append(line)
        indented = "\n".join(indented_lines)

        return (
            f"      * --- INLINED FROM {raw_name}.CPY ---\n"
            f"{indented}\n"
            f"      * --- END INLINED {raw_name}.CPY ---"
        )

    return _COPY_LINE_RE.sub(replacer, source)
