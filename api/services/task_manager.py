from __future__ import annotations

import asyncio
import logging
import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Optional, Any

from application.services.crawler_runtime import CrawlerFactory, cleanup_runtime
from application.services.requirement_mapper import (
    apply_runtime_request_overrides,
    build_requirement_from_request_payload,
)
from api.services import task_store
from api.services.crawler_log_service import CrawlerLogService
from api.schemas.task import TaskCreateRequest, TaskItemResponse

MAX_CONCURRENT = 3
MAX_CONSECUTIVE_ERRORS = 5


@dataclass(slots=True)
class TaskRuntime:
    task_id: str
    account_id: str
    platform: str
    crawler_type: str
    mode: str
    handle: Optional[asyncio.Task] = None
    status: str = "idle"
    started_at: Optional[datetime] = None
    loop_interval: int = 60


class ApiLogHandler(logging.Handler):
    def __init__(self, log_service: CrawlerLogService, task_id: str) -> None:
        super().__init__(level=logging.INFO)
        self.log_service = log_service
        self.task_id = task_id
        self.setFormatter(logging.Formatter(f"[{task_id}] %(message)s"))

    def emit(self, record: logging.LogRecord) -> None:
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        message = self.format(record)
        level = self.log_service.parse_level(record.levelname)
        entry = self.log_service.create_entry(message, level)
        loop.call_soon_threadsafe(lambda: asyncio.ensure_future(self.log_service.push(entry), loop=loop))


