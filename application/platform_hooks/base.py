from __future__ import annotations

import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any

from connectors.base.models import ConnectorContext
from schemas.tasks.models import CrawlJobEvent, CrawlTask
from schemas.tasks.runtime import PlatformTaskRequest, PlatformTaskResult

from application.services.crawl_state_service import CrawlStateService
from application.services.event_service import EventService
from application.services.normalized_content_service import NormalizedContentService
from application.services.raw_record_service import RawRecordService


@dataclass(slots=True)
class ExecutionServices:
    crawl_state_service: CrawlStateService
    event_service: EventService
    normalized_content_service: NormalizedContentService
    raw_record_service: RawRecordService


class BasePlatformHooks(ABC):
    platform_code: str
    short_code: str
    source_name: str
    handled_exceptions: tuple[type[Exception], ...]

    def __init__(self, crawler) -> None:
        self.crawler = crawler

    def make_job_id(self, task_type: str) -> str:
        return f"{self.short_code}-{task_type}-bridge-{uuid.uuid4().hex[:12]}"

    def build_connector_context(self, *, job_id: str, task_id: str) -> ConnectorContext:
        return ConnectorContext(
            account_id=None,
            proxy=getattr(self.crawler, "_platform_http_proxy", None),
            metadata={"source": self.source_name, "job_id": job_id, "task_id": task_id},
        )

    def build_started_event(self, task: CrawlTask, job_id: str) -> CrawlJobEvent | None:
        return None

    def build_finished_event(self, task: CrawlTask, job_id: str) -> CrawlJobEvent | None:
        return None

    @abstractmethod
    def build_connector(self):
        raise NotImplementedError

    @abstractmethod
    def build_request(self, task: CrawlTask, job_id: str) -> PlatformTaskRequest:
        raise NotImplementedError

    @abstractmethod
    def classify_error(self, message: str) -> str:
        raise NotImplementedError

    @abstractmethod
    def build_failure_event(self, *, task: CrawlTask, job_id: str, error_message: str, error_code: str) -> CrawlJobEvent:
        raise NotImplementedError

    @abstractmethod
    async def handle_success(
        self,
        *,
        task: CrawlTask,
        request: PlatformTaskRequest,
        task_result: PlatformTaskResult,
        job_id: str,
        task_id: str,
        services: ExecutionServices,
    ) -> dict[str, Any]:
        raise NotImplementedError
