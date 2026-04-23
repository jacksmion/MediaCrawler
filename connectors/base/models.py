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
class ContentDetailResult:
    """Unified detail output with a transitional legacy alias key."""

    item: dict[str, Any]
    item_key: str = "item"
    request_uri: str = ""
    raw_payload: dict[str, Any] | list[Any] | str | None = None
    request_params: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_payload(self) -> dict[str, Any]:
        payload = {
            "item": self.item,
            "request_uri": self.request_uri,
            "raw_payload": self.raw_payload,
            "request_params": self.request_params,
            "metadata": self.metadata,
        }
        payload[self.item_key] = self.item
        return payload


@dataclass(slots=True)
class CommentsPage:
    """Unified comments output page."""

    comments: list[dict[str, Any]]
    has_more: bool = False
    next_cursor: str | int | None = None
    request_uri: str = ""
    raw_payload: dict[str, Any] | list[Any] | str | None = None
    request_params: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_payload(self) -> dict[str, Any]:
        return {
            "comments": self.comments,
            "has_more": self.has_more,
            "next_cursor": self.next_cursor,
            "cursor": self.next_cursor,
            "request_uri": self.request_uri,
            "raw_payload": self.raw_payload,
            "request_params": self.request_params,
            "metadata": self.metadata,
        }


@dataclass(slots=True)
class CreatorResult:
    """Unified creator output."""

    creator: dict[str, Any]
    request_uri: str = ""
    raw_payload: dict[str, Any] | list[Any] | str | None = None
    request_params: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_payload(self) -> dict[str, Any]:
        return {
            "creator": self.creator,
            "request_uri": self.request_uri,
            "raw_payload": self.raw_payload,
            "request_params": self.request_params,
            "metadata": self.metadata,
        }


@dataclass(slots=True)
class CreatorContentsPage:
    """Unified creator contents output page."""

    items: list[dict[str, Any]]
    has_more: bool = False
    next_cursor: str | int | None = None
    request_uri: str = ""
    raw_payload: dict[str, Any] | list[Any] | str | None = None
    request_params: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_payload(self) -> dict[str, Any]:
        return {
            "items": self.items,
            "has_more": self.has_more,
            "next_cursor": self.next_cursor,
            "request_uri": self.request_uri,
            "raw_payload": self.raw_payload,
            "request_params": self.request_params,
            "metadata": self.metadata,
        }


@dataclass(slots=True)
class FetchCursor:
    """Cursor wrapper for comments or creator-content pagination."""

    value: str | int | None = None
    has_more: bool = True
    metadata: dict[str, Any] = field(default_factory=dict)
