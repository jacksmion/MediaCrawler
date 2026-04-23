from __future__ import annotations

from typing import Any

from connectors.base.models import CommentsPage, ContentDetailResult, CreatorContentsPage, CreatorResult, SearchQuery
from connectors.base.base_connector import BaseConnector
from schemas.tasks.runtime import PlatformTaskRequest, PlatformTaskResult


def _serialize_detail_payload(detail: dict[str, Any] | ContentDetailResult) -> dict[str, Any]:
    if isinstance(detail, ContentDetailResult):
        return detail.to_payload()
    return detail


def _serialize_comments_payload(comments: dict[str, Any] | CommentsPage) -> dict[str, Any]:
    if isinstance(comments, CommentsPage):
        return comments.to_payload()
    return comments


def _serialize_creator_payload(creator: dict[str, Any] | CreatorResult) -> dict[str, Any]:
    if isinstance(creator, CreatorResult):
        return creator.to_payload()
    return creator


def _serialize_creator_contents_payload(contents: dict[str, Any] | CreatorContentsPage) -> dict[str, Any]:
    if isinstance(contents, CreatorContentsPage):
        return contents.to_payload()
    return contents


def _extract_outcome(result_obj) -> dict[str, Any]:
    metadata = getattr(result_obj, "metadata", None)
    if isinstance(metadata, dict):
        return metadata.get("outcome", {})
    return {}


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
                outcome=_extract_outcome(page),
                metrics={
                    "items_count": len(page.items),
                    "has_more": int(page.has_more),
                },
            )
        if request.task_kind == "detail":
            content_id = str(request.payload["content_id"])
            extra = request.payload.get("extra")
            detail = await self.connector.fetch_content_detail(content_id, extra=extra)
            detail_payload = _serialize_detail_payload(detail)
            return PlatformTaskResult(
                job_id=request.job_id,
                platform_code=request.platform_code,
                task_kind=request.task_kind,
                success=True,
                payload=detail_payload,
                outcome=_extract_outcome(detail),
                metrics={"detail_count": 1},
            )
        if request.task_kind == "comments":
            content_id = str(request.payload["content_id"])
            comments = await self.connector.fetch_comments(
                content_id=content_id,
                cursor=request.payload.get("cursor"),
                limit=request.payload.get("limit"),
                extra=request.payload.get("extra"),
            )
            comments_payload = _serialize_comments_payload(comments)
            return PlatformTaskResult(
                job_id=request.job_id,
                platform_code=request.platform_code,
                task_kind=request.task_kind,
                success=True,
                payload=comments_payload,
                outcome=_extract_outcome(comments),
                metrics={
                    "comment_count": len(comments_payload.get("comments", [])),
                    "has_more": int(bool(comments_payload.get("has_more"))),
                },
            )
        if request.task_kind == "creator":
            creator_id = str(request.payload["creator_id"])
            creator = await self.connector.fetch_creator(creator_id)
            creator_payload = _serialize_creator_payload(creator)
            return PlatformTaskResult(
                job_id=request.job_id,
                platform_code=request.platform_code,
                task_kind=request.task_kind,
                success=True,
                payload=creator_payload,
                outcome=_extract_outcome(creator),
                metrics={"creator_count": 1},
            )
        if request.task_kind == "creator_contents":
            creator_id = str(request.payload["creator_id"])
            contents = await self.connector.fetch_creator_contents(
                creator_id=creator_id,
                cursor=request.payload.get("cursor"),
                limit=request.payload.get("limit"),
            )
            contents_payload = _serialize_creator_contents_payload(contents)
            return PlatformTaskResult(
                job_id=request.job_id,
                platform_code=request.platform_code,
                task_kind=request.task_kind,
                success=True,
                payload=contents_payload,
                outcome=_extract_outcome(contents),
                metrics={
                    "items_count": len(contents_payload.get("items", [])),
                    "has_more": int(bool(contents_payload.get("has_more"))),
                },
            )
        raise ValueError(f"Unsupported task kind: {request.task_kind}")
