from __future__ import annotations

import ast
import logging
import re
from typing import Any

from pydantic import BaseModel, Field

from cobol_migrator.agent.state import AgentState, Draft
from cobol_migrator.models import get_structured_model

logger = logging.getLogger(__name__)


class TranslationResult(BaseModel):
    """Structured output from the translation LLM."""

    code: str = Field(description="The Python code translation")
    rationale: str = Field(description="Explanation of key translation decisions")


TRANSLATE_SYSTEM_PROMPT = """\
You are an expert COBOL-to-Python translator. Translate the given COBOL program into 
idiomatic, minimal, working Python code.

## Critical Rules
1. **ONLY import modules you actually use** - if the code doesn't need decimal, math, or 
   typing, DO NOT import them. Empty or unnecessary imports are errors.
2. The Python code must be functionally equivalent to the COBOL
3. Use a main() function as the entry point
4. Use print() for DISPLAY statements
5. Keep the code minimal and readable - no unnecessary comments, no unused variables
6. Do NOT import os, subprocess, socket, or any dangerous system modules

## When to import what
- `decimal.Decimal`: ONLY if COBOL uses COMP-3, BINARY with V, packed decimals (PACKED-DECIMAL), or explicit decimal precision in PIC (V). Regular COMP/BINARY/COMP-5 with PIC 9 only -> `int`. POINTER -> `int`. COMP-1/COMP-2 -> `float`.
- `math`: ONLY if COBOL uses mathematical functions (SQRT, SIN, COS, etc.)
- `typing`: ONLY if you need type annotations for complex structures
- For simple programs that just DISPLAY text: NO IMPORTS NEEDED

## Table Access (OCCURS)
When the shared model has OCCURS fields typed as `list[ChildModel]`:
- Use `model.field_name[i]` to access element at 0-based index i
- Use `for item in model.field_name:` to iterate
- COBOL uses 1-based indexing, so `TABLE(1)` in COBOL → Python `table[0]`
- Nested: `model.field_name[i].child_field` accesses a field inside the i-th occurrence

## REDEFINES Fields
When a field has REDEFINES, multiple COBOL fields share the same storage bytes:
- The bytes-backed record class uses `@property` accessors on a shared `bytearray` buffer
- Writing to one field implicitly changes the value read from another field that REDEFINES it
- For fixed-width file I/O: read/write the full `bytearray` buffer, not individual fields

## Fixed-Width Records - CRITICAL
COBOL files use FIXED-WIDTH records with NO separators between fields:
- Each field has an EXACT position and length defined by PIC clauses
- Fields are concatenated directly - NO spaces between them!
- To read a field: slice the line at the exact positions

## COBOL PIC Clauses and Python Parsing
- `PIC X(n)`: n alphanumeric characters -> `line[start:start+n]`
- `PIC 9(n)`: n numeric digits -> `int(line[start:start+n])`
- `PIC 9(n)V99`: n+2 digits with IMPLIED decimal (V = virtual decimal point)
  The V does NOT occupy a character position - it's implicit!
  Example: `PIC 9(3)V99` = 5 characters total representing a number like 04000 = 040.00
  Parse as: `float(line[start:start+5]) / 100`

Example - parsing a record with PIC 9(03)V99:
```python
# COBOL: 05 EMP-HOURS PIC 9(03)V99.  -- 5 chars, 2 implied decimals
# Record: "04000" means 040.00
emp_hours = float(line[36:41]) / 100  # Divide by 100 for V99
```

{dependency_context}

{shared_model_context}

{copybook_context}

## Program Analysis
{analysis_context}

## COBOL Source
```cobol
{cobol_source}
```

{lessons_context}

Translate this COBOL program to Python. Be minimal - include only what's necessary.
"""


def _build_analysis_context(state: AgentState) -> str:
    """Build context from program analysis."""
    parts = []

    summary = state.get("program_summary")
    if summary:
        parts.append(f"Summary: {summary}")

    io_contract = state.get("io_contract")
    if io_contract:
        inputs = io_contract.get("inputs", [])
        outputs = io_contract.get("outputs", [])
        invariants = io_contract.get("invariants", [])

        if inputs:
            parts.append(f"Inputs: {inputs}")
        else:
            parts.append("Inputs: None (no input required)")

        if outputs:
            parts.append(f"Outputs: {outputs}")

        if invariants:
            parts.append(f"Invariants: {invariants}")

    return "\n".join(parts) if parts else "No analysis available yet."


