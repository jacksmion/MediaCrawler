# -*- coding: utf-8 -*-
#
# Execution planning for crawler runs.

from __future__ import annotations

from dataclasses import dataclass

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
                command=self._build_douyin_requirement_command(config),
            )
        return CrawlerExecutionPlan(
            mode="legacy_main",
            command=self.fallback_command_builder.build(config),
        )

    @staticmethod
    def _supports_platform_requirement_entry(config: ResolvedCrawlerConfig) -> bool:
        return (
            config.platform == PlatformEnum.DOUYIN
            and config.crawler_type in {CrawlerTypeEnum.SEARCH, CrawlerTypeEnum.DETAIL, CrawlerTypeEnum.CREATOR}
        )

    @staticmethod
    def _build_douyin_requirement_command(config: ResolvedCrawlerConfig) -> list[str]:
        cmd = [
            "uv",
            "run",
            "python",
            "run_douyin_requirement.py",
            "--mode",
            config.crawler_type.value,
            "--login-type",
            config.login_type.value,
            "--save-option",
            config.save_option.value,
            "--headless",
            "true" if config.headless else "false",
        ]

        if config.cookies:
            cmd.extend(["--cookies", config.cookies])

        if config.crawler_type == CrawlerTypeEnum.SEARCH:
            for keyword in [item.strip() for item in config.keywords.split(",") if item.strip()]:
                cmd.extend(["--keyword", keyword])
            cmd.extend(["--start-page", str(config.start_page)])
            cmd.extend(["--max-pages", "1"])
            cmd.extend(["--sort-type", str(config.sort_type or "0")])
        elif config.crawler_type == CrawlerTypeEnum.DETAIL:
            for aweme_id in [item.strip() for item in config.specified_ids.split(",") if item.strip()]:
                cmd.extend(["--aweme-id", aweme_id])
        elif config.crawler_type == CrawlerTypeEnum.CREATOR:
            for creator_id in [item.strip() for item in config.creator_ids.split(",") if item.strip()]:
                cmd.extend(["--creator-id", creator_id])

        if config.enable_comments:
            cmd.append("--include-comments")
        if config.crawler_type != CrawlerTypeEnum.DETAIL:
            cmd.append("--include-detail")
        if config.comment_time_filter_h > 0:
            cmd.extend(["--comment-limit", "50"])
        return cmd
