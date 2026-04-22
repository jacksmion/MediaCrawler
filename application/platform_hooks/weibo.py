from __future__ import annotations

from typing import Any

from connectors.weibo import build_weibo_connector_from_legacy
from connectors.weibo.errors import WeiboDataFetchError
from connectors.weibo.normalizer import normalize_weibo_note, normalize_weibo_notes
from schemas.tasks.models import CrawlJobEvent, CrawlTask, RawRecord
from schemas.tasks.runtime import PlatformTaskRequest, PlatformTaskResult

from .base import BasePlatformHooks, ExecutionServices


class WeiboPlatformHooks(BasePlatformHooks):
    platform_code = "weibo"
    short_code = "wb"
    source_name = "legacy_weibo_crawler"
    handled_exceptions = (WeiboDataFetchError,)

    def build_connector(self):
        return build_weibo_connector_from_legacy(self.crawler)

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
                    "filters": {"search_type": str(params.get("search_type", "default"))},
                },
            )
        if task_type == "detail":
            note_id = str(params.get("note_id") or params.get("content_id") or "")
            if not note_id:
                raise ValueError("Weibo detail task requires note_id")
            return PlatformTaskRequest(
                job_id=job_id,
                platform_code=self.platform_code,
                task_kind="detail",
                payload={"content_id": note_id},
            )
        if task_type == "comments":
            note_id = str(params.get("note_id") or params.get("content_id") or "")
            if not note_id:
                raise ValueError("Weibo comments task requires note_id")
            return PlatformTaskRequest(
                job_id=job_id,
                platform_code=self.platform_code,
                task_kind="comments",
                payload={
                    "content_id": note_id,
                    "cursor": params.get("cursor", -1),
                    "limit": self._optional_int(params.get("limit")) or 10,
                },
            )
        if task_type == "creator":
            creator_id = str(params.get("creator_id") or "")
            if not creator_id:
                raise ValueError("Weibo creator task requires creator_id")
            return PlatformTaskRequest(
                job_id=job_id,
                platform_code=self.platform_code,
                task_kind="creator",
                payload={"creator_id": creator_id},
            )
        if task_type == "creator_contents":
            creator_id = str(params.get("creator_id") or "")
            if not creator_id:
                raise ValueError("Weibo creator_contents task requires creator_id")
            return PlatformTaskRequest(
                job_id=job_id,
                platform_code=self.platform_code,
                task_kind="creator_contents",
                payload={
                    "creator_id": creator_id,
                    "cursor": self._optional_str(params.get("cursor")) or "",
                    "limit": int(params.get("limit", 10)),
                },
            )
        raise ValueError(f"Unsupported Weibo task type: {task_type}")

    def classify_error(self, message: str) -> str:
        lowered = message.lower()
        if "cookie" in lowered or "auth" in lowered:
            return "session_not_ready"
        if "parse" in lowered:
            return "parse_failed"
        if "status 4" in lowered or "status 5" in lowered:
            return "http_error"
        return "unknown_error"

    def build_failure_event(self, *, task: CrawlTask, job_id: str, error_message: str, error_code: str) -> CrawlJobEvent:
        params = task.params or {}
        details: dict[str, Any] = {"risk_type": error_code}
        if task.task_type == "search":
            details.update({"keyword": params.get("keyword"), "page": params.get("page")})
        elif task.task_type in {"detail", "comments"}:
            details["note_id"] = params.get("note_id") or params.get("content_id")
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
            notes = payload.get("items", [])
            normalized_records = normalize_weibo_notes(notes)
            await services.normalized_content_service.append_many(normalized_records)
            await services.raw_record_service.append(
                RawRecord(
                    platform_code=self.platform_code,
                    record_type="search",
                    source_uri="/api/container/getIndex",
                    request_meta={"keyword": params.get("keyword"), "page": params.get("page"), "job_id": job_id},
                    response_body=payload.get("raw"),
                    metadata={"bridge": "weibo_connector", "normalized_count": len(normalized_records)},
                )
            )
            await services.event_service.append(
                CrawlJobEvent(
                    job_id=job_id,
                    event_type="search_page_succeeded",
                    message="Weibo bridge search page succeeded",
                    details={"keyword": params.get("keyword"), "page": params.get("page"), "items_count": len(notes)},
                ),
                platform_code=self.platform_code,
            )
            return {**payload, "normalized_records": normalized_records}
        if task.task_type == "detail":
            note = payload["note"]
            normalized_record = normalize_weibo_note(note)
            if normalized_record is not None:
                await services.normalized_content_service.append_many([normalized_record])
            note_id = str(params.get("note_id") or params.get("content_id") or "")
            await services.raw_record_service.append(
                RawRecord(
                    platform_code=self.platform_code,
                    record_type="detail",
                    source_uri=payload.get("request_uri", f"/detail/{note_id}"),
                    request_meta={"note_id": note_id, "job_id": job_id},
                    response_body=payload.get("raw_payload"),
                    metadata={"bridge": "weibo_connector"},
                )
            )
            await services.event_service.append(
                CrawlJobEvent(
                    job_id=job_id,
                    event_type="detail_succeeded",
                    message="Weibo bridge detail succeeded",
                    details={"note_id": note_id},
                ),
                platform_code=self.platform_code,
            )
            return {"note": note}
        if task.task_type == "comments":
            note_id = str(params.get("note_id") or params.get("content_id") or "")
            await services.raw_record_service.append(
                RawRecord(
                    platform_code=self.platform_code,
                    record_type="comments",
                    source_uri=payload.get("request_uri", "/comments/hotflow"),
                    request_meta={"note_id": note_id, "job_id": job_id},
                    response_body=payload.get("raw_payload"),
                    metadata={"bridge": "weibo_connector", "comment_count": len(payload.get("comments", []))},
                )
            )
            await services.event_service.append(
                CrawlJobEvent(
                    job_id=job_id,
                    event_type="comments_succeeded",
                    message="Weibo bridge comments succeeded",
                    details={"note_id": note_id, "comment_count": len(payload.get("comments", []))},
                ),
                platform_code=self.platform_code,
            )
            return payload
        if task.task_type == "creator":
            creator_id = str(params.get("creator_id") or "")
            await services.raw_record_service.append(
                RawRecord(
                    platform_code=self.platform_code,
                    record_type="creator",
                    source_uri=payload.get("request_uri", "/api/container/getIndex"),
                    request_meta={"creator_id": creator_id, "job_id": job_id},
                    response_body=payload.get("raw_payload"),
                    metadata={"bridge": "weibo_connector"},
                )
            )
            await services.event_service.append(
                CrawlJobEvent(
                    job_id=job_id,
                    event_type="creator_succeeded",
                    message="Weibo bridge creator succeeded",
                    details={"creator_id": creator_id},
                ),
                platform_code=self.platform_code,
            )
            return payload
        if task.task_type == "creator_contents":
            creator_id = str(params.get("creator_id") or "")
            cursor = self._optional_str(params.get("cursor")) or ""
            notes = payload.get("items", [])
            normalized_records = normalize_weibo_notes(notes)
            await services.normalized_content_service.append_many(normalized_records)
            await services.raw_record_service.append(
                RawRecord(
                    platform_code=self.platform_code,
                    record_type="creator_contents",
                    source_uri=payload.get("request_uri", "/api/container/getIndex"),
                    request_meta={"creator_id": creator_id, "job_id": job_id, "cursor": cursor},
                    response_body=payload.get("raw_payload"),
                    metadata={"bridge": "weibo_connector", "normalized_count": len(normalized_records)},
                )
            )
            await services.event_service.append(
                CrawlJobEvent(
                    job_id=job_id,
                    event_type="creator_contents_succeeded",
                    message="Weibo bridge creator contents succeeded",
                    details={"creator_id": creator_id, "items_count": len(notes)},
                ),
                platform_code=self.platform_code,
            )
            return {**payload, "normalized_records": normalized_records}
        raise ValueError(f"Unsupported Weibo task type: {task.task_type}")

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
