# Plan: Wire VALUE Clauses as Pydantic Field Defaults

## Root Cause
`parse_copybook()` captures `VALUE` into `CopybookField.value` (line 152-160), but `generate_pydantic_model()` never reads it — field lines are generated as `name: type  # PIC` with no default. The LLM then tries `Ws_Msg4_ConstantsModel()` and gets 9 validation errors.

## Changes

### File: `backend/src/cobol_migrator/shared_model_generator.py`

**1. Add helper** after line 88 (before `_has_group_children`):

```python
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
```

**2. Wire into field lines** (~lines 296-298):

Before:
```python
field_lines.append(
    f"    {_py_name(child.name)}: {py_type}  # {child.pic or ''}"
)
```

After:
```python
default = _format_default_value(child.value, py_type)
field_lines.append(
    f"    {_py_name(child.name)}: {py_type}{default}  # {child.pic or ''}"
)
```

**3. Same for the "no children" fallback** (~lines 302-305):

Before:
```python
field_lines.append(
    f"    {_py_name(field.name)}: {py_type}  # {field.pic or ''}"
)
```

After:
```python
default = _format_default_value(field.value, py_type)
field_lines.append(
    f"    {_py_name(field.name)}: {py_type}{default}  # {field.pic or ''}"
)
```

### File: `backend/tests/test_copybook_parser.py`

Add test to `TestGenerateFlatModel`:

```python
def test_value_defaults_in_model(self):
    source = """01 WS-MSG4-CONSTANTS.
    05 MSG4-FRAUD-SUSPECTED PIC X(40)
           VALUE 'FRAUD SUSPECTED - HOLD ORDER.'.
    05 MSG4-BATCH-COMPLETE PIC X(40)
           VALUE 'BATCH PROCESSING COMPLETE'."""
    fields = parse_copybook(source)
    code = generate_pydantic_model(fields[0])
    assert "= 'FRAUD SUSPECTED - HOLD ORDER.'" in code
    assert "= 'BATCH PROCESSING COMPLETE'" in code
    ns = {}
    exec("from pydantic import BaseModel\n" + code, ns)
    m = ns["Ws_Msg4_ConstantsModel"]()
    assert m.msg4_fraud_suspected == 'FRAUD SUSPECTED - HOLD ORDER.'
```

## Verification
```bash
pytest backend/tests/test_copybook_parser.py -x -v -k "value_default"
```
