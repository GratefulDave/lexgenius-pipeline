"""Tests for new commercial and social data source connectors."""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from lexgenius_pipeline.common.models import IngestionQuery, NormalizedRecord, Watermark
from lexgenius_pipeline.common.types import HealthStatus, RecordType, SourceTier
from lexgenius_pipeline.ingestion.commercial.aboutlawsuits import AboutLawsuitsConnector
from lexgenius_pipeline.ingestion.commercial.classaction_org import ClassActionOrgConnector
from lexgenius_pipeline.ingestion.commercial.drugsdotcom_reviews import DrugsDotComReviewsConnector
from lexgenius_pipeline.ingestion.commercial.google_trends import GoogleTrendsConnector
from lexgenius_pipeline.ingestion.commercial.jdsupra_mass_tort import JDSupraMassTortConnector
from lexgenius_pipeline.ingestion.commercial.law_firm_hiring import LawFirmHiringConnector
from lexgenius_pipeline.ingestion.commercial.mdl_tracker import MDLTrackerConnector
from lexgenius_pipeline.ingestion.commercial.national_law_review import NationalLawReviewConnector
from lexgenius_pipeline.ingestion.commercial.reddit_forums import RedditForumsConnector
from lexgenius_pipeline.ingestion.commercial.ssrn import SSRNConnector
from lexgenius_pipeline.ingestion.commercial.stanford_clearinghouse import (
    StanfordClearinghouseConnector,
)
from lexgenius_pipeline.ingestion.commercial.topclassactions import TopClassActionsConnector


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

_RSS_XML = """\
<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <title>Test Feed</title>
    <item>
      <title>Mass Tort Update: Drug X Lawsuit</title>
      <link>https://example.com/article-1</link>
      <description>A new mass tort case has been filed.</description>
      <pubDate>Mon, 10 Mar 2026 12:00:00 GMT</pubDate>
    </item>
    <item>
      <title>Settlement in Class Action Y</title>
      <link>https://example.com/article-2</link>
      <description>$50 million settlement announced.</description>
      <pubDate>Tue, 11 Mar 2026 14:00:00 GMT</pubDate>
    </item>
  </channel>
</rss>
"""

_SCRAPE_HTML = """\
<html><body>
<h2 class="entry-title"><a href="/case-1">MDL 1234 Drug Litigation</a></h2>
<time datetime="2026-03-10T12:00:00+00:00">March 10, 2026</time>
<div class="entry-content">This is about MDL-1234 with 500 cases pending.</div>
<h2 class="entry-title"><a href="/case-2">Product Liability Settlement</a></h2>
<time datetime="2026-03-11T14:00:00+00:00">March 11, 2026</time>
<div class="entry-content">Deadline: April 15, 2026. $25 million settlement fund.</div>
</body></html>
"""

_DRUGS_HTML = """\
<html><body>
<div class="ddc-comment">
  <span class="comment-date">March 10, 2026</span>
  <span class="review-text">I experienced severe side effects including nausea and dizziness after taking this medication for two weeks.</span>
  <span>Rating: 3/10</span>
</div>
<div class="ddc-comment">
  <span class="comment-date">March 11, 2026</span>
  <span class="review-text">Short.</span>
</div>
</body></html>
"""

_REDDIT_RESPONSE = {
    "data": {
        "children": [
            {
                "data": {
                    "title": "Has anyone filed a lawsuit for Drug X side effects?",
                    "selftext": "I experienced severe side effects and my doctor recommended I look into legal options.",
                    "permalink": "/r/lawsuit/comments/abc123/test/",
                    "created_utc": 1741608000.0,
                    "score": 42,
                    "num_comments": 15,
                    "author": "testuser",
                }
            }
        ]
    }
}

_JOB_HTML = """\
<html><body>
<h2 class="jobTitle"><a href="/rc/clk?jk=abc123">Mass Tort Attorney</a></h2>
<span class="companyName">Smith & Associates</span>
<div class="companyLocation">New York, NY</div>
<span class="date">2 days ago</span>
</body></html>
"""


