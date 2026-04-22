# -*- coding: utf-8 -*-
#
# Execution adapter abstractions for crawler runs.

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Mapping


class CrawlerExecutor(ABC):
    """Execution adapter for crawler runs."""

    @abstractmethod
    async def start(
        self,
        command: list[str],
        *,
        cwd: Path,
        env: Mapping[str, str],
    ):
        """Start a crawler execution and return the underlying runtime handle."""

    @abstractmethod
    async def terminate(self, handle) -> None:
        """Request graceful termination of a running crawler execution."""

    @abstractmethod
    async def kill(self, handle) -> None:
        """Forcefully terminate a running crawler execution."""

    @abstractmethod
    def is_running(self, handle) -> bool:
        """Return whether the execution handle is still running."""

    @abstractmethod
    def return_code(self, handle) -> int | None:
        """Return the exit code when available."""
