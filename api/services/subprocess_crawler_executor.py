# -*- coding: utf-8 -*-
#
# Subprocess-backed crawler executor.

from __future__ import annotations

import asyncio
import subprocess
from pathlib import Path
from typing import Mapping

from .crawler_executor import CrawlerExecutor


class SubprocessCrawlerExecutor(CrawlerExecutor):
    """Runs crawlers through the existing `main.py` subprocess entrypoint."""

    async def start(
        self,
        command: list[str],
        *,
        cwd: Path,
        env: Mapping[str, str],
    ) -> subprocess.Popen:
        return subprocess.Popen(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            bufsize=1,
            cwd=str(cwd),
            env=dict(env),
        )

    async def terminate(self, handle: subprocess.Popen) -> None:
        handle.terminate()

    async def kill(self, handle: subprocess.Popen) -> None:
        handle.kill()

    def is_running(self, handle: subprocess.Popen) -> bool:
        return handle.poll() is None

    def return_code(self, handle: subprocess.Popen) -> int | None:
        return handle.poll()
