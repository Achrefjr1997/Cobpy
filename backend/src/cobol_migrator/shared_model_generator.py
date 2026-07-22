from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any

from cobol_migrator.copybook_parser import (
    CopybookField,
    parse_copybook,
    pic_to_python_type,
)

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


def _py_name(cobol_name: str) -> str:
    return cobol_name.lower().replace("-", "_")


def _format_default_value(value: str | None, py_type: str) -> str:
    if value is None:
        return ""
    if value.startswith("'") or value.startswith('"'):
        return f" = {value}"
    if py_type == "Decimal":
        return f" = Decimal('{value}')"
    if py_type == "int":
        try:
            return f" = {int(value)}"
        except ValueError:
            return f" = '{value}'"
    if py_type == "float":
        try:
            return f" = {float(value)}"
        except ValueError:
            return f" = '{value}'"
    return f" = '{value}'"


def _first_88_default(field: CopybookField) -> str | None:
    for child in field.children:
        if child.is_88 and child.condition_values:
            return child.condition_values[0]
    return None


def _has_group_children(field: CopybookField) -> bool:
    return len([c for c in field.children if not c.is_88 and not c.name.startswith("_filler_")]) > 0


def _generate_88_constants(field: CopybookField) -> list[str]:
    """Generate constant definitions from 88-level child fields."""
    constants: list[str] = []
    for child in field.children:
        if child.is_88 and child.condition_values:
            for val in child.condition_values:
                safe_val = val.replace(":", "_TO_")
                const_name = (
                    f"{field.name.upper().replace('-', '_')}_"
                    f"{child.name.upper().replace('-', '_')}_"
                    f"{safe_val}"
                )
                if val.lstrip("-").isdigit():
                    constants.append(f"{const_name}: int = {int(val)}")
                else:
                    constants.append(f"{const_name}: str = '{val}'")
    return constants


def _generate_field_validator(field: CopybookField) -> list[str]:
    """Generate a Pydantic v2 @field_validator for a field with 88-level children."""
    eighty_eights = [c for c in field.children if c.is_88 and c.condition_values]
    if not eighty_eights:
        return []

    py_field = _py_name(field.name)
    valid_values: set[str] = set()
    for child in eighty_eights:
        for val in child.condition_values:
            valid_values.add(val)

    is_numeric = all(v.lstrip("-").isdigit() for v in valid_values)
    if is_numeric:
        valid_repr = ", ".join(str(int(v)) for v in sorted(valid_values, key=lambda x: int(x)))
        valid_set = "{" + valid_repr + "}"
    else:
        valid_values.add("")
        valid_repr = ", ".join(repr(v) for v in sorted(valid_values))
        valid_set = "{" + valid_repr + "}"

    lines: list[str] = []
    lines.append("")
    lines.append(f"    @field_validator('{py_field}')")
    lines.append("    @classmethod")
    lines.append(f"    def validate_{py_field}(cls, v):")
    lines.append(f"        valid = {valid_set}")
    lines.append(f"        if v not in valid:")
    lines.append(f"            raise ValueError(f\"Invalid {py_field}: {{v!r}}. Valid: {{valid}}\")")
    lines.append("        return v")
    return lines


def _generate_set_true_helper(field: CopybookField) -> list[str]:
    """Generate a SET ... TO TRUE helper method for a field with 88-level children."""
    eighty_eights = [c for c in field.children if c.is_88 and c.condition_values]
    if not eighty_eights:
        return []

    py_field = _py_name(field.name)
    method_name = f"set_{py_field}_to_true"
    indent = " " * 4

    lines: list[str] = []
    lines.append("")
    lines.append(f"    def {method_name}(self, condition_name: str) -> None:")
    lines.append(f'        """Implement COBOL SET ... TO TRUE for 88-level conditions."""')
    lines.append(f"        mapping = {{")
    for child in eighty_eights:
        for val in child.condition_values:
            cond_key = child.name.upper().replace("-", "_")
            repr_val = repr(val)
            lines.append(f"            \"{cond_key}\": {repr_val},")
    lines.append(f"        }}")
    lines.append(f"        if condition_name in mapping:")
    lines.append(f"            self.{py_field} = mapping[condition_name]")
    return lines


