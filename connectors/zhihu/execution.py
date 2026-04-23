from __future__ import annotations

from typing import Any

from constant import zhihu as zhihu_constant
from connectors.zhihu import build_zhihu_connector_from_legacy
from connectors.zhihu.errors import ZhihuDataFetchError
from connectors.zhihu.normalizer import normalize_zhihu_content, normalize_zhihu_contents
from model.m_zhihu import ZhihuContent
from schemas.tasks.models import CrawlJobEvent, CrawlTask, RawRecord
from schemas.tasks.runtime import PlatformTaskRequest, PlatformTaskResult

from connectors.base.execution import BasePlatformHooks, ExecutionServices


class ZhihuPlatformHooks(BasePlatformHooks):
    platform_code = "zhihu"
    short_code = "zh"
    source_name = "legacy_zhihu_crawler"
    handled_exceptions = (ZhihuDataFetchError,)

    def build_connector(self):
        return build_zhihu_connector_from_legacy(self.crawler)

    def use_generic_success_handling(self) -> bool:
        return True

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
                    "page_size": int(params.get("page_size", 20)),
                },
            )
        if task_type == "detail":
            note_url = str(params.get("note_url") or "").split("?")[0]
            if not note_url:
                raise ValueError("Zhihu detail task requires note_url")
            content_id, content_type, question_id = self._parse_note_url(note_url)
            return PlatformTaskRequest(
                job_id=job_id,
                platform_code=self.platform_code,
                task_kind="detail",
                payload={
                    "content_id": content_id,
                    "extra": {"content_type": content_type, "detail_url": note_url, "question_id": question_id},
                },
            )
        if task_type == "comments":
            content_payload = params.get("content")
            if not isinstance(content_payload, dict):
                raise ValueError("Zhihu comments task requires content payload")
            content = ZhihuContent.model_validate(content_payload)
            return PlatformTaskRequest(
                job_id=job_id,
                platform_code=self.platform_code,
                task_kind="comments",
                payload={
                    "content_id": content.content_id,
                    "cursor": self._optional_str(params.get("cursor")) or "",
                    "limit": self._optional_int(params.get("limit")) or 10,
                    "extra": {"content_type": content.content_type, "content": content.model_dump()},
                },
            )
        if task_type == "creator":
            creator_url = str(params.get("creator_url") or "")
            if not creator_url:
                raise ValueError("Zhihu creator task requires creator_url")
            return PlatformTaskRequest(
                job_id=job_id,
                platform_code=self.platform_code,
                task_kind="creator",
                payload={"creator_id": self._parse_creator_url(creator_url)},
            )
        if task_type == "creator_contents":
            creator_url = str(params.get("creator_url") or "")
            if not creator_url:
                raise ValueError("Zhihu creator_contents task requires creator_url")
            return PlatformTaskRequest(
                job_id=job_id,
                platform_code=self.platform_code,
                task_kind="creator_contents",
                payload={
                    "creator_id": self._parse_creator_url(creator_url),
                    "cursor": self._optional_str(params.get("cursor")) or "",
                    "limit": int(params.get("limit", 20)),
                },
            )
        raise ValueError(f"Unsupported Zhihu task type: {task_type}")

    def classify_error(self, message: str) -> str:
        lowered = message.lower()
        if "d_c0" in lowered or "browser state" in lowered:
            return "session_not_ready"
        if "status 4" in lowered or "status 5" in lowered:
            return "http_error"
        if "parse" in lowered:
            return "parse_failed"
        return "unknown_error"

    def build_failure_event(self, *, task: CrawlTask, job_id: str, error_message: str, error_code: str) -> CrawlJobEvent:
        params = task.params or {}
        details: dict[str, Any] = {"risk_type": error_code}
        if task.task_type == "search":
            details.update({"keyword": params.get("keyword"), "page": params.get("page")})
        elif task.task_type == "detail":
            note_url = str(params.get("note_url") or "").split("?")[0]
            if note_url:
                content_id, content_type, _ = self._parse_note_url(note_url)
                details.update({"content_id": content_id, "content_type": content_type})
        elif task.task_type == "comments":
            content = params.get("content") or {}
            if isinstance(content, dict):
                details.update({"content_id": content.get("content_id"), "content_type": content.get("content_type")})
        elif task.task_type == "creator":
            details["creator_id"] = self._parse_creator_url(str(params.get("creator_url") or ""))
        elif task.task_type == "creator_contents":
            details.update({"creator_id": self._parse_creator_url(str(params.get("creator_url") or "")), "cursor": params.get("cursor", "")})
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
            items = [ZhihuContent.model_validate(item) for item in payload.get("items", [])]
            normalized_records = normalize_zhihu_contents(items)
            await services.normalized_content_service.append_many(normalized_records)
            await services.raw_record_service.append(
                RawRecord(
                    platform_code=self.platform_code,
                    record_type="search",
                    source_uri="/api/v4/search_v3",
                    request_meta={"keyword": params.get("keyword"), "page": params.get("page"), "job_id": job_id},
                    response_body=payload.get("raw"),
                    metadata={"bridge": "zhihu_connector", "normalized_count": len(normalized_records)},
                )
            )
            await services.event_service.append(
                CrawlJobEvent(
                    job_id=job_id,
                    event_type="search_page_succeeded",
                    message="Zhihu bridge search page succeeded",
                    details={"keyword": params.get("keyword"), "page": params.get("page"), "items_count": len(items)},
                ),
                platform_code=self.platform_code,
            )
            return {
                "items": [item.model_dump() for item in items],
                "normalized_records": normalized_records,
                "has_more": payload.get("has_more", False),
                "next_cursor": payload.get("next_cursor"),
            }
        if task.task_type == "detail":
            content = ZhihuContent.model_validate(payload["content"])
            normalized_record = normalize_zhihu_content(content)
            await services.normalized_content_service.append_many([normalized_record])
            content_id = request.payload["content_id"]
            detail_url = request.payload.get("extra", {}).get("detail_url", "")
            await services.raw_record_service.append(
                RawRecord(
                    platform_code=self.platform_code,
                    record_type="detail",
                    source_uri=payload.get("request_uri", detail_url),
                    request_meta={"content_id": content_id, "job_id": job_id},
                    response_body=payload.get("raw_payload"),
                    metadata={"bridge": "zhihu_connector", "content_type": content.content_type},
                )
            )
            await services.event_service.append(
                CrawlJobEvent(
                    job_id=job_id,
                    event_type="detail_succeeded",
                    message="Zhihu bridge detail succeeded",
                    details={"content_id": content_id, "content_type": content.content_type},
                ),
                platform_code=self.platform_code,
            )
            return {"content": content}
        if task.task_type == "comments":
            content_payload = params.get("content") or {}
            content_id = content_payload.get("content_id")
            await services.raw_record_service.append(
                RawRecord(
                    platform_code=self.platform_code,
                    record_type="comments",
                    source_uri=payload.get("request_uri", ""),
                    request_meta={"content_id": content_id, "job_id": job_id},
                    response_body=payload.get("raw_payload"),
                    metadata={"bridge": "zhihu_connector", "comment_count": len(payload.get("comments", []))},
                )
            )
            await services.event_service.append(
                CrawlJobEvent(
                    job_id=job_id,
                    event_type="comments_succeeded",
                    message="Zhihu bridge comments succeeded",
                    details={"content_id": content_id, "comment_count": len(payload.get("comments", []))},
                ),
                platform_code=self.platform_code,
            )
            return payload
        if task.task_type == "creator":
            creator_id = request.payload["creator_id"]
            await services.raw_record_service.append(
                RawRecord(
                    platform_code=self.platform_code,
                    record_type="creator",
                    source_uri=payload.get("request_uri", f"/people/{creator_id}"),
                    request_meta={"creator_id": creator_id, "job_id": job_id},
                    response_body=payload.get("raw_payload"),
                    metadata={"bridge": "zhihu_connector"},
                )
            )
            await services.event_service.append(
                CrawlJobEvent(
                    job_id=job_id,
                    event_type="creator_succeeded",
                    message="Zhihu bridge creator succeeded",
                    details={"creator_id": creator_id},
                ),
                platform_code=self.platform_code,
            )
            return payload
        if task.task_type == "creator_contents":
            creator_id = request.payload["creator_id"]
            cursor = request.payload.get("cursor", "")
            items = [ZhihuContent.model_validate(item) for item in payload.get("items", [])]
            normalized_records = normalize_zhihu_contents(items)
            await services.normalized_content_service.append_many(normalized_records)
            await services.raw_record_service.append(
                RawRecord(
                    platform_code=self.platform_code,
                    record_type="creator_contents",
                    source_uri=payload.get("request_uri", ""),
                    request_meta={"creator_id": creator_id, "job_id": job_id, "cursor": cursor},
                    response_body=payload.get("raw_payload"),
                    metadata={"bridge": "zhihu_connector", "normalized_count": len(normalized_records)},
                )
            )
            await services.event_service.append(
                CrawlJobEvent(
                    job_id=job_id,
                    event_type="creator_contents_succeeded",
                    message="Zhihu bridge creator contents succeeded",
                    details={"creator_id": creator_id, "items_count": len(items)},
                ),
                platform_code=self.platform_code,
            )
            return {
                "items": [item.model_dump() for item in items],
                "normalized_records": normalized_records,
                "has_more": payload.get("has_more", False),
                "next_cursor": payload.get("next_cursor", ""),
            }
        raise ValueError(f"Unsupported Zhihu task type: {task.task_type}")

    @staticmethod
    def _parse_creator_url(creator_url: str) -> str:
        if not creator_url:
            raise ValueError("Zhihu creator task requires creator_url")
        return creator_url.rstrip("/").split("/")[-1]

    @staticmethod
    def _parse_note_url(note_url: str) -> tuple[str, str, str]:
        if zhihu_constant.ANSWER_NAME in note_url:
            return note_url.split("/")[-1], zhihu_constant.ANSWER_NAME, note_url.split("/")[-3]
        if zhihu_constant.ARTICLE_NAME in note_url:
            return note_url.split("/")[-1], zhihu_constant.ARTICLE_NAME, ""
        if zhihu_constant.VIDEO_NAME in note_url:
            return note_url.split("/")[-1], zhihu_constant.VIDEO_NAME, ""
        raise ValueError(f"Unsupported Zhihu note url: {note_url}")

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
