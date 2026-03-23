import logging

from tenacity import (
    retry,
    retry_if_exception,
    stop_after_attempt,
    wait_exponential,
    wait_fixed,
    before_sleep_log,
)

from .errors import AuthenticationError, ConnectorError, RateLimitError

_log = logging.getLogger(__name__)


def _is_retryable_connector_error(exc: BaseException) -> bool:
    return isinstance(exc, ConnectorError) and not isinstance(exc, AuthenticationError)


def _is_rate_limit_error(exc: BaseException) -> bool:
    return isinstance(exc, RateLimitError)


default_retry = retry(
    retry=retry_if_exception(_is_retryable_connector_error),
    wait=wait_exponential(multiplier=1, min=1, max=30),
    stop=stop_after_attempt(3),
    before_sleep=before_sleep_log(_log, logging.WARNING),
    reraise=True,
)

rate_limit_retry = retry(
    retry=retry_if_exception(_is_rate_limit_error),
    wait=wait_fixed(1),
    stop=stop_after_attempt(5),
    before_sleep=before_sleep_log(_log, logging.WARNING),
    reraise=True,
)
