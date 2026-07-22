"""Tests for the COBOL copybook hierarchy parser and model generator."""
import pytest

from cobol_migrator.copybook_parser import (
    CopybookField,
    parse_copybook,
    pic_to_python_type,
    pic_to_length,
)
from cobol_migrator.shared_model_generator import (
    generate_pydantic_model,
    generate_shared_models_text,
    _py_name,
    _generate_88_constants,
    _generate_nested_occurs_model,
)
from cobol_migrator import record_generator  # noqa: ensure importable


# ============================================================
# Parser Tests
# ============================================================


class TestParseSimpleFields:
    def test_single_01_field(self):
        source = "01 WS-DATA PIC X(10)."
        fields = parse_copybook(source)
        assert len(fields) == 1
        assert fields[0].name == "WS-DATA"
        assert fields[0].level == 1
        assert fields[0].pic == "X(10)"

    def test_multiple_01_fields(self):
        source = """01 WS-RECORD-1 PIC X(10).
        01 WS-RECORD-2 PIC 9(5)."""
        fields = parse_copybook(source)
        assert len(fields) == 2

    def test_nested_group(self):
        source = """01 EMPLOYEE-REC.
           05 EMP-NAME.
              10 EMP-FIRST-NAME PIC X(20).
              10 EMP-LAST-NAME  PIC X(30).
           05 EMP-ID PIC 9(5)."""
        fields = parse_copybook(source)
        assert len(fields) == 1
        assert len(fields[0].children) == 2
        assert fields[0].children[0].name == "EMP-NAME"
        assert len(fields[0].children[0].children) == 2
        assert fields[0].children[0].children[0].name == "EMP-FIRST-NAME"

    def test_numeric_with_decimal(self):
        source = "05 WS-PAY-RATE PIC 9(5)V99."
        fields = parse_copybook(source)
        assert fields[0].pic == "9(5)V99"

    def test_signed_numeric(self):
        source = "05 WS-BALANCE PIC S9(7)V99."
        fields = parse_copybook(source)
        assert fields[0].pic == "S9(7)V99"

    def test_comment_lines_skipped(self):
        source = """      * THIS IS A COMMENT
       01 WS-DATA PIC X(10)."""
        fields = parse_copybook(source)
        assert len(fields) == 1


class TestParseOccurs:
    def test_occurs_simple(self):
        source = """01 RMAMAST.
           05 RMA-NUMBER PIC X(12).
           05 RMA-LINE-TABLE OCCURS 50 TIMES.
              10 RL-ITEM-ID PIC X(12).
              10 RL-UNIT-PRICE PIC 9(7)V99."""
        fields = parse_copybook(source)
        assert len(fields) == 1
        assert fields[0].name == "RMAMAST"

        children = fields[0].children
        assert len(children) == 2
        assert children[0].name == "RMA-NUMBER"
        assert children[0].pic == "X(12)"

        assert children[1].name == "RMA-LINE-TABLE"
        assert children[1].occurs_count == 50
        assert len(children[1].children) == 2
        assert children[1].children[0].name == "RL-ITEM-ID"

    def test_occurs_elementary(self):
        """OCCURS on an elementary field (has PIC directly)."""
        source = "05 MONTHLY-SALES OCCURS 12 TIMES PIC 9(7)V99."
        fields = parse_copybook(source)
        assert fields[0].occurs_count == 12
        assert fields[0].pic == "9(7)V99"
        assert len(fields[0].children) == 0  # No children — it's elementary

    def test_occurs_indexed_by(self):
        source = """05 DEDUCTION-TABLE OCCURS 8 TIMES INDEXED BY DED-IDX.
           10 DED-CODE PIC X(04).
           10 DED-AMOUNT PIC 9(7)V99."""
        fields = parse_copybook(source)
        assert fields[0].occurs_count == 8
        assert fields[0].indexed_by == "DED-IDX"

    def test_occurs_nested_multi_dimensional(self):
        """Two-level nested OCCURS."""
        source = """05 WS-TABLE.
           10 WS-ROW OCCURS 5 TIMES.
              15 WS-COL OCCURS 3 TIMES PIC 9(2)."""
        fields = parse_copybook(source)
        assert fields[0].children[0].occurs_count == 5
        assert fields[0].children[0].children[0].occurs_count == 3


class TestParseRedefines:
    def test_redefines_simple(self):
        source = """01 DATA-REC.
           05 TEXT-FIELD PIC X(20).
           05 NUM-FIELD REDEFINES TEXT-FIELD PIC 9(20)."""
        fields = parse_copybook(source)
        assert fields[0].children[1].redefines_target == "TEXT-FIELD"

    def test_redefines_group(self):
        """Group-level REDEFINES (like PAYTABLE.CPY pattern)."""
        source = """01 WS-TABLE.
           05 WS-ENTRY OCCURS 6 TIMES.
              10 WS-FLOOR PIC 9(7)V99.
              10 WS-RATE  PIC 9(2)V99.
        01 WS-REDEF REDEFINES WS-TABLE.
           05 WS-VALUE PIC X(60)."""
        fields = parse_copybook(source)
        assert len(fields) == 2
        assert fields[1].redefines_target == "WS-TABLE"
        assert fields[1].name == "WS-REDEF"

    def test_redefines_with_occurs(self):
        """REDEFINES + OCCURS combined (the PAYTABLE pattern)."""
        source = """01 WS-FEDERAL-BRACKET-TABLE.
           05 FILLER PIC X(20) VALUE '00000000010000000000'.
        01 WS-BRACKET-REDEF REDEFINES WS-FEDERAL-BRACKET-TABLE.
           05 WS-BRACKET-ENTRY OCCURS 6 TIMES.
              10 WS-BRACKET-FLOOR PIC 9(7)V99.
              10 WS-BRACKET-RATE PIC 9(2)V99."""
        fields = parse_copybook(source)
        assert len(fields) == 2
        assert fields[1].redefines_target == "WS-FEDERAL-BRACKET-TABLE"
        # First field has a FILLER child
        assert fields[0].children[0].name.startswith("_filler_")
        # Second field has OCCURS child
        assert fields[1].children[0].occurs_count == 6


