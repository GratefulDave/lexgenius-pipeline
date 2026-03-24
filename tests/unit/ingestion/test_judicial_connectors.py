"""Tests for judicial connectors: JPML, CourtListener Dockets, NCSC, Lead Counsel."""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from lexgenius_pipeline.common.models import IngestionQuery, NormalizedRecord, Watermark
from lexgenius_pipeline.common.types import HealthStatus, RecordType, SourceTier
from lexgenius_pipeline.ingestion.judicial.courtlistener_dockets import (
    CourtListenerDocketsConnector,
    _parse_cl_date,
)
from lexgenius_pipeline.ingestion.judicial.jpml import (
    JPMLTransferOrdersConnector,
    _extract_mdl_number,
    _extract_transfer_orders_from_html,
    _parse_jpml_date,
)
from lexgenius_pipeline.ingestion.judicial.lead_counsel import (
    LeadCounselConnector,
    _extract_counsel_from_html,
    _parse_date,
)
from lexgenius_pipeline.ingestion.judicial.ncsc import (
    NCSCStatisticsConnector,
    _extract_reports_from_html,
    _parse_ncsc_date,
)
from lexgenius_pipeline.ingestion.registry import ConnectorRegistry


# ---------------------------------------------------------------------------
# Instantiation
# ---------------------------------------------------------------------------


def test_jpml_instantiation():
    connector = JPMLTransferOrdersConnector()
    assert connector is not None


def test_courtlistener_dockets_instantiation():
    connector = CourtListenerDocketsConnector()
    assert connector is not None


def test_ncsc_instantiation():
    connector = NCSCStatisticsConnector()
    assert connector is not None


def test_lead_counsel_instantiation():
    connector = LeadCounselConnector()
    assert connector is not None


# ---------------------------------------------------------------------------
# connector_id
# ---------------------------------------------------------------------------


def test_jpml_connector_id():
    assert JPMLTransferOrdersConnector.connector_id == "judicial.jpml.transfer_orders"


def test_courtlistener_dockets_connector_id():
    assert CourtListenerDocketsConnector.connector_id == "judicial.courtlistener.dockets"


def test_ncsc_connector_id():
    assert NCSCStatisticsConnector.connector_id == "judicial.ncsc.statistics"


def test_lead_counsel_connector_id():
    assert LeadCounselConnector.connector_id == "judicial.lead_counsel"


# ---------------------------------------------------------------------------
# source_tier
# ---------------------------------------------------------------------------


def test_all_new_connectors_have_judicial_tier():
    for cls in (
        JPMLTransferOrdersConnector,
        CourtListenerDocketsConnector,
        NCSCStatisticsConnector,
        LeadCounselConnector,
    ):
        assert cls.source_tier == SourceTier.JUDICIAL, f"{cls.__name__} wrong tier"


# ---------------------------------------------------------------------------
# source_label
# ---------------------------------------------------------------------------


def test_jpml_source_label():
    assert JPMLTransferOrdersConnector.source_label == "JPML Transfer Orders"


def test_courtlistener_dockets_source_label():
    assert CourtListenerDocketsConnector.source_label == "CourtListener Dockets"


def test_ncsc_source_label():
    assert NCSCStatisticsConnector.source_label == "NCSC Court Statistics"


def test_lead_counsel_source_label():
    assert LeadCounselConnector.source_label == "MDL Lead Counsel"


# ---------------------------------------------------------------------------
# supports_incremental
# ---------------------------------------------------------------------------


def test_all_new_connectors_support_incremental():
    for cls in (
        JPMLTransferOrdersConnector,
        CourtListenerDocketsConnector,
        NCSCStatisticsConnector,
        LeadCounselConnector,
    ):
        assert cls.supports_incremental is True, f"{cls.__name__} should be incremental"


# ---------------------------------------------------------------------------
# __repr__
# ---------------------------------------------------------------------------


def test_jpml_repr():
    connector = JPMLTransferOrdersConnector()
    assert "JPMLTransferOrdersConnector" in repr(connector)
    assert "judicial.jpml.transfer_orders" in repr(connector)


