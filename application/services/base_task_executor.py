from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from schemas.tasks.models import CrawlTask
from schemas.tasks.runtime import PlatformTaskResult

from connectors.base.execution import BasePlatformHooks, ExecutionServices

from .platform_outcome_service import PlatformOutcomeService
from .platform_task_service import PlatformTaskService


class BaseTaskExecutor(ABC):
    platform_code: str

    def __init__(self, crawler, *, planner, hooks: BasePlatformHooks, services: ExecutionServices) -> None:
        self.crawler = crawler
        self.planner = planner
        self.hooks = hooks
        self.services = services

    async def execute(self, task: CrawlTask) -> dict[str, Any]:
        if task.platform_code != self.platform_code:
            raise ValueError(f"Unsupported platform for {self.__class__.__name__}: {task.platform_code}")

        persisted_task = await self.services.crawl_state_service.create_task(
            task_id=task.task_id,
            platform_code=task.platform_code,
            task_type=task.task_type,
            params=task.params or {},
            schedule_type=task.schedule_type,
            priority=task.priority,
        )
        job_id = self.hooks.make_job_id(task.task_type)
        request = self.hooks.build_request(task, job_id)
        connector = self.hooks.build_connector()
        task_service = PlatformTaskService(connector)
        job = await self.services.crawl_state_service.create_job(job_id=job_id, task=persisted_task)
        await connector.prepare(self.hooks.build_connector_context(job_id=job_id, task_id=persisted_task.task_id))
        started_event = self.hooks.build_started_event(task, job_id)
        if started_event is not None:
            await self.services.event_service.append(started_event, platform_code=self.platform_code)
        running_job = await self.services.crawl_state_service.mark_job_running(job)
        try:
            result = await task_service.execute(request)
            await self.services.crawl_state_service.append_result(result)
            await self.services.crawl_state_service.mark_job_succeeded(running_job, metrics=result.metrics)
            if self.hooks.use_generic_success_handling():
                payload = await PlatformOutcomeService.process_task_outcome(
                    self.services,
                    platform_code=self.platform_code,
                    job_id=job_id,
                    outcome=result.outcome,
                )
            else:
                payload = await self.hooks.handle_success(
                    task=task,
                    request=request,
                    task_result=result,
                    job_id=job_id,
                    task_id=persisted_task.task_id,
                    services=self.services,
                )
            return {"job_id": job_id, "task_id": persisted_task.task_id, **payload}
        except self.hooks.handled_exceptions as exc:  # type: ignore[misc]
            error_message = str(exc)
            error_code = self.hooks.classify_error(error_message)
            failed_result = PlatformTaskResult(
                job_id=job_id,
                platform_code=self.platform_code,
                task_kind=request.task_kind,
                success=False,
                payload={},
                metrics={},
                error_code=error_code,
                error_message=error_message,
            )
            failure_event = self.hooks.build_failure_event(
                task=task,
                job_id=job_id,
                error_message=error_message,
                error_code=error_code,
            )
            await self.services.event_service.append(failure_event, platform_code=self.platform_code)
            await self.services.crawl_state_service.append_result(failed_result)
            await self.services.crawl_state_service.mark_job_failed(
                running_job,
                error_code=failed_result.error_code,
                error_message=error_message,
                metrics=failed_result.metrics,
            )
            raise
        finally:
            finished_event = self.hooks.build_finished_event(task, job_id)
            if finished_event is not None:
                await self.services.event_service.append(finished_event, platform_code=self.platform_code)
            await connector.close()

    async def execute_many(self, tasks: list[CrawlTask]) -> list[dict[str, Any]]:
        results: list[dict[str, Any]] = []
        for task in tasks:
            results.append(await self.execute(task))
        return results

    async def execute_requirement(self, requirement: Any) -> dict[str, Any]:
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

    async def _execute_search_followups(self, base_results: list[dict[str, Any]], requirement: Any) -> list[dict[str, Any]]:
        targets = self._collect_targets_from_results(base_results)
        return await self._execute_content_followups(targets, requirement)

    async def _execute_detail_followups(self, base_results: list[dict[str, Any]], requirement: Any) -> list[dict[str, Any]]:
        targets = self._collect_targets_from_results(base_results)
        if not targets:
            targets = self._collect_targets_from_requirement(requirement)
        return await self._execute_content_followups(targets, requirement, include_detail=False)

    async def _execute_creator_followups(self, base_results: list[dict[str, Any]], requirement: Any) -> list[dict[str, Any]]:
        targets = self._collect_targets_from_results(base_results)
        return await self._execute_content_followups(targets, requirement)

    async def _execute_content_followups(
        self,
        targets: list[Any],
        requirement: Any,
        *,
        include_detail: bool | None = None,
    ) -> list[dict[str, Any]]:
        followup_tasks: list[CrawlTask] = []
        should_include_detail = requirement.include_detail if include_detail is None else include_detail
        unique_targets = self._dedupe_targets(targets)
        if should_include_detail:
            for index, target in enumerate(unique_targets, start=1):
                followup_tasks.append(self._build_detail_task(target, index))
        if requirement.include_comments:
            for index, target in enumerate(unique_targets, start=1):
                followup_tasks.append(self._build_comments_task(target, index, requirement.comment_limit))
        if not followup_tasks:
            return []
        return await self.execute_many(followup_tasks)

    def _dedupe_targets(self, targets: list[Any]) -> list[Any]:
        return targets

    @abstractmethod
    def _collect_targets_from_results(self, results: list[dict[str, Any]]) -> list[Any]:
        raise NotImplementedError

    @abstractmethod
    def _collect_targets_from_requirement(self, requirement: Any) -> list[Any]:
        raise NotImplementedError

    @abstractmethod
    def _build_detail_task(self, target: Any, index: int) -> CrawlTask:
        raise NotImplementedError

    @abstractmethod
    def _build_comments_task(self, target: Any, index: int, comment_limit: int | None) -> CrawlTask:
        raise NotImplementedError
