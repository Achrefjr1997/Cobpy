from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class ParamDef:
    name: str
    pic_clause: str
    level: int
    is_input: bool = True


@dataclass
class PythonParamDef:
    name: str
    type_hint: str | None = None


@dataclass
class InterfaceDef:
    program_id: str
    parameters: list[ParamDef] = field(default_factory=list)
    copybooks_used: list[str] = field(default_factory=list)
    calls_made: list[str] = field(default_factory=list)
    raw_linkage: str | None = None
    python_function_name: str | None = None
    python_parameters: list[PythonParamDef] = field(default_factory=list)
    python_return_type: str | None = None


LINKAGE_SECTION_RE = re.compile(
    r"LINKAGE\s+SECTION\.?\s*(.*?)(?=PROCEDURE\s+DIVISION)",
    re.DOTALL | re.IGNORECASE,
)

USING_RE = re.compile(
    r"PROCEDURE\s+DIVISION\s+USING\s+(.*?)\.(?=\s|\.)",
    re.DOTALL | re.IGNORECASE,
)

FIELD_RE = re.compile(
    r"^\s*(?P<level>\d{2})\s+(?P<name>\w+(?:-\w+)*)\s*"
    r"(?P<pic>PIC\s+(?:[\w().]+(?:\s+OCCURS\s+\d+)?(?:\s+TIMES)?(?:\s+DEPENDING\s+ON\s+\w+)?"
    r"(?:\s+REDEFINES\s+\w+(?:-\w+)*)?)+)?",
    re.IGNORECASE,
)

PROGRAM_ID_RE = re.compile(
    r"PROGRAM-ID\.\s*(\w+(?:-\w+)*)\s*",
    re.IGNORECASE,
)

COPY_RE = re.compile(
    r"COPY\s+(\w+(?:-\w+)*)",
    re.IGNORECASE,
)

CALL_RE = re.compile(
    r"CALL\s+['\"](\w+(?:-\w+)*)['\"]",
    re.IGNORECASE,
)


def extract_interface(program_id: str, cobol_source: str) -> InterfaceDef:
    linkage_match = LINKAGE_SECTION_RE.search(cobol_source)
    if not linkage_match:
        return InterfaceDef(program_id=program_id)

    linkage_block = linkage_match.group(1)
    raw_linkage = linkage_block.strip()

    params: list[ParamDef] = []
    for line in linkage_block.splitlines():
        m = FIELD_RE.match(line)
        if m:
            level = int(m.group("level"))
            name = m.group("name")
            pic = (m.group("pic") or "").strip()
            params.append(
                ParamDef(
                    name=name,
                    pic_clause=pic,
                    level=level,
                    is_input=True,
                )
            )

    copies = [m.group(1) for m in COPY_RE.finditer(cobol_source)]
    calls = [m.group(1) for m in CALL_RE.finditer(cobol_source)]

    return InterfaceDef(
        program_id=program_id,
        parameters=params,
        copybooks_used=copies,
        calls_made=calls,
        raw_linkage=raw_linkage,
    )


_PYTHON_FUNC_RE = re.compile(
    r"^def\s+(?P<name>\w+)\s*\((?P<params>[^)]*)\)\s*(->\s*(?P<return_type>[^:]+))?\s*:",
    re.MULTILINE,
)

_PARAM_SPLIT_RE = re.compile(r"[,\n]+")


def extract_python_interface(python_code: str, program_id: str | None = None) -> tuple[str | None, list[PythonParamDef], str | None]:
    """Extract Python function name, parameters, and return type from generated code.

    Picks the best function to expose:
    1. If only one def exists, use it.
    2. If `main()` exists alongside named functions, prefer the named function
       whose name best matches the module (program_id).
    3. Fall back to `main()` if nothing else matches.
    """
    if not python_code:
        return None, [], None

    matches = list(_PYTHON_FUNC_RE.finditer(python_code))
    if not matches:
        return None, [], None

    def parse_func(m):
        name = m.group("name")
        raw_params = m.group("params") or ""
        return_type_raw = m.group("return_type")
        ret = return_type_raw.strip() if return_type_raw else None
        params = []
        for segment in _PARAM_SPLIT_RE.split(raw_params):
            segment = segment.strip()
            if not segment:
                continue
            if ":" in segment:
                pname, _, ptype = segment.partition(":")
                params.append(PythonParamDef(name=pname.strip(), type_hint=ptype.strip()))
            else:
                params.append(PythonParamDef(name=segment))
        return name, params, ret

    if len(matches) == 1:
        return parse_func(matches[0])

    non_main = [m for m in matches if m.group("name") != "main"]
    if len(non_main) == 1:
        return parse_func(non_main[0])

    if program_id:
        expected = program_id.lower().replace("-", "_")
        for m in non_main:
            if m.group("name") == expected:
                return parse_func(m)

    main_matches = [m for m in matches if m.group("name") == "main"]
    if main_matches:
        return parse_func(main_matches[0])

    return parse_func(matches[0])


def interface_to_prompt_block(interface: InterfaceDef) -> str:
    if not interface.parameters and not interface.raw_linkage and not interface.python_function_name:
        return ""

    mod_name = interface.program_id.lower().replace("-", "_")
    lines = [f"**{interface.program_id}** — already migrated"]
    if interface.python_function_name:
        py_params = ", ".join(
            f"{p.name}: {p.type_hint}" if p.type_hint else p.name
            for p in interface.python_parameters
        )
        ret = f" -> {interface.python_return_type}" if interface.python_return_type else ""
        lines.append(f"Module: {mod_name}  (import with: from {mod_name} import {interface.python_function_name})")
        lines.append(f"Python signature: {interface.python_function_name}({py_params}){ret}")
    if interface.parameters:
        lines.append("LINKAGE parameters:")
        for p in interface.parameters:
            marker = "→" if p.is_input else "←"
            if p.pic_clause:
                lines.append(f"  {marker} {p.name} ({p.pic_clause})")
            else:
                lines.append(f"  {marker} {p.name}")
    if interface.calls_made:
        lines.append(f"Calls: {', '.join(interface.calls_made)}")
    if interface.copybooks_used:
        lines.append(f"Copybooks: {', '.join(interface.copybooks_used)}")
    return "\n".join(lines)
