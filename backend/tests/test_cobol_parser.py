"""Tests for the COBOL record layout parser."""
import pytest

from cobol_migrator.cobol_parser import (
    COBOLField,
    COBOLRecordLayout,
    extract_fd_records,
    extract_file_assignments,
    generate_cobol_sample_data,
    get_input_file_layout,
    parse_pic_clause,
)


class TestParsePicClause:
    """Tests for PIC clause parsing."""

    def test_alphanumeric_x_with_count(self):
        length, is_numeric, decimals = parse_pic_clause("X(06)")
        assert length == 6
        assert not is_numeric
        assert decimals == 0

    def test_alphanumeric_x_with_larger_count(self):
        length, is_numeric, decimals = parse_pic_clause("X(30)")
        assert length == 30
        assert not is_numeric
        assert decimals == 0

    def test_numeric_9_with_count(self):
        length, is_numeric, decimals = parse_pic_clause("9(05)")
        assert length == 5
        assert is_numeric
        assert decimals == 0

    def test_numeric_with_implied_decimal(self):
        length, is_numeric, decimals = parse_pic_clause("9(03)V99")
        assert length == 5  # 3 + 2
        assert is_numeric
        assert decimals == 2

    def test_numeric_with_different_decimal_places(self):
        length, is_numeric, decimals = parse_pic_clause("9(05)V9(3)")
        assert length == 8  # 5 + 3
        assert is_numeric
        assert decimals == 3

    def test_literal_x_characters(self):
        length, is_numeric, decimals = parse_pic_clause("XXX")
        assert length == 3
        assert not is_numeric

    def test_literal_9_characters(self):
        length, is_numeric, decimals = parse_pic_clause("9999")
        assert length == 4
        assert is_numeric

    def test_edited_numeric_z(self):
        length, is_numeric, decimals = parse_pic_clause("Z(07)V99")
        assert length == 9  # 7 + 2
        assert is_numeric
        assert decimals == 2


class TestCOBOLField:
    """Tests for COBOLField sample value generation."""

    def test_id_field_generates_numeric(self):
        field = COBOLField(
            name="EMP-ID",
            pic="X(06)",
            length=6,
            offset=0,
            is_numeric=False,
            decimal_places=0,
        )
        value = field.generate_sample_value(1)
        assert len(value) == 6
        assert value.isdigit()

    def test_name_field_generates_text(self):
        field = COBOLField(
            name="EMP-NAME",
            pic="X(30)",
            length=30,
            offset=6,
            is_numeric=False,
            decimal_places=0,
        )
        value = field.generate_sample_value(1)
        assert len(value) == 30
        assert "John Smith" in value or "Smith" in value.strip()

    def test_rate_field_generates_reasonable_value(self):
        field = COBOLField(
            name="EMP-RATE",
            pic="9(03)V99",
            length=5,
            offset=41,
            is_numeric=True,
            decimal_places=2,
        )
        value = field.generate_sample_value(1)
        assert len(value) == 5
        assert value.isdigit()
        # Should be around 17.50 (1750 in implied decimal)
        actual_value = int(value) / 100
        assert 10 <= actual_value <= 100

    def test_hours_field_generates_reasonable_value(self):
        field = COBOLField(
            name="EMP-HOURS",
            pic="9(03)V99",
            length=5,
            offset=36,
            is_numeric=True,
            decimal_places=2,
        )
        value = field.generate_sample_value(1)
        assert len(value) == 5
        assert value.isdigit()
        # Should be around 40 hours (4000 in implied decimal)
        actual_value = int(value) / 100
        assert 30 <= actual_value <= 100


class TestCOBOLRecordLayout:
    """Tests for COBOLRecordLayout."""

    @pytest.fixture
    def employee_layout(self):
        return COBOLRecordLayout(
            record_name="EMP-IN-REC",
            fields=[
                COBOLField("EMP-ID", "X(06)", 6, 0, False, 0),
                COBOLField("EMP-NAME", "X(30)", 30, 6, False, 0),
                COBOLField("EMP-HOURS", "9(03)V99", 5, 36, True, 2),
                COBOLField("EMP-RATE", "9(03)V99", 5, 41, True, 2),
            ],
            total_length=46,
        )

    def test_generate_sample_record_correct_length(self, employee_layout):
        record = employee_layout.generate_sample_record(1)
        assert len(record) == 46

    def test_generate_sample_record_no_spaces_between_fields(self, employee_layout):
        record = employee_layout.generate_sample_record(1)
        # The record should be exactly 46 chars with no extra spaces
        # ID(6) + NAME(30) + HOURS(5) + RATE(5) = 46
        emp_id = record[0:6]
        emp_name = record[6:36]
        emp_hours = record[36:41]
        emp_rate = record[41:46]
        
        assert len(emp_id) == 6
        assert len(emp_name) == 30
        assert len(emp_hours) == 5
        assert len(emp_rate) == 5
        
        # No spaces should appear between the numeric fields
        assert emp_hours.isdigit()
        assert emp_rate.isdigit()

    def test_generate_multiple_records_unique(self, employee_layout):
        records = employee_layout.generate_sample_records(3)
        assert len(records) == 3
        # Records should be different
        assert len(set(records)) == 3

    def test_field_documentation(self, employee_layout):
        docs = employee_layout.get_field_documentation()
        assert "EMP-ID" in docs
        assert "EMP-NAME" in docs
        assert "EMP-HOURS" in docs
        assert "EMP-RATE" in docs
        assert "46 chars total" in docs