def _make_response(text: str, status_code: int = 200) -> httpx.Response:
    return httpx.Response(
        status_code=status_code,
        text=text,
        request=httpx.Request("GET", "https://example.com"),
    )


def _make_json_response(data: dict, status_code: int = 200) -> httpx.Response:
    import json

    return httpx.Response(
        status_code=status_code,
        text=json.dumps(data),
        headers={"content-type": "application/json"},
        request=httpx.Request("GET", "https://example.com"),
    )


# ---------------------------------------------------------------------------
# Instantiation + metadata tests
# ---------------------------------------------------------------------------

_ALL_CONNECTORS = [
    (JDSupraMassTortConnector, "commercial.jdsupra_mass_tort", SourceTier.COMMERCIAL),
    (TopClassActionsConnector, "commercial.topclassactions", SourceTier.COMMERCIAL),
    (AboutLawsuitsConnector, "commercial.aboutlawsuits", SourceTier.COMMERCIAL),
    (NationalLawReviewConnector, "commercial.national_law_review", SourceTier.COMMERCIAL),
    (SSRNConnector, "commercial.ssrn", SourceTier.COMMERCIAL),
    (MDLTrackerConnector, "commercial.mdl_tracker", SourceTier.COMMERCIAL),
    (ClassActionOrgConnector, "commercial.classaction_org", SourceTier.COMMERCIAL),
    (StanfordClearinghouseConnector, "commercial.stanford_clearinghouse", SourceTier.COMMERCIAL),
    (RedditForumsConnector, "commercial.reddit_forums", SourceTier.COMMERCIAL),
    (GoogleTrendsConnector, "commercial.google_trends", SourceTier.COMMERCIAL),
    (DrugsDotComReviewsConnector, "commercial.drugsdotcom_reviews", SourceTier.COMMERCIAL),
    (LawFirmHiringConnector, "commercial.law_firm_hiring", SourceTier.COMMERCIAL),
]


@pytest.mark.parametrize("cls,connector_id,tier", _ALL_CONNECTORS)
def test_connector_instantiation(cls, connector_id, tier):
    connector = cls()
    assert connector is not None


@pytest.mark.parametrize("cls,connector_id,tier", _ALL_CONNECTORS)
def test_connector_id(cls, connector_id, tier):
    assert cls.connector_id == connector_id


@pytest.mark.parametrize("cls,connector_id,tier", _ALL_CONNECTORS)
def test_connector_tier(cls, connector_id, tier):
    assert cls.source_tier == tier


# ---------------------------------------------------------------------------
# Record type tests
# ---------------------------------------------------------------------------


def test_jdsupra_record_type_is_news():
    assert JDSupraMassTortConnector.connector_id == "commercial.jdsupra_mass_tort"


def test_topclassactions_record_type():
    assert TopClassActionsConnector.connector_id == "commercial.topclassactions"


def test_aboutlawsuits_record_type():
    assert AboutLawsuitsConnector.connector_id == "commercial.aboutlawsuits"


def test_ssrn_record_type():
    assert SSRNConnector.connector_id == "commercial.ssrn"


def test_mdl_tracker_record_type():
    assert MDLTrackerConnector.connector_id == "commercial.mdl_tracker"


def test_reddit_forums_record_type():
    assert RedditForumsConnector.connector_id == "commercial.reddit_forums"


def test_google_trends_record_type():
    assert GoogleTrendsConnector.connector_id == "commercial.google_trends"


def test_drugsdotcom_reviews_record_type():
    assert DrugsDotComReviewsConnector.connector_id == "commercial.drugsdotcom_reviews"


