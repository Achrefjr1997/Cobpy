from __future__ import annotations

import logging
from typing import Any

from cobol_migrator.agent.state import AgentState, TestRun
from cobol_migrator.test_environment import run_isolated_tests

logger = logging.getLogger(__name__)


def run_tests(state: AgentState) -> dict[str, Any]:
    """
    Execute tests against the current draft in an isolated environment.
    
    Uses a complete isolated test environment with:
    - Temporary directory for all files
    - Proper Python environment variables
    - Optional dummy file creation for file-dependent programs
    - Automatic cleanup on success
    """
    emit = state.get("emit", lambda t, p: None)
    run_logger = state.get("_run_logger")

    drafts = state.get("python_drafts", [])
    if not drafts:
        logger.warning("run_tests called with no drafts")
        return {"error": "No draft to test"}

    current_draft_id = state.get("current_draft_id")
    current_draft = next((d for d in drafts if d.id == current_draft_id), drafts[-1])
    python_code = current_draft.code

    generated_tests = state.get("generated_tests")
    if not generated_tests:
        logger.warning("run_tests called with no generated tests")
        return {"error": "No tests generated"}

    # Get configuration
    should_create_dummy_files = state.get("create_dummy_files", False)
    cobol_source = state.get("cobol_source", "")
    io_contract = state.get("io_contract")
    program_summary = state.get("program_summary")

    # Emit start event
    emit(
        "test_started",
        {
            "draft_id": current_draft.id,
            "create_dummy_files": should_create_dummy_files,
        },
    )

    # Run tests in isolated environment
    result = run_isolated_tests(
        python_code=python_code,
        test_code=generated_tests,
        cobol_source=cobol_source if should_create_dummy_files else None,
        io_contract=io_contract if should_create_dummy_files else None,
        create_dummy_files_flag=should_create_dummy_files,
        timeout=60,
        cleanup_on_success=True,
        program_summary=program_summary if should_create_dummy_files else None,
    )

    # Log to run logger if available
    if run_logger is not None:
        run_logger.log_test_execution(
            draft_id=current_draft.id,
            python_code=python_code,
            test_code=generated_tests,
            stdout=result.stdout,
            stderr=result.stderr,
            passed=result.passed,
            duration_ms=result.duration_ms,
        )

    # Create test run record
    test_run = TestRun(
        draft_id=current_draft.id,
        passed=result.passed,
        output=result.stdout,
        stderr=result.stderr,
        duration_ms=result.duration_ms,
    )

    # Build event payload
    event_payload: dict[str, Any] = {
        "draft_id": test_run.draft_id,
        "passed": test_run.passed,
        "output": test_run.output,
        "stderr": test_run.stderr,
        "duration_ms": test_run.duration_ms,
    }

    # Add issues if any were detected
    if result.issues:
        event_payload["issues"] = result.issues

    # Add dummy files info if used
    if result.dummy_files_created:
        event_payload["dummy_files_used"] = True
        event_payload["dummy_files_count"] = len(result.dummy_files_created)
        emit(
            "dummy_files_created",
            {
                "files": [f.split("/")[-1] for f in result.dummy_files_created],
                "count": len(result.dummy_files_created),
            },
        )
        logger.info(f"Created {len(result.dummy_files_created)} dummy files for testing")

    # Add safety error if present
    if result.safety_error:
        event_payload["safety_error"] = result.safety_error

    emit("test_run", event_payload)

    status = "PASSED" if result.passed else "FAILED"
    logger.info(f"Test run {status} for draft {current_draft.id} in {result.duration_ms}ms")

    if result.issues:
        logger.info(f"Issues detected: {result.issues}")

    # Update state
    existing_runs = list(state.get("test_runs", []))
    existing_runs.append(test_run)

    result_dict: dict[str, Any] = {
        "test_runs": existing_runs,
    }

    # Track issues for final reporting
    if result.issues:
        existing_issues = list(state.get("test_issues", []))
        existing_issues.extend(result.issues)
        # Deduplicate issues
        result_dict["test_issues"] = list(dict.fromkeys(existing_issues))

    # Track dummy files created
    if result.dummy_files_created:
        existing_dummy = list(state.get("dummy_files_created", []))
        existing_dummy.extend(result.dummy_files_created)
        result_dict["dummy_files_created"] = existing_dummy

    return result_dict
