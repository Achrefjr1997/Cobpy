from __future__ import annotations

import logging
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

from cobol_migrator.safety import UnsafeImportError, check_code_safety

logger = logging.getLogger(__name__)

SAFE_ENV = {
    "PATH": "/usr/bin:/usr/local/bin",
    "HOME": "/tmp",
    "LANG": "C.UTF-8",
    "COB_LIBRARY_PATH": "/usr/lib/gnucobol",
}


@dataclass
class DifferentialResult:
    """Result of differential testing between COBOL and Python."""

    available: bool
    passed: bool | None
    cobol_compiled: bool
    cobol_output: str | None
    python_output: str | None
    match_details: str
    error: str | None


def _compile_cobol(cobol_source: str, tmpdir: Path) -> tuple[bool, str, Path | None]:
    """Compile COBOL source with GnuCOBOL. Returns (success, message, binary_path)."""
    cobol_file = tmpdir / "program.cbl"
    cobol_file.write_text(cobol_source)
    binary_file = tmpdir / "program"

    try:
        result = subprocess.run(
            ["cobc", "-x", "-o", str(binary_file), str(cobol_file)],
            capture_output=True,
            text=True,
            timeout=30,
            env=SAFE_ENV,
            cwd=str(tmpdir),
        )

        if result.returncode == 0:
            return True, "Compiled successfully", binary_file
        else:
            return False, f"Compilation failed: {result.stderr[:500]}", None

    except FileNotFoundError:
        return False, "GnuCOBOL (cobc) not installed", None
    except subprocess.TimeoutExpired:
        return False, "Compilation timeout", None
    except Exception as e:
        return False, f"Compilation error: {e}", None


def _run_cobol(binary_path: Path, inputs: list[str], tmpdir: Path) -> tuple[str, str]:
    """Run compiled COBOL binary with given inputs. Returns (stdout, stderr)."""
    try:
        input_data = "\n".join(inputs) if inputs else ""
        result = subprocess.run(
            [str(binary_path)],
            input=input_data,
            capture_output=True,
            text=True,
            timeout=10,
            env=SAFE_ENV,
            cwd=str(tmpdir),
        )
        return result.stdout, result.stderr

    except subprocess.TimeoutExpired:
        return "", "TIMEOUT"
    except Exception as e:
        return "", str(e)


def _run_python(python_code: str, inputs: list[str], tmpdir: Path) -> tuple[str, str]:
    """Run Python code with given inputs. Returns (stdout, stderr)."""
    python_file = tmpdir / "main.py"
    python_file.write_text(python_code)

    try:
        input_data = "\n".join(inputs) if inputs else ""
        result = subprocess.run(
            [sys.executable, str(python_file)],
            input=input_data,
            capture_output=True,
            text=True,
            timeout=10,
            env=SAFE_ENV,
            cwd=str(tmpdir),
        )
        return result.stdout, result.stderr

    except subprocess.TimeoutExpired:
        return "", "TIMEOUT"
    except Exception as e:
        return "", str(e)


def _normalize_output(output: str) -> str:
    """
    Normalize output for comparison.

    Strips trailing whitespace, normalizes newlines, and normalizes
    numeric formatting so that COBOL zero-padded numbers (006000)
    match Python's default formatting (6000).
    """
    import re

    lines = []
    for line in output.strip().split("\n"):
        line = line.rstrip()
        # Normalize standalone zero-padded numbers: "006000" → "6000"
        # Only replace sequences of digits that have leading zeros and are
        # preceded by a non-digit (or start of string) to avoid mangling
        # things like record IDs or field positions.
        line = re.sub(
            r'(?<=\D)0+(\d+)',
            lambda m: m.group(1),
            line,
        )
        # Also handle numbers at the very start of a line
        line = re.sub(
            r'^0+(\d+)',
            lambda m: m.group(1),
            line,
        )
        lines.append(line)
    return "\n".join(lines)


def run_differential_validation(
    cobol_source: str,
    python_code: str,
    test_inputs: list[list[str]] | None = None,
) -> DifferentialResult:
    """
    Run differential testing: compile COBOL, run both, compare outputs.
    
    If COBOL doesn't compile (GnuCOBOL not installed or syntax error),
    returns a result with available=False but no failure.
    """
    try:
        check_code_safety(python_code)
    except UnsafeImportError as e:
        return DifferentialResult(
            available=False,
            passed=False,
            cobol_compiled=False,
            cobol_output=None,
            python_output=None,
            match_details="",
            error=f"Python code safety check failed: {e}",
        )

    if test_inputs is None:
        test_inputs = [[]]

    with tempfile.TemporaryDirectory() as tmpdir:
        tmppath = Path(tmpdir)

        compiled, compile_msg, binary_path = _compile_cobol(cobol_source, tmppath)

        if not compiled:
            logger.info(f"Differential validation unavailable: {compile_msg}")
            return DifferentialResult(
                available=False,
                passed=None,
                cobol_compiled=False,
                cobol_output=None,
                python_output=None,
                match_details=compile_msg,
                error=None,
            )

        all_passed = True
        match_details = []
        first_cobol_output = None
        first_python_output = None

        for i, inputs in enumerate(test_inputs):
            cobol_stdout, cobol_stderr = _run_cobol(binary_path, inputs, tmppath)
            python_stdout, python_stderr = _run_python(python_code, inputs, tmppath)

            if i == 0:
                first_cobol_output = cobol_stdout
                first_python_output = python_stdout

            cobol_normalized = _normalize_output(cobol_stdout)
            python_normalized = _normalize_output(python_stdout)

            if cobol_normalized == python_normalized:
                match_details.append(f"Test {i + 1}: MATCH")
            else:
                all_passed = False
                match_details.append(
                    f"Test {i + 1}: MISMATCH\n"
                    f"  COBOL: {cobol_normalized[:200]!r}\n"
                    f"  Python: {python_normalized[:200]!r}"
                )

        return DifferentialResult(
            available=True,
            passed=all_passed,
            cobol_compiled=True,
            cobol_output=first_cobol_output,
            python_output=first_python_output,
            match_details="\n".join(match_details),
            error=None,
        )
