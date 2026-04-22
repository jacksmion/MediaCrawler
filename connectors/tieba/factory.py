from __future__ import annotations

from connectors.tieba.connector import TiebaConnector
from runtime.browser.executor import BrowserExecutor
from runtime.session.service import SessionService


def build_tieba_connector_from_legacy(crawler) -> TiebaConnector:
    """Create a new-style Tieba connector by binding legacy crawler state."""
    browser_executor = BrowserExecutor()
    browser_executor.bind(
        context=getattr(crawler, "browser_context", None),
        page=getattr(crawler, "context_page", None),
        browser_type="chromium",
        cdp_enabled=bool(getattr(crawler, "cdp_manager", None)),
        headless=False,
    )
    session_service = SessionService(platform_code="tieba")
    return TiebaConnector(
        browser_executor=browser_executor,
        session_service=session_service,
    )