def _build_model(name: str, fields: list[str], methods: list[str] | None = None) -> str:
    parts = [f"class {name}(BaseModel):", f'    """Generated OCCURS model."""']
    if methods:
        parts.append("")
        parts.append("    model_config = {'validate_assignment': True}")
    if fields:
        parts.append("")
        parts.extend(fields)
    if methods:
        parts.extend(methods)
    return "\n".join(parts)


def _generate_nested_occurs_model(parent: CopybookField) -> str:
    """Generate a nested Pydantic model for an OCCURS group."""
    children = [c for c in parent.children if not c.is_88 and not c.name.startswith("_filler_")]
    if not children:
        return ""

    model_name = parent.name.replace("-", "_").replace(".", "_").title()
    if not model_name.endswith("Model"):
        model_name += "Model"

    field_lines: list[str] = []
    extra_models: list[str] = []
    child_constants: list[str] = []
    method_lines: list[str] = []

    for child in children:
        if child.occurs_count:
            sub_model = _generate_nested_occurs_model(child)
            if sub_model:
                extra_models.append(sub_model)
                sub_model_name = child.name.replace("-", "_").title()
                if not sub_model_name.endswith("Model"):
                    sub_model_name += "Model"
                field_lines.append(f"    {_py_name(child.name)}: list[{sub_model_name}]")
            continue

        cc = _generate_88_constants(child)
        if cc:
            child_constants.extend(cc)
        cv = _generate_field_validator(child)
        if cv:
            method_lines.extend(cv)
        ch = _generate_set_true_helper(child)
        if ch:
            method_lines.extend(ch)

        py_type = pic_to_python_type(child.pic or "", child.usage)
        if child.value is None:
            fb = _first_88_default(child)
            default = _format_default_value(fb, py_type) if fb is not None else ""
        else:
            default = _format_default_value(child.value, py_type)
        field_lines.append(f"    {_py_name(child.name)}: {py_type}{default}  # {child.pic or ''}")

    result_parts: list[str] = []
    if extra_models:
        result_parts.extend(extra_models)
        result_parts.append("")
    if child_constants:
        result_parts.extend(child_constants)
        result_parts.append("")

    result_parts.append(_build_model(model_name, field_lines, method_lines))
    return "\n\n".join(result_parts)


