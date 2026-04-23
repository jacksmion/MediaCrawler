from __future__ import annotations

from types import MethodType
from typing import Any

from connectors.xhs.connector import XhsConnector
from connectors.xhs.errors import XhsDataFetchError
from connectors.xhs.helpers import get_search_id, parse_note_info_from_note_url
from runtime.browser.executor import BrowserExecutor
from runtime.session.service import SessionService

from schemas.tasks.models import CrawlJobEvent, CrawlTask
from schemas.tasks.runtime import PlatformTaskRequest


def _use_generic_success_handling(self: XhsConnector) -> bool:
    return True


def _build_request(self: XhsConnector, task: CrawlTask, job_id: str) -> PlatformTaskRequest:
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
        note_id, xsec_source, xsec_token = _resolve_detail_params(params)
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
            payload={"content_id": note_id, "limit": _optional_int(params.get("limit")) or 10, "extra": {"xsec_token": xsec_token}},
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
            payload={"creator_id": creator_url, "cursor": _optional_str(params.get("cursor")) or "", "limit": int(params.get("limit", 30))},
        )
    raise ValueError(f"Unsupported XHS task type: {task_type}")


def _plan_requirement(self: XhsConnector, requirement: Any) -> list[CrawlTask]:
    if requirement.mode == "search":
        tasks: list[CrawlTask] = []
        keywords = [keyword.strip() for keyword in requirement.keywords if keyword.strip()]
        if not keywords:
            raise ValueError("XHS search requirement requires at least one keyword")
        sort_type = requirement.sort_type or "general"
        for keyword in keywords:
            for page in range(requirement.start_page, requirement.start_page + requirement.max_pages):
                tasks.append(
                    self.new_task(
                        task_type="search",
                        params={"keyword": keyword, "page": page, "page_size": requirement.page_size, "sort_type": sort_type},
                    )
                )
        return tasks
    if requirement.mode == "detail":
        note_urls = [note_url.strip() for note_url in requirement.note_urls if note_url.strip()]
        if not note_urls:
            raise ValueError("XHS detail requirement requires at least one note url")
        return [self.new_task(task_type="detail", params={"note_url": note_url}) for note_url in note_urls]
    if requirement.mode == "creator":
        tasks: list[CrawlTask] = []
        creator_urls = [creator_url.strip() for creator_url in requirement.creator_urls if creator_url.strip()]
        if not creator_urls:
            raise ValueError("XHS creator requirement requires at least one creator url")
        for creator_url in creator_urls:
            tasks.append(self.new_task(task_type="creator", params={"creator_url": creator_url}))
            for _ in range(requirement.creator_max_pages):
                tasks.append(
                    self.new_task(
                        task_type="creator_contents",
                        params={"creator_url": creator_url, "cursor": "", "limit": requirement.creator_contents_limit},
                    )
                )
        return tasks
    raise ValueError(f"Unsupported XHS requirement mode: {requirement.mode}")


def _classify_error(self: XhsConnector, message: str) -> str:
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


def _build_failure_event(
    self: XhsConnector,
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
        details["note_id"] = params.get("note_id")
    elif task.task_type == "creator":
        details["creator_url"] = params.get("creator_url")
    elif task.task_type == "creator_contents":
        details.update({"creator_url": params.get("creator_url"), "cursor": params.get("cursor", "")})
    return CrawlJobEvent(job_id=job_id, event_type=f"{task.task_type}_failed", message=error_message, details=details)


def _collect_targets_from_results(self: XhsConnector, results: list[dict[str, Any]]) -> list[dict[str, str]]:
    note_refs: list[dict[str, str]] = []
    for result in results:
        note = result.get("note")
        if isinstance(note, dict):
            note_id = str(note.get("note_id") or note.get("id") or "")
            xsec_token = str(note.get("xsec_token") or "")
            xsec_source = str(note.get("xsec_source") or "pc_search")
            if note_id and xsec_token:
                note_refs.append({"note_id": note_id, "xsec_token": xsec_token, "xsec_source": xsec_source})
        for item in result.get("items", []):
            if isinstance(item, dict):
                note_id = str(item.get("note_id") or item.get("id") or "")
                xsec_token = str(item.get("xsec_token") or "")
                xsec_source = str(item.get("xsec_source") or "pc_search")
                if note_id and xsec_token:
                    note_refs.append({"note_id": note_id, "xsec_token": xsec_token, "xsec_source": xsec_source})
    return note_refs


def _collect_targets_from_requirement(self: XhsConnector, requirement: Any) -> list[dict[str, str]]:
    note_refs: list[dict[str, str]] = []
    for note_url in requirement.note_urls:
        if not note_url.strip():
            continue
        note_info = parse_note_info_from_note_url(note_url)
        note_refs.append(
            {
                "note_id": note_info.note_id,
                "xsec_token": note_info.xsec_token,
                "xsec_source": note_info.xsec_source,
            }
        )
    return note_refs


def _build_detail_task(self: XhsConnector, target: dict[str, str], index: int) -> CrawlTask:
    return CrawlTask(
        task_id=f"xhs-followup-detail-{index}",
        platform_code=self.platform_code,
        task_type="detail",
        status="planned",
        params={
            "note_url": (
                f"https://www.xiaohongshu.com/explore/{target['note_id']}?"
                f"xsec_token={target['xsec_token']}&xsec_source={target['xsec_source']}"
            ),
        },
    )


def _build_comments_task(
    self: XhsConnector,
    target: dict[str, str],
    index: int,
    comment_limit: int | None,
) -> CrawlTask:
    return CrawlTask(
        task_id=f"xhs-followup-comments-{index}",
        platform_code=self.platform_code,
        task_type="comments",
        status="planned",
        params={"note_id": target["note_id"], "xsec_token": target["xsec_token"], "limit": comment_limit},
    )


def _dedupe_targets(self: XhsConnector, targets: list[dict[str, str]]) -> list[dict[str, str]]:
    unique: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for target in targets:
        key = (target["note_id"], target["xsec_token"])
        if key in seen:
            continue
        seen.add(key)
        unique.append(target)
    return unique


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


def _optional_int(value: Any) -> int | None:
    if value in (None, ""):
        return None
    return int(value)


def _optional_str(value: Any) -> str | None:
    if value in (None, ""):
        return None
    return str(value)


def _attach_platform_methods(connector: XhsConnector) -> XhsConnector:
    connector.short_code = "xhs"
    connector.source_name = "legacy_xhs_crawler"
    connector.handled_exceptions = (XhsDataFetchError,)
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


def build_xhs_connector_from_legacy(crawler) -> XhsConnector:
    browser_executor = BrowserExecutor()
    browser_executor.bind(
        context=getattr(crawler, "browser_context", None),
        page=getattr(crawler, "context_page", None),
        browser_type="chromium",
        cdp_enabled=bool(getattr(crawler, "cdp_manager", None)),
        headless=False,
    )
    session_service = SessionService(platform_code="xhs")
    connector = XhsConnector(
        browser_executor=browser_executor,
        session_service=session_service,
        legacy_client=getattr(crawler, "xhs_client", None),
    )
    return _attach_platform_methods(connector)
