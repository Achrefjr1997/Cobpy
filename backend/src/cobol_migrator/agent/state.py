from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Literal, TypedDict
from uuid import uuid4

NextAction = Literal[
    "VALIDATE_COBOL", "ANALYZE", "TRANSLATE", "GEN_TESTS", "RUN_TESTS",
    "VALIDATE", "REFLECT", "FINISH",
]


@dataclass(slots=True, frozen=True)
class Draft:
    """A Python translation draft with lineage tracking."""

    id: str
    code: str
    parent_id: str | None
    rationale: str

    @classmethod
    def create(cls, code: str, rationale: str, parent_id: str | None = None) -> Draft:
        return cls(id=uuid4().hex, code=code, parent_id=parent_id, rationale=rationale)


@dataclass(slots=True, frozen=True)
class TestRun:
    """Result of running tests on a draft."""

    draft_id: str
    passed: bool
    output: str
    stderr: str
    duration_ms: int


@dataclass(slots=True, frozen=True)
class ToolCall:
    """Record of an action taken by the agent."""

    name: str
    inputs_hash: str


def _default_emit(event_type: str, payload: dict[str, Any]) -> None:
    """Default no-op emit function for CLI/test usage."""
    pass


class AgentState(TypedDict, total=False):
    """
    The agent's memory and state.
    
    All list fields are append-only. Nodes return partial updates;
    the graph wrapper merges them into the canonical state.
    """

    # Input
    source_type: Literal["snippet", "file"]
    source_ref: str
    cobol_source: str

    # COBOL validation (runs before analysis)
    cobol_validated: bool
    cobol_output: str | None
    cobc_available: bool

    # Analysis (Stage 3)
    program_summary: str | None
    io_contract: dict | None

    # Translation history (append-only)
    python_drafts: list[Draft]
    current_draft_id: str | None

    # Test history
    generated_tests: str | None
    test_runs: list[TestRun]

    # Validation (Stage 4)
    validation_scores: dict

    # Planning
    plan: str
    next_action: NextAction | None
    tool_call_history: list[ToolCall]

    # Reflection (Stage 3)
    lessons_learned: list[str]

    # Control flow
    step_count: int
    step_budget: int
    done: bool
    error: str | None

    # Event emission (injected at runtime)
    emit: Callable[[str, dict[str, Any]], None]

    # Run metadata (for persistence)
    run_id: str | None
    created_at: str | None

    # External dependency tracking
    external_dependency_detected: bool
    external_resource: str | None

    # Dummy file options
    create_dummy_files: bool  # User option: create dummy files for testing
    dummy_files_created: list[str]  # List of dummy file paths created

    # Test issues tracking (for partial status reporting)
    test_issues: list[str]  # Detected issues during test execution


def create_initial_state(
    cobol_source: str,
    source_type: Literal["snippet", "file"] = "snippet",
    source_ref: str = "",
    step_budget: int = 25,
    emit: Callable[[str, dict[str, Any]], None] | None = None,
    run_id: str | None = None,
    created_at: str | None = None,
    create_dummy_files: bool = False,
) -> AgentState:
    """Create a fresh agent state for a new migration run."""
    return AgentState(
        source_type=source_type,
        source_ref=source_ref,
        cobol_source=cobol_source,
        cobol_validated=False,
        cobol_output=None,
        cobc_available=False,
        program_summary=None,
        io_contract=None,
        python_drafts=[],
        current_draft_id=None,
        generated_tests=None,
        test_runs=[],
        validation_scores={},
        plan="",
        next_action=None,
        tool_call_history=[],
        lessons_learned=[],
        step_count=0,
        step_budget=step_budget,
        done=False,
        error=None,
        emit=emit or _default_emit,
        run_id=run_id,
        created_at=created_at,
        create_dummy_files=create_dummy_files,
        dummy_files_created=[],
        test_issues=[],
    )
