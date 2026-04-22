from __future__ import annotations

import uuid

from schemas.tasks.models import CrawlTask
from schemas.tasks.requirements import XhsCrawlRequirement


class XhsTaskPlanner:
    """Builds persisted crawl tasks from user-facing Xiaohongshu requirements."""

    def plan(self, requirement: XhsCrawlRequirement) -> list[CrawlTask]:
        if requirement.mode == "search":
            return self._plan_search(requirement)
        if requirement.mode == "detail":
            return self._plan_detail(requirement)
        if requirement.mode == "creator":
            return self._plan_creator(requirement)
        raise ValueError(f"Unsupported XHS requirement mode: {requirement.mode}")

    def _plan_search(self, requirement: XhsCrawlRequirement) -> list[CrawlTask]:
        tasks: list[CrawlTask] = []
        keywords = [keyword.strip() for keyword in requirement.keywords if keyword.strip()]
        if not keywords:
            raise ValueError("XHS search requirement requires at least one keyword")
        sort_type = requirement.sort_type or "general"
        for keyword in keywords:
            for page in range(requirement.start_page, requirement.start_page + requirement.max_pages):
                tasks.append(
                    self._new_task(
                        task_type="search",
                        params={
                            "keyword": keyword,
                            "page": page,
                            "page_size": requirement.page_size,
                            "sort_type": sort_type,
                        },
                    )
                )
        return tasks

    def _plan_detail(self, requirement: XhsCrawlRequirement) -> list[CrawlTask]:
        note_urls = [note_url.strip() for note_url in requirement.note_urls if note_url.strip()]
        if not note_urls:
            raise ValueError("XHS detail requirement requires at least one note url")
        return [
            self._new_task(
                task_type="detail",
                params={"note_url": note_url},
            )
            for note_url in note_urls
        ]

    def _plan_creator(self, requirement: XhsCrawlRequirement) -> list[CrawlTask]:
        tasks: list[CrawlTask] = []
        creator_urls = [creator_url.strip() for creator_url in requirement.creator_urls if creator_url.strip()]
        if not creator_urls:
            raise ValueError("XHS creator requirement requires at least one creator url")
        for creator_url in creator_urls:
            tasks.append(self._new_task(task_type="creator", params={"creator_url": creator_url}))
            for _ in range(requirement.creator_max_pages):
                tasks.append(
                    self._new_task(
                        task_type="creator_contents",
                        params={
                            "creator_url": creator_url,
                            "cursor": "",
                            "limit": requirement.creator_contents_limit,
                        },
                    )
                )
        return tasks

    @staticmethod
    def _new_task(*, task_type: str, params: dict) -> CrawlTask:
        task_id = f"xhs-plan-{task_type}-{uuid.uuid4().hex[:12]}"
        return CrawlTask(
            task_id=task_id,
            platform_code="xhs",
            task_type=task_type,
            status="planned",
            params=params,
        )
