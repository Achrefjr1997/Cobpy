from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from cobol_migrator.agent.state import AgentState
from cobol_migrator.db import save_migration

logger = logging.getLogger(__name__)


def finalize(state: AgentState) -> dict[str, Any]:
    """
    Finalize the migration run.
    
    - Marks the run as done
    - Saves to SQLite database
    - Emits error event if there was an error
    - Emits done event with final state summary
    """
    emit = state.get("emit", lambda t, p: None)
    error = state.get("error")

    if error:
        emit("error", {"message": error})
        logger.error(f"Migration finalized with error: {error}")

    drafts = state.get("python_drafts", [])
    test_runs = state.get("test_runs", [])
    current_draft_id = state.get("current_draft_id")

    final_passed = False
    if test_runs:
        final_passed = test_runs[-1].passed

    validation_scores = state.get("validation_scores", {})
    validation_verdict = validation_scores.get("verdict")

    # Check for external dependency - this is a special case
    external_dependency = state.get("external_dependency_detected", False)
    external_resource = state.get("external_resource")

    if error:
        verdict = "errored"
    elif validation_verdict in ("equivalent", "likely_equivalent"):
        verdict = validation_verdict
    elif final_passed:
        verdict = validation_verdict if validation_verdict else "passed"
    elif external_dependency:
        # External dependency detected - code is likely correct but can't be tested
        verdict = "partial"
        logger.info(
            f"External dependency ({external_resource}) - marking as partial instead of failed"
        )
    elif drafts:
        verdict = validation_verdict if validation_verdict else "failed"
    else:
        verdict = "no_translation"

    run_id = state.get("run_id")
    if run_id:
        try:
            final_draft = next((d for d in drafts if d.id == current_draft_id), None)
            if final_draft is None and drafts:
                final_draft = drafts[-1]

            created_at_str = state.get("created_at")
            if created_at_str:
                created_at = datetime.fromisoformat(created_at_str)
            else:
                created_at = datetime.now()

            save_migration(
                run_id=run_id,
                source_type=state.get("source_type", "snippet"),
                source_ref=state.get("source_ref", ""),
                cobol_source=state.get("cobol_source", ""),
                final_code=final_draft.code if final_draft else None,
                final_tests=state.get("generated_tests"),
                validation=validation_scores if validation_scores else None,
                verdict=verdict,
                event_trace=None,
                step_count=state.get("step_count", 0),
                draft_count=len(drafts),
                test_count=len(test_runs),
                lessons=list(state.get("lessons_learned", [])),
                program_summary=state.get("program_summary"),
                error=error,
                created_at=created_at,
            )
            logger.info(f"Migration {run_id} saved to database")
        except Exception as e:
            logger.exception(f"Failed to save migration to database: {e}")

    confidence = validation_scores.get("confidence")

    done_payload: dict[str, Any] = {
        "final_draft_id": current_draft_id,
        "total_drafts": len(drafts),
        "total_test_runs": len(test_runs),
        "final_test_passed": final_passed,
        "verdict": verdict,
        "confidence": confidence,
        "step_count": state.get("step_count", 0),
        "validation_verdict": validation_verdict,
    }

    # Collect all issues for partial/failed verdicts
    all_issues: list[str] = []

    if external_dependency:
        done_payload["external_dependency"] = True
        done_payload["external_resource"] = external_resource
        all_issues.append(
            f"Requires external resource '{external_resource}' which cannot be provided "
            f"in test environment"
        )

    # Add test issues
    test_issues = list(state.get("test_issues", []))
    if test_issues:
        all_issues.extend(test_issues)

    # Note if dummy files were used for testing
    if state.get("create_dummy_files") and state.get("dummy_files_created"):
        done_payload["used_dummy_files"] = True
        all_issues.append(
            "Tests ran with auto-generated dummy input files - results may differ "
            "with real production data"
        )

    # Add issues to payload if any exist
    if all_issues:
        # Deduplicate while preserving order
        done_payload["issues"] = list(dict.fromkeys(all_issues))

    emit("done", done_payload)

    logger.info(
        f"Migration finalized: verdict={verdict}, drafts={len(drafts)}, "
        f"test_runs={len(test_runs)}, steps={state.get('step_count', 0)}"
    )

    return {"done": True}
