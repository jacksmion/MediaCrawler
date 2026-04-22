# -*- coding: utf-8 -*-
#
# Execution planning for crawler runs.

from __future__ import annotations

from dataclasses import dataclass
import json

from schemas.tasks.platform_mappings import PLATFORM_SEARCH_PAGE_HINTS
from ..schemas import CrawlerTypeEnum, PlatformEnum, ResolvedCrawlerConfig
from .crawler_command_builder import CrawlerCommandBuilder


@dataclass(frozen=True, slots=True)
class CrawlerExecutionPlan:
    """Selected execution command and mode for one crawler run."""

    mode: str
    command: list[str]


class CrawlerExecutionPlanner:
    """Selects the best execution path for a resolved crawler config."""

    def __init__(self, fallback_command_builder: CrawlerCommandBuilder | None = None) -> None:
        self.fallback_command_builder = fallback_command_builder or CrawlerCommandBuilder()

    def build_plan(self, config: ResolvedCrawlerConfig) -> CrawlerExecutionPlan:
        """Build an execution plan for the given resolved config."""
        if self._supports_platform_requirement_entry(config):
            return CrawlerExecutionPlan(
                mode="platform_requirement",
                command=self._build_platform_requirement_command(config),
            )
        return CrawlerExecutionPlan(
            mode="legacy_main",
            command=self.fallback_command_builder.build(config),
        )

    @staticmethod
    def _supports_platform_requirement_entry(config: ResolvedCrawlerConfig) -> bool:
        return (
            config.platform in {
                PlatformEnum.XHS,
                PlatformEnum.DOUYIN,
                PlatformEnum.KUAISHOU,
                PlatformEnum.BILIBILI,
                PlatformEnum.WEIBO,
                PlatformEnum.TIEBA,
                PlatformEnum.ZHIHU,
            }
            and config.crawler_type in {CrawlerTypeEnum.SEARCH, CrawlerTypeEnum.DETAIL, CrawlerTypeEnum.CREATOR}
        )

    @staticmethod
    def _build_platform_requirement_command(config: ResolvedCrawlerConfig) -> list[str]:
        payload = config.model_dump(mode="json")
        payload["max_pages"] = 1
        if config.comment_time_filter_h > 0:
            payload["comment_limit"] = 50

        cmd = [
            "uv",
            "run",
            "python",
            "run_platform_requirement.py",
            "--request-json",
            json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
        ]
        return cmd
