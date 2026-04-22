from __future__ import annotations

from enum import Enum


class SearchOrderType(Enum):
    DEFAULT = ""
    MOST_CLICK = "click"
    LAST_PUBLISH = "pubdate"
    MOST_DANMU = "dm"
    MOST_MARK = "stow"


class CommentOrderType(Enum):
    DEFAULT = 0
    MIXED = 1
    TIME = 2
