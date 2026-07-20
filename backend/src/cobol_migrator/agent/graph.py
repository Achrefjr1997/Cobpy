from __future__ import annotations

import hashlib
import logging
from collections.abc import Callable
from typing import Any
from uuid import uuid4

from langgraph.graph import END, StateGraph

import shutil
from pathlib import Path

from cobol_migrator.agent.nodes import (
    analyze,
    finalize,
    gen_tests,
    planner,
    reflect,
    run_tests,
    translate,
    validate,
    validate_cobol,
)
from cobol_migrator.agent.state import AgentState, NextAction, ToolCall
from cobol_migrator.run_logger import RunLogger, create_logging_emit

logger = logging.getLogger(__name__)

ACTION_TO_NODE: dict[NextAction, str] = {
    "VALIDATE_COBOL": "validate_cobol",
    "ANALYZE": "analyze",
    "TRANSLATE": "translate",
    "GEN_TESTS": "gen_tests",
    "RUN_TESTS": "run_tests",
    "VALIDATE": "validate",
    "REFLECT": "reflect",
    "FINISH": "finalize",
}


def _compute_action_hash(action: str, state: AgentState) -> str:
    """Compute a hash of the action and relevant state for repeat detection."""
    relevant = f"{action}:{state.get('current_draft_id')}:{len(state.get('test_runs', []))}"
    return hashlib.md5(relevant.encode()).hexdigest()[:8]


def _check_repeat_detection(state: AgentState, action: str) -> bool:
    """Check if the same action has been repeated too many times."""
    history = state.get("tool_call_history", [])
    if len(history) < 3:
        return False

    current_hash = _compute_action_hash(action, state)
    recent_hashes = [tc.inputs_hash for tc in history[-3:]]
    recent_names = [tc.name for tc in history[-3:]]

    if all(name == action for name in recent_names):
        if len(set(recent_hashes)) == 1 and recent_hashes[0] == current_hash:
            return True
    return False


def route_from_planner(state: AgentState) -> str:
    """
    Route from planner to the next node based on state.
    
    Implements robustness guards:
    - Step budget enforcement
    - Repeat detection
    - Action mapping
    """
    step_count = state.get("step_count", 0)
    step_budget = state.get("step_budget", 25)
    next_action = state.get("next_action")

    if step_count >= step_budget:
        logger.warning(f"Step budget exhausted ({step_count}/{step_budget}), forcing finalize")
        return "finalize"

    if next_action is None:
        logger.warning("No next_action set, defaulting to finalize")
        return "finalize"

    if _check_repeat_detection(state, next_action):
        logger.warning(f"Repeat detected for {next_action}, forcing reflect")
        return "reflect" if next_action != "REFLECT" else "finalize"

    return ACTION_TO_NODE.get(next_action, "finalize")


class MigrationCancelledError(Exception):
    """Raised when a migration is cancelled."""
    pass


def _wrap_node(
    node_fn: Callable[[AgentState], dict[str, Any]],
    node_name: str,
    run_logger: RunLogger | None = None,
    check_cancelled: Callable[[], bool] | None = None,
) -> Callable[[AgentState], dict[str, Any]]:
    """Wrap a node to add error handling, history tracking, and logging."""

    def wrapped(state: AgentState) -> dict[str, Any]:
        # Check for cancellation before executing node
        if check_cancelled and check_cancelled():
            logger.info(f"Migration cancelled before node {node_name}")
            raise MigrationCancelledError("Migration was cancelled")

        try:
            result = node_fn(state)

            # Check for cancellation after executing node
            if check_cancelled and check_cancelled():
                logger.info(f"Migration cancelled after node {node_name}")
                raise MigrationCancelledError("Migration was cancelled")

            if run_logger is not None:
                run_logger.log_state_update(node_name, result)

            if node_name != "planner" and node_name != "finalize":
                history = list(state.get("tool_call_history", []))
                action_hash = _compute_action_hash(node_name.upper(), state)
                history.append(ToolCall(name=node_name.upper(), inputs_hash=action_hash))
                result["tool_call_history"] = history

            return result

        except MigrationCancelledError:
            raise  # Re-raise cancellation errors

        except Exception as e:
            logger.exception(f"Node {node_name} failed with error: {e}")
            if run_logger is not None:
                run_logger.log_error(str(e), {"node": node_name})
            return {"error": f"Node {node_name} failed: {e}"}

    return wrapped


def _cleanup_test_runs() -> None:
    """Remove all test_runs directories after migration completes."""
    test_runs_dir = Path(__file__).resolve().parent.parent.parent.parent / "test_runs"
    if test_runs_dir.exists():
        try:
            shutil.rmtree(test_runs_dir)
            logger.info(f"Cleaned up test_runs directory: {test_runs_dir}")
        except Exception as e:
            logger.warning(f"Failed to cleanup test_runs: {e}")


def _route_after_cobol_validation(state: AgentState) -> str:
    """Route after COBOL validation: finalize on error, continue otherwise."""
    if state.get("error"):
        return "finalize"
    return "increment_step"


def _increment_step(state: AgentState) -> dict[str, Any]:
    """Increment the step counter before each planner call."""
    return {"step_count": state.get("step_count", 0) + 1}