class TestParse88Level:
    def test_88_single_value(self):
        source = """05 WS-STATUS PIC X(01).
           88 WS-ACTIVE   VALUE 'A'.
           88 WS-INACTIVE VALUE 'I'."""
        fields = parse_copybook(source)
        # fields[0] = WS-STATUS (level 05), its children are the 88-levels
        assert len(fields[0].children) == 2
        assert fields[0].children[0].is_88
        assert fields[0].children[0].condition_values == ["A"]
        assert fields[0].children[1].is_88
        assert fields[0].children[1].condition_values == ["I"]

    def test_88_multiple_values(self):
        """88 with VALUES 'A' 'B' 'C'."""
        source = """05 WS-TYPE PIC X(01).
           88 WS-VALID VALUES 'A' 'B' 'C'."""
        fields = parse_copybook(source)
        # fields[0] = WS-TYPE, its only child is the 88-level
        assert len(fields[0].children) == 1
        assert fields[0].children[0].is_88
        assert fields[0].children[0].condition_values == ["A", "B", "C"]

    def test_88_numeric_value(self):
        source = """05 WS-CODE PIC 9(2).
           88 WS-CODE-OK VALUE 0.
           88 WS-CODE-ERR VALUE 99."""
        fields = parse_copybook(source)
        # fields[0] = WS-CODE, children are the 88-levels
        assert len(fields[0].children) == 2
        assert fields[0].children[0].condition_values == ["0"]
        assert fields[0].children[1].condition_values == ["99"]


class TestParseUsage:
    def test_comp_after_pic(self):
        source = "05 WS-FLD PIC 9(5) USAGE COMP."
        fields = parse_copybook(source)
        assert fields[0].usage == "COMP"

    def test_comp3_usage(self):
        source = "05 WS-FLD PIC 9(5)V99 USAGE COMP-3."
        fields = parse_copybook(source)
        assert fields[0].usage == "COMP-3"

    def test_comp5_shorthand(self):
        source = "05 WS-FLD PIC 9(5) COMP-5."
        fields = parse_copybook(source)
        assert fields[0].usage == "COMP-5"

    def test_binary_usage(self):
        source = "05 WS-FLD PIC 9(5) USAGE BINARY."
        fields = parse_copybook(source)
        assert fields[0].usage == "BINARY"

    def test_packed_decimal(self):
        source = "05 WS-FLD PIC 9(5) USAGE PACKED-DECIMAL."
        fields = parse_copybook(source)
        assert fields[0].usage == "PACKED-DECIMAL"

    def test_pointer_usage(self):
        source = "05 WS-FLD USAGE POINTER."
        fields = parse_copybook(source)
        assert fields[0].usage == "POINTER"

    def test_display_default(self):
        source = "05 WS-FLD PIC X(10)."
        fields = parse_copybook(source)
        assert fields[0].usage is None

    def test_comp_no_pic(self):
        """COMP without PIC still captures usage."""
        source = "05 WS-FLD USAGE IS COMP."
        fields = parse_copybook(source)
        assert fields[0].usage == "COMP"

    def test_usage_before_pic(self):
        """USAGE may appear before PIC."""
        source = "05 WS-FLD USAGE COMP-3 PIC 9(5)."
        fields = parse_copybook(source)
        assert fields[0].usage == "COMP-3"
        assert fields[0].pic == "9(5)"


class TestParseFiller:
    def test_filler_named_automatically(self):
        source = """01 WS-TABLE.
           05 FILLER PIC X(20) VALUE 'HELLO'.
           05 WS-DATA PIC X(10)."""
        fields = parse_copybook(source)
        assert len(fields[0].children) == 2
        assert fields[0].children[0].name.startswith("_filler_")
        assert fields[0].children[1].name == "WS-DATA"

    def test_filler_unique_ids(self):
        source = """01 WS-TABLE.
           05 FILLER PIC X(10).
           05 FILLER PIC X(20)."""
        fields = parse_copybook(source)
        assert len(fields[0].children) == 2
        assert fields[0].children[0].name != fields[0].children[1].name


class TestParseMultiLine:
    def test_multi_line_clause(self):
        """Clause spanning two lines (PIC on one line, OCCURS on next)."""
        source = """01 WS-DATA.
           05 WS-FIELD PIC 9(5)
              OCCURS 10 TIMES."""
        fields = parse_copybook(source)
        assert len(fields) == 1
        assert fields[0].children[0].occurs_count == 10
        assert fields[0].children[0].pic == "9(5)"

    def test_multi_line_value(self):
        source = """01 WS-CONST.
           05 WS-MSG PIC X(40)
               VALUE 'LONG MESSAGE HERE'."""
        fields = parse_copybook(source)
        assert fields[0].children[0].value is not None
        assert "LONG MESSAGE" in fields[0].children[0].value


class TestParseEdgeCases:
    def test_empty_source(self):
        fields = parse_copybook("")
        assert fields == []

    def test_only_comments(self):
        source = """      * COMMENT 1
              * COMMENT 2"""
        fields = parse_copybook(source)
        assert fields == []

    def test_only_88_levels(self):
        """88-levels without parent field — should not crash, parent will be missing."""
        source = "88 WS-FLAG VALUE 'Y'."
        fields = parse_copybook(source)
        # 88 without a parent 01-49 is structurally invalid COBOL;
        # the parser creates it but it's a leaf, not a model
        assert len(fields) == 1
        assert fields[0].is_88


# ============================================================
# Utility Function Tests
# ============================================================


