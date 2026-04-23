from __future__ import annotations

from types import MethodType
from typing import Any

from connectors.zhihu.connector import ZhihuConnector
from connectors.zhihu.errors import ZhihuDataFetchError
from constant import zhihu as zhihu_constant
from model.m_zhihu import ZhihuContent
from runtime.browser.executor import BrowserExecutor
from runtime.http.executor import HttpExecutor
from runtime.session.service import SessionService

from schemas.tasks.models import CrawlJobEvent, CrawlTask
from schemas.tasks.runtime import PlatformTaskRequest


def _use_generic_success_handling(self: ZhihuConnector) -> bool:
    return True


def _build_request(self: ZhihuConnector, task: CrawlTask, job_id: str) -> PlatformTaskRequest:
    params = task.params or {}
    task_type = task.task_type
    if task_type == "search":
        return PlatformTaskRequest(job_id=job_id, platform_code=self.platform_code, task_kind="search", payload={"keyword": str(params["keyword"]), "page": int(params.get("page", 1)), "page_size": int(params.get("page_size", 20))})
    if task_type == "detail":
        note_url = str(params.get("note_url") or "").split("?")[0]
        if not note_url:
            raise ValueError("Zhihu detail task requires note_url")
        content_id, content_type, question_id = _parse_note_url(note_url)
        return PlatformTaskRequest(job_id=job_id, platform_code=self.platform_code, task_kind="detail", payload={"content_id": content_id, "extra": {"content_type": content_type, "detail_url": note_url, "question_id": question_id}})
    if task_type == "comments":
        content_payload = params.get("content")
        if not isinstance(content_payload, dict):
            raise ValueError("Zhihu comments task requires content payload")
        content = ZhihuContent.model_validate(content_payload)
        return PlatformTaskRequest(job_id=job_id, platform_code=self.platform_code, task_kind="comments", payload={"content_id": content.content_id, "cursor": _optional_str(params.get("cursor")) or "", "limit": _optional_int(params.get("limit")) or 10, "extra": {"content_type": content.content_type, "content": content.model_dump()}})
    if task_type == "creator":
        creator_url = str(params.get("creator_url") or "")
        if not creator_url:
            raise ValueError("Zhihu creator task requires creator_url")
        return PlatformTaskRequest(job_id=job_id, platform_code=self.platform_code, task_kind="creator", payload={"creator_id": _parse_creator_url(creator_url)})
    if task_type == "creator_contents":
        creator_url = str(params.get("creator_url") or "")
        if not creator_url:
            raise ValueError("Zhihu creator_contents task requires creator_url")
        return PlatformTaskRequest(job_id=job_id, platform_code=self.platform_code, task_kind="creator_contents", payload={"creator_id": _parse_creator_url(creator_url), "cursor": _optional_str(params.get("cursor")) or "", "limit": int(params.get("limit", 20))})
    raise ValueError(f"Unsupported Zhihu task type: {task_type}")


def _plan_requirement(self: ZhihuConnector, requirement: Any) -> list[CrawlTask]:
    if requirement.mode == "search":
        tasks: list[CrawlTask] = []
        keywords = [keyword.strip() for keyword in requirement.keywords if keyword.strip()]
        if not keywords:
            raise ValueError("Zhihu search requirement requires at least one keyword")
        for keyword in keywords:
            for page in range(requirement.start_page, requirement.start_page + requirement.max_pages):
                tasks.append(self.new_task(task_type="search", params={"keyword": keyword, "page": page, "page_size": requirement.page_size}))
        return tasks
    if requirement.mode == "detail":
        note_urls = [note_url.strip() for note_url in requirement.note_urls if note_url.strip()]
        if not note_urls:
            raise ValueError("Zhihu detail requirement requires at least one note url")
        return [self.new_task(task_type="detail", params={"note_url": note_url}) for note_url in note_urls]
    if requirement.mode == "creator":
        tasks: list[CrawlTask] = []
        creator_urls = [creator_url.strip() for creator_url in requirement.creator_urls if creator_url.strip()]
        if not creator_urls:
            raise ValueError("Zhihu creator requirement requires at least one creator url")
        for creator_url in creator_urls:
            tasks.append(self.new_task(task_type="creator", params={"creator_url": creator_url}))
            for _ in range(requirement.creator_max_pages):
                tasks.append(self.new_task(task_type="creator_contents", params={"creator_url": creator_url, "cursor": "", "limit": requirement.creator_contents_limit}))
        return tasks
    raise ValueError(f"Unsupported Zhihu requirement mode: {requirement.mode}")


def _classify_error(self: ZhihuConnector, message: str) -> str:
    lowered = message.lower()
    if "d_c0" in lowered or "browser state" in lowered:
        return "session_not_ready"
    if "status 4" in lowered or "status 5" in lowered:
        return "http_error"
    if "parse" in lowered:
        return "parse_failed"
    return "unknown_error"


