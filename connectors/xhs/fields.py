from __future__ import annotations

from enum import Enum


class SearchSortType(Enum):
    GENERAL = "general"
    MOST_POPULAR = "popularity_descending"
    LATEST = "time_descending"


class SearchNoteType(Enum):
    ALL = 0
    VIDEO = 1
    IMAGE = 2
