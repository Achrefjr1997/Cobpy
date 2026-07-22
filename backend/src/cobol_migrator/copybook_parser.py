from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

FIELD_LINE_RE = re.compile(
    r"^\s*(?P<level>\d{2})\s+"
    r"(?P<name>\w+(?:-\w+)*)\s*"
    r"(?P<clauses>.*?)\s*\.\s*$",
    re.IGNORECASE,
)

OCCURS_RE = re.compile(r"OCCURS\s+(?P<count>\d+)\s+TIMES?", re.IGNORECASE)
REDEFINES_RE = re.compile(r"REDEFINES\s+(?P<target>\w+(?:-\w+)*)", re.IGNORECASE)
PIC_RE = re.compile(r"PIC\s+(?P<pic>[\w().]+)", re.IGNORECASE)
USAGE_RE = re.compile(
    r"USAGE\s+(?:IS\s+)?(?P<usage>BINARY|COMP(?:-\d)?|PACKED-DECIMAL|POINTER|INDEX|DISPLAY)",
    re.IGNORECASE,
)
USAGE_SHORTHAND_RE = re.compile(
    r"\b(COMP(?:-\d)?|BINARY|PACKED-DECIMAL|POINTER|INDEX)\b",
    re.IGNORECASE,
)
VALUE_RE = re.compile(r"VALUE(?:S)?\s+(?P<value>.+)", re.IGNORECASE)
INDEXED_BY_RE = re.compile(r"INDEXED\s+BY\s+(?P<idx>\w+(?:-\w+)*)", re.IGNORECASE)

_PIC_CHAR_RE = re.compile(r"([XZA9SVP])(?:\((\d+)\))?")

_FILLER_COUNTER = iter(range(1, 1000))


def _next_filler_id() -> int:
    return next(_FILLER_COUNTER)


@dataclass
class CopybookField:
    level: int
    name: str
    pic: str | None = None
    usage: str | None = None
    occurs_count: int | None = None
    redefines_target: str | None = None
    value: str | None = None
    indexed_by: str | None = None
    children: list[CopybookField] = field(default_factory=list)
    is_88: bool = False
    condition_values: list[str] = field(default_factory=list)


def _normalize_source(source: str) -> str:
    """Join continuation lines that don't start with a level number.

    Handles multi-line COBOL clauses like:
        05 X PIC 9(5)
               OCCURS 10 TIMES.
    """
    lines = source.splitlines()
    result: list[str] = []
    for raw_line in lines:
        stripped = raw_line.rstrip()
        if not stripped.strip() or stripped.strip().startswith("*"):
            result.append(stripped)
            continue
        if re.match(r"^\s*\d{2}\s+", stripped):
            result.append(stripped)
        else:
            if result:
                result[-1] += " " + stripped.lstrip()
            else:
                result.append(stripped)
    return "\n".join(result)


def parse_copybook(source: str) -> list[CopybookField]:
    """Parse a COBOL copybook into a hierarchy of CopybookField nodes.

    Returns a list of top-level (01-level) fields with their children nested.
    Handles OCCURS, REDEFINES, 88-level conditions, GROUP items, PIC clauses,
    FILLER, INDEXED BY, and multi-line clauses.
    """
    normalized = _normalize_source(source)
    lines = normalized.splitlines()
    stack: list[CopybookField] = []
    top_fields: list[CopybookField] = []

    for raw_line in lines:
        stripped = raw_line.strip()
        if not stripped or stripped.startswith("*"):
            continue

        m = FIELD_LINE_RE.match(stripped)
        if not m:
            continue

        level = int(m.group("level"))
        raw_name = m.group("name")
        clauses = m.group("clauses")

        while stack and stack[-1].level >= level:
            stack.pop()

        name = raw_name
        is_filler = name.upper() == "FILLER"
        if is_filler:
            name = f"_filler_{_next_filler_id()}"

        field = CopybookField(level=level, name=name)

        if level == 88:
            field.is_88 = True
            val_m = VALUE_RE.search(clauses)
            if val_m:
                quoted = re.findall(
                    r"'([^']*)'|\"([^\"]*)\"", val_m.group(1)
                )
                field.condition_values = [
                    v[0] or v[1] for v in quoted
                ]
                if not field.condition_values:
                    raw = val_m.group(1).strip()
                    if raw:
                        field.condition_values = [raw]
        else:
            pic_m = PIC_RE.search(clauses)
            if pic_m:
                field.pic = pic_m.group("pic")

            usage_m = USAGE_RE.search(clauses)
            if usage_m:
                field.usage = usage_m.group("usage").upper()
            else:
                shorthand_m = USAGE_SHORTHAND_RE.search(clauses)
                if shorthand_m:
                    field.usage = shorthand_m.group(1).upper()

            occurs_m = OCCURS_RE.search(clauses)
            if occurs_m:
                field.occurs_count = int(occurs_m.group("count"))

            redef_m = REDEFINES_RE.search(clauses)
            if redef_m:
                field.redefines_target = redef_m.group("target")

            idx_m = INDEXED_BY_RE.search(clauses)
            if idx_m:
                field.indexed_by = idx_m.group("idx")

            val_m = VALUE_RE.search(clauses)
            if val_m:
                raw_val = val_m.group("value")
                raw_val = raw_val.strip()
                if len(raw_val) > 0 and raw_val[0] in ("'", '"'):
                    pass
                else:
                    raw_val = raw_val.rstrip(".")
                field.value = raw_val

        if not stack:
            top_fields.append(field)
        else:
            stack[-1].children.append(field)

        if not field.is_88:
            stack.append(field)

    return top_fields