# ---------------------------------------------------------------------------
# RSS connector fetch tests (JD Supra, NLR, SSRN)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_jdsupra_fetch_parses_rss():
    connector = JDSupraMassTortConnector()
    mock_client = AsyncMock()
    mock_client.get = AsyncMock(return_value=_make_response(_RSS_XML))
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    with patch(
        "lexgenius_pipeline.ingestion.commercial.jdsupra_mass_tort.create_http_client",
        return_value=mock_client,
    ):
        query = IngestionQuery(query_terms=["drug"])
        records = await connector.fetch_latest(query)

    assert len(records) == 2
    assert all(isinstance(r, NormalizedRecord) for r in records)
    assert records[0].record_type == RecordType.NEWS
    assert records[0].source_connector_id == "commercial.jdsupra_mass_tort"
    assert "Mass Tort Update" in records[0].title
    assert records[0].fingerprint


@pytest.mark.asyncio
async def test_national_law_review_fetch_parses_rss():
    connector = NationalLawReviewConnector()
    mock_client = AsyncMock()
    mock_client.get = AsyncMock(return_value=_make_response(_RSS_XML))
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    with patch(
        "lexgenius_pipeline.ingestion.commercial.national_law_review.create_http_client",
        return_value=mock_client,
    ):
        query = IngestionQuery(query_terms=["mass tort"])
        records = await connector.fetch_latest(query)

    assert len(records) == 1
    assert records[0].record_type == RecordType.NEWS
    assert records[0].source_connector_id == "commercial.national_law_review"


@pytest.mark.asyncio
async def test_national_law_review_no_filter_returns_all():
    connector = NationalLawReviewConnector()
    mock_client = AsyncMock()
    mock_client.get = AsyncMock(return_value=_make_response(_RSS_XML))
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    with patch(
        "lexgenius_pipeline.ingestion.commercial.national_law_review.create_http_client",
        return_value=mock_client,
    ):
        query = IngestionQuery()
        records = await connector.fetch_latest(query)

    assert len(records) == 2


@pytest.mark.asyncio
async def test_ssrn_fetch_parses_rss():
    connector = SSRNConnector()
    mock_client = AsyncMock()
    mock_client.get = AsyncMock(return_value=_make_response(_RSS_XML))
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    with patch(
        "lexgenius_pipeline.ingestion.commercial.ssrn.create_http_client",
        return_value=mock_client,
    ):
        query = IngestionQuery()
        records = await connector.fetch_latest(query)

    assert len(records) == 2
    assert records[0].record_type == RecordType.RESEARCH
    assert records[0].source_connector_id == "commercial.ssrn"


# ---------------------------------------------------------------------------
# RSS watermark filtering
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_jdsupra_watermark_filters_old_records():
    connector = JDSupraMassTortConnector()
    mock_client = AsyncMock()
    mock_client.get = AsyncMock(return_value=_make_response(_RSS_XML))
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    watermark = Watermark(
        scope_key="test",
        connector_id="commercial.jdsupra_mass_tort",
        last_fetched_at=datetime(2026, 3, 10, 13, 0, 0, tzinfo=timezone.utc),
        last_record_date=datetime(2026, 3, 10, 13, 0, 0, tzinfo=timezone.utc),
    )
    with patch(
        "lexgenius_pipeline.ingestion.commercial.jdsupra_mass_tort.create_http_client",
        return_value=mock_client,
    ):
        query = IngestionQuery()
        records = await connector.fetch_latest(query, watermark=watermark)

    assert len(records) == 1
    assert "Settlement" in records[0].title


# ---------------------------------------------------------------------------
# RSS error handling
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_jdsupra_http_error_raises():
    connector = JDSupraMassTortConnector()
    mock_client = AsyncMock()
    mock_client.get = AsyncMock(return_value=_make_response("", status_code=500))
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    from lexgenius_pipeline.common.errors import ConnectorError

    with patch(
        "lexgenius_pipeline.ingestion.commercial.jdsupra_mass_tort.create_http_client",
        return_value=mock_client,
    ):
        with pytest.raises(ConnectorError):
            await connector.fetch_latest(IngestionQuery())


