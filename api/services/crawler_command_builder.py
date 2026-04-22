# -*- coding: utf-8 -*-
#
# Command builder for crawler subprocess execution.

from __future__ import annotations

from ..schemas import CrawlerStartRequest, ResolvedCrawlerConfig


class CrawlerCommandBuilder:
    """Builds `run_platform_requirement.py` command lines from crawler start requests."""

    def build(self, config: CrawlerStartRequest | ResolvedCrawlerConfig) -> list[str]:
        """Build run_platform_requirement.py command line arguments."""
        cmd = ["uv", "run", "python", "run_platform_requirement.py"]

        cmd.extend(["--platform", config.platform.value])
        cmd.extend(["--login-type", config.login_type.value])
        cmd.extend(["--mode", config.crawler_type.value])
        cmd.extend(["--save-option", config.save_option.value])

        if config.crawler_type.value == "search" and config.keywords:
            for keyword in [item.strip() for item in config.keywords.split(",") if item.strip()]:
                cmd.extend(["--keyword", keyword])
        elif config.crawler_type.value == "detail" and config.specified_ids:
            for specified_id in [item.strip() for item in config.specified_ids.split(",") if item.strip()]:
                cmd.extend(["--specified-id", specified_id])
        elif config.crawler_type.value == "creator" and config.creator_ids:
            for creator_id in [item.strip() for item in config.creator_ids.split(",") if item.strip()]:
                cmd.extend(["--creator-id", creator_id])

        if config.start_page != 1:
            cmd.extend(["--start-page", str(config.start_page)])

        if config.enable_comments:
            cmd.append("--include-comments")

        if config.cookies:
            cmd.extend(["--cookies", config.cookies])

        if config.sort_type:
            cmd.extend(["--sort-type", config.sort_type])

        cmd.extend(["--headless", "true" if config.headless else "false"])
        return cmd
