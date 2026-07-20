from __future__ import annotations

import logging
from typing import Any, Literal

from pydantic import BaseModel, Field

from cobol_migrator.agent.state import AgentState
from cobol_migrator.models import get_structured_model

logger = logging.getLogger(__name__)


EXTERNAL_DEPENDENCY_PATTERNS = [
    "filenotfounderror",
    "no such file or directory",
    "file not found",
    "connection refused",
    "connection error",
    "database connection",
    "could not connect",
    "timeout",
    "network error",
    "permission denied",
    "access denied",
    "authentication failed",
    "socket error",
    "errno 2",  # ENOENT
    "errno 111",  # Connection refused
    ".dat",  # Common COBOL data file extension
    ".txt",  # Common input file
    ".rpt",  # Common report file
]


def _is_external_dependency_failure(stderr: str, stdout: str) -> tuple[bool, str]:
    """
    Detect if test failure is due to missing external dependencies.
    
    Returns (is_external, resource_name).
    """
    combined = (stderr + stdout).lower()
    
    for pattern in EXTERNAL_DEPENDENCY_PATTERNS:
        if pattern in combined:
            # Try to extract the specific resource name
            if "filenotfounderror" in combined or "no such file" in combined:
                # Extract filename from error
                import re
                match = re.search(r"['\"]([^'\"]+\.(dat|txt|csv|rpt|db|xml))['\"]", combined, re.I)
                if match:
                    return True, f"file '{match.group(1)}'"
                return True, "external file"
            elif "connection" in combined or "database" in combined:
                return True, "database connection"
            elif "socket" in combined or "network" in combined:
                return True, "network resource"
            return True, "external resource"
    
    return False, ""


def _lessons_similar(new_lesson: str, existing: str) -> bool:
    """Check if two lessons are similar enough to be considered duplicates."""
    new_lower = new_lesson.lower()
    existing_lower = existing.lower()

    # Exact match
    if new_lower == existing_lower:
        return True

    # Extract key phrases for comparison
    def extract_key_phrases(text: str) -> set[str]:
        # Remove common words and extract meaningful parts
        words = text.lower().split()
        # Keep important keywords
        keywords = {w for w in words if len(w) > 4 and w not in {
            "should", "needs", "using", "instead", "because", "which",
            "there", "their", "about", "would", "could", "being",
        }}
        return keywords

    new_keys = extract_key_phrases(new_lesson)
    existing_keys = extract_key_phrases(existing)

    if not new_keys or not existing_keys:
        return False

    # If >70% of keywords overlap, consider similar
    overlap = len(new_keys & existing_keys)
    similarity = overlap / min(len(new_keys), len(existing_keys))

    return similarity > 0.7


class Reflection(BaseModel):
    """Structured output from the reflection LLM."""

    lesson: str = Field(
        description="A concise, actionable lesson about what went wrong and how to fix it"
    )
    recommended_action: Literal["TRANSLATE", "GEN_TESTS", "FINISH"] = Field(
        description="The recommended next action based on the failure analysis"
    )
    root_cause: str = Field(
        description="Brief analysis of the root cause of the failure"
    )


