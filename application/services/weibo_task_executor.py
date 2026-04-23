from __future__ import annotations

from typing import Any

from connectors.base.execution import ExecutionServices
from connectors.weibo.execution import WeiboPlatformHooks

from schemas.tasks.models import CrawlTask
from schemas.tasks.requirements import WeiboCrawlRequirement

from .base_task_executor import BaseTaskExecutor
from .weibo_task_planner import WeiboTaskPlanner


class WeiboTaskExecutor(BaseTaskExecutor):
    """Dispatches persisted Weibo crawl tasks through the shared execution stack."""

    platform_code = "weibo"

    def __init__(
        self,
        crawler,
        *,
        crawl_state_service,
        event_service,
        normalized_content_service,
        raw_record_service,
        planner: WeiboTaskPlanner | None = None,
    ) -> None:
        super().__init__(
            crawler,
            planner=planner or WeiboTaskPlanner(),
            hooks=WeiboPlatformHooks(crawler),
            services=ExecutionServices(
                crawl_state_service=crawl_state_service,
                event_service=event_service,
                normalized_content_service=normalized_content_service,
                raw_record_service=raw_record_service,
            ),
        )

    def _collect_targets_from_results(self, results: list[dict[str, Any]]) -> list[str]:
        note_ids: list[str] = []
        for result in results:
            note = result.get("note")
            if isinstance(note, dict):
                mblog = note.get("mblog")
                if isinstance(mblog, dict) and mblog.get("id"):
                    note_ids.append(str(mblog["id"]))
            for item in result.get("items", []):
                if isinstance(item, dict):
                    mblog = item.get("mblog")
                    if isinstance(mblog, dict) and mblog.get("id"):
                        note_ids.append(str(mblog["id"]))
        return note_ids

    def _collect_targets_from_requirement(self, requirement: WeiboCrawlRequirement) -> list[str]:
        return [note_id.strip() for note_id in requirement.note_ids if note_id.strip()]

    def _build_detail_task(self, target: str, index: int) -> CrawlTask:
        return CrawlTask(
            task_id=f"wb-followup-detail-{index}",
            platform_code=self.platform_code,
            task_type="detail",
            status="planned",
            params={"note_id": target},
        )

    def _build_comments_task(self, target: str, index: int, comment_limit: int | None) -> CrawlTask:
        return CrawlTask(
            task_id=f"wb-followup-comments-{index}",
            platform_code=self.platform_code,
            task_type="comments",
            status="planned",
            params={"note_id": target, "cursor": -1, "limit": comment_limit},
        )

    def _dedupe_targets(self, targets: list[str]) -> list[str]:
        return list(dict.fromkeys([target for target in targets if target]))
