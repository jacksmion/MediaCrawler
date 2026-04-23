from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal


PlatformTaskKind = Literal["search", "detail", "comments", "creator", "creator_contents"]


@dataclass(slots=True)
class PlatformTaskRequest:
    """Unified request envelope for platform task execution."""

    job_id: str
    platform_code: str
    task_kind: PlatformTaskKind
    payload: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class PlatformTaskResult:
    """Unified result envelope for platform task execution."""

    job_id: str
    platform_code: str
    task_kind: PlatformTaskKind
    success: bool
    payload: dict[str, Any] = field(default_factory=dict)
    outcome: dict[str, Any] = field(default_factory=dict)
    metrics: dict[str, Any] = field(default_factory=dict)
    error_code: str | None = None
    error_message: str = ""
    created_at: datetime = field(default_factory=datetime.utcnow)
