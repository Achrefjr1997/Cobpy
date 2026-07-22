from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any

from cobol_migrator.copybook_parser import (
    CopybookField,
    parse_copybook,
    pic_to_length,
    pic_to_python_type,
)

logger = logging.getLogger(__name__)


@dataclass
class FieldSlot:
    """Computed layout slot for a single leaf field in a bytes-backed record."""

    py_name: str
    cobol_name: str
    offset: int
    length: int
    pic: str | None = None
    usage: str | None = None
    redefines_target: str | None = None
    occurs_count: int | None = None
    occurs_group_size: int | None = None
    children: list[FieldSlot] = field(default_factory=list)
    is_group: bool = False


_PIC_DECIMAL_RE = re.compile(r"9\((\d+)\)(?:V(?:9\((\d+)\))?)?")

_COUNT_RE = re.compile(r"(?:9|X|A|Z)\((\d+)\)")


def _parse_v_decimal(pic: str) -> tuple[int, int]:
    """Extract integer and decimal digit counts from a V-style PIC.

    Returns (int_digits, dec_digits).  e.g. 9(5)V99 -> (5, 2).
    Also handles V9(2) and plain V99 forms.
    """
    pic_upper = pic.upper()
    parts = pic_upper.split("V")
    int_part = parts[0]
    dec_part = parts[1] if len(parts) > 1 else ""

    int_m = _COUNT_RE.search(int_part)
    if int_m:
        int_digits = int(int_m.group(1))
    else:
        int_digits = len(re.sub(r"[^0-9]", "", int_part))

    dec_digits = 0
    if dec_part:
        dec_m = _COUNT_RE.search(dec_part)
        if dec_m:
            dec_digits = int(dec_m.group(1))
        else:
            dec_digits = len(re.sub(r"[^0-9]", "", dec_part))
    return int_digits, dec_digits


def _unpack_bcd(data: bytes) -> int:
    """Unpack COMP-3 packed BCD bytes to integer (without sign)."""
    if not data:
        return 0
    last = data[-1]
    nibbles = []
    for byte in data[:-1]:
        nibbles.append((byte >> 4) & 0x0F)
        nibbles.append(byte & 0x0F)
    nibbles.append((last >> 4) & 0x0F)
    sign_nibble = last & 0x0F

    value = 0
    for n in nibbles:
        value = value * 10 + n

    if sign_nibble in (0x0D, 0xB):
        value = -value
    return value


def _pack_bcd(value: int, n_bytes: int) -> bytes:
    """Pack an integer into COMP-3 packed BCD with given byte count.

    Each byte (except the last) holds 2 BCD digits; the last byte holds
    1 BCD digit in the high nibble and the sign (0xC=+, 0xD=-) in the
    low nibble.
    """
    negative = value < 0
    value = abs(value)
    digit_list = [int(c) for c in str(value)]

    total_digit_slots = n_bytes * 2 - 1
    if len(digit_list) < total_digit_slots:
        digit_list = [0] * (total_digit_slots - len(digit_list)) + digit_list

    result = bytearray(n_bytes)
    for i in range(n_bytes - 1):
        result[i] = (digit_list[i * 2] << 4) | digit_list[i * 2 + 1]
    result[-1] = (digit_list[-1] << 4) | (0x0D if negative else 0x0C)
    return bytes(result)


