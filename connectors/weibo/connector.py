from __future__ import annotations

import json
from typing import Any
from urllib.parse import parse_qs, unquote

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
from runtime.http.executor import HttpExecutor
from runtime.http.models import HttpRequest
from runtime.session.service import SessionService

from .errors import WeiboDataFetchError
from .fields import SearchType
from .helpers import filter_search_result_card
from .normalizer import normalize_weibo_note, normalize_weibo_notes


class WeiboConnector(BaseConnector):
    """New-style Weibo connector for incremental platform migration."""
    short_code = "wb"
    source_name = "legacy_weibo_crawler"
    handled_exceptions = (WeiboDataFetchError,)

    def __init__(
        self,
        *,
        browser_executor: BrowserExecutor,
        http_executor: HttpExecutor,
        session_service: SessionService,
    ) -> None:
        super().__init__(
            platform_code="weibo",
            capabilities=ConnectorCapability(
                supports_search=True,
                supports_detail=True,
                supports_comments=True,
                supports_creator=True,
                requires_browser=True,
                requires_signing=False,
                supports_incremental=True,
                supports_resume=True,
            ),
        )
        self.browser_executor = browser_executor
        self.http_executor = http_executor
        self.session_service = session_service
        self.context: ConnectorContext | None = None
        self.host = "https://m.weibo.cn"

    async def prepare(self, context: ConnectorContext) -> None:
        self.context = context

    async def authenticate(self, auth_context: AuthContext) -> AuthResult:
        return AuthResult(
            success=False,
            login_type=auth_context.login_type,
            account_id=auth_context.account_id,
            message="Weibo connector authentication is not migrated yet.",
        )

    def use_generic_success_handling(self) -> bool:
        return True

    def build_request(self, task: CrawlTask, job_id: str) -> PlatformTaskRequest:
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
            return PlatformTaskRequest(job_id=job_id, platform_code=self.platform_code, task_kind="comments", payload={"content_id": note_id, "cursor": params.get("cursor", -1), "limit": self._optional_int(params.get("limit")) or 10})
        if task_type == "creator":
            creator_id = str(params.get("creator_id") or "")
            if not creator_id:
                raise ValueError("Weibo creator task requires creator_id")
            return PlatformTaskRequest(job_id=job_id, platform_code=self.platform_code, task_kind="creator", payload={"creator_id": creator_id})
        if task_type == "creator_contents":
            creator_id = str(params.get("creator_id") or "")
            if not creator_id:
                raise ValueError("Weibo creator_contents task requires creator_id")
            return PlatformTaskRequest(job_id=job_id, platform_code=self.platform_code, task_kind="creator_contents", payload={"creator_id": creator_id, "cursor": self._optional_str(params.get("cursor")) or "", "limit": int(params.get("limit", 10))})
        raise ValueError(f"Unsupported Weibo task type: {task_type}")

    def plan_requirement(self, requirement: Any) -> list[CrawlTask]:
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

    def classify_error(self, message: str) -> str:
        lowered = message.lower()
        if "cookie" in lowered or "auth" in lowered:
            return "session_not_ready"
        if "parse" in lowered:
            return "parse_failed"
        if "status 4" in lowered or "status 5" in lowered:
            return "http_error"
        return "unknown_error"

    def build_failure_event(self, *, task: CrawlTask, job_id: str, error_message: str, error_code: str) -> CrawlJobEvent:
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

    def collect_targets_from_results(self, results: list[dict[str, Any]]) -> list[str]:
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

    def collect_targets_from_requirement(self, requirement: Any) -> list[str]:
        return [note_id.strip() for note_id in requirement.note_ids if note_id.strip()]

    def build_detail_task(self, target: str, index: int) -> CrawlTask:
        return CrawlTask(task_id=f"wb-followup-detail-{index}", platform_code=self.platform_code, task_type="detail", status="planned", params={"note_id": target})

    def build_comments_task(self, target: str, index: int, comment_limit: int | None) -> CrawlTask:
        return CrawlTask(task_id=f"wb-followup-comments-{index}", platform_code=self.platform_code, task_type="comments", status="planned", params={"note_id": target, "cursor": -1, "limit": comment_limit})

    def dedupe_targets(self, targets: list[str]) -> list[str]:
        return list(dict.fromkeys([target for target in targets if target]))

    async def health_check(self) -> HealthStatus:
        session = await self._refresh_session()
        ok = bool(session.cookie_dict.get("SUB") or session.cookie_dict.get("SCF"))
        return HealthStatus(
            ok=ok,
            platform_code=self.platform_code,
            message="Weibo session loaded" if ok else "Weibo session missing mobile auth cookies",
            details={"cookie_keys": sorted(session.cookie_dict.keys())[:10]},
        )

    async def search(self, query: SearchQuery) -> SearchPage:
        search_type = str(query.filters.get("search_type", SearchType.DEFAULT.value))
        payload = await self._get_json(
            "/api/container/getIndex",
            {
                "containerid": f"100103type={search_type}&q={query.keyword}",
                "page_type": "searchall",
                "page": query.page,
            },
        )
        cards = payload.get("cards", []) or []
        items = filter_search_result_card(cards)
        normalized_records = normalize_weibo_notes(items)
        return SearchPage(
            items=items,
            has_more=bool(items),
            next_cursor=str(query.page + 1) if items else None,
            raw=payload,
            metadata={
                "request_uri": "/api/container/getIndex",
                "keyword": query.keyword,
                "page": query.page,
                "outcome": {
                    "normalized_records": normalized_records,
                    "raw_record": {
                        "record_type": "search",
                        "source_uri": "/api/container/getIndex",
                        "request_meta": {"keyword": query.keyword, "page": query.page},
                        "response_body": payload,
                        "metadata": {
                            "bridge": "weibo_connector",
                            "normalized_count": len(normalized_records),
                        },
                    },
                    "events": [
                        {
                            "event_type": "search_page_succeeded",
                            "message": "Weibo bridge search page succeeded",
                            "details": {
                                "keyword": query.keyword,
                                "page": query.page,
                                "items_count": len(items),
                            },
                        }
                    ],
                    "response_payload": {
                        "items": items,
                        "normalized_records": normalized_records,
                        "has_more": bool(items),
                        "next_cursor": str(query.page + 1) if items else None,
                        "raw": payload,
                    },
                },
            },
        )

    async def fetch_content_detail(self, content_id: str, extra: dict[str, Any] | None = None) -> ContentDetailResult:
        response = await self._request_text(f"{self.host}/detail/{content_id}")
        match = __import__("re").search(r'var \$render_data = (\[.*?\])\[0\]', response, __import__("re").DOTALL)
        if not match:
            raise WeiboDataFetchError(f"Weibo detail payload could not be parsed for {content_id}")
        payload = json.loads(match.group(1))
        note = {"mblog": payload[0].get("status", {})}
        normalized_record = normalize_weibo_note(note)
        return ContentDetailResult(
            item=note,
            item_key="note",
            raw_payload=response,
            request_uri=f"/detail/{content_id}",
            metadata={
                "outcome": {
                    "normalized_records": [normalized_record] if normalized_record is not None else [],
                    "raw_record": {
                        "record_type": "detail",
                        "source_uri": f"/detail/{content_id}",
                        "request_meta": {"note_id": content_id},
                        "response_body": response,
                        "metadata": {"bridge": "weibo_connector"},
                    },
                    "events": [
                        {
                            "event_type": "detail_succeeded",
                            "message": "Weibo bridge detail succeeded",
                            "details": {"note_id": content_id},
                        }
                    ],
                    "response_payload": {"note": note},
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
        max_id = int(cursor or -1)
        max_id_type = 0
        is_end = False
        comments: list[dict[str, Any]] = []
        raw_pages: list[dict[str, Any]] = []
        max_count = int(limit or 10)
        while not is_end and len(comments) < max_count:
            params = {"id": content_id, "mid": content_id, "max_id_type": max_id_type}
            if max_id > 0:
                params["max_id"] = max_id
            payload = await self._get_json("/comments/hotflow", params, referer=f"https://m.weibo.cn/detail/{content_id}")
            raw_pages.append(payload)
            page_comments = payload.get("data", []) or []
            if not page_comments:
                break
            remaining = max_count - len(comments)
            comments.extend(page_comments[:remaining])
            max_id = int(payload.get("max_id", 0) or 0)
            max_id_type = int(payload.get("max_id_type", 0) or 0)
            is_end = max_id == 0
        return CommentsPage(
            comments=comments,
            next_cursor=max_id,
            has_more=not is_end,
            request_uri="/comments/hotflow",
            raw_payload=raw_pages,
            metadata={
                "outcome": {
                    "raw_record": {
                        "record_type": "comments",
                        "source_uri": "/comments/hotflow",
                        "request_meta": {"content_id": content_id, "cursor": cursor or -1, "limit": max_count},
                        "response_body": raw_pages,
                        "metadata": {
                            "bridge": "weibo_connector",
                            "comment_count": len(comments),
                        },
                    },
                    "events": [
                        {
                            "event_type": "comments_succeeded",
                            "message": "Weibo bridge comments succeeded",
                            "details": {"note_id": content_id, "comment_count": len(comments)},
                        }
                    ],
                    "response_payload": {
                        "comments": comments,
                        "cursor": max_id,
                        "has_more": not is_end,
                    },
                }
            },
        )

    async def fetch_creator(self, creator_id: str) -> CreatorResult:
        payload = await self._get_json(
            "/api/container/getIndex",
            {
                "jumpfrom": "weibocom",
                "type": "uid",
                "value": creator_id,
                "containerid": f"100505{creator_id}",
            },
        )
        user_info = payload.get("userInfo", {})
        if not user_info:
            raise WeiboDataFetchError(f"Weibo creator payload missing userInfo for {creator_id}")
        return CreatorResult(
            creator=user_info,
            raw_payload=payload,
            request_uri="/api/container/getIndex",
            metadata={
                "outcome": {
                    "raw_record": {
                        "record_type": "creator",
                        "source_uri": "/api/container/getIndex",
                        "request_meta": {"creator_id": creator_id},
                        "response_body": payload,
                        "metadata": {"bridge": "weibo_connector"},
                    },
                    "events": [
                        {
                            "event_type": "creator_succeeded",
                            "message": "Weibo bridge creator succeeded",
                            "details": {"creator_id": creator_id},
                        }
                    ],
                    "response_payload": {"creator": user_info},
                }
            },
        )

    async def fetch_creator_contents(
        self,
        creator_id: str,
        cursor: str | int | None = None,
        limit: int | None = None,
    ) -> CreatorContentsPage:
        container_id = str((cursor or "").strip())
        since_id = ""
        if "|" in container_id:
            container_id, since_id = container_id.split("|", 1)
        if not container_id:
            container_id = await self._resolve_creator_container_id(creator_id)
        payload = await self._get_json(
            "/api/container/getIndex",
            {
                "jumpfrom": "weibocom",
                "type": "uid",
                "value": creator_id,
                "containerid": container_id,
                "since_id": since_id,
            },
        )
        items = [item for item in payload.get("cards", []) if item.get("card_type") == 9]
        next_since = payload.get("cardlistInfo", {}).get("since_id", "0")
        result_items = items[: int(limit or len(items) or 10)]
        normalized_records = normalize_weibo_notes(result_items)
        next_cursor = f"{container_id}|{next_since}" if next_since and next_since != "0" else ""
        return CreatorContentsPage(
            items=result_items,
            has_more=bool(next_since and next_since != "0"),
            next_cursor=next_cursor,
            raw_payload=payload,
            request_uri="/api/container/getIndex",
            metadata={
                "outcome": {
                    "normalized_records": normalized_records,
                    "raw_record": {
                        "record_type": "creator_contents",
                        "source_uri": "/api/container/getIndex",
                        "request_meta": {"creator_id": creator_id, "cursor": str(cursor or "")},
                        "response_body": payload,
                        "metadata": {
                            "bridge": "weibo_connector",
                            "normalized_count": len(normalized_records),
                        },
                    },
                    "events": [
                        {
                            "event_type": "creator_contents_succeeded",
                            "message": "Weibo bridge creator contents succeeded",
                            "details": {"creator_id": creator_id, "items_count": len(result_items)},
                        }
                    ],
                    "response_payload": {
                        "items": result_items,
                        "normalized_records": normalized_records,
                        "has_more": bool(next_since and next_since != "0"),
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
        session.login_status = bool(session.cookie_dict.get("SUB") or session.cookie_dict.get("SCF"))
        self.session_service.save(session)
        return session

    async def _build_headers(self, referer: str | None = None) -> dict[str, str]:
        session = await self._refresh_session()
        cookie_str = ";".join(f"{key}={value}" for key, value in session.cookie_dict.items())
        headers = {
            "User-Agent": session.user_agent or "",
            "Cookie": cookie_str,
            "Origin": "https://m.weibo.cn",
            "Referer": referer or "https://m.weibo.cn",
            "Content-Type": "application/json;charset=UTF-8",
        }
        return headers

    async def _get_json(self, uri: str, params: dict[str, Any], referer: str | None = None) -> dict[str, Any]:
        response = await self.http_executor.send(
            HttpRequest(
                method="GET",
                url=f"{self.host}{uri}",
                params=params,
                headers=await self._build_headers(referer),
            )
        )
        if response.status_code != 200:
            raise WeiboDataFetchError(f"Weibo request failed with status {response.status_code}: {response.text[:300]}")
        payload = response.data if isinstance(response.data, dict) else {}
        ok_code = payload.get("ok")
        if ok_code != 1:
            raise WeiboDataFetchError(str(payload.get("msg", "response error")))
        return payload.get("data", {}) or {}

    async def _request_text(self, url: str) -> str:
        response = await self.http_executor.send(
            HttpRequest(
                method="GET",
                url=url,
                headers=await self._build_headers(url),
            )
        )
        if response.status_code != 200:
            raise WeiboDataFetchError(f"Weibo detail request failed with status {response.status_code}: {response.text[:300]}")
        return response.text

    async def _resolve_creator_container_id(self, creator_id: str) -> str:
        response = await self.http_executor.send(
            HttpRequest(
                method="GET",
                url=f"{self.host}/u/{creator_id}",
                headers=await self._build_headers(f"{self.host}/u/{creator_id}"),
            )
        )
        if response.status_code != 200:
            raise WeiboDataFetchError(f"Weibo creator container request failed with status {response.status_code}")
        m_weibocn_params = response.headers.get("set-cookie", "")
        if "M_WEIBOCN_PARAMS" not in m_weibocn_params:
            cookies = response.headers.get("Set-Cookie", "")
            m_weibocn_params = cookies
        match = __import__("re").search(r"M_WEIBOCN_PARAMS=([^;]+)", m_weibocn_params)
        if not match:
            raise WeiboDataFetchError("Weibo creator container id not found in cookies")
        query = parse_qs(unquote(match.group(1)))
        container_id = query.get("lfid", [""])[0]
        if not container_id:
            raise WeiboDataFetchError("Weibo creator lfid container id missing")
        return container_id

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
    return WeiboConnector(
        browser_executor=browser_executor,
        http_executor=http_executor,
        session_service=session_service,
    )
