from __future__ import annotations

import uuid
from typing import Any

from connectors.base.models import ConnectorContext
from connectors.xhs import build_xhs_connector_from_legacy
from connectors.xhs.errors import XhsDataFetchError
from connectors.xhs.normalizer import normalize_xhs_note, normalize_xhs_notes
from media_platform.xhs.help import get_search_id, parse_creator_info_from_url
from schemas.tasks.models import CrawlJobEvent, CrawlTask, RawRecord
from schemas.tasks.runtime import PlatformTaskRequest, PlatformTaskResult

from .crawl_state_service import CrawlStateService
from .event_service import EventService
from .normalized_content_service import NormalizedContentService
from .platform_task_service import PlatformTaskService
from .raw_record_service import RawRecordService


class XhsPlatformRunner:
    """Executes Xiaohongshu tasks through the new connector/task stack."""

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

    async def run_search_page(self, *, keyword: str, page: int, sort_type: str) -> dict[str, Any]:
        job_id = f"xhs-search-bridge-{uuid.uuid4().hex[:12]}"
        task = await self._create_task(
            task_id=f"xhs-search-task-{uuid.uuid4().hex[:12]}",
            task_type="search",
            params={"keyword": keyword, "page": page, "sort_type": sort_type},
        )
        search_id = get_search_id()
        task_result = await self._execute_task(
            task=task,
            job_id=job_id,
            request=PlatformTaskRequest(
                job_id=job_id,
                platform_code="xhs",
                task_kind="search",
                payload={
                    "keyword": keyword,
                    "page": page,
                    "page_size": 20,
                    "filters": {"sort": sort_type, "search_id": search_id},
                },
            ),
            failure_event_type="search_failed",
            failure_details={"keyword": keyword, "page": page},
        )
        raw_items = task_result.payload.get("items", [])
        notes: list[dict[str, Any]] = []
        for item in raw_items:
            note_id = str(item.get("id") or "")
            xsec_token = str(item.get("xsec_token") or "")
            if not note_id or not xsec_token:
                continue
            detail_result = await self.run_detail(
                note_id=note_id,
                xsec_source=str(item.get("xsec_source") or "pc_search"),
                xsec_token=xsec_token,
            )
            note = detail_result.get("note")
            if note:
                notes.append(note)

        normalized_records = normalize_xhs_notes(notes)
        await self.raw_record_service.append(
            RawRecord(
                platform_code="xhs",
                record_type="search",
                source_uri="/api/sns/web/v1/search/notes",
                request_meta={"keyword": keyword, "page": page, "job_id": job_id, "search_id": search_id},
                response_body=task_result.payload.get("raw"),
                metadata={"bridge": "xhs_connector", "normalized_count": len(normalized_records)},
            )
        )
        await self.event_service.append(
            CrawlJobEvent(
                job_id=job_id,
                event_type="search_page_succeeded",
                message="XHS bridge search page succeeded",
                details={"keyword": keyword, "page": page, "items_count": len(notes)},
            ),
            platform_code="xhs",
        )
        return {
            "job_id": job_id,
            "task_id": task.task_id,
            "items": notes,
            "raw_items": raw_items,
            "normalized_records": normalized_records,
            "has_more": task_result.payload.get("has_more", False),
            "next_cursor": task_result.payload.get("next_cursor"),
        }

    async def run_detail(self, *, note_id: str, xsec_source: str, xsec_token: str) -> dict[str, Any]:
        job_id = f"xhs-detail-bridge-{uuid.uuid4().hex[:12]}"
        task = await self._create_task(
            task_id=f"xhs-detail-task-{uuid.uuid4().hex[:12]}",
            task_type="detail",
            params={"note_id": note_id, "xsec_source": xsec_source, "xsec_token": xsec_token},
        )
        task_result = await self._execute_task(
            task=task,
            job_id=job_id,
            request=PlatformTaskRequest(
                job_id=job_id,
                platform_code="xhs",
                task_kind="detail",
                payload={
                    "content_id": note_id,
                    "extra": {"xsec_source": xsec_source, "xsec_token": xsec_token},
                },
            ),
            failure_event_type="detail_failed",
            failure_details={"note_id": note_id},
        )
        note = task_result.payload["note"]
        normalized_record = normalize_xhs_note(note)
        await self.normalized_content_service.append_many([normalized_record])
        await self.raw_record_service.append(
            RawRecord(
                platform_code="xhs",
                record_type="detail",
                source_uri=task_result.payload.get("request_uri", "/api/sns/web/v1/feed"),
                request_meta={"note_id": note_id, "job_id": job_id},
                response_body=task_result.payload.get("raw_payload"),
                metadata={"bridge": "xhs_connector"},
            )
        )
        await self.event_service.append(
            CrawlJobEvent(
                job_id=job_id,
                event_type="detail_succeeded",
                message="XHS bridge detail succeeded",
                details={"note_id": note_id},
            ),
            platform_code="xhs",
        )
        return {"job_id": job_id, "task_id": task.task_id, "note": note}

    async def run_comments(self, *, note_id: str, xsec_token: str, limit: int | None = None) -> dict[str, Any]:
        job_id = f"xhs-comments-bridge-{uuid.uuid4().hex[:12]}"
        task = await self._create_task(
            task_id=f"xhs-comments-task-{uuid.uuid4().hex[:12]}",
            task_type="comments",
            params={"note_id": note_id, "xsec_token": xsec_token, "limit": limit or 10},
        )
        task_result = await self._execute_task(
            task=task,
            job_id=job_id,
            request=PlatformTaskRequest(
                job_id=job_id,
                platform_code="xhs",
                task_kind="comments",
                payload={
                    "content_id": note_id,
                    "limit": limit or 10,
                    "extra": {"xsec_token": xsec_token},
                },
            ),
            failure_event_type="comments_failed",
            failure_details={"note_id": note_id},
        )
        await self.raw_record_service.append(
            RawRecord(
                platform_code="xhs",
                record_type="comments",
                source_uri=task_result.payload.get("request_uri", "/api/sns/web/v2/comment/page"),
                request_meta={"note_id": note_id, "job_id": job_id},
                response_body=task_result.payload.get("raw_payload"),
                metadata={"bridge": "xhs_connector", "comment_count": len(task_result.payload.get("comments", []))},
            )
        )
        await self.event_service.append(
            CrawlJobEvent(
                job_id=job_id,
                event_type="comments_succeeded",
                message="XHS bridge comments succeeded",
                details={"note_id": note_id, "comment_count": len(task_result.payload.get("comments", []))},
            ),
            platform_code="xhs",
        )
        return {"job_id": job_id, "task_id": task.task_id, **task_result.payload}

    async def run_creator(self, *, creator_url: str) -> dict[str, Any]:
        job_id = f"xhs-creator-bridge-{uuid.uuid4().hex[:12]}"
        task = await self._create_task(
            task_id=f"xhs-creator-task-{uuid.uuid4().hex[:12]}",
            task_type="creator",
            params={"creator_url": creator_url},
        )
        task_result = await self._execute_task(
            task=task,
            job_id=job_id,
            request=PlatformTaskRequest(
                job_id=job_id,
                platform_code="xhs",
                task_kind="creator",
                payload={"creator_id": creator_url},
            ),
            failure_event_type="creator_failed",
            failure_details={"creator_url": creator_url},
        )
        await self.raw_record_service.append(
            RawRecord(
                platform_code="xhs",
                record_type="creator",
                source_uri=task_result.payload.get("request_uri", creator_url),
                request_meta={"creator_url": creator_url, "job_id": job_id},
                response_body=task_result.payload.get("raw_payload"),
                metadata={"bridge": "xhs_connector"},
            )
        )
        await self.event_service.append(
            CrawlJobEvent(
                job_id=job_id,
                event_type="creator_succeeded",
                message="XHS bridge creator succeeded",
                details={"creator_url": creator_url},
            ),
            platform_code="xhs",
        )
        return {"job_id": job_id, "task_id": task.task_id, **task_result.payload}

    async def run_creator_contents(self, *, creator_url: str, cursor: str = "", limit: int = 30) -> dict[str, Any]:
        job_id = f"xhs-creator-contents-bridge-{uuid.uuid4().hex[:12]}"
        task = await self._create_task(
            task_id=f"xhs-creator-contents-task-{uuid.uuid4().hex[:12]}",
            task_type="creator_contents",
            params={"creator_url": creator_url, "cursor": cursor, "limit": limit},
        )
        task_result = await self._execute_task(
            task=task,
            job_id=job_id,
            request=PlatformTaskRequest(
                job_id=job_id,
                platform_code="xhs",
                task_kind="creator_contents",
                payload={"creator_id": creator_url, "cursor": cursor, "limit": limit},
            ),
            failure_event_type="creator_contents_failed",
            failure_details={"creator_url": creator_url, "cursor": cursor},
        )
        detailed_notes: list[dict[str, Any]] = []
        for item in task_result.payload.get("items", []):
            note_id = str(item.get("note_id") or item.get("id") or "")
            xsec_token = str(item.get("xsec_token") or "")
            if not note_id or not xsec_token:
                continue
            detail_result = await self.run_detail(
                note_id=note_id,
                xsec_source=str(item.get("xsec_source") or task_result.payload.get("xsec_source") or "pc_feed"),
                xsec_token=xsec_token,
            )
            note = detail_result.get("note")
            if note:
                detailed_notes.append(note)

        normalized_records = normalize_xhs_notes(detailed_notes)
        await self.raw_record_service.append(
            RawRecord(
                platform_code="xhs",
                record_type="creator_contents",
                source_uri=task_result.payload.get("request_uri", "/api/sns/web/v1/user_posted"),
                request_meta={"creator_url": creator_url, "job_id": job_id, "cursor": cursor},
                response_body=task_result.payload.get("raw_payload"),
                metadata={"bridge": "xhs_connector", "normalized_count": len(normalized_records)},
            )
        )
        await self.event_service.append(
            CrawlJobEvent(
                job_id=job_id,
                event_type="creator_contents_succeeded",
                message="XHS bridge creator contents succeeded",
                details={"creator_url": creator_url, "items_count": len(detailed_notes)},
            ),
            platform_code="xhs",
        )
        return {
            "job_id": job_id,
            "task_id": task.task_id,
            "items": detailed_notes,
            "raw_items": task_result.payload.get("items", []),
            "normalized_records": normalized_records,
            "has_more": task_result.payload.get("has_more", False),
            "next_cursor": task_result.payload.get("next_cursor", ""),
        }

    async def _create_task(self, *, task_id: str, task_type: str, params: dict[str, Any]) -> CrawlTask:
        return await self.crawl_state_service.create_task(
            task_id=task_id,
            platform_code="xhs",
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
        connector = build_xhs_connector_from_legacy(self.crawler)
        task_service = PlatformTaskService(connector=connector)
        job = await self.crawl_state_service.create_job(job_id=job_id, task=task)
        await connector.prepare(
            ConnectorContext(
                account_id=None,
                proxy=getattr(self.crawler, "_platform_http_proxy", None),
                metadata={"source": "legacy_xhs_crawler", "job_id": job_id, "task_id": task.task_id},
            )
        )
        running_job = await self.crawl_state_service.mark_job_running(job)
        try:
            result = await task_service.execute(request)
            await self.crawl_state_service.append_result(result)
            await self.crawl_state_service.mark_job_succeeded(running_job, metrics=result.metrics)
            return result
        except XhsDataFetchError as exc:
            error_message = str(exc)
            await self.event_service.append(
                CrawlJobEvent(
                    job_id=job_id,
                    event_type=failure_event_type,
                    message=error_message,
                    details={**failure_details, "risk_type": self._classify_error(error_message)},
                ),
                platform_code="xhs",
            )
            failed_result = PlatformTaskResult(
                job_id=job_id,
                platform_code="xhs",
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
            await connector.close()

    @staticmethod
    def _classify_error(message: str) -> str:
        lowered = message.lower()
        if "session" in lowered or "cookie" in lowered or "legacy client is not ready" in lowered:
            return "session_not_ready"
        if "xsec_token" in lowered:
            return "token_missing"
        if "sign" in lowered or "mnsv2" in lowered:
            return "signature_failed"
        if "parse" in lowered or "payload" in lowered:
            return "invalid_payload"
        return "unknown_error"
