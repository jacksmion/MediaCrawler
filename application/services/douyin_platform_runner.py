from __future__ import annotations

import uuid
from typing import Any

import config
from connectors.base.models import ConnectorContext
from connectors.douyin import build_douyin_connector_from_legacy
from connectors.douyin.errors import DouyinDataFetchError
from connectors.douyin.normalizer import normalize_aweme_detail, normalize_search_items
from schemas.tasks.models import CrawlJobEvent, CrawlTask, RawRecord
from schemas.tasks.runtime import PlatformTaskRequest, PlatformTaskResult

from .crawl_state_service import CrawlStateService
from .event_service import EventService
from .normalized_content_service import NormalizedContentService
from .platform_task_service import PlatformTaskService
from .raw_record_service import RawRecordService


class DouyinPlatformRunner:
    """Executes Douyin platform tasks through the new connector/task stack."""

    def __init__(
        self,
        crawler,
        *,
        crawl_state_service: CrawlStateService,
        event_service: EventService,
        normalized_content_service: NormalizedContentService,
        raw_record_service: RawRecordService,
    ) -> None:
        self.crawler = crawler
        self.crawl_state_service = crawl_state_service
        self.event_service = event_service
        self.normalized_content_service = normalized_content_service
        self.raw_record_service = raw_record_service

    async def run_search_page(
        self,
        *,
        keyword: str,
        page: int,
        search_id: str,
        page_size: int = 15,
        publish_time: str | None = None,
        sort_type: str | None = None,
    ) -> dict[str, Any]:
        """Execute a single Douyin search page through the platform task flow."""
        job_id = f"dy-search-bridge-{uuid.uuid4().hex[:12]}"
        task = await self._create_task(
            task_id=f"dy-search-task-{uuid.uuid4().hex[:12]}",
            task_type="search",
            params={
                "keyword": keyword,
                "page": page,
                "search_id": search_id,
                "page_size": page_size,
                "publish_time": publish_time or str(config.PUBLISH_TIME_TYPE),
                "sort_type": sort_type or str(config.SEARCH_SORT_TYPE),
            },
        )
        task_result = await self._execute_task(
            task=task,
            job_id=job_id,
            request=PlatformTaskRequest(
                job_id=job_id,
                platform_code="douyin",
                task_kind="search",
                payload={
                    "keyword": keyword,
                    "page": page,
                    "page_size": page_size,
                    "cursor": search_id,
                    "filters": {
                        "publish_time": publish_time or str(config.PUBLISH_TIME_TYPE),
                        "sort_type": sort_type or str(config.SEARCH_SORT_TYPE),
                        "search_id": search_id,
                    },
                },
            ),
            started_event=CrawlJobEvent(
                job_id=job_id,
                event_type="bridge_search_started",
                message="Douyin search bridge started",
                details={"keyword": keyword, "page": page},
            ),
            finished_event=CrawlJobEvent(
                job_id=job_id,
                event_type="bridge_search_finished",
                message="Douyin search bridge finished",
                details={},
            ),
            failure_event_type="search_failed",
            failure_details={"keyword": keyword, "page": page, "search_id": search_id},
        )
        search_payload = task_result.payload
        search_items = search_payload.get("items", [])
        normalized_records = normalize_search_items(search_items)
        await self.normalized_content_service.append_many(normalized_records)
        if search_payload.get("raw"):
            await self.raw_record_service.append(
                RawRecord(
                    platform_code="douyin",
                    record_type="search",
                    source_uri="/aweme/v1/web/general/search/single/",
                    request_meta={
                        "keyword": keyword,
                        "page": page,
                        "search_id": search_id,
                        "job_id": job_id,
                    },
                    response_body=search_payload.get("raw"),
                    metadata={
                        "bridge": "douyin_connector",
                        "normalized_count": len(normalized_records),
                    },
                )
            )
        await self.event_service.append(
            CrawlJobEvent(
                job_id=job_id,
                event_type="search_page_succeeded",
                message="Douyin bridge search page succeeded",
                details={
                    "keyword": keyword,
                    "page": page,
                    "items_count": len(search_items),
                    "normalized_count": len(normalized_records),
                    "next_cursor": search_payload.get("next_cursor"),
                },
            ),
            platform_code="douyin",
        )
        return {
            "job_id": job_id,
            "task_id": task.task_id,
            "items": search_items,
            "normalized_records": normalized_records,
            "next_cursor": search_payload.get("next_cursor"),
            "raw": search_payload.get("raw"),
        }

    async def run_detail(self, *, aweme_id: str) -> dict[str, Any]:
        """Execute a Douyin detail task through the platform task flow."""
        job_id = f"dy-detail-bridge-{uuid.uuid4().hex[:12]}"
        task = await self._create_task(
            task_id=f"dy-detail-task-{uuid.uuid4().hex[:12]}",
            task_type="detail",
            params={"aweme_id": aweme_id},
        )
        task_result = await self._execute_task(
            task=task,
            job_id=job_id,
            request=PlatformTaskRequest(
                job_id=job_id,
                platform_code="douyin",
                task_kind="detail",
                payload={"content_id": aweme_id},
            ),
            failure_event_type="detail_failed",
            failure_details={"aweme_id": aweme_id},
        )
        detail_result = task_result.payload
        aweme_detail = detail_result["aweme_detail"]
        normalized_record = normalize_aweme_detail(aweme_detail)
        if normalized_record is not None:
            await self.normalized_content_service.append_many([normalized_record])
        raw_payload = detail_result.get("raw_payload")
        if raw_payload:
            await self.raw_record_service.append(
                RawRecord(
                    platform_code="douyin",
                    record_type="detail",
                    source_uri=detail_result.get("request_uri", "/aweme/v1/web/aweme/detail/"),
                    request_meta={
                        "aweme_id": aweme_id,
                        "job_id": job_id,
                        "request_params": detail_result.get("request_params", {}),
                    },
                    response_body=raw_payload,
                    metadata={
                        "bridge": "douyin_connector",
                        "normalized_count": 1 if normalized_record is not None else 0,
                    },
                )
            )
        await self.event_service.append(
            CrawlJobEvent(
                job_id=job_id,
                event_type="detail_succeeded",
                message="Douyin bridge detail succeeded",
                details={"aweme_id": aweme_id},
            ),
            platform_code="douyin",
        )
        return {
            "job_id": job_id,
            "task_id": task.task_id,
            "aweme_detail": aweme_detail,
            "normalized_record": normalized_record,
        }

    async def run_comments(
        self,
        *,
        aweme_id: str,
        cursor: int | str = 0,
        limit: int | None = None,
    ) -> dict[str, Any]:
        """Execute a Douyin comments task through the platform task flow."""
        comments_limit = limit or config.CRAWLER_MAX_COMMENTS_COUNT_SINGLENOTES
        job_id = f"dy-comments-bridge-{uuid.uuid4().hex[:12]}"
        task = await self._create_task(
            task_id=f"dy-comments-task-{uuid.uuid4().hex[:12]}",
            task_type="comments",
            params={"aweme_id": aweme_id, "cursor": cursor, "limit": comments_limit},
        )
        task_result = await self._execute_task(
            task=task,
            job_id=job_id,
            request=PlatformTaskRequest(
                job_id=job_id,
                platform_code="douyin",
                task_kind="comments",
                payload={
                    "content_id": aweme_id,
                    "cursor": cursor,
                    "limit": comments_limit,
                },
            ),
            failure_event_type="comments_failed",
            failure_details={"aweme_id": aweme_id},
        )
        comment_result = task_result.payload
        await self.raw_record_service.append(
            RawRecord(
                platform_code="douyin",
                record_type="comments",
                source_uri=comment_result.get("request_uri", "/aweme/v1/web/comment/list/"),
                request_meta={
                    "aweme_id": aweme_id,
                    "job_id": job_id,
                    "limit": comments_limit,
                    "cursor": cursor,
                },
                response_body=comment_result,
                metadata={
                    "bridge": "douyin_connector",
                    "comment_count": len(comment_result.get("comments", [])),
                    "cursor": comment_result.get("cursor"),
                    "has_more": comment_result.get("has_more"),
                },
            )
        )
        await self.event_service.append(
            CrawlJobEvent(
                job_id=job_id,
                event_type="comments_succeeded",
                message="Douyin bridge comments succeeded",
                details={
                    "aweme_id": aweme_id,
                    "comment_count": len(comment_result.get("comments", [])),
                },
            ),
            platform_code="douyin",
        )
        return {"job_id": job_id, "task_id": task.task_id, **comment_result}

    async def run_creator(self, *, creator_id: str) -> dict[str, Any]:
        """Execute a Douyin creator-profile task through the platform task flow."""
        job_id = f"dy-creator-bridge-{uuid.uuid4().hex[:12]}"
        task = await self._create_task(
            task_id=f"dy-creator-task-{uuid.uuid4().hex[:12]}",
            task_type="creator",
            params={"creator_id": creator_id},
        )
        task_result = await self._execute_task(
            task=task,
            job_id=job_id,
            request=PlatformTaskRequest(
                job_id=job_id,
                platform_code="douyin",
                task_kind="creator",
                payload={"creator_id": creator_id},
            ),
            failure_event_type="creator_failed",
            failure_details={"creator_id": creator_id},
        )
        creator_result = task_result.payload
        raw_payload = creator_result.get("creator")
        if raw_payload:
            await self.raw_record_service.append(
                RawRecord(
                    platform_code="douyin",
                    record_type="creator",
                    source_uri=creator_result.get("request_uri", "/aweme/v1/web/user/profile/other/"),
                    request_meta={
                        "creator_id": creator_id,
                        "job_id": job_id,
                        "request_params": creator_result.get("request_params", {}),
                    },
                    response_body=raw_payload,
                    metadata={"bridge": "douyin_connector"},
                )
            )
        await self.event_service.append(
            CrawlJobEvent(
                job_id=job_id,
                event_type="creator_succeeded",
                message="Douyin bridge creator succeeded",
                details={"creator_id": creator_id},
            ),
            platform_code="douyin",
        )
        return {"job_id": job_id, "task_id": task.task_id, **creator_result}

    async def run_creator_contents(
        self,
        *,
        creator_id: str,
        cursor: str | None = "",
        limit: int = 18,
    ) -> dict[str, Any]:
        """Execute a Douyin creator-contents task through the platform task flow."""
        job_id = f"dy-creator-posts-bridge-{uuid.uuid4().hex[:12]}"
        task = await self._create_task(
            task_id=f"dy-creator-contents-task-{uuid.uuid4().hex[:12]}",
            task_type="creator_contents",
            params={"creator_id": creator_id, "cursor": cursor or "", "limit": limit},
        )
        task_result = await self._execute_task(
            task=task,
            job_id=job_id,
            request=PlatformTaskRequest(
                job_id=job_id,
                platform_code="douyin",
                task_kind="creator_contents",
                payload={
                    "creator_id": creator_id,
                    "cursor": cursor or "",
                    "limit": limit,
                },
            ),
            failure_event_type="creator_contents_failed",
            failure_details={"creator_id": creator_id, "cursor": cursor or ""},
        )
        contents_result = task_result.payload
        items = contents_result.get("items", [])
        normalized_records = []
        for item in items:
            record = normalize_aweme_detail(item)
            if record is not None:
                normalized_records.append(record)
        await self.normalized_content_service.append_many(normalized_records)
        raw_payload = contents_result.get("raw_payload")
        if raw_payload:
            await self.raw_record_service.append(
                RawRecord(
                    platform_code="douyin",
                    record_type="creator_contents",
                    source_uri=contents_result.get("request_uri", "/aweme/v1/web/aweme/post/"),
                    request_meta={
                        "creator_id": creator_id,
                        "job_id": job_id,
                        "cursor": cursor or "",
                        "request_params": contents_result.get("request_params", {}),
                    },
                    response_body=raw_payload,
                    metadata={
                        "bridge": "douyin_connector",
                        "normalized_count": len(normalized_records),
                    },
                )
            )
        await self.event_service.append(
            CrawlJobEvent(
                job_id=job_id,
                event_type="creator_contents_succeeded",
                message="Douyin bridge creator contents succeeded",
                details={
                    "creator_id": creator_id,
                    "items_count": len(items),
                    "next_cursor": contents_result.get("next_cursor"),
                },
            ),
            platform_code="douyin",
        )
        return {
            "job_id": job_id,
            "task_id": task.task_id,
            **contents_result,
            "normalized_records": normalized_records,
        }

    async def _create_task(self, *, task_id: str, task_type: str, params: dict[str, Any]) -> CrawlTask:
        """Create a persisted manual task snapshot for a platform runner execution."""
        return await self.crawl_state_service.create_task(
            task_id=task_id,
            platform_code="douyin",
            task_type=task_type,
            params=params,
        )

    async def _execute_task(
        self,
        *,
        task: CrawlTask,
        job_id: str,
        request: PlatformTaskRequest,
        failure_event_type: str,
        failure_details: dict[str, Any],
        started_event: CrawlJobEvent | None = None,
        finished_event: CrawlJobEvent | None = None,
    ) -> PlatformTaskResult:
        """Execute a platform task with persisted job lifecycle snapshots."""
        connector = build_douyin_connector_from_legacy(self.crawler)
        task_service = PlatformTaskService(connector)
        job = await self.crawl_state_service.create_job(job_id=job_id, task=task)
        await connector.prepare(
            ConnectorContext(
                account_id=None,
                proxy=getattr(self.crawler, "_platform_http_proxy", None),
                metadata={"source": "legacy_douyin_crawler", "job_id": job_id, "task_id": task.task_id},
            )
        )
        if started_event is not None:
            await self.event_service.append(started_event, platform_code="douyin")
        running_job = await self.crawl_state_service.mark_job_running(job)
        try:
            result = await task_service.execute(request)
            await self.crawl_state_service.append_result(result)
            await self.crawl_state_service.mark_job_succeeded(running_job, metrics=result.metrics)
            return result
        except DouyinDataFetchError as exc:
            error_message = str(exc)
            await self.event_service.append(
                CrawlJobEvent(
                    job_id=job_id,
                    event_type=failure_event_type,
                    message=error_message,
                    details={**failure_details, "risk_type": self._classify_error(error_message)},
                ),
                platform_code="douyin",
            )
            failed_result = PlatformTaskResult(
                job_id=job_id,
                platform_code="douyin",
                task_kind=request.task_kind,
                success=False,
                payload={},
                metrics={},
                error_code=self._classify_error(error_message),
                error_message=error_message,
            )
            await self.crawl_state_service.append_result(failed_result)
            await self.crawl_state_service.mark_job_failed(
                running_job,
                error_code=failed_result.error_code,
                error_message=error_message,
                metrics=failed_result.metrics,
            )
            raise
        finally:
            if finished_event is not None:
                await self.event_service.append(finished_event, platform_code="douyin")
            await connector.close()

    @staticmethod
    def _classify_error(message: str) -> str:
        """Map runner errors to coarse risk categories for future monitoring."""
        lowered = message.lower()
        if "user agent" in lowered or "browser state" in lowered:
            return "session_not_ready"
        if "status 4" in lowered or "status 5" in lowered:
            return "http_error"
        if "invalid payload" in lowered:
            return "invalid_payload"
        if "error payload" in lowered:
            return "platform_error_payload"
        if "a_bogus" in lowered or "sign" in lowered:
            return "signature_failed"
        return "unknown_error"
