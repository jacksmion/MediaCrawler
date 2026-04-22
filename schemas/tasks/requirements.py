from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal


DouyinRequirementMode = Literal["search", "detail", "creator"]
XhsRequirementMode = Literal["search", "detail", "creator"]
ZhihuRequirementMode = Literal["search", "detail", "creator"]
WeiboRequirementMode = Literal["search", "detail", "creator"]


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


@dataclass(slots=True)
class XhsCrawlRequirement:
    """User-facing Xiaohongshu crawl requirement model."""

    mode: XhsRequirementMode
    keywords: list[str] = field(default_factory=list)
    note_urls: list[str] = field(default_factory=list)
    creator_urls: list[str] = field(default_factory=list)
    start_page: int = 1
    max_pages: int = 1
    page_size: int = 20
    sort_type: str | None = None
    include_comments: bool = False
    include_detail: bool = False
    comment_limit: int | None = None
    creator_contents_limit: int = 30
    creator_max_pages: int = 1
    metadata: dict[str, str] = field(default_factory=dict)


@dataclass(slots=True)
class ZhihuCrawlRequirement:
    """User-facing Zhihu crawl requirement model."""

    mode: ZhihuRequirementMode
    keywords: list[str] = field(default_factory=list)
    note_urls: list[str] = field(default_factory=list)
    creator_urls: list[str] = field(default_factory=list)
    start_page: int = 1
    max_pages: int = 1
    page_size: int = 20
    include_comments: bool = False
    include_detail: bool = False
    comment_limit: int | None = None
    creator_contents_limit: int = 20
    creator_max_pages: int = 1
    metadata: dict[str, str] = field(default_factory=dict)


@dataclass(slots=True)
class WeiboCrawlRequirement:
    """User-facing Weibo crawl requirement model."""

    mode: WeiboRequirementMode
    keywords: list[str] = field(default_factory=list)
    note_ids: list[str] = field(default_factory=list)
    creator_ids: list[str] = field(default_factory=list)
    start_page: int = 1
    max_pages: int = 1
    search_type: str | None = None
    include_comments: bool = False
    include_detail: bool = False
    comment_limit: int | None = None
    creator_contents_limit: int = 10
    creator_max_pages: int = 1
    metadata: dict[str, str] = field(default_factory=dict)
