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


def parse_search_payload(payload: dict[str, Any]) -> dict[str, Any]:
    items = payload.get("items", [])
    normalized_records = normalize_search_items(items)
    return {
        "items": items,
        "normalized_records": normalized_records,
        "next_cursor": payload.get("next_cursor"),
        "raw": payload.get("raw"),
    }


def parse_detail_payload(payload: dict[str, Any]) -> dict[str, Any]:
    aweme_detail = payload.get("aweme_detail") or payload.get("item") or {}
    normalized_record = normalize_aweme_detail(aweme_detail) if aweme_detail else None
    return {
        "aweme_detail": aweme_detail,
        "normalized_record": normalized_record,
        "raw_payload": payload.get("raw_payload"),
        "request_uri": payload.get("request_uri", "/aweme/v1/web/aweme/detail/"),
        "request_params": payload.get("request_params", {}),
    }


def parse_comments_payload(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "comments": payload.get("comments", []),
        "cursor": payload.get("cursor", payload.get("next_cursor")),
        "has_more": payload.get("has_more", False),
        "raw_payload": payload.get("raw_payload", payload),
        "request_uri": payload.get("request_uri", "/aweme/v1/web/comment/list/"),
        "request_params": payload.get("request_params", {}),
    }


def parse_creator_payload(payload: dict[str, Any]) -> dict[str, Any]:
    creator_payload = payload.get("creator", payload.get("raw_payload"))
    return {
        "creator": creator_payload,
        "raw_payload": payload.get("raw_payload", creator_payload),
        "request_uri": payload.get("request_uri", "/aweme/v1/web/user/profile/other/"),
        "request_params": payload.get("request_params", {}),
    }


def parse_creator_contents_payload(payload: dict[str, Any]) -> dict[str, Any]:
    items = payload.get("items", [])
    normalized_records: list[ContentRecord] = []
    for item in items:
        record = normalize_aweme_detail(item)
        if record is not None:
            normalized_records.append(record)
    return {
        "items": items,
        "normalized_records": normalized_records,
        "next_cursor": payload.get("next_cursor"),
        "has_more": payload.get("has_more", False),
        "raw_payload": payload.get("raw_payload"),
        "request_uri": payload.get("request_uri", "/aweme/v1/web/aweme/post/"),
        "request_params": payload.get("request_params", {}),
    }
