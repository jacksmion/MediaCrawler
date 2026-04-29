# -*- coding: utf-8 -*-
# Copyright (c) 2025 relakkes@gmail.com
#
# This file is part of MediaCrawler project.
# Repository: https://github.com/NanmiCoder/MediaCrawler/blob/main/api/services/crawler_manager.py
# GitHub: https://github.com/NanmiCoder
# Licensed under NON-COMMERCIAL LEARNING LICENSE 1.1
#
# 声明：本代码仅供学习和研究目的使用。使用者应遵守以下原则：
# 1. 不得用于任何商业用途。
# 2. 使用时应遵守目标平台的使用条款和robots.txt规则。
# 3. 不得进行大规模爬取或对平台造成运营干扰。
# 4. 应合理控制请求频率，避免给目标平台带来不必要的负担。
# 5. 不得用于任何非法或不当的用途。
#
# 详细许可条款请参阅项目根目录下的LICENSE文件。
# 使用本代码即表示您同意遵守上述原则和LICENSE中的所有条款。

import asyncio
import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

from application.services.crawler_runtime import CrawlerFactory, cleanup_runtime
from application.services.requirement_mapper import (
    apply_runtime_request_overrides,
    build_requirement_from_request_payload,
    merge_request_with_runtime_overrides,
)
from application.services.runtime_config_service import RuntimeConfigService
from ..schemas import CrawlerStartRequest, LogEntry
from .crawler_log_service import CrawlerLogService

MAX_CONCURRENT_TASKS = 3


@dataclass(slots=True)
class InProcessCrawlerHandle:
    task: asyncio.Task


@dataclass(slots=True)
class CrawlerRuntimeState:
    task_id: str
    account_id: str
    platform: str = ""
    crawler_type: str = ""
    handle: Optional[object] = None
    status: str = "idle"
    started_at: Optional[datetime] = None
    current_config: Optional[object] = None


class ApiLogHandler(logging.Handler):
    def __init__(self, log_service: CrawlerLogService) -> None:
        super().__init__(level=logging.INFO)
        self.log_service = log_service
        self.setFormatter(logging.Formatter("%(message)s"))

    def emit(self, record: logging.LogRecord) -> None:
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return

        message = self.format(record)
        level = self.log_service.parse_level(record.levelname)
        entry = self.log_service.create_entry(message, level)
        loop.call_soon_threadsafe(lambda: asyncio.ensure_future(self.log_service.push(entry), loop=loop))