def _compute_layout(field: CopybookField) -> list[FieldSlot]:
    """Compute byte-offset layout for all leaf fields in a copybook hierarchy.

    Returns a flat list of FieldSlot records.  REDEFINES targets share the
    same offset.  OCCURS groups produce per-occurrence slots.
    """
    target_offsets: dict[str, int] = {}
    all_slots: list[FieldSlot] = []

    def _layout_children(
        children: list[CopybookField], base_offset: int,
        name_prefix: str = "",
    ) -> int:
        offset = base_offset
        for child in children:
            if child.is_88 or child.name.startswith("_filler_"):
                continue

            py_name = f"{name_prefix}{child.name.lower().replace('-', '_')}"

            if child.redefines_target:
                fld_offset = target_offsets.get(child.redefines_target)
                if fld_offset is None:
                    raise ValueError(
                        f"REDEFINES target {child.redefines_target!r} not found "
                        f"for field {child.name!r}"
                    )
            else:
                fld_offset = offset

            length = pic_to_length(child.pic or "", child.usage)

            # OCCURS group
            if child.occurs_count and child.children:
                inner = [c for c in child.children if not c.is_88 and not c.name.startswith("_filler_")]
                if inner:
                    sub_slots = _layout_flat(inner, 0)
                    entry_size = max((s.offset + s.length for s in sub_slots), default=0)
                    for occ_idx in range(child.occurs_count):
                        for s in sub_slots:
                            occ_py = f"{py_name}_{occ_idx}_{s.py_name}" if s.py_name else f"{py_name}_{occ_idx}"
                            clone = FieldSlot(
                                py_name=occ_py,
                                cobol_name=s.cobol_name,
                                offset=fld_offset + occ_idx * entry_size + s.offset,
                                length=s.length,
                                pic=s.pic,
                                usage=s.usage,
                                occurs_count=child.occurs_count,
                            )
                            all_slots.append(clone)
                    target_offsets[child.name] = fld_offset
                    if not child.redefines_target:
                        offset += entry_size * child.occurs_count
                    continue

            # OCCURS elementary
            elif child.occurs_count and child.pic:
                for occ_idx in range(child.occurs_count):
                    occ_offset = fld_offset + occ_idx * length
                    slot = FieldSlot(
                        py_name=f"{py_name}_{occ_idx}",
                        cobol_name=child.name,
                        offset=occ_offset,
                        length=length,
                        pic=child.pic,
                        usage=child.usage,
                        occurs_count=child.occurs_count,
                    )
                    all_slots.append(slot)
                target_offsets[child.name] = fld_offset
                if not child.redefines_target:
                    offset += length * child.occurs_count
                continue

            # Group field
            elif child.children:
                _layout_children(child.children, fld_offset, py_name + "_")
                target_offsets[child.name] = fld_offset
                if not child.redefines_target:
                    group_end = fld_offset
                    for s in all_slots:
                        end = s.offset + s.length
                        if end > group_end:
                            group_end = end
                    offset = group_end
                continue

            # Leaf field
            slot = FieldSlot(
                py_name=py_name,
                cobol_name=child.name,
                offset=fld_offset,
                length=length,
                pic=child.pic,
                usage=child.usage,
            )
            all_slots.append(slot)
            target_offsets[child.name] = fld_offset
            if not child.redefines_target:
                offset += length

        return offset

    def _layout_flat(fields: list[CopybookField], base_offset: int) -> list[FieldSlot]:
        """Layout a flat list of children without REDEFINES tracking (for OCCURS expansion)."""
        result: list[FieldSlot] = []
        off = base_offset
        for f in fields:
            if f.is_88 or f.name.startswith("_filler_"):
                continue
            length = pic_to_length(f.pic or "", f.usage)
            slot = FieldSlot(
                py_name=f.name.lower().replace("-", "_"),
                cobol_name=f.name,
                offset=off,
                length=length,
                pic=f.pic,
                usage=f.usage,
            )
            result.append(slot)
            off += length
        return result

    _layout_children(field.children, 0)
    return all_slots


def _record_size(slots: list[FieldSlot]) -> int:
    """Compute total record size (max offset + length, excluding REDEFINES)."""
    max_end = 0
    seen_offsets: set[tuple[int, int]] = set()
    for s in slots:
        key = (s.offset, s.length)
        if key in seen_offsets:
            continue  # skip REDEFINES duplicates
        seen_offsets.add(key)
        end = s.offset + s.length
        if end > max_end:
            max_end = end
    return max_end


