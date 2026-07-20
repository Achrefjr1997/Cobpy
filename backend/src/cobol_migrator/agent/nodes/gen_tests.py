from __future__ import annotations

import ast
import logging
import re
from typing import Any

from pydantic import BaseModel, Field

from cobol_migrator.agent.state import AgentState
from cobol_migrator.models import get_structured_model

logger = logging.getLogger(__name__)


def _validate_test_syntax(test_code: str) -> tuple[bool, str]:
    """
    Validate that test code is syntactically valid Python.
    Returns (is_valid, error_message).
    """
    try:
        ast.parse(test_code)
        return True, ""
    except SyntaxError as e:
        return False, f"Syntax error at line {e.lineno}: {e.msg}"


def _validate_test_structure(test_code: str) -> tuple[bool, list[str]]:
    """
    Validate that test code has required structure.
    Returns (is_valid, list_of_issues).
    """
    issues = []

    if "from main import" not in test_code and "import main" not in test_code:
        issues.append("Missing import from main.py")

    if "def test_" not in test_code:
        issues.append("No test functions found (must start with 'def test_')")

    if "subprocess" in test_code:
        issues.append("Uses subprocess (forbidden - use direct imports)")

    hallucination_patterns = [
        (r"import capsys", "capsys is a fixture, not an import"),
        (r"from pytest import capsys", "capsys is a fixture, not an import"),
        (r"capsys\s*=", "capsys must be a function parameter, not assigned"),
    ]

    for pattern, message in hallucination_patterns:
        if re.search(pattern, test_code):
            issues.append(message)

    return len(issues) == 0, issues


def _extract_test_functions(test_code: str) -> list[str]:
    """Extract test function names from test code."""
    return re.findall(r"def (test_\w+)\s*\(", test_code)


def _sanitize_test_code(test_code: str) -> str:
    """Clean up common issues in generated test code."""
    test_code = re.sub(r"^```python\s*\n?", "", test_code)
    test_code = re.sub(r"^```\s*\n?", "", test_code, flags=re.MULTILINE)
    test_code = re.sub(r"\n?```$", "", test_code)

    test_code = re.sub(r"import capsys\n?", "", test_code)
    test_code = re.sub(r"from pytest import capsys\n?", "", test_code)

    if "from main import" not in test_code and "import main" not in test_code:
        test_code = "from main import main\n\n" + test_code

    return test_code.strip()


class GeneratedTests(BaseModel):
    """Structured output from test generation LLM."""

    test_code: str = Field(description="Complete pytest test file content")
    rationale: str = Field(description="Brief explanation of test strategy")


GEN_TESTS_SYSTEM_PROMPT = """\
Generate simple, reliable pytest tests for this Python code translated from COBOL.

## Python Code to Test
```python
{python_code}
```

## Program Info
Summary: {program_summary}
Inputs: {inputs}
Outputs: {outputs}

{lessons_context}

{record_layout_info}

## OUTPUT METHOD ANALYSIS (follow this — do NOT guess)
{output_method_info}

## RULES - Follow EXACTLY

1. **Import**: `from main import main` (NEVER use subprocess)

2. **Fixtures are PARAMETERS, not imports**:
   - CORRECT: `def test_foo(capsys):` then `capsys.readouterr()`
   - WRONG: `import capsys` or `capsys = ...`

3. **Match the OUTPUT METHOD above**:
   - If output method is "stdout" → use `capsys` fixture, assert `captured.out`
   - If output method is "file" → check the EXACT output files listed above
   - If output method is "both" → check both
   - **NEVER assert that a file exists unless it is listed in "Output files" above**
   - **NEVER invent output filenames** — if the program prints to stdout, do NOT check for files

4. **For programs that READ input files** - the test environment already provides \
dummy input files in the working directory. Copy them into tmp_path:
```python
def test_main_runs(tmp_path, monkeypatch):
    import shutil, pathlib
    src_dir = pathlib.Path.cwd()
    for f in src_dir.iterdir():
        if f.suffix.upper() in (".DAT", ".TXT", ".DATA"):
            shutil.copy(f, tmp_path / f.name)
    monkeypatch.chdir(tmp_path)
    main()
```

5. **NEVER assert exact lengths, exact sizes, or hardcoded values**:
```python
# GOOD
assert len(captured.out.strip()) > 0
assert output_file.exists()

# BAD - NEVER do this
assert len(line) == 19
assert "35000" in content
```

## Generate exactly 2 tests:
1. `test_main_runs_without_error` - call main(), verify no exceptions
2. `test_produces_output` - verify output exists using the CORRECT method (stdout or file)

Keep tests SIMPLE. Two passing tests are better than three where one is brittle.
"""

