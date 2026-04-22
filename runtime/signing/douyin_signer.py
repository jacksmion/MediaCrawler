from __future__ import annotations

import urllib.parse
from typing import Any

from runtime.session.service import SessionService


class DouyinSigner:
    """Builds Douyin-specific request params from session state."""

    def __init__(self, session_service: SessionService) -> None:
        self.session_service = session_service

    def build_common_params(self) -> dict[str, Any]:
        """Return the common query params currently needed by Douyin requests."""
        session = self.session_service.get()
        local_storage = session.local_storage
        return {
            "device_platform": "webapp",
            "aid": "6383",
            "channel": "channel_pc_web",
            "pc_client_type": "1",
            "platform": "PC",
            "msToken": local_storage.get("xmst", ""),
        }

    async def sign_request(
        self,
        uri: str,
        params: dict[str, Any],
        headers: dict[str, str],
        request_method: str = "GET",
        page: Any = None,
    ) -> dict[str, Any]:
        """
        Return signed params for Douyin requests.

        This keeps the current legacy signing logic behind the new runtime boundary.
        """
        merged = dict(params)
        merged.update(self.build_common_params())
        user_agent = headers.get("User-Agent") or self.session_service.get().user_agent or ""
        query_string = urllib.parse.urlencode(merged)
        post_data = merged if request_method.upper() == "POST" else {}
        if "/v1/web/general/search" not in uri:
            from connectors.douyin.helpers import get_a_bogus

            merged["a_bogus"] = await get_a_bogus(uri, query_string, post_data, user_agent, page)
        return merged
