from __future__ import annotations

from typing import Any

from schemas.tasks.models import CrawlTask
from schemas.tasks.requirements import DouyinCrawlRequirement

from .douyin_platform_runner import DouyinPlatformRunner
from .douyin_task_planner import DouyinTaskPlanner


class DouyinTaskExecutor:
    """Dispatches persisted Douyin crawl tasks into the platform runner."""

    def __init__(self, runner: DouyinPlatformRunner, planner: DouyinTaskPlanner | None = None) -> None:
        self.runner = runner
        self.planner = planner or DouyinTaskPlanner()

    async def execute(self, task: CrawlTask) -> dict[str, Any]:
        """Execute one persisted Douyin task based on its task type and params."""
        if task.platform_code != "douyin":
            raise ValueError(f"Unsupported platform for DouyinTaskExecutor: {task.platform_code}")

        task_type = task.task_type
        params = task.params or {}
        if task_type == "search":
            return await self.runner.run_search_page(
                keyword=str(params["keyword"]),
                page=int(params.get("page", 1)),
                search_id=str(params.get("search_id", "")),
                page_size=int(params.get("page_size", 15)),
                publish_time=self._optional_str(params.get("publish_time")),
                sort_type=self._optional_str(params.get("sort_type")),
            )
        if task_type == "detail":
            aweme_id = str(params.get("aweme_id") or params.get("content_id") or "")
            if not aweme_id:
                raise ValueError("Douyin detail task requires aweme_id or content_id")
            return await self.runner.run_detail(aweme_id=aweme_id)
        if task_type == "comments":
            aweme_id = str(params.get("aweme_id") or params.get("content_id") or "")
            if not aweme_id:
                raise ValueError("Douyin comments task requires aweme_id or content_id")
            return await self.runner.run_comments(
                aweme_id=aweme_id,
                cursor=params.get("cursor", 0),
                limit=self._optional_int(params.get("limit")),
            )
        if task_type == "creator":
            creator_id = str(params.get("creator_id") or "")
            if not creator_id:
                raise ValueError("Douyin creator task requires creator_id")
            return await self.runner.run_creator(creator_id=creator_id)
        if task_type == "creator_contents":
            creator_id = str(params.get("creator_id") or "")
            if not creator_id:
                raise ValueError("Douyin creator_contents task requires creator_id")
            return await self.runner.run_creator_contents(
                creator_id=creator_id,
                cursor=self._optional_str(params.get("cursor")) or "",
                limit=int(params.get("limit", 18)),
            )
        raise ValueError(f"Unsupported Douyin task type: {task_type}")

    async def execute_many(self, tasks: list[CrawlTask]) -> list[dict[str, Any]]:
        """Execute multiple persisted Douyin tasks sequentially."""
        results: list[dict[str, Any]] = []
        for task in tasks:
            results.append(await self.execute(task))
        return results

    async def execute_requirement(self, requirement: DouyinCrawlRequirement) -> dict[str, Any]:
        """Plan and execute Douyin crawl work from a user-facing requirement."""
        planned_tasks = self.planner.plan(requirement)
        base_results = await self.execute_many(planned_tasks)

        if requirement.mode == "search":
            derived_results = await self._execute_search_followups(base_results, requirement)
        elif requirement.mode == "detail":
            derived_results = await self._execute_detail_followups(base_results, requirement)
        elif requirement.mode == "creator":
            derived_results = await self._execute_creator_followups(base_results, requirement)
        else:
            derived_results = []

        return {
            "planned_task_count": len(planned_tasks),
            "planned_tasks": planned_tasks,
            "base_results": base_results,
            "derived_results": derived_results,
        }

    async def _execute_search_followups(
        self,
        base_results: list[dict[str, Any]],
        requirement: DouyinCrawlRequirement,
    ) -> list[dict[str, Any]]:
        aweme_ids = self._collect_aweme_ids_from_results(base_results)
        return await self._execute_content_followups(aweme_ids, requirement)

    async def _execute_detail_followups(
        self,
        base_results: list[dict[str, Any]],
        requirement: DouyinCrawlRequirement,
    ) -> list[dict[str, Any]]:
        aweme_ids = self._collect_aweme_ids_from_results(base_results)
        if not aweme_ids:
            aweme_ids = [aweme_id.strip() for aweme_id in requirement.aweme_ids if aweme_id.strip()]
        return await self._execute_content_followups(aweme_ids, requirement, include_detail=False)

    async def _execute_creator_followups(
        self,
        base_results: list[dict[str, Any]],
        requirement: DouyinCrawlRequirement,
    ) -> list[dict[str, Any]]:
        aweme_ids = self._collect_aweme_ids_from_results(base_results)
        return await self._execute_content_followups(aweme_ids, requirement)

    async def _execute_content_followups(
        self,
        aweme_ids: list[str],
        requirement: DouyinCrawlRequirement,
        *,
        include_detail: bool | None = None,
    ) -> list[dict[str, Any]]:
        followup_tasks: list[CrawlTask] = []
        should_include_detail = requirement.include_detail if include_detail is None else include_detail
        unique_aweme_ids = list(dict.fromkeys([aweme_id for aweme_id in aweme_ids if aweme_id]))
        if should_include_detail:
            followup_tasks.extend(
                CrawlTask(
                    task_id=f"dy-followup-detail-{index}",
                    platform_code="douyin",
                    task_type="detail",
                    status="planned",
                    params={"aweme_id": aweme_id},
                )
                for index, aweme_id in enumerate(unique_aweme_ids, start=1)
            )
        if requirement.include_comments:
            followup_tasks.extend(
                CrawlTask(
                    task_id=f"dy-followup-comments-{index}",
                    platform_code="douyin",
                    task_type="comments",
                    status="planned",
                    params={
                        "aweme_id": aweme_id,
                        "cursor": 0,
                        "limit": requirement.comment_limit,
                    },
                )
                for index, aweme_id in enumerate(unique_aweme_ids, start=1)
            )
        if not followup_tasks:
            return []
        return await self.execute_many(followup_tasks)

    @staticmethod
    def _collect_aweme_ids_from_results(results: list[dict[str, Any]]) -> list[str]:
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

    @staticmethod
    def _optional_int(value: Any) -> int | None:
        if value in (None, ""):
            return None
        return int(value)

    @staticmethod
    def _optional_str(value: Any) -> str | None:
        if value in (None, ""):
            return None
        return str(value)
