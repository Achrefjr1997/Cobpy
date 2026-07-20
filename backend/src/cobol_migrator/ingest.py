from __future__ import annotations

import logging

from cobol_migrator.errors import IngestionError

logger = logging.getLogger(__name__)

MAX_BYTES = 1_000_000  # 1 MB


def load_snippet(text: str) -> str:
    """
    Load COBOL from a raw text snippet.

    Validates size limit and basic COBOL structure.
    """
    if len(text.encode("utf-8", errors="replace")) > MAX_BYTES:
        raise IngestionError("Snippet too large (max 1MB)")

    if not _looks_like_cobol(text):
        logger.warning("Snippet doesn't look like COBOL, proceeding anyway")

    return text


def load_file(content: str) -> str:
    """
    Load COBOL from uploaded file content.

    Validates size limit and basic COBOL structure.
    """
    if len(content.encode("utf-8", errors="replace")) > MAX_BYTES:
        raise IngestionError("Uploaded file too large (max 1MB)")

    if not _looks_like_cobol(content):
        logger.warning("Uploaded file doesn't look like COBOL, proceeding anyway")

    return content


def _looks_like_cobol(text: str) -> bool:
    """Check if text appears to be COBOL source code."""
    upper = text.upper()
    return "IDENTIFICATION DIVISION" in upper or "PROGRAM-ID" in upper


def load_source(
    source_type: str,
    source_ref: str,
) -> str:
    """
    Load COBOL source from the specified source type.

    Args:
        source_type: One of "snippet", "file"
        source_ref: The source content

    Returns:
        The COBOL source code as a string
    """
    if source_type == "snippet":
        return load_snippet(source_ref)
    elif source_type == "file":
        return load_file(source_ref)
    else:
        raise IngestionError(f"Unknown source type: {source_type}")
