from __future__ import annotations

import json
import logging
import os
from datetime import datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


def get_logs_dir() -> Path:
    """Get the logs directory, creating it if needed."""
    if env_dir := os.environ.get("COBOL_MIGRATOR_LOGS_DIR"):
        logs_dir = Path(env_dir)
    else:
        logs_dir = Path(__file__).resolve().parent.parent.parent.parent / "logs"

    logs_dir.mkdir(parents=True, exist_ok=True)
    return logs_dir


class RunLogger:
    """
    Logger for a single migration run.
    
    Creates a JSON-lines log file that captures all events, actions,
    and outputs during a migration for later analysis and improvement.
    
    Log files are stored in backend/logs/{run_id}.jsonl
    """

    def __init__(self, run_id: str) -> None:
        self.run_id = run_id
        self.start_time = datetime.now()
        self.logs_dir = get_logs_dir()
        self.log_file = self.logs_dir / f"{run_id}.jsonl"

        logger.info(f"Creating run log: {self.log_file}")

        self._write_entry(
            "run_started",
            {
                "run_id": run_id,
                "start_time": self.start_time.isoformat(),
            },
        )

    def _write_entry(self, entry_type: str, data: dict[str, Any]) -> None:
        """Write a single log entry to the file."""
        entry = {
            "timestamp": datetime.now().isoformat(),
            "type": entry_type,
            **data,
        }
        try:
            with open(self.log_file, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry, default=str) + "\n")
        except Exception as e:
            logger.warning(f"Failed to write log entry: {e}")

    def log_event(self, event_type: str, payload: dict[str, Any]) -> None:
        """Log an agent event (planner_decision, draft_created, etc.)."""
        self._write_entry(
            "event",
            {
                "event_type": event_type,
                "payload": payload,
            },
        )

    def log_input(
        self,
        source_type: str,
        source_ref: str,
        cobol_source: str,
        step_budget: int,
    ) -> None:
        """Log the migration input."""
        self._write_entry(
            "input",
            {
                "source_type": source_type,
                "source_ref": source_ref,
                "cobol_source": cobol_source,
                "step_budget": step_budget,
            },
        )

    def log_llm_call(
        self,
        node: str,
        prompt: str,
        response: Any,
        model: str,
        duration_ms: int,
    ) -> None:
        """Log an LLM API call with full prompt and response."""
        self._write_entry(
            "llm_call",
            {
                "node": node,
                "model": model,
                "prompt": prompt,
                "response": response if isinstance(response, dict) else str(response),
                "duration_ms": duration_ms,
            },
        )

    def log_test_execution(
        self,
        draft_id: str,
        python_code: str,
        test_code: str,
        stdout: str,
        stderr: str,
        passed: bool,
        duration_ms: int,
    ) -> None:
        """Log a test execution with all details."""
        self._write_entry(
            "test_execution",
            {
                "draft_id": draft_id,
                "python_code": python_code,
                "test_code": test_code,
                "stdout": stdout,
                "stderr": stderr,
                "passed": passed,
                "duration_ms": duration_ms,
            },
        )

    def log_state_update(self, node: str, update: dict[str, Any]) -> None:
        """Log a state update from a node."""
        safe_update = {}
        for key, value in update.items():
            if key == "emit":
                continue
            if hasattr(value, "__dict__"):
                safe_update[key] = str(value)
            else:
                safe_update[key] = value

        self._write_entry(
            "state_update",
            {
                "node": node,
                "update": safe_update,
            },
        )

    def log_error(self, error: str, context: dict[str, Any] | None = None) -> None:
        """Log an error."""
        self._write_entry(
            "error",
            {
                "error": error,
                "context": context or {},
            },
        )

    def log_completion(
        self,
        success: bool,
        total_steps: int,
        total_drafts: int,
        total_tests: int,
        lessons_learned: list[str],
        final_code: str | None,
        verdict: str,
    ) -> None:
        """Log the completion of the migration."""
        end_time = datetime.now()
        duration_ms = int((end_time - self.start_time).total_seconds() * 1000)

        self._write_entry(
            "run_completed",
            {
                "success": success,
                "total_steps": total_steps,
                "total_drafts": total_drafts,
                "total_tests": total_tests,
                "lessons_learned": lessons_learned,
                "final_code": final_code,
                "verdict": verdict,
                "duration_ms": duration_ms,
                "end_time": end_time.isoformat(),
            },
        )

    def get_log_path(self) -> Path:
        """Get the path to the log file."""
        return self.log_file


def create_logging_emit(
    run_logger: RunLogger,
    original_emit: Any | None = None,
) -> Any:
    """
    Create an emit function that logs events and optionally forwards to another emit.
    """

    def logging_emit(event_type: str, payload: dict[str, Any]) -> None:
        run_logger.log_event(event_type, payload)

        if original_emit is not None:
            original_emit(event_type, payload)

    return logging_emit
