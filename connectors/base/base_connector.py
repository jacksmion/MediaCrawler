from __future__ import annotations

import uuid
from abc import ABC, abstractmethod
from typing import Any

from schemas.tasks.models import CrawlJobEvent, CrawlTask
from schemas.tasks.runtime import PlatformTaskRequest, PlatformTaskResult

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
    short_code: str = ""
    source_name: str = ""
    handled_exceptions: tuple[type[Exception], ...] = (Exception,)

    def __init__(self, platform_code: str, capabilities: ConnectorCapability | None = None) -> None:
        self.platform_code = platform_code
        self.capabilities = capabilities or ConnectorCapability()

    def make_job_id(self, task_type: str) -> str:
        short_code = self.short_code or self.platform_code
        return f"{short_code}-{task_type}-bridge-{uuid.uuid4().hex[:12]}"

    def build_started_event(self, task: CrawlTask, job_id: str) -> CrawlJobEvent | None:
        return None

    def build_finished_event(self, task: CrawlTask, job_id: str) -> CrawlJobEvent | None:
        return None

    def use_generic_success_handling(self) -> bool:
        return False

    def dedupe_targets(self, targets: list[Any]) -> list[Any]:
        return targets

    def new_task(self, *, task_type: str, params: dict[str, Any]) -> CrawlTask:
        short_code = self.short_code or self.platform_code
        return CrawlTask(
            task_id=f"{short_code}-plan-{task_type}-{uuid.uuid4().hex[:12]}",
            platform_code=self.platform_code,
            task_type=task_type,
            status="planned",
            params=params,
        )

    def build_request(self, task: CrawlTask, job_id: str) -> PlatformTaskRequest:
        raise NotImplementedError

    def classify_error(self, message: str) -> str:
        raise NotImplementedError

    def build_failure_event(self, *, task: CrawlTask, job_id: str, error_message: str, error_code: str) -> CrawlJobEvent:
        raise NotImplementedError

    def plan_requirement(self, requirement: Any) -> list[CrawlTask]:
        raise NotImplementedError

    def collect_targets_from_results(self, results: list[dict[str, Any]]) -> list[Any]:
        raise NotImplementedError

    def collect_targets_from_requirement(self, requirement: Any) -> list[Any]:
        raise NotImplementedError

    def build_detail_task(self, target: Any, index: int) -> CrawlTask:
        raise NotImplementedError

    def build_comments_task(self, target: Any, index: int, comment_limit: int | None) -> CrawlTask:
        raise NotImplementedError

    async def handle_success(
        self,
        *,
        task: CrawlTask,
        request: PlatformTaskRequest,
        task_result: PlatformTaskResult,
        job_id: str,
        task_id: str,
        services: Any,
    ) -> dict[str, Any]:
        raise NotImplementedError(
            f"{self.__class__.__name__} does not implement handle_success(); "
            "enable generic success handling or provide a connector-specific implementation."
        )

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
