"""
Context-aware dummy file generator for testing COBOL-to-Python translations.

Uses the LLM to generate synthetic data that is tailored to each specific
COBOL program — not generic boilerplate. The LLM sees the COBOL source,
record layout, and program summary so it can produce data that exercises
the program's actual business logic (e.g., edge cases for payroll calculations,
boundary values for validation routines, etc.).

Fallback: if the LLM is unavailable, falls back to parser-based generation
using the COBOL record layout.
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from pathlib import Path

from cobol_migrator.cobol_parser import (
    COBOLRecordLayout,
    extract_fd_records,
    extract_file_assignments,
    generate_cobol_sample_data,
    get_input_file_layout,
    _detect_output_files,
)

logger = logging.getLogger(__name__)


@dataclass
class DummyFileSpec:
    """Specification for a dummy file to be created."""

    filename: str
    content: str
    record_count: int
    record_length: int
    field_docs: str | None = None


@dataclass
class DummyFileResult:
    """Result of dummy file creation."""

    files_created: list[str]
    temp_dir: Path | None
    success: bool
    error: str | None
    field_docs: dict[str, str] | None = None


def _extract_filenames_from_cobol(cobol_source: str) -> list[str]:
    """Extract file names referenced in COBOL source."""
    filenames = []
    assign_pattern = r"ASSIGN\s+TO\s+['\"]([^'\"]+)['\"]"
    matches = re.findall(assign_pattern, cobol_source, re.IGNORECASE)
    filenames.extend(matches)
    assign_pattern2 = r"ASSIGN\s+TO\s+(\S+\.(?:DAT|TXT|DATA|RPT|OUT|INP|IN))"
    matches2 = re.findall(assign_pattern2, cobol_source, re.IGNORECASE)
    filenames.extend(matches2)
    return list(set(filenames))


def _extract_filenames_from_python(python_code: str) -> list[str]:
    """Extract file names referenced in Python code."""
    filenames = []
    open_pattern = r"open\s*\(\s*['\"]([^'\"]+)['\"]"
    matches = re.findall(open_pattern, python_code, re.IGNORECASE)
    filenames.extend(matches)
    path_pattern = r"Path\s*\(\s*['\"]([^'\"]+)['\"]"
    matches2 = re.findall(path_pattern, python_code, re.IGNORECASE)
    filenames.extend(matches2)
    return list(set(filenames))


def _build_layout_description(layout: COBOLRecordLayout) -> str:
    """Build a human-readable description of a record layout for the LLM."""
    lines = [f"Record: {layout.record_name} (total {layout.total_length} characters, FIXED-WIDTH, NO separators)"]
    for f in layout.fields:
        ftype = "numeric" if f.is_numeric else "alphabetic/alphanumeric"
        dec = f" ({f.decimal_places} implied decimals)" if f.decimal_places else ""
        lines.append(
            f"  Positions {f.offset}-{f.offset + f.length - 1}: "
            f"{f.name} PIC {f.pic} ({f.length} chars, {ftype}{dec})"
        )
    return "\n".join(lines)


def _validate_and_repair_record(record: str, layout: COBOLRecordLayout) -> str:
    """
    Validate a record against the layout and repair field alignment if needed.

    The LLM often gets field widths slightly wrong (e.g., "Bob Johnson" = 11 chars
    in a 10-char field). This function extracts what the LLM intended for each
    field position and forces correct padding/truncation.
    """
    if len(record) == layout.total_length:
        # Quick check: try parsing each numeric field
        all_valid = True
        for field in layout.fields:
            chunk = record[field.offset:field.offset + field.length]
            if field.is_numeric:
                if not chunk.strip().isdigit():
                    all_valid = False
                    break
        if all_valid:
            return record

    # Rebuild record field-by-field from whatever the LLM gave us
    parts = []
    for field in layout.fields:
        # Try to extract the intended value from the approximate position
        raw = record[field.offset:field.offset + field.length] if field.offset < len(record) else ""

        if field.is_numeric:
            digits = "".join(c for c in raw if c.isdigit())
            if not digits:
                digits = "0"
            parts.append(digits.zfill(field.length)[:field.length])
        else:
            parts.append(raw.ljust(field.length)[:field.length])

    return "".join(parts)


def _generate_data_via_llm(
    cobol_source: str,
    layout: COBOLRecordLayout,
    filename: str,
    program_summary: str | None,
    io_contract: dict | None,
    record_count: int = 5,
) -> str | None:
    """
    Use the LLM to generate contextually appropriate synthetic data.

    The LLM sees the full COBOL source and record layout so it can
    produce data that makes sense for this specific program.

    After generation, each record is validated and repaired against the
    layout to guarantee correct field alignment.
    """
    try:
        from pydantic import BaseModel, Field
        from cobol_migrator.models import get_structured_model

        # Build a concrete example from the layout so the LLM can copy the pattern
        example_record = layout.generate_sample_record(1)
        field_examples = []
        for f in layout.fields:
            val = example_record[f.offset:f.offset + f.length]
            field_examples.append(f'    {f.name}: "{val}" ({f.length} chars)')

        class SyntheticData(BaseModel):
            records: list[str] = Field(
                description="List of fixed-width data records, each exactly the specified length"
            )
            reasoning: str = Field(
                description="Brief explanation of why these data values were chosen"
            )

        layout_desc = _build_layout_description(layout)

        prompt = f"""\
