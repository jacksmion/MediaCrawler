# -*- coding: utf-8 -*-

from pydantic import BaseModel, Field


class CommentSourceResponse(BaseModel):
    source_id: str
    platform_code: str
    platform_content_id: str
    content_title: str = ""
    content_url: str = ""
    author_short_id: str = ""
    comment_count: int = 0
    latest_comment_at: str | int | None = None
    updated_at: float
    file_path: str


class CommentSourceListResponse(BaseModel):
    items: list[CommentSourceResponse]


class CommentListItemResponse(BaseModel):
    comment_id: str
    platform_comment_id: str
    platform_content_id: str
    parent_comment_id: str | None = None
    root_comment_id: str | None = None
    comment_level: int
    comment_text: str
    author_platform_id: str = ""
    author_short_id: str = ""
    author_nickname: str = ""
    author_avatar: str = ""
    ip_location: str = ""
    author_home_location: str = ""
    published_at: str | None = None
    like_count: int = 0
    reply_count: int = 0
    raw_payload_available: bool = False


class CommentListResponse(BaseModel):
    items: list[CommentListItemResponse]
    total: int
    limit: int = Field(ge=1, le=200)
    offset: int = Field(ge=0)
