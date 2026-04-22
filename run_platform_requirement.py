# -*- coding: utf-8 -*-

from __future__ import annotations

import argparse
import io
import json
import sys
from typing import Any

if sys.stdout and hasattr(sys.stdout, "buffer"):
    if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
if sys.stderr and hasattr(sys.stderr, "buffer"):
    if sys.stderr.encoding and sys.stderr.encoding.lower() != "utf-8":
        sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

import asyncio

import config
from database import db
from main import CrawlerFactory
from tools.app_runner import run


crawler = None

PLATFORM_RUNNER_MODE_ATTR = {
    "xhs": "XHS_PLATFORM_RUNNER_MODE",
    "dy": "DOUYIN_PLATFORM_RUNNER_MODE",
    "ks": "KUAISHOU_PLATFORM_RUNNER_MODE",
    "bili": "BILIBILI_PLATFORM_RUNNER_MODE",
    "wb": "WEIBO_PLATFORM_RUNNER_MODE",
    "tieba": "TIEBA_PLATFORM_RUNNER_MODE",
    "zhihu": "ZHIHU_PLATFORM_RUNNER_MODE",
}

DETAIL_LIST_ATTR = {
    "xhs": "XHS_SPECIFIED_NOTE_URL_LIST",
    "dy": "DY_SPECIFIED_ID_LIST",
    "ks": "KS_SPECIFIED_ID_LIST",
    "bili": "BILI_SPECIFIED_ID_LIST",
    "wb": "WEIBO_SPECIFIED_ID_LIST",
    "tieba": "TIEBA_SPECIFIED_ID_LIST",
    "zhihu": "ZHIHU_SPECIFIED_ID_LIST",
}

CREATOR_LIST_ATTR = {
    "xhs": "XHS_CREATOR_ID_LIST",
    "dy": "DY_CREATOR_ID_LIST",
    "ks": "KS_CREATOR_ID_LIST",
    "bili": "BILI_CREATOR_ID_LIST",
    "wb": "WEIBO_CREATOR_ID_LIST",
    "tieba": "TIEBA_CREATOR_URL_LIST",
    "zhihu": "ZHIHU_CREATOR_URL_LIST",
}

SEARCH_PAGE_HINTS = {
    "xhs": 20,
    "dy": 15,
    "ks": 20,
    "bili": 20,
    "wb": 10,
    "tieba": 10,
    "zhihu": 20,
}


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run a migrated platform crawl entry.")
    parser.add_argument("--platform", choices=list(PLATFORM_RUNNER_MODE_ATTR.keys()), required=True)
    parser.add_argument("--mode", choices=["search", "detail", "creator"], required=True)
    parser.add_argument("--login-type", choices=["qrcode", "phone", "cookie"], help="Login type override.")
    parser.add_argument(
        "--save-option",
        choices=["csv", "db", "json", "jsonl", "sqlite", "mongodb", "excel", "postgres"],
        help="Data save option override.",
    )
    parser.add_argument("--cookies", default="", help="Cookie string override.")
    parser.add_argument("--headless", choices=["true", "false"], help="Headless mode override.")
    parser.add_argument("--keyword", action="append", default=[], help="Search keyword. Repeatable.")
    parser.add_argument("--specified-id", action="append", default=[], help="Detail-mode item id/url. Repeatable.")
    parser.add_argument("--creator-id", action="append", default=[], help="Creator-mode item id/url. Repeatable.")
    parser.add_argument("--start-page", type=int, default=1, help="Start page for search mode.")
    parser.add_argument("--max-pages", type=int, default=1, help="Max pages for search mode.")
    parser.add_argument("--sort-type", default="", help="Platform-specific search sort/type override.")
    parser.add_argument("--include-comments", action="store_true", help="Enable comments crawling.")
    parser.add_argument("--comment-limit", type=int, help="Single-note comment limit override.")
    return parser.parse_args()


def _apply_runtime_overrides(args: argparse.Namespace) -> None:
    config.PLATFORM = args.platform
    config.CRAWLER_TYPE = args.mode
    if args.login_type:
        config.LOGIN_TYPE = args.login_type
    if args.save_option:
        config.SAVE_DATA_OPTION = args.save_option
    if args.cookies:
        config.COOKIES = args.cookies
    if args.headless is not None:
        config.HEADLESS = args.headless == "true"
        config.CDP_HEADLESS = config.HEADLESS

    config.ENABLE_GET_COMMENTS = bool(args.include_comments)
    if args.comment_limit is not None:
        config.CRAWLER_MAX_COMMENTS_COUNT_SINGLENOTES = int(args.comment_limit)

    setattr(config, PLATFORM_RUNNER_MODE_ATTR[args.platform], "all")

    if args.mode == "search":
        keywords = [item.strip() for item in args.keyword if item.strip()]
        if not keywords:
            raise ValueError("--mode search requires at least one --keyword")
        config.KEYWORDS = ",".join(keywords)
        config.START_PAGE = int(args.start_page)
        config.CRAWLER_MAX_NOTES_COUNT = max(1, int(args.max_pages)) * SEARCH_PAGE_HINTS.get(args.platform, 20)
        _apply_search_sort(args.platform, args.sort_type)
    elif args.mode == "detail":
        specified_ids = [item.strip() for item in args.specified_id if item.strip()]
        if not specified_ids:
            raise ValueError("--mode detail requires at least one --specified-id")
        setattr(config, DETAIL_LIST_ATTR[args.platform], specified_ids)
    elif args.mode == "creator":
        creator_ids = [item.strip() for item in args.creator_id if item.strip()]
        if not creator_ids:
            raise ValueError("--mode creator requires at least one --creator-id")
        setattr(config, CREATOR_LIST_ATTR[args.platform], creator_ids)


def _apply_search_sort(platform: str, sort_type: str) -> None:
    if not sort_type:
        return
    if platform == "xhs":
        config.SORT_TYPE = sort_type
    elif platform == "dy":
        try:
            config.SEARCH_SORT_TYPE = int(sort_type)
        except ValueError:
            config.SEARCH_SORT_TYPE = 0
    elif platform == "wb":
        config.WEIBO_SEARCH_TYPE = sort_type
    elif platform == "bili":
        config.BILI_SEARCH_MODE = sort_type


def _summarize(args: argparse.Namespace) -> dict[str, Any]:
    return {
        "platform": args.platform,
        "mode": args.mode,
        "runner_mode": getattr(config, PLATFORM_RUNNER_MODE_ATTR[args.platform]),
        "keywords": [item.strip() for item in args.keyword if item.strip()],
        "specified_ids": [item.strip() for item in args.specified_id if item.strip()],
        "creator_ids": [item.strip() for item in args.creator_id if item.strip()],
        "enable_comments": config.ENABLE_GET_COMMENTS,
        "start_page": config.START_PAGE,
        "max_notes_count": config.CRAWLER_MAX_NOTES_COUNT,
        "save_option": config.SAVE_DATA_OPTION,
    }


async def main() -> None:
    global crawler
    args = _parse_args()
    _apply_runtime_overrides(args)
    crawler = CrawlerFactory.create_crawler(platform=config.PLATFORM)
    await crawler.start()
    print(json.dumps(_summarize(args), ensure_ascii=False, indent=2))


async def async_cleanup() -> None:
    global crawler
    if crawler and hasattr(crawler, "close"):
        await crawler.close()
    if config.SAVE_DATA_OPTION in ("db", "sqlite"):
        await db.close()


if __name__ == "__main__":
    run(main, async_cleanup, cleanup_timeout_seconds=15.0)
