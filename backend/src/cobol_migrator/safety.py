from __future__ import annotations

import ast
import logging

from cobol_migrator.errors import SafetyError

logger = logging.getLogger(__name__)

BLOCKED_MODULES = frozenset({
    "os",
    "subprocess",
    "socket",
    "ctypes",
    "shutil",
    "pathlib",
    "requests",
    "urllib",
    "multiprocessing",
    "ftplib",
    "telnetlib",
    "pickle",
    "shelve",
    "marshal",
    "tempfile",
    "glob",
    "importlib",
    "builtins",
    "sys",
    "code",
    "codeop",
    "compile",
    "exec",
    "eval",
})


class UnsafeImportError(SafetyError):
    """Raised when generated code imports a blocked module."""

    def __init__(self, module_name: str) -> None:
        self.module_name = module_name
        super().__init__(f"Unsafe import detected: {module_name}")


def check_code_safety(python_source: str) -> None:
    """
    Check generated Python code for unsafe imports.
    
    Raises UnsafeImportError if any blocked module is imported.
    This is a defense-in-depth measure; generated code also runs
    in a sandbox with restricted environment.
    """
    try:
        tree = ast.parse(python_source)
    except SyntaxError as e:
        logger.warning(f"Failed to parse generated code for safety check: {e}")
        return

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                root_module = alias.name.split(".")[0]
                if root_module in BLOCKED_MODULES:
                    raise UnsafeImportError(alias.name)

        elif isinstance(node, ast.ImportFrom):
            if node.module:
                root_module = node.module.split(".")[0]
                if root_module in BLOCKED_MODULES:
                    raise UnsafeImportError(node.module)

        elif isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name):
                if node.func.id in ("exec", "eval", "compile", "__import__"):
                    raise UnsafeImportError(f"dangerous builtin: {node.func.id}")


def truncate_output(text: str, max_bytes: int = 8192) -> str:
    """Truncate output to prevent state bloat."""
    encoded = text.encode("utf-8", errors="replace")
    if len(encoded) <= max_bytes:
        return text
    truncated = encoded[:max_bytes].decode("utf-8", errors="replace")
    return truncated + "\n... [truncated]"
