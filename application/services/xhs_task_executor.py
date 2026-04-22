from __future__ import annotations

from typing import Any

from application.platform_hooks.base import ExecutionServices
from application.platform_hooks.xhs import XhsPlatformHooks
from connectors.xhs.helpers import parse_note_info_from_note_url
from schemas.tasks.models import CrawlTask
from schemas.tasks.requirements import XhsCrawlRequirement

from .base_task_executor import BaseTaskExecutor
from .xhs_task_planner import XhsTaskPlanner


class XhsTaskExecutor(BaseTaskExecutor):
    """Dispatches persisted Xiaohongshu crawl tasks through the shared execution stack."""

    platform_code = "xhs"

    def __init__(
        self,
        crawler,
        *,
        crawl_state_service,
        event_service,
        normalized_content_service,
        raw_record_service,
        planner: XhsTaskPlanner | None = None,
    ) -> None:
        super().__init__(
            crawler,
            planner=planner or XhsTaskPlanner(),
            hooks=XhsPlatformHooks(crawler),
            services=ExecutionServices(
                crawl_state_service=crawl_state_service,
                event_service=event_service,
                normalized_content_service=normalized_content_service,
                raw_record_service=raw_record_service,
            ),
        )

    def _collect_targets_from_results(self, results: list[dict[str, Any]]) -> list[dict[str, str]]:
        note_refs: list[dict[str, str]] = []
        for result in results:
            note = result.get("note")
            if isinstance(note, dict):
                note_id = str(note.get("note_id") or note.get("id") or "")
                xsec_token = str(note.get("xsec_token") or "")
                xsec_source = str(note.get("xsec_source") or "pc_search")
                if note_id and xsec_token:
                    note_refs.append({"note_id": note_id, "xsec_token": xsec_token, "xsec_source": xsec_source})
            for item in result.get("items", []):
                if isinstance(item, dict):
                    note_id = str(item.get("note_id") or item.get("id") or "")
                    xsec_token = str(item.get("xsec_token") or "")
                    xsec_source = str(item.get("xsec_source") or "pc_search")
                    if note_id and xsec_token:
                        note_refs.append({"note_id": note_id, "xsec_token": xsec_token, "xsec_source": xsec_source})
        return note_refs

    def _collect_targets_from_requirement(self, requirement: XhsCrawlRequirement) -> list[dict[str, str]]:
        note_refs: list[dict[str, str]] = []
        for note_url in requirement.note_urls:
            if not note_url.strip():
                continue
            note_info = parse_note_info_from_note_url(note_url)
            note_refs.append(
                {
                    "note_id": note_info.note_id,
                    "xsec_token": note_info.xsec_token,
                    "xsec_source": note_info.xsec_source,
                }
            )
        return note_refs

    def _build_detail_task(self, target: dict[str, str], index: int) -> CrawlTask:
        return CrawlTask(
            task_id=f"xhs-followup-detail-{index}",
            platform_code=self.platform_code,
            task_type="detail",
            status="planned",
            params={
                "note_url": (
                    f"https://www.xiaohongshu.com/explore/{target['note_id']}?"
                    f"xsec_token={target['xsec_token']}&xsec_source={target['xsec_source']}"
                ),
            },
        )

    def _build_comments_task(self, target: dict[str, str], index: int, comment_limit: int | None) -> CrawlTask:
        return CrawlTask(
            task_id=f"xhs-followup-comments-{index}",
            platform_code=self.platform_code,
            task_type="comments",
            status="planned",
            params={"note_id": target["note_id"], "xsec_token": target["xsec_token"], "limit": comment_limit},
        )

    def _dedupe_targets(self, targets: list[dict[str, str]]) -> list[dict[str, str]]:
        unique: list[dict[str, str]] = []
        seen: set[tuple[str, str]] = set()
        for target in targets:
            key = (target["note_id"], target["xsec_token"])
            if key in seen:
                continue
            seen.add(key)
            unique.append(target)
        return unique