@pytest.mark.asyncio
async def test_jdsupra_invalid_xml_raises():
    connector = JDSupraMassTortConnector()
    mock_client = AsyncMock()
    mock_client.get = AsyncMock(return_value=_make_response("not xml"))
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    from lexgenius_pipeline.common.errors import ConnectorError

    with patch(
        "lexgenius_pipeline.ingestion.commercial.jdsupra_mass_tort.create_http_client",
        return_value=mock_client,
    ):
        with pytest.raises(ConnectorError, match="XML parse error"):
            await connector.fetch_latest(IngestionQuery())


# ---------------------------------------------------------------------------
# Scrape connector fetch tests (TopClassActions, MDL, ClassAction.org, Stanford)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_topclassactions_fetch_parses_html():
    connector = TopClassActionsConnector()

    mock_client = AsyncMock()
    mock_client.get = AsyncMock(return_value=_make_response(_SCRAPE_HTML))
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    with patch(
        "lexgenius_pipeline.ingestion.commercial.topclassactions.create_http_client",
        return_value=mock_client,
    ):
        query = IngestionQuery()
        records = await connector.fetch_latest(query)

    assert len(records) == 2
    assert records[0].record_type == RecordType.ENFORCEMENT
    assert records[0].source_connector_id == "commercial.topclassactions"


@pytest.mark.asyncio
async def test_mdl_tracker_fetch_parses_html():
    connector = MDLTrackerConnector()

    mock_client = AsyncMock()
    mock_client.get = AsyncMock(return_value=_make_response(_SCRAPE_HTML))
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    with patch(
        "lexgenius_pipeline.ingestion.commercial.mdl_tracker.create_http_client",
        return_value=mock_client,
    ):
        query = IngestionQuery()
        records = await connector.fetch_latest(query)

    assert len(records) == 2
    assert records[0].record_type == RecordType.FILING
    assert records[0].source_connector_id == "commercial.mdl_tracker"
    assert "MDL" in records[0].title or "Product" in records[0].title


@pytest.mark.asyncio
async def test_mdl_tracker_extracts_mdl_number():
    connector = MDLTrackerConnector()

    mock_client = AsyncMock()
    mock_client.get = AsyncMock(return_value=_make_response(_SCRAPE_HTML))
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    with patch(
        "lexgenius_pipeline.ingestion.commercial.mdl_tracker.create_http_client",
        return_value=mock_client,
    ):
        query = IngestionQuery()
        records = await connector.fetch_latest(query)

    mdl_record = next((r for r in records if "1234" in r.title), None)
    assert mdl_record is not None
    assert mdl_record.metadata.get("mdl_number") == "1234"


@pytest.mark.asyncio
async def test_classaction_org_fetch_parses_html():
    connector = ClassActionOrgConnector()

    mock_client = AsyncMock()
    mock_client.get = AsyncMock(return_value=_make_response(_SCRAPE_HTML))
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    with patch(
        "lexgenius_pipeline.ingestion.commercial.classaction_org.create_http_client",
        return_value=mock_client,
    ):
        query = IngestionQuery()
        records = await connector.fetch_latest(query)

    assert len(records) == 2
    assert records[0].record_type == RecordType.ENFORCEMENT


@pytest.mark.asyncio
async def test_stanford_clearinghouse_fetch_parses_html():
    connector = StanfordClearinghouseConnector()

    mock_client = AsyncMock()
    mock_client.get = AsyncMock(return_value=_make_response(_SCRAPE_HTML))
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    with patch(
        "lexgenius_pipeline.ingestion.commercial.stanford_clearinghouse.create_http_client",
        return_value=mock_client,
    ):
        query = IngestionQuery()
        records = await connector.fetch_latest(query)

    assert len(records) == 2
    assert records[0].record_type == RecordType.ENFORCEMENT
    assert records[0].source_connector_id == "commercial.stanford_clearinghouse"


@pytest.mark.asyncio
async def test_aboutlawsuits_fetch_parses_html():
    connector = AboutLawsuitsConnector()

    mock_client = AsyncMock()
    mock_client.get = AsyncMock(return_value=_make_response(_SCRAPE_HTML))
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    with patch(
        "lexgenius_pipeline.ingestion.commercial.aboutlawsuits.create_http_client",
        return_value=mock_client,
    ):
        query = IngestionQuery()
        records = await connector.fetch_latest(query)

    assert len(records) == 2
    assert records[0].record_type == RecordType.NEWS
    assert records[0].source_connector_id == "commercial.aboutlawsuits"


