from __future__ import annotations

import re
import urllib.parse
from hashlib import md5
from typing import Any

from model.m_bilibili import CreatorUrlInfo, VideoUrlInfo
from tools import utils


class BilibiliSign:
    def __init__(self, img_key: str, sub_key: str):
        self.img_key = img_key
        self.sub_key = sub_key
        self.map_table = [
            46, 47, 18, 2, 53, 8, 23, 32, 15, 50, 10, 31, 58, 3, 45, 35, 27, 43, 5, 49,
            33, 9, 42, 19, 29, 28, 14, 39, 12, 38, 41, 13, 37, 48, 7, 16, 24, 55, 40,
            61, 26, 17, 0, 1, 60, 51, 30, 4, 22, 25, 54, 21, 56, 59, 6, 63, 57, 62, 11,
            36, 20, 34, 44, 52,
        ]

    def get_salt(self) -> str:
        salt = "".join((self.img_key + self.sub_key)[index] for index in self.map_table)
        return salt[:32]

    def sign(self, req_data: dict[str, Any]) -> dict[str, Any]:
        req_data = dict(req_data)
        req_data["wts"] = utils.get_unix_timestamp()
        req_data = dict(sorted(req_data.items()))
        req_data = {k: "".join(filter(lambda ch: ch not in "!'()*", str(v))) for k, v in req_data.items()}
        query = urllib.parse.urlencode(req_data)
        req_data["w_rid"] = md5((query + self.get_salt()).encode()).hexdigest()
        return req_data


def parse_video_info_from_url(url: str) -> VideoUrlInfo:
    if url.startswith("BV"):
        return VideoUrlInfo(video_id=url)
    match = re.search(r"/video/(BV[a-zA-Z0-9]+)", url)
    if not match:
        raise ValueError(f"Unable to parse video ID from URL: {url}")
    return VideoUrlInfo(video_id=match.group(1))


def parse_creator_info_from_url(url: str) -> CreatorUrlInfo:
    if url.isdigit():
        return CreatorUrlInfo(creator_id=url)
    match = re.search(r"space\.bilibili\.com/(\d+)", url)
    if not match:
        raise ValueError(f"Unable to parse creator ID from URL: {url}")
    return CreatorUrlInfo(creator_id=match.group(1))
