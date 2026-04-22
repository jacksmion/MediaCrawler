from __future__ import annotations

from typing import Any

from connectors.xhs import build_xhs_connector_from_legacy
from connectors.xhs.errors import XhsDataFetchError
from connectors.xhs.normalizer import normalize_xhs_note, normalize_xhs_notes
from connectors.xhs.helpers import get_search_id, parse_note_info_from_note_url
from schemas.tasks.models import CrawlJobEvent, CrawlTask, RawRecord
from schemas.tasks.runtime import PlatformTaskRequest, PlatformTaskResult

from .base import BasePlatformHooks, ExecutionServices


class XhsPlatformHooks(BasePlatformHooks):
    platform_code = "xhs"
    short_code = "xhs"
    source_name = "legacy_xhs_crawler"
    handled_exceptions = (XhsDataFetchError,)

    def build_connector(self):
        return build_xhs_connector_from_legacy(self.crawler)

    def build_request(self, task: CrawlTask, job_id: str) -> PlatformTaskRequest:
        params = task.params or {}
        task_type = task.task_type
        if task_type == "search":
            search_id = get_search_id()
            return PlatformTaskRequest(
                job_id=job_id,
                platform_code=self.platform_code,
                task_kind="search",
                payload={
                    "keyword": str(params["keyword"]),
                    "page": int(params.get("page", 1)),
                    "page_size": int(params.get("page_size", 20)),
                    "filters": {"sort": str(params.get("sort_type", "general")), "search_id": search_id},
                },
                metadata={"search_id": search_id},
            )
        if task_type == "detail":
            note_id, xsec_source, xsec_token = self._resolve_detail_params(params)
            return PlatformTaskRequest(
                job_id=job_id,
                platform_code=self.platform_code,
                task_kind="detail",
                payload={"content_id": note_id, "extra": {"xsec_source": xsec_source, "xsec_token": xsec_token}},
            )
        if task_type == "comments":
            note_id = str(params.get("note_id") or "")
            xsec_token = str(params.get("xsec_token") or "")
            if not note_id or not xsec_token:
                raise ValueError("XHS comments task requires note_id and xsec_token")
            return PlatformTaskRequest(
                job_id=job_id,
                platform_code=self.platform_code,
                task_kind="comments",
                payload={"content_id": note_id, "limit": self._optional_int(params.get("limit")) or 10, "extra": {"xsec_token": xsec_token}},
            )
        if task_type == "creator":
            creator_url = str(params.get("creator_url") or "")
            if not creator_url:
                raise ValueError("XHS creator task requires creator_url")
            return PlatformTaskRequest(
                job_id=job_id,
                platform_code=self.platform_code,
                task_kind="creator",
                payload={"creator_id": creator_url},
            )
        if task_type == "creator_contents":
            creator_url = str(params.get("creator_url") or "")
            if not creator_url:
                raise ValueError("XHS creator_contents task requires creator_url")
            return PlatformTaskRequest(
                job_id=job_id,
                platform_code=self.platform_code,
                task_kind="creator_contents",
                payload={"creator_id": creator_url, "cursor": self._optional_str(params.get("cursor")) or "", "limit": int(params.get("limit", 30))},
            )
        raise ValueError(f"Unsupported XHS task type: {task_type}")

    def classify_error(self, message: str) -> str:
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

    def build_failure_event(self, *, task: CrawlTask, job_id: str, error_message: str, error_code: str) -> CrawlJobEvent:
        params = task.params or {}
        details: dict[str, Any] = {"risk_type": error_code}
        if task.task_type == "search":
            details.update({"keyword": params.get("keyword"), "page": params.get("page")})
        elif task.task_type in {"detail", "comments"}:
            details["note_id"] = params.get("note_id")
        elif task.task_type == "creator":
            details["creator_url"] = params.get("creator_url")
        elif task.task_type == "creator_contents":
            details.update({"creator_url": params.get("creator_url"), "cursor": params.get("cursor", "")})
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
            raw_items = payload.get("items", [])
            notes = await self._hydrate_note_details(raw_items, default_xsec_source="pc_search")
            normalized_records = normalize_xhs_notes(notes)
            await services.raw_record_service.append(
                RawRecord(
                    platform_code=self.platform_code,
                    record_type="search",
                    source_uri="/api/sns/web/v1/search/notes",
                    request_meta={
                        "keyword": params.get("keyword"),
                        "page": params.get("page"),
                        "job_id": job_id,
                        "search_id": request.metadata.get("search_id", ""),
                    },
                    response_body=payload.get("raw"),
                    metadata={"bridge": "xhs_connector", "normalized_count": len(normalized_records)},
                )
            )
            await services.event_service.append(
                CrawlJobEvent(
                    job_id=job_id,
                    event_type="search_page_succeeded",
                    message="XHS bridge search page succeeded",
                    details={"keyword": params.get("keyword"), "page": params.get("page"), "items_count": len(notes)},
                ),
                platform_code=self.platform_code,
            )
            return {
                "items": notes,
                "raw_items": raw_items,
                "normalized_records": normalized_records,
                "has_more": payload.get("has_more", False),
                "next_cursor": payload.get("next_cursor"),
            }
        if task.task_type == "detail":
            note = payload["note"]
            normalized_record = normalize_xhs_note(note)
            await services.normalized_content_service.append_many([normalized_record])
            note_id = request.payload["content_id"]
            await services.raw_record_service.append(
                RawRecord(
                    platform_code=self.platform_code,
                    record_type="detail",
                    source_uri=payload.get("request_uri", "/api/sns/web/v1/feed"),
                    request_meta={"note_id": note_id, "job_id": job_id},
                    response_body=payload.get("raw_payload"),
                    metadata={"bridge": "xhs_connector"},
                )
            )
            await services.event_service.append(
                CrawlJobEvent(
                    job_id=job_id,
                    event_type="detail_succeeded",
                    message="XHS bridge detail succeeded",
                    details={"note_id": note_id},
                ),
                platform_code=self.platform_code,
            )
            return {"note": note}
        if task.task_type == "comments":
            note_id = str(params.get("note_id") or "")
            await services.raw_record_service.append(
                RawRecord(
                    platform_code=self.platform_code,
                    record_type="comments",
                    source_uri=payload.get("request_uri", "/api/sns/web/v2/comment/page"),
                    request_meta={"note_id": note_id, "job_id": job_id},
                    response_body=payload.get("raw_payload"),
                    metadata={"bridge": "xhs_connector", "comment_count": len(payload.get("comments", []))},
                )
            )
            await services.event_service.append(
                CrawlJobEvent(
                    job_id=job_id,
                    event_type="comments_succeeded",
                    message="XHS bridge comments succeeded",
                    details={"note_id": note_id, "comment_count": len(payload.get("comments", []))},
                ),
                platform_code=self.platform_code,
            )
            return payload
        if task.task_type == "creator":
            creator_url = str(params.get("creator_url") or "")
            await services.raw_record_service.append(
                RawRecord(
                    platform_code=self.platform_code,
                    record_type="creator",
                    source_uri=payload.get("request_uri", creator_url),
                    request_meta={"creator_url": creator_url, "job_id": job_id},
                    response_body=payload.get("raw_payload"),
                    metadata={"bridge": "xhs_connector"},
                )
            )
            await services.event_service.append(
                CrawlJobEvent(
                    job_id=job_id,
                    event_type="creator_succeeded",
                    message="XHS bridge creator succeeded",
                    details={"creator_url": creator_url},
                ),
                platform_code=self.platform_code,
            )
            return payload
        if task.task_type == "creator_contents":
            creator_url = str(params.get("creator_url") or "")
            cursor = self._optional_str(params.get("cursor")) or ""
            raw_items = payload.get("items", [])
            notes = await self._hydrate_note_details(raw_items, default_xsec_source=str(payload.get("xsec_source") or "pc_feed"))
            normalized_records = normalize_xhs_notes(notes)
            await services.raw_record_service.append(
                RawRecord(
                    platform_code=self.platform_code,
                    record_type="creator_contents",
                    source_uri=payload.get("request_uri", "/api/sns/web/v1/user_posted"),
                    request_meta={"creator_url": creator_url, "job_id": job_id, "cursor": cursor},
                    response_body=payload.get("raw_payload"),
                    metadata={"bridge": "xhs_connector", "normalized_count": len(normalized_records)},
                )
            )
            await services.event_service.append(
                CrawlJobEvent(
                    job_id=job_id,
                    event_type="creator_contents_succeeded",
                    message="XHS bridge creator contents succeeded",
                    details={"creator_url": creator_url, "items_count": len(notes)},
                ),
                platform_code=self.platform_code,
            )
            return {
                "items": notes,
                "raw_items": raw_items,
                "normalized_records": normalized_records,
                "has_more": payload.get("has_more", False),
                "next_cursor": payload.get("next_cursor", ""),
            }
        raise ValueError(f"Unsupported XHS task type: {task.task_type}")

    async def _hydrate_note_details(self, raw_items: list[dict[str, Any]], *, default_xsec_source: str) -> list[dict[str, Any]]:
        if not raw_items:
            return []
        connector = self.build_connector()
        await connector.prepare(self.build_connector_context(job_id="xhs-followup", task_id="xhs-followup"))
        try:
            notes: list[dict[str, Any]] = []
            for item in raw_items:
                note_id = str(item.get("note_id") or item.get("id") or "")
                xsec_token = str(item.get("xsec_token") or "")
                if not note_id or not xsec_token:
                    continue
                detail = await connector.fetch_content_detail(
                    note_id,
                    extra={"xsec_source": str(item.get("xsec_source") or default_xsec_source), "xsec_token": xsec_token},
                )
                note = detail.get("note")
                if note:
                    notes.append(note)
            return notes
        finally:
            await connector.close()

    @staticmethod
    def _resolve_detail_params(params: dict[str, Any]) -> tuple[str, str, str]:
        note_url = str(params.get("note_url") or "")
        if note_url:
            note_info = parse_note_info_from_note_url(note_url)
            return note_info.note_id, note_info.xsec_source, note_info.xsec_token
        note_id = str(params.get("note_id") or "")
        xsec_source = str(params.get("xsec_source") or "pc_search")
        xsec_token = str(params.get("xsec_token") or "")
        if not note_id or not xsec_token:
            raise ValueError("XHS detail task requires note_url or note_id/xsec_token")
        return note_id, xsec_source, xsec_token

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
