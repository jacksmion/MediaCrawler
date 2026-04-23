from __future__ import annotations

from typing import Any

from connectors.tieba import build_tieba_connector_from_legacy
from connectors.tieba.errors import TiebaDataFetchError
from connectors.tieba.normalizer import normalize_tieba_note, normalize_tieba_notes
from model.m_baidu_tieba import TiebaNote
from schemas.tasks.models import CrawlJobEvent, CrawlTask, RawRecord
from schemas.tasks.runtime import PlatformTaskRequest, PlatformTaskResult

from connectors.base.execution import BasePlatformHooks, ExecutionServices


class TiebaPlatformHooks(BasePlatformHooks):
    platform_code = "tieba"
    short_code = "tb"
    source_name = "legacy_tieba_crawler"
    handled_exceptions = (TiebaDataFetchError,)

    def build_connector(self):
        return build_tieba_connector_from_legacy(self.crawler)

    def use_generic_success_handling(self) -> bool:
        return True

    def build_request(self, task: CrawlTask, job_id: str) -> PlatformTaskRequest:
        params = task.params or {}
        if task.task_type == "search":
            return PlatformTaskRequest(job_id=job_id, platform_code=self.platform_code, task_kind="search", payload={"keyword": str(params["keyword"]), "page": int(params.get("page", 1)), "page_size": int(params.get("page_size", 10))})
        if task.task_type == "detail":
            return PlatformTaskRequest(job_id=job_id, platform_code=self.platform_code, task_kind="detail", payload={"content_id": str(params.get("note_id") or ""), "extra": {"detail_url": str(params.get("detail_url") or "")}})
        if task.task_type == "comments":
            note_payload = params.get("note")
            note = TiebaNote.model_validate(note_payload) if isinstance(note_payload, dict) else None
            return PlatformTaskRequest(job_id=job_id, platform_code=self.platform_code, task_kind="comments", payload={"content_id": note.note_id if note else str(params.get("note_id") or ""), "cursor": params.get("cursor", 1), "limit": int(params.get("limit", 10)), "extra": {"note": note.model_dump() if note else note_payload}})
        if task.task_type == "creator":
            return PlatformTaskRequest(job_id=job_id, platform_code=self.platform_code, task_kind="creator", payload={"creator_id": str(params.get("creator_url") or "")})
        if task.task_type == "creator_contents":
            return PlatformTaskRequest(job_id=job_id, platform_code=self.platform_code, task_kind="creator_contents", payload={"creator_id": str(params.get("creator_url") or ""), "cursor": str(params.get("cursor", "")), "limit": int(params.get("limit", 20))})
        raise ValueError(f"Unsupported Tieba task type: {task.task_type}")

    def classify_error(self, message: str) -> str:
        lowered = message.lower()
        if "browser page" in lowered:
            return "session_not_ready"
        if "parse" in lowered:
            return "parse_failed"
        if "navigation" in lowered:
            return "navigation_failed"
        return "unknown_error"

    def build_failure_event(self, *, task: CrawlTask, job_id: str, error_message: str, error_code: str) -> CrawlJobEvent:
        params = task.params or {}
        details: dict[str, Any] = {"risk_type": error_code}
        if task.task_type == "search":
            details.update({"keyword": params.get("keyword"), "page": params.get("page")})
        elif task.task_type in {"detail", "comments"}:
            details["note_id"] = params.get("note_id") or (params.get("note") or {}).get("note_id")
        else:
            details.update({"creator_url": params.get("creator_url"), "cursor": params.get("cursor", "")})
        return CrawlJobEvent(job_id=job_id, event_type=f"{task.task_type}_failed", message=error_message, details=details)

    async def handle_success(self, *, task: CrawlTask, request: PlatformTaskRequest, task_result: PlatformTaskResult, job_id: str, task_id: str, services: ExecutionServices) -> dict[str, Any]:
        payload = task_result.payload
        params = task.params or {}
        if task.task_type == "search":
            notes = [TiebaNote.model_validate(item) for item in payload.get("items", [])]
            normalized_records = normalize_tieba_notes(notes)
            await services.normalized_content_service.append_many(normalized_records)
            await services.raw_record_service.append(RawRecord(platform_code=self.platform_code, record_type="search", source_uri=payload.get("metadata", {}).get("request_url", ""), request_meta={"keyword": params.get("keyword"), "page": params.get("page"), "job_id": job_id}, response_body=payload.get("raw"), metadata={"bridge": "tieba_connector", "normalized_count": len(normalized_records)}))
            await services.event_service.append(CrawlJobEvent(job_id=job_id, event_type="search_page_succeeded", message="Tieba bridge search page succeeded", details={"keyword": params.get("keyword"), "page": params.get("page"), "items_count": len(notes)}), platform_code=self.platform_code)
            return {"items": [note.model_dump() for note in notes], "normalized_records": normalized_records, "has_more": payload.get("has_more", False), "next_cursor": payload.get("next_cursor")}
        if task.task_type == "detail":
            note = TiebaNote.model_validate(payload["note"])
            normalized_record = normalize_tieba_note(note)
            await services.normalized_content_service.append_many([normalized_record])
            await services.raw_record_service.append(RawRecord(platform_code=self.platform_code, record_type="detail", source_uri=payload.get("request_uri", str(params.get("detail_url") or "")), request_meta={"note_id": params.get("note_id"), "job_id": job_id}, response_body=payload.get("raw_payload"), metadata={"bridge": "tieba_connector"}))
            await services.event_service.append(CrawlJobEvent(job_id=job_id, event_type="detail_succeeded", message="Tieba bridge detail succeeded", details={"note_id": params.get("note_id")}), platform_code=self.platform_code)
            return {"note": note}
        if task.task_type == "comments":
            note_payload = params.get("note") or {}
            note_id = note_payload.get("note_id") or params.get("note_id")
            await services.raw_record_service.append(RawRecord(platform_code=self.platform_code, record_type="comments", source_uri=payload.get("request_uri", ""), request_meta={"note_id": note_id, "job_id": job_id}, response_body=payload.get("raw_payload"), metadata={"bridge": "tieba_connector", "comment_count": len(payload.get("comments", []))}))
            await services.event_service.append(CrawlJobEvent(job_id=job_id, event_type="comments_succeeded", message="Tieba bridge comments succeeded", details={"note_id": note_id, "comment_count": len(payload.get("comments", []))}), platform_code=self.platform_code)
            return payload
        if task.task_type == "creator":
            await services.raw_record_service.append(RawRecord(platform_code=self.platform_code, record_type="creator", source_uri=payload.get("request_uri", str(params.get("creator_url") or "")), request_meta={"creator_url": params.get("creator_url"), "job_id": job_id}, response_body=payload.get("raw_payload"), metadata={"bridge": "tieba_connector"}))
            await services.event_service.append(CrawlJobEvent(job_id=job_id, event_type="creator_succeeded", message="Tieba bridge creator succeeded", details={"creator_url": params.get("creator_url")}), platform_code=self.platform_code)
            return payload
        notes = [TiebaNote.model_validate(item) for item in payload.get("items", [])]
        normalized_records = normalize_tieba_notes(notes)
        await services.normalized_content_service.append_many(normalized_records)
        await services.raw_record_service.append(RawRecord(platform_code=self.platform_code, record_type="creator_contents", source_uri=payload.get("request_uri", str(params.get("creator_url") or "")), request_meta={"creator_url": params.get("creator_url"), "job_id": job_id, "cursor": params.get("cursor", "")}, response_body=payload.get("raw_payload"), metadata={"bridge": "tieba_connector", "normalized_count": len(normalized_records)}))
        await services.event_service.append(CrawlJobEvent(job_id=job_id, event_type="creator_contents_succeeded", message="Tieba bridge creator contents succeeded", details={"creator_url": params.get("creator_url"), "items_count": len(notes)}), platform_code=self.platform_code)
        return {"items": [note.model_dump() for note in notes], "normalized_records": normalized_records, "has_more": payload.get("has_more", False), "next_cursor": payload.get("next_cursor", "")}