FALLBACK_TEST_TEMPLATE = '''\
"""Auto-generated tests for COBOL migration."""
from main import main


def test_main_runs_without_error():
    """Test that the main function runs without raising exceptions."""
    main()


def test_main_produces_output(capsys):
    """Test that the code produces some output."""
    main()
    captured = capsys.readouterr()
    assert captured.out.strip(), "Expected some output"
'''

FALLBACK_FILE_IO_TEST_TEMPLATE = '''\
"""Auto-generated tests for COBOL migration with file I/O."""
import shutil
import pathlib
from main import main


def test_main_runs_with_files(tmp_path, monkeypatch):
    """Test that main runs when input files exist."""
    # Copy pre-generated dummy files into isolated tmp_path
    src_dir = pathlib.Path.cwd()
    for f in src_dir.iterdir():
        if f.suffix.upper() in (".DAT", ".TXT", ".DATA", ".INP", ".IN"):
            shutil.copy(f, tmp_path / f.name)
    monkeypatch.chdir(tmp_path)
    main()


def test_produces_output(tmp_path, monkeypatch):
    """Test that main produces output files or content."""
    src_dir = pathlib.Path.cwd()
    for f in src_dir.iterdir():
        if f.suffix.upper() in (".DAT", ".TXT", ".DATA", ".INP", ".IN"):
            shutil.copy(f, tmp_path / f.name)
    monkeypatch.chdir(tmp_path)
    before = set(tmp_path.iterdir())
    main()
    after = set(tmp_path.iterdir())
    new_files = after - before
    has_output = len(new_files) > 0
    has_content = any(f.stat().st_size > 0 for f in new_files) if new_files else False
    assert has_output or has_content, "Expected program to produce output"
'''


FALLBACK_FILE_IO_STDOUT_TEMPLATE = '''\
"""Auto-generated tests for COBOL migration (reads files, prints to stdout)."""
import shutil
import pathlib
from main import main


def test_main_runs_with_files(tmp_path, monkeypatch):
    """Test that main runs when input files exist."""
    src_dir = pathlib.Path.cwd()
    for f in src_dir.iterdir():
        if f.suffix.upper() in (".DAT", ".TXT", ".DATA", ".INP", ".IN"):
            shutil.copy(f, tmp_path / f.name)
    monkeypatch.chdir(tmp_path)
    main()


def test_produces_output(tmp_path, monkeypatch, capsys):
    """Test that main produces printed output."""
    src_dir = pathlib.Path.cwd()
    for f in src_dir.iterdir():
        if f.suffix.upper() in (".DAT", ".TXT", ".DATA", ".INP", ".IN"):
            shutil.copy(f, tmp_path / f.name)
    monkeypatch.chdir(tmp_path)
    main()
    captured = capsys.readouterr()
    assert len(captured.out.strip()) > 0, "Expected printed output"
'''


def _code_uses_file_io(python_code: str) -> bool:
    """Detect if the Python code does file I/O operations."""
    file_indicators = [
        "open(",
        "read_text",
        "write_text",
        ".read()",
        ".write(",
        "with open",
    ]
    code_lower = python_code.lower()
    return any(indicator.lower() in code_lower for indicator in file_indicators)


