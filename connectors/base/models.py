from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass(slots=True)
class ConnectorCapability:
    """Declares what a connector can do and which runtime it needs."""

    supports_search: bool = True
    supports_detail: bool = True
    supports_comments: bool = True
    supports_creator: bool = True
    requires_browser: bool = False
    requires_signing: bool = False
    supports_incremental: bool = False
    supports_resume: bool = False


@dataclass(slots=True)
class ConnectorContext:
    """Shared runtime objects that a connector may use during prepare()."""

    account_id: str | None = None
    proxy: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class AuthContext:
    """Input for connector authentication or session validation."""

    login_type: str
    account_id: str | None = None
    cookie_str: str | None = None
    login_phone: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class AuthResult:
    """Standard authentication result for platform connectors."""

    success: bool
    login_type: str
    account_id: str | None = None
    session_id: str | None = None
    message: str = ""
    details: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class HealthStatus:
    """Simple connector health model for pre-run checks and monitoring."""

    ok: bool
    platform_code: str
    checked_at: datetime = field(default_factory=datetime.utcnow)
    message: str = ""
    details: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class SearchQuery:
    """Unified search input for platform connectors."""

    keyword: str
    page: int = 1
    page_size: int = 10
    cursor: str | None = None
    filters: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class SearchPage:
    """Unified search output page."""

    items: list[dict[str, Any]]
    has_more: bool
    next_cursor: str | None = None
    raw: dict[str, Any] | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class FetchCursor:
    """Cursor wrapper for comments or creator-content pagination."""

    value: str | int | None = None
    has_more: bool = True
    metadata: dict[str, Any] = field(default_factory=dict)

