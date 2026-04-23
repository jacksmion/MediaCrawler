from __future__ import annotations

from types import MethodType
from typing import Any

from connectors.weibo.connector import WeiboConnector
from connectors.weibo.errors import WeiboDataFetchError
from runtime.browser.executor import BrowserExecutor
from runtime.http.executor import HttpExecutor
from runtime.session.service import SessionService

from schemas.tasks.models import CrawlJobEvent, CrawlTask
from schemas.tasks.runtime import PlatformTaskRequest


def _use_generic_success_handling(self: WeiboConnector) -> bool:
    return True


def _build_request(self: WeiboConnector, task: CrawlTask, job_id: str) -> PlatformTaskRequest:
    params = task.params or {}
    task_type = task.task_type
    if task_type == "search":
        return PlatformTaskRequest(job_id=job_id, platform_code=self.platform_code, task_kind="search", payload={"keyword": str(params["keyword"]), "page": int(params.get("page", 1)), "filters": {"search_type": str(params.get("search_type", "default"))}})
    if task_type == "detail":
        note_id = str(params.get("note_id") or params.get("content_id") or "")
        if not note_id:
            raise ValueError("Weibo detail task requires note_id")
        return PlatformTaskRequest(job_id=job_id, platform_code=self.platform_code, task_kind="detail", payload={"content_id": note_id})
    if task_type == "comments":
        note_id = str(params.get("note_id") or params.get("content_id") or "")
        if not note_id:
            raise ValueError("Weibo comments task requires note_id")
        return PlatformTaskRequest(job_id=job_id, platform_code=self.platform_code, task_kind="comments", payload={"content_id": note_id, "cursor": params.get("cursor", -1), "limit": _optional_int(params.get("limit")) or 10})
    if task_type == "creator":
        creator_id = str(params.get("creator_id") or "")
        if not creator_id:
            raise ValueError("Weibo creator task requires creator_id")
        return PlatformTaskRequest(job_id=job_id, platform_code=self.platform_code, task_kind="creator", payload={"creator_id": creator_id})
    if task_type == "creator_contents":
        creator_id = str(params.get("creator_id") or "")
        if not creator_id:
            raise ValueError("Weibo creator_contents task requires creator_id")
        return PlatformTaskRequest(job_id=job_id, platform_code=self.platform_code, task_kind="creator_contents", payload={"creator_id": creator_id, "cursor": _optional_str(params.get("cursor")) or "", "limit": int(params.get("limit", 10))})
    raise ValueError(f"Unsupported Weibo task type: {task_type}")


def _plan_requirement(self: WeiboConnector, requirement: Any) -> list[CrawlTask]:
    if requirement.mode == "search":
        tasks: list[CrawlTask] = []
        keywords = [keyword.strip() for keyword in requirement.keywords if keyword.strip()]
        if not keywords:
            raise ValueError("Weibo search requirement requires at least one keyword")
        search_type = requirement.search_type or "default"
        for keyword in keywords:
            for page in range(requirement.start_page, requirement.start_page + requirement.max_pages):
                tasks.append(self.new_task(task_type="search", params={"keyword": keyword, "page": page, "search_type": search_type}))
        return tasks
    if requirement.mode == "detail":
        note_ids = [note_id.strip() for note_id in requirement.note_ids if note_id.strip()]
        if not note_ids:
            raise ValueError("Weibo detail requirement requires at least one note id")
        return [self.new_task(task_type="detail", params={"note_id": note_id}) for note_id in note_ids]
    if requirement.mode == "creator":
        tasks: list[CrawlTask] = []
        creator_ids = [creator_id.strip() for creator_id in requirement.creator_ids if creator_id.strip()]
        if not creator_ids:
            raise ValueError("Weibo creator requirement requires at least one creator id")
        for creator_id in creator_ids:
            tasks.append(self.new_task(task_type="creator", params={"creator_id": creator_id}))
            for _ in range(requirement.creator_max_pages):
                tasks.append(self.new_task(task_type="creator_contents", params={"creator_id": creator_id, "cursor": "", "limit": requirement.creator_contents_limit}))
        return tasks
    raise ValueError(f"Unsupported Weibo requirement mode: {requirement.mode}")


