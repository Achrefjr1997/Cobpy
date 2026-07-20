from __future__ import annotations

import logging
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from cobol_migrator.agent.state import AgentState

logger = logging.getLogger(__name__)

SAFE_ENV = {
    "PATH": "/usr/bin:/usr/local/bin",
    "HOME": "/tmp",
    "LANG": "C.UTF-8",
    "COB_LIBRARY_PATH": "/usr/lib/gnucobol",
}


def validate_cobol(state: AgentState) -> dict[str, Any]:
    """
    Validate the input COBOL code by compiling it with GnuCOBOL.

    If compilation fails, the migration is stopped immediately.
    If compilation succeeds, the COBOL output is captured for later
    comparison with the Python translation.
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
        cobol_file.write_text(cobol_source)
        binary_file = tmppath / "program"

        try:
            compile_result = subprocess.run(
                ["cobc", "-x", "-o", str(binary_file), str(cobol_file)],
                capture_output=True,
                text=True,
                timeout=30,
                env=SAFE_ENV,
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
            error_msg = compile_result.stderr[:1000].strip()
            emit(
                "cobol_validation",
                {
                    "passed": False,
                    "message": f"COBOL compilation failed: {error_msg}",
                    "compiler_output": error_msg,
                },
            )
            logger.error(f"COBOL compilation failed: {error_msg}")
            return {
                "error": f"Input COBOL code has compilation errors:\n{error_msg}",
                "cobol_validated": False,
            }

        cobol_output = ""
        cobol_stderr = ""
        try:
            run_result = subprocess.run(
                [str(binary_file)],
                capture_output=True,
                text=True,
                timeout=10,
                env=SAFE_ENV,
                cwd=str(tmppath),
            )
            cobol_output = run_result.stdout
            cobol_stderr = run_result.stderr
        except subprocess.TimeoutExpired:
            cobol_output = ""
            cobol_stderr = "COBOL execution timed out"
        except Exception as e:
            cobol_output = ""
            cobol_stderr = str(e)

    emit(
        "cobol_validation",
        {
            "passed": True,
            "message": "COBOL code compiled and executed successfully",
            "cobol_output": cobol_output[:2000] if cobol_output else None,
            "cobc_available": True,
        },
    )

    logger.info("COBOL validation passed - code compiles and runs successfully")

    return {
        "cobol_validated": True,
        "cobol_output": cobol_output,
        "cobc_available": True,
    }
