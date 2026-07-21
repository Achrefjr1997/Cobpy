from __future__ import annotations

import logging
import re
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from cobol_migrator.agent.state import AgentState
from cobol_migrator.env_utils import build_safe_env

logger = logging.getLogger(__name__)

# GnuCOBOL treats CALL to an undefined program as a hard error.
# In multi-file projects this is expected, so we detect and accept
# such errors when no other issues exist.
_UNDEFINED_CALL_RE = re.compile(
    r"error:\s+'([A-Za-z0-9\-_]+)'\s+is\s+not\s+defined",
    re.IGNORECASE,
)
_CALL_RE = re.compile(
    r"CALL\s+(?:'([A-Za-z0-9\-_]+)'|\"([A-Za-z0-9\-_]+)\"|([A-Za-z0-9\-_]+))",
    re.IGNORECASE,
)


def _extract_call_targets(source: str) -> set[str]:
    """Return the set of program names called in *source*."""
    targets: set[str] = set()
    for m in _CALL_RE.finditer(source):
        name = (m.group(1) or m.group(2) or m.group(3)).strip().upper()
        targets.add(name)
    return targets


_FREE_COMMENT_RE = re.compile(
    r"^(\s*)\*(?!>)(.*)", re.MULTILINE,
)


def _preprocess_free_format(source: str) -> str:
    """Convert fixed-format ``*`` comment lines to free-format ``*>``.

    In free-format COBOL (``>>SOURCE FORMAT FREE``), comments use ``*>``,
    not bare ``*``. Many hybrid sources use fixed-format ``*`` in column 7,
    which GnuCOBOL rejects with ``-free``. This converts them.
    """
    return _FREE_COMMENT_RE.sub(r"\1*>\2", source)


def _only_expected_call_errors(stderr: str, call_targets: set[str]) -> bool:
    """Return True if every error line is an expected CALL-not-defined."""
    for line in stderr.splitlines():
        if "error:" in line or "Error:" in line:
            m = _UNDEFINED_CALL_RE.search(line)
            if m is None or m.group(1).upper() not in call_targets:
                return False
    return True


def validate_cobol(state: AgentState) -> dict[str, Any]:
    """
    Validate the input COBOL code by compiling it with GnuCOBOL.

    If compilation fails, the migration is stopped immediately unless
    the only errors are CALL references to undefined programs (expected
    in multi-file projects).
    """
    emit = state.get("emit", lambda t, p: None)
    cobol_source = state.get("cobol_source", "")

    if not cobol_source.strip():
        emit("cobol_validation", {"passed": False, "message": "Empty COBOL source"})
        return {
            "error": "Empty COBOL source code provided",
            "cobol_validated": False,
        }

    with tempfile.TemporaryDirectory(prefix="cobol_validate_") as tmpdir:
        tmppath = Path(tmpdir)
        cobol_file = tmppath / "program.cbl"
        is_free_format = ">>SOURCE FORMAT FREE" in cobol_source.upper()
        if is_free_format:
            cobol_source = _preprocess_free_format(cobol_source)
        cobol_file.write_text(cobol_source)

        try:
            cobc_args = ["cobc", "-fsyntax-only"]
            if is_free_format:
                cobc_args.append("-free")
            cobc_args.append(str(cobol_file))
            include_dir_raw = state.get("copybook_include_dir")
            if include_dir_raw:
                for d in include_dir_raw.split(","):
                    if d.strip():
                        cobc_args.extend(["-I", d.strip()])
            compile_result = subprocess.run(
                cobc_args,
                capture_output=True,
                text=True,
                timeout=30,
                env=build_safe_env(include_cobol=True),
                cwd=str(tmppath),
            )
        except FileNotFoundError:
            logger.warning("GnuCOBOL (cobc) not installed, skipping COBOL validation")
            emit(
                "cobol_validation",
                {
                    "passed": True,
                    "message": "GnuCOBOL not installed - skipping compilation check",
                    "cobc_available": False,
                },
            )
            return {"cobol_validated": True, "cobc_available": False}
        except subprocess.TimeoutExpired:
            emit(
                "cobol_validation",
                {"passed": False, "message": "COBOL compilation timed out"},
            )
            return {
                "error": "COBOL compilation timed out after 30 seconds",
                "cobol_validated": False,
            }

        if compile_result.returncode != 0:
            stderr = compile_result.stderr[:2000].strip()
            call_targets = _extract_call_targets(cobol_source)

            if call_targets and _only_expected_call_errors(stderr, call_targets):
                logger.info(
                    "COBOL validation passed (only expected CALL-undefined errors)"
                )
                emit(
                    "cobol_validation",
                    {
                        "passed": True,
                        "message": "COBOL OK (expected cross-program CALLs accepted)",
                        "compiler_output": stderr,
                        "cobc_available": True,
                    },
                )
                return {"cobol_validated": True, "cobc_available": True}

            emit(
                "cobol_validation",
                {
                    "passed": False,
                    "message": f"COBOL compilation failed: {stderr}",
                    "compiler_output": stderr,
                },
            )
            logger.error(f"COBOL compilation failed: {stderr}")
            return {
                "error": f"Input COBOL code has compilation errors:\n{stderr}",
                "cobol_validated": False,
            }

    emit(
        "cobol_validation",
        {
            "passed": True,
            "message": "COBOL code validated successfully",
            "cobc_available": True,
        },
    )

    logger.info("COBOL validation passed")

    return {
        "cobol_validated": True,
        "cobol_output": "",
        "cobc_available": True,
    }
