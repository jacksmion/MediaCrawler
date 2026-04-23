from __future__ import annotations

from types import MethodType
from typing import Any

from connectors.kuaishou.connector import KuaishouConnector
from connectors.kuaishou.errors import KuaishouDataFetchError
from connectors.kuaishou.helpers import parse_video_info_from_url
from runtime.browser.executor import BrowserExecutor
from runtime.http.executor import HttpExecutor
from runtime.session.service import SessionService

from schemas.tasks.models import CrawlJobEvent, CrawlTask
from schemas.tasks.runtime import PlatformTaskRequest


def _use_generic_success_handling(self: KuaishouConnector) -> bool:
    return True


def _build_request(self: KuaishouConnector, task: CrawlTask, job_id: str) -> PlatformTaskRequest:
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


def _plan_requirement(self: KuaishouConnector, requirement: Any) -> list[CrawlTask]:
    if requirement.mode == "search":
        tasks: list[CrawlTask] = []
        keywords = [keyword.strip() for keyword in requirement.keywords if keyword.strip()]
        if not keywords:
            raise ValueError("Kuaishou search requirement requires at least one keyword")
        for keyword in keywords:
            for page in range(requirement.start_page, requirement.start_page + requirement.max_pages):
                tasks.append(self.new_task(task_type="search", params={"keyword": keyword, "page": page, "page_size": requirement.page_size, "search_session_id": ""}))
        return tasks
    if requirement.mode == "detail":
        video_ids = [video_id.strip() for video_id in requirement.video_ids if video_id.strip()]
        if not video_ids:
            raise ValueError("Kuaishou detail requirement requires at least one video id")
        return [self.new_task(task_type="detail", params={"video_id": video_id}) for video_id in video_ids]
    if requirement.mode == "creator":
        tasks: list[CrawlTask] = []
        creator_ids = [creator_id.strip() for creator_id in requirement.creator_ids if creator_id.strip()]
        if not creator_ids:
            raise ValueError("Kuaishou creator requirement requires at least one creator id")
        for creator_id in creator_ids:
            tasks.append(self.new_task(task_type="creator", params={"creator_id": creator_id}))
            tasks.append(self.new_task(task_type="creator_contents", params={"creator_id": creator_id, "cursor": "", "limit": requirement.creator_contents_limit}))
        return tasks
    raise ValueError(f"Unsupported Kuaishou requirement mode: {requirement.mode}")


def _classify_error(self: KuaishouConnector, message: str) -> str:
    lowered = message.lower()
    if "cookie" in lowered or "auth" in lowered:
        return "session_not_ready"
    if "graphql" in lowered or "rest" in lowered:
        return "request_failed"
    if "missing" in lowered:
        return "invalid_payload"
    return "unknown_error"


def _build_failure_event(
    self: KuaishouConnector,
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
        details["video_id"] = params.get("video_id")
    else:
        details.update({"creator_id": params.get("creator_id"), "cursor": params.get("cursor", "")})
    return CrawlJobEvent(job_id=job_id, event_type=f"{task.task_type}_failed", message=error_message, details=details)


def _collect_targets_from_results(self: KuaishouConnector, results: list[dict[str, Any]]) -> list[str]:
    targets: list[str] = []
    for result in results:
        video = result.get("video")
        if isinstance(video, dict):
            photo = video.get("photo", {})
            video_id = str(photo.get("id") or video.get("photoId") or "")
            if video_id:
                targets.append(video_id)
        for item in result.get("items", []):
            if isinstance(item, dict):
                photo = item.get("photo", {})
                video_id = str(photo.get("id") or item.get("photoId") or "")
                if video_id:
                    targets.append(video_id)
    return targets


def _collect_targets_from_requirement(self: KuaishouConnector, requirement: Any) -> list[str]:
    targets: list[str] = []
    for video_id in requirement.video_ids:
        if not video_id.strip():
            continue
        video_info = parse_video_info_from_url(video_id)
        targets.append(video_info.video_id)
    return targets


def _build_detail_task(self: KuaishouConnector, target: str, index: int) -> CrawlTask:
    return CrawlTask(task_id=f"ks-followup-detail-{index}", platform_code=self.platform_code, task_type="detail", status="planned", params={"video_id": target})


def _build_comments_task(self: KuaishouConnector, target: str, index: int, comment_limit: int | None) -> CrawlTask:
    return CrawlTask(task_id=f"ks-followup-comments-{index}", platform_code=self.platform_code, task_type="comments", status="planned", params={"video_id": target, "limit": comment_limit})


def _dedupe_targets(self: KuaishouConnector, targets: list[str]) -> list[str]:
    unique: list[str] = []
    seen: set[str] = set()
    for target in targets:
        if target in seen:
            continue
        seen.add(target)
        unique.append(target)
    return unique


def _attach_platform_methods(connector: KuaishouConnector) -> KuaishouConnector:
    connector.short_code = "ks"
    connector.source_name = "legacy_kuaishou_crawler"
    connector.handled_exceptions = (KuaishouDataFetchError,)
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


def build_kuaishou_connector_from_legacy(crawler) -> KuaishouConnector:
    browser_executor = BrowserExecutor()
    browser_executor.bind(
        context=getattr(crawler, "browser_context", None),
        page=getattr(crawler, "context_page", None),
        browser_type="chromium",
        cdp_enabled=bool(getattr(crawler, "cdp_manager", None)),
        headless=False,
    )
    http_executor = HttpExecutor(proxy=getattr(crawler, "_platform_http_proxy", None))
    session_service = SessionService(platform_code="kuaishou")
    connector = KuaishouConnector(
        browser_executor=browser_executor,
        http_executor=http_executor,
        session_service=session_service,
    )
    return _attach_platform_methods(connector)
