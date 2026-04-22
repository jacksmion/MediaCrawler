from __future__ import annotations

import uuid
from typing import Any

from connectors.base.models import ConnectorContext
from connectors.kuaishou import build_kuaishou_connector_from_legacy
from connectors.kuaishou.errors import KuaishouDataFetchError
from connectors.kuaishou.normalizer import normalize_kuaishou_video, normalize_kuaishou_videos
from schemas.tasks.models import CrawlJobEvent, CrawlTask, RawRecord
from schemas.tasks.runtime import PlatformTaskRequest, PlatformTaskResult

from .crawl_state_service import CrawlStateService
from .event_service import EventService
from .normalized_content_service import NormalizedContentService
from .platform_task_service import PlatformTaskService
from .raw_record_service import RawRecordService


class KuaishouPlatformRunner:
    """Executes Kuaishou platform tasks through the new connector/task stack."""

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

    async def run_search_page(self, *, keyword: str, page: int, search_session_id: str = "") -> dict[str, Any]:
        job_id = f"ks-search-bridge-{uuid.uuid4().hex[:12]}"
        task = await self._create_task(
            task_id=f"ks-search-task-{uuid.uuid4().hex[:12]}",
            task_type="search",
            params={"keyword": keyword, "page": page, "search_session_id": search_session_id},
        )
        task_result = await self._execute_task(
            task=task,
            job_id=job_id,
            request=PlatformTaskRequest(
                job_id=job_id,
                platform_code="kuaishou",
                task_kind="search",
                payload={"keyword": keyword, "page": page, "filters": {"search_session_id": search_session_id}},
            ),
            failure_event_type="search_failed",
            failure_details={"keyword": keyword, "page": page},
        )
        video_items = task_result.payload.get("items", [])
        normalized_records = normalize_kuaishou_videos(video_items)
        await self.normalized_content_service.append_many(normalized_records)
        await self.raw_record_service.append(
            RawRecord(
                platform_code="kuaishou",
                record_type="search",
                source_uri="/graphql",
                request_meta={"keyword": keyword, "page": page, "job_id": job_id},
                response_body=task_result.payload.get("raw"),
                metadata={"bridge": "kuaishou_connector", "normalized_count": len(normalized_records)},
            )
        )
        await self.event_service.append(
            CrawlJobEvent(
                job_id=job_id,
                event_type="search_page_succeeded",
                message="Kuaishou bridge search page succeeded",
                details={"keyword": keyword, "page": page, "items_count": len(video_items)},
            ),
            platform_code="kuaishou",
        )
        return {"job_id": job_id, "task_id": task.task_id, **task_result.payload, "normalized_records": normalized_records}

    async def run_detail(self, *, video_id: str) -> dict[str, Any]:
        job_id = f"ks-detail-bridge-{uuid.uuid4().hex[:12]}"
        task = await self._create_task(
            task_id=f"ks-detail-task-{uuid.uuid4().hex[:12]}",
            task_type="detail",
            params={"video_id": video_id},
        )
        task_result = await self._execute_task(
            task=task,
            job_id=job_id,
            request=PlatformTaskRequest(
                job_id=job_id,
                platform_code="kuaishou",
                task_kind="detail",
                payload={"content_id": video_id},
            ),
            failure_event_type="detail_failed",
            failure_details={"video_id": video_id},
        )
        video = task_result.payload["video"]
        normalized_record = normalize_kuaishou_video(video)
        if normalized_record is not None:
            await self.normalized_content_service.append_many([normalized_record])
        await self.raw_record_service.append(
            RawRecord(
                platform_code="kuaishou",
                record_type="detail",
                source_uri=task_result.payload.get("request_uri", "/graphql"),
                request_meta={"video_id": video_id, "job_id": job_id},
                response_body=task_result.payload.get("raw_payload"),
                metadata={"bridge": "kuaishou_connector"},
            )
        )
        await self.event_service.append(
            CrawlJobEvent(
                job_id=job_id,
                event_type="detail_succeeded",
                message="Kuaishou bridge detail succeeded",
                details={"video_id": video_id},
            ),
            platform_code="kuaishou",
        )
        return {"job_id": job_id, "task_id": task.task_id, "video": video}

    async def run_comments(self, *, video_id: str, cursor: str = "", limit: int | None = None) -> dict[str, Any]:
        job_id = f"ks-comments-bridge-{uuid.uuid4().hex[:12]}"
        task = await self._create_task(
            task_id=f"ks-comments-task-{uuid.uuid4().hex[:12]}",
            task_type="comments",
            params={"video_id": video_id, "cursor": cursor, "limit": limit or 10},
        )
        task_result = await self._execute_task(
            task=task,
            job_id=job_id,
            request=PlatformTaskRequest(
                job_id=job_id,
                platform_code="kuaishou",
                task_kind="comments",
                payload={"content_id": video_id, "cursor": cursor, "limit": limit or 10},
            ),
            failure_event_type="comments_failed",
            failure_details={"video_id": video_id},
        )
        await self.raw_record_service.append(
            RawRecord(
                platform_code="kuaishou",
                record_type="comments",
                source_uri=task_result.payload.get("request_uri", "/rest/v/photo/comment/list"),
                request_meta={"video_id": video_id, "job_id": job_id},
                response_body=task_result.payload.get("raw_payload"),
                metadata={"bridge": "kuaishou_connector", "comment_count": len(task_result.payload.get("comments", []))},
            )
        )
        await self.event_service.append(
            CrawlJobEvent(
                job_id=job_id,
                event_type="comments_succeeded",
                message="Kuaishou bridge comments succeeded",
                details={"video_id": video_id, "comment_count": len(task_result.payload.get("comments", []))},
            ),
            platform_code="kuaishou",
        )
        return {"job_id": job_id, "task_id": task.task_id, **task_result.payload}

    async def run_creator(self, *, creator_id: str) -> dict[str, Any]:
        job_id = f"ks-creator-bridge-{uuid.uuid4().hex[:12]}"
        task = await self._create_task(
            task_id=f"ks-creator-task-{uuid.uuid4().hex[:12]}",
            task_type="creator",
            params={"creator_id": creator_id},
        )
        task_result = await self._execute_task(
            task=task,
            job_id=job_id,
            request=PlatformTaskRequest(
                job_id=job_id,
                platform_code="kuaishou",
                task_kind="creator",
                payload={"creator_id": creator_id},
            ),
            failure_event_type="creator_failed",
            failure_details={"creator_id": creator_id},
        )
        await self.raw_record_service.append(
            RawRecord(
                platform_code="kuaishou",
                record_type="creator",
                source_uri=task_result.payload.get("request_uri", "/graphql"),
                request_meta={"creator_id": creator_id, "job_id": job_id},
                response_body=task_result.payload.get("raw_payload"),
                metadata={"bridge": "kuaishou_connector"},
            )
        )
        await self.event_service.append(
            CrawlJobEvent(
                job_id=job_id,
                event_type="creator_succeeded",
                message="Kuaishou bridge creator succeeded",
                details={"creator_id": creator_id},
            ),
            platform_code="kuaishou",
        )
        return {"job_id": job_id, "task_id": task.task_id, **task_result.payload}

    async def run_creator_contents(self, *, creator_id: str, cursor: str = "", limit: int = 20) -> dict[str, Any]:
        job_id = f"ks-creator-contents-bridge-{uuid.uuid4().hex[:12]}"
        task = await self._create_task(
            task_id=f"ks-creator-contents-task-{uuid.uuid4().hex[:12]}",
            task_type="creator_contents",
            params={"creator_id": creator_id, "cursor": cursor, "limit": limit},
        )
        task_result = await self._execute_task(
            task=task,
            job_id=job_id,
            request=PlatformTaskRequest(
                job_id=job_id,
                platform_code="kuaishou",
                task_kind="creator_contents",
                payload={"creator_id": creator_id, "cursor": cursor, "limit": limit},
            ),
            failure_event_type="creator_contents_failed",
            failure_details={"creator_id": creator_id, "cursor": cursor},
        )
        video_items = task_result.payload.get("items", [])
        normalized_records = normalize_kuaishou_videos(video_items)
        await self.normalized_content_service.append_many(normalized_records)
        await self.raw_record_service.append(
            RawRecord(
                platform_code="kuaishou",
                record_type="creator_contents",
                source_uri=task_result.payload.get("request_uri", "/graphql"),
                request_meta={"creator_id": creator_id, "job_id": job_id, "cursor": cursor},
                response_body=task_result.payload.get("raw_payload"),
                metadata={"bridge": "kuaishou_connector", "normalized_count": len(normalized_records)},
            )
        )
        await self.event_service.append(
            CrawlJobEvent(
                job_id=job_id,
                event_type="creator_contents_succeeded",
                message="Kuaishou bridge creator contents succeeded",
                details={"creator_id": creator_id, "items_count": len(video_items)},
            ),
            platform_code="kuaishou",
        )
        return {"job_id": job_id, "task_id": task.task_id, **task_result.payload, "normalized_records": normalized_records}

    async def _create_task(self, *, task_id: str, task_type: str, params: dict[str, Any]) -> CrawlTask:
        return await self.crawl_state_service.create_task(
            task_id=task_id,
            platform_code="kuaishou",
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
    ) -> PlatformTaskResult:
        connector = build_kuaishou_connector_from_legacy(self.crawler)
        task_service = PlatformTaskService(connector)
        job = await self.crawl_state_service.create_job(job_id=job_id, task=task)
        await connector.prepare(
            ConnectorContext(
                account_id=None,
                proxy=getattr(self.crawler, "_platform_http_proxy", None),
                metadata={"source": "legacy_kuaishou_crawler", "job_id": job_id, "task_id": task.task_id},
            )
        )
        running_job = await self.crawl_state_service.mark_job_running(job)
        try:
            result = await task_service.execute(request)
            await self.crawl_state_service.append_result(result)
            await self.crawl_state_service.mark_job_succeeded(running_job, metrics=result.metrics)
            return result
        except KuaishouDataFetchError as exc:
            error_message = str(exc)
            failed_result = PlatformTaskResult(
                job_id=job_id,
                platform_code="kuaishou",
                task_kind=request.task_kind,
                success=False,
                payload={},
                metrics={},
                error_code=self._classify_error(error_message),
                error_message=error_message,
            )
            await self.event_service.append(
                CrawlJobEvent(
                    job_id=job_id,
                    event_type=failure_event_type,
                    message=error_message,
                    details={**failure_details, "risk_type": failed_result.error_code},
                ),
                platform_code="kuaishou",
            )
            await self.crawl_state_service.append_result(failed_result)
            await self.crawl_state_service.mark_job_failed(
                running_job,
                error_code=failed_result.error_code,
                error_message=error_message,
            )
            raise
        finally:
            await connector.close()

    @staticmethod
    def _classify_error(message: str) -> str:
        lowered = message.lower()
        if "cookie" in lowered or "auth" in lowered:
            return "session_not_ready"
        if "graphql" in lowered or "rest" in lowered:
            return "request_failed"
        if "missing" in lowered:
            return "invalid_payload"
        return "unknown_error"
