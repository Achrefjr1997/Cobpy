"""
COBOL Record Layout Parser

Parses COBOL FD (File Description) and record definitions to extract
the exact field positions and lengths. This is critical for generating
correctly formatted dummy data files.

COBOL records are FIXED-WIDTH with NO separators between fields.
"""
from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass
class COBOLField:
    """Represents a single COBOL field definition."""
    
    name: str
    pic: str
    length: int
    offset: int  # Starting position in record (0-based)
    is_numeric: bool
    decimal_places: int  # For implied decimals (V)
    
    def generate_sample_value(self, index: int = 1) -> str:
        """Generate a sample value for this field."""
        if self.is_numeric:
            if self.decimal_places > 0:
                # Numeric with implied decimal: 9(3)V99 = 04000 represents 040.00
                # Generate realistic values (e.g., 40.00, 45.00, 50.00 for hours)
                # or (15.00, 17.50, 20.00 for rates)
                
                # Check if this might be an hourly rate or hours worked
                name_upper = self.name.upper()
                if "RATE" in name_upper or "PRICE" in name_upper or "COST" in name_upper:
                    base_value = 15 + (index * 2.5)  # 15.00, 17.50, 20.00
                elif "HOUR" in name_upper or "QTY" in name_upper or "QUANTITY" in name_upper:
                    base_value = 38 + (index * 2)  # 40, 42, 44
                else:
                    base_value = 100 + (index * 50)  # Generic: 150, 200, 250
                
                # Convert to integer representation (multiply by 10^decimals)
                int_value = int(base_value * (10 ** self.decimal_places))
                return str(int_value).zfill(self.length)[:self.length]
            else:
                # Pure integer: generate contextually appropriate values
                name_upper = self.name.upper()
                if any(x in name_upper for x in ["SALARY", "PAY", "WAGE", "AMOUNT", "TOTAL", "BONUS"]):
                    value = 30000 + (index * 5000)
                elif any(x in name_upper for x in ["ID", "NUM", "NO", "NBR", "CODE"]):
                    value = 1000 + index
                else:
                    value = index * 1000 + index
                return str(value).zfill(self.length)[:self.length]
        else:
            # Alphanumeric: right-pad with spaces
            # Check if this looks like an ID field
            name_upper = self.name.upper()
            if any(x in name_upper for x in ["ID", "CODE", "NUM", "NO", "NBR"]):
                # ID-like field: generate a numeric-looking ID
                value = str(index * 1000 + 234).zfill(self.length)
                return value[:self.length]
            else:
                # Name/description field: use sample names
                sample_names = [
                    "John Smith", "Jane Doe", "Bob Johnson",
                    "Alice Brown", "Charlie Wilson", "Diana Miller"
                ]
                value = sample_names[(index - 1) % len(sample_names)]
                return value.ljust(self.length)[:self.length]


@dataclass
class COBOLRecordLayout:
    """Complete layout of a COBOL record."""
    
    record_name: str
    fields: list[COBOLField]
    total_length: int
    
    def generate_sample_record(self, index: int = 1) -> str:
        """Generate a sample record with all fields concatenated."""
        parts = []
        for field in self.fields:
            parts.append(field.generate_sample_value(index))
        return "".join(parts)
    
    def generate_sample_records(self, count: int = 3) -> list[str]:
        """Generate multiple sample records."""
        return [self.generate_sample_record(i + 1) for i in range(count)]
    
    def get_field_documentation(self) -> str:
        """Generate documentation of field positions for tests."""
        lines = [f"# Record Layout ({self.total_length} chars total):"]
        for field in self.fields:
            end_pos = field.offset + field.length
            field_type = "numeric" if field.is_numeric else "alpha"
            decimal_info = f", {field.decimal_places} decimals" if field.decimal_places else ""
            lines.append(
                f"#   {field.name}: positions {field.offset}-{end_pos-1} "
                f"({field.length} chars, {field_type}{decimal_info})"
            )
        return "\n".join(lines)


