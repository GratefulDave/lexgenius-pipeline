from __future__ import annotations

from datetime import datetime, timezone

import pytest

from lexgenius_pipeline.common.models import NormalizedRecord, Watermark
from lexgenius_pipeline.common.types import RecordType


def _now() -> datetime:
    return datetime.now(tz=timezone.utc)


class TestNormalizedRecord:
    def test_required_fields(self):
        record = NormalizedRecord(
            title="Test Title",
            summary="Test Summary",
            record_type=RecordType.RECALL,
            source_connector_id="fda",
            source_label="FDA Recalls",
            source_url="https://example.com/recall/1",
            published_at=_now(),
            fingerprint="abc123",
        )
        assert record.title == "Test Title"
        assert record.record_type == RecordType.RECALL
        assert record.confidence == 1.0
        assert record.citation_url is None
        assert record.metadata == {}
        assert record.raw_payload == {}

    def test_optional_fields(self):
        record = NormalizedRecord(
            title="T",
            summary="S",
            record_type=RecordType.FILING,
            source_connector_id="sec",
            source_label="SEC",
            source_url="https://example.com",
            published_at=_now(),
            fingerprint="xyz",
            citation_url="https://example.com/cite",
            confidence=0.9,
            metadata={"key": "value"},
            raw_payload={"raw": True},
        )
        assert record.citation_url == "https://example.com/cite"
        assert record.confidence == 0.9
        assert record.metadata == {"key": "value"}

    def test_record_type_enum_values(self):
        for rt in RecordType:
            record = NormalizedRecord(
                title="T",
                summary="S",
                record_type=rt,
                source_connector_id="c",
                source_label="L",
                source_url="https://x.com",
                published_at=_now(),
                fingerprint=rt.value,
            )
            assert record.record_type == rt


class TestWatermark:
    def test_required_fields(self):
        now = _now()
        wm = Watermark(scope_key="fda:recalls", connector_id="fda", last_fetched_at=now)
        assert wm.scope_key == "fda:recalls"
        assert wm.connector_id == "fda"
        assert wm.last_fetched_at == now
        assert wm.last_record_date is None

    def test_with_last_record_date(self):
        now = _now()
        wm = Watermark(
            scope_key="sec:filings",
            connector_id="sec",
            last_fetched_at=now,
            last_record_date=now,
        )
        assert wm.last_record_date == now
