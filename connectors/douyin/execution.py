from __future__ import annotations

from typing import Any

from connectors.douyin import build_douyin_connector_from_legacy
from connectors.douyin.errors import DouyinDataFetchError, classify_douyin_error
from connectors.douyin.helpers import build_douyin_failure_details, build_douyin_task_request
from connectors.douyin.normalizer import (
    parse_comments_payload,
    parse_creator_contents_payload,
    parse_creator_payload,
    parse_detail_payload,
    parse_search_payload,
)
from schemas.tasks.models import CrawlJobEvent, CrawlTask, RawRecord
from schemas.tasks.runtime import PlatformTaskRequest, PlatformTaskResult

from connectors.base.execution import BasePlatformHooks, ExecutionServices
from application.services.platform_outcome_service import PlatformOutcomeService


class DouyinPlatformHooks(BasePlatformHooks):
    platform_code = "douyin"
    short_code = "dy"
    source_name = "legacy_douyin_crawler"
    handled_exceptions = (DouyinDataFetchError,)

    def build_connector(self):
        return build_douyin_connector_from_legacy(self.crawler)

    def build_request(self, task: CrawlTask, job_id: str) -> PlatformTaskRequest:
        return build_douyin_task_request(
            job_id=job_id,
            platform_code=self.platform_code,
            task_type=task.task_type,
            params=task.params or {},
        )

    def use_generic_success_handling(self) -> bool:
        return True

    def build_started_event(self, task: CrawlTask, job_id: str) -> CrawlJobEvent | None:
        if task.task_type != "search":
            return None
        params = task.params or {}
        return CrawlJobEvent(
            job_id=job_id,
            event_type="bridge_search_started",
            message="Douyin search bridge started",
            details={"keyword": params.get("keyword"), "page": params.get("page")},
        )

    def build_finished_event(self, task: CrawlTask, job_id: str) -> CrawlJobEvent | None:
        if task.task_type != "search":
            return None
        return CrawlJobEvent(
            job_id=job_id,
            event_type="bridge_search_finished",
            message="Douyin search bridge finished",
            details={},
        )

    def classify_error(self, message: str) -> str:
        return classify_douyin_error(message)

    def build_failure_event(self, *, task: CrawlTask, job_id: str, error_message: str, error_code: str) -> CrawlJobEvent:
        details = build_douyin_failure_details(
            task_type=task.task_type,
            params=task.params or {},
            error_code=error_code,
        )
        return CrawlJobEvent(job_id=job_id, event_type=f"{task.task_type}_failed", message=error_message, details=details)

    async def handle_success(
        self,
        *,
        task: CrawlTask,
        request: PlatformTaskRequest,
        task_result: PlatformTaskResult,
        job_id: str,
        task_id: str,
        services: ExecutionServices,
    ) -> dict[str, Any]:
        payload = task_result.payload
        params = task.params or {}
        if task.task_type == "search":
            parsed = parse_search_payload(payload)
            search_items = parsed["items"]
            normalized_records = parsed["normalized_records"]
            await PlatformOutcomeService.append_normalized_records(services, normalized_records)
            if parsed["raw"]:
                await PlatformOutcomeService.append_raw_record(
                    services,
                    platform_code=self.platform_code,
                    record_type="search",
                    source_uri="/aweme/v1/web/general/search/single/",
                    request_meta={
                        "keyword": params.get("keyword"),
                        "page": params.get("page"),
                        "search_id": params.get("search_id", ""),
                        "job_id": job_id,
                    },
                    response_body=parsed["raw"],
                    metadata={"bridge": "douyin_connector", "normalized_count": len(normalized_records)},
                )
            await PlatformOutcomeService.append_event(
                services,
                platform_code=self.platform_code,
                job_id=job_id,
                event_type="search_page_succeeded",
                message="Douyin bridge search page succeeded",
                details={
                    "keyword": params.get("keyword"),
                    "page": params.get("page"),
                    "items_count": len(search_items),
                    "normalized_count": len(normalized_records),
                    "next_cursor": parsed["next_cursor"],
                },
            )
            return parsed
        if task.task_type == "detail":
            aweme_id = str(params.get("aweme_id") or params.get("content_id") or "")
            parsed = parse_detail_payload(payload)
            aweme_detail = parsed["aweme_detail"]
            normalized_record = parsed["normalized_record"]
            if normalized_record is not None:
                await PlatformOutcomeService.append_normalized_records(services, [normalized_record])
            raw_payload = parsed["raw_payload"]
            if raw_payload:
                await PlatformOutcomeService.append_raw_record(
                    services,
                    platform_code=self.platform_code,
                    record_type="detail",
                    source_uri=parsed["request_uri"],
                    request_meta={"aweme_id": aweme_id, "job_id": job_id, "request_params": parsed["request_params"]},
                    response_body=raw_payload,
                    metadata={"bridge": "douyin_connector", "normalized_count": 1 if normalized_record is not None else 0},
                )
            await PlatformOutcomeService.append_event(
                services,
                platform_code=self.platform_code,
                job_id=job_id,
                event_type="detail_succeeded",
                message="Douyin bridge detail succeeded",
                details={"aweme_id": aweme_id},
            )
            return parsed
        if task.task_type == "comments":
            aweme_id = str(params.get("aweme_id") or params.get("content_id") or "")
            parsed = parse_comments_payload(payload)
            await PlatformOutcomeService.append_raw_record(
                services,
                platform_code=self.platform_code,
                record_type="comments",
                source_uri=payload.get("request_uri", "/aweme/v1/web/comment/list/"),
                request_meta={
                    "aweme_id": aweme_id,
                    "job_id": job_id,
                    "limit": self._optional_int(params.get("limit")) or config.CRAWLER_MAX_COMMENTS_COUNT_SINGLENOTES,
                    "cursor": params.get("cursor", 0),
                },
                response_body=parsed["raw_payload"],
                metadata={
                    "bridge": "douyin_connector",
                    "comment_count": len(parsed["comments"]),
                    "cursor": parsed["cursor"],
                    "has_more": parsed["has_more"],
                },
            )
            await PlatformOutcomeService.append_event(
                services,
                platform_code=self.platform_code,
                job_id=job_id,
                event_type="comments_succeeded",
                message="Douyin bridge comments succeeded",
                details={"aweme_id": aweme_id, "comment_count": len(parsed["comments"])},
            )
            return parsed
        if task.task_type == "creator":
            creator_id = str(params.get("creator_id") or "")
            parsed = parse_creator_payload(payload)
            raw_payload = parsed["raw_payload"]
            if raw_payload:
                await PlatformOutcomeService.append_raw_record(
                    services,
                    platform_code=self.platform_code,
                    record_type="creator",
                    source_uri=parsed["request_uri"],
                    request_meta={"creator_id": creator_id, "job_id": job_id, "request_params": parsed["request_params"]},
                    response_body=raw_payload,
                    metadata={"bridge": "douyin_connector"},
                )
            await PlatformOutcomeService.append_event(
                services,
                platform_code=self.platform_code,
                job_id=job_id,
                event_type="creator_succeeded",
                message="Douyin bridge creator succeeded",
                details={"creator_id": creator_id},
            )
            return parsed
        if task.task_type == "creator_contents":
            creator_id = str(params.get("creator_id") or "")
            cursor = self._optional_str(params.get("cursor")) or ""
            parsed = parse_creator_contents_payload(payload)
            items = parsed["items"]
            normalized_records = parsed["normalized_records"]
            await PlatformOutcomeService.append_normalized_records(services, normalized_records)
            raw_payload = parsed["raw_payload"]
            if raw_payload:
                await PlatformOutcomeService.append_raw_record(
                    services,
                    platform_code=self.platform_code,
                    record_type="creator_contents",
                    source_uri=parsed["request_uri"],
                    request_meta={"creator_id": creator_id, "job_id": job_id, "cursor": cursor, "request_params": parsed["request_params"]},
                    response_body=raw_payload,
                    metadata={"bridge": "douyin_connector", "normalized_count": len(normalized_records)},
                )
            await PlatformOutcomeService.append_event(
                services,
                platform_code=self.platform_code,
                job_id=job_id,
                event_type="creator_contents_succeeded",
                message="Douyin bridge creator contents succeeded",
                details={"creator_id": creator_id, "items_count": len(items), "next_cursor": parsed["next_cursor"]},
            )
            return parsed
        raise ValueError(f"Unsupported Douyin task type: {task.task_type}")

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
