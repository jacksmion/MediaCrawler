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
from dataclasses import dataclass
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


@dataclass(slots=True)
class InProcessCrawlerHandle:
    task: asyncio.Task


@dataclass(slots=True)
class CrawlerRuntimeState:
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
        loop.create_task(self.log_service.push(entry))


class CrawlerManager:
    """Crawler process manager"""

    def __init__(self):
        self._lock = asyncio.Lock()
        self.runtime = CrawlerRuntimeState()
        self.runtime_config_service = RuntimeConfigService()
        self.log_service = CrawlerLogService()

    @property
    def logs(self) -> list[LogEntry]:
        return self.log_service.logs

    @property
    def process(self):
        return self.runtime.handle

    @property
    def status(self) -> str:
        return self.runtime.status

    @property
    def started_at(self):
        return self.runtime.started_at

    @property
    def current_config(self):
        return self.runtime.current_config

    def get_log_queue(self) -> asyncio.Queue:
        """Get or create log queue"""
        return self.log_service.get_log_queue()

    async def _push_log(self, entry: LogEntry):
        """Push log to queue"""
        await self.log_service.push(entry)

    async def start(self, config: CrawlerStartRequest) -> bool:
        """Start crawler process"""
        async with self._lock:
            if self.is_running():
                return False

            self.log_service.reset()
            resolved_config = await self._resolve_config(config)
            await self._push_log(
                self.log_service.create_entry(
                    f"Starting crawler in-process: platform={resolved_config.platform.value}, type={resolved_config.crawler_type.value}",
                    "info",
                )
            )

            try:
                self.runtime.handle = InProcessCrawlerHandle(task=asyncio.create_task(self._run_crawler(resolved_config)))
                self.runtime.status = "running"
                self.runtime.started_at = datetime.now()
                self.runtime.current_config = resolved_config

                entry = self.log_service.create_entry(
                    f"Crawler started on platform: {resolved_config.platform.value}, type: {resolved_config.crawler_type.value}",
                    "success"
                )
                await self._push_log(entry)
                if resolved_config.runtime_override_keys:
                    entry = self.log_service.create_entry(
                        f"Applied runtime overrides: {', '.join(resolved_config.runtime_override_keys)}",
                        "debug",
                    )
                    await self._push_log(entry)
                return True
            except Exception as e:
                self.runtime.status = "error"
                entry = self.log_service.create_entry(f"Failed to start crawler: {str(e)}", "error")
                await self._push_log(entry)
                return False

    async def stop(self) -> bool:
        """Stop crawler process"""
        async with self._lock:
            if not self.is_running():
                return False

            self.runtime.status = "stopping"
            entry = self.log_service.create_entry("Cancelling in-process crawler task...", "warning")
            await self._push_log(entry)

            try:
                handle = self.process
                if isinstance(handle, InProcessCrawlerHandle):
                    handle.task.cancel()
                    try:
                        await asyncio.wait_for(handle.task, timeout=15.0)
                    except asyncio.CancelledError:
                        pass
                    except asyncio.TimeoutError:
                        entry = self.log_service.create_entry("Crawler cancellation timeout", "warning")
                        await self._push_log(entry)
                await self._push_log(self.log_service.create_entry("Crawler task terminated", "info"))

            except Exception as e:
                entry = self.log_service.create_entry(f"Error stopping crawler: {str(e)}", "error")
                await self._push_log(entry)

            self.runtime.status = "idle"
            self.runtime.current_config = None
            self.runtime.handle = None

            return True

    def get_status(self) -> dict:
        """Get current status"""
        return {
            "status": self.status,
            "platform": self.current_config.platform.value if self.current_config else None,
            "crawler_type": self.current_config.crawler_type.value if self.current_config else None,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "error_message": None
        }

    def is_running(self) -> bool:
        handle = self.process
        return isinstance(handle, InProcessCrawlerHandle) and not handle.task.done()

    async def _run_crawler(self, resolved_config) -> None:
        crawler = None
        api_log_handler = ApiLogHandler(self.log_service)
        logger = logging.getLogger("MediaCrawler")
        try:
            logger.addHandler(api_log_handler)
            payload = resolved_config.model_dump(mode="json")
            apply_runtime_request_overrides(payload)
            crawler = CrawlerFactory.create_crawler(platform=resolved_config.platform.value)
            if resolved_config.crawler_type.value == "login":
                await crawler.start()
            else:
                requirement = build_requirement_from_request_payload(
                    resolved_config,
                    source="webui_api",
                )
                await crawler.start_with_requirement(requirement)
            if self.status == "running":
                await self._push_log(self.log_service.create_entry("Crawler completed successfully", "success"))
                self.runtime.status = "idle"
        except asyncio.CancelledError:
            await self._push_log(self.log_service.create_entry("Crawler task cancelled", "warning"))
            self.runtime.status = "idle"
            raise
        except Exception as exc:
            self.runtime.status = "error"
            await self._push_log(self.log_service.create_entry(f"Crawler execution failed: {exc}", "error"))
        finally:
            logger.removeHandler(api_log_handler)
            await cleanup_runtime(crawler)
            self.runtime.handle = None

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
