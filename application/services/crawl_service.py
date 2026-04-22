from __future__ import annotations

from typing import Any

from connectors.base.base_connector import BaseConnector
from connectors.base.models import SearchPage, SearchQuery


class CrawlService:
    """Coordinates connector calls without binding to legacy crawler flows."""

    def __init__(self, connector: BaseConnector) -> None:
        self.connector = connector

    async def run_search(self, query: SearchQuery) -> SearchPage:
        """Execute a search flow through the configured connector."""
        return await self.connector.search(query)

    async def run_detail(self, content_id: str, extra: dict[str, Any] | None = None) -> dict[str, Any]:
        """Fetch a single content detail record."""
        return await self.connector.fetch_content_detail(content_id, extra=extra)