def build_graph(
    run_logger: RunLogger | None = None,
    check_cancelled: Callable[[], bool] | None = None,
) -> StateGraph:
    """Build the migration agent graph."""
    builder = StateGraph(AgentState)

    builder.add_node("increment_step", _increment_step)
    builder.add_node("planner", _wrap_node(planner, "planner", run_logger, check_cancelled))
    builder.add_node("validate_cobol", _wrap_node(validate_cobol, "validate_cobol", run_logger, check_cancelled))
    builder.add_node("analyze", _wrap_node(analyze, "analyze", run_logger, check_cancelled))
    builder.add_node("translate", _wrap_node(translate, "translate", run_logger, check_cancelled))
    builder.add_node("gen_tests", _wrap_node(gen_tests, "gen_tests", run_logger, check_cancelled))
    builder.add_node("run_tests", _wrap_node(run_tests, "run_tests", run_logger, check_cancelled))
    builder.add_node("validate", _wrap_node(validate, "validate", run_logger, check_cancelled))
    builder.add_node("reflect", _wrap_node(reflect, "reflect", run_logger, check_cancelled))
    builder.add_node("finalize", _wrap_node(finalize, "finalize", run_logger, check_cancelled))

    builder.set_entry_point("increment_step")
    builder.add_edge("increment_step", "planner")

    builder.add_conditional_edges("planner", route_from_planner)

    # validate_cobol routes to finalize on error, otherwise back to loop
    builder.add_conditional_edges(
        "validate_cobol",
        _route_after_cobol_validation,
    )

    for action_node in ["analyze", "translate", "gen_tests", "run_tests", "validate", "reflect"]:
        builder.add_edge(action_node, "increment_step")

    builder.add_edge("finalize", END)

    return builder.compile()


def run_migration(
    cobol_source: str,
    source_type: str = "snippet",
    source_ref: str = "",
    step_budget: int = 25,
    emit: Callable[[str, dict[str, Any]], None] | None = None,
    run_id: str | None = None,
    create_dummy_files: bool = False,
    check_cancelled: Callable[[], bool] | None = None,
) -> AgentState:
    """
    Run a complete migration on the given COBOL source.
    
    Creates a log file at logs/{run_id}.jsonl with full details
    of all actions, LLM calls, and outputs for analysis.
    Saves the completed run to SQLite database.
    
    Args:
        create_dummy_files: If True, create dummy input files when external
                           dependencies are detected, allowing tests to run.
                           If False, finish with partial verdict for external deps.
        check_cancelled: Optional callback that returns True if migration should stop.
    
    Returns the final agent state after the graph completes.
    """
    from datetime import datetime

    from cobol_migrator.agent.state import create_initial_state
    from cobol_migrator.db import init_db

    init_db()

    if run_id is None:
        run_id = uuid4().hex

    created_at = datetime.now()
    run_logger = RunLogger(run_id)

    run_logger.log_input(
        source_type=source_type,
        source_ref=source_ref,
        cobol_source=cobol_source,
        step_budget=step_budget,
    )

    logging_emit = create_logging_emit(run_logger, emit)

    initial_state = create_initial_state(
        cobol_source=cobol_source,
        source_type=source_type,  # type: ignore
        source_ref=source_ref,
        step_budget=step_budget,
        emit=logging_emit,
        run_id=run_id,
        created_at=created_at.isoformat(),
        create_dummy_files=create_dummy_files,
    )

    initial_state["_run_logger"] = run_logger  # type: ignore

    graph = build_graph(run_logger, check_cancelled)

    logger.info(f"Starting migration {run_id} with budget={step_budget}")
    logger.info(f"Log file: {run_logger.get_log_path()}")

    try:
        final_state = graph.invoke(initial_state)
    except MigrationCancelledError:
        logger.info(f"Migration {run_id} was cancelled")
        run_logger.log_error("Migration cancelled by user", {"phase": "cancelled"})
        final_state = dict(initial_state)
        final_state["error"] = "Cancelled by user"
        final_state["done"] = True
    except Exception as e:
        logger.exception(f"Graph execution failed: {e}")
        run_logger.log_error(str(e), {"phase": "graph_execution"})
        final_state = dict(initial_state)
        final_state["error"] = str(e)
        final_state["done"] = True

    # Clean up test_runs directory for this run
    _cleanup_test_runs()

    drafts = final_state.get("python_drafts", [])
    test_runs = final_state.get("test_runs", [])
    lessons = final_state.get("lessons_learned", [])

    cancelled = final_state.get("error") == "Cancelled by user"
    success = bool(test_runs and test_runs[-1].passed) and not cancelled

    if cancelled:
        verdict = "cancelled"
    elif success:
        verdict = "passed"
    elif final_state.get("error"):
        verdict = "errored"
    else:
        verdict = "failed"

    run_logger.log_completion(
        success=success,
        total_steps=final_state.get("step_count", 0),
        total_drafts=len(drafts),
        total_tests=len(test_runs),
        lessons_learned=lessons,
        final_code=drafts[-1].code if drafts else None,
        verdict=verdict,
    )

    logger.info(f"Migration {run_id} complete. Log: {run_logger.get_log_path()}")

    return final_state  # type: ignore
