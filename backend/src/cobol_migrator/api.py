from __future__ import annotations

import asyncio
import json
import logging
import zipfile
from collections.abc import AsyncGenerator
from pathlib import Path
from contextlib import asynccontextmanager
from typing import Any
from uuid import uuid4

from fastapi import FastAPI, File, Form, HTTPException, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response, StreamingResponse
from pydantic import BaseModel, Field

from cobol_migrator.config import settings
from cobol_migrator.db import MigrationRecord, get_migration, init_db, list_migrations
from cobol_migrator.copybook_resolver import resolve_copybooks
from cobol_migrator.zip_processor import (
    InvalidZipError,
    ZipSlipError,
    find_copybook_dirs,
    scan_cobol_dependencies,
    secure_extract_zip,
    topological_sort,
)

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
    copybook_include_dir: str | None = None,
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
            copybook_include_dir=copybook_include_dir,
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


class ZipUploadResponse(BaseModel):
    job_id: str
    programs_found: int
    dependency_graph: dict[str, Any]
    migration_order: list[str]
    extract_path: str


@ app.post("/api/migrations/upload-zip")
async def upload_zip(file: UploadFile = File(...)) -> ZipUploadResponse:
    """Upload a ZIP archive of COBOL programs and analyse dependencies.

    The ZIP is securely extracted to an isolated temporary directory.
    A dependency graph (CALL / COPY) is built from all ``.cbl`` /
    ``.cob`` / ``.cpy`` files found inside.
    """
    if not file.filename or not file.filename.lower().endswith(".zip"):
        raise HTTPException(
            status_code=400,
            detail="Only .zip files are supported.",
        )

    content = await file.read()
    if len(content) > 50_000_000:
        raise HTTPException(status_code=400, detail="ZIP too large (max 50 MB)")

    job_id = uuid4().hex
    jobs_root = Path(settings.data_dir) / "jobs"
    jobs_root.mkdir(parents=True, exist_ok=True)
    job_dir = jobs_root / job_id

    zip_tmp = job_dir.with_suffix(".zip")
    try:
        zip_tmp.write_bytes(content)

        extract_path = secure_extract_zip(zip_tmp, job_dir)
        graph = scan_cobol_dependencies(extract_path)
        order = topological_sort(graph)

        return ZipUploadResponse(
            job_id=job_id,
            programs_found=len(graph),
            dependency_graph=graph,
            migration_order=order,
            extract_path=str(extract_path),
        )

    except (zipfile.BadZipFile, InvalidZipError) as e:
        raise HTTPException(status_code=400, detail=f"Invalid ZIP file: {e}")
    except ZipSlipError as e:
        raise HTTPException(status_code=422, detail=f"Security violation: {e}")
    finally:
        if zip_tmp.exists():
            zip_tmp.unlink(missing_ok=True)


class ZipMigrateRequest(BaseModel):
    step_budget: int = Field(default=25, description="Maximum planner iterations")
    create_dummy_files: bool = Field(
        default=False,
        description="If True, create dummy input files with synthetic data for testing.",
    )


@ app.post("/api/migrations/zip-job/{job_id}/migrate/{program_id}")
async def migrate_from_zip(
    job_id: str,
    program_id: str,
    body: ZipMigrateRequest,
) -> MigrationStartResponse:
    """Migrate a single program from a previously uploaded ZIP job.

    The source is passed through the CopybookResolver to inline COPY
    statements for the LLM. The job directory is recorded as the
    ``copybook_include_dir`` so that ``validate_cobol`` can pass ``-I``
    to ``cobc``, letting GnuCOBOL resolve COPY natively during compilation.
    """
    job_dir = Path(settings.data_dir) / "jobs" / job_id
    if not job_dir.is_dir():
        raise HTTPException(status_code=404, detail=f"Job {job_id} not found")

    graph = scan_cobol_dependencies(job_dir)
    if program_id not in graph:
        raise HTTPException(
            status_code=404,
            detail=f"Program {program_id} not found in job {job_id}",
        )

    raw_source = graph[program_id]["source"]
    inlined_source = resolve_copybooks(raw_source, job_dir)
    cpy_dirs = find_copybook_dirs(job_dir)

    run_id = uuid4().hex
    queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=1024)
    _active_runs[run_id] = queue

    asyncio.create_task(
        _run_migration_task(
            run_id=run_id,
            source_type="file",
            source_ref=inlined_source,
            step_budget=body.step_budget,
            queue=queue,
            create_dummy_files=body.create_dummy_files,
            copybook_include_dir=",".join(cpy_dirs) if cpy_dirs else None,
        )
    )

    message = f"Migrating {program_id} from job {job_id[:8]}"
    return MigrationStartResponse(run_id=run_id, message=message)


