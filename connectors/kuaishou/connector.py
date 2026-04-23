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

from .errors import KuaishouDataFetchError
from .normalizer import normalize_kuaishou_video, normalize_kuaishou_videos


class KuaishouConnector(BaseConnector):
    """New-style Kuaishou connector for incremental platform migration."""

    def __init__(
        self,
        *,
        browser_executor: BrowserExecutor,
        http_executor: HttpExecutor,
        session_service: SessionService,
    ) -> None:
        super().__init__(
            platform_code="kuaishou",
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
        self.graphql_host = "https://www.kuaishou.com/graphql"
        self.rest_host = "https://www.kuaishou.com"

    async def prepare(self, context: ConnectorContext) -> None:
        self.context = context

    async def authenticate(self, auth_context: AuthContext) -> AuthResult:
        return AuthResult(
            success=False,
            login_type=auth_context.login_type,
            account_id=auth_context.account_id,
            message="Kuaishou connector authentication is not migrated yet.",
        )

    async def health_check(self) -> HealthStatus:
        session = await self._refresh_session()
        ok = bool(session.cookie_dict.get("kuaishou.server.web_st"))
        return HealthStatus(
            ok=ok,
            platform_code=self.platform_code,
            message="Kuaishou session loaded" if ok else "Kuaishou session missing web auth cookie",
            details={"cookie_keys": sorted(session.cookie_dict.keys())[:10]},
        )

    async def search(self, query: SearchQuery) -> SearchPage:
        payload = await self._post_graphql(
            {
                "operationName": "visionSearchPhoto",
                "variables": {
                    "keyword": query.keyword,
                    "pcursor": str(query.page),
                    "page": "search",
                    "searchSessionId": query.filters.get("search_session_id", ""),
                },
                "query": await self._load_graphql("search_query"),
            }
        )
        search_payload = payload.get("visionSearchPhoto", {})
        items = search_payload.get("feeds", []) or []
        normalized_records = normalize_kuaishou_videos(items)
        return SearchPage(
            items=items,
            has_more=bool(items),
            next_cursor=search_payload.get("searchSessionId", ""),
            raw=payload,
            metadata={
                "request_uri": "/graphql",
                "keyword": query.keyword,
                "page": query.page,
                "outcome": {
                    "normalized_records": normalized_records,
                    "raw_record": {
                        "record_type": "search",
                        "source_uri": "/graphql",
                        "request_meta": {"keyword": query.keyword, "page": query.page},
                        "response_body": payload,
                        "metadata": {"bridge": "kuaishou_connector", "normalized_count": len(normalized_records)},
                    },
                    "events": [
                        {
                            "event_type": "search_page_succeeded",
                            "message": "Kuaishou bridge search page succeeded",
                            "details": {"keyword": query.keyword, "page": query.page, "items_count": len(items)},
                        }
                    ],
                    "response_payload": {
                        "items": items,
                        "normalized_records": normalized_records,
                        "has_more": bool(items),
                        "next_cursor": search_payload.get("searchSessionId", ""),
                        "raw": payload,
                    },
                },
            },
        )

    async def fetch_content_detail(self, content_id: str, extra: dict[str, Any] | None = None) -> ContentDetailResult:
        payload = await self._post_graphql(
            {
                "operationName": "visionVideoDetail",
                "variables": {"photoId": content_id, "page": "search"},
                "query": await self._load_graphql("video_detail"),
            }
        )
        detail = payload.get("visionVideoDetail")
        if not detail:
            raise KuaishouDataFetchError(f"Kuaishou detail payload missing visionVideoDetail for {content_id}")
        normalized_record = normalize_kuaishou_video(detail)
        return ContentDetailResult(
            item=detail,
            item_key="video",
            raw_payload=payload,
            request_uri="/graphql",
            metadata={
                "outcome": {
                    "normalized_records": [normalized_record] if normalized_record is not None else [],
                    "raw_record": {
                        "record_type": "detail",
                        "source_uri": "/graphql",
                        "request_meta": {"video_id": content_id},
                        "response_body": payload,
                        "metadata": {"bridge": "kuaishou_connector"},
                    },
                    "events": [
                        {
                            "event_type": "detail_succeeded",
                            "message": "Kuaishou bridge detail succeeded",
                            "details": {"video_id": content_id},
                        }
                    ],
                    "response_payload": {"video": detail},
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
        pcursor = str(cursor or "")
        comments: list[dict[str, Any]] = []
        raw_pages: list[dict[str, Any]] = []
        max_count = int(limit or 10)
        while pcursor != "no_more" and len(comments) < max_count:
            payload = await self._post_rest("/rest/v/photo/comment/list", {"photoId": content_id, "pcursor": pcursor})
            raw_pages.append(payload)
            page_comments = payload.get("rootCommentsV2", []) or []
            if not page_comments:
                break
            remaining = max_count - len(comments)
            comments.extend(page_comments[:remaining])
            pcursor = payload.get("pcursorV2", "no_more")
        return CommentsPage(
            comments=comments,
            next_cursor=pcursor,
            has_more=pcursor != "no_more",
            request_uri="/rest/v/photo/comment/list",
            raw_payload=raw_pages,
            metadata={
                "outcome": {
                    "raw_record": {
                        "record_type": "comments",
                        "source_uri": "/rest/v/photo/comment/list",
                        "request_meta": {"video_id": content_id, "cursor": str(cursor or ""), "limit": max_count},
                        "response_body": raw_pages,
                        "metadata": {"bridge": "kuaishou_connector", "comment_count": len(comments)},
                    },
                    "events": [
                        {
                            "event_type": "comments_succeeded",
                            "message": "Kuaishou bridge comments succeeded",
                            "details": {"video_id": content_id, "comment_count": len(comments)},
                        }
                    ],
                    "response_payload": {
                        "comments": comments,
                        "cursor": pcursor,
                        "has_more": pcursor != "no_more",
                    },
                }
            },
        )

    async def fetch_creator(self, creator_id: str) -> CreatorResult:
        payload = await self._post_graphql(
            {
                "operationName": "visionProfile",
                "variables": {"userId": creator_id},
                "query": await self._load_graphql("vision_profile"),
            }
        )
        creator = payload.get("visionProfile", {}).get("userProfile")
        if not creator:
            raise KuaishouDataFetchError(f"Kuaishou creator payload missing userProfile for {creator_id}")
        return CreatorResult(
            creator=creator,
            raw_payload=payload,
            request_uri="/graphql",
            metadata={
                "outcome": {
                    "raw_record": {
                        "record_type": "creator",
                        "source_uri": "/graphql",
                        "request_meta": {"creator_id": creator_id},
                        "response_body": payload,
                        "metadata": {"bridge": "kuaishou_connector"},
                    },
                    "events": [
                        {
                            "event_type": "creator_succeeded",
                            "message": "Kuaishou bridge creator succeeded",
                            "details": {"creator_id": creator_id},
                        }
                    ],
                    "response_payload": {"creator": creator},
                }
            },
        )

    async def fetch_creator_contents(
        self,
        creator_id: str,
        cursor: str | int | None = None,
        limit: int | None = None,
    ) -> CreatorContentsPage:
        payload = await self._post_graphql(
            {
                "operationName": "visionProfilePhotoList",
                "variables": {"page": "profile", "pcursor": str(cursor or ""), "userId": creator_id},
                "query": await self._load_graphql("vision_profile_photo_list"),
            }
        )
        profile_photo_list = payload.get("visionProfilePhotoList", {})
        items = (profile_photo_list.get("feeds", []) or [])[: int(limit or 20)]
        normalized_records = normalize_kuaishou_videos(items)
        return CreatorContentsPage(
            items=items,
            has_more=profile_photo_list.get("pcursor", "no_more") != "no_more",
            next_cursor=profile_photo_list.get("pcursor", ""),
            raw_payload=payload,
            request_uri="/graphql",
            metadata={
                "outcome": {
                    "normalized_records": normalized_records,
                    "raw_record": {
                        "record_type": "creator_contents",
                        "source_uri": "/graphql",
                        "request_meta": {"creator_id": creator_id, "cursor": str(cursor or "")},
                        "response_body": payload,
                        "metadata": {"bridge": "kuaishou_connector", "normalized_count": len(normalized_records)},
                    },
                    "events": [
                        {
                            "event_type": "creator_contents_succeeded",
                            "message": "Kuaishou bridge creator contents succeeded",
                            "details": {"creator_id": creator_id, "items_count": len(items)},
                        }
                    ],
                    "response_payload": {
                        "items": items,
                        "normalized_records": normalized_records,
                        "has_more": profile_photo_list.get("pcursor", "no_more") != "no_more",
                        "next_cursor": profile_photo_list.get("pcursor", ""),
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
        session.login_status = bool(session.cookie_dict)
        self.session_service.save(session)
        return session

    async def _build_headers(self) -> dict[str, str]:
        session = await self._refresh_session()
        cookie_str = ";".join(f"{key}={value}" for key, value in session.cookie_dict.items())
        return {
            "User-Agent": session.user_agent or "",
            "Cookie": cookie_str,
            "Origin": "https://www.kuaishou.com",
            "Referer": "https://www.kuaishou.com",
            "Content-Type": "application/json;charset=UTF-8",
        }

    async def _post_graphql(self, data: dict[str, Any]) -> dict[str, Any]:
        response = await self.http_executor.send(
            HttpRequest(
                method="POST",
                url=self.graphql_host,
                data=__import__("json").dumps(data, separators=(",", ":"), ensure_ascii=False),
                headers=await self._build_headers(),
            )
        )
        if response.status_code != 200:
            raise KuaishouDataFetchError(f"Kuaishou GraphQL request failed with status {response.status_code}: {response.text[:300]}")
        payload = response.data if isinstance(response.data, dict) else {}
        if payload.get("errors"):
            raise KuaishouDataFetchError(str(payload.get("errors")))
        return payload.get("data", {}) or {}

    async def _post_rest(self, uri: str, data: dict[str, Any]) -> dict[str, Any]:
        response = await self.http_executor.send(
            HttpRequest(
                method="POST",
                url=f"{self.rest_host}{uri}",
                data=__import__("json").dumps(data, separators=(",", ":"), ensure_ascii=False),
                headers=await self._build_headers(),
            )
        )
        if response.status_code != 200:
            raise KuaishouDataFetchError(f"Kuaishou REST request failed with status {response.status_code}: {response.text[:300]}")
        payload = response.data if isinstance(response.data, dict) else {}
        if payload.get("result") != 1:
            raise KuaishouDataFetchError(str(payload))
        return payload

    async def _load_graphql(self, name: str) -> str:
        from pathlib import Path

        mapping = {
            "search_query": "search_query.graphql",
            "video_detail": "video_detail.graphql",
            "vision_profile": "vision_profile.graphql",
            "vision_profile_photo_list": "vision_profile_photo_list.graphql",
        }
        file_path = Path("connectors") / "kuaishou" / "graphql" / mapping[name]
        return file_path.read_text(encoding="utf-8")