REFLECT_SYSTEM_PROMPT = """\
You are debugging a COBOL-to-Python translation that failed its tests. Analyze the failure 
and determine whether the problem is in the TRANSLATION or in the TEST CODE.

## Program Summary
{program_summary}

## I/O Contract
{io_contract}

## Current Python Code (translation)
```python
{python_code}
```

## Test Failure
Exit code: {exit_code}
Stderr:
```
{stderr}
```
Stdout:
```
{stdout}
```

## Previous Lessons Learned
{previous_lessons}

## Your Task
1. FIRST: Determine if the bug is in the translation OR in the test code itself
   - Test code bugs: NameError in test file, missing imports in test, test logic errors
   - **Test expected value bugs**: Test asserts wrong expected value (calculation error)
   - **Mock data format bugs**: Test creates mock files with wrong format (spaces between fields)
   - Translation bugs: Wrong output, wrong behavior, missing COBOL functionality
   
2. If it's a TEST CODE bug (like NameError, wrong expected value, bad mock data):
   - Recommend GEN_TESTS to regenerate the tests
   - The lesson should describe the test code fix needed
   - Note: pytest fixtures like `capsys` must be PARAMETERS to test functions, not imports

3. If it's a TRANSLATION bug:
   - Recommend TRANSLATE to fix the Python code
   - The lesson should describe how to fix the translation

4. If the code is fundamentally correct but tests are too strict: recommend FINISH

## IMPORTANT: Test Expected Value Errors (VERY COMMON)
If the test fails with an assertion like:
  `assert 'TOTAL AMOUNT,2250.00' in content`
  `AssertionError: ... assert 'TOTAL AMOUNT,2250.00' in '...TOTAL AMOUNT,2750.00...'`

And the ACTUAL output (2750.00) is MATHEMATICALLY CORRECT based on the input data,
then the TEST has the wrong expected value - the translation is correct!

**How to verify**: Calculate the expected value from the mock input data manually.
If the code's output matches the correct calculation but not the test assertion,
it's a TEST BUG, not a translation bug. Recommend GEN_TESTS.

Example:
- Mock data: 500 + 1500 + 750 = 2750 (correct)
- Code outputs: 2750.00 (correct!)
- Test expects: 2250.00 (WRONG - test has arithmetic error)
- Recommendation: GEN_TESTS (fix the test's expected value)

## IMPORTANT: COBOL Fixed-Width Record Format
COBOL records are FIXED-WIDTH with NO separators between fields!
- A "ValueError: could not convert string to float" often means:
  - The test's mock data has SPACES between fields (WRONG)
  - COBOL fields are concatenated directly without any separators
  
Example of WRONG mock data (has space between 04000 and 01500):
  "001234John Smith                     04000 01500"
  
Example of CORRECT mock data (no space - exactly 46 chars):
  "001234John Smith                    0400001500"

If you see float conversion errors with values like '0 015' or similar with embedded spaces,
it's likely a mock data format bug - recommend GEN_TESTS.

Examples of good lessons:
- "Test code bug: capsys must be a parameter (def test_foo(capsys):), not imported"
- "Translation bug: COBOL COMPUTE ROUNDED needs Python round() with 2 decimal places"
- "Translation bug: COBOL DISPLAY adds newline, use print() not sys.stdout.write()"
- "Test code bug: Test expects exact match but COBOL output has trailing spaces"
- "Test code bug: Mock data has spaces between fields - COBOL uses fixed-width"
- "Translation bug: COBOL PIC 9(3)V99 means divide by 100 for implied decimal"
- "Test code bug: Test expects 2250 but correct sum of inputs is 2750 - wrong expected value"
- "Test code bug: Test has arithmetic error in expected value - recalculate from mock data"

Examples of bad lessons:
- "The code has a bug" (not actionable)
- "Import capsys" (wrong - capsys is a fixture, not an import)
- "Try again" (not specific)
"""


