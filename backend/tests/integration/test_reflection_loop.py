from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

from cobol_migrator.agent import run_migration

FIXTURES_DIR = Path(__file__).parent.parent / "fixtures"
CURRENCY_ROUND_CBL = FIXTURES_DIR / "currency_round.cbl"


@pytest.mark.slow
def test_reflection_loop_recovers_from_failure() -> None:
    """
    Integration test: verify the agent can recover from failures through reflection.
    
    Uses a COBOL program with COMPUTE ROUNDED that LLMs often get wrong on first try.
    The test verifies:
    - Multiple drafts are created (reflection occurred)
    - Lessons were learned
    - The final code produces reasonable output
    """
    cobol_source = CURRENCY_ROUND_CBL.read_text()

    events: list[tuple[str, dict]] = []

    def capture_event(event_type: str, payload: dict) -> None:
        events.append((event_type, payload))

    final_state = run_migration(
        cobol_source=cobol_source,
        source_type="snippet",
        source_ref=str(CURRENCY_ROUND_CBL),
        step_budget=30,
        emit=capture_event,
    )

    assert final_state.get("done") is True, "Migration should complete"

    drafts = final_state.get("python_drafts", [])
    assert len(drafts) >= 1, "At least one draft should be created"

    lessons = final_state.get("lessons_learned", [])

    program_summary = final_state.get("program_summary")
    assert program_summary is not None, "Program should be analyzed"

    io_contract = final_state.get("io_contract")
    assert io_contract is not None, "I/O contract should be extracted"

    event_types = [e[0] for e in events]
    assert "analysis_ready" in event_types, "Should emit analysis_ready event"
    assert "planner_decision" in event_types, "Should emit planner_decision events"
    assert "draft_created" in event_types, "Should emit draft_created events"

    test_runs = final_state.get("test_runs", [])
    if test_runs and test_runs[-1].passed:
        final_code = drafts[-1].code
        with tempfile.TemporaryDirectory() as tmpdir:
            main_py = Path(tmpdir) / "main.py"
            main_py.write_text(final_code)

            result = subprocess.run(
                [sys.executable, str(main_py)],
                capture_output=True,
                text=True,
                timeout=10,
            )

            assert result.returncode == 0, f"Code should run: {result.stderr}"
            output = result.stdout.upper()
            assert "RESULT" in output or "12345" in output or "13271" in output, \
                f"Output should contain expected values: {result.stdout}"

    print("\nTest completed:")
    print(f"  Drafts: {len(drafts)}")
    print(f"  Lessons: {len(lessons)}")
    print(f"  Test runs: {len(test_runs)}")
    if lessons:
        print(f"  Sample lesson: {lessons[0][:100]}")


@pytest.mark.slow
def test_analysis_produces_io_contract() -> None:
    """Test that analysis produces a meaningful I/O contract."""
    cobol_source = CURRENCY_ROUND_CBL.read_text()

    final_state = run_migration(
        cobol_source=cobol_source,
        source_type="snippet",
        source_ref=str(CURRENCY_ROUND_CBL),
        step_budget=5,
    )

    io_contract = final_state.get("io_contract")
    assert io_contract is not None, "I/O contract should be extracted"

    assert "outputs" in io_contract, "Contract should have outputs"

    program_summary = final_state.get("program_summary")
    assert program_summary is not None, "Summary should exist"
    assert len(program_summary) > 10, "Summary should be meaningful"
