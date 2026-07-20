from __future__ import annotations

import logging
from dataclasses import dataclass

from pydantic import BaseModel, Field

from cobol_migrator.models import get_structured_model

logger = logging.getLogger(__name__)


class JudgeAssessment(BaseModel):
    """Structured output from the LLM judge."""

    semantic_equivalence: int = Field(
        ge=1, le=5,
        description="1-5 score: do COBOL and Python compute the same thing?"
    )
    control_flow_match: int = Field(
        ge=1, le=5,
        description="1-5 score: do control flow structures translate correctly?"
    )
    data_type_safety: int = Field(
        ge=1, le=5,
        description="1-5 score: are data types handled correctly (no overflow/rounding issues)?"
    )
    edge_case_handling: int = Field(
        ge=1, le=5,
        description="1-5 score: does the Python handle edge cases the COBOL would?"
    )
    concerns: list[str] = Field(
        description="List of specific concerns or potential issues found"
    )
    overall_assessment: str = Field(
        description="Brief overall assessment of the translation quality"
    )


@dataclass
class JudgeResult:
    """Result of LLM-as-judge validation."""

    available: bool
    passed: bool | None
    score: float | None
    semantic_equivalence: int | None
    control_flow_match: int | None
    data_type_safety: int | None
    edge_case_handling: int | None
    concerns: list[str]
    assessment: str | None
    error: str | None


JUDGE_PROMPT = """\
You are an expert code reviewer evaluating a COBOL to Python translation.
Your task is to assess whether the Python code is semantically equivalent to the COBOL.

## Original COBOL
```cobol
{cobol_source}
```

## Translated Python
```python
{python_code}
```

## Evaluation Criteria

Score each criterion from 1 (poor) to 5 (excellent):

1. **Semantic Equivalence**: Do both programs compute the same thing for all inputs?
   - 5: Provably equivalent
   - 4: Very likely equivalent
   - 3: Mostly equivalent with minor differences
   - 2: Some differences in behavior
   - 1: Significantly different behavior

2. **Control Flow Match**: Are loops, conditionals, and program structure preserved?
   - Consider COBOL's PERFORM, IF/ELSE, EVALUATE vs Python equivalents

3. **Data Type Safety**: Are numeric types handled correctly?
   - COBOL's fixed-point decimals vs Python floats/Decimals
   - Rounding behavior, overflow handling
   - String/alphanumeric field handling

4. **Edge Case Handling**: Would both handle edge cases the same way?
   - Empty inputs, maximum values, special characters

List any specific concerns you find. Be critical but fair.
"""


def run_llm_judge_validation(
    cobol_source: str,
    python_code: str,
) -> JudgeResult:
    """
    Run LLM-as-judge validation.
    
    Asks a capable LLM to assess semantic equivalence between COBOL and Python.
    """
    prompt = JUDGE_PROMPT.format(
        cobol_source=cobol_source[:8000],
        python_code=python_code[:8000],
    )

    try:
        model = get_structured_model("judge", JudgeAssessment)
        result: JudgeAssessment = model.invoke(prompt)

        avg_score = (
            result.semantic_equivalence
            + result.control_flow_match
            + result.data_type_safety
            + result.edge_case_handling
        ) / 4.0

        passed = avg_score >= 3.5

        return JudgeResult(
            available=True,
            passed=passed,
            score=round(avg_score, 2),
            semantic_equivalence=result.semantic_equivalence,
            control_flow_match=result.control_flow_match,
            data_type_safety=result.data_type_safety,
            edge_case_handling=result.edge_case_handling,
            concerns=result.concerns,
            assessment=result.overall_assessment,
            error=None,
        )

    except Exception as e:
        logger.exception(f"LLM judge validation failed: {e}")
        return JudgeResult(
            available=False,
            passed=None,
            score=None,
            semantic_equivalence=None,
            control_flow_match=None,
            data_type_safety=None,
            edge_case_handling=None,
            concerns=[],
            assessment=None,
            error=str(e),
        )