def generate_pydantic_model(field: CopybookField) -> str:
    """Generate a Pydantic model from a top-level copybook field.

    Recursively handles:
    - Group items -> nested Pydantic models (only if has OCCURS or multiple children)
    - OCCURS (group) -> list[ChildModel]
    - OCCURS (elementary) -> list[scalar_type]
    - Elementary fields -> typed fields
    - 88-level -> constants
    - FILLER -> skipped
    - VALUE -> field defaults (for constants only, not model fields)
    """
    if field.is_88:
        return ""

    if field.level < 1:
        return ""

    children = [c for c in field.children if not c.is_88 and not c.name.startswith("_filler_")]
    has_occurs_children = any(c.occurs_count for c in children)
    has_group_children = len(children) > 0

    is_single_elementary = not has_occurs_children and not has_group_children
    needs_class = has_occurs_children or has_group_children or is_single_elementary

    constants = _generate_88_constants(field)

    if needs_class:
        model_name = field.name.replace("-", "_").replace(".", "_").title()
        if not model_name.endswith("Model"):
            model_name += "Model"

        field_lines: list[str] = []
        child_models: list[str] = []

        for child in children:
            if child.occurs_count and child.pic:
                field_lines.append(
                    f"    {_py_name(child.name)}: list[{pic_to_python_type(child.pic, child.usage)}]"
                    f"  # OCCURS {child.occurs_count} {child.pic}"
                )
            elif child.occurs_count:
                child_model = _generate_nested_occurs_model(child)
                if child_model:
                    child_models.append(child_model)
                    child_model_name = child.name.replace("-", "_").title()
                    if not child_model_name.endswith("Model"):
                        child_model_name += "Model"
                    field_lines.append(
                        f"    {_py_name(child.name)}: list[{child_model_name}]"
                        f"  # OCCURS {child.occurs_count}"
                    )
            elif _has_group_children(child):
                child_result = generate_pydantic_model(child)
                if child_result:
                    child_models.append(child_result)
                    child_type = child.name.replace("-", "_").title() + "Model"
                    field_lines.append(f"    {_py_name(child.name)}: {child_type}")
            else:
                py_type = pic_to_python_type(child.pic or "", child.usage)
                child_constants = _generate_88_constants(child)
                if child_constants:
                    constants.extend(child_constants)
                if child.value is None:
                    fb = _first_88_default(child)
                    default = _format_default_value(fb, py_type) if fb is not None else ""
                else:
                    default = _format_default_value(child.value, py_type)
                field_lines.append(
                    f"    {_py_name(child.name)}: {py_type}{default}  # {child.pic or ''}"
                )

        # If no children, use the field itself as the only field
        if not field_lines:
            py_type = pic_to_python_type(field.pic or "", field.usage)
            if field.value is None:
                fb = _first_88_default(field)
                default = _format_default_value(fb, py_type) if fb is not None else ""
            else:
                default = _format_default_value(field.value, py_type)
            field_lines.append(
                f"    {_py_name(field.name)}: {py_type}{default}  # {field.pic or ''}"
            )

        result_parts: list[str] = []

        # Constants go first (module-level)
        if constants:
            result_parts.extend(constants)
            result_parts.append("")

        # Child models go before parent (Pydantic requires referenced models defined first)
        if child_models:
            result_parts.extend(child_models)
            result_parts.append("")

        # Collect validators and SET TRUE helpers for the parent field itself
        method_lines: list[str] = []
        fv = _generate_field_validator(field)
        if fv:
            method_lines.extend(fv)
        fh = _generate_set_true_helper(field)
        if fh:
            method_lines.extend(fh)

        # Collect validators and helpers for simple children with 88-levels
        for child in children:
            if child.occurs_count or _has_group_children(child):
                continue
            if any(c.is_88 for c in child.children):
                cv = _generate_field_validator(child)
                if cv:
                    method_lines.extend(cv)
                ch = _generate_set_true_helper(child)
                if ch:
                    method_lines.extend(ch)

        result_parts.append(f"class {model_name}(BaseModel):")
        result_parts.append(f'    """Generated from {field.name}."""')
        if method_lines:
            result_parts.append("")
            result_parts.append(f"    model_config = {{'validate_assignment': True}}")
        if field_lines:
            result_parts.append("")
            result_parts.extend(field_lines)
        if method_lines:
            result_parts.extend(method_lines)

        return "\n\n".join(result_parts)

    else:
        py_type = pic_to_python_type(field.pic or "", field.usage)
        if constants:
            constants.append("")
        return "\n".join(constants) + (f"\n{_py_name(field.name)}: {py_type}  # {field.pic or ''}" if field.pic else "")


def _check_field_uses_decimal(field: CopybookField) -> bool:
    """Recursively check if a field or any child uses Decimal type."""
    usage_key = field.usage.upper().strip() if field.usage else ""
    if field.pic and ("V" in field.pic.upper()):
        return True
    if usage_key in ("COMP-3", "PACKED-DECIMAL"):
        return True
    for child in field.children:
        if _check_field_uses_decimal(child):
            return True
    return False


def _needs_field_validator(text: str) -> bool:
    """Check if generated text contains @field_validator usage."""
    return "@field_validator" in text


def generate_shared_models_text(copybooks: dict[str, dict[str, Any]], extract_path: Path) -> str:
    parts: list[str] = []
    has_model = False
    has_decimal = False
    has_validator = False

    for prog_id, info in copybooks.items():
        file_path = info.get("file_path", "")
        if not file_path.lower().endswith(".cpy"):
            continue
        source_path = extract_path / file_path
        if not source_path.exists():
            logger.warning(f"Copybook file not found: {source_path}")
            continue
        source = source_path.read_text(encoding="utf-8", errors="ignore")

        top_fields = parse_copybook(source)
        for field in top_fields:
            field_name_upper = field.name.upper()
            if field_name_upper.startswith("FILLER") or field_name_upper.startswith("_FILLER"):
                continue
            model_code = generate_pydantic_model(field)
            if not model_code:
                continue
            parts.append(model_code)
            if "class " in model_code:
                has_model = True
            if _check_field_uses_decimal(field):
                has_decimal = True
            if _needs_field_validator(model_code):
                has_validator = True

    if not parts:
        return ""

    header_lines: list[str] = []
    if has_model:
        header_lines.append("from pydantic import BaseModel")
    if has_validator:
        header_lines.append("from pydantic import field_validator")
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