# ---------------------------------------------------------------------------
# Scrape connector watermark filtering
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_topclassactions_watermark_filters():
    connector = TopClassActionsConnector()

    mock_client = AsyncMock()
    mock_client.get = AsyncMock(return_value=_make_response(_SCRAPE_HTML))
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    watermark = Watermark(
        scope_key="test",
        connector_id="commercial.topclassactions",
        last_fetched_at=datetime(2026, 3, 10, 13, 0, 0, tzinfo=timezone.utc),
        last_record_date=datetime(2026, 3, 10, 13, 0, 0, tzinfo=timezone.utc),
    )

    with patch(
        "lexgenius_pipeline.ingestion.commercial.topclassactions.create_http_client",
        return_value=mock_client,
    ):
        query = IngestionQuery()
        records = await connector.fetch_latest(query, watermark=watermark)

    assert len(records) == 1


# ---------------------------------------------------------------------------
# Scrape connector error handling
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_topclassactions_http_error_raises():
    connector = TopClassActionsConnector()

    mock_client = AsyncMock()
    mock_client.get = AsyncMock(return_value=_make_response("", status_code=500))
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    from lexgenius_pipeline.common.errors import ConnectorError

    with patch(
        "lexgenius_pipeline.ingestion.commercial.topclassactions.create_http_client",
        return_value=mock_client,
    ):
        with pytest.raises(ConnectorError):
            await connector.fetch_latest(IngestionQuery())


# ---------------------------------------------------------------------------
# Reddit connector tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_reddit_no_credentials_returns_empty():
    connector = RedditForumsConnector()
    query = IngestionQuery(query_terms=["lawsuit"])
    records = await connector.fetch_latest(query)
    assert records == []


@pytest.mark.asyncio
async def test_reddit_health_check_no_credentials():
    connector = RedditForumsConnector()
    status = await connector.health_check()
    assert status == HealthStatus.DEGRADED


@pytest.mark.asyncio
async def test_reddit_fetch_with_mocked_auth():
    connector = RedditForumsConnector()
    connector._settings = MagicMock()
    connector._settings.reddit_client_id = "test_id"
    connector._settings.reddit_client_secret = "test_secret"
    connector._access_token = "mock_token"

    mock_client = AsyncMock()
    mock_client.get = AsyncMock(return_value=_make_json_response(_REDDIT_RESPONSE))
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    with patch(
        "lexgenius_pipeline.ingestion.commercial.reddit_forums.create_http_client",
        return_value=mock_client,
    ):
        query = IngestionQuery(query_terms=["drug"])
        records = await connector.fetch_latest(query)

    assert len(records) >= 1
    assert records[0].record_type == RecordType.NEWS
    assert records[0].source_connector_id == "commercial.reddit_forums"
    assert "lawsuit" in records[0].title.lower() or "drug" in records[0].summary.lower()
    assert records[0].metadata.get("subreddit")


# ---------------------------------------------------------------------------
# Google Trends connector tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_google_trends_no_terms_returns_empty():
    connector = GoogleTrendsConnector()
    query = IngestionQuery()
    records = await connector.fetch_latest(query)
    assert records == []


@pytest.mark.asyncio
async def test_google_trends_missing_pytrends_returns_empty():
    connector = GoogleTrendsConnector()

    with patch.dict("sys.modules", {"pytrends": None, "pytrends.request": None}):
        query = IngestionQuery(query_terms=["aspirin"])
        records = await connector.fetch_latest(query)

    assert records == []


