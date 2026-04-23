from __future__ import annotations

from abc import ABC, abstractmethod

from playwright.async_api import BrowserContext


class AbstractApiClient(ABC):
    @abstractmethod
    async def request(self, method, url, **kwargs):
        pass

    @abstractmethod
    async def update_cookies(self, browser_context: BrowserContext):
        pass