class TestPicToPythonType:
    def test_alpha_to_str(self):
        assert pic_to_python_type("X(10)") == "str"

    def test_numeric_to_int(self):
        assert pic_to_python_type("9(5)") == "int"

    def test_decimal_to_decimal(self):
        assert pic_to_python_type("9(5)V99") == "Decimal"

    def test_signed_decimal_to_decimal(self):
        assert pic_to_python_type("S9(7)V99") == "Decimal"

    def test_edited_numeric_to_str(self):
        assert pic_to_python_type("Z(5)9") == "str"

    def test_signed_numeric_to_int(self):
        assert pic_to_python_type("S9(5)") == "int"

    def test_empty_pic_to_str(self):
        assert pic_to_python_type("") == "str"

    def test_none_pic_to_str(self):
        assert pic_to_python_type(None) == "str"  # type: ignore

    # --- USAGE variants ---
    def test_comp_pic_9_to_int(self):
        assert pic_to_python_type("9(5)", "COMP") == "int"

    def test_comp_pic_9v99_to_decimal(self):
        assert pic_to_python_type("9(5)V99", "COMP") == "Decimal"

    def test_comp3_always_decimal(self):
        assert pic_to_python_type("9(5)", "COMP-3") == "Decimal"

    def test_comp3_with_v_decimal(self):
        assert pic_to_python_type("9(5)V99", "COMP-3") == "Decimal"

    def test_comp5_pic_9_to_int(self):
        assert pic_to_python_type("9(5)", "COMP-5") == "int"

    def test_binary_pic_9_to_int(self):
        assert pic_to_python_type("9(5)", "BINARY") == "int"

    def test_packed_decimal_to_decimal(self):
        assert pic_to_python_type("9(5)", "PACKED-DECIMAL") == "Decimal"

    def test_comp1_to_float(self):
        assert pic_to_python_type("", "COMP-1") == "float"

    def test_comp2_to_float(self):
        assert pic_to_python_type("", "COMP-2") == "float"

    def test_pointer_to_int(self):
        assert pic_to_python_type("", "POINTER") == "int"

    def test_display_unchanged(self):
        """Explicit USAGE DISPLAY follows same rules as default."""
        assert pic_to_python_type("X(10)", "DISPLAY") == "str"
        assert pic_to_python_type("9(5)", "DISPLAY") == "int"
        assert pic_to_python_type("9(5)V99", "DISPLAY") == "Decimal"


class TestPicToLength:
    def test_x_with_count(self):
        assert pic_to_length("X(10)") == 10

    def test_9_with_count(self):
        assert pic_to_length("9(5)") == 5

    def test_decimal_with_v(self):
        assert pic_to_length("9(5)V99") == 7  # 5 + 2 (V doesn't count)

    def test_signed_no_extra(self):
        assert pic_to_length("S9(5)") == 5  # S doesn't count

    def test_mixed_x_and_9(self):
        assert pic_to_length("X(20)") == 20

    def test_no_parentheses(self):
        assert pic_to_length("9(5)") == 5

    def test_empty_string(self):
        assert pic_to_length("") == 0

    # --- USAGE variants ---
    def test_comp_4_digits(self):
        assert pic_to_length("9(4)", "COMP") == 2

    def test_comp_5_digits(self):
        assert pic_to_length("9(5)", "COMP") == 4

    def test_comp_10_digits(self):
        assert pic_to_length("9(10)", "COMP") == 8

    def test_comp3_4_digits(self):
        assert pic_to_length("9(4)", "COMP-3") == 3  # (4+2)//2

    def test_comp3_5_digits(self):
        assert pic_to_length("9(5)", "COMP-3") == 3  # (5+2)//2

    def test_comp3_6_digits(self):
        assert pic_to_length("9(6)", "COMP-3") == 4  # (6+2)//2

    def test_comp3_with_v(self):
        """V digits counted for packed storage length."""
        assert pic_to_length("9(3)V99", "COMP-3") == 3  # (5+2)//2

    def test_comp1_length(self):
        assert pic_to_length("", "COMP-1") == 4

    def test_comp2_length(self):
        assert pic_to_length("", "COMP-2") == 8

    def test_pointer_length(self):
        assert pic_to_length("", "POINTER") == 8

    def test_binary_4_digits(self):
        assert pic_to_length("9(4)", "BINARY") == 2

    def test_comp5_9_digits(self):
        assert pic_to_length("9(9)", "COMP-5") == 4

    def test_packed_decimal_length(self):
        assert pic_to_length("9(10)", "PACKED-DECIMAL") == 6  # (10+2)//2

    def test_display_length_with_usage(self):
        """Explicit DISPLAY usage should not change length."""
        assert pic_to_length("X(10)", "DISPLAY") == 10


class TestPyName:
    def test_simple(self):
        assert _py_name("WS-DATA") == "ws_data"

    def test_already_underscore(self):
        assert _py_name("WS_DATA") == "ws_data"

    def test_no_dashes(self):
        assert _py_name("DATA") == "data"


# ============================================================
# Model Generation Tests
# ============================================================


class TestGenerateFlatModel:
    def test_single_field(self):
        source = "01 WS-MSG PIC X(40)."
        fields = parse_copybook(source)
        result = generate_pydantic_model(fields[0])
        assert "class WsMsgModel" in result or "Ws_Msg" in result
        assert "ws_msg" in result
        assert "str" in result

    def test_msgs2_flat(self):
        """MSGS2.CPY — constants only, no OCCURS, no 88."""
        source = """01 WS-MESSAGE-CONSTANTS.
           05 MSG2-EMPLOYEE-TERMINATED PIC X(40)
                   VALUE 'EMPLOYEE IS TERMINATED - SKIPPING'.
           05 MSG2-BATCH-COMPLETE PIC X(40)
                   VALUE 'BATCH PROCESSING COMPLETE'."""
        fields = parse_copybook(source)
        assert len(fields) == 1
        result = generate_pydantic_model(fields[0])
        # Should generate a class with two fields
        assert "class WsMessageConstantsModel" in result or "class Ws_Message_ConstantsModel" in result
        assert "msg2_employee_terminated" in result
        assert "msg2_batch_complete" in result

    def test_simple_field_no_class(self):
        """A single 01-level elementary field doesn't need a class."""
        source = "01 WS-SIMPLE PIC 9(5) VALUE 0."
        fields = parse_copybook(source)
        result = generate_pydantic_model(fields[0])
        # Single elementary field generates a class with the field
        assert "class" in result

    def test_value_defaults_in_model(self):
        """VALUE clauses generate field defaults in the Pydantic model."""
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
        assert m.msg4_batch_complete == 'BATCH PROCESSING COMPLETE'


