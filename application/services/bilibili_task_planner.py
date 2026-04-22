from __future__ import annotations

import uuid

from schemas.tasks.models import CrawlTask
from schemas.tasks.requirements import BilibiliCrawlRequirement


class BilibiliTaskPlanner:
    """Build persisted crawl tasks from user-facing Bilibili requirements."""

    def plan(self, requirement: BilibiliCrawlRequirement) -> list[CrawlTask]:
        if requirement.mode == "search":
            return self._plan_search(requirement)
        if requirement.mode == "detail":
            return self._plan_detail(requirement)
        if requirement.mode == "creator":
            return self._plan_creator(requirement)
        raise ValueError(f"Unsupported Bilibili requirement mode: {requirement.mode}")

    def _plan_search(self, requirement: BilibiliCrawlRequirement) -> list[CrawlTask]:
        tasks: list[CrawlTask] = []
        keywords = [keyword.strip() for keyword in requirement.keywords if keyword.strip()]
        if not keywords:
            raise ValueError("Bilibili search requirement requires at least one keyword")
        for keyword in keywords:
            for page in range(requirement.start_page, requirement.start_page + requirement.max_pages):
                tasks.append(
                    self._new_task(
                        task_type="search",
                        params={"keyword": keyword, "page": page, "page_size": requirement.page_size},
                    )
                )
        return tasks

    def _plan_detail(self, requirement: BilibiliCrawlRequirement) -> list[CrawlTask]:
        video_ids = [video_id.strip() for video_id in requirement.video_ids if video_id.strip()]
        if not video_ids:
            raise ValueError("Bilibili detail requirement requires at least one video id")
        return [self._new_task(task_type="detail", params={"video_id": video_id}) for video_id in video_ids]

    def _plan_creator(self, requirement: BilibiliCrawlRequirement) -> list[CrawlTask]:
        tasks: list[CrawlTask] = []
        creator_ids = [creator_id.strip() for creator_id in requirement.creator_ids if creator_id.strip()]
        if not creator_ids:
            raise ValueError("Bilibili creator requirement requires at least one creator id")
        for creator_id in creator_ids:
            tasks.append(self._new_task(task_type="creator", params={"creator_id": creator_id}))
            for page in range(1, requirement.creator_max_pages + 1):
                tasks.append(
                    self._new_task(
                        task_type="creator_contents",
                        params={"creator_id": creator_id, "cursor": str(page), "limit": requirement.creator_contents_limit},
                    )
                )
        return tasks

    @staticmethod
    def _new_task(*, task_type: str, params: dict) -> CrawlTask:
        return CrawlTask(
            task_id=f"bili-plan-{task_type}-{uuid.uuid4().hex[:12]}",
            platform_code="bilibili",
            task_type=task_type,
            status="planned",
            params=params,
        )
