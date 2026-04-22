from __future__ import annotations

from datetime import datetime
from typing import Any

from connectors.base.models import SearchPage
from schemas.normalized.entities import ContentRecord


def _extract_aweme_from_search_item(item: dict[str, Any]) -> dict[str, Any] | None:
    """Extract the aweme payload from a Douyin search item."""
    aweme = item.get("aweme_info") or ((item.get("aweme_mix_info") or {}).get("mix_items") or [None])[0]
    if not aweme:
        return None
    return aweme


def normalize_aweme_detail(aweme: dict[str, Any]) -> ContentRecord | None:
    """Normalize a Douyin aweme detail payload into the shared content schema."""
    aweme_id = str(aweme.get("aweme_id", ""))
    if not aweme_id:
        return None
    published_at = None
    if aweme.get("create_time"):
        try:
            published_at = datetime.fromtimestamp(int(aweme["create_time"]))
        except (TypeError, ValueError, OSError):
            published_at = None
    return ContentRecord(
        platform_code="douyin",
        platform_content_id=aweme_id,
        content_type="video" if not aweme.get("images") else "note",
        title=aweme.get("desc", ""),
        body_text=aweme.get("desc", ""),
        url=f"https://www.douyin.com/video/{aweme_id}",
        author_platform_id=str((aweme.get("author") or {}).get("uid", "")),
        published_at=published_at,
        raw_payload=aweme,
        metadata={},
    )


def normalize_search_item(item: dict[str, Any]) -> ContentRecord | None:
    """Normalize a Douyin search item into the shared content schema."""
    aweme = _extract_aweme_from_search_item(item)
    if not aweme:
        return None
    record = normalize_aweme_detail(aweme)
    if record is None:
        return None
    record.metadata.update(
        {
            "search_item_type": item.get("type"),
            "search_model_type": item.get("aweme_info", None) is not None and "aweme_info" or "aweme_mix_info",
        }
    )
    return record


def normalize_search_page(page: SearchPage) -> list[ContentRecord]:
    """Normalize every content-like item in a Douyin search page."""
    return normalize_search_items(page.items)


def normalize_search_items(items: list[dict[str, Any]]) -> list[ContentRecord]:
    """Normalize a list of Douyin search items."""
    records: list[ContentRecord] = []
    for item in items:
        record = normalize_search_item(item)
        if record is not None:
            records.append(record)
    return records
