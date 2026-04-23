from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import config

from schemas.tasks.platform_mappings import (
    PLATFORM_CREATOR_LIST_ATTR,
    PLATFORM_DETAIL_LIST_ATTR,
    PLATFORM_SEARCH_SORT_ATTR,
)
from schemas.tasks.requirements import CrawlRequirement


def _split_csv(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


def _normalize_value(value: Any) -> Any:
    if hasattr(value, "value"):
        return value.value
    return value


def _get_value(payload: Mapping[str, Any] | Any, key: str, default: Any = None) -> Any:
    if isinstance(payload, Mapping):
        value = payload.get(key, default)
    else:
        value = getattr(payload, key, default)
    return _normalize_value(value)


REQUEST_FIELD_TO_CONFIG_KEY = {
    "platform": "PLATFORM",
    "login_type": "LOGIN_TYPE",
    "crawler_type": "CRAWLER_TYPE",
    "keywords": "KEYWORDS",
    "start_page": "START_PAGE",
    "enable_comments": "ENABLE_GET_COMMENTS",
    "enable_sub_comments": "ENABLE_GET_SUB_COMMENTS",
    "save_option": "SAVE_DATA_OPTION",
    "cookies": "COOKIES",
    "headless": "HEADLESS",
    "comment_time_filter_h": "COMMENT_TIME_FILTER_H",
}


def _platform_config_keys(platform: str) -> dict[str, str]:
    keys: dict[str, str] = {}
    detail_key = PLATFORM_DETAIL_LIST_ATTR.get(platform)
    if detail_key:
        keys["specified_ids"] = detail_key
    creator_key = PLATFORM_CREATOR_LIST_ATTR.get(platform)
    if creator_key:
        keys["creator_ids"] = creator_key
    sort_key = PLATFORM_SEARCH_SORT_ATTR.get(platform)
    if sort_key:
        keys["sort_type"] = sort_key
    return keys


def _adapt_runtime_value(field_name: str, value: Any) -> Any:
    if field_name in {"platform", "login_type", "crawler_type", "save_option"}:
        return value
    if field_name in {"specified_ids", "creator_ids"}:
        if isinstance(value, list):
            return ",".join(str(item) for item in value)
        return value
    if field_name == "sort_type":
        return str(value)
    return value


def merge_request_with_runtime_overrides(
    request_payload: Mapping[str, Any] | Any,
    merged_config: Mapping[str, Any],
    *,
    override_keys: Mapping[str, Any] | None = None,
    explicit_fields: set[str] | None = None,
) -> dict[str, Any]:
    resolved_data = {
        key: _normalize_value(value)
        for key, value in (
            request_payload.items()
            if isinstance(request_payload, Mapping)
            else vars(request_payload).items()
        )
        if not key.startswith("_")
    }

    if explicit_fields is None:
        if hasattr(request_payload, "model_fields_set"):
            explicit_fields = set(getattr(request_payload, "model_fields_set"))
        else:
            explicit_fields = set(resolved_data)

    applied_override_keys: list[str] = []
    runtime_override_key_set = set(override_keys or {})

    for field_name, config_key in REQUEST_FIELD_TO_CONFIG_KEY.items():
        if field_name in explicit_fields or config_key not in merged_config:
            continue
        override_value = _adapt_runtime_value(field_name, merged_config[config_key])
        if override_value is None:
            continue
        resolved_data[field_name] = override_value
        if config_key in runtime_override_key_set:
            applied_override_keys.append(config_key)

    platform_code = str(_normalize_value(resolved_data["platform"]))
    for field_name, config_key in _platform_config_keys(platform_code).items():
        if field_name in explicit_fields or config_key not in merged_config:
            continue
        override_value = _adapt_runtime_value(field_name, merged_config[config_key])
        if override_value is None:
            continue
        resolved_data[field_name] = override_value
        if config_key in runtime_override_key_set:
            applied_override_keys.append(config_key)

    resolved_data["runtime_override_keys"] = sorted(set(applied_override_keys))
    return resolved_data


def apply_runtime_request_overrides(payload: Mapping[str, Any] | Any) -> None:
    platform = str(_get_value(payload, "platform"))
    mode = str(_get_value(payload, "crawler_type"))
    config.PLATFORM = platform
    config.CRAWLER_TYPE = mode

    login_type = _get_value(payload, "login_type")
    if login_type:
        config.LOGIN_TYPE = str(login_type)

    save_option = _get_value(payload, "save_option")
    if save_option:
        config.SAVE_DATA_OPTION = str(save_option)

    cookies = _get_value(payload, "cookies")
    if cookies:
        config.COOKIES = str(cookies)

    headless = _get_value(payload, "headless")
    if headless is not None:
        config.HEADLESS = bool(headless)
        config.CDP_HEADLESS = bool(headless)

    config.ENABLE_GET_COMMENTS = bool(_get_value(payload, "enable_comments", False))

    comment_limit = _get_value(payload, "comment_limit")
    if comment_limit is not None:
        config.CRAWLER_MAX_COMMENTS_COUNT_SINGLENOTES = int(comment_limit)

    comment_time_filter_h = _get_value(payload, "comment_time_filter_h")
    if comment_time_filter_h is not None:
        config.COMMENT_TIME_FILTER_H = int(comment_time_filter_h)


def build_requirement_from_request_payload(
    payload: Mapping[str, Any] | Any,
    *,
    source: str = "request",
    max_pages_default: int = 1,
) -> CrawlRequirement:
    platform = str(_get_value(payload, "platform"))
    mode = str(_get_value(payload, "crawler_type"))
    keywords = _split_csv(str(_get_value(payload, "keywords", "")))
    specified_ids = _split_csv(str(_get_value(payload, "specified_ids", "")))
    creator_ids = _split_csv(str(_get_value(payload, "creator_ids", "")))
    shared = {
        "mode": mode,
        "start_page": int(_get_value(payload, "start_page", 1)),
        "max_pages": int(_get_value(payload, "max_pages", max_pages_default)),
        "include_comments": bool(_get_value(payload, "enable_comments", False)),
        "comment_limit": _get_value(payload, "comment_limit"),
        "metadata": {"source": source},
    }

    sort_type = _get_value(payload, "sort_type")

    if platform == "xhs":
        return CrawlRequirement(
            platform_code=platform,
            keywords=keywords,
            note_urls=specified_ids,
            creator_urls=creator_ids,
            sort_type=str(sort_type) if sort_type else None,
            **shared,
        )
    if platform == "dy":
        return CrawlRequirement(
            platform_code=platform,
            keywords=keywords,
            aweme_ids=specified_ids,
            creator_ids=creator_ids,
            sort_type=str(sort_type) if sort_type else None,
            **shared,
        )
    if platform == "wb":
        return CrawlRequirement(
            platform_code=platform,
            keywords=keywords,
            note_ids=specified_ids,
            creator_ids=creator_ids,
            search_type=str(sort_type) if sort_type else None,
            **shared,
        )
    if platform == "bili":
        return CrawlRequirement(
            platform_code=platform,
            keywords=keywords,
            video_ids=specified_ids,
            creator_ids=creator_ids,
            **shared,
        )
    if platform == "ks":
        return CrawlRequirement(
            platform_code=platform,
            keywords=keywords,
            video_ids=specified_ids,
            creator_ids=creator_ids,
            **shared,
        )
    if platform == "tieba":
        return CrawlRequirement(
            platform_code=platform,
            keywords=keywords,
            note_ids=specified_ids,
            creator_urls=creator_ids,
            **shared,
        )
    if platform == "zhihu":
        return CrawlRequirement(
            platform_code=platform,
            keywords=keywords,
            note_urls=specified_ids,
            creator_urls=creator_ids,
            **shared,
        )
    raise NotImplementedError(f"Requirement entry is not supported for platform: {platform}")


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
