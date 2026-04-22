# -*- coding: utf-8 -*-
#
# API settings for MediaCrawler WebUI service.

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class ApiSettings:
    """Resolved filesystem settings for the API service."""

    api_root: Path
    project_root: Path
    frontend_dist_dir: Path


def get_api_settings() -> ApiSettings:
    """Build API settings from the current repository layout."""
    api_root = Path(__file__).resolve().parent
    project_root = api_root.parent
    return ApiSettings(
        api_root=api_root,
        project_root=project_root,
        frontend_dist_dir=project_root / "webui-react" / "dist",
    )