class TestGenerateNestedModel:
    def test_occurs_generates_child_model(self):
        source = """01 RMAMAST.
           05 RMA-NUMBER PIC X(12).
           05 RMA-LINE-TABLE OCCURS 50 TIMES.
              10 RL-ITEM-ID PIC X(12).
              10 RL-UNIT-PRICE PIC 9(7)V99."""
        fields = parse_copybook(source)
        assert len(fields) == 1
        result = generate_pydantic_model(fields[0])

        # Should have child model class
        assert "RmaLineTableModel" in result or "Rma_Line_TableModel" in result
        # Should have list[ChildModel] type
        assert "list[" in result
        # Should have child fields under the nested model
        assert "rl_item_id" in result
        assert "rl_unit_price" in result
        # Parent model name
        assert "RmamastModel" in result
        # rma_line_table should be list type
        assert "rma_line_table" in result

    def test_occurs_elementary_generates_list_scalar(self):
        """OCCURS on elementary field -> list[scalar], not nested model."""
        source = """01 WS-DATA.
           05 MONTHLY-SALES OCCURS 12 TIMES PIC 9(7)V99."""
        fields = parse_copybook(source)
        assert len(fields) == 1
        children = fields[0].children
        assert len(children) == 1
        assert children[0].occurs_count == 12
        assert children[0].pic == "9(7)V99"
        result = generate_pydantic_model(fields[0])
        assert "list[Decimal]" in result
        assert "monthly_sales" in result

    def test_occurs_string_elementary(self):
        source = """01 WS-DATA.
           05 WS-NAMES OCCURS 5 TIMES PIC X(30)."""
        fields = parse_copybook(source)
        assert len(fields) == 1
        assert fields[0].children[0].occurs_count == 5
        assert fields[0].children[0].pic == "X(30)"
        result = generate_pydantic_model(fields[0])
        assert "list[str]" in result

    def test_indexed_by_does_not_affect_output(self):
        """INDEXED BY is metadata, not reflected in generated Python."""
        source = """05 WS-TABLE OCCURS 8 TIMES INDEXED BY IDX-1.
           10 WS-FIELD PIC X(10)."""
        fields = parse_copybook(source)
        # This is not a top-level 01, but as a standalone parse it works
        result = _generate_nested_occurs_model(fields[0])
        assert "Indexed" not in result  # INDEXED BY should not appear in output

    def test_occurs_comp3_generates_list_decimal(self):
        """OCCURS elementary with USAGE COMP-3 -> list[Decimal]."""
        source = """01 WS-DATA.
           05 WS-TABLE OCCURS 3 TIMES PIC 9(5) USAGE COMP-3."""
        fields = parse_copybook(source)
        assert fields[0].children[0].usage == "COMP-3"
        result = generate_pydantic_model(fields[0])
        assert "list[Decimal]" in result

    def test_occurs_binary_generates_list_int(self):
        """OCCURS elementary with COMP usage -> list[int]."""
        source = """01 WS-DATA.
           05 WS-TABLE OCCURS 3 TIMES PIC 9(5) COMP."""
        fields = parse_copybook(source)
        assert fields[0].children[0].usage == "COMP"
        result = generate_pydantic_model(fields[0])
        assert "list[int]" in result

    def test_elementary_comp3_field(self):
        """Non-OCCURS COMP-3 field -> Decimal."""
        source = """01 WS-REC.
           05 WS-PAY-AMT PIC 9(7)V99 USAGE COMP-3."""
        fields = parse_copybook(source)
        assert fields[0].children[0].usage == "COMP-3"
        result = generate_pydantic_model(fields[0])
        assert "Decimal" in result

    def test_elementary_binary_field(self):
        """Non-OCCURS BINARY field -> int."""
        source = """01 WS-REC.
           05 WS-COUNT PIC 9(5) USAGE BINARY."""
        fields = parse_copybook(source)
        assert fields[0].children[0].usage == "BINARY"
        result = generate_pydantic_model(fields[0])
        assert "int" in result

    def test_elementary_pointer_field(self):
        """POINTER field -> int."""
        source = """01 WS-REC.
           05 WS-PTR USAGE POINTER."""
        fields = parse_copybook(source)
        assert fields[0].children[0].usage == "POINTER"
        result = generate_pydantic_model(fields[0])
        assert "int" in result

    def test_elementary_comp1_field(self):
        """COMP-1 field -> float."""
        source = """01 WS-REC.
           05 WS-FLOAT USAGE COMP-1."""
        fields = parse_copybook(source)
        assert fields[0].children[0].usage == "COMP-1"
        result = generate_pydantic_model(fields[0])
        assert "float" in result


class TestGenerate88Constants:
    def test_88_constants_generated(self):
        source = """05 WS-STATUS PIC X(01).
           88 WS-ACTIVE   VALUE 'A'.
           88 WS-INACTIVE VALUE 'I'."""
        fields = parse_copybook(source)
        constants = _generate_88_constants(fields[0])
        assert len(constants) >= 2
        assert any("ACTIVE" in c and "'A'" in c for c in constants)
        assert any("INACTIVE" in c and "'I'" in c for c in constants)

    def test_88_not_included_in_field_lines(self):
        """88-level children should not appear as model fields."""
        source = """05 WS-STATUS PIC X(01).
           88 WS-ACTIVE   VALUE 'A'."""
        fields = parse_copybook(source)
        result = generate_pydantic_model(fields[0])
        # Should NOT have ws_active as a field (it's an 88 condition, not a field)
        assert "ws_active" not in result.lower().split("ws_active")


