from __future__ import annotations

import json

from runtime.http.models import HttpRequest, HttpResponse
from tools.httpx_util import make_async_client


class HttpExecutor:
    """Central place for request sending, retries, and future tracing hooks."""

    def __init__(self, proxy: str | None = None, follow_redirects: bool = True) -> None:
        self.proxy = proxy
        self.follow_redirects = follow_redirects

    async def send(self, request: HttpRequest) -> HttpResponse:
        """Send a normalized HTTP request and return a normalized response."""
        async with make_async_client(proxy=self.proxy, follow_redirects=self.follow_redirects) as client:
            response = await client.request(
                request.method,
                request.url,
                params=request.params or None,
                headers=request.headers or None,
                data=request.data,
                json=request.json,
                timeout=request.timeout,
            )
        try:
            data = response.json()
        except json.JSONDecodeError:
            data = None
        return HttpResponse(
            status_code=response.status_code,
            url=str(response.request.url),
            headers=dict(response.headers),
            text=response.text,
            data=data,
        )
