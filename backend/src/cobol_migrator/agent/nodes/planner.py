from __future__ import annotations

import logging
from typing import Any

from pydantic import BaseModel, Field

from cobol_migrator.agent.state import AgentState, NextAction
from cobol_migrator.models import get_structured_model

logger = logging.getLogger(__name__)


class PlannerDecision(BaseModel):
    """Structured output from the planner LLM."""

    reasoning: str = Field(description="Brief explanation of why this action was chosen")
    next_action: NextAction = Field(description="The next action to take")
    target_draft_id: str | None = Field(
        default=None,
        description="Optional: specific draft ID to target (for TRANSLATE revisions)",
    )


PLANNER_SYSTEM_PROMPT = """\
You are the planning component of a COBOL-to-Python migration agent. Your job is to decide 
what action to take next based on the current state of the migration.

## Available Actions
- VALIDATE_COBOL: Compile and validate the input COBOL code (mandatory first step, do NOT repeat if already done)
- ANALYZE: Analyze the COBOL source to understand its structure (do after COBOL is validated)
- TRANSLATE: Generate a new Python translation of the COBOL code
- GEN_TESTS: Generate pytest tests for the current Python draft
- RUN_TESTS: Execute the generated tests against the current draft
- VALIDATE: Run the validation stack (differential testing, etc.) - Stage 4
- REFLECT: Analyze test failures and extract lessons for the next attempt
- FINISH: Complete the migration (use when tests pass or budget exhausted)

## Decision Guidelines
1. If COBOL validated is "No", do VALIDATE_COBOL first (mandatory, one-time step)
2. If COBOL validated is "Yes" and program_summary is not set, ANALYZE next
3. If no drafts exist, TRANSLATE next
4. **CRITICAL: After tests PASS on a new draft, ALWAYS do VALIDATE before FINISH or TRANSLATE** \
   — never assume the old validation verdict still applies to the new draft
3. After TRANSLATE, do GEN_TESTS then RUN_TESTS
4. If tests FAIL, REFLECT to learn from the failure
5. After REFLECT:
   - If lesson says "test code bug" → do ONE GEN_TESTS, then if still failing → TRANSLATE
   - If lesson says "translation bug" → TRANSLATE immediately
   - If lesson says "external dependency" → **FINISH immediately** (can't fix in test env)
6. **CRITICAL: Never do GEN_TESTS twice for same draft** - if failed twice, TRANSLATE
7. If tests PASS, run VALIDATE then FINISH
8. Apply lessons learned to improve each translation
9. Don't repeat the same failing approach - if stuck, try TRANSLATE with different approach
10. **EXTERNAL DEPENDENCIES**: If errors mention missing files (.dat, .txt), database 
    connections, or network resources that the program legitimately needs, FINISH with 
    partial verdict - the code is likely correct but cannot be tested without those resources

## Current State

### Progress
Step: {step_count}/{step_budget}
COBOL validated: {cobol_validated}
Drafts created: {draft_count}
Tests run: {test_count}

### Program Understanding
{program_context}

### Translation History
{translation_history}

### Validation Status
{validation_context}

### External Dependencies
{external_deps_context}

### Lessons Learned
{lessons_context}

### Recent Actions
{action_history}
"""


def _build_program_context(state: AgentState) -> str:
    """Build the program understanding context."""
    lines = []

    summary = state.get("program_summary")
    if summary:
        lines.append(f"Summary: {summary}")
    else:
        lines.append("Summary: Not yet analyzed")

    io_contract = state.get("io_contract")
    if io_contract:
        inputs = io_contract.get("inputs", [])
        outputs = io_contract.get("outputs", [])
        invariants = io_contract.get("invariants", [])

        if inputs:
            inputs_str = ", ".join(f"{p['name']}:{p['type']}" for p in inputs)
            lines.append(f"Inputs: {inputs_str}")
        if outputs:
            outputs_str = ", ".join(f"{p['name']}:{p['type']}" for p in outputs)
            lines.append(f"Outputs: {outputs_str}")
        if invariants:
            lines.append(f"Invariants: {'; '.join(invariants[:3])}")
    else:
        lines.append("I/O Contract: Not yet analyzed")

    return "\n".join(lines)


