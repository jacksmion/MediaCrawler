from __future__ import annotations

from datetime import datetime

from model.m_baidu_tieba import TiebaNote
from schemas.normalized.entities import ContentRecord


def normalize_tieba_note(note: TiebaNote) -> ContentRecord:
    """Convert a Tieba note into the shared normalized content shape."""
    published_at = None
    if note.publish_time:
        try:
            published_at = datetime.strptime(note.publish_time, "%Y-%m-%d %H:%M")
        except ValueError:
            published_at = None
    return ContentRecord(
        platform_code="tieba",
        platform_content_id=note.note_id,
        content_type="thread",
        title=note.title,
        body_text=note.desc,
        url=note.note_url,
        author_platform_id=note.user_link,
        published_at=published_at,
        raw_payload=note.model_dump(),
        metadata={
            "tieba_name": note.tieba_name,
            "reply_count": note.total_replay_num,
            "reply_pages": note.total_replay_page,
            "ip_location": note.ip_location,
        },
    )


def normalize_tieba_notes(notes: list[TiebaNote]) -> list[ContentRecord]:
    """Normalize a batch of Tieba notes."""
    return [normalize_tieba_note(note) for note in notes]
