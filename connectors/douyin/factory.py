from __future__ import annotations

from connectors.douyin.connector import DouyinConnector
from runtime.browser.executor import BrowserExecutor
from runtime.http.executor import HttpExecutor
from runtime.hybrid.executor import HybridExecutor
from runtime.session.service import SessionService
from runtime.signing.douyin_signer import DouyinSigner


def build_douyin_connector_from_legacy(crawler) -> DouyinConnector:
    """Create a new-style Douyin connector by binding legacy crawler state."""
    browser_executor = BrowserExecutor()
    browser_executor.bind(
        context=getattr(crawler, "browser_context", None),
        page=getattr(crawler, "context_page", None),
        browser_type="chromium",
        cdp_enabled=bool(getattr(crawler, "cdp_manager", None)),
        headless=False,
    )
    http_executor = HttpExecutor(proxy=getattr(crawler, "_platform_http_proxy", None))
    hybrid_executor = HybridExecutor(browser_executor, http_executor)
    session_service = SessionService(platform_code="douyin")
    signer = DouyinSigner(session_service)
    return DouyinConnector(
        hybrid_executor=hybrid_executor,
        session_service=session_service,
        signer=signer,
    )

