from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class HttpRequest:
    """Normalized HTTP request for runtime executors."""

    method: str
    url: str
    params: dict[str, Any] = field(default_factory=dict)
    headers: dict[str, str] = field(default_factory=dict)
    data: Any = None
    json: Any = None
    timeout: float | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class HttpResponse:
    """Normalized HTTP response wrapper."""

    status_code: int
    url: str
    headers: dict[str, str] = field(default_factory=dict)
    text: str = ""
    data: Any = None
    metadata: dict[str, Any] = field(default_factory=dict)

