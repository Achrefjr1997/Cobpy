from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

from cobol_migrator.agent import run_migration

FIXTURES_DIR = Path(__file__).parent.parent / "fixtures"
HELLO_WORLD_CBL = FIXTURES_DIR / "hello_world.cbl"


@pytest.mark.slow
def test_hello_world_migration() -> None:
    """
    Integration test: migrate HELLO WORLD COBOL to Python.
    
    This test hits the real LLM API and verifies:
    - The agent completes within budget
    - At least one draft is produced
    - The final test run passes
    - The generated Python actually prints HELLO WORLD
    """
    cobol_source = HELLO_WORLD_CBL.read_text()

    events: list[tuple[str, dict]] = []

    def capture_event(event_type: str, payload: dict) -> None:
        events.append((event_type, payload))

    final_state = run_migration(
        cobol_source=cobol_source,
        source_type="snippet",
        source_ref=str(HELLO_WORLD_CBL),
        step_budget=25,
        emit=capture_event,
    )

    assert final_state.get("done") is True, "Migration should complete"
    assert final_state.get("error") is None, f"No error expected: {final_state.get('error')}"

    drafts = final_state.get("python_drafts", [])
    assert len(drafts) >= 1, "At least one draft should be created"

    test_runs = final_state.get("test_runs", [])
    assert len(test_runs) >= 1, "At least one test run should occur"
    assert test_runs[-1].passed is True, f"Final test should pass: {test_runs[-1].stderr}"

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
        assert "HELLO" in output or "WORLD" in output, \
            f"Output should contain HELLO/WORLD: {result.stdout}"

    event_types = [e[0] for e in events]
    assert "planner_decision" in event_types, "Should emit planner_decision events"
    assert "draft_created" in event_types, "Should emit draft_created events"
    assert "done" in event_types, "Should emit done event"


@pytest.mark.slow
def test_hello_world_cli() -> None:
    """Test the CLI entry point with HELLO WORLD."""
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "cobol_migrator.agent.cli",
            "--cobol-file",
            str(HELLO_WORLD_CBL),
            "--quiet",
        ],
        capture_output=True,
        text=True,
        timeout=120,
        cwd=FIXTURES_DIR.parent.parent,
    )

    assert result.returncode == 0, f"CLI should succeed: {result.stderr}"
    assert "def " in result.stdout or "print" in result.stdout, "Should output Python code"
