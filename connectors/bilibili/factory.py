from __future__ import annotations

from types import MethodType
from typing import Any

from connectors.bilibili.connector import BilibiliConnector
from connectors.bilibili.errors import BilibiliDataFetchError
from connectors.bilibili.helpers import parse_video_info_from_url
from runtime.browser.executor import BrowserExecutor
from runtime.http.executor import HttpExecutor
from runtime.session.service import SessionService

from schemas.tasks.models import CrawlJobEvent, CrawlTask
from schemas.tasks.runtime import PlatformTaskRequest


def _build_request(self: BilibiliConnector, task: CrawlTask, job_id: str) -> PlatformTaskRequest:
    params = task.params or {}
    if task.task_type == "search":
        return PlatformTaskRequest(job_id=job_id, platform_code=self.platform_code, task_kind="search", payload={"keyword": str(params["keyword"]), "page": int(params.get("page", 1)), "page_size": int(params.get("page_size", 20))})
    if task.task_type == "detail":
        content_id = str(params.get("content_id") or "")
        bvid = str(params.get("bvid") or "")
        return PlatformTaskRequest(job_id=job_id, platform_code=self.platform_code, task_kind="detail", payload={"content_id": content_id, "extra": {"bvid": bvid}})
    if task.task_type == "comments":
        return PlatformTaskRequest(job_id=job_id, platform_code=self.platform_code, task_kind="comments", payload={"content_id": str(params.get("content_id") or ""), "cursor": params.get("cursor", 0), "limit": int(params.get("limit", 10))})
    if task.task_type == "creator":
        return PlatformTaskRequest(job_id=job_id, platform_code=self.platform_code, task_kind="creator", payload={"creator_id": str(params.get("creator_id") or "")})
    if task.task_type == "creator_contents":
        return PlatformTaskRequest(job_id=job_id, platform_code=self.platform_code, task_kind="creator_contents", payload={"creator_id": str(params.get("creator_id") or ""), "cursor": str(params.get("cursor", "")), "limit": int(params.get("limit", 30))})
    raise ValueError(f"Unsupported Bilibili task type: {task.task_type}")


def _plan_requirement(self: BilibiliConnector, requirement: Any) -> list[CrawlTask]:
    if requirement.mode == "search":
        tasks: list[CrawlTask] = []
        keywords = [keyword.strip() for keyword in requirement.keywords if keyword.strip()]
        if not keywords:
            raise ValueError("Bilibili search requirement requires at least one keyword")
        for keyword in keywords:
            for page in range(requirement.start_page, requirement.start_page + requirement.max_pages):
                tasks.append(self.new_task(task_type="search", params={"keyword": keyword, "page": page, "page_size": requirement.page_size}))
        return tasks
    if requirement.mode == "detail":
        video_ids = [video_id.strip() for video_id in requirement.video_ids if video_id.strip()]
        if not video_ids:
            raise ValueError("Bilibili detail requirement requires at least one video id")
        return [self.new_task(task_type="detail", params={"video_id": video_id}) for video_id in video_ids]
    if requirement.mode == "creator":
        tasks: list[CrawlTask] = []
        creator_ids = [creator_id.strip() for creator_id in requirement.creator_ids if creator_id.strip()]
        if not creator_ids:
            raise ValueError("Bilibili creator requirement requires at least one creator id")
        for creator_id in creator_ids:
            tasks.append(self.new_task(task_type="creator", params={"creator_id": creator_id}))
            for page in range(1, requirement.creator_max_pages + 1):
                tasks.append(self.new_task(task_type="creator_contents", params={"creator_id": creator_id, "cursor": str(page), "limit": requirement.creator_contents_limit}))
        return tasks
    raise ValueError(f"Unsupported Bilibili requirement mode: {requirement.mode}")


def _use_generic_success_handling(self: BilibiliConnector) -> bool:
    return True


def _classify_error(self: BilibiliConnector, message: str) -> str:
    lowered = message.lower()
    if "sessdata" in lowered or "browser" in lowered:
        return "session_not_ready"
    if "status 4" in lowered or "status 5" in lowered:
        return "http_error"
    if "missing" in lowered:
        return "invalid_payload"
    return "unknown_error"


