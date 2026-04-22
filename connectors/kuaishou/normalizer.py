from __future__ import annotations

from datetime import datetime
from typing import Any

from schemas.normalized.entities import ContentRecord


def normalize_kuaishou_video(video_item: dict[str, Any]) -> ContentRecord | None:
    """Convert a Kuaishou video payload into the shared normalized content shape."""
    photo = video_item.get("photo", {}) or {}
    author = video_item.get("author", {}) or {}
    video_id = str(photo.get("id") or "")
    if not video_id:
        return None
    published_at = None
    timestamp = photo.get("timestamp")
    if timestamp:
        try:
            published_at = datetime.utcfromtimestamp(int(timestamp))
        except Exception:
            published_at = None
    return ContentRecord(
        platform_code="kuaishou",
        platform_content_id=video_id,
        content_type="video",
        title=photo.get("caption", ""),
        body_text=photo.get("caption", ""),
        url=f"https://www.kuaishou.com/short-video/{video_id}",
        author_platform_id=str(author.get("id") or ""),
        published_at=published_at,
        raw_payload=video_item,
        metadata={
            "liked_count": photo.get("realLikeCount", 0),
            "view_count": photo.get("viewCount", 0),
        },
    )


def normalize_kuaishou_videos(video_items: list[dict[str, Any]]) -> list[ContentRecord]:
    """Normalize a batch of Kuaishou videos."""
    records: list[ContentRecord] = []
    for video_item in video_items:
        record = normalize_kuaishou_video(video_item)
        if record is not None:
            records.append(record)
    return records
