from __future__ import annotations

from types import MethodType
from typing import Any

from connectors.tieba.connector import TiebaConnector
from connectors.tieba.errors import TiebaDataFetchError
from model.m_baidu_tieba import TiebaNote
from runtime.browser.executor import BrowserExecutor
from runtime.session.service import SessionService

from schemas.tasks.models import CrawlJobEvent, CrawlTask
from schemas.tasks.runtime import PlatformTaskRequest


def _use_generic_success_handling(self: TiebaConnector) -> bool:
    return True


def _build_request(self: TiebaConnector, task: CrawlTask, job_id: str) -> PlatformTaskRequest:
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


def _plan_requirement(self: TiebaConnector, requirement: Any) -> list[CrawlTask]:
    if requirement.mode == "search":
        tasks: list[CrawlTask] = []
        keywords = [keyword.strip() for keyword in requirement.keywords if keyword.strip()]
        if not keywords:
            raise ValueError("Tieba search requirement requires at least one keyword")
        for keyword in keywords:
            for page in range(requirement.start_page, requirement.start_page + requirement.max_pages):
                tasks.append(self.new_task(task_type="search", params={"keyword": keyword, "page": page, "page_size": requirement.page_size}))
        return tasks
    if requirement.mode == "detail":
        note_ids = [note_id.strip() for note_id in requirement.note_ids if note_id.strip()]
        if not note_ids:
            raise ValueError("Tieba detail requirement requires at least one note id")
        return [self.new_task(task_type="detail", params={"note_id": note_id}) for note_id in note_ids]
    if requirement.mode == "creator":
        tasks: list[CrawlTask] = []
        creator_urls = [creator_url.strip() for creator_url in requirement.creator_urls if creator_url.strip()]
        if not creator_urls:
            raise ValueError("Tieba creator requirement requires at least one creator url")
        for creator_url in creator_urls:
            tasks.append(self.new_task(task_type="creator", params={"creator_url": creator_url}))
            for page in range(requirement.creator_max_pages):
                cursor = "" if page == 0 else str(page + 1)
                tasks.append(self.new_task(task_type="creator_contents", params={"creator_url": creator_url, "cursor": cursor, "limit": requirement.creator_contents_limit}))
        return tasks
    raise ValueError(f"Unsupported Tieba requirement mode: {requirement.mode}")


def _classify_error(self: TiebaConnector, message: str) -> str:
    lowered = message.lower()
    if "browser page" in lowered:
        return "session_not_ready"
    if "parse" in lowered:
        return "parse_failed"
    if "navigation" in lowered:
        return "navigation_failed"
    return "unknown_error"


def _build_failure_event(
    self: TiebaConnector,
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
        details["note_id"] = params.get("note_id") or (params.get("note") or {}).get("note_id")
    else:
        details.update({"creator_url": params.get("creator_url"), "cursor": params.get("cursor", "")})
    return CrawlJobEvent(job_id=job_id, event_type=f"{task.task_type}_failed", message=error_message, details=details)


def _collect_targets_from_results(self: TiebaConnector, results: list[dict[str, Any]]) -> list[TiebaNote]:
    targets: list[TiebaNote] = []
    for result in results:
        note = result.get("note")
        if isinstance(note, TiebaNote):
            targets.append(note)
        elif isinstance(note, dict):
            targets.append(TiebaNote.model_validate(note))
        for item in result.get("items", []):
            if isinstance(item, dict):
                targets.append(TiebaNote.model_validate(item))
    return targets


def _collect_targets_from_requirement(self: TiebaConnector, requirement: Any) -> list[TiebaNote]:
    targets: list[TiebaNote] = []
    for note_id in requirement.note_ids:
        if not note_id.strip():
            continue
        targets.append(TiebaNote(note_id=note_id.strip(), title="", desc="", note_url=f"https://tieba.baidu.com/p/{note_id.strip()}", tieba_name="", tieba_link=""))
    return targets


def _build_detail_task(self: TiebaConnector, target: TiebaNote, index: int) -> CrawlTask:
    return CrawlTask(task_id=f"tb-followup-detail-{index}", platform_code=self.platform_code, task_type="detail", status="planned", params={"note_id": target.note_id, "detail_url": target.note_url})


def _build_comments_task(self: TiebaConnector, target: TiebaNote, index: int, comment_limit: int | None) -> CrawlTask:
    return CrawlTask(task_id=f"tb-followup-comments-{index}", platform_code=self.platform_code, task_type="comments", status="planned", params={"note_id": target.note_id, "note": target.model_dump(), "limit": comment_limit})


def _dedupe_targets(self: TiebaConnector, targets: list[TiebaNote]) -> list[TiebaNote]:
    unique: list[TiebaNote] = []
    seen: set[str] = set()
    for target in targets:
        if target.note_id in seen:
            continue
        seen.add(target.note_id)
        unique.append(target)
    return unique


def _attach_platform_methods(connector: TiebaConnector) -> TiebaConnector:
    connector.short_code = "tb"
    connector.source_name = "legacy_tieba_crawler"
    connector.handled_exceptions = (TiebaDataFetchError,)
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


def build_tieba_connector_from_legacy(crawler) -> TiebaConnector:
    browser_executor = BrowserExecutor()
    browser_executor.bind(
        context=getattr(crawler, "browser_context", None),
        page=getattr(crawler, "context_page", None),
        browser_type="chromium",
        cdp_enabled=bool(getattr(crawler, "cdp_manager", None)),
        headless=False,
    )
    session_service = SessionService(platform_code="tieba")
    connector = TiebaConnector(
        browser_executor=browser_executor,
        session_service=session_service,
    )
    return _attach_platform_methods(connector)