def test_courtlistener_dockets_repr():
    connector = CourtListenerDocketsConnector()
    assert "CourtListenerDocketsConnector" in repr(connector)


# ---------------------------------------------------------------------------
# Date parsing helpers
# ---------------------------------------------------------------------------


def test_parse_jpml_date_full():
    dt = _parse_jpml_date("January 15, 2025")
    assert dt.year == 2025
    assert dt.month == 1
    assert dt.day == 15
    assert dt.tzinfo == timezone.utc


def test_parse_jpml_date_slash():
    dt = _parse_jpml_date("03/15/2024")
    assert dt.year == 2024
    assert dt.month == 3


def test_parse_jpml_date_iso():
    dt = _parse_jpml_date("2025-06-01")
    assert dt.year == 2025
    assert dt.month == 6


def test_parse_jpml_date_month_year():
    dt = _parse_jpml_date("March 2025")
    assert dt.year == 2025
    assert dt.month == 3


def test_parse_jpml_date_empty():
    dt = _parse_jpml_date(None)
    assert dt.tzinfo == timezone.utc


def test_parse_jpml_date_garbage():
    dt = _parse_jpml_date("not a date at all")
    assert dt.tzinfo == timezone.utc


def test_parse_cl_date_iso():
    dt = _parse_cl_date("2025-03-15T12:00:00Z")
    assert dt.year == 2025
    assert dt.month == 3
    assert dt.tzinfo == timezone.utc


def test_parse_cl_date_none():
    dt = _parse_cl_date(None)
    assert dt.tzinfo == timezone.utc


def test_parse_ncsc_date_year_only():
    dt = _parse_ncsc_date("2023")
    assert dt.year == 2023
    assert dt.month == 1
    assert dt.day == 1


def test_parse_ncsc_date_embedded_year():
    dt = _parse_ncsc_date("Report from 2024 edition")
    assert dt.year == 2024


def test_parse_lead_counsel_date_iso():
    dt = _parse_date("2025-01-20T10:30:00+00:00")
    assert dt.year == 2025
    assert dt.month == 1


def test_parse_lead_counsel_date_us_format():
    dt = _parse_date("December 5, 2024")
    assert dt.year == 2024
    assert dt.month == 12


# ---------------------------------------------------------------------------
# MDL number extraction
# ---------------------------------------------------------------------------


def test_extract_mdl_number_standard():
    assert _extract_mdl_number("MDL No. 3100") == "3100"


def test_extract_mdl_number_dash():
    assert _extract_mdl_number("MDL-2741") == "2741"


def test_extract_mdl_number_no_match():
    assert _extract_mdl_number("no mdl here") == ""


def test_extract_mdl_number_case_insensitive():
    assert _extract_mdl_number("mdl no 1234") == "1234"


# ---------------------------------------------------------------------------
# HTML parsing — JPML transfer orders
# ---------------------------------------------------------------------------

_JPML_HTML = """
<table>
<tr><td>MDL No. 3100</td><td><a href="/mdl/3100">In re: Zantac Products Liability</a></td>
<td>Southern District of Florida</td><td>January 15, 2025</td></tr>
<tr><td>MDL-2741</td><td>In re: Roundup Products Liability</td>
<td>Northern District of California</td><td>October 3, 2016</td></tr>
</table>
"""


def test_extract_transfer_orders_from_html():
    orders = _extract_transfer_orders_from_html(_JPML_HTML)
    assert len(orders) == 2
    assert orders[0]["mdl_number"] == "3100"
    assert orders[1]["mdl_number"] == "2741"


def test_extract_transfer_orders_has_district():
    orders = _extract_transfer_orders_from_html(_JPML_HTML)
    assert "Florida" in orders[0]["district"] or "Southern" in orders[0]["district"]


def test_extract_transfer_orders_has_date():
    orders = _extract_transfer_orders_from_html(_JPML_HTML)
    assert "2025" in orders[0]["date"]


