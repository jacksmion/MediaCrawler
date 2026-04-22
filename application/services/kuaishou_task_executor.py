from __future__ import annotations

from typing import Any

from application.platform_hooks import ExecutionServices, KuaishouPlatformHooks
from media_platform.kuaishou.help import parse_video_info_from_url
from schemas.tasks.models import CrawlTask
from schemas.tasks.requirements import KuaishouCrawlRequirement

from .base_task_executor import BaseTaskExecutor
from .kuaishou_task_planner import KuaishouTaskPlanner


class KuaishouTaskExecutor(BaseTaskExecutor):
    platform_code = "kuaishou"

    def __init__(self, crawler, *, crawl_state_service, event_service, normalized_content_service, raw_record_service, planner: KuaishouTaskPlanner | None = None) -> None:
        super().__init__(
            crawler,
            planner=planner or KuaishouTaskPlanner(),
            hooks=KuaishouPlatformHooks(crawler),
            services=ExecutionServices(crawl_state_service=crawl_state_service, event_service=event_service, normalized_content_service=normalized_content_service, raw_record_service=raw_record_service),
        )

    def _collect_targets_from_results(self, results: list[dict[str, Any]]) -> list[str]:
        targets: list[str] = []
        for result in results:
            video = result.get("video")
            if isinstance(video, dict):
                photo = video.get("photo", {})
                video_id = str(photo.get("id") or video.get("photoId") or "")
                if video_id:
                    targets.append(video_id)
            for item in result.get("items", []):
                if isinstance(item, dict):
                    photo = item.get("photo", {})
                    video_id = str(photo.get("id") or item.get("photoId") or "")
                    if video_id:
                        targets.append(video_id)
        return targets

    def _collect_targets_from_requirement(self, requirement: KuaishouCrawlRequirement) -> list[str]:
        targets: list[str] = []
        for video_id in requirement.video_ids:
            if not video_id.strip():
                continue
            video_info = parse_video_info_from_url(video_id)
            targets.append(video_info.video_id)
        return targets

    def _build_detail_task(self, target: str, index: int) -> CrawlTask:
        return CrawlTask(
            task_id=f"ks-followup-detail-{index}",
            platform_code=self.platform_code,
            task_type="detail",
            status="planned",
            params={"video_id": target},
        )

    def _build_comments_task(self, target: str, index: int, comment_limit: int | None) -> CrawlTask:
        return CrawlTask(
            task_id=f"ks-followup-comments-{index}",
            platform_code=self.platform_code,
            task_type="comments",
            status="planned",
            params={"video_id": target, "limit": comment_limit},
        )

    def _dedupe_targets(self, targets: list[str]) -> list[str]:
        unique: list[str] = []
        seen: set[str] = set()
        for target in targets:
            if target in seen:
                continue
            seen.add(target)
            unique.append(target)
        return unique