class CrawlerManager:
    """Multi-task crawler process manager with per-account concurrency control."""

    def __init__(self):
        self._lock = asyncio.Lock()
        self._tasks: dict[str, CrawlerRuntimeState] = {}
        self._log_services: dict[str, CrawlerLogService] = {}
        self.runtime_config_service = RuntimeConfigService()

    def get_log_service(self, task_id: str) -> CrawlerLogService:
        return self._log_services.get(task_id, CrawlerLogService())

    def get_log_queue(self) -> asyncio.Queue:
        """Get a merged log queue from all active log services (for WebSocket broadcast)."""
        # Return the queue from the first active task, or create a fallback
        for log_service in self._log_services.values():
            return log_service.get_log_queue()
        # No active tasks — create a temporary service and return its queue
        return CrawlerLogService().get_log_queue()

    @property
    def logs(self) -> list[LogEntry]:
        """Legacy: return logs from the first available task."""
        for log_service in self._log_services.values():
            return log_service.logs
        return []

    def get_logs(self, task_id: str, limit: int = 100) -> list[dict]:
        """Get logs for a specific task."""
        log_service = self._log_services.get(task_id)
        if not log_service:
            return []
        logs = log_service.logs[-limit:] if limit > 0 else log_service.logs
        return [log.model_dump() for log in logs]

    async def start(self, config: CrawlerStartRequest) -> str | None:
        """Start a crawler task. Returns task_id on success, None on failure."""
        async with self._lock:
            account_id = config.account_id or self._default_account_id(config.platform.value)

            # Check concurrent limit
            running = [t for t in self._tasks.values() if t.status == "running"]
            if len(running) >= MAX_CONCURRENT_TASKS:
                return None

            # Check same-account conflict
            if any(t.account_id == account_id and t.status == "running" for t in running):
                return None

            task_id = config.task_id or f"task_{uuid.uuid4().hex[:16]}"
            if task_id in self._tasks and self._tasks[task_id].status == "running":
                return None

            log_service = CrawlerLogService()
            self._log_services[task_id] = log_service

            resolved_config = await self._resolve_config(config)
            # Patch account_id into resolved config
            resolved_config.account_id = account_id

            await log_service.push(log_service.create_entry(
                f"Starting crawler: platform={resolved_config.platform.value}, account={account_id}, type={resolved_config.crawler_type.value}",
                "info",
            ))

            try:
                runtime = CrawlerRuntimeState(
                    task_id=task_id,
                    account_id=account_id,
                    platform=resolved_config.platform.value,
                    crawler_type=resolved_config.crawler_type.value,
                    status="running",
                    started_at=datetime.now(),
                    current_config=resolved_config,
                )
                handle = InProcessCrawlerHandle(
                    task=asyncio.create_task(self._run_crawler(runtime, resolved_config))
                )
                runtime.handle = handle
                self._tasks[task_id] = runtime

                await log_service.push(log_service.create_entry(
                    f"Crawler started: {resolved_config.platform.value}, account={account_id}",
                    "success",
                ))
                if resolved_config.runtime_override_keys:
                    await log_service.push(log_service.create_entry(
                        f"Applied runtime overrides: {', '.join(resolved_config.runtime_override_keys)}",
                        "debug",
                    ))
                return task_id
            except Exception as e:
                await log_service.push(log_service.create_entry(f"Failed to start crawler: {str(e)}", "error"))
                return None

    async def stop(self, task_id: str) -> bool:
        """Stop a specific task."""
        handle = None
        log_service = None
        async with self._lock:
            runtime = self._tasks.get(task_id)
            if not runtime or runtime.status != "running":
                return False

            runtime.status = "stopping"
            log_service = self._log_services.get(task_id)
            handle = runtime.handle
            if log_service:
                await log_service.push(log_service.create_entry("Cancelling task...", "warning"))
            if isinstance(handle, InProcessCrawlerHandle):
                handle.task.cancel()

        # Wait for cancellation outside the lock
        if isinstance(handle, InProcessCrawlerHandle):
            try:
                await asyncio.wait_for(handle.task, timeout=15.0)
            except asyncio.CancelledError:
                pass
            except asyncio.TimeoutError:
                if log_service:
                    await log_service.push(log_service.create_entry("Task cancellation timeout", "warning"))

        async with self._lock:
            runtime = self._tasks.get(task_id)
            if runtime:
                runtime.status = "idle"
                runtime.current_config = None
                runtime.handle = None
            if log_service:
                await log_service.push(log_service.create_entry("Task terminated", "info"))
        return True

    def get_status(self) -> dict:
        """Return multi-task status for API response. Cleans up stale completed/error tasks."""
        # Clean up completed/error tasks older than the last 10
        stale = [tid for tid, rt in self._tasks.items() if rt.status in ("completed", "error", "idle")]
        if len(stale) > 10:
            for tid in stale[:-10]:
                del self._tasks[tid]
                self._log_services.pop(tid, None)

        tasks = []
        for tid, rt in self._tasks.items():
            if rt.status in ("running", "stopping"):
                tasks.append({
                    "task_id": tid,
                    "account_id": rt.account_id,
                    "platform": rt.platform,
                    "crawler_type": rt.crawler_type,
                    "status": rt.status,
                    "started_at": rt.started_at.isoformat() if rt.started_at else None,
                })
        return {
            "tasks": tasks,
            "active_count": len([t for t in tasks if t["status"] == "running"]),
        }

    def is_running(self, task_id: str | None = None) -> bool:
        if task_id:
            rt = self._tasks.get(task_id)
            return rt is not None and rt.status == "running"
        return any(rt.status == "running" for rt in self._tasks.values())

    # --- Internal helpers ---

    def _default_account_id(self, platform: str) -> str:
        """Fallback: use the legacy single-profile directory pattern."""
        return f"{platform}_user_data_dir"

    async def _run_crawler(self, runtime: CrawlerRuntimeState, resolved_config) -> None:
        task_id = runtime.task_id
        log_service = self._log_services.get(task_id, CrawlerLogService())
        crawler = None
        api_log_handler = ApiLogHandler(log_service)
        logger = logging.getLogger("MediaCrawler")
        try:
            logger.addHandler(api_log_handler)
            payload = resolved_config.model_dump(mode="json")
            apply_runtime_request_overrides(payload)
            crawler = CrawlerFactory.create_crawler(platform=resolved_config.platform.value)
            # Inject account_id for profile isolation
            if hasattr(crawler, "account_id"):
                crawler.account_id = resolved_config.account_id
            if resolved_config.crawler_type.value == "login":
                await crawler.start()
            else:
                requirement = build_requirement_from_request_payload(
                    resolved_config,
                    source="webui_api",
                )
                await crawler.start_with_requirement(requirement)
            if runtime.status == "running":
                await log_service.push(log_service.create_entry("Crawler completed successfully", "success"))
                runtime.status = "completed"
        except asyncio.CancelledError:
            await log_service.push(log_service.create_entry("Crawler task cancelled", "warning"))
            runtime.status = "idle"
            raise
        except Exception as exc:
            runtime.status = "error"
            await log_service.push(log_service.create_entry(f"Crawler execution failed: {exc}", "error"))
        finally:
            logger.removeHandler(api_log_handler)
            await cleanup_runtime(crawler)
            runtime.handle = None

    async def _resolve_config(self, request: CrawlerStartRequest):
        config_payload = await self.runtime_config_service.get_all()
        resolved_data = merge_request_with_runtime_overrides(
            request.model_dump(),
            config_payload["merged"],
            override_keys=config_payload["overrides"],
            explicit_fields=set(request.model_fields_set),
        )
        from ..schemas import ResolvedCrawlerConfig

        return ResolvedCrawlerConfig(**resolved_data)


# Global singleton
crawler_manager = CrawlerManager()
