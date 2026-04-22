from __future__ import annotations

import json
from dataclasses import asdict, replace
from datetime import datetime
from pathlib import Path

from schemas.tasks.models import CrawlJob, CrawlTask
from schemas.tasks.runtime import PlatformTaskResult


class CrawlStateService:
    """Persists crawl task/job/result snapshots during the platform migration phase."""

    def __init__(self, base_dir: str | Path = "data/platform_runtime/tasks") -> None:
        self.base_dir = Path(base_dir)

    async def create_task(
        self,
        *,
        task_id: str,
        platform_code: str,
        task_type: str,
        params: dict,
        schedule_type: str = "manual",
        priority: int = 0,
    ) -> CrawlTask:
        """Create and persist a crawl task snapshot."""
        task = CrawlTask(
            task_id=task_id,
            platform_code=platform_code,
            task_type=task_type,
            status="ready",
            schedule_type=schedule_type,
            priority=priority,
            params=params,
        )
        await self._append_snapshot(platform_code, "tasks", self._serialize_task(task))
        return task

    async def create_job(
        self,
        *,
        job_id: str,
        task: CrawlTask,
        batch_id: str | None = None,
    ) -> CrawlJob:
        """Create and persist an initial queued job snapshot."""
        job = CrawlJob(
            job_id=job_id,
            task_id=task.task_id,
            platform_code=task.platform_code,
            status="queued",
            batch_id=batch_id,
        )
        await self._append_snapshot(task.platform_code, "jobs", self._serialize_job(job))
        return job

    async def mark_job_running(self, job: CrawlJob) -> CrawlJob:
        """Persist a running job snapshot with start timestamp."""
        running_job = replace(
            job,
            status="running",
            started_at=job.started_at or datetime.utcnow(),
        )
        await self._append_snapshot(job.platform_code, "jobs", self._serialize_job(running_job))
        return running_job

    async def mark_job_succeeded(
        self,
        job: CrawlJob,
        *,
        metrics: dict | None = None,
    ) -> CrawlJob:
        """Persist a succeeded job snapshot."""
        succeeded_job = replace(
            job,
            status="succeeded",
            ended_at=datetime.utcnow(),
            metrics=metrics or job.metrics,
            error_code=None,
            error_message="",
        )
        await self._append_snapshot(job.platform_code, "jobs", self._serialize_job(succeeded_job))
        return succeeded_job

    async def mark_job_failed(
        self,
        job: CrawlJob,
        *,
        error_code: str | None,
        error_message: str,
        metrics: dict | None = None,
    ) -> CrawlJob:
        """Persist a failed job snapshot."""
        failed_job = replace(
            job,
            status="failed",
            ended_at=datetime.utcnow(),
            error_code=error_code,
            error_message=error_message,
            metrics=metrics or job.metrics,
        )
        await self._append_snapshot(job.platform_code, "jobs", self._serialize_job(failed_job))
        return failed_job

    async def append_result(self, result: PlatformTaskResult) -> Path:
        """Persist a platform task execution result snapshot."""
        payload = {
            "job_id": result.job_id,
            "platform_code": result.platform_code,
            "task_kind": result.task_kind,
            "success": result.success,
            "payload": result.payload,
            "metrics": result.metrics,
            "error_code": result.error_code,
            "error_message": result.error_message,
            "created_at": result.created_at.isoformat(),
        }
        return await self._append_snapshot(result.platform_code, "results", payload)

    async def _append_snapshot(self, platform_code: str, snapshot_type: str, payload: dict) -> Path:
        """Append a snapshot to a platform-scoped JSONL archive file."""
        target_dir = self.base_dir / platform_code
        target_dir.mkdir(parents=True, exist_ok=True)
        file_path = target_dir / f"{snapshot_type}.jsonl"
        with file_path.open("a", encoding="utf-8") as file:
            file.write(json.dumps(payload, ensure_ascii=False) + "\n")
        return file_path

    @staticmethod
    def _serialize_task(task: CrawlTask) -> dict:
        payload = asdict(task)
        payload["created_at"] = task.created_at.isoformat()
        payload["updated_at"] = task.updated_at.isoformat()
        return payload

    @staticmethod
    def _serialize_job(job: CrawlJob) -> dict:
        payload = asdict(job)
        payload["started_at"] = job.started_at.isoformat() if job.started_at else None
        payload["ended_at"] = job.ended_at.isoformat() if job.ended_at else None
        return payload