def test_extract_transfer_orders_empty_html():
    orders = _extract_transfer_orders_from_html("<html><body>No data</body></html>")
    assert orders == []


def test_extract_transfer_orders_fallback_no_table():
    html = "<p>The panel transferred MDL No. 4500 on March 1, 2025 to the court.</p>"
    orders = _extract_transfer_orders_from_html(html)
    assert len(orders) == 1
    assert orders[0]["mdl_number"] == "4500"


# ---------------------------------------------------------------------------
# HTML parsing — NCSC reports
# ---------------------------------------------------------------------------

_NCSC_HTML = """
<div>
<a href="/topics/court-statistics/2024-report.pdf">Court Statistics 2024 Annual Report</a>
<span>Published: January 2024</span>
</div>
<div>
<a href="/topics/court-statistics/tort-filings">State Tort Filing Trends</a>
<span>Updated: March 15, 2025</span>
</div>
"""


def test_extract_reports_from_html():
    reports = _extract_reports_from_html(_NCSC_HTML)
    assert len(reports) >= 1


def test_extract_reports_deduplicates():
    html = _NCSC_HTML + _NCSC_HTML
    reports = _extract_reports_from_html(html)
    urls = [r["url"] for r in reports]
    assert len(urls) == len(set(urls))


# ---------------------------------------------------------------------------
# HTML parsing — Lead counsel
# ---------------------------------------------------------------------------

_COUNSEL_HTML = """
<div>
<p>The court appointed John Smith as lead counsel for MDL No. 3100 on January 10, 2025.</p>
<p>Jane Doe was designated as liaison counsel for MDL-2741.</p>
<p>The Plaintiffs' Steering Committee in MDL No. 3200 includes five members.</p>
<p>Unrelated paragraph about court procedures.</p>
</div>
"""


def test_extract_counsel_from_html():
    entries = _extract_counsel_from_html(_COUNSEL_HTML)
    assert len(entries) >= 2


def test_extract_counsel_appointment_types():
    entries = _extract_counsel_from_html(_COUNSEL_HTML)
    types = {e["appointment_type"] for e in entries}
    assert "lead_counsel" in types or "liaison_counsel" in types or "psc_member" in types


def test_extract_counsel_mdl_numbers():
    entries = _extract_counsel_from_html(_COUNSEL_HTML)
    mdl_numbers = {e["mdl_number"] for e in entries if e["mdl_number"]}
    assert len(mdl_numbers) >= 1


# ---------------------------------------------------------------------------
# fetch_latest with mocked HTTP — JPML
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_jpml_fetch_latest_parses_html():
    html = """<table>
    <tr><td>MDL No. 5000</td><td><a href="/mdl/5000">In re: Test Product</a></td>
    <td>District of Test</td><td>February 1, 2025</td></tr>
    </table>"""

    mock_response = MagicMock()
    mock_response.text = html
    mock_response.status_code = 200
    mock_response.raise_for_status = MagicMock()

    mock_client = AsyncMock()
    mock_client.get = AsyncMock(return_value=mock_response)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    with patch(
        "lexgenius_pipeline.ingestion.judicial.jpml.create_http_client",
        return_value=mock_client,
    ):
        connector = JPMLTransferOrdersConnector()
        records = await connector.fetch_latest(IngestionQuery(query_terms=["Test"]))

    assert len(records) == 1
    assert records[0].record_type == RecordType.FILING
    assert "MDL-5000" in records[0].title
    assert records[0].source_connector_id == "judicial.jpml.transfer_orders"
    assert records[0].fingerprint


@pytest.mark.asyncio
async def test_jpml_fetch_latest_empty_with_no_match():
    mock_response = MagicMock()
    mock_response.text = "<html><body>Nothing here</body></html>"
    mock_response.status_code = 200
    mock_response.raise_for_status = MagicMock()

    mock_client = AsyncMock()
    mock_client.get = AsyncMock(return_value=mock_response)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    with patch(
        "lexgenius_pipeline.ingestion.judicial.jpml.create_http_client",
        return_value=mock_client,
    ):
        connector = JPMLTransferOrdersConnector()
        records = await connector.fetch_latest(IngestionQuery(query_terms=["zantac"]))

    assert records == []