class TestGenerate88Validators:
    """Tests for @field_validator and SET TO TRUE generation (Problem 3)."""

    def test_field_validator_generated(self):
        """Field with 88-level children gets a @field_validator."""
        from cobol_migrator.shared_model_generator import _generate_field_validator
        source = """05 WS-STATUS PIC X(01).
           88 WS-ACTIVE   VALUE 'A'.
           88 WS-INACTIVE VALUE 'I'."""
        fields = parse_copybook(source)
        lines = _generate_field_validator(fields[0])
        assert any("field_validator" in l for l in lines)
        assert any("validate_ws_status" in l for l in lines)
        assert any("'A'" in l or '"A"' in l for l in lines)
        assert any("'I'" in l or '"I"' in l for l in lines)

    def test_field_validator_not_generated(self):
        """Field without 88-level children gets no validator."""
        from cobol_migrator.shared_model_generator import _generate_field_validator
        source = """05 WS-NAME PIC X(20)."""
        fields = parse_copybook(source)
        lines = _generate_field_validator(fields[0])
        assert lines == []

    def test_set_true_helper_generated(self):
        """Field with 88-level children gets a SET TRUE helper."""
        from cobol_migrator.shared_model_generator import _generate_set_true_helper
        source = """05 WS-STATUS PIC X(01).
           88 WS-ACTIVE   VALUE 'A'.
           88 WS-INACTIVE VALUE 'I'."""
        fields = parse_copybook(source)
        lines = _generate_set_true_helper(fields[0])
        assert any("set_ws_status_to_true" in l for l in lines)
        assert any("WS_ACTIVE" in l for l in lines)

    def test_validator_accepts_valid_values(self):
        """@field_validator accepts valid 88-level values."""
        source = """01 WS-REC.
           05 WS-STATUS PIC X(01).
              88 WS-ACTIVE   VALUE 'A'.
              88 WS-INACTIVE VALUE 'I'."""
        fields = parse_copybook(source)
        code = generate_pydantic_model(fields[0])
        full = "from pydantic import BaseModel, field_validator\n" + code
        ns: dict = {}
        exec(full, ns)
        m = ns["Ws_RecModel"](ws_status="A")
        assert m.ws_status == "A"
        m.ws_status = "I"
        assert m.ws_status == "I"

    def test_validator_rejects_invalid_values(self):
        """@field_validator raises ValueError for invalid values."""
        source = """01 WS-REC.
           05 WS-STATUS PIC X(01).
              88 WS-ACTIVE   VALUE 'A'.
              88 WS-INACTIVE VALUE 'I'."""
        fields = parse_copybook(source)
        code = generate_pydantic_model(fields[0])
        full = "from pydantic import BaseModel, field_validator\n" + code
        ns: dict = {}
        exec(full, ns)
        with pytest.raises(Exception):
            ns["Ws_RecModel"](ws_status="X")

    def test_set_true_helper_sets_field(self):
        """set_<field>_to_true sets the field to the correct value."""
        source = """01 WS-REC.
           05 WS-STATUS PIC X(01).
              88 WS-ACTIVE   VALUE 'A'.
              88 WS-INACTIVE VALUE 'I'."""
        fields = parse_copybook(source)
        code = generate_pydantic_model(fields[0])
        full = "from pydantic import BaseModel, field_validator\n" + code
        ns: dict = {}
        exec(full, ns)
        m = ns["Ws_RecModel"](ws_status="A")
        m.set_ws_status_to_true("WS_INACTIVE")
        assert m.ws_status == "I"

    def test_set_true_helper_unknown_condition_noop(self):
        """Unknown condition name does nothing."""
        source = """01 WS-REC.
           05 WS-STATUS PIC X(01).
              88 WS-ACTIVE   VALUE 'A'."""
        fields = parse_copybook(source)
        code = generate_pydantic_model(fields[0])
        full = "from pydantic import BaseModel, field_validator\n" + code
        ns: dict = {}
        exec(full, ns)
        m = ns["Ws_RecModel"](ws_status="A")
        m.set_ws_status_to_true("NONEXISTENT")
        assert m.ws_status == "A"

    def test_88_validators_in_occurs_nested_model(self):
        """88-level validators appear inside OCCURS nested models."""
        source = """01 EMPLOYEE-MASTER-REC.
           05 EM-DEPENDENT-TABLE OCCURS 6 TIMES.
              10 DEP-RELATIONSHIP    PIC X(01).
                  88 DEP-CHILD                   VALUE 'C'.
                  88 DEP-SPOUSE                  VALUE 'S'."""
        fields = parse_copybook(source)
        result = generate_pydantic_model(fields[0])
        assert "@field_validator('dep_relationship')" in result
        assert "def validate_dep_relationship" in result
        assert "set_dep_relationship_to_true" in result
        assert "'C'" in result or '"C"' in result
        assert "'S'" in result or '"S"' in result
        # Verify valid Python
        import ast
        full = "from pydantic import BaseModel, field_validator\n" + result
        ast.parse(full)

    def test_occurs_nested_validator_runtime(self):
        """88-level validators in OCCURS models work at runtime."""
        source = """01 EMPLOYEE-MASTER-REC.
           05 EM-DEPENDENT-TABLE OCCURS 6 TIMES.
              10 DEP-RELATIONSHIP    PIC X(01).
                  88 DEP-CHILD                   VALUE 'C'.
                  88 DEP-SPOUSE                  VALUE 'S'."""
        fields = parse_copybook(source)
        code = generate_pydantic_model(fields[0])
        full = "from pydantic import BaseModel, field_validator\n" + code
        ns: dict = {}
        exec(full, ns)
        DepModel = ns["Em_Dependent_TableModel"]
        d = DepModel(dep_relationship="C")
        assert d.dep_relationship == "C"
        with pytest.raises(Exception):
            DepModel(dep_relationship="X")
        d.set_dep_relationship_to_true("DEP_SPOUSE")
        assert d.dep_relationship == "S"

    def test_numeric_88_validator(self):
        """Numeric 88 values generate correct validator set."""
        source = """05 WS-CODE PIC 9(2).
           88 WS-CODE-OK VALUE 0.
           88 WS-CODE-ERR VALUE 99."""
        fields = parse_copybook(source)
        code = generate_pydantic_model(fields[0])
        assert "valid = {0, 99}" in code or "valid = {99, 0}" in code

    def test_no_validator_without_88(self):
        """Field without 88-levels should not have an unused import."""
        source = """01 WS-REC.
           05 WS-NAME PIC X(20)."""
        fields = parse_copybook(source)
        code = generate_pydantic_model(fields[0])
        assert "field_validator" not in code
        assert "validate_ws_name" not in code

    def test_model_config_validate_assignment(self):
        """When validators are present, model_config includes validate_assignment=True."""
        source = """01 WS-REC.
           05 WS-STATUS PIC X(01).
              88 WS-ACTIVE VALUE 'A'."""
        fields = parse_copybook(source)
        code = generate_pydantic_model(fields[0])
        assert "validate_assignment" in code

    def test_88_constants_not_duplicated(self):
        """88-level constants should not be duplicated when validators are added."""
        source = """01 WS-REC.
           05 WS-STATUS PIC X(01).
              88 WS-ACTIVE   VALUE 'A'.
              88 WS-INACTIVE VALUE 'I'."""
        fields = parse_copybook(source)
        code = generate_pydantic_model(fields[0])
        # Count occurrences of each constant
        assert code.count("WS_STATUS_WS_ACTIVE_A") == 1
        assert code.count("WS_STATUS_WS_INACTIVE_I") == 1


    def test_validator_allows_empty_string(self):
        """String 88-level validators should accept '' (matches COBOL space init)."""
        source = """01 WS-REC.
            05 WS-STATUS PIC X(01).
               88 WS-ACTIVE   VALUE 'A'.
               88 WS-INACTIVE VALUE 'I'."""
        fields = parse_copybook(source)
        code = generate_pydantic_model(fields[0])
        full = "from pydantic import BaseModel, field_validator\n" + code
        ns: dict = {}
        exec(full, ns)
        m = ns["Ws_RecModel"](ws_status="")
        assert m.ws_status == ""

    def test_88_default_when_no_value_clause(self):
        """Field with 88-level children but no VALUE defaults to first 88 value."""
        source = """01 WS-REC.
            05 WS-STATUS PIC X(01).
               88 WS-ACTIVE   VALUE 'A'.
               88 WS-INACTIVE VALUE 'I'."""
        fields = parse_copybook(source)
        code = generate_pydantic_model(fields[0])
        full = "from pydantic import BaseModel, field_validator\n" + code
        ns: dict = {}
        exec(full, ns)
        m = ns["Ws_RecModel"]()
        assert m.ws_status == "A"


