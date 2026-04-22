from __future__ import annotations

from typing import Any

import config
from connectors.douyin import build_douyin_connector_from_legacy
from connectors.douyin.errors import DouyinDataFetchError
from connectors.douyin.normalizer import normalize_aweme_detail, normalize_search_items
from schemas.tasks.models import CrawlJobEvent, CrawlTask, RawRecord
from schemas.tasks.runtime import PlatformTaskRequest, PlatformTaskResult

from .base import BasePlatformHooks, ExecutionServices


class DouyinPlatformHooks(BasePlatformHooks):
    platform_code = "douyin"
    short_code = "dy"
    source_name = "legacy_douyin_crawler"
    handled_exceptions = (DouyinDataFetchError,)

    def build_connector(self):
        return build_douyin_connector_from_legacy(self.crawler)

    def build_request(self, task: CrawlTask, job_id: str) -> PlatformTaskRequest:
        params = task.params or {}
        task_type = task.task_type
        if task_type == "search":
            return PlatformTaskRequest(
                job_id=job_id,
                platform_code=self.platform_code,
                task_kind="search",
                payload={
                    "keyword": str(params["keyword"]),
                    "page": int(params.get("page", 1)),
                    "page_size": int(params.get("page_size", 15)),
                    "cursor": str(params.get("search_id", "")),
                    "filters": {
                        "publish_time": self._optional_str(params.get("publish_time")) or str(config.PUBLISH_TIME_TYPE),
                        "sort_type": self._optional_str(params.get("sort_type")) or str(config.SEARCH_SORT_TYPE),
                        "search_id": str(params.get("search_id", "")),
                    },
                },
            )
        if task_type == "detail":
            aweme_id = str(params.get("aweme_id") or params.get("content_id") or "")
            if not aweme_id:
                raise ValueError("Douyin detail task requires aweme_id or content_id")
            return PlatformTaskRequest(
                job_id=job_id,
                platform_code=self.platform_code,
                task_kind="detail",
                payload={"content_id": aweme_id},
            )
        if task_type == "comments":
            aweme_id = str(params.get("aweme_id") or params.get("content_id") or "")
            if not aweme_id:
                raise ValueError("Douyin comments task requires aweme_id or content_id")
            comments_limit = self._optional_int(params.get("limit")) or config.CRAWLER_MAX_COMMENTS_COUNT_SINGLENOTES
            return PlatformTaskRequest(
                job_id=job_id,
                platform_code=self.platform_code,
                task_kind="comments",
                payload={"content_id": aweme_id, "cursor": params.get("cursor", 0), "limit": comments_limit},
            )
        if task_type == "creator":
            creator_id = str(params.get("creator_id") or "")
            if not creator_id:
                raise ValueError("Douyin creator task requires creator_id")
            return PlatformTaskRequest(
                job_id=job_id,
                platform_code=self.platform_code,
                task_kind="creator",
                payload={"creator_id": creator_id},
            )
        if task_type == "creator_contents":
            creator_id = str(params.get("creator_id") or "")
            if not creator_id:
                raise ValueError("Douyin creator_contents task requires creator_id")
            return PlatformTaskRequest(
                job_id=job_id,
                platform_code=self.platform_code,
                task_kind="creator_contents",
                payload={
                    "creator_id": creator_id,
                    "cursor": self._optional_str(params.get("cursor")) or "",
                    "limit": int(params.get("limit", 18)),
                },
            )
        raise ValueError(f"Unsupported Douyin task type: {task_type}")

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

    def build_failure_event(self, *, task: CrawlTask, job_id: str, error_message: str, error_code: str) -> CrawlJobEvent:
        params = task.params or {}
        details: dict[str, Any] = {"risk_type": error_code}
        if task.task_type == "search":
            details.update({"keyword": params.get("keyword"), "page": params.get("page"), "search_id": params.get("search_id", "")})
        elif task.task_type in {"detail", "comments"}:
            details["aweme_id"] = params.get("aweme_id") or params.get("content_id")
        elif task.task_type == "creator":
            details["creator_id"] = params.get("creator_id")
        elif task.task_type == "creator_contents":
            details.update({"creator_id": params.get("creator_id"), "cursor": params.get("cursor", "")})
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
            search_items = payload.get("items", [])
            normalized_records = normalize_search_items(search_items)
            await services.normalized_content_service.append_many(normalized_records)
            if payload.get("raw"):
                await services.raw_record_service.append(
                    RawRecord(
                        platform_code=self.platform_code,
                        record_type="search",
                        source_uri="/aweme/v1/web/general/search/single/",
                        request_meta={
                            "keyword": params.get("keyword"),
                            "page": params.get("page"),
                            "search_id": params.get("search_id", ""),
                            "job_id": job_id,
                        },
                        response_body=payload.get("raw"),
                        metadata={"bridge": "douyin_connector", "normalized_count": len(normalized_records)},
                    )
                )
            await services.event_service.append(
                CrawlJobEvent(
                    job_id=job_id,
                    event_type="search_page_succeeded",
                    message="Douyin bridge search page succeeded",
                    details={
                        "keyword": params.get("keyword"),
                        "page": params.get("page"),
                        "items_count": len(search_items),
                        "normalized_count": len(normalized_records),
                        "next_cursor": payload.get("next_cursor"),
                    },
                ),
                platform_code=self.platform_code,
            )
            return {
                "items": search_items,
                "normalized_records": normalized_records,
                "next_cursor": payload.get("next_cursor"),
                "raw": payload.get("raw"),
            }
        if task.task_type == "detail":
            aweme_id = str(params.get("aweme_id") or params.get("content_id") or "")
            aweme_detail = payload["aweme_detail"]
            normalized_record = normalize_aweme_detail(aweme_detail)
            if normalized_record is not None:
                await services.normalized_content_service.append_many([normalized_record])
            raw_payload = payload.get("raw_payload")
            if raw_payload:
                await services.raw_record_service.append(
                    RawRecord(
                        platform_code=self.platform_code,
                        record_type="detail",
                        source_uri=payload.get("request_uri", "/aweme/v1/web/aweme/detail/"),
                        request_meta={"aweme_id": aweme_id, "job_id": job_id, "request_params": payload.get("request_params", {})},
                        response_body=raw_payload,
                        metadata={"bridge": "douyin_connector", "normalized_count": 1 if normalized_record is not None else 0},
                    )
                )
            await services.event_service.append(
                CrawlJobEvent(
                    job_id=job_id,
                    event_type="detail_succeeded",
                    message="Douyin bridge detail succeeded",
                    details={"aweme_id": aweme_id},
                ),
                platform_code=self.platform_code,
            )
            return {"aweme_detail": aweme_detail, "normalized_record": normalized_record}
        if task.task_type == "comments":
            aweme_id = str(params.get("aweme_id") or params.get("content_id") or "")
            await services.raw_record_service.append(
                RawRecord(
                    platform_code=self.platform_code,
                    record_type="comments",
                    source_uri=payload.get("request_uri", "/aweme/v1/web/comment/list/"),
                    request_meta={
                        "aweme_id": aweme_id,
                        "job_id": job_id,
                        "limit": self._optional_int(params.get("limit")) or config.CRAWLER_MAX_COMMENTS_COUNT_SINGLENOTES,
                        "cursor": params.get("cursor", 0),
                    },
                    response_body=payload,
                    metadata={
                        "bridge": "douyin_connector",
                        "comment_count": len(payload.get("comments", [])),
                        "cursor": payload.get("cursor"),
                        "has_more": payload.get("has_more"),
                    },
                )
            )
            await services.event_service.append(
                CrawlJobEvent(
                    job_id=job_id,
                    event_type="comments_succeeded",
                    message="Douyin bridge comments succeeded",
                    details={"aweme_id": aweme_id, "comment_count": len(payload.get("comments", []))},
                ),
                platform_code=self.platform_code,
            )
            return payload
        if task.task_type == "creator":
            creator_id = str(params.get("creator_id") or "")
            raw_payload = payload.get("creator")
            if raw_payload:
                await services.raw_record_service.append(
                    RawRecord(
                        platform_code=self.platform_code,
                        record_type="creator",
                        source_uri=payload.get("request_uri", "/aweme/v1/web/user/profile/other/"),
                        request_meta={"creator_id": creator_id, "job_id": job_id, "request_params": payload.get("request_params", {})},
                        response_body=raw_payload,
                        metadata={"bridge": "douyin_connector"},
                    )
                )
            await services.event_service.append(
                CrawlJobEvent(
                    job_id=job_id,
                    event_type="creator_succeeded",
                    message="Douyin bridge creator succeeded",
                    details={"creator_id": creator_id},
                ),
                platform_code=self.platform_code,
            )
            return payload
        if task.task_type == "creator_contents":
            creator_id = str(params.get("creator_id") or "")
            cursor = self._optional_str(params.get("cursor")) or ""
            items = payload.get("items", [])
            normalized_records = []
            for item in items:
                record = normalize_aweme_detail(item)
                if record is not None:
                    normalized_records.append(record)
            await services.normalized_content_service.append_many(normalized_records)
            raw_payload = payload.get("raw_payload")
            if raw_payload:
                await services.raw_record_service.append(
                    RawRecord(
                        platform_code=self.platform_code,
                        record_type="creator_contents",
                        source_uri=payload.get("request_uri", "/aweme/v1/web/aweme/post/"),
                        request_meta={"creator_id": creator_id, "job_id": job_id, "cursor": cursor, "request_params": payload.get("request_params", {})},
                        response_body=raw_payload,
                        metadata={"bridge": "douyin_connector", "normalized_count": len(normalized_records)},
                    )
                )
            await services.event_service.append(
                CrawlJobEvent(
                    job_id=job_id,
                    event_type="creator_contents_succeeded",
                    message="Douyin bridge creator contents succeeded",
                    details={"creator_id": creator_id, "items_count": len(items), "next_cursor": payload.get("next_cursor")},
                ),
                platform_code=self.platform_code,
            )
            return {**payload, "normalized_records": normalized_records}
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