def _field_slots_without_redefines_duplicates(slots: list[FieldSlot]) -> list[FieldSlot]:
    """Return unique field slots, filtering duplicates from REDEFINES.

    When two fields share the exact same offset and length, keep only the
    last one so that properties don't collide in the class.
    """
    seen: dict[tuple[int, int], FieldSlot] = {}
    for s in slots:
        key = (s.offset, s.length)
        if key in seen:
            # Same offset+length — keep the later one (likely the one with usage)
            seen[key] = s
        else:
            seen[key] = s
    return list(seen.values())


def _gen_getter_display(slot: FieldSlot) -> str:
    """Generate @property getter for a DISPLAY field."""
    off = slot.offset
    end = off + slot.length
    pic = (slot.pic or "").upper()

    if "9" in pic and "V" in pic:
        int_d, dec_d = _parse_v_decimal(pic)
        total = int_d + dec_d
        return (
            f"        raw = self._data[{off}:{end}].decode('utf-8', errors='replace')\n"
            f"        return Decimal(int(raw)) / Decimal('{10**dec_d}')"
        )
    if "9" in pic:
        return (
            f"        raw = self._data[{off}:{end}].decode('utf-8', errors='replace')\n"
            f"        return int(raw)"
        )
    # X / A / edited → str
    return (
        f"        raw = self._data[{off}:{end}].decode('utf-8', errors='replace')\n"
        f"        return raw.rstrip('\\x00').rstrip()"
    )


def _gen_setter_display(slot: FieldSlot) -> str:
    """Generate @property setter for a DISPLAY field."""
    off = slot.offset
    end = off + slot.length
    pic = (slot.pic or "").upper()

    if "9" in pic and "V" in pic:
        int_d, dec_d = _parse_v_decimal(pic)
        total = int_d + dec_d
        return (
            f"        raw = str(int(value * Decimal('{10**dec_d}'))).zfill({total})\n"
            f"        self._data[{off}:{end}] = raw.encode()"
        )
    if "9" in pic:
        return (
            f"        self._data[{off}:{end}] = str(value).zfill({slot.length}).encode()"
        )
    return (
        f"        encoded = str(value).encode('utf-8', errors='replace')\n"
        f"        self._data[{off}:{end}] = encoded.ljust({slot.length}, b' ')[:{slot.length}]"
    )


def _gen_getter_comp(slot: FieldSlot) -> str:
    """Generate @property getter for COMP / BINARY / COMP-5 field."""
    off = slot.offset
    end = off + slot.length
    fmt_map = {2: ">h", 4: ">i", 8: ">q"}
    fmt = fmt_map.get(slot.length, ">i")
    pic = (slot.pic or "").upper()

    if "9" in pic and "V" in pic:
        int_d, dec_d = _parse_v_decimal(pic)
        return (
            f"        raw = struct.unpack('{fmt}', self._data[{off}:{end}])[0]\n"
            f"        return Decimal(raw) / Decimal('{10**dec_d}')"
        )
    return (
        f"        return struct.unpack('{fmt}', self._data[{off}:{end}])[0]"
    )


def _gen_setter_comp(slot: FieldSlot) -> str:
    """Generate @property setter for COMP / BINARY / COMP-5 field."""
    off = slot.offset
    end = off + slot.length
    fmt_map = {2: ">h", 4: ">i", 8: ">q"}
    fmt = fmt_map.get(slot.length, ">i")
    pic = (slot.pic or "").upper()

    if "9" in pic and "V" in pic:
        _, dec_d = _parse_v_decimal(pic)
        return (
            f"        self._data[{off}:{end}] = struct.pack('{fmt}', int(value * Decimal('{10**dec_d}')))"
        )
    return (
        f"        self._data[{off}:{end}] = struct.pack('{fmt}', value)"
    )