def _detect_output_method(python_code: str) -> str:
    """
    Detect how the program produces output: 'stdout', 'file', or 'both'.

    Looks at what the code actually does — print() means stdout,
    open(..., 'w') means file output.
    """
    has_print = "print(" in python_code
    # Detect file writes: open('...', 'w'), open('...', 'a'), .write(
    has_file_write = bool(
        re.search(r"open\s*\([^)]*['\"][wa]['\"]", python_code)
        or ".write(" in python_code
        or "write_text(" in python_code
    )
    if has_print and has_file_write:
        return "both"
    if has_file_write:
        return "file"
    return "stdout"


def _detect_output_files(python_code: str) -> list[str]:
    """Extract filenames the Python code opens for writing."""
    files = []
    # Match open('file', 'w') or open('file', 'a') within a single call
    for match in re.finditer(r"open\s*\(\s*['\"]([^'\"]+)['\"],\s*['\"]([^'\"]*)['\"]", python_code):
        mode = match.group(2)
        if "w" in mode or "a" in mode:
            files.append(match.group(1))
    return files


def _build_lessons_context(state: AgentState) -> str:
    """Build context from lessons learned about test generation."""
    lessons = state.get("lessons_learned", [])
    test_lessons = [lesson for lesson in lessons if "test" in lesson.lower()]

    if not test_lessons:
        return ""

    parts = ["## Lessons from previous test failures - APPLY THESE"]
    for lesson in test_lessons[-3:]:
        parts.append(f"- {lesson}")
    return "\n".join(parts)


def _build_record_layout_context(state: AgentState) -> str:
    """Build context about ALL COBOL record layouts for the LLM."""
    cobol_source = state.get("cobol_source", "")

    if not cobol_source:
        return ""

    try:
        from cobol_migrator.cobol_parser import extract_fd_records, extract_file_assignments

        assignments = extract_file_assignments(cobol_source)
        layouts = extract_fd_records(cobol_source)

        if not layouts:
            return ""

        parts = ["## COBOL Record Layouts (for reference only — do NOT assert exact lengths)"]
        for fd_name, layout in layouts.items():
            physical = None
            for logical, phys in assignments.items():
                if fd_name.upper() in logical or logical in fd_name.upper():
                    physical = phys
                    break
            label = physical or fd_name
            parts.append(f"\n**{label}** ({layout.total_length} chars per record):")
            for f in layout.fields:
                ftype = "numeric" if f.is_numeric else "alpha"
                parts.append(
                    f"  {f.name}: pos {f.offset}-{f.offset + f.length - 1} "
                    f"({f.length} chars, {ftype})"
                )

        parts.append("\nNote: input record length != output record length. Do NOT hardcode either.")
        return "\n".join(parts)

    except Exception as e:
        logger.warning(f"Failed to build record layout context: {e}")
        return ""


