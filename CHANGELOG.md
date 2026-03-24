# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Security
- Replace unsafe `xml.etree.ElementTree` with `defusedxml` across all RSS/XML connectors

### Changed
- Migrate Pydantic `class Config` to `model_config = ConfigDict(...)` in `task_spec.py`

### Added
- This CHANGELOG

## [0.3.0] - 2026-03-24

### Added
- 12 commercial and social data source connectors (JD Supra, TopClassActions, AboutLawsuits, National Law Review, SSRN, MDL Tracker, ClassAction.org, Stanford Clearinghouse, Reddit, Google Trends, Drugs.com, Law Firm Hiring)
- Reddit OAuth2 authentication with 401 retry logic
- `beautifulsoup4` dependency for robust HTML parsing

### Changed
- Migrated 4 HTML scrapers from regex to BeautifulSoup for reliability
- Made `pytrends` an optional dependency (`trends` extra)
- Wrapped sync `pytrends` calls in `run_in_executor` to avoid blocking the event loop
- Removed unused `feedparser` dependency

### Fixed
- Resource leak in JDSupra, NLR, and SSRN connectors (httpx.AsyncClient never closed)
- Reddit 401 re-auth now retries the failed subreddit instead of skipping it
- Reddit env var fallbacks added to settings (`REDDIT_CLIENT_ID`, `REDDIT_CLIENT_SECRET`)
- Date parser fallbacks now log warnings instead of silently defaulting to `datetime.now()`

## [0.2.0] - 2026-03-24

### Added
- 23 federal agency connectors (CDC WONDER, DOJ, FTC, NHTSA, OSHA, FDA ×6, CPSC, CFPB, EPA ×3, ATSDR, USDA, NAAG, FJC, NIH SEER)
- 4 judicial connectors (JPML transfer orders, CourtListener dockets, NCSC statistics, lead counsel tracking)
- 10 state Attorney General connectors (CA, NY, TX, IL, MA, PA, FL, OH, CO, NC)
- Shared `date_utils.py` with `parse_date()` and `UNKNOWN_DATE` sentinel
- Shared `html_utils.py` with `LinkExtractorParser`
- `GenericPressReleaseParser` in AG base for configurable HTML parsing
- `defusedxml` dependency for safe XML parsing
- `respx` dev dependency for HTTP mocking in tests
- Rate limiting for CourtListener (auth/unauth) and Regulations.gov
- `AuthenticationError` handling for 401/403 responses in judicial connectors
- 500+ new unit tests with proper HTTP mocking

### Fixed
- XXE vulnerability in AG actions RSS parsing (switched to `defusedxml`)
- EPA ECHO logic bug (triple `resp.json()` call, dead code branch)
- Fingerprint instability in scrape connectors (use `UNKNOWN_DATE` instead of `datetime.now()`)
- Resource leak in CourtListener and Regulations.gov (httpx.AsyncClient never closed)
- 5xx errors silently swallowed in AG `_fetch_press_page`
- CA connector `TypeError` when `max_records` is `None`
- NY AG parser discarding title text inside `<a>` tags
- `import re` moved from inside loops to module level in DOJ/FTC connectors
- Eliminated massive HTML parser duplication across 9 state connectors

### Changed
- Scrape connectors (ATSDR, FJC, NIH SEER, NAAG) set `supports_incremental = False`
- Replaced 15+ duplicated `_parse_date` functions with shared `parse_date()`
- Replaced 3 identical inline `HTMLParser` classes with shared `LinkExtractorParser`
- Regulations.gov API key redacted in error messages
- Health check endpoints corrected (EPA ECHO, Regulations.gov)

## [0.1.0] - 2026-03-23

### Added
- Core pipeline architecture with async-first design and repository pattern
- FDA connectors: FAERS, MAUDE, recalls, DailyMed
- EPA connectors: enforcement actions, CompTox chemical data
- SEC EDGAR connector for financial filings
- CPSC product recall connector
- Federal Register notices connector
- NIH connectors: ClinicalTrials.gov, PubMed
- Congress.gov legislation connector
- USGS water quality connector
- Commercial connectors: Google News, news RSS, Exa search
- Connector registry with tier-based filtering
- Normalized record model with fingerprint-based deduplication
- Watermark-based incremental ingestion
- AWS Lambda handlers with SAM template
- RDS connection pooling for PostgreSQL
- SQLite and PostgreSQL repository implementations
- Structured logging with structlog
- LLM-powered agentic workflows (enrichment, scoring, analysis)
