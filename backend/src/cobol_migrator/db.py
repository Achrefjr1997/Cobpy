from __future__ import annotations

import json
import logging
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from cobol_migrator.config import settings

logger = logging.getLogger(__name__)


def get_db_path() -> Path:
    """Get the database file path."""
    return Path(settings.database_path)


def init_db() -> None:
    """Initialize the database schema."""
    db_path = get_db_path()
    db_path.parent.mkdir(parents=True, exist_ok=True)

    with sqlite3.connect(db_path) as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS migrations (
                id TEXT PRIMARY KEY,
                source_type TEXT NOT NULL,
                source_ref TEXT,
                cobol_source TEXT NOT NULL,
                final_code TEXT,
                final_tests TEXT,
                validation_json TEXT,
                verdict TEXT,
                event_trace TEXT,
                step_count INTEGER,
                draft_count INTEGER,
                test_count INTEGER,
                lessons_json TEXT,
                program_summary TEXT,
                error TEXT,
                created_at TEXT NOT NULL,
                completed_at TEXT
            );
            
            CREATE INDEX IF NOT EXISTS idx_migrations_created_at 
            ON migrations(created_at DESC);
            
            CREATE INDEX IF NOT EXISTS idx_migrations_verdict 
            ON migrations(verdict);
        """)

    logger.info(f"Database initialized at {db_path}")


@contextmanager
def get_connection() -> Iterator[sqlite3.Connection]:
    """Get a database connection with row factory."""
    db_path = get_db_path()
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


@dataclass
class MigrationRecord:
    """A completed migration record from the database."""

    id: str
    source_type: str
    source_ref: str | None
    cobol_source: str
    final_code: str | None
    final_tests: str | None
    validation: dict | None
    verdict: str | None
    event_trace: list[dict] | None
    step_count: int | None
    draft_count: int | None
    test_count: int | None
    lessons: list[str] | None
    program_summary: str | None
    error: str | None
    created_at: str
    completed_at: str | None

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> MigrationRecord:
        """Create a MigrationRecord from a database row."""
        return cls(
            id=row["id"],
            source_type=row["source_type"],
            source_ref=row["source_ref"],
            cobol_source=row["cobol_source"],
            final_code=row["final_code"],
            final_tests=row["final_tests"],
            validation=json.loads(row["validation_json"]) if row["validation_json"] else None,
            verdict=row["verdict"],
            event_trace=json.loads(row["event_trace"]) if row["event_trace"] else None,
            step_count=row["step_count"],
            draft_count=row["draft_count"],
            test_count=row["test_count"],
            lessons=json.loads(row["lessons_json"]) if row["lessons_json"] else None,
            program_summary=row["program_summary"],
            error=row["error"],
            created_at=row["created_at"],
            completed_at=row["completed_at"],
        )


def save_migration(
    run_id: str,
    source_type: str,
    source_ref: str,
    cobol_source: str,
    final_code: str | None,
    final_tests: str | None,
    validation: dict | None,
    verdict: str | None,
    event_trace: list[dict[str, Any]] | None,
    step_count: int,
    draft_count: int,
    test_count: int,
    lessons: list[str],
    program_summary: str | None,
    error: str | None,
    created_at: datetime,
) -> None:
    """Save a completed migration to the database."""
    with get_connection() as conn:
        conn.execute(
            """
            INSERT OR REPLACE INTO migrations (
                id, source_type, source_ref, cobol_source,
                final_code, final_tests, validation_json, verdict,
                event_trace, step_count, draft_count, test_count,
                lessons_json, program_summary, error,
                created_at, completed_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                run_id,
                source_type,
                source_ref,
                cobol_source,
                final_code,
                final_tests,
                json.dumps(validation) if validation else None,
                verdict,
                json.dumps(event_trace) if event_trace else None,
                step_count,
                draft_count,
                test_count,
                json.dumps(lessons) if lessons else None,
                program_summary,
                error,
                created_at.isoformat(),
                datetime.now().isoformat(),
            ),
        )

    logger.info(f"Saved migration {run_id} to database")


def get_migration(run_id: str) -> MigrationRecord | None:
    """Get a migration record by ID."""
    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM migrations WHERE id = ?",
            (run_id,),
        ).fetchone()

        if row is None:
            return None

        return MigrationRecord.from_row(row)


def list_migrations(
    limit: int = 20,
    offset: int = 0,
    verdict: str | None = None,
) -> tuple[list[MigrationRecord], int]:
    """
    List migrations with pagination.
    
    Returns (records, total_count).
    """
    with get_connection() as conn:
        if verdict:
            count_row = conn.execute(
                "SELECT COUNT(*) FROM migrations WHERE verdict = ?",
                (verdict,),
            ).fetchone()
            rows = conn.execute(
                """
                SELECT * FROM migrations 
                WHERE verdict = ?
                ORDER BY created_at DESC 
                LIMIT ? OFFSET ?
                """,
                (verdict, limit, offset),
            ).fetchall()
        else:
            count_row = conn.execute(
                "SELECT COUNT(*) FROM migrations"
            ).fetchone()
            rows = conn.execute(
                """
                SELECT * FROM migrations 
                ORDER BY created_at DESC 
                LIMIT ? OFFSET ?
                """,
                (limit, offset),
            ).fetchall()

        total = count_row[0] if count_row else 0
        records = [MigrationRecord.from_row(row) for row in rows]

        return records, total


def delete_migration(run_id: str) -> bool:
    """Delete a migration record. Returns True if deleted."""
    with get_connection() as conn:
        cursor = conn.execute(
            "DELETE FROM migrations WHERE id = ?",
            (run_id,),
        )
        return cursor.rowcount > 0
