from __future__ import annotations

import json
import re
from typing import Any

import humps


class XiaoHongShuExtractor:
    def extract_note_detail_from_html(self, note_id: str, html: str) -> dict[str, Any] | None:
        if "noteDetailMap" not in html:
            return None
        state = re.findall(r"window.__INITIAL_STATE__=({.*})</script>", html)[0].replace("undefined", '""')
        if state == "{}":
            return None
        note_dict = humps.decamelize(json.loads(state))
        return note_dict["note"]["note_detail_map"][note_id]["note"]

    def extract_creator_info_from_html(self, html: str) -> dict[str, Any] | None:
        match = re.search(r"<script>window.__INITIAL_STATE__=(.+)</script>", html, re.M)
        if match is None:
            return None
        info = json.loads(match.group(1).replace(":undefined", ":null"), strict=False)
        if info is None:
            return None
        return info.get("user", {}).get("userPageData")