def _build_failure_event(
    self: BilibiliConnector,
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
        details.update({"content_id": params.get("content_id"), "bvid": params.get("bvid", "")})
    else:
        details.update({"creator_id": params.get("creator_id"), "cursor": params.get("cursor", "")})
    return CrawlJobEvent(job_id=job_id, event_type=f"{task.task_type}_failed", message=error_message, details=details)


def _collect_targets_from_results(self: BilibiliConnector, results: list[dict[str, Any]]) -> list[dict[str, str]]:
    targets: list[dict[str, str]] = []
    for result in results:
        video = result.get("video")
        if isinstance(video, dict):
            view = video.get("View", {})
            content_id = str(view.get("aid") or video.get("aid") or "")
            bvid = str(view.get("bvid") or video.get("bvid") or "")
            if content_id or bvid:
                targets.append({"content_id": content_id, "bvid": bvid})
        for item in result.get("items", []):
            if isinstance(item, dict):
                view = item.get("View", {})
                content_id = str(view.get("aid") or item.get("aid") or "")
                bvid = str(view.get("bvid") or item.get("bvid") or "")
                if content_id or bvid:
                    targets.append({"content_id": content_id, "bvid": bvid})
    return targets


def _collect_targets_from_requirement(self: BilibiliConnector, requirement: Any) -> list[dict[str, str]]:
    targets: list[dict[str, str]] = []
    for video_id in requirement.video_ids:
        if not video_id.strip():
            continue
        video_info = parse_video_info_from_url(video_id)
        targets.append({"content_id": "", "bvid": video_info.video_id})
    return targets


def _build_detail_task(self: BilibiliConnector, target: dict[str, str], index: int) -> CrawlTask:
    return CrawlTask(task_id=f"bili-followup-detail-{index}", platform_code=self.platform_code, task_type="detail", status="planned", params={"content_id": target["content_id"], "bvid": target["bvid"]})


def _build_comments_task(self: BilibiliConnector, target: dict[str, str], index: int, comment_limit: int | None) -> CrawlTask:
    return CrawlTask(task_id=f"bili-followup-comments-{index}", platform_code=self.platform_code, task_type="comments", status="planned", params={"content_id": target["content_id"], "bvid": target["bvid"], "limit": comment_limit})


def _dedupe_targets(self: BilibiliConnector, targets: list[dict[str, str]]) -> list[dict[str, str]]:
    unique: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for target in targets:
        key = (target["content_id"], target["bvid"])
        if key in seen:
            continue
        seen.add(key)
        unique.append(target)
    return unique


def _attach_platform_methods(connector: BilibiliConnector) -> BilibiliConnector:
    connector.short_code = "bili"
    connector.source_name = "legacy_bilibili_crawler"
    connector.handled_exceptions = (BilibiliDataFetchError,)
    connector.build_request = MethodType(_build_request, connector)
    connector.plan_requirement = MethodType(_plan_requirement, connector)
    connector.use_generic_success_handling = MethodType(_use_generic_success_handling, connector)
    connector.classify_error = MethodType(_classify_error, connector)
    connector.build_failure_event = MethodType(_build_failure_event, connector)
    connector.collect_targets_from_results = MethodType(_collect_targets_from_results, connector)
    connector.collect_targets_from_requirement = MethodType(_collect_targets_from_requirement, connector)
    connector.build_detail_task = MethodType(_build_detail_task, connector)
    connector.build_comments_task = MethodType(_build_comments_task, connector)
    connector.dedupe_targets = MethodType(_dedupe_targets, connector)
    return connector


def build_bilibili_connector_from_legacy(crawler) -> BilibiliConnector:
    browser_executor = BrowserExecutor()
    browser_executor.bind(
        context=getattr(crawler, "browser_context", None),
        page=getattr(crawler, "context_page", None),
        browser_type="chromium",
        cdp_enabled=bool(getattr(crawler, "cdp_manager", None)),
        headless=False,
    )
    http_executor = HttpExecutor(proxy=getattr(crawler, "_platform_http_proxy", None))
    session_service = SessionService(platform_code="bilibili")
    connector = BilibiliConnector(
        browser_executor=browser_executor,
        http_executor=http_executor,
        session_service=session_service,
    )
    return _attach_platform_methods(connector)
