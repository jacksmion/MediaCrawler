from __future__ import annotations

import uuid

from schemas.tasks.models import CrawlTask
from schemas.tasks.requirements import WeiboCrawlRequirement


class WeiboTaskPlanner:
    """Builds persisted crawl tasks from user-facing Weibo requirements."""

    def plan(self, requirement: WeiboCrawlRequirement) -> list[CrawlTask]:
        if requirement.mode == "search":
            return self._plan_search(requirement)
        if requirement.mode == "detail":
            return self._plan_detail(requirement)
        if requirement.mode == "creator":
            return self._plan_creator(requirement)
        raise ValueError(f"Unsupported Weibo requirement mode: {requirement.mode}")

    def _plan_search(self, requirement: WeiboCrawlRequirement) -> list[CrawlTask]:
        tasks: list[CrawlTask] = []
        keywords = [keyword.strip() for keyword in requirement.keywords if keyword.strip()]
        if not keywords:
            raise ValueError("Weibo search requirement requires at least one keyword")
        search_type = requirement.search_type or "default"
        for keyword in keywords:
            for page in range(requirement.start_page, requirement.start_page + requirement.max_pages):
                tasks.append(
                    self._new_task(
                        task_type="search",
                        params={"keyword": keyword, "page": page, "search_type": search_type},
                    )
                )
        return tasks

    def _plan_detail(self, requirement: WeiboCrawlRequirement) -> list[CrawlTask]:
        note_ids = [note_id.strip() for note_id in requirement.note_ids if note_id.strip()]
        if not note_ids:
            raise ValueError("Weibo detail requirement requires at least one note id")
        return [self._new_task(task_type="detail", params={"note_id": note_id}) for note_id in note_ids]

    def _plan_creator(self, requirement: WeiboCrawlRequirement) -> list[CrawlTask]:
        tasks: list[CrawlTask] = []
        creator_ids = [creator_id.strip() for creator_id in requirement.creator_ids if creator_id.strip()]
        if not creator_ids:
            raise ValueError("Weibo creator requirement requires at least one creator id")
        for creator_id in creator_ids:
            tasks.append(self._new_task(task_type="creator", params={"creator_id": creator_id}))
            for _ in range(requirement.creator_max_pages):
                tasks.append(
                    self._new_task(
                        task_type="creator_contents",
                        params={"creator_id": creator_id, "cursor": "", "limit": requirement.creator_contents_limit},
                    )
                )
        return tasks

    @staticmethod
    def _new_task(*, task_type: str, params: dict) -> CrawlTask:
        task_id = f"wb-plan-{task_type}-{uuid.uuid4().hex[:12]}"
        return CrawlTask(
            task_id=task_id,
            platform_code="weibo",
            task_type=task_type,
            status="planned",
            params=params,
        )
