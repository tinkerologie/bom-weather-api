"""Exceptions raised by the Bureau of Meteorology API client."""

from __future__ import annotations


class BomError(Exception):
    """Base exception for all client errors."""


class BomConnectionError(BomError):
    """The BoM API could not be reached."""


class BomTimeoutError(BomConnectionError):
    """A request to the BoM API timed out."""


class BomResponseError(BomError):
    """The BoM API returned an unexpected HTTP status."""

    def __init__(self, message: str, *, status: int) -> None:
        """Initialise the error with the HTTP status code."""
        super().__init__(message)
        self.status = status


class BomNotFoundError(BomResponseError):
    """The requested resource (place, station, warning) does not exist."""


class BomRateLimitError(BomResponseError):
    """The BoM API is rate limiting requests."""

    def __init__(self, message: str, *, status: int, retry_after: int | None) -> None:
        """Initialise the error with the server supplied retry delay."""
        super().__init__(message, status=status)
        self.retry_after = retry_after


class BomParseError(BomError):
    """The BoM API returned data that could not be parsed."""
