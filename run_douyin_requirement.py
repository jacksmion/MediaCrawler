# -*- coding: utf-8 -*-

from __future__ import annotations

import argparse
import io
import json
import sys
from pathlib import Path
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
from media_platform.douyin import DouYinCrawler
from schemas.tasks.requirements import DouyinCrawlRequirement
from tools.app_runner import run


crawler: DouYinCrawler | None = None


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run a requirement-driven Douyin crawl.")
    parser.add_argument("--file", dest="file_path", help="Path to a JSON requirement file.")
    parser.add_argument("--mode", choices=["search", "detail", "creator"], help="Requirement mode.")
    parser.add_argument("--login-type", choices=["qrcode", "phone", "cookie"], help="Douyin login type override.")
    parser.add_argument(
        "--save-option",
        choices=["csv", "db", "json", "jsonl", "sqlite", "mongodb", "excel", "postgres"],
        help="Data save option override.",
    )
    parser.add_argument("--cookies", default="", help="Cookie string override.")
    parser.add_argument("--headless", choices=["true", "false"], help="Headless mode override.")
    parser.add_argument("--keyword", action="append", default=[], help="Search keyword. Repeatable.")
    parser.add_argument("--aweme-id", action="append", default=[], help="Douyin aweme id. Repeatable.")
    parser.add_argument("--creator-id", action="append", default=[], help="Douyin creator id. Repeatable.")
    parser.add_argument("--start-page", type=int, default=1, help="Start page for search mode.")
    parser.add_argument("--max-pages", type=int, default=1, help="Max pages for search mode.")
    parser.add_argument("--page-size", type=int, default=15, help="Page size for search mode.")
    parser.add_argument("--publish-time", help="Douyin publish_time filter value.")
    parser.add_argument("--sort-type", help="Douyin sort_type filter value.")
    parser.add_argument("--include-detail", action="store_true", help="Fetch details after base tasks.")
    parser.add_argument("--include-comments", action="store_true", help="Fetch comments after base tasks.")
    parser.add_argument("--comment-limit", type=int, help="Comment limit for follow-up comment tasks.")
    parser.add_argument(
        "--creator-contents-limit",
        type=int,
        default=18,
        help="Page size for creator contents mode.",
    )
    parser.add_argument(
        "--creator-max-pages",
        type=int,
        default=1,
        help="Number of creator contents tasks to plan.",
    )
    return parser.parse_args()


def _apply_runtime_overrides(args: argparse.Namespace) -> None:
    """Apply command-line runtime overrides to the global config module."""
    if args.login_type:
        config.LOGIN_TYPE = args.login_type
    if args.save_option:
        config.SAVE_DATA_OPTION = args.save_option
    if args.cookies:
        config.COOKIES = args.cookies
    if args.headless is not None:
        config.HEADLESS = args.headless == "true"


def _load_requirement(args: argparse.Namespace) -> DouyinCrawlRequirement:
    if args.file_path:
        file_path = Path(args.file_path)
        payload = json.loads(file_path.read_text(encoding="utf-8"))
        return DouyinCrawlRequirement(**payload)

    if not args.mode:
        raise ValueError("Either --file or --mode must be provided.")

    return DouyinCrawlRequirement(
        mode=args.mode,
        keywords=args.keyword,
        aweme_ids=args.aweme_id,
        creator_ids=args.creator_id,
        start_page=args.start_page,
        max_pages=args.max_pages,
        page_size=args.page_size,
        publish_time=args.publish_time,
        sort_type=args.sort_type,
        include_comments=args.include_comments,
        include_detail=args.include_detail,
        comment_limit=args.comment_limit,
        creator_contents_limit=args.creator_contents_limit,
        creator_max_pages=args.creator_max_pages,
    )


def _summarize_result(result: dict[str, Any]) -> dict[str, Any]:
    base_results = result.get("base_results", [])
    derived_results = result.get("derived_results", [])
    return {
        "planned_task_count": result.get("planned_task_count", 0),
        "base_result_count": len(base_results),
        "derived_result_count": len(derived_results),
        "base_result_keys": [sorted(item.keys()) for item in base_results[:5]],
        "derived_result_keys": [sorted(item.keys()) for item in derived_results[:5]],
    }


async def main() -> None:
    global crawler
    args = _parse_args()
    _apply_runtime_overrides(args)
    requirement = _load_requirement(args)
    crawler = DouYinCrawler()
    result = await crawler.start_with_requirement(requirement)
    print(json.dumps(_summarize_result(result), ensure_ascii=False, indent=2))


async def async_cleanup() -> None:
    global crawler
    if crawler:
        await crawler.close()
    if config.SAVE_DATA_OPTION in ("db", "sqlite"):
        await db.close()


if __name__ == "__main__":
    run(main, async_cleanup, cleanup_timeout_seconds=15.0)
