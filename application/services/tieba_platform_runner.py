from __future__ import annotations

import uuid
from typing import Any

from connectors.base.models import ConnectorContext
from connectors.tieba import build_tieba_connector_from_legacy
from connectors.tieba.errors import TiebaDataFetchError
from connectors.tieba.normalizer import normalize_tieba_note, normalize_tieba_notes
from model.m_baidu_tieba import TiebaComment, TiebaCreator, TiebaNote
from schemas.tasks.models import CrawlJobEvent, CrawlTask, RawRecord
from schemas.tasks.runtime import PlatformTaskRequest, PlatformTaskResult

from .crawl_state_service import CrawlStateService
from .event_service import EventService
from .normalized_content_service import NormalizedContentService
from .platform_task_service import PlatformTaskService
from .raw_record_service import RawRecordService


class TiebaPlatformRunner:
    """Executes Tieba platform tasks through the new connector/task stack."""

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

    async def run_search_page(self, *, keyword: str, page: int, page_size: int = 10) -> dict[str, Any]:
        job_id = f"tb-search-bridge-{uuid.uuid4().hex[:12]}"
        task = await self._create_task(
            task_id=f"tb-search-task-{uuid.uuid4().hex[:12]}",
            task_type="search",
            params={"keyword": keyword, "page": page, "page_size": page_size},
        )
        task_result = await self._execute_task(
            task=task,
            job_id=job_id,
            request=PlatformTaskRequest(
                job_id=job_id,
                platform_code="tieba",
                task_kind="search",
                payload={"keyword": keyword, "page": page, "page_size": page_size},
            ),
            failure_event_type="search_failed",
            failure_details={"keyword": keyword, "page": page},
        )
        notes = [TiebaNote.model_validate(item) for item in task_result.payload.get("items", [])]
        normalized_records = normalize_tieba_notes(notes)
        await self.normalized_content_service.append_many(normalized_records)
        await self.raw_record_service.append(
            RawRecord(
                platform_code="tieba",
                record_type="search",
                source_uri=task_result.payload.get("metadata", {}).get("request_url", ""),
                request_meta={"keyword": keyword, "page": page, "job_id": job_id},
                response_body=task_result.payload.get("raw"),
                metadata={"bridge": "tieba_connector", "normalized_count": len(normalized_records)},
            )
        )
        await self.event_service.append(
            CrawlJobEvent(
                job_id=job_id,
                event_type="search_page_succeeded",
                message="Tieba bridge search page succeeded",
                details={"keyword": keyword, "page": page, "items_count": len(notes)},
            ),
            platform_code="tieba",
        )
        return {
            "job_id": job_id,
            "task_id": task.task_id,
            "items": [note.model_dump() for note in notes],
            "normalized_records": normalized_records,
            "has_more": task_result.payload.get("has_more", False),
            "next_cursor": task_result.payload.get("next_cursor"),
        }

    async def run_detail(self, *, note_id: str, detail_url: str | None = None) -> dict[str, Any]:
        job_id = f"tb-detail-bridge-{uuid.uuid4().hex[:12]}"
        task = await self._create_task(
            task_id=f"tb-detail-task-{uuid.uuid4().hex[:12]}",
            task_type="detail",
            params={"note_id": note_id, "detail_url": detail_url or ""},
        )
        task_result = await self._execute_task(
            task=task,
            job_id=job_id,
            request=PlatformTaskRequest(
                job_id=job_id,
                platform_code="tieba",
                task_kind="detail",
                payload={"content_id": note_id, "extra": {"detail_url": detail_url or ""}},
            ),
            failure_event_type="detail_failed",
            failure_details={"note_id": note_id},
        )
        note = TiebaNote.model_validate(task_result.payload["note"])
        normalized_record = normalize_tieba_note(note)
        await self.normalized_content_service.append_many([normalized_record])
        await self.raw_record_service.append(
            RawRecord(
                platform_code="tieba",
                record_type="detail",
                source_uri=task_result.payload.get("request_uri", detail_url or ""),
                request_meta={"note_id": note_id, "job_id": job_id},
                response_body=task_result.payload.get("raw_payload"),
                metadata={"bridge": "tieba_connector"},
            )
        )
        await self.event_service.append(
            CrawlJobEvent(
                job_id=job_id,
                event_type="detail_succeeded",
                message="Tieba bridge detail succeeded",
                details={"note_id": note_id},
            ),
            platform_code="tieba",
        )
        return {"job_id": job_id, "task_id": task.task_id, "note": note}

    async def run_comments(self, *, note: TiebaNote, cursor: int | str = 1, limit: int | None = None) -> dict[str, Any]:
        job_id = f"tb-comments-bridge-{uuid.uuid4().hex[:12]}"
        task = await self._create_task(
            task_id=f"tb-comments-task-{uuid.uuid4().hex[:12]}",
            task_type="comments",
            params={"note": note.model_dump(), "cursor": cursor, "limit": limit or 10},
        )
        task_result = await self._execute_task(
            task=task,
            job_id=job_id,
            request=PlatformTaskRequest(
                job_id=job_id,
                platform_code="tieba",
                task_kind="comments",
                payload={
                    "content_id": note.note_id,
                    "cursor": cursor,
                    "limit": limit or 10,
                    "extra": {"note": note.model_dump()},
                },
            ),
            failure_event_type="comments_failed",
            failure_details={"note_id": note.note_id},
        )
        await self.raw_record_service.append(
            RawRecord(
                platform_code="tieba",
                record_type="comments",
                source_uri=task_result.payload.get("request_uri", ""),
                request_meta={"note_id": note.note_id, "job_id": job_id},
                response_body=task_result.payload.get("raw_payload"),
                metadata={"bridge": "tieba_connector", "comment_count": len(task_result.payload.get("comments", []))},
            )
        )
        await self.event_service.append(
            CrawlJobEvent(
                job_id=job_id,
                event_type="comments_succeeded",
                message="Tieba bridge comments succeeded",
                details={"note_id": note.note_id, "comment_count": len(task_result.payload.get("comments", []))},
            ),
            platform_code="tieba",
        )
        return {"job_id": job_id, "task_id": task.task_id, **task_result.payload}

    async def run_creator(self, *, creator_url: str) -> dict[str, Any]:
        job_id = f"tb-creator-bridge-{uuid.uuid4().hex[:12]}"
        task = await self._create_task(
            task_id=f"tb-creator-task-{uuid.uuid4().hex[:12]}",
            task_type="creator",
            params={"creator_url": creator_url},
        )
        task_result = await self._execute_task(
            task=task,
            job_id=job_id,
            request=PlatformTaskRequest(
                job_id=job_id,
                platform_code="tieba",
                task_kind="creator",
                payload={"creator_id": creator_url},
            ),
            failure_event_type="creator_failed",
            failure_details={"creator_url": creator_url},
        )
        await self.raw_record_service.append(
            RawRecord(
                platform_code="tieba",
                record_type="creator",
                source_uri=task_result.payload.get("request_uri", creator_url),
                request_meta={"creator_url": creator_url, "job_id": job_id},
                response_body=task_result.payload.get("raw_payload"),
                metadata={"bridge": "tieba_connector"},
            )
        )
        await self.event_service.append(
            CrawlJobEvent(
                job_id=job_id,
                event_type="creator_succeeded",
                message="Tieba bridge creator succeeded",
                details={"creator_url": creator_url},
            ),
            platform_code="tieba",
        )
        return {"job_id": job_id, "task_id": task.task_id, **task_result.payload}

    async def run_creator_contents(self, *, creator_url: str, cursor: str = "", limit: int = 20) -> dict[str, Any]:
        job_id = f"tb-creator-contents-bridge-{uuid.uuid4().hex[:12]}"
        task = await self._create_task(
            task_id=f"tb-creator-contents-task-{uuid.uuid4().hex[:12]}",
            task_type="creator_contents",
            params={"creator_url": creator_url, "cursor": cursor, "limit": limit},
        )
        task_result = await self._execute_task(
            task=task,
            job_id=job_id,
            request=PlatformTaskRequest(
                job_id=job_id,
                platform_code="tieba",
                task_kind="creator_contents",
                payload={"creator_id": creator_url, "cursor": cursor, "limit": limit},
            ),
            failure_event_type="creator_contents_failed",
            failure_details={"creator_url": creator_url, "cursor": cursor},
        )
        notes = [TiebaNote.model_validate(item) for item in task_result.payload.get("items", [])]
        normalized_records = normalize_tieba_notes(notes)
        await self.normalized_content_service.append_many(normalized_records)
        await self.raw_record_service.append(
            RawRecord(
                platform_code="tieba",
                record_type="creator_contents",
                source_uri=task_result.payload.get("request_uri", creator_url),
                request_meta={"creator_url": creator_url, "job_id": job_id, "cursor": cursor},
                response_body=task_result.payload.get("raw_payload"),
                metadata={"bridge": "tieba_connector", "normalized_count": len(normalized_records)},
            )
        )
        await self.event_service.append(
            CrawlJobEvent(
                job_id=job_id,
                event_type="creator_contents_succeeded",
                message="Tieba bridge creator contents succeeded",
                details={"creator_url": creator_url, "items_count": len(notes)},
            ),
            platform_code="tieba",
        )
        return {
            "job_id": job_id,
            "task_id": task.task_id,
            "items": [note.model_dump() for note in notes],
            "normalized_records": normalized_records,
            "has_more": task_result.payload.get("has_more", False),
            "next_cursor": task_result.payload.get("next_cursor", ""),
        }

    async def _create_task(self, *, task_id: str, task_type: str, params: dict[str, Any]) -> CrawlTask:
        return await self.crawl_state_service.create_task(
            task_id=task_id,
            platform_code="tieba",
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
        connector = build_tieba_connector_from_legacy(self.crawler)
        task_service = PlatformTaskService(connector)
        job = await self.crawl_state_service.create_job(job_id=job_id, task=task)
        await connector.prepare(
            ConnectorContext(
                account_id=None,
                proxy=getattr(self.crawler, "_platform_http_proxy", None),
                metadata={"source": "legacy_tieba_crawler", "job_id": job_id, "task_id": task.task_id},
            )
        )
        running_job = await self.crawl_state_service.mark_job_running(job)
        try:
            result = await task_service.execute(request)
            await self.crawl_state_service.append_result(result)
            await self.crawl_state_service.mark_job_succeeded(running_job, metrics=result.metrics)
            return result
        except TiebaDataFetchError as exc:
            error_message = str(exc)
            failed_result = PlatformTaskResult(
                job_id=job_id,
                platform_code="tieba",
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
                platform_code="tieba",
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
        if "browser page" in lowered:
            return "session_not_ready"
        if "parse" in lowered:
            return "parse_failed"
        if "navigation" in lowered:
            return "navigation_failed"
        return "unknown_error"
