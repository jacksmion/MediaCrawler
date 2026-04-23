from __future__ import annotations

from typing import Any

from connectors.kuaishou import build_kuaishou_connector_from_legacy
from connectors.kuaishou.errors import KuaishouDataFetchError
from connectors.kuaishou.normalizer import normalize_kuaishou_video, normalize_kuaishou_videos
from schemas.tasks.models import CrawlJobEvent, CrawlTask, RawRecord
from schemas.tasks.runtime import PlatformTaskRequest, PlatformTaskResult

from connectors.base.execution import BasePlatformHooks, ExecutionServices


class KuaishouPlatformHooks(BasePlatformHooks):
    platform_code = "kuaishou"
    short_code = "ks"
    source_name = "legacy_kuaishou_crawler"
    handled_exceptions = (KuaishouDataFetchError,)

    def build_connector(self):
        return build_kuaishou_connector_from_legacy(self.crawler)

    def use_generic_success_handling(self) -> bool:
        return True

    def build_request(self, task: CrawlTask, job_id: str) -> PlatformTaskRequest:
        params = task.params or {}
        if task.task_type == "search":
            return PlatformTaskRequest(job_id=job_id, platform_code=self.platform_code, task_kind="search", payload={"keyword": str(params["keyword"]), "page": int(params.get("page", 1)), "filters": {"search_session_id": str(params.get("search_session_id", ""))}})
        if task.task_type == "detail":
            return PlatformTaskRequest(job_id=job_id, platform_code=self.platform_code, task_kind="detail", payload={"content_id": str(params.get("video_id") or "")})
        if task.task_type == "comments":
            return PlatformTaskRequest(job_id=job_id, platform_code=self.platform_code, task_kind="comments", payload={"content_id": str(params.get("video_id") or ""), "cursor": str(params.get("cursor", "")), "limit": int(params.get("limit", 10))})
        if task.task_type == "creator":
            return PlatformTaskRequest(job_id=job_id, platform_code=self.platform_code, task_kind="creator", payload={"creator_id": str(params.get("creator_id") or "")})
        if task.task_type == "creator_contents":
            return PlatformTaskRequest(job_id=job_id, platform_code=self.platform_code, task_kind="creator_contents", payload={"creator_id": str(params.get("creator_id") or ""), "cursor": str(params.get("cursor", "")), "limit": int(params.get("limit", 20))})
        raise ValueError(f"Unsupported Kuaishou task type: {task.task_type}")

    def classify_error(self, message: str) -> str:
        lowered = message.lower()
        if "cookie" in lowered or "auth" in lowered:
            return "session_not_ready"
        if "graphql" in lowered or "rest" in lowered:
            return "request_failed"
        if "missing" in lowered:
            return "invalid_payload"
        return "unknown_error"

    def build_failure_event(self, *, task: CrawlTask, job_id: str, error_message: str, error_code: str) -> CrawlJobEvent:
        params = task.params or {}
        details: dict[str, Any] = {"risk_type": error_code}
        if task.task_type == "search":
            details.update({"keyword": params.get("keyword"), "page": params.get("page")})
        elif task.task_type in {"detail", "comments"}:
            details["video_id"] = params.get("video_id")
        else:
            details.update({"creator_id": params.get("creator_id"), "cursor": params.get("cursor", "")})
        return CrawlJobEvent(job_id=job_id, event_type=f"{task.task_type}_failed", message=error_message, details=details)

    async def handle_success(self, *, task: CrawlTask, request: PlatformTaskRequest, task_result: PlatformTaskResult, job_id: str, task_id: str, services: ExecutionServices) -> dict[str, Any]:
        payload = task_result.payload
        params = task.params or {}
        if task.task_type == "search":
            video_items = payload.get("items", [])
            normalized_records = normalize_kuaishou_videos(video_items)
            await services.normalized_content_service.append_many(normalized_records)
            await services.raw_record_service.append(RawRecord(platform_code=self.platform_code, record_type="search", source_uri="/graphql", request_meta={"keyword": params.get("keyword"), "page": params.get("page"), "job_id": job_id}, response_body=payload.get("raw"), metadata={"bridge": "kuaishou_connector", "normalized_count": len(normalized_records)}))
            await services.event_service.append(CrawlJobEvent(job_id=job_id, event_type="search_page_succeeded", message="Kuaishou bridge search page succeeded", details={"keyword": params.get("keyword"), "page": params.get("page"), "items_count": len(video_items)}), platform_code=self.platform_code)
            return {**payload, "normalized_records": normalized_records}
        if task.task_type == "detail":
            video = payload["video"]
            normalized_record = normalize_kuaishou_video(video)
            if normalized_record is not None:
                await services.normalized_content_service.append_many([normalized_record])
            await services.raw_record_service.append(RawRecord(platform_code=self.platform_code, record_type="detail", source_uri=payload.get("request_uri", "/graphql"), request_meta={"video_id": params.get("video_id"), "job_id": job_id}, response_body=payload.get("raw_payload"), metadata={"bridge": "kuaishou_connector"}))
            await services.event_service.append(CrawlJobEvent(job_id=job_id, event_type="detail_succeeded", message="Kuaishou bridge detail succeeded", details={"video_id": params.get("video_id")}), platform_code=self.platform_code)
            return {"video": video}
        if task.task_type == "comments":
            await services.raw_record_service.append(RawRecord(platform_code=self.platform_code, record_type="comments", source_uri=payload.get("request_uri", "/rest/v/photo/comment/list"), request_meta={"video_id": params.get("video_id"), "job_id": job_id}, response_body=payload.get("raw_payload"), metadata={"bridge": "kuaishou_connector", "comment_count": len(payload.get("comments", []))}))
            await services.event_service.append(CrawlJobEvent(job_id=job_id, event_type="comments_succeeded", message="Kuaishou bridge comments succeeded", details={"video_id": params.get("video_id"), "comment_count": len(payload.get("comments", []))}), platform_code=self.platform_code)
            return payload
        if task.task_type == "creator":
            await services.raw_record_service.append(RawRecord(platform_code=self.platform_code, record_type="creator", source_uri=payload.get("request_uri", "/graphql"), request_meta={"creator_id": params.get("creator_id"), "job_id": job_id}, response_body=payload.get("raw_payload"), metadata={"bridge": "kuaishou_connector"}))
            await services.event_service.append(CrawlJobEvent(job_id=job_id, event_type="creator_succeeded", message="Kuaishou bridge creator succeeded", details={"creator_id": params.get("creator_id")}), platform_code=self.platform_code)
            return payload
        video_items = payload.get("items", [])
        normalized_records = normalize_kuaishou_videos(video_items)
        await services.normalized_content_service.append_many(normalized_records)
        await services.raw_record_service.append(RawRecord(platform_code=self.platform_code, record_type="creator_contents", source_uri=payload.get("request_uri", "/graphql"), request_meta={"creator_id": params.get("creator_id"), "job_id": job_id, "cursor": params.get("cursor", "")}, response_body=payload.get("raw_payload"), metadata={"bridge": "kuaishou_connector", "normalized_count": len(normalized_records)}))
        await services.event_service.append(CrawlJobEvent(job_id=job_id, event_type="creator_contents_succeeded", message="Kuaishou bridge creator contents succeeded", details={"creator_id": params.get("creator_id"), "items_count": len(video_items)}), platform_code=self.platform_code)
        return {**payload, "normalized_records": normalized_records}
