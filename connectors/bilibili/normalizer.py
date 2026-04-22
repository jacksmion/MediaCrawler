from __future__ import annotations

from datetime import datetime
from typing import Any

from schemas.normalized.entities import ContentRecord


def normalize_bilibili_video(video_item: dict[str, Any]) -> ContentRecord | None:
    """Convert a Bilibili video payload into the shared normalized content shape."""
    view = video_item.get("View", {})
    if not view:
        return None
    owner = view.get("owner", {}) or {}
    published_at = None
    pubdate = view.get("pubdate")
    if pubdate:
        try:
            published_at = datetime.utcfromtimestamp(int(pubdate))
        except Exception:
            published_at = None
    aid = str(view.get("aid") or "")
    if not aid:
        return None
    return ContentRecord(
        platform_code="bilibili",
        platform_content_id=aid,
        content_type="video",
        title=view.get("title", ""),
        body_text=view.get("desc", ""),
        url=f"https://www.bilibili.com/video/av{aid}",
        author_platform_id=str(owner.get("mid") or ""),
        published_at=published_at,
        raw_payload=video_item,
        metadata={
            "bvid": view.get("bvid", ""),
            "comment_count": (view.get("stat") or {}).get("reply", 0),
            "play_count": (view.get("stat") or {}).get("view", 0),
        },
    )


def normalize_bilibili_videos(video_items: list[dict[str, Any]]) -> list[ContentRecord]:
    """Normalize a batch of Bilibili videos."""
    records: list[ContentRecord] = []
    for video_item in video_items:
        record = normalize_bilibili_video(video_item)
        if record is not None:
            records.append(record)
    return records
