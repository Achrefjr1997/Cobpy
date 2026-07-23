from __future__ import annotations

import asyncio
import json
import logging
import re
from collections.abc import AsyncGenerator
from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from cobol_migrator.copybook_resolver import resolve_copybooks
from cobol_migrator.test_environment import STDLIB_MODULES
from cobol_migrator.db import BatchRecord, get_batch_record, save_batch_record, update_batch_program
from cobol_migrator.interface_extractor import (
    InterfaceDef, ParamDef, PythonParamDef,
    extract_interface, extract_python_interface, interface_to_prompt_block,
)

_RE_IMPORT = re.compile(r"^\s*from\s+(\w+)\s+import\s+(\w+)", re.MULTILINE)
_RE_CALL = re.compile(r"(\w+)\s*\(([^)]*)\)")
_RE_PYTHON_FUNC = re.compile(
    r"^def\s+(?P<name>\w+)\s*\((?P<params>[^)]*)\)\s*(->\s*(?P<return_type>[^:]+))?\s*:",
    re.MULTILINE,
)


def _split_args(args_text: str) -> list[str]:
    """Split comma-separated function arguments, respecting nested parens."""
    args: list[str] = []
    depth = 0
    current: list[str] = []
    for ch in args_text:
        if ch == "," and depth == 0:
            args.append("".join(current).strip())
            current = []
        else:
            if ch in "([{":
                depth += 1
            elif ch in ")]}":
                depth -= 1
            current.append(ch)
    if current:
        args.append("".join(current).strip())
    return args


from cobol_migrator.zip_processor import find_copybook_dirs, scan_cobol_dependencies

logger = logging.getLogger(__name__)


def _get_transitive_callees(
    program_id: str,
    graph: dict[str, dict[str, Any]],
    visited: set[str] | None = None,
) -> set[str]:
    """Compute the transitive closure of a program's callees via DFS.

    Returns all program IDs reachable through the call graph starting
    from *program_id*, excluding *program_id* itself.  Cycles are
    handled via the *visited* set.
    """
    if visited is None:
        visited = set()
    visited.add(program_id)
    result: set[str] = set()
    for callee in graph.get(program_id, {}).get("calls", []):
        if callee not in visited:
            result.add(callee)
            result |= _get_transitive_callees(callee, graph, visited)
    return result


_batch_queues: dict[str, asyncio.Queue[dict[str, Any]]] = {}
_batch_completed: dict[str, dict[str, Any]] = {}
_batch_cancelled: set[str] = set()


class BatchCancelledError(Exception):
    pass


async def run_batch(
    job_id: str,
    migration_order: list[str],
    create_dummy_files: bool = False,
    batch_id: str | None = None,
) -> str:
    if batch_id is None:
        batch_id = uuid4().hex

    if batch_id in _batch_cancelled:
        _batch_cancelled.discard(batch_id)

    queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=2048)
    _batch_queues[batch_id] = queue

    job_dir = Path(job_id) if Path(job_id).is_dir() else (
        Path(__file__).resolve().parent.parent / "data" / "jobs" / job_id
    )

    graph = scan_cobol_dependencies(job_dir) if job_dir.is_dir() else {}
    cpy_dirs = find_copybook_dirs(job_dir) if job_dir.is_dir() else []

    asyncio.create_task(
        _run_batch_task(
            batch_id=batch_id,
            job_id=job_id,
            job_dir=job_dir,
            graph=graph,
            cpy_dirs=cpy_dirs,
            migration_order=migration_order,
            create_dummy_files=create_dummy_files,
            queue=queue,
        )
    )

    return batch_id


