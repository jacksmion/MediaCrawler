"""Connector package for platform-specific crawling implementations."""

from __future__ import annotations

from typing import Any, Callable

from connectors.base.base_connector import BaseConnector
from connectors.bilibili.connector import build_bilibili_connector_from_legacy
from connectors.douyin.connector import build_douyin_connector_from_legacy
from connectors.kuaishou.connector import build_kuaishou_connector_from_legacy
from connectors.tieba.connector import build_tieba_connector_from_legacy
from connectors.weibo.connector import build_weibo_connector_from_legacy
from connectors.xhs.connector import build_xhs_connector_from_legacy
from connectors.zhihu.connector import build_zhihu_connector_from_legacy

ConnectorBuilder = Callable[[Any], BaseConnector]

CONNECTOR_BUILDERS: dict[str, ConnectorBuilder] = {
    "xhs": build_xhs_connector_from_legacy,
    "douyin": build_douyin_connector_from_legacy,
    "kuaishou": build_kuaishou_connector_from_legacy,
    "bilibili": build_bilibili_connector_from_legacy,
    "weibo": build_weibo_connector_from_legacy,
    "tieba": build_tieba_connector_from_legacy,
    "zhihu": build_zhihu_connector_from_legacy,
}


def get_connector_builder(platform_code: str) -> ConnectorBuilder:
    try:
        return CONNECTOR_BUILDERS[platform_code]
    except KeyError as exc:
        raise ValueError(f"Unsupported connector platform: {platform_code}") from exc


def build_connector_from_runtime(platform_code: str, crawler: Any) -> BaseConnector:
    return get_connector_builder(platform_code)(crawler)