def _build_translation_history(state: AgentState) -> str:
    """Build the translation history context."""
    lines = []

    drafts = state.get("python_drafts", [])
    test_runs = state.get("test_runs", [])

    if not drafts:
        return "No translations yet"

    # Count test runs for current draft
    current_id = state.get("current_draft_id")
    current_draft_test_runs = sum(
        1 for r in test_runs if current_id and r.draft_id == current_id
    )

    for i, draft in enumerate(drafts[-3:], 1):
        matching_runs = [r for r in test_runs if r.draft_id == draft.id]
        run_count = len(matching_runs)
        if matching_runs:
            last_run = matching_runs[-1]
            status = "PASSED" if last_run.passed else f"FAILED ({run_count}x tested)"
            lines.append(f"Draft {i}: {status}")
            if not last_run.passed and last_run.stderr:
                error_preview = last_run.stderr[:150].replace("\n", " ")
                lines.append(f"  Error: {error_preview}")
        else:
            lines.append(f"Draft {i}: Not tested")

    if current_id:
        lines.append(f"Current draft: {current_id[:8]}...")
        if current_draft_test_runs >= 2:
            lines.append(
                f"  ⚠️ This draft tested {current_draft_test_runs}x - "
                "consider TRANSLATE instead of GEN_TESTS"
            )

    return "\n".join(lines) if lines else "No translation history"


def _build_lessons_context(state: AgentState) -> str:
    """Build the lessons learned context."""
    lessons = state.get("lessons_learned", [])

    if not lessons:
        return "No lessons learned yet"

    lines = []
    for lesson in lessons[-5:]:
        lines.append(f"• {lesson[:150]}")

    return "\n".join(lines)


def _build_action_history(state: AgentState) -> str:
    """Build the recent action history context."""
    history = state.get("tool_call_history", [])

    if not history:
        return "No actions taken yet"

    recent = [tc.name for tc in history[-7:]]
    return " → ".join(recent)


def _build_validation_context(state: AgentState) -> str:
    """Build the validation status context."""
    validation_scores = state.get("validation_scores", {})

    if not validation_scores:
        return "Not validated yet"

    verdict = validation_scores.get("verdict", "unknown")
    confidence = validation_scores.get("confidence", 0)

    lines = [f"Verdict: {verdict} (confidence: {confidence:.0%})"]

    if validation_scores.get("summary"):
        lines.append(f"Summary: {validation_scores['summary'][:200]}")

    return "\n".join(lines)


def _build_external_deps_context(state: AgentState) -> str:
    """Build context about external dependency issues."""
    if state.get("external_dependency_detected"):
        resource = state.get("external_resource", "unknown resource")
        return (
            f"⚠️ EXTERNAL DEPENDENCY DETECTED: {resource}\n"
            f"The program requires external resources that cannot be provided in tests.\n"
            f"Recommend: FINISH with partial verdict - translation is likely correct."
        )

    # Check lessons for external dependency patterns
    lessons = state.get("lessons_learned", [])
    ext_patterns = ["external", "file not found", ".dat", ".txt", "database", "connection"]
    ext_lessons = [
        lesson for lesson in lessons
        if any(p in lesson.lower() for p in ext_patterns)
    ]

    if ext_lessons:
        return (
            f"Potential external dependency issue detected in lessons:\n"
            f"- {ext_lessons[-1][:150]}\n"
            f"Consider: FINISH if this is a legitimate external resource requirement."
        )

    return "No external dependency issues detected"


def _count_gen_tests_for_draft(state: AgentState) -> int:
    """Count how many times GEN_TESTS was called for the current draft."""
    history = state.get("tool_call_history", [])
    current_draft_id = state.get("current_draft_id")
    
    if not current_draft_id:
        return 0
    
    # Count GEN_TESTS calls since the last TRANSLATE
    gen_tests_count = 0
    for tc in reversed(history):
        if tc.name == "TRANSLATE":
            break
        if tc.name == "GEN_TESTS":
            gen_tests_count += 1
    
    return gen_tests_count


def _should_force_translate(state: AgentState) -> tuple[bool, str]:
    """
    Check if we should force a TRANSLATE instead of allowing GEN_TESTS.
    Returns (should_force, reason).
    """
    gen_tests_count = _count_gen_tests_for_draft(state)
    test_runs = state.get("test_runs", [])
    current_draft_id = state.get("current_draft_id")
    
    # Count failed test runs for current draft
    failed_runs = sum(
        1 for r in test_runs 
        if r.draft_id == current_draft_id and not r.passed
    )
    
    # If we've generated tests 2+ times for this draft and still failing, force translate
    if gen_tests_count >= 2 and failed_runs >= 2:
        return True, f"GEN_TESTS called {gen_tests_count}x with {failed_runs} failures - need new translation"
    
    # If we've had 3+ consecutive test failures across all drafts, consider translate
    recent_failures = 0
    for run in reversed(test_runs[-5:]):
        if not run.passed:
            recent_failures += 1
        else:
            break
    
    if recent_failures >= 3 and gen_tests_count >= 1:
        return True, f"{recent_failures} consecutive test failures - new translation needed"
    
    return False, ""


