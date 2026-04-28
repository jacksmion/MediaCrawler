# -*- coding: utf-8 -*-

from fastapi import APIRouter, HTTPException, Query

from api.schemas.comments import CommentListResponse, CommentSourceListResponse
from api.services.comment_reader import CommentReaderService

router = APIRouter(prefix="/comments", tags=["comments"])
comment_reader = CommentReaderService()


@router.get("/sources", response_model=CommentSourceListResponse)
async def list_comment_sources():
    return {"items": comment_reader.list_sources()}


@router.get("", response_model=CommentListResponse)
async def list_comments(
    source_id: str,
    keyword: str | None = None,
    comment_level: int | None = Query(default=None, ge=1, le=2),
    location: str | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    sort: str = Query(default="published_at_desc"),
):
    try:
        return comment_reader.list_comments(
            source_id=source_id,
            keyword=keyword,
            comment_level=comment_level,
            location=location,
            limit=limit,
            offset=offset,
            sort=sort,
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Comment source not found") from exc


@router.get("/{comment_id}")
async def get_comment_detail(source_id: str, comment_id: str):
    try:
        return comment_reader.get_comment_detail(source_id=source_id, comment_id=comment_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Comment not found") from exc
