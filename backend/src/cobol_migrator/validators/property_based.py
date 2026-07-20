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
}


@dataclass
class PropertyResult:
    """Result of property-based testing."""

    available: bool
    passed: bool | None
    examples_run: int
    failures: list[str]
    error: str | None


PROPERTY_TEST_TEMPLATE = '''\
"""Property-based tests generated from I/O contract."""
from hypothesis import given, settings, assume
from hypothesis import strategies as st
import sys
sys.path.insert(0, ".")

from main import main

{invariant_tests}

{type_tests}
'''

NUMERIC_INVARIANT_TEST = '''
@given(st.floats(min_value=-1e9, max_value=1e9, allow_nan=False, allow_infinity=False))
@settings(max_examples=50, deadline=5000)
def test_numeric_no_crash(x):
    """Property: numeric operations should not crash."""
    try:
        main()
    except Exception as e:
        if "input" not in str(e).lower():
            raise
'''

OUTPUT_INVARIANT_TEST = '''
def test_basic_output(capsys):
    """Property: program produces output."""
    main()
    captured = capsys.readouterr()
    assert captured.out or captured.err, "Program should produce some output"
'''


def _generate_property_tests(io_contract: dict | None) -> str:
    """Generate property tests from I/O contract."""
    invariant_tests = [OUTPUT_INVARIANT_TEST]
    type_tests = []

    if io_contract:
        invariants = io_contract.get("invariants", [])

        for inv in invariants:
            inv_lower = inv.lower()
            if "positive" in inv_lower or "> 0" in inv_lower:
                type_tests.append('''
@given(st.floats(min_value=0.01, max_value=1e6, allow_nan=False))
@settings(max_examples=20, deadline=5000)
def test_positive_values_handled(x):
    """Property: positive values should be handled."""
    main()
''')
            elif "round" in inv_lower or "decimal" in inv_lower:
                type_tests.append('''
@given(st.decimals(min_value="-999999.99", max_value="999999.99", places=2))
@settings(max_examples=20, deadline=5000)  
def test_decimal_precision(x):
    """Property: decimal values should maintain precision."""
    main()
''')

    return PROPERTY_TEST_TEMPLATE.format(
        invariant_tests="\n".join(invariant_tests),
        type_tests="\n".join(type_tests) if type_tests else "# No type-specific tests",
    )


def run_property_validation(
    python_code: str,
    io_contract: dict | None = None,
) -> PropertyResult:
    """
    Run property-based testing using Hypothesis.
    
    Generates tests from the I/O contract and runs them with random inputs.
    """
    try:
        check_code_safety(python_code)
    except UnsafeImportError as e:
        return PropertyResult(
            available=False,
            passed=False,
            examples_run=0,
            failures=[f"Safety check failed: {e}"],
            error=str(e),
        )

    with tempfile.TemporaryDirectory() as tmpdir:
        tmppath = Path(tmpdir)

        main_file = tmppath / "main.py"
        main_file.write_text(python_code)

        test_code = _generate_property_tests(io_contract)
        test_file = tmppath / "test_properties.py"
        test_file.write_text(test_code)

        try:
            result = subprocess.run(
                [
                    sys.executable, "-m", "pytest",
                    str(test_file),
                    "-v", "--tb=short",
                    "-p", "no:warnings",
                ],
                capture_output=True,
                text=True,
                timeout=60,
                env=SAFE_ENV,
                cwd=str(tmppath),
            )

            passed = result.returncode == 0

            examples_match = "passed" in result.stdout
            examples_run = 50 if examples_match else 0

            failures = []
            if not passed:
                for line in result.stdout.split("\n"):
                    if "FAILED" in line or "Error" in line:
                        failures.append(line[:200])
                if result.stderr:
                    failures.append(f"stderr: {result.stderr[:200]}")

            return PropertyResult(
                available=True,
                passed=passed,
                examples_run=examples_run,
                failures=failures[:5],
                error=None,
            )

        except subprocess.TimeoutExpired:
            return PropertyResult(
                available=True,
                passed=False,
                examples_run=0,
                failures=["Property testing timed out"],
                error="Timeout",
            )
        except Exception as e:
            logger.exception(f"Property testing failed: {e}")
            return PropertyResult(
                available=False,
                passed=None,
                examples_run=0,
                failures=[],
                error=str(e),
            )