def gen_tests(state: AgentState) -> dict[str, Any]:
    """
    Generate pytest tests for the current draft using I/O contract.

    Includes validation to ensure generated tests are syntactically correct
    and don't contain common hallucination patterns. Falls back to safe
    templates if LLM output is invalid.
    """
    emit = state.get("emit", lambda t, p: None)

    drafts = state.get("python_drafts", [])
    if not drafts:
        logger.warning("gen_tests called with no drafts")
        return {"error": "No draft to test"}

    current_draft_id = state.get("current_draft_id")
    current_draft = next((d for d in drafts if d.id == current_draft_id), drafts[-1])
    python_code = current_draft.code

    io_contract = state.get("io_contract")
    program_summary = state.get("program_summary", "COBOL program")
    lessons_context = _build_lessons_context(state)
    record_layout_info = _build_record_layout_context(state)

    output_method = _detect_output_method(python_code)
    is_file_io = _code_uses_file_io(python_code)
    # Fallback: use file I/O template only if the program WRITES output files
    # If it only reads files but prints to stdout, use the stdout template
    if output_method in ("file", "both"):
        fallback_tests = FALLBACK_FILE_IO_TEST_TEMPLATE
    elif is_file_io:
        # Reads files but outputs to stdout — needs file setup + capsys
        fallback_tests = FALLBACK_FILE_IO_STDOUT_TEMPLATE
    else:
        fallback_tests = FALLBACK_TEST_TEMPLATE
    tests = fallback_tests

    if io_contract:
        inputs_str = ", ".join(
            f"{p['name']}: {p['type']}" for p in io_contract.get("inputs", [])
        ) or "None"
        outputs_str = ", ".join(
            f"{p['name']}: {p['type']}" for p in io_contract.get("outputs", [])
        ) or "stdout"

        # Detect how the program actually outputs results
        output_method = _detect_output_method(python_code)
        output_files = _detect_output_files(python_code)
        if output_method == "stdout":
            output_method_info = (
                "Output method: **STDOUT (print)**\n"
                "The program uses print() to display results. Use `capsys` fixture.\n"
                "Do NOT check for any output files — the program does not create them."
            )
        elif output_method == "file":
            files_list = ", ".join(output_files) if output_files else "unknown"
            output_method_info = (
                f"Output method: **FILE**\n"
                f"Output files: {files_list}\n"
                f"Check ONLY these files. Do NOT invent other filenames."
            )
        else:
            files_list = ", ".join(output_files) if output_files else "unknown"
            output_method_info = (
                f"Output method: **BOTH (stdout + file)**\n"
                f"Output files: {files_list}\n"
                f"The program prints AND writes files. Check either."
            )

        prompt = GEN_TESTS_SYSTEM_PROMPT.format(
            program_summary=program_summary,
            inputs=inputs_str,
            outputs=outputs_str,
            python_code=python_code[:6000],
            lessons_context=lessons_context,
            record_layout_info=record_layout_info,
            output_method_info=output_method_info,
        )

        try:
            model = get_structured_model("analyze", GeneratedTests)
            result: GeneratedTests = model.invoke(prompt)
            generated_tests = _sanitize_test_code(result.test_code)

            # Post-process: strip brittle length assertions
            generated_tests = _remove_brittle_assertions(generated_tests)

            syntax_valid, syntax_error = _validate_test_syntax(generated_tests)
            if not syntax_valid:
                logger.warning(f"Generated tests have syntax error: {syntax_error}")
                emit("test_generation_warning", {
                    "warning": f"LLM generated invalid syntax: {syntax_error}",
                    "using_fallback": True,
                })
            else:
                structure_valid, issues = _validate_test_structure(generated_tests)
                if not structure_valid:
                    logger.warning(f"Generated tests have structure issues: {issues}")
                    emit("test_generation_warning", {
                        "warning": f"LLM generated problematic tests: {', '.join(issues)}",
                        "using_fallback": True,
                    })
                else:
                    tests = generated_tests
                    test_funcs = _extract_test_functions(tests)
                    logger.info(
                        f"Generated valid tests with {len(test_funcs)} functions: "
                        f"{', '.join(test_funcs[:3])}"
                    )

        except Exception as e:
            logger.warning(f"Test generation LLM call failed: {e}, using fallback")
            emit("test_generation_warning", {
                "warning": f"LLM call failed: {str(e)[:100]}",
                "using_fallback": True,
            })
    else:
        logger.info("No I/O contract available, using fallback tests")

    emit("tests_generated", {"tests": tests})

    return {"generated_tests": tests}


def _remove_brittle_assertions(test_code: str) -> str:
    """Remove or comment out assertions that check exact lengths or hardcoded values."""
    lines = test_code.split("\n")
    cleaned = []
    for line in lines:
        stripped = line.strip()
        # Remove lines asserting exact len() == number
        if re.match(r'assert\s+len\(.+\)\s*==\s*\d+', stripped):
            cleaned.append(line.replace("assert", "# assert (removed: brittle length check)  # "))
            continue
        # Remove lines asserting exact string equality on output content
        if re.match(r'assert\s+\w+\s*==\s*["\']', stripped):
            cleaned.append(line.replace("assert", "# assert (removed: brittle exact match)  # "))
            continue
        cleaned.append(line)
    return "\n".join(cleaned)
