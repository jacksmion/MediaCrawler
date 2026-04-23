# -*- coding: utf-8 -*-

from __future__ import annotations

import argparse
import io
from dataclasses import asdict, is_dataclass
from datetime import date, datetime
import json
from pathlib import Path
import sys
from typing import Any

if sys.stdout and hasattr(sys.stdout, "buffer"):
    if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
if sys.stderr and hasattr(sys.stderr, "buffer"):
    if sys.stderr.encoding and sys.stderr.encoding.lower() != "utf-8":
        sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

import config
from application.services.crawler_runtime import CrawlerFactory, cleanup_runtime
from application.services.requirement_mapper import (
    apply_runtime_request_overrides,
    build_requirement_from_request_payload,
)
from schemas.tasks.platform_mappings import (
    PLATFORM_CREATOR_LIST_ATTR,
    PLATFORM_DETAIL_LIST_ATTR,
    PLATFORM_RUNNER_MODE_ATTR,
    PLATFORM_SEARCH_PAGE_HINTS,
)
from tools.app_runner import run


crawler = None


def _json_default(value: Any) -> Any:
    if is_dataclass(value):
        return asdict(value)
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, set):
        return list(value)
    raise TypeError(f"Object of type {value.__class__.__name__} is not JSON serializable")


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run a migrated platform crawl entry.")
    parser.add_argument("request", nargs="?", help="JSON file path or JSON string request payload.")
    parser.add_argument("-j", "--request-json", help="Serialized resolved crawler config payload.")
    parser.add_argument("-p", "--platform", choices=list(PLATFORM_RUNNER_MODE_ATTR.keys()))
    parser.add_argument("-m", "--mode", choices=["search", "detail", "creator", "login"])
    parser.add_argument("-l", "--login-type", choices=["qrcode", "phone", "cookie"], help="Login type override.")
    parser.add_argument(
        "-o",
        "--save-option",
        choices=["csv", "db", "json", "jsonl", "sqlite", "mongodb", "excel", "postgres"],
        help="Data save option override.",
    )
    parser.add_argument("--cookies", default="", help="Cookie string override.")
    parser.add_argument("--headless", choices=["true", "false"], help="Headless mode override.")
    parser.add_argument("-k", "--keyword", action="append", default=[], help="Search keyword. Repeatable.")
    parser.add_argument("-i", "--specified-id", action="append", default=[], help="Detail-mode item id/url. Repeatable.")
    parser.add_argument("-u", "--creator-id", action="append", default=[], help="Creator-mode item id/url. Repeatable.")
    parser.add_argument("-s", "--start-page", type=int, default=1, help="Start page for search mode.")
    parser.add_argument("-n", "--max-pages", type=int, default=1, help="Max pages for search mode.")
    parser.add_argument("-t", "--sort-type", default="", help="Platform-specific search sort/type override.")
    parser.add_argument("-c", "--include-comments", action="store_true", help="Enable comments crawling.")
    parser.add_argument("--comment-limit", type=int, help="Single-note comment limit override.")
    args = parser.parse_args()
    if args.request and not args.request_json:
        args.request_json = args.request
    if not args.request_json:
        if not args.platform or not args.mode:
            parser.error("--platform and --mode are required unless --request-json is provided")
    return args


def _split_csv(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if not value:
        return []
    return [item.strip() for item in str(value).split(",") if item.strip()]


def _parse_request_payload(args: argparse.Namespace) -> dict[str, Any]:
    if not args.request_json:
        return {}
    raw_value = str(args.request_json).strip()
    if not raw_value:
        return {}

    request_path = Path(raw_value)
    if request_path.exists() and request_path.is_file():
        payload = json.loads(request_path.read_text(encoding="utf-8"))
    else:
        payload = json.loads(raw_value)

    if not isinstance(payload, dict):
        raise ValueError("--request-json must decode to an object")
    return payload


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
        config.CRAWLER_MAX_NOTES_COUNT = max(1, int(args.max_pages)) * PLATFORM_SEARCH_PAGE_HINTS.get(args.platform, 20)
        _apply_search_sort(args.platform, args.sort_type)
    elif args.mode == "detail":
        specified_ids = [item.strip() for item in args.specified_id if item.strip()]
        if not specified_ids:
            raise ValueError("--mode detail requires at least one --specified-id")
        setattr(config, PLATFORM_DETAIL_LIST_ATTR[args.platform], specified_ids)
    elif args.mode == "creator":
        creator_ids = [item.strip() for item in args.creator_id if item.strip()]
        if not creator_ids:
            raise ValueError("--mode creator requires at least one --creator-id")
        setattr(config, PLATFORM_CREATOR_LIST_ATTR[args.platform], creator_ids)


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
    request_payload = _parse_request_payload(args)
    if request_payload:
        apply_runtime_request_overrides(request_payload)
        crawler = CrawlerFactory.create_crawler(platform=str(request_payload["platform"]))
        if str(request_payload["crawler_type"]) == "login":
            await crawler.start()
            print(
                json.dumps(
                    {
                        "mode": "login_entry",
                        "request": request_payload,
                    },
                    ensure_ascii=False,
                    indent=2,
                    default=_json_default,
                )
            )
            return
        requirement = build_requirement_from_request_payload(request_payload, source="webui_api")
        result = await crawler.start_with_requirement(requirement)
        summary = {
            "mode": "requirement_entry",
            "request": request_payload,
            "requirement": asdict(requirement),
            "result": result,
        }
        print(json.dumps(summary, ensure_ascii=False, indent=2, default=_json_default))
        return

    _apply_runtime_overrides(args)
    crawler = CrawlerFactory.create_crawler(platform=config.PLATFORM)
    await crawler.start()
    print(json.dumps(_summarize(args), ensure_ascii=False, indent=2, default=_json_default))


async def async_cleanup() -> None:
    global crawler
    await cleanup_runtime(crawler)


if __name__ == "__main__":
    run(main, async_cleanup, cleanup_timeout_seconds=15.0)
