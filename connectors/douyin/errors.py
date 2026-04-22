class DouyinConnectorError(Exception):
    """Base error for the new-style Douyin connector."""


class DouyinDataFetchError(DouyinConnectorError):
    """Raised when the new Douyin connector cannot fetch or validate data."""

