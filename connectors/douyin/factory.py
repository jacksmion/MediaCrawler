from __future__ import annotations

from types import MethodType
from typing import Any

from connectors.douyin.connector import DouyinConnector
from connectors.douyin.errors import DouyinDataFetchError, classify_douyin_error
from connectors.douyin.helpers import build_douyin_failure_details, build_douyin_task_request
from runtime.browser.executor import BrowserExecutor
from runtime.http.executor import HttpExecutor
from runtime.hybrid.executor import HybridExecutor
from runtime.session.service import SessionService
from runtime.signing.douyin_signer import DouyinSigner

from schemas.tasks.models import CrawlJobEvent, CrawlTask
from schemas.tasks.runtime import PlatformTaskRequest


def _build_request(self: DouyinConnector, task: CrawlTask, job_id: str) -> PlatformTaskRequest:
    return build_douyin_task_request(
        job_id=job_id,
        platform_code=self.platform_code,
        task_type=task.task_type,
        params=task.params or {},
    )


def _plan_requirement(self: DouyinConnector, requirement: Any) -> list[CrawlTask]:
    if requirement.mode == "search":
        tasks: list[CrawlTask] = []
        keywords = [keyword.strip() for keyword in requirement.keywords if keyword.strip()]
        if not keywords:
            raise ValueError("Douyin search requirement requires at least one keyword")
        for keyword in keywords:
            for page in range(requirement.start_page, requirement.start_page + requirement.max_pages):
                tasks.append(
                    self.new_task(
                        task_type="search",
                        params={
                            "keyword": keyword,
                            "page": page,
                            "search_id": "",
                            "page_size": requirement.page_size,
                            "publish_time": requirement.publish_time,
                            "sort_type": requirement.sort_type,
                        },
                    )
                )
        return tasks
    if requirement.mode == "detail":
        aweme_ids = [aweme_id.strip() for aweme_id in requirement.aweme_ids if aweme_id.strip()]
        if not aweme_ids:
            raise ValueError("Douyin detail requirement requires at least one aweme_id")
        return [self.new_task(task_type="detail", params={"aweme_id": aweme_id}) for aweme_id in aweme_ids]
    if requirement.mode == "creator":
        tasks: list[CrawlTask] = []
        creator_ids = [creator_id.strip() for creator_id in requirement.creator_ids if creator_id.strip()]
        if not creator_ids:
            raise ValueError("Douyin creator requirement requires at least one creator_id")
        for creator_id in creator_ids:
            tasks.append(self.new_task(task_type="creator", params={"creator_id": creator_id}))
            for _ in range(requirement.creator_max_pages):
                tasks.append(
                    self.new_task(
                        task_type="creator_contents",
                        params={"creator_id": creator_id, "cursor": "", "limit": requirement.creator_contents_limit},
                    )
                )
        return tasks
    raise ValueError(f"Unsupported Douyin requirement mode: {requirement.mode}")


def _use_generic_success_handling(self: DouyinConnector) -> bool:
    return True


def _build_started_event(self: DouyinConnector, task: CrawlTask, job_id: str) -> CrawlJobEvent | None:
    if task.task_type != "search":
        return None
    params = task.params or {}
    return CrawlJobEvent(
        job_id=job_id,
        event_type="bridge_search_started",
        message="Douyin search bridge started",
        details={"keyword": params.get("keyword"), "page": params.get("page")},
    )


def _build_finished_event(self: DouyinConnector, task: CrawlTask, job_id: str) -> CrawlJobEvent | None:
    if task.task_type != "search":
        return None
    return CrawlJobEvent(
        job_id=job_id,
        event_type="bridge_search_finished",
        message="Douyin search bridge finished",
        details={},
    )


def _classify_error(self: DouyinConnector, message: str) -> str:
    return classify_douyin_error(message)


