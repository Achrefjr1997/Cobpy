"""Tests for the validation stack."""
from __future__ import annotations

import pytest

from cobol_migrator.validators.static_analysis import run_static_validation
from cobol_migrator.validators.verdict import compute_verdict, ValidationScorecard
from cobol_migrator.validators.differential import DifferentialResult
from cobol_migrator.validators.property_based import PropertyResult
from cobol_migrator.validators.llm_judge import JudgeResult
from cobol_migrator.validators.static_analysis import StaticResult


class TestStaticValidation:
    """Tests for static analysis validator."""

    def test_valid_code_passes(self):
        code = '''
def main():
    print("Hello")

if __name__ == "__main__":
    main()
'''
        result = run_static_validation(code)
        assert result.available is True
        assert result.syntax_valid is True
        assert result.has_main_function is True
        assert result.passed is True

    def test_missing_main_fails(self):
        code = '''
def hello():
    print("Hello")

if __name__ == "__main__":
    hello()
'''
        result = run_static_validation(code)
        assert result.available is True
        assert result.syntax_valid is True
        assert result.has_main_function is False
        assert "Missing main() function" in result.structural_issues

    def test_syntax_error_detected(self):
        code = '''
def main(
    print("Hello")
'''
        result = run_static_validation(code)
        assert result.available is True
        assert result.syntax_valid is False
        assert result.passed is False

    def test_missing_guard_noted(self):
        code = '''
def main():
    print("Hello")

main()
'''
        result = run_static_validation(code)
        assert result.syntax_valid is True
        assert result.has_main_function is True
        assert "Missing if __name__" in str(result.structural_issues)


class TestVerdictComputation:
    """Tests for verdict computation logic."""

    def test_equivalent_when_all_pass(self):
        differential = DifferentialResult(
            available=True,
            passed=True,
            cobol_compiled=True,
            cobol_output="HELLO",
            python_output="HELLO",
            match_details="Match",
            error=None,
        )
        property_based = PropertyResult(
            available=True,
            passed=True,
            examples_run=50,
            failures=[],
            error=None,
        )
        llm_judge = JudgeResult(
            available=True,
            passed=True,
            score=4.5,
            semantic_equivalence=5,
            control_flow_match=4,
            data_type_safety=5,
            edge_case_handling=4,
            concerns=[],
            assessment="Good translation",
            error=None,
        )
        static = StaticResult(
            available=True,
            passed=True,
            has_main_function=True,
            syntax_valid=True,
            linter_issues=[],
            structural_issues=[],
            error=None,
        )

        scorecard = compute_verdict(differential, property_based, llm_judge, static)
        assert scorecard.verdict == "equivalent"
        assert scorecard.confidence > 0.8

    def test_likely_equivalent_without_differential(self):
        property_based = PropertyResult(
            available=True,
            passed=True,
            examples_run=50,
            failures=[],
            error=None,
        )
        llm_judge = JudgeResult(
            available=True,
            passed=True,
            score=4.0,
            semantic_equivalence=4,
            control_flow_match=4,
            data_type_safety=4,
            edge_case_handling=4,
            concerns=[],
            assessment="Good translation",
            error=None,
        )
        static = StaticResult(
            available=True,
            passed=True,
            has_main_function=True,
            syntax_valid=True,
            linter_issues=[],
            structural_issues=[],
            error=None,
        )

        scorecard = compute_verdict(None, property_based, llm_judge, static)
        assert scorecard.verdict == "likely_equivalent"

    def test_broken_when_differential_fails(self):
        differential = DifferentialResult(
            available=True,
            passed=False,
            cobol_compiled=True,
            cobol_output="HELLO",
            python_output="GOODBYE",
            match_details="Mismatch",
            error=None,
        )
        static = StaticResult(
            available=True,
            passed=False,
            has_main_function=False,
            syntax_valid=True,
            linter_issues=[],
            structural_issues=["Missing main"],
            error=None,
        )

        scorecard = compute_verdict(differential, None, None, static)
        assert scorecard.verdict == "broken"

    def test_unknown_when_no_validators(self):
        scorecard = compute_verdict(None, None, None, None)
        assert scorecard.verdict == "unknown"
        assert scorecard.confidence == 0.0
