from __future__ import annotations

import asyncio
from datetime import datetime
from pathlib import Path
from typing import Any

from application.services.douyin_comment_monitor_executor import DouyinCommentMonitorExecutor
from application.services.monitor_store import MonitorStore
from api.services.comment_reader import CommentReaderService


class DouyinMonitorManager:
    def __init__(
        self,
        *,
        data_base_dir: str | Path = "data",
        store: MonitorStore | None = None,
        executor: Any | None = None,
    ) -> None:
        self.store = store or MonitorStore(data_base_dir=data_base_dir)
        self.executor = executor or DouyinCommentMonitorExecutor()
        self.comment_reader = CommentReaderService(data_base_dir=data_base_dir)
        self._tasks: dict[str, asyncio.Task] = {}
        self._lock = asyncio.Lock()

    def list_items(self) -> list[dict[str, Any]]:
        return self.store.list_monitor_items()

    def get_item(self, monitor_item_id: str) -> dict[str, Any]:
        item = self.store.get_monitor_item(monitor_item_id)
        if item is None:
            raise FileNotFoundError(monitor_item_id)
        return item

    async def create_item(
        self,
        *,
        content_url: str,
        refresh_interval_seconds: int,
        title: str = "",
        author_short_id: str = "",
    ) -> dict[str, Any]:
        metadata = self._lookup_content_metadata(content_url)
        return self.store.create_monitor_item(
            content_url=content_url,
            refresh_interval_seconds=refresh_interval_seconds,
            title=title or metadata.get("title", ""),
            author_short_id=author_short_id or metadata.get("author_short_id", ""),
        )

    async def update_item(self, monitor_item_id: str, updates: dict[str, Any]) -> dict[str, Any]:
        item = self.store.update_monitor_item(monitor_item_id, updates)
        self.store.append_log(monitor_item_id=monitor_item_id, level="info", message="Updated monitor item", details=updates)
        return item

    async def start_item(self, monitor_item_id: str) -> dict[str, Any]:
        async with self._lock:
            item = self.get_item(monitor_item_id)
            running_task = self._tasks.get(monitor_item_id)
            if running_task and not running_task.done():
                return item
            item = self.store.update_monitor_item(monitor_item_id, {"status": "running", "last_error": ""})
            self.store.append_log(monitor_item_id=monitor_item_id, level="info", message="Started monitor loop")
            self._tasks[monitor_item_id] = asyncio.create_task(self._run_monitor_loop(monitor_item_id))
            return item

    async def stop_item(self, monitor_item_id: str) -> dict[str, Any]:
        async with self._lock:
            task = self._tasks.get(monitor_item_id)
            if task and not task.done():
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
            item = self.store.update_monitor_item(monitor_item_id, {"status": "paused"})
            self.store.append_log(monitor_item_id=monitor_item_id, level="info", message="Stopped monitor loop")
            self._tasks.pop(monitor_item_id, None)
            return item

    def list_logs(self, monitor_item_id: str, *, limit: int = 100) -> list[dict[str, Any]]:
        return self.store.list_logs(monitor_item_id, limit=limit)

    async def _run_monitor_loop(self, monitor_item_id: str) -> None:
        try:
            while True:
                item = self.get_item(monitor_item_id)
                try:
                    self.store.append_log(monitor_item_id=monitor_item_id, level="info", message="Refreshing comments")
                    result = await self.executor.refresh_once(item)
                    updates = {
                        "status": "running",
                        "last_cursor": result.get("last_cursor", ""),
                        "last_success_at": result.get("last_success_at") or self._utcnow(),
                        "last_error": result.get("last_error", ""),
                        "last_run_comment_count": int(result.get("last_run_comment_count") or 0),
                    }
                    self.store.update_monitor_item(monitor_item_id, updates)
                    self.store.append_log(
                        monitor_item_id=monitor_item_id,
                        level="success",
                        message="Refresh completed",
                        details={"comment_count": updates["last_run_comment_count"]},
                    )
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    self.store.update_monitor_item(
                        monitor_item_id,
                        {
                            "status": "error",
                            "last_error": str(exc),
                        },
                    )
                    self.store.append_log(monitor_item_id=monitor_item_id, level="error", message=f"Refresh failed: {exc}")
                await asyncio.sleep(max(5, int(item.get("refresh_interval_seconds") or 60)))
        except asyncio.CancelledError:
            raise
        finally:
            self._tasks.pop(monitor_item_id, None)

    @staticmethod
    def _utcnow() -> str:
        return datetime.utcnow().replace(microsecond=0).isoformat()

    def _lookup_content_metadata(self, content_url: str) -> dict[str, str]:
        try:
            content_id = self.store.extract_content_id(content_url)
        except ValueError:
            return {}
        index_loader = getattr(self.comment_reader, "_load_content_index", None)
        if not callable(index_loader):
            return {}
        record = index_loader().get(content_id, {})
        return {
            "title": str(record.get("title") or ""),
            "author_short_id": str(record.get("author_short_id") or ""),
        }


monitor_manager = DouyinMonitorManager()