@pytest.mark.asyncio
async def test_google_trends_fetch_with_mock():
    import pandas as pd

    connector = GoogleTrendsConnector()

    mock_df = pd.DataFrame(
        {"aspirin lawsuit": [30, 45, 60, 80], "aspirin class action": [20, 35, 50, 70]},
        index=pd.date_range("2026-01-01", periods=4, freq="W"),
    )

    mock_pytrends = MagicMock()
    mock_pytrends.build_payload = MagicMock()
    mock_pytrends.interest_over_time = MagicMock(return_value=mock_df)

    with patch(
        "pytrends.request.TrendReq",
        return_value=mock_pytrends,
    ):
        query = IngestionQuery(query_terms=["aspirin"])
        records = await connector.fetch_latest(query)

    assert len(records) == 1
    assert records[0].record_type == RecordType.RESEARCH
    assert records[0].source_connector_id == "commercial.google_trends"
    assert records[0].metadata.get("term") == "aspirin"
    assert records[0].metadata.get("max_interest") == 80


# ---------------------------------------------------------------------------
# Drugs.com reviews connector tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_drugsdotcom_no_terms_returns_empty():
    connector = DrugsDotComReviewsConnector()
    query = IngestionQuery()
    records = await connector.fetch_latest(query)
    assert records == []


@pytest.mark.asyncio
async def test_drugsdotcom_fetch_parses_reviews():
    connector = DrugsDotComReviewsConnector()

    mock_client = AsyncMock()
    mock_client.get = AsyncMock(return_value=_make_response(_DRUGS_HTML))
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    with patch(
        "lexgenius_pipeline.ingestion.commercial.drugsdotcom_reviews.create_http_client",
        return_value=mock_client,
    ):
        query = IngestionQuery(query_terms=["aspirin"])
        records = await connector.fetch_latest(query)

    assert len(records) >= 1
    assert records[0].record_type == RecordType.ADVERSE_EVENT
    assert records[0].source_connector_id == "commercial.drugsdotcom_reviews"


# ---------------------------------------------------------------------------
# Law firm hiring connector tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_law_firm_hiring_fetch_parses_jobs():
    connector = LawFirmHiringConnector()

    mock_client = AsyncMock()
    mock_client.get = AsyncMock(return_value=_make_response(_JOB_HTML))
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    with patch(
        "lexgenius_pipeline.ingestion.commercial.law_firm_hiring.create_http_client",
        return_value=mock_client,
    ):
        query = IngestionQuery()
        records = await connector.fetch_latest(query)

    assert len(records) >= 1
    assert records[0].record_type == RecordType.NEWS
    assert records[0].source_connector_id == "commercial.law_firm_hiring"
    assert "Mass Tort" in records[0].title


@pytest.mark.asyncio
async def test_law_firm_hiring_http_error_continues():
    connector = LawFirmHiringConnector()

    mock_client = AsyncMock()
    mock_client.get = AsyncMock(return_value=_make_response("", status_code=403))
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    with patch(
        "lexgenius_pipeline.ingestion.commercial.law_firm_hiring.create_http_client",
        return_value=mock_client,
    ):
        query = IngestionQuery()
        records = await connector.fetch_latest(query)

    assert records == []


# ---------------------------------------------------------------------------
# Health check tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_jdsupra_health_check_healthy():
    connector = JDSupraMassTortConnector()
    mock_client = AsyncMock()
    mock_client.get = AsyncMock(return_value=_make_response("OK", status_code=200))
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    with patch(
        "lexgenius_pipeline.ingestion.commercial.jdsupra_mass_tort.create_http_client",
        return_value=mock_client,
    ):
        status = await connector.health_check()
    assert status == HealthStatus.HEALTHY


@pytest.mark.asyncio
async def test_jdsupra_health_check_failed():
    connector = JDSupraMassTortConnector()
    mock_client = AsyncMock()
    mock_client.get = AsyncMock(side_effect=Exception("connection refused"))
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    with patch(
        "lexgenius_pipeline.ingestion.commercial.jdsupra_mass_tort.create_http_client",
        return_value=mock_client,
    ):
        status = await connector.health_check()
    assert status == HealthStatus.FAILED