@pytest.mark.asyncio
async def test_jpml_fetch_latest_watermark_filtering():
    html = """<table>
    <tr><td>MDL No. 5001</td><td>Old Case</td><td>Old District</td><td>January 1, 2020</td></tr>
    <tr><td>MDL No. 5002</td><td>New Case</td><td>New District</td><td>March 1, 2025</td></tr>
    </table>"""

    mock_response = MagicMock()
    mock_response.text = html
    mock_response.status_code = 200
    mock_response.raise_for_status = MagicMock()

    mock_client = AsyncMock()
    mock_client.get = AsyncMock(return_value=mock_response)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    watermark = Watermark(
        scope_key="test",
        connector_id="judicial.jpml.transfer_orders",
        last_fetched_at=datetime(2024, 6, 1, tzinfo=timezone.utc),
        last_record_date=datetime(2024, 6, 1, tzinfo=timezone.utc),
    )

    with patch(
        "lexgenius_pipeline.ingestion.judicial.jpml.create_http_client",
        return_value=mock_client,
    ):
        connector = JPMLTransferOrdersConnector()
        records = await connector.fetch_latest(IngestionQuery(), watermark=watermark)

    assert len(records) == 1
    assert "5002" in records[0].title


# ---------------------------------------------------------------------------
# fetch_latest with mocked HTTP — CourtListener Dockets
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cl_dockets_fetch_latest():
    api_response = {
        "results": [
            {
                "caseName": "Doe v. Acme Corp",
                "docketNumber": "1:24-cv-12345",
                "dateFiled": "2025-02-01",
                "court": "dcd",
                "absoluteUrl": "/docket/12345/doe-v-acme/",
                "cause": "28:1332 Diversity",
                "suitNature": "360 Personal Injury",
                "assignedTo": "Judge Smith",
            }
        ]
    }

    mock_response = MagicMock()
    mock_response.json.return_value = api_response
    mock_response.status_code = 200

    mock_client = AsyncMock()
    mock_client.get = AsyncMock(return_value=mock_response)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    with patch(
        "lexgenius_pipeline.ingestion.judicial.courtlistener_dockets.create_http_client",
        return_value=mock_client,
    ):
        connector = CourtListenerDocketsConnector()
        records = await connector.fetch_latest(IngestionQuery(query_terms=["Acme"]))

    assert len(records) == 1
    assert records[0].title == "Doe v. Acme Corp"
    assert records[0].record_type == RecordType.FILING
    assert "dcd" in records[0].metadata["court"]
    assert records[0].metadata["docket_number"] == "1:24-cv-12345"
    assert "Judge: Judge Smith" in records[0].summary


@pytest.mark.asyncio
async def test_cl_dockets_fetch_empty_terms():
    connector = CourtListenerDocketsConnector()
    records = await connector.fetch_latest(IngestionQuery())
    assert records == []


@pytest.mark.asyncio
async def test_cl_dockets_skips_unnamed_cases():
    api_response = {
        "results": [
            {"caseName": "", "dateFiled": "2025-01-01"},
            {"caseName": "Real Case", "dateFiled": "2025-01-01", "absoluteUrl": "/d/1/"},
        ]
    }

    mock_response = MagicMock()
    mock_response.json.return_value = api_response
    mock_response.status_code = 200

    mock_client = AsyncMock()
    mock_client.get = AsyncMock(return_value=mock_response)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    with patch(
        "lexgenius_pipeline.ingestion.judicial.courtlistener_dockets.create_http_client",
        return_value=mock_client,
    ):
        connector = CourtListenerDocketsConnector()
        records = await connector.fetch_latest(IngestionQuery(query_terms=["test"]))

    assert len(records) == 1
    assert records[0].title == "Real Case"


