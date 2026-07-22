# COBOL Support Gaps — Detailed Implementation Plan

> **Date:** July 2026
> **Goal:** Fix all critical COBOL parsing gaps (OCCURS, REDEFINES, 88-levels, transitive deps, nested models) in the existing `cobol2python` codebase

---

## Table of Contents

1. [Problem 1: OCCURS Tables → Nested Pydantic Models](#problem-1-occurs-tables--nested-pydantic-models)
2. [Problem 2: REDEFINES → Overlapping Storage](#problem-2-redefines--overlapping-storage)
3. [Problem 3: 88-Level Conditions → Validation Enums](#problem-3-88-level-conditions--validation-enums)
4. [Problem 4: Transitive Dependency Resolution](#problem-4-transitive-dependency-resolution)
5. [Problem 5: Test Environment Module Discovery](#problem-5-test-environment-module-discovery)
6. [Problem 6: LLM Context Enhancement](#problem-6-llm-context-enhancement)
7. [Integration & Testing Plan](#integration--testing-plan)
8. [Timeline & Effort Summary](#timeline--effort-summary)

---

## Problem 1: OCCURS Tables → Nested Pydantic Models

### Current Behavior

File: `backend/src/cobol_migrator/shared_model_generator.py`

The `generate_pydantic_model()` function (line 88) uses `FIELD_RE` regex that only matches individual field lines. When a COBOL copybook has:

```cobol
01 RMAMAST.
   05 RMA-NUMBER            PIC X(12).
   05 RMA-LINE-TABLE OCCURS 50 TIMES.
      10 RL-ITEM-ID         PIC X(12).
      10 RL-ITEM-CATEGORY   PIC X(02).
      10 RL-ORIGINAL-QTY    PIC 9(4).
      10 RL-UNIT-PRICE      PIC 9(7)V99.
```

The parser produces:
```python
class RmamastModel(BaseModel):
    rma_number: str
    rma_line_table: str           # ← OCCURS has no PIC → defaults to "str"
    rl_item_id: str               # ← child fields "leaked" to top level
    rl_item_category: str
    rl_original_qty: int
    rl_unit_price: Decimal
```

### Problems This Causes

1. `rma_line_table[i]` indexing fails at runtime (str is not subscriptable with int)
2. No `LineItem` class exists → `from shared_models import LineItem` gives ImportError
3. Child fields polluted into parent namespace → IDE autocomplete shows wrong fields
4. LLM generates incorrect table-access code because the model doesn't reflect the COBOL structure

### Root Cause

The `FIELD_RE` regex at line 26-30:
```python
FIELD_RE = re.compile(
    r"^\s*(?P<level>\d{2})\s+(?P<name>\w+(?:-\w+)*)\s+"
    r"(?:PIC\s+)?(?P<pic>[\w().]+)",
    re.IGNORECASE | re.MULTILINE,
)
```

This regex:
- Only matches lines that have a PIC clause
- When OCCURS has no PIC (it's a group item), the OCCURS keyword is not captured → the field name is captured but PIC group is empty → defaults to `str`
- Child fields under OCCURS are matched as independent top-level fields because hierarchy is not tracked

The `extract_copybook_fields()` at line 33 returns a **flat list** of dicts with no parent/child relationship:
```python
fields: list[dict[str, Any]] = []
```

### Implementation

#### Step 1: Build a Hierarchy-Aware Copybook Parser

Create a new file `backend/src/cobol_migrator/copybook_parser.py`:

```python
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional

FIELD_LINE_RE = re.compile(
    r"^\s*(?P<level>\d{2})\s+"
    r"(?P<name>\w+(?:-\w+)*)\s*"
    r"(?P<clauses>.*?)\s*\.\s*$",
    re.IGNORECASE,
)

OCCURS_RE = re.compile(r"OCCURS\s+(?P<count>\d+)\s+TIMES", re.IGNORECASE)
REDEFINES_RE = re.compile(r"REDEFINES\s+(?P<target>\w+(?:-\w+)*)", re.IGNORECASE)
PIC_RE = re.compile(r"PIC\s+(?P<pic>[\w().]+)", re.IGNORECASE)
VALUE_RE = re.compile(r"VALUE\s+(?P<value>'.*?'|\".*?\"|\S+)", re.IGNORECASE)

@dataclass
class CopybookField:
    level: int
    name: str
    pic: str | None = None
    occurs_count: int | None = None
    redefines_target: str | None = None
    value: str | None = None
    children: list[CopybookField] = field(default_factory=list)
    is_88: bool = False
    condition_values: list[str] = field(default_factory=list)


def parse_copybook(source: str) -> list[CopybookField]:
    """Parse a COBOL copybook into a hierarchy of CopybookField nodes.

    Returns a list of top-level (01-level) fields with their children nested.
    Handles OCCURS, REDEFINES, 88-level conditions, GROUP items, PIC clauses.
    """
    lines = source.splitlines()
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
        name = m.group("name")
        clauses = m.group("clauses").upper()

        # Pop stack until we find the parent for this level
        while stack and stack[-1].level >= level:
            stack.pop()

        field = CopybookField(level=level, name=name)

        # Detect field type
        if level == 88:
            field.is_88 = True
            # Extract condition values (multiple possible: THRU, OR)
            val_m = VALUE_RE.search(clauses)
            if val_m:
                field.condition_values = _parse_88_values(val_m.group("value"))
        else:
            # Normal field
            pic_m = PIC_RE.search(clauses)
            if pic_m:
                field.pic = pic_m.group("pic")

            occurs_m = OCCURS_RE.search(clauses)
            if occurs_m:
                field.occurs_count = int(occurs_m.group("count"))

            redef_m = REDEFINES_RE.search(clauses)
            if redef_m:
                field.redefines_target = redef_m.group("target")

            val_m = VALUE_RE.search(clauses)
            if val_m:
                raw_val = val_m.group("value")
                if not (raw_val.startswith("'") or raw_val.startswith('"')):
                    raw_val = raw_val.rstrip(".")
                field.value = raw_val

        if not stack:
            top_fields.append(field)
        else:
            stack[-1].children.append(field)

        if not field.is_88:
            stack.append(field)

    return top_fields


def _parse_88_values(raw: str) -> list[str]:
    """Parse 88-level condition values like 'A' 'B' THRU 'D'."""
    values = []
    parts = re.findall(r"'(?:[^']*)'|\"(?:[^\"]*)\"|\w+", raw)
    i = 0
    while i < len(parts):
        val = parts[i].strip("'\"")
        if val.upper() == "THRU" and i > 0 and i + 1 < len(parts):
            # Range: previous value THRU next value
            values.append(f"{parts[i-1].strip(chr(39)+chr(34))}:{parts[i+1].strip(chr(39)+chr(34))}")
            i += 2
            continue
        values.append(val)
        i += 1
    return values
```

#### Step 2: Enhance `pic_to_python_type()` for COMP Usage

In `shared_model_generator.py`, update `pic_to_python_type()` to handle edge cases:

```python
def pic_to_python_type(pic: str, usage: str | None = None) -> str:
    """Map PIC clause to Python type, considering USAGE."""
    pic_upper = pic.upper() if pic else ""

    # COMP-3 / PACKED-DECIMAL -> always Decimal
    if usage and "COMP" in usage.upper():
        if "COMP-3" in usage.upper() or "PACKED" in usage.upper():
            return "Decimal"
        if usage.upper() in ("COMP-1", "COMP-2"):
            return "float"
        if usage.upper() == "COMP-5":
            return "int"

    if not pic_upper:
        return "str"  # No PIC -> group item, but flattened

    if "9" in pic_upper:
        if "V" in pic_upper:
            return "Decimal"
        return "int"
    return "str"


def pic_to_length(pic: str) -> int:
    """Calculate storage length from PIC clause."""
    pic_upper = pic.upper() if pic else ""
    length = 0
    # Parse compound patterns like X(10), 9(5), A(3)
    for part in re.findall(r"([XZA9SVP])(?:\((\d+)\))?", pic_upper):
        char, count = part
        count = int(count) if count else 1
        if char == "S":  # Sign does not occupy storage
            continue
        if char == "V":  # Implied decimal doesn't occupy storage
            continue
        length += count
    return length if length > 0 else len(pic_upper)
```

#### Step 3: Rewrite `generate_pydantic_model()` for Hierarchy

Replace the flat model generation with hierarchy-aware generation:

```python
def generate_pydantic_model(field: CopybookField) -> str:
    """Generate a Pydantic model from a top-level copybook field.

    Recursively handles:
    - Group items -> nested Pydantic models (only if has OCCURS or multiple children)
    - OCCURS -> list[ChildModel]
    - Elementary fields -> typed fields
    - 88-level -> constants and validators
    - VALUE -> field defaults
    """
    if field.is_88:
        return ""  # Handled by parent's 88-processing

    # Check if this field needs a dedicated class (OCCURS group or multi-child group)
    has_occurs_children = any(c.occurs_count for c in field.children if not c.is_88)
    has_group_children = len([c for c in field.children if not c.is_88]) > 0
    needs_class = has_occurs_children or has_group_children

    # Gather 88-level conditions for this field
    constants = _generate_88_constants(field)

    if needs_class:
        # Generate a class for this group
        model_name = field.name.replace("-", "_").replace(".", "_").title()
        if not model_name.endswith("Model"):
            model_name += "Model"

        field_lines: list[str] = []
        child_models: list[str] = []

        for child in field.children:
            if child.is_88:
                continue  # Already handled in constants

            if child.occurs_count:
                # OCCURS child -> generate a nested model
                child_model = _generate_nested_occurs_model(child)
                if child_model:
                    child_models.append(child_model)
                    child_type = f"{child.name.replace('-', '_').title()}Model"
                    if not child_type.endswith("Model"):
                        child_type += "Model"

                    # Check for DEPENDING ON
                    if child.occurs_count:
                        field_lines.append(
                            f"    {_py_name(child.name)}: list[{child_type}]"
                        )
            elif _has_group_children(child):
                # Recursive group
                child_result = generate_pydantic_model(child)
                if child_result:
                    child_models.append(child_result)
                    child_type = child.name.replace("-", "_").title() + "Model"
                    field_lines.append(
                        f"    {_py_name(child.name)}: {child_type}"
                    )
            else:
                # Elementary field
                py_type = pic_to_python_type(child.pic or "")
                field_lines.append(
                    f"    {_py_name(child.name)}: {py_type}  # {child.pic or 'group'}"
                )

        parts: list[str] = []
        if constants:
            parts.extend(constants)
        if child_models:
            parts.extend(child_models)
        if parts and constants and child_models:
            parts.append("")

        parts.append(f"class {model_name}(BaseModel):")
        parts.append(f'    """Generated from {field.name}."""')
        if field_lines:
            parts.append("")
            parts.extend(field_lines)

        return "\n\n".join(parts)
    else:
        # Simple field - no class needed
        py_type = pic_to_python_type(field.pic or "")
        return f"{_py_name(field.name)}: {py_type}  # {field.pic or ''}"


def _generate_88_constants(field: CopybookField) -> list[str]:
    """Generate constant definitions from 88-level child fields."""
    constants: list[str] = []
    parent_py_name = _py_name(field.name)
    for child in field.children:
        if child.is_88 and child.condition_values:
            for val in child.condition_values:
                const_name = f"{parent_py_name}_{child.name.upper().replace('-', '_')}_{val.replace(':', '_TO_')}"
                # Determine type from the value
                if val.isdigit():
                    constants.append(f"{const_name}: int = {val}")
                else:
                    constants.append(f"{const_name}: str = '{val}'")
    return constants


def _py_name(cobol_name: str) -> str:
    return cobol_name.lower().replace("-", "_")


def _has_group_children(field: CopybookField) -> bool:
    return len([c for c in field.children if not c.is_88]) > 0


def _generate_nested_occurs_model(parent: CopybookField) -> str:
    """Generate a nested Pydantic model for an OCCURS group."""
    children = [c for c in parent.children if not c.is_88]
    if not children:
        return ""

    model_name = parent.name.replace("-", "_").replace(".", "_").title()
    if not model_name.endswith("Model"):
        model_name += "Model"

    field_lines: list[str] = []
    for child in children:
        if child.occurs_count:
            # Multi-dimensional OCCURS -> recursive
            sub_model = _generate_nested_occurs_model(child)
            if sub_model:
                sub_name = child.name.replace("-", "_").title() + "Model"
                field_lines.append(f"    {_py_name(child.name)}: list[{sub_name}]")
                sub_result = _generate_nested_occurs_model(child)
                if sub_result:
                    return sub_result + "\n\n" + _build_model(model_name, field_lines)
            continue
        py_type = pic_to_python_type(child.pic or "")
        field_lines.append(f"    {_py_name(child.name)}: {py_type}  # {child.pic or ''}")

    return _build_model(model_name, field_lines)


def _build_model(name: str, fields: list[str]) -> str:
    parts = [f"class {name}(BaseModel):", f'    """Generated OCCURS model."""']
    if fields:
        parts.append("")
        parts.extend(fields)
    return "\n".join(parts)
```

#### Step 4: Update `extract_copybook_fields()` Callers

The `generate_shared_models_text()` at line 125 needs to use the new parser:

```python
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

        # NEW: Use hierarchy-aware parser
        top_fields = parse_copybook(source)
        for field in top_fields:
            model_code = generate_pydantic_model(field)
            if not model_code:
                continue
            parts.append(model_code)

        # Check for Decimal usage
        for field in top_fields:
            _check_decimal_usage(field)

    # ... rest remains the same
```

#### Step 5: Fix `_check_decimal_usage` Recursive Helper

```python
def _check_decimal_usage(field: CopybookField) -> bool:
    """Recursively check if any child uses Decimal type."""
    has = False
    if field.pic and ("V" in field.pic.upper()):
        has = True
    for child in field.children:
        if _check_decimal_usage(child):
            has = True
    return has
```

### Problems Solved

| Symptom | Root Cause | Fix |
|---------|-----------|-----|
| `ImportError: cannot import name 'LineItem'` | No nested model generated for OCCURS group | Hierarchy-aware parser creates `LineItem` class |
| `rma_line_table: str` (wrong type) | OCCURS not parsed, PIC defaults to empty | OCCURS detected -> `list[LineItem]` type |
| Child fields at model root | Flat field list, no hierarchy | Children nested under parent model |
| `rma_line_table[i]` type error | str is not subscriptable with int | `list[LineItem]` supports indexing |

---

## Problem 2: REDEFINES → Overlapping Storage

### Current Behavior

REDEFINES clauses are captured as raw text by `interface_extractor.py:48-49` but not structurally parsed. `shared_model_generator.py` treats redefined fields as independent.

```cobol
05 WS-BUFFER PIC X(20).
05 WS-NUM-FIELD REDEFINES WS-BUFFER PIC 9(20).
```

Produces:
```python
ws_buffer: str    # 20 chars
ws_num_field: int # but shares same storage!
```

### Problems This Causes

1. Generated Python gives both fields independent storage → they hold different values
2. In COBOL, writing to `WS-NUM-FIELD` also changes `WS-BUFFER` (they overlap)
3. Record parsing produces wrong results when fields are redefined

### Implementation

#### Step 1: Track REDEFINES in Field Metadata

Already handled by `CopybookField.redefines_target` in the parser from Problem 1.

#### Step 2: Generate Bytes-Backed Record for REDEFINES-Having Models

Create `backend/src/cobol_migrator/model_generator.py`:

```python
from __future__ import annotations

from cobol_migrator.copybook_parser import CopybookField, pic_to_length

def generate_redefines_model(field: CopybookField) -> str:
    """Generate a bytes-backed Python class for fields with REDEFINES.

    Instead of multiple independent attributes, generate a single
    record class that reads/writes from a shared bytes buffer.

    For simple cases (no REDEFINES), still use regular Pydantic.
    """
    has_redefines = _has_redefines(field)

    if not has_redefines:
        # No REDEFINES -> standard Pydantic model
        return generate_pydantic_model(field)

    # Has REDEFINES -> generate bytes-backed class
    model_name = field.name.replace("-", "_").title()
    if not model_name.endswith("Record"):
        model_name += "Record"

    total_length = _calculate_record_length(field)
    lines: list[str] = []
    lines.append(f"class {model_name}:")
    lines.append(f'    """Bytes-backed record with overlapping REDEFINES fields.')
    lines.append(f"    Total record length: {total_length} bytes.")
    lines.append(f'    """')
    lines.append("")
    lines.append("    def __init__(self, data: bytes | None = None):")
    lines.append(f"        self._data = bytearray(data or b'\\x00' * {total_length})")
    lines.append("")

    # Group fields by redefine group
    groups = _group_redefines(field)

    for group_name, members in groups:
        for m in members:
            offset = _get_field_offset(field, m)
            length = pic_to_length(m.pic or "")

            if m.redefines_target:
                # This field shares storage with target
                lines.append(f"    @property")
                lines.append(f"    def {_py_name(m.name)}(self) -> {'int' if '9' in (m.pic or '') else 'str'}:")
                lines.append(f"        \"\"\"REDEFINES {m.redefines_target}.\"\"\"")
                if '9' in (m.pic or ''):
                    lines.append(f"        return int(self._data[{offset}:{offset+length}].decode().strip())")
                else:
                    lines.append(f"        return self._data[{offset}:{offset+length}].decode()")
                lines.append("")
                lines.append(f"    @{_py_name(m.name)}.setter")
                lines.append(f"    def {_py_name(m.name)}(self, value):")
                if '9' in (m.pic or ''):
                    lines.append(f"        self._data[{offset}:{offset+length}] = str(value).zfill({length}).encode()")
                else:
                    lines.append(f"        self._data[{offset}:{offset+length}] = str(value).ljust({length}).encode()")
                lines.append("")
            else:
                # Normal field (not REDEFINES)
                lines.append(f"    @property")
                lines.append(f"    def {_py_name(m.name)}(self) -> {'int' if '9' in (m.pic or '') else 'str'}:")
                if '9' in (m.pic or ''):
                    lines.append(f"        return int(self._data[{offset}:{offset+length}].decode().strip())")
                else:
                    lines.append(f"        return self._data[{offset}:{offset+length}].decode()")
                lines.append("")
                lines.append(f"    @{_py_name(m.name)}.setter")
                lines.append(f"    def {_py_name(m.name)}(self, value):")
                if '9' in (m.pic or ''):
                    lines.append(f"        self._data[{offset}:{offset+length}] = str(value).zfill({length}).encode()")
                else:
                    lines.append(f"        self._data[{offset}:{offset+length}] = str(value).ljust({length}).encode()")
                lines.append("")

    return "\n".join(lines)


def _has_redefines(field: CopybookField) -> bool:
    """Check if field or any child has REDEFINES."""
    if field.redefines_target:
        return True
    return any(_has_redefines(c) for c in field.children)


def _calculate_record_length(field: CopybookField) -> int:
    """Calculate total record length from all non-REDEFINES fields."""
    total = 0
    for child in field.children:
        if child.is_88:
            continue
        if child.redefines_target:
            continue  # REDEFINES fields share storage
        if child.pic:
            total += pic_to_length(child.pic)
        if child.occurs_count and child.children:
            # For OCCURS, multiply by children length
            child_len = sum(
                pic_to_length(gc.pic or "") for gc in child.children if not gc.is_88
            )
            total += child_len * child.occurs_count
    return total


def _group_redefines(field: CopybookField) -> list[tuple[str, list[CopybookField]]]:
    """Group fields by redefine chain (fields sharing storage)."""
    groups: list[tuple[str, list[CopybookField]]] = []
    current_group_name = field.name
    current_members: list[CopybookField] = []

    for child in field.children:
        if child.is_88:
            continue
        if child.redefines_target or child.redefines_target is not None:
            # Start a new redefine group
            if current_members:
                groups.append((current_group_name, current_members))
            current_group_name = child.redefines_target or child.name
            current_members = [child]
        else:
            current_members.append(child)

    if current_members:
        groups.append((current_group_name, current_members))

    return groups


def _get_field_offset(root: CopybookField, target: CopybookField) -> int:
    """Calculate byte offset of a field within a record."""
    offset = 0
    for child in root.children:
        if child is target:
            return offset
        if child.redefines_target:
            continue  # REDEFINES fields don't advance offset
        if child.pic:
            offset += pic_to_length(child.pic)
        if child.occurs_count and child.children:
            child_len = sum(
                pic_to_length(gc.pic or "") for gc in child.children if not gc.is_88
            )
            offset += child_len * child.occurs_count
    return offset
```

### Problems Solved

| Symptom | Root Cause | Fix |
|---------|-----------|-----|
| Redefined fields hold independent values | Flat field list assigns separate storage | Bytes-backed record with shared `_data` buffer |
| Wrong record length calculations | REDEFINES fields double-counted | `_calculate_record_length` skips REDEFINES fields |
| LLM generates wrong overlapping field logic | No structural REDEFINES info in context | Property-based accessors with `@property.setter` |

---

## Problem 3: 88-Level Conditions → Validation Enums

### Current Behavior

File: `shared_model_generator.py:38-39`

```python
if level == 88:
    continue  # ← silently skipped
```

### Problems This Causes

1. Condition values like `88 WS-ACTIVE VALUE 'A'` are lost
2. `SET WS-STATUS TO TRUE` in COBOL has no generated equivalent
3. LLM must guess valid values for fields from raw source
4. No validation in Pydantic models for constrained fields

### Implementation

#### Step 1: Collect 88-Level Conditions During Parsing

Already handled by the `_generate_88_constants()` function in Problem 1's Step 3. The `parse_copybook()` function captures 88-level entries with their condition values.

#### Step 2: Generate Validation Constants

For this copybook input:
```cobol
05 RMA-OVERALL-STATUS PIC X(01).
   88 RMA-STATUS-APPROVED VALUE 'A'.
   88 RMA-STATUS-REJECTED VALUE 'R'.
   88 RMA-STATUS-PENDING  VALUE 'P'.
```

Generate:
```python
# Constants
RMA_OVERALL_STATUS_RMA_STATUS_APPROVED: str = 'A'
RMA_OVERALL_STATUS_RMA_STATUS_REJECTED: str = 'R'
RMA_OVERALL_STATUS_RMA_STATUS_PENDING: str = 'P'

class RmamastModel(BaseModel):
    rma_overall_status: str = Field(default='P')

    @validator('rma_overall_status')
    def validate_rma_overall_status(cls, v):
        valid = {'A', 'R', 'P'}
        if v not in valid:
            raise ValueError(f"Invalid rma_overall_status: {v}. Valid: {valid}")
        return v
```

#### Step 3: Generate `SET TO TRUE` Logic

For COBOL's `SET RMA-STATUS-APPROVED TO TRUE`, generate a helper method:

```python
def set_status_true(self, condition_name: str) -> None:
    """Implement COBOL SET ... TO TRUE for 88-level conditions."""
    mapping = {
        "RMA_STATUS_APPROVED": "A",
        "RMA_STATUS_REJECTED": "R",
        "RMA_STATUS_PENDING": "P",
    }
    if condition_name in mapping:
        self.rma_overall_status = mapping[condition_name]
```

### Problems Solved

| Symptom | Root Cause | Fix |
|---------|-----------|-----|
| `88 WS-VALUE VALUE 'X'` silently dropped | `if level == 88: continue` | Parse as condition with values |
| No validation for constrained fields | No valid value set generated | `@validator` with allowed values |
| `SET condition TO TRUE` not implementable | No mapping from 88-name to value | `set_status_true()` helper |

---

## Problem 4: Transitive Dependency Resolution

### Current Behavior

File: `backend/src/cobol_migrator/batch_manager.py:180-184`

```python
dep_code = {
    pid: code
    for pid, code in completed_code.items()
    if pid in graph.get(program_id, {}).get("calls", [])
}
```

### Problems This Causes

```
RMADRIVE → calls RETNPROC → calls WARRCHK
                            → calls REFCALC
                            → calls EXCHPROC → calls RESTOCK
                                          → calls FRAUDRET
```

When RMADRIVE is migrated:
- `dep_code` = `{RETNPROC: ..., EXCHPROC: ...}` (direct calls only)
- RETNPROC's code contains `from warrchk import ...` → ModuleNotFoundError
- RETNPROC's code contains `from refcalc import ...` → ModuleNotFoundError

### Implementation

#### Step 1: Build Transitive Closure Function

```python
def _get_transitive_callees(
    program_id: str,
    graph: dict[str, dict[str, Any]],
    visited: set[str] | None = None,
) -> set[str]:
    """Get all transitive CALL targets for a program (DFS)."""
    if visited is None:
        visited = set()

    direct_calls = set(graph.get(program_id, {}).get("calls", []))
    all_callees = set(direct_calls)

    for callee in direct_calls:
        if callee not in visited and callee in graph:
            visited.add(callee)
            transitive = _get_transitive_callees(callee, graph, visited)
            all_callees.update(transitive)

    return all_callees
```

#### Step 2: Update batch_manager.py

```python
# Line 180: Replace direct-only with transitive
all_callees = _get_transitive_callees(program_id, graph)
dep_code = {
    pid: code
    for pid, code in completed_code.items()
    if pid in all_callees
}
```

#### Step 3: Handle Circular Dependencies

Add cycle protection (already in the `visited` set) and log warnings:

```python
# In _get_transitive_callees, add:
if program_id in visited:
    logger.warning(f"Circular dependency detected for {program_id}")
    return set()
```

### Problems Solved

| Symptom | Root Cause | Fix |
|---------|-----------|-----|
| `ModuleNotFoundError: No module named 'warrchk'` | Only direct CALLs in dep_code | Transitive closure includes all reachable CALL targets |
| `ModuleNotFoundError: No module named 'refcalc'` | Same | Same |
| Multiple migration failures for programs with deep CALL chains | Each migration re-fails the same way | One fix covers all depths |

---

## Problem 5: Test Environment Module Discovery

### Current Behavior

File: `backend/src/cobol_migrator/test_environment.py:154`

```python
local_modules = {"main", "test_main", "__init__", "shared_models"}
```

### Problems This Causes

1. Unknown modules (like `warrchk`, `refcalc`) are treated as pip packages → `pip install` fails
2. Even with transitive deps in `dep_code`, the `_get_required_packages()` function tries to install them

### Implementation

#### Step 1: Derive Local Modules from dependency_code

```python
# Line 154: Replace hardcoded set with dynamic derivation
local_modules = {"main", "test_main", "__init__", "shared_models"}

# Add all dependency modules as local
if dependency_code:
    local_modules.update(m.lower() for m in dependency_code.keys())

# Also scan dependency code for additional imports
if dependency_code:
    for module_name, module_code in dependency_code.items():
        imported = _extract_imports(module_code)
        local_modules.update(
            m.lower() for m in imported
            if m not in STDLIB_MODULES and m.lower() != "shared_models"
        )
```

#### Step 2: Remove `extra_local_modules` Parameter

The `extra_local_modules` parameter at line 549 becomes redundant since `dependency_code` now contains all transitive deps. Simplify:

```python
# Line 549: Remove extra_local parameter, just pass dependency_code
packages = _get_required_packages(python_code, test_code, set(dependency_code.keys()) if dependency_code else None)

# But _get_required_packages already calls local_modules.update(extra_local)
# So this works correctly now since dependency_code has ALL modules
```

### Problems Solved

| Symptom | Root Cause | Fix |
|---------|-----------|-----|
| `pip install warrentchk` tries to install program modules | Unknown modules treated as pip packages | All dependency modules registered as local |
| Test sandbox missing `warrchk.py` | Not in dependency_code, not in local_modules | Now in dependency_code → both written to sandbox and registered as local |

---

## Problem 6: LLM Context Enhancement

### Current Behavior

File: `backend/src/cobol_migrator/agent/nodes/translate.py:135-149`

```python
def _build_shared_models_context(state: AgentState) -> str:
    model_code = state.get("shared_model_code")
    if not model_code:
        return ""
    model_names = re.findall(r"^class\s+(\w+)", model_code, re.MULTILINE)
    import_list = ", ".join(model_names) if model_names else "..."
    return (
        "## Shared Data Models (from copybooks)\n"
        f"Import them with: `from shared_models import {import_list}`\n"
        f"```python\n{model_code}\n```"
    )
```

### Problems This Causes

1. Raw model code is verbose (lots of boilerplate)
2. OCCURS tables just show `list[LineItem]` without the table semantics
3. COBOL-specific constraints (PIC, OCCURS COUNT) are not visible to LLM
4. LLM must infer how to index into tables, how fields map to file records

### Implementation

#### Step 1: Build Structured Context for Models

```python
def _build_shared_models_context(state: AgentState) -> str:
    model_code = state.get("shared_model_code")
    cobol_source = state.get("cobol_source", "")

    if not model_code:
        return ""

    import re
    model_names = re.findall(r"^class\s+(\w+)", model_code, re.MULTILINE)
    import_list = ", ".join(model_names) if model_names else "..."

    # Build a structured summary alongside the raw model code
    structure_lines = [_build_model_structure(model_code)]
    structure = "\n".join(structure_lines) if structure_lines else ""

    return (
        "## Shared Data Models (from copybooks)\n"
        "These Pydantic models are defined in **shared_models.py**.\n"
        f"Import them with: `from shared_models import {import_list}`\n"
        "Do NOT redefine them — use the shared model.\n\n"
        "### Structure Summary\n"
        f"{structure}\n\n"
        "### Full Pydantic Code\n"
        f"```python\n{model_code}\n```"
    )


def _build_model_structure(model_code: str) -> str:
    """Extract structured field info from model code."""
    lines = []
    current_class = None
    for line in model_code.splitlines():
        class_m = re.match(r"^class\s+(\w+)", line)
        if class_m:
            current_class = class_m.group(1)
            lines.append(f"  {current_class}:")
            continue
        field_m = re.match(r"^\s+(\w+):\s+(\w+.*?)(?:\s+#\s*(.*))?$", line)
        if field_m and current_class:
            name = field_m.group(1)
            py_type = field_m.group(2)
            pic = field_m.group(3) or ""
            # Detect OCCURS (list type)
            if py_type.startswith("list["):
                child_type = py_type[5:-1]
                lines.append(f"    ├── {name}: {py_type} [TABLE]")
            else:
                lines.append(f"    ├── {name}: {py_type}  {pic}")
    return "\n".join(lines)
```

#### Step 2: Add Copybook Source Context

```python
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
```

#### Step 3: Enhance the Translate Prompt

In `translate.py`'s `TRANSLATE_SYSTEM_PROMPT`, add guidance for OCCURS table access:

```
### Table Access (OCCURS)
When the shared model has OCCURS fields typed as `list[ChildModel]`:
- Use `model.field_name[i]` to access element at 0-based index i
- Use `for item in model.field_name:` to iterate
- COBOL uses 1-based indexing, so `TABLE(1)` → Python `table[0]`
- The `model.field_name[i].child_field` accesses nested fields

### Fixed-Width Record I/O
When reading/writing files with COBOL layouts:
- Each record is `total_length` bytes, fields are concatenated with no separators
- Use record-level `bytes` parsing with field offsets
- REDEFINES fields share the same bytes — use property-based access
```

### Problems Solved

| Symptom | Root Cause | Fix |
|---------|-----------|-----|
| LLM misindexes tables (1-based vs 0-based) | No guidance in prompt about OCCURS meaning | Explicit table indexing rules in prompt |
| LLM creates wrong imports | Model code is long and LLM skips reading it | Structured summary shows key info at a glance |
| LLM produces wrong file I/O code | No record layout context in prompt | Fixed-width record guidance with offsets |

---

## Integration & Testing Plan

### Step 1: Unit Tests for New Parser

Create `backend/tests/test_copybook_parser.py`:

```python
def test_parse_occurs():
    source = """01 RMAMAST.
       05 RMA-NUMBER PIC X(12).
       05 RMA-LINE-TABLE OCCURS 50 TIMES.
          10 RL-ITEM-ID PIC X(12).
          10 RL-UNIT-PRICE PIC 9(7)V99.
    """
    fields = parse_copybook(source)
    assert len(fields) == 1
    assert fields[0].name == "RMAMAST"
    assert fields[0].children[0].name == "RMA-NUMBER"
    assert fields[0].children[1].name == "RMA-LINE-TABLE"
    assert fields[0].children[1].occurs_count == 50
    assert len(fields[0].children[1].children) == 2

def test_parse_redefines():
    source = """01 DATA-REC.
       05 TEXT-FIELD PIC X(20).
       05 NUM-FIELD REDEFINES TEXT-FIELD PIC 9(20).
    """
    fields = parse_copybook(source)
    assert fields[0].children[1].redefines_target == "TEXT-FIELD"

def test_parse_88_level():
    source = """05 STATUS-CODE PIC X(01).
       88 STATUS-ACTIVE VALUE 'A'.
       88 STATUS-INACTIVE VALUE 'I'.
    """
    fields = parse_copybook(source)
    assert len(fields[0].children) == 3  # main + 2 x 88-level
    assert fields[0].children[1].is_88
    assert fields[0].children[1].condition_values == ["A"]

def test_generate_nested_model():
    top_fields = parse_copybook(source_with_occurs)
    result = generate_pydantic_model(top_fields[0])
    assert "class RmamastModel" in result
    assert "class RmaLineTableModel" in result
    assert "rma_line_table: list[RmaLineTableModel]" in result
```

### Step 2: Integration Test → Monolith Corpus

Run against `monolith_corpus_1.zip` (2 programs, 3 copybooks):

1. **Before fix**: `shared_models.py` has flat fields, `rma_line_table: str`
2. **After fix**: `shared_models.py` has nested models, `rma_line_table: list[LineItem]`
3. Verify that generated Python imports and instantiates successfully

### Step 3: Integration Test → Returns Corpus

Run against `returns_corpus.zip` (7 programs, inter-CALL, OCCURS):

1. **Before fix**: `ModuleNotFoundError: No module named 'warrchk'` on transitive CALL chain
2. **After fix**: All 7 programs migrate and test successfully
3. Verify that `shared_models.py` contains `LineItem` and `list[LineItem]`

### Step 4: Regression Tests

- Run the existing validation suite on all existing programs
- Verify no regressions on programs that don't use OCCURS/REDEFINES

---

## Timeline & Effort Summary

| Phase | Tasks | Files | Effort | Dependencies |
|-------|-------|-------|--------|-------------|
| **Phase 1: Quick Wins** | | | **5 days** | |
| 1.1 | Transitive closure | `batch_manager.py:180-184` | 2 hours | None |
| 1.2 | Module discovery | `test_environment.py:154` | 1 hour | 1.1 |
| 1.3 | Parse 88-levels | `copybook_parser.py` (new) | 2 days | None |
| 1.4 | Constants from 88s | `shared_model_generator.py` | 1 day | 1.3 |
| **Phase 2: Core Parsing** | | | **8 days** | |
| 2.1 | Hierarchy parser | `copybook_parser.py` | 3 days | None |
| 2.2 | OCCURS -> nested model | `shared_model_generator.py` | 2 days | 2.1 |
| 2.3 | REDEFINES tracking | `model_generator.py` (new) | 2 days | 2.1 |
| 2.4 | Bytes-backed records | `model_generator.py` | 2 days | 2.3 |
| **Phase 3: Context & Prompts** | | | **3 days** | |
| 3.1 | Structured context builder | `translate.py` | 2 days | 2.2 |
| 3.2 | Prompt guidance for tables/REDEFINES | `translate.py` | 1 day | None |
| **Phase 4: Validation** | | | **3 days** | |
| 4.1 | Unit tests | `tests/` | 1 day | 2.1-2.4 |
| 4.2 | Monolith corpus validation | corpus files | 1 day | 3.1-3.2 |
| 4.3 | Returns corpus validation | corpus files | 1 day | 3.1-3.2 |

**Total: ~19 working days (~4 weeks)**

---

## File Summary (What to Create/Modify)

### New Files

| File | Purpose |
|------|---------|
| `backend/src/cobol_migrator/copybook_parser.py` | Hierarchy-aware COBOL copybook parser (OCCURS, REDEFINES, 88-levels) |
| `backend/src/cobol_migrator/model_generator.py` | Bytes-backed record models for REDEFINES; nested model generation |
| `backend/tests/test_copybook_parser.py` | Unit tests for the new parser |

### Modified Files

| File | Change |
|------|--------|
| `shared_model_generator.py` | Replace `extract_copybook_fields()` + `generate_pydantic_model()` with hierarchy-aware versions; add 88-level support |
| `batch_manager.py:180-184` | Replace direct CALL resolution with transitive closure |
| `test_environment.py:154` | Derive `local_modules` dynamically from `dependency_code` |
| `translate.py:135-149` | Add structured context + copybook source + table access guidance to LLM prompt |
