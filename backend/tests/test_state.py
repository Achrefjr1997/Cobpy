from __future__ import annotations

from cobol_migrator.agent.state import Draft, TestRun, create_initial_state


class TestDraft:
    def test_create_draft(self) -> None:
        """Test Draft creation with auto-generated ID."""
        draft = Draft.create(
            code="print('hello')",
            rationale="Simple translation",
            parent_id=None,
        )
        assert draft.id
        assert len(draft.id) == 32
        assert draft.code == "print('hello')"
        assert draft.rationale == "Simple translation"
        assert draft.parent_id is None

    def test_draft_immutable(self) -> None:
        """Draft should be immutable (frozen dataclass)."""
        draft = Draft.create(code="x", rationale="y")
        try:
            draft.code = "modified"  # type: ignore
            assert False, "Should raise FrozenInstanceError"
        except AttributeError:
            pass

    def test_draft_with_parent(self) -> None:
        """Draft can reference a parent draft."""
        parent = Draft.create(code="v1", rationale="first")
        child = Draft.create(code="v2", rationale="revision", parent_id=parent.id)
        assert child.parent_id == parent.id


class TestTestRun:
    def test_test_run_creation(self) -> None:
        """Test TestRun creation."""
        run = TestRun(
            draft_id="abc123",
            passed=True,
            output="OK",
            stderr="",
            duration_ms=100,
        )
        assert run.draft_id == "abc123"
        assert run.passed is True
        assert run.duration_ms == 100


class TestCreateInitialState:
    def test_creates_valid_state(self) -> None:
        """create_initial_state should produce a valid AgentState."""
        state = create_initial_state(
            cobol_source="DISPLAY 'HI'",
            source_type="snippet",
            step_budget=10,
        )
        assert state["cobol_source"] == "DISPLAY 'HI'"
        assert state["source_type"] == "snippet"
        assert state["step_budget"] == 10
        assert state["step_count"] == 0
        assert state["done"] is False
        assert state["python_drafts"] == []
        assert state["test_runs"] == []

    def test_emit_function_injectable(self) -> None:
        """emit function should be injectable."""
        captured = []

        def my_emit(t: str, p: dict) -> None:
            captured.append((t, p))

        state = create_initial_state(cobol_source="X", emit=my_emit)
        state["emit"]("test", {"foo": "bar"})
        assert captured == [("test", {"foo": "bar"})]

    def test_default_emit_is_noop(self) -> None:
        """Default emit should be a no-op that doesn't error."""
        state = create_initial_state(cobol_source="X")
        state["emit"]("event", {"data": 123})
