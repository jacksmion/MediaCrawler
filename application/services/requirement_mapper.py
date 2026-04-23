from __future__ import annotations

import config

from schemas.tasks.requirements import CrawlRequirement


def _split_csv(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


def build_requirement_from_runtime_config(platform_code: str) -> CrawlRequirement:
    mode = str(config.CRAWLER_TYPE)
    common = {
        "platform_code": platform_code,
        "mode": mode,
        "include_comments": bool(config.ENABLE_GET_COMMENTS),
        "comment_limit": int(config.CRAWLER_MAX_COMMENTS_COUNT_SINGLENOTES),
    }

    if platform_code == "xhs":
        if mode == "search":
            return CrawlRequirement(
                **common,
                keywords=_split_csv(config.KEYWORDS),
                start_page=int(config.START_PAGE),
                max_pages=max(1, int(config.CRAWLER_MAX_NOTES_COUNT) // 20),
                page_size=20,
                sort_type=str(config.SORT_TYPE or "general"),
                creator_contents_limit=30,
            )
        if mode == "detail":
            return CrawlRequirement(
                **common,
                note_urls=list(getattr(config, "XHS_SPECIFIED_NOTE_URL_LIST", [])),
                creator_contents_limit=30,
            )
        return CrawlRequirement(
            **common,
            creator_urls=list(getattr(config, "XHS_CREATOR_ID_LIST", [])),
            creator_contents_limit=30,
        )

    if platform_code == "douyin":
        if mode == "search":
            return CrawlRequirement(
                **common,
                keywords=_split_csv(config.KEYWORDS),
                start_page=int(config.START_PAGE),
                max_pages=max(1, int(config.CRAWLER_MAX_NOTES_COUNT) // 15),
                page_size=15,
                sort_type=str(config.SEARCH_SORT_TYPE),
                publish_time=str(config.PUBLISH_TIME_TYPE),
                creator_contents_limit=18,
            )
        if mode == "detail":
            return CrawlRequirement(
                **common,
                aweme_ids=list(getattr(config, "DY_SPECIFIED_ID_LIST", [])),
                creator_contents_limit=18,
            )
        return CrawlRequirement(
            **common,
            creator_ids=list(getattr(config, "DY_CREATOR_ID_LIST", [])),
            creator_contents_limit=18,
        )

    if platform_code == "kuaishou":
        if mode == "search":
            return CrawlRequirement(
                **common,
                keywords=_split_csv(config.KEYWORDS),
                start_page=int(config.START_PAGE),
                max_pages=max(1, int(config.CRAWLER_MAX_NOTES_COUNT) // 20),
                page_size=20,
                creator_contents_limit=20,
            )
        if mode == "detail":
            return CrawlRequirement(
                **common,
                video_ids=list(getattr(config, "KS_SPECIFIED_ID_LIST", [])),
                creator_contents_limit=20,
            )
        return CrawlRequirement(
            **common,
            creator_ids=list(getattr(config, "KS_CREATOR_ID_LIST", [])),
            creator_contents_limit=20,
        )

    if platform_code == "bilibili":
        if mode == "search":
            return CrawlRequirement(
                **common,
                keywords=_split_csv(config.KEYWORDS),
                start_page=int(config.START_PAGE),
                max_pages=max(1, int(config.CRAWLER_MAX_NOTES_COUNT) // 20),
                page_size=20,
                creator_contents_limit=30,
            )
        if mode == "detail":
            return CrawlRequirement(
                **common,
                video_ids=list(getattr(config, "BILI_SPECIFIED_ID_LIST", [])),
                creator_contents_limit=30,
            )
        return CrawlRequirement(
            **common,
            creator_ids=list(getattr(config, "BILI_CREATOR_ID_LIST", [])),
            creator_contents_limit=30,
        )

    if platform_code == "weibo":
        if mode == "search":
            return CrawlRequirement(
                **common,
                keywords=_split_csv(config.KEYWORDS),
                start_page=int(config.START_PAGE),
                max_pages=max(1, int(config.CRAWLER_MAX_NOTES_COUNT) // 10),
                search_type=str(config.WEIBO_SEARCH_TYPE or "default"),
                creator_contents_limit=10,
            )
        if mode == "detail":
            return CrawlRequirement(
                **common,
                note_ids=list(getattr(config, "WEIBO_SPECIFIED_ID_LIST", [])),
                creator_contents_limit=10,
            )
        return CrawlRequirement(
            **common,
            creator_ids=list(getattr(config, "WEIBO_CREATOR_ID_LIST", [])),
            creator_contents_limit=10,
        )

    if platform_code == "tieba":
        if mode == "search":
            return CrawlRequirement(
                **common,
                keywords=_split_csv(config.KEYWORDS),
                start_page=int(config.START_PAGE),
                max_pages=max(1, int(config.CRAWLER_MAX_NOTES_COUNT) // 10),
                page_size=10,
                creator_contents_limit=20,
            )
        if mode == "detail":
            return CrawlRequirement(
                **common,
                note_ids=list(getattr(config, "TIEBA_SPECIFIED_ID_LIST", [])),
                page_size=10,
                creator_contents_limit=20,
            )
        return CrawlRequirement(
            **common,
            creator_urls=list(getattr(config, "TIEBA_CREATOR_URL_LIST", [])),
            page_size=10,
            creator_contents_limit=20,
        )

    if platform_code == "zhihu":
        if mode == "search":
            return CrawlRequirement(
                **common,
                keywords=_split_csv(config.KEYWORDS),
                start_page=int(config.START_PAGE),
                max_pages=max(1, int(config.CRAWLER_MAX_NOTES_COUNT) // 20),
                page_size=20,
                creator_contents_limit=20,
            )
        if mode == "detail":
            return CrawlRequirement(
                **common,
                note_urls=list(getattr(config, "ZHIHU_SPECIFIED_ID_LIST", [])),
                creator_contents_limit=20,
            )
        return CrawlRequirement(
            **common,
            creator_urls=list(getattr(config, "ZHIHU_CREATOR_URL_LIST", [])),
            creator_contents_limit=20,
        )

    raise ValueError(f"Unsupported runtime requirement platform: {platform_code}")
