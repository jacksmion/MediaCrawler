from __future__ import annotations

from pydantic import BaseModel
from typing import Any


class TaskCreateRequest(BaseModel):
    """Request to create a new task."""
    name: str = ""
    platform: str  # dy, xhs, ks, bili, wb, tieba, zhihu
    account_id: str = ""
    crawler_type: str  # search, detail, creator
    mode: str = "once"  # once or loop
    loop_interval_seconds: int = 60  # minimum 5
    keywords: str = ""
    specified_ids: str = ""
    creator_ids: str = ""
    sort_type: str = ""
    enable_comments: bool = True
    enable_sub_comments: bool = False
    comment_time_filter_h: int = 0
    comment_keyword_filter: str = ""  # only show comments containing this keyword
    headless: bool = True


class TaskItemResponse(BaseModel):
    """Single task item."""
    task_id: str
    name: str
    platform: str
    account_id: str
    crawler_type: str
    mode: str  # once / loop
    status: str  # idle / running / paused / completed / error
    config: dict[str, Any] = {}
    loop_interval_seconds: int = 60
    created_at: str = ""
    last_run_at: str | None = None
    last_run_status: str | None = None
    comment_count: int = 0
    error_message: str | None = None


class TaskListResponse(BaseModel):
    """List of tasks."""
    tasks: list[TaskItemResponse]