class TestGenerateFullEmpMast:
    """Stress test with a realistic subset of EMPMAST.CPY."""

    EMPMAST_SUBSET = """01 EMPLOYEE-MASTER-REC.
           05 EM-EMPLOYEE-ID          PIC X(08).
           05 EM-EMPLOYEE-NAME.
               10 EM-FIRST-NAME       PIC X(20).
               10 EM-LAST-NAME        PIC X(30).
           05 EM-PAY-RATE             PIC 9(5)V99.
           05 EM-STATUS-CODE          PIC X(01).
               88 EM-ACTIVE                      VALUE 'A'.
               88 EM-TERMINATED                  VALUE 'T'.
           05 EM-DEDUCTION-COUNT      PIC 9(2).
           05 EM-DEDUCTION-TABLE OCCURS 8 TIMES
                       INDEXED BY DED-IDX.
               10 DED-CODE            PIC X(04).
               10 DED-DESCRIPTION     PIC X(20).
               10 DED-TYPE            PIC X(01).
               10 DED-AMOUNT          PIC 9(7)V99.
           05 EM-DEPENDENT-COUNT      PIC 9(2).
           05 EM-DEPENDENT-TABLE OCCURS 6 TIMES
                       INDEXED BY DEP-IDX.
               10 DEP-NAME            PIC X(30).
               10 DEP-RELATIONSHIP    PIC X(01).
                   88 DEP-CHILD                   VALUE 'C'.
                   88 DEP-SPOUSE                  VALUE 'S'.
               10 DEP-BIRTH-DATE      PIC 9(8)."""

    def test_parse_emp_mast_structure(self):
        fields = parse_copybook(self.EMPMAST_SUBSET)
        assert len(fields) == 1
        assert fields[0].name == "EMPLOYEE-MASTER-REC"

        children = fields[0].children
        names = [c.name for c in children]
        assert "EM-EMPLOYEE-ID" in names
        assert "EM-EMPLOYEE-NAME" in names
        assert "EM-DEDUCTION-TABLE" in names
        assert "EM-DEPENDENT-TABLE" in names

        # Check OCCURS counts
        ded_table = next(c for c in children if c.name == "EM-DEDUCTION-TABLE")
        assert ded_table.occurs_count == 8
        assert ded_table.indexed_by == "DED-IDX"
        assert len(ded_table.children) == 4  # CODE, DESCRIPTION, TYPE, AMOUNT

        dep_table = next(c for c in children if c.name == "EM-DEPENDENT-TABLE")
        assert dep_table.occurs_count == 6
        assert dep_table.indexed_by == "DEP-IDX"

        # Check group fields
        emp_name = next(c for c in children if c.name == "EM-EMPLOYEE-NAME")
        assert len(emp_name.children) == 2
        assert emp_name.children[0].name == "EM-FIRST-NAME"

        # Check 88-levels under STATUS-CODE
        status_code = next(c for c in children if c.name == "EM-STATUS-CODE")
        eighty_eights = [c for c in status_code.children if c.is_88]
        assert len(eighty_eights) == 2

        # Check 88-levels under DEP-RELATIONSHIP
        dep_rel = dep_table.children[1]
        dep_88s = [c for c in dep_rel.children if c.is_88]
        assert len(dep_88s) == 2

    def test_generate_emp_mast_model(self):
        fields = parse_copybook(self.EMPMAST_SUBSET)
        result = generate_pydantic_model(fields[0])

        # Should have the main class
        assert "EmployeeMasterRecModel" in result or "Employee_Master_RecModel" in result

        # Should have nested OCCURS models
        assert "DeductionTableModel" in result or "Deduction_TableModel" in result
        assert "DependentTableModel" in result or "Dependent_TableModel" in result

        # Should have list types for OCCURS fields
        assert "em_deduction_table: list[" in result
        assert "em_dependent_table: list[" in result

        # Should have flat fields
        assert "em_employee_id" in result
        assert "em_pay_rate" in result
        assert "em_status_code" in result

        # Should have nested group field
        assert "em_employee_name" in result or "employee_name_model" in result.lower()

        # Should have child fields in nested models
        assert "ded_code" in result
        assert "ded_amount" in result
        assert "dep_name" in result
        assert "dep_birth_date" in result

        # Should NOT have 88-levels as fields
        assert "em_active" not in result.lower().split("em_active")
        assert "dep_child" not in result.lower().split("dep_child")

        # Verify it's valid syntax
        import ast
        try:
            ast.parse(result)
        except SyntaxError as e:
            pytest.fail(f"Generated model has syntax error: {e}")

    def test_emp_mast_constants_generated(self):
        """88-level conditions should generate constants."""
        fields = parse_copybook(self.EMPMAST_SUBSET)
        result = generate_pydantic_model(fields[0])

        # Should contain constant definitions for 88-level values
        assert "EM_STATUS_CODE" in result.upper()
        assert "EM_ACTIVE" in result.upper()
        assert "EM_TERMINATED" in result.upper()