def _classify_error(self: WeiboConnector, message: str) -> str:
    lowered = message.lower()
    if "cookie" in lowered or "auth" in lowered:
        return "session_not_ready"
    if "parse" in lowered:
        return "parse_failed"
    if "status 4" in lowered or "status 5" in lowered:
        return "http_error"
    return "unknown_error"


def _build_failure_event(
    self: WeiboConnector,
    *,
    task: CrawlTask,
    job_id: str,
    error_message: str,
    error_code: str,
) -> CrawlJobEvent:
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


def _collect_targets_from_results(self: WeiboConnector, results: list[dict[str, Any]]) -> list[str]:
    note_ids: list[str] = []
    for result in results:
        note = result.get("note")
        if isinstance(note, dict):
            mblog = note.get("mblog")
            if isinstance(mblog, dict) and mblog.get("id"):
                note_ids.append(str(mblog["id"]))
        for item in result.get("items", []):
            if isinstance(item, dict):
                mblog = item.get("mblog")
                if isinstance(mblog, dict) and mblog.get("id"):
                    note_ids.append(str(mblog["id"]))
    return note_ids


def _collect_targets_from_requirement(self: WeiboConnector, requirement: Any) -> list[str]:
    return [note_id.strip() for note_id in requirement.note_ids if note_id.strip()]


def _build_detail_task(self: WeiboConnector, target: str, index: int) -> CrawlTask:
    return CrawlTask(task_id=f"wb-followup-detail-{index}", platform_code=self.platform_code, task_type="detail", status="planned", params={"note_id": target})


def _build_comments_task(self: WeiboConnector, target: str, index: int, comment_limit: int | None) -> CrawlTask:
    return CrawlTask(task_id=f"wb-followup-comments-{index}", platform_code=self.platform_code, task_type="comments", status="planned", params={"note_id": target, "cursor": -1, "limit": comment_limit})


def _dedupe_targets(self: WeiboConnector, targets: list[str]) -> list[str]:
    return list(dict.fromkeys([target for target in targets if target]))


def _optional_int(value: Any) -> int | None:
    if value in (None, ""):
        return None
    return int(value)


def _optional_str(value: Any) -> str | None:
    if value in (None, ""):
        return None
    return str(value)


def _attach_platform_methods(connector: WeiboConnector) -> WeiboConnector:
    connector.short_code = "wb"
    connector.source_name = "legacy_weibo_crawler"
    connector.handled_exceptions = (WeiboDataFetchError,)
    connector.use_generic_success_handling = MethodType(_use_generic_success_handling, connector)
    connector.build_request = MethodType(_build_request, connector)
    connector.plan_requirement = MethodType(_plan_requirement, connector)
    connector.classify_error = MethodType(_classify_error, connector)
    connector.build_failure_event = MethodType(_build_failure_event, connector)
    connector.collect_targets_from_results = MethodType(_collect_targets_from_results, connector)
    connector.collect_targets_from_requirement = MethodType(_collect_targets_from_requirement, connector)
    connector.build_detail_task = MethodType(_build_detail_task, connector)
    connector.build_comments_task = MethodType(_build_comments_task, connector)
    connector.dedupe_targets = MethodType(_dedupe_targets, connector)
    return connector


def build_weibo_connector_from_legacy(crawler) -> WeiboConnector:
    browser_executor = BrowserExecutor()
    browser_executor.bind(
        context=getattr(crawler, "browser_context", None),
        page=getattr(crawler, "context_page", None),
        browser_type="chromium",
        cdp_enabled=bool(getattr(crawler, "cdp_manager", None)),
        headless=False,
    )
    http_executor = HttpExecutor(proxy=getattr(crawler, "_platform_http_proxy", None))
    session_service = SessionService(platform_code="weibo")
    connector = WeiboConnector(
        browser_executor=browser_executor,
        http_executor=http_executor,
        session_service=session_service,
    )
    return _attach_platform_methods(connector)
