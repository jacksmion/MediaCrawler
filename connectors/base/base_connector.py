from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from .models import (
    AuthContext,
    AuthResult,
    CommentsPage,
    ConnectorCapability,
    ConnectorContext,
    ContentDetailResult,
    CreatorContentsPage,
    CreatorResult,
    HealthStatus,
    SearchPage,
    SearchQuery,
)


class BaseConnector(ABC):
    """Base contract for platform-oriented connectors."""

    platform_code: str
    capabilities: ConnectorCapability

    def __init__(self, platform_code: str, capabilities: ConnectorCapability | None = None) -> None:
        self.platform_code = platform_code
        self.capabilities = capabilities or ConnectorCapability()

    @abstractmethod
    async def prepare(self, context: ConnectorContext) -> None:
        """Prepare runtime dependencies before crawling."""

    @abstractmethod
    async def authenticate(self, auth_context: AuthContext) -> AuthResult:
        """Authenticate or validate a reusable session."""

    @abstractmethod
    async def health_check(self) -> HealthStatus:
        """Return connector health before or during execution."""

    @abstractmethod
    async def search(self, query: SearchQuery) -> SearchPage:
        """Search platform content using a normalized query."""

    @abstractmethod
    async def fetch_content_detail(self, content_id: str, extra: dict[str, Any] | None = None) -> dict[str, Any] | ContentDetailResult:
        """Fetch a single content detail payload."""

    @abstractmethod
    async def fetch_comments(
        self,
        content_id: str,
        cursor: str | int | None = None,
        limit: int | None = None,
        extra: dict[str, Any] | None = None,
    ) -> dict[str, Any] | CommentsPage:
        """Fetch a page or batch of comments for a content item."""

    @abstractmethod
    async def fetch_creator(self, creator_id: str) -> dict[str, Any] | CreatorResult:
        """Fetch a creator profile."""

    @abstractmethod
    async def fetch_creator_contents(
        self,
        creator_id: str,
        cursor: str | int | None = None,
        limit: int | None = None,
    ) -> dict[str, Any] | CreatorContentsPage:
        """Fetch a creator's content list."""

    @abstractmethod
    async def close(self) -> None:
        """Release runtime resources."""
