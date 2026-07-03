class ReaderError(Exception):
    """Base exception for FMKorea reader failures."""


class ParseError(ReaderError):
    """Raised when an FMKorea response does not have the expected structure."""


class FetchError(ReaderError):
    """Raised when an FMKorea response cannot be fetched."""


class RateLimited(FetchError):
    def __init__(self, retry_after: str | None = None) -> None:
        super().__init__("FMKorea request was rate limited")
        self.retry_after = retry_after


class AccessBlocked(FetchError):
    """Raised when FMKorea blocks access to a request."""
