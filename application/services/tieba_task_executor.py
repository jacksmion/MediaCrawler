from __future__ import annotations

from typing import Any

from application.platform_hooks import ExecutionServices, TiebaPlatformHooks
from model.m_baidu_tieba import TiebaNote
from schemas.tasks.models import CrawlTask
from schemas.tasks.requirements import TiebaCrawlRequirement

from .base_task_executor import BaseTaskExecutor
from .tieba_task_planner import TiebaTaskPlanner


class TiebaTaskExecutor(BaseTaskExecutor):
    platform_code = "tieba"

    def __init__(self, crawler, *, crawl_state_service, event_service, normalized_content_service, raw_record_service, planner: TiebaTaskPlanner | None = None) -> None:
        super().__init__(
            crawler,
            planner=planner or TiebaTaskPlanner(),
            hooks=TiebaPlatformHooks(crawler),
            services=ExecutionServices(crawl_state_service=crawl_state_service, event_service=event_service, normalized_content_service=normalized_content_service, raw_record_service=raw_record_service),
        )

    def _collect_targets_from_results(self, results: list[dict[str, Any]]) -> list[TiebaNote]:
        targets: list[TiebaNote] = []
        for result in results:
            note = result.get("note")
            if isinstance(note, TiebaNote):
                targets.append(note)
            elif isinstance(note, dict):
                targets.append(TiebaNote.model_validate(note))
            for item in result.get("items", []):
                if isinstance(item, dict):
                    targets.append(TiebaNote.model_validate(item))
        return targets

    def _collect_targets_from_requirement(self, requirement: TiebaCrawlRequirement) -> list[TiebaNote]:
        targets: list[TiebaNote] = []
        for note_id in requirement.note_ids:
            if not note_id.strip():
                continue
            targets.append(
                TiebaNote(
                    note_id=note_id.strip(),
                    title="",
                    desc="",
                    note_url=f"https://tieba.baidu.com/p/{note_id.strip()}",
                    tieba_name="",
                    tieba_link="",
                )
            )
        return targets

    def _build_detail_task(self, target: TiebaNote, index: int) -> CrawlTask:
        return CrawlTask(
            task_id=f"tb-followup-detail-{index}",
            platform_code=self.platform_code,
            task_type="detail",
            status="planned",
            params={"note_id": target.note_id, "detail_url": target.note_url},
        )

    def _build_comments_task(self, target: TiebaNote, index: int, comment_limit: int | None) -> CrawlTask:
        return CrawlTask(
            task_id=f"tb-followup-comments-{index}",
            platform_code=self.platform_code,
            task_type="comments",
            status="planned",
            params={"note_id": target.note_id, "note": target.model_dump(), "limit": comment_limit},
        )

    def _dedupe_targets(self, targets: list[TiebaNote]) -> list[TiebaNote]:
        unique: list[TiebaNote] = []
        seen: set[str] = set()
        for target in targets:
            if target.note_id in seen:
                continue
            seen.add(target.note_id)
            unique.append(target)
        return unique
