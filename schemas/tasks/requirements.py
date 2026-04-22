from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal


DouyinRequirementMode = Literal["search", "detail", "creator"]


@dataclass(slots=True)
class DouyinCrawlRequirement:
    """User-facing Douyin crawl requirement model."""

    mode: DouyinRequirementMode
    keywords: list[str] = field(default_factory=list)
    aweme_ids: list[str] = field(default_factory=list)
    creator_ids: list[str] = field(default_factory=list)
    start_page: int = 1
    max_pages: int = 1
    page_size: int = 15
    publish_time: str | None = None
    sort_type: str | None = None
    include_comments: bool = False
    include_detail: bool = False
    comment_limit: int | None = None
    creator_contents_limit: int = 18
    creator_max_pages: int = 1
    metadata: dict[str, str] = field(default_factory=dict)
