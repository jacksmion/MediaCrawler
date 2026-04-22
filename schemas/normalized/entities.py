from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass(slots=True)
class ContentRecord:
    """Normalized content entity independent of source platform shape."""

    platform_code: str
    platform_content_id: str
    content_type: str
    title: str = ""
    body_text: str = ""
    url: str = ""
    author_platform_id: str = ""
    published_at: datetime | None = None
    raw_payload: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class CommentRecord:
    """Normalized comment entity."""

    platform_code: str
    platform_comment_id: str
    platform_content_id: str
    author_platform_id: str = ""
    parent_comment_id: str | None = None
    text: str = ""
    published_at: datetime | None = None
    raw_payload: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class ActorRecord:
    """Normalized creator/account entity."""

    platform_code: str
    platform_actor_id: str
    nickname: str = ""
    profile_url: str = ""
    bio: str = ""
    location: str = ""
    followers_count: int | None = None
    raw_payload: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)

