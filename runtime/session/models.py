from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass(slots=True)
class SessionState:
    """Cross-runtime session snapshot used by connectors and signers."""

    platform_code: str
    session_id: str | None = None
    account_id: str | None = None
    login_status: bool = False
    user_agent: str | None = None
    cookies: list[dict[str, Any]] = field(default_factory=list)
    cookie_dict: dict[str, str] = field(default_factory=dict)
    local_storage: dict[str, Any] = field(default_factory=dict)
    proxy: str | None = None
    updated_at: datetime = field(default_factory=datetime.utcnow)
    metadata: dict[str, Any] = field(default_factory=dict)

