from __future__ import annotations

import re

from .models import CreatorUrlInfo, VideoUrlInfo


def parse_video_info_from_url(url: str) -> VideoUrlInfo:
    if not url.startswith("http") and "kuaishou.com" not in url:
        return VideoUrlInfo(video_id=url, url_type="normal")
    match = re.search(r"/short-video/([a-zA-Z0-9_-]+)", url)
    if not match:
        raise ValueError(f"Unable to parse video ID from URL: {url}")
    return VideoUrlInfo(video_id=match.group(1), url_type="normal")


def parse_creator_info_from_url(url: str) -> CreatorUrlInfo:
    if not url.startswith("http") and "kuaishou.com" not in url:
        return CreatorUrlInfo(user_id=url)
    match = re.search(r"/profile/([a-zA-Z0-9_-]+)", url)
    if not match:
        raise ValueError(f"Unable to parse creator ID from URL: {url}")
    return CreatorUrlInfo(user_id=match.group(1))
