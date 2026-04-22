from __future__ import annotations

import uuid
from typing import Any

from connectors.base.models import ConnectorContext
from connectors.zhihu import build_zhihu_connector_from_legacy
from connectors.zhihu.errors import ZhihuDataFetchError
from connectors.zhihu.normalizer import normalize_zhihu_content, normalize_zhihu_contents
from model.m_zhihu import ZhihuContent
from schemas.tasks.models import CrawlJobEvent, CrawlTask, RawRecord
from schemas.tasks.runtime import PlatformTaskRequest, PlatformTaskResult

from .crawl_state_service import CrawlStateService
from .event_service import EventService
from .normalized_content_service import NormalizedContentService
from .platform_task_service import PlatformTaskService
from .raw_record_service import RawRecordService


class ZhihuPlatformRunner:
    """Executes Zhihu platform tasks through the new connector/task stack."""

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
        job_id = f"zh-search-bridge-{uuid.uuid4().hex[:12]}"
        task = await self._create_task(
            task_id=f"zh-search-task-{uuid.uuid4().hex[:12]}",
            task_type="search",
            params={"keyword": keyword, "page": page, "page_size": page_size},
        )
        task_result = await self._execute_task(
            task=task,
            job_id=job_id,
            request=PlatformTaskRequest(
                job_id=job_id,
                platform_code="zhihu",
                task_kind="search",
                payload={"keyword": keyword, "page": page, "page_size": page_size},
            ),
            failure_event_type="search_failed",
            failure_details={"keyword": keyword, "page": page},
        )
        items = [ZhihuContent.model_validate(item) for item in task_result.payload.get("items", [])]
        normalized_records = normalize_zhihu_contents(items)
        await self.normalized_content_service.append_many(normalized_records)
        await self.raw_record_service.append(
            RawRecord(
                platform_code="zhihu",
                record_type="search",
                source_uri="/api/v4/search_v3",
                request_meta={"keyword": keyword, "page": page, "job_id": job_id},
                response_body=task_result.payload.get("raw"),
                metadata={"bridge": "zhihu_connector", "normalized_count": len(normalized_records)},
            )
        )
        await self.event_service.append(
            CrawlJobEvent(
                job_id=job_id,
                event_type="search_page_succeeded",
                message="Zhihu bridge search page succeeded",
                details={"keyword": keyword, "page": page, "items_count": len(items)},
            ),
            platform_code="zhihu",
        )
        return {
            "job_id": job_id,
            "task_id": task.task_id,
            "items": [item.model_dump() for item in items],
            "normalized_records": normalized_records,
            "has_more": task_result.payload.get("has_more", False),
            "next_cursor": task_result.payload.get("next_cursor"),
        }

    async def run_detail(
        self,
        *,
        content_id: str,
        content_type: str,
        detail_url: str,
        question_id: str = "",
    ) -> dict[str, Any]:
        job_id = f"zh-detail-bridge-{uuid.uuid4().hex[:12]}"
        task = await self._create_task(
            task_id=f"zh-detail-task-{uuid.uuid4().hex[:12]}",
            task_type="detail",
            params={
                "content_id": content_id,
                "content_type": content_type,
                "detail_url": detail_url,
                "question_id": question_id,
            },
        )
        task_result = await self._execute_task(
            task=task,
            job_id=job_id,
            request=PlatformTaskRequest(
                job_id=job_id,
                platform_code="zhihu",
                task_kind="detail",
                payload={
                    "content_id": content_id,
                    "extra": {
                        "content_type": content_type,
                        "detail_url": detail_url,
                        "question_id": question_id,
                    },
                },
            ),
            failure_event_type="detail_failed",
            failure_details={"content_id": content_id, "content_type": content_type},
        )
        content = ZhihuContent.model_validate(task_result.payload["content"])
        normalized_record = normalize_zhihu_content(content)
        await self.normalized_content_service.append_many([normalized_record])
        await self.raw_record_service.append(
            RawRecord(
                platform_code="zhihu",
                record_type="detail",
                source_uri=task_result.payload.get("request_uri", detail_url),
                request_meta={"content_id": content_id, "job_id": job_id},
                response_body=task_result.payload.get("raw_payload"),
                metadata={"bridge": "zhihu_connector", "content_type": content.content_type},
            )
        )
        await self.event_service.append(
            CrawlJobEvent(
                job_id=job_id,
                event_type="detail_succeeded",
                message="Zhihu bridge detail succeeded",
                details={"content_id": content_id, "content_type": content.content_type},
            ),
            platform_code="zhihu",
        )
        return {"job_id": job_id, "task_id": task.task_id, "content": content}

    async def run_comments(self, *, content: ZhihuContent, cursor: str = "", limit: int | None = None) -> dict[str, Any]:
        job_id = f"zh-comments-bridge-{uuid.uuid4().hex[:12]}"
        task = await self._create_task(
            task_id=f"zh-comments-task-{uuid.uuid4().hex[:12]}",
            task_type="comments",
            params={"content": content.model_dump(), "cursor": cursor, "limit": limit or 10},
        )
        task_result = await self._execute_task(
            task=task,
            job_id=job_id,
            request=PlatformTaskRequest(
                job_id=job_id,
                platform_code="zhihu",
                task_kind="comments",
                payload={
                    "content_id": content.content_id,
                    "cursor": cursor,
                    "limit": limit or 10,
                    "extra": {"content_type": content.content_type, "content": content.model_dump()},
                },
            ),
            failure_event_type="comments_failed",
            failure_details={"content_id": content.content_id, "content_type": content.content_type},
        )
        await self.raw_record_service.append(
            RawRecord(
                platform_code="zhihu",
                record_type="comments",
                source_uri=task_result.payload.get("request_uri", ""),
                request_meta={"content_id": content.content_id, "job_id": job_id},
                response_body=task_result.payload.get("raw_payload"),
                metadata={"bridge": "zhihu_connector", "comment_count": len(task_result.payload.get("comments", []))},
            )
        )
        await self.event_service.append(
            CrawlJobEvent(
                job_id=job_id,
                event_type="comments_succeeded",
                message="Zhihu bridge comments succeeded",
                details={"content_id": content.content_id, "comment_count": len(task_result.payload.get("comments", []))},
            ),
            platform_code="zhihu",
        )
        return {"job_id": job_id, "task_id": task.task_id, **task_result.payload}

    async def run_creator(self, *, creator_id: str) -> dict[str, Any]:
        job_id = f"zh-creator-bridge-{uuid.uuid4().hex[:12]}"
        task = await self._create_task(
            task_id=f"zh-creator-task-{uuid.uuid4().hex[:12]}",
            task_type="creator",
            params={"creator_id": creator_id},
        )
        task_result = await self._execute_task(
            task=task,
            job_id=job_id,
            request=PlatformTaskRequest(
                job_id=job_id,
                platform_code="zhihu",
                task_kind="creator",
                payload={"creator_id": creator_id},
            ),
            failure_event_type="creator_failed",
            failure_details={"creator_id": creator_id},
        )
        await self.raw_record_service.append(
            RawRecord(
                platform_code="zhihu",
                record_type="creator",
                source_uri=task_result.payload.get("request_uri", f"/people/{creator_id}"),
                request_meta={"creator_id": creator_id, "job_id": job_id},
                response_body=task_result.payload.get("raw_payload"),
                metadata={"bridge": "zhihu_connector"},
            )
        )
        await self.event_service.append(
            CrawlJobEvent(
                job_id=job_id,
                event_type="creator_succeeded",
                message="Zhihu bridge creator succeeded",
                details={"creator_id": creator_id},
            ),
            platform_code="zhihu",
        )
        return {"job_id": job_id, "task_id": task.task_id, **task_result.payload}

    async def run_creator_contents(self, *, creator_id: str, cursor: str = "", limit: int = 20) -> dict[str, Any]:
        job_id = f"zh-creator-contents-bridge-{uuid.uuid4().hex[:12]}"
        task = await self._create_task(
            task_id=f"zh-creator-contents-task-{uuid.uuid4().hex[:12]}",
            task_type="creator_contents",
            params={"creator_id": creator_id, "cursor": cursor, "limit": limit},
        )
        task_result = await self._execute_task(
            task=task,
            job_id=job_id,
            request=PlatformTaskRequest(
                job_id=job_id,
                platform_code="zhihu",
                task_kind="creator_contents",
                payload={"creator_id": creator_id, "cursor": cursor, "limit": limit},
            ),
            failure_event_type="creator_contents_failed",
            failure_details={"creator_id": creator_id, "cursor": cursor},
        )
        items = [ZhihuContent.model_validate(item) for item in task_result.payload.get("items", [])]
        normalized_records = normalize_zhihu_contents(items)
        await self.normalized_content_service.append_many(normalized_records)
        await self.raw_record_service.append(
            RawRecord(
                platform_code="zhihu",
                record_type="creator_contents",
                source_uri=task_result.payload.get("request_uri", ""),
                request_meta={"creator_id": creator_id, "job_id": job_id, "cursor": cursor},
                response_body=task_result.payload.get("raw_payload"),
                metadata={"bridge": "zhihu_connector", "normalized_count": len(normalized_records)},
            )
        )
        await self.event_service.append(
            CrawlJobEvent(
                job_id=job_id,
                event_type="creator_contents_succeeded",
                message="Zhihu bridge creator contents succeeded",
                details={"creator_id": creator_id, "items_count": len(items)},
            ),
            platform_code="zhihu",
        )
        return {
            "job_id": job_id,
            "task_id": task.task_id,
            "items": [item.model_dump() for item in items],
            "normalized_records": normalized_records,
            "has_more": task_result.payload.get("has_more", False),
            "next_cursor": task_result.payload.get("next_cursor", ""),
        }

    async def _create_task(self, *, task_id: str, task_type: str, params: dict[str, Any]) -> CrawlTask:
        return await self.crawl_state_service.create_task(
            task_id=task_id,
            platform_code="zhihu",
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
        connector = build_zhihu_connector_from_legacy(self.crawler)
        task_service = PlatformTaskService(connector)
        job = await self.crawl_state_service.create_job(job_id=job_id, task=task)
        await connector.prepare(
            ConnectorContext(
                account_id=None,
                proxy=getattr(self.crawler, "_platform_http_proxy", None),
                metadata={"source": "legacy_zhihu_crawler", "job_id": job_id, "task_id": task.task_id},
            )
        )
        running_job = await self.crawl_state_service.mark_job_running(job)
        try:
            result = await task_service.execute(request)
            await self.crawl_state_service.append_result(result)
            await self.crawl_state_service.mark_job_succeeded(running_job, metrics=result.metrics)
            return result
        except ZhihuDataFetchError as exc:
            error_message = str(exc)
            failed_result = PlatformTaskResult(
                job_id=job_id,
                platform_code="zhihu",
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
                platform_code="zhihu",
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
        if "d_c0" in lowered or "browser state" in lowered:
            return "session_not_ready"
        if "status 4" in lowered or "status 5" in lowered:
            return "http_error"
        if "parse" in lowered:
            return "parse_failed"
        return "unknown_error"