def parse_pic_clause(pic: str) -> tuple[int, bool, int]:
    """
    Parse a COBOL PIC clause to extract length, type, and decimal places.
    
    Examples:
        X(06)     -> (6, False, 0)   - 6 alphanumeric chars
        9(03)V99  -> (5, True, 2)    - 5 numeric chars with 2 implied decimals
        9(05)     -> (5, True, 0)    - 5 numeric chars
        XXX       -> (3, False, 0)   - 3 alphanumeric chars
        9999V99   -> (6, True, 2)    - 6 numeric chars with 2 implied decimals
        Z(07)V99  -> (9, True, 2)    - 9 chars (edited numeric, treated as numeric)
        
    Returns:
        (total_length, is_numeric, decimal_places)
    """
    pic = pic.upper().strip()
    
    total_length = 0
    is_numeric = False
    decimal_places = 0
    
    # Numeric if it contains 9 or Z but no X or A (alphabetic/alphanumeric)
    is_numeric = bool(re.search(r'[9Z]', pic)) and not re.search(r'[XA]', pic)
    
    # Handle V (implied decimal point)
    v_match = re.search(r'V(\d+|9+)', pic)
    if v_match:
        # V followed by digits like V99 or V9(2)
        after_v = v_match.group(1)
        if after_v.isdigit() and len(after_v) == 1:
            # V9(n) pattern - need to look at full pattern
            v9_match = re.search(r'V9\((\d+)\)', pic)
            if v9_match:
                decimal_places = int(v9_match.group(1))
            else:
                decimal_places = len(after_v)
        else:
            # V99, V999, etc. - count the 9s
            decimal_places = len(after_v)
    
    # Split by V if present, count each part
    if 'V' in pic:
        parts = pic.split('V')
        before_v = parts[0]
        after_v = parts[1] if len(parts) > 1 else ""
        
        # Count before V
        total_length += _count_pic_chars(before_v)
        # Count after V (decimal places already counted)
        total_length += _count_pic_chars(after_v)
    else:
        total_length = _count_pic_chars(pic)
    
    return total_length, is_numeric, decimal_places


def _count_pic_chars(pic_part: str) -> int:
    """Count the number of character positions in a PIC clause part."""
    count = 0

    # Handle (n) repetition notation: X(06), 9(3), A(10), Z(7)
    # S is a sign indicator and does NOT occupy a storage position
    repeat_pattern = r'([X9AZ])\((\d+)\)'
    for match in re.finditer(repeat_pattern, pic_part, re.IGNORECASE):
        count += int(match.group(2))

    # Remove matched patterns and count remaining literal chars
    remaining = re.sub(repeat_pattern, '', pic_part, flags=re.IGNORECASE)

    # Count individual X, 9, A, Z characters (S does not occupy a position)
    for char in remaining:
        if char.upper() in 'X9AZ':
            count += 1

    return count


def extract_fd_records(cobol_source: str) -> dict[str, COBOLRecordLayout]:
    """
    Extract all FD record layouts from COBOL source.
    
    Returns a dict mapping filename patterns to their record layouts.
    """
    layouts = {}
    
    # Find all FD sections
    # Pattern matches from FD to the next FD or WORKING-STORAGE or PROCEDURE
    fd_pattern = r'FD\s+(\w[\w-]*)\s*\.(.*?)(?=(?:FD\s|\s*WORKING-STORAGE|\s*PROCEDURE|$))'
    fd_matches = re.findall(fd_pattern, cobol_source, re.IGNORECASE | re.DOTALL)
    
    for fd_name, fd_content in fd_matches:
        fields = []
        current_offset = 0
        
        # Find the 01 level record definition
        record_pattern = r'01\s+(\w[\w-]*)\s*\.'
        record_match = re.search(record_pattern, fd_content, re.IGNORECASE)
        record_name = record_match.group(1) if record_match else fd_name
        
        # Find all field definitions (levels 02-49 or 05, etc.)
        # Pattern: level name PIC clause
        field_pattern = r'(?:0[2-9]|[1-4]\d)\s+(\w[\w-]*)\s+PIC\s+([^\s.]+)'
        field_matches = re.findall(field_pattern, fd_content, re.IGNORECASE)
        
        for field_name, pic in field_matches:
            # Skip FILLER fields in some contexts, but include them for offset calculation
            length, is_numeric, decimals = parse_pic_clause(pic)
            
            if "FILLER" not in field_name.upper():
                fields.append(COBOLField(
                    name=field_name,
                    pic=pic,
                    length=length,
                    offset=current_offset,
                    is_numeric=is_numeric,
                    decimal_places=decimals,
                ))
            
            current_offset += length
        
        if fields:
            layouts[fd_name] = COBOLRecordLayout(
                record_name=record_name,
                fields=fields,
                total_length=current_offset,
            )
    
    return layouts