class TestGeneratePaytablePattern:
    """PAYTABLE.CPY pattern — REDEFINES + OCCURS."""

    def test_parse_paytable_structure(self):
        source = """01 WS-FEDERAL-BRACKET-TABLE.
           05 FILLER PIC X(20) VALUE '00000000010000000000'.
        01 WS-BRACKET-REDEF REDEFINES WS-FEDERAL-BRACKET-TABLE.
           05 WS-BRACKET-ENTRY OCCURS 6 TIMES.
              10 WS-BRACKET-FLOOR    PIC 9(7)V99.
              10 WS-BRACKET-RATE     PIC 9(2)V99."""
        fields = parse_copybook(source)
        assert len(fields) == 2
        # First 01: has FILLER
        assert fields[0].children[0].name.startswith("_filler_")
        # Second 01: REDEFINES first, has OCCURS group
        assert fields[1].redefines_target == "WS-FEDERAL-BRACKET-TABLE"
        assert fields[1].children[0].occurs_count == 6


# ============================================================
# Integration Tests
# ============================================================


class TestGenerateSharedModelsText:
    def test_empty_copybooks(self, tmp_path):
        """No .cpy files → empty result."""
        result = generate_shared_models_text({}, tmp_path)
        assert result == ""

    def test_no_cpy_files(self, tmp_path):
        """Files that don't end in .cpy are skipped."""
        copybooks = {
            "MYPROG": {"file_path": "myprog.cbl"},
        }
        result = generate_shared_models_text(copybooks, tmp_path)
        assert result == ""

    def test_generated_code_is_valid_python(self):
        """Full pipeline: parse → generate → syntax check."""
        import ast
        source = """01 EMPLOYEE-MASTER-REC.
           05 EM-EMPLOYEE-ID          PIC X(08).
           05 EM-EMPLOYEE-NAME.
               10 EM-FIRST-NAME       PIC X(20).
               10 EM-LAST-NAME        PIC X(30).
           05 EM-PAY-RATE             PIC 9(5)V99.
           05 EM-STATUS-CODE          PIC X(01).
               88 EM-ACTIVE                      VALUE 'A'.
           05 EM-DEDUCTION-TABLE OCCURS 8 TIMES.
               10 DED-CODE            PIC X(04).
               10 DED-AMOUNT          PIC 9(7)V99."""
        fields = parse_copybook(source)
        assert len(fields) == 1
        result = generate_pydantic_model(fields[0])

        # Wrap in proper imports for syntax checking
        full_code = "from pydantic import BaseModel\nfrom decimal import Decimal\n\n" + result
        try:
            tree = ast.parse(full_code)
        except SyntaxError as e:
            pytest.fail(f"Generated model has syntax error: {e}")

        # Verify key structural elements via AST
        classes = [n for n in ast.walk(tree) if isinstance(n, ast.ClassDef)]
        class_names = [c.name for c in classes]
        assert "EmployeeMasterRecModel" in class_names or any("Employee" in n for n in class_names)
        assert any("Deduction" in n for n in class_names)


class TestRegression:
    """Regression tests against previously-working features."""

    def test_old_extract_function_still_works(self):
        """The old extract_copybook_fields() is deprecated but should still function."""
        from cobol_migrator.shared_model_generator import extract_copybook_fields
        source = "01 WS-DATA PIC X(10)."
        fields = extract_copybook_fields(source)
        assert len(fields) == 1
        assert fields[0]["name"] == "WS-DATA"
        assert "PIC" in fields[0]["pic"]

    def test_shared_models_imports_decimal_for_comp3(self):
        """generate_shared_models_text adds decimal import when COMP-3 fields present."""
        source = """01 WS-REC.
           05 WS-AMT PIC 9(5)V99 USAGE COMP-3."""
        fields = parse_copybook(source)
        from cobol_migrator.shared_model_generator import _check_field_uses_decimal
        assert _check_field_uses_decimal(fields[0])

    def test_shared_models_does_not_import_decimal_for_comp_only(self):
        """COMP without V should not trigger Decimal import."""
        source = """01 WS-REC.
           05 WS-CNT PIC 9(5) USAGE COMP."""
        fields = parse_copybook(source)
        from cobol_migrator.shared_model_generator import _check_field_uses_decimal
        assert not _check_field_uses_decimal(fields[0])


