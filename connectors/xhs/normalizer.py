from __future__ import annotations

from datetime import datetime
from typing import Any

from schemas.normalized.entities import ContentRecord


def _parse_published_at(value: Any) -> datetime | None:
    if value in (None, "", 0):
        return None
    if isinstance(value, (int, float)):
        timestamp = float(value)
        if timestamp > 10_000_000_000:
            timestamp /= 1000
        try:
            return datetime.fromtimestamp(timestamp)
        except (OSError, OverflowError, ValueError):
            return None
    return None


def normalize_xhs_note(note: dict[str, Any]) -> ContentRecord:
    """Convert a Xiaohongshu note payload into the shared normalized shape."""
    note_id = str(note.get("note_id") or note.get("id") or "")
    xsec_token = str(note.get("xsec_token") or "")
    note_url = str(note.get("note_url") or "")
    if not note_url and note_id:
        note_url = f"https://www.xiaohongshu.com/explore/{note_id}"
        if xsec_token:
            note_url += f"?xsec_token={xsec_token}&xsec_source={note.get('xsec_source', 'pc_search')}"

    user_info = note.get("user", {}) or {}
    interact_info = note.get("interact_info", {}) or {}
    return ContentRecord(
        platform_code="xhs",
        platform_content_id=note_id,
        content_type=str(note.get("type") or "note"),
        title=str(note.get("title") or note.get("desc") or "")[:255],
        body_text=str(note.get("desc") or ""),
        url=note_url,
        author_platform_id=str(user_info.get("user_id") or ""),
        published_at=_parse_published_at(note.get("time")),
        raw_payload=note,
        metadata={
            "nickname": user_info.get("nickname"),
            "ip_location": note.get("ip_location", ""),
            "liked_count": interact_info.get("liked_count"),
            "collected_count": interact_info.get("collected_count"),
            "comment_count": interact_info.get("comment_count"),
            "share_count": interact_info.get("share_count"),
            "xsec_token": xsec_token,
            "xsec_source": note.get("xsec_source", ""),
        },
    )


def normalize_xhs_notes(notes: list[dict[str, Any]]) -> list[ContentRecord]:
    """Normalize a batch of Xiaohongshu note payloads."""
    return [normalize_xhs_note(note) for note in notes if note]
