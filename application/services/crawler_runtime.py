# -*- coding: utf-8 -*-
#
# Shared crawler runtime helpers for CLI and requirement-based entrypoints.

from __future__ import annotations

from typing import Type

import config
from tools.async_file_writer import AsyncFileWriter
from var import crawler_type_var
from .contracts import AbstractCrawler
from runtime.storage import ExcelStoreBase, close_storage_backends
from .connector_crawlers import (
    BilibiliConnectorCrawler,
    DouyinConnectorCrawler,
    KuaishouConnectorCrawler,
    TiebaConnectorCrawler,
    WeiboConnectorCrawler,
    XhsConnectorCrawler,
    ZhihuConnectorCrawler,
)


class CrawlerFactory:
    CRAWLERS: dict[str, Type[AbstractCrawler]] = {
        "xhs": XhsConnectorCrawler,
        "dy": DouyinConnectorCrawler,
        "ks": KuaishouConnectorCrawler,
        "bili": BilibiliConnectorCrawler,
        "wb": WeiboConnectorCrawler,
        "tieba": TiebaConnectorCrawler,
        "zhihu": ZhihuConnectorCrawler,
    }

    @staticmethod
    def create_crawler(platform: str) -> AbstractCrawler:
        crawler_class = CrawlerFactory.CRAWLERS.get(platform)
        if not crawler_class:
            supported = ", ".join(sorted(CrawlerFactory.CRAWLERS))
            raise ValueError(f"Invalid media platform: {platform!r}. Supported: {supported}")
        return crawler_class()


def flush_excel_if_needed() -> None:
    if config.SAVE_DATA_OPTION != "excel":
        return

    try:
        ExcelStoreBase.flush_all()
        print("[Main] Excel files saved successfully")
    except Exception as e:
        print(f"[Main] Error flushing Excel data: {e}")


async def generate_wordcloud_if_needed() -> None:
    if config.SAVE_DATA_OPTION not in ("json", "jsonl") or not config.ENABLE_GET_WORDCLOUD:
        return

    try:
        file_writer = AsyncFileWriter(
            platform=config.PLATFORM,
            crawler_type=crawler_type_var.get(),
        )
        await file_writer.generate_wordcloud_from_comments()
    except Exception as e:
        print(f"[Main] Error generating wordcloud: {e}")


async def cleanup_runtime(crawler: AbstractCrawler | None) -> None:
    if crawler:
        await crawler.close()

    if config.SAVE_DATA_OPTION in ("db", "sqlite", "postgres", "mongodb"):
        await close_storage_backends()