def _gen_getter_comp3(slot: FieldSlot) -> str:
    """Generate @property getter for COMP-3 / PACKED-DECIMAL field."""
    off = slot.offset
    end = off + slot.length
    pic = (slot.pic or "").upper()

    if "9" in pic and "V" in pic:
        _, dec_d = _parse_v_decimal(pic)
        return (
            f"        raw = _unpack_bcd(self._data[{off}:{end}])\n"
            f"        return Decimal(raw) / Decimal('{10**dec_d}')"
        )
    return (
        f"        return _unpack_bcd(self._data[{off}:{end}])"
    )


def _gen_setter_comp3(slot: FieldSlot) -> str:
    """Generate @property setter for COMP-3 / PACKED-DECIMAL field."""
    off = slot.offset
    end = off + slot.length
    pic = (slot.pic or "").upper()

    if "9" in pic and "V" in pic:
        _, dec_d = _parse_v_decimal(pic)
        return (
            f"        raw = _pack_bcd(int(value * Decimal('{10**dec_d}')), {slot.length})\n"
            f"        self._data[{off}:{end}] = raw"
        )
    return (
        f"        self._data[{off}:{end}] = _pack_bcd(value, {slot.length})"
    )


def _gen_getter_comp1(slot: FieldSlot) -> str:
    off = slot.offset
    end = off + 4
    return f"        return struct.unpack('>f', self._data[{off}:{end}])[0]"


def _gen_setter_comp1(slot: FieldSlot) -> str:
    off = slot.offset
    end = off + 4
    return f"        self._data[{off}:{end}] = struct.pack('>f', value)"


def _gen_getter_comp2(slot: FieldSlot) -> str:
    off = slot.offset
    end = off + 8
    return f"        return struct.unpack('>d', self._data[{off}:{end}])[0]"


def _gen_setter_comp2(slot: FieldSlot) -> str:
    off = slot.offset
    end = off + 8
    return f"        self._data[{off}:{end}] = struct.pack('>d', value)"


def _gen_getter_pointer(slot: FieldSlot) -> str:
    off = slot.offset
    end = off + 8
    return f"        return int.from_bytes(self._data[{off}:{end}], 'big')"


def _gen_setter_pointer(slot: FieldSlot) -> str:
    off = slot.offset
    end = off + 8
    return f"        self._data[{off}:{end}] = value.to_bytes(8, 'big')"


def _usage_key(slot: FieldSlot) -> str:
    return (slot.usage or "").upper().strip()


def _needs_decimal(slots: list[FieldSlot]) -> bool:
    for s in slots:
        uk = _usage_key(s)
        pic = (s.pic or "").upper()
        if uk in ("COMP-3", "PACKED-DECIMAL"):
            return True
        if "V" in pic:
            return True
        if uk in ("COMP", "COMP-5", "BINARY") and "V" in pic:
            return True
    return False


def _needs_struct(slots: list[FieldSlot]) -> bool:
    for s in slots:
        uk = _usage_key(s)
        if uk in ("COMP", "COMP-5", "BINARY", "COMP-1", "COMP-2"):
            return True
    return False


def _gen_property(slot: FieldSlot) -> str:
    """Generate @property getter+setter for a single field slot."""
    uk = _usage_key(slot)
    name = slot.py_name
    comment = ""
    if slot.redefines_target:
        comment = f"  # REDEFINES {slot.redefines_target}"
    elif slot.occurs_count:
        comment = f"  # OCCURS {slot.occurs_count}"

    if uk in ("COMP", "COMP-5", "BINARY"):
        getter = _gen_getter_comp(slot)
        setter = _gen_setter_comp(slot)
    elif uk in ("COMP-3", "PACKED-DECIMAL"):
        getter = _gen_getter_comp3(slot)
        setter = _gen_setter_comp3(slot)
    elif uk == "COMP-1":
        getter = _gen_getter_comp1(slot)
        setter = _gen_setter_comp1(slot)
    elif uk == "COMP-2":
        getter = _gen_getter_comp2(slot)
        setter = _gen_setter_comp2(slot)
    elif uk == "POINTER":
        getter = _gen_getter_pointer(slot)
        setter = _gen_setter_pointer(slot)
    else:
        getter = _gen_getter_display(slot)
        setter = _gen_setter_display(slot)

    lines = [
        f"    @property",
        f"    def {name}(self) -> Any:{comment}",
        getter,
        "",
        f"    @{name}.setter",
        f"    def {name}(self, value: Any):{comment}",
        setter,
    ]
    return "\n".join(lines)