def extract_file_assignments(cobol_source: str) -> dict[str, str]:
    """
    Extract file assignments from COBOL FILE-CONTROL.
    
    Returns dict mapping logical name to physical filename.
    """
    assignments = {}
    
    # Pattern 1: SELECT logical-name ASSIGN TO 'physical-file' (quoted)
    quoted_pattern = r"SELECT\s+(\w[\w-]*)\s+ASSIGN\s+TO\s+['\"]([^'\"]+)['\"]"
    matches = re.findall(quoted_pattern, cobol_source, re.IGNORECASE)
    for logical, physical in matches:
        assignments[logical.upper()] = physical
    
    # Pattern 2: SELECT logical-name ASSIGN TO filename (unquoted) - fallback
    # Only match if not already found via quoted pattern
    unquoted_pattern = r"SELECT\s+(\w[\w-]*)\s+ASSIGN\s+TO\s+([\w.-]+)"
    matches = re.findall(unquoted_pattern, cobol_source, re.IGNORECASE)
    for logical, physical in matches:
        if logical.upper() not in assignments:
            assignments[logical.upper()] = physical
    
    return assignments


def get_input_file_layout(cobol_source: str) -> tuple[str | None, COBOLRecordLayout | None]:
    """
    Get the layout of the primary input file.
    
    Returns (filename, layout) or (None, None) if not found.
    """
    assignments = extract_file_assignments(cobol_source)
    layouts = extract_fd_records(cobol_source)
    
    # Try to find input files (not reports/outputs)
    for logical_name, physical_name in assignments.items():
        # Skip output files
        if any(x in physical_name.lower() for x in ['.rpt', '.out', 'report', 'output']):
            continue
        
        # Find matching layout
        for fd_name, layout in layouts.items():
            if fd_name.upper() == logical_name or fd_name.upper() in logical_name:
                return physical_name, layout
    
    # Return first non-output layout found
    for fd_name, layout in layouts.items():
        for logical, physical in assignments.items():
            if fd_name.upper() in logical:
                if not any(x in physical.lower() for x in ['.rpt', '.out', 'report', 'output']):
                    return physical, layout
    
    return None, None


def _detect_output_files(cobol_source: str) -> set[str]:
    """Detect which files are opened for OUTPUT or EXTEND in the PROCEDURE DIVISION."""
    output_files: set[str] = set()
    upper = cobol_source.upper()

    # Match OUTPUT/EXTEND followed by one or more file names
    # Handles: OPEN INPUT F1 OUTPUT F2 F3 EXTEND F4
    for match in re.finditer(r'(?:OUTPUT|EXTEND)\s+([\w-]+(?:\s+[\w-]+)*?)(?=\s+(?:INPUT|OUTPUT|EXTEND|I-O)\b|\.|\n)', upper):
        names = match.group(1).split()
        for name in names:
            name = name.strip()
            if name and name not in ("INPUT", "OUTPUT", "EXTEND", "I-O"):
                output_files.add(name)

    # Simpler fallback: just find OUTPUT followed by a single name
    for match in re.finditer(r'OUTPUT\s+([\w-]+)', upper):
        output_files.add(match.group(1))

    return output_files


def generate_cobol_sample_data(cobol_source: str, count: int = 3) -> dict[str, str]:
    """
    Generate sample data files based on COBOL source analysis.

    Input files get synthetic data records. Output files are created empty
    since the program writes to them.

    Returns dict mapping filename to file content.
    """
    result = {}

    assignments = extract_file_assignments(cobol_source)
    layouts = extract_fd_records(cobol_source)
    output_logical_names = _detect_output_files(cobol_source)

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
            result[physical_name] = ""
        else:
            records = layout.generate_sample_records(count)
            result[physical_name] = "\n".join(records) + "\n"

    return result
