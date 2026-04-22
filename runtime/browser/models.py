from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class BrowserState:
    """Serializable snapshot of browser-related runtime metadata."""

    browser_type: str = "chromium"
    cdp_enabled: bool = False
    headless: bool = True
    user_agent: str | None = None
    cookies: list[dict[str, Any]] = field(default_factory=list)
    local_storage: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)