@pytest.mark.asyncio
async def test_topclassactions_health_check_healthy():
    connector = TopClassActionsConnector()

    mock_client = AsyncMock()
    mock_client.get = AsyncMock(return_value=_make_response("OK", status_code=200))
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    with patch(
        "lexgenius_pipeline.ingestion.commercial.topclassactions.create_http_client",
        return_value=mock_client,
    ):
        status = await connector.health_check()

    assert status == HealthStatus.HEALTHY


@pytest.mark.asyncio
async def test_mdl_tracker_health_check_healthy():
    connector = MDLTrackerConnector()

    mock_client = AsyncMock()
    mock_client.get = AsyncMock(return_value=_make_response("OK", status_code=200))
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    with patch(
        "lexgenius_pipeline.ingestion.commercial.mdl_tracker.create_http_client",
        return_value=mock_client,
    ):
        status = await connector.health_check()

    assert status == HealthStatus.HEALTHY


@pytest.mark.asyncio
async def test_drugsdotcom_health_check_healthy():
    connector = DrugsDotComReviewsConnector()

    mock_client = AsyncMock()
    mock_client.get = AsyncMock(return_value=_make_response("OK", status_code=200))
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    with patch(
        "lexgenius_pipeline.ingestion.commercial.drugsdotcom_reviews.create_http_client",
        return_value=mock_client,
    ):
        status = await connector.health_check()

    assert status == HealthStatus.HEALTHY


@pytest.mark.asyncio
async def test_law_firm_hiring_health_check_healthy():
    connector = LawFirmHiringConnector()

    mock_client = AsyncMock()
    mock_client.get = AsyncMock(return_value=_make_response("OK", status_code=200))
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    with patch(
        "lexgenius_pipeline.ingestion.commercial.law_firm_hiring.create_http_client",
        return_value=mock_client,
    ):
        status = await connector.health_check()

    assert status == HealthStatus.HEALTHY


# ---------------------------------------------------------------------------
# Fingerprint uniqueness tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_jdsupra_fingerprints_are_unique():
    connector = JDSupraMassTortConnector()
    mock_client = AsyncMock()
    mock_client.get = AsyncMock(return_value=_make_response(_RSS_XML))
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    with patch(
        "lexgenius_pipeline.ingestion.commercial.jdsupra_mass_tort.create_http_client",
        return_value=mock_client,
    ):
        records = await connector.fetch_latest(IngestionQuery())
    fingerprints = [r.fingerprint for r in records]
    assert len(fingerprints) == len(set(fingerprints))


# ---------------------------------------------------------------------------
# Query term filtering tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_topclassactions_query_term_filtering():
    connector = TopClassActionsConnector()

    mock_client = AsyncMock()
    mock_client.get = AsyncMock(return_value=_make_response(_SCRAPE_HTML))
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    with patch(
        "lexgenius_pipeline.ingestion.commercial.topclassactions.create_http_client",
        return_value=mock_client,
    ):
        query = IngestionQuery(query_terms=["MDL"])
        records = await connector.fetch_latest(query)

    assert len(records) == 1
    assert "MDL" in records[0].title


# ---------------------------------------------------------------------------
# Normalized record field validation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_rss_records_have_required_fields():
    connector = JDSupraMassTortConnector()
    mock_client = AsyncMock()
    mock_client.get = AsyncMock(return_value=_make_response(_RSS_XML))
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    with patch(
        "lexgenius_pipeline.ingestion.commercial.jdsupra_mass_tort.create_http_client",
        return_value=mock_client,
    ):
        records = await connector.fetch_latest(IngestionQuery())

    for record in records:
        assert record.title
        assert record.summary
        assert record.record_type in RecordType
        assert record.source_connector_id == "commercial.jdsupra_mass_tort"
        assert record.source_label == "JD Supra Mass Tort"
        assert record.source_url.startswith("http")
        assert record.published_at.tzinfo is not None
        assert record.fingerprint
        assert isinstance(record.metadata, dict)


