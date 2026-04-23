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
from runtime.browser.executor import BrowserExecutor
from runtime.http.executor import HttpExecutor
from runtime.http.models import HttpRequest
from runtime.session.service import SessionService

from .errors import BilibiliDataFetchError
from .fields import CommentOrderType, SearchOrderType
from .helpers import BilibiliSign
from .normalizer import normalize_bilibili_video, normalize_bilibili_videos


class BilibiliConnector(BaseConnector):
    """New-style Bilibili connector for incremental platform migration."""

    def __init__(
        self,
        *,
        browser_executor: BrowserExecutor,
        http_executor: HttpExecutor,
        session_service: SessionService,
    ) -> None:
        super().__init__(
            platform_code="bilibili",
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
        self.http_executor = http_executor
        self.session_service = session_service
        self.context: ConnectorContext | None = None

    async def prepare(self, context: ConnectorContext) -> None:
        self.context = context

    async def authenticate(self, auth_context: AuthContext) -> AuthResult:
        return AuthResult(
            success=False,
            login_type=auth_context.login_type,
            account_id=auth_context.account_id,
            message="Bilibili connector authentication is not migrated yet.",
        )

    async def health_check(self) -> HealthStatus:
        session = await self._refresh_session()
        ok = bool(session.cookie_dict.get("SESSDATA"))
        return HealthStatus(
            ok=ok,
            platform_code=self.platform_code,
            message="Bilibili session loaded" if ok else "Bilibili session missing SESSDATA cookie",
            details={"cookie_keys": sorted(session.cookie_dict.keys())[:10]},
        )

    async def search(self, query: SearchQuery) -> SearchPage:
        payload = await self._get_json(
            "/x/web-interface/wbi/search/type",
            {
                "search_type": "video",
                "keyword": query.keyword,
                "page": query.page,
                "page_size": query.page_size,
                "order": query.filters.get("order", SearchOrderType.DEFAULT.value),
                "pubtime_begin_s": query.filters.get("pubtime_begin_s", 0),
                "pubtime_end_s": query.filters.get("pubtime_end_s", 0),
            },
        )
        items = payload.get("result", []) or []
        outcome = {
            "raw_record": {
                "record_type": "search",
                "source_uri": "/x/web-interface/wbi/search/type",
                "request_meta": {"keyword": query.keyword, "page": query.page},
                "response_body": payload,
                "metadata": {"bridge": "bilibili_connector", "items_count": len(items)},
            },
            "events": [
                {
                    "event_type": "search_page_succeeded",
                    "message": "Bilibili bridge search page succeeded",
                    "details": {"keyword": query.keyword, "page": query.page, "items_count": len(items)},
                }
            ],
            "response_payload": {
                "items": items,
                "has_more": bool(items),
                "next_cursor": str(query.page + 1) if items else None,
                "raw": payload,
            },
        }
        return SearchPage(
            items=items,
            has_more=bool(items),
            next_cursor=str(query.page + 1) if items else None,
            raw=payload,
            metadata={
                "request_uri": "/x/web-interface/wbi/search/type",
                "keyword": query.keyword,
                "page": query.page,
                "outcome": outcome,
            },
        )

    async def fetch_content_detail(self, content_id: str, extra: dict[str, Any] | None = None) -> ContentDetailResult:
        params: dict[str, Any]
        if str((extra or {}).get("bvid") or ""):
            params = {"bvid": str((extra or {}).get("bvid"))}
        else:
            params = {"aid": int(content_id)}
        payload = await self._get_json("/x/web-interface/view/detail", params, sign_params=False)
        if not payload.get("View"):
            raise BilibiliDataFetchError(f"Bilibili detail payload missing View for content {content_id}")
        normalized_record = normalize_bilibili_video(payload)
        return ContentDetailResult(
            item=payload,
            item_key="video",
            raw_payload=payload,
            request_uri="/x/web-interface/view/detail",
            request_params=params,
            metadata={
                "outcome": {
                    "normalized_records": [normalized_record] if normalized_record is not None else [],
                    "raw_record": {
                        "record_type": "detail",
                        "source_uri": "/x/web-interface/view/detail",
                        "request_meta": {
                            "content_id": content_id,
                            "bvid": str((extra or {}).get("bvid") or ""),
                        },
                        "response_body": payload,
                        "metadata": {"bridge": "bilibili_connector"},
                    },
                    "events": [
                        {
                            "event_type": "detail_succeeded",
                            "message": "Bilibili bridge detail succeeded",
                            "details": {
                                "content_id": content_id,
                                "bvid": str((extra or {}).get("bvid") or ""),
                            },
                        }
                    ],
                    "response_payload": {"video": payload},
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
        comments: list[dict[str, Any]] = []
        next_cursor = int(cursor or 0)
        is_end = False
        max_count = int(limit or 10)
        raw_pages: list[dict[str, Any]] = []
        while not is_end and len(comments) < max_count:
            payload = await self._get_json(
                "/x/v2/reply/wbi/main",
                {
                    "oid": content_id,
                    "mode": (extra or {}).get("order_mode", CommentOrderType.DEFAULT.value),
                    "type": 1,
                    "ps": 20,
                    "next": next_cursor,
                },
            )
            raw_pages.append(payload)
            page_comments = payload.get("replies", []) or []
            if not page_comments:
                break
            remaining = max_count - len(comments)
            comments.extend(page_comments[:remaining])
            cursor_info = payload.get("cursor", {})
            is_end = bool(cursor_info.get("is_end", True))
            next_cursor = int(cursor_info.get("next", next_cursor))
        return CommentsPage(
            comments=comments,
            next_cursor=next_cursor,
            has_more=not is_end,
            request_uri="/x/v2/reply/wbi/main",
            raw_payload=raw_pages,
            metadata={
                "outcome": {
                    "raw_record": {
                        "record_type": "comments",
                        "source_uri": "/x/v2/reply/wbi/main",
                        "request_meta": {"content_id": content_id},
                        "response_body": raw_pages,
                        "metadata": {"bridge": "bilibili_connector", "comment_count": len(comments)},
                    },
                    "events": [
                        {
                            "event_type": "comments_succeeded",
                            "message": "Bilibili bridge comments succeeded",
                            "details": {"content_id": content_id, "comment_count": len(comments)},
                        }
                    ],
                    "response_payload": {
                        "comments": comments,
                        "cursor": next_cursor,
                        "has_more": not is_end,
                    },
                }
            },
        )

    async def fetch_creator(self, creator_id: str) -> CreatorResult:
        payload = await self._get_json("/x/space/wbi/acc/info", {"mid": int(creator_id)})
        if not payload.get("name"):
            raise BilibiliDataFetchError(f"Bilibili creator payload missing name for creator {creator_id}")
        return CreatorResult(
            creator=payload,
            raw_payload=payload,
            request_uri="/x/space/wbi/acc/info",
            metadata={
                "outcome": {
                    "raw_record": {
                        "record_type": "creator",
                        "source_uri": "/x/space/wbi/acc/info",
                        "request_meta": {"creator_id": creator_id},
                        "response_body": payload,
                        "metadata": {"bridge": "bilibili_connector"},
                    },
                    "events": [
                        {
                            "event_type": "creator_succeeded",
                            "message": "Bilibili bridge creator succeeded",
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
        page_number = int(cursor or 1)
        page_size = int(limit or 30)
        payload = await self._get_json(
            "/x/space/wbi/arc/search",
            {
                "mid": int(creator_id),
                "pn": page_number,
                "ps": page_size,
                "order": SearchOrderType.LAST_PUBLISH.value,
            },
        )
        raw_items = (((payload.get("list") or {}).get("vlist")) or [])
        items: list[dict[str, Any]] = []
        for item in raw_items:
            detail = await self.fetch_content_detail(str(item.get("aid") or 0), extra={"bvid": item.get("bvid", "")})
            items.append(detail.item)
        page_info = payload.get("page", {}) or {}
        total = int(page_info.get("count", 0) or 0)
        has_more = total > page_number * page_size
        normalized_records = normalize_bilibili_videos(items)
        return CreatorContentsPage(
            items=items,
            has_more=has_more,
            next_cursor=str(page_number + 1) if has_more else "",
            raw_payload=payload,
            request_uri="/x/space/wbi/arc/search",
            metadata={
                "outcome": {
                    "normalized_records": normalized_records,
                    "raw_record": {
                        "record_type": "creator_contents",
                        "source_uri": "/x/space/wbi/arc/search",
                        "request_meta": {"creator_id": creator_id, "cursor": str(cursor or 1)},
                        "response_body": payload,
                        "metadata": {
                            "bridge": "bilibili_connector",
                            "normalized_count": len(normalized_records),
                        },
                    },
                    "events": [
                        {
                            "event_type": "creator_contents_succeeded",
                            "message": "Bilibili bridge creator contents succeeded",
                            "details": {"creator_id": creator_id, "items_count": len(items)},
                        }
                    ],
                    "response_payload": {
                        "items": items,
                        "normalized_records": normalized_records,
                        "has_more": has_more,
                        "next_cursor": str(page_number + 1) if has_more else "",
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
        session.login_status = bool(session.cookie_dict.get("SESSDATA"))
        self.session_service.save(session)
        return session

    async def _get_wbi_keys(self) -> tuple[str, str]:
        local_storage = (await self.browser_executor.snapshot()).local_storage
        wbi_img_urls = local_storage.get("wbi_img_urls", "")
        if not wbi_img_urls:
            img_url = local_storage.get("wbi_img_url")
            sub_url = local_storage.get("wbi_sub_url")
            if img_url and sub_url:
                wbi_img_urls = f"{img_url}-{sub_url}"
        if not wbi_img_urls or "-" not in wbi_img_urls:
            payload = await self._get_json("/x/web-interface/nav", {}, sign_params=False)
            img_url = payload["wbi_img"]["img_url"]
            sub_url = payload["wbi_img"]["sub_url"]
        else:
            img_url, sub_url = wbi_img_urls.split("-", 1)
        img_key = img_url.rsplit("/", 1)[1].split(".")[0]
        sub_key = sub_url.rsplit("/", 1)[1].split(".")[0]
        return img_key, sub_key

    async def _build_headers(self) -> dict[str, str]:
        session = await self._refresh_session()
        cookie_str = ";".join(f"{key}={value}" for key, value in session.cookie_dict.items())
        return {
            "User-Agent": session.user_agent or "",
            "Cookie": cookie_str,
            "Origin": "https://www.bilibili.com",
            "Referer": "https://www.bilibili.com",
            "Content-Type": "application/json;charset=UTF-8",
        }

    async def _get_json(self, uri: str, params: dict[str, Any], *, sign_params: bool = True) -> dict[str, Any]:
        headers = await self._build_headers()
        actual_params = dict(params)
        if sign_params:
            img_key, sub_key = await self._get_wbi_keys()
            actual_params = BilibiliSign(img_key, sub_key).sign(actual_params)
        response = await self.http_executor.send(
            HttpRequest(
                method="GET",
                url=f"https://api.bilibili.com{uri}",
                params=actual_params,
                headers=headers,
            )
        )
        if response.status_code != 200:
            raise BilibiliDataFetchError(f"Bilibili request failed with status {response.status_code}: {response.text[:300]}")
        payload = response.data if isinstance(response.data, dict) else {}
        if payload.get("code") != 0:
            raise BilibiliDataFetchError(str(payload.get("message", "unknown error")))
        return payload.get("data", {}) or {}