def _build_lessons_context(state: AgentState) -> str:
    """Build context from previous attempts and lessons."""
    parts = []

    lessons = state.get("lessons_learned", [])
    if lessons:
        parts.append("## Lessons from previous attempts")
        for lesson in lessons:
            parts.append(f"- {lesson}")

    test_runs = state.get("test_runs", [])
    if test_runs:
        last_run = test_runs[-1]
        if not last_run.passed:
            parts.append("\n## Last test failure")
            parts.append(f"Error output:\n{last_run.stderr[:500]}")

    drafts = state.get("python_drafts", [])
    if drafts:
        parts.append(f"\n## Previous attempts: {len(drafts)}")
        last_draft = drafts[-1]
        parts.append("Previous code that failed:")
        parts.append(f"```python\n{last_draft.code}\n```")
        parts.append("Fix the issues while keeping the code minimal.")

    return "\n".join(parts) if parts else ""


def _build_model_structure(model_code: str) -> str:
    """Extract a compact structural summary from generated model code.

    Returns a tree-like text showing class names, field names, types, and
    PIC clause annotations.  Detects OCCURS (list[...]) fields and marks
    them with [TABLE].
    """
    lines: list[str] = []
    current_class: str | None = None
    for line in model_code.splitlines():
        class_m = re.match(r"^class\s+(\w+)", line)
        if class_m:
            current_class = class_m.group(1)
            lines.append(f"  {current_class}:")
            continue
        if current_class is None:
            continue
        field_m = re.match(r"^\s+(\w+):\s+(\w+.*?)(?:\s+#\s*(.*))?$", line)
        if not field_m:
            continue
        name = field_m.group(1)
        py_type = field_m.group(2).rstrip(",")
        pic = (field_m.group(3) or "").strip()
        if py_type.startswith("list["):
            lines.append(f"    |-- {name}: {py_type}  [TABLE]")
        else:
            suffix = f"  # {pic}" if pic else ""
            lines.append(f"    |-- {name}: {py_type}{suffix}")
    return "\n".join(lines)


def _build_copybook_context(state: AgentState) -> str:
    """Provide original copybook source for fields used by this program."""
    copybook_source = state.get("copybook_source")
    if not copybook_source:
        return ""
    return (
        "## Copybook Sources\n"
        "The following copybook fields are used by this program:\n"
        f"```cobol\n{copybook_source}\n```"
    )


def _build_shared_models_context(state: AgentState) -> str:
    model_code = state.get("shared_model_code")
    if not model_code:
        return ""
    model_names = re.findall(r"^class\s+(\w+)", model_code, re.MULTILINE)
    import_list = ", ".join(model_names) if model_names else "..."
    structure = _build_model_structure(model_code)
    parts = [
        "## Shared Data Models (from copybooks)",
        "These Pydantic models are defined in **shared_models.py**.",
        f"Import them with: `from shared_models import {import_list}`",
        "Do NOT redefine them — use the shared model.\n",
    ]
    if structure:
        parts.append("### Structure Summary")
        parts.append(structure)
        parts.append("")
    parts.append("### Full Pydantic Code")
    parts.append(f"```python\n{model_code}\n```")
    return "\n".join(parts)


