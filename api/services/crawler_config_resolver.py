# -*- coding: utf-8 -*-
#
# Runtime-aware crawler config resolver.

from __future__ import annotations

from typing import Any

from ..schemas import CrawlerStartRequest, ResolvedCrawlerConfig
from .runtime_config_service import RuntimeConfigService


class CrawlerConfigResolver:
    """Merge request fields with runtime config overrides into one resolved config."""

    FIELD_TO_CONFIG_KEY = {
        "platform": "PLATFORM",
        "login_type": "LOGIN_TYPE",
        "crawler_type": "CRAWLER_TYPE",
        "keywords": "KEYWORDS",
        "specified_ids": "DY_SPECIFIED_ID_LIST",
        "creator_ids": "DY_CREATOR_ID_LIST",
        "start_page": "START_PAGE",
        "enable_comments": "ENABLE_GET_COMMENTS",
        "enable_sub_comments": "ENABLE_GET_SUB_COMMENTS",
        "save_option": "SAVE_DATA_OPTION",
        "cookies": "COOKIES",
        "headless": "HEADLESS",
        "sort_type": "SEARCH_SORT_TYPE",
        "comment_time_filter_h": "COMMENT_TIME_FILTER_H",
    }

    def __init__(self, runtime_config_service: RuntimeConfigService | None = None) -> None:
        self.runtime_config_service = runtime_config_service or RuntimeConfigService()

    async def resolve(self, request: CrawlerStartRequest) -> ResolvedCrawlerConfig:
        """Resolve a request against runtime overrides while honoring explicit request fields."""
        config_payload = await self.runtime_config_service.get_all()
        merged_config = config_payload["merged"]
        explicit_fields = set(request.model_fields_set)

        resolved_data = request.model_dump()
        applied_override_keys: list[str] = []
        for field_name, config_key in self.FIELD_TO_CONFIG_KEY.items():
            if field_name in explicit_fields:
                continue
            if config_key not in merged_config:
                continue
            override_value = self._adapt_value(field_name, merged_config[config_key])
            if override_value is None:
                continue
            resolved_data[field_name] = override_value
            if config_key in config_payload["overrides"]:
                applied_override_keys.append(config_key)

        resolved_data["runtime_override_keys"] = sorted(set(applied_override_keys))
        return ResolvedCrawlerConfig(**resolved_data)

    @staticmethod
    def _adapt_value(field_name: str, value: Any) -> Any:
        """Adapt raw config values into API schema-compatible field values."""
        if field_name in {"platform", "login_type", "crawler_type", "save_option"}:
            return value
        if field_name in {"specified_ids", "creator_ids"}:
            if isinstance(value, list):
                return ",".join(str(item) for item in value)
            return value
        if field_name == "sort_type":
            return str(value)
        return value
