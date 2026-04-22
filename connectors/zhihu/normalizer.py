from __future__ import annotations

from datetime import datetime

from model.m_zhihu import ZhihuContent
from schemas.normalized.entities import ContentRecord


def normalize_zhihu_content(content: ZhihuContent) -> ContentRecord:
    """Convert a Zhihu content model into the shared normalized content shape."""
    published_at = None
    if content.created_time:
        published_at = datetime.utcfromtimestamp(content.created_time)
    return ContentRecord(
        platform_code="zhihu",
        platform_content_id=content.content_id,
        content_type=content.content_type,
        title=content.title,
        body_text=content.content_text or content.desc,
        url=content.content_url,
        author_platform_id=content.user_id,
        published_at=published_at,
        raw_payload=content.model_dump(),
        metadata={
            "question_id": content.question_id,
            "comment_count": content.comment_count,
            "voteup_count": content.voteup_count,
            "user_url_token": content.user_url_token,
        },
    )


def normalize_zhihu_contents(contents: list[ZhihuContent]) -> list[ContentRecord]:
    """Normalize a batch of Zhihu contents."""
    return [normalize_zhihu_content(content) for content in contents]
