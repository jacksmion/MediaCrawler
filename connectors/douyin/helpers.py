from __future__ import annotations

import random
import re
from typing import Any

import execjs
from playwright.async_api import Page

import config
from .models import CreatorUrlInfo, VideoUrlInfo
from schemas.tasks.runtime import PlatformTaskRequest
from tools.crawler_util import extract_url_params_to_dict

_douyin_sign_obj = execjs.compile(open("libs/douyin.js", encoding="utf-8-sig").read())


def get_web_id() -> str:
    def _segment(value):
        if value is not None:
            return str(value ^ (int(16 * random.random()) >> (value // 4)))
        return "".join([str(int(1e7)), "-", str(int(1e3)), "-", str(int(4e3)), "-", str(int(8e3)), "-", str(int(1e11))])

    web_id = "".join(_segment(int(char)) if char in "018" else char for char in _segment(None))
    return web_id.replace("-", "")[:19]


async def get_a_bogus(url: str, params: str, post_data: dict, user_agent: str, page: Page | None = None):
    return get_a_bogus_from_js(url, params, user_agent)


def get_a_bogus_from_js(url: str, params: str, user_agent: str):
    sign_js_name = "sign_reply" if "/reply" in url else "sign_datail"
    return _douyin_sign_obj.call(sign_js_name, params, user_agent)


def parse_video_info_from_url(url: str) -> VideoUrlInfo:
    if url.isdigit():
        return VideoUrlInfo(aweme_id=url, url_type="normal")
    if "v.douyin.com" in url or (url.startswith("http") and len(url) < 50 and "video" not in url):
        return VideoUrlInfo(aweme_id="", url_type="short")
    params = extract_url_params_to_dict(url)
    modal_id = params.get("modal_id")
    if modal_id:
        return VideoUrlInfo(aweme_id=modal_id, url_type="modal")
    match = re.search(r"/video/(\d+)", url)
    if not match:
        raise ValueError(f"Unable to parse video ID from URL: {url}")
    return VideoUrlInfo(aweme_id=match.group(1), url_type="normal")


def parse_creator_info_from_url(url: str) -> CreatorUrlInfo:
    if url.startswith("MS4wLjABAAAA") or (not url.startswith("http") and "douyin.com" not in url):
        return CreatorUrlInfo(sec_user_id=url)
    match = re.search(r"/user/([^/?]+)", url)
    if not match:
        raise ValueError(f"Unable to parse creator ID from URL: {url}")
    return CreatorUrlInfo(sec_user_id=match.group(1))


def _optional_int(value: Any) -> int | None:
    if value in (None, ""):
        return None
    return int(value)


def _optional_str(value: Any) -> str | None:
    if value in (None, ""):
        return None
    return str(value)


def build_douyin_task_request(*, job_id: str, platform_code: str, task_type: str, params: dict[str, Any]) -> PlatformTaskRequest:
    if task_type == "search":
        return PlatformTaskRequest(
            job_id=job_id,
            platform_code=platform_code,
            task_kind="search",
            payload={
                "keyword": str(params["keyword"]),
                "page": int(params.get("page", 1)),
                "page_size": int(params.get("page_size", 15)),
                "cursor": str(params.get("search_id", "")),
                "filters": {
                    "publish_time": _optional_str(params.get("publish_time")) or str(config.PUBLISH_TIME_TYPE),
                    "sort_type": _optional_str(params.get("sort_type")) or str(config.SEARCH_SORT_TYPE),
                    "search_id": str(params.get("search_id", "")),
                },
            },
        )
    if task_type == "detail":
        aweme_id = str(params.get("aweme_id") or params.get("content_id") or "")
        if not aweme_id:
            raise ValueError("Douyin detail task requires aweme_id or content_id")
        return PlatformTaskRequest(
            job_id=job_id,
            platform_code=platform_code,
            task_kind="detail",
            payload={"content_id": aweme_id},
        )
    if task_type == "comments":
        aweme_id = str(params.get("aweme_id") or params.get("content_id") or "")
        if not aweme_id:
            raise ValueError("Douyin comments task requires aweme_id or content_id")
        comments_limit = _optional_int(params.get("limit")) or config.CRAWLER_MAX_COMMENTS_COUNT_SINGLENOTES
        return PlatformTaskRequest(
            job_id=job_id,
            platform_code=platform_code,
            task_kind="comments",
            payload={"content_id": aweme_id, "cursor": params.get("cursor", 0), "limit": comments_limit},
        )
    if task_type == "creator":
        creator_id = str(params.get("creator_id") or "")
        if not creator_id:
            raise ValueError("Douyin creator task requires creator_id")
        return PlatformTaskRequest(
            job_id=job_id,
            platform_code=platform_code,
            task_kind="creator",
            payload={"creator_id": creator_id},
        )
    if task_type == "creator_contents":
        creator_id = str(params.get("creator_id") or "")
        if not creator_id:
            raise ValueError("Douyin creator_contents task requires creator_id")
        return PlatformTaskRequest(
            job_id=job_id,
            platform_code=platform_code,
            task_kind="creator_contents",
            payload={
                "creator_id": creator_id,
                "cursor": _optional_str(params.get("cursor")) or "",
                "limit": int(params.get("limit", 18)),
            },
        )
    raise ValueError(f"Unsupported Douyin task type: {task_type}")


def build_douyin_failure_details(*, task_type: str, params: dict[str, Any], error_code: str) -> dict[str, Any]:
    details: dict[str, Any] = {"risk_type": error_code}
    if task_type == "search":
        details.update(
            {
                "keyword": params.get("keyword"),
                "page": params.get("page"),
                "search_id": params.get("search_id", ""),
            }
        )
    elif task_type in {"detail", "comments"}:
        details["aweme_id"] = params.get("aweme_id") or params.get("content_id")
    elif task_type == "creator":
        details["creator_id"] = params.get("creator_id")
    elif task_type == "creator_contents":
        details.update({"creator_id": params.get("creator_id"), "cursor": params.get("cursor", "")})
    return details