def generate_record_class(field: CopybookField) -> str:
    """Generate a bytes-backed record class for the given top-level copybook field.

    The generated class uses an internal ``bytearray`` buffer and exposes
    each leaf field via ``@property`` getters/setters.  REDEFINES fields
    share the same underlying byte slice, preserving COBOL overlap semantics.
    """
    if field.is_88 or field.level < 1:
        return ""

    slots = _compute_layout(field)
    size = _record_size(slots)
    unique_slots = _field_slots_without_redefines_duplicates(slots)

    class_name = field.name.replace("-", "_").replace(".", "_").title()
    if not class_name.endswith("Record"):
        class_name += "Record"

    imports: list[str] = []
    if _needs_decimal(slots):
        imports.append("from decimal import Decimal")
    if _needs_struct(slots):
        imports.append("import struct")
    imports.append("from typing import Any")

    helper_defs: list[str] = []
    if any(_usage_key(s) in ("COMP-3", "PACKED-DECIMAL") for s in slots):
        helper_defs.extend([
            "",
            "",
            "def _unpack_bcd(data: bytes) -> int:",
            '    """Unpack COMP-3 packed BCD bytes to integer."""',
            "    if not data:",
            "        return 0",
            "    last = data[-1]",
            "    nibbles = []",
            "    for byte in data[:-1]:",
            "        nibbles.append((byte >> 4) & 0x0F)",
            "        nibbles.append(byte & 0x0F)",
            "    nibbles.append((last >> 4) & 0x0F)",
            "    sign_nibble = last & 0x0F",
            "    value = 0",
            "    for n in nibbles:",
            "        value = value * 10 + n",
            "    if sign_nibble in (0x0D, 0xB):",
            "        value = -value",
            "    return value",
            "",
            "",
            "def _pack_bcd(value: int, n_bytes: int) -> bytes:",
            '    """Pack an integer into COMP-3 packed BCD with given byte count.',
            "",
            "    Each byte (except the last) holds 2 BCD digits; the last byte holds",
            "    1 BCD digit in the high nibble and the sign (0xC=+, 0xD=-) in the",
            "    low nibble.",
            '    """',
            "    negative = value < 0",
            "    value = abs(value)",
            "    digit_list = [int(c) for c in str(value)]",
            "",
            "    total_digit_slots = n_bytes * 2 - 1",
            "    if len(digit_list) < total_digit_slots:",
            "        digit_list = [0] * (total_digit_slots - len(digit_list)) + digit_list",
            "",
            "    result = bytearray(n_bytes)",
            "    for i in range(n_bytes - 1):",
            "        result[i] = (digit_list[i * 2] << 4) | digit_list[i * 2 + 1]",
            "    result[-1] = (digit_list[-1] << 4) | (0x0D if negative else 0x0C)",
            "    return bytes(result)",
        ])

    class_lines: list[str] = [
        "",
        "",
        f"class {class_name}:",
        f'    """Bytes-backed record for {field.name} (size={size})."""',
        "",
        f"    def __init__(self, data: bytes | None = None):",
        f"        self._data = bytearray(data or b'\\x00' * {size})",
        "",
        f"    @classmethod",
        f"    def size(cls) -> int:",
        f"        return {size}",
        "",
    ]

    for slot in unique_slots:
        class_lines.append(_gen_property(slot))
        class_lines.append("")

    body = "\n".join(class_lines)

    if helper_defs:
        body = "\n".join(helper_defs) + body

    header = "\n".join(imports) if imports else ""
    if header:
        return header + body
    return body.lstrip("\n")