def planner(state: AgentState) -> dict[str, Any]:
    """
    The planner node: decides what action to take next.
    
    Uses structured LLM output to select the next action with reasoning.
    Incorporates program summary, I/O contract, lessons learned, and history.
    Includes hardcoded rules to prevent excessive API calls from test regeneration loops.
    """
    emit = state.get("emit", lambda t, p: None)

    # COBOL must be validated before anything else
    if not state.get("cobol_validated", False):
        logger.info("COBOL not yet validated, forcing VALIDATE_COBOL")
        emit(
            "planner_decision",
            {
                "reasoning": "COBOL source must be validated before proceeding",
                "next_action": "VALIDATE_COBOL",
                "target_draft_id": None,
                "step_count": state.get("step_count", 0),
            },
        )
        return {
            "next_action": "VALIDATE_COBOL",
            "plan": "Validate COBOL source code first",
        }

    # Check for external dependency - shortcut to FINISH
    if state.get("external_dependency_detected"):
        resource = state.get("external_resource", "external resource")
        logger.info(f"External dependency detected ({resource}), recommending FINISH")
        emit(
            "planner_decision",
            {
                "reasoning": f"External dependency: {resource} - cannot test without it",
                "next_action": "FINISH",
                "target_draft_id": None,
                "step_count": state.get("step_count", 0),
                "external_dependency": True,
            },
        )
        return {
            "next_action": "FINISH",
            "plan": f"Finishing due to external dependency: {resource}",
        }
    
    # If tests passed on the current draft but it hasn't been validated
    # (or was validated on a different draft), force VALIDATE
    test_runs = state.get("test_runs", [])
    current_draft_id = state.get("current_draft_id")
    validation_scores = state.get("validation_scores", {})
    validated_draft = validation_scores.get("_validated_draft_id")
    if (
        current_draft_id
        and test_runs
        and test_runs[-1].draft_id == current_draft_id
        and test_runs[-1].passed
        and validated_draft != current_draft_id
    ):
        logger.info("Tests passed on current draft but not yet validated, forcing VALIDATE")
        emit(
            "planner_decision",
            {
                "reasoning": "Tests passed — running validation stack to compare COBOL vs Python output",
                "next_action": "VALIDATE",
                "target_draft_id": current_draft_id,
                "step_count": state.get("step_count", 0),
            },
        )
        return {
            "next_action": "VALIDATE",
            "plan": "Tests passed, validate before finishing",
        }

    # Check if we're stuck in a test loop - force translate if so
    should_translate, translate_reason = _should_force_translate(state)
    if should_translate:
        logger.info(f"Forcing TRANSLATE: {translate_reason}")
        emit(
            "planner_decision",
            {
                "reasoning": translate_reason,
                "next_action": "TRANSLATE",
                "target_draft_id": None,
                "step_count": state.get("step_count", 0),
                "forced": True,
            },
        )
        return {
            "next_action": "TRANSLATE",
            "plan": translate_reason,
        }

    program_context = _build_program_context(state)
    translation_history = _build_translation_history(state)
    validation_context = _build_validation_context(state)
    external_deps_context = _build_external_deps_context(state)
    lessons_context = _build_lessons_context(state)
    action_history = _build_action_history(state)

    prompt = PLANNER_SYSTEM_PROMPT.format(
        step_count=state.get("step_count", 0),
        step_budget=state.get("step_budget", 25),
        cobol_validated="Yes" if state.get("cobol_validated", False) else "No",
        draft_count=len(state.get("python_drafts", [])),
        test_count=len(state.get("test_runs", [])),
        program_context=program_context,
        translation_history=translation_history,
        validation_context=validation_context,
        external_deps_context=external_deps_context,
        lessons_context=lessons_context,
        action_history=action_history,
    )

    try:
        model = get_structured_model("planner", PlannerDecision)
        decision: PlannerDecision = model.invoke(prompt)
    except Exception as e:
        logger.error(f"Planner LLM call failed: {e}")
        decision = PlannerDecision(
            reasoning=f"Planner error: {e}. Defaulting to FINISH.",
            next_action="FINISH",
            target_draft_id=None,
        )

    # Post-LLM override: prevent excessive GEN_TESTS
    if decision.next_action == "GEN_TESTS":
        gen_tests_count = _count_gen_tests_for_draft(state)
        if gen_tests_count >= 2:
            logger.info(f"Overriding GEN_TESTS -> TRANSLATE (already {gen_tests_count} attempts)")
            decision = PlannerDecision(
                reasoning=f"Override: Already tried GEN_TESTS {gen_tests_count}x, need new translation",
                next_action="TRANSLATE",
                target_draft_id=None,
            )

    emit(
        "planner_decision",
        {
            "reasoning": decision.reasoning,
            "next_action": decision.next_action,
            "target_draft_id": decision.target_draft_id,
            "step_count": state.get("step_count", 0),
        },
    )

    logger.info(f"Planner decided: {decision.next_action} - {decision.reasoning[:80]}")

    return {
        "next_action": decision.next_action,
        "plan": decision.reasoning,
    }
