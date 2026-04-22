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
import os
from pathlib import Path
from typing import Optional

from ..schemas import CrawlerStartRequest, LogEntry
from .crawler_command_builder import CrawlerCommandBuilder
from .crawler_config_resolver import CrawlerConfigResolver
from .crawler_execution_planner import CrawlerExecutionPlanner
from .crawler_executor import CrawlerExecutor
from .subprocess_crawler_executor import SubprocessCrawlerExecutor
from .crawler_log_service import CrawlerLogService
from .crawler_process_runtime import CrawlerProcessRuntime


class CrawlerManager:
    """Crawler process manager"""

    def __init__(self, executor: CrawlerExecutor | None = None):
        self._lock = asyncio.Lock()
        self.runtime = CrawlerProcessRuntime()
        self.command_builder = CrawlerCommandBuilder()
        self.config_resolver = CrawlerConfigResolver()
        self.execution_planner = CrawlerExecutionPlanner(self.command_builder)
        self.executor = executor or SubprocessCrawlerExecutor()
        self.log_service = CrawlerLogService()
        self._read_task: Optional[asyncio.Task] = None
        # Project root directory
        self._project_root = Path(__file__).parent.parent.parent

    @property
    def logs(self) -> list[LogEntry]:
        return self.log_service.logs

    @property
    def process(self):
        return self.runtime.process

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
            if self.process and self.process.poll() is None:
                return False

            # Clear old logs
            self.log_service.reset()

            resolved_config = await self.config_resolver.resolve(config)
            execution_plan = self.execution_planner.build_plan(resolved_config)

            # Build command line arguments
            cmd = execution_plan.command

            # Log start information
            entry = self.log_service.create_entry(f"Starting crawler: {' '.join(cmd)}", "info")
            await self._push_log(entry)

            try:
                self.runtime.process = await self.executor.start(
                    cmd,
                    cwd=self._project_root,
                    env={**os.environ, "PYTHONUNBUFFERED": "1"},
                )

                from datetime import datetime
                self.runtime.status = "running"
                self.runtime.started_at = datetime.now()
                self.runtime.current_config = resolved_config

                entry = self.log_service.create_entry(
                    f"Crawler started on platform: {resolved_config.platform.value}, type: {resolved_config.crawler_type.value}",
                    "success"
                )
                await self._push_log(entry)
                entry = self.log_service.create_entry(
                    f"Execution mode: {execution_plan.mode}",
                    "debug",
                )
                await self._push_log(entry)
                if resolved_config.runtime_override_keys:
                    entry = self.log_service.create_entry(
                        f"Applied runtime overrides: {', '.join(resolved_config.runtime_override_keys)}",
                        "debug",
                    )
                    await self._push_log(entry)

                # Start log reading task
                self._read_task = asyncio.create_task(self._read_output())

                return True
            except Exception as e:
                self.runtime.status = "error"
                entry = self.log_service.create_entry(f"Failed to start crawler: {str(e)}", "error")
                await self._push_log(entry)
                return False

    async def stop(self) -> bool:
        """Stop crawler process"""
        async with self._lock:
            if not self.process or self.process.poll() is not None:
                return False

            self.runtime.status = "stopping"
            entry = self.log_service.create_entry("Sending SIGTERM to crawler process...", "warning")
            await self._push_log(entry)

            try:
                await self.executor.terminate(self.process)

                # Wait for graceful exit (up to 15 seconds)
                for _ in range(30):
                    if not self.executor.is_running(self.process):
                        break
                    await asyncio.sleep(0.5)

                # If still not exited, force kill
                if self.executor.is_running(self.process):
                    entry = self.log_service.create_entry("Process not responding, sending SIGKILL...", "warning")
                    await self._push_log(entry)
                    await self.executor.kill(self.process)

                entry = self.log_service.create_entry("Crawler process terminated", "info")
                await self._push_log(entry)

            except Exception as e:
                entry = self.log_service.create_entry(f"Error stopping crawler: {str(e)}", "error")
                await self._push_log(entry)

            self.runtime.status = "idle"
            self.runtime.current_config = None

            # Cancel log reading task
            if self._read_task:
                self._read_task.cancel()
                self._read_task = None

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

    async def _read_output(self):
        """Asynchronously read process output"""
        loop = asyncio.get_event_loop()

        try:
            while self.process and self.executor.is_running(self.process):
                # Read a line in thread pool
                line = await loop.run_in_executor(
                    None, self.process.stdout.readline
                )
                if line:
                    line = line.strip()
                    if line:
                        level = self.log_service.parse_level(line)
                        entry = self.log_service.create_entry(line, level)
                        await self._push_log(entry)

            # Read remaining output
            if self.process and self.process.stdout:
                remaining = await loop.run_in_executor(
                    None, self.process.stdout.read
                )
                if remaining:
                    for line in remaining.strip().split('\n'):
                        if line.strip():
                            level = self.log_service.parse_level(line)
                            entry = self.log_service.create_entry(line.strip(), level)
                            await self._push_log(entry)

            # Process ended
            if self.status == "running":
                exit_code = self.executor.return_code(self.process) if self.process else -1
                if exit_code == 0:
                    entry = self.log_service.create_entry("Crawler completed successfully", "success")
                else:
                    entry = self.log_service.create_entry(f"Crawler exited with code: {exit_code}", "warning")
                await self._push_log(entry)
                self.runtime.status = "idle"

        except asyncio.CancelledError:
            pass
        except Exception as e:
            entry = self.log_service.create_entry(f"Error reading output: {str(e)}", "error")
            await self._push_log(entry)


# Global singleton
crawler_manager = CrawlerManager()
