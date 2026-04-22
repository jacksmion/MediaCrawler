from __future__ import annotations

import uuid
from typing import Any

from connectors.base.models import ConnectorContext
from connectors.bilibili import build_bilibili_connector_from_legacy
from connectors.bilibili.errors import BilibiliDataFetchError
from connectors.bilibili.normalizer import normalize_bilibili_video, normalize_bilibili_videos
from schemas.tasks.models import CrawlJobEvent, CrawlTask, RawRecord
from schemas.tasks.runtime import PlatformTaskRequest, PlatformTaskResult

from .crawl_state_service import CrawlStateService
from .event_service import EventService
from .normalized_content_service import NormalizedContentService
from .platform_task_service import PlatformTaskService
from .raw_record_service import RawRecordService


class BilibiliPlatformRunner:
    """Executes Bilibili platform tasks through the new connector/task stack."""

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

    async def run_search_page(self, *, keyword: str, page: int, page_size: int = 20) -> dict[str, Any]:
        job_id = f"bili-search-bridge-{uuid.uuid4().hex[:12]}"
        task = await self._create_task(
            task_id=f"bili-search-task-{uuid.uuid4().hex[:12]}",
            task_type="search",
            params={"keyword": keyword, "page": page, "page_size": page_size},
        )
        task_result = await self._execute_task(
            task=task,
            job_id=job_id,
            request=PlatformTaskRequest(
                job_id=job_id,
                platform_code="bilibili",
                task_kind="search",
                payload={"keyword": keyword, "page": page, "page_size": page_size},
            ),
            failure_event_type="search_failed",
            failure_details={"keyword": keyword, "page": page},
        )
        await self.raw_record_service.append(
            RawRecord(
                platform_code="bilibili",
                record_type="search",
                source_uri="/x/web-interface/wbi/search/type",
                request_meta={"keyword": keyword, "page": page, "job_id": job_id},
                response_body=task_result.payload.get("raw"),
                metadata={"bridge": "bilibili_connector", "items_count": len(task_result.payload.get("items", []))},
            )
        )
        await self.event_service.append(
            CrawlJobEvent(
                job_id=job_id,
                event_type="search_page_succeeded",
                message="Bilibili bridge search page succeeded",
                details={"keyword": keyword, "page": page, "items_count": len(task_result.payload.get("items", []))},
            ),
            platform_code="bilibili",
        )
        return {"job_id": job_id, "task_id": task.task_id, **task_result.payload}

    async def run_detail(self, *, content_id: str, bvid: str = "") -> dict[str, Any]:
        job_id = f"bili-detail-bridge-{uuid.uuid4().hex[:12]}"
        task = await self._create_task(
            task_id=f"bili-detail-task-{uuid.uuid4().hex[:12]}",
            task_type="detail",
            params={"content_id": content_id, "bvid": bvid},
        )
        task_result = await self._execute_task(
            task=task,
            job_id=job_id,
            request=PlatformTaskRequest(
                job_id=job_id,
                platform_code="bilibili",
                task_kind="detail",
                payload={"content_id": content_id, "extra": {"bvid": bvid}},
            ),
            failure_event_type="detail_failed",
            failure_details={"content_id": content_id, "bvid": bvid},
        )
        video = task_result.payload["video"]
        normalized_record = normalize_bilibili_video(video)
        if normalized_record is not None:
            await self.normalized_content_service.append_many([normalized_record])
        await self.raw_record_service.append(
            RawRecord(
                platform_code="bilibili",
                record_type="detail",
                source_uri=task_result.payload.get("request_uri", "/x/web-interface/view/detail"),
                request_meta={"content_id": content_id, "bvid": bvid, "job_id": job_id},
                response_body=task_result.payload.get("raw_payload"),
                metadata={"bridge": "bilibili_connector"},
            )
        )
        await self.event_service.append(
            CrawlJobEvent(
                job_id=job_id,
                event_type="detail_succeeded",
                message="Bilibili bridge detail succeeded",
                details={"content_id": content_id, "bvid": bvid},
            ),
            platform_code="bilibili",
        )
        return {"job_id": job_id, "task_id": task.task_id, "video": video}

    async def run_comments(self, *, content_id: str, cursor: int | str = 0, limit: int | None = None) -> dict[str, Any]:
        job_id = f"bili-comments-bridge-{uuid.uuid4().hex[:12]}"
        task = await self._create_task(
            task_id=f"bili-comments-task-{uuid.uuid4().hex[:12]}",
            task_type="comments",
            params={"content_id": content_id, "cursor": cursor, "limit": limit or 10},
        )
        task_result = await self._execute_task(
            task=task,
            job_id=job_id,
            request=PlatformTaskRequest(
                job_id=job_id,
                platform_code="bilibili",
                task_kind="comments",
                payload={"content_id": content_id, "cursor": cursor, "limit": limit or 10},
            ),
            failure_event_type="comments_failed",
            failure_details={"content_id": content_id},
        )
        await self.raw_record_service.append(
            RawRecord(
                platform_code="bilibili",
                record_type="comments",
                source_uri=task_result.payload.get("request_uri", "/x/v2/reply/wbi/main"),
                request_meta={"content_id": content_id, "job_id": job_id},
                response_body=task_result.payload.get("raw_payload"),
                metadata={"bridge": "bilibili_connector", "comment_count": len(task_result.payload.get("comments", []))},
            )
        )
        await self.event_service.append(
            CrawlJobEvent(
                job_id=job_id,
                event_type="comments_succeeded",
                message="Bilibili bridge comments succeeded",
                details={"content_id": content_id, "comment_count": len(task_result.payload.get("comments", []))},
            ),
            platform_code="bilibili",
        )
        return {"job_id": job_id, "task_id": task.task_id, **task_result.payload}

    async def run_creator(self, *, creator_id: str) -> dict[str, Any]:
        job_id = f"bili-creator-bridge-{uuid.uuid4().hex[:12]}"
        task = await self._create_task(
            task_id=f"bili-creator-task-{uuid.uuid4().hex[:12]}",
            task_type="creator",
            params={"creator_id": creator_id},
        )
        task_result = await self._execute_task(
            task=task,
            job_id=job_id,
            request=PlatformTaskRequest(
                job_id=job_id,
                platform_code="bilibili",
                task_kind="creator",
                payload={"creator_id": creator_id},
            ),
            failure_event_type="creator_failed",
            failure_details={"creator_id": creator_id},
        )
        await self.raw_record_service.append(
            RawRecord(
                platform_code="bilibili",
                record_type="creator",
                source_uri=task_result.payload.get("request_uri", "/x/space/wbi/acc/info"),
                request_meta={"creator_id": creator_id, "job_id": job_id},
                response_body=task_result.payload.get("raw_payload"),
                metadata={"bridge": "bilibili_connector"},
            )
        )
        await self.event_service.append(
            CrawlJobEvent(
                job_id=job_id,
                event_type="creator_succeeded",
                message="Bilibili bridge creator succeeded",
                details={"creator_id": creator_id},
            ),
            platform_code="bilibili",
        )
        return {"job_id": job_id, "task_id": task.task_id, **task_result.payload}

    async def run_creator_contents(self, *, creator_id: str, cursor: str = "", limit: int = 30) -> dict[str, Any]:
        job_id = f"bili-creator-contents-bridge-{uuid.uuid4().hex[:12]}"
        task = await self._create_task(
            task_id=f"bili-creator-contents-task-{uuid.uuid4().hex[:12]}",
            task_type="creator_contents",
            params={"creator_id": creator_id, "cursor": cursor, "limit": limit},
        )
        task_result = await self._execute_task(
            task=task,
            job_id=job_id,
            request=PlatformTaskRequest(
                job_id=job_id,
                platform_code="bilibili",
                task_kind="creator_contents",
                payload={"creator_id": creator_id, "cursor": cursor, "limit": limit},
            ),
            failure_event_type="creator_contents_failed",
            failure_details={"creator_id": creator_id, "cursor": cursor},
        )
        video_items = task_result.payload.get("items", [])
        normalized_records = normalize_bilibili_videos(video_items)
        await self.normalized_content_service.append_many(normalized_records)
        await self.raw_record_service.append(
            RawRecord(
                platform_code="bilibili",
                record_type="creator_contents",
                source_uri=task_result.payload.get("request_uri", "/x/space/wbi/arc/search"),
                request_meta={"creator_id": creator_id, "job_id": job_id, "cursor": cursor},
                response_body=task_result.payload.get("raw_payload"),
                metadata={"bridge": "bilibili_connector", "normalized_count": len(normalized_records)},
            )
        )
        await self.event_service.append(
            CrawlJobEvent(
                job_id=job_id,
                event_type="creator_contents_succeeded",
                message="Bilibili bridge creator contents succeeded",
                details={"creator_id": creator_id, "items_count": len(video_items)},
            ),
            platform_code="bilibili",
        )
        return {"job_id": job_id, "task_id": task.task_id, **task_result.payload, "normalized_records": normalized_records}

    async def _create_task(self, *, task_id: str, task_type: str, params: dict[str, Any]) -> CrawlTask:
        return await self.crawl_state_service.create_task(
            task_id=task_id,
            platform_code="bilibili",
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
        connector = build_bilibili_connector_from_legacy(self.crawler)
        task_service = PlatformTaskService(connector)
        job = await self.crawl_state_service.create_job(job_id=job_id, task=task)
        await connector.prepare(
            ConnectorContext(
                account_id=None,
                proxy=getattr(self.crawler, "_platform_http_proxy", None),
                metadata={"source": "legacy_bilibili_crawler", "job_id": job_id, "task_id": task.task_id},
            )
        )
        running_job = await self.crawl_state_service.mark_job_running(job)
        try:
            result = await task_service.execute(request)
            await self.crawl_state_service.append_result(result)
            await self.crawl_state_service.mark_job_succeeded(running_job, metrics=result.metrics)
            return result
        except BilibiliDataFetchError as exc:
            error_message = str(exc)
            failed_result = PlatformTaskResult(
                job_id=job_id,
                platform_code="bilibili",
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
                platform_code="bilibili",
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
        if "sessdata" in lowered or "browser" in lowered:
            return "session_not_ready"
        if "status 4" in lowered or "status 5" in lowered:
            return "http_error"
        if "missing" in lowered:
            return "invalid_payload"
        return "unknown_error"
