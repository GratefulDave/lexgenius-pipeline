from __future__ import annotations

from difflib import SequenceMatcher

from lexgenius_pipeline.common.models import NormalizedRecord


def deduplicate_records(records: list[NormalizedRecord]) -> list[NormalizedRecord]:
    """Remove records with duplicate fingerprints, keeping first occurrence."""
    seen: set[str] = set()
    unique: list[NormalizedRecord] = []
    for record in records:
        if record.fingerprint not in seen:
            seen.add(record.fingerprint)
            unique.append(record)
    return unique


def find_near_duplicates(
    records: list[NormalizedRecord],
    threshold: float = 0.85,
) -> list[tuple[int, int]]:
    """Find pairs of indices whose titles are near-duplicates."""
    pairs: list[tuple[int, int]] = []
    for i in range(len(records)):
        for j in range(i + 1, len(records)):
            ratio = SequenceMatcher(None, records[i].title.lower(), records[j].title.lower()).ratio()
            if ratio >= threshold:
                pairs.append((i, j))
    return pairs
