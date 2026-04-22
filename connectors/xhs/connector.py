from __future__ import annotations

from typing import Any

from connectors.base.base_connector import BaseConnector
from connectors.base.models import AuthContext, AuthResult, ConnectorCapability, ConnectorContext, HealthStatus, SearchPage, SearchQuery
from media_platform.xhs.field import SearchSortType
from media_platform.xhs.help import parse_creator_info_from_url
from runtime.browser.executor import BrowserExecutor
from runtime.session.service import SessionService

from .errors import XhsDataFetchError


class XhsConnector(BaseConnector):
    """New-style Xiaohongshu connector that keeps browser-side signing intact."""

    def __init__(
        self,
        *,
        browser_executor: BrowserExecutor,
        session_service: SessionService,
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
        self.legacy_client = legacy_client
        self.context: ConnectorContext | None = None

    async def prepare(self, context: ConnectorContext) -> None:
        self.context = context

    async def authenticate(self, auth_context: AuthContext) -> AuthResult:
        return AuthResult(
            success=False,
            login_type=auth_context.login_type,
            account_id=auth_context.account_id,
            message="XHS connector authentication is not migrated yet.",
        )

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
        return SearchPage(
            items=items,
            has_more=bool(response.get("has_more", False)),
            next_cursor=str(query.page + 1) if response.get("has_more", False) else None,
            raw=response,
            metadata={"request_uri": "/api/sns/web/v1/search/notes", "keyword": query.keyword, "page": query.page},
        )

    async def fetch_content_detail(self, content_id: str, extra: dict[str, Any] | None = None) -> dict[str, Any]:
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
        return {
            "note": note_detail,
            "raw_payload": note_detail,
            "request_uri": "/api/sns/web/v1/feed",
        }

    async def fetch_comments(
        self,
        content_id: str,
        cursor: str | int | None = None,
        limit: int | None = None,
        extra: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
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
        return {
            "comments": comments[: int(limit or len(comments) or 10)],
            "cursor": cursor or "",
            "has_more": False,
            "request_uri": "/api/sns/web/v2/comment/page",
            "raw_payload": comments,
        }

    async def fetch_creator(self, creator_id: str) -> dict[str, Any]:
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
        return {
            "creator": creator,
            "raw_payload": creator,
            "request_uri": f"/user/profile/{parsed.user_id}",
            "creator_id": parsed.user_id,
            "xsec_token": parsed.xsec_token,
            "xsec_source": parsed.xsec_source,
        }

    async def fetch_creator_contents(
        self,
        creator_id: str,
        cursor: str | int | None = None,
        limit: int | None = None,
    ) -> dict[str, Any]:
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
        return {
            "items": items[: int(limit or len(items) or 30)],
            "has_more": bool(response.get("has_more", False)),
            "next_cursor": str(response.get("cursor") or ""),
            "raw_payload": response,
            "request_uri": "/api/sns/web/v1/user_posted",
            "creator_id": parsed.user_id,
            "xsec_token": parsed.xsec_token,
            "xsec_source": parsed.xsec_source,
        }

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
