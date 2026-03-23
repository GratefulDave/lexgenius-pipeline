from __future__ import annotations

import pytest

from lexgenius_pipeline.settings import get_settings


@pytest.fixture
def settings():
    get_settings.cache_clear()
    return get_settings()


def skip_if_no_key(settings, key_name: str) -> None:
    val = getattr(settings, key_name, "")
    if not val:
        pytest.skip(f"No {key_name} configured")
