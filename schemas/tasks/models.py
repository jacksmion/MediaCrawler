from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass(slots=True)
class CrawlTask:
    """Persistent task definition for scheduled or manual crawls."""

    task_id: str
    platform_code: str
    task_type: str
    status: str = "pending"
    schedule_type: str = "manual"
    priority: int = 0
    params: dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=datetime.utcnow)
    updated_at: datetime = field(default_factory=datetime.utcnow)


@dataclass(slots=True)
class CrawlJob:
    """Single execution instance spawned from a crawl task."""

    job_id: str
    task_id: str
    platform_code: str
    status: str = "queued"
    batch_id: str | None = None
    started_at: datetime | None = None
    ended_at: datetime | None = None
    error_code: str | None = None
    error_message: str = ""
    metrics: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class CrawlJobEvent:
    """Operational event emitted during a crawl job."""

    job_id: str
    event_type: str
    message: str = ""
    details: dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=datetime.utcnow)


@dataclass(slots=True)
class RawRecord:
    """Original response payload archived before normalization."""

    platform_code: str
    record_type: str
    source_uri: str
    fetched_at: datetime = field(default_factory=datetime.utcnow)
    request_meta: dict[str, Any] = field(default_factory=dict)
    response_body: dict[str, Any] | list[Any] | str | None = None
    content_hash: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
