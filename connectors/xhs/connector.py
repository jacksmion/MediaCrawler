from __future__ import annotations

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
from runtime.browser.executor import BrowserExecutor
from runtime.session.service import SessionService
from tools import utils

from .client import XiaoHongShuClient
from .errors import XhsDataFetchError
from .fields import SearchSortType
from .helpers import get_search_id, parse_creator_info_from_url, parse_note_info_from_note_url
from .normalizer import normalize_xhs_note, normalize_xhs_notes


class XhsConnector(BaseConnector):
    """New-style Xiaohongshu connector that keeps browser-side signing intact."""
    short_code = "xhs"
    source_name = "legacy_xhs_crawler"
    handled_exceptions = (XhsDataFetchError,)

    def __init__(
        self,
        *,
        browser_executor: BrowserExecutor,
        session_service: SessionService,
        browser_context=None,
        context_page=None,
        proxy: str | None = None,
        proxy_ip_pool=None,
        legacy_client=None,
    ) -> None:
        super().__init__(
            platform_code="xhs",
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
        self.browser_executor = browser_executor
        self.session_service = session_service
        self.browser_context = browser_context
        self.context_page = context_page
        self.proxy = proxy
        self.proxy_ip_pool = proxy_ip_pool
        self.legacy_client = legacy_client
        self.context: ConnectorContext | None = None

    async def prepare(self, context: ConnectorContext) -> None:
        self.context = context
        await self._ensure_legacy_client()

    async def authenticate(self, auth_context: AuthContext) -> AuthResult:
        return AuthResult(
            success=False,
            login_type=auth_context.login_type,
            account_id=auth_context.account_id,
            message="XHS connector authentication is not migrated yet.",
        )

    def use_generic_success_handling(self) -> bool:
        return True

    def build_request(self, task: CrawlTask, job_id: str) -> PlatformTaskRequest:
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
            note_id, xsec_source, xsec_token = self._resolve_detail_params(params)
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
                payload={"content_id": note_id, "limit": self._optional_int(params.get("limit")) or 10, "extra": {"xsec_token": xsec_token}},
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
                payload={"creator_id": creator_url, "cursor": self._optional_str(params.get("cursor")) or "", "limit": int(params.get("limit", 30))},
            )
        raise ValueError(f"Unsupported XHS task type: {task_type}")

    def plan_requirement(self, requirement: Any) -> list[CrawlTask]:
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

    def classify_error(self, message: str) -> str:
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

    def build_failure_event(self, *, task: CrawlTask, job_id: str, error_message: str, error_code: str) -> CrawlJobEvent:
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

    def collect_targets_from_results(self, results: list[dict[str, Any]]) -> list[dict[str, str]]:
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

    def collect_targets_from_requirement(self, requirement: Any) -> list[dict[str, str]]:
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

    def build_detail_task(self, target: dict[str, str], index: int) -> CrawlTask:
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

    def build_comments_task(self, target: dict[str, str], index: int, comment_limit: int | None) -> CrawlTask:
        return CrawlTask(
            task_id=f"xhs-followup-comments-{index}",
            platform_code=self.platform_code,
            task_type="comments",
            status="planned",
            params={"note_id": target["note_id"], "xsec_token": target["xsec_token"], "limit": comment_limit},
        )

    def dedupe_targets(self, targets: list[dict[str, str]]) -> list[dict[str, str]]:
        unique: list[dict[str, str]] = []
        seen: set[tuple[str, str]] = set()
        for target in targets:
            key = (target["note_id"], target["xsec_token"])
            if key in seen:
                continue
            seen.add(key)
            unique.append(target)
        return unique

    async def health_check(self) -> HealthStatus:
        session = await self._refresh_session()
        ok = bool(session.cookie_dict.get("a1"))
        return HealthStatus(
            ok=ok,
            platform_code=self.platform_code,
            message="XHS session loaded" if ok else "XHS session missing a1 cookie",
            details={"cookie_keys": sorted(session.cookie_dict.keys())[:10]},
        )

    async def search(self, query: SearchQuery) -> SearchPage:
        client = self._get_client()
        sort_value = str(query.filters.get("sort", SearchSortType.GENERAL.value))
        try:
            sort_type = SearchSortType(sort_value)
        except ValueError as exc:
            raise XhsDataFetchError(f"Unsupported XHS sort type: {sort_value}") from exc
        response = await client.get_note_by_keyword(
            keyword=query.keyword,
            search_id=str(query.metadata.get("search_id") or query.filters.get("search_id") or ""),
            page=query.page,
            page_size=query.page_size,
            sort=sort_type,
        )
        items = [
            item
            for item in response.get("items", []) or []
            if item.get("model_type") not in ("rec_query", "hot_query")
        ]
        notes = await self._hydrate_note_details(items, default_xsec_source="pc_search")
        normalized_records = normalize_xhs_notes(notes)
        has_more = bool(response.get("has_more", False))
        next_cursor = str(query.page + 1) if has_more else None
        return SearchPage(
            items=notes,
            has_more=has_more,
            next_cursor=next_cursor,
            raw=response,
            metadata={
                "request_uri": "/api/sns/web/v1/search/notes",
                "keyword": query.keyword,
                "page": query.page,
                "outcome": {
                    "normalized_records": normalized_records,
                    "raw_record": {
                        "record_type": "search",
                        "source_uri": "/api/sns/web/v1/search/notes",
                        "request_meta": {
                            "keyword": query.keyword,
                            "page": query.page,
                            "search_id": str(query.metadata.get("search_id") or query.filters.get("search_id") or ""),
                        },
                        "response_body": response,
                        "metadata": {
                            "bridge": "xhs_connector",
                            "normalized_count": len(normalized_records),
                        },
                    },
                    "events": [
                        {
                            "event_type": "search_page_succeeded",
                            "message": "XHS bridge search page succeeded",
                            "details": {"keyword": query.keyword, "page": query.page, "items_count": len(notes)},
                        }
                    ],
                    "response_payload": {
                        "items": notes,
                        "raw_items": items,
                        "normalized_records": normalized_records,
                        "has_more": has_more,
                        "next_cursor": next_cursor,
                    },
                },
            },
        )

    async def fetch_content_detail(self, content_id: str, extra: dict[str, Any] | None = None) -> ContentDetailResult:
        client = self._get_client()
        xsec_source = str((extra or {}).get("xsec_source") or "pc_search")
        xsec_token = str((extra or {}).get("xsec_token") or "")
        if not xsec_token:
            raise XhsDataFetchError("XHS detail request requires xsec_token in extra payload.")
        note_detail = await client.get_note_by_id(content_id, xsec_source, xsec_token)
        if not note_detail:
            note_detail = await client.get_note_by_id_from_html(
                content_id,
                xsec_source,
                xsec_token,
                enable_cookie=True,
            )
        if not note_detail:
            raise XhsDataFetchError(f"XHS detail payload could not be fetched for {content_id}")
        note_detail.update({"xsec_token": xsec_token, "xsec_source": xsec_source})
        normalized_record = normalize_xhs_note(note_detail)
        return ContentDetailResult(
            item=note_detail,
            item_key="note",
            raw_payload=note_detail,
            request_uri="/api/sns/web/v1/feed",
            metadata={
                "outcome": {
                    "normalized_records": [normalized_record],
                    "raw_record": {
                        "record_type": "detail",
                        "source_uri": "/api/sns/web/v1/feed",
                        "request_meta": {"note_id": content_id},
                        "response_body": note_detail,
                        "metadata": {"bridge": "xhs_connector"},
                    },
                    "events": [
                        {
                            "event_type": "detail_succeeded",
                            "message": "XHS bridge detail succeeded",
                            "details": {"note_id": content_id},
                        }
                    ],
                    "response_payload": {"note": note_detail},
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
        client = self._get_client()
        xsec_token = str((extra or {}).get("xsec_token") or "")
        if not xsec_token:
            raise XhsDataFetchError("XHS comments request requires xsec_token in extra payload.")
        comments: list[dict[str, Any]] = []

        async def _collect(_note_id: str, page_comments: list[dict[str, Any]]) -> None:
            comments.extend(page_comments)

        await client.get_note_all_comments(
            note_id=content_id,
            xsec_token=xsec_token,
            crawl_interval=0,
            callback=_collect,
            max_count=int(limit or 10),
        )
        result_comments = comments[: int(limit or len(comments) or 10)]
        return CommentsPage(
            comments=result_comments,
            next_cursor=cursor or "",
            has_more=False,
            request_uri="/api/sns/web/v2/comment/page",
            raw_payload=comments,
            metadata={
                "outcome": {
                    "raw_record": {
                        "record_type": "comments",
                        "source_uri": "/api/sns/web/v2/comment/page",
                        "request_meta": {"note_id": content_id},
                        "response_body": comments,
                        "metadata": {"bridge": "xhs_connector", "comment_count": len(result_comments)},
                    },
                    "events": [
                        {
                            "event_type": "comments_succeeded",
                            "message": "XHS bridge comments succeeded",
                            "details": {"note_id": content_id, "comment_count": len(result_comments)},
                        }
                    ],
                    "response_payload": {
                        "comments": result_comments,
                        "cursor": cursor or "",
                        "has_more": False,
                    },
                }
            },
        )

    async def fetch_creator(self, creator_id: str) -> CreatorResult:
        client = self._get_client()
        try:
            parsed = parse_creator_info_from_url(creator_id)
        except ValueError as exc:
            raise XhsDataFetchError(str(exc)) from exc
        creator = await client.get_creator_info(
            user_id=parsed.user_id,
            xsec_token=parsed.xsec_token,
            xsec_source=parsed.xsec_source,
        )
        if not creator:
            raise XhsDataFetchError(f"XHS creator payload could not be fetched for {creator_id}")
        return CreatorResult(
            creator=creator,
            raw_payload=creator,
            request_uri=f"/user/profile/{parsed.user_id}",
            metadata={
                "outcome": {
                    "raw_record": {
                        "record_type": "creator",
                        "source_uri": f"/user/profile/{parsed.user_id}",
                        "request_meta": {"creator_url": creator_id},
                        "response_body": creator,
                        "metadata": {"bridge": "xhs_connector"},
                    },
                    "events": [
                        {
                            "event_type": "creator_succeeded",
                            "message": "XHS bridge creator succeeded",
                            "details": {"creator_url": creator_id},
                        }
                    ],
                    "response_payload": {
                        "creator": creator,
                        "creator_id": parsed.user_id,
                        "xsec_token": parsed.xsec_token,
                        "xsec_source": parsed.xsec_source,
                    },
                }
            },
        )

    async def fetch_creator_contents(
        self,
        creator_id: str,
        cursor: str | int | None = None,
        limit: int | None = None,
    ) -> CreatorContentsPage:
        client = self._get_client()
        try:
            parsed = parse_creator_info_from_url(creator_id)
        except ValueError as exc:
            raise XhsDataFetchError(str(exc)) from exc
        response = await client.get_notes_by_creator(
            creator=parsed.user_id,
            cursor=str(cursor or ""),
            page_size=int(limit or 30),
            xsec_token=parsed.xsec_token,
            xsec_source=parsed.xsec_source or "pc_feed",
        )
        items = response.get("notes", []) or []
        raw_items = items[: int(limit or len(items) or 30)]
        notes = await self._hydrate_note_details(raw_items, default_xsec_source=parsed.xsec_source or "pc_feed")
        normalized_records = normalize_xhs_notes(notes)
        has_more = bool(response.get("has_more", False))
        next_cursor = str(response.get("cursor") or "")
        return CreatorContentsPage(
            items=notes,
            has_more=has_more,
            next_cursor=next_cursor,
            raw_payload=response,
            request_uri="/api/sns/web/v1/user_posted",
            metadata={
                "outcome": {
                    "normalized_records": normalized_records,
                    "raw_record": {
                        "record_type": "creator_contents",
                        "source_uri": "/api/sns/web/v1/user_posted",
                        "request_meta": {"creator_url": creator_id, "cursor": str(cursor or "")},
                        "response_body": response,
                        "metadata": {
                            "bridge": "xhs_connector",
                            "normalized_count": len(normalized_records),
                        },
                    },
                    "events": [
                        {
                            "event_type": "creator_contents_succeeded",
                            "message": "XHS bridge creator contents succeeded",
                            "details": {"creator_url": creator_id, "items_count": len(notes)},
                        }
                    ],
                    "response_payload": {
                        "items": notes,
                        "raw_items": raw_items,
                        "normalized_records": normalized_records,
                        "has_more": has_more,
                        "next_cursor": next_cursor,
                    },
                }
            },
        )

    async def close(self) -> None:
        await self.browser_executor.close()

    async def _refresh_session(self):
        session = await self.session_service.refresh_from_browser(
            self.browser_executor,
            account_id=self.context.account_id if self.context else None,
            proxy=self.context.proxy if self.context else None,
        )
        session.login_status = bool(session.cookie_dict.get("a1"))
        self.session_service.save(session)
        return session

    def _get_client(self):
        if self.legacy_client is None:
            raise XhsDataFetchError("XHS legacy client is not ready; browser runtime has not been initialized.")
        return self.legacy_client

    async def _ensure_legacy_client(self) -> None:
        if self.browser_context is None or self.context_page is None:
            raise XhsDataFetchError("XHS browser runtime is not initialized.")
        if self.legacy_client is None:
            self.legacy_client = await self._build_legacy_client()
            return
        await self.legacy_client.update_cookies(browser_context=self.browser_context)

    async def _build_legacy_client(self) -> XiaoHongShuClient:
        if self.browser_context is None or self.context_page is None:
            raise XhsDataFetchError("XHS browser runtime is not initialized.")
        cookie_str, cookie_dict = utils.convert_cookies(await self.browser_context.cookies())
        return XiaoHongShuClient(
            proxy=self.proxy,
            headers={
                "accept": "application/json, text/plain, */*",
                "accept-language": "zh-CN,zh;q=0.9",
                "cache-control": "no-cache",
                "content-type": "application/json;charset=UTF-8",
                "origin": "https://www.xiaohongshu.com",
                "pragma": "no-cache",
                "priority": "u=1, i",
                "referer": "https://www.xiaohongshu.com/",
                "sec-ch-ua": '"Chromium";v="136", "Google Chrome";v="136", "Not.A/Brand";v="99"',
                "sec-ch-ua-mobile": "?0",
                "sec-ch-ua-platform": '"Windows"',
                "sec-fetch-dest": "empty",
                "sec-fetch-mode": "cors",
                "sec-fetch-site": "same-site",
                "user-agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/137.0.0.0 Safari/537.36",
                "Cookie": cookie_str,
            },
            playwright_page=self.context_page,
            cookie_dict=cookie_dict,
            proxy_ip_pool=self.proxy_ip_pool,
        )

    @staticmethod
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

    async def _hydrate_note_details(self, raw_items: list[dict[str, Any]], *, default_xsec_source: str) -> list[dict[str, Any]]:
        if not raw_items:
            return []
        notes: list[dict[str, Any]] = []
        for item in raw_items:
            note_id = str(item.get("note_id") or item.get("id") or "")
            xsec_token = str(item.get("xsec_token") or "")
            if not note_id or not xsec_token:
                continue
            detail = await self.fetch_content_detail(
                note_id,
                extra={"xsec_source": str(item.get("xsec_source") or default_xsec_source), "xsec_token": xsec_token},
            )
            if detail.item:
                notes.append(detail.item)
        return notes


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
    return XhsConnector(
        browser_executor=browser_executor,
        session_service=session_service,
        browser_context=getattr(crawler, "browser_context", None),
        context_page=getattr(crawler, "context_page", None),
        proxy=getattr(crawler, "_platform_http_proxy", None),
        proxy_ip_pool=getattr(crawler, "ip_proxy_pool", None),
    )
