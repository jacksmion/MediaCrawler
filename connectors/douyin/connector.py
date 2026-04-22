from __future__ import annotations

import urllib.parse
from typing import Any

from connectors.base.base_connector import BaseConnector
from connectors.base.models import AuthContext, AuthResult, ConnectorCapability, ConnectorContext, HealthStatus, SearchPage, SearchQuery
from .errors import DouyinDataFetchError
from runtime.hybrid.executor import HybridExecutor
from runtime.http.models import HttpRequest
from runtime.session.service import SessionService
from runtime.signing.douyin_signer import DouyinSigner


class DouyinConnector(BaseConnector):
    """New-style Douyin connector scaffold for incremental migration."""

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
            },
        )

    async def fetch_content_detail(self, content_id: str, extra: dict[str, Any] | None = None) -> dict[str, Any]:
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
        return {
            "aweme_detail": detail,
            "raw_payload": payload,
            "request_uri": "/aweme/v1/web/aweme/detail/",
            "request_params": signed_params,
        }

    async def fetch_comments(
        self,
        content_id: str,
        cursor: str | int | None = None,
        limit: int | None = None,
    ) -> dict[str, Any]:
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
            page_comments = payload.get("comments", []) or []
            has_more = payload.get("has_more", 0)
            root_cursor = payload.get("cursor", 0)
            remaining = max_count - len(comments)
            if remaining <= 0:
                break
            page_comments = page_comments[:remaining]
            comments.extend(page_comments)
        return {
            "comments": comments,
            "cursor": root_cursor,
            "has_more": has_more,
            "request_uri": "/aweme/v1/web/comment/list/",
        }

    async def fetch_creator(self, creator_id: str) -> dict[str, Any]:
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
        return {
            "creator": payload,
            "request_uri": "/aweme/v1/web/user/profile/other/",
            "request_params": signed_params,
        }

    async def fetch_creator_contents(
        self,
        creator_id: str,
        cursor: str | int | None = None,
        limit: int | None = None,
    ) -> dict[str, Any]:
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
        return {
            "items": aweme_list,
            "has_more": payload.get("has_more", 0),
            "next_cursor": payload.get("max_cursor", ""),
            "raw_payload": payload,
            "request_uri": "/aweme/v1/web/aweme/post/",
            "request_params": signed_params,
        }

    async def close(self) -> None:
        await self.hybrid_executor.close()
