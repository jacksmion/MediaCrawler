from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal


RequirementMode = Literal["search", "detail", "creator"]


@dataclass(slots=True)
class CrawlRequirement:
    """Unified user-facing crawl requirement model."""

    platform_code: str
    mode: RequirementMode
    keywords: list[str] = field(default_factory=list)
    aweme_ids: list[str] = field(default_factory=list)
    note_urls: list[str] = field(default_factory=list)
    creator_urls: list[str] = field(default_factory=list)
    creator_ids: list[str] = field(default_factory=list)
    video_ids: list[str] = field(default_factory=list)
    note_ids: list[str] = field(default_factory=list)
    start_page: int = 1
    max_pages: int = 1
    page_size: int = 20
    publish_time: str | None = None
    sort_type: str | None = None
    search_type: str | None = None
    include_comments: bool = False
    include_detail: bool = False
    comment_limit: int | None = None
    creator_contents_limit: int = 20
    creator_max_pages: int = 1
    metadata: dict[str, str] = field(default_factory=dict)
