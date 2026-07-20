from __future__ import annotations

from cobol_migrator.validators.differential import run_differential_validation
from cobol_migrator.validators.llm_judge import run_llm_judge_validation
from cobol_migrator.validators.property_based import run_property_validation
from cobol_migrator.validators.static_analysis import run_static_validation
from cobol_migrator.validators.verdict import compute_verdict

__all__ = [
    "run_differential_validation",
    "run_property_validation",
    "run_llm_judge_validation",
    "run_static_validation",
    "compute_verdict",
]
