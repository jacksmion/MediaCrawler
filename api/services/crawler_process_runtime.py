# -*- coding: utf-8 -*-
#
# Process runtime state for crawler execution.

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from ..schemas import ResolvedCrawlerConfig


@dataclass(slots=True)
class CrawlerProcessRuntime:
    """Mutable runtime state for the currently managed crawler process."""

    process: Optional[subprocess.Popen] = None
    status: str = "idle"
    started_at: Optional[datetime] = None
    current_config: Optional[ResolvedCrawlerConfig] = None
