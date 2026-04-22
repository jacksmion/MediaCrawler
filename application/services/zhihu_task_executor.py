from __future__ import annotations

from typing import Any

from application.platform_hooks import ExecutionServices, ZhihuPlatformHooks
from constant import zhihu as zhihu_constant
from model.m_zhihu import ZhihuContent
from schemas.tasks.models import CrawlTask
from schemas.tasks.requirements import ZhihuCrawlRequirement

from .base_task_executor import BaseTaskExecutor
from .zhihu_task_planner import ZhihuTaskPlanner


class ZhihuTaskExecutor(BaseTaskExecutor):
    """Dispatches persisted Zhihu crawl tasks through the shared execution stack."""

    platform_code = "zhihu"

    def __init__(
        self,
        crawler,
        *,
        crawl_state_service,
        event_service,
        normalized_content_service,
        raw_record_service,
        planner: ZhihuTaskPlanner | None = None,
    ) -> None:
        super().__init__(
            crawler,
            planner=planner or ZhihuTaskPlanner(),
            hooks=ZhihuPlatformHooks(crawler),
            services=ExecutionServices(
                crawl_state_service=crawl_state_service,
                event_service=event_service,
                normalized_content_service=normalized_content_service,
                raw_record_service=raw_record_service,
            ),
        )

    def _collect_targets_from_results(self, results: list[dict[str, Any]]) -> list[ZhihuContent]:
        contents: list[ZhihuContent] = []
        for result in results:
            content = result.get("content")
            if isinstance(content, ZhihuContent):
                contents.append(content)
            elif isinstance(content, dict):
                contents.append(ZhihuContent.model_validate(content))
            for item in result.get("items", []):
                if isinstance(item, dict):
                    contents.append(ZhihuContent.model_validate(item))
        return contents

    def _collect_targets_from_requirement(self, requirement: ZhihuCrawlRequirement) -> list[ZhihuContent]:
        return [self._content_from_url(note_url) for note_url in requirement.note_urls if note_url.strip()]

    def _build_detail_task(self, target: ZhihuContent, index: int) -> CrawlTask:
        return CrawlTask(
            task_id=f"zh-followup-detail-{index}",
            platform_code=self.platform_code,
            task_type="detail",
            status="planned",
            params={"note_url": target.content_url},
        )

    def _build_comments_task(self, target: ZhihuContent, index: int, comment_limit: int | None) -> CrawlTask:
        return CrawlTask(
            task_id=f"zh-followup-comments-{index}",
            platform_code=self.platform_code,
            task_type="comments",
            status="planned",
            params={"content": target.model_dump(), "cursor": "", "limit": comment_limit},
        )

    def _dedupe_targets(self, targets: list[ZhihuContent]) -> list[ZhihuContent]:
        unique: list[ZhihuContent] = []
        seen: set[tuple[str, str]] = set()
        for target in targets:
            key = (target.content_type, target.content_id)
            if key in seen:
                continue
            seen.add(key)
            unique.append(target)
        return unique

    @staticmethod
    def _content_from_url(note_url: str) -> ZhihuContent:
        clean_url = note_url.split("?")[0]
        if zhihu_constant.ANSWER_NAME in clean_url:
            return ZhihuContent(
                content_id=clean_url.split("/")[-1],
                content_type=zhihu_constant.ANSWER_NAME,
                question_id=clean_url.split("/")[-3],
                content_url=clean_url,
            )
        if zhihu_constant.ARTICLE_NAME in clean_url:
            return ZhihuContent(
                content_id=clean_url.split("/")[-1],
                content_type=zhihu_constant.ARTICLE_NAME,
                question_id="",
                content_url=clean_url,
            )
        if zhihu_constant.VIDEO_NAME in clean_url:
            return ZhihuContent(
                content_id=clean_url.split("/")[-1],
                content_type=zhihu_constant.VIDEO_NAME,
                question_id="",
                content_url=clean_url,
            )
        raise ValueError(f"Unsupported Zhihu note url: {note_url}")
