from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Optional

from playwright.async_api import BrowserContext, BrowserType, Playwright


class AbstractCrawler(ABC):
    @abstractmethod
    async def start(self):
        pass

    @abstractmethod
    async def search(self):
        pass

    @abstractmethod
    async def launch_browser(
        self,
        chromium: BrowserType,
        playwright_proxy: Optional[dict],
        user_agent: Optional[str],
        headless: bool = True,
    ) -> BrowserContext:
        pass

    async def launch_browser_with_cdp(
        self,
        playwright: Playwright,
        playwright_proxy: Optional[dict],
        user_agent: Optional[str],
        headless: bool = True,
    ) -> BrowserContext:
        return await self.launch_browser(playwright.chromium, playwright_proxy, user_agent, headless)

    @abstractmethod
    async def close(self) -> None:
        pass
