from __future__ import annotations

from connectors.xhs.connector import XhsConnector
from runtime.browser.executor import BrowserExecutor
from runtime.session.service import SessionService


def build_xhs_connector_from_legacy(crawler) -> XhsConnector:
    """Create a new-style XHS connector by binding legacy crawler state."""
    browser_executor = BrowserExecutor()
    browser_executor.bind(
        context=getattr(crawler, "browser_context", None),
        page=getattr(crawler, "context_page", None),
        browser_type="chromium",
        cdp_enabled=bool(getattr(crawler, "cdp_manager", None)),
        headless=False,
    )
    session_service = SessionService(platform_code="xhs")
    return XhsConnector(
        browser_executor=browser_executor,
        session_service=session_service,
        legacy_client=getattr(crawler, "xhs_client", None),
    )
