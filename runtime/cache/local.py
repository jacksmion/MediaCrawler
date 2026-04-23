import asyncio
import time
from typing import Any, Dict, List, Optional, Tuple

from .base import AbstractCache


class ExpiringLocalCache(AbstractCache):
    def __init__(self, cron_interval: int = 10):
        self._cron_interval = cron_interval
        self._cache_container: Dict[str, Tuple[Any, float]] = {}
        self._cron_task: Optional[asyncio.Task] = None
        self._schedule_clear()

    def __del__(self):
        if self._cron_task is not None:
            self._cron_task.cancel()

    def get(self, key: str) -> Optional[Any]:
        value, expire_time = self._cache_container.get(key, (None, 0))
        if value is None:
            return None
        if expire_time < time.time():
            del self._cache_container[key]
            return None
        return value

    def set(self, key: str, value: Any, expire_time: int) -> None:
        self._cache_container[key] = (value, time.time() + expire_time)

    def keys(self, pattern: str) -> List[str]:
        if pattern == "*":
            return list(self._cache_container.keys())
        if "*" in pattern:
            pattern = pattern.replace("*", "")
        return [key for key in self._cache_container.keys() if pattern in key]

    def _schedule_clear(self):
        try:
            loop = asyncio.get_event_loop()
        except RuntimeError:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
        self._cron_task = loop.create_task(self._start_clear_cron())

    def _clear(self):
        expired_keys = [key for key, (_, expire_time) in self._cache_container.items() if expire_time < time.time()]
        for key in expired_keys:
            del self._cache_container[key]

    async def _start_clear_cron(self):
        while True:
            self._clear()
            await asyncio.sleep(self._cron_interval)
