from __future__ import annotations

from typing import Any
from urllib.parse import urlencode

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
from constant import zhihu as zhihu_constant
from model.m_zhihu import ZhihuContent
from schemas.tasks.models import CrawlJobEvent, CrawlTask
from schemas.tasks.runtime import PlatformTaskRequest
from runtime.browser.executor import BrowserExecutor
from runtime.http.executor import HttpExecutor
from runtime.http.models import HttpRequest
from runtime.session.service import SessionService

from .errors import ZhihuDataFetchError
from .helpers import ZhihuExtractor, judge_zhihu_url, sign
from .normalizer import normalize_zhihu_content, normalize_zhihu_contents


class ZhihuConnector(BaseConnector):
    """New-style Zhihu connector for incremental platform migration."""
    short_code = "zh"
    source_name = "legacy_zhihu_crawler"
    handled_exceptions = (ZhihuDataFetchError,)

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

    def use_generic_success_handling(self) -> bool:
        return True

    def build_request(self, task: CrawlTask, job_id: str) -> PlatformTaskRequest:
        params = task.params or {}
        task_type = task.task_type
        if task_type == "search":
            return PlatformTaskRequest(job_id=job_id, platform_code=self.platform_code, task_kind="search", payload={"keyword": str(params["keyword"]), "page": int(params.get("page", 1)), "page_size": int(params.get("page_size", 20))})
        if task_type == "detail":
            note_url = str(params.get("note_url") or "").split("?")[0]
            if not note_url:
                raise ValueError("Zhihu detail task requires note_url")
            content_id, content_type, question_id = self._parse_note_url(note_url)
            return PlatformTaskRequest(job_id=job_id, platform_code=self.platform_code, task_kind="detail", payload={"content_id": content_id, "extra": {"content_type": content_type, "detail_url": note_url, "question_id": question_id}})
        if task_type == "comments":
            content_payload = params.get("content")
            if not isinstance(content_payload, dict):
                raise ValueError("Zhihu comments task requires content payload")
            content = ZhihuContent.model_validate(content_payload)
            return PlatformTaskRequest(job_id=job_id, platform_code=self.platform_code, task_kind="comments", payload={"content_id": content.content_id, "cursor": self._optional_str(params.get("cursor")) or "", "limit": self._optional_int(params.get("limit")) or 10, "extra": {"content_type": content.content_type, "content": content.model_dump()}})
        if task_type == "creator":
            creator_url = str(params.get("creator_url") or "")
            if not creator_url:
                raise ValueError("Zhihu creator task requires creator_url")
            return PlatformTaskRequest(job_id=job_id, platform_code=self.platform_code, task_kind="creator", payload={"creator_id": self._parse_creator_url(creator_url)})
        if task_type == "creator_contents":
            creator_url = str(params.get("creator_url") or "")
            if not creator_url:
                raise ValueError("Zhihu creator_contents task requires creator_url")
            return PlatformTaskRequest(job_id=job_id, platform_code=self.platform_code, task_kind="creator_contents", payload={"creator_id": self._parse_creator_url(creator_url), "cursor": self._optional_str(params.get("cursor")) or "", "limit": int(params.get("limit", 20))})
        raise ValueError(f"Unsupported Zhihu task type: {task_type}")

    def plan_requirement(self, requirement: Any) -> list[CrawlTask]:
        if requirement.mode == "search":
            tasks: list[CrawlTask] = []
            keywords = [keyword.strip() for keyword in requirement.keywords if keyword.strip()]
            if not keywords:
                raise ValueError("Zhihu search requirement requires at least one keyword")
            for keyword in keywords:
                for page in range(requirement.start_page, requirement.start_page + requirement.max_pages):
                    tasks.append(self.new_task(task_type="search", params={"keyword": keyword, "page": page, "page_size": requirement.page_size}))
            return tasks
        if requirement.mode == "detail":
            note_urls = [note_url.strip() for note_url in requirement.note_urls if note_url.strip()]
            if not note_urls:
                raise ValueError("Zhihu detail requirement requires at least one note url")
            return [self.new_task(task_type="detail", params={"note_url": note_url}) for note_url in note_urls]
        if requirement.mode == "creator":
            tasks: list[CrawlTask] = []
            creator_urls = [creator_url.strip() for creator_url in requirement.creator_urls if creator_url.strip()]
            if not creator_urls:
                raise ValueError("Zhihu creator requirement requires at least one creator url")
            for creator_url in creator_urls:
                tasks.append(self.new_task(task_type="creator", params={"creator_url": creator_url}))
                for _ in range(requirement.creator_max_pages):
                    tasks.append(self.new_task(task_type="creator_contents", params={"creator_url": creator_url, "cursor": "", "limit": requirement.creator_contents_limit}))
            return tasks
        raise ValueError(f"Unsupported Zhihu requirement mode: {requirement.mode}")

    def classify_error(self, message: str) -> str:
        lowered = message.lower()
        if "d_c0" in lowered or "browser state" in lowered:
            return "session_not_ready"
        if "status 4" in lowered or "status 5" in lowered:
            return "http_error"
        if "parse" in lowered:
            return "parse_failed"
        return "unknown_error"

    def build_failure_event(self, *, task: CrawlTask, job_id: str, error_message: str, error_code: str) -> CrawlJobEvent:
        params = task.params or {}
        details: dict[str, Any] = {"risk_type": error_code}
        if task.task_type == "search":
            details.update({"keyword": params.get("keyword"), "page": params.get("page")})
        elif task.task_type == "detail":
            note_url = str(params.get("note_url") or "").split("?")[0]
            if note_url:
                content_id, content_type, _ = self._parse_note_url(note_url)
                details.update({"content_id": content_id, "content_type": content_type})
        elif task.task_type == "comments":
            content = params.get("content") or {}
            if isinstance(content, dict):
                details.update({"content_id": content.get("content_id"), "content_type": content.get("content_type")})
        elif task.task_type == "creator":
            details["creator_id"] = self._parse_creator_url(str(params.get("creator_url") or ""))
        elif task.task_type == "creator_contents":
            details.update({"creator_id": self._parse_creator_url(str(params.get("creator_url") or "")), "cursor": params.get("cursor", "")})
        return CrawlJobEvent(job_id=job_id, event_type=f"{task.task_type}_failed", message=error_message, details=details)

    def collect_targets_from_results(self, results: list[dict[str, Any]]) -> list[ZhihuContent]:
        contents: list[ZhihuContent] = []
        for result in results:
            content = result.get("content")
            if isinstance(content, ZhihuContent):
                contents.append(content)
            elif isinstance(content, dict):
                contents.append(ZhihuContent.model_validate(content))
            for item in result.get("items", []):
                if isinstance(item, dict):
                    contents.append(ZhihuContent.model_validate(item))
        return contents

    def collect_targets_from_requirement(self, requirement: Any) -> list[ZhihuContent]:
        return [self._content_from_url(note_url) for note_url in requirement.note_urls if note_url.strip()]

    def build_detail_task(self, target: ZhihuContent, index: int) -> CrawlTask:
        return CrawlTask(task_id=f"zh-followup-detail-{index}", platform_code=self.platform_code, task_type="detail", status="planned", params={"note_url": target.content_url})

    def build_comments_task(self, target: ZhihuContent, index: int, comment_limit: int | None) -> CrawlTask:
        return CrawlTask(task_id=f"zh-followup-comments-{index}", platform_code=self.platform_code, task_type="comments", status="planned", params={"content": target.model_dump(), "cursor": "", "limit": comment_limit})

    def dedupe_targets(self, targets: list[ZhihuContent]) -> list[ZhihuContent]:
        unique: list[ZhihuContent] = []
        seen: set[tuple[str, str]] = set()
        for target in targets:
            key = (target.content_type, target.content_id)
            if key in seen:
                continue
            seen.add(key)
            unique.append(target)
        return unique

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
        normalized_records = normalize_zhihu_contents(contents)
        return SearchPage(
            items=items,
            has_more=not bool(paging.get("is_end", not items)),
            next_cursor=str((query.page + 1)) if items else None,
            raw=payload,
            metadata={
                "request_uri": "/api/v4/search_v3",
                "keyword": query.keyword,
                "page": query.page,
                "outcome": {
                    "normalized_records": normalized_records,
                    "raw_record": {
                        "record_type": "search",
                        "source_uri": "/api/v4/search_v3",
                        "request_meta": {"keyword": query.keyword, "page": query.page},
                        "response_body": payload,
                        "metadata": {"bridge": "zhihu_connector", "normalized_count": len(normalized_records)},
                    },
                    "events": [
                        {
                            "event_type": "search_page_succeeded",
                            "message": "Zhihu bridge search page succeeded",
                            "details": {"keyword": query.keyword, "page": query.page, "items_count": len(items)},
                        }
                    ],
                    "response_payload": {
                        "items": items,
                        "normalized_records": normalized_records,
                        "has_more": not bool(paging.get("is_end", not items)),
                        "next_cursor": str((query.page + 1)) if items else None,
                        "raw": payload,
                    },
                },
            },
        )

    async def fetch_content_detail(self, content_id: str, extra: dict[str, Any] | None = None) -> ContentDetailResult:
        detail_url = self._resolve_detail_url(content_id, extra)
        html = await self._get_text(detail_url)
        content = self._extract_detail_from_html(detail_url, html)
        if content is None:
            raise ZhihuDataFetchError(f"Zhihu detail payload could not be parsed for {detail_url}")
        normalized_record = normalize_zhihu_content(content)
        return ContentDetailResult(
            item=content.model_dump(),
            item_key="content",
            raw_payload=html,
            request_uri=detail_url,
            metadata={
                "outcome": {
                    "normalized_records": [normalized_record],
                    "raw_record": {
                        "record_type": "detail",
                        "source_uri": detail_url,
                        "request_meta": {"content_id": content_id},
                        "response_body": html,
                        "metadata": {"bridge": "zhihu_connector", "content_type": content.content_type},
                    },
                    "events": [
                        {
                            "event_type": "detail_succeeded",
                            "message": "Zhihu bridge detail succeeded",
                            "details": {"content_id": content_id, "content_type": content.content_type},
                        }
                    ],
                    "response_payload": {"content": content.model_dump()},
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
        request_uri = f"/api/v4/comment_v5/{content_type}s/{content_id}/root_comment"
        return CommentsPage(
            comments=comments,
            next_cursor=offset,
            has_more=not is_end,
            request_uri=request_uri,
            raw_payload=raw_pages,
            metadata={
                "outcome": {
                    "raw_record": {
                        "record_type": "comments",
                        "source_uri": request_uri,
                        "request_meta": {"content_id": content_id, "content_type": content_type},
                        "response_body": raw_pages,
                        "metadata": {"bridge": "zhihu_connector", "comment_count": len(comments)},
                    },
                    "events": [
                        {
                            "event_type": "comments_succeeded",
                            "message": "Zhihu bridge comments succeeded",
                            "details": {"content_id": content_id, "comment_count": len(comments)},
                        }
                    ],
                    "response_payload": {
                        "comments": comments,
                        "cursor": offset,
                        "has_more": not is_end,
                    },
                }
            },
        )

    async def fetch_creator(self, creator_id: str) -> CreatorResult:
        html = await self._get_text(f"/people/{creator_id}")
        creator = self.extractor.extract_creator(creator_id, html)
        if creator is None:
            raise ZhihuDataFetchError(f"Zhihu creator payload could not be parsed for {creator_id}")
        return CreatorResult(
            creator=creator.model_dump(),
            raw_payload=html,
            request_uri=f"/people/{creator_id}",
            metadata={
                "outcome": {
                    "raw_record": {
                        "record_type": "creator",
                        "source_uri": f"/people/{creator_id}",
                        "request_meta": {"creator_id": creator_id},
                        "response_body": html,
                        "metadata": {"bridge": "zhihu_connector"},
                    },
                    "events": [
                        {
                            "event_type": "creator_succeeded",
                            "message": "Zhihu bridge creator succeeded",
                            "details": {"creator_id": creator_id},
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
        items = [content.model_dump() for content in contents]
        normalized_records = normalize_zhihu_contents(contents)
        paging = payload.get("paging", {})
        is_end = bool(paging.get("is_end", True))
        request_uri = f"/api/v4/members/{creator_id}/answers"
        return CreatorContentsPage(
            items=items,
            has_more=not is_end,
            next_cursor="" if is_end else str(offset + page_limit),
            raw_payload=payload,
            request_uri=request_uri,
            metadata={
                "outcome": {
                    "normalized_records": normalized_records,
                    "raw_record": {
                        "record_type": "creator_contents",
                        "source_uri": request_uri,
                        "request_meta": {"creator_id": creator_id, "cursor": str(cursor or "")},
                        "response_body": payload,
                        "metadata": {"bridge": "zhihu_connector", "normalized_count": len(normalized_records)},
                    },
                    "events": [
                        {
                            "event_type": "creator_contents_succeeded",
                            "message": "Zhihu bridge creator contents succeeded",
                            "details": {"creator_id": creator_id, "items_count": len(items)},
                        }
                    ],
                    "response_payload": {
                        "items": items,
                        "normalized_records": normalized_records,
                        "has_more": not is_end,
                        "next_cursor": "" if is_end else str(offset + page_limit),
                    },
                }
            },
        )

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

    @staticmethod
    def _parse_creator_url(creator_url: str) -> str:
        if not creator_url:
            raise ValueError("Zhihu creator task requires creator_url")
        return creator_url.rstrip("/").split("/")[-1]

    @staticmethod
    def _parse_note_url(note_url: str) -> tuple[str, str, str]:
        if zhihu_constant.ANSWER_NAME in note_url:
            return note_url.split("/")[-1], zhihu_constant.ANSWER_NAME, note_url.split("/")[-3]
        if zhihu_constant.ARTICLE_NAME in note_url:
            return note_url.split("/")[-1], zhihu_constant.ARTICLE_NAME, ""
        if zhihu_constant.VIDEO_NAME in note_url:
            return note_url.split("/")[-1], zhihu_constant.VIDEO_NAME, ""
        raise ValueError(f"Unsupported Zhihu note url: {note_url}")

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

    @staticmethod
    def _content_from_url(note_url: str) -> ZhihuContent:
        clean_url = note_url.split("?")[0]
        if zhihu_constant.ANSWER_NAME in clean_url:
            return ZhihuContent(content_id=clean_url.split("/")[-1], content_type=zhihu_constant.ANSWER_NAME, question_id=clean_url.split("/")[-3], content_url=clean_url)
        if zhihu_constant.ARTICLE_NAME in clean_url:
            return ZhihuContent(content_id=clean_url.split("/")[-1], content_type=zhihu_constant.ARTICLE_NAME, question_id="", content_url=clean_url)
        if zhihu_constant.VIDEO_NAME in clean_url:
            return ZhihuContent(content_id=clean_url.split("/")[-1], content_type=zhihu_constant.VIDEO_NAME, question_id="", content_url=clean_url)
        raise ValueError(f"Unsupported Zhihu note url: {note_url}")


def build_zhihu_connector_from_legacy(crawler) -> ZhihuConnector:
    browser_executor = BrowserExecutor()
    browser_executor.bind(
        context=getattr(crawler, "browser_context", None),
        page=getattr(crawler, "context_page", None),
        browser_type="chromium",
        cdp_enabled=bool(getattr(crawler, "cdp_manager", None)),
        headless=False,
    )
    http_executor = HttpExecutor(proxy=getattr(crawler, "_platform_http_proxy", None))
    session_service = SessionService(platform_code="zhihu")
    return ZhihuConnector(
        browser_executor=browser_executor,
        http_executor=http_executor,
        session_service=session_service,
    )
