class ReaderError(Exception):
    """Base exception for community reader failures."""


class TargetError(ReaderError):
    """Raised before network access when a community URL is unsupported."""


class ParseError(ReaderError):
    """Raised when a community response does not have the expected structure."""


class FetchError(ReaderError):
    """Raised when a community response cannot be fetched."""


class RateLimited(FetchError):
    def __init__(self, site_name: str, retry_after: str | None = None) -> None:
        message = f"{site_name} rate limit"
        if retry_after:
            message += f" (Retry-After: {retry_after})"
        super().__init__(message)
        self.site_name = site_name
        self.retry_after = retry_after


class AccessBlocked(FetchError):
    """Raised when a community site blocks access to a request."""
