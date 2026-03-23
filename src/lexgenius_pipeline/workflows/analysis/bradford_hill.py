from __future__ import annotations

from dataclasses import dataclass

from lexgenius_pipeline.workflows.analysis.signal_detection import PRRResult, RORResult


@dataclass
class BradfordHillAssessment:
    strength: float
    consistency: float
    specificity: float
    temporality: float
    biological_gradient: float
    plausibility: float
    coherence: float
    overall_score: float
    meets_threshold: bool


def assess_bradford_hill(
    ror_result: RORResult | None = None,
    prr_result: PRRResult | None = None,
    case_count: int = 0,
    has_temporal_relationship: bool = False,
    has_dose_response: bool = False,
    has_biological_plausibility: bool = False,
    consistent_across_studies: bool = False,
    specific_to_exposure: bool = False,
) -> BradfordHillAssessment:
    """Assess Bradford Hill criteria for causality."""
    strength = 0.0
    if ror_result and ror_result.significant:
        strength = min(1.0, ror_result.ror / 5.0)
    elif prr_result and prr_result.significant:
        strength = min(1.0, prr_result.prr / 5.0)

    consistency = 1.0 if consistent_across_studies else 0.0
    specificity = 1.0 if specific_to_exposure else 0.0
    temporality = 1.0 if has_temporal_relationship else 0.0
    biological_gradient = 1.0 if has_dose_response else 0.0
    plausibility = 1.0 if has_biological_plausibility else 0.0
    coherence = min(1.0, case_count / 100) if case_count > 0 else 0.0

    weights = [0.25, 0.15, 0.10, 0.15, 0.10, 0.15, 0.10]
    scores = [strength, consistency, specificity, temporality, biological_gradient, plausibility, coherence]
    overall = sum(w * s for w, s in zip(weights, scores))

    return BradfordHillAssessment(
        strength=strength,
        consistency=consistency,
        specificity=specificity,
        temporality=temporality,
        biological_gradient=biological_gradient,
        plausibility=plausibility,
        coherence=coherence,
        overall_score=overall,
        meets_threshold=overall >= 0.6,
    )
