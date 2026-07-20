from __future__ import annotations

import logging
from dataclasses import asdict, dataclass
from typing import Literal

from cobol_migrator.validators.differential import DifferentialResult
from cobol_migrator.validators.llm_judge import JudgeResult
from cobol_migrator.validators.property_based import PropertyResult
from cobol_migrator.validators.static_analysis import StaticResult

logger = logging.getLogger(__name__)

Verdict = Literal["equivalent", "likely_equivalent", "partial", "broken", "unknown"]


@dataclass
class ValidationScorecard:
    """Combined validation results with overall verdict."""

    differential: dict | None
    property_based: dict | None
    llm_judge: dict | None
    static_analysis: dict | None
    verdict: Verdict
    confidence: float
    summary: str


def _result_to_dict(result: object | None) -> dict | None:
    """Convert a dataclass result to dict for JSON serialization."""
    if result is None:
        return None
    if hasattr(result, "__dataclass_fields__"):
        return asdict(result)
    return None


def compute_verdict(
    differential: DifferentialResult | None,
    property_based: PropertyResult | None,
    llm_judge: JudgeResult | None,
    static_analysis: StaticResult | None,
) -> ValidationScorecard:
    """
    Combine validator results into an overall verdict.
    
    Verdict levels:
    - equivalent: Strong confidence in correctness
    - likely_equivalent: Good confidence without ground truth
    - partial: Mixed signals, needs review
    - broken: Significant issues found
    - unknown: Insufficient validation data
    """
    scores = {
        "differential": 0.0,
        "property": 0.0,
        "judge": 0.0,
        "static": 0.0,
    }
    weights = {
        "differential": 0.35,
        "property": 0.25,
        "judge": 0.25,
        "static": 0.15,
    }
    available_count = 0
    summary_parts = []

    if differential is not None and differential.available:
        available_count += 1
        if differential.passed:
            scores["differential"] = 1.0
            summary_parts.append("Differential: PASS (outputs match)")
        else:
            scores["differential"] = 0.0
            summary_parts.append(f"Differential: FAIL ({differential.match_details[:100]})")
    elif differential is not None:
        summary_parts.append(f"Differential: N/A ({differential.match_details[:50]})")
        weights["differential"] = 0
    else:
        weights["differential"] = 0

    if property_based is not None and property_based.available:
        available_count += 1
        if property_based.passed:
            scores["property"] = 1.0
            summary_parts.append(
                f"Property: PASS ({property_based.examples_run} examples)"
            )
        else:
            scores["property"] = 0.0
            failures_str = "; ".join(property_based.failures[:2])
            summary_parts.append(f"Property: FAIL ({failures_str[:100]})")
    elif property_based is not None:
        summary_parts.append(f"Property: N/A ({property_based.error or 'unavailable'})")
        weights["property"] = 0
    else:
        weights["property"] = 0

    if llm_judge is not None and llm_judge.available:
        available_count += 1
        if llm_judge.score is not None:
            normalized_score = (llm_judge.score - 1) / 4.0
            scores["judge"] = normalized_score
            status = "PASS" if llm_judge.passed else "CONCERNS"
            summary_parts.append(f"LLM Judge: {status} ({llm_judge.score}/5)")
            if llm_judge.concerns:
                summary_parts.append(f"  Concerns: {llm_judge.concerns[0][:80]}")
        else:
            weights["judge"] = 0
    elif llm_judge is not None:
        summary_parts.append(f"LLM Judge: N/A ({llm_judge.error or 'unavailable'})")
        weights["judge"] = 0
    else:
        weights["judge"] = 0

    if static_analysis is not None and static_analysis.available:
        available_count += 1
        if static_analysis.passed:
            scores["static"] = 1.0
            summary_parts.append("Static: PASS")
        else:
            issues = static_analysis.structural_issues + static_analysis.linter_issues
            issue_str = "; ".join(issues[:2])
            scores["static"] = 0.3 if static_analysis.has_main_function else 0.0
            summary_parts.append(f"Static: ISSUES ({issue_str[:100]})")
    elif static_analysis is not None:
        summary_parts.append(f"Static: N/A ({static_analysis.error or 'unavailable'})")
        weights["static"] = 0
    else:
        weights["static"] = 0

    total_weight = sum(weights.values())
    if total_weight > 0:
        weighted_score = sum(
            scores[k] * weights[k] for k in scores
        ) / total_weight
    else:
        weighted_score = 0.0

    if available_count == 0:
        verdict: Verdict = "unknown"
        confidence = 0.0
    elif (
        differential is not None
        and differential.available
        and differential.passed
        and (property_based is None or property_based.passed)
        and (llm_judge is None or (llm_judge.passed and llm_judge.score and llm_judge.score >= 4.0))
    ):
        verdict = "equivalent"
        confidence = min(0.95, weighted_score)
    elif (
        (differential is None or not differential.available)
        and property_based is not None
        and property_based.passed
        and llm_judge is not None
        and llm_judge.passed
        and static_analysis is not None
        and static_analysis.passed
    ):
        verdict = "likely_equivalent"
        confidence = min(0.85, weighted_score)
    elif weighted_score >= 0.5:
        verdict = "partial"
        confidence = weighted_score
    else:
        verdict = "broken"
        confidence = 1.0 - weighted_score

    summary = "\n".join(summary_parts)

    return ValidationScorecard(
        differential=_result_to_dict(differential),
        property_based=_result_to_dict(property_based),
        llm_judge=_result_to_dict(llm_judge),
        static_analysis=_result_to_dict(static_analysis),
        verdict=verdict,
        confidence=round(confidence, 3),
        summary=summary,
    )
