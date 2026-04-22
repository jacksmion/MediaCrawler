from __future__ import annotations

from runtime.browser.executor import BrowserExecutor
from runtime.http.executor import HttpExecutor
from runtime.http.models import HttpRequest, HttpResponse


class HybridExecutor:
    """Combines browser state access with HTTP execution for high-risk platforms."""

    def __init__(self, browser_executor: BrowserExecutor, http_executor: HttpExecutor) -> None:
        self.browser_executor = browser_executor
        self.http_executor = http_executor

    async def browser_snapshot(self):
        """Read state from the managed browser layer."""
        return await self.browser_executor.snapshot()

    async def send(self, request: HttpRequest) -> HttpResponse:
        """Send HTTP requests while relying on browser state for pre-processing."""
        return await self.http_executor.send(request)

    async def close(self) -> None:
        await self.browser_executor.close()

