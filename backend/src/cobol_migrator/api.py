from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import Any
from uuid import uuid4

from fastapi import FastAPI, File, Form, HTTPException, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response, StreamingResponse
from pydantic import BaseModel, Field

from cobol_migrator.config import settings
from cobol_migrator.db import MigrationRecord, get_migration, init_db, list_migrations

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize database on startup."""
    init_db()
    logger.info("Database initialized")
    yield


app = FastAPI(
    title="COBOL Migrator API",
    description="Agentic COBOL to Python migration service",
    version="0.3.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

_active_runs: dict[str, asyncio.Queue[dict[str, Any]]] = {}
_completed_runs: dict[str, dict[str, Any]] = {}
_cancelled_runs: set[str] = set()


class HealthResponse(BaseModel):
    status: str


class MigrationRequest(BaseModel):
    source_type: str = Field(description="One of: snippet, file")
    source_ref: str = Field(description="The COBOL source code")
    step_budget: int = Field(default=25, description="Maximum planner iterations")
    create_dummy_files: bool = Field(
        default=False,
        description="If True, create dummy input files with synthetic data for testing.",
    )


class MigrationStartResponse(BaseModel):
    run_id: str
    message: str


class ValidationScore(BaseModel):
    available: bool
    passed: bool | None = None
    score: float | None = None


class ValidationScores(BaseModel):
    differential: ValidationScore | None = None
    property_based: ValidationScore | None = None
    llm_judge: ValidationScore | None = None
    static_analysis: ValidationScore | None = None
    verdict: str | None = None
    confidence: float | None = None
    summary: str | None = None


class MigrationStatusResponse(BaseModel):
    run_id: str
    done: bool
    error: str | None = None
    draft_count: int
    test_count: int
    lessons_count: int
    final_code: str | None = None
    final_tests: str | None = None
    verdict: str | None = None
    confidence: float | None = None
    validation: ValidationScores | None = None
    program_summary: str | None = None


class MigrationListItem(BaseModel):
    id: str
    source_type: str
    verdict: str | None
    step_count: int | None
    draft_count: int | None
    created_at: str
    program_summary: str | None = None


class MigrationListResponse(BaseModel):
    items: list[MigrationListItem]
    total: int
    limit: int
    offset: int


@app.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    return HealthResponse(status="ok")


class CancellationError(Exception):
    """Raised when a migration is cancelled."""
    pass


async def _run_migration_task(
    run_id: str,
    source_type: str,
    source_ref: str,
    step_budget: int,
    queue: asyncio.Queue[dict[str, Any]],
    create_dummy_files: bool = False,
) -> None:
    """Background task that runs the migration and emits events to the queue."""
    from cobol_migrator.agent.graph import run_migration

    def emit(event_type: str, payload: dict[str, Any]) -> None:
        event = {"type": event_type, "payload": payload, "run_id": run_id}
        try:
            queue.put_nowait(event)
        except asyncio.QueueFull:
            logger.warning(f"Event queue full for run {run_id}, dropping event")

    def check_cancelled() -> bool:
        return run_id in _cancelled_runs

    try:
        cobol_source = source_ref

        if check_cancelled():
            raise CancellationError("Migration cancelled before start")

        final_state = await asyncio.to_thread(
            run_migration,
            cobol_source=cobol_source,
            source_type=source_type,
            source_ref=source_ref,
            step_budget=step_budget,
            emit=emit,
            run_id=run_id,
            create_dummy_files=create_dummy_files,
            check_cancelled=check_cancelled,
        )

        if check_cancelled():
            raise CancellationError("Migration was cancelled")

        drafts = final_state.get("python_drafts", [])
        test_runs = final_state.get("test_runs", [])
        validation_scores = final_state.get("validation_scores", {})

        _completed_runs[run_id] = {
            "done": True,
            "error": final_state.get("error"),
            "draft_count": len(drafts),
            "test_count": len(test_runs),
            "lessons_count": len(final_state.get("lessons_learned", [])),
            "final_code": drafts[-1].code if drafts else None,
            "final_tests": final_state.get("generated_tests"),
            "verdict": validation_scores.get("verdict") or (
                "passed" if test_runs and test_runs[-1].passed else "failed"
            ),
            "confidence": validation_scores.get("confidence"),
            "validation": validation_scores,
            "program_summary": final_state.get("program_summary"),
        }

    except CancellationError:
        logger.info(f"Migration {run_id} was cancelled")
        emit("cancelled", {"message": "Migration was cancelled by user"})
        _completed_runs[run_id] = {
            "done": True,
            "error": "Cancelled by user",
            "draft_count": 0,
            "test_count": 0,
            "lessons_count": 0,
            "final_code": None,
            "final_tests": None,
            "verdict": "cancelled",
            "confidence": None,
            "validation": None,
            "program_summary": None,
        }

    except Exception as e:
        logger.exception(f"Migration {run_id} failed: {e}")
        emit("error", {"message": str(e)})
        _completed_runs[run_id] = {
            "done": True,
            "error": str(e),
            "draft_count": 0,
            "test_count": 0,
            "lessons_count": 0,
            "final_code": None,
            "final_tests": None,
            "verdict": "errored",
            "confidence": None,
            "validation": None,
            "program_summary": None,
        }

    finally:
        _cancelled_runs.discard(run_id)
        await queue.put({"type": "done", "run_id": run_id})


@app.post("/api/migrations", response_model=MigrationStartResponse)
async def start_migration(request: MigrationRequest) -> MigrationStartResponse:
    """Start a new migration run from a code snippet."""
    if request.source_type not in ("snippet", "file"):
        raise HTTPException(status_code=400, detail="Invalid source_type. Must be 'snippet' or 'file'.")

    if len(request.source_ref) > 100000:
        raise HTTPException(status_code=400, detail="Source too large (max 100KB)")

    run_id = uuid4().hex
    queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=1024)
    _active_runs[run_id] = queue

    asyncio.create_task(
        _run_migration_task(
            run_id=run_id,
            source_type=request.source_type,
            source_ref=request.source_ref,
            step_budget=request.step_budget,
            queue=queue,
            create_dummy_files=request.create_dummy_files,
        )
    )

    message = "Migration started"
    if request.create_dummy_files:
        message += " (dummy files with synthetic data will be created for testing)"

    return MigrationStartResponse(run_id=run_id, message=message)


@app.post("/api/migrations/upload", response_model=MigrationStartResponse)
async def upload_and_migrate(
    file: UploadFile = File(...),
    step_budget: int = Form(default=25),
    create_dummy_files: bool = Form(default=False),
) -> MigrationStartResponse:
    """Start a migration by uploading a COBOL file."""
    if file.filename and not file.filename.lower().endswith((".cbl", ".cob", ".cobol", ".cpy", ".txt")):
        raise HTTPException(
            status_code=400,
            detail="Unsupported file type. Please upload a .cbl, .cob, .cobol, .cpy, or .txt file.",
        )

    content = await file.read()
    if len(content) > 1_000_000:
        raise HTTPException(status_code=400, detail="File too large (max 1MB)")

    try:
        source_ref = content.decode("utf-8")
    except UnicodeDecodeError:
        source_ref = content.decode("latin-1")

    run_id = uuid4().hex
    queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=1024)
    _active_runs[run_id] = queue

    asyncio.create_task(
        _run_migration_task(
            run_id=run_id,
            source_type="file",
            source_ref=source_ref,
            step_budget=step_budget,
            queue=queue,
            create_dummy_files=create_dummy_files,
        )
    )

    message = f"Migration started from uploaded file: {file.filename}"
    return MigrationStartResponse(run_id=run_id, message=message)


class StopMigrationResponse(BaseModel):
    run_id: str
    message: str
    was_running: bool


@app.post("/api/migrations/{run_id}/stop", response_model=StopMigrationResponse)
async def stop_migration(run_id: str) -> StopMigrationResponse:
    """Stop an ongoing migration."""
    if run_id in _active_runs:
        _cancelled_runs.add(run_id)
        logger.info(f"Cancellation requested for migration {run_id}")
        return StopMigrationResponse(
            run_id=run_id,
            message="Cancellation requested",
            was_running=True,
        )

    if run_id in _completed_runs or run_id in _cancelled_runs:
        return StopMigrationResponse(
            run_id=run_id,
            message="Migration already completed or cancelled",
            was_running=False,
        )

    raise HTTPException(status_code=404, detail="Run not found")


@app.get("/api/migrations/{run_id}/download")
async def download_python(run_id: str) -> Response:
    """Download the generated Python code as a .py file."""
    final_code = None

    if run_id in _completed_runs:
        final_code = _completed_runs[run_id].get("final_code")
    else:
        db_record = get_migration(run_id)
        if db_record:
            final_code = db_record.final_code

    if not final_code:
        raise HTTPException(status_code=404, detail="No generated code found for this run")

    return Response(
        content=final_code,
        media_type="text/x-python",
        headers={"Content-Disposition": f'attachment; filename="migrated_{run_id[:8]}.py"'},
    )


async def _event_generator(run_id: str) -> AsyncGenerator[str, None]:
    """Generate SSE events for a migration run."""
    queue = _active_runs.get(run_id)

    if queue is None:
        if run_id in _completed_runs:
            result = _completed_runs[run_id]
            yield f"data: {json.dumps({'type': 'done', 'run_id': run_id, 'result': result})}\n\n"
        else:
            yield f"data: {json.dumps({'type': 'error', 'message': 'Run not found'})}\n\n"
        return

    heartbeat_interval = 15
    last_heartbeat = asyncio.get_event_loop().time()

    while True:
        try:
            event = await asyncio.wait_for(queue.get(), timeout=1.0)

            yield f"data: {json.dumps(event)}\n\n"

            if event.get("type") == "done":
                _active_runs.pop(run_id, None)
                break

        except TimeoutError:
            now = asyncio.get_event_loop().time()
            if now - last_heartbeat >= heartbeat_interval:
                yield ": ping\n\n"
                last_heartbeat = now


@app.get("/api/migrations/{run_id}/events")
async def migration_events(run_id: str) -> StreamingResponse:
    """Stream migration events via SSE."""
    return StreamingResponse(
        _event_generator(run_id),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


def _record_to_response(record: MigrationRecord) -> MigrationStatusResponse:
    """Convert a database record to API response."""
    validation = None
    if record.validation:
        validation = ValidationScores(
            differential=ValidationScore(
                available=record.validation.get("differential", {}).get("available", False),
                passed=record.validation.get("differential", {}).get("passed"),
            ) if record.validation.get("differential") else None,
            property_based=ValidationScore(
                available=record.validation.get("property_based", {}).get("available", False),
                passed=record.validation.get("property_based", {}).get("passed"),
            ) if record.validation.get("property_based") else None,
            llm_judge=ValidationScore(
                available=record.validation.get("llm_judge", {}).get("available", False),
                passed=record.validation.get("llm_judge", {}).get("passed"),
                score=record.validation.get("llm_judge", {}).get("score"),
            ) if record.validation.get("llm_judge") else None,
            static_analysis=ValidationScore(
                available=record.validation.get("static_analysis", {}).get("available", False),
                passed=record.validation.get("static_analysis", {}).get("passed"),
            ) if record.validation.get("static_analysis") else None,
            verdict=record.validation.get("verdict"),
            confidence=record.validation.get("confidence"),
            summary=record.validation.get("summary"),
        )

    return MigrationStatusResponse(
        run_id=record.id,
        done=True,
        error=record.error,
        draft_count=record.draft_count or 0,
        test_count=record.test_count or 0,
        lessons_count=len(record.lessons) if record.lessons else 0,
        final_code=record.final_code,
        final_tests=record.final_tests,
        verdict=record.verdict,
        confidence=record.validation.get("confidence") if record.validation else None,
        validation=validation,
        program_summary=record.program_summary,
    )


@app.get("/api/migrations/{run_id}", response_model=MigrationStatusResponse)
async def get_migration_status(run_id: str) -> MigrationStatusResponse:
    """Get the status of a migration run."""
    if run_id in _completed_runs:
        result = _completed_runs[run_id]
        validation = None
        if result.get("validation"):
            v = result["validation"]
            validation = ValidationScores(
                differential=ValidationScore(
                    available=v.get("differential", {}).get("available", False),
                    passed=v.get("differential", {}).get("passed"),
                ) if v.get("differential") else None,
                property_based=ValidationScore(
                    available=v.get("property_based", {}).get("available", False),
                    passed=v.get("property_based", {}).get("passed"),
                ) if v.get("property_based") else None,
                llm_judge=ValidationScore(
                    available=v.get("llm_judge", {}).get("available", False),
                    passed=v.get("llm_judge", {}).get("passed"),
                    score=v.get("llm_judge", {}).get("score"),
                ) if v.get("llm_judge") else None,
                static_analysis=ValidationScore(
                    available=v.get("static_analysis", {}).get("available", False),
                    passed=v.get("static_analysis", {}).get("passed"),
                ) if v.get("static_analysis") else None,
                verdict=v.get("verdict"),
                confidence=v.get("confidence"),
                summary=v.get("summary"),
            )

        return MigrationStatusResponse(
            run_id=run_id,
            done=result["done"],
            error=result.get("error"),
            draft_count=result["draft_count"],
            test_count=result["test_count"],
            lessons_count=result["lessons_count"],
            final_code=result.get("final_code"),
            final_tests=result.get("final_tests"),
            verdict=result.get("verdict"),
            confidence=result.get("confidence"),
            validation=validation,
            program_summary=result.get("program_summary"),
        )

    if run_id in _active_runs:
        return MigrationStatusResponse(
            run_id=run_id,
            done=False,
            error=None,
            draft_count=0,
            test_count=0,
            lessons_count=0,
            final_code=None,
            final_tests=None,
            verdict=None,
            confidence=None,
            validation=None,
            program_summary=None,
        )

    db_record = get_migration(run_id)
    if db_record:
        return _record_to_response(db_record)

    raise HTTPException(status_code=404, detail="Run not found")


@app.get("/api/migrations", response_model=MigrationListResponse)
async def list_migration_history(
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    verdict: str | None = Query(default=None),
) -> MigrationListResponse:
    """List migration history with pagination."""
    records, total = list_migrations(limit=limit, offset=offset, verdict=verdict)

    items = [
        MigrationListItem(
            id=r.id,
            source_type=r.source_type,
            verdict=r.verdict,
            step_count=r.step_count,
            draft_count=r.draft_count,
            created_at=r.created_at,
            program_summary=r.program_summary,
        )
        for r in records
    ]

    return MigrationListResponse(
        items=items,
        total=total,
        limit=limit,
        offset=offset,
    )