@pytest.mark.asyncio
async def test_scrape_records_have_required_fields():
    connector = TopClassActionsConnector()

    mock_client = AsyncMock()
    mock_client.get = AsyncMock(return_value=_make_response(_SCRAPE_HTML))
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    with patch(
        "lexgenius_pipeline.ingestion.commercial.topclassactions.create_http_client",
        return_value=mock_client,
    ):
        records = await connector.fetch_latest(IngestionQuery())

    for record in records:
        assert record.title
        assert record.summary
        assert record.record_type == RecordType.ENFORCEMENT
        assert record.source_url.startswith("http")
        assert record.published_at.tzinfo is not None
        assert record.fingerprint


# ---------------------------------------------------------------------------
# Google Trends supports_incremental=False check
# ---------------------------------------------------------------------------


def test_google_trends_not_incremental():
    assert GoogleTrendsConnector.supports_incremental is False


def test_other_connectors_incremental():
    for cls, _, _ in _ALL_CONNECTORS:
        if cls is GoogleTrendsConnector:
            continue
        assert cls.supports_incremental is True, f"{cls.__name__} should be incremental"


# ---------------------------------------------------------------------------
# Reddit 401 re-auth tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_reddit_401_reauth_retries_subreddit():
    """After a 401, the connector should re-authenticate and retry the same subreddit."""
    connector = RedditForumsConnector()
    connector._settings = MagicMock()
    connector._settings.reddit_client_id = "test_id"
    connector._settings.reddit_client_secret = "test_secret"
    connector._access_token = "expired_token"

    auth_response = _make_json_response({"access_token": "new_token"})
    first_get = _make_json_response({}, status_code=401)
    second_get = _make_json_response(_REDDIT_RESPONSE)

    mock_client = AsyncMock()
    mock_client.get = AsyncMock(side_effect=[first_get, second_get])
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    mock_auth_client = AsyncMock()
    mock_auth_client.post = AsyncMock(return_value=auth_response)
    mock_auth_client.__aenter__ = AsyncMock(return_value=mock_auth_client)
    mock_auth_client.__aexit__ = AsyncMock(return_value=False)

    call_count = 0
    original_create = None

    def _mock_create():
        nonlocal call_count
        call_count += 1
        # First call is from fetch_latest (the data client), second from _authenticate
        if call_count == 1:
            return mock_client
        return mock_auth_client

    with patch(
        "lexgenius_pipeline.ingestion.commercial.reddit_forums.create_http_client",
        side_effect=_mock_create,
    ):
        query = IngestionQuery(query_terms=["drug"])
        records = await connector.fetch_latest(query)

    # The retry should have fetched posts from the subreddit
    assert len(records) >= 1
    assert records[0].record_type == RecordType.NEWS


@pytest.mark.asyncio
async def test_reddit_401_reauth_updates_token():
    """After re-auth on 401, the connector should store the new token."""
    connector = RedditForumsConnector()
    connector._settings = MagicMock()
    connector._settings.reddit_client_id = "test_id"
    connector._settings.reddit_client_secret = "test_secret"
    connector._access_token = "expired_token"

    auth_response = _make_json_response({"access_token": "fresh_token"})
    # Return 401 on first subreddit, then 200 with data on retry and subsequent
    first_get = _make_json_response({}, status_code=401)
    retry_get = _make_json_response(_REDDIT_RESPONSE)

    mock_client = AsyncMock()
    mock_client.get = AsyncMock(side_effect=[first_get, retry_get])
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    mock_auth_client = AsyncMock()
    mock_auth_client.post = AsyncMock(return_value=auth_response)
    mock_auth_client.__aenter__ = AsyncMock(return_value=mock_auth_client)
    mock_auth_client.__aexit__ = AsyncMock(return_value=False)

    call_count = 0

    def _mock_create():
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return mock_client
        return mock_auth_client

    with patch(
        "lexgenius_pipeline.ingestion.commercial.reddit_forums.create_http_client",
        side_effect=_mock_create,
    ):
        query = IngestionQuery(query_terms=["drug"])
        await connector.fetch_latest(query)

    assert connector._access_token == "fresh_token"
