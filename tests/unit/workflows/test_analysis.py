from __future__ import annotations

from datetime import datetime, timezone

import pytest

from lexgenius_pipeline.common.models import NormalizedRecord
from lexgenius_pipeline.common.types import RecordType
from lexgenius_pipeline.workflows.analysis.bradford_hill import assess_bradford_hill
from lexgenius_pipeline.workflows.analysis.dedup import deduplicate_records, find_near_duplicates
from lexgenius_pipeline.workflows.analysis.signal_detection import (
    calculate_bcpnn,
    calculate_prr,
    calculate_ror,
)


def _make_record(title: str, fingerprint: str, record_type: RecordType = RecordType.ADVERSE_EVENT) -> NormalizedRecord:
    return NormalizedRecord(
        title=title,
        summary="test summary",
        record_type=record_type,
        source_connector_id="test",
        source_label="Test Source",
        source_url="https://example.com",
        published_at=datetime(2024, 1, 1, tzinfo=timezone.utc),
        fingerprint=fingerprint,
    )


# --- signal_detection ---

def test_calculate_ror_known_values():
    result = calculate_ror(a=100, b=50, c=10, d=1000)
    assert result.ror == pytest.approx(200.0, rel=0.01)
    assert result.significant is True
    assert result.case_count == 100


def test_calculate_ror_zero_denominator():
    result = calculate_ror(a=10, b=0, c=5, d=100)
    assert result.ror == 0.0
    assert result.significant is False


def test_calculate_prr_known_values():
    result = calculate_prr(a=100, b=50, c=10, d=1000)
    assert result.prr > 2.0
    assert result.significant is True
    assert result.case_count == 100


def test_calculate_prr_zero_denominator():
    result = calculate_prr(a=0, b=0, c=5, d=100)
    assert result.prr == 0.0
    assert result.significant is False


def test_calculate_bcpnn_known_values():
    result = calculate_bcpnn(a=100, b=50, c=10, d=1000)
    assert result.ic > 0.0
    assert result.significant is True
    assert result.case_count == 100


def test_calculate_bcpnn_zero_input():
    result = calculate_bcpnn(a=0, b=0, c=0, d=0)
    assert result.ic == 0.0
    assert result.significant is False


# --- bradford_hill ---

def test_assess_bradford_hill_high_score():
    from lexgenius_pipeline.workflows.analysis.signal_detection import RORResult
    ror = RORResult(ror=4.0, ci_lower=2.5, ci_upper=6.0, significant=True, case_count=200)
    result = assess_bradford_hill(
        ror_result=ror,
        case_count=200,
        has_temporal_relationship=True,
        has_dose_response=True,
        has_biological_plausibility=True,
        consistent_across_studies=True,
        specific_to_exposure=True,
    )
    assert result.overall_score > 0.5
    assert result.strength > 0.0
    assert result.temporality == 1.0
    assert result.biological_gradient == 1.0


def test_assess_bradford_hill_low_score():
    result = assess_bradford_hill(case_count=0)
    assert result.overall_score == 0.0
    assert result.meets_threshold is False


# --- dedup ---

def test_deduplicate_records_removes_dupes():
    records = [
        _make_record("Title A", "fp1"),
        _make_record("Title B", "fp2"),
        _make_record("Title A dup", "fp1"),  # same fingerprint
    ]
    unique = deduplicate_records(records)
    assert len(unique) == 2
    fingerprints = {r.fingerprint for r in unique}
    assert fingerprints == {"fp1", "fp2"}


def test_deduplicate_records_no_dupes():
    records = [
        _make_record("Title A", "fp1"),
        _make_record("Title B", "fp2"),
    ]
    unique = deduplicate_records(records)
    assert len(unique) == 2


def test_find_near_duplicates_detects_similar():
    records = [
        _make_record("FDA Warning on Drug X Side Effects", "fp1"),
        _make_record("FDA Warning on Drug X Side Effect", "fp2"),  # very similar
        _make_record("Completely Different Topic", "fp3"),
    ]
    pairs = find_near_duplicates(records, threshold=0.85)
    assert (0, 1) in pairs
    assert (0, 2) not in pairs


def test_find_near_duplicates_no_matches():
    records = [
        _make_record("Apple banana cherry", "fp1"),
        _make_record("Unrelated document here", "fp2"),
    ]
    pairs = find_near_duplicates(records, threshold=0.85)
    assert pairs == []
