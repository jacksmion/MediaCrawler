from __future__ import annotations

from typing import Any

from application.platform_hooks import DouyinPlatformHooks, ExecutionServices

from schemas.tasks.models import CrawlTask
from schemas.tasks.requirements import DouyinCrawlRequirement

from .base_task_executor import BaseTaskExecutor
from .douyin_task_planner import DouyinTaskPlanner


class DouyinTaskExecutor(BaseTaskExecutor):
    """Dispatches persisted Douyin crawl tasks through the shared execution stack."""

    platform_code = "douyin"

    def __init__(
        self,
        crawler,
        *,
        crawl_state_service,
        event_service,
        normalized_content_service,
        raw_record_service,
        planner: DouyinTaskPlanner | None = None,
    ) -> None:
        super().__init__(
            crawler,
            planner=planner or DouyinTaskPlanner(),
            hooks=DouyinPlatformHooks(crawler),
            services=ExecutionServices(
                crawl_state_service=crawl_state_service,
                event_service=event_service,
                normalized_content_service=normalized_content_service,
                raw_record_service=raw_record_service,
            ),
        )

    def _collect_targets_from_results(self, results: list[dict[str, Any]]) -> list[str]:
        aweme_ids: list[str] = []
        for result in results:
            if "aweme_detail" in result and isinstance(result["aweme_detail"], dict):
                aweme_id = result["aweme_detail"].get("aweme_id")
                if aweme_id:
                    aweme_ids.append(str(aweme_id))
            for item in result.get("items", []):
                if isinstance(item, dict):
                    aweme_id = item.get("aweme_id")
                    if not aweme_id:
                        aweme_info = item.get("aweme_info")
                        if isinstance(aweme_info, dict):
                            aweme_id = aweme_info.get("aweme_id")
                    if aweme_id:
                        aweme_ids.append(str(aweme_id))
        return aweme_ids

    def _collect_targets_from_requirement(self, requirement: DouyinCrawlRequirement) -> list[str]:
        return [aweme_id.strip() for aweme_id in requirement.aweme_ids if aweme_id.strip()]

    def _build_detail_task(self, target: str, index: int) -> CrawlTask:
        return CrawlTask(
            task_id=f"dy-followup-detail-{index}",
            platform_code=self.platform_code,
            task_type="detail",
            status="planned",
            params={"aweme_id": target},
        )

    def _build_comments_task(self, target: str, index: int, comment_limit: int | None) -> CrawlTask:
        return CrawlTask(
            task_id=f"dy-followup-comments-{index}",
            platform_code=self.platform_code,
            task_type="comments",
            status="planned",
            params={"aweme_id": target, "cursor": 0, "limit": comment_limit},
        )

    def _dedupe_targets(self, targets: list[str]) -> list[str]:
        return list(dict.fromkeys([target for target in targets if target]))
