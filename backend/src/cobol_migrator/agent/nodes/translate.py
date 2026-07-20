from __future__ import annotations

import logging
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
- `decimal.Decimal`: ONLY if COBOL uses COMP-3, packed decimals, or explicit decimal precision
- `math`: ONLY if COBOL uses mathematical functions (SQRT, SIN, COS, etc.)
- `typing`: ONLY if you need type annotations for complex structures
- For simple programs that just DISPLAY text: NO IMPORTS NEEDED

## COBOL Fixed-Width Records - CRITICAL
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

    prompt = TRANSLATE_SYSTEM_PROMPT.format(
        cobol_source=cobol_source,
        analysis_context=analysis_context,
        lessons_context=lessons_context,
    )

    try:
        model = get_structured_model("translate", TranslationResult)
        result: TranslationResult = model.invoke(prompt)
    except Exception as e:
        logger.error(f"Translation LLM call failed: {e}")
        return {"error": f"Translation failed: {e}"}

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

    existing_drafts = list(state.get("python_drafts", []))
    existing_drafts.append(draft)

    return {
        "python_drafts": existing_drafts,
        "current_draft_id": draft.id,
    }