# ---------------------------------------------------------------------------
# fetch_latest with mocked HTTP — NCSC
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_ncsc_fetch_latest():
    html = """<div>
    <a href="/data/court-statistics/report-2024.pdf">Annual Court Statistics 2024</a>
    <span>2024</span>
    </div>"""

    mock_response = MagicMock()
    mock_response.text = html
    mock_response.status_code = 200
    mock_response.raise_for_status = MagicMock()

    mock_client = AsyncMock()
    mock_client.get = AsyncMock(return_value=mock_response)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    with patch(
        "lexgenius_pipeline.ingestion.judicial.ncsc.create_http_client",
        return_value=mock_client,
    ):
        connector = NCSCStatisticsConnector()
        records = await connector.fetch_latest(IngestionQuery(query_terms=["statistics"]))

    assert len(records) >= 1
    assert records[0].record_type == RecordType.RESEARCH
    assert records[0].source_connector_id == "judicial.ncsc.statistics"


@pytest.mark.asyncio
async def test_ncsc_fetch_empty_page():
    mock_response = MagicMock()
    mock_response.text = "<html><body>No links</body></html>"
    mock_response.status_code = 200
    mock_response.raise_for_status = MagicMock()

    mock_client = AsyncMock()
    mock_client.get = AsyncMock(return_value=mock_response)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    with patch(
        "lexgenius_pipeline.ingestion.judicial.ncsc.create_http_client",
        return_value=mock_client,
    ):
        connector = NCSCStatisticsConnector()
        records = await connector.fetch_latest(IngestionQuery())

    assert records == []


# ---------------------------------------------------------------------------
# fetch_latest with mocked HTTP — Lead Counsel
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_lead_counsel_fetch_from_jpml():
    html = (
        "<p>The court appointed Jane Doe as lead counsel for MDL No. 3100 on January 10, 2025.</p>"
    )

    jpml_response = MagicMock()
    jpml_response.text = html
    jpml_response.status_code = 200
    jpml_response.raise_for_status = MagicMock()

    mock_client = AsyncMock()
    mock_client.get = AsyncMock(return_value=jpml_response)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    with patch(
        "lexgenius_pipeline.ingestion.judicial.lead_counsel.create_http_client",
        return_value=mock_client,
    ):
        connector = LeadCounselConnector()
        records = await connector.fetch_latest(IngestionQuery())

    assert len(records) >= 1
    assert records[0].record_type == RecordType.FILING
    assert records[0].source_connector_id == "judicial.lead_counsel"
    assert records[0].metadata["appointment_type"] == "lead_counsel"


@pytest.mark.asyncio
async def test_lead_counsel_fetch_no_counsel_data():
    html = "<p>General court information with no counsel appointments.</p>"

    mock_response = MagicMock()
    mock_response.text = html
    mock_response.status_code = 200
    mock_response.raise_for_status = MagicMock()

    mock_client = AsyncMock()
    mock_client.get = AsyncMock(return_value=mock_response)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    with patch(
        "lexgenius_pipeline.ingestion.judicial.lead_counsel.create_http_client",
        return_value=mock_client,
    ):
        connector = LeadCounselConnector()
        records = await connector.fetch_latest(IngestionQuery())

    assert records == []


# ---------------------------------------------------------------------------
# health_check
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_jpml_health_check_healthy():
    mock_response = MagicMock()
    mock_response.status_code = 200

    mock_client = AsyncMock()
    mock_client.get = AsyncMock(return_value=mock_response)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    with patch(
        "lexgenius_pipeline.ingestion.judicial.jpml.create_http_client",
        return_value=mock_client,
    ):
        connector = JPMLTransferOrdersConnector()
        status = await connector.health_check()

    assert status == HealthStatus.HEALTHY


@pytest.mark.asyncio
async def test_jpml_health_check_failed():
    mock_client = AsyncMock()
    mock_client.get = AsyncMock(side_effect=httpx.ConnectError("Connection refused"))
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    with patch(
        "lexgenius_pipeline.ingestion.judicial.jpml.create_http_client",
        return_value=mock_client,
    ):
        connector = JPMLTransferOrdersConnector()
        status = await connector.health_check()

    assert status == HealthStatus.FAILED


