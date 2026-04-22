from __future__ import annotations

import uuid

from schemas.tasks.models import CrawlTask
from schemas.tasks.requirements import TiebaCrawlRequirement


class TiebaTaskPlanner:
    """Build persisted crawl tasks from user-facing Tieba requirements."""

    def plan(self, requirement: TiebaCrawlRequirement) -> list[CrawlTask]:
        if requirement.mode == "search":
            return self._plan_search(requirement)
        if requirement.mode == "detail":
            return self._plan_detail(requirement)
        if requirement.mode == "creator":
            return self._plan_creator(requirement)
        raise ValueError(f"Unsupported Tieba requirement mode: {requirement.mode}")

    def _plan_search(self, requirement: TiebaCrawlRequirement) -> list[CrawlTask]:
        tasks: list[CrawlTask] = []
        keywords = [keyword.strip() for keyword in requirement.keywords if keyword.strip()]
        if not keywords:
            raise ValueError("Tieba search requirement requires at least one keyword")
        for keyword in keywords:
            for page in range(requirement.start_page, requirement.start_page + requirement.max_pages):
                tasks.append(
                    self._new_task(
                        task_type="search",
                        params={"keyword": keyword, "page": page, "page_size": requirement.page_size},
                    )
                )
        return tasks

    def _plan_detail(self, requirement: TiebaCrawlRequirement) -> list[CrawlTask]:
        note_ids = [note_id.strip() for note_id in requirement.note_ids if note_id.strip()]
        if not note_ids:
            raise ValueError("Tieba detail requirement requires at least one note id")
        return [self._new_task(task_type="detail", params={"note_id": note_id}) for note_id in note_ids]

    def _plan_creator(self, requirement: TiebaCrawlRequirement) -> list[CrawlTask]:
        tasks: list[CrawlTask] = []
        creator_urls = [creator_url.strip() for creator_url in requirement.creator_urls if creator_url.strip()]
        if not creator_urls:
            raise ValueError("Tieba creator requirement requires at least one creator url")
        for creator_url in creator_urls:
            tasks.append(self._new_task(task_type="creator", params={"creator_url": creator_url}))
            for page in range(requirement.creator_max_pages):
                cursor = "" if page == 0 else str(page + 1)
                tasks.append(
                    self._new_task(
                        task_type="creator_contents",
                        params={"creator_url": creator_url, "cursor": cursor, "limit": requirement.creator_contents_limit},
                    )
                )
        return tasks

    @staticmethod
    def _new_task(*, task_type: str, params: dict) -> CrawlTask:
        return CrawlTask(
            task_id=f"tb-plan-{task_type}-{uuid.uuid4().hex[:12]}",
            platform_code="tieba",
            task_type=task_type,
            status="planned",
            params=params,
        )