class TestExtractFDRecords:
    """Tests for extracting FD records from COBOL source."""

    def test_extract_simple_fd(self):
        cobol = """
       DATA DIVISION.
       FILE SECTION.
       FD  EMP-INFILE.
       01  EMP-IN-REC.
           05 EMP-ID              PIC X(06).
           05 EMP-NAME            PIC X(30).
       WORKING-STORAGE SECTION.
        """
        records = extract_fd_records(cobol)
        assert "EMP-INFILE" in records
        layout = records["EMP-INFILE"]
        assert layout.total_length == 36
        assert len(layout.fields) == 2

    def test_extract_fd_with_numeric_fields(self):
        cobol = """
       DATA DIVISION.
       FILE SECTION.
       FD  EMP-INFILE.
       01  EMP-IN-REC.
           05 EMP-ID              PIC X(06).
           05 EMP-HOURS           PIC 9(03)V99.
           05 EMP-RATE            PIC 9(03)V99.
       WORKING-STORAGE SECTION.
        """
        records = extract_fd_records(cobol)
        layout = records["EMP-INFILE"]
        assert layout.total_length == 16  # 6 + 5 + 5


class TestExtractFileAssignments:
    """Tests for extracting file assignments."""

    def test_extract_quoted_assignment(self):
        cobol = """
       FILE-CONTROL.
           SELECT EMP-INFILE ASSIGN TO 'EMPLOYEE.DAT'
               ORGANIZATION IS LINE SEQUENTIAL.
        """
        assignments = extract_file_assignments(cobol)
        assert assignments["EMP-INFILE"] == "EMPLOYEE.DAT"

    def test_extract_double_quoted_assignment(self):
        cobol = """
       FILE-CONTROL.
           SELECT EMP-INFILE ASSIGN TO "EMPLOYEE.DAT"
        """
        assignments = extract_file_assignments(cobol)
        assert assignments["EMP-INFILE"] == "EMPLOYEE.DAT"


class TestGetInputFileLayout:
    """Tests for getting input file layout."""

    def test_finds_input_file(self):
        cobol = """
       FILE-CONTROL.
           SELECT EMP-INFILE ASSIGN TO 'EMPLOYEE.DAT'.
           SELECT REPORT-OUT ASSIGN TO 'PAYROLL.RPT'.
       
       DATA DIVISION.
       FILE SECTION.
       FD  EMP-INFILE.
       01  EMP-IN-REC.
           05 EMP-ID              PIC X(06).
       WORKING-STORAGE SECTION.
        """
        filename, layout = get_input_file_layout(cobol)
        assert filename == "EMPLOYEE.DAT"
        assert layout is not None

    def test_skips_output_files(self):
        cobol = """
       FILE-CONTROL.
           SELECT REPORT-OUT ASSIGN TO 'PAYROLL.RPT'.
       
       DATA DIVISION.
       FILE SECTION.
       FD  REPORT-OUT.
       01  REPORT-REC             PIC X(132).
       WORKING-STORAGE SECTION.
        """
        filename, layout = get_input_file_layout(cobol)
        # Should not return the report file as input
        assert filename is None or "RPT" not in filename.upper()


class TestGenerateCOBOLSampleData:
    """Tests for generating sample data files."""

    def test_generates_correct_format(self):
        cobol = """
       FILE-CONTROL.
           SELECT EMP-INFILE ASSIGN TO 'EMPLOYEE.DAT'.
       
       DATA DIVISION.
       FILE SECTION.
       FD  EMP-INFILE.
       01  EMP-IN-REC.
           05 EMP-ID              PIC X(06).
           05 EMP-NAME            PIC X(30).
           05 EMP-HOURS           PIC 9(03)V99.
           05 EMP-RATE            PIC 9(03)V99.
       WORKING-STORAGE SECTION.
        """
        sample_data = generate_cobol_sample_data(cobol, count=3)
        
        assert "EMPLOYEE.DAT" in sample_data
        content = sample_data["EMPLOYEE.DAT"]
        lines = content.strip().split("\n")
        
        assert len(lines) == 3
        for line in lines:
            assert len(line) == 46  # Exact record length
