from __future__ import annotations

import uuid
from typing import Any

from connectors.base.models import ConnectorContext
from connectors.weibo import build_weibo_connector_from_legacy
from connectors.weibo.errors import WeiboDataFetchError
from connectors.weibo.normalizer import normalize_weibo_note, normalize_weibo_notes
from schemas.tasks.models import CrawlJobEvent, CrawlTask, RawRecord
from schemas.tasks.runtime import PlatformTaskRequest, PlatformTaskResult

from .crawl_state_service import CrawlStateService
from .event_service import EventService
from .normalized_content_service import NormalizedContentService
from .platform_task_service import PlatformTaskService
from .raw_record_service import RawRecordService


class WeiboPlatformRunner:
    """Executes Weibo platform tasks through the new connector/task stack."""

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

    async def run_search_page(self, *, keyword: str, page: int, search_type: str) -> dict[str, Any]:
        job_id = f"wb-search-bridge-{uuid.uuid4().hex[:12]}"
        task = await self._create_task(
            task_id=f"wb-search-task-{uuid.uuid4().hex[:12]}",
            task_type="search",
            params={"keyword": keyword, "page": page, "search_type": search_type},
        )
        task_result = await self._execute_task(
            task=task,
            job_id=job_id,
            request=PlatformTaskRequest(
                job_id=job_id,
                platform_code="weibo",
                task_kind="search",
                payload={"keyword": keyword, "page": page, "filters": {"search_type": search_type}},
            ),
            failure_event_type="search_failed",
            failure_details={"keyword": keyword, "page": page},
        )
        notes = task_result.payload.get("items", [])
        normalized_records = normalize_weibo_notes(notes)
        await self.normalized_content_service.append_many(normalized_records)
        await self.raw_record_service.append(
            RawRecord(
                platform_code="weibo",
                record_type="search",
                source_uri="/api/container/getIndex",
                request_meta={"keyword": keyword, "page": page, "job_id": job_id},
                response_body=task_result.payload.get("raw"),
                metadata={"bridge": "weibo_connector", "normalized_count": len(normalized_records)},
            )
        )
        await self.event_service.append(
            CrawlJobEvent(
                job_id=job_id,
                event_type="search_page_succeeded",
                message="Weibo bridge search page succeeded",
                details={"keyword": keyword, "page": page, "items_count": len(notes)},
            ),
            platform_code="weibo",
        )
        return {"job_id": job_id, "task_id": task.task_id, **task_result.payload, "normalized_records": normalized_records}

    async def run_detail(self, *, note_id: str) -> dict[str, Any]:
        job_id = f"wb-detail-bridge-{uuid.uuid4().hex[:12]}"
        task = await self._create_task(
            task_id=f"wb-detail-task-{uuid.uuid4().hex[:12]}",
            task_type="detail",
            params={"note_id": note_id},
        )
        task_result = await self._execute_task(
            task=task,
            job_id=job_id,
            request=PlatformTaskRequest(
                job_id=job_id,
                platform_code="weibo",
                task_kind="detail",
                payload={"content_id": note_id},
            ),
            failure_event_type="detail_failed",
            failure_details={"note_id": note_id},
        )
        note = task_result.payload["note"]
        normalized_record = normalize_weibo_note(note)
        if normalized_record is not None:
            await self.normalized_content_service.append_many([normalized_record])
        await self.raw_record_service.append(
            RawRecord(
                platform_code="weibo",
                record_type="detail",
                source_uri=task_result.payload.get("request_uri", f"/detail/{note_id}"),
                request_meta={"note_id": note_id, "job_id": job_id},
                response_body=task_result.payload.get("raw_payload"),
                metadata={"bridge": "weibo_connector"},
            )
        )
        await self.event_service.append(
            CrawlJobEvent(
                job_id=job_id,
                event_type="detail_succeeded",
                message="Weibo bridge detail succeeded",
                details={"note_id": note_id},
            ),
            platform_code="weibo",
        )
        return {"job_id": job_id, "task_id": task.task_id, "note": note}

    async def run_comments(self, *, note_id: str, cursor: int | str = -1, limit: int | None = None) -> dict[str, Any]:
        job_id = f"wb-comments-bridge-{uuid.uuid4().hex[:12]}"
        task = await self._create_task(
            task_id=f"wb-comments-task-{uuid.uuid4().hex[:12]}",
            task_type="comments",
            params={"note_id": note_id, "cursor": cursor, "limit": limit or 10},
        )
        task_result = await self._execute_task(
            task=task,
            job_id=job_id,
            request=PlatformTaskRequest(
                job_id=job_id,
                platform_code="weibo",
                task_kind="comments",
                payload={"content_id": note_id, "cursor": cursor, "limit": limit or 10},
            ),
            failure_event_type="comments_failed",
            failure_details={"note_id": note_id},
        )
        await self.raw_record_service.append(
            RawRecord(
                platform_code="weibo",
                record_type="comments",
                source_uri=task_result.payload.get("request_uri", "/comments/hotflow"),
                request_meta={"note_id": note_id, "job_id": job_id},
                response_body=task_result.payload.get("raw_payload"),
                metadata={"bridge": "weibo_connector", "comment_count": len(task_result.payload.get("comments", []))},
            )
        )
        await self.event_service.append(
            CrawlJobEvent(
                job_id=job_id,
                event_type="comments_succeeded",
                message="Weibo bridge comments succeeded",
                details={"note_id": note_id, "comment_count": len(task_result.payload.get("comments", []))},
            ),
            platform_code="weibo",
        )
        return {"job_id": job_id, "task_id": task.task_id, **task_result.payload}

    async def run_creator(self, *, creator_id: str) -> dict[str, Any]:
        job_id = f"wb-creator-bridge-{uuid.uuid4().hex[:12]}"
        task = await self._create_task(
            task_id=f"wb-creator-task-{uuid.uuid4().hex[:12]}",
            task_type="creator",
            params={"creator_id": creator_id},
        )
        task_result = await self._execute_task(
            task=task,
            job_id=job_id,
            request=PlatformTaskRequest(
                job_id=job_id,
                platform_code="weibo",
                task_kind="creator",
                payload={"creator_id": creator_id},
            ),
            failure_event_type="creator_failed",
            failure_details={"creator_id": creator_id},
        )
        await self.raw_record_service.append(
            RawRecord(
                platform_code="weibo",
                record_type="creator",
                source_uri=task_result.payload.get("request_uri", "/api/container/getIndex"),
                request_meta={"creator_id": creator_id, "job_id": job_id},
                response_body=task_result.payload.get("raw_payload"),
                metadata={"bridge": "weibo_connector"},
            )
        )
        await self.event_service.append(
            CrawlJobEvent(
                job_id=job_id,
                event_type="creator_succeeded",
                message="Weibo bridge creator succeeded",
                details={"creator_id": creator_id},
            ),
            platform_code="weibo",
        )
        return {"job_id": job_id, "task_id": task.task_id, **task_result.payload}

    async def run_creator_contents(self, *, creator_id: str, cursor: str = "", limit: int = 10) -> dict[str, Any]:
        job_id = f"wb-creator-contents-bridge-{uuid.uuid4().hex[:12]}"
        task = await self._create_task(
            task_id=f"wb-creator-contents-task-{uuid.uuid4().hex[:12]}",
            task_type="creator_contents",
            params={"creator_id": creator_id, "cursor": cursor, "limit": limit},
        )
        task_result = await self._execute_task(
            task=task,
            job_id=job_id,
            request=PlatformTaskRequest(
                job_id=job_id,
                platform_code="weibo",
                task_kind="creator_contents",
                payload={"creator_id": creator_id, "cursor": cursor, "limit": limit},
            ),
            failure_event_type="creator_contents_failed",
            failure_details={"creator_id": creator_id, "cursor": cursor},
        )
        notes = task_result.payload.get("items", [])
        normalized_records = normalize_weibo_notes(notes)
        await self.normalized_content_service.append_many(normalized_records)
        await self.raw_record_service.append(
            RawRecord(
                platform_code="weibo",
                record_type="creator_contents",
                source_uri=task_result.payload.get("request_uri", "/api/container/getIndex"),
                request_meta={"creator_id": creator_id, "job_id": job_id, "cursor": cursor},
                response_body=task_result.payload.get("raw_payload"),
                metadata={"bridge": "weibo_connector", "normalized_count": len(normalized_records)},
            )
        )
        await self.event_service.append(
            CrawlJobEvent(
                job_id=job_id,
                event_type="creator_contents_succeeded",
                message="Weibo bridge creator contents succeeded",
                details={"creator_id": creator_id, "items_count": len(notes)},
            ),
            platform_code="weibo",
        )
        return {"job_id": job_id, "task_id": task.task_id, **task_result.payload, "normalized_records": normalized_records}

    async def _create_task(self, *, task_id: str, task_type: str, params: dict[str, Any]) -> CrawlTask:
        return await self.crawl_state_service.create_task(
            task_id=task_id,
            platform_code="weibo",
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
        connector = build_weibo_connector_from_legacy(self.crawler)
        task_service = PlatformTaskService(connector)
        job = await self.crawl_state_service.create_job(job_id=job_id, task=task)
        await connector.prepare(
            ConnectorContext(
                account_id=None,
                proxy=getattr(self.crawler, "_platform_http_proxy", None),
                metadata={"source": "legacy_weibo_crawler", "job_id": job_id, "task_id": task.task_id},
            )
        )
        running_job = await self.crawl_state_service.mark_job_running(job)
        try:
            result = await task_service.execute(request)
            await self.crawl_state_service.append_result(result)
            await self.crawl_state_service.mark_job_succeeded(running_job, metrics=result.metrics)
            return result
        except WeiboDataFetchError as exc:
            error_message = str(exc)
            failed_result = PlatformTaskResult(
                job_id=job_id,
                platform_code="weibo",
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
                platform_code="weibo",
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
        if "parse" in lowered:
            return "parse_failed"
        if "status 4" in lowered or "status 5" in lowered:
            return "http_error"
        return "unknown_error"