Generate {record_count} synthetic data records for the file "{filename}" used by this COBOL program.

## COBOL Source Code
```cobol
{cobol_source[:4000]}
```

## Record Layout
{layout_desc}

## CONCRETE EXAMPLE (copy this pattern exactly)
"{example_record}" (total {layout.total_length} chars)
Field breakdown:
{chr(10).join(field_examples)}

## Program Context
{f"Summary: {program_summary}" if program_summary else "No summary available."}

## CRITICAL RULES
1. Each record must be EXACTLY {layout.total_length} characters — no more, no less.
2. Fields are concatenated directly with NO spaces, commas, or separators between them.
3. Numeric fields (PIC 9): zero-pad on LEFT to exact width. "42" in 5-char field → "00042".
4. Alpha fields (PIC A or X): pad with spaces on RIGHT to exact width. "Jo" in 10-char field → "Jo        ".
5. EVERY field must be EXACTLY its specified width — truncate if too long, pad if too short.
6. For implied decimals (PIC 9(3)V99), store as integer: 150.75 → "15075".

## DATA QUALITY
- Use realistic domain values (real salary ranges, real names that fit the field width, etc.)
- Include edge cases (zero value, boundary conditions)
- Vary values across records to exercise different code paths

Return exactly {record_count} records. Each must be a single string of exactly {layout.total_length} characters.
"""

        model = get_structured_model("analyze", SyntheticData)
        result: SyntheticData = model.invoke(prompt)

        valid_records = []
        for record in result.records:
            repaired = _validate_and_repair_record(record, layout)
            if len(repaired) == layout.total_length:
                valid_records.append(repaired)

        if valid_records:
            logger.info(
                f"LLM generated {len(valid_records)} synthetic records for {filename}: "
                f"{result.reasoning[:80]}"
            )
            return "\n".join(valid_records) + "\n"

    except Exception as e:
        logger.warning(f"LLM synthetic data generation failed for {filename}: {e}")

    return None


def generate_dummy_file_specs(
    cobol_source: str,
    python_code: str,
    io_contract: dict | None = None,
    program_summary: str | None = None,
) -> list[DummyFileSpec]:
    """
    Generate specifications for dummy files needed by the program.

    Uses the LLM to produce context-aware synthetic data for each file.
    Falls back to parser-based generation if LLM is unavailable.
    """
    specs = []

    assignments = extract_file_assignments(cobol_source)
    layouts = extract_fd_records(cobol_source)
    output_logical_names = _detect_output_files(cobol_source)

    python_files = _extract_filenames_from_python(python_code)
    cobol_files = _extract_filenames_from_cobol(cobol_source)

    filename, input_layout = get_input_file_layout(cobol_source)
    field_docs = input_layout.get_field_documentation() if input_layout else None

    for fd_name, layout in layouts.items():
        physical_name = None
        for logical, physical in assignments.items():
            if fd_name.upper() in logical or logical in fd_name.upper():
                physical_name = physical
                break
        if not physical_name:
            physical_name = f"{fd_name}.DAT"

        is_output = (
            fd_name.upper() in output_logical_names
            or any(x in physical_name.lower() for x in ['.rpt', '.out', 'report', 'output'])
        )

        if is_output:
            specs.append(DummyFileSpec(
                filename=physical_name,
                content="",
                record_count=0,
                record_length=layout.total_length,
                field_docs=None,
            ))
            continue

        # Try LLM-based generation first for input files
        content = _generate_data_via_llm(
            cobol_source=cobol_source,
            layout=layout,
            filename=physical_name,
            program_summary=program_summary,
            io_contract=io_contract,
            record_count=5,
        )

        # Fallback to parser-based generation
        if not content:
            logger.info(f"Using parser-based fallback for {physical_name}")
            records = layout.generate_sample_records(5)
            content = "\n".join(records) + "\n"

        records = [r for r in content.strip().split("\n") if r]
        record_length = len(records[0]) if records else layout.total_length

        specs.append(DummyFileSpec(
            filename=physical_name,
            content=content,
            record_count=len(records),
            record_length=record_length,
            field_docs=field_docs if physical_name == filename else None,
        ))

    # Handle Python-referenced files not in COBOL
    processed_names = {s.filename.lower() for s in specs}

    for py_file in python_files:
        if py_file.lower() in processed_names:
            continue
        if any(x in py_file.lower() for x in ['.rpt', '.out', 'report', 'output']):
            continue
        is_in_cobol = any(
            py_file.lower() in cf.lower() or cf.lower() in py_file.lower()
            for cf in cobol_files
        )
        if not is_in_cobol:
            specs.append(DummyFileSpec(
                filename=py_file,
                content="",
                record_count=0,
                record_length=0,
                field_docs=None,
            ))

    return specs


def create_dummy_files(
    specs: list[DummyFileSpec],
    target_dir: Path,
) -> DummyFileResult:
    """Create dummy files in the target directory."""
    created_files = []
    file_docs = {}

    try:
        target_dir.mkdir(parents=True, exist_ok=True)

        for spec in specs:
            file_path = target_dir / spec.filename
            file_path.write_text(spec.content)
            created_files.append(str(file_path))

            if spec.field_docs:
                file_docs[spec.filename] = spec.field_docs

            logger.info(
                f"Created dummy file: {spec.filename} "
                f"({spec.record_count} records, {spec.record_length} chars/record)"
            )

        return DummyFileResult(
            files_created=created_files,
            temp_dir=target_dir,
            success=True,
            error=None,
            field_docs=file_docs if file_docs else None,
        )

    except Exception as e:
        logger.exception(f"Failed to create dummy files: {e}")
        return DummyFileResult(
            files_created=created_files,
            temp_dir=target_dir,
            success=False,
            error=str(e),
            field_docs=None,
        )


def cleanup_dummy_files(files: list[str]) -> None:
    """Remove dummy files after testing."""
    for file_path in files:
        try:
            path = Path(file_path)
            if path.exists():
                path.unlink()
                logger.info(f"Cleaned up dummy file: {file_path}")
        except Exception as e:
            logger.warning(f"Failed to clean up {file_path}: {e}")


def get_record_layout_for_tests(cobol_source: str) -> str | None:
    """
    Get a documentation string describing the record layout.

    This can be included in test generation prompts so the LLM
    generates correctly formatted mock data.
    """
    fname, layout = get_input_file_layout(cobol_source)

    if layout:
        docs = layout.get_field_documentation()
        sample = layout.generate_sample_record(1)

        return f"""{docs}
#
# Sample record (exactly {layout.total_length} characters, NO spaces between fields):
# "{sample}"
"""

    return None