@pytest.mark.asyncio
async def test_cl_dockets_health_check_healthy():
    mock_response = MagicMock()
    mock_response.status_code = 200

    mock_client = AsyncMock()
    mock_client.get = AsyncMock(return_value=mock_response)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    with patch(
        "lexgenius_pipeline.ingestion.judicial.courtlistener_dockets.create_http_client",
        return_value=mock_client,
    ):
        connector = CourtListenerDocketsConnector()
        status = await connector.health_check()

    assert status == HealthStatus.HEALTHY


@pytest.mark.asyncio
async def test_ncsc_health_check_healthy():
    mock_response = MagicMock()
    mock_response.status_code = 200

    mock_client = AsyncMock()
    mock_client.get = AsyncMock(return_value=mock_response)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    with patch(
        "lexgenius_pipeline.ingestion.judicial.ncsc.create_http_client",
        return_value=mock_client,
    ):
        connector = NCSCStatisticsConnector()
        status = await connector.health_check()

    assert status == HealthStatus.HEALTHY


@pytest.mark.asyncio
async def test_lead_counsel_health_check_healthy():
    mock_response = MagicMock()
    mock_response.status_code = 200

    mock_client = AsyncMock()
    mock_client.get = AsyncMock(return_value=mock_response)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    with patch(
        "lexgenius_pipeline.ingestion.judicial.lead_counsel.create_http_client",
        return_value=mock_client,
    ):
        connector = LeadCounselConnector()
        status = await connector.health_check()

    assert status == HealthStatus.HEALTHY


@pytest.mark.asyncio
async def test_lead_counsel_health_check_degraded():
    mock_response = MagicMock()
    mock_response.status_code = 503

    mock_client = AsyncMock()
    mock_client.get = AsyncMock(return_value=mock_response)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    with patch(
        "lexgenius_pipeline.ingestion.judicial.lead_counsel.create_http_client",
        return_value=mock_client,
    ):
        connector = LeadCounselConnector()
        status = await connector.health_check()

    assert status == HealthStatus.DEGRADED


# ---------------------------------------------------------------------------
# ConnectorError on HTTP failure
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_jpml_raises_connector_error():
    from lexgenius_pipeline.common.errors import ConnectorError

    mock_client = AsyncMock()
    mock_client.get = AsyncMock(side_effect=httpx.ConnectError("timeout"))
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    with patch(
        "lexgenius_pipeline.ingestion.judicial.jpml.create_http_client",
        return_value=mock_client,
    ):
        connector = JPMLTransferOrdersConnector()
        with pytest.raises(ConnectorError) as exc_info:
            await connector.fetch_latest(IngestionQuery())

    assert exc_info.value.connector_id == "judicial.jpml.transfer_orders"


@pytest.mark.asyncio
async def test_cl_dockets_raises_connector_error():
    from lexgenius_pipeline.common.errors import ConnectorError

    mock_client = AsyncMock()
    mock_client.get = AsyncMock(side_effect=httpx.ConnectError("timeout"))
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    with patch(
        "lexgenius_pipeline.ingestion.judicial.courtlistener_dockets.create_http_client",
        return_value=mock_client,
    ):
        connector = CourtListenerDocketsConnector()
        with pytest.raises(ConnectorError) as exc_info:
            await connector.fetch_latest(IngestionQuery(query_terms=["test"]))

    assert exc_info.value.connector_id == "judicial.courtlistener.dockets"


# ---------------------------------------------------------------------------
# Registry integration
# ---------------------------------------------------------------------------


def test_registry_register_all_new_judicial():
    registry = ConnectorRegistry()
    connectors = [
        JPMLTransferOrdersConnector(),
        CourtListenerDocketsConnector(),
        NCSCStatisticsConnector(),
        LeadCounselConnector(),
    ]
    for c in connectors:
        registry.register(c)
    assert len(registry) == 4


