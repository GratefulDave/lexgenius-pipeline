from __future__ import annotations


class LexGeniusError(Exception):
    """Base exception for all LexGenius errors."""

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class ConnectorError(LexGeniusError):
    """Error raised by a data connector."""

    def __init__(self, message: str, connector_id: str) -> None:
        super().__init__(message)
        self.connector_id = connector_id


class RateLimitError(ConnectorError):
    """Raised when a connector hits a rate limit."""

    def __init__(
        self,
        message: str,
        connector_id: str,
        retry_after: float | None = None,
    ) -> None:
        super().__init__(message, connector_id)
        self.retry_after = retry_after


class AuthenticationError(ConnectorError):
    """Raised when a connector fails to authenticate."""


class DataValidationError(LexGeniusError):
    """Raised when incoming data fails validation."""


class RepositoryError(LexGeniusError):
    """Raised on database / repository failures."""


class WorkflowError(LexGeniusError):
    """Raised on workflow orchestration failures."""
