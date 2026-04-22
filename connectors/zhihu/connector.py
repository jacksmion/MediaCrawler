from __future__ import annotations

from typing import Any
from urllib.parse import urlencode

from connectors.base.base_connector import BaseConnector
from connectors.base.models import AuthContext, AuthResult, ConnectorCapability, ConnectorContext, HealthStatus, SearchPage, SearchQuery
from constant import zhihu as zhihu_constant
from model.m_zhihu import ZhihuContent
from runtime.browser.executor import BrowserExecutor
from runtime.http.executor import HttpExecutor
from runtime.http.models import HttpRequest
from runtime.session.service import SessionService

from .errors import ZhihuDataFetchError
from .helpers import ZhihuExtractor, judge_zhihu_url, sign


class ZhihuConnector(BaseConnector):
    """New-style Zhihu connector for incremental platform migration."""

    def __init__(
        self,
        *,
        browser_executor: BrowserExecutor,
        http_executor: HttpExecutor,
        session_service: SessionService,
    ) -> None:
        super().__init__(
            platform_code="zhihu",
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
        self.extractor = ZhihuExtractor()

    async def prepare(self, context: ConnectorContext) -> None:
        self.context = context

    async def authenticate(self, auth_context: AuthContext) -> AuthResult:
        return AuthResult(
            success=False,
            login_type=auth_context.login_type,
            account_id=auth_context.account_id,
            message="Zhihu connector authentication is not migrated yet.",
        )

    async def health_check(self) -> HealthStatus:
        session = await self._refresh_session()
        ok = bool(session.cookie_dict.get("d_c0"))
        return HealthStatus(
            ok=ok,
            platform_code=self.platform_code,
            message="Zhihu session loaded" if ok else "Zhihu session missing d_c0 cookie",
            details={"cookie_keys": sorted(session.cookie_dict.keys())[:10]},
        )

    async def search(self, query: SearchQuery) -> SearchPage:
        params = {
            "gk_version": "gz-gaokao",
            "t": "general",
            "q": query.keyword,
            "correction": 1,
            "offset": (query.page - 1) * query.page_size,
            "limit": query.page_size,
            "filter_fields": "",
            "lc_idx": (query.page - 1) * query.page_size,
            "show_all_topics": 0,
            "search_source": "Filter",
            "time_interval": query.filters.get("search_time", "a_year"),
            "sort": query.filters.get("sort", "default"),
            "vertical": query.filters.get("note_type", "content"),
        }
        payload = await self._get_json("/api/v4/search_v3", params=params)
        contents = self.extractor.extract_contents_from_search(payload)
        items = [content.model_dump() for content in contents]
        paging = payload.get("paging", {}) if isinstance(payload, dict) else {}
        return SearchPage(
            items=items,
            has_more=not bool(paging.get("is_end", not items)),
            next_cursor=str((query.page + 1)) if items else None,
            raw=payload,
            metadata={"request_uri": "/api/v4/search_v3", "keyword": query.keyword, "page": query.page},
        )

    async def fetch_content_detail(self, content_id: str, extra: dict[str, Any] | None = None) -> dict[str, Any]:
        detail_url = self._resolve_detail_url(content_id, extra)
        html = await self._get_text(detail_url)
        content = self._extract_detail_from_html(detail_url, html)
        if content is None:
            raise ZhihuDataFetchError(f"Zhihu detail payload could not be parsed for {detail_url}")
        return {
            "content": content.model_dump(),
            "raw_payload": html,
            "request_uri": detail_url,
            "content_type": content.content_type,
        }

    async def fetch_comments(
        self,
        content_id: str,
        cursor: str | int | None = None,
        limit: int | None = None,
        extra: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        content_type = str((extra or {}).get("content_type") or "")
        if not content_type:
            raise ZhihuDataFetchError("Zhihu comments require content_type in extra payload.")
        content_payload = (extra or {}).get("content")
        content = ZhihuContent.model_validate(content_payload) if isinstance(content_payload, dict) else ZhihuContent(
            content_id=content_id,
            content_type=content_type,
        )
        comments: list[dict[str, Any]] = []
        offset = str(cursor or "")
        max_count = int(limit or 10)
        is_end = False
        raw_pages: list[dict[str, Any]] = []
        while not is_end and len(comments) < max_count:
            page_payload = await self._get_json(
                f"/api/v4/comment_v5/{content_type}s/{content_id}/root_comment",
                params={"order": "score", "offset": offset, "limit": min(10, max_count - len(comments))},
            )
            raw_pages.append(page_payload)
            page_comments = self.extractor.extract_comments(content, page_payload.get("data", []))
            if not page_comments:
                break
            comments.extend([item.model_dump() for item in page_comments[: max_count - len(comments)]])
            paging = page_payload.get("paging", {})
            is_end = bool(paging.get("is_end", True))
            offset = self.extractor.extract_offset(paging)
            if not offset and not is_end:
                break
        return {
            "comments": comments,
            "cursor": offset,
            "has_more": not is_end,
            "request_uri": f"/api/v4/comment_v5/{content_type}s/{content_id}/root_comment",
            "raw_payload": raw_pages,
        }

    async def fetch_creator(self, creator_id: str) -> dict[str, Any]:
        html = await self._get_text(f"/people/{creator_id}")
        creator = self.extractor.extract_creator(creator_id, html)
        if creator is None:
            raise ZhihuDataFetchError(f"Zhihu creator payload could not be parsed for {creator_id}")
        return {
            "creator": creator.model_dump(),
            "raw_payload": html,
            "request_uri": f"/people/{creator_id}",
        }

    async def fetch_creator_contents(
        self,
        creator_id: str,
        cursor: str | int | None = None,
        limit: int | None = None,
    ) -> dict[str, Any]:
        offset = int(cursor or 0)
        page_limit = int(limit or 20)
        payload = await self._get_json(
            f"/api/v4/members/{creator_id}/answers",
            params={
                "include": (
                    "data[*].is_normal,admin_closed_comment,reward_info,is_collapsed,annotation_action,"
                    "annotation_detail,collapse_reason,collapsed_by,suggest_edit,comment_count,can_comment,"
                    "content,editable_content,attachment,voteup_count,reshipment_settings,comment_permission,"
                    "created_time,updated_time,review_info,excerpt,paid_info,reaction_instruction,is_labeled,"
                    "label_info,relationship.is_authorized,voting,is_author,is_thanked,is_nothelp;"
                    "data[*].vessay_info;data[*].author.badge[?(type=best_answerer)].topics;"
                    "data[*].author.vip_info;data[*].question.has_publishing_draft,relationship"
                ),
                "offset": offset,
                "limit": page_limit,
                "order_by": "created",
            },
        )
        contents = self.extractor.extract_content_list_from_creator(payload.get("data", []))
        paging = payload.get("paging", {})
        is_end = bool(paging.get("is_end", True))
        return {
            "items": [content.model_dump() for content in contents],
            "has_more": not is_end,
            "next_cursor": "" if is_end else str(offset + page_limit),
            "raw_payload": payload,
            "request_uri": f"/api/v4/members/{creator_id}/answers",
        }

    async def close(self) -> None:
        await self.browser_executor.close()

    async def _refresh_session(self):
        return await self.session_service.refresh_from_browser(
            self.browser_executor,
            account_id=self.context.account_id if self.context else None,
            proxy=self.context.proxy if self.context else None,
        )

    async def _build_headers(self, final_uri: str) -> dict[str, str]:
        session = await self._refresh_session()
        cookie_dict = session.cookie_dict
        cookie_str = ";".join(f"{key}={value}" for key, value in cookie_dict.items())
        if not cookie_dict.get("d_c0"):
            raise ZhihuDataFetchError("Zhihu session is missing d_c0 cookie; browser state is not ready.")
        signed = sign(final_uri, cookie_str)
        return {
            "accept": "*/*",
            "accept-language": "zh-CN,zh;q=0.9",
            "cookie": cookie_str,
            "priority": "u=1, i",
            "referer": "https://www.zhihu.com/search?q=python&time_interval=a_year&type=content",
            "user-agent": session.user_agent or "",
            "x-api-version": "3.0.91",
            "x-app-za": "OS=Web",
            "x-requested-with": "fetch",
            "x-zse-93": "101_3_3.0",
            "x-zst-81": signed["x-zst-81"],
            "x-zse-96": signed["x-zse-96"],
        }

    async def _get_json(self, uri: str, *, params: dict[str, Any] | None = None) -> dict[str, Any]:
        final_uri = uri
        if params:
            final_uri = f"{uri}?{urlencode(params)}"
        headers = await self._build_headers(final_uri)
        base_url = zhihu_constant.ZHIHU_ZHUANLAN_URL if "/p/" in uri else zhihu_constant.ZHIHU_URL
        response = await self.http_executor.send(
            HttpRequest(
                method="GET",
                url=f"{base_url}{uri}",
                params=params,
                headers=headers,
            )
        )
        if response.status_code == 404:
            return {}
        if response.status_code != 200:
            raise ZhihuDataFetchError(f"Zhihu request failed with status {response.status_code}: {response.text[:300]}")
        payload = response.data if isinstance(response.data, dict) else {}
        if payload.get("error"):
            raise ZhihuDataFetchError(str(payload.get("error", {}).get("message") or payload["error"]))
        return payload

    async def _get_text(self, uri: str) -> str:
        headers = await self._build_headers(uri)
        base_url = zhihu_constant.ZHIHU_ZHUANLAN_URL if "/p/" in uri else zhihu_constant.ZHIHU_URL
        response = await self.http_executor.send(
            HttpRequest(
                method="GET",
                url=f"{base_url}{uri}",
                headers=headers,
            )
        )
        if response.status_code != 200:
            raise ZhihuDataFetchError(f"Zhihu page request failed with status {response.status_code}: {response.text[:300]}")
        return response.text

    @staticmethod
    def _resolve_detail_url(content_id: str, extra: dict[str, Any] | None) -> str:
        detail_url = str((extra or {}).get("detail_url") or "")
        if detail_url:
            if detail_url.startswith("http"):
                if detail_url.startswith(zhihu_constant.ZHIHU_ZHUANLAN_URL):
                    return detail_url.replace(zhihu_constant.ZHIHU_ZHUANLAN_URL, "")
                if detail_url.startswith(zhihu_constant.ZHIHU_URL):
                    return detail_url.replace(zhihu_constant.ZHIHU_URL, "")
            return detail_url
        content_type = str((extra or {}).get("content_type") or "")
        if content_type == zhihu_constant.ARTICLE_NAME:
            return f"/p/{content_id}"
        if content_type == zhihu_constant.VIDEO_NAME:
            return f"/zvideo/{content_id}"
        question_id = str((extra or {}).get("question_id") or "")
        if question_id:
            return f"/question/{question_id}/answer/{content_id}"
        return f"/answer/{content_id}"

    def _extract_detail_from_html(self, detail_url: str, html: str) -> ZhihuContent | None:
        note_type = judge_zhihu_url(f"{zhihu_constant.ZHIHU_URL}{detail_url}")
        if note_type == zhihu_constant.ANSWER_NAME:
            return self.extractor.extract_answer_content_from_html(html)
        if note_type == zhihu_constant.ARTICLE_NAME:
            return self.extractor.extract_article_content_from_html(html)
        if note_type == zhihu_constant.VIDEO_NAME:
            return self.extractor.extract_zvideo_content_from_html(html)
        return None
