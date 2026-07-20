from __future__ import annotations

import logging
from typing import Any, Literal

from pydantic import BaseModel, Field

from cobol_migrator.agent.state import AgentState
from cobol_migrator.models import get_structured_model

logger = logging.getLogger(__name__)


class Param(BaseModel):
    """A parameter in the I/O contract."""

    name: str = Field(description="Parameter name")
    type: Literal["int", "float", "str", "bool", "list", "dict"] = Field(
        description="Python type for the parameter"
    )
    description: str = Field(description="Brief description of what this parameter represents")


class IOContract(BaseModel):
    """The input/output contract for a COBOL program."""

    inputs: list[Param] = Field(
        default_factory=list,
        description="List of input parameters the program expects",
    )
    outputs: list[Param] = Field(
        default_factory=list,
        description="List of output values the program produces",
    )
    invariants: list[str] = Field(
        default_factory=list,
        description="Plain-English assertions the translation must uphold",
    )


class AnalyzeResult(BaseModel):
    """Structured output from the analyze LLM."""

    program_summary: str = Field(
        description="A 1-2 sentence summary of what the COBOL program does"
    )
    io_contract: IOContract = Field(
        description="The input/output contract for the program"
    )


ANALYZE_SYSTEM_PROMPT = """\
You are an expert COBOL analyst. Analyze the given COBOL program and extract:

1. **Program Summary**: A concise 1-2 sentence description of what this program does.

2. **I/O Contract**: 
   - **Inputs**: What data does this program read? (ACCEPT, files, WORKING-STORAGE)
   - **Outputs**: What does it produce? (DISPLAY, files, computed values)
   - **Invariants**: What must always be true? (business rules, constraints)

For simple DISPLAY programs, inputs may be empty and outputs describe the displayed text.

## COBOL Source
```cobol
{cobol_source}
```

Analyze this program and provide the structured output.
"""


def analyze(state: AgentState) -> dict[str, Any]:
    """
    Analyze the COBOL source to extract structure and I/O contract.
    
    Uses LLM to produce:
    - program_summary: Human-readable description
    - io_contract: Structured I/O specification for test generation
    """
    emit = state.get("emit", lambda t, p: None)
    cobol_source = state.get("cobol_source", "")

    cobol_preview = cobol_source[:30000]
    prompt = ANALYZE_SYSTEM_PROMPT.format(cobol_source=cobol_preview)

    try:
        model = get_structured_model("analyze", AnalyzeResult)
        result: AnalyzeResult = model.invoke(prompt)
    except Exception as e:
        logger.error(f"Analysis LLM call failed: {e}")
        result = AnalyzeResult(
            program_summary="COBOL program (analysis failed)",
            io_contract=IOContract(inputs=[], outputs=[], invariants=[]),
        )

    io_contract_dict = result.io_contract.model_dump()

    emit(
        "analysis_ready",
        {
            "program_summary": result.program_summary,
            "io_contract": io_contract_dict,
        },
    )

    logger.info(f"Analysis complete: {result.program_summary[:80]}")

    return {
        "program_summary": result.program_summary,
        "io_contract": io_contract_dict,
    }
