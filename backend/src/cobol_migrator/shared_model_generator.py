from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_LINE_FIELD_RE = re.compile(
    r"^\s*(?P<level>\d{2})\s+(?P<name>\w+(?:-\w+)*)",
    re.IGNORECASE,
)

_PIC_RE = re.compile(
    r"PIC\s+(?P<pic>[\w().]+)",
    re.IGNORECASE,
)

_VALUE_RE = re.compile(
    r"VALUE\s+(?P<value>'.*?'|\".*?\"|\S+)",
    re.IGNORECASE,
)

# Keep the original FIELD_RE for callers that rely on single-line matching
FIELD_RE = re.compile(
    r"^\s*(?P<level>\d{2})\s+(?P<name>\w+(?:-\w+)*)\s+"
    r"(?:PIC\s+)?(?P<pic>[\w().]+)",
    re.IGNORECASE | re.MULTILINE,
)


def extract_copybook_fields(copybook_source: str) -> list[dict[str, Any]]:
    fields: list[dict[str, Any]] = []

    for m in FIELD_RE.finditer(copybook_source):
        level = int(m.group("level"))
        if level == 88:
            continue
        name = m.group("name")
        raw_pic = m.group("pic")
        pic_clause = raw_pic if raw_pic.upper().startswith("PIC") else f"PIC {raw_pic}"
        pic_clause = pic_clause.rstrip(".")

        line_start = copybook_source.rfind("\n", 0, m.start()) + 1
        line_end_idx = copybook_source.find("\n", m.end())
        if line_end_idx == -1:
            line_end_idx = len(copybook_source)

        block_end = line_end_idx
        rest = copybook_source[line_end_idx:]
        for peek_line in rest.splitlines():
            if not peek_line.strip():
                continue
            if _LINE_FIELD_RE.match(peek_line):
                break
            if block_end < len(copybook_source):
                next_nl = copybook_source.find("\n", block_end + 1)
                block_end = next_nl if next_nl != -1 else len(copybook_source)
            if block_end == -1:
                block_end = len(copybook_source)

        full_line = copybook_source[line_start:block_end]
        value_m = _VALUE_RE.search(full_line)
        value = value_m.group("value") if value_m else None
        if value and not (value.startswith("'") or value.startswith('"')):
            value = value.rstrip(".")

        fields.append({
            "level": level,
            "name": name,
            "pic": pic_clause,
            "value": value,
        })

    return fields


def pic_to_python_type(pic: str) -> str:
    pic_upper = pic.upper()
    if "9" in pic_upper:
        if "V" in pic_upper:
            return "Decimal"
        return "int"
    return "str"


def generate_pydantic_model(copybook_id: str, fields: list[dict[str, Any]]) -> str:
    model_name = copybook_id.replace("-", "_").replace(".", "_").title()
    if not model_name.endswith("Model"):
        model_name += "Model"

    if not fields:
        return ""

    constants: list[str] = []
    model_fields: list[str] = []

    for f in fields:
        py_type = pic_to_python_type(f["pic"])
        if f.get("value"):
            const_name = f["name"].upper().replace("-", "_")
            raw_val = f["value"]
            constants.append(f"{const_name}: {py_type} = {raw_val}")
        else:
            py_name = f["name"].lower().replace("-", "_")
            model_fields.append(f"    {py_name}: {py_type}  # {f['pic']}")

    parts: list[str] = []

    if constants:
        parts.extend(constants)

    if model_fields:
        if parts:
            parts.append("")
        parts.append(f"class {model_name}(BaseModel):")
        parts.append(f'    """Generated from {copybook_id}."""')
        parts.append("")
        parts.extend(model_fields)

    return "\n".join(parts)


def generate_shared_models_text(copybooks: dict[str, dict[str, Any]], extract_path: Path) -> str:
    parts: list[str] = []
    has_model = False
    has_decimal = False

    for prog_id, info in copybooks.items():
        file_path = info.get("file_path", "")
        if not file_path.lower().endswith(".cpy"):
            continue
        source_path = extract_path / file_path
        if not source_path.exists():
            logger.warning(f"Copybook file not found: {source_path}")
            continue
        source = source_path.read_text(encoding="utf-8", errors="ignore")
        fields = extract_copybook_fields(source)

        # Skip copybooks that produce no output
        if not fields:
            continue

        model_code = generate_pydantic_model(prog_id, fields)
        if not model_code:
            continue
        parts.append(model_code)
        if "class " in model_code:
            has_model = True
        if "Decimal" in model_code:
            has_decimal = True

    if not parts:
        return ""

    header_lines: list[str] = []
    if has_model:
        header_lines.append("from pydantic import BaseModel")
    if has_decimal:
        header_lines.append("from decimal import Decimal")

    header = "\n".join(header_lines) + "\n\n" if header_lines else ""
    return header + "\n\n".join(parts)


def write_shared_models_file(job_dir: Path, copybooks: dict[str, dict[str, Any]]) -> Path | None:
    text = generate_shared_models_text(copybooks, job_dir)
    if not text:
        return None
    output_path = job_dir / "shared_models.py"
    output_path.write_text(text, encoding="utf-8")
    logger.info(f"Shared models written to {output_path}")
    return output_path
