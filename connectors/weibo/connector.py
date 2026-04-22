from __future__ import annotations

import json
from typing import Any
from urllib.parse import parse_qs, unquote

from connectors.base.base_connector import BaseConnector
from connectors.base.models import AuthContext, AuthResult, ConnectorCapability, ConnectorContext, HealthStatus, SearchPage, SearchQuery
from media_platform.weibo.field import SearchType
from media_platform.weibo.help import filter_search_result_card
from runtime.browser.executor import BrowserExecutor
from runtime.http.executor import HttpExecutor
from runtime.http.models import HttpRequest
from runtime.session.service import SessionService

from .errors import WeiboDataFetchError


class WeiboConnector(BaseConnector):
    """New-style Weibo connector for incremental platform migration."""

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
        return SearchPage(
            items=items,
            has_more=bool(items),
            next_cursor=str(query.page + 1) if items else None,
            raw=payload,
            metadata={"request_uri": "/api/container/getIndex", "keyword": query.keyword, "page": query.page},
        )

    async def fetch_content_detail(self, content_id: str, extra: dict[str, Any] | None = None) -> dict[str, Any]:
        response = await self._request_text(f"{self.host}/detail/{content_id}")
        match = __import__("re").search(r'var \$render_data = (\[.*?\])\[0\]', response, __import__("re").DOTALL)
        if not match:
            raise WeiboDataFetchError(f"Weibo detail payload could not be parsed for {content_id}")
        payload = json.loads(match.group(1))
        note = {"mblog": payload[0].get("status", {})}
        return {
            "note": note,
            "raw_payload": response,
            "request_uri": f"/detail/{content_id}",
        }

    async def fetch_comments(
        self,
        content_id: str,
        cursor: str | int | None = None,
        limit: int | None = None,
        extra: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
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
        return {
            "comments": comments,
            "cursor": max_id,
            "has_more": not is_end,
            "request_uri": "/comments/hotflow",
            "raw_payload": raw_pages,
        }

    async def fetch_creator(self, creator_id: str) -> dict[str, Any]:
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
        return {
            "creator": user_info,
            "raw_payload": payload,
            "request_uri": "/api/container/getIndex",
        }

    async def fetch_creator_contents(
        self,
        creator_id: str,
        cursor: str | int | None = None,
        limit: int | None = None,
    ) -> dict[str, Any]:
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
        return {
            "items": items[: int(limit or len(items) or 10)],
            "has_more": bool(next_since and next_since != "0"),
            "next_cursor": f"{container_id}|{next_since}" if next_since and next_since != "0" else "",
            "raw_payload": payload,
            "request_uri": "/api/container/getIndex",
        }

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
