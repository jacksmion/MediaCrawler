from __future__ import annotations

from typing import Any
from collections.abc import Callable

from connectors.base.models import CommentsPage, ContentDetailResult, CreatorContentsPage, CreatorResult, SearchQuery
from schemas.tasks.models import CrawlTask
from schemas.tasks.runtime import PlatformTaskRequest, PlatformTaskResult

from connectors.base.base_connector import BaseConnector

from .state_store import StateStore


def _serialize_detail_payload(detail: dict[str, Any] | ContentDetailResult) -> dict[str, Any]:
    if isinstance(detail, ContentDetailResult):
        return detail.to_payload()
    return detail


def _serialize_comments_payload(comments: dict[str, Any] | CommentsPage) -> dict[str, Any]:
    if isinstance(comments, CommentsPage):
        return comments.to_payload()
    return comments


def _serialize_creator_payload(creator: dict[str, Any] | CreatorResult) -> dict[str, Any]:
    if isinstance(creator, CreatorResult):
        return creator.to_payload()
    return creator


def _serialize_creator_contents_payload(contents: dict[str, Any] | CreatorContentsPage) -> dict[str, Any]:
    if isinstance(contents, CreatorContentsPage):
        return contents.to_payload()
    return contents


def _extract_outcome(result_obj) -> dict[str, Any]:
    metadata = getattr(result_obj, "metadata", None)
    if isinstance(metadata, dict):
        return metadata.get("outcome", {})
    return {}