class TaskManager:
    """Unified task scheduler for both one-shot and recurring crawl tasks."""

    def __init__(self):
        self._lock = asyncio.Lock()
        self._runtimes: dict[str, TaskRuntime] = {}
        self._log_services: dict[str, CrawlerLogService] = {}

    # --- Public API ---

    def list_tasks(self) -> list[TaskItemResponse]:
        items = task_store.list_tasks()
        result = []
        for item in items:
            rt = self._runtimes.get(item.get("task_id", ""))
            if rt and rt.status in ("running", "stopping"):
                item["status"] = rt.status
            result.append(TaskItemResponse(**item))
        return result

    def get_task(self, task_id: str) -> Optional[TaskItemResponse]:
        item = task_store.get_task(task_id)
        if not item:
            return None
        rt = self._runtimes.get(task_id)
        if rt and rt.status in ("running", "stopping"):
            item["status"] = rt.status
        return TaskItemResponse(**item)

    async def create_task(self, req: TaskCreateRequest) -> TaskItemResponse:
        fields = {
            "name": req.name or f"{req.platform}_{req.crawler_type}",
            "platform": req.platform,
            "account_id": req.account_id,
            "crawler_type": req.crawler_type,
            "mode": req.mode,
            "loop_interval_seconds": max(req.loop_interval_seconds, 5),
            "config": {
                "keywords": req.keywords,
                "specified_ids": req.specified_ids,
                "creator_ids": req.creator_ids,
                "sort_type": req.sort_type,
                "enable_comments": req.enable_comments,
                "enable_sub_comments": req.enable_sub_comments,
                "comment_time_filter_h": req.comment_time_filter_h,
                "headless": req.headless,
            },
        }
        item = task_store.create_task(fields)
        return TaskItemResponse(**item)

    async def start_task(self, task_id: str) -> bool:
        async with self._lock:
            item = task_store.get_task(task_id)
            if not item:
                return False

            running = [rt for rt in self._runtimes.values() if rt.status == "running"]
            if len(running) >= MAX_CONCURRENT:
                return False

            account_id = item.get("account_id", "")
            if account_id and any(rt.account_id == account_id and rt.status == "running" for rt in running):
                return False

            log_service = CrawlerLogService()
            self._log_services[task_id] = log_service

            rt = TaskRuntime(
                task_id=task_id,
                account_id=account_id,
                platform=item["platform"],
                crawler_type=item["crawler_type"],
                mode=item.get("mode", "once"),
                status="running",
                started_at=datetime.now(),
                loop_interval=item.get("loop_interval_seconds", 60),
            )
            rt.handle = asyncio.create_task(self._run(rt, item))
            self._runtimes[task_id] = rt

            task_store.update_task(task_id, {"status": "running"})
            task_store.append_event(task_id, "info", "Task started")
            return True

    async def pause_task(self, task_id: str) -> bool:
        async with self._lock:
            rt = self._runtimes.get(task_id)
            if not rt or rt.status != "running":
                return False
            if rt.mode != "loop":
                return False

            rt.status = "paused"
            if isinstance(rt.handle, asyncio.Task):
                rt.handle.cancel()

            task_store.update_task(task_id, {"status": "paused"})
            task_store.append_event(task_id, "info", "Task paused")
            return True

    async def stop_task(self, task_id: str) -> bool:
        handle = None
        log_service = None
        async with self._lock:
            rt = self._runtimes.get(task_id)
            if not rt or rt.status != "running":
                return False

            rt.status = "stopping"
            log_service = self._log_services.get(task_id)
            handle = rt.handle
            if isinstance(handle, asyncio.Task):
                handle.cancel()

        if isinstance(handle, asyncio.Task):
            try:
                await asyncio.wait_for(handle, timeout=15.0)
            except (asyncio.CancelledError, asyncio.TimeoutError):
                pass

        async with self._lock:
            rt = self._runtimes.get(task_id)
            if rt:
                rt.status = "idle"
                rt.handle = None

        task_store.update_task(task_id, {"status": "idle"})
        task_store.append_event(task_id, "info", "Task stopped")
        return True

    async def delete_task(self, task_id: str) -> bool:
        rt = self._runtimes.get(task_id)
        if rt and rt.status == "running":
            await self.stop_task(task_id)

        self._runtimes.pop(task_id, None)
        self._log_services.pop(task_id, None)
        return task_store.delete_task(task_id)

    # --- Log & Status (compatible with old WebSocket) ---

    def get_log_queue(self) -> asyncio.Queue:
        for log_service in self._log_services.values():
            return log_service.get_log_queue()
        return CrawlerLogService().get_log_queue()

    @property
    def logs(self) -> list:
        for log_service in self._log_services.values():
            return log_service.logs
        return []

    def get_logs(self, task_id: str, limit: int = 100) -> list[dict]:
        log_service = self._log_services.get(task_id)
        if not log_service:
            return []
        return [log.model_dump() for log in log_service.logs[-limit:]]

    def get_status(self) -> dict:
        stale = [tid for tid, rt in self._runtimes.items() if rt.status in ("idle", "paused", "completed", "error")]
        if len(stale) > 10:
            for tid in stale[:-10]:
                self._runtimes.pop(tid, None)
                self._log_services.pop(tid, None)

        tasks = []
        for tid, rt in self._runtimes.items():
            if rt.status in ("running", "stopping"):
                tasks.append({
                    "task_id": tid,
                    "account_id": rt.account_id,
                    "platform": rt.platform,
                    "crawler_type": rt.crawler_type,
                    "status": rt.status,
                    "started_at": rt.started_at.isoformat() if rt.started_at else None,
                })
        return {"tasks": tasks, "active_count": len([t for t in tasks if t["status"] == "running"])}

    @property
    def active_count(self) -> int:
        return sum(1 for rt in self._runtimes.values() if rt.status == "running")

    def is_running(self, task_id: str | None = None) -> bool:
        if task_id:
            rt = self._runtimes.get(task_id)
            return rt is not None and rt.status == "running"
        return any(rt.status == "running" for rt in self._runtimes.values())

    # --- Internal ---

    async def _run(self, rt: TaskRuntime, item: dict) -> None:
        if rt.mode == "once":
            await self._run_once(rt, item)
            rt.status = "completed"
            task_store.update_task(rt.task_id, {"status": "completed"})
        else:
            await self._run_loop(rt, item)

    async def _run_loop(self, rt: TaskRuntime, item: dict) -> None:
        log_service = self._log_services.get(rt.task_id, CrawlerLogService())
        consecutive_errors = 0
        try:
            while rt.status == "running":
                try:
                    await self._run_once(rt, item)
                    consecutive_errors = 0
                    task_store.update_task(rt.task_id, {
                        "last_run_at": datetime.now().isoformat(),
                        "last_run_status": "success",
                        "status": "running",
                    })
                except Exception as exc:
                    consecutive_errors += 1
                    await log_service.push(log_service.create_entry(f"Loop cycle error ({consecutive_errors}/{MAX_CONSECUTIVE_ERRORS}): {exc}", "error"))
                    task_store.update_task(rt.task_id, {
                        "last_run_at": datetime.now().isoformat(),
                        "last_run_status": "error",
                        "error_message": str(exc),
                    })
                    if consecutive_errors >= MAX_CONSECUTIVE_ERRORS:
                        await log_service.push(log_service.create_entry(f"Stopping loop: {MAX_CONSECUTIVE_ERRORS} consecutive errors", "error"))
                        rt.status = "error"
                        task_store.update_task(rt.task_id, {"status": "error"})
                        break
                await asyncio.sleep(rt.loop_interval)
        except asyncio.CancelledError:
            pass

    async def _run_once(self, rt: TaskRuntime, item: dict) -> dict[str, Any]:
        task_id = rt.task_id
        log_service = self._log_services.get(task_id, CrawlerLogService())
        crawler = None
        api_log_handler = ApiLogHandler(log_service, task_id)
        logger = logging.getLogger("MediaCrawler")

        try:
            logger.addHandler(api_log_handler)
            await log_service.push(log_service.create_entry(
                f"Starting crawl: platform={rt.platform}, account={rt.account_id}, type={rt.crawler_type}",
                "info",
            ))

            crawler = CrawlerFactory.create_crawler(platform=rt.platform)
            if hasattr(crawler, "account_id"):
                crawler.account_id = rt.account_id

            config = item.get("config", {})
            payload = {
                "platform": rt.platform,
                "crawler_type": rt.crawler_type,
                "keywords": config.get("keywords", ""),
                "specified_ids": config.get("specified_ids", ""),
                "creator_ids": config.get("creator_ids", ""),
                "sort_type": config.get("sort_type", ""),
                "enable_comments": config.get("enable_comments", True),
                "enable_sub_comments": config.get("enable_sub_comments", False),
                "comment_time_filter_h": config.get("comment_time_filter_h", 0),
                "headless": config.get("headless", True),
                "save_option": "jsonl",
            }
            apply_runtime_request_overrides(payload)

            requirement = build_requirement_from_request_payload(payload, source="task_center")
            result = await crawler.start_with_requirement(requirement)

            comment_count = 0
            if isinstance(result, dict):
                for task_result in result.values():
                    if isinstance(task_result, list):
                        comment_count += len(task_result)

            task_store.update_task(task_id, {
                "comment_count": comment_count,
                "last_run_at": datetime.now().isoformat(),
                "last_run_status": "success",
            })
            await log_service.push(log_service.create_entry("Crawl completed successfully", "success"))
            return result or {}

        except asyncio.CancelledError:
            await log_service.push(log_service.create_entry("Task cancelled", "warning"))
            raise
        except Exception as exc:
            rt.status = "error"
            task_store.update_task(task_id, {
                "status": "error",
                "last_run_status": "error",
                "error_message": str(exc),
            })
            await log_service.push(log_service.create_entry(f"Crawl failed: {exc}", "error"))
            raise
        finally:
            logger.removeHandler(api_log_handler)
            await cleanup_runtime(crawler)


task_manager = TaskManager()
