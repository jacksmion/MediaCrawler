from __future__ import annotations

from datetime import datetime
from typing import Any

from application.services.crawler_runtime import CrawlerFactory, cleanup_runtime
from application.services.requirement_mapper import build_requirement_from_request_payload


class DouyinCommentMonitorExecutor:
    async def refresh_once(self, item: dict[str, Any]) -> dict[str, Any]:
        payload = {
            "platform": "dy",
            "crawler_type": "detail",
            "specified_ids": item["content_id"],
            "enable_comments": True,
            "enable_sub_comments": True,
            "save_option": "jsonl",
            "headless": True,
            "comment_limit": 100,
        }
        requirement = build_requirement_from_request_payload(payload, source="douyin_monitor", max_pages_default=1)
        crawler = CrawlerFactory.create_crawler(platform="dy")
        try:
            result = await crawler.start_with_requirement(requirement)
        finally:
            await cleanup_runtime(crawler)

        derived_results = result.get("derived_results", [])
        comment_results = [row for row in derived_results if isinstance(row, dict) and row.get("task_kind") == "comments"]
        last_payload = comment_results[-1] if comment_results else {}
        response_payload = last_payload if isinstance(last_payload, dict) else {}
        metrics = last_payload.get("metrics", {}) if isinstance(last_payload.get("metrics"), dict) else {}
        return {
            "last_cursor": str(response_payload.get("next_cursor") or response_payload.get("cursor") or item.get("last_cursor") or ""),
            "last_success_at": datetime.utcnow().replace(microsecond=0).isoformat(),
            "last_error": "",
            "last_run_comment_count": int(metrics.get("comment_count") or len(response_payload.get("comments", [])) or 0),
        }
