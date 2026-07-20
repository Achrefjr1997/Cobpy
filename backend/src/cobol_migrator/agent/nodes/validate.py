from __future__ import annotations

import logging
from dataclasses import asdict
from typing import Any

from cobol_migrator.agent.state import AgentState
from cobol_migrator.validators import (
    compute_verdict,
    run_differential_validation,
    run_llm_judge_validation,
    run_property_validation,
    run_static_validation,
)

logger = logging.getLogger(__name__)


def _code_uses_file_io(python_code: str) -> bool:
    """Check if the Python code uses file I/O operations."""
    file_indicators = ["open(", "read_text", "write_text", ".read()", ".write(", "with open"]
    code_lower = python_code.lower()
    return any(indicator.lower() in code_lower for indicator in file_indicators)


def validate(state: AgentState) -> dict[str, Any]:
    """
    Run the full validation stack on the current draft.

    Flow:
    1. COBOL was already validated and its output captured in validate_cobol step
    2. Python tests were already run in run_tests step
    3. Now compare outputs (differential) and run remaining validators
    4. Combine into verdict with confidence score
    """
    emit = state.get("emit", lambda t, p: None)

    drafts = state.get("python_drafts", [])
    if not drafts:
        logger.warning("validate called with no drafts")
        return {"error": "No draft to validate"}

    current_draft_id = state.get("current_draft_id")
    current_draft = next((d for d in drafts if d.id == current_draft_id), drafts[-1])
    python_code = current_draft.code
    cobol_source = state.get("cobol_source", "")
    io_contract = state.get("io_contract")

    used_dummy_files = state.get("create_dummy_files", False)
    is_file_io_program = _code_uses_file_io(python_code)

    logger.info(f"Running validation stack on draft {current_draft.id}")

    differential_result = None
    property_result = None
    judge_result = None
    static_result = None

    # Differential: compare COBOL and Python outputs
    # COBOL was already validated in the validate_cobol step
    try:
        logger.info("Running differential validation (COBOL vs Python output comparison)...")
        differential_result = run_differential_validation(cobol_source, python_code)
        logger.info(
            f"Differential: available={differential_result.available}, "
            f"passed={differential_result.passed}"
        )
    except Exception as e:
        logger.exception(f"Differential validation error: {e}")

    if is_file_io_program or used_dummy_files:
        logger.info(
            "Skipping property-based validation (file-dependent program requires input files)"
        )
        property_result = None
    else:
        try:
            logger.info("Running property-based validation...")
            property_result = run_property_validation(python_code, io_contract)
            logger.info(
                f"Property: available={property_result.available}, "
                f"passed={property_result.passed}"
            )
        except Exception as e:
            logger.exception(f"Property validation error: {e}")

    try:
        logger.info("Running LLM judge validation...")
        judge_result = run_llm_judge_validation(cobol_source, python_code)
        logger.info(
            f"LLM Judge: available={judge_result.available}, "
            f"score={judge_result.score}"
        )
    except Exception as e:
        logger.exception(f"LLM judge validation error: {e}")

    try:
        logger.info("Running static analysis validation...")
        static_result = run_static_validation(python_code, io_contract)
        logger.info(
            f"Static: available={static_result.available}, "
            f"passed={static_result.passed}"
        )
    except Exception as e:
        logger.exception(f"Static analysis error: {e}")

    scorecard = compute_verdict(
        differential=differential_result,
        property_based=property_result,
        llm_judge=judge_result,
        static_analysis=static_result,
    )

    logger.info(f"Validation verdict: {scorecard.verdict} (confidence: {scorecard.confidence})")

    scores_summary = {
        "differential": (
            {"available": differential_result.available, "passed": differential_result.passed}
            if differential_result
            else None
        ),
        "property": (
            {"available": property_result.available, "passed": property_result.passed}
            if property_result
            else None
        ),
        "llm_judge": (
            {"available": judge_result.available, "score": judge_result.score}
            if judge_result
            else None
        ),
        "static": (
            {"available": static_result.available, "passed": static_result.passed}
            if static_result
            else None
        ),
    }

    emit(
        "validation_scored",
        {
            "draft_id": current_draft.id,
            "verdict": scorecard.verdict,
            "confidence": scorecard.confidence,
            "summary": scorecard.summary,
            "scores": scores_summary,
        },
    )

    result = asdict(scorecard)
    result["_validated_draft_id"] = current_draft.id

    return {
        "validation_scores": result,
    }
