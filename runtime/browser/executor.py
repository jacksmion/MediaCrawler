from __future__ import annotations

from typing import Any

from .models import BrowserState


class BrowserExecutor:
    """Thin abstraction over browser lifecycle and page state access."""

    def __init__(self) -> None:
        self.state = BrowserState()
        self._context: Any = None
        self._page: Any = None

    def bind(
        self,
        *,
        context: Any = None,
        page: Any = None,
        browser_type: str = "chromium",
        cdp_enabled: bool = False,
        headless: bool = True,
    ) -> None:
        """Bind an existing browser runtime during incremental migration."""
        self._context = context
        self._page = page
        self.state.browser_type = browser_type
        self.state.cdp_enabled = cdp_enabled
        self.state.headless = headless

    async def start(self) -> BrowserState:
        """Start or attach to a browser runtime."""
        return await self.snapshot()

    async def snapshot(self) -> BrowserState:
        """Return the latest known browser state snapshot."""
        if self._page is not None:
            try:
                self.state.user_agent = await self._page.evaluate("() => navigator.userAgent")
            except Exception:
                pass
            try:
                self.state.local_storage = await self._page.evaluate("() => window.localStorage")
            except Exception:
                pass
        if self._context is not None:
            try:
                self.state.cookies = await self._context.cookies()
            except Exception:
                pass
        return self.state

    async def evaluate(self, script: str) -> Any:
        """Evaluate a browser-side expression against the bound page."""
        if self._page is None:
            raise RuntimeError("No browser page is bound to the BrowserExecutor.")
        return await self._page.evaluate(script)

    @property
    def page(self) -> Any:
        return self._page

    @property
    def context(self) -> Any:
        return self._context

    async def close(self) -> None:
        """Close any managed browser resources."""
