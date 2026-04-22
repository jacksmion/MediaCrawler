# -*- coding: utf-8 -*-
#
# Command builder for crawler subprocess execution.

from __future__ import annotations

from ..schemas import CrawlerStartRequest, ResolvedCrawlerConfig


class CrawlerCommandBuilder:
    """Builds `main.py` command lines from crawler start requests."""

    def build(self, config: CrawlerStartRequest | ResolvedCrawlerConfig) -> list[str]:
        """Build main.py command line arguments."""
        cmd = ["uv", "run", "python", "main.py"]

        cmd.extend(["--platform", config.platform.value])
        cmd.extend(["--lt", config.login_type.value])
        cmd.extend(["--type", config.crawler_type.value])
        cmd.extend(["--save_data_option", config.save_option.value])

        if config.crawler_type.value == "search" and config.keywords:
            cmd.extend(["--keywords", config.keywords])
        elif config.crawler_type.value == "detail" and config.specified_ids:
            cmd.extend(["--specified_id", config.specified_ids])
        elif config.crawler_type.value == "creator" and config.creator_ids:
            cmd.extend(["--creator_id", config.creator_ids])

        if config.start_page != 1:
            cmd.extend(["--start", str(config.start_page)])

        cmd.extend(["--get_comment", "true" if config.enable_comments else "false"])
        cmd.extend(["--get_sub_comment", "true" if config.enable_sub_comments else "false"])

        if config.cookies:
            cmd.extend(["--cookies", config.cookies])

        if config.sort_type:
            cmd.extend(["--sort", config.sort_type])

        if config.comment_time_filter_h > 0:
            cmd.extend(["--comment_time_filter_h", str(config.comment_time_filter_h)])

        cmd.extend(["--headless", "true" if config.headless else "false"])
        return cmd
