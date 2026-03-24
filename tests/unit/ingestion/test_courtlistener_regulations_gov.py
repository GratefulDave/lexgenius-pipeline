"""Tests for CourtListener and Regulations.gov connectors (PR #3 fixes)."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from lexgenius_pipeline.common.errors import AuthenticationError, ConnectorError, RateLimitError
from lexgenius_pipeline.common.models import IngestionQuery, Watermark
from lexgenius_pipeline.common.types import HealthStatus
from lexgenius_pipeline.ingestion.judicial.courtlistener import (
    CourtListenerConnector,
    _parse_cl_date,
)
from lexgenius_pipeline.ingestion.judicial.regulations_gov import (
    RegulationsGovConnector,
    _parse_reg_date,
    _redact_api_key,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _mock_client(response):
    """Build an AsyncMock httpx client context manager returning `response`."""
    mock_client = AsyncMock()
    mock_client.get = AsyncMock(return_value=response)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    return mock_client


def _json_response(data, status_code=200):
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = data
    resp.headers = {}
    resp.url = "https://example.com"
    return resp


def _status_response(status_code, headers=None):
    resp = MagicMock()
    resp.status_code = status_code
    resp.headers = headers or {}
    resp.url = "https://example.com"
    return resp


# ---------------------------------------------------------------------------
# _parse_cl_date
# ---------------------------------------------------------------------------


def test_parse_cl_date_valid_iso():
    dt = _parse_cl_date("2025-03-15T12:00:00Z")
    assert dt.year == 2025
    assert dt.month == 3
    assert dt.tzinfo == timezone.utc


def test_parse_cl_date_none_returns_now():
    dt = _parse_cl_date(None)
    assert dt.tzinfo == timezone.utc


def test_parse_cl_date_no_redundant_replace():
    """After .astimezone(timezone.utc) the tzinfo must already be UTC."""
    dt = _parse_cl_date("2025-06-01")
    assert dt.tzinfo == timezone.utc


def test_parse_cl_date_malformed_warns_and_falls_back(caplog):
    import structlog.testing

    with structlog.testing.capture_logs() as logs:
        dt = _parse_cl_date("not-a-date")
    assert dt.tzinfo == timezone.utc
    assert any("malformed_date" in log.get("event", "") for log in logs)


# ---------------------------------------------------------------------------
# _parse_reg_date
# ---------------------------------------------------------------------------


def test_parse_reg_date_valid_iso():
    dt = _parse_reg_date("2024-11-01T00:00:00Z")
    assert dt.year == 2024
    assert dt.month == 11
    assert dt.tzinfo == timezone.utc


def test_parse_reg_date_none_returns_now():
    dt = _parse_reg_date(None)
    assert dt.tzinfo == timezone.utc


def test_parse_reg_date_malformed_warns_and_falls_back(caplog):
    import structlog.testing

    with structlog.testing.capture_logs() as logs:
        dt = _parse_reg_date("garbage-date")
    assert dt.tzinfo == timezone.utc
    assert any("malformed_date" in log.get("event", "") for log in logs)


# ---------------------------------------------------------------------------
# _redact_api_key
# ---------------------------------------------------------------------------


def test_redact_api_key_replaces_key():
    url = "https://api.regulations.gov/v4/documents?api_key=secret123&foo=bar"
    result = _redact_api_key(url, "secret123")
    assert "secret123" not in result
    assert "***" in result


def test_redact_api_key_no_key_passthrough():
    url = "https://api.regulations.gov/v4/documents?foo=bar"
    assert _redact_api_key(url, None) == url


# ---------------------------------------------------------------------------
# CourtListenerConnector — HTTP 401/403 → AuthenticationError
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_courtlistener_401_raises_auth_error():
    resp = _status_response(401)
    client = _mock_client(resp)
    with patch(
        "lexgenius_pipeline.ingestion.judicial.courtlistener.create_http_client",
        return_value=client,
    ):
        connector = CourtListenerConnector()
        with pytest.raises(AuthenticationError) as exc_info:
            await connector.fetch_latest(IngestionQuery(query_terms=["test"]))
    assert exc_info.value.connector_id == "judicial.courtlistener"


@pytest.mark.asyncio
async def test_courtlistener_403_raises_auth_error():
    resp = _status_response(403)
    client = _mock_client(resp)
    with patch(
        "lexgenius_pipeline.ingestion.judicial.courtlistener.create_http_client",
        return_value=client,
    ):
        connector = CourtListenerConnector()
        with pytest.raises(AuthenticationError):
            await connector.fetch_latest(IngestionQuery(query_terms=["test"]))


# ---------------------------------------------------------------------------
# CourtListenerConnector — HTTP 429 → RateLimitError with retry_after
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_courtlistener_429_raises_rate_limit_error():
    resp = _status_response(429, headers={"Retry-After": "30"})
    client = _mock_client(resp)
    with patch(
        "lexgenius_pipeline.ingestion.judicial.courtlistener.create_http_client",
        return_value=client,
    ):
        connector = CourtListenerConnector()
        with pytest.raises(RateLimitError) as exc_info:
            await connector.fetch_latest(IngestionQuery(query_terms=["test"]))
    assert exc_info.value.retry_after == 30.0


@pytest.mark.asyncio
async def test_courtlistener_429_default_retry_after():
    resp = _status_response(429, headers={})
    client = _mock_client(resp)
    with patch(
        "lexgenius_pipeline.ingestion.judicial.courtlistener.create_http_client",
        return_value=client,
    ):
        connector = CourtListenerConnector()
        with pytest.raises(RateLimitError) as exc_info:
            await connector.fetch_latest(IngestionQuery(query_terms=["test"]))
    assert exc_info.value.retry_after == 60.0


# ---------------------------------------------------------------------------
# CourtListenerConnector — malformed JSON → ConnectorError
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_courtlistener_bad_json_raises_connector_error():
    resp = MagicMock()
    resp.status_code = 200
    resp.headers = {}
    resp.json.side_effect = json.JSONDecodeError("Expecting value", "", 0)
    client = _mock_client(resp)
    with patch(
        "lexgenius_pipeline.ingestion.judicial.courtlistener.create_http_client",
        return_value=client,
    ):
        connector = CourtListenerConnector()
        with pytest.raises(ConnectorError) as exc_info:
            await connector.fetch_latest(IngestionQuery(query_terms=["test"]))
    assert exc_info.value.connector_id == "judicial.courtlistener"


# ---------------------------------------------------------------------------
# CourtListenerConnector — watermark filtering
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_courtlistener_watermark_filters_old_records():
    api_response = {
        "results": [
            {
                "caseName": "Old Case",
                "dateFiled": "2020-01-01",
                "absoluteUrl": "/old/",
                "court": "dcd",
                "snippet": "",
            },
            {
                "caseName": "New Case",
                "dateFiled": "2025-06-01",
                "absoluteUrl": "/new/",
                "court": "dcd",
                "snippet": "",
            },
        ]
    }
    resp = _json_response(api_response)
    client = _mock_client(resp)
    watermark = Watermark(
        scope_key="test",
        connector_id="judicial.courtlistener",
        last_fetched_at=datetime(2024, 1, 1, tzinfo=timezone.utc),
        last_record_date=datetime(2024, 1, 1, tzinfo=timezone.utc),
    )
    with patch(
        "lexgenius_pipeline.ingestion.judicial.courtlistener.create_http_client",
        return_value=client,
    ):
        connector = CourtListenerConnector()
        records = await connector.fetch_latest(
            IngestionQuery(query_terms=["test"]), watermark=watermark
        )
    assert len(records) == 1
    assert records[0].title == "New Case"


# ---------------------------------------------------------------------------
# CourtListenerConnector — successful fetch
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_courtlistener_fetch_latest_success():
    api_response = {
        "results": [
            {
                "caseName": "Doe v. Corp",
                "dateFiled": "2025-03-01",
                "absoluteUrl": "/opinion/123/",
                "court": "ca9",
                "snippet": "Important ruling",
            }
        ]
    }
    resp = _json_response(api_response)
    client = _mock_client(resp)
    with patch(
        "lexgenius_pipeline.ingestion.judicial.courtlistener.create_http_client",
        return_value=client,
    ):
        connector = CourtListenerConnector()
        records = await connector.fetch_latest(IngestionQuery(query_terms=["corp"]))
    assert len(records) == 1
    assert records[0].title == "Doe v. Corp"
    assert records[0].metadata["court"] == "ca9"
    assert records[0].fingerprint


# ---------------------------------------------------------------------------
# CourtListenerConnector — no query terms
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_courtlistener_no_query_terms_returns_empty():
    connector = CourtListenerConnector()
    records = await connector.fetch_latest(IngestionQuery())
    assert records == []


# ---------------------------------------------------------------------------
# RegulationsGovConnector — HTTP 401/403 → AuthenticationError
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_regulations_gov_401_raises_auth_error():
    resp = _status_response(401)
    client = _mock_client(resp)
    with patch(
        "lexgenius_pipeline.ingestion.judicial.regulations_gov.create_http_client",
        return_value=client,
    ):
        connector = RegulationsGovConnector()
        with pytest.raises(AuthenticationError) as exc_info:
            await connector.fetch_latest(IngestionQuery(query_terms=["test"]))
    assert exc_info.value.connector_id == "judicial.regulations_gov"


@pytest.mark.asyncio
async def test_regulations_gov_403_raises_auth_error():
    resp = _status_response(403)
    client = _mock_client(resp)
    with patch(
        "lexgenius_pipeline.ingestion.judicial.regulations_gov.create_http_client",
        return_value=client,
    ):
        connector = RegulationsGovConnector()
        with pytest.raises(AuthenticationError):
            await connector.fetch_latest(IngestionQuery(query_terms=["test"]))


# ---------------------------------------------------------------------------
# RegulationsGovConnector — HTTP 429 → RateLimitError
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_regulations_gov_429_raises_rate_limit_error():
    resp = _status_response(429, headers={"Retry-After": "120"})
    client = _mock_client(resp)
    with patch(
        "lexgenius_pipeline.ingestion.judicial.regulations_gov.create_http_client",
        return_value=client,
    ):
        connector = RegulationsGovConnector()
        with pytest.raises(RateLimitError) as exc_info:
            await connector.fetch_latest(IngestionQuery(query_terms=["test"]))
    assert exc_info.value.retry_after == 120.0


# ---------------------------------------------------------------------------
# RegulationsGovConnector — malformed JSON → ConnectorError
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_regulations_gov_bad_json_raises_connector_error():
    resp = MagicMock()
    resp.status_code = 200
    resp.headers = {}
    resp.json.side_effect = json.JSONDecodeError("Expecting value", "", 0)
    client = _mock_client(resp)
    with patch(
        "lexgenius_pipeline.ingestion.judicial.regulations_gov.create_http_client",
        return_value=client,
    ):
        connector = RegulationsGovConnector()
        with pytest.raises(ConnectorError) as exc_info:
            await connector.fetch_latest(IngestionQuery(query_terms=["test"]))
    assert exc_info.value.connector_id == "judicial.regulations_gov"


# ---------------------------------------------------------------------------
# RegulationsGovConnector — watermark filtering
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_regulations_gov_watermark_filters_old_records():
    api_response = {
        "data": [
            {
                "id": "old-001",
                "attributes": {
                    "title": "Old Rule",
                    "postedDate": "2020-06-01T00:00:00Z",
                    "documentType": "Rule",
                    "objectId": "old-001",
                },
            },
            {
                "id": "new-002",
                "attributes": {
                    "title": "New Rule",
                    "postedDate": "2025-07-01T00:00:00Z",
                    "documentType": "Rule",
                    "objectId": "new-002",
                },
            },
        ]
    }
    resp = _json_response(api_response)
    client = _mock_client(resp)
    watermark = Watermark(
        scope_key="test",
        connector_id="judicial.regulations_gov",
        last_fetched_at=datetime(2024, 1, 1, tzinfo=timezone.utc),
        last_record_date=datetime(2024, 1, 1, tzinfo=timezone.utc),
    )
    with patch(
        "lexgenius_pipeline.ingestion.judicial.regulations_gov.create_http_client",
        return_value=client,
    ):
        connector = RegulationsGovConnector()
        records = await connector.fetch_latest(
            IngestionQuery(query_terms=["rule"]), watermark=watermark
        )
    assert len(records) == 1
    assert records[0].title == "New Rule"


# ---------------------------------------------------------------------------
# RegulationsGovConnector — health_check includes API key
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_regulations_gov_health_check_includes_api_key():
    """Verify health_check passes api_key so it does not get a 403."""
    resp = _status_response(200)
    client = _mock_client(resp)

    from lexgenius_pipeline.settings import Settings

    settings = Settings(regulations_gov_api_key="test-key-abc")

    with patch(
        "lexgenius_pipeline.ingestion.judicial.regulations_gov.create_http_client",
        return_value=client,
    ):
        connector = RegulationsGovConnector(settings=settings)
        status = await connector.health_check()

    assert status == HealthStatus.HEALTHY
    call_kwargs = client.get.call_args
    params = call_kwargs[1].get("params", call_kwargs[0][1] if len(call_kwargs[0]) > 1 else {})
    assert params.get("api_key") == "test-key-abc"


# ---------------------------------------------------------------------------
# RegulationsGovConnector — successful fetch
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_regulations_gov_fetch_latest_success():
    api_response = {
        "data": [
            {
                "id": "FDA-2025-N-0001",
                "attributes": {
                    "title": "New Drug Safety Guidance",
                    "postedDate": "2025-04-01T00:00:00Z",
                    "documentType": "Notice",
                    "objectId": "FDA-2025-N-0001",
                },
            }
        ]
    }
    resp = _json_response(api_response)
    client = _mock_client(resp)
    with patch(
        "lexgenius_pipeline.ingestion.judicial.regulations_gov.create_http_client",
        return_value=client,
    ):
        connector = RegulationsGovConnector()
        records = await connector.fetch_latest(IngestionQuery(query_terms=["drug safety"]))
    assert len(records) == 1
    assert records[0].title == "New Drug Safety Guidance"
    assert "Notice" in records[0].summary
    assert records[0].fingerprint


# ---------------------------------------------------------------------------
# RegulationsGovConnector — no query terms
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_regulations_gov_no_query_terms_returns_empty():
    connector = RegulationsGovConnector()
    records = await connector.fetch_latest(IngestionQuery())
    assert records == []