def _build_failure_event(
    self: ZhihuConnector,
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
    elif task.task_type == "detail":
        note_url = str(params.get("note_url") or "").split("?")[0]
        if note_url:
            content_id, content_type, _ = _parse_note_url(note_url)
            details.update({"content_id": content_id, "content_type": content_type})
    elif task.task_type == "comments":
        content = params.get("content") or {}
        if isinstance(content, dict):
            details.update({"content_id": content.get("content_id"), "content_type": content.get("content_type")})
    elif task.task_type == "creator":
        details["creator_id"] = _parse_creator_url(str(params.get("creator_url") or ""))
    elif task.task_type == "creator_contents":
        details.update({"creator_id": _parse_creator_url(str(params.get("creator_url") or "")), "cursor": params.get("cursor", "")})
    return CrawlJobEvent(job_id=job_id, event_type=f"{task.task_type}_failed", message=error_message, details=details)


def _collect_targets_from_results(self: ZhihuConnector, results: list[dict[str, Any]]) -> list[ZhihuContent]:
    contents: list[ZhihuContent] = []
    for result in results:
        content = result.get("content")
        if isinstance(content, ZhihuContent):
            contents.append(content)
        elif isinstance(content, dict):
            contents.append(ZhihuContent.model_validate(content))
        for item in result.get("items", []):
            if isinstance(item, dict):
                contents.append(ZhihuContent.model_validate(item))
    return contents


def _collect_targets_from_requirement(self: ZhihuConnector, requirement: Any) -> list[ZhihuContent]:
    return [_content_from_url(note_url) for note_url in requirement.note_urls if note_url.strip()]


def _build_detail_task(self: ZhihuConnector, target: ZhihuContent, index: int) -> CrawlTask:
    return CrawlTask(task_id=f"zh-followup-detail-{index}", platform_code=self.platform_code, task_type="detail", status="planned", params={"note_url": target.content_url})


def _build_comments_task(self: ZhihuConnector, target: ZhihuContent, index: int, comment_limit: int | None) -> CrawlTask:
    return CrawlTask(task_id=f"zh-followup-comments-{index}", platform_code=self.platform_code, task_type="comments", status="planned", params={"content": target.model_dump(), "cursor": "", "limit": comment_limit})


def _dedupe_targets(self: ZhihuConnector, targets: list[ZhihuContent]) -> list[ZhihuContent]:
    unique: list[ZhihuContent] = []
    seen: set[tuple[str, str]] = set()
    for target in targets:
        key = (target.content_type, target.content_id)
        if key in seen:
            continue
        seen.add(key)
        unique.append(target)
    return unique


def _parse_creator_url(creator_url: str) -> str:
    if not creator_url:
        raise ValueError("Zhihu creator task requires creator_url")
    return creator_url.rstrip("/").split("/")[-1]


def _parse_note_url(note_url: str) -> tuple[str, str, str]:
    if zhihu_constant.ANSWER_NAME in note_url:
        return note_url.split("/")[-1], zhihu_constant.ANSWER_NAME, note_url.split("/")[-3]
    if zhihu_constant.ARTICLE_NAME in note_url:
        return note_url.split("/")[-1], zhihu_constant.ARTICLE_NAME, ""
    if zhihu_constant.VIDEO_NAME in note_url:
        return note_url.split("/")[-1], zhihu_constant.VIDEO_NAME, ""
    raise ValueError(f"Unsupported Zhihu note url: {note_url}")


def _optional_int(value: Any) -> int | None:
    if value in (None, ""):
        return None
    return int(value)


def _optional_str(value: Any) -> str | None:
    if value in (None, ""):
        return None
    return str(value)


def _content_from_url(note_url: str) -> ZhihuContent:
    clean_url = note_url.split("?")[0]
    if zhihu_constant.ANSWER_NAME in clean_url:
        return ZhihuContent(content_id=clean_url.split("/")[-1], content_type=zhihu_constant.ANSWER_NAME, question_id=clean_url.split("/")[-3], content_url=clean_url)
    if zhihu_constant.ARTICLE_NAME in clean_url:
        return ZhihuContent(content_id=clean_url.split("/")[-1], content_type=zhihu_constant.ARTICLE_NAME, question_id="", content_url=clean_url)
    if zhihu_constant.VIDEO_NAME in clean_url:
        return ZhihuContent(content_id=clean_url.split("/")[-1], content_type=zhihu_constant.VIDEO_NAME, question_id="", content_url=clean_url)
    raise ValueError(f"Unsupported Zhihu note url: {note_url}")


def _attach_platform_methods(connector: ZhihuConnector) -> ZhihuConnector:
    connector.short_code = "zh"
    connector.source_name = "legacy_zhihu_crawler"
    connector.handled_exceptions = (ZhihuDataFetchError,)
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


def build_zhihu_connector_from_legacy(crawler) -> ZhihuConnector:
    browser_executor = BrowserExecutor()
    browser_executor.bind(
        context=getattr(crawler, "browser_context", None),
        page=getattr(crawler, "context_page", None),
        browser_type="chromium",
        cdp_enabled=bool(getattr(crawler, "cdp_manager", None)),
        headless=False,
    )
    http_executor = HttpExecutor(proxy=getattr(crawler, "_platform_http_proxy", None))
    session_service = SessionService(platform_code="zhihu")
    connector = ZhihuConnector(
        browser_executor=browser_executor,
        http_executor=http_executor,
        session_service=session_service,
    )
    return _attach_platform_methods(connector)
