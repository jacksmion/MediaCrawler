from __future__ import annotations

import random
import re

import execjs
from playwright.async_api import Page

from model.m_douyin import CreatorUrlInfo, VideoUrlInfo
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