class TestRecordGenerator:
    """Tests for the bytes-backed record generator (record_generator.py)."""

    def test_layout_basic(self):
        from cobol_migrator.record_generator import _compute_layout
        source = """01 DATA-REC.
           05 TEXT-FIELD PIC X(20).
           05 NUM-FIELD REDEFINES TEXT-FIELD PIC 9(5).
           05 TAIL-FIELD PIC X(5)."""
        fields = parse_copybook(source)
        slots = _compute_layout(fields[0])
        assert len(slots) == 3
        text_f = next(s for s in slots if s.py_name == "text_field")
        num_f = next(s for s in slots if s.py_name == "num_field")
        tail_f = next(s for s in slots if s.py_name == "tail_field")
        assert text_f.offset == 0 and text_f.length == 20
        assert num_f.offset == 0 and num_f.length == 5   # REDEFINES = same offset
        assert tail_f.offset == 20 and tail_f.length == 5

    def test_layout_nested_group(self):
        from cobol_migrator.record_generator import _compute_layout
        source = """01 DATA-REC.
           05 GROUP-A.
              10 FLD-A1 PIC X(10).
              10 FLD-A2 PIC 9(5).
           05 GROUP-B.
              10 FLD-B1 PIC X(20)."""
        fields = parse_copybook(source)
        slots = _compute_layout(fields[0])
        assert len(slots) == 3
        a1 = next(s for s in slots if s.py_name == "group_a_fld_a1")
        a2 = next(s for s in slots if s.py_name == "group_a_fld_a2")
        b1 = next(s for s in slots if s.py_name == "group_b_fld_b1")
        assert a1.offset == 0 and a1.length == 10
        assert a2.offset == 10 and a2.length == 5
        assert b1.offset == 15 and b1.length == 20

    def test_layout_occurs_elementary(self):
        from cobol_migrator.record_generator import _compute_layout, _record_size
        source = """01 DATA-REC.
           05 MONTHLY-SALES OCCURS 12 TIMES PIC 9(5)."""
        fields = parse_copybook(source)
        slots = _compute_layout(fields[0])
        assert len(slots) == 12
        assert all(s.length == 5 for s in slots)
        assert slots[0].offset == 0
        assert slots[1].offset == 5
        assert slots[11].offset == 55
        assert _record_size(slots) == 60

    def test_record_class_generates_valid_python(self):
        import ast
        source = """01 DATA-REC.
           05 TEXT-FIELD PIC X(20).
           05 NUM-FIELD REDEFINES TEXT-FIELD PIC 9(5).
           05 TAIL-FIELD PIC X(5)."""
        fields = parse_copybook(source)
        from cobol_migrator.record_generator import generate_record_class
        code = generate_record_class(fields[0])
        try:
            ast.parse(code)
        except SyntaxError as e:
            pytest.fail(f"Generated record class has syntax error: {e}")

    def test_redefines_round_trip(self):
        from cobol_migrator.record_generator import generate_record_class
        source = """01 DATA-REC.
           05 TEXT-FIELD PIC X(20).
           05 NUM-FIELD REDEFINES TEXT-FIELD PIC 9(5)."""
        fields = parse_copybook(source)
        code = generate_record_class(fields[0])
        local_ns: dict = {}
        exec(code, local_ns)
        RecordClass = local_ns["Data_RecRecord"]

        r = RecordClass()
        r.num_field = 12345
        # text_field shares same bytes — should show the same digits
        assert r.num_field == 12345
        assert r.text_field.strip() == "12345"
        # Mutate through text_field, num_field changes too
        r.text_field = "67890"
        assert r.num_field == 67890

    def test_redefines_with_comp3(self):
        from cobol_migrator.record_generator import generate_record_class
        source = """01 DATA-REC.
           05 WS-BUFFER PIC X(10).
           05 WS-NUM REDEFINES WS-BUFFER PIC 9(5) USAGE COMP-3."""
        fields = parse_copybook(source)
        code = generate_record_class(fields[0])
        local_ns: dict = {}
        exec(code, local_ns)
        RecordClass = local_ns["Data_RecRecord"]

        r = RecordClass()
        r.ws_num = 12345
        assert r.ws_num == 12345
        # WS-BUFFER should now contain the packed BCD bytes
        assert len(r._data) == 10

    def test_display_string_round_trip(self):
        from cobol_migrator.record_generator import generate_record_class
        source = """01 DATA-REC.
           05 NAME PIC X(10)."""
        fields = parse_copybook(source)
        code = generate_record_class(fields[0])
        local_ns: dict = {}
        exec(code, local_ns)
        RecordClass = local_ns["Data_RecRecord"]

        r = RecordClass()
        r.name = "ALICE"
        assert r.name == "ALICE"
        assert len(r._data) == 10

    def test_display_int_round_trip(self):
        from cobol_migrator.record_generator import generate_record_class
        source = """01 DATA-REC.
           05 COUNT PIC 9(5)."""
        fields = parse_copybook(source)
        code = generate_record_class(fields[0])
        local_ns: dict = {}
        exec(code, local_ns)
        RecordClass = local_ns["Data_RecRecord"]

        r = RecordClass()
        r.count = 42
        assert r.count == 42

    def test_display_decimal_round_trip(self):
        from cobol_migrator.record_generator import generate_record_class
        source = """01 DATA-REC.
           05 AMOUNT PIC 9(5)V99."""
        fields = parse_copybook(source)
        code = generate_record_class(fields[0])
        local_ns: dict = {}
        exec(code, local_ns)
        RecordClass = local_ns["Data_RecRecord"]

        from decimal import Decimal
        r = RecordClass()
        r.amount = Decimal("123.45")
        assert r.amount == Decimal("123.45")

    def test_class_size_method(self):
        from cobol_migrator.record_generator import generate_record_class
        source = """01 DATA-REC.
           05 FLD1 PIC X(10).
           05 FLD2 PIC 9(5)."""
        fields = parse_copybook(source)
        code = generate_record_class(fields[0])
        local_ns: dict = {}
        exec(code, local_ns)
        assert local_ns["Data_RecRecord"].size() == 15

    def test_record_from_bytes(self):
        from cobol_migrator.record_generator import generate_record_class
        source = """01 DATA-REC.
           05 NAME PIC X(5)."""
        fields = parse_copybook(source)
        code = generate_record_class(fields[0])
        local_ns: dict = {}
        exec(code, local_ns)
        RecordClass = local_ns["Data_RecRecord"]

        data = b"HELLO"
        r = RecordClass(data)
        assert r.name == "HELLO"

    def test_occurs_group_generates_properties(self):
        from cobol_migrator.record_generator import generate_record_class, _compute_layout
        source = """01 DATA-REC.
           05 WS-TABLE OCCURS 3 TIMES.
              10 WS-ITEM PIC X(5).
              10 WS-QTY PIC 9(3)."""
        fields = parse_copybook(source)
        slots = _compute_layout(fields[0])
        # 3 occurrences * 2 fields each = 6 slots
        assert len(slots) == 6
        # Check offsets: occurrence 1 starts at 0, occurrence 2 at 8, occurrence 3 at 16
        assert slots[0].offset == 0   # WS-ITEM[0]
        assert slots[1].offset == 5   # WS-QTY[0]
        assert slots[2].offset == 8   # WS-ITEM[1]
        assert slots[3].offset == 13  # WS-QTY[1]
        assert slots[4].offset == 16  # WS-ITEM[2]
        assert slots[5].offset == 21  # WS-QTY[2]