def _build_dependency_context(state: AgentState) -> str:
    dep_interfaces = state.get("dependency_interfaces", {})
    if not dep_interfaces:
        return ""

    from cobol_migrator.interface_extractor import (
        InterfaceDef, ParamDef, PythonParamDef, interface_to_prompt_block,
    )

    parts = ["## Dependency programs already migrated"]
    for pid, iface_data in dep_interfaces.items():
        if isinstance(iface_data, dict):
            params = [
                ParamDef(
                    name=p.get("name", ""),
                    pic_clause=p.get("pic_clause", ""),
                    level=p.get("level", 1),
                )
                for p in iface_data.get("parameters", [])
            ]
            py_params = [
                PythonParamDef(
                    name=p.get("name", ""),
                    type_hint=p.get("type_hint"),
                )
                for p in iface_data.get("python_parameters", [])
            ]
            iface = InterfaceDef(
                program_id=iface_data.get("program_id", pid),
                parameters=params,
                copybooks_used=iface_data.get("copybooks_used", []),
                python_function_name=iface_data.get("python_function_name"),
                python_parameters=py_params,
                python_return_type=iface_data.get("python_return_type"),
            )
            block = interface_to_prompt_block(iface)
        else:
            block = interface_to_prompt_block(iface_data)
        if block:
            parts.append(block)

    parts.append(
        "\nThese programs are already migrated to Python. "
        "If this program CALLs any of them, import and call the generated Python function. "
        "Use the Python function name and signature shown above."
    )
    return "\n\n".join(parts)


def _validate_dependency_calls(
    code: str,
    dep_interfaces: dict[str, Any],
) -> list[str]:
    """Check cross-module function calls match known dependency signatures."""
    errors: list[str] = []
    if not dep_interfaces:
        return errors

    callee_map: dict[str, tuple[int, str]] = {}
    for pid, iface_data in dep_interfaces.items():
        if isinstance(iface_data, dict):
            func_name = iface_data.get("python_function_name")
            params = iface_data.get("python_parameters", [])
        else:
            func_name = iface_data.python_function_name
            params = iface_data.python_parameters
        if func_name:
            callee_map[func_name] = (len(params), pid)

    try:
        tree = ast.parse(code)
    except SyntaxError:
        return errors

    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            func_name = node.func.id
            if func_name in callee_map:
                expected_count, callee_pid = callee_map[func_name]
                actual_count = len(node.args)
                if actual_count != expected_count:
                    errors.append(
                        f"Integration: {func_name}() called with {actual_count} args, "
                        f"expected {expected_count} (defined in {callee_pid})"
                    )

    return errors


def translate(state: AgentState) -> dict[str, Any]:
    """
    The translate node: generates a Python translation of the COBOL source.
    
    Creates a new Draft with lineage tracking. Emits a 'draft_created' event.
    """
    emit = state.get("emit", lambda t, p: None)
    cobol_source = state.get("cobol_source", "")
    current_draft_id = state.get("current_draft_id")

    analysis_context = _build_analysis_context(state)
    lessons_context = _build_lessons_context(state)
    dependency_context = _build_dependency_context(state)
    shared_model_context = _build_shared_models_context(state)
    copybook_context = _build_copybook_context(state)

    prompt = TRANSLATE_SYSTEM_PROMPT.format(
        cobol_source=cobol_source,
        analysis_context=analysis_context,
        lessons_context=lessons_context,
        dependency_context=dependency_context,
        shared_model_context=shared_model_context,
        copybook_context=copybook_context,
    )

    existing_drafts = list(state.get("python_drafts", []))

    try:
        model = get_structured_model("translate", TranslationResult)
        result: TranslationResult = model.invoke(prompt)
    except Exception as e:
        logger.error(f"Translation LLM call failed: {e}")
        return {"python_drafts": existing_drafts, "error": f"Translation failed: {e}"}

    validation_errors = _validate_dependency_calls(
        result.code, state.get("dependency_interfaces", {})
    )

    if validation_errors:
        lessons = list(state.get("lessons_learned", []))
        lessons.append(
            "Call signature mismatch: "
            + "; ".join(validation_errors)
        )
        logger.warning(f"Integration errors: {validation_errors}")
        emit(
            "integration_error",
            {"errors": validation_errors, "code": result.code},
        )
        return {
            "python_drafts": existing_drafts,
            "lessons_learned": lessons,
            "error": "; ".join(validation_errors),
        }

    draft = Draft.create(
        code=result.code,
        rationale=result.rationale,
        parent_id=current_draft_id,
    )

    emit(
        "draft_created",
        {
            "draft_id": draft.id,
            "parent_id": draft.parent_id,
            "code": draft.code,
            "rationale": draft.rationale,
        },
    )

    logger.info(f"Created draft {draft.id}: {result.rationale[:80]}")

    existing_drafts.append(draft)

    return {
        "python_drafts": existing_drafts,
        "current_draft_id": draft.id,
    }