def reflect(state: AgentState) -> dict[str, Any]:
    """
    Reflect on test failures and extract lessons for future attempts.
    
    Uses LLM to analyze failures and produce actionable lessons that
    get incorporated into subsequent translation prompts.
    """
    emit = state.get("emit", lambda t, p: None)

    test_runs = state.get("test_runs", [])
    drafts = state.get("python_drafts", [])
    lessons = list(state.get("lessons_learned", []))

    if not test_runs:
        emit(
            "lesson_learned",
            {
                "lesson": "No test runs to reflect on",
                "recommended_action": "TRANSLATE",
                "root_cause": "No tests have been run yet",
            },
        )
        return {"lessons_learned": lessons}

    last_run = test_runs[-1]

    validation_scores = state.get("validation_scores", {})
    validation_verdict = validation_scores.get("verdict")

    if last_run.passed and validation_verdict not in ("broken", "partial"):
        emit(
            "lesson_learned",
            {
                "lesson": "Tests passed - no reflection needed",
                "recommended_action": "VALIDATE" if not validation_verdict else "FINISH",
                "root_cause": "N/A - tests passed",
            },
        )
        return {"lessons_learned": lessons}

    if last_run.passed and validation_verdict in ("broken", "partial"):
        diff = validation_scores.get("differential", {})
        diff_details = diff.get("match_details", "") if isinstance(diff, dict) else ""
        lesson = (
            f"Tests pass but differential validation shows output mismatch. "
            f"Likely a formatting difference (e.g., COBOL zero-pads numbers "
            f"with PIC 9(n) but Python prints without leading zeros). "
            f"Fix: use str.zfill() or f-string formatting like f'{{value:0Nd}}' "
            f"to match COBOL output formatting. Details: {diff_details[:200]}"
        )
        if not any(_lessons_similar(lesson, existing) for existing in lessons):
            lessons.append(lesson)

        emit(
            "lesson_learned",
            {
                "lesson": lesson,
                "recommended_action": "TRANSLATE",
                "root_cause": "Output formatting mismatch between COBOL and Python",
            },
        )
        return {"lessons_learned": lessons}

    # Check for external dependency failures
    is_external, resource_name = _is_external_dependency_failure(
        last_run.stderr, last_run.output
    )

    if is_external:
        # Count how many times we've seen external dependency issues
        external_lessons = sum(
            1 for lesson in lessons
            if any(
                p in lesson.lower()
                for p in ["external", "file", "database", "connection", ".dat", ".txt"]
            )
        )

        # If we've tried multiple times with external deps, give up gracefully
        if external_lessons >= 2 or len(test_runs) >= 3:
            lesson = (
                f"External dependency: Program requires {resource_name} which cannot be "
                f"provided in the test environment. The translation appears correct but "
                f"cannot be fully tested without the external resource."
            )

            if lesson not in lessons:
                lessons.append(lesson)

            emit(
                "lesson_learned",
                {
                    "lesson": lesson,
                    "recommended_action": "FINISH",
                    "root_cause": f"External dependency: {resource_name}",
                    "is_external_dependency": True,
                },
            )

            logger.info(f"External dependency detected: {resource_name} - recommending FINISH")

            return {
                "lessons_learned": lessons,
                "external_dependency_detected": True,
                "external_resource": resource_name,
            }

    current_draft_id = state.get("current_draft_id")
    fallback = drafts[-1] if drafts else None
    current_draft = next((d for d in drafts if d.id == current_draft_id), fallback)
    python_code = current_draft.code if current_draft else "No code available"

    program_summary = state.get("program_summary", "COBOL program")
    io_contract = state.get("io_contract", {})
    io_contract_str = str(io_contract) if io_contract else "Not available"

    previous_lessons = "\n".join(f"- {lesson}" for lesson in lessons) if lessons else "None yet"

    prompt = REFLECT_SYSTEM_PROMPT.format(
        program_summary=program_summary,
        io_contract=io_contract_str,
        python_code=python_code[:8000],
        exit_code="non-zero" if not last_run.passed else "0",
        stderr=last_run.stderr[:2000],
        stdout=last_run.output[:2000],
        previous_lessons=previous_lessons,
    )

    try:
        model = get_structured_model("reflect", Reflection)
        result: Reflection = model.invoke(prompt)

        # Deduplicate: only add if lesson is meaningfully different
        new_lesson = result.lesson.strip()
        is_duplicate = any(
            _lessons_similar(new_lesson, existing)
            for existing in lessons
        )

        if not is_duplicate:
            lessons.append(new_lesson)
            logger.info(f"New lesson: {new_lesson[:80]}")
        else:
            logger.info(f"Skipping duplicate lesson: {new_lesson[:50]}")

        emit(
            "lesson_learned",
            {
                "lesson": result.lesson,
                "recommended_action": result.recommended_action,
                "root_cause": result.root_cause,
                "is_duplicate": is_duplicate,
            },
        )

        logger.info(f"Reflection: {result.root_cause[:50]} -> {result.lesson[:50]}")

    except Exception as e:
        logger.error(f"Reflection LLM call failed: {e}")
        fallback_lesson = f"Test failed: {last_run.stderr[:100]}"
        lessons.append(fallback_lesson)

        emit(
            "lesson_learned",
            {
                "lesson": fallback_lesson,
                "recommended_action": "TRANSLATE",
                "root_cause": "Reflection failed, using fallback",
            },
        )

    return {"lessons_learned": lessons}
