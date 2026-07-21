from __future__ import annotations

import os
import shutil
from pathlib import Path


def build_safe_env(include_cobol: bool = False) -> dict[str, str]:
    """Build cross-platform safe environment for subprocess execution.

    Preserves the system PATH so executables (cobc, python, etc.)
    can be found on Windows, Linux, or macOS.

    Args:
        include_cobol: If True, attempts to locate COB_LIBRARY_PATH
                       from the cobc installation.
    """
    env = dict(os.environ)
    env["LANG"] = "C.UTF-8"

    if include_cobol:
        cobc_path = shutil.which("cobc")
        if cobc_path and "COB_LIBRARY_PATH" not in env:
            cobc_dir = Path(cobc_path).resolve().parent
            candidates = [
                cobc_dir / ".." / "lib" / "gnucobol",
                cobc_dir / ".." / "lib" / "cobol",
                cobc_dir / ".." / ".." / "lib" / "gnucobol",
                Path("/usr/lib/gnucobol"),
                Path("/usr/local/lib/gnucobol"),
                Path("/opt/homebrew/lib/gnucobol"),
            ]
            for candidate in candidates:
                resolved = candidate.resolve()
                if resolved.is_dir():
                    env["COB_LIBRARY_PATH"] = str(resolved)
                    break

    return env