async def _run_batch_task(
    batch_id: str,
    job_id: str,
    job_dir: Path,
    graph: dict[str, Any],
    cpy_dirs: list[str],
    migration_order: list[str],
    create_dummy_files: bool,
    queue: asyncio.Queue[dict[str, Any]],
) -> None:
    from cobol_migrator.agent.graph import run_migration
    from cobol_migrator.db import save_migration
    from cobol_migrator.shared_model_generator import generate_shared_models_text

    shared_model_code = ""
    if job_dir.is_dir():
        copybooks = {
            pid: info for pid, info in graph.items()
            if info.get("file_path", "").lower().endswith(".cpy")
        }
        if copybooks:
            shared_model_code = generate_shared_models_text(copybooks, job_dir)
            if shared_model_code:
                logger.info(f"Generated shared models from {len(copybooks)} copybook(s)")
                # Write to file for reference
                models_path = job_dir / "shared_models.py"
                models_path.write_text(shared_model_code, encoding="utf-8")

    def emit_batch(event_type: str, payload: dict[str, Any]) -> None:
        event = {"type": event_type, "payload": payload, "batch_id": batch_id}
        try:
            queue.put_nowait(event)
        except asyncio.QueueFull:
            logger.warning(f"Batch event queue full for {batch_id}, dropping event")

    def check_cancelled() -> bool:
        return batch_id in _batch_cancelled

    # Filter out copybooks — they are not standalone programs
    program_order = [
        pid for pid in migration_order
        if pid not in graph or not graph[pid].get("file_path", "").lower().endswith(".cpy")
    ]
    skipped_cpy = [pid for pid in migration_order if pid not in program_order]
    if skipped_cpy:
        logger.info(f"Batch {batch_id}: skipping copybooks {skipped_cpy}")

    created_at = datetime.now()
    program_results: dict[str, dict[str, Any]] = {}

    save_batch_record(BatchRecord(
        batch_id=batch_id,
        job_id=job_id,
        status="running",
        migration_order=program_order,
        program_results={},
        created_at=created_at.isoformat(),
        updated_at=created_at.isoformat(),
    ))

    completed_interfaces: dict[str, InterfaceDef] = {}
    completed_code: dict[str, str] = {}
    total = len(program_order)
    all_succeeded = True

    emit_batch("batch_started", {
        "batch_id": batch_id,
        "programs": total,
        "migration_order": program_order,
    })

    for idx, program_id in enumerate(program_order, 1):
        if check_cancelled():
            raise BatchCancelledError("Batch cancelled")

        transitive_callees = _get_transitive_callees(program_id, graph)
        dep_interfaces = {
            pid: iface
            for pid, iface in completed_interfaces.items()
            if pid in transitive_callees
        }
        dep_code = {
            pid: code
            for pid, code in completed_code.items()
            if pid in transitive_callees
        }
        dep_context = ""
        if dep_interfaces:
            blocks = [interface_to_prompt_block(iface) for iface in dep_interfaces.values()]
            dep_context = "\n\n".join(blocks)

        emit_batch("program_started", {
            "batch_id": batch_id,
            "program_id": program_id,
            "index": idx,
            "total": total,
            "dependency_interfaces": list(dep_interfaces.keys()),
        })

        program_run_id = uuid4().hex

        try:
            program_info = graph.get(program_id, {})
            raw_source = program_info.get("source", "")
            if not raw_source and job_dir.is_dir():
                file_path = job_dir / program_info.get("file_path", f"{program_id}.cbl")
                if file_path.exists():
                    raw_source = file_path.read_text()

            if not raw_source:
                raise ValueError(f"Source not found for {program_id}")

            inlined_source = resolve_copybooks(raw_source, job_dir) if job_dir.is_dir() else raw_source
            cpy_include = ",".join(cpy_dirs) if cpy_dirs else None

            program_queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=1024)

            def make_emit(pid: str, pidx: int, ptotal: int):
                def emit(event_type: str, payload: dict[str, Any]) -> None:
                    event = {
                        "type": "program_event",
                        "payload": {
                            "program_id": pid,
                            "index": pidx,
                            "total": ptotal,
                            "event_type": event_type,
                            "event_payload": payload,
                        },
                        "batch_id": batch_id,
                    }
                    try:
                        queue.put_nowait(event)
                    except asyncio.QueueFull:
                        logger.warning(f"Batch queue full, dropping event for {pid}")
                return emit

            prog_emit = make_emit(program_id, idx, total)

            logger.info(f"Batch {batch_id}: migrating {program_id} ({idx}/{total})")
            final_state = await asyncio.to_thread(
                run_migration,
                cobol_source=inlined_source,
                source_type="file",
                source_ref=raw_source,
                step_budget=10,
                emit=prog_emit,
                run_id=program_run_id,
                create_dummy_files=create_dummy_files,
                check_cancelled=check_cancelled,
                copybook_include_dir=cpy_include,
                dependency_interfaces=dep_interfaces,
                dependency_code=dep_code,
                shared_model_code=shared_model_code or None,
            )

            if check_cancelled():
                raise BatchCancelledError("Batch cancelled")

            drafts = final_state.get("python_drafts", [])
            test_runs = final_state.get("test_runs", [])
            validation_scores = final_state.get("validation_scores", {})
            final_code = drafts[-1].code if drafts else None
            verdict = validation_scores.get("verdict")
            if not verdict:
                verdict = "passed" if test_runs and test_runs[-1].passed else "failed"

            iface = extract_interface(program_id, inlined_source)
            if final_code:
                py_name, py_params, py_return = extract_python_interface(final_code, program_id)
                iface.python_function_name = py_name
                iface.python_parameters = py_params
                iface.python_return_type = py_return
                completed_code[program_id] = final_code
            completed_interfaces[program_id] = iface

            result = {
                "program_id": program_id,
                "status": "completed",
                "verdict": verdict,
                "error": final_state.get("error"),
                "final_code": final_code,
                "run_id": program_run_id,
                "draft_count": len(drafts),
                "test_count": len(test_runs),
                "interface": {
                    "program_id": iface.program_id,
                    "parameters": [{"name": p.name, "pic_clause": p.pic_clause, "level": p.level} for p in iface.parameters],
                    "copybooks_used": iface.copybooks_used,
                },
            }
            program_results[program_id] = result
            update_batch_program(batch_id, program_id, result)

            emit_batch("program_completed", {
                "batch_id": batch_id,
                "program_id": program_id,
                "index": idx,
                "total": total,
                "verdict": verdict,
                "error": final_state.get("error"),
            })

            logger.info(f"Batch {batch_id}: {program_id} completed with verdict={verdict}")

        except BatchCancelledError:
            raise

        except Exception as e:
            logger.exception(f"Batch {batch_id}: {program_id} failed: {e}")
            result = {
                "program_id": program_id,
                "status": "error",
                "verdict": "errored",
                "error": str(e),
                "final_code": None,
                "run_id": program_run_id,
                "draft_count": 0,
                "test_count": 0,
                "interface": None,
            }
            program_results[program_id] = result
            update_batch_program(batch_id, program_id, result)
            all_succeeded = False

            emit_batch("program_error", {
                "batch_id": batch_id,
                "program_id": program_id,
                "index": idx,
                "total": total,
                "error": str(e),
            })

    # Cross-program integration check
    integration_issues = _check_integration(program_results, completed_code, completed_interfaces, shared_model_code)
    if integration_issues:
        logger.warning(f"Batch {batch_id}: integration issues found:")
        for issue in integration_issues:
            logger.warning(f"  - {issue}")

    final_status = "completed" if all_succeeded else "partial"

    update_batch_program(batch_id, None, None, final_status)

    _batch_completed[batch_id] = {
        "batch_id": batch_id,
        "status": final_status,
        "migration_order": migration_order,
        "program_results": program_results,
        "shared_model_code": shared_model_code or None,
        "integration_issues": integration_issues,
    }

    emit_batch("batch_completed", {
        "batch_id": batch_id,
        "status": final_status,
        "program_results": {
            pid: {"program_id": pid, "verdict": r["verdict"], "error": r.get("error")}
            for pid, r in program_results.items()
        },
        "shared_model_code": shared_model_code or None,
        "integration_issues": integration_issues,
    })

    await queue.put({"type": "batch_done", "batch_id": batch_id})


