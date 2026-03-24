"""Shared date-parsing utilities for connectors."""
from __future__ import annotations

from datetime import datetime, timezone

import structlog

logger = structlog.get_logger(__name__)

# Superset of formats used across all connectors.
_COMMON_FORMATS: tuple[str, ...] = (
    "%Y-%m-%d",
    "%m/%d/%Y",
    "%Y-%m-%dT%H:%M:%S",
    "%Y%m%d",
    "%B %d, %Y",
    "%b %d, %Y",
)

# Stable sentinel returned when no date is available, so fingerprints
# are deterministic across runs.
UNKNOWN_DATE = datetime(1970, 1, 1, tzinfo=timezone.utc)


def parse_date(
    value: str | None,
    *,
    extra_formats: tuple[str, ...] = (),
    max_chars: int = 20,
) -> datetime:
    """Parse a date string trying multiple common formats.

    Returns *UNKNOWN_DATE* (1970-01-01 UTC) when *value* is empty or
    cannot be parsed, and logs a warning on parse failure.
    """
    if not value:
        return UNKNOWN_DATE
    trimmed = value.strip()[:max_chars]
    for fmt in (*extra_formats, *_COMMON_FORMATS):
        try:
            return datetime.strptime(trimmed, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    logger.warning("date_utils.parse_failed", raw_value=value)
    return UNKNOWN_DATE
