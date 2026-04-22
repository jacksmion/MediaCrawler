from __future__ import annotations

import json
from typing import Any
from urllib.parse import quote, urlencode

from connectors.base.base_connector import BaseConnector
from connectors.base.models import AuthContext, AuthResult, ConnectorCapability, ConnectorContext, HealthStatus, SearchPage, SearchQuery
from constant import baidu_tieba as tieba_constant
from media_platform.tieba.help import TieBaExtractor
from model.m_baidu_tieba import TiebaCreator, TiebaNote
from runtime.browser.executor import BrowserExecutor
from runtime.session.service import SessionService

from .errors import TiebaDataFetchError


class TiebaConnector(BaseConnector):
    """New-style Tieba connector backed by the bound browser page."""

    def __init__(self, *, browser_executor: BrowserExecutor, session_service: SessionService) -> None:
        super().__init__(
            platform_code="tieba",
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
        self.session_service = session_service
        self.context: ConnectorContext | None = None
        self.extractor = TieBaExtractor()

    async def prepare(self, context: ConnectorContext) -> None:
        self.context = context

    async def authenticate(self, auth_context: AuthContext) -> AuthResult:
        return AuthResult(
            success=False,
            login_type=auth_context.login_type,
            account_id=auth_context.account_id,
            message="Tieba connector authentication is not migrated yet.",
        )

    async def health_check(self) -> HealthStatus:
        session = await self.session_service.refresh_from_browser(
            self.browser_executor,
            account_id=self.context.account_id if self.context else None,
            proxy=self.context.proxy if self.context else None,
        )
        ok = bool(session.cookie_dict.get("BDUSS") or session.cookie_dict.get("STOKEN") or session.cookie_dict.get("PTOKEN"))
        return HealthStatus(
            ok=ok,
            platform_code=self.platform_code,
            message="Tieba session loaded" if ok else "Tieba session missing login cookies",
            details={"cookie_keys": sorted(session.cookie_dict.keys())[:10]},
        )

    async def search(self, query: SearchQuery) -> SearchPage:
        full_url = (
            f"{tieba_constant.TIEBA_URL}/f/search/res?"
            f"{urlencode({'ie': 'utf-8', 'qw': query.keyword, 'rn': query.page_size, 'pn': query.page, 'sm': query.filters.get('sort', '1'), 'only_thread': query.filters.get('note_type', '0')})}"
        )
        html = await self._goto_and_content(full_url)
        notes = self.extractor.extract_search_note_list(html)
        return SearchPage(
            items=[note.model_dump() for note in notes],
            has_more=bool(notes),
            next_cursor=str(query.page + 1) if notes else None,
            raw={"html": html},
            metadata={"request_url": full_url},
        )

    async def fetch_content_detail(self, content_id: str, extra: dict[str, Any] | None = None) -> dict[str, Any]:
        detail_url = str((extra or {}).get("detail_url") or f"{tieba_constant.TIEBA_URL}/p/{content_id}")
        html = await self._goto_and_content(detail_url)
        note = self.extractor.extract_note_detail(html)
        if not note:
            raise TiebaDataFetchError(f"Tieba detail payload could not be parsed for {detail_url}")
        return {
            "note": note.model_dump(),
            "raw_payload": html,
            "request_uri": detail_url,
        }

    async def fetch_comments(
        self,
        content_id: str,
        cursor: str | int | None = None,
        limit: int | None = None,
        extra: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        note_payload = (extra or {}).get("note")
        if not isinstance(note_payload, dict):
            raise TiebaDataFetchError("Tieba comments require note detail in extra payload.")
        note = TiebaNote.model_validate(note_payload)
        max_count = int(limit or 10)
        current_page = int(cursor or 1)
        comments: list[dict[str, Any]] = []
        raw_pages: list[dict[str, Any]] = []
        while note.total_replay_page >= current_page and len(comments) < max_count:
            comment_url = f"{tieba_constant.TIEBA_URL}/p/{note.note_id}?pn={current_page}"
            html = await self._goto_and_content(comment_url)
            page_comments = self.extractor.extract_tieba_note_parment_comments(html, note_id=note.note_id)
            if not page_comments:
                break
            remaining = max_count - len(comments)
            comments.extend([item.model_dump() for item in page_comments[:remaining]])
            raw_pages.append({"page": current_page, "html": html})
            current_page += 1
        return {
            "comments": comments,
            "cursor": current_page,
            "has_more": current_page <= note.total_replay_page and len(comments) < max_count,
            "request_uri": f"/p/{note.note_id}",
            "raw_payload": raw_pages,
        }

    async def fetch_creator(self, creator_id: str) -> dict[str, Any]:
        creator_url = str(creator_id)
        html = await self._goto_and_content(creator_url)
        creator = self.extractor.extract_creator_info(html)
        if not creator:
            raise TiebaDataFetchError(f"Tieba creator payload could not be parsed for {creator_url}")
        return {
            "creator": creator.model_dump(),
            "raw_payload": html,
            "request_uri": creator_url,
        }

    async def fetch_creator_contents(
        self,
        creator_id: str,
        cursor: str | int | None = None,
        limit: int | None = None,
    ) -> dict[str, Any]:
        creator_url = str(creator_id)
        if str(cursor or "") in ("", "0"):
            html = await self._goto_and_content(creator_url)
            thread_ids = self.extractor.extract_tieba_thread_id_list_from_creator_page(html)
            thread_ids = thread_ids[: int(limit or len(thread_ids) or 20)]
            items: list[dict[str, Any]] = []
            for thread_id in thread_ids:
                detail = await self.fetch_content_detail(thread_id)
                items.append(detail["note"])
            return {
                "items": items,
                "has_more": False,
                "next_cursor": "",
                "raw_payload": {"html": html, "thread_ids": thread_ids},
                "request_uri": creator_url,
            }

        page_number = int(cursor)
        user_name = str((await self.fetch_creator(creator_url))["creator"]["user_name"])
        api_url = (
            f"{tieba_constant.TIEBA_URL}/home/get/getthread?"
            f"un={quote(user_name)}&pn={page_number}&id=utf-8"
        )
        await self.browser_executor.page.goto(api_url, wait_until="domcontentloaded")
        body_text = await self.browser_executor.page.evaluate("() => document.body.innerText")
        try:
            payload = json.loads(body_text)
        except json.JSONDecodeError as exc:
            raise TiebaDataFetchError(f"Tieba creator contents JSON parse failed: {exc}") from exc
        notes = payload.get("data", {}).get("thread_list", [])
        thread_ids = [str(item.get("thread_id", "")) for item in notes if item.get("thread_id")]
        thread_ids = thread_ids[: int(limit or len(thread_ids) or 20)]
        items = []
        for thread_id in thread_ids:
            detail = await self.fetch_content_detail(thread_id)
            items.append(detail["note"])
        return {
            "items": items,
            "has_more": bool(payload.get("data", {}).get("has_more")),
            "next_cursor": str(page_number + 1) if payload.get("data", {}).get("has_more") else "",
            "raw_payload": payload,
            "request_uri": api_url,
        }

    async def close(self) -> None:
        await self.browser_executor.close()

    async def _goto_and_content(self, url: str) -> str:
        if self.browser_executor.page is None:
            raise TiebaDataFetchError("Tieba browser page is not bound.")
        try:
            await self.browser_executor.page.goto(url, wait_until="domcontentloaded")
            return await self.browser_executor.page.content()
        except Exception as exc:
            raise TiebaDataFetchError(f"Tieba page navigation failed for {url}: {exc}") from exc