async def get_batch_status(batch_id: str) -> dict[str, Any] | None:
    if batch_id in _batch_completed:
        return _batch_completed[batch_id]

    if batch_id in _batch_queues:
        record = get_batch_record(batch_id)
        if record:
            return {
                "batch_id": record.batch_id,
                "status": record.status,
                "migration_order": record.migration_order,
                "program_results": record.program_results,
            }
        return {
            "batch_id": batch_id,
            "status": "running",
            "migration_order": [],
            "program_results": {},
        }

    record = get_batch_record(batch_id)
    if record:
        return {
            "batch_id": record.batch_id,
            "status": record.status,
            "migration_order": record.migration_order,
            "program_results": record.program_results,
        }

    return None


async def batch_event_generator(batch_id: str) -> AsyncGenerator[str, None]:
    queue = _batch_queues.get(batch_id)

    if queue is None:
        if batch_id in _batch_completed:
            result = _batch_completed[batch_id]
            yield f"data: {json.dumps({'type': 'batch_completed', 'payload': result, 'batch_id': batch_id})}\n\n"
        else:
            yield f"data: {json.dumps({'type': 'error', 'batch_id': batch_id, 'payload': {'message': 'Batch not found'}})}\n\n"
        return

    heartbeat_interval = 15
    last_heartbeat = asyncio.get_event_loop().time()

    while True:
        try:
            event = await asyncio.wait_for(queue.get(), timeout=1.0)
            yield f"data: {json.dumps(event)}\n\n"

            if event.get("type") == "batch_done":
                _batch_queues.pop(batch_id, None)
                _batch_cancelled.discard(batch_id)
                break

        except TimeoutError:
            now = asyncio.get_event_loop().time()
            if now - last_heartbeat >= heartbeat_interval:
                yield ": ping\n\n"
                last_heartbeat = now