class BatchMigrateRequest(BaseModel):
    create_dummy_files: bool = Field(
        default=False,
        description="If True, create dummy input files with synthetic data for testing.",
    )


class BatchStartResponse(BaseModel):
    batch_id: str
    migration_order: list[str]


class BatchStatusResponse(BaseModel):
    batch_id: str
    status: str
    migration_order: list[str]
    program_results: dict[str, Any]


@app.post("/api/migrations/zip-job/{job_id}/batch", response_model=BatchStartResponse)
async def start_batch_migration(
    job_id: str,
    body: BatchMigrateRequest,
) -> BatchStartResponse:
    """Migrate all programs in a ZIP job in dependency order.

    Programs are migrated one at a time following the topological sort
    order. Each downstream program receives interface context from its
    completed dependencies (LINKAGE SECTION, PROCEDURE DIVISION USING).
    """
    job_dir = Path(settings.data_dir) / "jobs" / job_id
    if not job_dir.is_dir():
        raise HTTPException(status_code=404, detail=f"Job {job_id} not found")

    graph = scan_cobol_dependencies(job_dir)
    order = topological_sort(graph)
    order = [
        pid for pid in order
        if pid not in graph or not graph[pid].get("file_path", "").lower().endswith(".cpy")
    ]

    from cobol_migrator.batch_manager import run_batch

    batch_id = uuid4().hex
    await run_batch(
        job_id=str(job_dir),
        migration_order=order,
        create_dummy_files=body.create_dummy_files,
        batch_id=batch_id,
    )

    return BatchStartResponse(
        batch_id=batch_id,
        migration_order=order,
    )


@app.get("/api/migrations/batch/{batch_id}", response_model=BatchStatusResponse)
async def get_batch_status_endpoint(batch_id: str) -> BatchStatusResponse:
    """Get the status of a batch migration."""
    from cobol_migrator.batch_manager import get_batch_status as _get_batch_status

    status = await _get_batch_status(batch_id)
    if status is None:
        raise HTTPException(status_code=404, detail=f"Batch {batch_id} not found")

    return BatchStatusResponse(
        batch_id=status["batch_id"],
        status=status["status"],
        migration_order=status["migration_order"],
        program_results=status["program_results"],
    )


@app.get("/api/migrations/batch/{batch_id}/events")
async def batch_migration_events(batch_id: str) -> StreamingResponse:
    """Stream batch migration events via SSE."""
    from cobol_migrator.batch_manager import batch_event_generator

    return StreamingResponse(
        batch_event_generator(batch_id),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@app.post("/api/migrations/batch/{batch_id}/stop")
async def stop_batch_migration(batch_id: str) -> dict[str, Any]:
    """Stop an ongoing batch migration."""
    from cobol_migrator.batch_manager import cancel_batch, get_batch_status as _get_batch_status

    if await _get_batch_status(batch_id) is None:
        raise HTTPException(status_code=404, detail=f"Batch {batch_id} not found")

    was_running = cancel_batch(batch_id)
    return {
        "batch_id": batch_id,
        "message": "Cancellation requested" if was_running else "Batch already completed",
    }


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


@app.get("/api/migrations/batch/{batch_id}/download")
async def download_batch_zip(batch_id: str) -> Response:
    """Download all generated Python files as a ZIP archive."""
    from cobol_migrator.batch_manager import get_batch_status as _get_batch_status

    status = await _get_batch_status(batch_id)
    if status is None:
        raise HTTPException(status_code=404, detail=f"Batch {batch_id} not found")

    import io
    import zipfile

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for pid, prog in status.get("program_results", {}).items():
            if isinstance(prog, dict) and prog.get("final_code"):
                zf.writestr(f"{pid.lower()}.py", prog["final_code"])

        shared_code = status.get("shared_model_code")
        if shared_code:
            zf.writestr("shared_models.py", shared_code)

    return Response(
        content=buf.getvalue(),
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="migration-{batch_id[:8]}.zip"'},
    )


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
