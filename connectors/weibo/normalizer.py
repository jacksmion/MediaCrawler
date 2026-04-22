from __future__ import annotations

import re
from datetime import datetime
from typing import Any

from schemas.normalized.entities import ContentRecord


def _clean_html_text(value: str) -> str:
    return re.sub(r"<.*?>", "", value or "")


def normalize_weibo_note(note_item: dict[str, Any]) -> ContentRecord | None:
    """Convert a Weibo note payload into the shared normalized content shape."""
    mblog = note_item.get("mblog", {})
    if not mblog:
        return None
    user = mblog.get("user", {}) or {}
    note_id = str(mblog.get("id") or "")
    if not note_id:
        return None
    published_at = None
    created_at = mblog.get("created_at")
    if created_at:
        try:
            published_at = datetime.strptime(created_at, "%a %b %d %H:%M:%S %z %Y")
        except Exception:
            published_at = None
    return ContentRecord(
        platform_code="weibo",
        platform_content_id=note_id,
        content_type="note",
        title=_clean_html_text(mblog.get("text", ""))[:80],
        body_text=_clean_html_text(mblog.get("text", "")),
        url=f"https://m.weibo.cn/detail/{note_id}",
        author_platform_id=str(user.get("id") or ""),
        published_at=published_at,
        raw_payload=note_item,
        metadata={
            "comments_count": mblog.get("comments_count", 0),
            "liked_count": mblog.get("attitudes_count", 0),
            "shared_count": mblog.get("reposts_count", 0),
        },
    )


def normalize_weibo_notes(note_items: list[dict[str, Any]]) -> list[ContentRecord]:
    """Normalize a batch of Weibo notes."""
    records: list[ContentRecord] = []
    for item in note_items:
        record = normalize_weibo_note(item)
        if record is not None:
            records.append(record)
    return records