def pic_to_python_type(pic: str, usage: str | None = None) -> str:
    """Map PIC clause and optional USAGE to Python type.

    Handles both display usage (X, 9, A, S, V, Z, edited patterns)
    and binary/packed usage (COMP, COMP-3, COMP-5, BINARY, PACKED-DECIMAL,
    COMP-1, COMP-2, POINTER).
    """
    pic_upper = pic.upper() if pic else ""
    usage_key = usage.upper().strip() if usage else ""

    if not pic_upper and usage_key not in ("COMP-1", "COMP-2", "POINTER"):
        return "str"

    # USAGE overrides PIC-based inference
    if usage_key == "COMP-1":
        return "float"
    if usage_key == "COMP-2":
        return "float"
    if usage_key == "POINTER":
        return "int"

    # COMP-3 / PACKED-DECIMAL always -> Decimal (packed BCD)
    if usage_key in ("COMP-3", "PACKED-DECIMAL"):
        return "Decimal"

    # COMP / BINARY / COMP-5 -> int if no decimal point, Decimal if V
    if usage_key in ("COMP", "COMP-5", "BINARY"):
        if "V" in pic_upper:
            return "Decimal"
        return "int"

    # DISPLAY usage (default) — existing logic
    if not pic_upper:
        return "str"

    # Edited numeric fields (Z, +, -, $, CR, DB, *, /, comma, period) -> str
    edited_chars = set("Z+-$*,/")
    for ch in pic_upper:
        if ch in edited_chars:
            return "str"
    if "CR" in pic_upper or "DB" in pic_upper:
        return "str"

    if "9" in pic_upper:
        if "V" in pic_upper:
            return "Decimal"
        return "int"
    return "str"


def pic_to_length(pic: str, usage: str | None = None) -> int:
    """Calculate storage length from PIC clause and optional USAGE.

    Handles:
      DISPLAY — each PIC char = 1 byte
      COMP / BINARY / COMP-5 — binary (2, 4, or 8 bytes)
      COMP-3 / PACKED-DECIMAL — packed BCD
      COMP-1 — float (4 bytes)
      COMP-2 — double (8 bytes)
      POINTER — address (8 bytes)
    """
    pic_upper = pic.upper() if pic else ""
    usage_key = usage.upper().strip() if usage else ""

    if not pic_upper and usage_key not in ("COMP-1", "COMP-2", "POINTER"):
        return 0

    # Count total display digits (excluding S and V)
    digits = 0
    for part in _PIC_CHAR_RE.findall(pic_upper):
        char, count = part
        count = int(count) if count else 1
        if char in ("S", "V"):
            continue
        digits += count

    if usage_key == "COMP-1":
        return 4
    if usage_key == "COMP-2":
        return 8
    if usage_key == "POINTER":
        return 8

    if usage_key in ("COMP-3", "PACKED-DECIMAL"):
        if digits == 0:
            return 0
        return (digits + 2) // 2

    if usage_key in ("COMP", "COMP-5", "BINARY"):
        if digits <= 4:
            return 2
        if digits <= 9:
            return 4
        return 8

    # DISPLAY: each PIC character = 1 byte
    length = 0
    for part in _PIC_CHAR_RE.findall(pic_upper):
        char, count = part
        count = int(count) if count else 1
        if char in ("S", "V"):
            continue
        length += count
    return length if length > 0 else 0