def cancel_batch(batch_id: str) -> bool:
    if batch_id in _batch_queues:
        _batch_cancelled.add(batch_id)
        return True
    return False


def _check_integration(
    program_results: dict[str, dict[str, Any]],
    completed_code: dict[str, str],
    completed_interfaces: dict[str, InterfaceDef],
    shared_model_code: str | None,
) -> list[str]:
    issues: list[str] = []
    defined_functions: dict[str, str] = {}  # function_name -> program_id
    defined_modules: dict[str, str] = {}  # module_name (lowercase) -> program_id

    for pid, code in completed_code.items():
        defined_modules[pid.lower()] = pid
        for m in _RE_PYTHON_FUNC.finditer(code):
            defined_functions[m.group("name")] = pid

    for pid, code in completed_code.items():
        for m in _RE_IMPORT.finditer(code):
            mod_name = m.group(1)
            func_name = m.group(2)
            mod_lower = mod_name.lower()
            if mod_lower == "shared_models":
                if not shared_model_code:
                    issues.append(f"{pid}: imports from shared_models but no shared_models.py generated")
                continue
            if mod_lower not in defined_modules:
                if mod_lower not in STDLIB_MODULES:
                    issues.append(f"{pid}: imports from '{mod_name}' but no such module found in batch")
                continue
            actual_pid = defined_modules[mod_lower]
            expected_import = actual_pid.lower()
            if mod_name != expected_import and mod_name != actual_pid:
                issues.append(f"{pid}: imports '{mod_name}' but actual module file is '{actual_pid}.py' (case mismatch)")
            if func_name not in defined_functions:
                actual_funcs = [f for f, p in defined_functions.items() if p == actual_pid]
                issues.append(
                    f"{pid}: imports '{func_name}' from '{mod_name}' "
                    f"but '{actual_pid}' defines functions: {actual_funcs}"
                )

    for pid, code in completed_code.items():
        for m in _RE_CALL.finditer(code):
            callee = m.group(1)
            if callee in defined_functions and callee != "main":
                callee_pid = defined_functions[callee]
                if callee_pid in completed_interfaces:
                    iface = completed_interfaces[callee_pid]
                    if iface.python_function_name and callee == iface.python_function_name:
                        expected_param_count = len(iface.python_parameters)
                        args_text = m.group(2).strip()
                        actual_arg_count = 0
                        if args_text:
                            actual_arg_count = len(
                                [a for a in _split_args(args_text) if a.strip()]
                            )
                        if expected_param_count != actual_arg_count:
                            issues.append(
                                f"{pid}: calls '{callee}({args_text})' "
                                f"(defined in {callee_pid}) with {actual_arg_count} args, "
                                f"expected {expected_param_count} params"
                            )

    return issues


def get_batch_download_urls(batch_id: str) -> list[dict[str, str]]:
    record = get_batch_record(batch_id)
    if not record:
        return []

    results = []
    for pid, prog in record.program_results.items():
        if isinstance(prog, dict) and prog.get("final_code"):
            results.append({
                "program_id": pid,
                "verdict": prog.get("verdict", "unknown"),
            })
    return results