def _build_failure_event(
    self: DouyinConnector,
    *,
    task: CrawlTask,
    job_id: str,
    error_message: str,
    error_code: str,
) -> CrawlJobEvent:
    details = build_douyin_failure_details(
        task_type=task.task_type,
        params=task.params or {},
        error_code=error_code,
    )
    return CrawlJobEvent(job_id=job_id, event_type=f"{task.task_type}_failed", message=error_message, details=details)


def _collect_targets_from_results(self: DouyinConnector, results: list[dict[str, Any]]) -> list[str]:
    aweme_ids: list[str] = []
    for result in results:
        if "aweme_detail" in result and isinstance(result["aweme_detail"], dict):
            aweme_id = result["aweme_detail"].get("aweme_id")
            if aweme_id:
                aweme_ids.append(str(aweme_id))
        for item in result.get("items", []):
            if isinstance(item, dict):
                aweme_id = item.get("aweme_id")
                if not aweme_id:
                    aweme_info = item.get("aweme_info")
                    if isinstance(aweme_info, dict):
                        aweme_id = aweme_info.get("aweme_id")
                if aweme_id:
                    aweme_ids.append(str(aweme_id))
    return aweme_ids


def _collect_targets_from_requirement(self: DouyinConnector, requirement: Any) -> list[str]:
    return [aweme_id.strip() for aweme_id in requirement.aweme_ids if aweme_id.strip()]


def _build_detail_task(self: DouyinConnector, target: str, index: int) -> CrawlTask:
    return CrawlTask(
        task_id=f"dy-followup-detail-{index}",
        platform_code=self.platform_code,
        task_type="detail",
        status="planned",
        params={"aweme_id": target},
    )


def _build_comments_task(
    self: DouyinConnector,
    target: str,
    index: int,
    comment_limit: int | None,
) -> CrawlTask:
    return CrawlTask(
        task_id=f"dy-followup-comments-{index}",
        platform_code=self.platform_code,
        task_type="comments",
        status="planned",
        params={"aweme_id": target, "cursor": 0, "limit": comment_limit},
    )


def _dedupe_targets(self: DouyinConnector, targets: list[str]) -> list[str]:
    return list(dict.fromkeys([target for target in targets if target]))


def _attach_platform_methods(connector: DouyinConnector) -> DouyinConnector:
    connector.short_code = "dy"
    connector.source_name = "legacy_douyin_crawler"
    connector.handled_exceptions = (DouyinDataFetchError,)
    connector.build_request = MethodType(_build_request, connector)
    connector.plan_requirement = MethodType(_plan_requirement, connector)
    connector.use_generic_success_handling = MethodType(_use_generic_success_handling, connector)
    connector.build_started_event = MethodType(_build_started_event, connector)
    connector.build_finished_event = MethodType(_build_finished_event, connector)
    connector.classify_error = MethodType(_classify_error, connector)
    connector.build_failure_event = MethodType(_build_failure_event, connector)
    connector.collect_targets_from_results = MethodType(_collect_targets_from_results, connector)
    connector.collect_targets_from_requirement = MethodType(_collect_targets_from_requirement, connector)
    connector.build_detail_task = MethodType(_build_detail_task, connector)
    connector.build_comments_task = MethodType(_build_comments_task, connector)
    connector.dedupe_targets = MethodType(_dedupe_targets, connector)
    return connector


def build_douyin_connector_from_legacy(crawler) -> DouyinConnector:
    browser_executor = BrowserExecutor()
    browser_executor.bind(
        context=getattr(crawler, "browser_context", None),
        page=getattr(crawler, "context_page", None),
        browser_type="chromium",
        cdp_enabled=bool(getattr(crawler, "cdp_manager", None)),
        headless=False,
    )
    http_executor = HttpExecutor(proxy=getattr(crawler, "_platform_http_proxy", None))
    hybrid_executor = HybridExecutor(browser_executor, http_executor)
    session_service = SessionService(platform_code="douyin")
    signer = DouyinSigner(session_service)
    connector = DouyinConnector(
        hybrid_executor=hybrid_executor,
        session_service=session_service,
        signer=signer,
    )
    return _attach_platform_methods(connector)