def test_registry_all_new_listed_by_judicial_tier():
    registry = ConnectorRegistry()
    for cls in (
        JPMLTransferOrdersConnector,
        CourtListenerDocketsConnector,
        NCSCStatisticsConnector,
        LeadCounselConnector,
    ):
        registry.register(cls())

    judicial = registry.list_by_tier(SourceTier.JUDICIAL)
    assert len(judicial) == 4


def test_registry_mixed_old_and_new_judicial():
    from lexgenius_pipeline.ingestion.judicial.courtlistener import CourtListenerConnector
    from lexgenius_pipeline.ingestion.judicial.pacer import PACERConnector
    from lexgenius_pipeline.ingestion.judicial.regulations_gov import RegulationsGovConnector

    registry = ConnectorRegistry()
    all_judicial = [
        CourtListenerConnector(),
        PACERConnector(),
        RegulationsGovConnector(),
        JPMLTransferOrdersConnector(),
        CourtListenerDocketsConnector(),
        NCSCStatisticsConnector(),
        LeadCounselConnector(),
    ]
    for c in all_judicial:
        registry.register(c)

    assert len(registry) == 7
    judicial = registry.list_by_tier(SourceTier.JUDICIAL)
    assert len(judicial) == 7


def test_registry_contains_new_connectors():
    registry = ConnectorRegistry()
    registry.register(JPMLTransferOrdersConnector())
    registry.register(LeadCounselConnector())

    assert "judicial.jpml.transfer_orders" in registry
    assert "judicial.lead_counsel" in registry
    assert "judicial.nonexistent" not in registry


def test_registry_duplicate_new_connector_raises():
    registry = ConnectorRegistry()
    registry.register(JPMLTransferOrdersConnector())
    with pytest.raises(ValueError, match="already registered"):
        registry.register(JPMLTransferOrdersConnector())


# ---------------------------------------------------------------------------
# NormalizedRecord field validation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_jpml_record_has_required_fields():
    html = """<table>
    <tr><td>MDL No. 9999</td><td>In re: Widget Litigation</td>
    <td>Eastern District</td><td>March 1, 2025</td></tr>
    </table>"""

    mock_response = MagicMock()
    mock_response.text = html
    mock_response.status_code = 200
    mock_response.raise_for_status = MagicMock()

    mock_client = AsyncMock()
    mock_client.get = AsyncMock(return_value=mock_response)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    with patch(
        "lexgenius_pipeline.ingestion.judicial.jpml.create_http_client",
        return_value=mock_client,
    ):
        connector = JPMLTransferOrdersConnector()
        records = await connector.fetch_latest(IngestionQuery())

    assert len(records) == 1
    record = records[0]
    assert record.title
    assert record.summary
    assert record.record_type == RecordType.FILING
    assert record.source_connector_id == "judicial.jpml.transfer_orders"
    assert record.source_label == "JPML Transfer Orders"
    assert record.source_url
    assert record.published_at.tzinfo == timezone.utc
    assert record.fingerprint
    assert isinstance(record.metadata, dict)
    assert "mdl_number" in record.metadata


# ---------------------------------------------------------------------------
# Package __init__ exports
# ---------------------------------------------------------------------------


def test_judicial_init_exports_new_connectors():
    from lexgenius_pipeline.ingestion.judicial import (
        CourtListenerDocketsConnector,
        JPMLTransferOrdersConnector,
        LeadCounselConnector,
        NCSCStatisticsConnector,
    )

    assert JPMLTransferOrdersConnector is not None
    assert CourtListenerDocketsConnector is not None
    assert NCSCStatisticsConnector is not None
    assert LeadCounselConnector is not None


def test_judicial_init_all_list():
    import lexgenius_pipeline.ingestion.judicial as judicial_pkg

    assert "JPMLTransferOrdersConnector" in judicial_pkg.__all__
    assert "CourtListenerDocketsConnector" in judicial_pkg.__all__
    assert "NCSCStatisticsConnector" in judicial_pkg.__all__
    assert "LeadCounselConnector" in judicial_pkg.__all__
