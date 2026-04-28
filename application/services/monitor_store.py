from __future__ import annotations

import json
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse


class MonitorStore:
    def __init__(
        self,
        *,
        data_base_dir: str | Path = "data",
        tasks_base_dir: str | Path | None = None,
        events_base_dir: str | Path | None = None,
    ) -> None:
        self.data_base_dir = Path(data_base_dir)
        self.tasks_base_dir = Path(tasks_base_dir) if tasks_base_dir else self.data_base_dir / "platform_runtime" / "tasks" / "douyin"
        self.events_base_dir = Path(events_base_dir) if events_base_dir else self.data_base_dir / "platform_runtime" / "events" / "douyin"
        self.monitor_items_file = self.tasks_base_dir / "monitor_items.jsonl"
        self.monitor_events_file = self.events_base_dir / "monitor_events.jsonl"

    def list_monitor_items(self) -> list[dict[str, Any]]:
        items = list(self._load_latest_snapshots(self.monitor_items_file).values())
        items.sort(key=lambda item: item.get("updated_at", ""), reverse=True)
        return items

    def get_monitor_item(self, monitor_item_id: str) -> dict[str, Any] | None:
        return self._load_latest_snapshots(self.monitor_items_file).get(monitor_item_id)

    def create_monitor_item(
        self,
        *,
        content_url: str,
        refresh_interval_seconds: int,
        title: str = "",
        author_short_id: str = "",
    ) -> dict[str, Any]:
        content_id = self.extract_content_id(content_url)
        now = self._utcnow()
        item = {
            "monitor_item_id": uuid.uuid4().hex,
            "platform_code": "dy",
            "content_id": content_id,
            "content_url": content_url,
            "title": title,
            "author_short_id": author_short_id,
            "refresh_interval_seconds": refresh_interval_seconds,
            "status": "idle",
            "last_cursor": "",
            "last_success_at": None,
            "last_error": "",
            "last_run_comment_count": 0,
            "created_at": now,
            "updated_at": now,
        }
        self._append_jsonl(self.monitor_items_file, item)
        self.append_log(monitor_item_id=item["monitor_item_id"], level="info", message=f"Created monitor item for content {content_id}")
        return item

    def update_monitor_item(self, monitor_item_id: str, updates: dict[str, Any]) -> dict[str, Any]:
        current = self.get_monitor_item(monitor_item_id)
        if current is None:
            raise FileNotFoundError(monitor_item_id)
        next_item = {
            **current,
            **{key: value for key, value in updates.items() if value is not None},
            "updated_at": self._utcnow(),
        }
        self._append_jsonl(self.monitor_items_file, next_item)
        return next_item

    def append_log(self, *, monitor_item_id: str, level: str, message: str, details: dict[str, Any] | None = None) -> dict[str, Any]:
        event = {
            "event_id": uuid.uuid4().hex,
            "monitor_item_id": monitor_item_id,
            "level": level,
            "message": message,
            "details": details or {},
            "created_at": self._utcnow(),
        }
        self._append_jsonl(self.monitor_events_file, event)
        return event

    def list_logs(self, monitor_item_id: str, *, limit: int = 100) -> list[dict[str, Any]]:
        logs = [row for row in self._read_jsonl(self.monitor_events_file) if row.get("monitor_item_id") == monitor_item_id]
        logs.sort(key=lambda row: row.get("created_at", ""), reverse=True)
        return logs[:limit]

    @staticmethod
    def extract_content_id(content_url: str) -> str:
        parsed = urlparse(content_url)
        path_parts = [part for part in parsed.path.split("/") if part]
        if path_parts:
            candidate = path_parts[-1]
            if candidate.isdigit():
                return candidate
        if content_url.isdigit():
            return content_url
        raise ValueError("Unable to extract Douyin content ID from URL")

    def _load_latest_snapshots(self, file_path: Path) -> dict[str, dict[str, Any]]:
        items: dict[str, dict[str, Any]] = {}
        for row in self._read_jsonl(file_path):
            item_id = str(row.get("monitor_item_id") or "")
            if not item_id:
                continue
            items[item_id] = row
        return items

    def _read_jsonl(self, file_path: Path) -> list[dict[str, Any]]:
        if not file_path.exists():
            return []
        rows: list[dict[str, Any]] = []
        with file_path.open("r", encoding="utf-8") as file:
            for line in file:
                line = line.strip()
                if not line:
                    continue
                try:
                    parsed = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(parsed, dict):
                    rows.append(parsed)
        return rows

    def _append_jsonl(self, file_path: Path, payload: dict[str, Any]) -> None:
        file_path.parent.mkdir(parents=True, exist_ok=True)
        with file_path.open("a", encoding="utf-8") as file:
            file.write(json.dumps(payload, ensure_ascii=False) + "\n")

    @staticmethod
    def _utcnow() -> str:
        return datetime.utcnow().replace(microsecond=0).isoformat()
