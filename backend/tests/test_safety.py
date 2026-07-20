from __future__ import annotations

import pytest

from cobol_migrator.safety import UnsafeImportError, check_code_safety, truncate_output


class TestCheckCodeSafety:
    def test_safe_code_passes(self) -> None:
        """Safe code should pass without raising."""
        safe_code = '''
def main():
    x = 1 + 2
    print(f"Result: {x}")

if __name__ == "__main__":
    main()
'''
        check_code_safety(safe_code)

    def test_safe_imports_pass(self) -> None:
        """Safe standard library imports should pass."""
        code = '''
import math
from decimal import Decimal
from typing import List

def main():
    print(math.sqrt(2))
'''
        check_code_safety(code)

    def test_os_import_blocked(self) -> None:
        """Direct os import should be blocked."""
        code = "import os\nos.system('ls')"
        with pytest.raises(UnsafeImportError) as exc_info:
            check_code_safety(code)
        assert "os" in str(exc_info.value)

    def test_subprocess_import_blocked(self) -> None:
        """subprocess import should be blocked."""
        code = "import subprocess"
        with pytest.raises(UnsafeImportError):
            check_code_safety(code)

    def test_from_os_import_blocked(self) -> None:
        """from os import should be blocked."""
        code = "from os import path"
        with pytest.raises(UnsafeImportError):
            check_code_safety(code)

    def test_socket_import_blocked(self) -> None:
        """socket import should be blocked."""
        code = "import socket"
        with pytest.raises(UnsafeImportError):
            check_code_safety(code)

    def test_exec_call_blocked(self) -> None:
        """exec() call should be blocked."""
        code = "exec('print(1)')"
        with pytest.raises(UnsafeImportError) as exc_info:
            check_code_safety(code)
        assert "exec" in str(exc_info.value)

    def test_eval_call_blocked(self) -> None:
        """eval() call should be blocked."""
        code = "x = eval('1+1')"
        with pytest.raises(UnsafeImportError):
            check_code_safety(code)

    def test_syntax_error_handled(self) -> None:
        """Syntax errors should be handled gracefully."""
        bad_code = "def foo(:\n  pass"
        check_code_safety(bad_code)


class TestTruncateOutput:
    def test_short_text_unchanged(self) -> None:
        """Short text should pass through unchanged."""
        text = "Hello, World!"
        assert truncate_output(text) == text

    def test_long_text_truncated(self) -> None:
        """Long text should be truncated with marker."""
        text = "x" * 10000
        result = truncate_output(text, max_bytes=100)
        assert len(result.encode()) <= 120
        assert "[truncated]" in result

    def test_unicode_handled(self) -> None:
        """Unicode text should be handled correctly."""
        text = "Hello 🌍" * 1000
        result = truncate_output(text, max_bytes=100)
        assert "[truncated]" in result
