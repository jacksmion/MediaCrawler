from __future__ import annotations

from typing import Any

from application.platform_hooks import ExecutionServices, KuaishouPlatformHooks
from schemas.tasks.models import CrawlTask

from .base_task_executor import BaseTaskExecutor, UnsupportedRequirementPlanner


class KuaishouTaskExecutor(BaseTaskExecutor):
    platform_code = "kuaishou"

    def __init__(self, crawler, *, crawl_state_service, event_service, normalized_content_service, raw_record_service) -> None:
        super().__init__(
            crawler,
            planner=UnsupportedRequirementPlanner(self.platform_code),
            hooks=KuaishouPlatformHooks(crawler),
            services=ExecutionServices(crawl_state_service=crawl_state_service, event_service=event_service, normalized_content_service=normalized_content_service, raw_record_service=raw_record_service),
        )

    def _collect_targets_from_results(self, results: list[dict[str, Any]]) -> list[Any]:
        return []

    def _collect_targets_from_requirement(self, requirement: Any) -> list[Any]:
        return []

    def _build_detail_task(self, target: Any, index: int) -> CrawlTask:
        raise NotImplementedError

    def _build_comments_task(self, target: Any, index: int, comment_limit: int | None) -> CrawlTask:
        raise NotImplementedError
