from __future__ import annotations

import json
from typing import Any
from urllib.parse import quote, urlencode

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
from constant import baidu_tieba as tieba_constant
from model.m_baidu_tieba import TiebaCreator, TiebaNote
from schemas.tasks.models import CrawlJobEvent, CrawlTask
from schemas.tasks.runtime import PlatformTaskRequest
from runtime.browser.executor import BrowserExecutor
from runtime.session.service import SessionService

from .errors import TiebaDataFetchError
from .helpers import TieBaExtractor
from .normalizer import normalize_tieba_note, normalize_tieba_notes


class TiebaConnector(BaseConnector):
    """New-style Tieba connector backed by the bound browser page."""
    short_code = "tb"
    source_name = "legacy_tieba_crawler"
    handled_exceptions = (TiebaDataFetchError,)

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

    def use_generic_success_handling(self) -> bool:
        return True

    def build_request(self, task: CrawlTask, job_id: str) -> PlatformTaskRequest:
        params = task.params or {}
        if task.task_type == "search":
            return PlatformTaskRequest(job_id=job_id, platform_code=self.platform_code, task_kind="search", payload={"keyword": str(params["keyword"]), "page": int(params.get("page", 1)), "page_size": int(params.get("page_size", 10))})
        if task.task_type == "detail":
            return PlatformTaskRequest(job_id=job_id, platform_code=self.platform_code, task_kind="detail", payload={"content_id": str(params.get("note_id") or ""), "extra": {"detail_url": str(params.get("detail_url") or "")}})
        if task.task_type == "comments":
            note_payload = params.get("note")
            note = TiebaNote.model_validate(note_payload) if isinstance(note_payload, dict) else None
            return PlatformTaskRequest(job_id=job_id, platform_code=self.platform_code, task_kind="comments", payload={"content_id": note.note_id if note else str(params.get("note_id") or ""), "cursor": params.get("cursor", 1), "limit": int(params.get("limit", 10)), "extra": {"note": note.model_dump() if note else note_payload}})
        if task.task_type == "creator":
            return PlatformTaskRequest(job_id=job_id, platform_code=self.platform_code, task_kind="creator", payload={"creator_id": str(params.get("creator_url") or "")})
        if task.task_type == "creator_contents":
            return PlatformTaskRequest(job_id=job_id, platform_code=self.platform_code, task_kind="creator_contents", payload={"creator_id": str(params.get("creator_url") or ""), "cursor": str(params.get("cursor", "")), "limit": int(params.get("limit", 20))})
        raise ValueError(f"Unsupported Tieba task type: {task.task_type}")

    def plan_requirement(self, requirement: Any) -> list[CrawlTask]:
        if requirement.mode == "search":
            tasks: list[CrawlTask] = []
            keywords = [keyword.strip() for keyword in requirement.keywords if keyword.strip()]
            if not keywords:
                raise ValueError("Tieba search requirement requires at least one keyword")
            for keyword in keywords:
                for page in range(requirement.start_page, requirement.start_page + requirement.max_pages):
                    tasks.append(self.new_task(task_type="search", params={"keyword": keyword, "page": page, "page_size": requirement.page_size}))
            return tasks
        if requirement.mode == "detail":
            note_ids = [note_id.strip() for note_id in requirement.note_ids if note_id.strip()]
            if not note_ids:
                raise ValueError("Tieba detail requirement requires at least one note id")
            return [self.new_task(task_type="detail", params={"note_id": note_id}) for note_id in note_ids]
        if requirement.mode == "creator":
            tasks: list[CrawlTask] = []
            creator_urls = [creator_url.strip() for creator_url in requirement.creator_urls if creator_url.strip()]
            if not creator_urls:
                raise ValueError("Tieba creator requirement requires at least one creator url")
            for creator_url in creator_urls:
                tasks.append(self.new_task(task_type="creator", params={"creator_url": creator_url}))
                for page in range(requirement.creator_max_pages):
                    cursor = "" if page == 0 else str(page + 1)
                    tasks.append(self.new_task(task_type="creator_contents", params={"creator_url": creator_url, "cursor": cursor, "limit": requirement.creator_contents_limit}))
            return tasks
        raise ValueError(f"Unsupported Tieba requirement mode: {requirement.mode}")

    def classify_error(self, message: str) -> str:
        lowered = message.lower()
        if "browser page" in lowered:
            return "session_not_ready"
        if "parse" in lowered:
            return "parse_failed"
        if "navigation" in lowered:
            return "navigation_failed"
        return "unknown_error"

    def build_failure_event(self, *, task: CrawlTask, job_id: str, error_message: str, error_code: str) -> CrawlJobEvent:
        params = task.params or {}
        details: dict[str, Any] = {"risk_type": error_code}
        if task.task_type == "search":
            details.update({"keyword": params.get("keyword"), "page": params.get("page")})
        elif task.task_type in {"detail", "comments"}:
            details["note_id"] = params.get("note_id") or (params.get("note") or {}).get("note_id")
        else:
            details.update({"creator_url": params.get("creator_url"), "cursor": params.get("cursor", "")})
        return CrawlJobEvent(job_id=job_id, event_type=f"{task.task_type}_failed", message=error_message, details=details)

    def collect_targets_from_results(self, results: list[dict[str, Any]]) -> list[TiebaNote]:
        targets: list[TiebaNote] = []
        for result in results:
            note = result.get("note")
            if isinstance(note, TiebaNote):
                targets.append(note)
            elif isinstance(note, dict):
                targets.append(TiebaNote.model_validate(note))
            for item in result.get("items", []):
                if isinstance(item, dict):
                    targets.append(TiebaNote.model_validate(item))
        return targets

    def collect_targets_from_requirement(self, requirement: Any) -> list[TiebaNote]:
        targets: list[TiebaNote] = []
        for note_id in requirement.note_ids:
            if not note_id.strip():
                continue
            targets.append(TiebaNote(note_id=note_id.strip(), title="", desc="", note_url=f"https://tieba.baidu.com/p/{note_id.strip()}", tieba_name="", tieba_link=""))
        return targets

    def build_detail_task(self, target: TiebaNote, index: int) -> CrawlTask:
        return CrawlTask(task_id=f"tb-followup-detail-{index}", platform_code=self.platform_code, task_type="detail", status="planned", params={"note_id": target.note_id, "detail_url": target.note_url})

    def build_comments_task(self, target: TiebaNote, index: int, comment_limit: int | None) -> CrawlTask:
        return CrawlTask(task_id=f"tb-followup-comments-{index}", platform_code=self.platform_code, task_type="comments", status="planned", params={"note_id": target.note_id, "note": target.model_dump(), "limit": comment_limit})

    def dedupe_targets(self, targets: list[TiebaNote]) -> list[TiebaNote]:
        unique: list[TiebaNote] = []
        seen: set[str] = set()
        for target in targets:
            if target.note_id in seen:
                continue
            seen.add(target.note_id)
            unique.append(target)
        return unique

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
        normalized_records = normalize_tieba_notes(notes)
        return SearchPage(
            items=[note.model_dump() for note in notes],
            has_more=bool(notes),
            next_cursor=str(query.page + 1) if notes else None,
            raw={"html": html},
            metadata={
                "request_url": full_url,
                "outcome": {
                    "normalized_records": normalized_records,
                    "raw_record": {
                        "record_type": "search",
                        "source_uri": full_url,
                        "request_meta": {"keyword": query.keyword, "page": query.page},
                        "response_body": {"html": html},
                        "metadata": {"bridge": "tieba_connector", "normalized_count": len(normalized_records)},
                    },
                    "events": [
                        {
                            "event_type": "search_page_succeeded",
                            "message": "Tieba bridge search page succeeded",
                            "details": {"keyword": query.keyword, "page": query.page, "items_count": len(notes)},
                        }
                    ],
                    "response_payload": {
                        "items": [note.model_dump() for note in notes],
                        "normalized_records": normalized_records,
                        "has_more": bool(notes),
                        "next_cursor": str(query.page + 1) if notes else None,
                    },
                },
            },
        )

    async def fetch_content_detail(self, content_id: str, extra: dict[str, Any] | None = None) -> ContentDetailResult:
        detail_url = str((extra or {}).get("detail_url") or f"{tieba_constant.TIEBA_URL}/p/{content_id}")
        html = await self._goto_and_content(detail_url)
        note = self.extractor.extract_note_detail(html)
        if not note:
            raise TiebaDataFetchError(f"Tieba detail payload could not be parsed for {detail_url}")
        normalized_record = normalize_tieba_note(note)
        return ContentDetailResult(
            item=note.model_dump(),
            item_key="note",
            raw_payload=html,
            request_uri=detail_url,
            metadata={
                "outcome": {
                    "normalized_records": [normalized_record],
                    "raw_record": {
                        "record_type": "detail",
                        "source_uri": detail_url,
                        "request_meta": {"note_id": content_id},
                        "response_body": html,
                        "metadata": {"bridge": "tieba_connector"},
                    },
                    "events": [
                        {
                            "event_type": "detail_succeeded",
                            "message": "Tieba bridge detail succeeded",
                            "details": {"note_id": content_id},
                        }
                    ],
                    "response_payload": {"note": note.model_dump()},
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
        request_uri = f"/p/{note.note_id}"
        has_more = current_page <= note.total_replay_page and len(comments) < max_count
        return CommentsPage(
            comments=comments,
            next_cursor=current_page,
            has_more=has_more,
            request_uri=request_uri,
            raw_payload=raw_pages,
            metadata={
                "outcome": {
                    "raw_record": {
                        "record_type": "comments",
                        "source_uri": request_uri,
                        "request_meta": {"note_id": note.note_id, "cursor": cursor or 1, "limit": max_count},
                        "response_body": raw_pages,
                        "metadata": {"bridge": "tieba_connector", "comment_count": len(comments)},
                    },
                    "events": [
                        {
                            "event_type": "comments_succeeded",
                            "message": "Tieba bridge comments succeeded",
                            "details": {"note_id": note.note_id, "comment_count": len(comments)},
                        }
                    ],
                    "response_payload": {
                        "comments": comments,
                        "cursor": current_page,
                        "has_more": has_more,
                    },
                }
            },
        )

    async def fetch_creator(self, creator_id: str) -> CreatorResult:
        creator_url = str(creator_id)
        html = await self._goto_and_content(creator_url)
        creator = self.extractor.extract_creator_info(html)
        if not creator:
            raise TiebaDataFetchError(f"Tieba creator payload could not be parsed for {creator_url}")
        return CreatorResult(
            creator=creator.model_dump(),
            raw_payload=html,
            request_uri=creator_url,
            metadata={
                "outcome": {
                    "raw_record": {
                        "record_type": "creator",
                        "source_uri": creator_url,
                        "request_meta": {"creator_url": creator_url},
                        "response_body": html,
                        "metadata": {"bridge": "tieba_connector"},
                    },
                    "events": [
                        {
                            "event_type": "creator_succeeded",
                            "message": "Tieba bridge creator succeeded",
                            "details": {"creator_url": creator_url},
                        }
                    ],
                    "response_payload": {"creator": creator.model_dump()},
                }
            },
        )

    async def fetch_creator_contents(
        self,
        creator_id: str,
        cursor: str | int | None = None,
        limit: int | None = None,
    ) -> CreatorContentsPage:
        creator_url = str(creator_id)
        if str(cursor or "") in ("", "0"):
            html = await self._goto_and_content(creator_url)
            thread_ids = self.extractor.extract_tieba_thread_id_list_from_creator_page(html)
            thread_ids = thread_ids[: int(limit or len(thread_ids) or 20)]
            items: list[dict[str, Any]] = []
            for thread_id in thread_ids:
                detail = await self.fetch_content_detail(thread_id)
                items.append(detail.item)
            normalized_records = normalize_tieba_notes([TiebaNote.model_validate(item) for item in items])
            return CreatorContentsPage(
                items=items,
                has_more=False,
                next_cursor="",
                raw_payload={"html": html, "thread_ids": thread_ids},
                request_uri=creator_url,
                metadata={
                    "outcome": {
                        "normalized_records": normalized_records,
                        "raw_record": {
                            "record_type": "creator_contents",
                            "source_uri": creator_url,
                            "request_meta": {"creator_url": creator_url, "cursor": str(cursor or "")},
                            "response_body": {"html": html, "thread_ids": thread_ids},
                            "metadata": {"bridge": "tieba_connector", "normalized_count": len(normalized_records)},
                        },
                        "events": [
                            {
                                "event_type": "creator_contents_succeeded",
                                "message": "Tieba bridge creator contents succeeded",
                                "details": {"creator_url": creator_url, "items_count": len(items)},
                            }
                        ],
                        "response_payload": {
                            "items": items,
                            "normalized_records": normalized_records,
                            "has_more": False,
                            "next_cursor": "",
                        },
                    }
                },
            )

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
            items.append(detail.item)
        has_more = bool(payload.get("data", {}).get("has_more"))
        next_cursor = str(page_number + 1) if has_more else ""
        normalized_records = normalize_tieba_notes([TiebaNote.model_validate(item) for item in items])
        return CreatorContentsPage(
            items=items,
            has_more=has_more,
            next_cursor=next_cursor,
            raw_payload=payload,
            request_uri=api_url,
            metadata={
                "outcome": {
                    "normalized_records": normalized_records,
                    "raw_record": {
                        "record_type": "creator_contents",
                        "source_uri": api_url,
                        "request_meta": {"creator_url": creator_url, "cursor": str(cursor or "")},
                        "response_body": payload,
                        "metadata": {"bridge": "tieba_connector", "normalized_count": len(normalized_records)},
                    },
                    "events": [
                        {
                            "event_type": "creator_contents_succeeded",
                            "message": "Tieba bridge creator contents succeeded",
                            "details": {"creator_url": creator_url, "items_count": len(items)},
                        }
                    ],
                    "response_payload": {
                        "items": items,
                        "normalized_records": normalized_records,
                        "has_more": has_more,
                        "next_cursor": next_cursor,
                    },
                }
            },
        )

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


def build_tieba_connector_from_legacy(crawler) -> TiebaConnector:
    browser_executor = BrowserExecutor()
    browser_executor.bind(
        context=getattr(crawler, "browser_context", None),
        page=getattr(crawler, "context_page", None),
        browser_type="chromium",
        cdp_enabled=bool(getattr(crawler, "cdp_manager", None)),
        headless=False,
    )
    session_service = SessionService(platform_code="tieba")
    return TiebaConnector(
        browser_executor=browser_executor,
        session_service=session_service,
    )
