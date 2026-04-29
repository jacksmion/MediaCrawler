# -*- coding: utf-8 -*-
#
# Log buffering service for crawler runtime.

from __future__ import annotations

import asyncio
from datetime import datetime

from ..schemas import LogEntry


class CrawlerLogService:
    """Stores recent crawler logs and broadcasts them to websocket consumers."""

    def __init__(self, *, max_logs: int = 500) -> None:
        self.max_logs = max_logs
        self._log_id = 0
        self._logs: list[LogEntry] = []
        self._log_queue: asyncio.Queue | None = None

    @property
    def logs(self) -> list[LogEntry]:
        return self._logs

    def get_log_queue(self) -> asyncio.Queue:
        """Get or create the log queue."""
        if self._log_queue is None:
            self._log_queue = asyncio.Queue()
        return self._log_queue

    def reset(self) -> None:
        """Clear log buffer and pending queue entries for a new run."""
        self._logs = []
        self._log_id = 0
        queue = self.get_log_queue()
        try:
            while True:
                queue.get_nowait()
        except asyncio.QueueEmpty:
            pass

    def create_entry(self, message: str, level: str = "info", task_id: str = "") -> LogEntry:
        """Create and persist a log entry in the in-memory buffer."""
        self._log_id += 1
        entry = LogEntry(
            id=self._log_id,
            task_id=task_id,
            timestamp=datetime.now().strftime("%H:%M:%S"),
            level=level,
            message=message,
        )
        self._logs.append(entry)
        if len(self._logs) > self.max_logs:
            self._logs = self._logs[-self.max_logs:]
        return entry

    async def push(self, entry: LogEntry) -> None:
        """Push a log entry to websocket listeners."""
        if self._log_queue is not None:
            try:
                self._log_queue.put_nowait(entry)
            except asyncio.QueueFull:
                pass

    def parse_level(self, line: str) -> str:
        """Infer log level from a raw process output line."""
        line_upper = line.upper()
        if "ERROR" in line_upper or "FAILED" in line_upper:
            return "error"
        if "WARNING" in line_upper or "WARN" in line_upper:
            return "warning"
        if "SUCCESS" in line_upper or "完成" in line or "成功" in line:
            return "success"
        if "DEBUG" in line_upper:
            return "debug"
        return "info"
