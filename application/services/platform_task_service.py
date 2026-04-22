from __future__ import annotations

from typing import Any

from connectors.base.models import SearchQuery
from connectors.base.base_connector import BaseConnector
from schemas.tasks.runtime import PlatformTaskRequest, PlatformTaskResult


class PlatformTaskService:
    """Minimal task execution entry point for platform connectors."""

    def __init__(self, connector: BaseConnector) -> None:
        self.connector = connector

    async def execute(self, request: PlatformTaskRequest) -> PlatformTaskResult:
        """Dispatch a platform task to the matching connector method."""
        if request.task_kind == "search":
            query = SearchQuery(**request.payload)
            page = await self.connector.search(query)
            return PlatformTaskResult(
                job_id=request.job_id,
                platform_code=request.platform_code,
                task_kind=request.task_kind,
                success=True,
                payload={
                    "items": page.items,
                    "has_more": page.has_more,
                    "next_cursor": page.next_cursor,
                    "raw": page.raw,
                    "metadata": page.metadata,
                },
                metrics={
                    "items_count": len(page.items),
                    "has_more": int(page.has_more),
                },
            )
        if request.task_kind == "detail":
            content_id = str(request.payload["content_id"])
            extra = request.payload.get("extra")
            detail = await self.connector.fetch_content_detail(content_id, extra=extra)
            return PlatformTaskResult(
                job_id=request.job_id,
                platform_code=request.platform_code,
                task_kind=request.task_kind,
                success=True,
                payload=detail,
                metrics={"detail_count": 1},
            )
        if request.task_kind == "comments":
            content_id = str(request.payload["content_id"])
            comments = await self.connector.fetch_comments(
                content_id=content_id,
                cursor=request.payload.get("cursor"),
                limit=request.payload.get("limit"),
            )
            return PlatformTaskResult(
                job_id=request.job_id,
                platform_code=request.platform_code,
                task_kind=request.task_kind,
                success=True,
                payload=comments,
                metrics={
                    "comment_count": len(comments.get("comments", [])),
                    "has_more": int(bool(comments.get("has_more"))),
                },
            )
        if request.task_kind == "creator":
            creator_id = str(request.payload["creator_id"])
            creator = await self.connector.fetch_creator(creator_id)
            return PlatformTaskResult(
                job_id=request.job_id,
                platform_code=request.platform_code,
                task_kind=request.task_kind,
                success=True,
                payload=creator,
                metrics={"creator_count": 1},
            )
        if request.task_kind == "creator_contents":
            creator_id = str(request.payload["creator_id"])
            contents = await self.connector.fetch_creator_contents(
                creator_id=creator_id,
                cursor=request.payload.get("cursor"),
                limit=request.payload.get("limit"),
            )
            return PlatformTaskResult(
                job_id=request.job_id,
                platform_code=request.platform_code,
                task_kind=request.task_kind,
                success=True,
                payload=contents,
                metrics={
                    "items_count": len(contents.get("items", [])),
                    "has_more": int(bool(contents.get("has_more"))),
                },
            )
        raise ValueError(f"Unsupported task kind: {request.task_kind}")
