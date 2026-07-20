from __future__ import annotations

import ast
import logging
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass
class StaticResult:
    """Result of static analysis validation."""

    available: bool
    passed: bool | None
    has_main_function: bool
    syntax_valid: bool
    linter_issues: list[str]
    structural_issues: list[str]
    error: str | None


def _check_syntax(python_code: str) -> tuple[bool, str | None]:
    """Check if Python code has valid syntax."""
    try:
        ast.parse(python_code)
        return True, None
    except SyntaxError as e:
        return False, f"Syntax error at line {e.lineno}: {e.msg}"


def _check_structure(python_code: str) -> tuple[bool, list[str]]:
    """Check structural properties of the code."""
    issues = []

    try:
        tree = ast.parse(python_code)
    except SyntaxError:
        return False, ["Could not parse code"]

    has_main = False
    has_main_guard = False

    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "main":
            has_main = True

        if isinstance(node, ast.If):
            test = node.test
            if isinstance(test, ast.Compare):
                if isinstance(test.left, ast.Name) and test.left.id == "__name__":
                    has_main_guard = True

    if not has_main:
        issues.append("Missing main() function")

    if not has_main_guard:
        issues.append("Missing if __name__ == '__main__' guard")

    for node in ast.walk(tree):
        if isinstance(node, ast.Global):
            issues.append(f"Uses global statement: {', '.join(node.names)}")

    return len(issues) == 0, issues


def _run_ruff(python_code: str) -> list[str]:
    """Run ruff linter on the code."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
        f.write(python_code)
        f.flush()
        tmp_path = f.name

    try:
        result = subprocess.run(
            [sys.executable, "-m", "ruff", "check", tmp_path, "--output-format=text"],
            capture_output=True,
            text=True,
            timeout=10,
        )

        issues = []
        for line in result.stdout.strip().split("\n"):
            if line and tmp_path in line:
                clean_line = line.replace(tmp_path, "code.py")
                issues.append(clean_line[:150])

        return issues[:10]

    except FileNotFoundError:
        return []
    except subprocess.TimeoutExpired:
        return ["Ruff timeout"]
    except Exception as e:
        logger.warning(f"Ruff check failed: {e}")
        return []
    finally:
        Path(tmp_path).unlink(missing_ok=True)


def _run_pyflakes(python_code: str) -> list[str]:
    """Run pyflakes on the code."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
        f.write(python_code)
        f.flush()
        tmp_path = f.name

    try:
        result = subprocess.run(
            [sys.executable, "-m", "pyflakes", tmp_path],
            capture_output=True,
            text=True,
            timeout=10,
        )

        issues = []
        for line in result.stdout.strip().split("\n"):
            if line and tmp_path in line:
                clean_line = line.replace(tmp_path, "code.py")
                issues.append(clean_line[:150])

        return issues[:10]

    except FileNotFoundError:
        return []
    except subprocess.TimeoutExpired:
        return ["Pyflakes timeout"]
    except Exception as e:
        logger.warning(f"Pyflakes check failed: {e}")
        return []
    finally:
        Path(tmp_path).unlink(missing_ok=True)


def run_static_validation(
    python_code: str,
    io_contract: dict | None = None,
) -> StaticResult:
    """
    Run static analysis on the generated Python code.
    
    Checks:
    - Syntax validity
    - Structural properties (main function, guard)
    - Linter issues (ruff, pyflakes)
    """
    syntax_valid, syntax_error = _check_syntax(python_code)

    if not syntax_valid:
        return StaticResult(
            available=True,
            passed=False,
            has_main_function=False,
            syntax_valid=False,
            linter_issues=[syntax_error or "Syntax error"],
            structural_issues=["Could not parse due to syntax error"],
            error=None,
        )

    structure_ok, structural_issues = _check_structure(python_code)

    ruff_issues = _run_ruff(python_code)
    pyflakes_issues = _run_pyflakes(python_code)

    all_linter_issues = ruff_issues + pyflakes_issues

    serious_issues = [
        i for i in all_linter_issues
        if any(
            x in i.lower()
            for x in ["undefined", "unused", "error", "invalid"]
        )
    ]

    has_main = "Missing main() function" not in structural_issues

    passed = (
        syntax_valid
        and has_main
        and len(serious_issues) == 0
        and len(structural_issues) <= 1
    )

    return StaticResult(
        available=True,
        passed=passed,
        has_main_function=has_main,
        syntax_valid=syntax_valid,
        linter_issues=all_linter_issues,
        structural_issues=structural_issues,
        error=None,
    )
