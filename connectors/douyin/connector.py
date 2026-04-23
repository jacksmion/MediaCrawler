from __future__ import annotations

import urllib.parse
from typing import Any

from connectors.base.base_connector import BaseConnector
from connectors.base.models import (
    AuthContext,
    AuthResult,
    CommentsPage,
    ConnectorCapability,
    ConnectorContext,
    ContentDetailResult,
    CreatorContentsPage,
    CreatorResult,
    HealthStatus,
    SearchPage,
    SearchQuery,
)
from schemas.tasks.models import CrawlJobEvent, CrawlTask
from schemas.tasks.runtime import PlatformTaskRequest

from .errors import DouyinDataFetchError, classify_douyin_error
from .helpers import build_douyin_failure_details, build_douyin_task_request
from .normalizer import normalize_aweme_detail, normalize_search_items
from runtime.browser.executor import BrowserExecutor
from runtime.http.executor import HttpExecutor
from runtime.hybrid.executor import HybridExecutor
from runtime.http.models import HttpRequest
from runtime.session.service import SessionService
from runtime.signing.douyin_signer import DouyinSigner


class DouyinConnector(BaseConnector):
    """New-style Douyin connector scaffold for incremental migration."""
    short_code = "dy"
    source_name = "legacy_douyin_crawler"
    handled_exceptions = (DouyinDataFetchError,)

    def __init__(
        self,
        hybrid_executor: HybridExecutor,
        session_service: SessionService,
        signer: DouyinSigner,
    ) -> None:
        super().__init__(
            platform_code="douyin",
            capabilities=ConnectorCapability(
                supports_search=True,
                supports_detail=True,
                supports_comments=True,
                supports_creator=True,
                requires_browser=True,
                requires_signing=True,
                supports_incremental=True,
                supports_resume=True,
            ),
        )
        self.hybrid_executor = hybrid_executor
        self.session_service = session_service
        self.signer = signer
        self.context: ConnectorContext | None = None

    async def prepare(self, context: ConnectorContext) -> None:
        self.context = context

    async def authenticate(self, auth_context: AuthContext) -> AuthResult:
        return AuthResult(
            success=False,
            login_type=auth_context.login_type,
            account_id=auth_context.account_id,
            message="Douyin connector authentication is not migrated yet.",
        )

    def build_request(self, task: CrawlTask, job_id: str) -> PlatformTaskRequest:
        return build_douyin_task_request(
            job_id=job_id,
            platform_code=self.platform_code,
            task_type=task.task_type,
            params=task.params or {},
        )

    def plan_requirement(self, requirement: Any) -> list[CrawlTask]:
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

    def use_generic_success_handling(self) -> bool:
        return True

    def build_started_event(self, task: CrawlTask, job_id: str) -> CrawlJobEvent | None:
        if task.task_type != "search":
            return None
        params = task.params or {}
        return CrawlJobEvent(
            job_id=job_id,
            event_type="bridge_search_started",
            message="Douyin search bridge started",
            details={"keyword": params.get("keyword"), "page": params.get("page")},
        )

    def build_finished_event(self, task: CrawlTask, job_id: str) -> CrawlJobEvent | None:
        if task.task_type != "search":
            return None
        return CrawlJobEvent(
            job_id=job_id,
            event_type="bridge_search_finished",
            message="Douyin search bridge finished",
            details={},
        )

    def classify_error(self, message: str) -> str:
        return classify_douyin_error(message)

    def build_failure_event(self, *, task: CrawlTask, job_id: str, error_message: str, error_code: str) -> CrawlJobEvent:
        details = build_douyin_failure_details(
            task_type=task.task_type,
            params=task.params or {},
            error_code=error_code,
        )
        return CrawlJobEvent(job_id=job_id, event_type=f"{task.task_type}_failed", message=error_message, details=details)

    def collect_targets_from_results(self, results: list[dict[str, Any]]) -> list[str]:
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

    def collect_targets_from_requirement(self, requirement: Any) -> list[str]:
        return [aweme_id.strip() for aweme_id in requirement.aweme_ids if aweme_id.strip()]

    def build_detail_task(self, target: str, index: int) -> CrawlTask:
        return CrawlTask(
            task_id=f"dy-followup-detail-{index}",
            platform_code=self.platform_code,
            task_type="detail",
            status="planned",
            params={"aweme_id": target},
        )

    def build_comments_task(self, target: str, index: int, comment_limit: int | None) -> CrawlTask:
        return CrawlTask(
            task_id=f"dy-followup-comments-{index}",
            platform_code=self.platform_code,
            task_type="comments",
            status="planned",
            params={"aweme_id": target, "cursor": 0, "limit": comment_limit},
        )

    def dedupe_targets(self, targets: list[str]) -> list[str]:
        return list(dict.fromkeys([target for target in targets if target]))

    async def health_check(self) -> HealthStatus:
        session = await self.session_service.refresh_from_browser(
            self.hybrid_executor.browser_executor,
            account_id=self.context.account_id if self.context else None,
            proxy=self.context.proxy if self.context else None,
        )
        return HealthStatus(
            ok=session.login_status,
            platform_code=self.platform_code,
            message="Session loaded" if session.login_status else "Session not authenticated",
            details={"session_id": session.session_id, "account_id": session.account_id},
        )

    async def search(self, query: SearchQuery) -> SearchPage:
        session = await self.session_service.refresh_from_browser(
            self.hybrid_executor.browser_executor,
            account_id=self.context.account_id if self.context else None,
            proxy=self.context.proxy if self.context else None,
        )
        if not session.user_agent:
            raise DouyinDataFetchError("Douyin session is missing user agent; browser state is not ready.")
        headers = {
            "User-Agent": session.user_agent or "",
            "Cookie": ";".join(f"{key}={value}" for key, value in session.cookie_dict.items()),
            "Host": "www.douyin.com",
            "Origin": "https://www.douyin.com/",
            "Referer": "https://www.douyin.com/",
            "Content-Type": "application/json;charset=UTF-8",
        }
        page_size = query.page_size or 15
        params = {
            "search_channel": query.filters.get("search_channel", "aweme_general"),
            "enable_history": "1",
            "keyword": query.keyword,
            "search_source": "tab_search",
            "query_correct_type": "1",
            "is_filter_search": "0",
            "from_group_id": query.filters.get("from_group_id", "7378810571505847586"),
            "offset": max(query.page - 1, 0) * page_size,
            "count": str(page_size),
            "need_filter_settings": "1",
            "list_type": "multi",
            "search_id": query.filters.get("search_id", query.cursor or ""),
        }
        if query.filters.get("sort_type") is not None or query.filters.get("publish_time") is not None:
            params["filter_selected"] = (
                '{"sort_type":"%s","publish_time":"%s"}'
                % (
                    query.filters.get("sort_type", "0"),
                    query.filters.get("publish_time", "0"),
                )
            )
            params["is_filter_search"] = 1
        referer_url = f"https://www.douyin.com/search/{query.keyword}?type=general"
        headers["Referer"] = urllib.parse.quote(referer_url, safe=":/?=&")
        signed_params = await self.signer.sign_request(
            "/aweme/v1/web/general/search/single/",
            params,
            headers,
            request_method="GET",
            page=self.hybrid_executor.browser_executor.page,
        )
        response = await self.hybrid_executor.send(
            HttpRequest(
                method="GET",
                url="https://www.douyin.com/aweme/v1/web/general/search/single/",
                params=signed_params,
                headers=headers,
            )
        )
        if response.status_code != 200:
            raise DouyinDataFetchError(f"Douyin search request failed with status {response.status_code}: {response.text}")
        payload = response.data if isinstance(response.data, dict) else {}
        if not payload:
            raise DouyinDataFetchError(f"Douyin search returned invalid payload: {response.text[:300]}")
        if payload.get("data") is None and payload.get("status_code") not in (0, None):
            raise DouyinDataFetchError(f"Douyin search returned error payload: {payload}")
        items = payload.get("data", []) if isinstance(payload, dict) else []
        extra = payload.get("extra", {}) if isinstance(payload, dict) else {}
        normalized_records = normalize_search_items(items)
        return SearchPage(
            items=items,
            has_more=bool(items),
            next_cursor=extra.get("logid"),
            raw=payload,
            metadata={
                "offset": signed_params.get("offset"),
                "search_id": signed_params.get("search_id"),
                "logid": extra.get("logid"),
                "request_uri": "/aweme/v1/web/general/search/single/",
                "outcome": {
                    "normalized_records": normalized_records,
                    "raw_record": {
                        "record_type": "search",
                        "source_uri": "/aweme/v1/web/general/search/single/",
                        "request_meta": {
                            "keyword": query.keyword,
                            "page": query.page,
                            "search_id": query.filters.get("search_id", query.cursor or ""),
                        },
                        "response_body": payload,
                        "metadata": {"bridge": "douyin_connector"},
                    },
                    "events": [
                        {
                            "event_type": "search_page_succeeded",
                            "message": "Douyin bridge search page succeeded",
                            "details": {
                                "keyword": query.keyword,
                                "page": query.page,
                                "items_count": len(items),
                                "normalized_count": len(normalized_records),
                                "next_cursor": extra.get("logid"),
                            },
                        }
                    ],
                    "response_payload": {
                        "items": items,
                        "normalized_records": normalized_records,
                        "next_cursor": extra.get("logid"),
                        "raw": payload,
                    },
                },
            },
        )

    async def fetch_content_detail(self, content_id: str, extra: dict[str, Any] | None = None) -> ContentDetailResult:
        session = await self.session_service.refresh_from_browser(
            self.hybrid_executor.browser_executor,
            account_id=self.context.account_id if self.context else None,
            proxy=self.context.proxy if self.context else None,
        )
        if not session.user_agent:
            raise DouyinDataFetchError("Douyin session is missing user agent; browser state is not ready.")
        headers = {
            "User-Agent": session.user_agent or "",
            "Cookie": ";".join(f"{key}={value}" for key, value in session.cookie_dict.items()),
            "Host": "www.douyin.com",
            "Referer": "https://www.douyin.com/",
            "Content-Type": "application/json;charset=UTF-8",
        }
        params = {"aweme_id": content_id}
        signed_params = await self.signer.sign_request(
            "/aweme/v1/web/aweme/detail/",
            params,
            headers,
            request_method="GET",
            page=self.hybrid_executor.browser_executor.page,
        )
        response = await self.hybrid_executor.send(
            HttpRequest(
                method="GET",
                url="https://www.douyin.com/aweme/v1/web/aweme/detail/",
                params=signed_params,
                headers=headers,
            )
        )
        if response.status_code != 200:
            raise DouyinDataFetchError(f"Douyin detail request failed with status {response.status_code}: {response.text}")
        payload = response.data if isinstance(response.data, dict) else {}
        if not payload:
            raise DouyinDataFetchError(f"Douyin detail returned invalid payload: {response.text[:300]}")
        detail = payload.get("aweme_detail", {})
        if not detail:
            raise DouyinDataFetchError(f"Douyin detail payload missing aweme_detail: {payload}")
        normalized_record = normalize_aweme_detail(detail)
        return ContentDetailResult(
            item=detail,
            item_key="aweme_detail",
            raw_payload=payload,
            request_uri="/aweme/v1/web/aweme/detail/",
            request_params=signed_params,
            metadata={
                "outcome": {
                    "normalized_records": [normalized_record] if normalized_record is not None else [],
                    "raw_record": {
                        "record_type": "detail",
                        "source_uri": "/aweme/v1/web/aweme/detail/",
                        "request_meta": {"aweme_id": content_id, "request_params": signed_params},
                        "response_body": payload,
                        "metadata": {"bridge": "douyin_connector"},
                    },
                    "events": [
                        {
                            "event_type": "detail_succeeded",
                            "message": "Douyin bridge detail succeeded",
                            "details": {"aweme_id": content_id},
                        }
                    ],
                    "response_payload": {"aweme_detail": detail, "normalized_record": normalized_record},
                }
            },
        )

    async def fetch_comments(
        self,
        content_id: str,
        cursor: str | int | None = None,
        limit: int | None = None,
        extra: dict[str, Any] | None = None,
    ) -> CommentsPage:
        session = await self.session_service.refresh_from_browser(
            self.hybrid_executor.browser_executor,
            account_id=self.context.account_id if self.context else None,
            proxy=self.context.proxy if self.context else None,
        )
        if not session.user_agent:
            raise DouyinDataFetchError("Douyin session is missing user agent; browser state is not ready.")
        headers = {
            "User-Agent": session.user_agent or "",
            "Cookie": ";".join(f"{key}={value}" for key, value in session.cookie_dict.items()),
            "Host": "www.douyin.com",
            "Referer": "https://www.douyin.com/",
            "Content-Type": "application/json;charset=UTF-8",
        }
        comments: list[dict[str, Any]] = []
        root_cursor = int(cursor or 0)
        has_more = 1
        max_count = limit or 20
        last_payload: dict[str, Any] | None = None
        last_signed_params: dict[str, Any] = {}
        while has_more and len(comments) < max_count:
            params = {
                "aweme_id": content_id,
                "cursor": root_cursor,
                "count": 20,
                "item_type": 0,
            }
            signed_params = await self.signer.sign_request(
                "/aweme/v1/web/comment/list/",
                params,
                headers,
                request_method="GET",
                page=self.hybrid_executor.browser_executor.page,
            )
            response = await self.hybrid_executor.send(
                HttpRequest(
                    method="GET",
                    url="https://www.douyin.com/aweme/v1/web/comment/list/",
                    params=signed_params,
                    headers=headers,
                )
            )
            if response.status_code != 200:
                raise DouyinDataFetchError(
                    f"Douyin comment request failed with status {response.status_code}: {response.text}"
                )
            payload = response.data if isinstance(response.data, dict) else {}
            if not payload:
                raise DouyinDataFetchError(f"Douyin comment returned invalid payload: {response.text[:300]}")
            last_payload = payload
            last_signed_params = signed_params
            page_comments = payload.get("comments", []) or []
            has_more = payload.get("has_more", 0)
            root_cursor = payload.get("cursor", 0)
            remaining = max_count - len(comments)
            if remaining <= 0:
                break
            page_comments = page_comments[:remaining]
            comments.extend(page_comments)
        return CommentsPage(
            comments=comments,
            next_cursor=root_cursor,
            has_more=bool(has_more),
            request_uri="/aweme/v1/web/comment/list/",
            raw_payload=last_payload,
            request_params=last_signed_params,
            metadata={
                "outcome": {
                    "raw_record": {
                        "record_type": "comments",
                        "source_uri": "/aweme/v1/web/comment/list/",
                        "request_meta": {"aweme_id": content_id, "limit": max_count, "cursor": cursor or 0},
                        "response_body": last_payload or {"comments": comments, "cursor": root_cursor, "has_more": has_more},
                        "metadata": {
                            "bridge": "douyin_connector",
                            "comment_count": len(comments),
                            "cursor": root_cursor,
                            "has_more": bool(has_more),
                        },
                    },
                    "events": [
                        {
                            "event_type": "comments_succeeded",
                            "message": "Douyin bridge comments succeeded",
                            "details": {"aweme_id": content_id, "comment_count": len(comments)},
                        }
                    ],
                    "response_payload": {
                        "comments": comments,
                        "cursor": root_cursor,
                        "has_more": bool(has_more),
                    },
                }
            },
        )

    async def fetch_creator(self, creator_id: str) -> CreatorResult:
        session = await self.session_service.refresh_from_browser(
            self.hybrid_executor.browser_executor,
            account_id=self.context.account_id if self.context else None,
            proxy=self.context.proxy if self.context else None,
        )
        if not session.user_agent:
            raise DouyinDataFetchError("Douyin session is missing user agent; browser state is not ready.")
        headers = {
            "User-Agent": session.user_agent or "",
            "Cookie": ";".join(f"{key}={value}" for key, value in session.cookie_dict.items()),
            "Host": "www.douyin.com",
            "Referer": "https://www.douyin.com/",
            "Content-Type": "application/json;charset=UTF-8",
        }
        params = {
            "sec_user_id": creator_id,
            "publish_video_strategy_type": 2,
            "personal_center_strategy": 1,
        }
        signed_params = await self.signer.sign_request(
            "/aweme/v1/web/user/profile/other/",
            params,
            headers,
            request_method="GET",
            page=self.hybrid_executor.browser_executor.page,
        )
        response = await self.hybrid_executor.send(
            HttpRequest(
                method="GET",
                url="https://www.douyin.com/aweme/v1/web/user/profile/other/",
                params=signed_params,
                headers=headers,
            )
        )
        if response.status_code != 200:
            raise DouyinDataFetchError(f"Douyin creator request failed with status {response.status_code}: {response.text}")
        payload = response.data if isinstance(response.data, dict) else {}
        if not payload:
            raise DouyinDataFetchError(f"Douyin creator returned invalid payload: {response.text[:300]}")
        user = payload.get("user", {})
        if not user:
            raise DouyinDataFetchError(f"Douyin creator payload missing user: {payload}")
        return CreatorResult(
            creator=payload,
            request_uri="/aweme/v1/web/user/profile/other/",
            raw_payload=payload,
            request_params=signed_params,
            metadata={
                "outcome": {
                    "raw_record": {
                        "record_type": "creator",
                        "source_uri": "/aweme/v1/web/user/profile/other/",
                        "request_meta": {"creator_id": creator_id, "request_params": signed_params},
                        "response_body": payload,
                        "metadata": {"bridge": "douyin_connector"},
                    },
                    "events": [
                        {
                            "event_type": "creator_succeeded",
                            "message": "Douyin bridge creator succeeded",
                            "details": {"creator_id": creator_id},
                        }
                    ],
                    "response_payload": {"creator": payload},
                }
            },
        )

    async def fetch_creator_contents(
        self,
        creator_id: str,
        cursor: str | int | None = None,
        limit: int | None = None,
    ) -> CreatorContentsPage:
        session = await self.session_service.refresh_from_browser(
            self.hybrid_executor.browser_executor,
            account_id=self.context.account_id if self.context else None,
            proxy=self.context.proxy if self.context else None,
        )
        if not session.user_agent:
            raise DouyinDataFetchError("Douyin session is missing user agent; browser state is not ready.")
        headers = {
            "User-Agent": session.user_agent or "",
            "Cookie": ";".join(f"{key}={value}" for key, value in session.cookie_dict.items()),
            "Host": "www.douyin.com",
            "Referer": "https://www.douyin.com/",
            "Content-Type": "application/json;charset=UTF-8",
        }
        params = {
            "sec_user_id": creator_id,
            "count": limit or 18,
            "max_cursor": str(cursor or ""),
            "locate_query": "false",
            "publish_video_strategy_type": 2,
            "verifyFp": "verify_ma3hrt8n_q2q2HyYA_uLyO_4N6D_BLvX_E2LgoGmkA1BU",
            "fp": "verify_ma3hrt8n_q2q2HyYA_uLyO_4N6D_BLvX_E2LgoGmkA1BU",
        }
        signed_params = await self.signer.sign_request(
            "/aweme/v1/web/aweme/post/",
            params,
            headers,
            request_method="GET",
            page=self.hybrid_executor.browser_executor.page,
        )
        response = await self.hybrid_executor.send(
            HttpRequest(
                method="GET",
                url="https://www.douyin.com/aweme/v1/web/aweme/post/",
                params=signed_params,
                headers=headers,
            )
        )
        if response.status_code != 200:
            raise DouyinDataFetchError(
                f"Douyin creator contents request failed with status {response.status_code}: {response.text}"
            )
        payload = response.data if isinstance(response.data, dict) else {}
        if not payload:
            raise DouyinDataFetchError(f"Douyin creator contents returned invalid payload: {response.text[:300]}")
        aweme_list = payload.get("aweme_list", []) or []
        normalized_records = [record for item in aweme_list if (record := normalize_aweme_detail(item)) is not None]
        return CreatorContentsPage(
            items=aweme_list,
            has_more=bool(payload.get("has_more", 0)),
            next_cursor=payload.get("max_cursor", ""),
            raw_payload=payload,
            request_uri="/aweme/v1/web/aweme/post/",
            request_params=signed_params,
            metadata={
                "outcome": {
                    "normalized_records": normalized_records,
                    "raw_record": {
                        "record_type": "creator_contents",
                        "source_uri": "/aweme/v1/web/aweme/post/",
                        "request_meta": {
                            "creator_id": creator_id,
                            "cursor": cursor or "",
                            "request_params": signed_params,
                        },
                        "response_body": payload,
                        "metadata": {"bridge": "douyin_connector"},
                    },
                    "events": [
                        {
                            "event_type": "creator_contents_succeeded",
                            "message": "Douyin bridge creator contents succeeded",
                            "details": {
                                "creator_id": creator_id,
                                "items_count": len(aweme_list),
                                "normalized_count": len(normalized_records),
                                "next_cursor": payload.get("max_cursor", ""),
                            },
                        }
                    ],
                    "response_payload": {
                        "items": aweme_list,
                        "normalized_records": normalized_records,
                        "has_more": bool(payload.get("has_more", 0)),
                        "next_cursor": payload.get("max_cursor", ""),
                    },
                }
            },
        )

    async def close(self) -> None:
        await self.hybrid_executor.close()


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
    return DouyinConnector(
        hybrid_executor=hybrid_executor,
        session_service=session_service,
        signer=signer,
    )
