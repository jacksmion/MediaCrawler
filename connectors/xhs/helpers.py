from __future__ import annotations

import random
import re
import time

from model.m_xiaohongshu import CreatorUrlInfo, NoteUrlInfo
from tools.crawler_util import extract_url_params_to_dict


def base36encode(number: int, alphabet: str = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ") -> str:
    if not isinstance(number, int):
        raise TypeError("number must be an integer")
    if number == 0:
        return "0"
    sign = ""
    if number < 0:
        sign = "-"
        number = -number
    base36 = ""
    while number:
        number, i = divmod(number, 36)
        base36 = alphabet[i] + base36
    return sign + base36


def get_search_id() -> str:
    value = int(time.time() * 1000) << 64
    suffix = int(random.uniform(0, 2147483646))
    return base36encode(value + suffix)


def parse_note_info_from_note_url(url: str) -> NoteUrlInfo:
    note_id = url.split("/")[-1].split("?")[0]
    params = extract_url_params_to_dict(url)
    return NoteUrlInfo(
        note_id=note_id,
        xsec_token=params.get("xsec_token", ""),
        xsec_source=params.get("xsec_source", ""),
    )


def parse_creator_info_from_url(url: str) -> CreatorUrlInfo:
    if len(url) == 24 and all(char in "0123456789abcdef" for char in url):
        return CreatorUrlInfo(user_id=url, xsec_token="", xsec_source="")
    match = re.search(r"/user/profile/([^/?]+)", url)
    if not match:
        raise ValueError(f"Unable to parse creator info from URL: {url}")
    params = extract_url_params_to_dict(url)
    return CreatorUrlInfo(
        user_id=match.group(1),
        xsec_token=params.get("xsec_token", ""),
        xsec_source=params.get("xsec_source", ""),
    )
