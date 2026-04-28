from __future__ import annotations

from pydantic import BaseModel, Field


class MonitorItemCreateRequest(BaseModel):
    content_url: str
    refresh_interval_seconds: int = Field(default=60, ge=10, le=86400)
    title: str = ""
    author_short_id: str = ""


class MonitorItemUpdateRequest(BaseModel):
    title: str | None = None
    author_short_id: str | None = None
    refresh_interval_seconds: int | None = Field(default=None, ge=10, le=86400)
    status: str | None = None


class MonitorItemResponse(BaseModel):
    monitor_item_id: str
    platform_code: str
    content_id: str
    content_url: str
    title: str = ""
    author_short_id: str = ""
    refresh_interval_seconds: int
    status: str
    last_cursor: str = ""
    last_success_at: str | None = None
    last_error: str = ""
    last_run_comment_count: int = 0
    created_at: str
    updated_at: str


class MonitorItemListResponse(BaseModel):
    items: list[MonitorItemResponse]


class MonitorLogItemResponse(BaseModel):
    event_id: str
    monitor_item_id: str
    level: str
    message: str
    details: dict = {}
    created_at: str


class MonitorLogListResponse(BaseModel):
    items: list[MonitorLogItemResponse]
