# -*- coding: utf-8 -*-

from enum import Enum
from typing import Optional, Literal
from pydantic import BaseModel


class PlatformEnum(str, Enum):
    """Supported media platforms"""
    XHS = "xhs"
    DOUYIN = "dy"
    KUAISHOU = "ks"
    BILIBILI = "bili"
    WEIBO = "wb"
    TIEBA = "tieba"
    ZHIHU = "zhihu"


class LoginTypeEnum(str, Enum):
    """Login method"""
    QRCODE = "qrcode"
    PHONE = "phone"
    COOKIE = "cookie"


class CrawlerTypeEnum(str, Enum):
    """Crawler type"""
    SEARCH = "search"
    DETAIL = "detail"
    CREATOR = "creator"
    LOGIN = "login"


class SaveDataOptionEnum(str, Enum):
    """Data save option"""
    CSV = "csv"
    DB = "db"
    JSON = "json"
    JSONL = "jsonl"
    SQLITE = "sqlite"
    MONGODB = "mongodb"
    EXCEL = "excel"


class CrawlerStartRequest(BaseModel):
    """Crawler start request"""
    platform: PlatformEnum
    login_type: LoginTypeEnum = LoginTypeEnum.QRCODE
    crawler_type: CrawlerTypeEnum = CrawlerTypeEnum.SEARCH
    keywords: str = ""  # Keywords for search mode
    specified_ids: str = ""  # Post/video ID list for detail mode, comma-separated
    creator_ids: str = ""  # Creator ID list for creator mode, comma-separated
    start_page: int = 1
    enable_comments: bool = True
    enable_sub_comments: bool = False
    save_option: SaveDataOptionEnum = SaveDataOptionEnum.JSONL
    cookies: str = ""
    headless: bool = False
    sort_type: str = ""  # Sort mode for search (search mode)
    comment_time_filter_h: int = 0  # Max age of comments to crawl in hours (0 = unlimited)
    account_id: str = ""  # Which account to use for this task
    task_id: str = ""  # Optional task ID, auto-generated if empty


class ResolvedCrawlerConfig(BaseModel):
    """Final crawler config after merging request values with runtime overrides."""

    platform: PlatformEnum
    login_type: LoginTypeEnum
    crawler_type: CrawlerTypeEnum
    keywords: str = ""
    specified_ids: str = ""
    creator_ids: str = ""
    start_page: int = 1
    enable_comments: bool = True
    enable_sub_comments: bool = False
    save_option: SaveDataOptionEnum = SaveDataOptionEnum.JSONL
    cookies: str = ""
    headless: bool = False
    sort_type: str = ""
    comment_time_filter_h: int = 0
    runtime_override_keys: list[str] = []
    account_id: str = ""


class TaskStatus(BaseModel):
    """Single task status entry."""
    task_id: str
    account_id: str
    platform: str
    crawler_type: str
    status: str  # idle / running / stopping / error / completed
    started_at: Optional[str] = None


class CrawlerStatusResponse(BaseModel):
    """Crawler status response - multi-task"""
    tasks: list[TaskStatus] = []
    active_count: int = 0


class LogEntry(BaseModel):
    """Log entry"""
    id: int
    task_id: str = ""
    timestamp: str
    level: Literal["info", "warning", "error", "success", "debug"]
    message: str


class DataFileInfo(BaseModel):
    """Data file information"""
    name: str
    path: str
    size: int
    modified_at: str
    record_count: Optional[int] = None