class TaskExecutor:
    platform_code: str

    def __init__(
        self,
        crawler,
        *,
        platform_code: str,
        connector: BaseConnector,
        connector_factory: Callable[[], BaseConnector],
        state_store: StateStore,
    ) -> None:
        self.crawler = crawler
        self.platform_code = platform_code
        self.connector = connector
        self.connector_factory = connector_factory
        self.state_store = state_store

    async def execute(self, task: CrawlTask) -> dict[str, Any]:
        if task.platform_code != self.platform_code:
            raise ValueError(f"Unsupported platform for {self.__class__.__name__}: {task.platform_code}")

        persisted_task = await self.state_store.create_task(
            task_id=task.task_id,
            platform_code=task.platform_code,
            task_type=task.task_type,
            params=task.params or {},
            schedule_type=task.schedule_type,
            priority=task.priority,
        )
        job_id = self.connector.make_job_id(task.task_type)
        request = self.connector.build_request(task, job_id)
        connector = self.connector_factory()
        job = await self.state_store.create_job(job_id=job_id, task=persisted_task)
        await connector.prepare(self.crawler._build_connector_context(job_id=job_id, task_id=persisted_task.task_id))
        started_event = self.connector.build_started_event(task, job_id)
        if started_event is not None:
            await self.state_store.append_event(started_event, platform_code=self.platform_code)
        running_job = await self.state_store.mark_job_running(job)
        try:
            result = await self._execute_platform_request(connector, request)
            await self.state_store.append_result(result)
            await self.state_store.mark_job_succeeded(running_job, metrics=result.metrics)
            if self.connector.use_generic_success_handling():
                payload = await self.state_store.process_task_outcome(
                    platform_code=self.platform_code,
                    job_id=job_id,
                    outcome=result.outcome,
                )
            else:
                payload = await self.connector.handle_success(
                    task=task,
                    request=request,
                    task_result=result,
                    job_id=job_id,
                    task_id=persisted_task.task_id,
                    services=self.state_store,
                )
            return {"job_id": job_id, "task_id": persisted_task.task_id, **payload}
        except self.connector.handled_exceptions as exc:  # type: ignore[misc]
            error_message = str(exc)
            error_code = self.connector.classify_error(error_message)
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
            failure_event = self.connector.build_failure_event(
                task=task,
                job_id=job_id,
                error_message=error_message,
                error_code=error_code,
            )
            await self.state_store.append_event(failure_event, platform_code=self.platform_code)
            await self.state_store.append_result(failed_result)
            await self.state_store.mark_job_failed(
                running_job,
                error_code=failed_result.error_code,
                error_message=error_message,
                metrics=failed_result.metrics,
            )
            raise
        finally:
            finished_event = self.connector.build_finished_event(task, job_id)
            if finished_event is not None:
                await self.state_store.append_event(finished_event, platform_code=self.platform_code)
            await connector.close()

    async def execute_many(self, tasks: list[CrawlTask]) -> list[dict[str, Any]]:
        results: list[dict[str, Any]] = []
        for task in tasks:
            results.append(await self.execute(task))
        return results

    async def execute_requirement(self, requirement: Any) -> dict[str, Any]:
        planned_tasks = self.connector.plan_requirement(requirement)
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
        targets = self.connector.collect_targets_from_results(base_results)
        return await self._execute_content_followups(targets, requirement)

    async def _execute_detail_followups(self, base_results: list[dict[str, Any]], requirement: Any) -> list[dict[str, Any]]:
        targets = self.connector.collect_targets_from_results(base_results)
        if not targets:
            targets = self.connector.collect_targets_from_requirement(requirement)
        return await self._execute_content_followups(targets, requirement, include_detail=False)

    async def _execute_creator_followups(self, base_results: list[dict[str, Any]], requirement: Any) -> list[dict[str, Any]]:
        targets = self.connector.collect_targets_from_results(base_results)
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
        unique_targets = self.connector.dedupe_targets(targets)
        if should_include_detail:
            for index, target in enumerate(unique_targets, start=1):
                followup_tasks.append(self.connector.build_detail_task(target, index))
        if requirement.include_comments:
            for index, target in enumerate(unique_targets, start=1):
                followup_tasks.append(self.connector.build_comments_task(target, index, requirement.comment_limit))
        if not followup_tasks:
            return []
        return await self.execute_many(followup_tasks)

    async def _execute_platform_request(self, connector: BaseConnector, request: PlatformTaskRequest) -> PlatformTaskResult:
        if request.task_kind == "search":
            query = SearchQuery(**request.payload)
            page = await connector.search(query)
            return PlatformTaskResult(
                job_id=request.job_id,
                platform_code=request.platform_code,
                task_kind=request.task_kind,
                success=True,
                payload={
                    "items": page.items,
                    "has_more": page.has_more,
                    "next_cursor": page.next_cursor,
                    "raw": page.raw,
                    "metadata": page.metadata,
                },
                outcome=_extract_outcome(page),
                metrics={"items_count": len(page.items), "has_more": int(page.has_more)},
            )
        if request.task_kind == "detail":
            content_id = str(request.payload["content_id"])
            detail = await connector.fetch_content_detail(content_id, extra=request.payload.get("extra"))
            return PlatformTaskResult(
                job_id=request.job_id,
                platform_code=request.platform_code,
                task_kind=request.task_kind,
                success=True,
                payload=_serialize_detail_payload(detail),
                outcome=_extract_outcome(detail),
                metrics={"detail_count": 1},
            )
        if request.task_kind == "comments":
            content_id = str(request.payload["content_id"])
            comments = await connector.fetch_comments(
                content_id=content_id,
                cursor=request.payload.get("cursor"),
                limit=request.payload.get("limit"),
                extra=request.payload.get("extra"),
            )
            comments_payload = _serialize_comments_payload(comments)
            return PlatformTaskResult(
                job_id=request.job_id,
                platform_code=request.platform_code,
                task_kind=request.task_kind,
                success=True,
                payload=comments_payload,
                outcome=_extract_outcome(comments),
                metrics={
                    "comment_count": len(comments_payload.get("comments", [])),
                    "has_more": int(bool(comments_payload.get("has_more"))),
                },
            )
        if request.task_kind == "creator":
            creator_id = str(request.payload["creator_id"])
            creator = await connector.fetch_creator(creator_id)
            return PlatformTaskResult(
                job_id=request.job_id,
                platform_code=request.platform_code,
                task_kind=request.task_kind,
                success=True,
                payload=_serialize_creator_payload(creator),
                outcome=_extract_outcome(creator),
                metrics={"creator_count": 1},
            )
        if request.task_kind == "creator_contents":
            creator_id = str(request.payload["creator_id"])
            contents = await connector.fetch_creator_contents(
                creator_id=creator_id,
                cursor=request.payload.get("cursor"),
                limit=request.payload.get("limit"),
            )
            contents_payload = _serialize_creator_contents_payload(contents)
            return PlatformTaskResult(
                job_id=request.job_id,
                platform_code=request.platform_code,
                task_kind=request.task_kind,
                success=True,
                payload=contents_payload,
                outcome=_extract_outcome(contents),
                metrics={
                    "items_count": len(contents_payload.get("items", [])),
                    "has_more": int(bool(contents_payload.get("has_more"))),
                },
            )
        raise ValueError(f"Unsupported task kind: {request.task_kind}")
