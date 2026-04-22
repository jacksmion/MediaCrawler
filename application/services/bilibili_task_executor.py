from __future__ import annotations

from typing import Any

from application.platform_hooks import BilibiliPlatformHooks, ExecutionServices
from media_platform.bilibili.help import parse_video_info_from_url
from schemas.tasks.models import CrawlTask
from schemas.tasks.requirements import BilibiliCrawlRequirement

from .base_task_executor import BaseTaskExecutor
from .bilibili_task_planner import BilibiliTaskPlanner


class BilibiliTaskExecutor(BaseTaskExecutor):
    platform_code = "bilibili"

    def __init__(self, crawler, *, crawl_state_service, event_service, normalized_content_service, raw_record_service, planner: BilibiliTaskPlanner | None = None) -> None:
        super().__init__(
            crawler,
            planner=planner or BilibiliTaskPlanner(),
            hooks=BilibiliPlatformHooks(crawler),
            services=ExecutionServices(crawl_state_service=crawl_state_service, event_service=event_service, normalized_content_service=normalized_content_service, raw_record_service=raw_record_service),
        )

    def _collect_targets_from_results(self, results: list[dict[str, Any]]) -> list[dict[str, str]]:
        targets: list[dict[str, str]] = []
        for result in results:
            video = result.get("video")
            if isinstance(video, dict):
                view = video.get("View", {})
                content_id = str(view.get("aid") or video.get("aid") or "")
                bvid = str(view.get("bvid") or video.get("bvid") or "")
                if content_id or bvid:
                    targets.append({"content_id": content_id, "bvid": bvid})
            for item in result.get("items", []):
                if isinstance(item, dict):
                    view = item.get("View", {})
                    content_id = str(view.get("aid") or item.get("aid") or "")
                    bvid = str(view.get("bvid") or item.get("bvid") or "")
                    if content_id or bvid:
                        targets.append({"content_id": content_id, "bvid": bvid})
        return targets

    def _collect_targets_from_requirement(self, requirement: BilibiliCrawlRequirement) -> list[dict[str, str]]:
        targets: list[dict[str, str]] = []
        for video_id in requirement.video_ids:
            if not video_id.strip():
                continue
            video_info = parse_video_info_from_url(video_id)
            targets.append({"content_id": "", "bvid": video_info.video_id})
        return targets

    def _build_detail_task(self, target: dict[str, str], index: int) -> CrawlTask:
        return CrawlTask(
            task_id=f"bili-followup-detail-{index}",
            platform_code=self.platform_code,
            task_type="detail",
            status="planned",
            params={"content_id": target["content_id"], "bvid": target["bvid"]},
        )

    def _build_comments_task(self, target: dict[str, str], index: int, comment_limit: int | None) -> CrawlTask:
        return CrawlTask(
            task_id=f"bili-followup-comments-{index}",
            platform_code=self.platform_code,
            task_type="comments",
            status="planned",
            params={"content_id": target["content_id"], "bvid": target["bvid"], "limit": comment_limit},
        )

    def _dedupe_targets(self, targets: list[dict[str, str]]) -> list[dict[str, str]]:
        unique: list[dict[str, str]] = []
        seen: set[tuple[str, str]] = set()
        for target in targets:
            key = (target["content_id"], target["bvid"])
            if key in seen:
                continue
            seen.add(key)
            unique.append(target)
        return unique
