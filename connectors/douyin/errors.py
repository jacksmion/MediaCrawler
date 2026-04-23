class DouyinConnectorError(Exception):
    """Base error for the new-style Douyin connector."""


class DouyinDataFetchError(DouyinConnectorError):
    """Raised when the new Douyin connector cannot fetch or validate data."""


def classify_douyin_error(message: str) -> str:
    lowered = message.lower()
    if "user agent" in lowered or "browser state" in lowered:
        return "session_not_ready"
    if "status 4" in lowered or "status 5" in lowered:
        return "http_error"
    if "invalid payload" in lowered:
        return "invalid_payload"
    if "error payload" in lowered:
        return "platform_error_payload"
    if "a_bogus" in lowered or "sign" in lowered:
        return "signature_failed"
    return "unknown_error"
