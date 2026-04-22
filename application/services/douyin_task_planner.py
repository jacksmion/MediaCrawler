from __future__ import annotations

import uuid

from schemas.tasks.models import CrawlTask
from schemas.tasks.requirements import DouyinCrawlRequirement


class DouyinTaskPlanner:
    """Builds persisted crawl tasks from user-facing Douyin crawl requirements."""

    def plan(self, requirement: DouyinCrawlRequirement) -> list[CrawlTask]:
        """Expand a requirement into one or more crawl tasks."""
        if requirement.mode == "search":
            return self._plan_search(requirement)
        if requirement.mode == "detail":
            return self._plan_detail(requirement)
        if requirement.mode == "creator":
            return self._plan_creator(requirement)
        raise ValueError(f"Unsupported Douyin requirement mode: {requirement.mode}")

    def _plan_search(self, requirement: DouyinCrawlRequirement) -> list[CrawlTask]:
        tasks: list[CrawlTask] = []
        keywords = [keyword.strip() for keyword in requirement.keywords if keyword.strip()]
        if not keywords:
            raise ValueError("Douyin search requirement requires at least one keyword")
        for keyword in keywords:
            for page in range(requirement.start_page, requirement.start_page + requirement.max_pages):
                tasks.append(
                    self._new_task(
                        task_type="search",
                        params={
                            "keyword": keyword,
                            "page": page,
                            "search_id": "",
                            "page_size": requirement.page_size,
                            "publish_time": requirement.publish_time,
                            "sort_type": requirement.sort_type,
                        },
                    )
                )
        return tasks

    def _plan_detail(self, requirement: DouyinCrawlRequirement) -> list[CrawlTask]:
        aweme_ids = [aweme_id.strip() for aweme_id in requirement.aweme_ids if aweme_id.strip()]
        if not aweme_ids:
            raise ValueError("Douyin detail requirement requires at least one aweme_id")
        return [
            self._new_task(
                task_type="detail",
                params={"aweme_id": aweme_id},
            )
            for aweme_id in aweme_ids
        ]

    def _plan_creator(self, requirement: DouyinCrawlRequirement) -> list[CrawlTask]:
        tasks: list[CrawlTask] = []
        creator_ids = [creator_id.strip() for creator_id in requirement.creator_ids if creator_id.strip()]
        if not creator_ids:
            raise ValueError("Douyin creator requirement requires at least one creator_id")
        for creator_id in creator_ids:
            tasks.append(self._new_task(task_type="creator", params={"creator_id": creator_id}))
            for _ in range(requirement.creator_max_pages):
                tasks.append(
                    self._new_task(
                        task_type="creator_contents",
                        params={
                            "creator_id": creator_id,
                            "cursor": "",
                            "limit": requirement.creator_contents_limit,
                        },
                    )
                )
        return tasks

    @staticmethod
    def _new_task(*, task_type: str, params: dict) -> CrawlTask:
        task_id = f"dy-plan-{task_type}-{uuid.uuid4().hex[:12]}"
        return CrawlTask(
            task_id=task_id,
            platform_code="douyin",
            task_type=task_type,
            status="planned",
            params=params,
        )
