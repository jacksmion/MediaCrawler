from __future__ import annotations

from connectors.kuaishou.connector import KuaishouConnector
from runtime.browser.executor import BrowserExecutor
from runtime.http.executor import HttpExecutor
from runtime.session.service import SessionService


def build_kuaishou_connector_from_legacy(crawler) -> KuaishouConnector:
    """Create a new-style Kuaishou connector by binding legacy crawler state."""
    browser_executor = BrowserExecutor()
    browser_executor.bind(
        context=getattr(crawler, "browser_context", None),
        page=getattr(crawler, "context_page", None),
        browser_type="chromium",
        cdp_enabled=bool(getattr(crawler, "cdp_manager", None)),
        headless=False,
    )
    http_executor = HttpExecutor(proxy=getattr(crawler, "_platform_http_proxy", None))
    session_service = SessionService(platform_code="kuaishou")
    return KuaishouConnector(
        browser_executor=browser_executor,
        http_executor=http_executor,
        session_service=session_service,
    )
